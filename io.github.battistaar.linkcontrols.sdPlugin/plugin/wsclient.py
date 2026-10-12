"""Minimal WebSocket client (RFC 6455), enough to talk to OpenDeck on localhost.

Only what a Stream Deck plugin needs: text frames in and out, ping/pong, close.
Standard library only, so the plugin runs on linkctl's own interpreter.
"""

import base64
import os
import socket
import struct
import threading

OP_CONT, OP_TEXT, OP_BINARY, OP_CLOSE, OP_PING, OP_PONG = 0x0, 0x1, 0x2, 0x8, 0x9, 0xA


class ConnectionClosed(Exception):
    pass


class WebSocket:
    def __init__(self, host, port, path="/"):
        self._sock = socket.create_connection((host, port))
        self._send_lock = threading.Lock()
        self._buffer = b""
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self._sock.sendall(request.encode())
        head = self._read_until(b"\r\n\r\n")
        status = head.split(b"\r\n", 1)[0]
        if b" 101 " not in status:
            raise ConnectionError(f"WebSocket handshake failed: {status!r}")

    def _read_until(self, marker):
        while marker not in self._buffer:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionClosed("connection closed during handshake")
            self._buffer += chunk
        head, self._buffer = self._buffer.split(marker, 1)
        return head

    def _read_exact(self, count):
        while len(self._buffer) < count:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise ConnectionClosed("connection closed")
            self._buffer += chunk
        data, self._buffer = self._buffer[:count], self._buffer[count:]
        return data

    def _send_frame(self, opcode, payload):
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 1 << 16:
            header.append(0x80 | 126)
            header += struct.pack(">H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", length)
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        with self._send_lock:
            self._sock.sendall(bytes(header) + mask + masked)

    def send(self, text):
        self._send_frame(OP_TEXT, text.encode())

    def recv(self):
        """Return the next text message. Raises ConnectionClosed when the peer closes."""
        message, message_op = b"", None
        while True:
            first, second = self._read_exact(2)
            fin, opcode = first & 0x80, first & 0x0F
            length = second & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read_exact(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read_exact(8))[0]
            mask = self._read_exact(4) if second & 0x80 else None
            payload = self._read_exact(length)
            if mask:
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
            if opcode == OP_PING:
                self._send_frame(OP_PONG, payload)
                continue
            if opcode == OP_PONG:
                continue
            if opcode == OP_CLOSE:
                try:
                    self._send_frame(OP_CLOSE, payload[:2])
                finally:
                    raise ConnectionClosed("closed by peer")
            if opcode in (OP_TEXT, OP_BINARY):
                message, message_op = payload, opcode
            else:  # continuation
                message += payload
            if fin:
                return message.decode() if message_op == OP_TEXT else message

    def close(self):
        try:
            self._send_frame(OP_CLOSE, struct.pack(">H", 1000))
        except OSError:
            pass
        self._sock.close()

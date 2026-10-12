"""A stand-in for OpenDeck: starts the plugin, sends it events, records what it sends back.

Usage from a test script:

    with FakeOpenDeck() as deck:
        deck.appear("ctx1", "io.github.battistaar.linkcontrols.zoom", {"direction": "in"})
        deck.press("ctx1")
        deck.wait_for("showOk", "ctx1")
"""

import base64
import hashlib
import json
import os
import queue
import socket
import struct
import subprocess
import threading
import time
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parent.parent / "io.github.battistaar.linkcontrols.sdPlugin"
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class FakeOpenDeck:
    def __init__(self):
        self.server = socket.socket()
        self.server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server.bind(("127.0.0.1", 0))
        self.server.listen(1)
        self.port = self.server.getsockname()[1]
        self.messages = queue.Queue()
        self.log = []

    def __enter__(self):
        self.proc = subprocess.Popen(
            [str(PLUGIN_DIR / "bin/linkcontrols"), "-port", str(self.port),
             "-pluginUUID", "test-uuid", "-registerEvent", "registerPlugin", "-info", "{}"],
        )
        self.server.settimeout(15)
        self.conn, _ = self.server.accept()
        self._buffer = b""
        request = self._read_until(b"\r\n\r\n").decode()
        key = next(line.split(":", 1)[1].strip() for line in request.split("\r\n")
                   if line.lower().startswith("sec-websocket-key"))
        accept = base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()
        self.conn.sendall(
            ("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
             f"Sec-WebSocket-Accept: {accept}\r\n\r\n").encode())
        threading.Thread(target=self._reader, daemon=True).start()
        registration = self.messages.get(timeout=10)
        assert registration == {"event": "registerPlugin", "uuid": "test-uuid"}, registration
        return self

    def __exit__(self, *exc):
        try:
            self.conn.sendall(bytes([0x88, 0x02]) + struct.pack(">H", 1000))
        except OSError:
            pass
        self.proc.wait(timeout=5)
        self.server.close()

    # ---------- wire ----------

    def _read_until(self, marker):
        while marker not in self._buffer:
            self._buffer += self.conn.recv(4096)
        head, self._buffer = self._buffer.split(marker, 1)
        return head

    def _read_exact(self, count):
        while len(self._buffer) < count:
            chunk = self.conn.recv(65536)
            if not chunk:
                raise EOFError
            self._buffer += chunk
        data, self._buffer = self._buffer[:count], self._buffer[count:]
        return data

    def _reader(self):
        try:
            while True:
                first, second = self._read_exact(2)
                length = second & 0x7F
                if length == 126:
                    length = struct.unpack(">H", self._read_exact(2))[0]
                elif length == 127:
                    length = struct.unpack(">Q", self._read_exact(8))[0]
                mask = self._read_exact(4)
                payload = bytes(b ^ mask[i % 4] for i, b in enumerate(self._read_exact(length)))
                if first & 0x0F == 0x1:
                    message = json.loads(payload)
                    self.log.append((time.monotonic(), message))
                    self.messages.put(message)
        except (EOFError, OSError):
            pass

    def send(self, message):
        data = json.dumps(message).encode()
        header = bytes([0x81])
        header += bytes([len(data)]) if len(data) < 126 else bytes([126]) + struct.pack(">H", len(data))
        self.conn.sendall(header + data)

    # ---------- events ----------

    def appear(self, context, action, settings=None):
        self.send({"event": "willAppear", "action": action, "context": context, "device": "dev",
                   "payload": {"settings": settings or {}, "coordinates": {"column": 0, "row": 0},
                               "state": 0, "isInMultiAction": False}})

    def press(self, context, action=None, hold=0.0):
        base = {"action": action, "context": context, "device": "dev",
                "payload": {"settings": {}, "coordinates": {"column": 0, "row": 0}, "state": 0}}
        self.send({**base, "event": "keyDown"})
        time.sleep(hold)
        self.send({**base, "event": "keyUp"})

    def wait_for(self, event, context=None, timeout=10):
        """Return the next message with this event (and context), dropping others."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                message = self.messages.get(timeout=deadline - time.monotonic())
            except queue.Empty:
                break
            if message.get("event") == event and (context is None or message.get("context") == context):
                return message
        raise TimeoutError(f"no {event} for {context} within {timeout}s")

    def drain(self, seconds=0.5):
        out, deadline = [], time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                out.append(self.messages.get(timeout=max(0.01, deadline - time.monotonic())))
            except queue.Empty:
                pass
        return out

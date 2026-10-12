"""OpenDeck plugin that drives an Insta360 Link camera through linkctl.

Started by OpenDeck with the Stream Deck plugin arguments (-port, -pluginUUID,
-registerEvent, -info). Talks the Stream Deck SDK protocol over a local WebSocket.
"""

import argparse
import base64
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

from camera import Camera, camera_nodes, node_in_use, remembered_mode
from wsclient import ConnectionClosed, WebSocket

PLUGIN = "io.github.battistaar.linkcontrols"
PAN_TILT = f"{PLUGIN}.pantilt"
ZOOM = f"{PLUGIN}.zoom"
TRACKING = f"{PLUGIN}.tracking"
PRESET = f"{PLUGIN}.preset"

ICONS = Path(__file__).resolve().parent.parent / "icons"
STATE_POLL_SECONDS = 2.0
ZOOM_TICK_SECONDS = 0.1

DEFAULTS = {
    PAN_TILT: {"direction": "up", "step": 3.0, "continuous": False, "speed": 5},
    ZOOM: {"direction": "in", "step": 0.25, "continuous": False, "speed": 5},
    PRESET: {"preset": 1, "source": "computer"},
    TRACKING: {},
}

log = logging.getLogger("linkcontrols")


def settings_for(action, raw):
    merged = dict(DEFAULTS.get(action, {}))
    merged.update({k: v for k, v in (raw or {}).items() if v not in ("", None)})
    return merged


def as_bool(value):
    return value is True or str(value).lower() in ("true", "1", "on")


def icon_data(name):
    data = (ICONS / f"{name}.png").read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode()


class Plugin:
    def __init__(self, port, uuid, register_event):
        self.ws = WebSocket("127.0.0.1", port)
        self.ws.send(json.dumps({"event": register_event, "uuid": uuid}))
        self.camera = Camera()
        self.contexts = {}          # context -> (action, settings)
        self.held = {}              # context -> threading.Event while a continuous key is down
        self.tracking = None        # last known tracking state, None if unknown
        self.streaming = False
        # Until video is live, show the mode linkctl last set rather than asking the camera.
        mode = remembered_mode()
        if mode is not None:
            self.tracking = mode == "track"
        self._wake = threading.Event()
        threading.Thread(target=self._watch, daemon=True).start()

    # ---------- protocol ----------

    def send(self, event, context=None, payload=None):
        message = {"event": event}
        if context is not None:
            message["context"] = context
        if payload is not None:
            message["payload"] = payload
        self.ws.send(json.dumps(message))

    def alert(self, context, error):
        log.warning("%s", error)
        self.send("showAlert", context)

    def run(self):
        while True:
            try:
                message = json.loads(self.ws.recv())
            except ConnectionClosed:
                log.info("OpenDeck closed the connection")
                return
            try:
                self.handle(message)
            except Exception:
                log.exception("failed to handle %s", message.get("event"))

    def handle(self, message):
        event = message.get("event")
        context = message.get("context")
        action = message.get("action")
        payload = message.get("payload") or {}
        if event in ("willAppear", "didReceiveSettings"):
            self.contexts[context] = (action, settings_for(action, payload.get("settings")))
            self.refresh_look(context)
            if action == TRACKING:
                self._wake.set()
        elif event == "willDisappear":
            self.contexts.pop(context, None)
            self.release(context)
        elif event == "keyDown":
            action, settings = self.contexts.get(context, (action, settings_for(action, payload.get("settings"))))
            self.key_down(context, action, settings)
        elif event == "keyUp":
            self.release(context)

    # ---------- appearance ----------

    def refresh_look(self, context):
        action, settings = self.contexts[context]
        if action == PAN_TILT:
            self.send("setImage", context, {"image": icon_data(f"pan-{settings['direction']}"), "target": 0})
        elif action == ZOOM:
            self.send("setImage", context, {"image": icon_data(f"zoom-{settings['direction']}"), "target": 0})
        elif action == PRESET:
            self.send("setTitle", context, {"title": str(settings["preset"]), "target": 0})
        elif action == TRACKING and self.tracking is not None:
            self.send("setState", context, {"state": int(self.tracking)})

    def show_tracking(self, state):
        if state == self.tracking:
            return
        self.tracking = state
        for context, (action, _) in list(self.contexts.items()):
            if action == TRACKING:
                self.send("setState", context, {"state": int(state)})

    # ---------- keys ----------

    def key_down(self, context, action, settings):
        if action == PAN_TILT:
            self.pan_tilt(context, settings)
        elif action == ZOOM:
            self.zoom(context, settings)
        elif action == TRACKING:
            self.background(context, self.toggle_tracking)
        elif action == PRESET:
            self.background(context, lambda: self.recall_preset(settings), ok=True)

    def background(self, context, work, ok=False):
        def run():
            try:
                work()
                if ok:
                    self.send("showOk", context)
            except Exception as exc:  # camera missing, slot empty, ...
                self.alert(context, exc)
        threading.Thread(target=run, daemon=True).start()

    def release(self, context):
        held = self.held.pop(context, None)
        if held is not None:
            held.set()

    def video_live(self):
        """Whether video is streaming now; checked only when a key is pressed."""
        return self._streaming_now()

    def pan_tilt(self, context, settings):
        if not self.video_live():
            self.alert(context, "pan/tilt ignored: no application is streaming video")
            return
        direction = settings["direction"]
        sign = 1 if direction in ("up", "right") else -1
        horizontal = direction in ("left", "right")
        if as_bool(settings["continuous"]):
            speed = sign * max(1, min(10, int(settings["speed"])))
            done = threading.Event()
            self.held[context] = done

            def drive():
                try:
                    self.camera.call(lambda c: c.drive(speed if horizontal else 0, 0 if horizontal else speed))
                    done.wait()
                finally:
                    try:
                        self.camera.call(lambda c: c.stop())
                    except Exception as exc:
                        self.alert(context, exc)
            threading.Thread(target=drive, daemon=True).start()
        else:
            step = sign * abs(float(settings["step"]))
            self.background(context, lambda: self.camera.call(
                lambda c: c.move(step if horizontal else 0, 0 if horizontal else step)))

    def zoom(self, context, settings):
        if not self.video_live():
            self.alert(context, "zoom ignored: no application is streaming video")
            return
        sign = 1 if settings["direction"] == "in" else -1

        def clamp_set(cam, delta):
            low, high = cam.zoom_range
            return cam.set_zoom(max(low, min(high, cam.get_zoom() + delta)))

        if as_bool(settings["continuous"]):
            # The camera has no continuous zoom, so step it while the key is held.
            rate = sign * max(1, min(10, int(settings["speed"]))) * 0.1  # x per second
            done = threading.Event()
            self.held[context] = done

            def ramp():
                try:
                    while not done.wait(ZOOM_TICK_SECONDS):
                        self.camera.call(lambda c: clamp_set(c, rate * ZOOM_TICK_SECONDS))
                except Exception as exc:
                    self.alert(context, exc)
            threading.Thread(target=ramp, daemon=True).start()
        else:
            step = sign * abs(float(settings["step"]))
            self.background(context, lambda: self.camera.call(lambda c: clamp_set(c, step)))

    def toggle_tracking(self):
        current = self.camera.call(lambda c: c.get_tracking())
        self.camera.call(lambda c: c.set_tracking(not current))
        self.show_tracking(not current)
        self._wake.set()

    def recall_preset(self, settings):
        slot = int(settings["preset"])
        if settings["source"] == "camera":
            self.camera.call(lambda c: c.recall_camera_preset(slot))
        else:
            self.camera.call(lambda c: c.recall_preset(slot))

    # ---------- state polling ----------

    def _streaming_now(self):
        """Live video right now. /proc first, so an idle camera is never queried."""
        if not node_in_use(camera_nodes()):
            return False
        try:
            streaming = self.camera.call(lambda c: c.is_streaming())
        except Exception:
            return True  # someone has it open and we cannot ask; assume they stream
        return True if streaming is None else streaming

    def _watch(self):
        """Read the tracking state, but only while a tracking key is shown and video is live."""
        while True:
            self._wake.wait(STATE_POLL_SECONDS)
            self._wake.clear()
            if not any(action == TRACKING for action, _ in list(self.contexts.values())):
                continue
            try:
                live = self._streaming_now()
                if live != self.streaming:
                    log.info("video %s", "started" if live else "stopped")
                    self.streaming = live
                if live:
                    self.show_tracking(self.camera.call(lambda c: c.get_tracking()))
            except Exception as exc:
                log.debug("state poll failed: %s", exc)
                self.camera.close()


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("-port", type=int, required=True)
    parser.add_argument("-pluginUUID", required=True)
    parser.add_argument("-registerEvent", required=True)
    parser.add_argument("-info", default="{}")
    args, _ = parser.parse_known_args(argv)

    state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "opendeck-link-controls"
    state.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=state / "plugin.log",
        level=logging.DEBUG if os.environ.get("LINKCONTROLS_DEBUG") else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log.info("starting, linkctl from %s", sys.executable)
    Plugin(args.port, args.pluginUUID, args.registerEvent).run()


if __name__ == "__main__":
    main()

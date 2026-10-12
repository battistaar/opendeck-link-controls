"""End-to-end test against a real Insta360 Link. Moves the camera and changes its mode.

Run with linkctl's interpreter, so linkctl can be imported to check the results:

    "$(head -1 "$(readlink -f "$(command -v linkctl)")" | cut -c3-)" tests/hardware_test.py

Needs the camera plugged in and free (no other application using it), and computer
preset 1 and camera preset 6 saved.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_opendeck import FakeOpenDeck  # noqa: E402

from linkctl.camera import LinkCamera  # noqa: E402

PLUGIN = "io.github.battistaar.linkcontrols"
LOG = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "opendeck-link-controls/plugin.log"
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}", flush=True)


def position(cam):
    tilt, pan = cam.ptz_raw()
    return pan / 3600, tilt / 3600


def camera_calls():
    return LOG.read_text().count("camera call") if LOG.exists() else 0


def stream():
    with LinkCamera() as cam:
        node = cam.node
    return subprocess.Popen(["ffmpeg", "-loglevel", "quiet", "-f", "v4l2", "-i", node, "-f", "null", "-"])


def main():
    os.environ["LINKCONTROLS_DEBUG"] = "1"
    cam = LinkCamera()
    with FakeOpenDeck() as deck:
        # --- idle: keys refuse to move, tracking is not polled ---
        deck.appear("pt", f"{PLUGIN}.pantilt", {"direction": "right", "step": 3})
        deck.appear("trk", f"{PLUGIN}.tracking")
        deck.drain(1)
        cam.close()  # an open handle here would count as "someone uses the camera"
        before = camera_calls()
        deck.press("pt")
        alert = deck.wait_for("showAlert", "pt")
        check("pan refused while no video", alert is not None)
        time.sleep(6)
        check("no camera queries while idle", camera_calls() == before,
              f"{camera_calls() - before} calls in 6 s")

        video = stream()
        cam = LinkCamera()
        try:
            time.sleep(5)
            cam.center()
            time.sleep(2.5)

            # --- pan/tilt step ---
            deck.press("pt")
            time.sleep(1.5)
            pan, tilt = position(cam)
            check("pan right 3 degrees", abs(pan - 3) < 0.6, f"pan {pan:+.1f}")
            deck.appear("up", f"{PLUGIN}.pantilt", {"direction": "up", "step": 5})
            deck.press("up")
            time.sleep(1.5)
            pan, tilt = position(cam)
            check("tilt up 5 degrees", abs(tilt - 5) < 0.6, f"tilt {tilt:+.1f}")

            # --- pan/tilt continuous ---
            deck.appear("ptc", f"{PLUGIN}.pantilt", {"direction": "left", "continuous": True, "speed": 5})
            start = position(cam)[0]
            deck.press("ptc", hold=1.5)
            time.sleep(0.8)
            end = position(cam)[0]
            check("continuous pan left while held", start - end > 10, f"{start:+.1f} -> {end:+.1f}")
            check("setpoint synced after continuous move", abs(cam.get_pan() - end) < 0.6,
                  f"setpoint {cam.get_pan():+.1f} actual {end:+.1f}")

            # --- zoom ---
            cam.set_zoom(1.0)
            deck.appear("zi", f"{PLUGIN}.zoom", {"direction": "in", "step": 0.5})
            deck.press("zi")
            time.sleep(1)
            check("zoom in step 0.5", abs(cam.get_zoom() - 1.5) < 0.02, f"zoom {cam.get_zoom():.2f}")
            deck.appear("zc", f"{PLUGIN}.zoom", {"direction": "out", "continuous": True, "speed": 5})
            deck.press("zc", hold=0.6)
            time.sleep(0.3)
            zoom = cam.get_zoom()
            check("continuous zoom out while held", 1.0 <= zoom < 1.4, f"zoom {zoom:.2f}")
            cam.set_zoom(1.0)

            # --- tracking toggle and state polling ---
            cam.set_mode("normal", confirm=True)
            time.sleep(3)
            deck.drain(0.5)
            deck.press("trk")
            state = deck.wait_for("setState", "trk")["payload"]["state"]
            # Tracking falls back to normal by itself when nobody is in view, so check
            # the request reached the camera rather than what it settled on.
            requested = cam._recall_mode()
            check("tracking key turns tracking on", state == 1 and requested == "track",
                  f"key state {state}, requested {requested}")
            subprocess.run(["linkctl", "mode", "normal"], capture_output=True)
            state = deck.wait_for("setState", "trk", timeout=6)["payload"]["state"]
            check("key follows a mode change made elsewhere", state == 0, f"key state {state}")

            # --- presets ---
            deck.appear("p1", f"{PLUGIN}.preset", {"preset": 1, "source": "computer"})
            deck.press("p1")
            deck.wait_for("showOk", "p1")
            time.sleep(2)
            preset = cam.list_presets().get("1")
            pan, tilt = position(cam)
            check("computer preset 1", abs(pan - preset["pan"]) < 0.6 and abs(tilt - preset["tilt"]) < 0.6,
                  f"at {pan:+.1f}/{tilt:+.1f}")
            deck.appear("p6", f"{PLUGIN}.preset", {"preset": 6, "source": "camera"})
            deck.press("p6")
            deck.wait_for("showOk", "p6", timeout=10)
            pan, tilt = position(cam)
            check("camera preset 6", abs(pan + 30) < 1 and abs(tilt - 8) < 1, f"at {pan:+.1f}/{tilt:+.1f}")
            deck.appear("p9", f"{PLUGIN}.preset", {"preset": 9, "source": "camera"})
            deck.press("p9")
            check("invalid camera slot shows an alert", deck.wait_for("showAlert", "p9") is not None)
            cam.center()
            cam.set_zoom(1.0)
            time.sleep(2)
        finally:
            cam.close()
            video.terminate()
            video.wait()

        # --- back to idle ---
        time.sleep(3)
        before = camera_calls()
        time.sleep(6)
        check("polling stops when video stops", camera_calls() == before,
              f"{camera_calls() - before} calls in 6 s")

    print(f"\n{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())

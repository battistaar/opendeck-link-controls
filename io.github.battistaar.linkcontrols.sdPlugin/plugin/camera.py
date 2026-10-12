"""Access to the camera through linkctl, and a cheap check for live video.

The camera is opened lazily and reopened after it leaves the bus (unplugged, or
restarting after a portrait change). Whether some application is streaming is
worked out from /proc without touching the camera, so idle polling costs nothing.
"""

import errno
import glob
import json
import logging
import os
import threading

from linkctl.camera import CONFIG_DIR, INSTA360_VID, LinkCamera, _sysfs_usb_attrs

log = logging.getLogger("linkcontrols")

# ioctl errors that mean the device node is stale.
GONE_ERRNOS = {errno.ENODEV, errno.ENXIO, errno.EIO, errno.EPROTO, errno.EBADF, errno.ENOENT}


class Camera:
    def __init__(self):
        self._cam = None
        self.lock = threading.RLock()

    def call(self, fn):
        """Run fn(LinkCamera) with the camera open, reopening it once if it went away."""
        log.debug("camera call")
        with self.lock:
            for attempt in (1, 2):
                if self._cam is None:
                    self._cam = LinkCamera()
                try:
                    return fn(self._cam)
                except OSError as exc:
                    if exc.errno in GONE_ERRNOS and attempt == 1:
                        self.close()
                        continue
                    raise

    def close(self):
        with self.lock:
            if self._cam is not None:
                try:
                    self._cam.close()
                except OSError:
                    pass
                self._cam = None


def camera_nodes():
    """Every /dev/video* node that belongs to an Insta360 camera, from sysfs only."""
    nodes = set()
    for node in glob.glob("/dev/video*"):
        attrs = _sysfs_usb_attrs(node)
        if attrs and attrs["vid"].lower() == INSTA360_VID:
            nodes.add(node)
    return nodes


def node_in_use(nodes):
    """True if any other process has one of these device nodes open.

    A process that holds the node open is not necessarily streaming (the linkctl GUI
    keeps it open with the preview off), so callers confirm with the camera before
    trusting this, but only when it says yes.
    """
    if not nodes:
        return False
    own = str(os.getpid())
    for pid in os.listdir("/proc"):
        if not pid.isdigit() or pid == own:
            continue
        fd_dir = f"/proc/{pid}/fd"
        try:
            fds = os.listdir(fd_dir)
        except OSError:
            continue
        for fd in fds:
            try:
                if os.readlink(f"{fd_dir}/{fd}") in nodes:
                    return True
            except OSError:
                continue
    return False


def remembered_mode():
    """The mode linkctl last set on this camera, read from its state file, or None."""
    try:
        with open(os.path.join(CONFIG_DIR, "state.json")) as handle:
            modes = json.load(handle).get("modes", {})
    except (OSError, ValueError):
        return None
    for node in camera_nodes():
        attrs = _sysfs_usb_attrs(node)
        if attrs and attrs["syspath"] in modes:
            return modes[attrs["syspath"]]
    return None

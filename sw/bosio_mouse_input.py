"""Minimal Linux evdev relative-mouse adapter for the spherical pointer."""

from __future__ import annotations

import glob
import os
import struct
import threading


EV_SYN, EV_KEY, EV_REL = 0, 1, 2
SYN_REPORT = 0
REL_X, REL_Y = 0, 1
BUTTONS = {272: "left", 273: "right", 274: "middle"}


def find_mouse_device():
    candidates = sorted(glob.glob("/dev/input/by-id/*-event-mouse"))
    if not candidates:
        for path in sorted(glob.glob("/sys/class/input/event*/device/name")):
            try:
                if "mouse" in open(path, encoding="utf-8").read().lower():
                    candidates.append("/dev/input/" + path.split("/")[-3])
            except OSError:
                pass
    return candidates[0] if candidates else None


class EvdevMouse:
    def __init__(self, manager, device="auto", sensitivity=0.12):
        self.manager = manager
        self.device = find_mouse_device() if device == "auto" else device
        self.sensitivity = float(sensitivity)
        self.thread = None
        self.error = None

    def start(self):
        if not self.device:
            return False
        self.thread = threading.Thread(target=self._run, name="bosio-mouse", daemon=True)
        self.thread.start()
        return True

    def _run(self):
        event_struct = struct.Struct("llHHi")
        dx = dy = 0
        try:
            fd = os.open(self.device, os.O_RDONLY)
            with os.fdopen(fd, "rb", buffering=0) as stream:
                while True:
                    raw = stream.read(event_struct.size)
                    if len(raw) != event_struct.size:
                        return
                    _, _, event_type, code, value = event_struct.unpack(raw)
                    if event_type == EV_REL:
                        if code == REL_X:
                            dx += value
                        elif code == REL_Y:
                            dy += value
                    elif event_type == EV_KEY and code in BUTTONS:
                        self.manager.pointer_button(BUTTONS[code], value != 0)
                    elif event_type == EV_SYN and code == SYN_REPORT and (dx or dy):
                        self.manager.pointer_move(dx * self.sensitivity, -dy * self.sensitivity)
                        dx = dy = 0
        except Exception as exc:
            self.error = repr(exc)

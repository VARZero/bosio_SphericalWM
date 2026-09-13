"""Client SDK for the BOSIO spherical window manager IPC protocol."""

from __future__ import annotations

import base64
import json
import os
import socket
import threading
import uuid

import numpy as np


class BosioWMError(RuntimeError):
    pass


class BosioWMClient:
    def __init__(self, app_name, socket_path="/tmp/bosio-wm.sock", timeout=5.0):
        self.app = f"{app_name}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.settimeout(float(timeout))
        self.socket.connect(str(socket_path))
        self.file = self.socket.makefile("rwb")
        self._sequence = 0
        self._lock = threading.Lock()
        self._button_event_id = int(self.call("get_button_state")["last_event_id"])

    def close(self):
        if self.file is not None:
            self.file.close(); self.file = None
            self.socket.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def call(self, op, **args):
        with self._lock:
            self._sequence += 1
            request = {"id": self._sequence, "app": self.app, "op": op, "args": args}
            self.file.write((json.dumps(request, separators=(",", ":")) + "\n").encode())
            self.file.flush()
            line = self.file.readline()
            if not line:
                raise BosioWMError("window manager disconnected")
            response = json.loads(line)
            if response.get("id") != self._sequence:
                raise BosioWMError("IPC response sequence mismatch")
            if not response.get("ok"):
                raise BosioWMError(response.get("error", "window manager error"))
            return response.get("result")

    def ping(self):
        return self.call("ping")

    def create_window(self, title, azimuth=0, elevation=0, width_deg=34, height_deg=24,
                      surface_width=320, surface_height=200):
        return self.call("create_window", title=title, azimuth=azimuth, elevation=elevation,
                         width_deg=width_deg, height_deg=height_deg,
                         surface_width=surface_width, surface_height=surface_height)

    def destroy_window(self, window_id):
        return self.call("destroy_window", window_id=window_id)

    def configure_window(self, window_id, **changes):
        return self.call("configure_window", window_id=window_id, **changes)

    def focus_window(self, window_id, raise_window=True):
        return self.call("focus_window", window_id=window_id, raise_window=raise_window)

    def raise_window(self, window_id):
        return self.call("raise_window", window_id=window_id)

    def lower_window(self, window_id):
        return self.call("lower_window", window_id=window_id)

    def fill(self, window_id, rgb):
        return self.call("fill", window_id=window_id, rgb=list(map(int, rgb)))

    def update_surface(self, window_id, rgb, x=0, y=0):
        array = np.ascontiguousarray(rgb, dtype=np.uint8)
        if array.ndim != 3 or array.shape[2] != 3:
            raise ValueError("surface must have shape (height,width,3)")
        height, width, _ = array.shape
        data = base64.b64encode(array.tobytes()).decode("ascii")
        return self.call("update_surface", window_id=window_id, x=x, y=y,
                         width=width, height=height, rgb24=data)

    def pointer_warp(self, azimuth, elevation):
        return self.call("pointer_warp", azimuth=azimuth, elevation=elevation)

    def pointer_move(self, delta_azimuth, delta_elevation):
        return self.call("pointer_move", delta_azimuth=delta_azimuth, delta_elevation=delta_elevation)

    def pointer_button(self, pressed, button="left"):
        return self.call("pointer_button", button=button, pressed=bool(pressed))

    def poll_events(self, limit=64):
        return self.call("poll_events", limit=limit)

    def get_button_state(self):
        """Return the current BTN0..BTN3 bit mask and availability."""
        return self.call("get_button_state")

    def poll_button_events(self, limit=64):
        """Return each debounced button edge once for this client instance."""
        result = self.call("poll_button_events", after_id=self._button_event_id, limit=limit)
        self._button_event_id = max(self._button_event_id, int(result["next_id"]))
        return result["events"]

    def get_state(self):
        return self.call("get_state")

    def set_frame_limit(self, fps):
        return self.call("set_frame_limit", fps=float(fps))

    def reset_performance(self):
        return self.call("reset_performance")

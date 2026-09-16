"""Standard-library client for external BOSIO pointer input processes."""

from __future__ import annotations

import json
import os
import socket
import threading
import uuid


class BosioInputError(RuntimeError):
    pass


class BosioInputClient:
    """Inject spherical pointer input without creating an application window."""

    def __init__(self, source_name, socket_path="/tmp/bosio-wm.sock", timeout=5.0):
        self.source = f"input:{source_name}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.settimeout(float(timeout))
        self.socket.connect(str(socket_path))
        self.file = self.socket.makefile("rwb")
        self._sequence = 0
        self._lock = threading.Lock()

    def close(self):
        if self.file is not None:
            self.file.close()
            self.file = None
            self.socket.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def _call(self, op, **args):
        if self.file is None:
            raise BosioInputError("input connection is closed")
        with self._lock:
            self._sequence += 1
            request = {"id": self._sequence, "app": self.source, "op": op, "args": args}
            self.file.write((json.dumps(request, separators=(",", ":")) + "\n").encode())
            self.file.flush()
            line = self.file.readline()
            if not line:
                raise BosioInputError("window manager disconnected")
            response = json.loads(line)
            if response.get("id") != self._sequence:
                raise BosioInputError("IPC response sequence mismatch")
            if not response.get("ok"):
                raise BosioInputError(response.get("error", "window manager error"))
            return response.get("result")

    def move_absolute(self, azimuth, elevation):
        """Move to an absolute spherical direction in degrees."""
        return self._call("input_warp", azimuth=float(azimuth), elevation=float(elevation))

    def move_relative(self, delta_azimuth, delta_elevation):
        """Move by angular deltas in degrees."""
        return self._call("input_move", delta_azimuth=float(delta_azimuth),
                          delta_elevation=float(delta_elevation))

    def button(self, pressed, button="left"):
        """Press or release a pointer button for this input source."""
        return self._call("input_button", button=str(button), pressed=bool(pressed))

    def click(self, button="left"):
        """Send one complete press and release without a timing dependency."""
        return self._call("input_click", button=str(button))

    def scroll(self, delta):
        return self._call("input_scroll", delta=float(delta))

    def state(self):
        """Return the global pointer state and buttons held by this source."""
        return self._call("input_status")

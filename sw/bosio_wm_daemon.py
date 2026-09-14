#!/usr/bin/env python3
"""BOSIO spherical window manager daemon and Unix-domain JSON IPC server."""

from __future__ import annotations

import argparse
import base64
from collections import deque
import json
import os
import signal
import socket
import socketserver
import threading
import time
from pathlib import Path

import numpy as np

try:
    from bosio_window_manager import SphericalWindowManager, WindowManagerError
except ImportError:
    from .bosio_window_manager import SphericalWindowManager, WindowManagerError


MAX_REQUEST = 8 * 1024 * 1024


class _UnixStreamServer(socketserver.TCPServer):
    address_family = getattr(socket, "AF_UNIX", socket.AF_INET)


class _Server(socketserver.ThreadingMixIn, _UnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True


class _Handler(socketserver.StreamRequestHandler):
    def handle(self):
        applications = set()
        try:
            while True:
                line = self.rfile.readline(MAX_REQUEST + 1)
                if not line:
                    return
                if len(line) > MAX_REQUEST:
                    self._reply(None, error="request too large")
                    return
                request_id = None
                try:
                    request = json.loads(line)
                    request_id = request.get("id")
                    applications.add(str(request.get("app", "anonymous")))
                    result = self.server.dispatch(request)
                    self._reply(request_id, result=result)
                except (ValueError, TypeError, KeyError, WindowManagerError) as exc:
                    self._reply(request_id, error=str(exc))
                except Exception as exc:
                    self._reply(request_id, error=f"internal error: {exc}")
        finally:
            for app in applications:
                self.server.manager.destroy_owner_windows(app)
                self.server.daemon.release_scene_owner(app)

    def _reply(self, request_id, result=None, error=None):
        payload = {"id": request_id, "ok": error is None}
        payload["result" if error is None else "error"] = result if error is None else error
        self.wfile.write((json.dumps(payload, separators=(",", ":")) + "\n").encode())
        self.wfile.flush()


class BosioWindowDaemon:
    def __init__(self, socket_path, m=32, fps=12, bitstream=None, headless=False,
                 sensor=True, invert_mask=0, mouse=None, mouse_sensitivity=0.12,
                 socket_group=None, antialias=True, aa_threshold=24, aa_strength=32):
        self.socket_path = Path(socket_path)
        self.manager = SphericalWindowManager(m)
        self.frame_period = 1.0 / max(1.0, float(fps))
        self.bitstream = Path(bitstream) if bitstream else None
        self.headless = bool(headless)
        self.sensor = bool(sensor)
        self.invert_mask = int(invert_mask) & 7
        self.mouse_device = mouse
        self.mouse_sensitivity = float(mouse_sensitivity)
        self.socket_group = socket_group
        self.antialias = bool(antialias)
        self.aa_threshold = int(aa_threshold)
        self.aa_strength = int(aa_strength)
        self.mouse = None
        self.driver = None
        self.running = False
        self.last_rendered = 0
        self.server = None
        self.output_status = None
        self.render_error = None
        self.render_count = 0
        self.full_update_count = 0
        self.patch_update_count = 0
        self.update_words = 0
        self.no_op_update_count = 0
        self.compose_seconds = 0.0
        self.upload_seconds = 0.0
        self.last_compose_seconds = 0.0
        self.last_upload_seconds = 0.0
        self.metrics_started = time.monotonic()
        self._last_status_time = 0.0
        self.lock_file = None
        self.buttons = None
        self.button_thread = None
        self.button_state = 0
        self.button_event_id = 0
        self.button_events = deque(maxlen=256)
        self.button_lock = threading.Lock()
        self.driver_lock = threading.RLock()
        self.scene_lock = threading.RLock()
        self.scene_owner = None

    def dispatch(self, request):
        op = request["op"]
        args = request.get("args", {})
        app = str(request.get("app", "anonymous"))
        wm = self.manager
        if op == "ping":
            return {"version": 2, "m": wm.m, "headless": self.headless,
                    "features": ["windows", "pointer", "button-events", "scene-stream"]}
        if op == "claim_scene":
            with self.scene_lock:
                if self.scene_owner not in (None, app):
                    raise WindowManagerError("BOSIO scene is owned by another application")
                self.scene_owner = app
            return {"owner": app, "m": wm.m}
        if op == "upload_scene_words":
            with self.scene_lock:
                if self.scene_owner != app:
                    raise WindowManagerError("application does not own the BOSIO scene")
            raw = base64.b64decode(args["words32"], validate=True)
            if len(raw) % 4:
                raise WindowManagerError("packed scene is not uint32 aligned")
            words = np.frombuffer(raw, dtype="<u4").copy()
            if not 16 <= len(words) <= 53664:
                raise WindowManagerError("packed scene word count is invalid")
            if self.driver is not None:
                with self.driver_lock:
                    self.driver.upload_words(words)
            self.update_words += len(words)
            self.full_update_count += 1
            return {"words": len(words)}
        if op == "release_scene":
            self.release_scene_owner(app)
            return True
        if op == "set_frame_limit":
            fps = float(args["fps"])
            if not 1 <= fps <= 500:
                raise WindowManagerError("fps must be between 1 and 500")
            self.frame_period = 1.0 / fps
            return fps
        if op == "set_antialias":
            if self.driver is None:
                raise WindowManagerError("output driver is not available")
            enabled = bool(args.get("enabled", True))
            threshold = int(args.get("threshold", self.aa_threshold))
            strength = int(args.get("strength", self.aa_strength))
            self.driver.set_antialias(enabled, threshold, strength)
            self.antialias, self.aa_threshold, self.aa_strength = enabled, threshold, strength
            self.output_status = self.driver.status()
            return {"enabled": enabled, "threshold": threshold, "strength": strength}
        if op == "reset_performance":
            self.render_count = 0
            self.full_update_count = 0
            self.patch_update_count = 0
            self.update_words = 0
            self.no_op_update_count = 0
            self.compose_seconds = 0.0
            self.upload_seconds = 0.0
            self.last_compose_seconds = 0.0
            self.last_upload_seconds = 0.0
            self.metrics_started = time.monotonic()
            return True
        if op == "create_window":
            return wm.create_window(app, **args)
        if op == "destroy_window":
            wm.destroy_window(app, args["window_id"]); return True
        if op == "configure_window":
            changes = dict(args); wid = changes.pop("window_id")
            return wm.configure_window(app, wid, **changes)
        if op == "raise_window":
            wm.raise_window(app, args["window_id"]); return True
        if op == "lower_window":
            wm.lower_window(app, args["window_id"]); return True
        if op == "focus_window":
            return wm.focus_window(args["window_id"], bool(args.get("raise_window", True)))
        if op == "fill":
            wm.fill(app, args["window_id"], args["rgb"]); return True
        if op == "update_surface":
            wm.update_surface(app, **args); return True
        if op == "pointer_warp":
            return wm.pointer_warp(args["azimuth"], args["elevation"])
        if op == "pointer_move":
            return wm.pointer_move(args["delta_azimuth"], args["delta_elevation"])
        if op == "pointer_button":
            return wm.pointer_button(args.get("button", "left"), args["pressed"])
        if op == "poll_events":
            return wm.poll_events(app, args.get("limit", 64))
        if op == "get_button_state":
            with self.button_lock:
                return {"state": self.button_state, "available": self.buttons is not None,
                        "last_event_id": self.button_event_id}
        if op == "poll_button_events":
            after_id = max(0, int(args.get("after_id", 0)))
            limit = max(1, min(256, int(args.get("limit", 64))))
            with self.button_lock:
                events = [event for event in self.button_events if event["id"] > after_id][:limit]
                return {"events": events, "next_id": events[-1]["id"] if events else after_id,
                        "state": self.button_state, "available": self.buttons is not None}
        if op == "get_state":
            if self.driver is not None:
                with self.driver_lock:
                    self.output_status = self.driver.status()
            state = wm.state()
            state["output"] = self.output_status
            with self.button_lock:
                state["buttons"] = {"state": self.button_state,
                                    "available": self.buttons is not None,
                                    "last_event_id": self.button_event_id}
            state["render_error"] = self.render_error
            with self.scene_lock:
                state["scene_owner"] = self.scene_owner
            count = self.render_count
            state["performance"] = {
                "render_count": count,
                "full_update_count": self.full_update_count,
                "patch_update_count": self.patch_update_count,
                "update_words": self.update_words,
                "no_op_update_count": self.no_op_update_count,
                "uptime_seconds": time.monotonic() - self.metrics_started,
                "average_compose_ms": self.compose_seconds * 1000 / count if count else 0.0,
                "average_upload_ms": self.upload_seconds * 1000 / count if count else 0.0,
                "last_compose_ms": self.last_compose_seconds * 1000,
                "last_upload_ms": self.last_upload_seconds * 1000,
                "frame_limit": 1.0 / self.frame_period,
            }
            return state
        raise WindowManagerError("unknown operation")

    def _start_driver(self):
        if self.headless:
            return
        if self.bitstream is None:
            raise RuntimeError("--bit is required unless --headless is used")
        from bosio_driver_v2 import BosioV2
        self.driver = BosioV2(self.bitstream, self.manager.m)
        self.buttons = self.driver.buttons
        self.button_state = self.buttons.read_state()
        self.driver.set_antialias(self.antialias, self.aa_threshold, self.aa_strength)
        self.driver.upload(self.manager.render())
        self.driver.set_pose(0, 0, 0)
        self.driver.start()
        self.driver.set_sensor_invert(bool(self.invert_mask & 1), bool(self.invert_mask & 2), bool(self.invert_mask & 4))
        if self.sensor:
            self.driver.use_sensor(True)
        self.output_status = self.driver.status()

    def _button_loop(self):
        from bosio_buttons import ButtonDebouncer
        debouncer = ButtonDebouncer(self.button_state, 0.03)
        while self.running:
            try:
                state = self.buttons.read_state()
                events = debouncer.update(state)
                with self.button_lock:
                    self.button_state = state
                    for event in events:
                        self.button_event_id += 1
                        event.update(id=self.button_event_id, type="button",
                                     monotonic_ns=time.monotonic_ns())
                        self.button_events.append(event)
                        print(f'BOSIO_BUTTON {event["name"]} '
                              f'{"pressed" if event["pressed"] else "released"}', flush=True)
            except Exception as exc:
                self.render_error = f"button input: {exc!r}"
            time.sleep(0.005)

    def _render_loop(self):
        while self.running:
            generation = self.manager.generation
            with self.scene_lock:
                external_scene = self.scene_owner is not None
            if not external_scene and generation != self.last_rendered:
                try:
                    compose_started = time.monotonic()
                    packed_direct = self.manager.native is not None
                    if packed_direct:
                        scene, _, update_kind = self.manager.render_update()
                    else:
                        scene = self.manager.render()
                        update_kind = "full"
                    compose_finished = time.monotonic()
                    if self.driver is not None:
                        with self.driver_lock:
                            if packed_direct:
                                if update_kind == "patch":
                                    self.driver.upload_patch(scene)
                                else:
                                    self.driver.upload_words(scene)
                            else:
                                self.driver.upload(scene)
                    upload_finished = time.monotonic()
                    self.last_compose_seconds = compose_finished - compose_started
                    self.last_upload_seconds = upload_finished - compose_finished
                    self.compose_seconds += self.last_compose_seconds
                    self.upload_seconds += self.last_upload_seconds
                    self.render_count += 1
                    self.update_words += len(scene) if packed_direct else 0
                    if update_kind == "patch" and len(scene):
                        self.patch_update_count += 1
                    elif update_kind == "patch":
                        self.no_op_update_count += 1
                    else:
                        self.full_update_count += 1
                    self.last_rendered = generation
                    self.render_error = None
                except Exception as exc:
                    self.render_error = repr(exc)
                    print(f"BOSIO_RENDER_ERROR {self.render_error}", flush=True)
            now = time.monotonic()
            if self.driver is not None and now - self._last_status_time >= 0.25:
                try:
                    with self.driver_lock:
                        self.output_status = self.driver.status()
                    self._last_status_time = now
                except Exception as exc:
                    self.render_error = repr(exc)
            time.sleep(self.frame_period)

    def release_scene_owner(self, app):
        with self.scene_lock:
            if self.scene_owner != str(app):
                return False
            self.scene_owner = None
        self.last_rendered = 0
        self.manager._changed()
        return True

    def run(self):
        import fcntl
        lock_path = str(self.socket_path) + ".lock"
        self.lock_file = open(lock_path, "w")
        try:
            fcntl.flock(self.lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another BOSIO window manager owns this socket") from exc
        if self.socket_path.exists():
            self.socket_path.unlink()
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        self._start_driver()
        if self.mouse_device:
            from bosio_mouse_input import EvdevMouse
            self.mouse = EvdevMouse(self.manager, self.mouse_device, self.mouse_sensitivity)
            active = self.mouse.start()
            print(f"BOSIO_MOUSE device={self.mouse.device!r} active={active}", flush=True)
        self.server = _Server(str(self.socket_path), _Handler)
        self.server.dispatch = self.dispatch
        self.server.manager = self.manager
        self.server.daemon = self
        os.chmod(self.socket_path, 0o660)
        if self.socket_group:
            import grp
            os.chown(self.socket_path, -1, grp.getgrnam(self.socket_group).gr_gid)
        self.running = True
        render_thread = threading.Thread(target=self._render_loop, name="bosio-compositor", daemon=True)
        render_thread.start()
        if self.buttons is not None:
            self.button_thread = threading.Thread(target=self._button_loop, name="bosio-buttons", daemon=True)
            self.button_thread.start()
        print(f"BOSIO_WM_READY {self.socket_path}", flush=True)
        try:
            self.server.serve_forever(poll_interval=0.1)
        finally:
            self.running = False
            self.server.server_close()
            render_thread.join(timeout=2)
            if self.button_thread is not None:
                self.button_thread.join(timeout=1)
            if self.driver is not None:
                self.driver.close()
            if self.socket_path.exists():
                self.socket_path.unlink()
            self.lock_file.close()

    def stop(self, *_):
        if self.server is not None:
            threading.Thread(target=self.server.shutdown, daemon=True).start()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default="/tmp/bosio-wm.sock")
    parser.add_argument("--bit", default="bitstream/bosio_output_disp.bit")
    parser.add_argument("--m", type=int, choices=(8, 16, 32), default=32)
    parser.add_argument("--fps", type=float, default=12)
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--no-sensor", action="store_true")
    parser.add_argument("--invert-mask", type=lambda value: int(value, 0), default=0)
    parser.add_argument("--mouse", help="Linux evdev path, or 'auto'")
    parser.add_argument("--mouse-sensitivity", type=float, default=0.12,
                        help="degrees per relative mouse count")
    parser.add_argument("--socket-group", help="group allowed to connect to the 0660 socket")
    parser.add_argument("--no-aa", action="store_true", help="disable projected-stream antialiasing")
    parser.add_argument("--aa-threshold", type=int, default=24, help="edge threshold, 0..255")
    parser.add_argument("--aa-strength", type=int, default=32, help="blend strength, 0..255")
    args = parser.parse_args()
    daemon = BosioWindowDaemon(args.socket, args.m, args.fps, args.bit, args.headless,
                               not args.no_sensor, args.invert_mask, args.mouse,
                               args.mouse_sensitivity, args.socket_group,
                               not args.no_aa, args.aa_threshold, args.aa_strength)
    signal.signal(signal.SIGTERM, daemon.stop)
    signal.signal(signal.SIGINT, daemon.stop)
    daemon.run()

if __name__ == "__main__":
    main()

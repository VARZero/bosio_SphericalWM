"""Spherical window model, compositor, focus, and pointer routing for BOSIO."""

from __future__ import annotations

import base64
import math
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field

import numpy as np

from bosio_geometry_v2 import cell_rays


class WindowManagerError(RuntimeError):
    pass


def _azimuth(value: float) -> float:
    return (float(value) + 180.0) % 360.0 - 180.0


def _elevation(value: float) -> float:
    return max(-89.5, min(89.5, float(value)))


def _direction(azimuth: float, elevation: float) -> np.ndarray:
    az, el = np.radians([azimuth, elevation])
    return np.asarray(
        [math.cos(el) * math.sin(az), math.sin(el), -math.cos(el) * math.cos(az)],
        dtype=np.float32,
    )


def _basis(azimuth: float, elevation: float, roll: float = 0.0):
    center = _direction(azimuth, elevation)
    az = math.radians(azimuth)
    right = np.asarray([math.cos(az), 0.0, math.sin(az)], dtype=np.float32)
    up = np.cross(right, center)
    angle = math.radians(roll)
    return center, right * math.cos(angle) + up * math.sin(angle), up * math.cos(angle) - right * math.sin(angle)


@dataclass
class SphericalWindow:
    window_id: int
    owner: str
    title: str
    azimuth: float
    elevation: float
    width_deg: float
    height_deg: float
    surface_width: int
    surface_height: int
    roll: float = 0.0
    mapped: bool = True
    surface_revision: int = 1
    dirty_rect: tuple[int, int, int, int] | None = None
    surface: np.ndarray = field(repr=False, default=None)

    def public(self, focused=False, z=0):
        return {
            "window_id": self.window_id,
            "owner": self.owner,
            "title": self.title,
            "azimuth": self.azimuth,
            "elevation": self.elevation,
            "roll": self.roll,
            "width_deg": self.width_deg,
            "height_deg": self.height_deg,
            "surface_width": self.surface_width,
            "surface_height": self.surface_height,
            "mapped": self.mapped,
            "focused": focused,
            "z": z,
        }


class SphericalWindowManager:
    """Thread-safe state and cell-center compositor for the 20-face framebuffer."""

    MAX_WINDOWS = 64
    MAX_SURFACE_PIXELS = 1024 * 1024

    def __init__(self, m=16, background=(2, 6, 14)):
        self.m = int(m)
        self._rays = cell_rays(self.m).astype(np.float32)
        self._flat_rays = self._rays.reshape(-1, 3)
        self._shape = self._rays.shape[:-1]
        self.background = np.asarray(background, dtype=np.uint8)
        self.windows: dict[int, SphericalWindow] = {}
        self.z_order: list[int] = []
        self.focused_window: int | None = None
        self.pointer_azimuth = 0.0
        self.pointer_elevation = 0.0
        self.pointer_visible = True
        self._drag: tuple[int, float, float] | None = None
        self._events = defaultdict(lambda: deque(maxlen=256))
        self._next_id = 1
        self.generation = 1
        self.lock = threading.RLock()
        self.native = None
        try:
            from bosio_native_compositor import NativeCompositor
            self.native = NativeCompositor(self._rays)
        except (OSError, RuntimeError, ImportError):
            self.native = None

    def _changed(self):
        self.generation += 1

    def _window(self, window_id, owner=None):
        try:
            window = self.windows[int(window_id)]
        except (KeyError, ValueError):
            raise WindowManagerError("unknown window")
        if owner is not None and window.owner != owner:
            raise WindowManagerError("window belongs to another application")
        return window

    def _event(self, owner, event_type, **payload):
        self._events[owner].append({"type": event_type, **payload})

    def create_window(self, owner, title, azimuth=0, elevation=0, width_deg=34,
                      height_deg=24, surface_width=320, surface_height=200):
        with self.lock:
            if len(self.windows) >= self.MAX_WINDOWS:
                raise WindowManagerError("window limit reached")
            sw, sh = int(surface_width), int(surface_height)
            if sw < 1 or sh < 1 or sw * sh > self.MAX_SURFACE_PIXELS:
                raise WindowManagerError("invalid surface size")
            if not 2 <= float(width_deg) <= 160 or not 2 <= float(height_deg) <= 120:
                raise WindowManagerError("invalid angular size")
            wid = self._next_id
            self._next_id += 1
            window = SphericalWindow(
                wid, str(owner), str(title)[:96], _azimuth(azimuth), _elevation(elevation),
                float(width_deg), float(height_deg), sw, sh,
                surface=np.full((sh, sw, 3), (16, 24, 32), dtype=np.uint8),
                dirty_rect=(0, 0, sw, sh),
            )
            self.windows[wid] = window
            self.z_order.append(wid)
            self._set_focus_locked(wid)
            self._changed()
            return window.public(True, len(self.z_order) - 1)

    def destroy_window(self, owner, window_id):
        with self.lock:
            window = self._window(window_id, owner)
            self.windows.pop(window.window_id)
            self.z_order.remove(window.window_id)
            if self.focused_window == window.window_id:
                self.focused_window = self.z_order[-1] if self.z_order else None
                if self.focused_window is not None:
                    target = self.windows[self.focused_window]
                    self._event(target.owner, "focus", window_id=target.window_id, focused=True)
            self._changed()

    def destroy_owner_windows(self, owner):
        with self.lock:
            owned = [wid for wid in self.z_order if self.windows[wid].owner == owner]
            for wid in owned:
                self.destroy_window(owner, wid)
            self._events.pop(owner, None)
            return len(owned)

    def _set_focus_locked(self, window_id):
        if self.focused_window == window_id:
            return
        previous = self.windows.get(self.focused_window)
        if previous:
            self._event(previous.owner, "focus", window_id=previous.window_id, focused=False)
        self.focused_window = window_id
        if window_id is not None:
            current = self.windows[window_id]
            self._event(current.owner, "focus", window_id=window_id, focused=True)

    def focus_window(self, window_id, raise_window=True):
        with self.lock:
            window = self._window(window_id)
            self._set_focus_locked(window.window_id)
            if raise_window:
                self.z_order.remove(window.window_id)
                self.z_order.append(window.window_id)
            self._changed()
            return window.public(True, self.z_order.index(window.window_id))

    def configure_window(self, owner, window_id, **changes):
        with self.lock:
            window = self._window(window_id, owner)
            if "title" in changes:
                window.title = str(changes["title"])[:96]
            if "azimuth" in changes:
                window.azimuth = _azimuth(changes["azimuth"])
            if "elevation" in changes:
                window.elevation = _elevation(changes["elevation"])
            if "roll" in changes:
                window.roll = _azimuth(changes["roll"])
            if "width_deg" in changes:
                value = float(changes["width_deg"])
                if not 2 <= value <= 160:
                    raise WindowManagerError("invalid width")
                window.width_deg = value
            if "height_deg" in changes:
                value = float(changes["height_deg"])
                if not 2 <= value <= 120:
                    raise WindowManagerError("invalid height")
                window.height_deg = value
            if "mapped" in changes:
                window.mapped = bool(changes["mapped"])
            self._changed()
            return window.public(window.window_id == self.focused_window, self.z_order.index(window.window_id))

    def raise_window(self, owner, window_id):
        with self.lock:
            window = self._window(window_id, owner)
            self.z_order.remove(window.window_id)
            self.z_order.append(window.window_id)
            self._changed()

    def lower_window(self, owner, window_id):
        with self.lock:
            window = self._window(window_id, owner)
            self.z_order.remove(window.window_id)
            self.z_order.insert(0, window.window_id)
            self._changed()

    def fill(self, owner, window_id, rgb):
        with self.lock:
            window = self._window(window_id, owner)
            color = np.asarray(rgb, dtype=np.int64)
            if color.shape != (3,) or np.any(color < 0) or np.any(color > 255):
                raise WindowManagerError("rgb must contain three bytes")
            window.surface[:] = color.astype(np.uint8)
            window.surface_revision += 1
            window.dirty_rect = (0, 0, window.surface_width, window.surface_height)
            self._changed()

    def update_surface(self, owner, window_id, x, y, width, height, rgb24):
        with self.lock:
            window = self._window(window_id, owner)
            x, y, width, height = map(int, (x, y, width, height))
            if x < 0 or y < 0 or width < 1 or height < 1 or x + width > window.surface_width or y + height > window.surface_height:
                raise WindowManagerError("surface update is out of bounds")
            try:
                raw = base64.b64decode(rgb24, validate=True)
            except Exception as exc:
                raise WindowManagerError("invalid rgb24 base64") from exc
            if len(raw) != width * height * 3:
                raise WindowManagerError("rgb24 byte count does not match rectangle")
            window.surface[y:y + height, x:x + width] = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 3)
            window.surface_revision += 1
            if window.dirty_rect is None:
                window.dirty_rect = (x, y, width, height)
            else:
                ox, oy, ow, oh = window.dirty_rect
                x0, y0 = min(ox, x), min(oy, y)
                x1, y1 = max(ox + ow, x + width), max(oy + oh, y + height)
                window.dirty_rect = (x0, y0, x1 - x0, y1 - y0)
            self._changed()

    def _project(self, window, directions):
        center, right, up = _basis(window.azimuth, window.elevation, window.roll)
        dot = directions @ center
        safe = np.maximum(dot, 1e-8)
        x = (directions @ right) / safe / math.tan(math.radians(window.width_deg / 2))
        y = (directions @ up) / safe / math.tan(math.radians(window.height_deg / 2))
        return dot, x, y

    def hit_test(self, azimuth, elevation):
        direction = _direction(_azimuth(azimuth), _elevation(elevation))[None, :]
        with self.lock:
            for wid in reversed(self.z_order):
                window = self.windows[wid]
                if not window.mapped:
                    continue
                dot, x, y = self._project(window, direction)
                if dot[0] > 0 and abs(x[0]) <= 1 and abs(y[0]) <= 1:
                    u = float((x[0] + 1) * 0.5)
                    v = float((1 - y[0]) * 0.5)
                    return window, u, v, "title" if v < 0.14 else "content"
        return None

    def pointer_warp(self, azimuth, elevation):
        with self.lock:
            old_az, old_el = self.pointer_azimuth, self.pointer_elevation
            self.pointer_azimuth, self.pointer_elevation = _azimuth(azimuth), _elevation(elevation)
            if self._drag:
                wid, base_az, base_el = self._drag
                window = self.windows.get(wid)
                if window:
                    delta_az = _azimuth(self.pointer_azimuth - old_az)
                    window.azimuth = _azimuth(window.azimuth + delta_az)
                    window.elevation = _elevation(window.elevation + self.pointer_elevation - old_el)
            hit = self.hit_test(self.pointer_azimuth, self.pointer_elevation)
            if hit:
                window, u, v, zone = hit
                self._event(window.owner, "pointer_motion", window_id=window.window_id, u=u, v=v, zone=zone,
                            azimuth=self.pointer_azimuth, elevation=self.pointer_elevation)
            self._changed()
            return self.pointer_state(hit)

    def pointer_move(self, delta_azimuth, delta_elevation):
        return self.pointer_warp(self.pointer_azimuth + float(delta_azimuth), self.pointer_elevation + float(delta_elevation))

    def pointer_button(self, button, pressed):
        button, pressed = str(button), bool(pressed)
        with self.lock:
            hit = self.hit_test(self.pointer_azimuth, self.pointer_elevation)
            if pressed and button == "left" and hit:
                window, _, _, zone = hit
                self.focus_window(window.window_id, True)
                if zone == "title":
                    self._drag = (window.window_id, window.azimuth, window.elevation)
            if not pressed and button == "left":
                self._drag = None
            if hit:
                window, u, v, zone = hit
                self._event(window.owner, "pointer_button", window_id=window.window_id, button=button,
                            pressed=pressed, u=u, v=v, zone=zone)
            self._changed()
            return self.pointer_state(hit)

    def pointer_state(self, hit=None):
        if hit is None:
            hit = self.hit_test(self.pointer_azimuth, self.pointer_elevation)
        return {
            "azimuth": self.pointer_azimuth,
            "elevation": self.pointer_elevation,
            "visible": self.pointer_visible,
            "window_id": hit[0].window_id if hit else None,
            "zone": hit[3] if hit else None,
            "dragging": self._drag is not None,
        }

    def poll_events(self, owner, limit=64):
        with self.lock:
            queue = self._events[str(owner)]
            return [queue.popleft() for _ in range(min(max(0, int(limit)), len(queue)))]

    def state(self):
        with self.lock:
            return {
                "generation": self.generation,
                "compositor": "cpp-neon" if self.native is not None else "numpy",
                "focused_window": self.focused_window,
                "pointer": self.pointer_state(),
                "windows": [self.windows[wid].public(wid == self.focused_window, z)
                            for z, wid in enumerate(self.z_order)],
            }

    def render(self):
        """Return RGB[20,211,M*M,3], composited from back to front."""
        with self.lock:
            if self.native is not None:
                order = [wid for wid in self.z_order if self.windows[wid].mapped]
                return self.native.render(
                    self.windows, order, self.focused_window,
                    (self.pointer_azimuth, self.pointer_elevation, self.pointer_visible),
                    self.background, self._shape,
                )
            image = np.empty((*self._shape, 3), dtype=np.uint8)
            image[:] = self.background
            flat = image.reshape(-1, 3)
            for wid in self.z_order:
                window = self.windows[wid]
                if not window.mapped:
                    continue
                dot, x, y = self._project(window, self._flat_rays)
                mask = (dot > 0) & (np.abs(x) <= 1) & (np.abs(y) <= 1)
                indices = np.flatnonzero(mask)
                if not len(indices):
                    continue
                px = np.clip(np.rint((x[mask] + 1) * 0.5 * (window.surface_width - 1)), 0, window.surface_width - 1).astype(np.int32)
                py = np.clip(np.rint((1 - y[mask]) * 0.5 * (window.surface_height - 1)), 0, window.surface_height - 1).astype(np.int32)
                flat[indices] = window.surface[py, px]
                title = y[mask] > 0.72
                border = (np.abs(x[mask]) > 0.94) | (np.abs(y[mask]) > 0.92)
                flat[indices[title]] = (22, 112, 190) if wid == self.focused_window else (55, 65, 81)
                flat[indices[border]] = (250, 204, 21) if wid == self.focused_window else (120, 130, 145)
            if self.pointer_visible:
                pointer = _direction(self.pointer_azimuth, self.pointer_elevation)
                dots = self._flat_rays @ pointer
                outer = dots >= math.cos(math.radians(2.2))
                inner = dots >= math.cos(math.radians(1.0))
                flat[outer] = (10, 10, 10)
                flat[inner] = (255, 255, 255)
            return image

    def render_packed(self):
        """Return the output-core scene words directly when native support exists."""
        with self.lock:
            if self.native is not None:
                order = [wid for wid in self.z_order if self.windows[wid].mapped]
                return self.native.render_packed(
                    self.windows, order, self.focused_window,
                    (self.pointer_azimuth, self.pointer_elevation, self.pointer_visible),
                    self.background, self.m,
                )
        from bosio_geometry_v2 import pack_scene
        return pack_scene(self.render(), self.m)

    def render_update(self):
        """Return ``(words, tile_count, kind)`` where kind is full or patch."""
        with self.lock:
            if self.native is not None:
                order = [wid for wid in self.z_order if self.windows[wid].mapped]
                return self.native.render_update(
                    self.windows, order, self.focused_window,
                    (self.pointer_azimuth, self.pointer_elevation, self.pointer_visible),
                    self.background, self.m,
                )
        words, count = self.render_packed()
        return words, count, "full"

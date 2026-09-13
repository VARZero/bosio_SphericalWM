#!/usr/bin/env python3
"""Minimal BOSIO application: change an image every second and print clicks."""

from __future__ import annotations

import argparse
import time

import numpy as np

from bosio_wm_client import BosioWMClient


def make_image(width: int, height: int, frame: int) -> np.ndarray:
    """Create a small RGB image without requiring Pillow or a GUI toolkit."""
    y, x = np.mgrid[0:height, 0:width]
    phase = frame * 32
    image = np.empty((height, width, 3), dtype=np.uint8)
    image[..., 0] = (x + phase) % 256
    image[..., 1] = (y * 2 + phase) % 256
    image[..., 2] = ((x // 2 + y + phase) % 256)
    # A bright moving marker makes the one-second update visible.
    cx = (frame * 37) % width
    cy = (frame * 23) % height
    image[max(0, cy - 8):min(height, cy + 8),
          max(0, cx - 8):min(width, cx + 8)] = (255, 255, 255)
    return image


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default="/tmp/bosio-wm.sock")
    parser.add_argument("--width", type=int, default=320)
    parser.add_argument("--height", type=int, default=200)
    parser.add_argument("--azimuth", type=float, default=0.0)
    parser.add_argument("--elevation", type=float, default=-20.0)
    args = parser.parse_args()

    with BosioWMClient("image-demo", args.socket) as wm:
        window = wm.create_window(
            "IMAGE DEMO",
            azimuth=args.azimuth,
            elevation=args.elevation,
            width_deg=36,
            height_deg=24,
            surface_width=args.width,
            surface_height=args.height,
        )
        window_id = window["window_id"]
        print(f"window_id={window_id}; click inside the window; Ctrl-C to exit")

        frame = 0
        next_image = 0.0
        try:
            while True:
                now = time.monotonic()
                if now >= next_image:
                    wm.update_surface(window_id, make_image(args.width, args.height, frame))
                    print(f"image frame={frame}", flush=True)
                    frame += 1
                    next_image = now + 1.0

                for event in wm.poll_events():
                    if event.get("type") == "pointer_button":
                        u = float(event.get("u", 0.0))
                        v = float(event.get("v", 0.0))
                        px = min(args.width - 1, max(0, int(u * args.width)))
                        py = min(args.height - 1, max(0, int(v * args.height)))
                        print(
                            "click "
                            f"button={event.get('button')} pressed={event.get('pressed')} "
                            f"u={u:.4f} v={v:.4f} pixel=({px},{py}) "
                            f"zone={event.get('zone')}",
                            flush=True,
                        )
                    elif event.get("type") == "focus":
                        print(f"focus={event.get('focused')}", flush=True)
                time.sleep(0.01)
        except KeyboardInterrupt:
            print("stopping image demo")


if __name__ == "__main__":
    main()

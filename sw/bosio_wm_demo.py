#!/usr/bin/env python3
"""Create overlapping spherical windows through the public IPC client API."""

import argparse
import time

import numpy as np

from bosio_wm_client import BosioWMClient


def surface(width, height, color, accent):
    image = np.empty((height, width, 3), dtype=np.uint8)
    image[:] = color
    image[::12, :] = accent
    image[:, ::16] = accent
    image[height // 3:height // 3 + 8, 8:-8] = (245, 245, 245)
    return image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default="/tmp/bosio-wm.sock")
    parser.add_argument("--hold", type=float, default=0, help="seconds; zero waits until Ctrl-C")
    parser.add_argument("--center-azimuth", type=float, default=0)
    parser.add_argument("--center-elevation", type=float, default=0)
    args = parser.parse_args()
    clients = []
    specs = [
        ("flight", "FLIGHT", -12, 4, (18, 62, 105), (40, 170, 245)),
        ("navigation", "NAV", 10, 2, (18, 96, 63), (50, 220, 135)),
        ("system", "SYSTEM", 43, 10, (84, 38, 112), (190, 90, 240)),
        ("radio", "RADIO", -53, -9, (105, 45, 28), (245, 125, 60)),
    ]
    for app, title, az, el, color, accent in specs:
        client = BosioWMClient(app, args.socket)
        window = client.create_window(title, args.center_azimuth + az,
                                      args.center_elevation + el, 38, 27, 192, 120)
        client.update_surface(window["window_id"], surface(192, 120, color, accent))
        clients.append((client, window["window_id"]))
    clients[1][0].focus_window(clients[1][1])
    clients[1][0].pointer_warp(args.center_azimuth + 10, args.center_elevation + 2)
    clients[1][0].pointer_button(True)
    clients[1][0].pointer_button(False)
    print(clients[1][0].get_state())
    try:
        if args.hold > 0:
            time.sleep(args.hold)
        else:
            while True:
                time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        for client, window_id in clients:
            try:
                client.destroy_window(window_id)
            except Exception:
                pass
            client.close()


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Small external-input example for BOSIO."""

import argparse
import time

from bosio_input_client import BosioInputClient


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default="/tmp/bosio-wm.sock")
    parser.add_argument("--azimuth", type=float, default=0.0)
    parser.add_argument("--elevation", type=float, default=-59.0)
    parser.add_argument("--drag-degrees", type=float, default=0.0)
    args = parser.parse_args()

    with BosioInputClient("input-demo", args.socket) as pointer:
        pointer.move_absolute(args.azimuth, args.elevation)
        if args.drag_degrees:
            pointer.button(True)
            steps = 20
            for _ in range(steps):
                pointer.move_relative(args.drag_degrees / steps, 0)
                time.sleep(0.02)
            pointer.button(False)
        else:
            pointer.click()
        print(pointer.state(), flush=True)


if __name__ == "__main__":
    main()

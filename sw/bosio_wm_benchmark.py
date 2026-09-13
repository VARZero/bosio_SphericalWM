#!/usr/bin/env python3
"""End-to-end BOSIO compositor, scene pack/DMA, IPC, and HDMI benchmark."""

from __future__ import annotations

import argparse
import json
import time

import numpy as np

from bosio_wm_client import BosioWMClient


def solid(height, width, rgb):
    image = np.empty((height, width, 3), dtype=np.uint8)
    image[:] = rgb
    return image


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default="/tmp/bosio-wm.sock")
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--output", default="bosio_wm_benchmark.json")
    parser.add_argument("--frame-limit", type=float, default=240.0)
    parser.add_argument("--patch-size", type=int, default=1)
    args = parser.parse_args()
    client = BosioWMClient("wm-benchmark", args.socket, timeout=15)
    original_limit = client.get_state()["performance"]["frame_limit"]
    client.set_frame_limit(args.frame_limit)
    results = []
    windows = []

    def remove_windows():
        while windows:
            client.destroy_window(windows.pop())
        time.sleep(0.4)

    def add_window(title, az, el, wdeg, hdeg, width, height, color):
        window = client.create_window(title, az, el, wdeg, hdeg, width, height)
        wid = window["window_id"]
        client.update_surface(wid, solid(height, width, color))
        windows.append(wid)
        return wid

    def measure(name, full_surface=None):
        time.sleep(0.5)
        client.reset_performance()
        start = client.get_state()
        start_frames = start["output"]["frames"]
        start_words = start["output"]["received"]
        calls = 0
        toggle = 0
        t0 = time.monotonic()
        deadline = t0 + args.seconds
        while time.monotonic() < deadline:
            if windows:
                toggle ^= 1
                if full_surface is None:
                    patch = np.empty((args.patch_size, args.patch_size, 3), dtype=np.uint8)
                    patch[:] = (255 if toggle else 32, 64, 192)
                    client.update_surface(windows[-1], patch, calls % 32, (calls // 32) % 32)
                else:
                    frame = full_surface.copy()
                    frame[0, 0] = (255 if toggle else 0, 64, 192)
                    client.update_surface(windows[-1], frame)
            else:
                client.pointer_move(0.002, 0)
            calls += 1
        final = client.get_state()
        elapsed = time.monotonic() - t0
        perf = final["performance"]
        applied = perf.get("full_update_count", 0) + perf.get("patch_update_count", 0)
        result = {
            "case": name,
            "seconds": elapsed,
            "windows": len(windows),
            "ipc_calls": calls,
            "ipc_calls_per_second": calls / elapsed,
            "scene_updates": perf["render_count"],
            "full_updates": perf.get("full_update_count", 0),
            "patch_updates": perf.get("patch_update_count", 0),
            "no_op_updates": perf.get("no_op_update_count", 0),
            "average_packet_words": (perf.get("update_words", 0) / applied if applied else 0),
            "scene_update_fps": perf["render_count"] / elapsed,
            "applied_update_fps": applied / elapsed,
            "average_compose_ms": perf["average_compose_ms"],
            "average_pack_dma_ms": perf["average_upload_ms"],
            "hdmi_fps": ((final["output"]["frames"] - start_frames) & 0xffff) / elapsed,
            "dma_words_transferred": (final["output"]["received"] - start_words) & 0xffffffff,
            "average_dma_words_per_update": (((final["output"]["received"] - start_words) & 0xffffffff)
                                             / applied if applied else 0),
            "render_error": final["render_error"],
        }
        print(json.dumps(result), flush=True)
        results.append(result)

    try:
        remove_windows()
        measure("no_windows_pointer_dirty")

        add_window("FOV25", 0, 0, 30, 22.5, 152, 112, (20, 100, 180))
        measure("one_window_25_percent_fov")
        remove_windows()

        add_window("FOV50", 0, 0, 42.4, 31.8, 216, 160, (25, 130, 90))
        measure("one_window_50_percent_fov")
        remove_windows()

        full = solid(192, 304, (90, 35, 145))
        add_window("FOV100", 0, 0, 60, 45, 304, 192, (90, 35, 145))
        measure("one_window_100_percent_fov")
        measure("one_window_100_percent_fov_full_rgb_ipc", full)
        remove_windows()

        for index, (az, el) in enumerate(((-15, -11.25), (15, -11.25), (-15, 11.25), (15, 11.25))):
            add_window(f"TILE{index}", az, el, 30, 22.5, 152, 112,
                       (30 + index * 35, 80, 150 - index * 20))
        measure("four_windows_covering_fov")
        remove_windows()

        for index in range(8):
            add_window(f"OVERLAP{index}", 0, 0, 60, 45, 64, 64,
                       (20 + index * 20, 40 + index * 10, 100))
        measure("eight_overlapping_full_fov_windows")
    finally:
        remove_windows()
        client.set_frame_limit(original_limit)
        client.close()

    report = {
        "m": 16,
        "output_resolution": [1280, 720],
        "output_target_fps": 60,
        "benchmark_frame_limit": args.frame_limit,
        "duration_per_case_seconds": args.seconds,
        "results": results,
    }
    with open(args.output, "w", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()

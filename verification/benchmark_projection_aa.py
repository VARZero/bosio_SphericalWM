import base64
import time

import numpy as np

from sw.bosio_window_manager import SphericalWindowManager


def measure(aa):
    wm = SphericalWindowManager(16, background=(0, 0, 0), projection_aa=aa)
    win = wm.create_window("bench", "TEXT", width_deg=42, height_deg=30,
                           surface_width=640, surface_height=360)
    frame = np.full((360, 640, 3), 255, dtype=np.uint8)
    for x in range(80, 560, 19):
        frame[60:300, x:x + 2] = 0
    wm.update_surface("bench", win["window_id"], 0, 0, 640, 360,
                      base64.b64encode(frame.tobytes()).decode("ascii"))
    wm.render_update()
    times = []
    for i in range(5):
        frame[60:300, 80 + i * 19:82 + i * 19] = 255
        wm.update_surface("bench", win["window_id"], 80 + i * 19, 60, 2, 240,
                          base64.b64encode(np.full((240, 2, 3), 255, np.uint8).tobytes()).decode("ascii"))
        start = time.perf_counter()
        _, tiles, kind = wm.render_update()
        times.append((time.perf_counter() - start) * 1000)
    scene = wm.render()
    mid = int(np.count_nonzero((scene[..., 0] > 15) & (scene[..., 0] < 240)))
    print(f"aa={aa} native={wm.native is not None} mid_cells={mid} dirty_ms={np.median(times):.2f} update_kind={kind} tiles={tiles}")


measure(False)
measure(True)

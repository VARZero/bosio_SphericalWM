"""Measure the live launcher in view, then restore hardware sensor tracking."""
import json
from pathlib import Path
import time
from pynq import MMIO, PL
from pynq.pl_server import embedded_device
from bosio_geometry_v2 import camera_coefficients

assert Path(PL.bitfile_name).name == 'bosio_output_projection_dual.bit'
core = MMIO(0x43c00000, 0x10000)
assert core.read(0x5c) == 2 and core.read(4) & 0x23 == 3
sensor = core.read(0x78) & 1
assert sensor == 1, 'This check requires sensor tracking so the previous view can be restored'


def wait(predicate, timeout=10):
    deadline = time.monotonic()+timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise TimeoutError('Pose transition did not complete')
        time.sleep(.001)


report = {}
try:
    core.write(0x78, 0)
    wait(lambda: not core.read(4) & 8)
    core.write(0x60, 0)
    for value in camera_coefficients(0, 0, 0, 60, 45).flat:
        core.write(0x64, int(value) & 0xffffffff)
    core.write(0x68, 1)
    wait(lambda: not core.read(4) & 8)
    time.sleep(.2)
    before = core.read(4) >> 16
    started = time.monotonic()
    time.sleep(3)
    status = core.read(4)
    elapsed = time.monotonic()-started
    delta = ((status >> 16)-before) & 65535
    assert delta > 0 and status & 0x23 == 3
    report.update(center_yaw=0, center_pitch=0, fov=[60,45], m=32,
                  frame_delta=delta, elapsed_seconds=elapsed, output_fps=delta/elapsed,
                  output_error=False)
finally:
    before_sensor = core.read(0x78) >> 16
    core.write(0x78, sensor)
    wait(lambda: (core.read(0x78) & 3) == 3 and (core.read(0x78) >> 16) != before_sensor)
    report['sensor_restored'] = True
report['passed'] = True
Path(__file__).with_name('display_pose_results.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report), flush=True)

"""Read-only HDMI health plus reversible pose/producer-stall fault injection.

Run on the board alongside the WM, using its existing allocation and overlay.
The capture runner records the physical HDMI output independently.
"""
import json
import signal
import time

from pynq import MMIO
from pynq.pl_server import embedded_device
from bosio_geometry_v2 import camera_coefficients
from bosio_wm_client import BosioWMClient
from bosio_scanout import BufferedScanout

core = MMIO(0x43c00000, 0x10000)
vdma = MMIO(0x43000000, 0x10000)
health = MMIO(0x41210000, 0x10000)
scanout = BufferedScanout(vdma, health, lambda **_: None)

def emit(**data):
    print(json.dumps(data), flush=True)

def wait_pose():
    end = time.monotonic() + 5
    while core.read(4) & 8:
        if time.monotonic() > end:
            raise TimeoutError('pose commit')
        time.sleep(.001)

def pose(yaw, pitch, roll):
    wait_pose()
    core.write(0x60, 0)
    for value in camera_coefficients(yaw, pitch, roll, 60, 45).flat:
        core.write(0x64, int(value) & 0xffffffff)
    core.write(0x68, 1)
    wait_pose()

def snapshot():
    return dict(t=time.monotonic(), core=core.read(4), received=core.read(0x70), **scanout.status())

def sample(name, seconds=2):
    before = snapshot()
    emit(type='begin', name=name, snapshot=before)
    time.sleep(seconds)
    after = snapshot()
    elapsed = after['t'] - before['t']
    row = dict(type='result', name=name, seconds=elapsed,
               producer_fps=(((after['core'] >> 16) - (before['core'] >> 16)) & 65535) / elapsed,
               hdmi_fps=((after['video_frames']-before['video_frames']) & 0xffffffff) / elapsed,
               lock_losses=after['lock_losses']-before['lock_losses'],
               underflows=after['underflow_events']-before['underflow_events'],
               metadata_words=(after['received']-before['received']) & 0xffffffff,
               snapshot=after)
    emit(**row)
    assert after['video_locked'] and not row['lock_losses'] and not row['underflows'], row
    assert 58 < row['hdmi_fps'] < 62, row
    assert not after['read_errors'], row
    return row

def interrupted(*_):
    raise KeyboardInterrupt()

signal.signal(signal.SIGTERM, interrupted)
signal.signal(signal.SIGINT, interrupted)
sensor, enabled = core.read(0x78) & 1, core.read(0) & 1
with BosioWMClient('scanout-validation', timeout=30) as wm:
    state = wm.get_state()
    assert state.get('scanout') and wm.ping()['m'] == 32, 'Requires running M=32 buffered scanout overlay'
    app = next(w for w in state['windows'] if w['title'] == 'Dashboard' and w['mapped'])
    y, p = app['azimuth'], app['elevation']
    emit(type='setup', m=wm.ping()['m'], center=[y, p], sensor=sensor,
         cache_bytes=core.read(0x38), initial=snapshot())
    try:
        core.write(0x78, 0)
        for roll in (0, 45, 90, 135, 180, 225, 270, 315, 0):
            pose(y, p, roll)
            time.sleep(.3)
            row = sample('roll_%d' % roll)
            assert not row['snapshot']['write_errors'], row
        for yaw, pitch in ((y-10, p), (y+10, p), (y, p-8), (y, p+8)):
            pose(yaw, pitch, 45)
            time.sleep(.3)
            sample('yaw_pitch_%g_%g' % (yaw, pitch))
        pose(y, p, 0)
        time.sleep(1)
        sample('before_stall')
        core.write(0, 0)
        time.sleep(.2)
        row = sample('producer_stopped', 4)
        assert row['producer_fps'] == 0, row
        core.write(0, enabled)
        time.sleep(1)
        # Disabling the producer discards a partial frame. Record any expected
        # S2MM SOF-early indication, then verify recovery and new full frames.
        emit(type='restart', snapshot=snapshot())
        vdma.write(0x34, scanout.WRITE_ERRORS)
        row = sample('producer_resumed', 3)
        assert row['producer_fps'] > 10 and not row['snapshot']['write_errors'], row
        emit(type='reference', result=wm.call('check_incremental_reference'))
    finally:
        core.write(0, enabled)
        core.write(0x78, sensor)
        emit(type='restored', sensor=bool(core.read(0x78) & 1), snapshot=snapshot())

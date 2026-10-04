"""Run with the display services stopped; reloads the FPGA and tests BS25 DDR ownership."""
import json
import time
from pathlib import Path

import numpy as np
from bosio_driver_v2 import BosioV2
from bosio_native_compositor import pack_scene


def measure(core, seconds=2):
    first = core.status()
    start = time.monotonic()
    time.sleep(seconds)
    last = core.status()
    elapsed = time.monotonic() - start
    assert not last['error'], last
    frames = (last['frames'] - first['frames']) & 0xffff
    hits = (last['cache_hits'] - first['cache_hits']) & 0xffffffff
    misses = (last['cache_misses'] - first['cache_misses']) & 0xffffffff
    assert frames > 0, 'Output stream stopped'
    return dict(frames=frames, seconds=elapsed, stream_fps=frames/elapsed,
                hits=hits, misses=misses,
                hit_rate=hits/max(1, hits+misses), status=last)


def main():
    result = {'m': 16}
    core = BosioV2('bitstream/bosio_output_disp.bit', m=16)
    try:
        assert core.ddr_cache, 'BS25 bitstream required'
        assert (core.core.read(0x34), core.core.read(0x38), core.core.read(0x3c)) == (64, 16384, 2)
        image = np.full((20, 211, 256, 3), (96, 160, 192), dtype=np.uint8)
        scene, tiles = pack_scene(image, 16)
        assert tiles == 4220 and len(scene) > 53632
        result.update(active_tiles=tiles, scene_words=len(scene), scene_bytes=scene.nbytes)
        core.upload_words(scene)
        core.set_pose(0, 0, wait=False)
        core.start()
        result['full_sphere'] = measure(core)
        patch = np.zeros(96, dtype=np.uint32)
        patch[:4] = [0x42505431, 64, 1, 96]
        patch[16:18] = [0, 0]
        times = []
        for revision in range(8):
            payload = np.uint32(0x55555555 if revision & 1 else 0xaaaaaaaa)
            patch[32:] = payload
            previous = core._ddr_current
            start = time.monotonic()
            assert core.upload_patch(patch) == 1
            times.append((time.monotonic()-start)*1000)
            assert core._ddr_current != previous
            assert core.core.read(0x44) == core._ddr_buffers[core._ddr_current].physical_address
            for buffer in core._ddr_buffers:
                assert np.all(buffer[4476:4540] == payload)
        result['patches'] = dict(count=len(times), upload_ms=times,
                                 average_ms=float(np.mean(times)), packet_words=len(patch))
        core.use_sensor(True)
        result['sensor'] = measure(core)
        image32 = np.full((20, 211, 1024, 3), 255, dtype=np.uint8)
        packed32, tiles32 = pack_scene(image32, 32)
        assert tiles32 == 4220 and len(packed32) == 1084800
        result['m32_native_pack'] = dict(active_tiles=tiles32, words=len(packed32))
    finally:
        core.close()
    result['buffers_released_after_drain'] = all(buffer is None for buffer in core._ddr_buffers)
    Path('/tmp/bosio_cache_board_validation.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()

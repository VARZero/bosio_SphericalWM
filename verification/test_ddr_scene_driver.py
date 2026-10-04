import unittest
import numpy as np
from sw.bosio_driver_v2 import BosioV2
from sw.bosio_geometry_v2 import pack_scene


class Buffer(np.ndarray):
    next_address = 0x10000000

    def __new__(cls, shape, dtype):
        obj = np.zeros(shape, dtype=dtype).view(cls)
        obj.physical_address = cls.next_address
        cls.next_address += 0x800000
        obj.freed = False
        return obj

    def flush(self):
        pass

    def freebuffer(self):
        self.freed = True


class Registers:
    def __init__(self):
        self.reg = {0: 0, 0x44: 0}
        self.pending = False

    def write(self, offset, value):
        self.reg[offset] = value
        if offset == 0x6c:
            self.pending = True
        if self.pending and self.reg[0]:
            self.reg[0x44] = self.reg[8]
            self.pending = False

    def read(self, offset):
        return self.reg.get(offset, 0)


class DDRSceneDriverTests(unittest.TestCase):
    def setUp(self):
        self.driver = BosioV2.__new__(BosioV2)
        d = self.driver
        d.core = Registers()
        d.allocate = Buffer
        d.ddr_cache = True
        d.running = False
        d.m = 16
        d._ddr_buffers = [None, None]
        d._ddr_current = 0
        d._ddr_pending = None
        d._scene_shadow = None
        d._wait = self.wait
        self.scene = np.zeros(4544, dtype=np.uint32)
        self.scene[256:4476] = 0xffffffff
        self.scene[256] = 0
        self.scene[4476:4540] = 0x01010101

    def wait(self, predicate, timeout=3):
        state = dict(scene_pending=self.driver.core.pending,
                     dma_busy=self.driver.core.pending,
                     scene_valid=bool(self.driver.core.read(0x44)), pose_pending=False)
        self.assertTrue(predicate(state), 'driver waited for an invalid completion condition')
        return state

    def patch(self):
        patch = np.zeros(96, dtype=np.uint32)
        patch[:4] = [0x42505431, 64, 1, 96]
        patch[16:18] = [0, 0]
        patch[32:] = 0x02020202
        return patch

    def test_stopped_start_and_partial_mirror(self):
        d = self.driver
        d.upload_words(self.scene)
        self.assertEqual(d._ddr_pending, 1)
        self.assertIsNone(d._ddr_buffers[0])
        d.start()
        self.assertIsNone(d._ddr_pending)
        for buf in d._ddr_buffers:
            np.testing.assert_array_equal(buf[:len(self.scene)], self.scene)
        previous = d._ddr_current
        self.assertEqual(d.upload_patch(self.patch()), 1)
        self.assertNotEqual(previous, d._ddr_current)
        self.assertEqual(d.core.reg[0x6c], 2)
        for buf in d._ddr_buffers:
            np.testing.assert_array_equal(buf[4476:4540], np.full(64, 0x02020202, dtype=np.uint32))

    def test_bad_patch_does_not_mutate_scene(self):
        d = self.driver
        d.upload_words(self.scene)
        d.start()
        malformed = self.patch()
        malformed[16] = 1000000
        with self.assertRaises(ValueError):
            d.upload_patch(malformed)
        np.testing.assert_array_equal(d._scene_shadow, self.scene)

    def test_full_sphere_m32_pack_exceeds_legacy_limit(self):
        image = np.full((20, 211, 1024, 3), 255, dtype=np.uint8)
        words, active = pack_scene(image, 32)
        self.assertEqual(active, 4220)
        self.assertGreater(len(words), 1000000)
        self.assertEqual(int(words[256+4219]), 4219*1024)


if __name__ == '__main__':
    unittest.main()

import math
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "sw"))

from bosio_gy521 import ComplementaryPoseFilter, MotionSample, _s16


class GY521SensorHubTest(unittest.TestCase):
    def test_signed_register_decode(self):
        self.assertEqual(_s16(0x00, 0x01), 1)
        self.assertEqual(_s16(0x7F, 0xFF), 32767)
        self.assertEqual(_s16(0xFF, 0xFF), -1)
        self.assertEqual(_s16(0x80, 0x00), -32768)

    def test_level_stationary_pose(self):
        sample = MotionSample((0, 0, 8192), 0, (12, -7, 4), 1.0)
        filt = ComplementaryPoseFilter()
        filt.calibrate([sample] * 20)
        pose = filt.update(MotionSample((0, 0, 8192), 0, (12, -7, 4), 1.01))
        self.assertAlmostEqual(pose.pitch, 0.0, places=5)
        self.assertAlmostEqual(pose.roll, 0.0, places=5)
        self.assertAlmostEqual(pose.yaw, 0.0, places=5)

    def test_gravity_corrects_roll(self):
        filt = ComplementaryPoseFilter(alpha=0.0)
        level = MotionSample((0, 0, 8192), 0, (0, 0, 0), 1.0)
        filt.calibrate([level])
        s = int(8192 / math.sqrt(2))
        pose = filt.update(MotionSample((0, s, s), 0, (0, 0, 0), 1.01))
        self.assertAlmostEqual(pose.roll, 45.0, delta=0.1)


if __name__ == "__main__":
    unittest.main()

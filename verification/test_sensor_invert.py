import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "sw"))
from bosio_driver_v2 import BosioV2


class FakeCore:
    def __init__(self):
        self.regs = {}

    def write(self, address, value):
        self.regs[address] = value


class SensorInvertTest(unittest.TestCase):
    def test_independent_axis_bits(self):
        driver = object.__new__(BosioV2)
        driver.core = FakeCore()

        self.assertEqual(driver.set_sensor_invert(yaw=True), 0b001)
        self.assertEqual(driver.core.regs[0x20], 0b001)
        self.assertEqual(driver.set_sensor_invert(pitch=True), 0b010)
        self.assertEqual(driver.set_sensor_invert(roll=True), 0b100)
        self.assertEqual(
            driver.set_sensor_invert(yaw=True, pitch=True, roll=True), 0b111
        )


if __name__ == "__main__":
    unittest.main()

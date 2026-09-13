"""Software diagnostic GY-521/MPU6050 sensor hub for an AXI-IIC overlay.

This is retained as a fallback for older overlays exposing ``iic_0``. The
current production path reads and filters the sensor entirely in RTL.
This module configures the MPU6050, reads its 14-byte motion frame, estimates
yaw/pitch/roll, and commits the pose through :class:`BosioV2`.

MPU6050 has no magnetometer.  Pitch and roll are corrected by gravity while
yaw is gyro-only and will drift over time.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import time
from typing import Optional, Sequence


MPU6050_ADDRESS = 0x68
WHO_AM_I = 0x75
PWR_MGMT_1 = 0x6B
SMPLRT_DIV = 0x19
CONFIG = 0x1A
GYRO_CONFIG = 0x1B
ACCEL_CONFIG = 0x1C
INT_ENABLE = 0x38
ACCEL_XOUT_H = 0x3B


def _s16(msb: int, lsb: int) -> int:
    value = (msb << 8) | lsb
    return value - 0x10000 if value & 0x8000 else value


@dataclass(frozen=True)
class MotionSample:
    accel: tuple[int, int, int]
    temperature_raw: int
    gyro: tuple[int, int, int]
    timestamp: float


@dataclass(frozen=True)
class Pose:
    yaw: float
    pitch: float
    roll: float


class AxiIICRegisterBus:
    """Small register-oriented adapter for PYNQ's ``AxiIIC`` driver."""

    def __init__(self, axi_iic, address: int = MPU6050_ADDRESS):
        from pynq import allocate

        self.iic = axi_iic
        self.address = int(address)
        self.allocate = allocate

    def write(self, register: int, values: Sequence[int] | int) -> None:
        if isinstance(values, int):
            values = (values,)
        payload = bytes((register & 0xFF, *(int(v) & 0xFF for v in values)))
        with self.allocate(shape=(len(payload),), dtype="u1") as buffer:
            buffer[:] = list(payload)
            sent = self.iic.send(self.address, buffer, len(payload), 0)
            if sent != len(payload):
                raise IOError(f"MPU6050 I2C short write: {sent}/{len(payload)}")

    def read(self, register: int, length: int) -> bytes:
        if length <= 0:
            return b""
        with self.allocate(shape=(1,), dtype="u1") as pointer:
            pointer[0] = register & 0xFF
            sent = self.iic.send(self.address, pointer, 1, 1)
            if sent != 1:
                raise IOError("MPU6050 I2C register-select failed")
        with self.allocate(shape=(length,), dtype="u1") as buffer:
            received = self.iic.receive(self.address, buffer, length, 0)
            if received != length:
                raise IOError(f"MPU6050 I2C short read: {received}/{length}")
            return bytes(int(v) for v in buffer)


class MPU6050:
    """MPU6050 configuration and raw motion-frame access."""

    ACCEL_LSB_PER_G = 8192.0       # AFS_SEL=1, +/-4 g
    GYRO_LSB_PER_DPS = 65.5        # FS_SEL=1, +/-500 deg/s

    def __init__(self, bus: AxiIICRegisterBus):
        self.bus = bus

    def initialize(self) -> None:
        identity = self.bus.read(WHO_AM_I, 1)[0]
        if identity not in (0x68, 0x69):
            raise RuntimeError(f"MPU6050 WHO_AM_I mismatch: 0x{identity:02x}")
        self.bus.write(PWR_MGMT_1, 0x01)    # wake, PLL from X gyro
        time.sleep(0.05)
        self.bus.write(CONFIG, 0x03)        # DLPF ~44 Hz gyro / 42 Hz accel
        self.bus.write(GYRO_CONFIG, 0x08)   # +/-500 deg/s
        self.bus.write(ACCEL_CONFIG, 0x08)  # +/-4 g
        self.bus.write(SMPLRT_DIV, 0x09)    # 1 kHz / (1+9) = 100 Hz
        self.bus.write(INT_ENABLE, 0x00)

    def read_motion(self) -> MotionSample:
        data = self.bus.read(ACCEL_XOUT_H, 14)
        values = tuple(_s16(data[i], data[i + 1]) for i in range(0, 14, 2))
        return MotionSample(
            accel=values[0:3],
            temperature_raw=values[3],
            gyro=values[4:7],
            timestamp=time.monotonic(),
        )


class ComplementaryPoseFilter:
    """Gravity-corrected pitch/roll and gyro-integrated yaw estimator."""

    def __init__(self, alpha: float = 0.98):
        if not 0.0 <= alpha < 1.0:
            raise ValueError("alpha must be in [0, 1)")
        self.alpha = float(alpha)
        self.pose = Pose(0.0, 0.0, 0.0)
        self.gyro_bias = [0.0, 0.0, 0.0]
        self.last_timestamp: Optional[float] = None

    def calibrate(self, samples: Sequence[MotionSample]) -> None:
        if not samples:
            raise ValueError("at least one stationary sample is required")
        self.gyro_bias = [
            sum(sample.gyro[axis] for sample in samples) / len(samples)
            for axis in range(3)
        ]
        ax, ay, az = samples[-1].accel
        roll = math.degrees(math.atan2(ay, az))
        pitch = math.degrees(math.atan2(-ax, math.hypot(ay, az)))
        self.pose = Pose(0.0, pitch, roll)
        self.last_timestamp = samples[-1].timestamp

    def update(self, sample: MotionSample) -> Pose:
        if self.last_timestamp is None:
            self.calibrate((sample,))
            return self.pose
        dt = min(max(sample.timestamp - self.last_timestamp, 0.0001), 0.1)
        self.last_timestamp = sample.timestamp

        gx, gy, gz = (
            (sample.gyro[i] - self.gyro_bias[i]) / MPU6050.GYRO_LSB_PER_DPS
            for i in range(3)
        )
        ax, ay, az = sample.accel
        accel_roll = math.degrees(math.atan2(ay, az))
        accel_pitch = math.degrees(math.atan2(-ax, math.hypot(ay, az)))

        gyro_roll = self.pose.roll + gx * dt
        gyro_pitch = self.pose.pitch + gy * dt
        yaw = self.pose.yaw + gz * dt
        yaw = (yaw + 180.0) % 360.0 - 180.0
        self.pose = Pose(
            yaw=yaw,
            pitch=self.alpha * gyro_pitch + (1.0 - self.alpha) * accel_pitch,
            roll=self.alpha * gyro_roll + (1.0 - self.alpha) * accel_roll,
        )
        return self.pose


class BosioGY521Hub:
    """Connect an overlay's ``iic_0`` to a running ``BosioV2`` driver."""

    def __init__(self, bosio, rate_hz: float = 50.0, alpha: float = 0.98):
        if rate_hz <= 0:
            raise ValueError("rate_hz must be positive")
        if not hasattr(bosio.overlay, "iic_0"):
            raise RuntimeError("overlay has no iic_0; rebuild with GY-521 support")
        self.bosio = bosio
        self.imu = MPU6050(AxiIICRegisterBus(bosio.overlay.iic_0))
        self.filter = ComplementaryPoseFilter(alpha)
        self.period = 1.0 / float(rate_hz)

    def initialize(self, calibration_samples: int = 200) -> None:
        self.imu.initialize()
        samples = []
        for _ in range(calibration_samples):
            samples.append(self.imu.read_motion())
            time.sleep(0.01)
        self.filter.calibrate(samples)

    def step(self) -> Pose:
        pose = self.filter.update(self.imu.read_motion())
        # The current integration uses the output core's coefficient mailbox.
        # Keep RTL sensor mode disabled while Python is the pose producer.
        self.bosio.set_pose(pose.yaw, pose.pitch, pose.roll, wait=False)
        return pose

    def run(self, duration: Optional[float] = None) -> None:
        deadline = None if duration is None else time.monotonic() + duration
        next_tick = time.monotonic()
        while deadline is None or time.monotonic() < deadline:
            self.step()
            next_tick += self.period
            time.sleep(max(0.0, next_tick - time.monotonic()))

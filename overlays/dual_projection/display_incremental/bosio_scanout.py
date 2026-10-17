"""720p60 scanout from three completed RGB24 frames.

The two projection engines still cache/update triangular scene tiles. This DMA
is downstream of the Output Core: no CPU frame copies, no scene recomposition.
Hardware dynamic genlock publishes complete frames and repeats the latest one
when the producer stalls. VTC is a free-running timing master.
"""
from __future__ import annotations

import time


class BufferedScanout:
    WIDTH, HEIGHT, CHANNELS, STORES = 1280, 720, 3, 3
    # PG020: RS, Circular_Park, GenlockEn, internal GenlockSrc.
    RUN_GENLOCK = 0x8B
    READ_ERRORS = 0x40F0
    WRITE_ERRORS = 0xC9F0

    def __init__(self, mmio=None, health=None, allocate=None):
        if mmio is None or health is None or allocate is None:
            import pynq
            mmio = mmio if mmio is not None else pynq.MMIO(0x43000000, 0x10000)
            health = health if health is not None else pynq.MMIO(0x41210000, 0x10000)
            allocate = allocate if allocate is not None else pynq.allocate
        self.mmio, self.health, self.allocate = mmio, health, allocate
        self.buffer = None
        self.running = False
        self.stride = self.WIDTH * self.CHANNELS
        self.frame_bytes = self.stride * self.HEIGHT

    def _wait(self, condition, label, timeout=3):
        end = time.monotonic() + timeout
        while not condition():
            if time.monotonic() >= end:
                raise TimeoutError(label + '; scanout buffers retained')
            time.sleep(.001)

    def _reset(self):
        for control in (0x00, 0x30):
            self.mmio.write(control, 4)
        self._wait(lambda: not ((self.mmio.read(0) | self.mmio.read(0x30)) & 4), 'VDMA reset')
        self._wait(lambda: (self.mmio.read(4) & self.mmio.read(0x34) & 1) == 1, 'VDMA halt')
        self.running = False

    def start(self):
        if self.running:
            return
        self._reset()
        if self.buffer is None:
            self.buffer = self.allocate(shape=(self.STORES, self.HEIGHT, self.WIDTH, self.CHANNELS), dtype='uint8')
        self.buffer[:] = 0
        self.buffer.flush()
        address = int(self.buffer.physical_address)
        if address % 64 or (address + self.STORES*self.frame_bytes) > (1 << 32):
            raise ValueError('Scanout requires aligned 32-bit DDR addresses')
        # VSIZE is the final write that starts each channel. Identical address
        # tables plus dynamic master/slave genlock prevent read/write tearing.
        for control, status, params in ((0x30, 0x34, 0xA0), (0x00, 0x04, 0x50)):
            self.mmio.write(status, 0xFFFFFFFF)
            self.mmio.write(control, self.RUN_GENLOCK | (0x8000 if control == 0x30 else 0))
            for index in range(self.STORES):
                self.mmio.write(params + 12 + index*4, address + index*self.frame_bytes)
            self.mmio.write(params + 8, self.stride)
            self.mmio.write(params + 4, self.stride)
            self.mmio.write(params, self.HEIGHT)
        self.running = True

    def status(self):
        read, write = self.mmio.read(4), self.mmio.read(0x34)
        flags, frames = self.health.read(0), self.health.read(8)
        pointers = self.mmio.read(0x28)
        return dict(mode='triple-buffer-dynamic-genlock', width=self.WIDTH, height=self.HEIGHT,
                    frame_buffers=self.STORES, buffer_bytes=self.STORES*self.frame_bytes,
                    read_status=read, write_status=write,
                    read_errors=read & self.READ_ERRORS, write_errors=write & self.WRITE_ERRORS,
                    read_frame=(pointers >> 16) & 31, write_frame=(pointers >> 24) & 31,
                    video_locked=bool(flags & 1), underflow=bool(flags & 2), overflow=bool(flags & 4),
                    ever_locked=bool(flags & 8), overflow_seen=bool(flags & 16),
                    lock_losses=(flags >> 8) & 255, underflow_events=flags >> 16,
                    video_frames=frames)

    def close(self):
        # A reset must finish before releasing the memory either channel uses.
        self._reset()
        if self.buffer is not None:
            self.buffer.freebuffer()
            self.buffer = None

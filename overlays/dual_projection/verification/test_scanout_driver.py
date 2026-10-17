import sys
import unittest
from pathlib import Path
from unittest.mock import Mock
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'display_incremental'))
from bosio_scanout import BufferedScanout


class Buffer:
    physical_address = 0x10000000
    def __init__(self, shape, dtype):
        self.data = np.full(shape, 123, dtype=dtype)
        self.flushed = self.freed = False
    def __setitem__(self, key, value): self.data[key] = value
    def flush(self): self.flushed = True
    def freebuffer(self): self.freed = True


class Registers:
    def __init__(self):
        self.values = {4: 1, 0x34: 1}
        self.writes = []
    def read(self, offset): return self.values.get(offset, 0)
    def write(self, offset, value):
        self.writes.append((offset, value))
        if offset in (0, 0x30) and value == 4:
            self.values[offset] = 0
            self.values[offset+4] = 1
        elif offset in (4, 0x34):
            self.values[offset] &= ~(value & ~1)
        else:
            self.values[offset] = value


class ScanoutTests(unittest.TestCase):
    def make(self):
        reg = Registers()
        allocate = Mock(side_effect=lambda **kw: Buffer(**kw))
        obj = BufferedScanout(reg, Registers(), allocate)
        return obj, reg, allocate

    def test_complete_frame_buffers_are_shared_by_both_channels(self):
        obj, reg, alloc = self.make()
        obj.start()
        self.assertEqual(obj.buffer.data.shape, (3, 720, 1280, 3))
        self.assertFalse(np.any(obj.buffer.data))
        self.assertTrue(obj.buffer.flushed)
        for i in range(3):
            address = obj.buffer.physical_address + i*720*1280*3
            self.assertEqual(reg.read(0x5C+i*4), address)
            self.assertEqual(reg.read(0xAC+i*4), address)
        self.assertEqual(reg.read(0) & 0x8B, 0x8B)
        self.assertEqual(reg.read(0x30) & 0x8B, 0x8B)
        for base in (0x50, 0xA0):
            trigger = reg.writes.index((base, 720))
            self.assertLess(reg.writes.index((base+8, 3840)), trigger)
            self.assertLess(reg.writes.index((base+4, 3840)), trigger)
            self.assertLess(reg.writes.index((base+20, obj.buffer.physical_address+2*obj.frame_bytes)), trigger)

    def test_idle_status_neither_copies_frames_nor_writes_registers(self):
        obj, reg, alloc = self.make()
        obj.start(); writes = list(reg.writes)
        obj.status(); obj.status(); obj.start()
        self.assertEqual(reg.writes, writes)
        alloc.assert_called_once()

    def test_buffers_are_retained_if_hardware_cannot_be_quiesced(self):
        obj, reg, _ = self.make()
        obj.start(); buf = obj.buffer
        obj._wait = Mock(side_effect=TimeoutError('stuck DMA'))
        with self.assertRaises(TimeoutError): obj.close()
        self.assertIs(obj.buffer, buf)
        self.assertFalse(buf.freed)

    def test_close_resets_channels_before_releasing_memory(self):
        obj, reg, _ = self.make()
        obj.start(); buf = obj.buffer
        def release():
            self.assertEqual(reg.read(0) | reg.read(0x30), 0)
            self.assertEqual(reg.read(4) & reg.read(0x34) & 1, 1)
            buf.freed = True
        buf.freebuffer = release
        obj.close()
        self.assertTrue(buf.freed)
        self.assertIsNone(obj.buffer)

    def test_health_reports_receiver_lock_separately_from_dma_errors(self):
        obj, reg, _ = self.make()
        obj.health.values.update({0:(7<<16)|(2<<8)|9,8:3600})
        reg.values.update({4:0x20,0x34:0x800,0x28:(2<<24)|(1<<16)})
        state=obj.status()
        self.assertTrue(state['video_locked'])
        self.assertEqual(state['video_frames'],3600)
        self.assertEqual(state['underflow_events'],7)
        self.assertEqual(state['lock_losses'],2)
        self.assertEqual(state['read_errors'],0x20)
        self.assertEqual(state['write_errors'],0x800)
        self.assertEqual((state['read_frame'],state['write_frame']),(1,2))


if __name__ == '__main__': unittest.main()

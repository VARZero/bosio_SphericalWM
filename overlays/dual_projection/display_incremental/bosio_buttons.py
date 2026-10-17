#!/usr/bin/env python3
"""Linux-side access and debouncing for the four PYNQ-Z2 push buttons.

The hardware endpoint is a standard four-bit AXI GPIO at 0x41200000.  This
module has no dependency on the BOSIO compositor or window model and can be
used directly by another Linux process while the FPGA overlay is loaded.
"""

from __future__ import annotations

import argparse
import mmap
import os
import struct
import time


BUTTON_NAMES = ("BTN0", "BTN1", "BTN2", "BTN3")
DEFAULT_ADDRESS = 0x41200000
DEFAULT_RANGE = 0x10000


class PhysicalMemoryRegisters:
    """Minimal standard-library /dev/mem mapping for an AXI-Lite peripheral."""

    def __init__(self, address, length=DEFAULT_RANGE):
        page_size = mmap.PAGESIZE
        base = int(address) & ~(page_size - 1)
        self.offset = int(address) - base
        self.fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        self.mapping = mmap.mmap(self.fd, self.offset + int(length),
                                 flags=mmap.MAP_SHARED,
                                 prot=mmap.PROT_READ | mmap.PROT_WRITE,
                                 offset=base)

    def read(self, offset):
        return struct.unpack_from("<I", self.mapping, self.offset + int(offset))[0]

    def close(self):
        if self.mapping is not None:
            self.mapping.close()
            self.mapping = None
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None


class BosioButtons:
    """Read the active-high PYNQ-Z2 buttons from an AXI GPIO object or MMIO."""

    def __init__(self, registers):
        self.registers = registers

    @classmethod
    def from_address(cls, address=DEFAULT_ADDRESS, length=DEFAULT_RANGE):
        return cls(PhysicalMemoryRegisters(address, length))

    def close(self):
        close = getattr(self.registers, "close", None)
        if close is not None:
            close()

    def read_state(self):
        return int(self.registers.read(0x00)) & 0x0F

    def pressed(self, button):
        index = int(button)
        if not 0 <= index < 4:
            raise ValueError("button must be 0..3")
        return bool(self.read_state() & (1 << index))


class ButtonDebouncer:
    """Convert sampled masks into stable per-button edge events."""

    def __init__(self, initial_state=0, debounce_seconds=0.03):
        self.stable_state = int(initial_state) & 0x0F
        self.candidate_state = self.stable_state
        self.candidate_since = 0.0
        self.debounce_seconds = max(0.0, float(debounce_seconds))

    def update(self, state, now=None):
        state = int(state) & 0x0F
        now = time.monotonic() if now is None else float(now)
        if state != self.candidate_state:
            self.candidate_state = state
            self.candidate_since = now
            return []
        if state == self.stable_state or now - self.candidate_since < self.debounce_seconds:
            return []
        changed = self.stable_state ^ state
        self.stable_state = state
        return [
            {
                "button": index,
                "name": BUTTON_NAMES[index],
                "pressed": bool(state & (1 << index)),
                "state": state,
            }
            for index in range(4) if changed & (1 << index)
        ]


def main():
    parser = argparse.ArgumentParser(description="Read PYNQ-Z2 BTN0..BTN3 without the BOSIO daemon")
    parser.add_argument("--address", type=lambda value: int(value, 0), default=DEFAULT_ADDRESS)
    parser.add_argument("--once", action="store_true", help="print the current mask and exit")
    parser.add_argument("--poll-ms", type=float, default=5.0)
    parser.add_argument("--debounce-ms", type=float, default=30.0)
    args = parser.parse_args()
    buttons = BosioButtons.from_address(args.address)
    state = buttons.read_state()
    if args.once:
        print(f"0x{state:x}")
        buttons.close()
        return
    debouncer = ButtonDebouncer(state, args.debounce_ms / 1000.0)
    print(f"PYNQ-Z2 buttons ready: state=0x{state:x}", flush=True)
    try:
        while True:
            for event in debouncer.update(buttons.read_state()):
                action = "pressed" if event["pressed"] else "released"
                print(f'{event["name"]} {action} state=0x{event["state"]:x}', flush=True)
            time.sleep(max(0.001, args.poll_ms / 1000.0))
    except KeyboardInterrupt:
        pass
    finally:
        buttons.close()


if __name__ == "__main__":
    main()

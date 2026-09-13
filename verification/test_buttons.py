import unittest

from sw.bosio_buttons import BosioButtons, ButtonDebouncer


class FakeRegisters:
    def __init__(self, value=0):
        self.value = value

    def read(self, offset):
        self.last_offset = offset
        return self.value


class ButtonTests(unittest.TestCase):
    def test_axi_gpio_mask_and_pressed(self):
        registers = FakeRegisters(0xF5)
        buttons = BosioButtons(registers)
        self.assertEqual(buttons.read_state(), 5)
        self.assertTrue(buttons.pressed(0))
        self.assertFalse(buttons.pressed(1))
        self.assertTrue(buttons.pressed(2))
        self.assertEqual(registers.last_offset, 0)

    def test_debounce_press_and_release(self):
        debouncer = ButtonDebouncer(0, 0.03)
        self.assertEqual(debouncer.update(1, 1.00), [])
        self.assertEqual(debouncer.update(0, 1.01), [])
        self.assertEqual(debouncer.update(1, 1.02), [])
        events = debouncer.update(1, 1.051)
        self.assertEqual(events, [{"button": 0, "name": "BTN0", "pressed": True, "state": 1}])
        self.assertEqual(debouncer.update(0, 2.00), [])
        events = debouncer.update(0, 2.031)
        self.assertFalse(events[0]["pressed"])

    def test_simultaneous_edges(self):
        debouncer = ButtonDebouncer(0, 0)
        debouncer.update(0b1010, 1.0)
        events = debouncer.update(0b1010, 1.0)
        self.assertEqual([event["button"] for event in events], [1, 3])


if __name__ == "__main__":
    unittest.main()

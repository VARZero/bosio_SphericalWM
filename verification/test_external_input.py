import unittest

from sw.bosio_wm_daemon import BosioWindowDaemon


class ExternalInputTests(unittest.TestCase):
    def setUp(self):
        self.daemon = BosioWindowDaemon("/tmp/bosio-input-test.sock", m=8, headless=True)

    @staticmethod
    def request(source, op, **args):
        return {"app": source, "op": op, "args": args}

    def test_absolute_relative_and_click(self):
        source = "input:camera:1"
        state = self.daemon.dispatch(self.request(
            source, "input_warp", azimuth=179, elevation=10))
        self.assertEqual((state["azimuth"], state["elevation"]), (179.0, 10.0))
        state = self.daemon.dispatch(self.request(
            source, "input_move", delta_azimuth=4, delta_elevation=-2))
        self.assertEqual((state["azimuth"], state["elevation"]), (-177.0, 8.0))
        state = self.daemon.dispatch(self.request(source, "input_click", button="left"))
        self.assertNotIn("left", state["buttons"])
        self.assertEqual(state["left_press_serial"], 1)

    def test_source_buttons_merge_and_disconnect_release(self):
        first, second = "input:gaze:1", "input:gesture:2"
        self.daemon.dispatch(self.request(first, "input_button", button="left", pressed=True))
        self.daemon.dispatch(self.request(second, "input_button", button="left", pressed=True))
        self.daemon.dispatch(self.request(first, "input_button", button="left", pressed=False))
        self.assertIn("left", self.daemon.manager.pointer_buttons)
        self.daemon.release_input_source(second)
        self.assertNotIn("left", self.daemon.manager.pointer_buttons)

    def test_source_status_and_validation(self):
        source = "input:camera:1"
        self.daemon.dispatch(self.request(source, "input_button", button="right", pressed=True))
        state = self.daemon.dispatch(self.request(source, "input_status"))
        self.assertEqual(state["source_buttons"], ["right"])
        self.assertEqual(state["active_button_source_count"], 1)
        with self.assertRaisesRegex(Exception, "left, middle, or right"):
            self.daemon.dispatch(self.request(source, "input_button", button="touch", pressed=True))


if __name__ == "__main__":
    unittest.main()

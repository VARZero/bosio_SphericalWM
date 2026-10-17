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

    def test_workspace_actions_capture_and_cancel_dispatch(self):
        app = self.daemon.dispatch(self.request("app", "create_window", title="APP",
            workspace={"role": "app", "state": "open"}, decorated=False))
        self.assertIn("spatial-workspace", self.daemon.dispatch(self.request("app", "ping"))["features"])
        self.daemon.dispatch(self.request("desktop", "request_window_action",
            window_id=app["window_id"], action="restore", azimuth=179, elevation=5))
        event = [e for e in self.daemon.dispatch(self.request("app", "poll_events"))
                 if e["type"] == "window_action"][0]
        self.assertEqual((event["action"], event["azimuth"], event["elevation"]), ("restore", 179, 5))
        self.daemon.dispatch(self.request("input", "input_warp", azimuth=0, elevation=0))
        self.daemon.dispatch(self.request("input", "input_button", button="left", pressed=True))
        self.assertTrue(self.daemon.dispatch(self.request("app", "capture_pointer", window_id=app["window_id"])))
        self.daemon.dispatch(self.request("input", "input_key", key="escape"))
        self.assertFalse(self.daemon.input_buttons)
        self.assertIsNone(self.daemon.manager._capture)


if __name__ == "__main__":
    unittest.main()

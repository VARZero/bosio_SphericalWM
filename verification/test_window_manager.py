import base64
import unittest

import numpy as np

from sw.bosio_window_manager import SphericalWindowManager, WindowManagerError


class WindowManagerTests(unittest.TestCase):
    def setUp(self):
        self.wm = SphericalWindowManager(8)

    def test_overlap_focus_and_z_order(self):
        first = self.wm.create_window("a", "FIRST", 0, 0)
        second = self.wm.create_window("b", "SECOND", 0, 0)
        hit = self.wm.hit_test(0, 0)
        self.assertEqual(hit[0].window_id, second["window_id"])
        self.wm.focus_window(first["window_id"])
        self.assertEqual(self.wm.hit_test(0, 0)[0].window_id, first["window_id"])
        self.assertEqual(self.wm.focused_window, first["window_id"])

    def test_pointer_wrap_focus_and_drag(self):
        window = self.wm.create_window("a", "DRAG", 179, 0, 30, 20)
        self.wm.pointer_warp(179, 8)
        self.wm.pointer_button("left", True)
        self.wm.pointer_move(4, 3)
        self.wm.pointer_button("left", False)
        self.assertAlmostEqual(self.wm.windows[window["window_id"]].azimuth, -177)
        self.assertAlmostEqual(self.wm.windows[window["window_id"]].elevation, 3)
        self.assertEqual(self.wm.pointer_azimuth, -177)

    def test_surface_update_and_ownership(self):
        window = self.wm.create_window("a", "PIXELS", 0, 0, surface_width=2, surface_height=2)
        pixels = np.arange(12, dtype=np.uint8).reshape(2, 2, 3)
        self.wm.update_surface("a", window["window_id"], 0, 0, 2, 2,
                               base64.b64encode(pixels.tobytes()).decode())
        np.testing.assert_array_equal(self.wm.windows[window["window_id"]].surface, pixels)
        self.assertEqual(self.wm.windows[window["window_id"]].dirty_rect, (0, 0, 2, 2))
        with self.assertRaises(WindowManagerError):
            self.wm.fill("b", window["window_id"], [0, 0, 0])

    def test_dirty_rect_union(self):
        window = self.wm.create_window("a", "DIRTY", surface_width=32, surface_height=24)
        model = self.wm.windows[window["window_id"]]
        model.dirty_rect = None
        a = np.zeros((3, 4, 3), dtype=np.uint8)
        b = np.zeros((2, 5, 3), dtype=np.uint8)
        self.wm.update_surface("a", window["window_id"], 2, 4, 4, 3,
                               base64.b64encode(a.tobytes()).decode())
        self.wm.update_surface("a", window["window_id"], 10, 1, 5, 2,
                               base64.b64encode(b.tobytes()).decode())
        self.assertEqual(model.dirty_rect, (2, 1, 13, 6))

    def test_compositor_and_events(self):
        window = self.wm.create_window("a", "EVENT", 0, 0, 40, 30, 8, 8)
        self.wm.fill("a", window["window_id"], [255, 0, 0])
        self.wm.pointer_warp(0, 0)
        self.wm.pointer_button("left", True)
        self.wm.pointer_button("left", False)
        events = self.wm.poll_events("a")
        self.assertTrue(any(event["type"] == "pointer_button" for event in events))
        scene = self.wm.render()
        self.assertEqual(scene.shape, (20, 211, 64, 3))
        self.assertTrue(np.any(scene[..., 0] > scene[..., 1]))

    def test_disconnect_cleanup_model(self):
        self.wm.create_window("a", "ONE")
        self.wm.create_window("a", "TWO")
        self.wm.create_window("b", "THREE")
        self.assertEqual(self.wm.destroy_owner_windows("a"), 2)
        self.assertEqual(len(self.wm.windows), 1)


if __name__ == "__main__":
    unittest.main()

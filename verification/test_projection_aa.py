"""A thin source stroke must survive the M16 spherical cell footprint."""
import base64
import unittest

import numpy as np

from sw.bosio_window_manager import SphericalWindowManager


class ProjectionAATests(unittest.TestCase):
    def _scene(self, aa):
        wm = SphericalWindowManager(16, background=(0, 0, 0), projection_aa=aa)
        created = wm.create_window("aa-test", "STROKE", width_deg=42, height_deg=30,
                                   surface_width=320, surface_height=200)
        surface = np.full((200, 320, 3), 255, dtype=np.uint8)
        surface[:, 159:161] = 0
        surface[99:101, :] = 0
        wm.update_surface("aa-test", created["window_id"], 0, 0, 320, 200,
                          base64.b64encode(surface.tobytes()).decode("ascii"))
        return wm.render(), wm

    def test_area_sampling_makes_thin_strokes_visible(self):
        aliased, aliased_wm = self._scene(False)
        filtered, filtered_wm = self._scene(True)
        self.assertEqual(aliased_wm.native is not None, filtered_wm.native is not None)
        mid = (filtered[..., 0] > 15) & (filtered[..., 0] < 240)
        self.assertGreater(np.count_nonzero(mid), 0)
        self.assertGreater(np.count_nonzero(mid), np.count_nonzero(
            (aliased[..., 0] > 15) & (aliased[..., 0] < 240)))
        self.assertTrue(np.any(filtered[..., 0] < aliased[..., 0]))

    def test_aa_gray_palette_has_no_color_fringe(self):
        _, wm = self._scene(True)
        words, _ = wm.render_packed()
        for level in range(8):
            gray = level * 255 // 7
            index = (level << 5) | (level << 2) | (gray >> 6)
            word = int(words[index])
            self.assertEqual(((word >> 16) & 255, word & 255, (word >> 8) & 255),
                             (gray, gray, gray))

    def test_numpy_reference_stays_close_to_native(self):
        scene, wm = self._scene(True)
        if wm.native is None:
            self.skipTest("native compositor is unavailable")
        wm.native.close()
        wm.native = None
        reference = wm.render()
        visible = np.any(scene != 0, axis=-1) | np.any(reference != 0, axis=-1)
        difference = np.abs(scene.astype(np.int16) - reference.astype(np.int16))
        self.assertLess(float(np.mean(difference[visible])), 8.)

    def test_dirty_update_reaches_aa_neighbor_cells(self):
        scene, wm = self._scene(True)
        if wm.native is None:
            self.skipTest("native BPT1 path requires a built compositor")
        wm.render_update()  # Establish an immutable snapshot first.
        window = next(iter(wm.windows.values()))
        patch = np.full((200, 2, 3), 255, dtype=np.uint8)
        wm.update_surface("aa-test", window.window_id, 159, 0, 2, 200,
                          base64.b64encode(patch.tobytes()).decode("ascii"))
        words, tiles, kind = wm.render_update()
        self.assertEqual(kind, "patch")
        self.assertGreater(tiles, 0)
        self.assertEqual(int(words[0]), 0x42505431)
        changed = scene.reshape(-1, 3)[:, 0] != wm.render().reshape(-1, 3)[:, 0]
        _, x, _ = wm._project(window, wm._flat_rays)
        center_x = (x + 1) * .5 * (window.surface_width - 1)
        self.assertTrue(np.any(changed & ((center_x < 158) | (center_x > 162))))


if __name__ == "__main__":
    unittest.main()

import base64
import unittest

import numpy as np

from sw.bosio_wm_daemon import BosioWindowDaemon


class SceneStreamTests(unittest.TestCase):
    def setUp(self):
        self.daemon = BosioWindowDaemon("/tmp/bosio-scene-test.sock", m=8, headless=True)

    @staticmethod
    def request(app, op, **args):
        return {"app": app, "op": op, "args": args}

    def test_scene_ownership_and_upload(self):
        claim = self.daemon.dispatch(self.request("boayo", "claim_scene"))
        self.assertEqual(claim["m"], 8)
        with self.assertRaisesRegex(Exception, "owned by another"):
            self.daemon.dispatch(self.request("other", "claim_scene"))
        words = np.zeros(4480, dtype="<u4")
        words[256:256 + 20 * 211] = 0xffffffff  # No active tiles.
        payload = base64.b64encode(words.tobytes()).decode("ascii")
        result = self.daemon.dispatch(self.request("boayo", "upload_scene_words", words32=payload))
        self.assertEqual(result["words"], len(words))
        self.daemon.dispatch(self.request("boayo", "release_scene"))
        self.assertIsNone(self.daemon.scene_owner)


if __name__ == "__main__":
    unittest.main()

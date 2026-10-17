import sys
import unittest
import threading
from pathlib import Path
from unittest.mock import Mock

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'display_incremental'),str(ROOT.parents[1]/'sw')]
from bosio_mouse_input import inverse_display_motion

class DisplayInputTests(unittest.TestCase):
    def test_inverse_restores_screen_motion_for_all_transforms(self):
        for rotation in (0,90,180,270):
            for flip_x in (False,True):
                for flip_y in (False,True):
                    # A logical delta rotates clockwise on a y-down screen.
                    x,y=7,-3
                    for _ in range(rotation//90):x,y=-y,x
                    if flip_x:x=-x
                    if flip_y:y=-y
                    self.assertEqual(inverse_display_motion(x,y,dict(active_rotation=rotation,
                        active_flip_x=flip_x,active_flip_y=flip_y)),(7,-3))
    def test_client_exposes_output_settings_without_modifying_windows(self):
        from bosio_wm_client import BosioWMClient
        client=BosioWMClient.__new__(BosioWMClient);client.call=Mock(return_value={'pending':False})
        self.assertEqual(client.set_display_transform(90,True,False),{'pending':False})
        client.call.assert_called_once_with('set_display_transform',rotation=90,flip_x=True,flip_y=False)
        client.file=None

    def test_daemon_changes_only_output_and_keeps_spherical_gaze_untouched(self):
        from bosio_wm_daemon import BosioWindowDaemon
        daemon=BosioWindowDaemon.__new__(BosioWindowDaemon)
        daemon.driver=Mock();daemon.manager=Mock();daemon.driver_lock=threading.RLock()
        daemon.driver.set_display_transform.return_value={'pending':False}
        result=daemon.dispatch({'op':'set_display_transform','args':{'rotation':90,'flip_x':True}})
        self.assertEqual(result,{'pending':False})
        self.assertEqual(daemon.manager.method_calls,[])
        daemon.driver.get_display_transform.return_value={'active_rotation':90,'active_flip_x':True}
        daemon.dispatch({'op':'input_display_move','args':{'dx':4,'dy':6}})
        daemon.manager.pointer_move.assert_called_once_with(6.,-4.)

if __name__=='__main__':unittest.main()

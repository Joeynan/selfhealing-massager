import sys, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bridge import IntentEngine
from server import Dashboard
import launch

def camera(gesture='pinch',**kw):
    return dict(ready=True,frame_id=10,capture_monotonic_ms=10000,
                frame_age_ms=50,received_monotonic_ms=10000,gesture=gesture,
                transport='wifi',camera_session_id='123',camera_frame_id=7,**kw)

class WiFiBridgeTests(unittest.TestCase):
    def test_forward_proof_and_charge_age_at_send(self):
        e=IntentEngine();e.set_source('camera')
        c=e.step(camera(),10.1)
        self.assertEqual(c['camera_session_id'],'123')
        self.assertEqual(c['camera_frame_id'],7)
        self.assertEqual(c['frame_age_ms'],150)
        self.assertEqual(c['lease_ms'],450)

    def test_wifi_missing_proof_stops_instead_of_forwarding(self):
        e=IntentEngine();e.set_source('camera');c=camera();c.pop('camera_session_id')
        self.assertEqual(e.step(c,10)['gesture'],'stop')

    def test_valid_no_hand_stop_has_proof_and_does_not_disarm(self):
        d=Dashboard('http://fake','http://local');d.diagnostic_active=True
        d.camera={'online':True,'data':camera('stop')}
        with patch('server.fetch',return_value={'ok':True}) as f:
            d.forward_inputs(10)
        self.assertEqual(f.call_args.args[0],'http://fake/gesture')
        self.assertEqual(f.call_args.args[1]['camera_frame_id'],7)

    def test_camera_loss_uses_explicit_disarming_stop(self):
        d=Dashboard('http://fake','http://local');d.diagnostic_active=True
        with patch('server.fetch',return_value={'ok':True}) as f:d.forward_inputs(10)
        self.assertEqual(f.call_args.args[0],'http://fake/stop')

    def test_loss_after_valid_no_hand_stop_still_disarms(self):
        d=Dashboard('http://fake','http://local');d.diagnostic_active=True
        d.camera={'online':True,'data':camera('stop')}
        with patch('server.fetch',return_value={'ok':True}) as f:
            d.forward_inputs(10)
            d.camera={'online':False,'data':{}}
            d.forward_inputs(10.1)
            self.assertEqual(f.call_args.args[0],'http://fake/stop')

    def test_wifi_launch_is_explicit_and_cannot_reuse_usb_reader(self):
        o=launch.parse_options(['--wifi-camera'])
        self.assertTrue(o.wifi_camera);self.assertFalse(o.mac_camera)
        with self.assertRaises(ValueError):
            launch.validate_camera_service({'transport':'usb'},'wifi','http://host:8081/frame','watcher-test')
        launch.validate_camera_service({'transport':'wifi','camera_url':'http://host:8081/frame',
                                       'watcher_id':'watcher-test','observation_version':2,'recognition_instance_id':'service-a'},'wifi','http://host:8081/frame','watcher-test')

if __name__=='__main__':unittest.main()

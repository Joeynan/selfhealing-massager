import sys,unittest,tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import Dashboard

class V6DashboardTests(unittest.TestCase):
    def test_default_run_is_2000(self):
        self.assertEqual(Dashboard('http://unused','http://unused').servo['profile']['run_us'],[2000]*3)

    def test_saved_profile_accepts_2000(self):
        d=Dashboard('http://unused','http://unused');d.engine.set_source('simulation');d.diagnostic_active=True
        with tempfile.TemporaryDirectory() as folder, patch('server.ROOT',Path(folder)), patch('server.fetch',return_value={'ok':True}):
            result=d.action('/api/servo/profile',{'neutral_us':[1500]*3,'run_us':[2000]*3})
        self.assertTrue(result['ok'])

    def test_observer_does_not_forward_activity_or_commands(self):
        d=Dashboard('http://unused','http://unused')
        d.diagnostic_active=False  # Explicit observer fixture; current default is camera control.
        d.camera={'online':True,'data':{'capture_frame_id':3,'capture_age_ms':1}}
        with patch('server.fetch') as send:
            d.forward_inputs(10)
        send.assert_not_called()

    def test_observer_rejects_remote_arm(self):
        d=Dashboard('http://unused','http://unused')
        d.diagnostic_active=False  # Explicit observer fixture; current default is camera control.
        with patch('server.fetch') as send, self.assertRaises(ValueError):
            d.action('/api/servo/arm',{'enabled':True,'power_confirmed':True})
        send.assert_not_called()

    def test_onboard_snapshot_uses_device_recognition(self):
        d=Dashboard('http://unused','http://unused')
        d.diagnostic_active=False  # Explicit observer fixture; current default is camera control.
        d.watcher={'online':True,'error':'','data':{'input_source':'onboard','standalone_ready':True,'gesture':'pinch','recognition_location':'watcher'}}
        import time
        d.observed['watcher']=time.monotonic()
        s=d.snapshot()
        self.assertEqual(s['source'],'onboard')
        self.assertEqual(s['requested_gesture'],'pinch')
        self.assertTrue(s['standalone_ready'])
        self.assertTrue(s['observer_only'])

    def test_onboard_camera_never_uses_old_mac_landmarks(self):
        import time
        d=Dashboard('http://watcher','http://camera')
        d.diagnostic_active=False  # Explicit observer fixture; current default is camera control.
        d.observed['watcher']=time.monotonic()
        d.watcher={'online':True,'error':'','data':{'input_source':'onboard','camera_active':True,'camera_age_ms':20,'frame_id':6,'hands':[{'id':1}],'raw_gesture':'kneading','inference_fps':4.2}}
        d.camera={'online':True,'data':{'hands':[{'id':99}]}}
        s=d.snapshot()['camera']
        self.assertEqual(s['data']['hands'],[{'id':1}])
        self.assertEqual(s['data']['transport'],'sscma_spi')
        self.assertFalse(s['data']['image_available'])

    def test_onboard_calibration_goes_to_watcher(self):
        d=Dashboard('http://watcher','http://camera')
        d.watcher={'online':True,'data':{'input_source':'onboard'}}
        with patch('server.fetch',return_value={'ok':True}) as send:
            d.action('/api/calibrate',{})
        send.assert_called_once_with('http://watcher/onboard/calibrate',{},timeout=2)

    def test_short_test_does_not_disarm_before_test(self):
        d=Dashboard('http://watcher','http://camera');d.diagnostic_active=True;d.engine.set_source('simulation')
        d.watcher={'online':True,'data':{'outputs_enabled':True,'profile_match':True}}
        with patch('server.fetch',return_value={'ok':True}) as send:
            d.action('/api/servo/test',{'channel':2,'pulse_us':2000,'duration_ms':500})
        self.assertEqual([c.args[0] for c in send.call_args_list],['http://watcher/servo/test'])

    def test_calibration_unknown_source_never_uses_mac(self):
        d=Dashboard('http://watcher','http://camera')
        with patch('server.fetch') as send,self.assertRaises(ValueError):
            d.action('/api/calibrate',{})
        send.assert_not_called()

    def test_offline_observer_never_shows_mac_image(self):
        d=Dashboard('http://watcher','http://camera')
        d.diagnostic_active=False  # Explicit observer fixture; current default is camera control.
        d.camera={'online':True,'data':{'hands':[{'id':99}]}}
        s=d.snapshot()['camera']
        self.assertFalse(s['online'])
        self.assertEqual(s['data']['hands'],[])
        self.assertFalse(s['data']['image_available'])

if __name__=='__main__':unittest.main()

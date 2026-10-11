import unittest,sys
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server import Dashboard
class DashboardTests(unittest.TestCase):
 def test_v4_has_disarmed_servo_state(self):
  self.assertEqual(Dashboard('http://unused','http://unused').snapshot().get('api_version'),2)
 def test_observation_rejects_unknown_test(self):
  d=Dashboard('http://unused','http://unused')
  with self.assertRaises(ValueError):d.action('/api/servo/observation',{'test_id':'unknown','result':'moving'})
 def test_short_test_rejects_camera_source(self):
  d=Dashboard('http://unused','http://unused');d.engine.set_source('camera')
  with self.assertRaises(ValueError):d.action('/api/servo/test',{'channel':1,'pulse_us':1650,'duration_ms':500})
 def test_default_camera_cannot_arm_before_devices_are_ready(self):
  d=Dashboard('http://unused','http://unused')
  with self.assertRaisesRegex(ValueError,'两板在线'):d.action('/api/servo/arm',{'enabled':True})
class CameraRoutingTests(unittest.TestCase):
 def test_new_camera_session_resumes_green_light_after_clock_reset(self):
  d=Dashboard('http://unused','http://unused')
  c={'capture_frame_id':100,'capture_age_ms':20,'capture_monotonic_ms_latest':558000,
     'received_monotonic_ms':10000,'capture_session_id':'old'}
  d.camera={'online':True,'data':c}; d.observed['camera']=10
  first=d.activity(10)
  d.camera['data']=dict(c,capture_frame_id=1,capture_monotonic_ms_latest=100,
    received_monotonic_ms=10100,capture_session_id='new')
  second=d.activity(10.1)
  self.assertIsNotNone(second)
  self.assertNotEqual(first['session_id'],second['session_id'])
  self.assertIsNone(d.activity(10.2))
 def test_lock_wait_cannot_rejuvenate_camera_light_lease(self):
  d=Dashboard('http://unused','http://unused')
  d.camera={'online':True,'data':{'capture_frame_id':1,'capture_age_ms':20,
   'capture_monotonic_ms_latest':980,'server_monotonic_ms':1000,'received_monotonic_ms':10000}}
  d.observed['camera']=10.6
  self.assertIsNone(d.activity(10.7))
 def test_camera_heartbeat_uses_reported_age_across_clock_epochs(self):
  d=Dashboard('http://unused','http://unused')
  d.camera={'online':True,'data':{'capture_frame_id':1,'capture_age_ms':20,
   'capture_monotonic_ms_latest':980,'server_monotonic_ms':1000}}
  d.observed['camera']=1000
  heartbeat=d.activity(1000)
  self.assertIsNotNone(heartbeat)
  self.assertEqual(heartbeat['frame_age_ms'],20)
  self.assertIsNone(d.activity(1000.1))
 def test_startup_previews_camera_with_outputs_disabled(self):
  d=Dashboard('http://unused','http://unused')
  self.assertEqual(d.engine.source,'camera')
  self.assertFalse(d.snapshot()['servo']['armed'])
 def test_camera_diagnostic_cannot_remote_arm(self):
  d=Dashboard('http://unused','http://unused');d.engine.set_source('camera');d.diagnostic_active=True
  with patch('server.fetch',return_value={'ok':True}) as send,self.assertRaises(ValueError):
   d.action('/api/servo/arm',{'enabled':True,'power_confirmed':True})
  send.assert_not_called()
  self.assertEqual(d.engine.source,'camera')
if __name__=='__main__':unittest.main()

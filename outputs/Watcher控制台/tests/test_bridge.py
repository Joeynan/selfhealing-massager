import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bridge import IntentEngine
class IntentTests(unittest.TestCase):
 def test_simulate_preserves_mode_and_expires(self):
  e=IntentEngine();e.simulate('kneading',2000,10)
  self.assertEqual(e.step(None,10)['gesture'],'kneading')
  self.assertEqual(e.step(None,11.9)['gesture'],'kneading')
  self.assertEqual(e.step(None,12)['gesture'],'stop')
 def test_stop_changes_source_and_prevents_restart(self):
  e=IntentEngine();e.set_source('camera');e.stop()
  self.assertEqual(e.source,'simulation');self.assertEqual(e.gesture,'stop')
 def test_camera_repeated_frame_does_not_renew(self):
  e=IntentEngine();e.set_source('camera')
  c={'ready':True,'frame_id':10,'capture_monotonic_ms':10000,'frame_age_ms':50,'gesture':'pounding'}
  self.assertEqual(e.step(c,10)['gesture'],'pounding')
  self.assertIsNone(e.step(c,10.3))
  self.assertEqual(e.step(c,10.7)['gesture'],'stop')
 def test_camera_restart_new_capture_can_resume(self):
  e=IntentEngine();e.set_source('camera')
  self.assertEqual(e.step({'ready':True,'frame_id':55,'capture_monotonic_ms':1000,'frame_age_ms':20,'gesture':'pinch'},1)['gesture'],'pinch')
  self.assertEqual(e.step({'ready':True,'frame_id':1,'capture_monotonic_ms':2000,'frame_age_ms':20,'gesture':'kneading'},2)['gesture'],'kneading')
 def test_camera_old_frame_or_lost_camera_stops(self):
  e=IntentEngine();e.set_source('camera')
  e.step({'ready':True,'frame_id':1,'capture_monotonic_ms':1000,'frame_age_ms':20,'gesture':'pinch'},1)
  self.assertEqual(e.step({'ready':True,'frame_id':2,'capture_monotonic_ms':1050,'frame_age_ms':900,'gesture':'pinch'},1.1)['gesture'],'stop')
  self.assertIsNone(e.step(None,1.2))
 def test_cached_age_cannot_revive_old_capture(self):
  e=IntentEngine();e.set_source('camera')
  self.assertEqual(e.step({'ready':True,'frame_id':1,'capture_monotonic_ms':10000,'frame_age_ms':20,'gesture':'pinch'},12)['gesture'],'stop')
 def test_invalid_gesture_and_duration_rejected(self):
  e=IntentEngine()
  for label,duration in [('invalid',2000),('pinch',0),('pinch',True)]:
   with self.assertRaises(ValueError):e.simulate(label,duration,0)
  with self.assertRaises(ValueError):e.set_source('invalid')
if __name__=='__main__':unittest.main()

class V4LeaseTests(unittest.TestCase):
 def test_new_camera_session_can_reset_remote_capture_clock(self):
  e=IntentEngine();e.set_source('camera')
  c={'ready':True,'frame_id':1,'capture_monotonic_ms':558080265,'frame_age_ms':20,
     'received_monotonic_ms':10000,'gesture':'pinch','capture_session_id':'old'}
  self.assertEqual(e.step(c,10)['gesture'],'pinch')
  new=dict(c,capture_monotonic_ms=100,received_monotonic_ms=10100,capture_session_id='new',gesture='pounding')
  self.assertEqual(e.step(new,10.1)['gesture'],'pounding')
  self.assertIsNone(e.step(new,10.2))
 def test_camera_clock_epoch_does_not_block_fresh_hand_gesture(self):
  e=IntentEngine();e.set_source('camera')
  c={'ready':True,'frame_id':1,'capture_monotonic_ms':558080265,'frame_age_ms':50,
     'received_monotonic_ms':10000,'gesture':'pinch'}
  self.assertEqual(e.step(c,10)['gesture'],'pinch')
  self.assertEqual(e.step(c,10.1),None)
  self.assertEqual(e.step(c,10.7)['gesture'],'stop')
 def test_received_clock_cannot_make_cached_result_fresh(self):
  e=IntentEngine();e.set_source('camera')
  c={'ready':True,'frame_id':1,'capture_monotonic_ms':558080265,'frame_age_ms':20,
     'received_monotonic_ms':10000,'gesture':'pinch'}
  self.assertEqual(e.step(c,12)['gesture'],'stop')
 def test_old_camera_frame_has_transport_reserve(self):
  e=IntentEngine();e.set_source('camera')
  c={'ready':True,'frame_id':1,'capture_monotonic_ms':10000,'frame_age_ms':650,'gesture':'pinch'}
  self.assertEqual(e.step(c,10.65)['gesture'],'stop')
 def test_simulation_does_not_renew_beyond_duration(self):
  e=IntentEngine();e.simulate('pinch',200,1)
  self.assertEqual(e.step(None,1)['lease_ms'],200)

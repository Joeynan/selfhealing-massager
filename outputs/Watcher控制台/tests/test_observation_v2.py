import math
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'camera'))
from gesture_rules import Config, GestureEngine
from runtime_state import FramePipeline
from test_gesture_rules import hand


def static_curl(**kw):
    h=hand('fist',**kw)
    scale=kw.get('scale',90);rotation=kw.get('rotation',0);mirror=kw.get('mirror',False)
    x,y=-1.6,-1.4
    if mirror:x=-x
    c,s=math.cos(rotation),math.sin(rotation)
    h['landmarks'][4]=[(320+scale*(c*x-s*y))/640,(330+scale*(s*x+c*y))/480,0]
    return h


class ObservationV2Tests(unittest.TestCase):
    def setUp(self):
        self.engine=GestureEngine(Config(back_sign_by_hand={'Left':1,'Right':-1}))

    def feed(self,h,times=(100,250,450)):
        for n,t in enumerate(times,1):self.engine.process(n,t,[h],t)
        return self.engine.snapshot(times[-1])

    def test_static_curl_thumb_extended_confirms_without_back_calibration(self):
        self.engine=GestureEngine(Config())
        s=self.feed(static_curl())
        self.assertEqual(s['gesture'],'kneading')
        self.assertEqual(s.get('observation_state'),'confirmed')
        self.assertTrue(s.get('confirmed_this_frame'))
        self.assertEqual(s.get('observation_gesture'),'kneading')
        self.assertEqual(s.get('knead_kind'),'static_curl')

    def test_static_curl_requires_300ms_and_three_distinct_frames(self):
        h=static_curl()
        for n,t in ((1,100),(1,300),(2,450)):self.engine.process(n,t,[h],t)
        s=self.engine.snapshot(450)
        self.assertEqual(s.get('observation_state'),'confirming')
        self.assertFalse(s.get('confirmed_this_frame'))
        self.engine.process(3,500,[h],500)
        self.assertEqual(self.engine.snapshot(500).get('observation_gesture'),'kneading')

    def test_static_curl_is_scale_rotation_and_hand_invariant(self):
        for side,mirror,rotation,scale in [('Left',False,-.7,50),('Right',True,.7,110)]:
            self.engine=GestureEngine(Config())
            self.assertEqual(self.feed(static_curl(side=side,mirror=mirror,rotation=rotation,scale=scale))['gesture'],'kneading')

    def test_historical_cycle_does_not_emit_on_closed_or_open_hold(self):
        for n,(t,k) in enumerate([(100,'closed'),(400,'open'),(800,'closed')],1):
            self.engine.process(n,t,[hand(k)],t)
        self.assertTrue(self.engine.snapshot(800).get('confirmed_this_frame'))
        self.assertEqual(self.engine.snapshot(800).get('knead_kind'),'cycle')
        self.engine.process(4,1000,[hand('closed')],1000)
        s=self.engine.snapshot(1000)
        self.assertFalse(s.get('confirmed_this_frame'))
        self.assertEqual(s.get('observation_gesture'),'stop')
        self.assertEqual(s['raw_gesture'],'stop')
        self.engine.process(5,1200,[hand('open')],1200)
        self.assertFalse(self.engine.snapshot(1200).get('confirmed_this_frame'))

    def test_new_target_is_not_blocked_by_previous_cycle(self):
        for n,(t,k) in enumerate([(100,'closed'),(400,'open'),(800,'closed'),(950,'pinch'),(1100,'pinch'),(1300,'pinch')],1):
            self.engine.process(n,t,[hand(k)],t)
        s=self.engine.snapshot(1300)
        self.assertEqual(s.get('observation_gesture'),'pinch')
        self.assertTrue(s.get('confirmed_this_frame'))

    def test_no_hand_has_no_confirmation_during_compatibility_grace(self):
        self.feed(hand('pinch'));self.engine.process(4,600,[],600)
        s=self.engine.snapshot(600)
        self.assertEqual(s['gesture'],'pinch')
        self.assertEqual(s.get('observation_state'),'no_hand')
        self.assertFalse(s.get('hand_present'))
        self.assertFalse(s.get('confirmed_this_frame'))
        self.assertEqual(s.get('observation_gesture'),'stop')

    def test_unrecognized_valid_hand_is_distinct_from_error(self):
        s=self.feed(hand('open'))
        self.assertEqual(s.get('observation_state'),'unrecognized')
        self.assertTrue(s.get('hand_present'))
        self.engine.process(4,600,[{'id':'bad','landmarks':[[0,0,0]]*20}],600)
        s=self.engine.snapshot(600)
        self.assertEqual(s.get('observation_state'),'error')
        self.assertFalse(s.get('hand_present'))

    def test_conflict_is_explicit_and_cannot_confirm(self):
        self.feed(hand('pinch'))
        self.engine.process(4,600,[hand('pinch'),static_curl(identity='b')],600)
        s=self.engine.snapshot(600)
        self.assertEqual(s.get('observation_state'),'conflict')
        self.assertTrue(s.get('hand_present'))
        self.assertFalse(s.get('confirmed_this_frame'))

    def test_observation_event_expires_at_800ms(self):
        self.feed(hand('pinch'));s=self.engine.snapshot(1250)
        self.assertEqual(s.get('observation_version'),2)
        self.assertEqual(s.get('observation_state'),'error')
        self.assertFalse(s.get('confirmed_this_frame'))
        self.assertEqual(s.get('observation_gesture'),'stop')

    def test_thumb_deadband_does_not_create_both_static_targets(self):
        h=hand('fist');h['landmarks'][4]=[(320-1.5*90)/640,(330-.9*90)/480,0]
        self.assertEqual(self.feed(h)['gesture'],'stop')

    def test_static_thumb_hysteresis_maintains_disjoint_targets(self):
        self.feed(hand('fist'))
        h=hand('fist');h['landmarks'][4]=[(320-1.43*90)/640,(330-.9*90)/480,0]
        self.engine.process(4,600,[h],600)
        self.assertEqual(self.engine.snapshot(600).get('observation_gesture'),'pounding')
        self.engine=GestureEngine(Config());self.feed(static_curl())
        h=static_curl();h['landmarks'][4]=[(320-1.52*90)/640,(330-.9*90)/480,0]
        self.engine.process(4,600,[h],600)
        self.assertEqual(self.engine.snapshot(600).get('observation_gesture'),'kneading')

    def test_static_confirmation_uses_a_recent_per_hand_window(self):
        self.feed(hand('pinch'))
        self.assertEqual(self.engine.snapshot(450).get('confirmation_age_ms'),350)
        for n,t in enumerate((600,750,900,1050,1200,1350,1500,1650),4):
            self.engine.process(n,t,[hand('pinch')],t)
            age=self.engine.snapshot(t).get('confirmation_age_ms')
            self.assertIsNotNone(age)
            self.assertGreaterEqual(age,300)
            self.assertLessEqual(age,450)
        self.engine.process(12,1800,[hand('pinch',identity='new')],1800)
        self.assertEqual(self.engine.snapshot(1800).get('confirmation_age_ms'),0)
        self.assertFalse(self.engine.snapshot(1800).get('confirmed_this_frame'))

    def test_dynamic_confirmation_age_is_the_new_cycle_not_old_history(self):
        for n,(t,k) in enumerate([(100,'closed'),(400,'open'),(800,'closed')],1):
            self.engine.process(n,t,[hand(k)],t)
        self.assertEqual(self.engine.snapshot(800).get('confirmation_age_ms'),700)
        self.engine.process(4,1000,[hand('closed')],1000)
        self.assertEqual(self.engine.snapshot(1000).get('confirmation_age_ms'),0)

    def test_invalid_thumb_threshold_overlap_rejected(self):
        with self.assertRaises(ValueError):Config(pound_thumb_hold=1.2).validate()

    def test_reappearing_hand_must_confirm_again_on_three_new_frames(self):
        self.feed(hand('pinch'))
        self.engine.process(4,600,[],600)
        for n,t in ((5,700),(6,850)):
            self.engine.process(n,t,[hand('pinch')],t)
            self.assertFalse(self.engine.snapshot(t).get('confirmed_this_frame'))
            self.assertEqual(self.engine.snapshot(t).get('confirmation_age_ms'),0)
        self.engine.process(7,1050,[hand('pinch')],1050)
        self.assertEqual(self.engine.snapshot(1050).get('confirmation_age_ms'),350)

    def test_duplicate_callback_cannot_emit_another_confirmed_event(self):
        self.feed(hand('pinch'))
        self.engine.process(3,600,[hand('pinch')],600)
        s=self.engine.snapshot(600)
        self.assertFalse(s.get('confirmed_this_frame'))
        self.assertEqual(s.get('observation_gesture'),'stop')
        self.assertEqual(s.get('confirmation_age_ms'),0)

    def test_old_callback_cannot_clear_new_generation_inference_slot(self):
        p=FramePipeline();p.capture_wifi(b'old',1000,'boot',1);old=p.take_latest()
        p.reset_confirmation(1100)
        p.capture_wifi(b'new',1200,'boot',2);new=p.take_latest()
        self.assertFalse(p.complete(old,[hand('pinch')],1250,640,480))
        self.assertEqual(p.pending,new)
        self.assertTrue(p.complete(new,[hand('pinch')],1300,640,480))
        self.assertEqual(p.snapshot(1300)['camera_frame_id'],2)
        self.assertFalse(p.snapshot(1300).get('confirmed_this_frame'))

    def test_excessive_thumb_length_and_invalid_nodes_do_not_trigger_static_knead(self):
        h=static_curl();h['landmarks'][4]=[(320-2.4*90)/640,(330-1.9*90)/480,0]
        self.assertEqual(self.feed(h)['raw_gesture'],'stop')
        self.engine=GestureEngine(Config())
        h=static_curl();h['landmarks'][8]=[float('nan'),0,0]
        self.assertEqual(self.feed(h).get('observation_state'),'error')

    def test_confirmation_reset_rejects_cached_pending_and_pre_reset_capture(self):
        p=FramePipeline()
        for n,t in enumerate((1000,1150,1350),1):
            p.capture_wifi(b'jpeg',t,'boot',n)
            self.assertTrue(p.complete(p.take_latest(),[hand('pinch')],t,640,480))
        self.assertTrue(p.snapshot(1350).get('confirmed_this_frame'))
        p.capture_wifi(b'pending',1400,'boot',4);old=p.take_latest()
        self.assertTrue(hasattr(p,'reset_confirmation'),'ARM confirmation barrier is missing')
        result=p.reset_confirmation(1450)
        self.assertEqual(result['confirmation_reset_monotonic_ms'],1450)
        self.assertFalse(p.complete(old,[hand('pinch')],1500,640,480))
        self.assertIsNone(p.take_latest())
        self.assertFalse(p.capture_wifi(b'late-capture',1440,'boot',5))
        self.assertFalse(p.snapshot(1500).get('confirmed_this_frame'))
        for n,t in enumerate((1500,1650,1850),6):
            p.capture_wifi(b'new',t,'boot',n)
            self.assertTrue(p.complete(p.take_latest(),[hand('pinch')],t,640,480))
            self.assertEqual(p.snapshot(t).get('confirmed_this_frame'),n==8)
        self.assertEqual(p.snapshot(1850).get('observation_gesture'),'pinch')

    def test_observation_proof_is_published_image_and_expires(self):
        p=FramePipeline()
        for n,t in enumerate((1000,1150,1350),1):
            p.capture_wifi(b'jpeg',t,'boot',n)
            p.complete(p.take_latest(),[hand('pinch')],t,640,480)
        p.capture_wifi(b'new-image',1500,'boot',4);s=p.snapshot(1500)
        self.assertEqual(s.get('observation_gesture'),'pinch')
        self.assertEqual(s['camera_frame_id'],3)
        self.assertTrue(s.get('confirmed_this_frame'))
        p.capture_wifi(b'newer-image',2149,'boot',5);s=p.snapshot(2150)
        self.assertTrue(s['ready'])
        self.assertFalse(s.get('confirmed_this_frame'))
        self.assertEqual(s.get('observation_state'),'error')

    def test_preview_without_result_cannot_claim_confirmation(self):
        p=FramePipeline();p.capture_wifi(b'preview',1000,'boot',1);s=p.snapshot(1000)
        self.assertEqual(s.get('observation_version'),2)
        self.assertFalse(s.get('confirmed_this_frame'))
        self.assertEqual(s.get('observation_gesture'),'stop')

if __name__=='__main__':unittest.main()

class RecognitionInstanceTests(unittest.TestCase):
    def test_instance_changes_only_for_new_pipeline_not_camera_or_confirmation_reset(self):
        pipeline=FramePipeline();identity=pipeline.snapshot(0).get('recognition_instance_id')
        self.assertIsInstance(identity,str);self.assertTrue(identity)
        pipeline.reset();response=pipeline.reset_confirmation(1)
        self.assertEqual(response.get('recognition_instance_id'),identity)
        self.assertEqual(pipeline.snapshot(2).get('recognition_instance_id'),identity)
        self.assertNotEqual(FramePipeline().snapshot(0).get('recognition_instance_id'),identity)

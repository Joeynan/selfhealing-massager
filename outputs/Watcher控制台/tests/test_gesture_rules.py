import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'camera'))


def hand(kind='open', identity='a', side='Left', scale=90, rotation=0, mirror=False):
    p = [[0., 0., 0.] for _ in range(21)]
    p[0] = [0, 0, 0]
    p[1:5] = [[-.3, -.2, 0], [-.6, -.4, 0], [-.72, -.62, 0], [-.85, -.9, 0]]
    for base, x, y in [(5, -.4, -.9), (9, 0, -1), (13, .3, -.9), (17, .55, -.75)]:
        p[base] = [x, y, 0]
        p[base+1] = [x, y-.5, 0]
        p[base+2] = [x, y-.9, 0]
        p[base+3] = [x, y-1.25, 0]
        if kind in ('fist', 'closed'):
            p[base+2] = [x+.18, y-.35, 0]
            p[base+3] = [x+.18, y-.05, 0]
    if kind == 'pinch':
        p[8] = list(p[4])
    if kind == 'closed':
        p[4] = [-.2, -1.2, 0]
        for n, i in enumerate([8, 12, 16, 20]):
            p[i] = [-.2+n*.06, -1.2+n*.02, 0]
    c, s = math.cos(rotation), math.sin(rotation)
    result = []
    for x, y, z in p:
        x = -x if mirror else x
        result.append([(320+scale*(c*x-s*y))/640, (330+scale*(s*x+c*y))/480, z*scale/640])
    return {'id': identity, 'handedness': side, 'landmarks': result}


class RulesTests(unittest.TestCase):
    def setUp(self):
        try:
            from gesture_rules import Config, GestureEngine
        except ImportError:
            self.fail('The landmark rule engine has not been implemented')
        self.Config = Config
        self.Engine = GestureEngine
        self.engine = GestureEngine(Config(back_sign_by_hand={'Left': 1, 'Right': -1}))

    def feed(self, h, times=(100, 250, 450)):
        for n, t in enumerate(times, 1):
            self.engine.process(n, t, [h], t)
        return self.engine.snapshot(times[-1])

    def test_thumb_outside_four_finger_curl_cycle_is_kneading(self):
        self.engine = self.Engine(self.Config())
        for n, (t, k) in enumerate([(100,'fist'), (400,'open'), (650,'open'), (950,'fist')], 1):
            self.engine.process(n,t,[hand(k)],t)
        self.assertEqual(self.engine.snapshot(950)['gesture'], 'kneading')

    def test_static_micro_open_fist_is_not_kneading_without_back_calibration(self):
        self.engine = self.Engine(self.Config())
        self.assertEqual(self.feed(hand('fist'))['gesture'], 'stop')

    def test_static_calibrated_micro_open_fist_stays_pounding_after_curl_support(self):
        self.assertEqual(self.feed(hand('fist'))['gesture'], 'pounding')

    def test_calibrated_fist_with_completed_motion_is_kneading(self):
        for n, (t, k) in enumerate([(100,'fist'), (400,'open'), (650,'open'), (950,'fist')], 1):
            self.engine.process(n,t,[hand(k)],t)
        self.assertEqual(self.engine.snapshot(950)['gesture'], 'kneading')

    def test_thumb_outside_cycle_is_rotation_and_scale_invariant(self):
        for rotation,scale in ((-.7,50),(.7,110)):
            self.engine = self.Engine(self.Config())
            for n, (t,k) in enumerate([(100,'fist'),(400,'open'),(650,'open'),(950,'fist')],1):
                self.engine.process(n,t,[hand(k,rotation=rotation,scale=scale)],t)
            self.assertEqual(self.engine.snapshot(950)['gesture'], 'kneading')

    def test_pinch_requires_three_fresh_frames_and_300ms(self):
        h = hand('pinch')
        self.engine.process(1, 100, [h], 100)
        self.engine.process(2, 200, [h], 200)
        self.assertEqual(self.engine.snapshot(200)['gesture'], 'stop')
        self.engine.process(3, 450, [h], 450)
        self.assertEqual(self.engine.snapshot(450)['gesture'], 'pinch')

    def test_scale_rotation_and_aspect_do_not_change_pinch(self):
        for scale, rotation in [(40, -.7), (120, .7), (90, 1.2)]:
            self.engine = self.Engine(self.Config())
            self.assertEqual(self.feed(hand('pinch', scale=scale, rotation=rotation))['gesture'], 'pinch')

    def test_fist_requires_back_calibration(self):
        self.engine = self.Engine(self.Config())
        self.assertEqual(self.feed(hand('fist'))['gesture'], 'stop')

    def test_calibrated_fist_is_pounding(self):
        self.assertEqual(self.feed(hand('fist'))['gesture'], 'pounding')

    def test_mirrored_right_fist_can_be_calibrated(self):
        self.assertEqual(self.feed(hand('fist', side='Right', mirror=True))['gesture'], 'pounding')

    def test_front_facing_fist_does_not_trigger(self):
        self.assertEqual(self.feed(hand('fist', mirror=True))['gesture'], 'stop')

    def test_extended_thumb_does_not_count_as_micro_open(self):
        h = hand('fist'); h['landmarks'][4] = [.2, .1, 0]
        self.assertEqual(self.feed(h)['gesture'], 'stop')

    def test_image_curled_fingers_are_not_extended_by_noisy_world_angles(self):
        from gesture_rules import features
        h=hand('closed');h['world_landmarks']=hand('open')['landmarks']
        actual=features(h,640,480,self.Config())
        self.assertFalse(any(actual['extended']))

    def test_user_fist_accepts_wider_thumb_after_tuning(self):
        h=hand('fist');h['landmarks'][4]=[(320-1.2*90)/640,(330-1.4*90)/480,0]
        self.engine=self.Engine(self.Config(folded_angle=145,thumb_open_max=1.25,thumb_length_max=1.95,back_sign_by_hand={'Left':1,'Right':-1}))
        self.assertEqual(self.feed(h)['gesture'],'pounding')

    def test_static_all_finger_pinch_is_not_kneading_or_light_pinch(self):
        self.assertEqual(self.feed(hand('closed'))['gesture'], 'stop')

    def test_kneading_requires_closed_open_closed_cycle(self):
        for n, (t, k) in enumerate([(100, 'closed'), (400, 'open'), (800, 'closed')], 1):
            self.engine.process(n, t, [hand(k)], t)
        self.assertEqual(self.engine.snapshot(800)['gesture'], 'kneading')

    def test_too_fast_and_too_slow_cycles_are_rejected(self):
        sequences=[[(100,'closed'),(200,'open'),(300,'closed')],
                   [(100,'open'),(400,'half'),(800,'half'),(1200,'half'),
                    (1600,'half'),(2000,'half'),(2400,'half'),(2800,'closed')]]
        for sequence in sequences:
            self.engine = self.Engine(self.Config())
            for n, (t, k) in enumerate(sequence, 1):
                h=hand(k if k!='half' else 'open')
                if k=='half':
                    # Partial motion, not yet a five-finger gather.
                    for i in (8,12,16,20):h['landmarks'][i][1]+=.12
                self.engine.process(n, t, [h], t)
            self.assertEqual(self.engine.snapshot(sequence[-1][0])['gesture'], 'stop')

    def test_static_hold_after_cycle_cannot_refresh_kneading_forever(self):
        for n, (t, k) in enumerate([(100,'closed'), (400,'open'), (800,'closed'), (1200,'closed'), (1650,'closed')],1):
            self.engine.process(n,t,[hand(k)],t)
        self.assertEqual(self.engine.snapshot(1650)['gesture'], 'stop')

    def test_conflicting_hands_stop_immediately(self):
        self.feed(hand('pinch'))
        self.engine.process(4, 550, [hand('pinch'),hand('fist', identity='b')],550)
        self.assertEqual(self.engine.snapshot(550)['gesture'], 'stop')

    def test_repeated_frame_does_not_confirm_or_refresh(self):
        h=hand('pinch')
        self.engine.process(1,100,[h],100)
        self.engine.process(1,450,[h],450)
        self.engine.process(1,600,[h],600)
        self.assertEqual(self.engine.snapshot(600)['gesture'],'stop')
        self.engine = self.Engine(self.Config())
        self.feed(h)
        self.engine.process(3, 1200, [h],1200)
        self.assertEqual(self.engine.snapshot(1300)['gesture'],'stop')

    def test_no_frame_watchdog_stops_without_another_callback(self):
        self.feed(hand('pinch'))
        self.assertEqual(self.engine.snapshot(1251)['gesture'], 'stop')

    def test_late_callback_cannot_restart_output(self):
        self.engine.process(1,100,[hand('pinch')],1100)
        self.assertEqual(self.engine.snapshot(1100)['raw_gesture'], 'stop')

    def test_missing_hand_resets_pending_confirmation(self):
        self.engine.process(1,100,[hand('pinch')],100)
        self.engine.process(2,250,[],250)
        self.engine.process(3,450,[hand('pinch')],450)
        self.assertEqual(self.engine.snapshot(450)['gesture'], 'stop')

    def test_nonfinite_or_incomplete_points_are_rejected(self):
        for points in [[[0,0,0]]*20, [[float('nan'),0,0]]*21]:
            h=hand('pinch');h['landmarks']=points
            self.assertEqual(self.feed(h)['gesture'],'stop')

    def test_unrelated_hands_cannot_form_one_kneading_cycle(self):
        for n,(t,k,identity) in enumerate([(100,'closed','a'),(400,'open','b'),(800,'closed','a')],1):
            self.engine.process(n,t,[hand(k,identity=identity)],t)
        self.assertEqual(self.engine.snapshot(800)['gesture'],'stop')

    def test_conflicting_config_thresholds_rejected(self):
        with self.assertRaises(ValueError):
            self.Config(pinch_enter=.5,pinch_exit=.35).validate()

    def test_different_hands_cannot_combine_static_confirmation(self):
        for n,t in enumerate([100,250,450],1):
            self.engine.process(n,t,[hand('pinch',identity=str(n))],t)
        self.assertEqual(self.engine.snapshot(450)['gesture'],'stop')

    def test_conflict_requires_a_new_complete_kneading_cycle(self):
        for n,(t,k) in enumerate([(100,'closed'),(400,'open')],1):
            self.engine.process(n,t,[hand(k)],t)
        self.engine.process(3,800,[hand('closed'),hand('pinch',identity='b')],800)
        self.assertEqual(self.engine.snapshot(800)['gesture'],'stop')
        self.engine.process(4,1000,[hand('closed')],1000)
        self.assertEqual(self.engine.snapshot(1000)['gesture'],'stop')

    def test_expired_kneading_cannot_restart_with_only_opening(self):
        for n,(t,k) in enumerate([(100,'closed'),(400,'open'),(800,'closed'),(1200,'closed'),(1650,'closed'),(2000,'open')],1):
            self.engine.process(n,t,[hand(k)],t)
            self.engine.snapshot(t)
        self.assertEqual(self.engine.snapshot(2000)['gesture'],'stop')


if __name__ == '__main__':
    unittest.main()

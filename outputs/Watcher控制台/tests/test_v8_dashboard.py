import sys,time,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bridge import IntentEngine
from server import Dashboard
import launch


def observation(**changes):
    c=dict(ready=True,transport='wifi',frame_id=8,capture_monotonic_ms=10000,
           received_monotonic_ms=10600,frame_age_ms=600,capture_session_id='local-a',
           camera_session_id='boot-a',camera_frame_id=8,observation_version=2,
           observation_state='confirmed',confirmed_this_frame=True,hand_present=True,
           observation_gesture='pinch',gesture='pinch',raw_gesture='pinch',knead_kind='none',
           confirmation_age_ms=350,confirmation_generation=1,recognition_instance_id='service-a')
    c.update(changes);return c


def ready_dashboard(source='camera'):
    d=Dashboard('http://watcher','http://camera');d.diagnostic_active=True;d.engine.set_source(source)
    now=time.monotonic()
    d.observed={'watcher':now,'camera':now}
    d.watcher={'online':True,'error':'','data':dict(firmware='watcher-servo-controller-v8-wifi',client_firmware='esp8266-servo-controller-v7',
       input_source=source,client_connected=True,outputs_enabled=False,profile_match=True,hold_protocol=2,
       camera_observation_version=2,mac_observation_version=2,ack_age_ms=20,camera_active=True,camera_age_ms=20,
       servo_profile={'neutral_us':[1500]*3,'run_us':[2000]*3})}
    d.camera={'online':True,'error':'','data':observation(received_monotonic_ms=now*1000,frame_age_ms=50,capture_monotonic_ms=(now*1000)-50)}
    return d


class V8BridgeTests(unittest.TestCase):
    def test_fresh_observation_600ms_is_forwarded_and_not_hard_stopped(self):
        e=IntentEngine();e.set_source('camera');p=e.step(observation(),10.6)
        self.assertEqual(p.get('observation_version'),2)
        self.assertEqual(p['gesture'],'pinch')
        self.assertEqual(p.get('confirmation_age_ms'),350)
        self.assertEqual(p.get('camera_frame_id'),8)
        self.assertGreaterEqual(p['frame_age_ms'],600)
        self.assertIsNone(e.step(observation(),10.7))
        self.assertEqual(e.step(observation(),10.8)['gesture'],'stop')

    def test_grace_stable_gesture_cannot_be_sent_as_a_new_confirmation(self):
        e=IntentEngine();e.set_source('camera')
        p=e.step(observation(observation_state='no_hand',confirmed_this_frame=False,hand_present=False,observation_gesture='stop',confirmation_age_ms=0),10.6)
        self.assertEqual(p['gesture'],'stop')
        self.assertEqual(p.get('observation_state'),'no_hand')
        self.assertFalse(p.get('confirmed_this_frame'))

    def test_repeated_proof_under_changed_capture_timestamp_does_not_refresh(self):
        e=IntentEngine();e.set_source('camera');e.step(observation(),10.6)
        self.assertIsNone(e.step(observation(capture_monotonic_ms=10100),10.7))

    def test_confirmation_barrier_generation_rejects_pre_arm_published_result(self):
        e=IntentEngine();e.set_source('camera')
        self.assertTrue(hasattr(e,'confirmation_barrier'))
        e.confirmation_barrier(2)
        self.assertIsNone(e.step(observation(),10.6))
        self.assertEqual(e.step(observation(confirmation_generation=2),10.6)['gesture'],'pinch')

    def test_arm_barrier_allows_bounded_wait_for_first_publication(self):
        e=IntentEngine();e.set_source('camera')
        self.assertTrue(hasattr(e,'confirmation_barrier'))
        now=time.monotonic();e.confirmation_barrier(2)
        waiting=observation(confirmation_generation=2,camera_session_id=None,camera_frame_id=None,
                            ready=False,frame_age_ms=None,error='')
        self.assertIsNone(e.step(waiting,now+.2))
        self.assertEqual(e.step(waiting,now+.81)['gesture'],'stop')

    def test_invalid_confirmation_cannot_use_cached_stable_label(self):
        e=IntentEngine();e.set_source('camera')
        p=e.step(observation(observation_state='unrecognized',confirmed_this_frame=True,observation_gesture='pinch'),10.6)
        self.assertEqual(p['gesture'],'stop')
        self.assertNotEqual(p.get('observation_version'),2)


class V8DashboardTests(unittest.TestCase):
    def test_header_uses_device_held_gesture_instead_of_unsent_engine(self):
        d=ready_dashboard();d.engine.gesture='pounding'
        d.watcher['data'].update(held_gesture='pinch',expression_gesture='pinch',hold_remaining_ms=4600,servo_hold_remaining_ms=0,gesture='stop')
        s=d.snapshot()
        self.assertEqual(s['requested_gesture'],'pinch')
        self.assertTrue(4500<=s.get('hold_remaining_ms',0)<=4600)
        self.assertEqual(s.get('software_release'),'wifi-camera-v8')

    def test_no_hand_observation_routes_gesture_endpoint_not_hard_stop(self):
        d=ready_dashboard();d.camera['data']=observation(observation_state='no_hand',confirmed_this_frame=False,hand_present=False,observation_gesture='stop',confirmation_age_ms=0)
        with patch('server.fetch',return_value={'ok':True}) as send:d.forward_inputs(10.6)
        self.assertEqual(send.call_args.args[0],'http://watcher/gesture')
        self.assertEqual(send.call_args.args[1].get('observation_state'),'no_hand')

    def test_camera_arm_uses_two_confirmation_barriers_and_awaits_actual_arm(self):
        d=ready_dashboard();calls=[];resets=0
        def send(url,body=None,**kwargs):
            nonlocal resets
            calls.append((url,body))
            if url.endswith('/reset_confirmation'):
                resets+=1;return {'ok':True,'confirmation_generation':resets,'confirmation_reset_monotonic_ms':time.monotonic()*1000}
            if url.endswith('/status'):return dict(d.watcher['data'],outputs_enabled=True)
            return {'ok':True}
        with patch('server.fetch',side_effect=send):result=d.action('/api/servo/arm',{'enabled':True,'power_confirmed':True})
        self.assertTrue(result['ok'])
        urls=[u for u,b in calls]
        self.assertLess(urls.index('http://watcher/stop'),urls.index('http://camera/reset_confirmation'))
        self.assertEqual(urls.count('http://camera/reset_confirmation'),2)
        self.assertLess(urls.index('http://watcher/servo/arm'),len(urls)-1)
        self.assertFalse(d.forward_paused)
        self.assertEqual(d.engine.minimum_confirmation_generation,2)

    def test_old_protocol_firmware_never_receives_arm(self):
        d=ready_dashboard();d.watcher['data']['hold_protocol']=0
        with patch('server.fetch') as send,self.assertRaises(ValueError):d.action('/api/servo/arm',{'enabled':True,'power_confirmed':True})
        send.assert_not_called()

    def test_arm_error_stops_disables_and_keeps_forwarding_paused(self):
        d=ready_dashboard()
        def send(url,body=None,**kwargs):
            if url.endswith('/reset_confirmation'):return {'ok':False,'error':'reset failed'}
            return {'ok':True}
        with patch('server.fetch',side_effect=send) as mock,self.assertRaises(ValueError):d.action('/api/servo/arm',{'enabled':True,'power_confirmed':True})
        self.assertTrue(d.forward_paused)
        self.assertIn(('http://watcher/servo/arm',{'enabled':False}),[(c.args[0],c.args[1]) for c in mock.call_args_list])

    def test_arm_rejection_recovers_preview_only_after_stop_disable_and_new_barrier(self):
        d=ready_dashboard();calls=[];generation=0
        def send(url,body=None,**kwargs):
            nonlocal generation
            calls.append((url,body))
            if url.endswith('/reset_confirmation'):
                generation+=1;return {'ok':True,'confirmation_generation':generation}
            if url.endswith('/servo/arm') and body.get('enabled'):
                return {'ok':False,'error':'arm rejected'}
            return {'ok':True}
        with patch('server.fetch',side_effect=send),self.assertRaises(ValueError):
            d.action('/api/servo/arm',{'enabled':True,'power_confirmed':True})
        self.assertFalse(d.forward_paused)
        self.assertFalse(d.servo['armed'])
        self.assertEqual(d.engine.gesture,'stop')
        self.assertEqual(d.engine.minimum_confirmation_generation,2)
        self.assertEqual(sum(u.endswith('/servo/arm') and b.get('enabled') is True for u,b in calls),1)
        self.assertEqual(calls[-1][0],'http://camera/reset_confirmation')

    def test_arm_rejection_with_failed_stop_keeps_forward_paused(self):
        d=ready_dashboard();stops=0;resets=0
        def send(url,body=None,**kwargs):
            nonlocal stops,resets
            if url.endswith('/stop'):
                stops+=1;return {'ok':stops==1,'error':'' if stops==1 else 'stop failed'}
            if url.endswith('/reset_confirmation'):
                resets+=1;return {'ok':True,'confirmation_generation':resets}
            if url.endswith('/servo/arm') and body.get('enabled'):
                return {'ok':False,'error':'arm rejected'}
            return {'ok':True}
        with patch('server.fetch',side_effect=send),self.assertRaises(ValueError):
            d.action('/api/servo/arm',{'enabled':True,'power_confirmed':True})
        self.assertTrue(d.forward_paused)
        self.assertFalse(d.servo['armed'])
        self.assertEqual(resets,1)

    def test_recognition_process_restart_disables_clears_old_generation_and_recovers_preview(self):
        d=ready_dashboard();d.camera_instance_id='service-a';d.engine.confirmation_barrier(3,'service-a')
        d.servo['armed']=True;calls=[]
        fresh=observation(recognition_instance_id='service-b',confirmation_generation=0,
                          camera_frame_id=9,frame_age_ms=50,received_monotonic_ms=time.monotonic()*1000)
        def send(url,body=None,**kwargs):
            calls.append((url,body))
            if url=='http://camera/status':return dict(fresh)
            if url.endswith('/reset_confirmation'):
                return {'ok':True,'confirmation_generation':1,'recognition_instance_id':'service-b'}
            return {'ok':True}
        with patch('server.fetch',side_effect=send):d.poll('camera','http://camera')
        self.assertEqual([url for url,_ in calls],['http://camera/status','http://watcher/stop','http://watcher/servo/arm','http://camera/reset_confirmation'])
        self.assertEqual(calls[2][1],{'enabled':False})
        self.assertFalse(d.forward_paused);self.assertFalse(d.servo['armed'])
        self.assertEqual(d.engine.minimum_confirmation_generation,1)
        self.assertIsNone(d.engine.step(d.camera['data'],time.monotonic()))
        fresh.update(confirmation_generation=1,camera_frame_id=10)
        self.assertEqual(d.engine.step(fresh,time.monotonic())['gesture'],'pinch')
        self.assertEqual(sum(body.get('enabled') is True for url,body in calls if body),0)

    def test_recognition_restart_reset_failure_remains_paused(self):
        d=ready_dashboard();d.camera_instance_id='service-a';d.engine.confirmation_barrier(3,'service-a')
        def send(url,body=None,**kwargs):
            if url=='http://camera/status':return observation(recognition_instance_id='service-b',confirmation_generation=0)
            if url.endswith('/reset_confirmation'):return {'ok':False,'error':'reset failed'}
            return {'ok':True}
        with patch('server.fetch',side_effect=send):d.poll('camera','http://camera')
        self.assertTrue(d.forward_paused);self.assertFalse(d.servo['armed'])

    def test_changed_capture_session_does_not_lower_confirmation_barrier(self):
        d=ready_dashboard();d.camera_instance_id='service-a';d.engine.confirmation_barrier(3,'service-a')
        def send(url,body=None,**kwargs):
            return observation(recognition_instance_id='service-a',capture_session_id='new-camera-session',confirmation_generation=0)
        with patch('server.fetch',side_effect=send) as calls:d.poll('camera','http://camera')
        self.assertEqual(calls.call_count,1)
        self.assertEqual(d.engine.minimum_confirmation_generation,3)

    def test_recognition_restart_stop_failure_keeps_paused_without_reset(self):
        d=ready_dashboard();d.camera_instance_id='service-a';d.engine.confirmation_barrier(3,'service-a')
        def send(url,body=None,**kwargs):
            if url=='http://camera/status':return observation(recognition_instance_id='service-b',confirmation_generation=0)
            if url.endswith('/stop'):return {'ok':False,'error':'stop failed'}
            return {'ok':True}
        with patch('server.fetch',side_effect=send) as calls:d.poll('camera','http://camera')
        self.assertTrue(d.forward_paused);self.assertFalse(d.servo['armed'])
        self.assertNotIn('http://camera/reset_confirmation',[call.args[0] for call in calls.call_args_list])

    def test_observer_does_not_take_device_ownership_when_camera_restarts(self):
        d=ready_dashboard();d.diagnostic_active=False;d.camera_instance_id='service-a'
        with patch('server.fetch',return_value=observation(recognition_instance_id='service-b',confirmation_generation=0)) as calls:
            d.poll('camera','http://camera')
        self.assertEqual(calls.call_count,1)
        self.assertEqual(d.camera_instance_id,'service-b')

class V8LaunchTests(unittest.TestCase):
    def test_reusing_legacy_camera_service_is_rejected(self):
        with self.assertRaises(ValueError):
            launch.validate_camera_service({'transport':'wifi','camera_url':'http://host:8081/frame','watcher_id':'test'},'wifi','http://host:8081/frame','test')
        launch.validate_camera_service({'transport':'wifi','camera_url':'http://host:8081/frame','watcher_id':'test','observation_version':2,'recognition_instance_id':'service-a'},'wifi','http://host:8081/frame','test')

    def test_v2_service_without_process_identity_must_be_restarted_before_reuse(self):
        with self.assertRaises(ValueError):
            launch.validate_camera_service({'transport':'wifi','camera_url':'http://host:8081/frame','watcher_id':'test','observation_version':2},'wifi','http://host:8081/frame','test')

    def test_wifi_launch_supports_v8_and_legacy_v7_preview(self):
        self.assertTrue(hasattr(launch,'wifi_firmware_supported'))
        self.assertTrue(launch.wifi_firmware_supported('watcher-servo-controller-v8-wifi'))
        self.assertTrue(launch.wifi_firmware_supported('watcher-servo-controller-v7-wifi'))
        self.assertFalse(launch.wifi_firmware_supported('unknown'))

if __name__=='__main__':unittest.main()

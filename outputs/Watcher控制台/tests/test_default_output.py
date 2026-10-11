import time
import unittest
from unittest.mock import patch

from test_v8_dashboard import ready_dashboard as v8_dashboard
from server import Dashboard


def ready_dashboard(source='camera'):
    dashboard=v8_dashboard(source)
    dashboard.default_enable_generation=7
    dashboard.watcher['data'].update(output_policy_revision='default-enable-1', stop_generation=7,
                                   outputs_enabled=False, applied_mode=0)
    return dashboard


class DefaultOutputTests(unittest.TestCase):
    def test_expected_confirmation_reset_wait_does_not_cancel_default_enable(self):
        dashboard = ready_dashboard()
        dashboard.default_enable_pending = True
        dashboard.engine.confirmation_barrier(2, 'service-a')
        dashboard.camera['data'].update(confirmation_generation=2, recognition_instance_id='service-a',
                                       observation_state='error', ready=False, error='',
                                       camera_session_id=None, camera_frame_id=None, frame_age_ms=None)
        with patch('server.fetch', side_effect=self.responder(dashboard)) as calls:
            dashboard.forward_inputs(time.monotonic())
        self.assertTrue(dashboard.default_enable_pending)
        self.assertFalse(any(c.args[0].endswith('/stop') for c in calls.call_args_list))

    def test_real_camera_error_during_confirmation_wait_cancels_enable(self):
        dashboard = ready_dashboard()
        dashboard.default_enable_pending = True
        dashboard.engine.confirmation_barrier(2, 'service-a')
        dashboard.camera['data'].update(confirmation_generation=2, recognition_instance_id='service-a',
                                       observation_state='error', ready=False, error='camera disconnected',
                                       camera_session_id=None, camera_frame_id=None, frame_age_ms=None)
        with patch('server.fetch', side_effect=self.responder(dashboard)):
            dashboard.forward_inputs(time.monotonic())
        self.assertFalse(dashboard.default_enable_pending)

    def test_confirmation_wait_does_not_hide_wrong_instance_or_old_generation(self):
        dashboard = ready_dashboard()
        dashboard.engine.confirmation_barrier(2, 'service-a')
        empty = dict(dashboard.camera['data'], confirmation_generation=2,
                     recognition_instance_id='service-a', error='',
                     camera_session_id=None, camera_frame_id=None)
        self.assertTrue(dashboard.engine.awaiting_publication(empty, time.monotonic()))
        self.assertFalse(dashboard.engine.awaiting_publication(
            dict(empty, recognition_instance_id='other-service'), time.monotonic()))
        self.assertFalse(dashboard.engine.awaiting_publication(
            dict(empty, confirmation_generation=1), time.monotonic()))

    def test_expired_confirmation_wait_cancels_default_enable(self):
        dashboard = ready_dashboard()
        dashboard.default_enable_pending = True
        dashboard.engine.confirmation_barrier(2, 'service-a')
        dashboard.camera['data'].update(confirmation_generation=2, recognition_instance_id='service-a',
                                       observation_state='error', ready=False, error='',
                                       camera_session_id=None, camera_frame_id=None, frame_age_ms=None)
        with patch('server.fetch', side_effect=self.responder(dashboard)):
            dashboard.forward_inputs(dashboard.engine.publication_wait_until + .001)
        self.assertFalse(dashboard.default_enable_pending)

    def test_default_enable_waits_for_actual_disabled_ack(self):
        dashboard = ready_dashboard('simulation')
        dashboard.default_enable_pending = True
        dashboard.watcher['data']['outputs_enabled'] = True
        with patch('server.fetch', side_effect=self.responder(dashboard)) as calls:
            dashboard.maybe_default_enable()
        self.assertTrue(dashboard.default_enable_pending)
        self.assertFalse(any(c.args[0].endswith('/servo/arm') for c in calls.call_args_list))

    def test_default_enable_waits_for_neutral_ack(self):
        dashboard = ready_dashboard('simulation')
        dashboard.default_enable_pending = True
        dashboard.watcher['data']['applied_mode'] = 2
        with patch('server.fetch', side_effect=self.responder(dashboard)) as calls:
            dashboard.maybe_default_enable()
        self.assertTrue(dashboard.default_enable_pending)
        self.assertFalse(any(c.args[0].endswith('/servo/arm') for c in calls.call_args_list))

    def responder(self, dashboard):
        def send(url, body=None, **kwargs):
            if url == dashboard.camera_url + '/status':
                return dict(dashboard.camera['data'])
            if url.endswith('/status'):
                return dict(dashboard.watcher['data'], outputs_enabled=True)
            if url.endswith('/reset_confirmation'):
                return {'ok': True, 'confirmation_generation': 2,
                        'recognition_instance_id': 'service-a'}
            if url.endswith('/source'):
                return {'ok':True, 'stop_generation':7, 'source':body['source']}
            return {'ok': True}
        return send

    def test_camera_cold_start_waits_for_fresh_published_proof(self):
        dashboard = ready_dashboard()
        responses = [dict(dashboard.camera['data'], ready=False, error='HTTP 503'),
                     dict(dashboard.camera['data'], camera_session_id=None, camera_frame_id=None),
                     dict(dashboard.camera['data'])]
        with patch('server.fetch', side_effect=responses) as calls:
            dashboard._wait_for_camera_ready()
        self.assertEqual(calls.call_count, 3)

    def test_camera_cold_start_timeout_never_arms(self):
        dashboard = ready_dashboard()
        class Clock:
            value = 0
            def __call__(self):
                self.value += .4
                return self.value
        with patch('server.time.monotonic', side_effect=Clock()), patch('server.fetch', return_value={'ready':False}) as calls:
            with self.assertRaises(ValueError):
                dashboard._wait_for_camera_ready()
        self.assertFalse(dashboard.default_enable_pending)
        self.assertFalse(any(c.args[0].endswith('/servo/arm') for c in calls.call_args_list))

    def test_enable_needs_no_power_checkbox(self):
        dashboard = ready_dashboard('simulation')
        with patch('server.fetch', side_effect=self.responder(dashboard)):
            self.assertTrue(dashboard.action('/api/servo/arm', {'enabled': True})['ok'])
        self.assertTrue(dashboard.servo['armed'])

    def test_selected_source_waits_for_ready_then_enables_once(self):
        dashboard = ready_dashboard('simulation')
        with patch('server.fetch', side_effect=self.responder(dashboard)) as send:
            dashboard.action('/api/source', {'source': 'simulation'})
            dashboard.observed['watcher']=max(time.monotonic(), dashboard.default_enable_after + .001)
            dashboard.watcher['data']['profile_match'] = False
            dashboard.maybe_default_enable()
            self.assertFalse(any(c.args[0].endswith('/servo/arm') and c.args[1].get('enabled')
                                 for c in send.call_args_list))
            self.assertTrue(dashboard.snapshot()['default_enable_pending'])
            dashboard.watcher['data']['profile_match'] = True
            dashboard.maybe_default_enable()
            dashboard.maybe_default_enable()
        arms = [c for c in send.call_args_list
                if c.args[0].endswith('/servo/arm') and c.args[1].get('enabled')]
        self.assertEqual(len(arms), 1)
        self.assertTrue(dashboard.servo['armed'])
        self.assertFalse(dashboard.snapshot()['default_enable_pending'])

    def test_explicit_stop_cancels_pending_default_enable(self):
        dashboard = ready_dashboard('simulation')
        with patch('server.fetch', side_effect=self.responder(dashboard)) as send:
            dashboard.action('/api/source', {'source': 'simulation'})
            dashboard.action('/api/stop', {})
            dashboard.maybe_default_enable()
        self.assertFalse(any(c.args[0].endswith('/servo/arm') and c.args[1].get('enabled')
                             for c in send.call_args_list))

    def test_manual_disable_is_not_undone(self):
        dashboard = ready_dashboard('simulation')
        with patch('server.fetch', side_effect=self.responder(dashboard)) as send:
            dashboard.action('/api/source', {'source': 'simulation'})
            dashboard.action('/api/servo/arm', {'enabled': False})
            dashboard.maybe_default_enable()
        self.assertFalse(any(c.args[0].endswith('/servo/arm') and c.args[1].get('enabled')
                             for c in send.call_args_list))

    def test_default_enable_failure_does_not_loop_or_rearm_after_fault(self):
        dashboard = ready_dashboard('simulation')
        dashboard.default_enable_pending = True
        def send(url, body=None, **kwargs):
            if url.endswith('/servo/arm') and body.get('enabled'):
                return {'ok': False, 'error': 'link lost'}
            return {'ok': True}
        with patch('server.fetch', side_effect=send) as calls:
            dashboard.maybe_default_enable()
            dashboard.maybe_default_enable()
        self.assertEqual(sum(c.args[0].endswith('/servo/arm') and c.args[1].get('enabled') is True
                             for c in calls.call_args_list), 1)
        self.assertFalse(dashboard.servo['armed'])

    def test_camera_default_enable_keeps_post_arm_confirmation_barriers(self):
        dashboard = ready_dashboard()
        dashboard.default_enable_pending = True
        with patch('server.fetch', side_effect=self.responder(dashboard)) as calls:
            dashboard.maybe_default_enable()
        self.assertEqual(sum(c.args[0].endswith('/reset_confirmation')
                             for c in calls.call_args_list), 2)
        self.assertEqual(dashboard.engine.minimum_confirmation_generation, 2)
        self.assertEqual(dashboard.engine.gesture, 'stop')

    def test_viewer_startup_does_not_send_an_arm(self):
        dashboard = Dashboard('http://watcher', 'http://camera')
        with patch('server.fetch') as send:
            dashboard.maybe_default_enable()
        send.assert_not_called()

    def test_normal_simulation_expiry_sends_neutral_without_disarming(self):
        dashboard = ready_dashboard('simulation')
        now = time.monotonic()
        dashboard.engine.simulate('pinch', 500, now)
        with patch('server.fetch', return_value={'ok': True}) as send:
            dashboard.forward_inputs(now + .1)
            dashboard.forward_inputs(now + .51)
        self.assertEqual(send.call_args.args[0], 'http://watcher/gesture')
        self.assertEqual(send.call_args.args[1]['gesture'], 'stop')
        self.assertEqual(send.call_args.args[1]['source'], 'simulation')
        self.assertNotIn('http://watcher/stop', [c.args[0] for c in send.call_args_list])

    def test_camera_fault_still_hard_stops_and_disables(self):
        dashboard = ready_dashboard()
        dashboard.engine.last_sent = 'pinch'
        dashboard.camera = {'online': False, 'data': {}}
        with patch('server.fetch', return_value={'ok': True}) as send:
            dashboard.forward_inputs(time.monotonic())
        self.assertEqual(send.call_args.args[0], 'http://watcher/stop')

    def test_camera_error_cancels_pending_before_next_healthy_frame(self):
        dashboard = ready_dashboard()
        dashboard.default_enable_pending = True
        dashboard.camera['data'].update(observation_state='error', confirmed_this_frame=False,
                                        observation_gesture='stop', confirmation_age_ms=0)
        with patch('server.fetch', side_effect=self.responder(dashboard)) as calls:
            dashboard.forward_inputs(time.monotonic())
            dashboard.camera['data'].update(observation_state='unrecognized')
            dashboard.maybe_default_enable()
        self.assertFalse(any(c.args[0].endswith('/servo/arm') for c in calls.call_args_list))

    def test_first_black_connection_can_complete_pending_enable(self):
        dashboard = ready_dashboard('simulation')
        dashboard.watcher['data'].update(client_connected=False, client_connection_id=0)
        with patch('server.fetch', side_effect=self.responder(dashboard)) as calls:
            dashboard.action('/api/source', {'source': 'simulation'})
            dashboard.watcher['data'].update(client_connected=True, client_connection_id=1)
            dashboard.observed['watcher']=max(time.monotonic(), dashboard.default_enable_after + .001)
            dashboard.maybe_default_enable()
        self.assertTrue(any(c.args[0].endswith('/servo/arm') and c.args[1].get('enabled')
                            for c in calls.call_args_list))

    def test_reconnect_before_initial_enable_cancels_pending(self):
        dashboard = ready_dashboard('simulation')
        dashboard.watcher['data']['client_connection_id'] = 1
        with patch('server.fetch', side_effect=self.responder(dashboard)) as calls:
            dashboard.action('/api/source', {'source': 'simulation'})
            dashboard.watcher['data']['client_connection_id'] = 2
            dashboard.observed['watcher']=max(time.monotonic(), dashboard.default_enable_after + .001)
            dashboard.maybe_default_enable()
        self.assertFalse(any(c.args[0].endswith('/servo/arm') and c.args[1].get('enabled')
                             for c in calls.call_args_list))

    def test_device_stop_cancels_pending_enable(self):
        dashboard = ready_dashboard('simulation')
        with patch('server.fetch', side_effect=self.responder(dashboard)) as calls:
            dashboard.action('/api/source', {'source': 'simulation'})
            dashboard.watcher['data']['last_stop_reason'] = 'button_stop'
            dashboard.observed['watcher']=max(time.monotonic(), dashboard.default_enable_after + .001)
            dashboard.maybe_default_enable()
        self.assertFalse(any(c.args[0].endswith('/servo/arm') and c.args[1].get('enabled')
                             for c in calls.call_args_list))

    def test_forward_failure_cancels_pending_enable(self):
        dashboard = ready_dashboard()
        dashboard.default_enable_pending = True
        with patch('server.fetch', side_effect=OSError('offline')):
            dashboard.forward_inputs(time.monotonic())
        self.assertFalse(dashboard.default_enable_pending)

    def test_auto_enable_uses_atomic_stop_generation_and_no_second_stop(self):
        dashboard=ready_dashboard('simulation')
        dashboard.default_enable_pending=True
        with patch('server.fetch', side_effect=self.responder(dashboard)) as calls:
            dashboard.maybe_default_enable()
        arm=next(c for c in calls.call_args_list if c.args[0].endswith('/servo/arm'))
        self.assertEqual(arm.args[1], {'enabled':True,'expected_stop_generation':7,'expected_source':'simulation'})
        self.assertNotIn('http://watcher/stop',[c.args[0] for c in calls.call_args_list])

    def test_stop_generation_changed_cannot_auto_enable_after_reason_overwritten(self):
        dashboard=ready_dashboard('simulation')
        dashboard.default_enable_pending=True
        dashboard.watcher['data'].update(stop_generation=8,last_stop_reason='input_stop')
        with patch('server.fetch') as calls:dashboard.maybe_default_enable()
        calls.assert_not_called()
        self.assertFalse(dashboard.default_enable_pending)

    def test_old_firmware_waits_for_upgrade_instead_of_unprotected_auto_arm(self):
        dashboard=ready_dashboard('simulation')
        dashboard.default_enable_pending=True
        dashboard.watcher['data'].pop('output_policy_revision')
        with patch('server.fetch') as calls:dashboard.maybe_default_enable()
        calls.assert_not_called()
        self.assertTrue(dashboard.default_enable_pending)
        self.assertEqual(dashboard.output_enable_reason,'firmware_update')

    def test_camera_poll_from_previous_source_cannot_cancel_new_enable(self):
        dashboard=ready_dashboard()
        dashboard.default_enable_pending=True
        before=dashboard.camera['data'].copy()
        def old_reply(url, body=None, **kwargs):
            dashboard.generation+=1  # Source changes while the HTTP read is in flight.
            return dict(before,observation_state='error',recognition_instance_id='old-service')
        with patch('server.fetch',side_effect=old_reply):
            self.assertFalse(dashboard.poll('camera','http://camera'))
        self.assertEqual(dashboard.camera['data'],before)
        self.assertTrue(dashboard.default_enable_pending)

    def test_equal_clock_tick_cannot_arm_from_pre_selection_status(self):
        # Python 3.12 Windows monotonic ticks can match across source selection.
        with patch('server.time.monotonic', return_value=1000):
            dashboard = ready_dashboard('simulation')
            with patch('server.fetch', side_effect=self.responder(dashboard)) as calls:
                dashboard.action('/api/source', {'source': 'simulation'})
                dashboard.maybe_default_enable()
        self.assertFalse(any(c.args[0].endswith('/servo/arm') and c.args[1].get('enabled')
                             for c in calls.call_args_list))
        self.assertTrue(dashboard.default_enable_pending)

    def test_status_before_source_selection_cannot_arm_from_old_cache(self):
        dashboard=ready_dashboard('simulation')
        with patch('server.fetch',side_effect=self.responder(dashboard)) as calls:
            dashboard.action('/api/source',{'source':'simulation'})
            dashboard.maybe_default_enable()
        self.assertFalse(any(c.args[0].endswith('/servo/arm') and c.args[1].get('enabled')
                             for c in calls.call_args_list))
        self.assertTrue(dashboard.default_enable_pending)


if __name__ == '__main__':
    unittest.main()

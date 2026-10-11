import time
import unittest
from unittest.mock import patch
import server


class ContinuousOutputTests(unittest.TestCase):
    def dashboard(self, source='camera'):
        d = server.Dashboard('http://watcher', 'http://camera')
        d.engine.set_source(source)
        d.watcher = {'online': True, 'error': '', 'data': {
            'output_policy_revision': 'continuous-enable-1',
            'default_output_enabled': True, 'outputs_enabled': False,
            'input_source': source, 'stop_generation': 5}}
        d.observed['watcher'] = time.monotonic()
        return d

    def test_startup_owns_camera_without_an_extra_enable_click(self):
        d = self.dashboard()
        self.assertTrue(d.diagnostic_active)
        self.assertFalse(d.forward_paused)
        self.assertEqual(d.snapshot()['control_policy_revision'], 'continuous-enable-1')

    def test_stop_retains_camera_and_does_not_send_disarm(self):
        d = self.dashboard()
        d.diagnostic_active = True
        calls = []
        def rpc(url, body=None, **kwargs):
            calls.append((url, body))
            return {'ok': True, 'confirmation_generation': 1}
        with patch.object(server, 'fetch', rpc):
            d.action('/api/stop', {})
        self.assertEqual(d.engine.source, 'camera')
        self.assertTrue(d.diagnostic_active)
        self.assertFalse(d.forward_paused)
        self.assertFalse(any(url.endswith('/servo/arm') for url, _ in calls))
        self.assertTrue(any(url.endswith('/stop') for url, _ in calls))

    def test_firmware_owns_continuous_enable_no_arm_rpc_on_poll(self):
        d = self.dashboard('simulation')
        d.diagnostic_active = True
        with patch.object(server, 'fetch') as rpc:
            d.maybe_default_enable()
        rpc.assert_not_called()
        self.assertTrue(d.default_enable_pending)
        self.assertEqual(d.output_enable_reason, 'pending')
        d.watcher['data']['outputs_enabled'] = True
        d.maybe_default_enable()
        self.assertFalse(d.default_enable_pending)
        self.assertEqual(d.output_enable_reason, 'enabled')

    def test_explicit_disable_is_respected(self):
        d = self.dashboard('simulation')
        d.diagnostic_active = True
        d.watcher['data']['default_output_enabled'] = False
        with patch.object(server, 'fetch') as rpc:
            d.maybe_default_enable()
        rpc.assert_not_called()
        self.assertFalse(d.default_enable_pending)
        self.assertEqual(d.output_enable_reason, 'manual_disable')

    def test_source_switch_does_not_permanently_disable_default(self):
        d = self.dashboard('simulation')
        calls = []
        def rpc(url, body=None, **kwargs):
            calls.append((url, body))
            return {'ok': True, 'stop_generation': 6}
        with patch.object(server, 'fetch', rpc):
            d.action('/api/source', {'source': 'simulation'})
        self.assertFalse(any(url.endswith('/servo/arm') and body == {'enabled': False}
                             for url, body in calls))

    def test_missing_recognition_suspends_motion_not_default_policy(self):
        d = self.dashboard()
        d.diagnostic_active = True
        d.camera = {'online': False, 'error': '', 'data': {}}
        d.engine.last_sent = 'pinch'
        calls = []
        with patch.object(server, 'fetch', lambda url, body=None, **kw: calls.append((url, body)) or {'ok': True}):
            d.forward_inputs(time.monotonic())
        self.assertTrue(any(url.endswith('/suspend') for url, _ in calls))

    def test_failed_simulation_cannot_replay_after_reconnect(self):
        d = self.dashboard('simulation')
        d.engine.simulate('pinch', 2000, time.monotonic())
        with patch.object(server, 'fetch', side_effect=OSError('connection lost')):
            d.forward_inputs(time.monotonic())
        self.assertEqual(d.engine.gesture, 'stop')
        self.assertEqual(d.engine.source, 'simulation')

    def test_offline_status_clears_cached_simulation(self):
        d = self.dashboard('simulation')
        d.engine.simulate('pinch', 2000, time.monotonic())
        with patch.object(server, 'fetch', side_effect=OSError('offline')):
            d.poll('watcher', d.watcher_url)
        self.assertEqual(d.engine.gesture, 'stop')

    def test_changed_peer_clears_cached_simulation(self):
        d = self.dashboard('simulation')
        d.watcher['data']['client_connection_id'] = 1
        d.engine.simulate('pinch', 2000, time.monotonic())
        reply = dict(d.watcher['data'], client_connection_id=2)
        with patch.object(server, 'fetch', return_value=reply):
            d.poll('watcher', d.watcher_url)
        self.assertEqual(d.engine.gesture, 'stop')

    def test_service_exit_suspends_without_latching_default_off(self):
        d = self.dashboard('simulation')
        d.engine.simulate('pinch', 2000, time.monotonic())
        calls = []
        with patch.object(server, 'fetch', lambda url, body=None, **kw: calls.append((url, body)) or {'ok': True}):
            d.stop_service()
        self.assertEqual(d.engine.gesture, 'stop')
        self.assertTrue(d.forward_paused)
        self.assertEqual(calls, [('http://watcher/suspend', {})])


if __name__ == '__main__':
    unittest.main()

import unittest
from unittest.mock import Mock
import launch


class LaunchOutputPolicyTests(unittest.TestCase):
    def test_current_startup_preserves_default_permission(self):
        rpc = Mock(return_value={'ok': True})
        launch.switch_camera_source('http://watcher', {'output_policy_revision': 'continuous-enable-1'}, rpc)
        self.assertEqual([c.args for c in rpc.call_args_list], [
            ('http://watcher/suspend', {}),
            ('http://watcher/source', {'source': 'camera'})])

    def test_legacy_startup_keeps_explicit_disable(self):
        rpc = Mock(return_value={'ok': True})
        launch.switch_camera_source('http://watcher', {}, rpc)
        self.assertEqual([c.args for c in rpc.call_args_list], [
            ('http://watcher/stop', {}),
            ('http://watcher/servo/arm', {'enabled': False}),
            ('http://watcher/source', {'source': 'camera'})])

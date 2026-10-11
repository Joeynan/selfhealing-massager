"""Session ownership checks; all requests and child processes are mocked."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import launch

WATCHER = 'http://watcher-test:8080'
DASHBOARD = 'http://127.0.0.1:8890'


class LaunchSessionOwnershipTests(unittest.TestCase):
    def launch_case(self, camera=False, dashboard=False, owner_error=None,
                    dashboard_release='wifi-camera-v8', camera_version=2,
                    startup_error=None):
        events = []
        mutations = []
        children = []
        camera_state = {'observation_version': camera_version, 'recognition_instance_id': 'existing-camera',
                        'transport': 'wifi', 'camera_url': 'http://watcher-test:8081/frame',
                        'watcher_id': 'watcher-test'}
        dashboard_state = {'software_release': dashboard_release, 'control_policy_revision': 'continuous-enable-1',
                           'watcher_url': WATCHER}
        device = {'firmware': 'watcher-servo-controller-v9-wheel', 'watcher_id': 'watcher-test',
                  'output_policy_revision': 'continuous-enable-1'}

        def request(req, **_kwargs):
            events.append(('request', req.full_url, req.data))
            if req.data is not None:
                mutations.append((req.full_url, json.loads(req.data)))
                response = {'ok': True}
            elif req.full_url == WATCHER + '/status':
                response = device
            elif req.full_url == 'http://127.0.0.1:8877/status':
                response = camera_state
            elif req.full_url == DASHBOARD + '/api/status':
                response = dashboard_state
            else:
                raise AssertionError('Unexpected mocked URL: ' + req.full_url)
            return io.StringIO(json.dumps(response))

        def owner(service, port):
            events.append(('owner', service, port))
            if service == owner_error:
                raise RuntimeError('无法确认属于当前工程')

        def popen(argv, **_kwargs):
            events.append(('child', argv))
            if startup_error == 'dashboard-spawn' and str(ROOT / 'server.py') in argv:
                raise OSError('dashboard spawn failed')
            child = Mock(pid=100 + len(children))
            child.poll.return_value = None
            children.append(child)
            return child

        def wait(port, *_args):
            events.append(('ready', port))
            if startup_error == 'camera-ready' and port == 8877:
                raise RuntimeError('camera startup failed')

        opener = Mock()
        opener.open.side_effect = request
        apps = {8877: 'watcher-handnodes' if camera else None,
                8890: 'watcher-control-dashboard' if dashboard else None}
        with tempfile.TemporaryDirectory() as folder, patch.object(launch, 'WORK', Path(folder)), \
             patch.object(launch, 'application', side_effect=lambda port: apps[port]), \
             patch.object(launch, 'validate_service_owner', side_effect=owner), \
             patch.object(launch, 'select_python', return_value=Path(folder) / 'venv/bin/python'), \
             patch.object(launch, 'wait_ready', side_effect=wait), \
             patch.object(launch, 'build_opener', return_value=opener), \
             patch.object(launch.subprocess, 'Popen', side_effect=popen), \
             patch.object(launch.webbrowser, 'open', return_value=True) as browser, \
             patch.object(launch, 'process_birth', return_value=10.0), \
             patch.object(launch.time, 'sleep', side_effect=KeyboardInterrupt), \
             patch('builtins.input'), contextlib.redirect_stdout(io.StringIO()), \
             patch.object(sys, 'argv', ['launch.py', '--wifi-camera', '--watcher-url', WATCHER]):
            result = launch.main()
        return result, events, mutations, children, browser

    def test_camera_ownership_failure_never_mutates_device(self):
        result, _, mutations, children, browser = self.launch_case(camera=True, dashboard=True, owner_error='camera')
        self.assertEqual(result, 1)
        self.assertEqual(mutations, [])
        self.assertEqual(children, [])
        browser.assert_not_called()

    def test_dashboard_ownership_failure_precedes_new_camera_and_device_mutations(self):
        result, _, mutations, children, browser = self.launch_case(dashboard=True, owner_error='dashboard')
        self.assertEqual(result, 1)
        self.assertEqual(mutations, [])
        self.assertEqual(children, [])
        browser.assert_not_called()

    def test_dashboard_version_failure_precedes_new_camera_and_device_mutations(self):
        result, _, mutations, children, _ = self.launch_case(dashboard=True, dashboard_release='old-release')
        self.assertEqual(result, 1)
        self.assertEqual(mutations, [])
        self.assertEqual(children, [])

    def test_camera_version_failure_never_mutates_device(self):
        result, _, mutations, children, _ = self.launch_case(camera=True, dashboard=True, camera_version=1)
        self.assertEqual(result, 1)
        self.assertEqual(mutations, [])
        self.assertEqual(children, [])

    def test_reusing_two_services_only_opens_browser_without_stop_or_source_change(self):
        result, events, mutations, children, browser = self.launch_case(camera=True, dashboard=True)
        self.assertEqual(result, 0)
        self.assertIn(('owner', 'camera', 8877), events)
        self.assertIn(('owner', 'dashboard', 8890), events)
        self.assertEqual(mutations, [])
        self.assertEqual(children, [])
        browser.assert_called_once_with(DASHBOARD + '/', new=2)

    def test_existing_camera_without_dashboard_is_rejected_without_ownership(self):
        result, _, mutations, children, browser = self.launch_case(camera=True)
        self.assertEqual(result, 1)
        self.assertEqual(mutations, [])
        self.assertEqual(children, [])
        browser.assert_not_called()

    def test_existing_dashboard_without_camera_is_rejected_without_ownership(self):
        result, _, mutations, children, browser = self.launch_case(dashboard=True)
        self.assertEqual(result, 1)
        self.assertEqual(mutations, [])
        self.assertEqual(children, [])
        browser.assert_not_called()

    def test_new_session_ctrl_c_stops_only_its_own_session_and_children(self):
        result, events, mutations, children, browser = self.launch_case()
        self.assertEqual(result, 0)
        self.assertEqual(len(children), 2)
        self.assertEqual([url for url, _ in mutations], [WATCHER + '/suspend', WATCHER + '/source',
                                                       DASHBOARD + '/api/source', WATCHER + '/stop'])
        first_mutation = next(i for i, event in enumerate(events) if event[0] == 'request' and event[2] is not None)
        self.assertGreater(first_mutation, events.index(('ready', 8890)))
        for child in children:
            child.terminate.assert_called_once()
        browser.assert_called_once()

    def test_failed_new_camera_without_dashboard_does_not_stop_device(self):
        result, _, mutations, children, browser = self.launch_case(startup_error='camera-ready')
        self.assertEqual(result, 1)
        self.assertEqual(mutations, [])
        self.assertEqual(len(children), 1)
        children[0].terminate.assert_called_once()
        browser.assert_not_called()

    def test_failed_dashboard_spawn_does_not_acquire_partial_session(self):
        result, _, mutations, children, browser = self.launch_case(startup_error='dashboard-spawn')
        self.assertEqual(result, 1)
        self.assertEqual(mutations, [])
        self.assertEqual(len(children), 1)
        children[0].terminate.assert_called_once()
        browser.assert_not_called()


if __name__ == '__main__':
    unittest.main()

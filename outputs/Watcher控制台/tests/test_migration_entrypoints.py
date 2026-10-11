"""Entry points only: network calls and child processes are mocked."""
import contextlib
import io
import importlib.util
import json
from pathlib import Path
import runpy
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import launch


class MigrationEntryPointTests(unittest.TestCase):
    def test_runtime_configuration_is_relative_to_its_directory(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(launch, 'WORK', Path(folder)):
            (Path(folder) / 'runtime.json').write_text('{"python":"venv/bin/python"}')
            self.assertEqual(launch.runtime_candidates()[0], (Path(folder) / 'venv/bin/python').resolve())

    def test_runtime_does_not_fall_back_to_old_temporary_or_cache_paths(self):
        for candidate in launch.runtime_candidates():
            self.assertTrue(candidate.is_relative_to(ROOT.parents[1]), candidate)

    def test_old_absolute_runtime_configuration_is_ignored(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(launch, 'WORK', Path(folder)):
            (Path(folder) / 'runtime.json').write_text('{"python":"/private/tmp/old/bin/python"}')
            self.assertNotIn(Path('/private/tmp/old/bin/python'), launch.runtime_candidates())

    def test_runtime_configuration_cannot_escape_runtime_directory(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(launch, 'WORK', Path(folder)):
            (Path(folder) / 'runtime.json').write_text('{"python":"../../old/bin/python"}')
            self.assertEqual(launch.runtime_candidates(), [launch.venv_python(Path(folder) / 'venv')])

    def test_v9_wifi_firmware_is_supported(self):
        self.assertTrue(launch.wifi_firmware_supported('watcher-servo-controller-v9-wheel'))
        self.assertFalse(launch.wifi_firmware_supported('watcher-servo-controller-v6'))

    def test_offline_and_custom_port_options_are_available(self):
        with contextlib.redirect_stderr(io.StringIO()):
            try:
                options = launch.parse_options(['--offline', '--no-browser', '--dashboard-port', '8895'])
            except SystemExit:
                self.fail('offline, no-browser and dashboard-port options are missing')
        self.assertTrue(options.offline)
        self.assertTrue(options.no_browser)
        self.assertEqual(options.dashboard_port, 8895)

    def test_invalid_dashboard_port_is_rejected(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            launch.parse_options(['--dashboard-port', '0'])

    def test_service_status_endpoint_follows_service_identity(self):
        response = Mock()
        response.__enter__ = Mock(return_value=io.StringIO('{"application":"watcher-control-dashboard"}'))
        response.__exit__ = Mock(return_value=False)
        self.assertTrue(hasattr(launch, 'LOCAL_OPENER'), 'local status requests must bypass inherited proxies')
        with patch.object(launch.LOCAL_OPENER, 'open', return_value=response) as fetch:
            self.assertEqual(launch.application(8895), 'watcher-control-dashboard')
        self.assertEqual(fetch.call_args.args[0], 'http://127.0.0.1:8895/api/status')

    def test_existing_service_requires_current_project_metadata(self):
        self.assertTrue(hasattr(launch, 'validate_service_owner'), 'service ownership guard is missing')
        with tempfile.TemporaryDirectory() as folder, patch.object(launch, 'WORK', Path(folder)), patch.object(launch.subprocess, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, '当前工程'):
                launch.validate_service_owner('dashboard', 8895)
            run.assert_not_called()

    def test_existing_service_from_another_root_is_not_reused(self):
        self.assertTrue(hasattr(launch, 'validate_service_owner'), 'service ownership guard is missing')
        with tempfile.TemporaryDirectory() as folder, patch.object(launch, 'WORK', Path(folder)), patch.object(launch.subprocess, 'run') as run:
            (Path(folder) / 'dashboard-8895.json').write_text(json.dumps({'project_root': '/other/project', 'pid': 123, 'script': 'outputs/Watcher控制台/server.py'}))
            with self.assertRaisesRegex(RuntimeError, '当前工程'):
                launch.validate_service_owner('dashboard', 8895)
            run.assert_not_called()

    def test_offline_starts_only_dashboard_and_keeps_normal_settings(self):
        child = Mock(pid=123)
        child.poll.return_value = None
        opener = Mock()
        reserved = [Mock(), Mock()]
        reserved[0].getsockname.return_value = ('127.0.0.1', 55001)
        reserved[1].getsockname.return_value = ('127.0.0.1', 55002)
        with tempfile.TemporaryDirectory() as folder, patch.object(launch, 'WORK', Path(folder)), \
             patch.object(launch, 'application', return_value=None), patch.object(launch, 'wait_ready'), \
             patch.object(launch, 'build_opener', return_value=opener), \
             patch.object(launch.socket, 'socket', side_effect=reserved), \
             patch.object(launch.subprocess, 'Popen', return_value=child) as popen, \
             patch.object(launch, 'process_birth', return_value=10.0), \
             patch.object(launch, 'base_python', return_value=launch.BASE_PYTHON), \
             patch.object(launch.subprocess, 'run') as run, \
             patch.object(launch.time, 'sleep', side_effect=KeyboardInterrupt), \
             patch('builtins.input'), \
             patch.object(sys, 'argv', ['launch.py', '--offline', '--no-browser', '--dashboard-port', '8895', '--wifi-camera']):
            normal_settings = Path(folder) / 'settings.json'
            normal_settings.write_text('{"watcher_url":"http://saved-device:8080"}')
            try:
                launch.main()
            except SystemExit:
                self.fail('offline startup is missing')
            self.assertEqual(popen.call_count, 1)
            argv = popen.call_args.args[0]
            self.assertIn(str(ROOT / 'server.py'), argv)
            self.assertEqual(argv[argv.index('--port') + 1], '8895')
            config = json.loads(Path(argv[argv.index('--config') + 1]).read_text())
            self.assertTrue(config['watcher_url'].startswith('http://127.0.0.1:'))
            self.assertTrue(config['camera_url'].startswith('http://127.0.0.1:'))
            self.assertNotEqual(config['watcher_url'], config['camera_url'])
            self.assertEqual(json.loads(normal_settings.read_text())['watcher_url'], 'http://saved-device:8080')
            opener.open.assert_not_called()
            run.assert_not_called()
            child.terminate.assert_called_once()
            for endpoint in reserved:
                endpoint.bind.assert_called_once_with(('127.0.0.1', 0))
                endpoint.listen.assert_not_called()
                endpoint.close.assert_called_once()

    def test_camera_child_uses_project_source_data_and_cache_directories(self):
        child = Mock(pid=123)
        child.poll.return_value = None
        device = {'firmware': 'watcher-servo-controller-v9-wheel', 'watcher_id': 'watcher-test',
                  'output_policy_revision': 'continuous-enable-1'}
        opener = Mock()
        opener.open.side_effect = lambda *_args, **_kwargs: io.StringIO(json.dumps(dict(device, ok=True)))
        with tempfile.TemporaryDirectory() as folder, patch.object(launch, 'WORK', Path(folder)), \
             patch.object(launch, 'application', return_value=None), patch.object(launch, 'wait_ready'), \
             patch.object(launch, 'select_python', return_value=Path(folder) / 'venv/bin/python'), \
             patch.object(launch, 'build_opener', return_value=opener), \
             patch.object(launch.subprocess, 'Popen', return_value=child) as popen, \
             patch.object(launch, 'process_birth', return_value=10.0), \
             patch.object(launch, 'base_python', return_value=launch.BASE_PYTHON), \
             patch.object(launch.subprocess, 'run') as run, \
             patch.object(launch.time, 'sleep', side_effect=KeyboardInterrupt), \
             patch('builtins.input'), \
             patch.object(sys, 'argv', ['launch.py', '--wifi-camera', '--no-browser']):
            self.assertEqual(launch.main(), 0)
            self.assertEqual(popen.call_count, 2)
            camera = popen.call_args_list[0]
            argv = camera.args[0]
            self.assertIn(str(ROOT / 'camera/landmark_server.py'), argv)
            self.assertEqual(argv[argv.index('--data-dir') + 1], str(Path(folder) / 'camera-data'))
            self.assertIn('--camera-url', argv)
            self.assertNotIn('--port', argv)
            self.assertIn('env', camera.kwargs, 'camera child needs project-local cache configuration')
            self.assertEqual(camera.kwargs['env']['MPLCONFIGDIR'], str(Path(folder) / 'matplotlib'))
            self.assertEqual(camera.kwargs['env']['XDG_CACHE_HOME'], str(Path(folder) / 'cache'))
            self.assertNotIn('PYTHONHOME', camera.kwargs['env'])
            self.assertNotIn('PYTHONPATH', camera.kwargs['env'])
            run.assert_not_called()

    def test_existing_service_must_own_its_listening_port_and_script(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(launch, 'WORK', Path(folder)), \
             patch.object(launch, 'process_birth', return_value=10.0):
            launch.record_service_owner('dashboard', 8895, Mock(pid=123), ROOT / 'server.py')
            with patch.object(launch, 'verify_listener_owner') as verify:
                launch.validate_service_owner('dashboard', 8895)
                verify.assert_called_once_with(123, ROOT/'server.py', 8895, 10.0)
            with patch.object(launch, 'verify_listener_owner', side_effect=RuntimeError('wrong owner')):
                with self.assertRaisesRegex(RuntimeError, '当前工程'):
                    launch.validate_service_owner('dashboard', 8895)

    def test_installer_uses_project_python_and_relative_runtime_configuration(self):
        spec = importlib.util.spec_from_file_location('migration_installer', ROOT/'install_runtime.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with patch.object(module, 'base_python', return_value=launch.BASE_PYTHON), \
             patch.object(module, 'ensure_model'), patch.object(module, 'load_settings'), \
             patch('subprocess.run') as run, patch('builtins.input'), \
             patch.object(Path, 'mkdir'), patch.object(Path, 'is_dir', return_value=True), \
             patch.object(Path, 'write_text') as write:
            self.assertEqual(module.main(['--wheel-dir', str(ROOT.parents[1]/'work/wheels')]), 0)
        first = run.call_args_list[0].args[0]
        self.assertEqual(first[0], str(ROOT.parents[1]/'work/tools/python-base/bin/python3.12'))
        self.assertEqual(first[-1], str(ROOT.parents[1]/'work/watcher-control-runtime/venv'))
        pip = run.call_args_list[1]
        self.assertEqual(pip.args[0][pip.args[0].index('-r') + 1], str(ROOT/'requirements-runtime.lock'))
        self.assertIn('--no-index', pip.args[0], 'portable installer must prefer local cached wheels before fetching missing ones')
        self.assertEqual(pip.args[0][pip.args[0].index('--find-links') + 1], str(ROOT.parents[1]/'work/wheels'))
        self.assertEqual(pip.kwargs['env']['PIP_CACHE_DIR'], str(ROOT.parents[1]/'work/watcher-control-runtime/cache/pip'))
        configuration = json.loads(write.call_args.args[0])
        self.assertEqual(configuration['python'], module.venv_python(module.WORK/'venv').relative_to(module.WORK).as_posix())


if __name__ == '__main__':
    unittest.main()

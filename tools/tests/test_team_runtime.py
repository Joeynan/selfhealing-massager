"""Portable teammate runtime behavior; no device or real network access."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT / 'outputs/Watcher控制台'))
import launch

try:
    import runtime_support as support
except ImportError:
    support = None


class TeamRuntimeTests(unittest.TestCase):
    def require_support(self):
        self.assertIsNotNone(support, 'portable runtime_support helper is missing')
        return support

    def test_windows_venv_and_flash_interpreters(self):
        s = self.require_support()
        self.assertEqual(s.venv_python(Path('/project/runtime/venv'), 'win32'), Path('/project/runtime/venv/Scripts/python.exe'))
        self.assertEqual(s.flash_python(Path('/project'), 'win32'), Path('/project/work/watcher-control-runtime/flash-venv/Scripts/python.exe'))

    def test_posix_venv(self):
        s = self.require_support()
        self.assertEqual(s.venv_python(Path('/project/runtime/venv'), 'darwin'), Path('/project/runtime/venv/bin/python'))

    def test_base_python_falls_back_to_current_standard_python312(self):
        s = self.require_support()
        with tempfile.TemporaryDirectory(prefix='中文 空格 ') as folder, patch.object(s, 'python_is_312', return_value=True):
            self.assertEqual(s.base_python(Path(folder)), Path(getattr(sys, '_base_executable', sys.executable)))

    def test_python311_is_rejected_with_actionable_message(self):
        s = self.require_support()
        with tempfile.TemporaryDirectory() as folder, patch.object(s, 'python_is_312', return_value=False), patch.object(s.shutil, 'which', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'Python 3.12'):
                s.base_python(Path(folder))

    def test_python_resolution_avoids_both_rebuild_targets(self):
        import inspect
        s = self.require_support()
        self.assertIn('exclude_dirs', inspect.signature(s.base_python).parameters, 'rebuild interpreter exclusion is missing')
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder); runtime = project/'work/watcher-control-runtime'
            current = runtime/'venv/bin/python'; current.parent.mkdir(parents=True); current.touch()
            base = project/'system/python312'; base.parent.mkdir(); base.touch()
            with patch.object(s.sys, 'executable', str(current)), patch.object(s.sys, '_base_executable', str(base)), \
                 patch.object(s, 'python_is_312', return_value=True):
                self.assertEqual(s.base_python(project, exclude_dirs=[runtime/'venv', runtime/'flash-venv']), base)
                with self.assertRaisesRegex(RuntimeError, '重建'):
                    s.base_python(project, current, exclude_dirs=[runtime/'venv', runtime/'flash-venv'])
                self.assertTrue(current.is_file())

    def test_explicit_wrong_python_does_not_silently_fall_back(self):
        s = self.require_support()
        with tempfile.TemporaryDirectory() as folder:
            wrong = Path(folder)/'python311'; wrong.touch()
            with patch.object(s, 'python_is_312', side_effect=lambda value: value != wrong):
                with self.assertRaisesRegex(RuntimeError, '指定'):
                    s.base_python(Path(folder), wrong)

    def test_missing_settings_seeded_from_example(self):
        s = self.require_support()
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder); example = folder/'settings.example.json'; private = folder/'settings.json'
            example.write_text('{"watcher_url":"http://192.0.2.1:8080","camera_url":"http://127.0.0.1:8877"}')
            value = s.load_settings(private, example, 'http://192.0.2.8:8080/')
            self.assertEqual(value['watcher_url'], 'http://192.0.2.8:8080')
            self.assertTrue(private.is_file())
            self.assertEqual(json.loads(private.read_text())['watcher_url'], 'http://192.0.2.1:8080')

    def test_existing_private_settings_never_overwritten(self):
        s = self.require_support()
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder); private = folder/'settings.json'; private.write_text('{"watcher_url":"http://saved:8080","camera_url":"http://127.0.0.1:8877"}')
            before = private.read_bytes()
            self.assertEqual(s.load_settings(private, folder/'missing.json', 'http://override:8080')['watcher_url'], 'http://override:8080')
            self.assertEqual(before, private.read_bytes())

    def test_model_download_hash_mismatch_leaves_no_model_or_partial(self):
        s = self.require_support()
        response = io.BytesIO(b'incorrect model'); response.headers = {}
        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder)/'hand_landmarker.task'
            with self.assertRaisesRegex(RuntimeError, '校验'):
                s.ensure_model(model, {'url':'https://example.com/model','sha256':'0'*64,'bytes':15}, opener=Mock(return_value=response))
            self.assertFalse(model.exists())
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_model_download_exact_hash_atomically_installs(self):
        import hashlib
        s = self.require_support(); content = b'verified model'
        response = io.BytesIO(content); response.headers = {'Content-Length':str(len(content))}
        with tempfile.TemporaryDirectory() as folder:
            model = Path(folder)/'hand_landmarker.task'
            s.ensure_model(model, {'url':'https://example.com/model','sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content)}, opener=Mock(return_value=response))
            self.assertEqual(model.read_bytes(), content)
            opening = Mock(side_effect=AssertionError('must reuse verified model'))
            s.ensure_model(model, {'url':'https://example.com/model','sha256':hashlib.sha256(content).hexdigest(),'bytes':len(content)}, opener=opening)

    def test_oversized_model_rejected_before_install(self):
        s = self.require_support(); response = io.BytesIO(b'x'*10); response.headers = {'Content-Length':'13000000'}
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(RuntimeError, '大小'):
                s.ensure_model(Path(folder)/'model', {'url':'https://example.com/model','sha256':'0'*64,'bytes':10}, opener=Mock(return_value=response))
            self.assertEqual(list(Path(folder).iterdir()), [])

    def fake_process(self, script, port=8890, started=10.0):
        process = Mock(); process.create_time.return_value = started
        process.cmdline.return_value = ['python.exe', str(script)]
        process.net_connections.return_value = [types.SimpleNamespace(status='LISTEN', laddr=types.SimpleNamespace(port=port))]
        return process

    def test_listener_ownership_requires_exact_script_and_birth_time(self):
        s = self.require_support(); script = Path('/project with spaces/server.py')
        fake = types.SimpleNamespace(Process=Mock(return_value=self.fake_process(script)))
        s.verify_listener_owner(123, script, 8890, 10.0, provider=fake)
        fake.Process.return_value.cmdline.return_value = ['python', str(script)+'.other']
        with self.assertRaises(RuntimeError): s.verify_listener_owner(123, script, 8890, 10.0, provider=fake)
        fake.Process.return_value = self.fake_process(script, started=20.0)
        with self.assertRaises(RuntimeError): s.verify_listener_owner(123, script, 8890, 10.0, provider=fake)

    def test_process_inspection_denied_fails_closed(self):
        s = self.require_support(); fake = types.SimpleNamespace(Process=Mock(side_effect=PermissionError('denied')))
        with self.assertRaisesRegex(RuntimeError, '归属'):
            s.verify_listener_owner(123, Path('/project/server.py'), 8890, 10.0, provider=fake)

    def test_browser_uses_portable_module(self):
        self.assertTrue(hasattr(launch, 'webbrowser'), 'launcher must use portable webbrowser module')
        self.assertNotIn("subprocess.run(['open'", Path(launch.__file__).read_text(encoding="utf-8"))

    def test_windows_runtime_metadata_is_relative_and_contained(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(launch, 'WORK', Path(folder)):
            (Path(folder)/'runtime.json').write_text('{"python":"venv/Scripts/python.exe"}')
            self.assertEqual(launch.runtime_candidates()[0], (Path(folder)/'venv/Scripts/python.exe').resolve())
            (Path(folder)/'runtime.json').write_text('{"python":"../../outside/python.exe"}')
            self.assertNotIn((Path(folder)/'../../outside/python.exe').resolve(), launch.runtime_candidates())



class TeamInstallerTests(unittest.TestCase):
    def installer(self):
        spec = importlib.util.spec_from_file_location('team_install_runtime', ROOT/'outputs/Watcher控制台/install_runtime.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        self.assertTrue(hasattr(module, 'parse_options'), 'installer has no portable modes')
        return module

    def test_windows_installer_uses_scripts_and_portable_lock(self):
        module = self.installer()
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder); console = project/'outputs/Watcher控制台'; console.mkdir(parents=True)
            (console/'camera').mkdir()
            (console/'camera/hand_landmarker.model.json').write_text('{}')
            (console/'settings.example.json').write_text('{"watcher_url":"http://192.0.2.1:8080","camera_url":"http://127.0.0.1:8877"}')
            with patch.object(module, 'ROOT', console), patch.object(module, 'PROJECT_ROOT', project), \
                 patch.object(module, 'WORK', project/'work/watcher-control-runtime'), \
                 patch.object(module, 'base_python', return_value=Path('/python.exe')), \
                 patch.object(module.sys, 'platform', 'win32'), patch.object(module, 'ensure_model'), \
                 patch.object(module.subprocess, 'run') as run, patch.object(module.sys.stdin, 'isatty', return_value=False):
                self.assertEqual(module.main([]), 0)
            install = run.call_args_list[1].args[0]
            self.assertEqual(install[0], str(project/'work/watcher-control-runtime/venv/Scripts/python.exe'))
            self.assertEqual(install[install.index('-r')+1], str(console/'requirements-runtime.lock'))
            meta = json.loads((project/'work/watcher-control-runtime/runtime.json').read_text())
            self.assertEqual(meta['python'], 'venv/Scripts/python.exe')

    def test_windows_running_venv_rebuild_stops_before_deleting_environment(self):
        module = self.installer()
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder)
            runtime = project/'work/watcher-control-runtime'
            active = runtime/'flash-venv/Scripts/python.exe'
            active.parent.mkdir(parents=True); active.write_bytes(b'protected running interpreter')
            with patch.object(module, 'PROJECT_ROOT', project), patch.object(module, 'WORK', runtime), \
                 patch.object(module, 'base_python', return_value=project/'base/python.exe'), \
                 patch.object(module.sys, 'platform', 'win32'), patch.object(module.sys, 'executable', str(active)), \
                 patch.object(module.os, 'execve') as restart, patch.object(module.subprocess, 'run') as run, \
                 patch.object(module.sys.stdin, 'isatty', return_value=False), patch('builtins.print') as message:
                self.assertEqual(module.main(['--flash-only', '--rebuild']), 1)
                restart.assert_not_called(); run.assert_not_called()
                self.assertTrue(any('Python 3.12' in str(call) for call in message.call_args_list))
            self.assertEqual(active.read_bytes(), b'protected running interpreter')

    def test_flash_only_does_not_load_or_download_camera_model(self):
        module = self.installer()
        with tempfile.TemporaryDirectory() as folder, patch.object(module, 'WORK', Path(folder)), \
             patch.object(module, 'base_python', return_value=Path('/python')), \
             patch.object(module, 'ensure_model') as model, patch.object(module, 'load_settings') as settings, \
             patch.object(module.subprocess, 'run') as run, patch.object(module.sys.stdin, 'isatty', return_value=False):
            self.assertEqual(module.main(['--flash-only']), 0)
            model.assert_not_called(); settings.assert_not_called()
            self.assertIn('flash-venv', run.call_args_list[0].args[0][-1])

    def test_local_wheels_are_tried_before_network_fallback(self):
        import subprocess
        module = self.installer()
        calls = []
        def run(arguments, **kwargs):
            calls.append(arguments)
            if '--no-index' in arguments:
                raise subprocess.CalledProcessError(1, arguments)
        with tempfile.TemporaryDirectory() as folder, patch.object(module, 'WORK', Path(folder)/'runtime'), \
             patch.object(module, 'base_python', return_value=Path('/python')), \
             patch.object(module.subprocess, 'run', side_effect=run), patch.object(module.sys.stdin, 'isatty', return_value=False):
            self.assertEqual(module.main(['--flash-only','--wheel-dir',folder]), 0)
        self.assertEqual(len(calls), 3)
        self.assertIn('--no-index', calls[1])
        self.assertNotIn('--no-index', calls[2])

    def test_offline_missing_model_is_actionable_and_never_downloads(self):
        module = self.installer()
        with tempfile.TemporaryDirectory() as folder, patch.object(module, 'ROOT', Path(folder)), \
             patch.object(module, 'WORK', Path(folder)/'runtime'), patch.object(module, 'base_python', return_value=Path('/python')), \
             patch.object(module, 'ensure_model') as model, patch.object(module.subprocess, 'run'), \
             patch.object(module.sys.stdin, 'isatty', return_value=False):
            with patch('builtins.print') as message:
                self.assertEqual(module.main(['--offline']), 1)
            self.assertTrue(any('模型' in str(call) for call in message.call_args_list))
            model.assert_not_called()

class TeamEntryTests(unittest.TestCase):
    def entry(self):
        path = ROOT/'tools/runtime_entry.py'
        self.assertTrue(path.is_file(), 'portable entry helper is missing')
        spec = importlib.util.spec_from_file_location('team_runtime_entry', path)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        return module

    def test_start_defaults_wifi_without_duplicating_explicit_mode(self):
        entry = self.entry()
        self.assertEqual(entry.start_arguments(['--watcher-url','http://test:8080']), ['--wifi-camera','--watcher-url','http://test:8080'])
        self.assertEqual(entry.start_arguments(['--offline']), ['--offline'])

    def test_windows_entry_rebuild_rejects_running_venv_before_forwarding(self):
        entry = self.entry()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            current = root/'work/watcher-control-runtime/venv/Scripts/python.exe'
            with patch.object(entry, 'ROOT', root), patch.object(entry.sys, 'platform', 'win32'), \
                 patch.object(entry.sys, 'executable', str(current)), \
                 patch.object(entry, 'base_python', return_value=root/'base/python.exe'), \
                 patch.object(entry.os, 'execv') as restart, patch.object(entry.os, 'chdir'):
                with self.assertRaisesRegex(SystemExit, 'Python 3.12'):
                    entry.main(['install', '--rebuild'])
                restart.assert_not_called()

    def test_rebuild_preserves_settings_and_refuses_symlink_environment(self):
        spec = importlib.util.spec_from_file_location('team_rebuild_installer', ROOT/'outputs/Watcher控制台/install_runtime.py')
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        with self.assertRaises(SystemExit) as caught:
            module.parse_options(['--rebuild','--check'])
        self.assertEqual(caught.exception.code, 2)
        self.assertTrue(hasattr(module, 'prepare_venv'), 'rebuild guard is missing')
        with tempfile.TemporaryDirectory() as folder:
            runtime = Path(folder)/'venv'; outside = Path(folder)/'other'; outside.mkdir(); (outside/'keep').touch(); runtime.symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, '链接'):
                module.prepare_venv(runtime, rebuild=True)
            self.assertTrue((outside/'keep').is_file())

class TeamRebuildIntegrationTests(unittest.TestCase):
    def test_fresh_clone_can_rebuild_when_started_from_its_own_venv(self):
        import shutil
        import subprocess
        with tempfile.TemporaryDirectory(prefix='selfhealing 中文 空格 ') as folder:
            project = Path(folder)
            for name in ('tools/runtime_support.py', 'outputs/Watcher控制台/install_runtime.py'):
                target = project/name; target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(ROOT/name, target)
            (project/'outputs/Watcher控制台/requirements-flash.lock').write_text('')
            runtime = project/'work/watcher-control-runtime/flash-venv'
            subprocess.run([sys.executable, '-m', 'venv', str(runtime)], check=True, capture_output=True, timeout=90)
            interpreter = runtime/('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
            original = subprocess.run([str(interpreter), str(project/'outputs/Watcher控制台/install_runtime.py'),
                '--flash-only', '--rebuild', '--offline'], capture_output=True, text=True, encoding='utf-8', timeout=90)
            if sys.platform == 'win32':
                self.assertEqual(original.returncode, 1)
                self.assertIn('Python 3.12', original.stdout)
                self.assertTrue(interpreter.is_file())
                original = subprocess.run([getattr(sys, '_base_executable', sys.executable),
                    str(project/'outputs/Watcher\u63a7\u5236\u53f0/install_runtime.py'),
                    '--flash-only', '--rebuild', '--offline'],
                    capture_output=True, text=True, encoding='utf-8', timeout=90)
            self.assertEqual(original.returncode, 0, original.stdout + original.stderr)
            self.assertTrue(interpreter.is_file())
            subprocess.run([str(interpreter), '-c', 'import sys; assert sys.version_info[:2] == (3,12)'],
                           check=True, capture_output=True, timeout=10)

if __name__ == "__main__": unittest.main()

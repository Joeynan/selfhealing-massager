"""源码配网的错误必须在 SDK/cache 操作前阻止构建，且不泄露私有值。"""
import importlib.util
import hashlib
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path, PureWindowsPath
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))
spec = importlib.util.spec_from_file_location('build_wifi_preflight', ROOT / 'tools/build_watcher.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


class BuildWifiPreflightTests(unittest.TestCase):
    def run_fake_build(self, root, arguments, before_app):
        project = root / 'work/xiaozhi-esp32'
        project.mkdir(parents=True, exist_ok=True)
        (project / 'dependencies.lock').write_bytes(b'fixed-lock')
        runtime = {'sdk': root / 'sdk', 'python': root / 'python',
                   'ninja': root / 'ninja', 'environment': {}}
        def run(command, **kwargs):
            if command[-1] == 'app':
                before_app()
                raise RuntimeError('已验证编译前状态；不执行编译器')
        with ExitStack() as context:
            for name, value in [('ROOT', root), ('PROJECT', project)]:
                context.enter_context(patch.object(build, name, value))
            for name, value in [('validate_source_wifi_config', {}), ('select_build_runtime', runtime),
                                ('metadata', {'dependencies_lock_sha256': hashlib.sha256(b'fixed-lock').hexdigest()}),
                                ('validate_sdk', None), ('apply_sdk_path_patch', None),
                                ('select_board_config', []), ('locked_template', b'# fixed sdkconfig\n'),
                                ('apply_managed_patches', {}), ('validate_config', {})]:
                context.enter_context(patch.object(build, name, return_value=value))
            context.enter_context(patch.object(build.subprocess, 'run', side_effect=run))
            context.enter_context(patch.object(sys, 'argv', ['build_watcher.py', *arguments]))
            return build.main()

    def object_fixture(self, root):
        obj = root / 'work/xiaozhi-esp32/build/esp-idf/main/CMakeFiles/__idf_main.dir/boards/sensecap-watcher-gesture/source_wifi_config.cc.obj'
        obj.parent.mkdir(parents=True)
        obj.write_bytes(b'cached without optional header')
        return obj

    def test_optional_header_refreshes_cached_object_before_app_compilation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); obj = self.object_fixture(root)
            with self.assertRaisesRegex(RuntimeError, '编译前状态'):
                self.run_fake_build(root, [], lambda: self.assertFalse(
                    obj.exists(), 'Adding an optional Wi-Fi header must not reuse the disabled object'))

    def test_preview_and_configure_only_keep_existing_application_object(self):
        for arguments in (['--dry-run'], ['--configure-only']):
            with self.subTest(arguments=arguments), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); obj = self.object_fixture(root)
                self.assertEqual(self.run_fake_build(root, arguments, lambda: self.fail('No app build expected')), 0)
                self.assertTrue(obj.exists())

    def test_linked_object_is_rejected_without_deleting_external_file(self):
        self.assertTrue(callable(getattr(build, 'invalidate_source_wifi_object', None)))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); obj = self.object_fixture(root); obj.unlink()
            outside = root / 'outside.obj'; outside.write_bytes(b'keep')
            try: obj.symlink_to(outside)
            except OSError: self.skipTest('Symlinks require privilege on this platform')
            with self.assertRaises(ValueError):build.invalidate_source_wifi_object(root / 'work/xiaozhi-esp32/build')
            self.assertEqual(outside.read_bytes(), b'keep')

    def test_windows_build_report_uses_portable_relative_path(self):
        self.assertTrue(callable(getattr(build, 'report_application_path', None)),
                        'Windows build reports must use portable relative paths')
        root = PureWindowsPath('C:/工程/selfhealing 按摩仪')
        image = root / 'work/xiaozhi-esp32/build/xiaozhi.bin'
        self.assertEqual(build.report_application_path(image, root),
                         'work/xiaozhi-esp32/build/xiaozhi.bin')

    def test_invalid_source_wifi_stops_before_sdk_or_build_cache_access(self):
        self.assertTrue(callable(getattr(build, 'validate_source_wifi_config', None)),
                        'Validate optional private source Wi-Fi before selecting the SDK')
        with patch.object(sys, 'argv', ['build_watcher.py', '--dry-run']), \
             patch.object(build, 'validate_source_wifi_config', side_effect=ValueError('源码 Wi-Fi 配置无效')) as check, \
             patch.object(build, 'select_build_runtime') as runtime:
            with self.assertRaisesRegex(ValueError, 'Wi-Fi'):
                build.main()
            check.assert_called_once_with(build.PROJECT)
            runtime.assert_not_called()


if __name__ == '__main__':
    unittest.main()

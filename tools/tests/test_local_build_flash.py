"""Offline acceptance of explicitly selected, locally rebuilt Watcher applications."""
import builtins
import copy
import hashlib
import importlib.util
import io
import json
import struct
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('local_build_flash', ROOT/'tools/flash_watcher.py')
flash = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flash)
TEMPLATE = ROOT/'tools/config/watcher-wheel-v9.sdkconfig'
TEMPLATE_SHA = '18193edabd61d6135e729872840903d666fa8b57677583e6a09c952efe0abf63'


class LocalBuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='小智 本地构建 ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root/'work/xiaozhi-esp32'
        self.directory = self.project/'build'
        self.directory.mkdir(parents=True)
        self.report_path = self.directory/'selfhealing-build-report.json'
        self.image = self.directory/'xiaozhi.bin'
        self.config = self.directory/'sdkconfig'
        self.config.write_bytes(TEMPLATE.read_bytes())
        board = self.project/'main/boards/sensecap-watcher-gesture/config.json'
        board.parent.mkdir(parents=True)
        board.write_bytes((ROOT/'work/xiaozhi-esp32/main/boards/sensecap-watcher-gesture/config.json').read_bytes())
        self.dependencies = self.project/'dependencies.lock'
        self.dependencies.write_bytes((ROOT/'work/xiaozhi-esp32/dependencies.lock').read_bytes())
        self.partition = self.directory/'partition_table/partition-table.bin'
        self.partition.parent.mkdir()
        self.partition.write_bytes(self.table())
        data = bytearray(256)
        data[0] = 0xe9
        data[12] = 9
        self.image.write_bytes(data)
        baseline = json.loads((ROOT/'tools/config/build-baseline.json').read_text())
        self.report = {
            'build_verified': True,
            'application': 'work/xiaozhi-esp32/build/xiaozhi.bin',
            'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(),
            'chip': 'esp32s3', 'application_address': '0x200000', 'hardware_access': False,
            'configuration': self.expected_config(),
            'configuration_template_sha256': TEMPLATE_SHA,
            'partition': {'name': 'ota_0', 'address': '0x200000', 'bytes': 0x400000},
            'sdk_commit': baseline['sdk_commit'],
            'source_baseline_commit': baseline['app_source_commit'],
            'managed_patches': {'changed': [], 'verified_files': len(baseline['sscma_files'])},
        }
        self.save()
        self.addCleanup(patch.stopall)
        patch.object(flash, 'ROOT', self.root).start()
        self._baseline = baseline

    @staticmethod
    def table(address=0x200000, size=0x400000):
        rows = [(1, 0, 0x10d000, 0x2000, b'otadata'),
                (0, 0x10, address, size, b'ota_0'),
                (0, 0x11, address + size, size, b'ota_1')]
        data = b''.join(struct.pack('<HBBII16sI', 0x50aa, *row, 0) for row in rows)
        return data + struct.pack('<H14s16s', 0xebeb, b'\xff'*14, hashlib.md5(data).digest()) + b'\xff'*32

    def save(self):
        self.report_path.write_text(json.dumps(self.report), encoding='utf-8')

    @staticmethod
    def expected_config():
        expected = {'CONFIG_IDF_TARGET': '"esp32s3"',
                    'CONFIG_ESPTOOLPY_FLASHSIZE_32MB': 'y',
                    'CONFIG_PARTITION_TABLE_CUSTOM': 'y',
                    'CONFIG_PARTITION_TABLE_CUSTOM_FILENAME': '"partitions/watcher-gesture.csv"',
                    'CONFIG_BOARD_TYPE_SENSECAP_WATCHER_GESTURE': 'y',
                    'CONFIG_WATCHER_GESTURE_PIPELINE': 'y',
                    'CONFIG_FREERTOS_HZ': '1000', 'CONFIG_LANGUAGE_ZH_CN': 'y'}
        board = json.loads((ROOT/'work/xiaozhi-esp32/main/boards/sensecap-watcher-gesture/config.json').read_text())
        expected.update(row.split('=', 1) for row in board['builds'][0]['sdkconfig_append'])
        return expected

    def checked(self, directory=None):
        self.assertTrue(callable(getattr(flash, 'validate_local_build', None)),
                        'Explicit local builds must be verified before reaching the existing writer')
        sys.path.insert(0, str(ROOT/'tools'))
        import build_watcher as build
        with patch.object(build, 'PROJECT', self.project):
            return flash.validate_local_build(directory or self.directory)

    def test_verified_build_creates_only_in_memory_application_manifest(self):
        release, image, manifest = self.checked()
        self.assertEqual(image, self.image)
        self.assertEqual(manifest['app'], 'xiaozhi.bin')
        self.assertEqual(manifest['address'], '0x200000')
        self.assertEqual(manifest['device_mac'], '10:b4:1d:e6:00:9c')
        self.assertEqual(manifest['sha256'], self.report['sha256'])
        self.assertTrue(callable(release.flash_checked))
        self.assertFalse((self.directory/'release-manifest.json').exists())

    def test_windows_report_relative_path_separator_is_supported(self):
        self.report['application'] = self.report['application'].replace('/', '\\')
        self.save()
        self.assertEqual(self.checked()[1], self.image)

    def test_missing_build_report_is_rejected(self):
        self.report_path.unlink()
        with self.assertRaisesRegex(ValueError, 'report|报告'):
            self.checked()

    def test_report_critical_fields_cannot_authorize_incompatible_build(self):
        original = copy.deepcopy(self.report)
        mutations = {'build_verified': False, 'hardware_access': True, 'chip': 'esp32',
                     'application_address': '0x10000', 'sdk_commit': 'unknown',
                     'source_baseline_commit': 'unknown', 'configuration_template_sha256': '0'*64,
                     'bytes': True, 'sha256': '0'*64, 'configuration': {}, 'partition': {},
                     'managed_patches': {'changed': [], 'verified_files': 0}}
        for field, value in mutations.items():
            with self.subTest(field=field):
                self.report = copy.deepcopy(original)
                self.report[field] = value
                self.save()
                with self.assertRaises(ValueError):
                    self.checked()

    def test_image_bytes_hash_chip_header_and_limit_are_checked(self):
        original = self.image.read_bytes()
        self.image.write_bytes(original + b'changed')
        with self.assertRaises(ValueError):
            self.checked()
        for data in (b'x'*256, b'\xe9' + bytes(0x400000)):
            with self.subTest(bytes=len(data)):
                self.image.write_bytes(data)
                self.report['bytes'] = len(data)
                self.report['sha256'] = hashlib.sha256(data).hexdigest()
                self.save()
                with self.assertRaises(ValueError):
                    self.checked()

    def test_configuration_report_matches_actual_isolated_sdkconfig(self):
        self.config.write_text(self.config.read_text().replace('CONFIG_FREERTOS_HZ=1000', 'CONFIG_FREERTOS_HZ=100'))
        with self.assertRaisesRegex(ValueError, 'configuration|配置'):
            self.checked()

    def test_modified_board_defaults_cannot_redefine_the_verified_configuration(self):
        board = self.project/'main/boards/sensecap-watcher-gesture/config.json'
        content = board.read_text()
        board.write_text(content.replace('CONFIG_FREERTOS_HZ=1000', 'CONFIG_FREERTOS_HZ=100'))
        self.config.write_text(self.config.read_text().replace('CONFIG_FREERTOS_HZ=1000', 'CONFIG_FREERTOS_HZ=100'))
        self.report['configuration']['CONFIG_FREERTOS_HZ'] = '100'
        self.save()
        with self.assertRaisesRegex(ValueError, 'board|configuration|基线|板型'):
            self.checked()

    def test_fixed_dependencies_are_checked(self):
        self.dependencies.write_text('modified lock')
        with self.assertRaisesRegex(ValueError, 'dependencies|依赖'):
            self.checked()

    def test_partition_report_matches_real_partition_table(self):
        self.partition.write_bytes(self.table(address=0x10000))
        with self.assertRaisesRegex(ValueError, 'partition|分区'):
            self.checked()

    def test_partition_md5_and_duplicate_ota0_are_rejected(self):
        original = self.partition.read_bytes()
        for data in (original.replace(original[-48:-32], b'X'*16), original[:96] + original[32:64] + b'\xff'*32):
            with self.subTest(table=data.hex()):
                self.partition.write_bytes(data)
                with self.assertRaises(ValueError):
                    self.checked()

    def test_report_paths_cannot_escape_or_select_a_different_image(self):
        for path in ('../xiaozhi.bin', '/tmp/xiaozhi.bin', 'work/xiaozhi-esp32/build/other.bin',
                     'work/xiaozhi-esp32/build/../build/xiaozhi.bin', 'C:\\temp\\xiaozhi.bin'):
            with self.subTest(application=path):
                self.report['application'] = path
                self.save()
                with self.assertRaisesRegex(ValueError, 'path|路径|application'):
                    self.checked()

    def test_symlinked_artifacts_and_build_directory_are_rejected(self):
        for path in (self.image, self.report_path, self.config, self.partition):
            with self.subTest(artifact=path.name):
                saved = path.with_suffix('.saved')
                path.rename(saved)
                try:
                    path.symlink_to(saved.name)
                except OSError as error:
                    saved.rename(path)
                    if getattr(error, 'winerror', None) == 1314:
                        self.skipTest('Windows symlink privilege is unavailable; guards are exercised on macOS')
                    raise
                try:
                    with self.assertRaisesRegex(ValueError, 'symlink|链接|path|路径'):
                        self.checked()
                finally:
                    path.unlink()
                    saved.rename(path)
        alias = self.directory.parent/'alias'
        alias.symlink_to(self.directory, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, 'symlink|链接|path|路径'):
            self.checked(alias)

    def test_explicit_build_and_release_or_rollback_are_mutually_exclusive(self):
        for arguments in (['--release-dir', str(self.directory)], ['--rollback']):
            with self.subTest(arguments=arguments):
                with patch.object(sys, 'argv', ['flash_watcher.py', '--build-dir', str(self.directory), *arguments, '--dry-run']), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    flash.main()
                self.assertEqual(error.exception.code, 2)

    def fake_tool(self, chip='ESP32-S3', mac='10:b4:1d:e6:00:9c', selection=None):
        spec = importlib.util.spec_from_file_location('local_flash_fakes', ROOT/'outputs/Watcher控制台/滚轮表情版/tests/test_flash_release.py')
        tests = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tests)
        class Tool(tests.FakeEsptool):
            __version__ = '5.4.0'
            def attach_flash(inner, device):
                inner.events.append(('attach', device))
            def read_flash(inner, device, address, size, **kwargs):
                inner.events.append(('read', device, address, size))
                return self.table() if address == 0x8000 else (selection or b'\xff'*0x2000)
        return Tool(chip, mac)

    def hardware_entry(self, tool, port='COM7'):
        # Only in-memory device and port doubles enter the real non-dry-run path.
        sys.path.insert(0, str(ROOT/'tools'))
        import build_watcher as build
        ports = [SimpleNamespace(device='COM7', vid=0x303a, pid=0x1001, serial_number='fixture')]
        serial_tools = SimpleNamespace(list_ports=SimpleNamespace(comports=lambda: ports))
        arguments = ['flash_watcher.py', '--build-dir', str(self.directory)]
        if port is not None:
            arguments.extend(['--port', port])
        with patch.object(build, 'PROJECT', self.project), patch.object(sys, 'argv', arguments), patch.object(sys, 'platform', 'win32'), patch.dict(sys.modules, {'esptool': tool, 'serial': SimpleNamespace(tools=serial_tools), 'serial.tools': serial_tools}), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            return flash.main()

    def test_local_build_uses_the_same_authenticated_identity_and_layout_writer(self):
        tool = self.fake_tool()
        self.assertEqual(self.hardware_entry(tool), 0)
        names = [event[0] for event in tool.events]
        self.assertEqual(names, ['detect', 'enter', 'mac', 'stub', 'attach', 'read', 'read', 'write', 'verify', 'reset', 'exit'])
        write = next(event for event in tool.events if event[0] == 'write')
        self.assertEqual(write[2], [(0x200000, self.image.read_bytes())])
        self.assertFalse(write[3]['erase_all'])

    def test_local_build_wrong_device_or_layout_cannot_write(self):
        cases = [('ESP8266', '10:b4:1d:e6:00:9c', None),
                 ('ESP32-S3', '00:11:22:33:44:55', None),
                 ('ESP32-S3', '10:b4:1d:e6:00:9c', b'\0'*0x2000)]
        for chip, mac, selection in cases:
            with self.subTest(chip=chip, mac=mac):
                tool = self.fake_tool(chip, mac, selection)
                self.assertEqual(self.hardware_entry(tool), 1)
                self.assertNotIn('write', [event[0] for event in tool.events])
                self.assertNotIn('reset', [event[0] for event in tool.events])

    def test_local_build_requires_explicit_recognized_windows_com_port(self):
        for port in (None, 'COM8'):
            with self.subTest(port=port):
                tool = self.fake_tool()
                self.assertEqual(self.hardware_entry(tool, port), 1)
                self.assertEqual(tool.events, [])

    def test_dry_run_with_unicode_space_path_never_imports_hardware(self):
        self.assertTrue(callable(getattr(flash, 'validate_local_build', None)), 'Local build selection is missing')
        original = builtins.__import__
        def reject_hardware(name, *args, **kwargs):
            if name.split('.')[0] in ('serial', 'esptool'):
                self.fail('offline local validation imported a hardware library')
            return original(name, *args, **kwargs)
        sys.path.insert(0, str(ROOT/'tools'))
        if callable(getattr(flash, 'validate_local_build', None)):
            import build_watcher as build
            patch.object(build, 'PROJECT', self.project).start()
        with patch.object(sys, 'argv', ['flash_watcher.py', '--build-dir', str(self.directory), '--dry-run']), patch('builtins.__import__', side_effect=reject_hardware), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            self.assertEqual(flash.main(), 0)


if __name__ == '__main__':
    unittest.main()

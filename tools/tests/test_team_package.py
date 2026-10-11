"""A teammate export must be source-complete without local secrets or backups."""
from pathlib import Path
import hashlib
import importlib.util
import json
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / 'tools/package_team.py'


class TeamPackageTests(unittest.TestCase):
    def module(self):
        self.assertTrue(MODULE.is_file(), 'Missing teammate packaging tool')
        spec = importlib.util.spec_from_file_location('team_package', MODULE)
        value = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(value)
        return value

    def put(self, root, name, value='source'):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding='utf-8')
        return path

    def test_active_sources_and_required_vendor_lock_are_selected(self):
        package = self.module()
        for name in ('README.md', 'tools/package_team.py', 'tools/config/watcher-wheel-v9.sdkconfig',
                     'work/xiaozhi-esp32/dependencies.lock',
                     'work/xiaozhi-esp32/main/boards/sensecap-watcher-gesture/gesture_service.cc',
                     'outputs/Watcher控制台/camera/gesture_rules.py',
                     'outputs/Watcher控制台/firmware/esp8266/watcher_controller/watcher_controller.ino'):
            self.assertTrue(package.eligible(Path(name)), name)

    def test_private_and_regenerable_files_are_never_selected(self):
        package = self.module()
        for name in ('work/esp-idf/tools/idf.py', 'work/idf-tools/python-env/bin/python',
                     'work/xiaozhi-esp32/managed_components/a/source.cc',
                     'work/xiaozhi-esp32/build/xiaozhi.bin', 'work/xiaozhi-esp32/sdkconfig',
                     'work/xiaozhi-esp32/main/assets/lang_config.h',
                     'outputs/Watcher控制台/settings.json',
                     'outputs/Watcher控制台/camera/hand_landmarker.task',
                     'outputs/Watcher控制台/firmware/esp8266/watcher_controller/wifi_settings.h',
                     'outputs/Watcher控制台/烧录记录/2026-10-11/烧录前备份/application-before.bin',
                     'docs/迁移验证/当前文件清单.json', 'work/capture/person.jpg',
                     'tools/__pycache__/private.pyc', 'tools/config/node_stubs/wifi_settings.h'):
            self.assertFalse(package.eligible(Path(name)), name)

    def test_secret_detection_reports_only_location(self):
        package = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.put(root, 'outputs/Watcher控制台/firmware/esp8266/watcher_controller/wifi_settings.h',
                     'constexpr const char* WIFI_PASSWORD = "UnitSecret98";')
            self.put(root, 'tools/accidental.py', 'text = "UnitSecret98"')
            result = package.audit(root)
            self.assertFalse(result['ok'])
            self.assertEqual(result['issues'][0]['path'], 'tools/accidental.py')
            self.assertNotIn('UnitSecret98', json.dumps(result))

    def test_safe_example_and_test_credentials_do_not_block_export(self):
        package = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.put(root, 'README.md', 'Guide')
            self.put(root, 'outputs/Watcher控制台/firmware/esp8266/watcher_controller/wifi_settings.example.h',
                     'constexpr const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";')
            self.assertTrue(package.audit(root)['ok'])

    def test_test_stub_is_selected_but_never_treated_as_private_credentials(self):
        package = self.module()
        name = 'outputs/Watcher控制台/tests/node_stubs/wifi_settings.h'
        self.assertTrue(package.eligible(Path(name)))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.put(root, 'work/control-v8/node-tests/stubs/wifi_settings.h',
                     'constexpr const char* WIFI_PASSWORD = "host-tests";')
            self.put(root, 'tools/runner.py', 'folder = "host-tests"')
            self.assertTrue(package.audit(root)['ok'])

    def test_array_credentials_are_detected_without_printing_them(self):
        package = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.put(root, 'work/private/wifi_settings.h', 'constexpr char WIFI_PASSWORD[] = "UnitSecret98";')
            self.put(root, 'tools/accidental.py', 'text = "UnitSecret98"')
            result = package.audit(root)
            self.assertFalse(result['ok'])
            self.assertNotIn('UnitSecret98', json.dumps(result))

    def test_export_has_matching_checksums_and_excludes_runtime_data(self):
        package = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / '源 目录'; root.mkdir()
            self.put(root, 'README.md', 'hello')
            self.put(root, 'outputs/Watcher控制台/settings.json', '{"private":true}')
            target = Path(folder) / '队友 副本'
            result = package.export_source(root, target)
            self.assertEqual((target / 'README.md').read_text(), 'hello')
            self.assertFalse((target / 'outputs/Watcher控制台/settings.json').exists())
            self.assertIn('README.md', result['files'])
            self.assertEqual(result['files']['README.md']['bytes'], 5)
            self.assertTrue((target / 'source-manifest.json').is_file())

    def test_existing_destination_and_source_tree_are_not_overwritten(self):
        package = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'source'; root.mkdir()
            self.put(root, 'README.md', 'hello')
            target = Path(folder) / 'existing'; target.mkdir()
            self.put(target, 'personal.txt', 'keep')
            with self.assertRaises(ValueError): package.export_source(root, target)
            with self.assertRaises(ValueError): package.export_source(root, root)
            with self.assertRaises(ValueError): package.export_source(root, root / 'tools/export')
            self.assertEqual((target / 'personal.txt').read_text(), 'keep')

    def test_selected_symlink_is_rejected(self):
        package = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            outside = root / 'private'; outside.write_text('private')
            (root / 'README.md').symlink_to(outside)
            result = package.audit(root)
            self.assertFalse(result['ok'])
            self.assertNotIn('private', json.dumps(result['issues']))

    def test_release_bytes_are_scanned_even_though_not_git_sources(self):
        package = self.module()
        issues = package.scan_sensitive('release/app.bin', b'headerUnitSecret98tail', ['UnitSecret98'])
        self.assertTrue(issues)
        self.assertNotIn('UnitSecret98', json.dumps(issues))

    def test_export_manifest_counts_only_source_files(self):
        package = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'source'; root.mkdir()
            self.put(root, 'README.md', 'hello')
            self.put(root, 'source-manifest.json', '{}')
            result = package.export_source(root, Path(folder) / 'next')
            self.assertEqual(result['file_count'], len(result['files']))
            self.assertEqual(result['bytes'], 5)

    def test_rewritten_release_manifest_cannot_replace_preserved_image(self):
        package = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / 'source'; root.mkdir()
            data = bytearray(96); data[0] = 0xe9; data[12] = 9
            for prefix, image, version in (('', 'watcher-controller-v9-wheel-face.bin', 'watcher-servo-controller-v9-wheel'),
                        ('上一版回滚/', 'watcher-controller-v8-continuous-output.bin', 'watcher-controller-v8-continuous-output')):
                relative = package.CONSOLE + '/滚轮表情版/' + prefix
                self.put(root, relative + 'release-manifest.json', json.dumps({
                    'app': image, 'chip': 'esp32s3', 'address': '0x200000',
                    'device_mac': '10:b4:1d:e6:00:9c', 'build_verified': True,
                    'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest(), 'version': version}))
                (root / relative / image).write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'preserved'):
                package.release_assets(root, Path(folder) / 'release')

    def git(self, root, *arguments):
        return subprocess.run(['git', '-C', str(root), *arguments], check=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout

    def test_staged_audit_checks_index_bytes_and_rejects_non_allowlisted_file(self):
        package = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.git(root, 'init', '-q')
            self.put(root, 'tools/accidental.py', 'const char* password = "UnitSecret98";')
            self.git(root, 'add', 'tools/accidental.py')
            self.put(root, 'tools/accidental.py', 'clean working copy')
            result = package.audit_staged(root)
            self.assertFalse(result['ok'])
            self.assertNotIn('UnitSecret98', json.dumps(result))
            self.assertEqual(result['issues'][0]['path'], 'tools/accidental.py')
            self.put(root, 'private.env', 'personal')
            self.git(root, 'add', '-f', 'private.env')
            result = package.audit_staged(root)
            self.assertTrue(any(i['path'] == 'private.env' and i['reason'] == 'outside_allowlist' for i in result['issues']))

    def test_git_index_preserves_manifest_bytes_on_crlf_source(self):
        package = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.git(root, 'init', '-q')
            self.put(root, '.gitattributes', (ROOT / '.gitattributes').read_text())
            source = self.put(root, 'tools/example.py', 'temporary')
            source.write_bytes(b'print("example")\r\n')
            self.git(root, 'add', '.')
            result = package.audit_staged(root)
            self.assertTrue(result['ok'])
            self.assertEqual(result['files']['tools/example.py']['sha256'], hashlib.sha256(source.read_bytes()).hexdigest())

    def test_staged_audit_rejects_index_symlink(self):
        package = self.module()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.git(root, 'init', '-q')
            target = self.put(root, 'private', 'secret')
            (root / 'README.md').symlink_to(target)
            self.git(root, 'add', 'README.md')
            result = package.audit_staged(root)
            self.assertFalse(result['ok'])
            self.assertEqual(result['issues'][0]['reason'], 'unsupported_index_mode')

    def test_pem_parser_marker_is_not_a_key_but_complete_key_is_blocked(self):
        package = self.module()
        self.assertFalse(package.scan_sensitive('release/app.bin', b'prefix-----BEGIN PRIVATE KEY-----\x00parser\x00'))
        key = b'-----BEGIN PRIVATE KEY-----\n' + b'M' * 96 + b'\n-----END PRIVATE KEY-----'
        self.assertTrue(package.scan_sensitive('release/app.bin', key))


if __name__ == '__main__': unittest.main()

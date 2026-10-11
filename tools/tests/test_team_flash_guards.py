"""No hardware is opened: exercise the public entry and authenticated adapter."""
import builtins, hashlib, importlib.util, io, json, struct, sys, tempfile, unittest, zlib
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('team_flash', ROOT/'tools/flash_watcher.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)

def table(address=0x200000, size=0xc00000):
    entries = [(1, 0, 0x10d000, 0x2000, b'otadata'),
               (0, 0x10, address, size, b'ota_0'),
               (0, 0x11, address+size, size, b'ota_1')]
    return b''.join(struct.pack('<HBBII16sI', 0x50aa, *r, 0) for r in entries) + b'\xff'*32

def ota(seq=1, state=2, invalid_crc=False):
    record = struct.pack('<I20sII', seq, b'\xff'*20, state,
                         zlib.crc32(struct.pack('<I', seq), 0xffffffff) ^ int(invalid_crc))
    return record + b'\xff'*(0x2000-len(record))

class LayoutTests(unittest.TestCase):
    def layout(self, part=None, selection=None):
        self.assertTrue(callable(getattr(m, 'validate_device_layout', None)),
                        'Before a write, inspect actual partition table and OTA selection')
        return m.validate_device_layout(part or table(), selection or ota(), 2879808)
    def test_factory_layout_and_selected_ota0_accepted(self):
        self.assertEqual(self.layout()['application_address'], 0x200000)
    def test_four_megabyte_layout_also_fits_release(self):
        self.assertEqual(self.layout(table(size=0x400000))['application_bytes'], 0x400000)
    def test_wrong_partition_address_cannot_write(self):
        with self.assertRaisesRegex(ValueError, 'partition|分区'): self.layout(table(address=0x10000))
    def test_selected_ota1_cannot_write(self):
        with self.assertRaisesRegex(ValueError, 'ota_0'): self.layout(selection=ota(2))
    def test_corrupt_ota_record_is_not_accepted_as_erased(self):
        with self.assertRaisesRegex(ValueError, 'CRC|OTA'): self.layout(selection=ota(invalid_crc=True))
    def test_erased_ota_selects_ota0_without_factory(self):
        self.assertEqual(self.layout(selection=b'\xff'*0x2000)['selected_application'], 'ota_0')
    def test_newest_valid_record_controls_selection(self):
        selection = bytearray(ota(1)); selection[4096:4128] = ota(2)[:32]
        with self.assertRaisesRegex(ValueError, 'ota_0'): self.layout(selection=bytes(selection))
    def test_overlap_with_saved_configuration_is_rejected(self):
        overlapping=struct.pack('<HBBII16sI',0x50aa,1,2,0x180000,0x100000,b'nvs',0)+table()
        with self.assertRaisesRegex(ValueError,'overlap|重叠'):self.layout(overlapping)
    def test_unrecognized_third_ota_partition_cannot_change_selection_math(self):
        third=struct.pack('<HBBII16sI',0x50aa,0,0x12,0x1a00000,0x100000,b'ota_2',0)
        with self.assertRaisesRegex(ValueError,'partition|分区'):self.layout(third+table())

class PortTests(unittest.TestCase):
    def test_explicit_windows_ch342_port_is_a_candidate(self):
        row = SimpleNamespace(device='COM7', vid=0x1a86, pid=0x55d2, serial_number='5AF9164570')
        self.assertIn('COM7', m.candidate_ports([row]))
    def test_unknown_windows_bridge_is_rejected(self):
        row = SimpleNamespace(device='COM7', vid=0x1a86, pid=0x7523, serial_number=None)
        self.assertEqual(m.candidate_ports([row]), [])

class EntryTests(unittest.TestCase):
    def test_release_dir_is_offline_and_never_imports_serial(self):
        original = builtins.__import__
        def reject_hardware(name, *args, **kwargs):
            if name.split('.')[0] in ('esptool', 'serial'): self.fail('offline check imported hardware library')
            return original(name, *args, **kwargs)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);image=root/'app.bin';image.write_bytes(b'offline fixture')
            manifest={'bytes':image.stat().st_size,'sha256':hashlib.sha256(image.read_bytes()).hexdigest(),'device_mac':'10:b4:1d:e6:00:9c'}
            with patch.object(sys, 'argv', ['flash_watcher.py', '--release-dir', str(root), '--dry-run']), patch.object(m,'validate_release',return_value=(None,image,manifest)), patch('builtins.__import__', side_effect=reject_hardware), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(m.main(), 0)
    def test_modified_release_manifest_cannot_authorize_new_image(self):
        self.assertTrue(callable(getattr(m, 'validate_release', None)), 'Only immutable verified releases are authorized')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); data = bytearray(96); data[0]=0xe9; data[12]=9
            (root/'watcher-controller-v9-wheel-face.bin').write_bytes(data)
            (root/'release-manifest.json').write_text(json.dumps({'build_verified':True,'chip':'esp32s3', 'address':'0x200000', 'device_mac':'10:b4:1d:e6:00:9c', 'app':'watcher-controller-v9-wheel-face.bin','bytes':96,'sha256':hashlib.sha256(data).hexdigest()}))
            with self.assertRaisesRegex(ValueError, '发布|release'): m.validate_release(root, False)
    def test_clean_clone_without_release_image_explains_download(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'release-manifest.json').write_text(json.dumps({'app':m.RELEASES[False][0]}))
            with self.assertRaisesRegex(ValueError,'release-dir'):m.validate_release(root,False)

class AuthenticatedLayoutTests(unittest.TestCase):
    def fake(self,part=None,selection=None,chip='ESP32-S3',mac='10:b4:1d:e6:00:9c'):
        spec=importlib.util.spec_from_file_location('release_fakes',m.RELEASE/'tests/test_flash_release.py')
        tests=importlib.util.module_from_spec(spec);spec.loader.exec_module(tests)
        class Tool(tests.FakeEsptool):
            def attach_flash(self,device):self.events.append(('attach',device))
            def read_flash(self,device,address,size,**kwargs):
                self.events.append(('read',device,address,size))
                return (part or table()) if address==0x8000 else (selection or ota())
        return Tool(chip,mac),tests.m
    def test_layout_reads_are_after_identity_before_write_same_connection(self):
        tool,release=self.fake()
        release.flash_checked(b'bytes',{'device_mac':release.TARGET_MAC},'test-port',m.LayoutCheckedTool(tool,2879808))
        self.assertEqual([row[0] for row in tool.events],['detect','enter','mac','stub','attach','read','read','write','verify','reset','exit'])
        self.assertIs(tool.events[5][1],tool.events[7][1]);self.assertIs(tool.events[6][1],tool.events[7][1])
    def test_invalid_layout_never_calls_write_or_reset(self):
        tool,release=self.fake(selection=ota(2))
        with self.assertRaises(ValueError):release.flash_checked(b'bytes',{'device_mac':release.TARGET_MAC},'test-port',m.LayoutCheckedTool(tool,2879808))
        self.assertNotIn('write',[r[0] for r in tool.events]);self.assertNotIn('reset',[r[0] for r in tool.events])
    def test_wrong_device_cannot_even_read_partition_table(self):
        for chip,mac in [('ESP8266','10:b4:1d:e6:00:9c'),('ESP32-S3','00:11:22:33:44:55')]:
            tool,release=self.fake(chip=chip,mac=mac)
            with self.assertRaises(ValueError):release.flash_checked(b'bytes',{'device_mac':release.TARGET_MAC},'test-port',m.LayoutCheckedTool(tool,2879808))
            self.assertNotIn('read',[r[0] for r in tool.events]);self.assertNotIn('write',[r[0] for r in tool.events])

if __name__ == '__main__': unittest.main()

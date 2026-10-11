"""Offline checks for board/configuration and application partition guards."""
from pathlib import Path
import importlib.util, json, struct, tempfile, unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('build_watcher',ROOT/'tools/build_watcher.py')
build=importlib.util.module_from_spec(spec);spec.loader.exec_module(build)

class BuildGuardTests(unittest.TestCase):
    def test_verified_config(self):
        checked=build.validate_config(build.CONFIG_TEMPLATE,build.select_board_config())
        self.assertEqual(checked['CONFIG_IDF_TARGET'],'"esp32s3"')
    def test_wrong_config_rejected(self):
        text=build.CONFIG_TEMPLATE.read_text().replace('CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="partitions/watcher-gesture.csv"','CONFIG_PARTITION_TABLE_CUSTOM_FILENAME="partitions/v2/16m.csv"')
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'sdkconfig';path.write_text(text)
            with self.assertRaisesRegex(ValueError,'configuration mismatch'):
                build.validate_config(path,build.select_board_config())
    def test_missing_v9_has_no_fallback(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'main/boards/sensecap-watcher-gesture/config.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'target':'esp32s3','builds':[{'name':'other-board','sdkconfig_append':['CONFIG_OTHER=y']}]}))
            with patch.object(build,'PROJECT',root),self.assertRaisesRegex(ValueError,'Missing or ambiguous'):
                build.select_board_config()
    def test_wrong_chip_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);path=root/'main/boards/sensecap-watcher-gesture/config.json'
            path.parent.mkdir(parents=True);path.write_text(json.dumps({'target':'esp32'}))
            with patch.object(build,'PROJECT',root),self.assertRaisesRegex(ValueError,'target must'):
                build.select_board_config()
    def test_correct_partition(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'part.bin';path.write_bytes(struct.pack('<HBBII16sI',0x50aa,0,0x10,0x200000,0x400000,b'ota_0',0))
            self.assertEqual(build.validate_partition(path)['address'],'0x200000')
    def test_wrong_partition_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'part.bin';path.write_bytes(struct.pack('<HBBII16sI',0x50aa,0,0x10,0x10000,0x400000,b'ota_0',0))
            with self.assertRaisesRegex(ValueError,'partition mismatch'):build.validate_partition(path)
    def test_partition_required(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'part.bin';path.write_bytes(bytes(64))
            with self.assertRaisesRegex(ValueError,'not found'):build.validate_partition(path)

if __name__=='__main__':unittest.main()

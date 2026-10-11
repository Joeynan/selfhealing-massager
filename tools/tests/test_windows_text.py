"""Simulate Windows' legacy locale while preserving real file decoding checks."""
import hashlib, importlib.util, io, json, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]

def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

class WindowsTextTests(unittest.TestCase):
    def locale_read(self):
        original=Path.read_text
        def read(path,encoding=None,*args,**kwargs):
            self.assertEqual(encoding,'utf-8','Project text must explicitly select UTF-8 on Windows cp1252')
            return original(path,encoding=encoding or 'cp1252',*args,**kwargs)
        return patch.object(Path,'read_text',read)
    def test_release_manifest_with_chinese_note_loads_with_cp1252_default(self):
        release=load('windows_release',ROOT/'outputs/Watcher控制台/滚轮表情版/flash_release.py')
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);data=bytearray(96);data[0]=0xe9;data[12]=9
            (root/'app.bin').write_bytes(data)
            manifest={'build_verified':True,'chip':'esp32s3','address':'0x200000','device_mac':release.TARGET_MAC,
                      'app':'app.bin','bytes':96,'sha256':hashlib.sha256(data).hexdigest(),'note':'历史已验证应用镜像；保留配置'}
            (root/'release-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False),encoding='utf-8')
            with self.locale_read():self.assertEqual(release.validate(root)[1]['note'],manifest['note'])
    def test_board_config_explicitly_reads_utf8(self):
        build=load('windows_board',ROOT/'tools/build_watcher.py')
        with self.locale_read():self.assertTrue(build.select_board_config())
    def test_sdkconfig_explicitly_reads_utf8(self):
        build=load('windows_config',ROOT/'tools/build_watcher.py')
        appended=build.select_board_config()
        with self.locale_read():self.assertEqual(build.validate_config(build.CONFIG_TEMPLATE,appended)['CONFIG_IDF_TARGET'],'"esp32s3"')
    def test_common_entry_launches_children_with_utf8_mode(self):
        entry=load('windows_entry',ROOT/'tools/team_entry.py')
        with patch.object(sys,'argv',['team_entry.py','flash','--dry-run']),patch.object(entry.subprocess,'call',return_value=0) as child:
            self.assertEqual(entry.main(),0)
        self.assertEqual(child.call_args.kwargs.get('env',{}).get('PYTHONUTF8'),'1')

if __name__=='__main__':unittest.main()

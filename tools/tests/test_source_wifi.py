"""Source Wi-Fi checks use synthetic settings and never open hardware."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
BOARD = ROOT / 'work/xiaozhi-esp32/main/boards/sensecap-watcher-gesture'


class PreflightTests(unittest.TestCase):
    def helper(self):
        path = ROOT / 'tools/watcher_wifi_config.py'
        self.assertTrue(path.is_file(), 'Watcher source Wi-Fi preflight is not implemented')
        spec = importlib.util.spec_from_file_location('source_wifi_preflight', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def config(self, text):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        project = Path(temp.name)
        board = project / 'main/boards/sensecap-watcher-gesture'
        board.mkdir(parents=True)
        if text is not None: (board / 'wifi_settings.h').write_text(text, encoding='utf-8')
        return project

    def header(self, enabled='true', ssid='TEST network', password='TEST_password'):
        return '#pragma once\nconstexpr bool WATCHER_SOURCE_WIFI_ENABLED = ' + enabled + ';\nconstexpr const char* WIFI_SSID = "' + ssid + '";\nconstexpr const char* WIFI_PASSWORD = "' + password + '";\n'

    def test_no_private_header_and_disabled_template_preserve_saved_networks(self):
        helper = self.helper()
        self.assertFalse(helper.validate_source_wifi_config(self.config(None))['enabled'])
        self.assertFalse(helper.validate_source_wifi_config(self.config(self.header('false', 'YOUR_WIFI_NAME', 'YOUR_WIFI_PASSWORD')))['enabled'])

    def test_spaces_unicode_and_escaped_quotes_are_supported_without_secrets_in_report(self):
        result = self.helper().validate_source_wifi_config(self.config(self.header(ssid='TEST 按摩 \\"Studio\\"', password='TEST_\\\\password')))
        self.assertTrue(result['enabled'])
        self.assertNotIn('TEST_', str(result))

    def test_lengths_are_bytes(self):
        helper = self.helper()
        for ssid, password in [('', 'TEST_password'), ('界' * 11, 'TEST_password'), ('TEST_name', 'short'), ('TEST_name', 'x' * 64)]:
            with self.subTest(ssid_bytes=len(ssid.encode()), password_bytes=len(password.encode())):
                with self.assertRaises(ValueError): helper.validate_source_wifi_config(self.config(self.header(ssid=ssid, password=password)))
        helper.validate_source_wifi_config(self.config(self.header(ssid='界' * 10, password='x' * 63)))

    def test_placeholders_controls_unknown_syntax_and_symlinks_are_rejected(self):
        helper = self.helper()
        for text in [self.header(ssid='YOUR_WIFI_NAME'), self.header(password='YOUR_WIFI_PASSWORD'), self.header(ssid='TEST_\\nname'), self.header(enabled='some_flag'), self.header().replace('"TEST network"', 'get_ssid()')]:
            with self.subTest():
                with self.assertRaises(ValueError): helper.validate_source_wifi_config(self.config(text))
        project = self.config(None)
        target = project / 'private-header.h';target.write_text(self.header())
        try: (project / 'main/boards/sensecap-watcher-gesture/wifi_settings.h').symlink_to(target)
        except OSError: self.skipTest('Creating symlinks requires privilege on this platform')
        with self.assertRaises(ValueError): helper.validate_source_wifi_config(project)

    def test_error_only_identifies_location_not_credentials(self):
        with self.assertRaises(ValueError) as caught: self.helper().validate_source_wifi_config(self.config(self.header(password='TEST_secret_too_long_' * 4)))
        self.assertIn('wifi_settings.h', str(caught.exception))
        self.assertNotIn('TEST_secret', str(caught.exception))

    def test_enable_flag_must_be_a_compile_time_constant(self):
        helper = self.helper()
        for declaration in ('constexpr bool', 'const bool', 'constexpr const bool'):
            with self.subTest(declaration=declaration):
                text = self.header().replace('constexpr bool', declaration)
                self.assertTrue(helper.validate_source_wifi_config(self.config(text))['enabled'])
        with self.assertRaises(ValueError):
            helper.validate_source_wifi_config(self.config(self.header().replace('constexpr bool', 'bool')))


NVS_STUB = r'''
#pragma once
#include <cstdint>
#include <cstring>
#include <map>
#include <string>
#include <vector>
using esp_err_t=int;
using nvs_handle_t=unsigned;
using nvs_open_mode_t=int;
constexpr int ESP_OK=0,ESP_FAIL=-1,ESP_ERR_NVS_NOT_FOUND=1,ESP_ERR_NVS_INVALID_LENGTH=2,ESP_ERR_NVS_TYPE_MISMATCH=3;
constexpr int NVS_READONLY=0,NVS_READWRITE=1;
struct Value {bool is_string=true;std::string text;uint8_t number=0;};
struct Handle {std::string space;std::map<std::string,Value> data;};
inline std::map<std::string,std::map<std::string,Value>> store;
inline std::map<unsigned,Handle> handles;
inline std::vector<std::string> operations;
inline std::string fail_operation;
inline unsigned next_handle=1;
inline bool fail_readback=false,wifi_committed=false,fail_crypto=false,fail_fingerprint_readback=false,source_committed=false;
inline bool failed(const std::string& op){operations.push_back(op);if(op==fail_operation){fail_operation.clear();return true;}return false;}
inline esp_err_t nvs_open(const char* name,int mode,nvs_handle_t* out){
 if(failed(std::string("open:")+name))return ESP_FAIL;
 if(mode==NVS_READONLY&&!store.count(name))return ESP_ERR_NVS_NOT_FOUND;
 *out=next_handle++;handles[*out]={name,store[name]};return ESP_OK;
}
inline void nvs_close(nvs_handle_t h){handles.erase(h);}
inline esp_err_t nvs_get_str(nvs_handle_t h,const char* key,char* out,size_t* length){
 auto& handle=handles.at(h);if(failed("get:"+handle.space+":"+key))return ESP_FAIL;
 if(fail_readback&&wifi_committed&&handle.space=="wifi")return ESP_FAIL;
 if(fail_fingerprint_readback&&source_committed&&handle.space=="source_wifi")return ESP_FAIL;
 auto item=handle.data.find(key);if(item==handle.data.end())return ESP_ERR_NVS_NOT_FOUND;
 if(!item->second.is_string)return ESP_ERR_NVS_TYPE_MISMATCH;
 size_t need=item->second.text.size()+1;if(!out){*length=need;return ESP_OK;}
 if(*length<need){*length=need;return ESP_ERR_NVS_INVALID_LENGTH;}
 memcpy(out,item->second.text.c_str(),need);*length=need;return ESP_OK;
}
inline esp_err_t nvs_get_u8(nvs_handle_t h,const char* key,uint8_t* out){
 auto& handle=handles.at(h);if(failed("get:"+handle.space+":"+key))return ESP_FAIL;
 auto item=handle.data.find(key);if(item==handle.data.end())return ESP_ERR_NVS_NOT_FOUND;
 if(item->second.is_string)return ESP_ERR_NVS_TYPE_MISMATCH;*out=item->second.number;return ESP_OK;
}
inline esp_err_t nvs_set_str(nvs_handle_t h,const char* key,const char* value){auto& handle=handles.at(h);if(failed("set:"+handle.space+":"+key))return ESP_FAIL;handle.data[key]={true,value,0};return ESP_OK;}
inline esp_err_t nvs_set_u8(nvs_handle_t h,const char* key,uint8_t value){auto& handle=handles.at(h);if(failed("set:"+handle.space+":"+key))return ESP_FAIL;handle.data[key]={false,"",value};return ESP_OK;}
inline esp_err_t nvs_erase_key(nvs_handle_t h,const char* key){auto& handle=handles.at(h);if(failed("erase:"+handle.space+":"+key))return ESP_FAIL;return handle.data.erase(key)?ESP_OK:ESP_ERR_NVS_NOT_FOUND;}
inline esp_err_t nvs_commit(nvs_handle_t h){auto& handle=handles.at(h);if(failed("commit:"+handle.space))return ESP_FAIL;store[handle.space]=handle.data;if(handle.space=="wifi")wifi_committed=true;if(handle.space=="source_wifi")source_committed=true;return ESP_OK;}
inline void seed(int i,const std::string& ssid,const std::string& password,uint8_t channel=0){auto s=i?std::to_string(i):"";store["wifi"]["ssid"+s]={true,ssid,0};store["wifi"]["password"+s]={true,password,0};store["wifi"]["channel"+s]={false,"",channel};}
'''
PSA_STUB = r'''
#pragma once
#include <cstddef>
#include <cstdint>
constexpr int PSA_SUCCESS=0,PSA_ALG_SHA_256=0x02000009;
using psa_status_t=int;
inline psa_status_t psa_crypto_init(){return fail_crypto?-1:0;}
// Hardware crypto is isolated; real target uses ESP-IDF PSA SHA256.
inline psa_status_t psa_hash_compute(int,const uint8_t* input,size_t length,uint8_t* output,size_t capacity,size_t* written){
 if(capacity<32)return -1;
 for(unsigned j=0;j<32;++j){uint32_t value=2166136261u+j;for(size_t i=0;i<length;++i)value=(value^input[i])*16777619u;output[j]=uint8_t(value>>(j%4)*8);}
 *written=32;return 0;
}
'''
HARNESS = r'''
#include "nvs.h"
#include "source_wifi_config.h"
#include <iostream>
using watcher_source_wifi::Apply;
using watcher_source_wifi::ApplyCompiled;
using watcher_source_wifi::Result;
#define CHECK(c) do{if(!(c)){std::cerr<<"check failed at "<<__LINE__<<"\n";return 1;}}while(0)
bool marked(){return store["source_wifi"].count("fingerprint");}
int main(int argc,char**argv){
 std::string scenario=argc>1?argv[1]:"";
 if(scenario=="disabled"){CHECK(Apply(false,"YOUR_WIFI_NAME","YOUR_WIFI_PASSWORD")==Result::Disabled);CHECK(operations.empty());CHECK(ApplyCompiled()==Result::Disabled);}
 else if(scenario=="invalid"){
  for(auto ssid:{"","YOUR_WIFI_NAME","TEST\nname"})CHECK(Apply(true,ssid,"TEST_password")==Result::Invalid);
  CHECK(Apply(true,"TEST_name","short")==Result::Invalid);CHECK(Apply(true,"TEST_name","YOUR_WIFI_PASSWORD")==Result::Invalid);CHECK(operations.empty());
 }
 else if(scenario=="first"){
  CHECK(Apply(true,"TEST_name","TEST_password")==Result::Applied);CHECK(marked());CHECK(store["wifi"]["ssid"].text=="TEST_name");CHECK(store["wifi"]["password"].text=="TEST_password");CHECK(store["source_wifi"]["fingerprint"].text.size()==64);
 }
 else if(scenario=="same_preserves_serial"){
  CHECK(Apply(true,"TEST_name","TEST_password")==Result::Applied);auto fingerprint=store["source_wifi"]["fingerprint"].text;
  seed(0,"TEST_serial","TEST_serial_password",8);CHECK(Apply(true,"TEST_name","TEST_password")==Result::Unchanged);CHECK(store["wifi"]["ssid"].text=="TEST_serial");CHECK(store["source_wifi"]["fingerprint"].text==fingerprint);
 }
 else if(scenario=="changed_preserves_networks"){
  seed(0,"TEST_old","TEST_old_password",6);seed(1,"TEST_name","TEST_saved_password",11);
  CHECK(Apply(true,"TEST_name","TEST_password")==Result::Applied);CHECK(store["wifi"]["ssid"].text=="TEST_name");CHECK(store["wifi"]["channel"].number==11);CHECK(store["wifi"]["ssid1"].text=="TEST_old");
  auto fingerprint=store["source_wifi"]["fingerprint"].text;CHECK(Apply(true,"TEST_name","TEST_changed_password")==Result::Applied);CHECK(store["source_wifi"]["fingerprint"].text!=fingerprint);CHECK(store["wifi"]["password"].text=="TEST_changed_password");
  CHECK(Apply(true,"TEST_new","TEST_new_password")==Result::Applied);CHECK(store["wifi"]["ssid"].text=="TEST_new");CHECK(store["wifi"]["ssid1"].text=="TEST_name");CHECK(store["wifi"]["ssid2"].text=="TEST_old");
 }
 else if(scenario=="full"){
  for(int i=0;i<10;++i)seed(i,"TEST_"+std::to_string(i),"TEST_password",uint8_t(i));
  CHECK(Apply(true,"TEST_new","TEST_password")==Result::ListFull);CHECK(!marked());CHECK(store["wifi"]["ssid9"].text=="TEST_9");
  CHECK(Apply(true,"TEST_9","TEST_updated_password")==Result::Applied);CHECK(store["wifi"]["ssid"].text=="TEST_9");CHECK(store["wifi"]["ssid9"].text=="TEST_8");
 }
 else if(scenario=="holes"){seed(4,"TEST_old","TEST_old_password",6);CHECK(Apply(true,"TEST_name","TEST_password")==Result::Applied);CHECK(store["wifi"]["ssid1"].text=="TEST_old");CHECK(!store["wifi"].count("ssid4"));}
 else if(scenario=="corrupt_saved"){store["wifi"]["ssid"]={true,"TEST_orphan",0};CHECK(Apply(true,"TEST_name","TEST_password")==Result::StorageError);CHECK(!marked());CHECK(store["wifi"]["ssid"].text=="TEST_orphan");}
 else if(scenario=="readback"){fail_readback=true;CHECK(Apply(true,"TEST_name","TEST_password")==Result::StorageError);CHECK(!marked());}
 else if(scenario=="fingerprint_readback"){fail_fingerprint_readback=true;CHECK(Apply(true,"TEST_name","TEST_password")==Result::StorageError);CHECK(!marked());}
 else if(scenario=="compiled"){CHECK(ApplyCompiled()==Result::Applied);CHECK(store["wifi"]["ssid"].text=="TEST_compiled");}
 else if(scenario=="crypto"){fail_crypto=true;CHECK(Apply(true,"TEST_name","TEST_password")==Result::StorageError);CHECK(operations.empty());}
 else if(scenario.rfind("fail:",0)==0){store["source_wifi"]={};seed(0,"TEST_old","TEST_old_password",6);fail_operation=scenario.substr(5);CHECK(Apply(true,"TEST_name","TEST_password")==Result::StorageError);CHECK(!marked());}
 else return 2;
 CHECK(handles.empty());return 0;
}
'''


class FirmwareImporterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compiler = shutil.which('clang++') or shutil.which('g++')
        if not cls.compiler: raise unittest.SkipTest('Host C++ compiler unavailable; firmware target build is checked separately')
        cls.temp = tempfile.TemporaryDirectory();cls.addClassCleanup(cls.temp.cleanup)
        cls.directory = Path(cls.temp.name);(cls.directory / 'psa').mkdir()
        (cls.directory / 'nvs.h').write_text(NVS_STUB)
        (cls.directory / 'psa/crypto.h').write_text(PSA_STUB)
        (cls.directory / 'esp_log.h').write_text('#pragma once\n#define ESP_LOGI(tag, ...) ((void)(tag))\n#define ESP_LOGW(tag, ...) ((void)(tag))\n#define ESP_LOGE(tag, ...) ((void)(tag))\n')
        (cls.directory / 'harness.cc').write_text(HARNESS)
        # 仅复制公共导入器；真实工程中的私有头不能影响测试，更不能进入测试二进制。
        cls.source = cls.directory / 'board';cls.source.mkdir()
        for name in ('source_wifi_config.cc', 'source_wifi_config.h'):
            shutil.copyfile(BOARD / name, cls.source / name)
        cls.binary = cls.directory / 'source-wifi-test';cls.compiled = False

    def run_scenario(self, scenario):
        self.assertTrue((BOARD / 'source_wifi_config.cc').is_file(), 'The board Wi-Fi importer is not implemented')
        if not self.__class__.compiled:
            command = [self.compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror', '-I' + str(self.directory), '-I' + str(self.source), str(self.directory / 'harness.cc'), str(self.source / 'source_wifi_config.cc'), '-o', str(self.binary)]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr);self.__class__.compiled = True
        result = subprocess.run([str(self.binary), scenario], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_private_header_enabled_and_disabled_build_branches(self):
        for enabled in (False, True):
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as temporary:
                local_board = Path(temporary)
                shutil.copyfile(BOARD / 'source_wifi_config.cc', local_board / 'source_wifi_config.cc')
                shutil.copyfile(BOARD / 'source_wifi_config.h', local_board / 'source_wifi_config.h')
                name = 'TEST_compiled' if enabled else 'TEST_DISABLED_PRIVATE_ONLY'
                (local_board / 'wifi_settings.h').write_text(
                    '#pragma once\nconstexpr bool WATCHER_SOURCE_WIFI_ENABLED = ' + ('true' if enabled else 'false') + ';\n'
                    'constexpr const char* WIFI_SSID = "' + name + '";\n'
                    'constexpr const char* WIFI_PASSWORD = "TEST_compiled_password";\n'
                )
                binary = local_board / 'test-importer'
                result = subprocess.run([self.compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                                         '-I' + str(self.directory), '-I' + str(local_board),
                                         str(self.directory / 'harness.cc'), str(local_board / 'source_wifi_config.cc'),
                                         '-o', str(binary)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                result = subprocess.run([str(binary), 'compiled' if enabled else 'disabled'], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                if not enabled:self.assertFalse(name.encode() in binary.read_bytes(),
                                                'Disabled source setup must exclude private configuration strings')

    def test_working_copy_private_header_is_not_used_by_importer_tests(self):
        with tempfile.TemporaryDirectory() as temporary:
            origin = Path(temporary)
            for name in ('source_wifi_config.cc', 'source_wifi_config.h'):
                shutil.copyfile(BOARD / name, origin / name)
            (origin / 'wifi_settings.h').write_text('#error Unit tests must not consume private working-copy settings\n')
            isolated = type('IsolatedImporterTests', (FirmwareImporterTests,), {})
            with patch.dict(globals(), {'BOARD': origin}):
                isolated.setUpClass()
                try:isolated('test_disabled_and_missing_header_never_touch_nvs').run_scenario('disabled')
                finally:isolated.doClassCleanups()

    def test_disabled_and_missing_header_never_touch_nvs(self): self.run_scenario('disabled')
    def test_invalid_and_placeholder_config_never_touch_nvs(self): self.run_scenario('invalid')
    def test_first_import_is_saved_and_marked(self): self.run_scenario('first')
    def test_same_fingerprint_preserves_serial_overrides(self): self.run_scenario('same_preserves_serial')
    def test_changed_config_updates_default_without_deleting_other_networks(self): self.run_scenario('changed_preserves_networks')
    def test_full_list_rejects_new_network_but_can_update_saved_one(self): self.run_scenario('full')
    def test_sparse_saved_list_is_preserved_and_compacted(self): self.run_scenario('holes')
    def test_corrupt_saved_network_is_not_overwritten(self): self.run_scenario('corrupt_saved')
    def test_failed_readback_never_records_fingerprint(self): self.run_scenario('readback')
    def test_failed_crypto_never_touches_nvs(self): self.run_scenario('crypto')
    def test_failed_fingerprint_readback_removes_success_marker(self): self.run_scenario('fingerprint_readback')
    def test_all_nvs_errors_fail_without_success_marker(self):
        for operation in ['open:source_wifi', 'get:source_wifi:fingerprint', 'open:wifi', 'get:wifi:ssid', 'get:wifi:password', 'get:wifi:channel', 'set:wifi:ssid', 'set:wifi:password', 'set:wifi:channel', 'erase:wifi:ssid9', 'commit:wifi', 'set:source_wifi:fingerprint', 'commit:source_wifi']:
            with self.subTest(operation=operation): self.run_scenario('fail:' + operation)


if __name__ == '__main__': unittest.main()

"""已选择网络不能被更强的旧网络或旧信道扫描覆盖；不访问设备。"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'work/xiaozhi-esp32/main/boards/sensecap-watcher-gesture/wifi_network_preference.cc'


class WifiNetworkPreferenceTests(unittest.TestCase):
    def test_station_scan_uses_selected_saved_name_without_erasing_other_networks(self):
        self.assertTrue(SOURCE.is_file(),
                        'Watcher must constrain station scans to the selected saved network')
        compiler = shutil.which('clang++') or shutil.which('g++')
        self.assertIsNotNone(compiler, 'A host C++ compiler is required')
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            (folder / 'esp_wifi.h').write_text('''#pragma once
#include <cstdint>
using esp_err_t=int;
constexpr int ESP_OK=0;
enum wifi_mode_t { WIFI_MODE_STA=1, WIFI_MODE_APSTA=3 };
struct wifi_scan_config_t {
  uint8_t* ssid=nullptr; uint8_t* bssid=nullptr; uint8_t channel=0;
  bool show_hidden=false;
  struct { uint32_t ghz_2_channels=0, ghz_5_channels=0; } channel_bitmap;
};
extern "C" esp_err_t esp_wifi_get_mode(wifi_mode_t* mode);
''')
            (folder / 'nvs.h').write_text('''#pragma once
#include <cstddef>
using nvs_handle_t=int;
constexpr int NVS_READONLY=0;
extern "C" int nvs_open(const char*,int,nvs_handle_t*);
extern "C" int nvs_get_str(nvs_handle_t,const char*,char*,size_t*);
extern "C" void nvs_close(nvs_handle_t);
''')
            (folder / 'test.cpp').write_text(r'''
#include <cassert>
#include <cstring>
#include <string>
#include "esp_wifi.h"
#include "nvs.h"
static std::string saved="TEST_SELECTED_NETWORK", selected;
static wifi_mode_t mode=WIFI_MODE_STA;
static bool store_ok=true, mode_ok=true, got_block=false;
static int opened=0, closed=0, scans=0;
static const wifi_scan_config_t* passed=nullptr;
static wifi_scan_config_t captured;
extern "C" int esp_wifi_get_mode(wifi_mode_t* value) {
  *value=mode; return mode_ok?0:1;
}
extern "C" int nvs_open(const char* space,int access,nvs_handle_t* handle) {
  assert(!strcmp(space,"wifi") && access==NVS_READONLY);
  if(!store_ok)return 1; ++opened;*handle=7;return 0;
}
extern "C" int nvs_get_str(nvs_handle_t handle,const char* key,char* output,size_t* size) {
  assert(handle==7 && !strcmp(key,"ssid"));
  if(saved.empty() || saved.size()+1>*size)return 1;
  memcpy(output,saved.c_str(),saved.size()+1);*size=saved.size()+1;return 0;
}
extern "C" void nvs_close(nvs_handle_t handle) {assert(handle==7);++closed;}
extern "C" int __real_esp_wifi_scan_start(const wifi_scan_config_t* config,bool block) {
  ++scans;passed=config;got_block=block;
  selected=config && config->ssid?reinterpret_cast<const char*>(config->ssid):"";
  if(config)captured=*config;
  return 37;
}
extern "C" int __wrap_esp_wifi_scan_start(const wifi_scan_config_t*,bool);
int main() {
  wifi_scan_config_t original;original.channel=11;
  original.channel_bitmap.ghz_2_channels=1u<<11;
  original.show_hidden=true;
  assert(__wrap_esp_wifi_scan_start(&original,false)==37);
  assert(selected=="TEST_SELECTED_NETWORK" && captured.channel==0);
  assert(captured.channel_bitmap.ghz_2_channels==0 && captured.channel_bitmap.ghz_5_channels==0);
  assert(captured.show_hidden && !got_block && captured.bssid==nullptr);
  assert(original.channel==11 && original.ssid==nullptr);
  assert(__wrap_esp_wifi_scan_start(nullptr,true)==37 && got_block && selected=="TEST_SELECTED_NETWORK");
  saved="Next network";
  assert(__wrap_esp_wifi_scan_start(nullptr,false)==37 && selected==saved);
  saved=std::string(32,'s');
  __wrap_esp_wifi_scan_start(nullptr,false);assert(selected==saved);
  mode=WIFI_MODE_APSTA;
  __wrap_esp_wifi_scan_start(&original,false);assert(passed==&original);
  mode=WIFI_MODE_STA;store_ok=false;
  __wrap_esp_wifi_scan_start(&original,false);assert(passed==&original);
  store_ok=true;saved="";
  __wrap_esp_wifi_scan_start(&original,false);assert(passed==&original);
  saved=std::string(33,'s');
  __wrap_esp_wifi_scan_start(&original,false);assert(passed==&original);
  saved="bad\nname";
  __wrap_esp_wifi_scan_start(&original,false);assert(passed==&original);
  saved="TEST_SELECTED_NETWORK";mode_ok=false;
  __wrap_esp_wifi_scan_start(&original,false);assert(passed==&original);
  assert(opened==closed && scans==10);
}
''')
            binary = folder / 'wifi-preference-test'
            build = subprocess.run([compiler, '-std=c++17', '-Wall', '-Wextra', '-Werror',
                                    '-I'+str(folder), str(SOURCE), str(folder/'test.cpp'),
                                    '-o', str(binary)], capture_output=True, text=True)
            self.assertEqual(build.returncode, 0, build.stdout+build.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_link_override_is_scoped_to_watcher_board(self):
        cmake = (ROOT/'work/xiaozhi-esp32/main/CMakeLists.txt').read_text()
        flag = '"-Wl,--wrap=esp_wifi_scan_start"'
        self.assertTrue(flag in cmake, 'Watcher-specific scan link override is missing')
        preceding = cmake[:cmake.index(flag)]
        self.assertIn('CONFIG_BOARD_TYPE_SENSECAP_WATCHER_GESTURE', preceding.split('if(')[-1])


if __name__ == '__main__':
    unittest.main()

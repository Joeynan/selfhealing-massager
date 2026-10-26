// Watcher 连接用户当前选定的网络，避免更强的旧网络让电脑与设备分离。
// 只约束 STA 扫描，不删除保存项，也不修改第三方 Wi-Fi 组件。
#include <array>
#include <cstring>
#include <mutex>

#include <esp_wifi.h>
#include <nvs.h>

extern "C" esp_err_t __real_esp_wifi_scan_start(const wifi_scan_config_t* config, bool block);

namespace {
std::mutex scan_mutex;
std::array<uint8_t, 33> selected_name{};

bool ReadSelectedNetwork() {
    nvs_handle_t handle;
    if (nvs_open("wifi", NVS_READONLY, &handle) != ESP_OK)
        return false;
    size_t size = selected_name.size();
    selected_name.fill(0);
    const auto result =
        nvs_get_str(handle, "ssid", reinterpret_cast<char*>(selected_name.data()), &size);
    nvs_close(handle);
    if (result != ESP_OK || size < 2 || size > selected_name.size() ||
        selected_name[size - 1] != 0 ||
        std::strlen(reinterpret_cast<const char*>(selected_name.data())) != size - 1)
        return false;
    for (size_t index = 0; index < size - 1; ++index)
        if (selected_name[index] < 32 || selected_name[index] == 127)
            return false;
    return true;
}
}  // namespace

extern "C" esp_err_t __wrap_esp_wifi_scan_start(const wifi_scan_config_t* config, bool block) {
    std::lock_guard<std::mutex> guard(scan_mutex);
    wifi_mode_t mode;
    // 配网 AP 仍能扫描全部网络；无有效选择时保留 SDK 原始行为。
    if (esp_wifi_get_mode(&mode) != ESP_OK || mode != WIFI_MODE_STA || !ReadSelectedNetwork())
        return __real_esp_wifi_scan_start(config, block);
    wifi_scan_config_t selected = config ? *config : wifi_scan_config_t{};
    selected.ssid = selected_name.data();
    selected.bssid = nullptr;
    // 新网络可能不在旧网络的缓存信道，必须查找全部信道。
    selected.channel = 0;
    selected.channel_bitmap = {};
    return __real_esp_wifi_scan_start(&selected, block);
}

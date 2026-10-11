#include "source_wifi_config.h"

#include <algorithm>
#include <array>
#include <cstring>
#include <string>
#include <utility>
#include <vector>

#include <esp_log.h>
#include <nvs.h>
#include <psa/crypto.h>

#if __has_include("wifi_settings.h")
#include "wifi_settings.h"
#define WATCHER_HAS_PRIVATE_SOURCE_WIFI 1
#else
#define WATCHER_HAS_PRIVATE_SOURCE_WIFI 0
#endif

namespace watcher_source_wifi {
namespace {
constexpr const char* kTag = "WatcherSourceWifi";
constexpr size_t kMaximumNetworks = 10;

struct Network {
    std::string ssid;
    std::string password;
    uint8_t channel = 0;
    bool operator==(const Network& other) const {
        return ssid == other.ssid && password == other.password && channel == other.channel;
    }
};

// NVS 句柄只在这次启动导入中存活。所有退出路径都会关闭句柄。
class Handle {
public:
    ~Handle() { if (opened_) nvs_close(value); }
    esp_err_t Open(const char* space, int mode) {
        const auto error = nvs_open(space, static_cast<nvs_open_mode_t>(mode), &value);
        opened_ = error == ESP_OK;
        return error;
    }
    nvs_handle_t value{};
private:
    bool opened_ = false;
};

enum class ReadResult { Missing, Present, Error };

ReadResult ReadText(nvs_handle_t handle, const char* key, size_t maximum, std::string& output) {
    std::array<char, 65> buffer{};
    size_t length = maximum + 1;
    const auto error = nvs_get_str(handle, key, buffer.data(), &length);
    if (error == ESP_ERR_NVS_NOT_FOUND) return ReadResult::Missing;
    if (error != ESP_OK || length == 0 || length > maximum + 1 ||
        buffer[length - 1] != '\0' || std::strlen(buffer.data()) != length - 1) {
        return ReadResult::Error;
    }
    output.assign(buffer.data(), length - 1);
    return ReadResult::Present;
}

std::string Key(const char* prefix, size_t index) {
    return index == 0 ? prefix : std::string(prefix) + std::to_string(index);
}

// 与固定 SsidManager 的 wifi/ssid、password、channel 键兼容；不编辑第三方组件。
// 先完整读取旧列表。孤立/损坏的保存项导致拒绝导入，避免错误地覆盖旧网络。
bool ReadNetworks(std::vector<Network>& networks) {
    Handle handle;
    const auto error = handle.Open("wifi", NVS_READONLY);
    if (error == ESP_ERR_NVS_NOT_FOUND) return true;
    if (error != ESP_OK) return false;
    for (size_t index = 0; index < kMaximumNetworks; ++index) {
        Network item;
        const auto ssid = ReadText(handle.value, Key("ssid", index).c_str(), 32, item.ssid);
        const auto password = ReadText(handle.value, Key("password", index).c_str(), 64, item.password);
        const auto channel = nvs_get_u8(handle.value, Key("channel", index).c_str(), &item.channel);
        if (ssid == ReadResult::Error || password == ReadResult::Error ||
            (channel != ESP_OK && channel != ESP_ERR_NVS_NOT_FOUND)) return false;
        if (ssid == ReadResult::Missing && password == ReadResult::Missing) {
            if (channel != ESP_ERR_NVS_NOT_FOUND) return false;
            continue;
        }
        if (ssid != ReadResult::Present || password != ReadResult::Present || item.ssid.empty()) return false;
        networks.push_back(std::move(item));
    }
    return true;
}

bool EraseOptional(nvs_handle_t handle, const std::string& key) {
    const auto error = nvs_erase_key(handle, key.c_str());
    return error == ESP_OK || error == ESP_ERR_NVS_NOT_FOUND;
}

bool WriteNetworks(const std::vector<Network>& networks) {
    Handle handle;
    if (handle.Open("wifi", NVS_READWRITE) != ESP_OK) return false;
    for (size_t index = 0; index < kMaximumNetworks; ++index) {
        if (index < networks.size()) {
            const auto& item = networks[index];
            if (nvs_set_str(handle.value, Key("ssid", index).c_str(), item.ssid.c_str()) != ESP_OK ||
                nvs_set_str(handle.value, Key("password", index).c_str(), item.password.c_str()) != ESP_OK ||
                nvs_set_u8(handle.value, Key("channel", index).c_str(), item.channel) != ESP_OK) return false;
        } else if (!EraseOptional(handle.value, Key("ssid", index)) ||
                   !EraseOptional(handle.value, Key("password", index)) ||
                   !EraseOptional(handle.value, Key("channel", index))) return false;
    }
    return nvs_commit(handle.value) == ESP_OK;
}

bool HasControls(const std::string& text) {
    return std::any_of(text.begin(), text.end(), [](unsigned char byte) { return byte < 32 || byte == 127; });
}

bool Valid(const char* ssid, const char* password) {
    if (!ssid || !password) return false;
    const size_t ssid_length = std::strlen(ssid), password_length = std::strlen(password);
    return ssid_length >= 1 && ssid_length <= 32 && password_length >= 8 && password_length <= 63 &&
           std::strncmp(ssid, "YOUR_", 5) != 0 && std::strncmp(password, "YOUR_", 5) != 0 &&
           !HasControls(ssid) && !HasControls(password);
}

// 指纹包含名称和密码，并用长度分隔防止不同字段拼接相同；仅用于判断配置是否改变。
// 不记录实际凭据，也不把指纹输出到日志。ESP-IDF 6 的公共 PSA 接口提供 SHA256。
bool Fingerprint(const char* ssid, const char* password, std::string& fingerprint) {
    const std::string name(ssid), secret(password);
    const std::string input = "watcher-source-wifi-v1:" + std::to_string(name.size()) + ":" + name +
                              ":" + std::to_string(secret.size()) + ":" + secret;
    std::array<uint8_t, 32> digest{};
    size_t written = 0;
    if (psa_crypto_init() != PSA_SUCCESS ||
        psa_hash_compute(PSA_ALG_SHA_256, reinterpret_cast<const uint8_t*>(input.data()), input.size(),
                         digest.data(), digest.size(), &written) != PSA_SUCCESS || written != digest.size()) return false;
    constexpr char hex[] = "0123456789abcdef";
    fingerprint.clear();
    fingerprint.reserve(64);
    for (const auto byte : digest) {
        fingerprint.push_back(hex[byte >> 4]);
        fingerprint.push_back(hex[byte & 15]);
    }
    return true;
}

bool WriteFingerprint(const std::string& fingerprint) {
    Handle handle;
    if (handle.Open("source_wifi", NVS_READWRITE) != ESP_OK) return false;
    const bool written = fingerprint.empty()
                             ? EraseOptional(handle.value, "fingerprint")
                             : nvs_set_str(handle.value, "fingerprint", fingerprint.c_str()) == ESP_OK;
    return written && nvs_commit(handle.value) == ESP_OK;
}

bool RecordFingerprint(const std::string& fingerprint, const std::string& previous) {
    bool valid = WriteFingerprint(fingerprint);
    if (valid) {
        Handle verify;
        std::string stored;
        valid = verify.Open("source_wifi", NVS_READONLY) == ESP_OK &&
                ReadText(verify.value, "fingerprint", 64, stored) == ReadResult::Present && stored == fingerprint;
    }
    // 标记本身提交/读回失败，也需撤销新标记；绝不把半完成导入当作成功。
    if (!valid && !WriteFingerprint(previous)) ESP_LOGE(kTag, "Source Wi-Fi marker restoration failed");
    return valid;
}

}  // namespace

Result Apply(bool enabled, const char* ssid, const char* password) {
    if (!enabled) return Result::Disabled;
    if (!Valid(ssid, password)) return Result::Invalid;
    std::string fingerprint, previous_fingerprint;
    if (!Fingerprint(ssid, password, fingerprint)) return Result::StorageError;
    {
        Handle handle;
        const auto error = handle.Open("source_wifi", NVS_READONLY);
        if (error != ESP_OK && error != ESP_ERR_NVS_NOT_FOUND) return Result::StorageError;
        if (error == ESP_OK) {
            std::string saved;
            const auto read = ReadText(handle.value, "fingerprint", 64, saved);
            if (read == ReadResult::Error) return Result::StorageError;
            // 同一版本源码不覆盖之后的 lan_wifi 修改；无需每次开机重写 Flash。
            if (read == ReadResult::Present && saved == fingerprint) return Result::Unchanged;
            if (read == ReadResult::Present) previous_fingerprint = std::move(saved);
        }
    }
    std::vector<Network> original;
    if (!ReadNetworks(original)) return Result::StorageError;
    auto networks = original;
    const auto existing = std::find_if(networks.begin(), networks.end(),
                                      [ssid](const Network& item) { return item.ssid == ssid; });
    Network preferred{ssid, password, 0};
    if (existing != networks.end()) {
        preferred.channel = existing->channel;
        networks.erase(existing);
    } else if (networks.size() >= kMaximumNetworks) {
        return Result::ListFull;  // 不像通用 AddSsid 那样挤掉已保存的最后一个网络。
    }
    networks.insert(networks.begin(), std::move(preferred));
    if (!WriteNetworks(networks)) {
        // NVS 多键写入不是事务；发生错误时尝试恢复旧列表，仍不记录成功指纹。
        if (!WriteNetworks(original)) ESP_LOGE(kTag, "Source Wi-Fi save and restoration both failed");
        return Result::StorageError;
    }
    std::vector<Network> verified;
    if (!ReadNetworks(verified) || verified != networks) {
        if (!WriteNetworks(original)) ESP_LOGE(kTag, "Source Wi-Fi readback and restoration both failed");
        return Result::StorageError;
    }
    // 必须已提交且完整读回 wifi 列表，才能记录本次源码配置已应用。
    if (!RecordFingerprint(fingerprint, previous_fingerprint)) {
        if (!WriteNetworks(original)) ESP_LOGE(kTag, "Source Wi-Fi marker save and network restoration failed");
        return Result::StorageError;
    }
    return Result::Applied;
}

Result ApplyCompiled() {
#if WATCHER_HAS_PRIVATE_SOURCE_WIFI
    // 关闭的源码配网在编译时排除，既不访问 NVS，也不链接这些私有字符串。
    const auto result = [] {
        if constexpr (WATCHER_SOURCE_WIFI_ENABLED) return Apply(true, WIFI_SSID, WIFI_PASSWORD);
        return Result::Disabled;
    }();
#else
    const auto result = Result::Disabled;
#endif
    switch (result) {
        case Result::Applied: ESP_LOGI(kTag, "SOURCE_WIFI_APPLIED"); break;
        case Result::Unchanged: ESP_LOGI(kTag, "SOURCE_WIFI_UNCHANGED; saved settings retained"); break;
        case Result::Disabled: break;
        case Result::Invalid: ESP_LOGE(kTag, "SOURCE_WIFI_INVALID; saved settings retained"); break;
        case Result::ListFull: ESP_LOGE(kTag, "SOURCE_WIFI_LIST_FULL; no network removed"); break;
        case Result::StorageError: ESP_LOGE(kTag, "SOURCE_WIFI_STORAGE_FAILED; application not confirmed"); break;
    }
    return result;
}
}  // namespace watcher_source_wifi

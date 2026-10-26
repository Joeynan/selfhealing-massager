#pragma once

#include <cstddef>
#include <cstdint>
#include <string>

inline constexpr const char* kGestureUiRevision = "wheel-face-1";
inline constexpr size_t kGestureDataRowCount = 10;

// ESP-IDF 的 SSID 是固定长度字节数组；32 字节名称不一定带结尾零，不能直接 strlen。
inline std::string GestureWifiName(const uint8_t* bytes, size_t capacity) {
    if (!bytes)
        return {};
    size_t length = 0;
    while (length < capacity && length < 32 && bytes[length])
        ++length;
    return std::string(reinterpret_cast<const char*>(bytes), length);
}
enum class GestureDisplayPage : uint8_t { Expression, Data };
enum class GesturePowerState : uint8_t { Active, Standby, ShuttingDown };

inline const char* GesturePageName(GestureDisplayPage page) {
    return page == GestureDisplayPage::Data ? "data" : "expression";
}
inline const char* GesturePowerName(GesturePowerState power) {
    switch (power) {
        case GesturePowerState::Standby:
            return "standby";
        case GesturePowerState::ShuttingDown:
            return "shutting_down";
        default:
            return "active";
    }
}

// A coherent value snapshot. Control state is copied under its own lock; network
// and battery fields are populated before the display acquires its LVGL lock.
struct DisplaySnapshot {
    uint8_t mode = 0;
    bool connected = false;
    bool pending = false;
    bool servo_ready = false;
    bool output_preference = true;
    bool camera_fresh = false;
    bool recognition_fresh = false;
    bool pulse_fresh = false;
    bool wifi_connected = false;
    uint32_t hold_remaining_ms = 0;
    uint16_t pulses_us[3] = {1500, 1500, 1500};
    int battery_percent = -1;
    bool charging = false;
    std::string wifi_ssid;
    std::string wifi_ip;
    std::string board_ip;
    GestureDisplayPage page = GestureDisplayPage::Expression;
    GesturePowerState power = GesturePowerState::Active;
    std::string power_prompt;
};

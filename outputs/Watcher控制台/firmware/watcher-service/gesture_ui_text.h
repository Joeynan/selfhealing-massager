#pragma once

#include <array>
#include <cstdio>
#include "gesture_ui.h"

inline std::array<std::string, kGestureDataRowCount> GestureDataRows(const DisplaySnapshot& state) {
    std::array<std::string, kGestureDataRowCount> lines;
    const char* gesture = state.mode == 1   ? "捶打"
                          : state.mode == 2 ? "揉搓"
                          : state.mode == 3 ? "轻捏"
                                            : "等待手势";
    lines[0] = !state.connected ? "黑色板未连接" : state.servo_ready ? "舵机可控制" : "舵机准备中";
    lines[1] = state.wifi_connected
                   ? "Wi-Fi " + (state.wifi_ssid.empty() ? "已连接" : state.wifi_ssid)
                   : "Wi-Fi 未连接";
    lines[2] = state.wifi_connected ? "IP " + state.wifi_ip : "IP --";
    lines[3] = state.connected ? "黑板 " + state.board_ip : "黑板连接：未连接";
    lines[4] = state.camera_fresh ? "摄像头：运行中" : "摄像头：待机";
    lines[5] = state.recognition_fresh ? "识别：有效" : "识别：等待新画面";
    char remaining[32];
    snprintf(remaining, sizeof(remaining), " · %.1fs", state.hold_remaining_ms / 1000.0f);
    lines[6] = std::string(gesture) + (state.mode ? remaining : "");
    lines[7] = !state.output_preference ? "输出：已禁用"
               : state.pending          ? "输出：等待回执"
                                        : "输出：默认启用";
    char pulses[96];
    snprintf(pulses, sizeof(pulses), "%s%u / %u / %u",
             state.pulse_fresh ? "D1/D2/D3 " : "上次回报 ", unsigned(state.pulses_us[0]),
             unsigned(state.pulses_us[1]), unsigned(state.pulses_us[2]));
    lines[8] = pulses;
    lines[9] = state.battery_percent < 0 ? "电量：读取中"
                                         : "电量：" + std::to_string(state.battery_percent) + "%" +
                                               (state.charging ? " · USB" : " · 电池");
    return lines;
}

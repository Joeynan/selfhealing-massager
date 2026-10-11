#pragma once
#include <cstdint>
#include <string>

inline const char* ServoControlStatus(bool connected, bool enabled, bool ready) {
    if (!connected)
        return "黑色板未连接";
    if (!enabled)
        return "舵机已禁用";
    return ready ? "舵机可控制" : "舵机准备中";
}

inline std::string GestureFaceTitle(uint8_t mode, bool pending, bool preview,
                                    const char* hint) {
    std::string title = mode == 1 ? "捶打" : mode == 2 ? "揉搓" : mode == 3 ? "轻捏"
                                                                            : "等待手势";
    if (mode && preview)
        title += "（预览）";
    if (mode && pending)
        title += " · 确认中";
    if (hint && *hint)
        title += std::string("\n") + hint;
    return title;
}

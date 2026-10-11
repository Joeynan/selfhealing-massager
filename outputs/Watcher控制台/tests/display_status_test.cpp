#include <cassert>
#include <string>
#include "../firmware/watcher-service/gesture_status_text.h"

int main() {
    assert(std::string(ServoControlStatus(false, true, true)) == "黑色板未连接");
    assert(std::string(ServoControlStatus(true, true, true)) == "舵机可控制");
    assert(std::string(ServoControlStatus(true, true, false)) == "舵机准备中");
    assert(std::string(ServoControlStatus(true, false, true)) == "舵机已禁用");
    // Connection notice must remain visible during a held recognized expression.
    for (unsigned mode = 0; mode <= 3; ++mode) {
        auto offline = GestureFaceTitle(mode, false, true, ServoControlStatus(false, true, false));
        assert(offline.find("黑色板未连接") != std::string::npos);
        auto ready = GestureFaceTitle(mode, false, false, ServoControlStatus(true, true, true));
        assert(ready.find("舵机可控制") != std::string::npos);
        assert(ready.find("未连接") == std::string::npos);
        assert(ready.find("已连接") == std::string::npos);
    }
    auto pinch = GestureFaceTitle(3, true, false, "黑色板未连接");
    assert(pinch.find("轻捏") != std::string::npos);
    assert(pinch.find("确认中") != std::string::npos);
    assert(pinch.find("黑色板未连接") != std::string::npos);
    assert(GestureFaceTitle(0, false, false, nullptr) == "等待手势");
}

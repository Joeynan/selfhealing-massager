#include "../firmware/watcher-service/gesture_ui_text.h"
#include <cassert>

int main() {
    DisplaySnapshot state;
    auto rows = GestureDataRows(state);
    assert(rows[0] == "黑色板未连接");
    assert(rows[7].find("上次回报") != std::string::npos);
    assert(rows[8] == "电量：读取中");
    state.connected = true;
    state.servo_ready = true;
    state.pulse_fresh = true;
    state.mode = 3;
    state.hold_remaining_ms = 4500;
    state.pending = true;
    state.pulses_us[2] = 2000;
    state.battery_percent = 70;
    rows = GestureDataRows(state);
    assert(rows[0] == "舵机可控制");
    assert(rows[5] == "轻捏 · 4.5s");
    assert(rows[6] == "输出：等待回执");
    assert(rows[7].find("2000") != std::string::npos);
    assert(rows[7].find("上次回报") == std::string::npos);
    state.connected = false;
    state.pulse_fresh = false;
    state.output_preference = false;
    rows = GestureDataRows(state);
    assert(rows[0] == "黑色板未连接");
    assert(rows[6] == "输出：已禁用");
    assert(rows[7].find("上次回报") != std::string::npos);
    assert(GesturePageName(GestureDisplayPage::Data) == std::string("data"));
    assert(GesturePowerName(GesturePowerState::Standby) == std::string("standby"));
}

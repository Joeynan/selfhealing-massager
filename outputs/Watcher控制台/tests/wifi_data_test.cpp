#include "../firmware/watcher-service/gesture_ui_text.h"
#include <cassert>

int main() {
    DisplaySnapshot state;
    state.wifi_connected = true;
    state.wifi_ssid = "TEST_NETWORK";
    state.wifi_ip = "192.168.8.209";
    const auto rows = GestureDataRows(state);
    assert(rows.size() == 10);
    assert(rows[1] == "Wi-Fi TEST_NETWORK");
    assert(rows[2] == "IP 192.168.8.209");
}

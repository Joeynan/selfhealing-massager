#include "../firmware/watcher-service/gesture_ui.h"
#include <cassert>
#include <cstring>

int main() {
    const uint8_t name[] = "TEST_NETWORK";
    assert(GestureWifiName(name, sizeof(name)) == "TEST_NETWORK");
    const uint8_t early[] = {'a', 0, 'b'};
    assert(GestureWifiName(early, sizeof(early)) == "a");
    uint8_t full[33];
    std::memset(full, 'x', sizeof(full));
    assert(GestureWifiName(full, sizeof(full)) == std::string(32, 'x'));
    assert(GestureWifiName(nullptr, 0).empty());
    DisplaySnapshot state;
    state.wifi_connected = true;
    state.wifi_ssid = "TEST_NETWORK";
    assert(state.wifi_ssid == "TEST_NETWORK");
}

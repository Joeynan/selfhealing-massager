#include <cassert>
#include <cstdint>
#include <cstdio>
#include "../firmware/watcher-service/button_policy.h"
#include "../firmware/watcher-service/power_gate.h"
#include "../firmware/watcher-service/capture_epoch.h"

int main() {
    ButtonPolicy b;
    b.Boot(true); b.Down(0);
    assert(b.Pressed());
    assert(b.Tick(6000) == ButtonAction::None);
    assert(b.Up(6001) == ButtonAction::None);
    assert(!b.Pressed());
    assert(b.Up(6002) == ButtonAction::None);
    b.Down(7000);
    assert(b.Tick(9999) == ButtonAction::None);
    assert(b.Up(9999) == ButtonAction::None);
    b.Down(10000);
    assert(b.Tick(13000) == ButtonAction::Disarm);
    assert(b.Tick(17000) == ButtonAction::None);
    assert(b.Up(17001) == ButtonAction::Shutdown);
    assert(b.Up(17002) == ButtonAction::None);
    b.Down(20000);
    assert(b.Up(23000) == ButtonAction::Shutdown); // delayed tick still shuts down
    b.Boot(true); // wake release is consumed
    assert(b.Up(30000) == ButtonAction::None);
    b.Boot(false); b.Down(UINT32_MAX - 2000);
    assert(b.Tick(998) == ButtonAction::None);
    assert(b.Tick(999) == ButtonAction::Disarm);
    assert(b.Up(1000) == ButtonAction::Shutdown);

    PowerGate gate;
    const auto admitted = gate.Epoch();
    assert(gate.Accept(admitted));
    assert(gate.BeginShutdown());
    assert(!gate.BeginShutdown());
    assert(!gate.Accept(admitted));
    for (auto state : {GesturePowerState::ShuttingDown, GesturePowerState::Standby}) {
        assert(!PowerRequestAllowed(state, "/gesture"));
        assert(!PowerRequestAllowed(state, "/arm"));
        assert(!PowerRequestAllowed(state, "/test"));
        assert(PowerRequestAllowed(state, "/stop"));
        assert(PowerRequestAllowed(state, "/suspend"));
    }
    assert(!gate.Resume()); gate.Standby();
    assert(gate.Resume()); assert(!gate.Resume());
    assert(!gate.Accept(admitted));
    assert(gate.Accept(gate.Epoch()));
    auto expression = GestureDisplayPage::Expression;
    auto data = GestureDisplayPage::Data;
    auto active = GesturePowerState::Active;
    assert(RotatedPage(expression, true, false, active) == data);
    assert(RotatedPage(data, true, false, active) == data);
    assert(RotatedPage(data, false, false, active) == expression);
    assert(RotatedPage(expression, false, false, active) == expression);
    assert(RotatedPage(expression, true, true, active) == expression);
    assert(RotatedPage(expression, true, false, GesturePowerState::Standby) == expression);
    assert(!CaptureNeedsSession("wifi", "wifi", 1, 1, false));
    assert(CaptureNeedsSession("wifi", "usb", 1, 1, false));
    assert(CaptureNeedsSession("wifi", "wifi", 1, 2, false));
    assert(CaptureNeedsSession("wifi", "wifi", 1, 1, true));
    puts("wheel power boundaries, release guards, epochs and rotation passed");
}

#pragma once
#include "gesture_ui.h"
#include <cstring>

// All access is serialized by GestureService's mutex. Epochs also invalidate
// HTTP work admitted before a power transition, even if it finishes after wake.
class PowerGate {
    GesturePowerState state_ = GesturePowerState::Active;
    uint32_t epoch_ = 1;
public:
    GesturePowerState State() const { return state_; }
    uint32_t Epoch() const { return epoch_; }
    bool Active() const { return state_ == GesturePowerState::Active; }
    bool Accept(uint32_t epoch) const { return Active() && epoch == epoch_; }
    bool BeginShutdown() {
        if (!Active()) return false;
        state_ = GesturePowerState::ShuttingDown;
        ++epoch_;
        return true;
    }
    void Standby() { state_ = GesturePowerState::Standby; }
    bool Resume() {
        if (state_ != GesturePowerState::Standby) return false;
        state_ = GesturePowerState::Active;
        ++epoch_;
        return true;
    }
};
inline bool PowerRequestAllowed(GesturePowerState state, const char* path) {
    return state == GesturePowerState::Active || !strcmp(path, "/stop") || !strcmp(path, "/suspend");
}
inline GestureDisplayPage RotatedPage(GestureDisplayPage page, bool clockwise,
                                     bool pressed, GesturePowerState state) {
    if (pressed || state != GesturePowerState::Active) return page;
    return clockwise ? GestureDisplayPage::Data : GestureDisplayPage::Expression;
}

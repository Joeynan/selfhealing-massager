#pragma once
#include <cstdint>
#include <string>
enum class ButtonAction { None, Stop, Arm, Disarm, Shutdown };
class ButtonPolicy {
    bool down_ = false, disarmed_ = false, release_guard_ = true;
    uint32_t started_ = 0;

public:
    void Boot(bool pressed) { release_guard_ = pressed; }
    bool Pressed() const { return down_ || release_guard_; }
    void Down(uint32_t t) {
        if (release_guard_ || down_) return;
        down_ = true;
        disarmed_ = false;
        started_ = t;
    }
    ButtonAction Tick(uint32_t t) {
        if (down_ && !disarmed_ && uint32_t(t - started_) >= 3000) {
            disarmed_ = true;
            return ButtonAction::Disarm;
        }
        return ButtonAction::None;
    }
    ButtonAction Up(uint32_t t) {
        if (release_guard_) { release_guard_ = false; down_ = false; return ButtonAction::None; }
        if (!down_)
            return ButtonAction::None;
        down_ = false;
        uint32_t age = t - started_;
        return age >= 3000 ? ButtonAction::Shutdown : ButtonAction::None;
    }
};
class InputOwner {
    std::string source_ = "onboard";

public:
    bool Switch(const std::string& s) {
        if (s != "onboard" && s != "camera" && s != "simulation")
            return false;
        source_ = s;
        return true;
    }
    bool Accept(const std::string& s) const { return s == source_; }
    bool AllowsServoConfiguration() const { return source_ == "simulation"; }
    const std::string& Source() const { return source_; }
};

inline bool ShutdownReady(bool enabled, bool wanted, bool inflight, bool possible_motion,
                          uint32_t deadline, uint32_t now) {
    return !enabled && !wanted && !inflight && (!possible_motion || int32_t(deadline - now) <= 0);
}

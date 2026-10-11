#pragma once
#include <cstdint>
#include <cstring>
#include "servo_profile.h"
struct ModeCommand {
    uint32_t sequence = 0;
    uint8_t mode = 0;
    uint16_t lease_ms = 0;
};
struct TestCommand {
    uint32_t sequence = 0;
    uint8_t channel = 0;
    uint16_t pulse = 0, lease_ms = 0;
};
struct Applied {
    uint32_t sequence = 0;
    uint8_t mode = 0;
    uint16_t pulse_us[3] = {};
    uint32_t uptime_ms = 0;
};
inline bool ReadControlNumbers(const char* text, const char* prefix, uint32_t* numbers, int count) {
    size_t n = std::strlen(prefix);
    if (std::strncmp(text, prefix, n))
        return false;
    text += n;
    for (int i = 0; i < count; ++i) {
        if (*text < '0' || *text > '9')
            return false;
        uint32_t v = 0;
        while (*text >= '0' && *text <= '9') {
            uint32_t d = *text++ - '0';
            if (v > (UINT32_MAX - d) / 10)
                return false;
            v = v * 10 + d;
        }
        numbers[i] = v;
        if (i < count - 1) {
            if (*text++ != ' ')
                return false;
        } else if (*text)
            return false;
    }
    return true;
}
inline bool ParseSet(const char* s, ModeCommand& c) {
    uint32_t v[3];
    if (!ReadControlNumbers(s, "SET ", v, 3) || v[1] > 3 || v[2] < 100 || v[2] > 600)
        return false;
    c = {v[0], uint8_t(v[1]), uint16_t(v[2])};
    return true;
}
inline bool ParseTest(const char* s, TestCommand& c) {
    uint32_t v[4];
    if (!ReadControlNumbers(s, "TEST ", v, 4) || v[1] < 1 || v[1] > 3 || v[2] < 1000 ||
        v[2] > 2000 || v[3] < 100 || v[3] > 500)
        return false;
    c = {v[0], uint8_t(v[1]), uint16_t(v[2]), uint16_t(v[3])};
    return true;
}
inline bool ReadApplied(const char* s, const char* prefix, Applied& a) {
    uint32_t v[6];
    if (!ReadControlNumbers(s, prefix, v, 6) || v[1] > 3)
        return false;
    a.sequence = v[0];
    a.mode = v[1];
    for (int i = 0; i < 3; ++i) {
        if (v[i + 2] < 1000 || v[i + 2] > 2000)
            return false;
        a.pulse_us[i] = v[i + 2];
    }
    a.uptime_ms = v[5];
    return true;
}
inline bool ParseApplied(const char* s, Applied& a, const ServoProfile& p = ServoProfile()) {
    if (!ReadApplied(s, "APPLIED ", a))
        return false;
    for (int i = 0; i < 3; ++i)
        if (a.pulse_us[i] != (a.mode == i + 1 ? p.run[i] : p.neutral[i]))
            return false;
    return true;
}
class OutputState {
    bool enabled_, seen_ = false, active_ = false, test_ = false;
    uint32_t sequence_ = 0, deadline_ = 0;
    uint8_t mode_ = 0;
    uint16_t test_pulse_ = 1500;
    ServoProfile profile_;
    bool Accept(uint32_t seq) {
        if (seen_ && static_cast<int32_t>(seq - sequence_) <= 0)
            return false;
        seen_ = true;
        sequence_ = seq;
        return true;
    }

public:
    explicit OutputState(bool enabled = true) : enabled_(enabled) {}
    bool Configure(const ServoProfile& p) {
        if (mode_ || !p.Valid())
            return false;
        profile_ = p;
        return true;
    }
    void Enable(bool e) {
        enabled_ = e;
        mode_ = 0;
        test_ = false;
        active_ = false;
    }
    bool Apply(const ModeCommand& c, uint32_t now) {
        if (c.mode > 3 || c.lease_ms < 100 || c.lease_ms > 600 || !Accept(c.sequence))
            return false;
        mode_ = enabled_ ? c.mode : 0;
        test_ = false;
        active_ = true;
        deadline_ = now + c.lease_ms;
        return true;
    }
    bool ApplyTest(const TestCommand& c, uint32_t now) {
        if (c.channel < 1 || c.channel > 3 || c.pulse < 1000 || c.pulse > 2000 ||
            c.lease_ms < 100 || c.lease_ms > 500 || !Accept(c.sequence))
            return false;
        mode_ = enabled_ ? c.channel : 0;
        test_ = enabled_;
        test_pulse_ = c.pulse;
        active_ = true;
        deadline_ = now + c.lease_ms;
        return true;
    }
    bool Tick(uint32_t now) {
        if (active_ && static_cast<int32_t>(now - deadline_) >= 0) {
            active_ = false;
            bool changed = mode_ != 0;
            mode_ = 0;
            test_ = false;
            return changed;
        }
        return false;
    }
    void Disconnect() {
        mode_ = 0;
        active_ = false;
        test_ = false;
        seen_ = false;
    }
    uint32_t Remaining(uint32_t now) const {
        return active_ && static_cast<int32_t>(deadline_ - now) > 0 ? deadline_ - now : 0;
    }
    uint16_t Pulse(int i) const {
        return i < 0 || i >= 3  ? 0
               : mode_ == i + 1 ? (test_ ? test_pulse_ : profile_.run[i])
                                : profile_.neutral[i];
    }
    uint8_t Mode() const { return mode_; }
    uint32_t Sequence() const { return sequence_; }
};

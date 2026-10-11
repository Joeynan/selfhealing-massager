#pragma once
#include <cstdint>
#include <string>
// Ages arrive from the same Mac capture clock; no cross-device clock comparison.
class CameraActivity {
    std::string session_;
    uint32_t frame_ = 0, deadline_ = 0;
    bool seen_ = false;

public:
    bool Apply(const std::string& session, uint32_t frame, uint32_t age, uint32_t now) {
        if (session.empty() || session.size() > 64 || frame == 0 || age >= 600)
            return false;
        if (seen_ && session == session_ && frame <= frame_)
            return false;
        session_ = session;
        frame_ = frame;
        seen_ = true;
        deadline_ = now + 600 - age;
        return true;
    }
    bool Active(uint32_t now) const { return seen_ && static_cast<int32_t>(deadline_ - now) > 0; }
    uint32_t Remaining(uint32_t now) const { return Active(now) ? deadline_ - now : 0; }
};

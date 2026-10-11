#pragma once
#include <cstdint>
class LocalCaptureActivity {
    uint64_t id_ = 0;
    uint32_t captured_ = 0;
    bool seen_ = false;

public:
    bool Apply(bool valid, bool ready, uint64_t id, uint32_t captured, uint32_t now) {
        if (!valid || !ready) {
            seen_ = false;
            return false;
        }
        if (id <= id_)
            return false;  // Duplicates never restore invalidated health.
        if (int32_t(now - captured) < 0 || uint32_t(now - captured) >= 800) {
            seen_ = false;
            return false;
        }
        seen_ = true;
        id_ = id;
        captured_ = captured;
        return true;
    }
    bool Active(uint32_t now) const { return seen_ && uint32_t(now - captured_) < 800; }
    bool Seen() const { return seen_; }
    uint64_t Id() const { return id_; }
    uint32_t Captured() const { return captured_; }
};

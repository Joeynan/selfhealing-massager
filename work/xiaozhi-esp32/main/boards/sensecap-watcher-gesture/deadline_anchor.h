#pragma once
#include <cstdint>

// APPLIED uptime is sampled before its response reaches us. Translating from
// response receive time is therefore conservative, even with queued responses.
// Caller only supplies the current connection's fully matched APPLIED.
class DeadlineAnchor {
    bool seen_ = false;
    uint32_t remote_ = 0, received_ = 0;
public:
    void Reset() { seen_ = false; }
    void Acknowledge(uint32_t remote, uint32_t received) {
        seen_ = true; remote_ = remote; received_ = received;
    }
    bool Fresh(uint32_t now) const { return seen_ && now - received_ < 800; }
    bool Map(uint32_t local_deadline, uint32_t now, uint32_t& deadline) const {
        int32_t remaining = int32_t(local_deadline - now);
        if (!Fresh(now) || remaining <= 20 || remaining > 600) return false;
        deadline = remote_ + (local_deadline - received_) - 20;
        return true;
    }
};

#pragma once
#include <algorithm>
#include <array>
#include <cstdint>
#include <memory>
#include <vector>
namespace wifi_camera {
constexpr size_t kMaxJpeg = 98304;
// Remote uptime origins are unrelated. Date a capture relative to this request,
// charging the entire round trip (including SPI queues) against its freshness.
inline bool CaptureTime(uint32_t start, uint32_t received, uint32_t remote_capture,
                        uint32_t remote_send, uint32_t& local_capture) {
    uint32_t remote_age = remote_send - remote_capture;
    uint32_t elapsed = received - start;
    if (remote_age >= 800 || elapsed >= 800 || remote_age + elapsed >= 800)
        return false;
    local_capture = start - remote_age;
    return true;
}
struct Frame {
    uint32_t session = 0, id = 0, captured = 0;
    uint16_t width = 0, height = 0;
    std::vector<uint8_t> jpeg;
};
class Ledger {
    struct Entry {
        uint32_t id = 0, captured = 0;
        bool used = false;
    };
    std::array<Entry, 8> entries_{};
    uint32_t session_ = 0, last_ = 0;
    uint32_t result_ms_ = 0, last_result_id_ = 0;
    bool result_seen_ = false;
    size_t next_ = 0;

public:
    void Begin(uint32_t session) {
        session_ = session;
        last_ = last_result_id_ = 0;
        next_ = 0;
        entries_ = {};
        result_seen_ = false;
    }
    bool Record(uint32_t session, uint32_t id, uint32_t captured, uint32_t now) {
        if (!session || session != session_ || !id || id <= last_ ||
            uint32_t(now - captured) >= 800)
            return false;
        last_ = id;
        entries_[next_] = {id, captured, false};
        next_ = (next_ + 1) % entries_.size();
        return true;
    }
    bool Observe(uint32_t session, uint32_t id, uint32_t supplied_age, uint32_t now,
                 uint32_t& captured) {
        if (!session || session != session_ || !id || id <= last_result_id_ || supplied_age >= 800)
            return false;
        for (auto& e : entries_) {
            if (e.id != id) continue;
            uint32_t age = now - e.captured;
            if (e.used || age >= 800) return false;
            e.used = true;
            last_result_id_ = id;
            captured = now - std::max(age, supplied_age);
            result_seen_ = true;
            result_ms_ = captured;
            return true;
        }
        return false;
    }
    bool Consume(uint32_t session, uint32_t id, uint32_t supplied_age, uint16_t requested,
                 uint32_t now, uint16_t& lease) {
        if (session != session_ || !id || supplied_age >= 600 || requested < 100 || requested > 600)
            return false;
        for (auto& e : entries_)
            if (e.id == id) {
                uint32_t age = now - e.captured;
                if (e.used || age >= 800)
                    return false;
                uint32_t remaining =
                    std::min<uint32_t>({requested, 600, 800 - age, 600 - supplied_age});
                if (remaining < 100)
                    return false;
                e.used = true;
                result_seen_ = true;
                result_ms_ = now;
                lease = remaining;
                return true;
            }
        return false;
    }
    bool ResultActive(uint32_t now) const {
        return result_seen_ && uint32_t(now - result_ms_) < 800;
    }
};
}  // namespace wifi_camera

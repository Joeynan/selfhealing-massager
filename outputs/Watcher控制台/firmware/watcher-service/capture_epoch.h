#pragma once
#include <cstdint>
#include <string>
inline bool CaptureNeedsSession(const std::string& previous, const std::string& next,
                               uint32_t old_epoch, uint32_t new_epoch, bool restarted) {
    return previous != next || old_epoch != new_epoch || restarted;
}

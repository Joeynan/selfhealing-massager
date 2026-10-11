#pragma once
#include <cstdint>

// The protocol's minimum wire lease is 100ms. Finish shorter motion tails as
// neutral instead of sending a fresh nonzero command likely to arrive expired.
inline uint8_t ModeForRemainingLease(uint8_t requested_mode, uint32_t remaining,
                                    bool armed, bool desired) {
    return armed && desired && remaining >= 100 ? requested_mode : 0;
}

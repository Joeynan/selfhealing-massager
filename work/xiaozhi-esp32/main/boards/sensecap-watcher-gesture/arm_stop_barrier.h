#pragma once
#include <cstdint>

struct ArmStopExpectation {
    bool guarded = false;
    bool valid = false;
    uint32_t generation = 0;
};

// Call while holding the same mutex used to change generation and input source.
inline bool ArmStopBarrierAllows(bool enabled, const ArmStopExpectation& expected,
                                 uint32_t generation, bool source_matches) {
    return !enabled || !expected.guarded ||
           (expected.valid && expected.generation == generation && source_matches);
}

inline bool CameraSessionNeedsDisarm(uint32_t previous_session, bool wanted, bool enabled) {
    return previous_session != 0 || wanted || enabled;
}

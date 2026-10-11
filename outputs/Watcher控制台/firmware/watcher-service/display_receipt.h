#pragma once
#include <cstdint>
inline bool HasCurrentServoReceipt(uint8_t mode, uint32_t intent, uint32_t applied_intent,
                                   uint8_t applied_mode, const uint16_t expected[3],
                                   const uint16_t actual[3], uint32_t last_ack, uint32_t now) {
    if (!mode || mode != applied_mode || intent != applied_intent || now - last_ack > 600)
        return false;
    for (int i = 0; i < 3; ++i)
        if (expected[i] != actual[i])
            return false;
    return true;
}
inline bool FaceNeedsReceipt(uint8_t mode, bool wanted_arm, bool outputs_enabled) {
    return mode && (wanted_arm || outputs_enabled);
}

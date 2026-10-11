#pragma once
#include "control_protocol.h"

// A TEST with less than the minimum wire duration must finish as neutral MODE.
inline bool FinishServoTestTail(bool& active, OutputState& requested, uint32_t& remaining) {
    if (!active || remaining >= 100)
        return false;
    active = false;
    requested.Disconnect();
    remaining = 0;
    return true;
}

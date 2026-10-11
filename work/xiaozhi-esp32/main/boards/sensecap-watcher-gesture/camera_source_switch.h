#pragma once
#include <string>
#include "wifi_frame.h"

inline void ResetCameraCaptureOnSourceSwitch(bool previous_camera, bool next_camera,
                                            uint32_t& session, wifi_camera::Ledger& ledger,
                                            std::shared_ptr<const wifi_camera::Frame>& frame,
                                            std::string& error) {
    // A control-source reset must not invalidate the camera worker's live session
    // or its in-flight/consumed frame proofs when the physical source is unchanged.
    if (previous_camera && next_camera && session != 0)
        return;
    frame.reset();
    session = 0;
    ledger.Begin(0);
    error = "awaiting_camera_frame";
}

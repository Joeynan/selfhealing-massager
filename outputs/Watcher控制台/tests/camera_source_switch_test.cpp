#include <cassert>
#include <iostream>
#include "../firmware/watcher-service/camera_source_switch.h"

struct CaptureState {
    uint32_t session = 41;
    wifi_camera::Ledger ledger;
    std::shared_ptr<const wifi_camera::Frame> frame;
    std::string error = "";
    CaptureState() {
        ledger.Begin(session);
        auto f = std::make_shared<wifi_camera::Frame>();
        f->session = session; f->id = 10; f->captured = 1000;
        frame = f;
        assert(ledger.Record(session, 10, 1000, 1010));
        assert(ledger.Record(session, 11, 1020, 1030));
    }
    void Switch(bool previous_camera, bool next_camera) {
        ResetCameraCaptureOnSourceSwitch(previous_camera, next_camera,
                                        session, ledger, frame, error);
    }
};

int main() {
    CaptureState same;
    const auto original_frame = same.frame;
    uint32_t captured = 0;
    assert(same.ledger.Observe(41, 10, 20, 1050, captured));
    same.error = "prior_capture_status";
    same.Switch(true, true);
    // Same-source control reset must not interrupt the physical camera session.
    assert(same.session == 41 && same.frame == original_frame);
    assert(same.error == "prior_capture_status");
    // An already consumed proof remains spent after the control reset.
    assert(!same.ledger.Observe(41, 10, 20, 1060, captured));
    // An in-flight frame still has its real age/proof, and only one result wins.
    assert(same.ledger.Observe(41, 11, 30, 1060, captured));
    assert(captured == 1020);
    assert(!same.ledger.Observe(41, 11, 30, 1070, captured));
    assert(!same.ledger.Record(41, 11, 1020, 1070));
    assert(same.ledger.Record(41, 12, 1070, 1080));
    assert(same.ledger.Observe(41, 12, 10, 1090, captured));

    for (const auto change : {std::pair<bool, bool>{true, false}, {false, true}, {false, false}}) {
        CaptureState changed;
        changed.Switch(change.first, change.second);
        assert(changed.session == 0 && !changed.frame);
        assert(changed.error == "awaiting_camera_frame");
        assert(!changed.ledger.Record(41, 12, 1070, 1080));
        assert(!changed.ledger.Observe(41, 11, 30, 1060, captured));
    }
    CaptureState zero;
    zero.session = 0;
    zero.Switch(true, true);
    assert(zero.session == 0 && !zero.frame);
    assert(zero.error == "awaiting_camera_frame");
    assert(!zero.ledger.Record(41, 12, 1070, 1080));

    std::cout << "PASS camera source switch: same-camera capture/session/in-flight proof retained; consumed proof and duplicate frame rejected; changed/zero-session cleared\n";
}

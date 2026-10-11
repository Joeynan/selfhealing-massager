#include <cassert>
#include <cstdio>
#include "../firmware/watcher-service/gesture_hold.h"

int main() {
    GestureHold h;
    assert(h.Observe(100, 3, ObservationKind::Confirmed, true, true, 300, 110));
    assert(h.Face(110) == 3 && h.Motion(110) == 3);
    assert(h.FaceRemaining(110) == 4990);
    // Healthy hands in view, ordinary misses do not clear or renew the hold.
    for (uint32_t t = 500; t < 5100; t += 400)
        assert(h.Observe(t, 0, ObservationKind::Unrecognized, false, true, 0, t));
    assert(h.Motion(5099) == 3 && h.Face(5099) == 3);
    assert(h.Motion(5100) == 0 && h.Face(5100) == 0);
    assert(h.Observe(6000, 1, ObservationKind::Confirmed, true, true, 300, 6000));
    assert(h.Observe(6300, 1, ObservationKind::Confirmed, true, true, 300, 6300));
    assert(h.FaceRemaining(6300) == 5000);
    assert(h.Observe(6600, 2, ObservationKind::Confirmed, true, true, 300, 6600));
    assert(h.Face(6600) == 2 && h.Motion(6600) == 2);
    // No hands: neutral within 800 ms of the last real hand, keep face for 5s.
    assert(h.Observe(7000, 0, ObservationKind::NoHand, false, false, 0, 7000));
    assert(h.Observe(7390, 0, ObservationKind::NoHand, false, false, 0, 7390));
    assert(h.Motion(7400) == 0 && h.Face(7400) == 2);
    assert(h.Observe(7500, 0, ObservationKind::Unrecognized, false, true, 0, 7500));
    assert(h.Motion(7500) == 0);  // Health recovery cannot restart an old action.
    // A new confirmation may restart after normal hand loss.
    assert(h.Observe(7900, 3, ObservationKind::Confirmed, true, true, 300, 7900));
    assert(h.Motion(7900) == 3);
    // Cached stable values without this-frame evidence must never trigger.
    assert(!h.Observe(8000, 3, ObservationKind::Unrecognized, false, true, 0, 8000));
    assert(!h.Observe(7100, 1, ObservationKind::Confirmed, true, true, 300, 8000));
    // Full confirmation window must be after ARM (not only its final frame).
    h.ArmEpoch(8100);
    assert(h.Observe(8200, 3, ObservationKind::Confirmed, true, true, 300, 8200));
    assert(h.Motion(8200) == 0 && h.Face(8200) == 0);
    assert(h.Observe(8500, 3, ObservationKind::Confirmed, true, true, 300, 8500));
    assert(h.Motion(8500) == 3);
    assert(h.Observe(8600, 0, ObservationKind::Conflict, false, true, 0, 8600));
    assert(h.Motion(8600) == 0);
    h.Reset();
    assert(h.Face(8600) == 0 && !h.Healthy(8600));
    // STOP cancels cached action while retaining only the actual health timestamp.
    assert(h.Observe(9000, 3, ObservationKind::Confirmed, true, true, 300, 9000));
    h.Cancel();
    assert(h.Face(9100) == 0 && h.Motion(9100) == 0 && h.Healthy(9799));
    assert(!h.Healthy(9800));
    h.ArmEpoch(9100);
    assert(h.Observe(9200, 3, ObservationKind::Confirmed, true, true, 300, 9200));
    assert(h.Motion(9200) == 0);
    assert(h.Observe(9500, 3, ObservationKind::Confirmed, true, true, 300, 9500));
    assert(h.Motion(9500) == 3);
    // Wrap-safe deadlines and capture-relative expiry.
    h.Reset();
    uint32_t t = 0xfffffff0u;
    assert(h.Observe(t, 2, ObservationKind::Confirmed, true, true, 300, t + 10));
    assert(h.Motion(t + 799) == 2);
    assert(h.Motion(t + 800) == 0);
    assert(h.Face(t + 4999) == 2 && h.Face(t + 5000) == 0);
    puts("gesture_hold: five-second hold, switch, hand loss, epoch, and wrap passed");
}

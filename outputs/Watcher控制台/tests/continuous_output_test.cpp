#include <cassert>
#include "continuous_output.h"
#include "gesture_hold.h"

int main() {
    ContinuousOutput policy;
    assert(policy.Enabled());
    assert(!policy.ShouldArm(false, false, false, false));
    assert(policy.ShouldArm(true, false, false, false));
    assert(!policy.ShouldArm(true, true, true, false));
    assert(!policy.ShouldArm(true, false, false, true));
    // Fault only changes real readiness; permission survives and can recover.
    assert(!policy.ShouldArm(false, false, false, false));
    assert(policy.Enabled());
    assert(policy.ShouldArm(true, false, false, false));
    policy.SetEnabled(false);
    assert(!policy.ShouldArm(true, false, false, false));
    policy.SetEnabled(true);
    assert(policy.ShouldArm(true, false, false, false));
    // STOP and auto ARM cannot replay a pre-barrier stable result.
    GestureHold hold;
    assert(hold.Observe(1000, 3, ObservationKind::Confirmed, true, true, 300, 1000));
    assert(hold.Motion(1000) == 3);
    hold.Cancel(); hold.ArmEpoch(1050);
    assert(hold.Observe(1100, 3, ObservationKind::Confirmed, true, true, 300, 1100));
    assert(hold.Motion(1100) == 0);
    assert(hold.Observe(1400, 3, ObservationKind::Confirmed, true, true, 300, 1400));
    assert(hold.Motion(1400) == 3);
    assert(hold.Motion(2200) == 0);
    return 0;
}

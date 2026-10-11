#include <cassert>
#include <cstdint>
#include <iostream>
#include "../firmware/watcher-service/arm_stop_barrier.h"

int main() {
    const ArmStopExpectation manual{};
    assert(ArmStopBarrierAllows(true, manual, 7, false));
    ArmStopExpectation automatic{true, true, 7};
    assert(ArmStopBarrierAllows(true, automatic, 7, true));
    // The source reply captured 7. An explicit STOP/button/network fault raises
    // the generation before readiness: the delayed automatic ARM must fail.
    assert(!ArmStopBarrierAllows(true, automatic, 8, true));
    assert(!ArmStopBarrierAllows(true, automatic, 7, false));
    assert(!ArmStopBarrierAllows(true, {true, false, 7}, 7, true));
    // A stale expectation may never block an explicit disable.
    assert(ArmStopBarrierAllows(false, automatic, 8, false));
    assert(ArmStopBarrierAllows(false, {true, false, 7}, 8, false));

    uint32_t generation = UINT32_MAX;
    automatic.generation = generation;
    assert(ArmStopBarrierAllows(true, automatic, generation, true));
    ++generation;
    assert(generation == 0);
    assert(!ArmStopBarrierAllows(true, automatic, generation, true));
    automatic.generation = 0;
    assert(ArmStopBarrierAllows(true, automatic, generation, true));

    assert(!CameraSessionNeedsDisarm(0, false, false));
    assert(CameraSessionNeedsDisarm(0, true, false));
    assert(CameraSessionNeedsDisarm(0, false, true));
    assert(CameraSessionNeedsDisarm(23, false, false));
    assert(CameraSessionNeedsDisarm(23, true, true));
    std::cout << "PASS stop barrier: stale generation/source/malformed rejected, manual arm and disable retained, rollover, initial/restarted capture\n";
}

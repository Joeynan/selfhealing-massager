#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <iostream>
#include "../firmware/watcher-service/servo_test_tail.h"
#include "../firmware/watcher-service/deadline_anchor.h"
namespace receiver {
#include "../firmware/esp8266/watcher_controller/control_protocol.h"
}

int main() {
    OutputState requested(true);
    bool active = true;
    assert(requested.ApplyTest({1, 1, 1700, 500}, 1000));
    requested.Tick(1400);
    uint32_t remaining = requested.Remaining(1400);
    assert(remaining == 100);
    assert(!FinishServoTestTail(active, requested, remaining));
    assert(active && requested.Mode() == 1 && requested.Pulse(0) == 1700 && remaining == 100);

    requested.Tick(1401);
    remaining = requested.Remaining(1401);
    assert(remaining == 99);
    assert(FinishServoTestTail(active, requested, remaining));
    assert(!active && requested.Mode() == 0 && remaining == 0);
    for (int c = 0; c < 3; ++c) assert(requested.Pulse(c) == 1500);

    // Completion clears a request, not the permission to accept the next TEST.
    active = true;
    assert(requested.ApplyTest({2, 2, 2000, 500}, 2000));
    assert(requested.Tick(2500));
    remaining = requested.Remaining(2500);
    assert(FinishServoTestTail(active, requested, remaining));
    assert(!active && requested.Mode() == 0 && remaining == 0);
    assert(requested.ApplyTest({3, 3, 2000, 500}, 2600));
    assert(requested.Mode() == 3);

    // A short normal MODE lease is unrelated and keeps its original deadline.
    active = false;
    assert(requested.Apply({4, 1, 100}, 3000));
    remaining = requested.Remaining(3001);
    assert(!FinishServoTestTail(active, requested, remaining));
    assert(requested.Mode() == 1 && remaining == 99);
    assert(requested.Tick(3100) && requested.Mode() == 0);

    // A cancellation or a new normal input cannot resurrect/retain the old TEST.
    requested.Disconnect();
    remaining = 0;
    assert(!FinishServoTestTail(active, requested, remaining));
    assert(requested.Mode() == 0);
    assert(requested.Apply({5, 2, 600}, 3200));
    remaining = requested.Remaining(3200);
    assert(!FinishServoTestTail(active, requested, remaining));
    assert(requested.Mode() == 2 && remaining == 600);

    // The reported failure: an 80ms TEST remainder used to become MODE1. Its
    // cutoff maps to 1380, so arrival at 1385 correctly returned neutral and the
    // sender then rejected that valid neutral ACK as a channel mismatch.
    DeadlineAnchor clock;
    clock.Acknowledge(900, 1000);
    uint32_t old_cutoff = 0;
    assert(clock.Map(1500, 1420, old_cutoff) && old_cutoff == 1380);
    receiver::OutputState old_receiver(true);
    assert(old_receiver.Apply({1, 1, 100, old_cutoff, true}, 1385));
    assert(old_receiver.ExpiredCommand() && old_receiver.Mode() == 0);
    assert(old_receiver.Mode() != 1); // Strict ACK mismatch in the old sender.

    requested.Disconnect();
    assert(requested.ApplyTest({6, 1, 2000, 500}, 1000));
    active = true;
    requested.Tick(1420);
    remaining = requested.Remaining(1420);
    assert(remaining == 80 && FinishServoTestTail(active, requested, remaining));
    uint32_t cutoff = 0;
    assert(clock.Map(1420 + (requested.Mode() && remaining ? remaining : 600), 1420, cutoff));
    assert(cutoff == 1900);
    receiver::OutputState black(true);
    assert(black.Apply({2, requested.Mode(), uint16_t(std::max<uint32_t>(100, remaining)), cutoff, true}, 1385));
    assert(!black.ExpiredCommand() && black.Mode() == requested.Mode() && black.Mode() == 0);
    assert(black.Enabled());
    for (int c = 0; c < 3; ++c) assert(black.Pulse(c) == 1500);
    std::cout << "PASS TEST100 stays TEST; TEST99/expiry becomes neutral; late tail ACK matches; next TEST and normal MODE preserved\n";
}

#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstring>
#include <iostream>
#include "../firmware/watcher-service/mode_lease_tail.h"
#include "../firmware/watcher-service/deadline_anchor.h"
#include "../firmware/watcher-service/control_protocol.h"
namespace receiver {
#include "../firmware/esp8266/watcher_controller/control_protocol.h"
}

int main() {
    assert(ModeForRemainingLease(2, 100, true, true) == 2);
    assert(ModeForRemainingLease(2, 99, true, true) == 0);
    assert(ModeForRemainingLease(2, 20, true, true) == 0);
    for (uint8_t mode = 0; mode <= 3; ++mode) {
        assert(ModeForRemainingLease(mode, 600, true, true) == mode);
        assert(ModeForRemainingLease(mode, 100, true, true) == mode);
        for (uint32_t remaining : {0u, 1u, 20u, 21u, 80u, 99u})
            assert(ModeForRemainingLease(mode, remaining, true, true) == 0);
        assert(ModeForRemainingLease(mode, 600, false, true) == 0);
        assert(ModeForRemainingLease(mode, 600, true, false) == 0);
    }

    // A normal simulation input can finish without an ARM permission change.
    OutputState requested(true);
    assert(requested.Apply({1, 2, 600}, 1000));
    requested.Tick(1520);
    const uint32_t remaining = requested.Remaining(1520);
    assert(remaining == 80 && requested.Mode() == 2);
    const uint8_t mode = ModeForRemainingLease(requested.Mode(), remaining, true, true);
    assert(mode == 0 && requested.Mode() == 2 && requested.Remaining(1520) == 80);

    DeadlineAnchor clock;
    clock.Acknowledge(900, 1000);
    // Old rem80 was rounded to a 100ms wire lease, but its deadline remained
    // only 80ms away (minus the conservative 20ms), so receipt at1485 was late.
    uint32_t old_cutoff = 0;
    assert(clock.Map(1600, 1520, old_cutoff) && old_cutoff == 1480);
    receiver::OutputState old_black(true);
    assert(old_black.Apply({1, 2, 100, old_cutoff, true}, 1485));
    assert(old_black.ExpiredCommand() && old_black.Mode() == 0);
    assert(old_black.Mode() != 2); // Existing strict ACK rejected this MODE tail.

    uint32_t cutoff = 0;
    assert(clock.Map(1520 + (mode ? remaining : 600), 1520, cutoff));
    assert(cutoff == 2000);
    receiver::OutputState black(true);
    assert(black.Apply({2, mode, uint16_t(std::max<uint32_t>(100, remaining)), cutoff, true}, 1485));
    assert(!black.ExpiredCommand() && black.Mode() == mode && black.Enabled());
    for (int channel = 0; channel < 3; ++channel) assert(black.Pulse(channel) == 1500);
    // Do not widen the actual requested motion deadline or relax a late ACK.
    assert(!black.Apply({2, 2, 600, cutoff, true}, 1486));
    receiver::OutputState late_black(true);
    const uint8_t valid_mode = ModeForRemainingLease(2, 100, true, true);
    assert(valid_mode == 2);
    assert(late_black.Apply({1, valid_mode, 100, old_cutoff, true}, 1485));
    assert(late_black.ExpiredCommand() && late_black.Mode() != valid_mode);

    // Fresh new simulation input starts normally after the neutral tail.
    assert(requested.Apply({2, 3, 600}, 1601));
    assert(ModeForRemainingLease(requested.Mode(), requested.Remaining(1601), true, true) == 3);
    std::cout << "PASS MODE100 preserved; MODE99/20 neutral; late tail ACK matches without disarm; duplicate/real late deadline protections unchanged; new motion accepted\n";
}

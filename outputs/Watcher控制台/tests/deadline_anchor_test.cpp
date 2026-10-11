#include <cassert>
#include <cstdio>
#include "../firmware/watcher-service/deadline_anchor.h"
int main() {
    DeadlineAnchor a;
    uint32_t deadline;
    assert(!a.Map(1600, 1000, deadline));
    a.Acknowledge(9000, 1000);
    assert(a.Map(1600, 1000, deadline) && deadline == 9580);
    assert(a.Map(1800, 1200, deadline) && deadline == 9780);
    assert(!a.Map(2000, 1800, deadline));
    assert(!a.Map(1010, 1000, deadline));
    assert(!a.Map(1700, 1000, deadline));
    a.Reset();
    assert(!a.Map(1600, 1000, deadline));
    a.Acknowledge(0xfffffff0u, 0xfffffff0u);
    assert(a.Map(0xfffffff0u + 600, 0xfffffff0u, deadline));
    assert(deadline == 0xfffffff0u + 580);
    puts("deadline_anchor: conservative remote cutoff, expiry, and wrap passed");
}

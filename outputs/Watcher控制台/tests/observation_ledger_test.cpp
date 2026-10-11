#include <cassert>
#include <cstdio>
#include "../firmware/watcher-service/wifi_frame.h"
int main() {
    wifi_camera::Ledger l;
    l.Begin(7);
    uint32_t captured = 0;
    assert(l.Record(7, 1, 1000, 1000));
    assert(l.Observe(7, 1, 799, 1799, captured) && captured == 1000);
    assert(l.ResultActive(1799) && !l.ResultActive(1800));
    assert(!l.Observe(7, 1, 0, 1799, captured));
    assert(l.Record(7, 2, 2000, 2000));
    assert(l.Record(7, 3, 2100, 2100));
    assert(l.Observe(7, 3, 20, 2120, captured));
    assert(!l.Observe(7, 2, 130, 2130, captured));
    assert(!l.Observe(8, 3, 0, 2130, captured));
    l.Begin(8);
    assert(!l.ResultActive(2130));
    assert(l.Record(8, 1, 2200, 2200));
    assert(l.Observe(8, 1, 700, 2250, captured) && captured == 1550);
    assert(!l.ResultActive(2350));
    puts("observation_ledger: 799ms evidence, capture age, duplicate/order/session passed");
}

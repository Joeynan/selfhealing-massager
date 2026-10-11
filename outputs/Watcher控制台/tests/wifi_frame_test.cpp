#include "../firmware/watcher-service/wifi_frame.h"
#include <cassert>
int main() {
    wifi_camera::Ledger ledger;
    ledger.Begin(42);
    uint32_t capture = 0;
    assert(wifi_camera::CaptureTime(1000, 1100, 999000, 999050, capture));
    assert(capture == 950);  // Charge the entire request round trip.
    assert(!wifi_camera::CaptureTime(1000, 1750, 999000, 999050, capture));
    assert(!wifi_camera::CaptureTime(1000, 1100, 999050, 999000, capture));
    assert(ledger.Record(42, 1, 950, 1100));
    assert(!ledger.Record(42, 1, 1100, 1100));
    assert(!ledger.Record(43, 2, 1100, 1100));
    uint16_t lease = 0;
    assert(ledger.Consume(42, 1, 50, 600, 1100, lease));
    assert(lease == 550);
    assert(ledger.ResultActive(1899));
    assert(!ledger.ResultActive(1900));
    assert(!ledger.Consume(42, 1, 0, 600, 1100, lease));
    assert(ledger.Record(42, 2, 1100, 1100));
    assert(!ledger.Consume(42, 2, 600, 600, 1100, lease));
    assert(ledger.Consume(42, 2, 550, 600, 1100, lease) == false);  // <100 lease never extended.
    ledger.Begin(43);
    assert(!ledger.ResultActive(1100));
    assert(!ledger.Consume(42, 2, 0, 600, 1100, lease));
    for (uint32_t i = 1; i <= 9; i++)
        assert(ledger.Record(43, i, 1200, 1200));
    assert(!ledger.Consume(43, 1, 0, 600, 1200, lease));  // bounded history eviction
    assert(ledger.Consume(43, 9, 0, 600, 1900, lease));
    assert(lease == 100);
    assert(ledger.Record(43, 10, 1900, 1900));
    assert(!ledger.Consume(43, 10, 0, 600, 2700, lease));
    assert(wifi_camera::CaptureTime(UINT32_MAX - 30, 20, 5, 25, capture));
    assert(uint32_t(20 - capture) == 71);
}

#include <cassert>
#include <cstdio>
#include <iostream>
#include "../firmware/esp8266/watcher_controller/control_protocol.h"

ModeCommand Deadline(uint32_t sequence, uint8_t mode, uint16_t lease, uint32_t deadline) {
  char line[100];
  std::snprintf(line, sizeof(line), "SET2 %lu %u %u %lu", (unsigned long)sequence,
                mode, lease, (unsigned long)deadline);
  ModeCommand command;
  assert(ParseSet(line, command));
  return command;
}

int main() {
  ModeCommand command;
  assert(!ParseSet("SET2 1 1 601 2000", command));
  assert(!ParseSet("SET2 1 1 600 4294967296", command));
  assert(!ParseSet("SET2 1 1 600 2000 extra", command));
  OutputState state(true);
  // A packet's absolute deadline wins over its nominal 600 ms lease.
  assert(state.Apply(Deadline(1, 1, 600, 1500), 1000));
  assert(state.Mode() == 1 && state.Remaining(1000) == 500);
  assert(!state.Tick(1499)); assert(state.Tick(1500));
  assert(state.Pulse(0) == 1500 && state.Mode() == 0);
  // Arrival cannot grant a full new lease, even when fewer than 100 ms remain.
  assert(state.Apply(Deadline(2, 2, 600, 1800), 1765));
  assert(state.Remaining(1765) == 35 && state.Mode() == 2);
  assert(state.Pulse(0) == 1500 && state.Pulse(1) == 2000 && state.Pulse(2) == 1500);
  assert(state.Tick(1800));
  // Consume a late sequence, return neutral, and prevent its replay from reviving it.
  assert(state.Apply(Deadline(3, 3, 600, 1700), 1801));
  assert(state.Sequence() == 3 && state.Mode() == 0 && state.Remaining(1801) == 0);
  assert(!state.Apply(Deadline(3, 3, 600, 2400), 1810));
  assert(!state.Apply(Deadline(2, 1, 600, 2400), 1810));
  // The nominal lease still bounds a far-future absolute deadline.
  assert(state.Apply(Deadline(4, 3, 100, 5000), 1900));
  assert(state.Remaining(1900) == 100); assert(state.Tick(2000));
  // uint32 millis rollover is interpreted with signed deadline comparisons.
  OutputState wrap(true);
  assert(wrap.Apply(Deadline(UINT32_MAX, 1, 600, 120), 0xffffff00u));
  assert(wrap.Remaining(0xffffff00u) == 376);
  assert(!wrap.Tick(119)); assert(wrap.Tick(120));
  assert(wrap.Apply(Deadline(0, 2, 600, 500), 130));
  assert(wrap.Pulse(0) == 1500 && wrap.Pulse(1) == 2000);
  wrap.Disconnect();
  assert(wrap.Mode() == 0 && wrap.Remaining(131) == 0);
  std::cout << "PASS absolute deadlines, late/replayed packets, short remainder, rollover, one active channel\n";
}

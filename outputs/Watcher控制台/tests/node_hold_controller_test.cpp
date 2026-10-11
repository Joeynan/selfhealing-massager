// Execute the production sketch against a controlled clock, network and servos.
#include <cassert>
#include <iostream>
#include "../firmware/esp8266/watcher_controller/watcher_controller.ino"

void FeedHold(const char* line) { client.incoming += line; loop(); }
void DrainHold() { while (tx.Size()) pumpTx(); }
void ConnectHold(bool capability = true) {
  disconnectController(); nextConnect = millis(); preferSaved = true;
  assert(ParseTargetIp("10.20.74.207", targetIp));
  strcpy(watcherId, "watcher-10b41de6009c");
  client.outgoing.clear(); loop(); DrainHold();
  assert(client.outgoing.find("6 hold_protocol=2\n") != std::string::npos);
  FeedHold(capability ? "WELCOME SERVO360 watcher-10b41de6009c 6 hold_protocol=2\n"
                      : "WELCOME SERVO360 watcher-10b41de6009c 6\n");
  DrainHold(); assert(identity.Verified());
  assert(client.outgoing.find(capability ? "READY SERVO360 watcher-10b41de6009c hold_protocol=2\n"
                                        : "READY SERVO360 watcher-10b41de6009c hold_protocol=0\n") != std::string::npos);
  assert(!armed && attachedMask() == 0);
}
void ProfileHold(uint32_t sequence) {
  char line[128];
  snprintf(line, sizeof(line), "PROFILE %lu 1500 1500 1500 2000 2000 2000\n", (unsigned long)sequence);
  FeedHold(line); assert(profileConfirmed);
}
void SetHold(uint32_t sequence, uint8_t mode, uint32_t deadline, uint16_t lease = 600) {
  char line[128]; snprintf(line, sizeof(line), "SET2 %lu %u %u %lu\n", (unsigned long)sequence,
                           mode, lease, (unsigned long)deadline);
  FeedHold(line);
}
int main() {
  setup(); assert(!armed && attachedMask() == 0 && profile.run[0] == 2000);
  // A verified older Watcher still cannot arm or activate through SET/SET2/TEST.
  ConnectHold(false); ProfileHold(1); FeedHold("ARM 2 1\n");
  assert(!armed && attachedMask() == 0);
  FeedHold("SET 3 2 600\n"); assert(output.Mode() == 0 && lastSeq == 2);
  SetHold(3, 2, millis() + 500); assert(output.Mode() == 0 && lastSeq == 2);
  FeedHold("TEST 3 2 2000 500\n"); assert(output.Mode() == 0 && attachedMask() == 0);
  // An unarmed neutral legacy SET is allowed for a current APPLIED clock anchor.
  ConnectHold(); FeedHold("SET 1 0 600\n"); DrainHold();
  assert(client.outgoing.find("APPLIED 1 0 1500 1500 1500 ") != std::string::npos);
  assert(attachedMask() == 0); ProfileHold(2); FeedHold("ARM 3 1\n");
  assert(armed && attachedMask() == 7 && identity.HoldProtocol() == 2);
  const uint32_t firstDeadline = millis() + 500;
  SetHold(4, 1, firstDeadline);
  assert(output.Mode() == 1 && servos[0].pulse == 2000 && servos[1].pulse == 1500 && servos[2].pulse == 1500);
  // Duplicates/old sequence cannot extend the deadline or switch channels.
  fakeNow += 200; SetHold(4, 3, millis() + 600); assert(output.Mode() == 1);
  SetHold(3, 2, millis() + 600); assert(output.Mode() == 1);
  assert(output.Remaining(millis()) <= firstDeadline - millis());
  // Old SET cannot bypass the deadline policy while armed, including SET mode 0.
  FeedHold("SET 5 2 600\n"); assert(output.Mode() == 1 && lastSeq == 4);
  FeedHold("SET 5 0 600\n"); assert(output.Mode() == 1 && lastSeq == 4);
  // A newer but expired packet consumes its sequence and immediately returns neutral.
  SetHold(5, 2, millis() - 1); DrainHold();
  assert(output.Mode() == 0 && lastSeq == 5 && servos[0].pulse == 1500);
  assert(history[historyCount - 1].reason == 8 && history[historyCount - 1].sequence == 5);
  assert(client.outgoing.find("APPLIED 5 0 1500 1500 1500 ") != std::string::npos);
  SetHold(5, 2, millis() + 600); assert(output.Mode() == 0);
  // A deadline with <100 ms remaining must never receive a fresh 600 ms extension.
  const uint32_t shortDeadline = millis() + 35;
  SetHold(6, 2, shortDeadline);
  assert(output.Mode() == 2 && output.Remaining(millis()) <= 35);
  assert(servos[0].pulse == 1500 && servos[1].pulse == 2000 && servos[2].pulse == 1500);
  fakeNow = shortDeadline; loop();
  assert(output.Mode() == 0 && servos[1].pulse == 1500);
  SetHold(7, 3, millis() + 500);
  assert(servos[0].pulse == 1500 && servos[1].pulse == 1500 && servos[2].pulse == 2000);
  disconnectController(); assert(!armed && attachedMask() == 0 && !output.Enabled());
  assert(servos[2].pulse == 1500);
  ConnectHold(); assert(!armed && !profileConfirmed && attachedMask() == 0);
  ProfileHold(1); FeedHold("ARM 2 1\n"); assert(armed);
  fakeNow += 700; SetHold(3, 1, millis() + 500);
  assert(!client.connected() && !armed && attachedMask() == 0 && output.Mode() == 0);
  // Absolute deadlines and the sketch session guard also survive millis rollover.
  fakeNow = 0xfffffff0u; ConnectHold(); ProfileHold(1); FeedHold("ARM 2 1\n");
  SetHold(3, 1, 50); assert(output.Mode() == 1);
  fakeNow = 50; loop(); assert(output.Mode() == 0 && servos[0].pulse == 1500);
  std::cout << "PASS actual sketch: HELLO/READY capability, legacy preview gate, late/replayed SET2, short remainder, disconnect/reconnect, neutral pulses, rollover\n";
}

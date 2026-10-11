// Host-side integration: execute the actual sketch with fake networking/Servo/EEPROM.
#include <cassert>
#include <iostream>
#include "../firmware/esp8266/watcher_controller/watcher_controller.ino"

void Feed(const char* line) { client.incoming += line; loop(); }
void FeedSet(uint32_t seq,uint8_t mode,uint16_t lease) {
 char line[100];snprintf(line,sizeof(line),"SET2 %lu %u %u %lu\n",(unsigned long)seq,mode,lease,(unsigned long)(millis()+lease));Feed(line);
}
void Connect(const char* id) {
  disconnectController();
  nextConnect = 0; preferSaved = true;
  ParseTargetIp("10.20.74.207", targetIp); strcpy(watcherId, id);
  loop(); assert(client.connected()); assert(!identity.Verified());
}
void Profile(uint32_t sequence = 1) {
  char line[128]; snprintf(line, sizeof(line), "PROFILE %lu 1500 1500 1500 2000 2000 2000\n", (unsigned long)sequence);
  Feed(line); assert(profileConfirmed);
}
int main() {
  setup();
  assert(!armed && attachedMask() == 0 && persistenceHealthy);
  assert(Serial.text.find("CONFIG_AUTH user=admin key=") != std::string::npos);
  const char* id = "watcher-10b41de6009c";
  Connect(id); fakeNow += 1500; loop();
  assert(!identity.Verified() && !client.connected() && attachedMask() == 0);
  Connect(id); Feed("ARM 1 1\n");
  assert(!armed && attachedMask() == 0 && !client.connected());
  Connect(id); Feed("WELCOME SERVO360 watcher-aaaaaaaaaaaa 6\n");
  assert(!armed && attachedMask() == 0 && !client.connected());
  Connect(id); Feed("WELCOME SERVO360 watcher-10b41de6009c 6 hold_protocol=2\n");
  assert(identity.Verified() && !armed);
  Feed("ARM 1 1\n"); assert(!armed && attachedMask() == 0); // profile required
  Profile(2); Feed("ARM 3 1\n"); assert(armed && attachedMask() == 7);
  FeedSet(4,1,600);
  assert(output.Mode() == 1 && servos[0].pulse == 2000 && servos[1].pulse == 1500 && servos[2].pulse == 1500);
  fakeNow += 300; FeedSet(4,1,600); // duplicate cannot renew deadline
  fakeNow += 301; loop();
  assert(output.Mode() == 0 && servos[0].pulse == 1500);
  fakeNow += 100; loop(); assert(!armed && attachedMask() == 0);
  assert(history[historyCount - 1].attached_mask == 0);
  Connect(id); Feed("WELCOME SERVO360 watcher-10b41de6009c 6 hold_protocol=2\n");
  assert(!profileConfirmed && !armed && attachedMask() == 0);
  Profile(); Feed("ARM 2 1\n"); Feed("TEST 3 2 1760 500\n");
  assert(output.Mode() == 2 && servos[1].pulse == 1760 && servos[0].pulse == 1500);
  fakeNow += 501; loop(); assert(output.Mode() == 0 && servos[1].pulse == 1500);
  portal.authenticated = true; portalPage();
  assert(!armed && attachedMask() == 0 && !client.connected());
  assert(portal.body.find("name='csrf'") != std::string::npos);
  portal.authenticated = false; portal.args["target_ip"] = "10.20.74.99"; portalPair();
  assert(targetIp[3] == 207); // unauthenticated configuration is ignored
  portal.authenticated = true; portal.args["csrf"] = "wrong"; portalPair();
  assert(portal.status == 403 && targetIp[3] == 207);
  portal.args["csrf"] = csrfToken; portal.args["watcher_id"] = id; portalPair();
  assert(portal.status == 200 && targetIp[3] == 99 && !armed && attachedMask() == 0);
  NodeStoredRecord saved; EEPROM.get(0, saved); assert(saved.target_ip[3] == 99);
  bool migrated = false; uint8_t restoredIp[4]; char restoredId[32]; ServoProfile restored;
  assert(LoadNodeRecord(saved, restored, restoredIp, restoredId, migrated) && !strcmp(restoredId, id));
  // A changed IP can be discovered, but unrelated identities/ports cannot be selected.
  MDNS.answers = {{"watcher-aaaaaaaaaaaa.local.", {10,20,74,10}, 8888},
                  {"watcher-10b41de6009c.local.", {10,20,74,88}, 8888},
                  {"watcher-10b41de6009c.local.", {10,20,74,89}, 9999}};
  nextDiscovery = 0; preferSaved = false;
  IPAddress discovered; char expected[32] = {};
  assert(choosePeer(discovered, expected, millis()));
  assert(candidateCount == 1 && discovered[3] == 88 && !strcmp(expected, id));
  MDNS.answers.clear(); candidateCount = 0;
  Connect(id); Feed("WELCOME SERVO360 watcher-10b41de6009c 6 hold_protocol=2\n");
  Profile(); EEPROM.canCommit = false;
  Feed("PROFILE 2 1490 1500 1500 1990 2000 2000\n");
  assert(!persistenceHealthy && !profileConfirmed && profile.neutral[0] == 1500);
  Feed("ARM 3 1\n"); assert(!armed && attachedMask() == 0);
  EEPROM.canCommit = true; Profile(4);
  assert(persistenceHealthy); Feed("ARM 5 1\n"); assert(armed && attachedMask() == 7);
  fakeNow += 700;
  FeedSet(6,2,600);
  assert(!client.connected() && !armed && attachedMask() == 0 && output.Mode() == 0);
  disarm(5); assert(attachedMask() == 0);
  std::cout << "PASS actual sketch: welcome/profile/arm gate, expiry/duplicate, reconnect/config detach, persistence failure, submitted pulses\n";
}

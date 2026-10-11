// 黑色 ESP-12F / NodeMCU 固件入口；用 Arduino IDE 编译本目录，保留所有配套头文件。
// Wi-Fi 名称和密码只在私有 wifi_settings.h 填写；目标小智由发现/配对信息确定。
#include <ESP8266WiFi.h>
#include <ESP8266mDNS.h>
#include <ESP8266WebServer.h>
#include <EEPROM.h>
#include <Servo.h>
extern "C" {
#include <osapi.h>
}
#include "wifi_settings.h"
#include "output_settings.h"
#include "control_protocol.h"
#include "stop_protocol.h"
#include "tx_queue.h"
#include "node_state.h"
#include "node_event.h"
#include "node_portal_guard.h"

WiFiClient client;
ESP8266WebServer portal(80);
TxQueue tx;
Servo servos[3];
OutputState output(false);
ServoProfile profile;
NodeIdentityGate identity;
StopLineParser parser;
constexpr uint16_t kControllerPort = 8888;
// 通道顺序固定：捶打 D1(GPIO5)、揉搓 D2(GPIO4)、轻捏 D3(GPIO0)。
// Servo 按 50Hz 输出；当前默认运行 2000µs、中立 1500µs，由配置与校准状态提供。
const uint8_t pins[3] = {D1, D2, D3};
static_assert(D1 == 5 && D2 == 4 && D3 == 0, "NodeMCU pin map required");
static_assert(sizeof(NodeStoredRecord) <= 512, "EEPROM record exceeds reserved area");
NodeStoredRecord stored;
uint8_t targetIp[4] = {};
char watcherId[32] = {}, csrfToken[33] = {}, nodeHostname[32] = {};
bool armed = false, reportedWifi = false, mdnsStarted = false, sendFailed = false;
bool seen = false, preferSaved = true, profileConfirmed = false, persistenceHealthy = false;
uint32_t lastSeq = 0, lastReceive = 0, welcomeBegan = 0, nextConnect = 0;
uint32_t nextWifiRetry = 0, nextDiscovery = 0, eventId = 0;
uint16_t written[3] = {};
uint8_t writtenMode = 255, writtenMask = 255;
NodeOutputEvent history[8];
uint8_t historyCount = 0;
struct PeerCandidate { IPAddress ip; char id[32] = {}; };
PeerCandidate candidates[8];
uint8_t candidateCount = 0, candidateIndex = 0;
IPAddress connectingIp;

void sendLine(const char* line) { if (!tx.Push(line)) sendFailed = true; }
void pumpTx() {
  size_t count = tx.NextSize(client.availableForWrite());
  if (count) tx.Consume(client.write(reinterpret_cast<const uint8_t*>(tx.Data()), count));
}
uint8_t attachedMask() {
  uint8_t mask = 0;
  for (int index = 0; index < 3; ++index) if (servos[index].attached()) mask |= uint8_t(1u << index);
  return mask;
}
void event(uint8_t reason) {
  NodeOutputEvent record;
  record.id = ++eventId; record.sequence = lastSeq; record.reason = reason;
  record.mode = output.Mode(); record.uptime = millis(); record.attached_mask = attachedMask();
  for (int index = 0; index < 3; ++index) record.submitted[index] = output.Pulse(index);
  char line[128];
  if (!record.Format(line, sizeof(line), false)) return;
  Serial.print(line);
  if (historyCount == 8) { for (int index = 0; index < 7; ++index) history[index] = history[index + 1]; historyCount = 7; }
  history[historyCount++] = record;
  if (client.connected() && identity.Verified()) sendLine(line);
}
// 切换前先让所有通道回中立，再设置选中一路；日志记录提交值，不推断机械转动。
bool writeOutputs(uint8_t reason) {
  bool changed = writtenMode != output.Mode() || writtenMask != attachedMask();
  for (int index = 0; index < 3; ++index) changed = changed || written[index] != output.Pulse(index);
  if (!changed) return false;
  // Submitted pulse is a software value. Only explicitly armed, verified sessions emit waveforms.
  if (armed && identity.Verified()) {
    for (int index = 0; index < 3; ++index) servos[index].writeMicroseconds(profile.neutral[index]);
    if (output.Mode()) servos[output.Mode() - 1].writeMicroseconds(output.Pulse(output.Mode() - 1));
  }
  writtenMode = output.Mode(); writtenMask = attachedMask();
  for (int index = 0; index < 3; ++index) written[index] = output.Pulse(index);
  event(reason); return true;
}
// 禁用先短暂输出中立再解除信号，区别于只把运行通道设置为 1500µs。
void disarm(uint8_t reason) {
  output.Enable(false);
  if (attachedMask()) {
    for (int index = 0; index < 3; ++index) if (servos[index].attached()) servos[index].writeMicroseconds(profile.neutral[index]);
    delay(25);
    for (auto& servo : servos) servo.detach();
  }
  armed = false;
  // Report the mask after detach, rather than treating neutral pulse as output disabled.
  writeOutputs(reason);
}
void disconnectController() {
  output.Disconnect(); disarm(4); client.stop(20);
  identity.Reset(); profileConfirmed = false; parser = StopLineParser(); seen = false;
  nextConnect = millis() + 1000; tx.Clear(); sendFailed = false;
}
bool sessionExpired(uint32_t now) {
  return identity.Verified() ? uint32_t(now - lastReceive) > 650
                             : uint32_t(now - welcomeBegan) >= 1500;
}
void randomHex(char value[33]) {
  for (int index = 0; index < 4; ++index) snprintf(value + index * 8, 9, "%08lx", (unsigned long)os_random());
  value[32] = 0;
}
bool saveSettings() {
  NodeStoredRecord replacement = MakeNodeRecord(profile, targetIp, watcherId);
  memcpy(replacement.portal_key, stored.portal_key, sizeof(replacement.portal_key));
  SealNodeRecord(replacement);
  if (persistenceHealthy && !memcmp(&replacement, &stored, sizeof(stored))) return true;
  EEPROM.put(0, replacement);
  persistenceHealthy = EEPROM.commit();
  if (!persistenceHealthy) { Serial.println("PERSIST_FAILED outputs_disabled=1"); return false; }
  stored = replacement; return true;
}
// EEPROM 只保存校准、配对及本地配置身份；重新启动不会继承上一次已启用会话。
void loadSettings() {
  EEPROM.begin(512); EEPROM.get(0, stored);
  bool migrated = false;
  if (!LoadNodeRecord(stored, profile, targetIp, watcherId, migrated)) {
    profile = ServoProfile(); memset(targetIp, 0, sizeof(targetIp)); watcherId[0] = 0;
    stored = MakeNodeRecord(profile, targetIp, watcherId); stored.checksum = 0;
  } else persistenceHealthy = true;
  if (strlen(stored.portal_key) != 32) { randomHex(stored.portal_key); stored.checksum = 0; }
  if (migrated) { stored.profile_version = 1; Serial.println("PROFILE_DEFAULT_MIGRATED version=2 run_us=2000,2000,2000"); }
  saveSettings(); output.Configure(profile);
}
bool portalAuthenticated() {
  if (portal.authenticate("admin", stored.portal_key)) return true;
  portal.requestAuthentication(DIGEST_AUTH, "Watcher pairing", "需要黑色板的本地配置密码"); return false;
}
void portalPage() {
  if (!portalAuthenticated()) return;
  // Opening authenticated configuration immediately disables and detaches outputs.
  disconnectController();
  String page; page.reserve(2000);
  page = F("<!doctype html><html lang='zh-CN'><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>黑色板配对</title><style>body{font:16px sans-serif;max-width:560px;margin:32px auto;padding:16px;background:#f5f6f4;color:#173b38}input,button{font:inherit;padding:12px;box-sizing:border-box;width:100%;margin:8px 0 20px;border:1px solid #9baea8;border-radius:8px}button{background:#007e72;color:white}p{line-height:1.6}</style><h1>连接小智</h1><p>输出已禁用。请查看小智屏幕上的 IP，并填写下面的信息。</p><form method='post' action='/pair'><label>小智 IP</label><input name='target_ip' required maxlength='15' inputmode='decimal' value='");
  if (UnicastTargetIp(targetIp)) page += IPAddress(targetIp).toString();
  page += F("'><label>小智设备编号（首次配对可留空）</label><input name='watcher_id' maxlength='20' value='");
  page += watcherId; page += F("'><input type='hidden' name='csrf' value='"); page += csrfToken;
  page += F("'><button type='submit'>保存并验证小智</button></form><p>首次配对以小智的 v6 握手登记设备编号。之后 IP 改变时仍须匹配同一编号。保存后不会自动启用舵机。</p></html>");
  portal.sendHeader("Cache-Control", "no-store"); portal.send(200, "text/html; charset=utf-8", page);
}
void portalPair() {
  if (!portalAuthenticated()) return;
  if (!NodePortalRequestAllowed(true, csrfToken, portal.arg("csrf").c_str())) { portal.send(403, "text/plain; charset=utf-8", "配置页面已失效，请重新打开页面。"); return; }
  uint8_t address[4]; String id = portal.arg("watcher_id");
  if (!ParseTargetIp(portal.arg("target_ip").c_str(), address) || (id.length() && !ValidWatcherId(id.c_str()))) {
    portal.send(400, "text/plain; charset=utf-8", "请填写有效 IP；设备编号应为 watcher- 加 12 位小写十六进制。"); return;
  }
  disconnectController(); memcpy(targetIp, address, 4); strncpy(watcherId, id.c_str(), sizeof(watcherId) - 1); watcherId[31] = 0;
  candidateCount = candidateIndex = 0; preferSaved = true; nextDiscovery = 0;
  if (!saveSettings()) { portal.send(500, "text/plain; charset=utf-8", "保存失败，输出保持禁用，请重试。"); return; }
  Serial.println("TARGET_CONFIGURED outputs_detached=1");
  portal.sendHeader("Cache-Control", "no-store");
  portal.send(200, "text/plain; charset=utf-8", "已保存。黑色板会检查小智设备身份，输出仍禁用。请在控制台查看配对结果，再手动启用。");
}
void discoverPeers(uint32_t now) {
  if (!mdnsStarted || (int32_t)(now - nextDiscovery) < 0) return;
  nextDiscovery = now + 10000; candidateCount = candidateIndex = 0;
  // Blocking discovery occurs only while disconnected and detached, so it cannot extend an active lease.
  uint32_t count = MDNS.queryService("watcher-servo", "tcp", 300);
  for (uint32_t index = 0; index < count && candidateCount < 8; ++index) {
    if (MDNS.port(index) != kControllerPort) continue;
    String host = MDNS.hostname(index); if (host.endsWith(".")) host.remove(host.length() - 1);
    if (host.endsWith(".local")) host.remove(host.length() - 6);
    if (!ValidWatcherId(host.c_str()) || (*watcherId && strcmp(host.c_str(), watcherId))) continue;
    IPAddress address = MDNS.IP(index); uint8_t bytes[4]; for (int byte = 0; byte < 4; ++byte) bytes[byte] = address[byte];
    if (!UnicastTargetIp(bytes)) continue;
    candidates[candidateCount].ip = address; strncpy(candidates[candidateCount].id, host.c_str(), 31); candidates[candidateCount].id[31] = 0; ++candidateCount;
  }
  MDNS.removeQuery();
  if (candidateCount) { Serial.print("MDNS_WATCHER_CANDIDATES count="); Serial.println(candidateCount); }
}
bool choosePeer(IPAddress& address, char expected[32], uint32_t now) {
  if (UnicastTargetIp(targetIp) && (preferSaved || !*watcherId)) {
    address = IPAddress(targetIp); strcpy(expected, watcherId); preferSaved = false; return true;
  }
  discoverPeers(now);
  if (candidateCount) {
    const PeerCandidate& candidate = candidates[candidateIndex++ % candidateCount];
    address = candidate.ip; strcpy(expected, *watcherId ? watcherId : candidate.id); return true;
  }
  if (UnicastTargetIp(targetIp)) { address = IPAddress(targetIp); strcpy(expected, watcherId); return true; }
  return false;
}
void replayHistory() {
  for (int index = 0; index < historyCount; ++index) { char line[128]; if (history[index].Format(line, sizeof(line), true)) sendLine(line); }
}
void ack(const char* prefix, uint32_t sequence) {
  char line[96]; snprintf(line, sizeof(line), "%s %lu %u %u %u %u %lu\n", prefix, (unsigned long)sequence,
    output.Mode(), output.Pulse(0), output.Pulse(1), output.Pulse(2), (unsigned long)millis()); sendLine(line);
}
// 先恢复配置并保持输出禁用，再连接 Wi-Fi；身份与 PROFILE/ARM 握手后才输出信号。
void setup() {
  Serial.begin(115200); Serial.println("\nWATCHER_SERVO_CONTROLLER_V7 outputs_disabled_at_boot firmware=esp8266-servo-controller-v7 hold_protocol=2");
  Serial.println("NODE_PIN_MAP D1=GPIO5 D2=GPIO4 D3=GPIO0");
  for (auto pin : pins) pinMode(pin, INPUT);
  loadSettings(); randomHex(csrfToken); writeOutputs(5);
  // Private USB setup information only. Never forward this line to public logs or TCP.
  Serial.print("CONFIG_AUTH user=admin key="); Serial.println(stored.portal_key);
  snprintf(nodeHostname, sizeof(nodeHostname), "watcher-node-%06lx", (unsigned long)ESP.getChipId());
  portal.on("/", HTTP_GET, portalPage); portal.on("/pair", HTTP_POST, portalPair);
  portal.onNotFound([] { portal.send(404, "text/plain", "Not found"); }); portal.begin();
  WiFi.persistent(false); WiFi.mode(WIFI_STA); WiFi.hostname(nodeHostname); WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD); nextWifiRetry = millis() + 30000;
}
// 持续处理网络和 SET2 截止时间；断线、租约过期和停止均结束当前动作。
void loop() {
  uint32_t now = millis(); if (output.Tick(now)) writeOutputs(3);
  if (sendFailed) { disconnectController(); return; }
  // Expiry precedes receive: a queued late command must never revive an expired session.
  if (client.connected() && sessionExpired(now)) { disconnectController(); return; }
  if (client.connected()) pumpTx();
  // Slow phone requests cannot delay a running command's maximum 600 ms lease.
  if (!armed || !output.Mode()) portal.handleClient();
  if (WiFi.status() != WL_CONNECTED) {
    if (client.connected() || armed) disconnectController(); reportedWifi = false;
    if (mdnsStarted) { MDNS.close(); mdnsStarted = false; }
    if ((int32_t)(now - nextWifiRetry) >= 0) { WiFi.disconnect(); WiFi.begin(WIFI_SSID, WIFI_PASSWORD); nextWifiRetry = now + 30000; }
    delay(5); return;
  }
  if (!reportedWifi) {
    Serial.print("WIFI_JOINED ip="); Serial.println(WiFi.localIP()); reportedWifi = true;
    mdnsStarted = MDNS.begin(nodeHostname); if (mdnsStarted) MDNS.addService("http", "tcp", 80); nextDiscovery = 0;
  }
  if (mdnsStarted) MDNS.update();
  if (!client.connected()) {
    if (armed) disarm(4); output.Disconnect(); identity.Reset(); profileConfirmed = false; seen = false; tx.Clear(); sendFailed = false;
    if ((int32_t)(now - nextConnect) < 0) { delay(5); return; } nextConnect = now + 1000;
    char expected[32] = {}; if (!choosePeer(connectingIp, expected, now) || !client.connect(connectingIp, kControllerPort)) { delay(5); return; }
    client.setNoDelay(true); client.setTimeout(100); parser = StopLineParser(); welcomeBegan = lastReceive = millis(); identity.Begin(expected, welcomeBegan);
    char hello[128]; snprintf(hello, sizeof(hello), "HELLO SERVO360 %s %s %u %lu 6 hold_protocol=2\n", WiFi.macAddress().c_str(),
      WiFi.localIP().toString().c_str(), ENABLE_OUTPUTS ? 1 : 0, (unsigned long)profile.Id()); sendLine(hello);
  }
  uint32_t began = millis(); unsigned bytes = 0;
  while (client.available() && bytes++ < 256 && (uint32_t)(millis() - began) < 20) {
    if (sessionExpired(millis())) { disconnectController(); return; }
    if (output.Tick(millis())) writeOutputs(3);
    int ch = client.read(); if (ch < 0) break; if (!parser.Feed(char(ch))) continue;
    if (!identity.Verified()) {
      if (!identity.Receive(parser.Line(), millis())) { Serial.println("WELCOME_REJECTED outputs_detached=1"); disconnectController(); break; }
      strcpy(watcherId, identity.Id()); for (int index = 0; index < 4; ++index) targetIp[index] = connectingIp[index];
      if (!saveSettings()) { disconnectController(); break; }
      Serial.print("WATCHER_VERIFIED id="); Serial.print(watcherId); Serial.print(" ip="); Serial.println(connectingIp);
      char ready[96]; snprintf(ready, sizeof(ready), "READY SERVO360 %s hold_protocol=%u\n", watcherId, identity.HoldProtocol());
      sendLine(ready); lastReceive = millis(); replayHistory(); continue;
    }
    uint32_t values[7] = {}; ModeCommand command; TestCommand test; uint32_t sequence = 0;
    enum {BAD, SET, TEST, ARM, PROFILE} kind = BAD;
    if (ParseSet(parser.Line(), command)) { kind = SET; sequence = command.sequence; }
    else if (ParseTest(parser.Line(), test)) { kind = TEST; sequence = test.sequence; }
    else if (ReadControlNumbers(parser.Line(), "ARM ", values, 2) && values[1] <= 1) { kind = ARM; sequence = values[0]; }
    else if (ReadControlNumbers(parser.Line(), "PROFILE ", values, 7)) { kind = PROFILE; sequence = values[0]; }
    if (kind == BAD || (seen && (int32_t)(sequence - lastSeq) <= 0)) { Serial.println("COMMAND_REJECTED"); continue; }
    // Legacy traffic may obtain a neutral clock anchor while detached. It cannot
    // activate a channel or bypass absolute deadlines in an armed session.
    if (kind == SET && ((!command.absolute_deadline && (command.mode || armed)) ||
        (command.absolute_deadline && identity.HoldProtocol() != 2))) {
      Serial.println("COMMAND_REJECTED deadline_capability_required"); continue;
    }
    if (kind == PROFILE) {
      ServoProfile candidate;
      for (int index = 0; index < 3; ++index) {
        if (values[index + 1] > 65535 || values[index + 4] > 65535) { kind = BAD; break; }
        candidate.neutral[index] = values[index + 1]; candidate.run[index] = values[index + 4];
      }
      if (kind == BAD || armed || !candidate.Valid()) continue;
      ServoProfile previous = profile; output.Disconnect(); profile = candidate;
      if (!saveSettings()) { profile = previous; output.Configure(profile); profileConfirmed = false; continue; }
      output.Configure(profile); profileConfirmed = true; writtenMode = 255; lastSeq = sequence; writeOutputs(7);
      char reply[64]; snprintf(reply, sizeof(reply), "PROFILED %lu %lu\n", (unsigned long)sequence, (unsigned long)profile.Id()); sendLine(reply);
    } else if (kind == ARM) {
      lastSeq = sequence;
      if (values[1] && ENABLE_OUTPUTS && persistenceHealthy && profileConfirmed && identity.Verified() && identity.HoldProtocol() == 2) {
        bool ready = true;
        for (int index = 0; index < 3; ++index) {
          if (!servos[index].attached()) servos[index].attach(pins[index], 1000, 2000, profile.neutral[index]);
          ready = ready && servos[index].attached();
        }
        if (!ready) for (auto& servo : servos) servo.detach();
        armed = ready; output.Enable(armed); writtenMode = 255; writeOutputs(5);
      } else disarm(5);
      char reply[64]; snprintf(reply, sizeof(reply), "ARMED %lu %u\n", (unsigned long)sequence, armed ? 1 : 0); sendLine(reply);
    } else {
      bool accepted = kind == TEST ? output.ApplyTest(test, millis()) : output.Apply(command, millis());
      if (!accepted) continue; lastSeq = sequence;
      const bool expired = kind == SET && output.ExpiredCommand();
      const uint8_t reason = expired ? 8 : kind == TEST ? 6 : command.mode ? 1 : 2;
      // A late packet still generates an event if the channel was already neutral.
      if (!writeOutputs(reason) && expired) event(8);
      ack(kind == TEST ? "TEST_APPLIED" : "APPLIED", sequence);
    }
    seen = true; lastSeq = sequence; lastReceive = millis();
  }
  if (!client.connected() || (!identity.Verified() ? (uint32_t)(millis() - welcomeBegan) >= 1500 : (uint32_t)(millis() - lastReceive) > 650)) disconnectController();
  delay(2);
}

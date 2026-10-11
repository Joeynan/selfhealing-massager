#pragma once
#include "ESP8266WiFi.h"
#include <vector>
struct FakeMdns {
  struct Answer { String host; IPAddress ip; uint16_t service_port; };
  std::vector<Answer> answers;
  bool begin(const char*) { return true; } void close() {} void update() {} void addService(const char*, const char*, int) {}
  uint32_t queryService(const char*, const char*, uint16_t) { return uint32_t(answers.size()); }
  uint16_t port(uint32_t index) { return answers.at(index).service_port; } String hostname(uint32_t index) { return answers.at(index).host; }
  IPAddress IP(uint32_t index) { return answers.at(index).ip; } void removeQuery() {}
};
inline FakeMdns MDNS;

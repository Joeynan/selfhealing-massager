#pragma once
#include <array>
#include <cstdint>
#include <cstring>
#include <sstream>
#include <string>
#include <utility>
inline uint32_t fakeNow = 100;
inline uint32_t millis() { return fakeNow; }
inline void delay(unsigned duration) { fakeNow += duration; }
constexpr int D1 = 5, D2 = 4, D3 = 0, INPUT = 0, WIFI_STA = 1, WL_CONNECTED = 3;
inline void pinMode(int, int) {}
#define F(value) value
class String {
  std::string text_;
public:
  String() = default; String(const char* value):text_(value ? value : "") {} String(std::string value):text_(std::move(value)) {}
  String& operator=(const char* value) { text_ = value; return *this; }
  String& operator+=(const char* value) { text_ += value; return *this; }
  String& operator+=(const String& value) { text_ += value.text_; return *this; }
  const char* c_str() const { return text_.c_str(); } size_t length() const { return text_.size(); }
  void reserve(size_t size) { text_.reserve(size); }
  bool endsWith(const char* suffix) const { size_t n = strlen(suffix); return text_.size() >= n && text_.compare(text_.size() - n, n, suffix) == 0; }
  void remove(size_t index) { text_.erase(index); }
};
class IPAddress {
  std::array<uint8_t, 4> address_{};
public:
  IPAddress() = default; explicit IPAddress(const uint8_t* value) { memcpy(address_.data(), value, 4); }
  IPAddress(uint8_t a, uint8_t b, uint8_t c, uint8_t d):address_{{a,b,c,d}} {}
  uint8_t operator[](size_t index) const { return address_[index]; }
  String toString() const { std::ostringstream out; out << unsigned(address_[0]) << '.' << unsigned(address_[1]) << '.' << unsigned(address_[2]) << '.' << unsigned(address_[3]); return out.str(); }
};
inline std::ostream& operator<<(std::ostream& out, const IPAddress& ip) { return out << ip.toString().c_str(); }
struct FakeSerial {
  std::string text;
  void begin(int) {}
  template<typename T> void print(const T& value) { std::ostringstream out; out << value; text += out.str(); }
  void print(uint8_t value) { print(unsigned(value)); }
  template<typename T> void println(const T& value) { print(value); text += '\n'; }
};
inline FakeSerial Serial;
struct WiFiClient {
  bool open = false; std::string incoming, outgoing;
  bool connected() const { return open; }
  bool connect(IPAddress, uint16_t) { open = true; return true; }
  void stop(int = 0) { open = false; incoming.clear(); }
  void setNoDelay(bool) {} void setTimeout(int) {}
  int availableForWrite() const { return 1024; }
  size_t write(const uint8_t* data, size_t count) { outgoing.append(reinterpret_cast<const char*>(data), count); return count; }
  int available() const { return int(incoming.size()); }
  int read() { if (incoming.empty()) return -1; int value = uint8_t(incoming.front()); incoming.erase(0,1); return value; }
};
struct FakeWifi {
  int status() const { return WL_CONNECTED; }
  void persistent(bool) {} void mode(int) {} void hostname(const char*) {} void setAutoReconnect(bool) {} void begin(const char*, const char*) {} void disconnect() {}
  String macAddress() const { return "01:23:45:67:89:ab"; }
  IPAddress localIP() const { return {10,20,74,5}; }
};
inline FakeWifi WiFi;
struct FakeEsp { uint32_t getChipId() const { return 0xabcdef; } };
inline FakeEsp ESP;

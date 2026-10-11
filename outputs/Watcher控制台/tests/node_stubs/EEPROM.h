#pragma once
#include <array>
#include <cstring>
struct FakeEeprom {
  std::array<unsigned char,512> buffer{}; bool canCommit = true;
  void begin(int) {}
  template<typename T> void get(int offset, T& value) { memcpy(&value, buffer.data() + offset, sizeof(T)); }
  template<typename T> void put(int offset, const T& value) { memcpy(buffer.data() + offset, &value, sizeof(T)); }
  bool commit() { return canCommit; }
};
inline FakeEeprom EEPROM;

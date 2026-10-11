#pragma once
#include <cstddef>
#include <cstdint>
namespace watcher_vision {
struct ModelSpan {const uint8_t* data=nullptr;size_t bytes=0;};
struct Bundle {ModelSpan palm,hand;bool calibrated=false;};
uint32_t Crc32(const uint8_t*,size_t);
bool ParseBundle(const uint8_t* flash,size_t available,Bundle&);
}

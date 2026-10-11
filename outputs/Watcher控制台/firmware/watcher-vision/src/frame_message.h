#pragma once
#include <cstddef>
#include <cstdint>
namespace watcher_vision {
constexpr size_t kMaximumJpegBytes = 98304;
constexpr size_t kFrameMessageBytes = 131584;
struct Snapshot {
 uint32_t session, frame_id, capture_ms, send_ms;
 uint16_t width, height;
 const uint8_t* jpeg;
 size_t jpeg_bytes;
};
// Returns zero without publishing a success message if any input/bound is invalid.
size_t EncodeSnapshot(const Snapshot&, char*, size_t);
size_t EncodeSnapshotError(uint32_t session, const char* error, char*, size_t);
}

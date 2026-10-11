#pragma once
#include "hand_geometry.h"
namespace watcher_vision {
constexpr size_t kMessageBytes=6144;
enum class Error:uint8_t {None,ModelMissing,ModelSchema,ModelFormat,Arena,Camera,Invoke,Points};
struct Hand {uint32_t id=0;float presence=0,right_probability=0;Point points[21]{};Point world[21]{};bool has_world=false;};
// Accumulated real stage elapsed time. Invoke includes hardware waiting; this is
// diagnostic timing, not a replacement for end-to-end camera throughput.
struct Profile {uint32_t load_ms=0,crop_ms=0,invoke_ms=0,decode_ms=0;};
struct Frame {
 uint32_t session=0,frame_id=0,capture_ms=0,inference_ms=0;
 int width=0,height=0;bool mirrored=false,model_ready=false,valid=false,calibrated=false;
 uint8_t hand_count=0;Hand hands[2]{};Error error=Error::None;
 Profile profile{};
};
// Emits one complete SSCMA type=1 event, or returns 0 and empties the buffer.
// session is supplied by the host's AT+HANDS command; ids identify hands within one frame only.
size_t EncodeFrame(const Frame&,char*,size_t);
// Opening response provides the remote monotonic clock for a conservative request-time anchor.
size_t EncodeOpeningAck(uint32_t session,uint32_t now_ms,char*,size_t);
const char* ErrorName(Error);
}

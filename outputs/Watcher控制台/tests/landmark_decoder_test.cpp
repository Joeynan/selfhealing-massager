#include <cassert>
#include <string>
#include "../firmware/watcher-service/landmark_decoder.h"
std::string Message(unsigned session,unsigned frame,unsigned capture,unsigned infer=10){return "{\"type\":1,\"name\":\"HANDS\",\"code\":0,\"data\":{\"version\":1,\"session\":"+std::to_string(session)+",\"frame_id\":"+std::to_string(frame)+",\"capture_ms\":"+std::to_string(capture)+",\"inference_ms\":"+std::to_string(infer)+",\"width\":640,\"height\":480,\"mirrored\":false,\"model\":\"test-hand-model\",\"model_ready\":true,\"valid\":true,\"calibrated\":true,\"hands\":[]}}";}
std::string Ack(unsigned session,unsigned now){return "{\"type\":0,\"name\":\"HANDS\",\"code\":0,\"data\":{\"version\":1,\"session\":"+std::to_string(session)+",\"now_ms\":"+std::to_string(now)+"}}";}
bool Anchor(onboard::Decoder& d,unsigned session,unsigned remote,unsigned local){auto* j=cJSON_Parse(Ack(session,remote).c_str());bool ok=d.AnchorFromAck(j,local);cJSON_Delete(j);return ok;}
int main(){
 onboard::Decoder d;d.Begin(7);onboard::Frame out;auto run=[&](std::string s,unsigned t){auto* j=cJSON_Parse(s.c_str());auto r=d.Decode(j,t,out);cJSON_Delete(j);return r;};
 assert(run(Message(7,1,500),100)==onboard::DecodeResult::Ignore); // No ACK means no clock bridge.
 assert(!Anchor(d,6,500,80));assert(Anchor(d,7,500,80));assert(!Anchor(d,7,500,900)); // Repeated ACK cannot renew old frames.
 assert(run(Message(6,1,500),100)==onboard::DecodeResult::Ignore);
 assert(run(Message(7,1,500),100)==onboard::DecodeResult::Frame);assert(out.id==1&&out.captured_ms==80&&out.model_ready&&out.calibrated);
 assert(run(Message(7,1,500),450)==onboard::DecodeResult::Ignore);
 assert(run(Message(7,2,600),1000)==onboard::DecodeResult::Invalid);
 assert(out.error=="landmark_frame_stale");
 assert(run(Message(7,2,600),170)==onboard::DecodeResult::Invalid);
 assert(out.error=="landmark_frame_future");
 d.Begin(8);assert(run(Message(8,1,0),1100)==onboard::DecodeResult::Ignore);assert(Anchor(d,8,0,1080));
 assert(run(Message(8,1,0),1100)==onboard::DecodeResult::Frame);assert(out.id==2&&out.captured_ms==1080);
 assert(run(Message(8,2,200,900),1300)==onboard::DecodeResult::Invalid);
 assert(out.error=="landmark_inference_expired");
 auto huge=Message(8,3,300);huge.replace(huge.find("640"),3,"100000");assert(run(huge,1400)==onboard::DecodeResult::Invalid);
 onboard::Decoder delayed;delayed.Begin(9);assert(Anchor(delayed,9,500,100));auto* j=cJSON_Parse(Message(9,1,500).c_str());assert(delayed.Decode(j,1000,out)==onboard::DecodeResult::Invalid);cJSON_Delete(j); // First queued frame cannot be rebased fresh.
 onboard::Decoder wrapping;wrapping.Begin(10);assert(Anchor(wrapping,10,UINT32_MAX-50,100));j=cJSON_Parse(Message(10,1,49).c_str());assert(wrapping.Decode(j,220,out)==onboard::DecodeResult::Frame);assert(out.captured_ms==200);cJSON_Delete(j);
 puts("decoder ACK anchor, first-frame queue age, reboot and duplicate tests passed");
}

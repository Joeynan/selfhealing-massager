#include <cassert>
#include <cstdio>
#include "../firmware/watcher-service/landmark_decoder.h"
#include "../firmware/watcher-vision/src/landmark_message.h"
int main(){
 watcher_vision::Frame f;f.session=42;f.frame_id=1;f.capture_ms=100;f.inference_ms=20;f.width=f.height=416;f.valid=f.model_ready=f.calibrated=true;f.hand_count=2;
 for(int i=0;i<2;i++){auto& h=f.hands[i];h.id=i+1;h.presence=.9;h.right_probability=i?.9:.1;h.has_world=true;for(int j=0;j<21;j++){h.points[j]={.3f+j*.01f,.4f+j*.005f,-.02f};h.world[j]={j*.002f,j*.001f,-.005f};}}
 char buffer[watcher_vision::kMessageBytes];auto len=watcher_vision::EncodeFrame(f,buffer,sizeof(buffer));assert(len>0&&len<sizeof(buffer));auto* json=cJSON_Parse(buffer);assert(json);onboard::Decoder decoder;decoder.Begin(42);auto* ack=cJSON_Parse("{\"type\":0,\"name\":\"HANDS\",\"code\":0,\"data\":{\"version\":1,\"session\":42,\"now_ms\":100}}");assert(decoder.AnchorFromAck(ack,180));onboard::Frame out;assert(decoder.Decode(json,200,out)==onboard::DecodeResult::Frame);assert(out.hand_count==2&&out.hands[0].side==onboard::Side::Left&&out.hands[1].side==onboard::Side::Right);assert(out.hands[0].has_world&&out.calibrated&&out.captured_ms==180);
 auto* data=cJSON_GetObjectItem(json,"data");auto* hs=cJSON_GetObjectItem(data,"hands");auto* first=cJSON_GetArrayItem(hs,0);auto* points=cJSON_GetObjectItem(first,"landmarks");cJSON_DeleteItemFromArray(points,20);onboard::Decoder malformed;malformed.Begin(42);assert(malformed.AnchorFromAck(ack,180));cJSON_Delete(ack);assert(malformed.Decode(json,200,out)==onboard::DecodeResult::Invalid);cJSON_Delete(json);puts("real vision encoder to ESP32 decoder (2x21 nodes, world, malformed rejection) passed");
}

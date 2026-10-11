#include "landmark_message.h"
#include <cmath>
#include <cstdio>
#include <cstdarg>
namespace watcher_vision {
namespace {
struct Writer {
 char* p;size_t capacity,used=0;bool ok=true;
 void add(const char* f,...){if(!ok)return;va_list args;va_start(args,f);const int n=vsnprintf(p+used,capacity-used,f,args);va_end(args);if(n<0||size_t(n)>=capacity-used){ok=false;return;}used+=size_t(n);}
 // WE2 links newlib-nano without _printf_float. Only integer printf is used;
 // all public values are validated and bounded before reaching this writer.
 void number(float value){
  if(!std::isfinite(value)||std::fabs(value)>10.f){ok=false;return;}
  const int32_t scaled=int32_t(std::round(double(value)*1000000.));
  const uint32_t magnitude=uint32_t(scaled<0?-scaled:scaled);
  add("%s%lu.%06lu",scaled<0?"-":"",(unsigned long)(magnitude/1000000u),(unsigned long)(magnitude%1000000u));
 }
 void points(const Point* ps){add("[");for(size_t i=0;i<21;i++){add("%s[",i?",":"");number(ps[i].x);add(",");number(ps[i].y);add(",");number(ps[i].z);add("]");}add("]");}
};
bool probability(float p){return std::isfinite(p)&&p>=0&&p<=1;}
}
const char* ErrorName(Error e){switch(e){
 case Error::None:return "";case Error::ModelMissing:return "model_bundle_missing";case Error::ModelSchema:return "model_schema_mismatch";
 case Error::ModelFormat:return "model_cop1_or_shape_mismatch";case Error::Arena:return "arena_allocate_failed";
 case Error::Camera:return "camera_failed";case Error::Invoke:return "invoke_failed";case Error::Points:return "invalid_landmarks";
 }return "unknown_error";}
size_t EncodeOpeningAck(uint32_t session,uint32_t now_ms,char*out,size_t bytes){
 if(!out||!bytes)return 0;out[0]=0;if(!session)return 0;
 Writer w{out,bytes};
 w.add("\r{\"type\":0,\"name\":\"HANDS\",\"code\":0,\"data\":{\"version\":1,\"session\":%lu,\"now_ms\":%lu}}\n",(unsigned long)session,(unsigned long)now_ms);
 if(!w.ok){out[0]=0;return 0;}return w.used;
}
size_t EncodeFrame(const Frame&f,char*out,size_t bytes){
 if(!out||!bytes)return 0;out[0]=0;
 if(bytes>kMessageBytes)bytes=kMessageBytes;
 if(f.width<=0||f.height<=0||f.width>8192||f.height>8192||f.hand_count>2||(!f.valid&&f.hand_count)||(!f.model_ready&&f.hand_count))return 0;
 for(size_t i=0;i<f.hand_count;i++){const auto&h=f.hands[i];if(!probability(h.presence)||!probability(h.right_probability))return 0;for(size_t k=0;k<21;k++)if(!ValidPoint(h.points[k])||(h.has_world&&!ValidPoint(h.world[k],true)))return 0;}
 Writer w{out,bytes};
 w.add("\r{\"type\":1,\"name\":\"HANDS\",\"code\":0,\"data\":{\"version\":1,\"model\":\"mediapipe-full-int8-u55-64\",\"session\":%lu,\"frame_id\":%lu,\"capture_ms\":%lu,\"inference_ms\":%lu,\"width\":%d,\"height\":%d,\"mirrored\":%s,\"model_ready\":%s,\"valid\":%s,\"calibrated\":%s,\"error\":\"%s\",\"hands\":[",
 (unsigned long)f.session,(unsigned long)f.frame_id,(unsigned long)f.capture_ms,(unsigned long)f.inference_ms,f.width,f.height,f.mirrored?"true":"false",f.model_ready?"true":"false",f.valid?"true":"false",f.calibrated?"true":"false",ErrorName(f.error));
 for(size_t i=0;i<f.hand_count;i++){
  const auto&h=f.hands[i];w.add("%s{\"id\":%lu,\"handedness\":\"%s\",\"presence\":",i?",":"",(unsigned long)h.id,h.right_probability>=.5f?"right":"left");
  w.number(h.presence);w.add(",\"right_probability\":");w.number(h.right_probability);w.add(",\"landmarks\":");
  w.points(h.points);if(h.has_world){w.add(",\"world_landmarks\":");w.points(h.world);}w.add("}");
 }
 w.add("],\"profile\":{\"load_ms\":%lu,\"crop_ms\":%lu,\"invoke_ms\":%lu,\"decode_ms\":%lu}}}\n",
 (unsigned long)f.profile.load_ms,(unsigned long)f.profile.crop_ms,(unsigned long)f.profile.invoke_ms,(unsigned long)f.profile.decode_ms);
 if(!w.ok){out[0]=0;return 0;}return w.used;
}
}

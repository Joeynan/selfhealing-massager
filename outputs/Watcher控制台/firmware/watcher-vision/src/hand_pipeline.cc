#include "hand_pipeline.h"
#include <cmath>
namespace watcher_vision {
namespace {
struct StageTimer {
 uint32_t&elapsed;uint32_t(*clock)();uint32_t start;
 StageTimer(uint32_t&ms,uint32_t(*now)()):elapsed(ms),clock(now),start(now?now():0){}
 ~StageTimer(){if(clock)elapsed+=clock()-start;}
};
}
Error HandPipeline::Process(RgbImage image,Frame& frame){
 frame.valid=false;frame.hand_count=0;frame.error=Error::None;frame.width=image.width;frame.height=image.height;frame.profile={};
 const auto fail=[&](Error e){frame.error=e;frame.hand_count=0;frame.valid=false;return e;};
 Error err;
 {StageTimer timer(frame.profile.load_ms,clock_);err=backend_.Load(ModelKind::Palm);if(err!=Error::None)return fail(err);}
 auto input=backend_.Input();
 {StageTimer timer(frame.profile.crop_ms,clock_);if(input.bytes!=192*192*3||!CropRgb(image,PalmInputRoi(image.width,image.height),192,192,input.data,input.bytes,input.scale,input.zero,Border::Zero))return fail(Error::ModelFormat);}
 {StageTimer timer(frame.profile.invoke_ms,clock_);if((err=backend_.Invoke())!=Error::None)return fail(err);}
 Palm palms[2]{};const auto boxes=backend_.Output(0),scores=backend_.Output(1);
 if(!boxes.Valid()||!scores.Valid()||boxes.count!=2016*18||scores.count!=2016)return fail(Error::ModelFormat);
 size_t count;
 {StageTimer timer(frame.profile.decode_ms,clock_);count=DecodePalms(boxes,scores,image.width,image.height,palms);}
 // Palm decoding is complete before replacing the interpreter. No arena pointer survives Load().
 if(count){
  {StageTimer timer(frame.profile.load_ms,clock_);if((err=backend_.Load(ModelKind::Landmark))!=Error::None)return fail(err);}
  input=backend_.Input();if(input.bytes!=224*224*3)return fail(Error::ModelFormat);
 }
 for(size_t i=0;i<count;i++){
  Roi roi;if(!PalmToRoi(palms[i],roi))continue;
  {StageTimer timer(frame.profile.crop_ms,clock_);if(!CropRgb(image,roi,224,224,input.data,input.bytes,input.scale,input.zero,Border::Replicate))return fail(Error::ModelFormat);}
  {StageTimer timer(frame.profile.invoke_ms,clock_);if((err=backend_.Invoke())!=Error::None)return fail(err);}
  StageTimer timer(frame.profile.decode_ms,clock_);
  const auto points=backend_.Output(0),presence=backend_.Output(1),side=backend_.Output(2),world=backend_.Output(3);
  if(!points.Valid()||!presence.Valid()||!side.Valid()||!world.Valid()||points.count!=63||presence.count!=1||side.count!=1||world.count!=63)return fail(Error::ModelFormat);
  const float confidence=presence.At(0),right=side.At(0);
  if(!std::isfinite(confidence)||!std::isfinite(right)||confidence<0||confidence>1||right<0||right>1)return fail(Error::Points);
  if(confidence<.5f)continue;
  auto&h=frame.hands[frame.hand_count];h=Hand{};h.id=uint32_t(i);h.presence=confidence;
  // The original MediaPipe model assumes selfie/mirrored input; this frame remains unmirrored.
  h.right_probability=frame.mirrored?right:1-right;h.has_world=true;
  for(size_t k=0;k<21;k++){
   h.points[k]=Project({points.At(k*3),points.At(k*3+1),points.At(k*3+2)},roi,image.width,image.height);
   h.world[k]=ProjectWorld({world.At(k*3),world.At(k*3+1),world.At(k*3+2)},roi);
   if(!ValidPoint(h.points[k])||!ValidPoint(h.world[k],true))return fail(Error::Points);
  }frame.hand_count++;
 }
 frame.valid=true;return Error::None;
}
}

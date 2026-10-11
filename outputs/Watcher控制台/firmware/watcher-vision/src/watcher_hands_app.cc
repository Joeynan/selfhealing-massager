#include "sscma.h"
#include "sscma/main_task.hpp"
#include "el_sspi_we2.h"
#include "porting/el_flash.h"
#include "hand_pipeline.h"
#include "model_bundle.h"
#include "tflm_backend.h"
#include "frame_message.h"
extern "C" {
#include <drivers/drv_common.h>
}
#include <cerrno>
#include <cstdlib>

using namespace watcher_vision;
namespace {
constexpr size_t arena_size=1110*1024;
// Existing models occupy 0x400000,0x600000,0x800000. New bundle is placed after those slots.
constexpr uint32_t bundle_offset_in_models=0x600000; // absolute flash address 0xA00000
TflmBackend* backend=nullptr;
HandPipeline* pipeline=nullptr;
bool ready=false,calibrated=false,camera_ready=false;
Error startup_error=Error::ModelMissing;
uint32_t sequence=0,last_capture_sequence=0;
constexpr uint32_t maximum_capture_age_ms=800;
// Shared output buffer used only by the single SSCMA executor; no per-frame heap allocation.
char event_buffer[kMessageBytes];
char* snapshot_buffer=nullptr;
// Camera and NPU jobs run on the same executor. Reuse the SDK's existing
// fixed 1112 KiB arena instead of taking a 128 KiB block from the RTOS heap.
uint8_t* workspace=nullptr;
bool ensure_workspace(){
 if(!workspace)workspace=static_cast<uint8_t*>(el_aligned_malloc_once(32,arena_size));
 return workspace!=nullptr;
}
uint32_t last_snapshot_sequence=0;

void emit(Frame& f,void*caller){
 auto* transport=static_cast<edgelab::Transport*>(caller);
 if(!transport)return;
 const size_t bytes=EncodeFrame(f,event_buffer,sizeof(event_buffer));
 if(bytes)transport->send_bytes(event_buffer,bytes);
}
bool pending(void*caller){
 auto*t=static_cast<edgelab::Transport*>(caller);
 return t&&t->type==EL_TRANSPORT_SPI&&static_cast<edgelab::sspiWE2*>(t)->tx_ring_buffer->size()!=0;
}
void snapshot_error(uint32_t session,const char*error,void*caller){
 auto*transport=static_cast<edgelab::Transport*>(caller);if(!transport)return;
 const size_t n=EncodeSnapshotError(session,error,event_buffer,sizeof(event_buffer));
 if(n)transport->send_bytes(event_buffer,n);
}
bool send_snapshot(const char*data,size_t bytes,size_t task_id,void*caller){
 auto*r=sscma::static_resource;auto*t=static_cast<edgelab::Transport*>(caller);
 if(!t)return false;
 const uint32_t started=uint32_t(el_get_time_ms());
 for(size_t offset=0;offset<bytes;){
  if(r->current_task_id.load()!=task_id||uint32_t(el_get_time_ms())-started>=750)return false;
  // SPI length is uint16. Keep queued bytes below 64 KiB and never send a
  // 128 KiB base64 payload as one write to the 64 KiB TX ring.
  if(t->type==EL_TRANSPORT_SPI&&static_cast<edgelab::sspiWE2*>(t)->tx_ring_buffer->size()>32768){
   el_sleep(5);r->device->yield();continue;
  }
  const size_t chunk=(bytes-offset)>8192?8192:(bytes-offset);
  if(t->send_bytes(data+offset,chunk)!=chunk)return false;
  offset+=chunk;
 }
 return true;
}
void snapshot(uint32_t session,size_t task_id,void*caller){
 auto*r=sscma::static_resource;
 if(!caller||r->current_task_id.load()!=task_id)return;
 // FRAME is a single camera operation. It deliberately does not call initialize().
 if(!ensure_workspace()){snapshot_error(session,"camera_memory",caller);return;}
 // Destroy the interpreter while its arena is intact, before camera JSON
 // overwrites it. Switching back to HANDS rebuilds its tensors in this arena.
 if(backend){delete pipeline;pipeline=nullptr;delete backend;backend=nullptr;ready=false;calibrated=false;startup_error=Error::ModelMissing;}
 snapshot_buffer=reinterpret_cast<char*>(workspace);
 auto*camera=r->device->get_camera();
 if(!camera_ready){camera->deinit();camera_ready=camera->init(1)==EL_OK;}
 if(!camera_ready){snapshot_error(session,"camera_init",caller);return;}
 const char*error="camera_capture";
 const uint32_t started=uint32_t(el_get_time_ms());
 for(unsigned attempt=0;attempt<2;++attempt){
  if(r->current_task_id.load()!=task_id)return;
  if(camera->start_stream()!=EL_OK){camera_ready=false;break;}
  drv_capture_stamp_t before{},after{};
  const uint32_t now=uint32_t(el_get_time_ms());
  const bool stamp_ok=_drv_get_capture_stamp(&before);
  if(!stamp_ok||before.sequence==last_snapshot_sequence||uint32_t(now-before.capture_ms)>=800){
   error=before.sequence==last_snapshot_sequence?"camera_duplicate":"camera_stale";
   if(camera->stop_stream()!=EL_OK){camera_ready=false;error="camera_stop";break;}
   // Old cached DMA is drained and retriggered, never given a new timestamp.
   if(uint32_t(el_get_time_ms())-started>=600)break;
   continue;
  }
  el_img_t jpeg{};
  if(camera->get_processed_frame(&jpeg)!=EL_OK){
   error="camera_jpeg";
   if(camera->stop_stream()!=EL_OK){camera_ready=false;error="camera_stop";}
   break;
  }
  if(!_drv_get_capture_stamp(&after)||before.sequence!=after.sequence||before.capture_ms!=after.capture_ms){
   error="camera_changed";
   if(camera->stop_stream()!=EL_OK){camera_ready=false;error="camera_stop";}
   break;
  }
  Snapshot f{session,before.sequence,before.capture_ms,uint32_t(el_get_time_ms()),jpeg.width,jpeg.height,jpeg.data,jpeg.size};
  const size_t n=EncodeSnapshot(f,snapshot_buffer,kFrameMessageBytes);
  // Base64 is copied before retriggering DMA; later capture cannot mutate this reply.
  if(camera->stop_stream()!=EL_OK){camera_ready=false;error="camera_stop";break;}
  if(!n){error="camera_jpeg";break;}
  if(uint32_t(el_get_time_ms())-before.capture_ms>=800){error="camera_stale";break;}
  if(r->current_task_id.load()!=task_id)return;
  last_snapshot_sequence=before.sequence;
  // A interrupted/failed partial transport reply must time out at the S3 reader;
  // never append a success message or re-date this DMA frame.
  send_snapshot(snapshot_buffer,n,task_id,caller);return;
 }
 if(r->current_task_id.load()==task_id)snapshot_error(session,error,caller);
}
void initialize(){
 if(backend)return;
 uint32_t offset=0,size=0,handler=0;const uint8_t*flash=nullptr;Bundle bundle;
 if(!edgelab::porting::el_flash_mmap_init(&offset,&size,&flash,&handler)||size<=bundle_offset_in_models||!ParseBundle(flash+bundle_offset_in_models,size-bundle_offset_in_models,bundle)){startup_error=Error::ModelMissing;return;}
 auto*arena=ensure_workspace()?workspace:nullptr;
 if(!arena){startup_error=Error::Arena;return;}
 backend=new TflmBackend(arena,arena_size,{bundle.palm.data,bundle.palm.bytes},{bundle.hand.data,bundle.hand.bytes});
 startup_error=backend->Load(ModelKind::Palm);
 if(startup_error==Error::None){el_printf("HANDS palm allocation %u\r\n",unsigned(backend->Used()));startup_error=backend->Load(ModelKind::Landmark);}
 if(startup_error==Error::None){el_printf("HANDS landmark allocation %u\r\n",unsigned(backend->Used()));pipeline=new HandPipeline(*backend,[](){return uint32_t(el_get_time_ms());});ready=true;calibrated=bundle.calibrated;}
}
void next_frame(uint32_t session,size_t task_id,void*caller,const std::atomic<bool>&stop){
 auto*resources=sscma::static_resource;
 if(stop.load()||resources->current_task_id.load()!=task_id)return;
 // A single outstanding message prevents an unread SPI queue accumulating old frames.
 if(pending(caller)){el_sleep(20);resources->device->yield();resources->executor->add_task([=](const std::atomic<bool>&s){next_frame(session,task_id,caller,s);});return;}
 initialize();
 Frame f{};f.session=session;f.frame_id=++sequence;f.width=416;f.height=416;f.model_ready=ready;f.calibrated=calibrated;f.error=startup_error;
 auto*camera=resources->device->get_camera();
 if(ready&&!camera_ready){camera->deinit();camera_ready=camera->init(1)==EL_OK;}
 if(ready&&camera_ready){
  el_img_t image{};
  if(camera->start_stream()==EL_OK){
   drv_capture_stamp_t stamp{};
   if(!_drv_get_capture_stamp(&stamp)||stamp.sequence==last_capture_sequence||uint32_t(el_get_time_ms())-stamp.capture_ms>maximum_capture_age_ms){
    // stop_stream retriggers capture: discard an old DMA image rather than re-date it.
    if(camera->stop_stream()!=EL_OK)camera_ready=false;
    resources->executor->add_task([=](const std::atomic<bool>&s){next_frame(session,task_id,caller,s);});return;
   }
   last_capture_sequence=stamp.sequence;f.capture_ms=stamp.capture_ms;
   if(camera->get_frame(&image)==EL_OK&&image.data&&image.format==EL_PIXEL_FORMAT_YUV422&&image.rotate==EL_PIXEL_ROTATE_0&&image.size==size_t(image.width)*image.height*2){
    pipeline->Process({image.data,image.width,image.height,image.width,ImageFormat::Yuv422Planar},f);
   }else f.error=Error::Camera;
   if(camera->stop_stream()!=EL_OK){f.valid=false;f.hand_count=0;f.error=Error::Camera;camera_ready=false;}
  }else {f.error=Error::Camera;camera_ready=false;}
  f.inference_ms=uint32_t(el_get_time_ms())-f.capture_ms;
  if(f.inference_ms>maximum_capture_age_ms){f.valid=false;f.hand_count=0;f.error=Error::Camera;}
 }else if(ready)f.error=Error::Camera;
 if(stop.load()||resources->current_task_id.load()!=task_id)return;
 emit(f,caller);
 if(!ready||!camera_ready)el_sleep(200);
 resources->executor->add_task([=](const std::atomic<bool>&s){next_frame(session,task_id,caller,s);});
}
void app(void*){
 // Retain the official transport, sensor, watchdog, OTA and device initialization.
 sscma::main_task::init_static_resource();sscma::main_task::register_commands();
 auto*r=sscma::static_resource;
 // These paths can allocate a second arena or capture concurrently. This independent profile exposes HANDS and SAMPLE only.
 r->instance->unregister_cmd("MODEL","INVOKE","ALGO");
 r->instance->register_cmd("FRAME","Get one fresh camera JPEG without NPU","SESSION",[](std::vector<std::string>argv,void*caller){
  if(argv.size()!=2||argv[1].empty()||argv[1].find_first_not_of("0123456789")!=std::string::npos)return EL_EINVAL;
  errno=0;char*end=nullptr;const unsigned long number=strtoul(argv[1].c_str(),&end,10);
  if(errno||!end||*end||number>0xfffffffful||number==0)return EL_EINVAL;
  auto*r=sscma::static_resource;r->executor->try_stop_task();const size_t task_id=r->current_task_id.fetch_add(1)+1;
  r->executor->add_task([session=uint32_t(number),task_id,caller](const std::atomic<bool>&){snapshot(session,task_id,caller);});return EL_OK;
 });
 r->instance->register_cmd("HANDS","Stream 21 landmarks for up to two hands","SESSION",[](std::vector<std::string>argv,void*caller){
  if(argv.size()!=2||argv[1].empty()||argv[1].find_first_not_of("0123456789")!=std::string::npos)return EL_EINVAL;
  errno=0;char*end=nullptr;const unsigned long number=strtoul(argv[1].c_str(),&end,10);
  if(errno||!end||*end||number>0xfffffffful||number==0)return EL_EINVAL;
  auto*r=sscma::static_resource;r->executor->try_stop_task();const size_t task_id=r->current_task_id.fetch_add(1)+1;
  r->executor->add_task([session=uint32_t(number),task_id,caller](const std::atomic<bool>&){
   auto*r=sscma::static_resource;
   // try_stop_task cancels the preceding job; the executor resets that flag after this
   // opening job. The generation check prevents obsolete openings from sending ACKs.
   if(r->current_task_id.load()!=task_id)return;
   sequence=0;last_capture_sequence=0;
   auto*transport=static_cast<edgelab::Transport*>(caller);if(!transport)return;
   const size_t bytes=EncodeOpeningAck(session,uint32_t(el_get_time_ms()),event_buffer,sizeof(event_buffer));
   if(bytes)transport->send_bytes(event_buffer,bytes);
   r->executor->add_task([=](const std::atomic<bool>&s){next_frame(session,task_id,caller,s);});
  });return EL_OK;
 });
 r->instance->register_cmd("HANDS?","Get landmark protocol capability","",[](std::vector<std::string>,void*caller){
  sscma::static_resource->executor->add_task([caller](const std::atomic<bool>&){initialize();const char* reply="\r{\"type\":0,\"name\":\"HANDS?\",\"code\":0,\"data\":{\"version\":1,\"supports_hands\":true}}\n";static_cast<edgelab::Transport*>(caller)->send_bytes(reply,strlen(reply));});return EL_OK;
 });
 xTaskCreate(sscma::main_task::wait_for_inputs,"listener",4096,nullptr,3,nullptr);vTaskDelete(nullptr);
}
}
extern "C" int app_main(){
 if(xTaskCreate(app,"hands",20480,nullptr,3,nullptr)!=pdPASS){el_printf("HANDS app task failed\r\n");return -1;}
 vTaskStartScheduler();return 0;
}

#pragma once
#include "hand_pipeline.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
namespace watcher_vision {
struct ModelBlob {const uint8_t* data;size_t bytes;};
class TflmBackend:public ModelBackend {
 uint8_t* arena_;size_t arena_bytes_;ModelBlob blobs_[2];
 tflite::MicroMutableOpResolver<1> resolver_;
 alignas(tflite::MicroInterpreter) uint8_t interpreter_storage_[sizeof(tflite::MicroInterpreter)];
 tflite::MicroInterpreter* interpreter_=nullptr;int current_=-1;
 void Reset();
 public:
 TflmBackend(uint8_t* arena,size_t bytes,ModelBlob palm,ModelBlob hand);
 ~TflmBackend()override; // only destroys interpreter; external model/arena ownership remains with the caller
 Error Load(ModelKind)override;
 InputTensor Input()override;
 Error Invoke()override;
 TensorView Output(size_t)override;
 size_t Used()const{return interpreter_?interpreter_->arena_used_bytes():0;}
};
}

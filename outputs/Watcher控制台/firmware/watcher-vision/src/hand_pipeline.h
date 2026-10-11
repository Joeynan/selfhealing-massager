#pragma once
#include "landmark_message.h"
namespace watcher_vision {
enum class ModelKind {Palm=0,Landmark=1};
struct InputTensor {int8_t* data;size_t bytes;float scale;int zero;};
class ModelBackend {
 public:virtual ~ModelBackend()=default;
 virtual Error Load(ModelKind)=0;
 virtual InputTensor Input()=0;
 virtual Error Invoke()=0;
 virtual TensorView Output(size_t)=0;
};
class HandPipeline {
 ModelBackend& backend_;
 uint32_t(*clock_)();
 public:explicit HandPipeline(ModelBackend& backend,uint32_t(*clock)()=nullptr):backend_(backend),clock_(clock){}
 Error Process(RgbImage,Frame&);
};
}

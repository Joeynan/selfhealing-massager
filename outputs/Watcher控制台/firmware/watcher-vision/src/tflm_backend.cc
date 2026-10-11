#include "tflm_backend.h"
#include "flatbuffers/verifier.h"
#include "tensorflow/lite/schema/schema_generated.h"
#include <cstring>
#include <new>
namespace watcher_vision {
TflmBackend::TflmBackend(uint8_t* a,size_t n,ModelBlob p,ModelBlob h):arena_(a),arena_bytes_(n),blobs_{p,h}{resolver_.AddEthosU();}
TflmBackend::~TflmBackend(){Reset();}
void TflmBackend::Reset(){if(interpreter_){interpreter_->~MicroInterpreter();interpreter_=nullptr;}current_=-1;}
Error TflmBackend::Load(ModelKind kind){
 const int index=int(kind);if(index<0||index>1)return Error::ModelFormat;
 if(index==current_&&interpreter_)return Error::None;
 Reset();const auto blob=blobs_[index];
 if(!blob.data||blob.bytes<8||blob.bytes>10*1024*1024||!arena_||arena_bytes_<16||reinterpret_cast<uintptr_t>(arena_)%16)return Error::ModelFormat;
 flatbuffers::Verifier verifier(blob.data,blob.bytes);
 if(!tflite::VerifyModelBuffer(verifier))return Error::ModelFormat;
 const auto*model=tflite::GetModel(blob.data);if(model->version()!=TFLITE_SCHEMA_VERSION)return Error::ModelSchema;
 if(!model->subgraphs()||model->subgraphs()->size()!=1||!model->operator_codes()||!model->buffers())return Error::ModelFormat;
 const auto*g=model->subgraphs()->Get(0);
 if(!g->inputs()||g->inputs()->size()!=1||!g->outputs()||g->outputs()->size()!=(index==0?2u:4u)||!g->operators()||!g->tensors())return Error::ModelFormat;
 // Only fully delegated U55 models are accepted. No accidental desktop/CPU fallbacks.
 for(const auto*op:*g->operators()){
  if(op->opcode_index()>=model->operator_codes()->size()||!op->inputs()||op->inputs()->size()<1)return Error::ModelFormat;
  const auto*code=model->operator_codes()->Get(op->opcode_index());
  if(code->builtin_code()!=tflite::BuiltinOperator_CUSTOM||!code->custom_code()||std::strcmp(code->custom_code()->c_str(),"ethos-u"))return Error::ModelFormat;
  const int ci=op->inputs()->Get(0);if(ci<0||size_t(ci)>=g->tensors()->size())return Error::ModelFormat;
  const auto*command=g->tensors()->Get(ci);if(command->buffer()>=model->buffers()->size())return Error::ModelFormat;
  const auto*data=model->buffers()->Get(command->buffer())->data();
  if(!data||data->size()<4||std::memcmp(data->data(),"COP1",4))return Error::ModelFormat;
 }
 interpreter_=new(interpreter_storage_) tflite::MicroInterpreter(model,resolver_,arena_,arena_bytes_);
 if(interpreter_->AllocateTensors()!=kTfLiteOk){Reset();return Error::Arena;}
 const auto*in=interpreter_->input(0);const int edge=index==0?192:224;
 if(!in||in->type!=kTfLiteInt8||!in->dims||in->dims->size!=4||in->dims->data[0]!=1||in->dims->data[1]!=edge||in->dims->data[2]!=edge||in->dims->data[3]!=3||in->bytes!=size_t(edge*edge*3)||in->params.scale<=0){Reset();return Error::ModelFormat;}
 const size_t expected_palm[]={2016*18,2016},expected_hand[]={63,1,1,63};
 for(size_t i=0;i<(index==0?2u:4u);i++){
  const auto*o=interpreter_->output(i);const size_t expected=index==0?expected_palm[i]:expected_hand[i];
  if(!o||o->type!=kTfLiteInt8||o->bytes!=expected||o->params.scale<=0){Reset();return Error::ModelFormat;}
 }
 current_=index;return Error::None;
}
InputTensor TflmBackend::Input(){if(!interpreter_)return {nullptr,0,0,0};auto*t=interpreter_->input(0);return {t->data.int8,t->bytes,t->params.scale,t->params.zero_point};}
TensorView TflmBackend::Output(size_t i){if(!interpreter_||i>=(current_==0?2u:4u))return {};auto*t=interpreter_->output(i);return TensorView::Int8(t->data.int8,t->bytes,t->params.scale,t->params.zero_point);}
Error TflmBackend::Invoke(){return interpreter_&&interpreter_->Invoke()==kTfLiteOk?Error::None:Error::Invoke;}
}

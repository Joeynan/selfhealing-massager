#pragma once
#include <cstddef>
#include <cstdint>
namespace watcher_vision {
constexpr size_t kPalmAnchors=2016;
constexpr size_t kLandmarks=21;
struct Point2 {float x=0,y=0;};
struct Point {float x=0,y=0,z=0;};
struct Palm {Point2 center{};float width=0,height=0,score=0;Point2 keypoints[7]{};};
// ROI units are source pixels, clockwise rotation in the image's y-down coordinate system.
struct Roi {Point2 center{};float size=0,rotation=0;};
enum class ImageFormat {Rgb888,Yuv422Planar};
struct RgbImage {const uint8_t* data;int width,height;size_t stride;ImageFormat format=ImageFormat::Rgb888;};
enum class Border {Zero,Replicate};
struct TensorView {
 const void* data=nullptr;size_t count=0;float scale=0;int zero=0;bool is_int8=false;
 static TensorView Float(const float* p,size_t n){return {p,n,1,0,false};}
 static TensorView Int8(const int8_t* p,size_t n,float s,int z){return {p,n,s,z,true};}
 bool Valid()const;
 float At(size_t i)const;
};
Point2 Anchor(size_t index);
size_t DecodePalms(TensorView boxes,TensorView scores,int width,int height,Palm out[2],float score_threshold=.5f,float iou_threshold=.3f);
bool PalmToRoi(const Palm&,Roi&);
Roi PalmInputRoi(int width,int height);
int8_t Quantize01(float value,float scale,int zero);
// Identical quantization for a 0..255 pixel, with a guarded path for the models'
// 1/255 input scale; half-integer boundaries retain the scalar operation order.
int8_t QuantizePixel255(float pixel,float scale,int zero);
bool CropRgb(RgbImage,Roi,int out_width,int out_height,int8_t*,size_t bytes,float scale,int zero,Border border=Border::Zero);
Point Project(Point model_pixels,Roi,int frame_width,int frame_height);
Point ProjectWorld(Point world,Roi);
bool ValidPoint(Point,bool world=false);
}

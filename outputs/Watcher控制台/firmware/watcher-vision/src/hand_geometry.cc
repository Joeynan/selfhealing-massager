#include "hand_geometry.h"
#include <algorithm>
#include <cmath>
#include <limits>
namespace watcher_vision {
namespace {
constexpr float pi=3.14159265358979323846f;
bool finite(float f){return std::isfinite(f);}
float sigmoid(float x){return 1.f/(1.f+std::exp(-std::max(-100.f,std::min(100.f,x))));}
bool Decode(TensorView boxes,TensorView scores,size_t n,int w,int h,Palm& p,float threshold){
 const float logit=scores.At(n);if(!finite(logit))return false;
 p.score=sigmoid(logit);if(p.score<threshold)return false;
 float raw[18];for(size_t i=0;i<18;i++){raw[i]=boxes.At(n*18+i);if(!finite(raw[i])||std::fabs(raw[i])>192*8)return false;}
 const auto anchor=Anchor(n);const float side=float(std::max(w,h)),padx=(side-w)/2,pady=(side-h)/2;
 p.center={(raw[0]/192+anchor.x)*side-padx,(raw[1]/192+anchor.y)*side-pady};
 p.width=raw[2]/192*side;p.height=raw[3]/192*side;
 if(p.width<=0||p.height<=0||p.width>side*4||p.height>side*4)return false;
 for(size_t i=0;i<7;i++)p.keypoints[i]={(raw[4+i*2]/192+anchor.x)*side-padx,(raw[5+i*2]/192+anchor.y)*side-pady};
 return true;
}
float IoU(const Palm&a,const Palm&b){
 const float x=std::max(0.f,std::min(a.center.x+a.width/2,b.center.x+b.width/2)-std::max(a.center.x-a.width/2,b.center.x-b.width/2));
 const float y=std::max(0.f,std::min(a.center.y+a.height/2,b.center.y+b.height/2)-std::max(a.center.y-a.height/2,b.center.y-b.height/2));
 const float overlap=x*y,un=a.width*a.height+b.width*b.height-overlap;return un>0?overlap/un:0;
}
struct RgbSample {float c[3];};
RgbSample Pixel(RgbImage image,int x,int y,Border border){
 if(border==Border::Replicate){x=std::max(0,std::min(image.width-1,x));y=std::max(0,std::min(image.height-1,y));}
 else if(x<0||y<0||x>=image.width||y>=image.height)return {{0,0,0}};
 if(image.format==ImageFormat::Rgb888){const auto*p=image.data+size_t(y)*image.stride+size_t(x)*3;return {{float(p[0]),float(p[1]),float(p[2])}};}
 // Himax/SSCMA planar YUV422: full Y, half-width U, half-width V; full-range coefficients from el_cv.cpp.
 const size_t pixels=size_t(image.width)*image.height,index=size_t(y)*image.width+x;
 const int luma=image.data[index],cb=int(image.data[pixels+index/2])-128,cr=int(image.data[pixels+pixels/2+index/2])-128;
 const int red=luma+(14065*cr)/10000,green=luma-(3455*cb)/10000-(7169*cr)/10000,blue=luma+(17790*cb)/10000;
 return {{float(std::max(0,std::min(255,red))),float(std::max(0,std::min(255,green))),float(std::max(0,std::min(255,blue)))}};
}
}
bool TensorView::Valid()const{return data&&count&&(!is_int8||(finite(scale)&&scale>0&&zero>=-128&&zero<=127));}
float TensorView::At(size_t i)const{
 if(!Valid()||i>=count)return std::numeric_limits<float>::quiet_NaN();
 return is_int8?(int(static_cast<const int8_t*>(data)[i])-zero)*scale:static_cast<const float*>(data)[i];
}
Point2 Anchor(size_t i){
 if(i>=2016)return {0,0};
 if(i<1152){const size_t cell=i/2;return {(float(cell%24)+.5f)/24,(float(cell/24)+.5f)/24};}
 const size_t cell=(i-1152)/6;return {(float(cell%12)+.5f)/12,(float(cell/12)+.5f)/12};
}
size_t DecodePalms(TensorView boxes,TensorView scores,int w,int h,Palm out[2],float threshold,float iou){
 if(!out||w<=0||h<=0||w>8192||h>8192||!boxes.Valid()||!scores.Valid()||boxes.count!=2016*18||scores.count!=2016||!finite(threshold)||threshold<=0||threshold>=1||!finite(iou)||iou<=0||iou>=1)return 0;
 // All anchors are considered. A bitset avoids a large candidate heap or a top-K cap hiding a second hand.
 uint8_t suppressed[(2016+7)/8]{};size_t found=0;
 for(;found<2;found++){
  Palm seed{};size_t best=2016;
  for(size_t i=0;i<2016;i++){if(suppressed[i/8]&(1u<<(i%8)))continue;Palm p{};if(Decode(boxes,scores,i,w,h,p,threshold)&&(best==2016||p.score>seed.score)){seed=p;best=i;}}
  if(best==2016)break;
  Palm sum{};float weight=0;
  for(size_t i=0;i<2016;i++){
   if(suppressed[i/8]&(1u<<(i%8)))continue;Palm p{};if(!Decode(boxes,scores,i,w,h,p,threshold))continue;
   if(i!=best&&IoU(seed,p)<=iou)continue;
   suppressed[i/8]|=uint8_t(1u<<(i%8));weight+=p.score;
   sum.center.x+=p.center.x*p.score;sum.center.y+=p.center.y*p.score;sum.width+=p.width*p.score;sum.height+=p.height*p.score;
   for(size_t k=0;k<7;k++){sum.keypoints[k].x+=p.keypoints[k].x*p.score;sum.keypoints[k].y+=p.keypoints[k].y*p.score;}
  }
  sum.center.x/=weight;sum.center.y/=weight;sum.width/=weight;sum.height/=weight;
  for(auto&k:sum.keypoints){k.x/=weight;k.y/=weight;}sum.score=seed.score;out[found]=sum;
 }
 return found;
}
bool PalmToRoi(const Palm&p,Roi&r){
 const float dx=p.keypoints[2].x-p.keypoints[0].x,dy=p.keypoints[2].y-p.keypoints[0].y;
 if(!finite(dx)||!finite(dy)||dx*dx+dy*dy<1e-6f||!finite(p.width)||!finite(p.height)||p.width<=0||p.height<=0||!finite(p.center.x)||!finite(p.center.y))return false;
 float angle=pi/2-std::atan2(-dy,dx);angle-=2*pi*std::floor((angle+pi)/(2*pi));
 r.rotation=angle;r.size=std::max(p.width,p.height)*2.6f;
 // Shift uses the original height BEFORE squaring/scaling, exactly as RectTransformationCalculator.
 r.center={p.center.x+.5f*p.height*std::sin(angle),p.center.y-.5f*p.height*std::cos(angle)};return true;
}
Roi PalmInputRoi(int w,int h){return {{w*.5f,h*.5f},float(std::max(w,h)),0};}
int8_t Quantize01(float value,float scale,int zero){
 if(!finite(value)||!finite(scale)||scale<=0)return -128;
 const float q=std::round(std::max(0.f,std::min(1.f,value))/scale)+zero;
 return int8_t(std::max(-128.f,std::min(127.f,q)));
}
int8_t QuantizePixel255(float pixel,float scale,int zero){
 if(scale!=1.f/255.f||!finite(pixel)||pixel<0||pixel>255||zero<-128||zero>127)return Quantize01(pixel/255,scale,zero);
 const int nearest=int(pixel+.5f);
 // For binary32 pixels <=255, normalizing/dividing by this exact scale changes
 // the unrounded value by <0.0001. Retain both original divisions and roundf
 // near a half-integer so optimizing cannot change tie or adjacent-float input.
 if(std::fabs(pixel-(nearest-.5f))<=.0001f||std::fabs(pixel-(nearest+.5f))<=.0001f)return Quantize01(pixel/255,scale,zero);
 return int8_t(std::max(-128,std::min(127,nearest+zero)));
}
bool CropRgb(RgbImage im,Roi r,int ow,int oh,int8_t*dst,size_t n,float scale,int zero,Border border){
 if(!im.data||im.width<=0||im.height<=0||im.width>8192||im.height>8192||(im.format==ImageFormat::Rgb888?im.stride<size_t(im.width)*3:(im.width%2||im.stride!=size_t(im.width)))||ow<=0||oh<=0||ow>1024||oh>1024||!dst||n!=size_t(ow)*oh*3||!finite(scale)||scale<=0||zero<-128||zero>127||!finite(r.size)||r.size<=0||r.size>float(std::max(im.width,im.height))*8||!finite(r.center.x)||!finite(r.center.y)||std::fabs(r.center.x)>65536||std::fabs(r.center.y)>65536||!finite(r.rotation))return false;
 const float cs=std::cos(r.rotation),sn=std::sin(r.rotation);
 for(int y=0;y<oh;y++)for(int x=0;x<ow;x++){
  const float u=((x+.5f)/ow-.5f)*r.size,v=((y+.5f)/oh-.5f)*r.size;
  const float sx=r.center.x+cs*u-sn*v-.5f,sy=r.center.y+sn*u+cs*v-.5f;
  const int ix=int(std::floor(sx)),iy=int(std::floor(sy));const float ax=sx-ix,ay=sy-iy;
  const auto p00=Pixel(im,ix,iy,border),p10=Pixel(im,ix+1,iy,border),p01=Pixel(im,ix,iy+1,border),p11=Pixel(im,ix+1,iy+1,border);
  for(int k=0;k<3;k++){
   const float p=(1-ay)*((1-ax)*p00.c[k]+ax*p10.c[k])+ay*((1-ax)*p01.c[k]+ax*p11.c[k]);
   dst[(size_t(y)*ow+x)*3+k]=QuantizePixel255(p,scale,zero);
  }
 }return true;
}
Point Project(Point p,Roi r,int w,int h){
 const float u=(p.x/224-.5f)*r.size,v=(p.y/224-.5f)*r.size,c=std::cos(r.rotation),s=std::sin(r.rotation);
 return {(r.center.x+c*u-s*v)/w,(r.center.y+s*u+c*v)/h,p.z/224/.4f*r.size/w};
}
Point ProjectWorld(Point p,Roi r){const float c=std::cos(r.rotation),s=std::sin(r.rotation);return {c*p.x-s*p.y,s*p.x+c*p.y,p.z};}
bool ValidPoint(Point p,bool world){const float bound=world?10.f:8.f;return finite(p.x)&&finite(p.y)&&finite(p.z)&&std::fabs(p.x)<=bound&&std::fabs(p.y)<=bound&&std::fabs(p.z)<=bound;}
}

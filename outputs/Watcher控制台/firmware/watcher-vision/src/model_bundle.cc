#include "model_bundle.h"
#include <cstring>
namespace watcher_vision {
uint32_t Crc32(const uint8_t*p,size_t n){uint32_t crc=~0u;for(size_t i=0;i<n;i++){crc^=p[i];for(int bit=0;bit<8;bit++)crc=(crc>>1)^(0xedb88320u&uint32_t(-int(crc&1)));}return ~crc;}
namespace {uint32_t Read32(const uint8_t*p){return uint32_t(p[0])|uint32_t(p[1])<<8|uint32_t(p[2])<<16|uint32_t(p[3])<<24;}}
bool ParseBundle(const uint8_t*p,size_t n,Bundle&b){
 b={};if(!p||n<64||std::memcmp(p,"WH21",4)||Read32(p+4)!=1)return false;
 const uint32_t total=Read32(p+8),flags=Read32(p+12),po=Read32(p+16),pl=Read32(p+20),ho=Read32(p+24),hl=Read32(p+28);
 if(total<64||total>n||total>10*1024*1024||flags>1||po<64||ho<64||po%16||ho%16||pl<8||hl<8||po>total||pl>total-po||ho>total||hl>total-ho)return false;
 if(!(po+pl<=ho||ho+hl<=po))return false;
 if(Crc32(p+po,pl)!=Read32(p+32)||Crc32(p+ho,hl)!=Read32(p+36))return false;
 b.palm={p+po,pl};b.hand={p+ho,hl};b.calibrated=(flags&1)!=0;return true;
}
}

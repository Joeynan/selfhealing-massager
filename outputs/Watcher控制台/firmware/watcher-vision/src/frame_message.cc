#include "frame_message.h"
#include <cstdio>
#include <cstring>
namespace watcher_vision {
size_t EncodeSnapshot(const Snapshot& s, char* out, size_t capacity) {
 if(!out || !s.session || !s.frame_id || !s.width || !s.height || s.width>640 || s.height>640 ||
    !s.jpeg || s.jpeg_bytes<4 || s.jpeg_bytes>kMaximumJpegBytes ||
    s.jpeg[0]!=0xff || s.jpeg[1]!=0xd8 ||
    uint32_t(s.send_ms-s.capture_ms)>=800) return 0;
 // Hardware DMA includes trailing zero padding. Remove only zero bytes;
 // require the true EOI marker and never accept arbitrary trailing garbage.
 size_t jpeg_bytes=s.jpeg_bytes;
 while(jpeg_bytes>2 && s.jpeg[jpeg_bytes-1]==0) --jpeg_bytes;
 if(jpeg_bytes<4 || s.jpeg[jpeg_bytes-2]!=0xff || s.jpeg[jpeg_bytes-1]!=0xd9) return 0;
 const size_t encoded=((jpeg_bytes+2)/3)*4;
 // Worst-case header is under 256 bytes; never emit a partial message on a short buffer.
 if(capacity<encoded+512) return 0;
 const int prefix=snprintf(out,capacity,"\r{\"type\":0,\"name\":\"FRAME\",\"code\":0,\"data\":{\"version\":1,\"session\":%lu,\"frame_id\":%lu,\"capture_ms\":%lu,\"send_ms\":%lu,\"width\":%u,\"height\":%u,\"image\":\"",
  (unsigned long)s.session,(unsigned long)s.frame_id,(unsigned long)s.capture_ms,(unsigned long)s.send_ms,unsigned(s.width),unsigned(s.height));
 if(prefix<0 || size_t(prefix)>=capacity) return 0;
 static constexpr char alphabet[]="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
 size_t at=size_t(prefix);
 for(size_t i=0;i<jpeg_bytes;i+=3){
  const size_t left=jpeg_bytes-i;
  const uint32_t value=(uint32_t(s.jpeg[i])<<16)|(left>1?uint32_t(s.jpeg[i+1])<<8:0)|(left>2?s.jpeg[i+2]:0);
  out[at++]=alphabet[(value>>18)&63];out[at++]=alphabet[(value>>12)&63];
  out[at++]=left>1?alphabet[(value>>6)&63]:'=';out[at++]=left>2?alphabet[value&63]:'=';
 }
 const char suffix[]="\"}}\n";memcpy(out+at,suffix,sizeof(suffix));return at+sizeof(suffix)-1;
}
size_t EncodeSnapshotError(uint32_t session,const char* error,char* out,size_t capacity){
 if(!out || !error || !capacity) return 0;
 // Error labels are identifiers, never arbitrary data interpolated into JSON.
 for(const char* p=error;*p;++p)if(!((*p>='a'&&*p<='z')||*p=='_'))return 0;
 const int n=snprintf(out,capacity,"\r{\"type\":0,\"name\":\"FRAME\",\"code\":-1,\"data\":{\"version\":1,\"session\":%lu,\"error\":\"%s\"}}\n",(unsigned long)session,error);
 return n>0&&size_t(n)<capacity?size_t(n):0;
}
}

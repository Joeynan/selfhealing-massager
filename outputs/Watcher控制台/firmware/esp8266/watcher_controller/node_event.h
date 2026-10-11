#pragma once
#include <cstddef>
#include <cstdint>
#include <cstdio>
struct NodeOutputEvent {
 uint32_t id=0,sequence=0,uptime=0;uint8_t reason=0,mode=0,attached_mask=0;uint16_t submitted[3]={};
 bool Format(char* line,size_t size,bool historical)const {
  int count=std::snprintf(line,size,"EVENT %lu %lu %u %u %u %u %u %lu %u %u 5 4 0\n",(unsigned long)id,(unsigned long)sequence,reason,mode,submitted[0],submitted[1],submitted[2],(unsigned long)uptime,historical?1:0,attached_mask);
  return count>0&&size_t(count)<size;
 }
};

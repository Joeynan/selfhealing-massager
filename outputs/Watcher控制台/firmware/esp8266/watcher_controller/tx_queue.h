#pragma once
#include <cstring>
#include <algorithm>
class TxQueue {
 char data_[1024]={};size_t length_=0;
public:
 bool Push(const char* s){size_t n=strlen(s);if(n>sizeof(data_)-length_)return false;memcpy(data_+length_,s,n);length_+=n;return true;}
 size_t NextSize(size_t space)const{return std::min(std::min(space,size_t(32)),length_);}
 const char* Data()const{return data_;}
 void Consume(size_t n){if(n>length_)n=length_;memmove(data_,data_+n,length_-n);length_-=n;}
 void Clear(){length_=0;}size_t Size()const{return length_;}
};

#pragma once
#include <cstring>
#include <cstdint>
inline bool NodePortalRequestAllowed(bool authenticated,const char* expected,const char* supplied){
 if(!authenticated||!expected||!supplied||std::strlen(expected)!=32||std::strlen(supplied)!=32)return false;
 uint8_t difference=0;for(int index=0;index<32;++index)difference|=uint8_t(expected[index]^supplied[index]);return difference==0;
}

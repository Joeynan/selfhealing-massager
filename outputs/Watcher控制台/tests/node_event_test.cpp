#include <cassert>
#include <cstring>
#include <iostream>
#include "../firmware/esp8266/watcher_controller/node_event.h"
int main(){
 NodeOutputEvent e;e.id=4;e.sequence=9;e.reason=5;e.mode=0;e.uptime=60;e.attached_mask=0;for(int i=0;i<3;++i)e.submitted[i]=1500;
 char text[128]={};assert(e.Format(text,sizeof(text),false));assert(!strcmp(text,"EVENT 4 9 5 0 1500 1500 1500 60 0 0 5 4 0\n"));
 e.attached_mask=7;assert(e.Format(text,sizeof(text),true));assert(strstr(text,"60 1 7 5 4 0\n"));
 e.id=e.sequence=e.uptime=UINT32_MAX;e.mode=3;for(auto& p:e.submitted)p=2000;assert(e.Format(text,sizeof(text),false));assert(strlen(text)<127);char small[8]={};assert(!e.Format(small,sizeof(small),false));
 std::cout<<"PASS v6 event history flag, detach mask, explicit GPIO mapping, maximum framing\n";
}

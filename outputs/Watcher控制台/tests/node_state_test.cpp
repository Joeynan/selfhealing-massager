#include <cassert>
#include <cstring>
#include <iostream>
#include "../firmware/esp8266/watcher_controller/node_state.h"
int main() {
 const char* id="watcher-10b41de6009c";
 uint8_t ip[4]={}; assert(ParseTargetIp("10.20.74.207",ip));
 assert(ip[0]==10&&ip[3]==207); assert(!ParseTargetIp("127.0.0.1",ip));
 assert(!ParseTargetIp("10.20.74.999",ip));assert(!ParseTargetIp("10.20.74.207x",ip));
 assert(ValidWatcherId(id)); assert(!ValidWatcherId("watcher-10B41de6009c"));
 NodeIdentityGate gate; gate.Begin(id,100);
 assert(!gate.Verified());assert(!gate.Receive("ARM 1 1",110));
 assert(!gate.Receive("WELCOME SERVO360 watcher-aaaaaaaaaaaa 6",120));
 assert(gate.Receive("WELCOME SERVO360 watcher-10b41de6009c 6",130));assert(gate.Verified());
 gate.Reset();assert(!gate.Verified());gate.Begin(id,0xffffff00u);
 assert(gate.Receive("WELCOME SERVO360 watcher-10b41de6009c 6",0x100u));
 gate.Begin(id,100);assert(!gate.Receive("WELCOME SERVO360 watcher-10b41de6009c 4",200));
 assert(!gate.Receive("WELCOME SERVO360 watcher-10b41de6009c 6 extra",200));
 assert(!gate.Receive("WELCOME SERVO360 watcher-10b41de6009c 6",1600));
 gate.Begin("",100);assert(gate.Receive("WELCOME SERVO360 watcher-10b41de6009c 6",101));assert(!strcmp(gate.Id(),id));
 ServoProfile p; uint8_t address[4]={10,20,74,207};NodeStoredRecord record=MakeNodeRecord(p,address,id);
 ServoProfile loaded;uint8_t loadedIp[4]={};char loadedId[32]={};bool migrated=false;
 assert(LoadNodeRecord(record,loaded,loadedIp,loadedId,migrated));assert(!migrated&&loaded.Id()==p.Id());assert(!strcmp(loadedId,id)&&loadedIp[3]==207);
 record.run[0]=1999;assert(!LoadNodeRecord(record,loaded,loadedIp,loadedId,migrated));
 for(int i=0;i<3;++i)p.run[i]=1560;record=MakeNodeRecord(p,address,id,1);
 assert(LoadNodeRecord(record,loaded,loadedIp,loadedId,migrated));assert(migrated&&loaded.run[0]==2000&&loaded.run[2]==2000);
 record=MakeNodeRecord(p,address,id,2);assert(LoadNodeRecord(record,loaded,loadedIp,loadedId,migrated));assert(!migrated&&loaded.run[0]==1560);
 p.neutral[1]=1490;p.run[1]=1590;record=MakeNodeRecord(p,address,id,1);
 assert(LoadNodeRecord(record,loaded,loadedIp,loadedId,migrated));assert(!migrated&&loaded.neutral[1]==1490&&loaded.run[1]==1590);
 std::cout<<"PASS node identity, strict IPv4, handshake timeout/wrap, checksum, profile migration/custom preservation\n";
}

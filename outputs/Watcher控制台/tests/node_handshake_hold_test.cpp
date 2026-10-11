#include <cassert>
#include <iostream>
#include "../firmware/esp8266/watcher_controller/node_state.h"
int main(){
 NodeIdentityGate gate; const char* id="watcher-10b41de6009c";
 gate.Begin(id,100);assert(gate.Receive("WELCOME SERVO360 watcher-10b41de6009c 6 hold_protocol=2",110));assert(gate.Verified()&&gate.HoldProtocol()==2);
 gate.Reset();assert(!gate.Verified()&&gate.HoldProtocol()==0);
 gate.Begin(id,100);assert(gate.Receive("WELCOME SERVO360 watcher-10b41de6009c 6",110));assert(gate.Verified()&&gate.HoldProtocol()==0);
 gate.Begin(id,100);assert(!gate.Receive("WELCOME SERVO360 watcher-10b41de6009c 6 hold_protocol=1",110));
 assert(!gate.Receive("WELCOME SERVO360 watcher-10b41de6009c 6 hold_protocol=2 extra",110));
 assert(!gate.Receive("WELCOME SERVO360 watcher-aaaaaaaaaaaa 6 hold_protocol=2",110));
 assert(!gate.Receive("WELCOME SERVO360 watcher-10b41de6009c 6 hold_protocol=2",1600));
 gate.Begin(id,0xffffff00u);assert(gate.Receive("WELCOME SERVO360 watcher-10b41de6009c 6 hold_protocol=2",20));
 std::cout<<"PASS capability negotiation, legacy preview identity, strict welcome, reset and rollover\n";
}

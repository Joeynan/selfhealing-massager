#include <cassert>
#include <iostream>
#include "../firmware/esp8266/watcher_controller/control_protocol.h"
#include "../firmware/watcher-service/camera_activity.h"
int main(){
 ModeCommand c; assert(!ParseSet("SET 1 1 601",c));assert(ParseSet("SET 1 1 600",c));
 OutputState o(true);assert(o.Apply({1,1,600},100));assert(!o.Apply({1,2,600},200));assert(!o.Tick(699));assert(o.Tick(700));assert(o.Mode()==0);
 TestCommand t;assert(ParseTest("TEST 2 2 1650 500",t));assert(!ParseTest("TEST 2 2 1650 501",t));assert(!ParseTest("TEST 2 4 1650 500",t));assert(o.ApplyTest(t,800));assert(o.Pulse(0)==1500&&o.Pulse(1)==1650&&o.Pulse(2)==1500);assert(o.Tick(1300));assert(o.Pulse(1)==1500);
 ServoProfile p; p.neutral[1]=1490;p.run[1]=1590;assert(p.Valid());assert(o.Configure(p));assert(o.Apply({3,2,500},1400));assert(o.Pulse(1)==1590);o.Disconnect();assert(o.Pulse(1)==1490);
 OutputState disabled(false);assert(disabled.ApplyTest(t,0));assert(disabled.Mode()==0&&disabled.Pulse(1)==1500);
 CameraActivity cam;assert(cam.Apply("session",1,100,1000));assert(cam.Active(1499));assert(!cam.Apply("session",1,0,1499));assert(!cam.Active(1500));assert(cam.Apply("new-session",1,0,1600));assert(!cam.Apply("new-session",2,750,1700));assert(!cam.Active(2200));
 OutputState wrap;assert(wrap.Apply({0xffffffff,3,600},0xffffff00));assert(!wrap.Tick(343));assert(wrap.Tick(344));assert(wrap.Apply({0,1,100},350));
 std::cout<<"PASS leases, duplicates, bounded tests, neutral/profile, camera expiry, wrap\n";
}

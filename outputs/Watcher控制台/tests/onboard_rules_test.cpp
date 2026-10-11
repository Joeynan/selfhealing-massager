#include <cassert>
#include <cmath>
#include <cstdio>
#include "../firmware/watcher-service/onboard_rules.h"
#include "../firmware/watcher-service/button_policy.h"
#include "../firmware/watcher-service/local_capture_activity.h"
using namespace onboard;
Hand Make(const char* kind, uint32_t id=1,float scale=90,float rotation=0,bool mirror=false) {
 Hand h;h.id=id;h.side=mirror?Side::Right:Side::Left;
 h.points[1]={-.3f,-.2f,0};h.points[2]={-.6f,-.4f,0};h.points[3]={-.72f,-.62f,0};h.points[4]={-.85f,-.9f,0};
 float x[4]={-.4f,0,.3f,.55f},y[4]={-.9f,-1,-.9f,-.75f};
 for(int j=0;j<4;j++){int b=5+j*4;h.points[b]={x[j],y[j],0};h.points[b+1]={x[j],y[j]-.5f,0};h.points[b+2]={x[j],y[j]-.9f,0};h.points[b+3]={x[j],y[j]-1.25f,0};
 if(std::string(kind)=="fist"||std::string(kind)=="closed"){h.points[b+2]={x[j]+.18f,y[j]-.35f,0};h.points[b+3]={x[j]+.18f,y[j]-.05f,0};}}
 if(std::string(kind)=="pinch")h.points[8]=h.points[4];
 if(std::string(kind)=="closed"){h.points[4]={-.2f,-1.2f,0};for(int j=0;j<4;j++)h.points[8+j*4]={-.2f+j*.06f,-1.2f+j*.02f,0};}
 for(auto& p:h.points){float px=mirror?-p.x:p.x;float py=p.y;p={(320+scale*(cos(rotation)*px-sin(rotation)*py))/640,(330+scale*(sin(rotation)*px+cos(rotation)*py))/480,0};}return h;
}
Frame F(uint64_t id,uint32_t t,Hand h){Frame f;f.id=id;f.captured_ms=t;f.width=640;f.height=480;f.valid=f.model_ready=true;f.hand_count=1;f.hands[0]=h;return f;}
void Feed(Engine& e,Hand h){e.Process(F(1,100,h),100);e.Process(F(2,250,h),250);e.Process(F(3,450,h),450);}
int main(){
 Config c;c.back_sign[0]=1;c.back_sign[1]=-1;
 Engine e(c);Feed(e,Make("pinch"));assert(e.Snapshot(450).stable==3);assert(e.Snapshot(1250).stable==0);
 Engine dup(c);auto f=F(1,100,Make("pinch"));dup.Process(f,100);f.captured_ms=450;dup.Process(f,450);assert(dup.Snapshot(450).stable==0);
 Engine late(c);late.Process(F(1,100,Make("pinch")),1000);assert(late.Snapshot(1000).stable==0);
 for(float rot:{-.7f,.7f}){Engine r(c);Feed(r,Make("pinch",1,50,rot));assert(r.Snapshot(450).stable==3);}
 Engine fist(c);Feed(fist,Make("fist"));assert(fist.Snapshot(450).stable==1);
 Engine uncal;Feed(uncal,Make("fist"));assert(uncal.Snapshot(450).stable==0);
 Engine right(c);Feed(right,Make("fist",1,90,0,true));assert(right.Snapshot(450).stable==1);
 Engine staticGather(c);Feed(staticGather,Make("closed"));assert(staticGather.Snapshot(450).stable==0);
 for(const char* close:{"closed","fist"}){Engine k(c);k.Process(F(1,100,Make(close)),100);k.Process(F(2,400,Make("open")),400);k.Process(F(3,800,Make(close)),800);assert(k.Snapshot(800).stable==2);k.Process(F(4,1200,Make(close)),1200);k.Process(F(5,1650,Make(close)),1650);assert(k.Snapshot(1650).stable!=2);k.Process(F(6,2000,Make("open")),2000);assert(k.Snapshot(2000).stable!=2);}
 Engine conflict(c);Feed(conflict,Make("pinch"));f=F(4,550,Make("pinch"));f.hand_count=2;f.hands[1]=Make("fist",2);conflict.Process(f,550);assert(conflict.Snapshot(550).stable==0);
 Engine identities(c);for(int j=0;j<3;j++)identities.Process(F(j+1,100+175*j,Make("pinch",j+1)),100+175*j);assert(identities.Snapshot(450).stable==0);
 Engine missing(c);missing.Process(F(1,100,Make("pinch")),100);f=F(2,250,Make("pinch"));f.hand_count=0;missing.Process(f,250);missing.Process(F(3,450,Make("pinch")),450);assert(missing.Snapshot(450).stable==0);
 Engine bad(c);auto h=Make("pinch");h.points[4].x=NAN;Feed(bad,h);assert(bad.Snapshot(450).stable==0);
 Engine identityAfterInvalid(c);Feed(identityAfterInvalid,Make("pinch"));auto invalid=Make("pinch");invalid.points[4].x=NAN;identityAfterInvalid.Process(F(4,550,invalid),550);identityAfterInvalid.Process(F(5,650,Make("pinch",2)),650);assert(identityAfterInvalid.Snapshot(650).stable==0);
 assert(!ShutdownReady(false,false,false,true,900,500));assert(ShutdownReady(false,false,false,true,900,900));assert(!ShutdownReady(false,false,true,false,0,900));
 ButtonPolicy b;assert(b.Up(6000)==ButtonAction::None);b.Down(10000);assert(b.Tick(12999)==ButtonAction::None);assert(b.Tick(13000)==ButtonAction::Disarm);assert(b.Tick(13020)==ButtonAction::None);assert(b.Up(13050)==ButtonAction::Shutdown);b.Down(20000);assert(b.Up(22500)==ButtonAction::None);b.Down(30000);assert(b.Up(30500)==ButtonAction::None);
 InputOwner owner;assert(!owner.AllowsServoConfiguration());assert(!owner.Accept("camera"));assert(owner.Accept("onboard"));assert(owner.Switch("simulation"));assert(owner.Accept("simulation")&&!owner.Accept("onboard"));assert(!owner.Switch("invalid"));assert(owner.AllowsServoConfiguration());assert(owner.Switch("camera"));assert(!owner.AllowsServoConfiguration());
 LocalCaptureActivity activity;assert(activity.Apply(true,true,1,100,120));assert(activity.Active(120));assert(!activity.Apply(false,true,2,150,170));assert(!activity.Active(170));assert(!activity.Apply(true,true,1,180,190));assert(!activity.Active(190));assert(activity.Apply(true,true,3,200,220));assert(!activity.Apply(true,false,4,250,270));assert(!activity.Active(270));assert(activity.Apply(true,true,5,300,320));assert(!activity.Apply(true,true,6,350,1200));assert(!activity.Active(1200));
 puts("onboard rules, uniqueness, safety and button policy tests passed");
}

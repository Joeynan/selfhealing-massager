#include "../firmware/watcher-service/servo_profile.h"
#include <cassert>
int main() {
    ServoProfile p;
    for (int i=0;i<3;++i) assert(p.run[i]==2000 && p.neutral[i]==1500);
    assert(p.Valid());
    p.run[1]=2010; assert(!p.Valid());
    p.run[1]=1500; assert(!p.Valid());
    p.run[1]=1995; assert(!p.Valid());
    p.run[1]=1600; assert(p.Valid());
    ServoProfile legacy;
    for(int i=0;i<3;++i) legacy.run[i]=1560;
    assert(legacy.MigrateLegacyDefault(1));
    assert(legacy.run[1]==2000);
    assert(!legacy.MigrateLegacyDefault(2));
    ServoProfile custom;
    custom.run[0]=1650;
    assert(!custom.MigrateLegacyDefault(1));
    assert(custom.run[0]==1650);
}

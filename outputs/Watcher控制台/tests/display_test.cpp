#include <cassert>
#include "../firmware/watcher-service/display_receipt.h"
int main() {
 const uint16_t expected[3]={1650,1500,1500}, previous[3]={1560,1500,1500};
 assert(!HasCurrentServoReceipt(1,10,9,1,expected,expected,100,101));
 assert(!HasCurrentServoReceipt(1,10,10,1,expected,previous,100,101));
 assert(HasCurrentServoReceipt(1,10,10,1,expected,expected,100,101));
 assert(!HasCurrentServoReceipt(1,10,10,1,expected,expected,100,701));
 assert(!FaceNeedsReceipt(1,false,false)); // Disarmed preview must change expression.
 assert(FaceNeedsReceipt(1,true,false));  // ARM pending cannot look applied.
 assert(FaceNeedsReceipt(1,true,true));
 assert(!FaceNeedsReceipt(0,true,true));
}

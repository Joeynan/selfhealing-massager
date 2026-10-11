#include <cassert>
#include <iostream>
#include "../firmware/esp8266/watcher_controller/node_portal_guard.h"
int main(){const char* token="a123456789abcdefa123456789abcdef";assert(!NodePortalRequestAllowed(false,token,token));assert(!NodePortalRequestAllowed(true,token,""));assert(!NodePortalRequestAllowed(true,"",token));assert(!NodePortalRequestAllowed(true,token,"b123456789abcdefa123456789abcdef"));assert(NodePortalRequestAllowed(true,token,token));std::cout<<"PASS configuration requires authenticated request and exact nonempty boot token\n";}

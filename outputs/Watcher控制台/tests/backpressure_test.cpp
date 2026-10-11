#include <cassert>
#include "../firmware/esp8266/watcher_controller/tx_queue.h"
#include "../firmware/esp8266/watcher_controller/control_protocol.h"
int main(){TxQueue q;OutputState state;assert(state.Apply({1,1,600},0));assert(q.Push("ACK delayed by a zero-window peer\n"));for(unsigned t=0;t<=600;++t){assert(q.NextSize(0)==0);state.Tick(t);}assert(state.Mode()==0&&state.Pulse(0)==1500);assert(q.Size()>0);assert(q.NextSize(1000)<=32);}

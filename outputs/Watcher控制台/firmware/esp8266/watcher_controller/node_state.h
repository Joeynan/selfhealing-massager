#pragma once
#include <cstdint>
#include <cstring>
#include "servo_profile.h"
#include <cstddef>
inline bool UnicastTargetIp(const uint8_t ip[4]) { return ip[0] > 0 && ip[0] < 224 && ip[0] != 127; }
inline bool ParseTargetIp(const char* text,uint8_t result[4]) {
 if(!text)return false;uint8_t parsed[4]={};
 for(int index=0;index<4;++index){unsigned value=0,digits=0;while(*text>='0'&&*text<='9'){if(++digits>3)return false;value=value*10+unsigned(*text++-'0');if(value>255)return false;}if(!digits)return false;parsed[index]=value;if(index<3){if(*text++!='.')return false;}else if(*text)return false;}
 if(!UnicastTargetIp(parsed))return false;std::memcpy(result,parsed,4);return true;
}
inline bool ValidWatcherId(const char* id) {
 if(!id||std::strlen(id)!=20||std::strncmp(id,"watcher-",8))return false;
 for(int i=8;i<20;++i)if(!((id[i]>='0'&&id[i]<='9')||(id[i]>='a'&&id[i]<='f')))return false;return true;
}
class NodeIdentityGate {
 char expected_[32]={},identity_[32]={};uint32_t began_=0;bool verified_=false,invalid_=false;uint8_t hold_protocol_=0;
public:
 void Begin(const char* expected,uint32_t now){Reset();began_=now;invalid_=expected&&*expected&&!ValidWatcherId(expected);if(expected&&!invalid_)std::strncpy(expected_,expected,sizeof(expected_)-1);}
 bool Receive(const char* line,uint32_t now){
  constexpr const char* prefix="WELCOME SERVO360 ";constexpr size_t length=sizeof("WELCOME SERVO360 ")-1;
  if(verified_||invalid_||(uint32_t)(now-began_)>=1500||!line||std::strncmp(line,prefix,length))return false;
  const char* payload=line+length;const char* space=std::strchr(payload,' ');if(!space||space-payload!=20)return false;
  const bool capable=!std::strcmp(space," 6 hold_protocol=2");
  if(!capable&&std::strcmp(space," 6"))return false;
  char id[32]={};std::memcpy(id,payload,20);if(!ValidWatcherId(id)||(*expected_&&std::strcmp(id,expected_)))return false;
  std::strcpy(identity_,id);verified_=true;hold_protocol_=capable?2:0;return true;
 }
 bool Verified()const{return verified_;}const char* Id()const{return identity_;}uint8_t HoldProtocol()const{return hold_protocol_;}
 void Reset(){verified_=false;invalid_=false;hold_protocol_=0;expected_[0]=identity_[0]=0;}
};
#pragma pack(push,1)
struct NodeStoredRecord {
 uint32_t magic=0;uint16_t storage_version=2;uint32_t profile_version=kServoProfileVersion;
 uint8_t target_ip[4]={};char watcher_id[32]={};uint16_t neutral[3]={},run[3]={};char portal_key[33]={};uint32_t checksum=0;
};
#pragma pack(pop)
inline uint32_t NodeRecordChecksum(const NodeStoredRecord& record){uint32_t value=2166136261u;const auto* bytes=reinterpret_cast<const uint8_t*>(&record);for(size_t i=0;i<offsetof(NodeStoredRecord,checksum);++i)value=(value^bytes[i])*16777619u;return value;}
inline void SealNodeRecord(NodeStoredRecord& record){record.checksum=NodeRecordChecksum(record);}
inline NodeStoredRecord MakeNodeRecord(const ServoProfile& profile,const uint8_t ip[4],const char* id,uint32_t version=kServoProfileVersion){
 NodeStoredRecord record;record.magic=0x4e534336u;record.profile_version=version;std::memcpy(record.target_ip,ip,4);if(id)std::strncpy(record.watcher_id,id,sizeof(record.watcher_id)-1);
 for(int i=0;i<3;++i){record.neutral[i]=profile.neutral[i];record.run[i]=profile.run[i];}SealNodeRecord(record);return record;
}
inline bool LoadNodeRecord(const NodeStoredRecord& record,ServoProfile& profile,uint8_t ip[4],char id[32],bool& migrated){
 migrated=false;if(record.magic!=0x4e534336u||record.storage_version<1||record.storage_version>2||record.profile_version<1||record.profile_version>kServoProfileVersion||record.checksum!=NodeRecordChecksum(record))return false;
 if(record.watcher_id[31]||record.portal_key[32])return false;if(*record.watcher_id&&!ValidWatcherId(record.watcher_id))return false;
 bool noIp=true;for(int i=0;i<4;++i)noIp=noIp&&record.target_ip[i]==0;if(!noIp&&!UnicastTargetIp(record.target_ip))return false;
 ServoProfile candidate;for(int i=0;i<3;++i){candidate.neutral[i]=record.neutral[i];candidate.run[i]=record.run[i];}if(!candidate.Valid())return false;
 migrated=candidate.MigrateLegacyDefault(record.profile_version);profile=candidate;std::memcpy(ip,record.target_ip,4);std::strcpy(id,record.watcher_id);return true;
}

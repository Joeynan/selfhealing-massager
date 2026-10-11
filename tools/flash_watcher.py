#!/usr/bin/env python3
"""Run the preserved, identity-checked v9 application flasher from this project."""
from pathlib import Path
import argparse, hashlib, importlib.util, re, struct, sys, zlib
ROOT=Path(__file__).resolve().parent.parent
RELEASE=ROOT/'outputs/Watcher控制台/滚轮表情版'
RELEASES={False:('watcher-controller-v9-wheel-face.bin',2879808,'fb4fe0e39777e3e5d0594b7662ad559fc3a42af490dd71064be9d42bea4cbece'),
          True:('watcher-controller-v8-continuous-output.bin',3013408,'319edfdc630860f65c453ab4eeaca90a378a59741e5ba938f1e368db7c3cbc9e')}

def release_module():
    spec=importlib.util.spec_from_file_location('preserved_watcher_release',RELEASE/'flash_release.py')
    release=importlib.util.module_from_spec(spec);spec.loader.exec_module(release)
    return release

def validate_release(root, rollback):
    if not (root/'release-manifest.json').is_file() or not (root/RELEASES[rollback][0]).is_file():
        raise ValueError('缺少发布附件；请下载并解压 selfhealing-watcher-v9.zip，再用 --release-dir 指定解压目录。')
    release=release_module();image,manifest=release.validate(root)
    expected=RELEASES[rollback]
    if (manifest.get('app'),manifest.get('bytes'),manifest.get('sha256'))!=expected:
        raise ValueError('发布版与已验证 release 的固定校验值不符。')
    return release,image,manifest

def partition_entries(data):
    entries=[]; consumed=b''
    for offset in range(0,len(data)-31,32):
        block=data[offset:offset+32];magic=struct.unpack_from('<H',block)[0]
        if block==b'\xff'*32:break
        if magic==0xebeb:
            if block[16:]!=hashlib.md5(consumed).digest():
                raise ValueError('实际 partition table MD5 校验失败，未写入。')
            break
        if magic!=0x50aa:raise ValueError('实际 partition table 格式不符，未写入。')
        _,kind,subtype,address,size,label,_=struct.unpack('<HBBII16sI',block)
        entries.append((kind,subtype,address,size,label.split(b'\0')[0].decode('ascii')))
        consumed+=block
    if not entries:raise ValueError('实际 partition table 为空，未写入。')
    return entries

def validate_device_layout(partitions, ota_data, image_bytes):
    entries=partition_entries(partitions)
    apps=[r for r in entries if r[0]==0]
    ota0=[r for r in apps if r[1]==0x10]
    ota1=[r for r in apps if r[1]==0x11]
    metadata=[r for r in entries if r[:2]==(1,0)]
    if (len(apps)!=2 or len(ota0)!=1 or len(ota1)!=1 or len(metadata)!=1 or
        ota0[0][2]!=0x200000 or ota0[0][3] not in (0x400000,0xc00000) or
        ota0[0][4]!='ota_0' or image_bytes>ota0[0][3] or
        ota1[0][2]!=ota0[0][2]+ota0[0][3] or ota1[0][3]!=ota0[0][3] or
        metadata[0][3]!=0x2000 or metadata[0][2]+metadata[0][3]>0x200000):
        raise ValueError('实际应用 partition 分区与已验证布局不符，未写入。')
    previous_end=0x9000
    for _,_,address,size,_ in sorted(entries,key=lambda r:r[2]):
        if address<previous_end or size<=0 or address+size>0x2000000:
            raise ValueError('实际 partition 分区重叠 overlap 或超出 Flash，未写入。')
        previous_end=address+size
    if len(ota_data)!=0x2000:raise ValueError('实际 OTA 数据不完整，未写入。')
    sequences=[]
    for offset in (0,4096):
        record=ota_data[offset:offset+32]
        if record==b'\xff'*32:continue
        sequence,state,crc=struct.unpack_from('<I20xII',record)
        if sequence in (0,0xffffffff) or crc!=(zlib.crc32(record[:4],0xffffffff)&0xffffffff):
            raise ValueError('实际 OTA 记录 CRC 不符，未写入。')
        if state not in (0,1,2,3,4,0xffffffff):raise ValueError('实际 OTA 状态未知，未写入。')
        if state not in (3,4):sequences.append(sequence)
    if not sequences and any(r[1]==0 for r in apps):
        raise ValueError('当前启动分区可能是 factory 而非 ota_0，未写入。')
    if sequences and (max(sequences)-1)%2:
        raise ValueError('设备当前 OTA 选择不是 ota_0，未写入；保留 OTA 配置。')
    return {'application_address':0x200000,'application_bytes':ota0[0][3],
            'selected_application':'ota_0','ota_address':metadata[0][2]}

class SpiInitializedTool:
    """Initialize the SPI bus while keeping the preserved writer's guard order."""
    def __init__(self, tool):
        self.tool=tool
    def __getattr__(self, name):
        return getattr(self.tool, name)
    def run_stub(self, device):
        stub=self.tool.run_stub(device)
        self.tool.attach_flash(stub)
        return stub

class LayoutCheckedTool(SpiInitializedTool):
    """Read layout through the same authenticated connection before any write."""
    def __init__(self,tool,image_bytes):
        super().__init__(tool);self.image_bytes=image_bytes
    def run_stub(self,device):
        stub=super().run_stub(device)
        table=self.tool.read_flash(stub,0x8000,0x1000,no_progress=True)
        entries=partition_entries(table)
        metadata=[r for r in entries if r[:2]==(1,0)]
        if len(metadata)!=1 or metadata[0][3]!=0x2000 or metadata[0][2]+0x2000>0x200000:
            raise ValueError('实际 OTA partition 元数据位置不符，未写入。')
        selected=self.tool.read_flash(stub,metadata[0][2],0x2000,no_progress=True)
        validate_device_layout(table,selected,self.image_bytes)
        print('实际分区与 ota_0 启动选择检查通过。',flush=True)
        return stub

def candidate_ports(rows):
    # Watcher exposes ESP32-S3 and WE2 through one CH342 USB bridge. Only its
    # known controller interface is a candidate; chip/MAC authentication follows.
    ports=[]
    for row in rows:
        native=row.vid==0x303a
        bridge=(row.vid==0x1a86 and row.pid==0x55d2 and row.serial_number=='5AF9164570')
        windows=bool(re.fullmatch(r'COM[1-9][0-9]*',row.device,re.IGNORECASE))
        mac=row.device.startswith('/dev/cu.usbmodem')
        if ((mac and (native or (bridge and row.device.endswith('03')))) or
            (windows and (native or bridge))):ports.append(row.device)
    return sorted(set(ports))

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rollback',action='store_true')
    parser.add_argument('--dry-run',action='store_true')
    parser.add_argument('--port')
    parser.add_argument('--release-dir',type=Path,default=RELEASE,help='Downloaded release bundle root; contains release-manifest.json and 上一版回滚/')
    args=parser.parse_args()
    root=args.release_dir/'上一版回滚' if args.rollback else args.release_dir
    try:
        release,image,manifest=validate_release(root,args.rollback);data=image.read_bytes()
        if len(data)!=manifest['bytes'] or hashlib.sha256(data).hexdigest()!=manifest['sha256']:
            raise ValueError('镜像在读取期间已变化。')
        print(f"镜像验证通过：{len(data)} 字节；只写应用地址 0x200000。",flush=True)
        print('设备：ESP32-S3 / '+manifest['device_mac'],flush=True)
        if args.dry_run:
            print('离线检查通过；未枚举、打开或重置串口。');return 0
        import esptool
        from serial.tools import list_ports
        if esptool.__version__!='5.4.0':raise ValueError('此入口需要 esptool 5.4.0。')
        ports=candidate_ports(list_ports.comports())
        if args.port:
            if args.port not in ports:raise ValueError('指定串口不是已识别的小智控制接口。')
            ports=[args.port]
        elif sys.platform=='win32':raise ValueError('Windows 必须用 --port COM号 明确选择小智控制接口；两个 CH342 接口不能自动区分。')
        if len(ports)!=1:raise ValueError('未找到唯一小智控制接口；多候选时使用 --port 指定。')
        release.flash_checked(data,manifest,ports[0],LayoutCheckedTool(esptool,len(data)))
        print('应用写入及内容校验完成；请继续实机验收。');return 0
    except Exception as error:
        print('已停止：'+str(error),file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

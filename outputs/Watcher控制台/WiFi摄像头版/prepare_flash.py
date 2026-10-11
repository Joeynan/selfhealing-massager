"""Default is artifact verification only. Tomorrow's scoped update is explicit."""
import argparse,hashlib,json,re,struct,subprocess,sys
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parent

def verified_files(rollback=False):
    manifest=json.loads((ROOT/'release-manifest.json').read_text())
    key='rollback' if rollback else 'firmware'
    files=[]
    for item in manifest[key]:
        path=ROOT/item['file']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('固件校验失败：'+item['file'])
        files.append((path,item))
    return manifest,files

def verify_layout(boot):
    entries={}
    for offset in range(0x8000,0x9000,32):
        block=boot[offset:offset+32]
        if len(block)!=32 or block[:2]!=b'\xaa\x50':break
        _,kind,subtype,address,size,label,_=struct.unpack('<HBBII16sI',block)
        entries[label.rstrip(b'\0').decode('ascii')]=(kind,subtype,address,size)
    if entries.get('ota_0')!=(0,16,0x200000,0xc00000):
        raise ValueError('实际应用分区与本发布版不符，未烧录；请先核对分区表')
    # Existing project uses ota_0. Refuse a later switched ota_1 rather than alter otadata.
    records=[struct.unpack_from('<I',boot,p)[0] for p in (0x10d000,0x10e000)]
    valid=[seq for seq in records if seq not in (0,0xffffffff)]
    if valid and (max(valid)-1)%2!=0:
        raise ValueError('设备当前 OTA 选择不是 ota_0，未烧录；保留原 OTA 配置')

def main(argv=None):
    parser=argparse.ArgumentParser(description='默认只校验文件；添加 --execute 才接触 USB 并烧录')
    parser.add_argument('--execute',action='store_true')
    parser.add_argument('--rollback',action='store_true')
    parser.add_argument('--s3-port',help='小智 ESP32-S3 的 USB 串口')
    parser.add_argument('--vision-port',help='小智视觉芯片的 USB 串口，不能填黑板串口')
    parser.add_argument('--baud',type=int,choices=[115200,230400,460800,921600],default=230400,help='ESP32 烧录速率，默认使用实机验证的 230400')
    args=parser.parse_args(argv)
    manifest,files=verified_files(args.rollback)
    print('文件校验通过。只写 S3 的 0x200000 应用分区和视觉应用；保留 NVS、模型、引脚映射。')
    for path,item in files:print(path.name,item['bytes'],'bytes',item['sha256'])
    if not args.execute:
        print('预检查完成，未连接设备、未烧录。执行前关闭旧服务并断开舵机电源。')
        return
    if (not args.s3_port or not args.vision_port or args.s3_port==args.vision_port or
        not all(re.fullmatch(r'/dev/cu\.[A-Za-z0-9_.-]+',p) for p in (args.s3_port,args.vision_port))):
        parser.error('需要两个不同且已核实的小智 /dev/cu.* 串口')
    base=[sys.executable,'-m','esptool','--chip','esp32s3','--port',args.s3_port,
          '--baud',str(args.baud),'--after','no-reset']
    # esptool rejects an ESP8266 before any write; bind the known Watcher identity too.
    identity=subprocess.run(base+['read-mac'],check=True,capture_output=True,text=True).stdout
    expected=manifest['watcher_mac'].lower()
    if expected not in identity.lower():raise RuntimeError('串口芯片 MAC 与目标小智不符，未烧录')
    work=ROOT.parents[2]/'work/control-v7/device-backups'/datetime.now().strftime('%Y%m%d-%H%M%S')
    work.mkdir(parents=True,exist_ok=False,mode=0o700)
    # These are readbacks from tomorrow's actual device, not assumptions about its NVS.
    subprocess.run(base+['read-flash','0x0','0x200000',str(work/'boot-and-settings.bin')],check=True)
    verify_layout((work/'boot-and-settings.bin').read_bytes())
    subprocess.run(base+['read-flash','0x200000','0xc00000',str(work/'s3-application-partition.bin')],check=True)
    for p in work.iterdir():p.chmod(0o600)
    app,vision=files
    subprocess.run([sys.executable,str(ROOT/'vision_upload.py'),'--port',args.vision_port,
                    '--image',str(vision[0]),'--image-sha',vision[1]['sha256']],check=True)
    # S3 remains in ROM download while the visual application is updated above.
    writebase=[sys.executable,'-m','esptool','--chip','esp32s3','--port',args.s3_port,
               '--baud',str(args.baud),'--after','hard-reset']
    subprocess.run(writebase+['write-flash','0x200000',str(app[0])],check=True)
    print('应用写入流程完成；实际无线画面、表情和舵机运动仍需逐项测试。备份：',work)

if __name__=='__main__':main()

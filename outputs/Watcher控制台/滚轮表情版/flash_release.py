#!/usr/bin/env python3
"""Validate and flash only a designated Watcher application partition."""
import argparse,hashlib,json,re,sys
from pathlib import Path
APP_ADDRESS=0x200000
APP_LIMIT=0x400000
TARGET_MAC='10:b4:1d:e6:00:9c'
def validate(root):
 root=Path(root).resolve();m=json.loads((root/'release-manifest.json').read_text(encoding='utf-8'))
 if m.get('build_verified') is not True:raise ValueError('没有已验证的构建结果。')
 if m.get('chip')!='esp32s3' or m.get('address')!='0x200000':raise ValueError('包不是 ESP32-S3 的指定应用分区。')
 if m.get('device_mac')!=TARGET_MAC:raise ValueError('设备身份不符。')
 name=m.get('app','')
 if not isinstance(name,str) or not name or Path(name).name!=name:raise ValueError('镜像必须在包内。')
 image=root/name
 if image.is_symlink() or image.resolve().parent!=root:raise ValueError('镜像路径不在包内。')
 data=image.read_bytes()
 if not 96<=len(data)<=APP_LIMIT:raise ValueError('镜像超出应用分区。')
 if len(data)!=m.get('bytes') or hashlib.sha256(data).hexdigest()!=m.get('sha256'):raise ValueError('镜像大小或 SHA256 不匹配。')
 if data[0]!=0xe9 or int.from_bytes(data[12:14],'little')!=9:raise ValueError('镜像不是 ESP32-S3 应用。')
 return image,m
def identity_matches(description,expected_mac):
 return 'ESP32-S3' in description and bool(re.search(r'(?i)\b'+re.escape(expected_mac)+r'\b',description))
def flash_checked(data,m,port,tool):
 # The authenticated connection and verified bytes are reused for write and verify.
 with tool.detect_chip(port=port,baud=115200,connect_mode='default-reset',connect_attempts=3) as device:
  if device.CHIP_NAME!='ESP32-S3':raise ValueError('芯片不符，未写入：'+device.CHIP_NAME)
  values=device.read_mac();actual=':'.join(f'{v:02x}' for v in values) if values else ''
  if actual!=m['device_mac']:raise ValueError('设备 MAC 不符，未写入：'+actual)
  device=tool.run_stub(device);images=[(APP_ADDRESS,data)]
  options=dict(flash_freq='keep',flash_mode='keep',flash_size='keep')
  tool.write_flash(device,images,compress=True,erase_all=False,force=False,**options)
  tool.verify_flash(device,images,**options);device.hard_reset()
def main():
 p=argparse.ArgumentParser(description='仅更新指定小智的应用，保留配置和视觉固件')
 p.add_argument('--root',type=Path,default=Path(__file__).resolve().parent);p.add_argument('--dry-run',action='store_true');p.add_argument('--port')
 a=p.parse_args()
 try:
  image,m=validate(a.root);data=image.read_bytes()
  if len(data)!=m['bytes'] or hashlib.sha256(data).hexdigest()!=m['sha256']:raise ValueError('镜像在读取期间已变化。')
  print(f'镜像验证通过：{len(data)} 字节；只写应用地址 0x200000。');print('设备：ESP32-S3 / '+m['device_mac'])
  if a.dry_run:print('离线检查通过；未枚举、打开或重置串口。');return 0
  import esptool
  if esptool.__version__!='5.4.0':raise ValueError('此入口需要 esptool 5.4.0。')
  from serial.tools import list_ports
  ports=sorted(p.device for p in list_ports.comports() if p.device.startswith('/dev/cu.usbmodem') and p.vid in (None,0x303A))
  if a.port:
   if a.port not in ports:raise ValueError('指定串口不是已识别的小智原生 USB 口。')
   ports=[a.port]
  if len(ports)!=1:raise ValueError('未找到唯一小智原生 USB 口；连接数据口，多候选时用 --port 指定。')
  flash_checked(data,m,ports[0],esptool);print('应用写入及内容校验完成；请继续实机验收。');return 0
 except Exception as error:print('已停止：'+str(error),file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())

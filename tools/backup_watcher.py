#!/usr/bin/env python3
"""Read the identity-checked Watcher update/configuration area before app flashing."""
from pathlib import Path
import argparse,datetime,hashlib,json,os,sys
from flash_watcher import candidate_ports
TARGET_MAC='10:b4:1d:e6:00:9c'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    import esptool
    from serial.tools import list_ports
    if esptool.__version__!='5.4.0':raise ValueError('Pinned esptool 5.4.0 required')
    if args.port not in candidate_ports(list_ports.comports()):raise ValueError('Not a recognized Watcher control interface')
    args.output.mkdir(parents=True,exist_ok=True);args.output.chmod(0o700)
    paths=[('boot-config-before.bin',0,0x200000),('application-before.bin',0x200000,0x400000)]
    for name,_,_ in paths:
        if (args.output/name).exists():raise ValueError('Refusing to replace an earlier backup: '+name)
    rows=[]
    with esptool.detect_chip(port=args.port,baud=115200,connect_mode='default-reset',connect_attempts=3) as device:
        if device.CHIP_NAME!='ESP32-S3':raise ValueError('Wrong chip; no backup or writes performed')
        actual=':'.join(f'{v:02x}' for v in device.read_mac())
        if actual!=TARGET_MAC:raise ValueError('Wrong device MAC; no backup or writes performed')
        device=esptool.run_stub(device)
        esptool.attach_flash(device)  # Use the verified 115200 baud rate throughout.
        for name,address,size in paths:
            path=args.output/name
            esptool.read_flash(device,address,size,output=str(path),no_progress=False)
            path.chmod(0o600)
            if path.stat().st_size!=size:raise ValueError('Incomplete backup: '+name)
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            rows.append({'file':name,'address':hex(address),'bytes':size,'sha256':digest})
            print('Backup verified: '+name+' '+str(size)+' bytes',flush=True)
        report={'time':datetime.datetime.now().astimezone().isoformat(),'chip':'esp32s3','device_mac':actual,'port':args.port,'flash_write_performed':False,'files':rows}
        manifest=args.output/'backup-manifest.json';manifest.write_text(json.dumps(report,indent=2)+'\n');manifest.chmod(0o600)
        device.hard_reset()
    return 0
if __name__=='__main__':
    try:sys.exit(main())
    except Exception as e:print('Backup stopped: '+str(e),file=sys.stderr);sys.exit(1)

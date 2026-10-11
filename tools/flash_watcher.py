#!/usr/bin/env python3
"""Flash an immutable release or an explicitly selected verified local build.

Use --release-dir for the preserved v9/v8 package, or --build-dir for this
project's build directory (report, sdkconfig, partition table and xiaozhi.bin).
Both paths authenticate the same ESP32-S3 device and inspect the actual OTA
layout before writing only 0x200000. --dry-run never imports hardware libraries.
"""
from pathlib import Path
import argparse, hashlib, importlib.util, json, re, struct, sys, zlib
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

def checked_project_path(path):
    """Keep a local build artifact inside this clone, without symlink indirection."""
    path=Path(path).absolute();root=ROOT.absolute()
    try:relative=path.relative_to(root)
    except ValueError:raise ValueError('本地构建 path 路径必须位于当前工程内。') from None
    current=root
    # 路径中的链接也必须拒绝，不能仅检查最后的文件名。
    for part in relative.parts:
        if part in ('.','..'):raise ValueError('本地构建 path 路径不能包含跳转段。')
        current=current/part
        if current.is_symlink():raise ValueError('本地构建 path 路径不能使用 symlink 链接。')
    try:path.resolve().relative_to(root.resolve())
    except ValueError:raise ValueError('本地构建 path 路径逃离当前工程。') from None
    return path


def validate_local_build(directory):
    """Return (writer, image, in-memory manifest) after read-only build checks.

    The report's application is a project-relative path to xiaozhi.bin.
    source_baseline_commit identifies the fixed upstream base, not the current
    edited source revision. No release manifest is generated or replaced here.
    """
    directory=checked_project_path(directory)
    if not directory.is_dir():raise ValueError('缺少本地构建目录。')
    report_path=checked_project_path(directory/'selfhealing-build-report.json')
    if not report_path.is_file():raise ValueError('缺少已验证的本地 build report 构建报告。')
    report=json.loads(report_path.read_text(encoding='utf-8'))
    if not isinstance(report,dict):raise ValueError('本地 build report 构建报告格式不符。')
    if (report.get('build_verified') is not True or report.get('hardware_access') is not False or
        report.get('chip')!='esp32s3' or report.get('application_address')!='0x200000'):
        raise ValueError('本地构建报告不是已验证的 ESP32-S3 指定应用。')
    application=report.get('application')
    parts=re.split(r'[/\\]',application) if isinstance(application,str) else []
    # 兼容 Windows 旧报告中的反斜杠，但拒绝绝对地址、驱动器和路径跳转。
    if not parts or ':' in application or any(part in ('','.','..') for part in parts):
        raise ValueError('本地 application path 路径格式不符。')
    image=checked_project_path(ROOT.joinpath(*parts))
    if image!=directory/'xiaozhi.bin' or not image.is_file():
        raise ValueError('本地 application path 必须精确指向构建目录中的 xiaozhi.bin。')
    data=image.read_bytes()
    if (type(report.get('bytes')) is not int or not 96<=len(data)<=0x400000 or
        len(data)!=report['bytes'] or not isinstance(report.get('sha256'),str) or
        not re.fullmatch('[0-9a-f]{64}',report['sha256']) or
        hashlib.sha256(data).hexdigest()!=report['sha256']):
        raise ValueError('本地应用大小或 SHA256 校验不符。')
    if data[0]!=0xe9 or int.from_bytes(data[12:14],'little')!=9:
        raise ValueError('本地镜像不是 ESP32-S3 应用。')
    # 复用构建器的只读校验函数，不执行构建、补丁、SDK 安装或串口操作。
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    import build_watcher as build
    baseline=build.metadata(build.ROOT)
    build.locked_template()
    if (baseline.get('idf_version')!='6.0.1' or
        report.get('sdk_commit')!=baseline['sdk_commit'] or
        report.get('source_baseline_commit')!=baseline['app_source_commit'] or
        report.get('configuration_template_sha256')!=build.CONFIG_TEMPLATE_SHA):
        raise ValueError('本地构建 SDK / source baseline / configuration 模板基线不符。')
    dependencies=checked_project_path(build.PROJECT/'dependencies.lock')
    if not dependencies.is_file() or build.digest(dependencies.read_bytes())!=baseline['dependencies_lock_sha256']:
        raise ValueError('本地构建 fixed dependencies 依赖锁基线不符。')
    config=checked_project_path(directory/'sdkconfig')
    if not config.is_file():raise ValueError('缺少本地隔离 configuration sdkconfig。')
    appended=build.select_board_config()
    # 板型追加配置也要与锁定模板一致，不能通过同时改报告和配置绕过基线。
    build.validate_config(build.CONFIG_TEMPLATE,appended)
    verified_config=build.validate_config(config,appended)
    if report.get('configuration')!=verified_config:
        raise ValueError('构建报告 configuration 与实际 sdkconfig 不符。')
    patches=report.get('managed_patches');known={row['path'] for row in baseline['sscma_files']}
    if (not isinstance(patches,dict) or type(patches.get('verified_files')) is not int or
        patches['verified_files']!=len(known) or not isinstance(patches.get('changed'),list) or
        any(not isinstance(path,str) or path not in known for path in patches['changed']) or
        len(patches['changed'])!=len(set(patches['changed']))):
        raise ValueError('本地构建摄像头组件补丁校验记录不符。')
    partition=checked_project_path(directory/'partition_table/partition-table.bin')
    if not partition.is_file():raise ValueError('缺少实际构建 partition table 分区文件。')
    verified_partition=build.validate_partition(partition)
    if (verified_partition!={'name':'ota_0','address':'0x200000','bytes':0x400000} or
        report.get('partition')!=verified_partition):
        raise ValueError('本地构建报告 partition 与实际 0x200000 分区不符。')
    # 擦除态的临时 OTA 数据只用于本地布局检查；真烧录仍读取设备自己的 OTA 选择。
    validate_device_layout(partition.read_bytes(),b'\xff'*0x2000,len(data))
    release=release_module()
    manifest={'build_verified':True,'app':'xiaozhi.bin','bytes':len(data),
              'sha256':report['sha256'],'chip':'esp32s3','address':'0x200000',
              'device_mac':release.TARGET_MAC}
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
    source=parser.add_mutually_exclusive_group()
    source.add_argument('--release-dir',type=Path,help='Downloaded immutable release bundle root; contains release-manifest.json and 上一版回滚/')
    source.add_argument('--build-dir',type=Path,help='Explicit local build directory inside this project; contains selfhealing-build-report.json, sdkconfig, partition table and xiaozhi.bin')
    args=parser.parse_args()
    if args.build_dir is not None and args.rollback:
        parser.error('--build-dir cannot be combined with --rollback; rollback only accepts the preserved release')
    root=args.release_dir if args.release_dir is not None else RELEASE
    if args.rollback:root=root/'上一版回滚'
    try:
        if args.build_dir is not None:release,image,manifest=validate_local_build(args.build_dir)
        else:release,image,manifest=validate_release(root,args.rollback)
        data=image.read_bytes()
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

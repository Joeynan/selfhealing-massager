#!/usr/bin/env python3
"""Build the pinned Watcher application; no serial ports or hardware are accessed."""
from pathlib import Path
import argparse, hashlib, json, os, shutil, struct, subprocess, sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from watcher_build_support import apply_managed_patches, apply_sdk_path_patch, digest, metadata, validate_sdk

ROOT = Path(__file__).resolve().parent.parent
PROJECT = ROOT / 'work/xiaozhi-esp32'
SDK = ROOT / 'work/esp-idf'
TOOLS = ROOT / 'work/idf-tools'
CONFIG_TEMPLATE = ROOT / 'tools/config/watcher-wheel-v9.sdkconfig'
CONFIG_TEMPLATE_SHA = '18193edabd61d6135e729872840903d666fa8b57677583e6a09c952efe0abf63'

def locked_template(path=CONFIG_TEMPLATE):
    data=path.read_bytes()
    if digest(data)!=CONFIG_TEMPLATE_SHA:raise ValueError('Locked Watcher baseline configuration checksum mismatch')
    return data

def select_board_config():
    board = json.loads((PROJECT/'main/boards/sensecap-watcher-gesture/config.json').read_text(encoding='utf-8'))
    if board.get('target') != 'esp32s3': raise ValueError('Watcher target must be esp32s3')
    configs = [b for b in board.get('builds',[]) if b.get('name')=='sensecap-watcher-wheel-v9']
    if len(configs)!=1: raise ValueError('Missing or ambiguous verified v9 Watcher configuration')
    values = configs[0].get('sdkconfig_append')
    if not values: raise ValueError('Missing verified Watcher build defaults')
    return values

def validate_config(path, appended):
    values = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if line.startswith('CONFIG_') and '=' in line:
            key,value=line.split('=',1); values[key]=value
        elif line.startswith('# CONFIG_') and line.endswith(' is not set'):
            values[line[2:-11]]='n'
    expected = {'CONFIG_IDF_TARGET':'"esp32s3"',
                'CONFIG_ESPTOOLPY_FLASHSIZE_32MB':'y',
                'CONFIG_PARTITION_TABLE_CUSTOM':'y',
                'CONFIG_PARTITION_TABLE_CUSTOM_FILENAME':'"partitions/watcher-gesture.csv"',
                'CONFIG_BOARD_TYPE_SENSECAP_WATCHER_GESTURE':'y',
                'CONFIG_WATCHER_GESTURE_PIPELINE':'y',
                'CONFIG_FREERTOS_HZ':'1000','CONFIG_LANGUAGE_ZH_CN':'y'}
    expected.update(line.split('=',1) for line in appended)
    mismatches={k:{'expected':v,'actual':values.get(k)} for k,v in expected.items() if values.get(k)!=v}
    if mismatches: raise ValueError('Watcher configuration mismatch: '+json.dumps(mismatches))
    return expected

def validate_partition(path):
    data=path.read_bytes()
    for offset in range(0,len(data)-31,32):
        magic,typ,sub,addr,size,label,flags=struct.unpack('<HBBII16sI',data[offset:offset+32])
        if magic==0x50aa and typ==0 and sub==0x10:
            if addr!=0x200000 or size!=0x400000: raise ValueError('Watcher ota_0 partition mismatch')
            return {'name':label.split(b'\0')[0].decode(),'address':'0x200000','bytes':size}
    raise ValueError('Watcher ota_0 application partition not found')

def select_build_runtime(root=ROOT, environ=None, platform=None, sdk_override=None):
    env=dict(os.environ if environ is None else environ);platform=platform or sys.platform
    bundled_sdk=root/'work/esp-idf';bundled_tools=root/'work/idf-tools'
    bundled=sdk_override is None and (bundled_sdk/'tools/idf.py').is_file() and (bundled_tools/'python-env/bin/python').is_file() and platform!='win32'
    if bundled:
        sdk=bundled_sdk;python=bundled_tools/'python-env/bin/python';ninja=bundled_tools/'bin/ninja'
        env.update(IDF_TOOLS_PATH=str(bundled_tools),IDF_PYTHON_ENV_PATH=str(bundled_tools/'python-env'),ESP_ROM_ELF_DIR=str(bundled_tools/'rom'))
        env['PATH']=os.pathsep.join([str(python.parent),str(ninja.parent),str(bundled_tools/'toolchain/xtensa-esp-elf/bin'),env.get('PATH','')])
    else:
        path=sdk_override or env.get('IDF_PATH')
        if not path:raise ValueError('请先安装并激活固定 ESP-IDF 6.0.1（export.sh / export.ps1），或使用 --idf-path。')
        sdk=Path(path)
        prefix=env.get('IDF_PYTHON_ENV_PATH')
        if not prefix:raise ValueError('ESP-IDF Python 环境未激活；先运行 export.sh / export.ps1。')
        python=Path(prefix)/('Scripts/python.exe' if platform=='win32' else 'bin/python')
        if platform=='win32':
            ninja=next((Path(directory)/'ninja.exe' for directory in env.get('PATH','').split(os.pathsep) if (Path(directory)/'ninja.exe').is_file()),None)
        else:
            found=shutil.which('ninja',path=env.get('PATH',''));ninja=Path(found) if found else None
        if not python.is_file() or ninja is None:raise ValueError('ESP-IDF Python / Ninja 未就绪；安装 SDK 工具后重新激活环境。')
    env.update(IDF_PATH=str(sdk),IDF_COMPONENT_MANAGER='1',ESP_IDF_VERSION='6.0.1',PYTHONUTF8='1',XDG_CACHE_HOME=str(root/'work/idf-cache'))
    return {'sdk':sdk,'python':python,'ninja':ninja,'environment':env,'bundled':bundled}

def build_environment():
    return select_build_runtime()['environment']

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--configure-only', action='store_true')
    parser.add_argument('--clean', action='store_true', help='Regenerate this project build cache before configuring')
    parser.add_argument('--jobs', type=int, default=6)
    parser.add_argument('--idf-path',type=Path,help='Activated official ESP-IDF 6.0.1 checkout; its exact commit is checked')
    args = parser.parse_args()
    build = PROJECT / 'build'
    defaults = build / 'xiaozhi-build.sdkconfig.defaults'
    runtime=select_build_runtime(sdk_override=args.idf_path)
    python=runtime['python'];sdk=runtime['sdk'];ninja=runtime['ninja'];environment=runtime['environment']
    commands = [[str(python), str(sdk/'tools/idf.py'), '-B', str(build),
                 '-DIDF_TARGET=esp32s3',
                 '-DSDKCONFIG='+str(build/'sdkconfig'),
                 '-DSDKCONFIG_DEFAULTS=sdkconfig.defaults;'+str(defaults),
                 '-DCMAKE_PROJECT_INCLUDE='+str(ROOT/'tools/watcher_build_paths.cmake'),
                 '-DBOARD_NAME=sensecap-watcher-wheel-v9', 'reconfigure']]
    if not args.configure_only:
        commands.extend([[str(ninja), '-j'+str(args.jobs), '-C', str(build), 'lang_header'],
                         [str(ninja), '-j'+str(args.jobs), '-C', str(build), 'app']])
    if args.dry_run:
        print(json.dumps({'project':str(PROJECT),'commands':commands,'clean_build_cache':args.clean,'hardware_access':False},ensure_ascii=False,indent=2))
        return 0
    if not 1<=args.jobs<=16: raise ValueError('jobs must be between 1 and 16')
    baseline=metadata(ROOT);validate_sdk(sdk,ROOT)
    lock=PROJECT/'dependencies.lock'
    if digest(lock.read_bytes())!=baseline['dependencies_lock_sha256']:raise ValueError('Fixed dependencies.lock baseline checksum mismatch')
    apply_sdk_path_patch(sdk,ROOT)
    appended=select_board_config()
    template=locked_template()
    if args.clean and build.exists():
        if build.is_symlink(): raise ValueError('Refusing to remove a symlinked build cache')
        shutil.rmtree(build)
    build.mkdir(parents=True,exist_ok=True)
    # Root sdkconfig can belong to another board; never reuse it. Seed the isolated
    # build configuration from the verified v9 baseline only on initial/clean build.
    config_path=build/'sdkconfig'
    if not config_path.exists():config_path.write_bytes(template)
    defaults.write_text('\n'.join(appended)+'\n',encoding='utf-8')
    subprocess.run(commands[0],cwd=PROJECT,env=environment,check=True)
    if digest(lock.read_bytes())!=baseline['dependencies_lock_sha256']:raise ValueError('Component manager changed fixed dependencies.lock; stopped before application build')
    patch_report=apply_managed_patches(PROJECT,ROOT)
    verified_config=validate_config(config_path,appended)
    for cmd in commands[1:]:subprocess.run(cmd,cwd=PROJECT,env=environment,check=True)
    if not args.configure_only:
        image=build/'xiaozhi.bin'; data=image.read_bytes()
        if not (data[0]==0xe9 and int.from_bytes(data[12:14],'little')==9 and len(data)<=0x400000):
            raise ValueError('Invalid ESP32-S3 application or application partition overflow')
        report={'build_verified':True,'application':str(image.relative_to(ROOT)),
                'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),
                'chip':'esp32s3','application_address':'0x200000','hardware_access':False,
                'configuration':verified_config,'configuration_template_sha256':CONFIG_TEMPLATE_SHA,
                'partition':validate_partition(build/'partition_table/partition-table.bin'),
                'sdk_commit':baseline['sdk_commit'],'source_baseline_commit':baseline['app_source_commit'],
                'managed_patches':patch_report,
                'note':'Rebuilt application is not automatically substituted for the preserved v9 flash package.'}
        (build/'selfhealing-build-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('Build verified: '+str(len(data))+' bytes; no hardware accessed.')
    return 0

if __name__=='__main__': sys.exit(main())

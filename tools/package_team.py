#!/usr/bin/env python3
"""Export a source allowlist and unchanged release assets; never access devices."""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
CONSOLE = 'outputs/Watcher控制台'
ROOT_FILES = {'README.md', 'AGENTS.md', '.gitignore', '.gitattributes', 'source-manifest.json'}
DOC_FILES = {'使用指南.md', 'GitHub上传指南.md', '第三方来源与许可.md', '验收清单.md'}
LOCAL_TOOLS = {'verify_project.py', 'setup_environments.py', 'install_arduino_tools.py', 'restore_vision_tools.py'}
PRESERVED_APPS = {
    '': ('watcher-controller-v9-wheel-face.bin', 2879808, 'fb4fe0e39777e3e5d0594b7662ad559fc3a42af490dd71064be9d42bea4cbece'),
    '上一版回滚/': ('watcher-controller-v8-continuous-output.bin', 3013408, '319edfdc630860f65c453ab4eeaca90a378a59741e5ba938f1e368db7c3cbc9e'),
}
SECRET_LITERAL = re.compile(r'(?:WIFI_PASSWORD|WIFI_SSID|const\s+char\s*\*\s*(?:password|ssid))\s*(?:\[\s*\])?\s*=\s*"([^"\n]*)"|#define\s+WIFI_(?:PASSWORD|SSID)\s+"([^"\n]*)"')

def network_literals(text):
    return [left or right for left, right in SECRET_LITERAL.findall(text)]


def eligible(relative):
    parts = PurePosixPath(relative.as_posix()).parts
    if not parts or '..' in parts or relative.is_absolute(): return False
    name = parts[-1]
    # 系统目录元数据可能包含本机路径及文件名，不属于可发布源码。
    if name in {'.DS_Store', 'Thumbs.db', 'desktop.ini'} or name.startswith('._'): return False
    if any(part in {'__pycache__', '.git', '.venv', '.cache', 'managed_components', 'build'} for part in parts): return False
    if name.endswith(('.pyc', '.log', '.bin', '.img', '.zip', '.elf', '.task', '.map')): return False
    # Unit-test credentials are synthetic and required by the black-board stubs.
    if parts == ('outputs', 'Watcher控制台', 'tests', 'node_stubs', 'wifi_settings.h'): return True
    if name in {'wifi_settings.h', '.env', 'settings.json', 'sdkconfig', 'sdkconfig.old'}: return False
    if len(parts) == 1:
        return name in ROOT_FILES or name.endswith(('.command', '.ps1'))
    if parts[0] == 'docs':
        return len(parts) == 2 and name in DOC_FILES or parts[1:2] == ('交付验证',) and name.endswith(('.json', '.md'))
    if parts[0] == '.github': return parts[1:2] == ('workflows',) and name == 'team-validation.yml'
    if parts[0] == 'releases': return len(parts) == 2 and name == 'release-index.json'
    if parts[0] == 'tools':
        if len(parts) == 2: return name not in LOCAL_TOOLS and name.endswith(('.py', '.cmake'))
        if parts[1] == 'tests': return name != 'test_verify_runtime_logs.py' and name.endswith('.py')
        if parts[1] in {'config', 'patches'}: return name.endswith(('.json', '.patch', '.sdkconfig'))
        return False
    if parts[:2] == ('work', 'requirements'): return name.endswith('.lock')
    if parts[:2] == ('work', 'xiaozhi-esp32'):
        if parts[2:3] in (('.github',), ('docker',)): return False
        if name == 'lang_config.h' or name.startswith('mmap_generate_'): return False
        return True
    if parts[:2] != ('outputs', 'Watcher控制台'): return False
    tail = parts[2:]
    if len(tail) == 1:
        return name.endswith(('.py', '.js', '.css', '.html', '.command', '.json', '.lock')) or name == '运行说明.md'
    if tail[0] == 'camera':
        return len(tail) == 2 and name.endswith(('.py', '.json', '.txt'))
    if tail[0] == 'tests': return name.endswith(('.py', '.cpp', '.cjs', '.h', '.sh', '.json'))
    if tail[:2] == ('firmware', 'esp8266'): return name.endswith(('.ino', '.h', '.example.h', '.txt'))
    if tail[:2] == ('firmware', 'watcher-service'):
        return name.endswith(('.h', '.cc', '.c', '.json', '.patch', '.txt'))
    if tail[:3] == ('firmware', 'watcher-vision', 'src'): return name.endswith(('.h', '.cc'))
    if tail[0] == 'WiFi摄像头版': return len(tail) == 2 and name == 'prepare_flash.py'
    if tail[0] == '滚轮表情版':
        return tail[1:] in (('flash_release.py',), ('release-manifest.json',),
                            ('tests', 'test_flash_release.py'), ('上一版回滚', 'release-manifest.json'))
    return False


def sha(data): return hashlib.sha256(data).hexdigest()


def private_values(root):
    values = set()
    # Read only private build headers. Do not collect credentials from test stubs.
    for parent in (root / 'outputs', root / 'work'):
        if not parent.exists(): continue
        for path in parent.rglob('wifi_settings.h'):
            if path.is_symlink() or any(p in ('tests', 'node_stubs', 'stubs', 'managed_components', 'build', 'venv') or p.endswith('-tests') for p in path.parts): continue
            try:
                values.update(v for v in network_literals(path.read_text(encoding='utf-8'))
                              if len(v) >= 8 and not v.startswith(('YOUR_', 'TEST_', 'test-')))
            except (OSError, UnicodeError): pass
    return sorted(values)


def scan_sensitive(relative, data, values=()):
    issues = []
    if any(value.encode() in data for value in values if value):
        issues.append({'path': str(relative), 'reason': 'known_local_credential'})
    if re.search(rb'-----BEGIN (?P<kind>(?:RSA |EC |OPENSSH )?PRIVATE KEY)-----[\r\n]+[A-Za-z0-9+/=\r\n]{64,}-----END (?P=kind)-----|\bgh[pousr]_[A-Za-z0-9]{30,}', data):
        issues.append({'path': str(relative), 'reason': 'private_key_or_token'})
    path = PurePosixPath(str(relative))
    if 'tests' not in path.parts and 'example' not in path.name:
        text = data.decode('utf-8', errors='ignore')
        if any(v and not v.startswith(('YOUR_', 'TEST_')) for v in network_literals(text)):
            issues.append({'path': str(relative), 'reason': 'literal_network_credential'})
    return issues


def selected_files(root):
    root = Path(root)
    # Do not descend into the 5+ GB local SDK/tool/cache trees.
    for directory, folders, names in os.walk(root, followlinks=False):
        base = Path(directory)
        relative = base.relative_to(root)
        folders[:] = [name for name in folders if name not in {'__pycache__', '.git', 'build', 'managed_components'}]
        if relative == Path('work'):
            folders[:] = [name for name in folders if name in {'xiaozhi-esp32', 'requirements'}]
        elif relative == Path('outputs'):
            folders[:] = [name for name in folders if name == 'Watcher控制台']
        elif relative == Path(CONSOLE):
            folders[:] = [name for name in folders if name in {'camera', 'tests', 'firmware', '滚轮表情版', 'WiFi摄像头版'}]
        elif relative == Path(CONSOLE) / 'firmware':
            folders[:] = [name for name in folders if name in {'esp8266', 'watcher-service', 'watcher-vision'}]
        elif relative == Path('docs'):
            folders[:] = [name for name in folders if name == '交付验证']
        for name in sorted(names):
            path = base / name
            if eligible(path.relative_to(root)): yield path
        for name in list(folders):
            path = base / name
            if path.is_symlink():
                # Surface an eligible directory link instead of following it.
                if eligible(path.relative_to(root) / 'source.cc'): yield path
                folders.remove(name)


def audit(root=ROOT):
    root = Path(root).resolve()
    values = private_values(root)
    files = {}; issues = []
    for path in sorted(selected_files(root)):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            issues.append({'path': relative, 'reason': 'symlink_or_escape'}); continue
        data = path.read_bytes()
        files[relative] = {'bytes': len(data), 'sha256': sha(data)}
        issues.extend(scan_sensitive(relative, data, values))
    return {'ok': not issues, 'files': files, 'file_count': len(files),
            'bytes': sum(item['bytes'] for item in files.values()), 'issues': issues,
            'hardware_access': False}


def audit_staged(root=ROOT):
    """Inspect every blob in Git's index, including force-added ignored files."""
    root = Path(root).resolve()
    def git(*arguments):
        result = subprocess.run(['git', '-C', str(root), *arguments], stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, check=False)
        if result.returncode:
            raise ValueError('Git index unavailable; initialize and stage the clean export first')
        return result.stdout
    top = Path(os.fsdecode(git('rev-parse', '--show-toplevel').strip())).resolve()
    if top != root:
        raise ValueError('Git repository root must be this project directory')
    values = private_values(root); files = {}; issues = []
    for entry in git('ls-files', '--stage', '-z').split(b'\0'):
        if not entry: continue
        metadata, name = entry.split(b'\t', 1)
        mode, object_id, stage = metadata.split()
        relative = os.fsdecode(name)
        if not eligible(Path(relative)):
            issues.append({'path': relative, 'reason': 'outside_allowlist'}); continue
        if mode not in (b'100644', b'100755') or stage != b'0':
            issues.append({'path': relative, 'reason': 'unsupported_index_mode'}); continue
        data = git('cat-file', 'blob', object_id.decode('ascii'))
        files[relative] = {'bytes': len(data), 'sha256': sha(data)}
        issues.extend(scan_sensitive(relative, data, values))
    return {'ok': not issues, 'files': files, 'file_count': len(files),
            'bytes': sum(item['bytes'] for item in files.values()), 'issues': issues,
            'scope': 'git_index', 'hardware_access': False}


def destination(root, target):
    root, target = Path(root).resolve(), Path(target).absolute()
    if target.is_symlink(): raise ValueError('Destination must not be a symlink')
    target = target.resolve()
    if target == root or root.is_relative_to(target): raise ValueError('Destination contains source tree')
    if target.is_relative_to(root):
        relative = target.relative_to(root)
        if not relative.parts[:2] == ('work', 'team-delivery'):
            raise ValueError('Inside the project only work/team-delivery is an export destination')
    if target.exists() and (not target.is_dir() or any(target.iterdir())):
        raise ValueError('Destination must be new or empty; existing files will not be overwritten')
    return target


def export_source(root, target):
    root = Path(root).resolve(); target = destination(root, target)
    result = audit(root)
    if not result['ok']: raise ValueError('Audit rejected candidate files: ' + json.dumps(result['issues'], ensure_ascii=False))
    target.mkdir(parents=True, exist_ok=True)
    for relative, expected in result['files'].items():
        if relative == 'source-manifest.json': continue
        source = root / relative
        data = source.read_bytes()
        if len(data) != expected['bytes'] or sha(data) != expected['sha256']:
            raise ValueError('Source changed during export: ' + relative)
        copy = target / relative; copy.parent.mkdir(parents=True, exist_ok=True)
        copy.write_bytes(data); shutil.copymode(source, copy)
    result['files'].pop('source-manifest.json', None)
    result['file_count'] = len(result['files'])
    result['bytes'] = sum(item['bytes'] for item in result['files'].values())
    (target / 'source-manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return result


def release_assets(root, target):
    root = Path(root).resolve(); target = destination(root, target)
    release = root / CONSOLE / '滚轮表情版'
    values = private_values(root); entries = {}; issues = []
    versions = []
    for prefix in ('', '上一版回滚/'):
        folder = release / prefix
        mpath = folder / 'release-manifest.json'; manifest_bytes = mpath.read_bytes(); m = json.loads(manifest_bytes)
        image = folder / m['app']
        if image.is_symlink() or image.resolve().parent != folder.resolve(): raise ValueError('Invalid release image path')
        data = image.read_bytes()
        if (m['app'], len(data), sha(data)) != PRESERVED_APPS[prefix]:
            raise ValueError('Release differs from preserved v9/v8 image: ' + prefix + m['app'])
        if m.get('chip') != 'esp32s3' or m.get('address') != '0x200000' or m.get('device_mac') != '10:b4:1d:e6:00:9c':
            raise ValueError('Release device, chip or address mismatch')
        if m.get('build_verified') is not True or len(data) != m['bytes'] or sha(data) != m['sha256']:
            raise ValueError('Release checksum mismatch: ' + prefix + m['app'])
        if not 96 <= len(data) <= 0x400000 or data[0] != 0xe9 or int.from_bytes(data[12:14], 'little') != 9:
            raise ValueError('Release is not a bounded ESP32-S3 application')
        for name, content in ((prefix + 'release-manifest.json', manifest_bytes), (prefix + m['app'], data)):
            issues.extend(scan_sensitive(name, content, values)); entries[name] = content
        versions.append({'version': m['version'], 'app': prefix + m['app'], 'bytes': len(data), 'sha256': sha(data)})
    if issues: raise ValueError('Release credential audit failed: ' + json.dumps(issues, ensure_ascii=False))
    target.mkdir(parents=True, exist_ok=True)
    archive = target / 'selfhealing-watcher-v9.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as output:
        for name, content in sorted(entries.items()):
            # Deterministic ZIP: original contents, stable metadata.
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 11, 0, 0, 0)); info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16; output.writestr(info, content)
    index = {'schema_version': 1, 'asset': archive.name, 'asset_bytes': archive.stat().st_size,
             'asset_sha256': sha(archive.read_bytes()), 'download_url': None,
             'publication_state': 'prepared_not_uploaded', 'applications': versions,
             'device_mac': '10:b4:1d:e6:00:9c', 'application_address': '0x200000',
             'esptool_version': '5.4.0', 'black_firmware': 'esp8266-servo-controller-v7 (build locally with private Wi-Fi)',
             'vision': {'required_preinstalled': True, 'bytes': 585728,
                        'sha256': 'af4241e1f085b337659d8eb5c42f32ebba7e240899fb697bfde02f594e5f4b4a',
                        'note': 'Existing WE2 Wi-Fi camera firmware; no visual firmware update in this handoff'},
             'hardware_access': False}
    (target / 'release-index.json').write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return index


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['audit', 'export', 'releases'])
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--destination', type=Path)
    parser.add_argument('--staged', action='store_true', help='For audit: inspect Git index blobs')
    args = parser.parse_args(argv)
    if args.staged and args.action != 'audit': parser.error('--staged is only valid for audit')
    if args.action != 'audit' and args.destination is None: parser.error('--destination is required')
    try:
        if args.action == 'audit':
            result = audit_staged(args.root) if args.staged else audit(args.root)
            print(json.dumps({key: value for key, value in result.items() if key != 'files'}, ensure_ascii=False, indent=2))
            return 0 if result['ok'] else 1
        result = export_source(args.root, args.destination) if args.action == 'export' else release_assets(args.root, args.destination)
        print(json.dumps({key: value for key, value in result.items() if key != 'files'}, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError) as error:
        print('Packaging stopped: ' + str(error), file=sys.stderr); return 1


if __name__ == '__main__': raise SystemExit(main())

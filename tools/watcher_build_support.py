"""Exact baseline checks and deterministic patches, without git/patch executables."""
import hashlib, json, re, subprocess
from pathlib import Path

def normalized(data):
    return data.replace(b'\r\n',b'\n')

def digest(data):
    return hashlib.sha256(normalized(data)).hexdigest()

def metadata(root):
    return json.loads((root/'tools/config/build-baseline.json').read_text(encoding='utf-8'))

def parse_unified_patch(text):
    files={};current=None;hunk=None
    for line in text.splitlines(keepends=True):
        if line.startswith('+++ b/'):
            current=line[6:].strip();files[current]=[];hunk=None
        elif line.startswith('@@ '):
            match=re.match(r'@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@',line)
            if not match or current is None:raise ValueError('Invalid patch hunk')
            hunk={'old':int(match[1]),'new':int(match[3]),'lines':[]};files[current].append(hunk)
        elif hunk is not None and line[:1] in (' ','+','-') and not line.startswith('--- a/'):
            hunk['lines'].append(line)
    return files

def apply_file_diff(source,hunks,reverse=False):
    original=source.splitlines(keepends=True);output=[];position=0
    for hunk in hunks:
        start=hunk['new' if reverse else 'old']-1
        before=[];after=[]
        for line in hunk['lines']:
            flag=line[0];content=line[1:]
            if flag==' ' or flag==('+' if reverse else '-'):before.append(content)
            if flag==' ' or flag==('-' if reverse else '+'):after.append(content)
        if start<position or original[start:start+len(before)]!=before:
            raise ValueError('Exact baseline patch context mismatch')
        output.extend(original[position:start]);output.extend(after);position=start+len(before)
    output.extend(original[position:]);return ''.join(output)

def checked_patches(base,files,patch):
    changes=[]
    # Check all sources before changing any file, so unknown baselines fail closed.
    for item in files:
        path=base/item['path']
        if not path.is_file() or path.is_symlink():raise ValueError('Missing/unknown baseline source: '+item['path'])
        actual=digest(path.read_bytes())
        if actual==item['patched_sha256']:continue
        if actual!=item['baseline_sha256']:raise ValueError('未知 unknown source baseline: '+item['path'])
        source=normalized(path.read_bytes()).decode('utf-8')
        updated=apply_file_diff(source,patch[item['path']]).encode()
        if digest(updated)!=item['patched_sha256']:raise ValueError('Verified patched checksum mismatch: '+item['path'])
        changes.append((path,updated,item['path']))
    for path,updated,_ in changes:path.write_bytes(updated)
    return {'changed':[name for _,_,name in changes],'verified_files':len(files)}

def apply_managed_patches(project,root):
    manifest=metadata(root);patch=root/'tools/patches/sscma-client-hardening.patch'
    if digest(patch.read_bytes())!=manifest['sscma_patch_sha256']:raise ValueError('Locked camera hardening patch checksum mismatch')
    return checked_patches(project,manifest['sscma_files'],parse_unified_patch(patch.read_text(encoding='utf-8')))

def validate_sdk(sdk,root):
    spec=metadata(root)
    for name,expected in spec['sdk_files'].items():
        path=sdk/name
        if not path.is_file() or digest(path.read_bytes())!=expected:
            raise ValueError('ESP-IDF 6.0.1 baseline 基线不符：'+name)
    if (sdk/'.git').exists():
        actual=subprocess.check_output(['git','-C',str(sdk),'rev-parse','HEAD'],text=True).strip()
        if actual!=spec['sdk_commit']:raise ValueError('ESP-IDF SDK commit 与固定基线不符。')
    return spec['sdk_commit']

def apply_sdk_path_patch(sdk,root):
    manifest=metadata(root);patch=root/'tools/patches/idf-6.0.1-utf8-paths.patch'
    if digest(patch.read_bytes())!=manifest['sdk_path_patch_sha256']:raise ValueError('Locked UTF-8 patch checksum mismatch')
    return checked_patches(sdk,[manifest['sdk_path_file']],parse_unified_patch(patch.read_text(encoding='utf-8')))

#!/usr/bin/env python3
"""Shared build/flash entry for shell and PowerShell; never bypass guards."""
import argparse, os, subprocess, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from runtime_support import flash_python
from build_watcher import select_build_runtime

ROOT=Path(__file__).resolve().parent.parent

def entry_python(action,args,root=ROOT):
    if action=='build':
        override=None
        for index,value in enumerate(args):
            if value=='--idf-path' and index+1<len(args):override=Path(args[index+1])
            elif value.startswith('--idf-path='):override=Path(value.split('=',1)[1])
        return select_build_runtime(root,sdk_override=override)['python']
    if '--dry-run' in args:return Path(sys.executable)
    dedicated=flash_python(root)
    if dedicated.is_file():return dedicated
    bundled=root/'work/idf-tools/python-env/bin/python'
    if sys.platform!='win32' and bundled.is_file():return bundled
    raise RuntimeError('请先用 Python 3.12 运行 tools/runtime_entry.py install --flash-only，再执行烧录入口。')

def command_for(action,args,root=ROOT):
    python=entry_python(action,args,root)
    if action=='build':return [str(python),str(root/'tools/build_watcher.py'),*args]
    return [str(python),str(root/'tools/flash_watcher.py'),*(['--rollback'] if action=='rollback' else []),*args]

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['build','flash','rollback'])
    known,remaining=parser.parse_known_args()
    try:return subprocess.call(command_for(known.action,remaining),env={**os.environ,'PYTHONUTF8':'1'})
    except (ValueError,RuntimeError) as exc:
        print('已停止：'+str(exc),file=sys.stderr);return 1

if __name__=='__main__':raise SystemExit(main())

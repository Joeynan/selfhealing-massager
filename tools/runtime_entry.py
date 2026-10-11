#!/usr/bin/env python3
"""Common Mac / Windows installation and launch entry; no device probing here."""
from pathlib import Path
import os
import sys
from runtime_support import base_python, python_inside, venv_python

ROOT = Path(__file__).resolve().parents[1]


def start_arguments(arguments):
    if not any(value in ('--offline', '--wifi-camera', '--mac-camera') for value in arguments):
        return ['--wifi-camera'] + list(arguments)
    return list(arguments)


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments or arguments[0] not in ('start', 'install'):
        raise SystemExit('Usage: runtime_entry.py start|install [options]')
    operation = arguments.pop(0)
    if operation == 'start':
        runtime = venv_python(ROOT/'work/watcher-control-runtime/venv')
        python = runtime if runtime.is_file() else base_python(ROOT)
        script = ROOT/'outputs/Watcher控制台/launch.py'
        arguments = start_arguments(arguments)
    else:
        if '--rebuild' in arguments and sys.platform == 'win32' and python_inside(
                sys.executable, (ROOT/'work/watcher-control-runtime/venv', ROOT/'work/watcher-control-runtime/flash-venv')):
            raise SystemExit('Windows rebuild: close this venv and use system Python 3.12 or the root PowerShell rebuild entry.')
        python = base_python(ROOT)
        script = ROOT/'outputs/Watcher控制台/install_runtime.py'
    for name in ('PYTHONHOME', 'PYTHONPATH'):
        os.environ.pop(name, None)
    os.environ['PYTHONUTF8'] = '1'
    os.chdir(ROOT)
    os.execv(str(python), [str(python), str(script)] + arguments)


if __name__ == '__main__': main()

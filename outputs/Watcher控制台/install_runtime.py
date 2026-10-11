"""Install portable Python 3.12 camera / flash environments inside the project."""
import argparse
import json
import os
import shutil
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parents[1]
WORK = PROJECT_ROOT / 'work/watcher-control-runtime'
sys.path.insert(0, str(PROJECT_ROOT / 'tools'))
from runtime_support import base_python, ensure_model, load_settings, python_inside, venv_python


def parse_options(argv=None):
    parser = argparse.ArgumentParser(description='安装队友本地运行环境；不连接设备')
    parser.add_argument('--python', help='指定 Python 3.12 可执行文件')
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--flash-only', action='store_true', help='仅安装 esptool 烧录环境')
    modes.add_argument('--with-flash', action='store_true', help='同时安装识别与烧录环境')
    parser.add_argument('--offline', action='store_true', help='仅使用本地 wheels 与已下载模型')
    parser.add_argument('--wheel-dir', type=Path, help='额外的本地 wheel 目录（须对应当前系统）')
    parser.add_argument('--check', action='store_true', help='只检查已安装版本与模型，不安装或下载')
    parser.add_argument('--rebuild', action='store_true', help='只重建运行与烧录环境，保留私人配置和记录')
    options = parser.parse_args(argv)
    if options.check and options.rebuild:
        parser.error('--check 与 --rebuild 不能同时使用')
    return options


def prepare_venv(runtime, rebuild=False):
    if runtime.is_symlink():
        raise RuntimeError("拒绝操作链接的虚拟环境。")
    if rebuild and runtime.exists():
        shutil.rmtree(runtime)


def check_environment(python, requirements, environment):
    script = ('from importlib.metadata import version; from pathlib import Path; import sys; '
              'items=[x.strip() for x in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines() if x.strip() and not x.startswith("#")]; '
              'bad=[x for x in items if version(x.split("==")[0]) != x.split("==")[1]]; '
              'raise SystemExit("依赖版本不一致: "+", ".join(bad) if bad else 0)')
    subprocess.run([str(python), '-I', '-c', script, str(requirements)], check=True,
                   cwd=str(PROJECT_ROOT), env=environment)


def main(argv=None):
    options = parse_options(argv)
    try:
        rebuild_targets = (WORK/'venv', WORK/'flash-venv') if options.rebuild else ()
        python = (base_python(PROJECT_ROOT, options.python, exclude_dirs=rebuild_targets)
                  if options.rebuild else base_python(PROJECT_ROOT, options.python))
        environment = os.environ.copy()
        for variable in ('PYTHONHOME', 'PYTHONPATH'):
            environment.pop(variable, None)
        environment.update(PIP_CACHE_DIR=str(WORK / 'cache/pip'), PIP_DISABLE_PIP_VERSION_CHECK='1', PYTHONUTF8='1')
        if options.rebuild and python_inside(sys.executable, rebuild_targets):
            if sys.platform == 'win32':
                # Windows exec keeps its parent EXE locked; stop before any deletion.
                raise RuntimeError('Windows 请关闭当前虚拟环境，用系统 Python 3.12 或工程根目录的重建运行环境.ps1 重建。')
            # POSIX replaces the running interpreter before deleting its old venv.
            arguments = list(sys.argv[1:] if argv is None else argv)
            os.execve(str(python), [str(python), str(Path(__file__).resolve())] + arguments, environment)
        installations = [] if options.flash_only else [('venv', ROOT/'requirements-runtime.lock')]
        if options.flash_only or options.with_flash:
            installations.append(('flash-venv', ROOT/'requirements-flash.lock'))
        for name, requirements in installations:
            runtime = WORK/name
            interpreter = venv_python(runtime)
            if options.check:
                if not interpreter.is_file():
                    raise RuntimeError(f'缺少 {name} 环境，请先运行安装入口。')
                check_environment(interpreter, requirements, environment)
                continue
            WORK.mkdir(parents=True, exist_ok=True)
            prepare_venv(runtime, options.rebuild)
            subprocess.run([str(python), '-m', 'venv', str(runtime)], check=True,
                           cwd=str(PROJECT_ROOT), env=environment)
            pip_args = [str(interpreter), '-m', 'pip', 'install']
            wheels = options.wheel_dir
            if wheels is None and sys.platform != 'win32' and (PROJECT_ROOT/'work/wheels').is_dir():
                wheels = PROJECT_ROOT/'work/wheels'
            if wheels is not None:
                if not wheels.is_dir():
                    raise RuntimeError('指定的本地 wheel 目录不存在。')
                pip_args += ['--find-links', str(wheels)]
            command = pip_args + ['-r', str(requirements)]
            if options.offline or wheels is not None:
                try:
                    subprocess.run(command + ['--no-index'], check=True, cwd=str(PROJECT_ROOT), env=environment)
                except subprocess.CalledProcessError:
                    if options.offline:
                        raise
                    print('本地依赖不完整，按锁定版本补齐缺失项。')
                    subprocess.run(command, check=True, cwd=str(PROJECT_ROOT), env=environment)
            else:
                subprocess.run(command, check=True, cwd=str(PROJECT_ROOT), env=environment)
            if name == 'venv':
                relative = interpreter.relative_to(WORK).as_posix()
                (WORK/'runtime.json').write_text(json.dumps({'python':relative, 'python_version':'3.12',
                    'platform':sys.platform}, indent=2)+'\n', encoding='utf-8')
        if not options.flash_only:
            model = ROOT/'camera/hand_landmarker.task'
            if (options.offline or options.check) and not model.is_file():
                raise RuntimeError('缺少手节点模型；联网运行安装入口下载，或先放入已校验模型文件再离线安装。')
            manifest = json.loads((ROOT/'camera/hand_landmarker.model.json').read_text(encoding='utf-8'))
            ensure_model(model, manifest)
            if not options.check:
                load_settings(ROOT/'settings.json', ROOT/'settings.example.json')
        print('运行环境检查通过。' if options.check else '依赖安装完成。可运行工程根目录的启动控制台入口。')
        result = 0
    except Exception as exc:
        print('安装未完成：' + str(exc))
        result = 1
    if sys.stdin.isatty():
        input('按回车关闭窗口。')
    return result


if __name__ == '__main__':
    sys.exit(main())

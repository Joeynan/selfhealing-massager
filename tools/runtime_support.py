"""Shared portable Python, settings, model and process ownership helpers."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.request import urlopen

MODEL_LIMIT_BYTES = 12 * 1024 * 1024


def venv_python(runtime_dir: Path, platform: str | None = None) -> Path:
    return Path(runtime_dir) / ('Scripts/python.exe' if (platform or sys.platform) == 'win32' else 'bin/python')


def flash_python(project_root: Path, platform: str | None = None) -> Path:
    return venv_python(Path(project_root) / 'work/watcher-control-runtime/flash-venv', platform)


def python_is_312(candidate: Path) -> bool:
    try:
        result = subprocess.run([str(candidate), '-I', '-c', 'import sys; raise SystemExit(sys.version_info[:2] != (3,12))'],
                                capture_output=True, timeout=10, check=False)
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def python_inside(candidate: str | Path, directories) -> bool:
    # Do not resolve executable symlinks: deleting their containing venv removes
    # the invocation path even when the linked base interpreter survives.
    absolute = Path(os.path.abspath(candidate))
    return any(absolute.is_relative_to(Path(os.path.abspath(directory))) for directory in directories)


def base_python(project_root: Path, explicit: str | Path | None = None, *, exclude_dirs=()) -> Path:
    """Find Python 3.12; never depend on a copied virtualenv on a fresh clone."""
    if explicit:
        selected = Path(explicit)
        if python_inside(selected, exclude_dirs):
            raise RuntimeError('指定的 Python 位于待重建环境内；请指定环境外的 Python 3.12。')
        if selected.is_file() and python_is_312(selected):
            return selected
        raise RuntimeError('指定的解释器不是可用的 Python 3.12。')
    candidates = []
    candidates += [Path(project_root) / 'work/tools/python-base/bin/python3.12',
                   Path(project_root) / 'work/tools/python-base/python.exe',
                   Path(getattr(sys, '_base_executable', sys.executable)), Path(sys.executable)]
    candidates += [Path(found) for name in ('python3.12', 'python3', 'python') if (found := shutil.which(name))]
    for candidate in dict.fromkeys(candidates):
        if not python_inside(candidate, exclude_dirs) and candidate.is_file() and python_is_312(candidate):
            return candidate
    raise RuntimeError('请安装 Python 3.12，再用它运行安装入口（Windows 可使用 py -3.12）。')


def load_settings(private: Path, example: Path, watcher_url: str | None = None) -> dict:
    """Create private settings once; command-line override applies to this run only."""
    if not private.exists():
        template = json.loads(example.read_text(encoding='utf-8'))
        private.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents two launchers from replacing a private file.
        try:
            with private.open('x', encoding='utf-8') as handle:
                json.dump(template, handle, ensure_ascii=False, indent=2)
                handle.write('\n')
        except FileExistsError:
            pass
    settings = json.loads(private.read_text(encoding='utf-8'))
    if not isinstance(settings, dict) or not all(isinstance(settings.get(key), str) for key in ('watcher_url', 'camera_url')):
        raise RuntimeError('settings.json 格式无效，请参考 settings.example.json。')
    if watcher_url:
        settings['watcher_url'] = watcher_url.rstrip('/')
    return settings


def ensure_model(destination: Path, manifest: dict, opener=None) -> Path:
    """Fetch only the pinned public model; verify before atomically installing it."""
    destination = Path(destination)
    expected_size = int(manifest['bytes'])
    expected_sha = manifest['sha256']
    if expected_size <= 0 or expected_size > MODEL_LIMIT_BYTES:
        raise RuntimeError('模型清单大小无效。')
    def matches(path):
        if path.stat().st_size != expected_size:
            return False
        digest = hashlib.sha256()
        with path.open('rb') as handle:
            for chunk in iter(lambda: handle.read(65536), b''):
                digest.update(chunk)
        return digest.hexdigest() == expected_sha
    if destination.is_file():
        if not matches(destination):
            raise RuntimeError('已有手节点模型校验失败；请备份并删除该文件后重新安装。')
        return destination
    if not manifest['url'].startswith('https://'):
        raise RuntimeError('模型下载地址必须使用 HTTPS。')
    destination.parent.mkdir(parents=True, exist_ok=True)
    pending = None
    try:
        with (opener or urlopen)(manifest['url'], timeout=60) as response:
            declared = response.headers.get('Content-Length')
            if declared is not None and (int(declared) != expected_size or int(declared) > MODEL_LIMIT_BYTES):
                raise RuntimeError('模型下载大小与清单不一致。')
            with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.hand-model-', suffix='.part', delete=False) as handle:
                pending = Path(handle.name)
                received = 0
                for chunk in iter(lambda: response.read(65536), b''):
                    received += len(chunk)
                    if received > expected_size or received > MODEL_LIMIT_BYTES:
                        raise RuntimeError('模型下载大小超过限制。')
                    handle.write(chunk)
        if not matches(pending):
            raise RuntimeError('模型下载校验失败，未安装。')
        pending.replace(destination)
        return destination
    finally:
        if pending is not None:
            pending.unlink(missing_ok=True)


def _process_provider():
    try:
        import psutil
        return psutil
    except ImportError as exc:
        raise RuntimeError('缺少 psutil 7.0.0，请先运行安装摄像头依赖入口。') from exc


def process_birth(pid: int, provider=None) -> float:
    return (provider or _process_provider()).Process(pid).create_time()


def verify_listener_owner(pid: int, script: Path, port: int, started: float, provider=None) -> None:
    """Fail closed on reused PIDs, different scripts or inaccessible process details."""
    try:
        process = (provider or _process_provider()).Process(pid)
        if abs(process.create_time() - float(started)) > .01:
            raise ValueError('PID reused')
        wanted = os.path.normcase(os.path.abspath(script))
        exact_script = any(os.path.normcase(os.path.abspath(argument)) == wanted for argument in process.cmdline())
        listeners = process.net_connections(kind='tcp')
        listening = any(connection.status == 'LISTEN' and connection.laddr.port == port for connection in listeners)
        if not exact_script or not listening:
            raise ValueError('script or port mismatch')
    except Exception as exc:
        raise RuntimeError('无法确认监听服务归属；请关闭原启动窗口或改用其他控制台端口。') from exc

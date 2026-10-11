"""Reuse running services; create one camera owner when the service is stopped."""
import argparse
import json
import os
import shutil
import subprocess
import sys
import socket
import time
import webbrowser
from pathlib import Path
from urllib.request import Request, build_opener, ProxyHandler
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parents[1]
WORK = PROJECT_ROOT / 'work' / 'watcher-control-runtime'
BASE_PYTHON = PROJECT_ROOT / 'work/tools/python-base/bin/python3.12'
sys.path.insert(0, str(PROJECT_ROOT / 'tools'))
from runtime_support import base_python, load_settings, process_birth, verify_listener_owner, venv_python
LOCAL_OPENER = build_opener(ProxyHandler({}))


def application(port):
    try:
        with LOCAL_OPENER.open(f'http://127.0.0.1:{port}/' + ('status' if port == 8877 else 'api/status'), timeout=1) as r:
            return json.load(r).get('application', 'unknown-service')
    except Exception:
        return None


def select_python(candidates):
    return next((p for p in candidates if p.is_file()), None)


def prepare_camera_config(saved, target):
    if not target.exists() and saved.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(saved, target)


def wait_ready(port, expected, child, attempts, interval):
    for _ in range(attempts):
        if application(port) == expected:
            return
        if child.poll() is not None:
            raise RuntimeError('服务启动失败，详情见 work/watcher-control-runtime 日志')
        time.sleep(interval)
    raise RuntimeError('服务启动超时，请查看 work/watcher-control-runtime 日志')


def runtime_candidates():
    configured = []
    config = WORK / 'runtime.json'
    if config.is_file():
        try:
            relative = Path(json.loads(config.read_text(encoding='utf-8'))['python'])
            resolved = (WORK / relative).resolve()
            if not relative.is_absolute() and resolved.is_relative_to(WORK.resolve()):
                configured = [resolved]
        except (ValueError, KeyError, TypeError):
            pass
    return configured + [venv_python(WORK / 'venv')]


def service_metadata(service, port):
    return WORK / f'{service}-{port}.json'


def record_service_owner(service, port, child, script):
    path = service_metadata(service, port)
    path.write_text(json.dumps({'project_root': str(PROJECT_ROOT), 'pid': child.pid,
                               'script': str(script.relative_to(PROJECT_ROOT)), 'port': port,
                               'started': process_birth(child.pid)},
                              ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return path


def validate_service_owner(service, port):
    message = f'{port} 端口的服务无法确认属于当前工程，请关闭其原启动窗口或使用其他控制台端口'
    try:
        metadata = json.loads(service_metadata(service, port).read_text(encoding='utf-8'))
        script = ROOT / ('server.py' if service == 'dashboard' else 'camera/landmark_server.py')
        pid = metadata['pid']
        if (metadata['project_root'] != str(PROJECT_ROOT) or type(pid) is not int or pid <= 0 or
                metadata['script'] != str(script.relative_to(PROJECT_ROOT)) or metadata.get('port') != port):
            raise ValueError(message)
        verify_listener_owner(pid, script, port, metadata['started'])
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, RuntimeError) as exc:
        raise RuntimeError(message) from exc


def parse_options(argv=None):
    parser=argparse.ArgumentParser(description='启动控制台；摄像头手势为默认来源')
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--mac-camera',action='store_true',help='显式启动 USB 摄像头诊断')
    mode.add_argument('--wifi-camera',action='store_true',help='启动 Wi-Fi 取图与 Mac 识别，设备就绪后默认启用输出')
    parser.add_argument('--watcher-url',help='小智控制地址，例如 http://192.168.1.20:8080')
    parser.add_argument('--offline', action='store_true', help='只启动本机离线页面，不连接或切换设备')
    parser.add_argument('--no-browser', action='store_true', help='启动后不自动打开浏览器')
    parser.add_argument('--dashboard-port', type=int, default=8890, help='本机控制台端口，默认 8890')
    options = parser.parse_args(argv)
    if not 1 <= options.dashboard_port <= 65535:
        parser.error('控制台端口必须在 1–65535 之间')
    if options.dashboard_port == 8877:
        parser.error('8877 保留给摄像头识别服务，请使用其他控制台端口')
    return options


def wifi_firmware_supported(firmware):
    return firmware in ('watcher-servo-controller-v7-wifi','watcher-servo-controller-v8-wifi',
                        'watcher-servo-controller-v9-wheel')


def validate_camera_service(state,transport,camera_url=None,watcher_id=None):
    if state.get('observation_version')!=2 or not isinstance(state.get('recognition_instance_id'),str) or not state['recognition_instance_id']:
        raise ValueError('已有识别服务版本较旧，请关闭旧启动窗口后打开新版')
    if state.get('transport')!=transport:
        raise ValueError('已有摄像头服务来源不同，请关闭旧启动窗口后重试')
    if transport=='wifi' and (state.get('camera_url')!=camera_url or state.get('watcher_id')!=watcher_id):
        raise ValueError('已有无线摄像头服务连接另一台设备，请关闭旧启动窗口后重试')


def switch_camera_source(watcher_url, device, request):
    steps=(('/suspend',{}),) if device.get('output_policy_revision')=='continuous-enable-1' else (
        ('/stop',{}),('/servo/arm',{'enabled':False}))
    for path,body in steps+(('/source',{'source':'camera'}),):
        result=request(watcher_url+path,body)
        if result.get('ok') is False:raise RuntimeError('小智未接受Mac诊断切换')


def main():
    options=parse_options()
    WORK.mkdir(parents=True, exist_ok=True)
    children = []
    logfiles = []
    metadata_files = []
    offline_sockets = []
    camera_child = None
    session_owned = False
    diagnostic=(options.mac_camera or options.wifi_camera) and not options.offline
    dashboard_port = options.dashboard_port
    dashboard_url = f'http://127.0.0.1:{dashboard_port}'
    service_env = os.environ.copy()
    for variable in ('PYTHONHOME', 'PYTHONPATH'):
        service_env.pop(variable, None)
    service_env.update(MPLCONFIGDIR=str(WORK / 'matplotlib'), XDG_CACHE_HOME=str(WORK / 'cache'))
    settings=load_settings(ROOT/'settings.json', ROOT/'settings.example.json', options.watcher_url)
    watcher_url=settings['watcher_url'].rstrip('/')
    opener=build_opener(ProxyHandler({}))
    def request_json(url,body=None):
        req=Request(url,None if body is None else json.dumps(body).encode(),{'Content-Type':'application/json'})
        with opener.open(req,timeout=2) as response:return json.load(response)
    try:
        if options.offline:
            # Keep these loopback ports bound, without listen(), so no service can
            # answer dashboard polling or receive a control request at either URL.
            for key in ('watcher_url', 'camera_url'):
                reserved = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                offline_sockets.append(reserved)
                reserved.bind(('127.0.0.1', 0))
                settings[key] = f'http://127.0.0.1:{reserved.getsockname()[1]}'
            watcher_url = settings['watcher_url']
        app = application(8877) if diagnostic else 'observer'
        if diagnostic and app and app != 'watcher-handnodes':
            raise RuntimeError('8877 端口由其他服务使用，请先关闭该服务')
        camera_app = app
        dashboard_app = application(dashboard_port)
        if dashboard_app and dashboard_app != 'watcher-control-dashboard':
            raise RuntimeError(f'{dashboard_port} 端口由其他服务使用，请先关闭该服务')
        # Inspect every existing service before creating a worker or modifying
        # the shared device. A launcher that only reuses services owns no session.
        if diagnostic and camera_app:
            validate_service_owner('camera', 8877)
        if dashboard_app:
            if options.offline:
                raise RuntimeError('离线验证端口已有服务，请使用未占用的 --dashboard-port')
            validate_service_owner('dashboard', dashboard_port)
            state=request_json(dashboard_url+'/api/status')
            if (state.get('software_release')!='wifi-camera-v8' or
                state.get('control_policy_revision')!='continuous-enable-1'):
                raise RuntimeError('请先关闭旧版控制台启动窗口，再打开持续启用版')
            if state.get('watcher_url')!=watcher_url:raise RuntimeError('更换小智地址前请先关闭已有控制台窗口')
        camera_args=['--port','/dev/cu.usbmodem5AF91645701'];frame_url=None;watcher_id=None
        if diagnostic and options.wifi_camera:
            device=request_json(watcher_url+'/status')
            if not wifi_firmware_supported(device.get('firmware')):
                raise RuntimeError('请先烧录 Wi-Fi 摄像头版小智固件，再启动无线识别')
            watcher_id=device.get('watcher_id') or device.get('device_id')
            parsed=urlsplit(watcher_url)
            if parsed.scheme!='http' or not parsed.hostname:raise ValueError('小智地址无效')
            frame_url='http://'+parsed.hostname+':8081/frame'
            from importlib.util import spec_from_file_location,module_from_spec
            spec=spec_from_file_location('watcher_wifi_reader',ROOT/'camera/wifi_camera.py')
            module=module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
            module.WiFiFrameReader(frame_url,watcher_id)
            camera_args=['--camera-url',frame_url,'--watcher-id',watcher_id]
        elif diagnostic and options.mac_camera:
            device=request_json(watcher_url+'/status')
            if wifi_firmware_supported(device.get('firmware')):
                raise RuntimeError('无线固件请使用 --wifi-camera；旧 USB 模式请配合回滚的 v6 固件')
        if diagnostic:
            if app:
                validate_camera_service(request_json('http://127.0.0.1:8877/status'),
                                        'wifi' if options.wifi_camera else 'usb',frame_url,watcher_id)
            if bool(camera_app) != bool(dashboard_app):
                raise RuntimeError('摄像头与控制台只有一个服务正在运行，无法取得完整会话；请在原启动窗口关闭已有服务后重新启动')
        if diagnostic and camera_app is None:
            python = select_python(runtime_candidates())
            if python is None:
                raise RuntimeError('缺少摄像头运行环境，请先运行“安装摄像头依赖.command”')
            prepare_camera_config(ROOT / 'camera/config.calibrated.json', WORK / 'camera-data/config.json')
            log = (WORK / 'camera.log').open('a'); logfiles.append(log)
            children.append(subprocess.Popen([str(python), '-B', '-u', str(ROOT / 'camera/landmark_server.py'),
                                               '--data-dir', str(WORK / 'camera-data'), '--http-port', '8877']+camera_args, stdout=log, stderr=log, cwd=str(PROJECT_ROOT), env=service_env))
            camera_child = children[-1]
            wait_ready(8877, 'watcher-handnodes', camera_child, 60, .5)
            metadata_files.append(record_service_owner('camera', 8877, children[-1], ROOT / 'camera/landmark_server.py'))
        if dashboard_app is None:
            runtime_settings=WORK/(f'settings-offline-{dashboard_port}.json' if options.offline else 'settings.json')
            runtime_settings.write_text(json.dumps(settings,ensure_ascii=False,indent=2), encoding='utf-8')
            log = (WORK / (f'dashboard-offline-{dashboard_port}.log' if options.offline else 'dashboard.log')).open('a'); logfiles.append(log)
            children.append(subprocess.Popen([str(select_python(runtime_candidates()) or base_python(PROJECT_ROOT)), '-u', str(ROOT / 'server.py'),'--port',str(dashboard_port),'--config',str(runtime_settings)], stdout=log, stderr=log, cwd=str(PROJECT_ROOT), env=service_env))
            session_owned = diagnostic and camera_child is not None
            wait_ready(dashboard_port, 'watcher-control-dashboard', children[-1], 10, .3)
            metadata_files.append(record_service_owner('dashboard', dashboard_port, children[-1], ROOT / 'server.py'))
        if session_owned:
            switch_camera_source(watcher_url, device, request_json)
            request_json(dashboard_url+'/api/source',{'source':'camera'})
        if not options.no_browser:
            webbrowser.open(dashboard_url+'/', new=2)
        print('离线控制台已启动：'+dashboard_url+'/' if options.offline else
              '已有服务已验证，控制台已打开。' if diagnostic and not session_owned else
              '无线识别与 5 秒联动控制台已启动，设备就绪后默认启用输出；保留 Mac 运行。' if options.wifi_camera else '控制台已打开。')
        if children:
            print('保留这个窗口。按 Ctrl+C 关闭本次启动的服务。')
            while all(child.poll() is None for child in children): time.sleep(.5)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print('启动失败：' + str(exc))
        if sys.stdin.isatty(): input('按回车关闭窗口。')
        return 1
    finally:
        if session_owned:
            try:request_json(watcher_url+'/stop',{})
            except Exception:pass
        for child in reversed(children):
            if child.poll() is None:
                child.terminate()
                try: child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.kill(); child.wait()
        for path in metadata_files: path.unlink(missing_ok=True)
        for reserved in offline_sockets: reserved.close()
        for log in logfiles: log.close()
    return 0


if __name__ == '__main__': sys.exit(main())

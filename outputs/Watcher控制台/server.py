"""Local control dashboard. Watcher owns the TCP link to the ESP8266."""
import argparse
import copy
import datetime
import json
import mimetypes
import math
import signal
import threading
import time
import uuid
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, build_opener, ProxyHandler

from bridge import IntentEngine

ROOT = Path(__file__).resolve().parent
LABELS = {'stop': '停止', 'pounding': '捶打', 'kneading': '揉搓', 'pinch': '轻捏'}
OPENER = build_opener(ProxyHandler({}))


def fetch(url, payload=None, timeout=.35):
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(url, data, {'Content-Type': 'application/json'})
    with OPENER.open(request, timeout=timeout) as response:
        return json.loads(response.read(65536))


class Dashboard:
    def __init__(self, watcher, camera):
        self.watcher_url = watcher.rstrip('/')
        self.camera_url = camera.rstrip('/')
        self.lock = threading.RLock()
        self.engine = IntentEngine()
        self.engine.set_source('camera')
        self.diagnostic_active = True  # User-selected default: camera control starts ready to accept new frames.
        self.default_enable_pending = False
        self.output_enable_reason = 'pending'
        self.default_enable_connection = None
        self.default_enable_generation = None
        self.default_enable_after = 0
        self.generation = 0
        self.forward_paused = False
        self.watcher = {'online': False, 'error': '', 'data': {}}
        self.camera = {'online': False, 'error': '', 'data': {}}
        self.logs = deque(maxlen=500)
        self.servo = {'armed': False, 'test_id': None, 'profile': {'neutral_us': [1500]*3, 'run_us': [2000]*3}}
        self.tests = {}
        self.output_events = set()
        self.capture_session = str(uuid.uuid4())
        self.last_activity_capture = -1
        self.last_activity_id = -1
        self.last_camera_session = None
        self.camera_instance_id = None
        self.events = {}
        self.observed = {}
        self.wake = threading.Event()
        self.shutdown = threading.Event()
        self.worker = threading.Thread(target=self.run, daemon=True)

    def log(self, event, message, error=False, details=None):
        with self.lock:
            self.logs.appendleft({'time': datetime.datetime.now().strftime('%H:%M:%S'),
                                   'level': 'error' if error else 'info',
                                   'event': event, 'message': message, 'details': details or {},
                                   'timestamp': datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat()})

    def changed(self, key, value, message, error=False):
        if self.events.get(key) != value:
            self.events[key] = value
            self.log(key, message, error)

    def action(self, path, payload):
        if not isinstance(payload, dict):
            raise ValueError('请求需要 JSON 对象')
        if path == '/api/calibrate':
            with self.lock:
                source=self.watcher['data'].get('input_source') if self.watcher['online'] else None
            if source not in ('onboard','camera'):
                raise ValueError('请先连接小智，并选择板上识别或 Mac 摄像头诊断')
            target=self.watcher_url+'/onboard/calibrate' if source=='onboard' else self.camera_url+'/calibrate/back'
            result = fetch(target, {}, timeout=2)
            if result.get('error') or result.get('ok') is False:
                raise ValueError(result.get('error', '校准失败，请将手背正对摄像头'))
            self.log('calibration', '已保存当前手背方向校准')
            return result
        if path.startswith('/api/servo/'):
            with self.lock:
                data = self.watcher['data'] if self.watcher['online'] else {}
                if path == '/api/servo/observation':
                    test_id, result = payload.get('test_id'), payload.get('result')
                    if test_id not in self.tests or result not in ('moving','stopped','no_response','abnormal'):
                        raise ValueError('请选择已有测试及有效的现场观察结果')
                    labels = {'moving':'转动','stopped':'停转','no_response':'无响应','abnormal':'异常'}
                    self.tests[test_id]['observation'] = result
                    self.log('user_observation','现场观察：'+labels[result],details=dict(self.tests[test_id],test_id=test_id))
                    return {'ok':True}
                if path == '/api/servo/arm':
                    enabled = payload.get('enabled')
                    if type(enabled) is not bool:
                        raise ValueError('输出启用状态需为 true 或 false')
                    if enabled and not self.diagnostic_active:
                        raise ValueError('当前仅观察设备；板上联动请使用小智滚轮启用，短测请先切换诊断来源')
                    if enabled:
                        self._validate_arm(data)
                    self.default_enable_pending = False
                    self.output_enable_reason = 'enabling' if enabled else 'manual_disable'
                    selected_source=self.engine.source
                    self.forward_paused=True
                    self.engine.set_source(selected_source);self.engine.last_sent='stop'
                    try:
                        automatic=payload.get('_default_enable') is True
                        if not automatic:self._require_ok(fetch(self.watcher_url+'/stop',{}))
                        if enabled and selected_source=='camera':self._reset_confirmation()
                        arm_body={'enabled':enabled}
                        if automatic:
                            arm_body.update(expected_stop_generation=payload['expected_stop_generation'],
                                            expected_source=selected_source)
                        # Compatibility with already installed v8 firmware. The
                        # current release no longer has a power checkbox gate.
                        if enabled and data.get('output_policy_revision') not in ('default-enable-1','continuous-enable-1'):
                            arm_body['power_confirmed']=True
                        result=self._require_ok(fetch(self.watcher_url+'/servo/arm',arm_body))
                        if enabled:
                            until=time.monotonic()+1.5
                            while True:
                                actual=fetch(self.watcher_url+'/status',timeout=.25)
                                if (actual.get('outputs_enabled') is True and actual.get('client_connected') is True and
                                    actual.get('profile_match') is True and actual.get('hold_protocol')==2):
                                    self.watcher={'online':True,'error':'','data':actual}
                                    self.observed['watcher']=time.monotonic();self.servo['armed']=True;break
                                if time.monotonic()>=until:raise ValueError('黑色板未确认启用；请检查通信')
                                self.shutdown.wait(.05)
                            if selected_source=='camera':self._reset_confirmation()
                        self.forward_paused=False
                        self.output_enable_reason='enabled' if enabled else 'manual_disable'
                        self.log('arm_request','输出已确认启用；等待新采集的稳定手势' if enabled else '请求禁用输出（停止波形）')
                        return result
                    except (URLError,OSError,ValueError):
                        self.engine.set_source(selected_source);self.engine.last_sent='stop';self.servo['armed']=False
                        self.output_enable_reason='fault'
                        stopped=True
                        for endpoint,body in self._suspend_endpoints():
                            try:self._require_ok(fetch(self.watcher_url+endpoint,body))
                            except (URLError,OSError,ValueError):stopped=False
                        if stopped:
                            try:
                                if selected_source=='camera':self._reset_confirmation()
                                self.forward_paused=False  # Preview resumes; execution remains disabled.
                            except (URLError,OSError,ValueError):pass
                        recovery=('连接与新画面恢复后自动启用' if data.get('output_policy_revision')=='continuous-enable-1'
                                  else '需重新启用')
                        self.log('arm_failed','启用失败，已暂停动作；'+recovery,True,
                                 details={'preview_resumed':not self.forward_paused,'stop_disable_confirmed':stopped})
                        raise
                if not self.diagnostic_active or self.engine.source != 'simulation':
                    raise ValueError('请先切换到手动模拟')
                if path == '/api/servo/test':
                    channel,pulse,duration=payload.get('channel'),payload.get('pulse_us'),payload.get('duration_ms')
                    if any(type(x) is not int for x in (channel,pulse,duration)) or not 1<=channel<=3 or not 1000<=pulse<=2000 or not 100<=duration<=500:
                        raise ValueError('短测需选择D1–D3、1000–2000µs，持续100–500ms')
                    if not data.get('outputs_enabled') or not data.get('profile_match'):
                        raise ValueError('输出未启用或校准配置尚未同步')
                    self.engine.stop();self.engine.last_sent='stop'
                    result=fetch(self.watcher_url+'/servo/test',payload)
                    self.new_test('calibration',payload)
                    return dict(result,test_id=self.servo['test_id'])
                if path == '/api/servo/profile':
                    n,r=payload.get('neutral_us'),payload.get('run_us')
                    if not isinstance(n,list) or not isinstance(r,list) or len(n)!=3 or len(r)!=3 or any(type(x)is not int for x in n+r) or any(not 1400<=n[i]<=1600 or n[i]%10 or not n[i]<r[i]<=2000 or r[i]%10 for i in range(3)):
                        raise ValueError('中立1400–1600µs；运行须大于中立且不超过2000µs，两者均为10µs步进')
                    if data.get('outputs_enabled') or self.engine.gesture!='stop':
                        raise ValueError('保存校准前请停止并禁用输出')
                    result=fetch(self.watcher_url+'/servo/profile',payload)
                    (ROOT/'servo_calibration.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n')
                    self.log('servo_profile','校准已保存到小智，等待黑色板配置回执',details=payload)
                    return result
                raise KeyError(path)
        # Commands and transport share this lock: an older queued activation cannot
        # overtake an explicit STOP. Network timeout is bounded to 350 ms.
        with self.lock:
            if path == '/api/simulate':
                if not self.diagnostic_active or self.engine.source != 'simulation':
                    raise ValueError('请先显式切换至模拟诊断，设备自动联动会停止并禁用')
                self.engine.simulate(payload.get('gesture'), payload.get('duration_ms', 2000), time.monotonic())
                self.new_test('simulation',dict(payload,gesture=self.engine.gesture))
            elif path == '/api/stop':
                selected_source=self.engine.source
                self.forward_paused=True
                self.engine.set_source(selected_source);self.engine.last_sent='stop'
                self._require_ok(fetch(self.watcher_url+'/stop',{}))
                if selected_source=='camera':self._reset_confirmation()
                self.forward_paused=False
                self.output_enable_reason='stopped'
                self.log('stop', '全部回中立；保留默认启用，等待新手势')
            elif path == '/api/source':
                selected=payload.get('source')
                if selected not in ('camera','simulation','onboard'):
                    raise ValueError('请选择板上识别、Mac摄像头诊断或模拟诊断')
                self.diagnostic_active=False
                self.default_enable_pending=False
                self.output_enable_reason='source_changed'
                self.engine.stop()
                fetch(self.watcher_url+'/stop',{})
                result=fetch(self.watcher_url+'/source',{'source':selected})
                if result.get('ok') is False:
                    raise ValueError(result.get('error','设备未接受来源切换'))
                if selected!='onboard': self.engine.set_source(selected)
                if selected=='camera':
                    # Camera may be intentionally closed in simulation mode.
                    # Warm it up while still disabled, before creating an ARM permit.
                    self._wait_for_camera_ready()
                    current=fetch(self.watcher_url+'/status')
                    generation=result.get('stop_generation')
                    if (type(generation) is int and
                        (current.get('stop_generation')!=generation or current.get('input_source')!='camera')):
                        raise ValueError('启动期间控制状态已改变；输出保持禁用，请重新选择来源')
                    self._reset_confirmation()
                self.diagnostic_active=selected!='onboard'
                self.forward_paused=False
                self.default_enable_pending=selected!='onboard'
                board=self.watcher['data']
                self.default_enable_connection=board.get('client_connection_id') if board.get('client_connected') else None
                self.default_enable_generation=result.get('stop_generation')
                self.default_enable_after=time.monotonic()
                self.output_enable_reason='pending' if self.default_enable_pending else 'observer'
                self.log('source', '输入来源：' + {'onboard':'Watcher板上识别','camera':'Mac摄像头诊断','simulation':'手动模拟诊断'}[selected])
            else:
                raise KeyError(path)
            self.generation += 1
            self.wake.set()
            return {'ok': True, 'requested': self.engine.gesture}

    def _suspend_endpoints(self):
        if self.watcher['data'].get('output_policy_revision')=='continuous-enable-1':
            return (('/suspend',{}),)
        return (('/stop',{}),('/servo/arm',{'enabled':False}))

    def stop_service(self):
        with self.lock:
            self.engine.stop()
            self.forward_paused=True
            if self.diagnostic_active:
                for endpoint,body in self._suspend_endpoints():
                    try:fetch(self.watcher_url+endpoint,body)
                    except (URLError,OSError,ValueError):pass

    @staticmethod
    def _require_ok(result):
        if not isinstance(result,dict) or result.get('ok') is not True:
            raise ValueError(result.get('error','设备未接受操作') if isinstance(result,dict) else '设备回报格式错误')
        return result

    def _wait_for_camera_ready(self):
        until=time.monotonic()+2
        while not self.shutdown.is_set() and time.monotonic()<until:
            started=time.monotonic()
            try:
                camera=fetch(self.camera_url+'/status',timeout=.25)
                camera['received_monotonic_ms']=started*1000
                frame=camera.get('camera_frame_id');session=camera.get('camera_session_id')
                if (camera.get('observation_version')==2 and camera.get('ready') is True and
                    not camera.get('error') and isinstance(session,str) and bool(session) and
                    type(frame) is int and 1<=frame<=0xffffffff and
                    IntentEngine.camera_age(camera,time.monotonic())<800):
                    return
            except (URLError,OSError,ValueError):
                pass
            self.shutdown.wait(.05)
        raise ValueError('摄像头尚未就绪，输出保持禁用；画面恢复后重新选择摄像头来源')

    def _reset_confirmation(self):
        result=self._require_ok(fetch(self.camera_url+'/reset_confirmation',{},timeout=.5))
        generation=result.get('confirmation_generation')
        if type(generation) is not int or generation<0:raise ValueError('识别服务未返回新版确认屏障')
        identity=result.get('recognition_instance_id')
        self.engine.confirmation_barrier(generation,identity)
        if identity is not None:self.camera_instance_id=identity
        return result

    def _camera_instance_changed(self, identity):
        previous=self.camera_instance_id;self.camera_instance_id=identity
        if previous is None or previous==identity or not self.diagnostic_active or self.engine.source!='camera':return
        self.default_enable_pending=False;self.output_enable_reason='fault'
        self.forward_paused=True;self.servo['armed']=False
        self.engine.set_source('camera');self.engine.last_sent='stop'
        stopped=True
        for endpoint,body in self._suspend_endpoints():
            try:self._require_ok(fetch(self.watcher_url+endpoint,body))
            except (URLError,OSError,ValueError):stopped=False
        if stopped:
            try:
                self._reset_confirmation()
                self.forward_paused=False
            except (URLError,OSError,ValueError):pass
        recovery=('新画面确认后自动恢复启用' if self.watcher['data'].get('output_policy_revision')=='continuous-enable-1'
                  else '已恢复表情预览，舵机需重新启用')
        self.log('recognition_restart','识别服务已重启，动作已取消；'+(recovery if not self.forward_paused else '转发暂停，等待停止及确认重置成功'),
                 self.forward_paused,{'previous_instance':previous,'recognition_instance':identity,'preview_resumed':not self.forward_paused})

    def maybe_default_enable(self):
        # New firmware owns continuous permission and readiness. Observing it
        # never manufactures a device receipt or sends repeated ARM commands.
        with self.lock:
            data=self.watcher['data'] if self.watcher['online'] else {}
            if data.get('output_policy_revision')=='continuous-enable-1':
                enabled=data.get('default_output_enabled') is True
                self.default_enable_pending=enabled and data.get('outputs_enabled') is not True
                self.output_enable_reason=('enabled' if data.get('outputs_enabled') is True
                                          else 'pending' if enabled else 'manual_disable')
                return
            if not self.default_enable_pending or not self.diagnostic_active or self.forward_paused:
                return
            data=self.watcher['data'] if self.watcher['online'] else {}
            if self.observed.get('watcher',0)<self.default_enable_after:
                return  # A response obtained before this source selection is stale.
            if data.get('output_policy_revision') not in ('default-enable-1','continuous-enable-1'):
                self.output_enable_reason='firmware_update'
                return
            generation=data.get('stop_generation')
            if (type(self.default_enable_generation) is not int or
                generation!=self.default_enable_generation):
                self.default_enable_pending=False;self.output_enable_reason='fault'
                return
            if data.get('last_stop_reason') in ('button_stop','button_long_hold','shutdown','explicit_stop','disarm'):
                self.default_enable_pending=False;self.output_enable_reason='explicit_stop'
                return
            connection=data.get('client_connection_id')
            if (self.default_enable_connection is not None and connection is not None and
                connection!=self.default_enable_connection):
                self.default_enable_pending=False;self.output_enable_reason='fault'
                return
            if self.default_enable_connection is None and data.get('client_connected'):
                self.default_enable_connection=connection
            if data.get('input_source')!=self.engine.source:
                return
            # Source selection requests STOP asynchronously. Wait for the peer's
            # disabled, neutral receipt before requesting a fresh ARM epoch.
            if data.get('outputs_enabled') is not False or data.get('applied_mode')!=0:
                return
            try:self._validate_arm(data)
            except ValueError:return
            self.default_enable_pending=False
            try:
                self.action('/api/servo/arm',{'enabled':True,'_default_enable':True,
                                            'expected_stop_generation':generation})
                self.log('default_output_enabled','设备就绪，输出已默认启用；正常手势和短测无需重复启用')
            except (URLError,OSError,ValueError):
                # action() already stopped/disarmed and logged the failure.
                self.output_enable_reason='fault'

    def _validate_arm(self, data):
        now=time.monotonic()
        if (not self.watcher['online'] or now-self.observed.get('watcher',0)>1.2 or
            data.get('client_connected') is not True or data.get('profile_match') is not True or
            data.get('hold_protocol')!=2 or type(data.get('ack_age_ms')) not in (int,float) or
            not math.isfinite(data['ack_age_ms']) or data['ack_age_ms']+(now-self.observed.get('watcher',0))*1000>=600):
            raise ValueError('请等待两板在线、配置同步及新版截止时间协议确认；旧版仅支持预览')
        if self.engine.source=='camera':
            camera=self.camera['data'] if self.camera['online'] else {}
            if (camera.get('observation_version')!=2 or not camera.get('ready') or
                camera.get('observation_state') in ('conflict','error') or
                IntentEngine.camera_age(camera,now)>=800 or data.get('camera_observation_version',data.get('mac_observation_version'))!=2):
                raise ValueError('请等待新版识别服务和新鲜有效摄像头观察')

    def new_test(self, kind, payload):
        identity=str(uuid.uuid4())
        self.servo['test_id']=identity
        record=dict(payload,kind=kind,source=self.engine.source)
        self.tests[identity]=record
        if len(self.tests)>200: del self.tests[next(iter(self.tests))]
        self.log('servo_test','单路脉宽短测' if kind=='calibration' else '模拟'+LABELS[self.engine.gesture],details=dict(record,test_id=identity))

    def activity(self, now):
        if not self.camera['online']:return None
        if self.camera['data'].get('transport')=='wifi':return None
        c=self.camera['data'];frame=c.get('capture_frame_id');age=c.get('capture_age_ms')
        if type(frame)is not int or frame<=0 or not isinstance(age,(int,float)):return None
        received=c.get('received_monotonic_ms',self.observed.get('camera',now)*1000)
        age=max(age+max(0,now*1000-received),0)
        captured=c.get('capture_monotonic_ms_latest',c.get('server_monotonic_ms',now*1000)-c.get('capture_age_ms',0))
        if age>=600:return None
        session=c.get('capture_session_id')
        if isinstance(session,str) and session and session!=self.last_camera_session:
            self.last_camera_session=session;self.capture_session=str(uuid.uuid4())
            self.last_activity_capture=-1;self.last_activity_id=-1
        if captured<=self.last_activity_capture:return None
        if frame<=self.last_activity_id:self.capture_session=str(uuid.uuid4())
        self.last_activity_capture=captured;self.last_activity_id=frame
        return {'session_id':self.capture_session,'frame_id':frame,'frame_age_ms':int(age)}

    def snapshot(self):
        with self.lock:
            devices = {}
            now = time.monotonic()
            for name in ('watcher', 'camera'):
                device = copy.deepcopy(getattr(self, name))
                elapsed_ms = (now - self.observed.get(name, 0)) * 1000
                if elapsed_ms > 1200:
                    device['online'] = False
                    device['error'] = '设备状态已过期'
                for field in ('hold_remaining_ms','expression_remaining_ms','servo_hold_remaining_ms'):
                    value=device['data'].get(field)
                    if isinstance(value,(int,float)):device['data'][field]=max(0,int(value-elapsed_ms))
                for field in ('ack_age_ms', 'frame_age_ms', 'camera_age_ms'):
                    value = device['data'].get(field)
                    if isinstance(value, (int, float)):
                        device['data'][field] = int(value + elapsed_ms)
                devices[name] = device
            board=devices['watcher']['data'] if devices['watcher']['online'] else {}
            source=self.engine.source if self.diagnostic_active else board.get('input_source','onboard')
            if source=='onboard':
                devices['camera']={'online':devices['watcher']['online'],'error':board.get('model_error',''),'data':{
                    'ready':board.get('camera_active') is True,'transport':'sscma_spi','image_available':False,
                    'frame_age_ms':board.get('camera_age_ms'),'frame_id':board.get('frame_id'),
                    'hands':copy.deepcopy(board.get('hands',[])),'raw_gesture':board.get('raw_gesture','stop'),
                    'gesture':board.get('gesture','stop'),'inference_fps':board.get('inference_fps'),
                    'model_ready':board.get('model_ready') is True}}
            return {'application': 'watcher-control-dashboard', 'api_version': 2, 'software_release':'wifi-camera-v8', 'servo': copy.deepcopy(self.servo),
                    'control_policy_revision':'continuous-enable-1',
                    'watcher_url':self.watcher_url,
                    'observer_only':not self.diagnostic_active,
                    'default_output_enabled':board.get('default_output_enabled',True),
                    'default_enable_pending':self.default_enable_pending,
                    'output_enable_reason':self.output_enable_reason,
                    'recognition_mode': 'onboard' if board.get('recognition_location')=='watcher' else 'mac_wifi' if devices['camera']['data'].get('transport')=='wifi' else 'mac_usb',
                    'standalone_ready': board.get('standalone_ready') is True,
                    'source': source,
                    'requested_gesture': board.get('held_gesture',board.get('gesture','stop')),
                    'hold_remaining_ms':board.get('hold_remaining_ms',0),
                    'expression_gesture':board.get('expression_gesture','stop'),
                    'servo_hold_remaining_ms':board.get('servo_hold_remaining_ms',0),
                    'observation_state':board.get('observation_state','error'),
                    'execution_pending':board.get('execution_pending') is True,
                    'simulation_remaining_ms': max(0, int((self.engine.deadline - time.monotonic()) * 1000))
                    if self.engine.source == 'simulation' and self.engine.gesture != 'stop' else 0,
                    'watcher': devices['watcher'], 'camera': devices['camera'], 'logs': list(self.logs)}

    def poll(self, name, base):
        with self.lock:poll_generation=self.generation
        started = time.monotonic()
        try:
            data = fetch(base + '/status')
            if not isinstance(data, dict):
                raise ValueError('状态格式错误')
            received = time.monotonic()
            transport_ms = max(0, (received - started) * 1000)
            if name == 'camera':
                # Charge the whole HTTP round trip conservatively, then age in
                # this process's clock. Do not subtract another runtime's epoch.
                for field in ('frame_age_ms', 'capture_age_ms'):
                    if isinstance(data.get(field), (int, float)):
                        data[field] += transport_ms
                data['received_monotonic_ms'] = received * 1000
            else:
                for field in ('ack_age_ms','camera_age_ms'):
                    if isinstance(data.get(field),(int,float)):
                        data[field]+=transport_ms
            result = {'online': True, 'error': '', 'data': data}
        except (URLError, OSError, ValueError) as exc:
            received = time.monotonic()
            result = {'online': False, 'error': '摄像头服务未连接，请重新启动控制台' if name == 'camera' else '小智未连接，请检查供电和 Wi-Fi', 'data': {}}
        with self.lock:
            if poll_generation!=self.generation:
                return False  # Do not publish a pre-source-switch response.
            if (not result['online'] and self.default_enable_pending and
                (name=='watcher' or self.engine.source=='camera')):
                self.default_enable_pending=False;self.output_enable_reason='fault'
            if name=='watcher' and self.engine.source=='simulation':
                previous=self.watcher['data'].get('client_connection_id')
                current=result['data'].get('client_connection_id')
                if not result['online'] or (previous is not None and current!=previous):
                    self.engine.set_source('simulation');self.engine.last_sent='stop'
            setattr(self, name, result)
            self.observed[name] = received
            identity=result['data'].get('recognition_instance_id') if name=='camera' and result['online'] else None
            if isinstance(identity,str) and identity:self._camera_instance_changed(identity)
        self.changed(name + '_online', result['online'],
                     ('小智' if name == 'watcher' else '摄像头服务') + ('已连接' if result['online'] else '未连接'),
                     not result['online'])
        if name == 'watcher' and result['online']:
            d = result['data']
            with self.lock:
                self.servo['armed']=d.get('outputs_enabled') is True
                if self.output_enable_reason=='enabled' and not self.servo['armed']:
                    self.output_enable_reason='fault'
                if isinstance(d.get('servo_profile'),dict):self.servo['profile']=d['servo_profile']
                for event in d.get('output_events',[]):
                    key=(event.get('connection_id'),event.get('event_id'))
                    if key in self.output_events:continue
                    self.output_events.add(key)
                    if len(self.output_events)>1000:self.output_events={key}
                    self.log('servo_output',('历史：' if event.get('historical') else '')+'MOD'+str(event.get('mode'))+' '+str(event.get('reason'))+'，软件脉宽 '+str(event.get('pulse_us')),details=dict(event,test_id=None if event.get('historical') else self.servo['test_id']))
            self.changed('camera_light',d.get('led_color'),'摄像头灯：'+str(d.get('led_color','未知')))
            self.changed('profile_match',d.get('profile_match'),'舵机配置'+('已同步' if d.get('profile_match') else '等待同步'))
            self.changed('black_board', (d.get('client_connected'), d.get('outputs_enabled')),
                         '黑色板' + ('已连接' if d.get('client_connected') else '未连接') +
                         ('，输出启用' if d.get('outputs_enabled') else '，输出禁用'))
            if d.get('client_connected'):
                self.changed('applied_mode', d.get('applied_mode'),
                             '板子回报 MOD' + str(d.get('applied_mode', 0)) + '，脉宽 µs ' + str(d.get('client_pulse_us', [])))
            self.changed('last_stop_reason',d.get('last_stop_reason'),'停止原因：'+str(d.get('last_stop_reason','未知')))
            if type(d.get('hold_event_id')) is int and d.get('hold_event_id')>0:
                previous=self.events.get('held_gesture')
                held=d.get('held_gesture','stop')
                if self.events.get('hold_event_id')!=d['hold_event_id']:
                    event='hold_refresh' if previous==held else 'hold_switch' if previous in ('pounding','kneading','pinch') else 'hold_accepted'
                    self.log(event,'Watcher '+('刷新保持' if event=='hold_refresh' else '切换手势' if event=='hold_switch' else '接受手势')+'：'+LABELS.get(held,held),details={'hold_event_id':d['hold_event_id'],'gesture':held,'remaining_ms':d.get('hold_remaining_ms',0)})
                    self.events['hold_event_id']=d['hold_event_id']
                self.events['held_gesture']=held
            self.changed('observation_state',d.get('observation_state'),'观察状态：'+str(d.get('observation_state','未知')))
            self.changed('expression', d.get('emotion'), '小智表情：' + str(d.get('emotion', '未知')))
        return True

    def forward_inputs(self, now):
        if not self.diagnostic_active or self.forward_paused:
            return
        begun=time.monotonic()
        activity=self.activity(now)
        if activity:
            try:fetch(self.watcher_url+'/camera/activity',activity,timeout=.2)
            except (URLError,OSError,ValueError):pass
        camera = self.camera['data'] if self.camera['online'] else None
        effective_now=now+max(0,time.monotonic()-begun)
        if (self.engine.source=='camera' and camera and camera.get('observation_state')=='error' and
            not self.engine.awaiting_publication(camera,effective_now)):
            self.default_enable_pending=False;self.output_enable_reason='fault'
        command = self.engine.step(camera, effective_now)
        if command:
            try:
                valid_camera_stop=command.get('observation_version')==2 or (command['gesture']=='stop' and 'camera_frame_id' in command)
                normal_simulation_stop=(self.engine.source=='simulation' and not self.engine.last_fault)
                hard_stop=command['gesture']=='stop' and not valid_camera_stop and not normal_simulation_stop
                if hard_stop:
                    self.default_enable_pending=False;self.output_enable_reason='fault'
                reply=fetch(self.watcher_url + ('/suspend' if hard_stop and self.watcher['data'].get('output_policy_revision')=='continuous-enable-1' else '/stop' if hard_stop else '/gesture'), command)
                if reply.get('ok') is False or reply.get('error'):raise ValueError(reply.get('error','设备拒绝过期或不匹配的画面'))
                self.changed('send_error', False, '控制接口已连接')
                if command['gesture']!='stop':
                    self.changed('camera_gesture',command['gesture'],'稳定手势已发送：'+LABELS[command['gesture']])
            except (URLError, OSError, ValueError):
                if self.engine.source=='simulation':
                    self.engine.set_source('simulation');self.engine.last_sent='stop'
                self.default_enable_pending=False;self.output_enable_reason='fault'
                self.changed('send_error', True, '指令未送达小智；现有指令将超时停止', True)
                if command['gesture'] == 'stop': self.engine.last_sent = None

    def run_inputs(self):
        # One camera/status owner and one forwarding owner. Slow Watcher status
        # reads cannot make the next recognition result wait behind them.
        while not self.shutdown.is_set():
            started=time.monotonic()
            self.poll('camera',self.camera_url)
            with self.lock:self.forward_inputs(time.monotonic())
            self.wake.wait(max(.005,.1-(time.monotonic()-started)));self.wake.clear()

    def run(self):
        inputs=threading.Thread(target=self.run_inputs,daemon=True);inputs.start()
        while not self.shutdown.is_set():
            if self.poll('watcher',self.watcher_url):self.maybe_default_enable()
            self.shutdown.wait(.15)
        inputs.join(timeout=1)


def handler_for(dashboard):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, code, body, content_type='application/json; charset=utf-8'):
            if not isinstance(body, bytes): body = json.dumps(body, ensure_ascii=False).encode()
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.end_headers()
            try: self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError): pass

        def do_GET(self):
            path = self.path.split('?', 1)[0]
            if path == '/api/status':
                return self.reply(200, dashboard.snapshot())
            if path == '/api/frame':
                try:
                    with OPENER.open(dashboard.camera_url + '/frame', timeout=.6) as r:
                        return self.reply(200, r.read(2 * 1024 * 1024), 'image/jpeg')
                except (URLError, OSError):
                    return self.reply(503, {'error': '摄像头画面不可用'})
            files = {'/': 'index.html', '/index.html': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css', '/watcher_ui.js': 'watcher_ui.js', '/watcher_ui.css': 'watcher_ui.css'}
            if path not in files:
                return self.reply(404, {'error': '页面不存在'})
            filename = ROOT / files[path]
            return self.reply(200, filename.read_bytes(), mimetypes.guess_type(filename.name)[0] or 'text/plain')

        def do_POST(self):
            origin = self.headers.get('Origin')
            port = self.server.server_port
            if origin is not None and origin not in (f'http://127.0.0.1:{port}', f'http://localhost:{port}'):
                return self.reply(403, {'error': '来源不可用'})
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096:
                    raise ValueError('请求内容长度无效')
                self.connection.settimeout(2)
                payload = json.loads(self.rfile.read(length))
                result = dashboard.action(self.path, payload)
                return self.reply(200, result)
            except KeyError:
                return self.reply(404, {'error': '控制接口不存在'})
            except (ValueError, TypeError) as exc:
                return self.reply(400, {'error': str(exc)})
            except (URLError, OSError) as exc:
                return self.reply(503, {'error': '设备未响应：' + str(exc)})
    return Handler


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8890)
    parser.add_argument('--config', type=Path, default=ROOT / 'settings.json')
    args = parser.parse_args()
    settings = json.loads(args.config.read_text())
    dashboard = Dashboard(settings['watcher_url'], settings['camera_url'])
    signal.signal(signal.SIGTERM,lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler_for(dashboard))
    dashboard.worker.start()
    print(f'控制台已启动：http://127.0.0.1:{args.port}/', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        dashboard.stop_service()
        dashboard.shutdown.set()
        server.server_close()


if __name__ == '__main__':
    main()

# 电脑识别服务入口：从 Watcher 获取图像，调用 MediaPipe 提取 21 节点，再交给手势规则。
# 本文件运行在电脑上；设备采集、显示和舵机接收分别由两块板的固件负责。
"""Local Watcher camera + MediaPipe Tasks service. No motor communication."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import signal
from threading import Event, Thread
import time
from urllib.parse import urlsplit
from gesture_rules import Config
from runtime_state import FramePipeline


def now_ms():return time.monotonic_ns()//1_000_000


def save_json(path, value):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(path)


class App:
    def __init__(self, data_dir, port=None, resolution='416x416', camera_url=None, watcher_id=None):
        self.data_dir=Path(data_dir);self.data_dir.mkdir(parents=True,exist_ok=True)
        self.config_path=self.data_dir/'config.json'
        c=Config(**json.loads(self.config_path.read_text())) if self.config_path.exists() else Config()
        self.pipeline=FramePipeline(c.validate());self.port=port;self.stopping=Event()
        if resolution not in ('240x240','416x416','480x480','640x480'):raise ValueError('摄像头分辨率无效')
        self.resolution=resolution
        self.camera_url=camera_url;self.watcher_id=watcher_id
        if camera_url:
            from wifi_camera import WiFiFrameReader
            self.wifi_reader=WiFiFrameReader(camera_url,watcher_id)
            self.pipeline.transport='wifi'
        self.trials_path=self.data_dir/'trials.json'
        if self.trials_path.exists():
            previous=json.loads(self.trials_path.read_text())
            self.pipeline.trials.records=previous.get('records',[])
            active=previous.get('active')
            if active:
                active['result']='cancelled';active['cancel_reason']='程序重启，测试中断'
                self.pipeline.trials.records.append(active)
        self.model=None;self.input_images={};self.model_sha256=None
        self.last_model_timestamp=-1
        self.workers=[]

    def save_config(self):save_json(self.config_path,asdict(self.pipeline.engine.config))

    def save_trials(self):
        with self.pipeline.lock:
            save_json(self.trials_path,{'records':self.pipeline.trials.records,
                'active':self.pipeline.trials.active,'summary':self.pipeline.trials.summary()})

    def change_config(self, values):
        with self.pipeline.lock:
            current=asdict(self.pipeline.engine.config)
            if not isinstance(values,dict) or set(values)-set(current):raise ValueError('未知参数')
            current.update(values);c=Config(**current).validate()
            self.pipeline.reset(c);self.save_config()

    def start_trial(self,label):
        with self.pipeline.lock:
            now=now_ms();s=self.pipeline.snapshot(now)
            if not s['ready'] or s['frame_age_ms'] is None or s['frame_age_ms']>800:
                raise ValueError('请等待摄像头与手节点检测准备好')
            self.pipeline.trials.start(label,now)
            self.pipeline.reset()
            self.save_trials()

    # 固定模型由安装器下载并校验；使用内存中的模型字节，兼容中文与空格路径。
    def initialize_model(self, model_path):
        import hashlib
        import mediapipe as mp
        self.mp=mp
        path=Path(model_path)
        if not path.is_file():raise FileNotFoundError('缺少手节点模型，请运行安装脚本')
        # Python supports Unicode paths; the native Windows model loader may not.
        # Pass the exact hashed content instead of asking native code to reopen it.
        model_bytes=path.read_bytes()
        self.model_sha256=hashlib.sha256(model_bytes).hexdigest()
        options=mp.tasks.vision.HandLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_buffer=model_bytes,delegate=mp.tasks.BaseOptions.Delegate.CPU),
            running_mode=mp.tasks.vision.RunningMode.LIVE_STREAM,num_hands=2,
            min_hand_detection_confidence=.6,min_hand_presence_confidence=.6,min_tracking_confidence=.6,
            result_callback=self.on_result)
        self.model=mp.tasks.vision.HandLandmarker.create_from_options(options)

    # 异步结果只能对应原提交帧；旧采集会话或重置前的回调不会发布新的有效确认。
    def on_result(self,result,image,timestamp_ms):
        try:
            # The frame and RGB owner remain alive until this exact callback.
            record=self.input_images.pop(timestamp_ms,None)
            if record is None:return
            frame,rgb=record
            with self.pipeline.lock:
                if (frame.generation!=self.pipeline.generation or self.pipeline.pending is None or
                        self.pipeline.pending.id!=frame.id):return
            observations=[]
            for index,landmarks in enumerate(result.hand_landmarks):
                handedness=result.handedness[index][0].category_name
                observations.append({'handedness':handedness,
                    'landmarks':[[p.x,p.y,p.z] for p in landmarks],
                    'world_landmarks':[[p.x,p.y,p.z] for p in result.hand_world_landmarks[index]]})
            accepted=self.pipeline.complete(frame,observations,now_ms(),rgb.shape[1],rgb.shape[0])
            if accepted:
                with self.pipeline.lock:
                    self.save_trials()
                    active=self.pipeline.trials.active
                    if active and active['begin_ms']<=now_ms()<active['end_ms']:
                        state=self.pipeline.snapshot(now_ms())
                        with (self.data_dir/'trial-landmarks.jsonl').open('a',encoding='utf-8') as f:
                            f.write(json.dumps({'expected':active['expected'],'frame_id':state['frame_id'],
                                'capture_monotonic_ms':state['capture_monotonic_ms'],'gesture':state['gesture'],
                                'raw_gesture':state['raw_gesture'],'hands':state['hands']},ensure_ascii=False)+'\n')
        except Exception as e:
            self.pipeline.fail_inference('手节点结果处理失败：'+str(e))

    # 一次处理最新一帧，避免排队图像让识别结果越来越旧。
    def inference_worker(self):
        import cv2
        import numpy as np
        while not self.stopping.is_set():
            frame=self.pipeline.take_latest()
            if frame is None:self.stopping.wait(.004);continue
            try:
                bgr=cv2.imdecode(np.frombuffer(frame.jpeg,dtype=np.uint8),cv2.IMREAD_COLOR)
                if bgr is None:raise ValueError('无法解码摄像头画面')
                rgb=cv2.cvtColor(bgr,cv2.COLOR_BGR2RGB)
                image=self.mp.Image(image_format=self.mp.ImageFormat.SRGB,data=rgb)
                stamp=max(frame.timestamp_ms,self.last_model_timestamp+1)
                self.last_model_timestamp=stamp
                self.input_images[stamp]=(frame,rgb)
                self.model.detect_async(image,stamp)
            except Exception as e:
                if 'stamp' in locals():self.input_images.pop(stamp,None)
                self.pipeline.fail_inference('手节点检测失败：'+str(e));return

    def camera_worker(self):
        if self.camera_url:return self.wifi_camera_worker()
        from watcher_camera import SerialPort,decode_image,option_for_resolution
        while not self.stopping.is_set():
            try:
                with SerialPort(self.port) as port:
                    port.request('AT+BREAK',timeout=3)
                    sensors=port.request('AT+SENSORS?',timeout=3)['data']
                    sensor=next(s for s in sensors if s.get('type')==1)
                    option=option_for_resolution(sensor,self.resolution)
                    port.request('AT+SENSOR={0},1,{1}'.format(sensor['id'],option),timeout=5)
                    while not self.stopping.is_set():
                        begun=now_ms()
                        jpeg=decode_image(port.request('AT+SAMPLE=1',timeout=2,want_image=True))
                        self.pipeline.capture(jpeg,now_ms(),now_ms()-begun)
            except Exception as e:
                self.pipeline.error('摄像头连接异常：'+str(e))
                self.stopping.wait(3)

    # Wi-Fi 画面传入同一识别流水线；摄像头故障通过状态发布，不使用旧帧续期。
    def wifi_camera_worker(self):
        while not self.stopping.is_set():
            with self.pipeline.lock:
                capture_generation=self.pipeline.generation
            try:
                frame=self.wifi_reader.fetch()
                if frame is not None:
                    self.pipeline.capture_wifi(frame.jpeg,frame.timestamp_ms,frame.session_id,
                                               frame.frame_id,frame.transfer_ms,
                                               capture_generation=capture_generation)
                self.stopping.wait(.025)
            except Exception as e:
                self.pipeline.error('无线摄像头连接异常：'+str(e),capture_generation=capture_generation)
                self.stopping.wait(.5)

    def measurement_worker(self):
        while not self.stopping.wait(2):
            try:
                s=self.pipeline.snapshot(now_ms())
                s['measured_at_utc']=datetime.now(timezone.utc).isoformat()
                s['model_sha256']=self.model_sha256
                self.save_trials()
                save_json(self.data_dir/'measurements.json',s)
            except OSError as e:print('报告保存失败：'+str(e),flush=True)

    def start_workers(self):
        for worker in (self.camera_worker,self.inference_worker,self.measurement_worker):
            thread=Thread(target=worker,daemon=True);self.workers.append(thread);thread.start()

    def close(self):
        self.stopping.set()
        for thread in self.workers:thread.join(timeout=8)
        if self.model is not None:self.model.close()
        s=self.pipeline.snapshot(now_ms());s['model_sha256']=self.model_sha256
        self.save_trials()
        save_json(self.data_dir/'measurements.json',s)


def make_server(app,http_port=8877):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,value,status=200,kind='application/json'):
            data=json.dumps(value,ensure_ascii=False,allow_nan=False).encode() if not isinstance(value,bytes) else value
            self.send_response(status);self.send_header('Content-Type',kind)
            self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(data)))
            self.send_header('X-Content-Type-Options','nosniff')
            self.end_headers()
            try:self.wfile.write(data)
            except (BrokenPipeError,ConnectionResetError):pass

        def do_GET(self):
            path=urlsplit(self.path).path
            if path=='/':return self.reply(Path(__file__).with_name('index.html').read_bytes(),kind='text/html; charset=utf-8')
            if path in ('/status','/snapshot'):
                state=app.pipeline.snapshot(now_ms(),include_image=path=='/snapshot')
                state.update(camera_url=app.camera_url,watcher_id=app.watcher_id)
                return self.reply(state)
            if path=='/frame':
                with app.pipeline.lock:
                    f=app.pipeline.published or app.pipeline.latest
                    return self.reply(f.jpeg if f else b'',200 if f else 503,kind='image/jpeg')
            if path=='/trials':
                with app.pipeline.lock:return self.reply({'records':app.pipeline.trials.records,'summary':app.pipeline.trials.summary()})
            return self.reply({'error':'页面不存在'},404)

        def do_POST(self):
            origin=self.headers.get('Origin')
            port=self.server.server_address[1]
            if origin not in (None,'http://127.0.0.1:'+str(port),'http://localhost:'+str(port)):
                return self.reply({'error':'请从本机调试页面操作'},403)
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 0<=length<=4096:raise ValueError('参数过大')
                values=json.loads(self.rfile.read(length)) if length else {}
                if not isinstance(values,dict):raise ValueError('操作参数须为对象')
                path=urlsplit(self.path).path
                if path=='/config':app.change_config(values)
                elif path=='/calibrate/back':
                    with app.pipeline.lock:
                        side=app.pipeline.calibrate_back(now_ms());app.save_config()
                    return self.reply({'ok':True,'handedness':side})
                elif path=='/trials/start':app.start_trial(values.get('label'))
                elif path=='/trials/cancel':
                    with app.pipeline.lock:app.pipeline.trials.cancel();app.pipeline.reset();app.save_trials()
                elif path=='/reset_confirmation':
                    return self.reply(app.pipeline.reset_confirmation(now_ms()))
                elif path=='/reset':
                    with app.pipeline.lock:app.pipeline.reset()
                else:return self.reply({'error':'操作不存在'},404)
                return self.reply({'ok':True})
            except (ValueError,TypeError,KeyError) as e:return self.reply({'error':str(e)},400)

    server=ThreadingHTTPServer(('127.0.0.1',http_port),Handler)
    server.daemon_threads=True
    return server


def main():
    p=argparse.ArgumentParser(description='Watcher 手节点实时验证')
    source=p.add_mutually_exclusive_group()
    source.add_argument('--port',help='显式使用 USB 摄像头串口')
    source.add_argument('--camera-url',help='http://小智地址:8081/frame；无线模式不打开 USB')
    p.add_argument('--watcher-id',help='无线模式必填的目标设备 ID')
    p.add_argument('--http-port',type=int,default=8877)
    p.add_argument('--resolution',choices=['240x240','416x416','480x480','640x480'],default='416x416')
    p.add_argument('--data-dir',type=Path,default=Path(__file__).parent/'data')
    p.add_argument('--model',type=Path,default=Path(__file__).with_name('hand_landmarker.task'))
    args=p.parse_args()
    if not args.port and not args.camera_url:p.error('请指定 --camera-url 或 --port')
    app=App(args.data_dir,args.port,args.resolution,args.camera_url,args.watcher_id)
    signal.signal(signal.SIGTERM,lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    app.initialize_model(args.model)
    server=make_server(app,args.http_port)
    app.start_workers()
    def stop(*_):
        app.stopping.set()
        Thread(target=server.shutdown,daemon=True).start()
    signal.signal(signal.SIGINT,stop);signal.signal(signal.SIGTERM,stop)
    print('Watcher 手节点页面：http://127.0.0.1:'+str(args.http_port),flush=True)
    try:server.serve_forever(poll_interval=.1)
    finally:
        server.server_close();app.close()


if __name__=='__main__':main()

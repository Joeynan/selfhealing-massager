# 识别流水线共享状态：一个最新采集槽、一个推理槽和一次完整结果发布。
# 采集/识别/网页线程通过锁交换状态，现场测试记录与软件确认结果分别保存。
"""One capture slot, one inference slot, an atomic result, and trial evidence."""
from collections import deque
from dataclasses import asdict, dataclass
import base64
import copy
import math
import uuid
from threading import RLock
from gesture_rules import Config, GestureEngine, valid_points


@dataclass(frozen=True)
class Frame:
    id: int
    timestamp_ms: int
    jpeg: bytes
    generation: int=0
    remote_session_id: str=None
    remote_frame_id: int=None


class TrialRecorder:
    def __init__(self):
        self.active=None;self.records=[]

    def start(self, label, now):
        if label not in ('pounding','kneading','pinch'):
            raise ValueError('测试手势无效')
        if self.active:
            raise ValueError('请等待本次测试结束')
        self.active={'expected':label,'started_ms':now,'begin_ms':now+3000,'end_ms':now+8000,
                     'observed':[],'first_correct_ms':None}

    def observe(self, now, gesture, capture_ms=None, raw_gesture=None, event_ms=None):
        captured=now if capture_ms is None else capture_ms
        raw=gesture if raw_gesture is None else raw_gesture
        event=captured if event_ms is None else event_ms
        if (self.active and self.active['begin_ms']<=now<self.active['end_ms'] and
            self.active['begin_ms']<=captured<self.active['end_ms'] and
            self.active['begin_ms']<=event<self.active['end_ms'] and gesture!='stop' and raw==gesture):
            if gesture not in self.active['observed']:self.active['observed'].append(gesture)
            if gesture==self.active['expected'] and self.active['first_correct_ms'] is None:
                self.active['first_correct_ms']=now

    def tick(self, now):
        if self.active and now>=self.active['end_ms']:
            r=self.active
            r['result']='passed' if r['observed']==[r['expected']] else 'failed'
            r['trial_number']=1+sum(x['expected']==r['expected'] and x['result']!='cancelled' for x in self.records)
            self.records.append(r);self.active=None

    def cancel(self):
        if self.active:
            self.active['result']='cancelled';self.records.append(self.active);self.active=None

    def summary(self):
        result={}
        for label in ('pounding','kneading','pinch'):
            rows=[r for r in self.records if r['expected']==label and r['result']!='cancelled']
            passed=sum(r['result']=='passed' for r in rows)
            result[label]={'completed':len(rows),'passed':passed,'failed':len(rows)-passed,
                           'target_trials':20,'accuracy':passed/len(rows) if rows else None,
                           'accepted':len(rows)>=20 and passed/len(rows)>=.9}
        return result


# 按左右手与掌心位置延续手的身份；离开画面后不沿用旧手的揉搓历史。
class HandTracker:
    def __init__(self):
        self.previous={};self.counter=0

    def update(self, hands):
        available=dict(self.previous);current={};output=[]
        for h in hands:
            points=h.get('landmarks')
            if not valid_points(points):
                output.append(dict(h,id='invalid'));continue
            center=points[9][:2];side=h.get('handedness')
            candidates=[(math.dist(center,old['center']),identity) for identity,old in available.items() if old['side']==side]
            best=min(candidates,default=(float('inf'),None))
            if best[0]<=.22:
                identity=best[1];available.pop(identity)
            else:
                self.counter+=1;identity=str(self.counter)
            current[identity]={'center':center,'side':side}
            output.append(dict(h,id=identity))
        self.previous=current
        return output


class FramePipeline:
    def __init__(self, config=None):
        self.capture_session_id=str(uuid.uuid4())
        self.recognition_instance_id=str(uuid.uuid4())  # Stable for this service process.
        self.lock=RLock();self.engine=GestureEngine(config);self.tracker=HandTracker()
        self.latest=None;self.pending=None;self.published=None
        self.sequence=0;self.submitted=0;self.processed=0;self.ready=False;self.message=''
        self.generation=0
        self.capture_times=deque(maxlen=180);self.result_times=deque(maxlen=180)
        self.latencies=deque(maxlen=180);self.capture_latencies=deque(maxlen=180)
        self.trials=TrialRecorder();self.started_ms=None
        self.last_dimensions=(640,480)
        self.inference_error=''
        self.transport='usb';self.remote_session=None;self.remote_frame_id=0
        self.retired_sessions=deque(maxlen=16)
        self.confirmation_reset_monotonic_ms=-1
        self.confirmation_generation=0

    def capture_wifi(self, jpeg, timestamp_ms, remote_session_id, remote_frame_id, capture_latency_ms=0,
                     capture_generation=None):
        with self.lock:
            # The request began before network I/O; a reset invalidates even a
            # response whose reported capture time appears newer than the reset.
            if capture_generation is not None and capture_generation!=self.generation:return False
            if timestamp_ms<=self.confirmation_reset_monotonic_ms:return False
            if remote_session_id in self.retired_sessions:return False
            if self.remote_session!=remote_session_id:
                if self.remote_session is not None:self.retired_sessions.append(self.remote_session)
                self.remote_session=remote_session_id;self.remote_frame_id=0
                self.reset();self.pending=None;self.latest=None
                self.capture_session_id=str(uuid.uuid4())
            if remote_frame_id<=self.remote_frame_id:return False
            if self.latest and timestamp_ms<=self.latest.timestamp_ms:return False
            self.transport='wifi';self.remote_frame_id=remote_frame_id
            self.sequence+=1
            self.latest=Frame(self.sequence,timestamp_ms,jpeg,self.generation,remote_session_id,remote_frame_id)
            self.ready=True;self.message='';self.capture_times.append(timestamp_ms)
            self.capture_latencies.append(capture_latency_ms)
            if self.started_ms is None:self.started_ms=timestamp_ms
            return True

    def capture(self, jpeg, timestamp_ms, capture_latency_ms=0):
        with self.lock:
            if timestamp_ms<=self.confirmation_reset_monotonic_ms:return False
            if self.latest and timestamp_ms<=self.latest.timestamp_ms:
                timestamp_ms=self.latest.timestamp_ms+1
            self.sequence+=1;self.latest=Frame(self.sequence,timestamp_ms,jpeg,self.generation)
            self.ready=True;self.message='';self.capture_times.append(timestamp_ms)
            self.capture_latencies.append(capture_latency_ms)
            if self.started_ms is None:self.started_ms=timestamp_ms

    def take_latest(self):
        with self.lock:
            if not self.ready or self.inference_error or self.pending is not None or self.latest is None or self.latest.id<=self.submitted:
                return None
            if self.latest.generation!=self.generation:return None
            self.pending=self.latest;self.submitted=self.latest.id
            return self.pending

    def complete(self, frame, observations, now_ms, width, height):
        with self.lock:
            if self.pending is None or self.pending.id!=frame.id:return False
            self.pending=None
            if not self.ready or self.inference_error or frame.generation!=self.generation:return False
            if now_ms<frame.timestamp_ms or now_ms-frame.timestamp_ms>=self.engine.config.lost_ms:
                self.engine.stop('识别结果超时');self.tracker.previous={};return False
            if self.engine.timestamp_ms>=0 and frame.timestamp_ms-self.engine.timestamp_ms>self.engine.config.lost_ms:
                self.tracker.previous={}
            tracked=self.tracker.update(observations)
            self.engine.process(frame.id,frame.timestamp_ms,tracked,now_ms,width,height)
            self.last_dimensions=(width,height);self.published=frame
            self.processed+=1;self.result_times.append(now_ms)
            self.latencies.append(now_ms-frame.timestamp_ms)
            state=self.engine.snapshot(now_ms)
            completed=[h['metrics'].get('knead_completed_at_ms') for h in state['hands'] if h.get('metrics',{}).get('knead_completed_this_frame')]
            event=max((t for t in completed if t is not None),default=frame.timestamp_ms)
            self.trials.observe(now_ms,state['observation_gesture'],frame.timestamp_ms,state['raw_gesture'],event)
            self.trials.tick(now_ms)
            return True

    def error(self, message, capture_generation=None):
        with self.lock:
            if capture_generation is not None and capture_generation!=self.generation:return False
            self.message=str(message);self.ready=False;self.generation+=1
            self.engine.stop('摄像头或识别服务异常');self.engine.states.clear();self.tracker.previous={}
            return True

    def fail_inference(self, message):
        with self.lock:
            self.inference_error=str(message);self.pending=None
            self.engine.stop('手节点检测异常');self.engine.states.clear()

    def reset(self, config=None):
        with self.lock:
            if config is not None:config.validate()
            self.engine=GestureEngine(config or self.engine.config)
            self.tracker=HandTracker();self.published=None
            self.generation+=1

    # 启用输出或切换来源时建立新确认代际，禁止缓存中的旧确认重新启动舵机。
    def reset_confirmation(self, now_ms):
        with self.lock:
            self.reset()
            self.pending=None;self.latest=None;self.ready=False
            # Capture errors belong to the previous request generation. Model
            # errors stay sticky until the recognition service is restarted.
            self.message=''
            self.confirmation_reset_monotonic_ms=now_ms
            self.confirmation_generation+=1
            return {'ok':True,'confirmation_reset_monotonic_ms':now_ms,
                    'confirmation_generation':self.confirmation_generation,'recognition_instance_id':self.recognition_instance_id}

    @staticmethod
    def rate(times, now):
        recent=[t for t in times if now-t<=3000]
        if len(recent)<2 or now-recent[-1]>800:return 0.
        return round((len(recent)-1)*1000/(recent[-1]-recent[0]),2)

    @staticmethod
    def percentile(values, fraction):
        if not values:return None
        ordered=sorted(values)
        return round(ordered[max(0,math.ceil(len(ordered)*fraction)-1)],2)

    def snapshot(self, now_ms, include_image=False):
        with self.lock:
            self.trials.tick(now_ms)
            if self.pending and now_ms-self.pending.timestamp_ms>2000:
                self.inference_error='手节点检测响应超时，请重新打开启动程序'
            if self.inference_error:self.engine.stop('手节点检测异常')
            state=copy.deepcopy(self.engine.snapshot(now_ms))
            frame=self.published or self.latest
            # A preview before the first result has no matching landmark overlay.
            if self.published is None:
                state.update(hands=[],confirmed_this_frame=False,observation_gesture='stop',hand_present=False,
                             observation_state='error',knead_kind='none')
                state['frame_id']=frame.id if frame else -1
                state['capture_monotonic_ms']=frame.timestamp_ms if frame else -1
                state['frame_age_ms']=max(0,now_ms-frame.timestamp_ms) if frame else None
            age=None if self.latest is None else max(0,now_ms-self.latest.timestamp_ms)
            state.update(ready=self.ready and not self.inference_error and age is not None and age<self.engine.config.lost_ms,
                         error=self.inference_error or self.message, width=self.last_dimensions[0],height=self.last_dimensions[1],
                         capture_frame_id=self.sequence,capture_age_ms=age,
                         capture_monotonic_ms_latest=self.latest.timestamp_ms if self.latest else None,
                         capture_fps=self.rate(self.capture_times,now_ms),inference_fps=self.rate(self.result_times,now_ms),
                         processed_frames=self.processed,dropped_frames=max(0,self.sequence-self.processed-(1 if self.pending else 0)),
                         latency_p50_ms=self.percentile(self.latencies,.5),latency_p95_ms=self.percentile(self.latencies,.95),
                         capture_p95_ms=self.percentile(self.capture_latencies,.95),
                         trials={'active':copy.deepcopy(self.trials.active),'summary':self.trials.summary(),'records':copy.deepcopy(self.trials.records[-60:])},
                         config=asdict(self.engine.config))
            state['server_monotonic_ms']=now_ms
            state['application']='watcher-handnodes'
            state['capture_session_id']=self.capture_session_id
            state['recognition_instance_id']=self.recognition_instance_id
            state['transport']=self.transport
            state['camera_session_id']=self.published.remote_session_id if self.published else None
            state['camera_frame_id']=self.published.remote_frame_id if self.published else None
            state['api_version']=2
            state['confirmation_generation']=self.confirmation_generation
            state['confirmation_reset_monotonic_ms']=self.confirmation_reset_monotonic_ms
            if include_image:state['image_base64']=base64.b64encode(frame.jpeg).decode() if frame else ''
            return state

    def calibrate_back(self, now_ms):
        with self.lock:
            state=self.engine.snapshot(now_ms)
            candidates=[h for h in state['hands'] if h.get('metrics',{}).get('folded')==[True]*4]
            if state['frame_age_ms'] is None or state['frame_age_ms']>self.engine.config.lost_ms or not candidates:
                raise ValueError('请把手背朝向摄像头，四指握拳并稍微张开拇指')
            h=max(candidates,key=lambda v:v['metrics']['palm_px']);normal=h['metrics']['normal_z']
            if abs(normal)<self.engine.config.back_normal_min:raise ValueError('请正对摄像头，避免手掌侧立')
            side=h['handedness']
            if side not in ('Left','Right'):raise ValueError('左右手信息不确定，请调整姿势')
            c=Config(**asdict(self.engine.config));c.back_sign_by_hand[side]=1 if normal>0 else -1
            self.reset(c)
            return side

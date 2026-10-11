"""Bounded gesture intent. Camera duplicates never extend a command lease."""
import math
import re
import time

GESTURES = {'stop': 0, 'pounding': 1, 'kneading': 2, 'pinch': 3}


class IntentEngine:
    def __init__(self):
        self.source = 'simulation'
        self.gesture = 'stop'
        self.deadline = 0
        self.last_capture = -1
        self.last_session = None
        self.last_sent = None
        self.last_fault = False
        self.minimum_confirmation_generation = 0
        self.last_proof = None
        self.publication_wait_until = 0
        self.recognition_instance_id = None

    def simulate(self, gesture, duration_ms, now):
        if gesture not in GESTURES or type(duration_ms) is not int or not 100 <= duration_ms <= 5000:
            raise ValueError('请选择有效手势，模拟时间应在 100–5000 毫秒之间')
        self.source = 'simulation'
        self.gesture = gesture
        self.deadline = now + duration_ms / 1000
        self.last_sent = None

    def stop(self):
        self.source = 'simulation'
        self.gesture = 'stop'
        self.deadline = 0
        self.last_sent = None

    def set_source(self, source):
        if source not in ('simulation', 'camera'):
            raise ValueError('无效输入来源')
        self.source = source
        self.gesture = 'stop'
        self.deadline = 0
        self.last_sent = None

    def confirmation_barrier(self, generation, instance_id=None):
        if type(generation) is not int or generation < 0:
            raise ValueError('确认屏障无效')
        if instance_id is not None:
            if not isinstance(instance_id,str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,96}',instance_id):
                raise ValueError('识别服务实例无效')
            self.recognition_instance_id=instance_id
        self.minimum_confirmation_generation=generation
        self.last_capture=-1;self.last_session=None;self.last_proof=None
        self.gesture='stop';self.deadline=0;self.last_sent='stop'
        self.publication_wait_until=time.monotonic()+.8

    @staticmethod
    def camera_age(camera, now):
        age=camera.get('frame_age_ms');received=camera.get('received_monotonic_ms')
        if type(age) not in (int,float) or not math.isfinite(age):return float('inf')
        if type(received) in (int,float) and math.isfinite(received):
            elapsed=now*1000-received
            return age+max(0,elapsed) if elapsed>=-1 else float('inf')
        capture=camera.get('capture_monotonic_ms')
        if type(capture) in (int,float) and math.isfinite(capture):
            elapsed=now*1000-capture
            return max(age,elapsed) if elapsed>=-100 else float('inf')
        return float('inf')

    def awaiting_publication(self, camera, now):
        # Resetting confirmation deliberately clears the published proof. This
        # bounded wait cannot forward a command, and never hides a real error.
        generation=camera.get('confirmation_generation')
        return (camera.get('observation_version')==2 and
                type(generation) is int and generation>=self.minimum_confirmation_generation and
                (self.recognition_instance_id is None or
                 camera.get('recognition_instance_id')==self.recognition_instance_id) and
                camera.get('camera_session_id') is None and camera.get('camera_frame_id') is None and
                not camera.get('error') and now<self.publication_wait_until)

    def _observation_step(self, camera, now):
        instance=camera.get('recognition_instance_id')
        if self.recognition_instance_id is not None and instance!=self.recognition_instance_id:
            return self._stop_once(fault=True)  # Dashboard must disable and reset the new service first.
        if self.recognition_instance_id is None and isinstance(instance,str):self.recognition_instance_id=instance
        generation=camera.get('confirmation_generation')
        if type(generation) is not int or generation<self.minimum_confirmation_generation:return None
        age=self.camera_age(camera,now)
        state=camera.get('observation_state');confirmed=camera.get('confirmed_this_frame')
        present=camera.get('hand_present');label=camera.get('observation_gesture')
        kind=camera.get('knead_kind');confirmation_age=camera.get('confirmation_age_ms')
        session=camera.get('camera_session_id');frame=camera.get('camera_frame_id')
        if self.awaiting_publication(camera,now):
            return None
        valid=(camera.get('ready') is True and 0<=age<800 and
               isinstance(session,str) and bool(re.fullmatch(r'[A-Za-z0-9_.-]{1,96}',session)) and
               type(frame) is int and 1<=frame<=0xffffffff and
               state in ('confirmed','confirming','unrecognized','no_hand','conflict','error') and
               type(confirmed) is bool and type(present) is bool and kind in ('none','static_curl','cycle') and
               type(confirmation_age) is int and 0<=confirmation_age<=2500 and
               ((state=='confirmed' and confirmed and present and label in GESTURES and label!='stop' and
                 confirmation_age>0) or (state!='confirmed' and not confirmed and label=='stop' and confirmation_age==0)))
        if not valid:return self._stop_once(fault=True)
        proof=(session,frame)
        if proof==self.last_proof:
            return self._stop_once(fault=True) if now>=self.deadline else None
        if self.last_proof and session==self.last_proof[0] and frame<=self.last_proof[1]:return None
        self.publication_wait_until=0
        self.last_proof=proof;self.last_capture=camera.get('capture_monotonic_ms',-1)
        self.gesture=label;self.deadline=now+(800-age)/1000
        payload=self._payload()
        payload.update(observation_version=2,observation_state=state,confirmed_this_frame=confirmed,
                       hand_present=present,knead_kind=kind,confirmation_age_ms=confirmation_age,
                       confirmation_generation=generation,camera_session_id=session,camera_frame_id=frame,
                       frame_age_ms=int(math.ceil(age)))
        return payload

    def _payload(self, lease=600):
        self.last_sent = self.gesture
        self.last_fault = False
        return {'gesture': self.gesture, 'source': self.source, 'lease_ms': lease}

    def _stop_once(self, fault=False):
        self.gesture = 'stop'
        if self.last_sent=='stop' and (not fault or self.last_fault):return None
        payload=self._payload();self.last_fault=fault
        return payload

    def step(self, camera, now):
        if self.source == 'simulation':
            if self.gesture != 'stop' and now < self.deadline:
                remaining = int((self.deadline - now) * 1000 + .001)
                return self._payload(min(600, remaining)) if remaining >= 100 else self._stop_once()
            return self._stop_once()

        camera = camera or {}
        if camera.get('observation_version')==2:
            return self._observation_step(camera,now)
        age = camera.get('frame_age_ms')
        capture = camera.get('capture_monotonic_ms')
        label = camera.get('gesture')
        received = camera.get('received_monotonic_ms')
        if isinstance(received, (int, float)) and math.isfinite(received) and isinstance(age, (int, float)):
            # Python runtimes may expose different monotonic epochs. The poller
            # attaches its own receive timestamp; remote capture time is only an
            # ordering/duplicate identity, never a cross-process deadline.
            elapsed = now * 1000 - received
            age = age + max(0, elapsed) if elapsed >= -1 else float('inf')
        elif isinstance(capture, (int, float)) and math.isfinite(capture) and isinstance(age, (int, float)):
            elapsed = now * 1000 - capture
            age = max(age, elapsed) if elapsed >= -100 else float('inf')
        valid = (camera.get('ready') is True and camera.get('frame_id') is not None
                 and isinstance(age, (int, float)) and math.isfinite(age) and 0 <= age < 800
                 and isinstance(capture, (int, float)) and math.isfinite(capture)
                 and label in GESTURES)
        wifi=camera.get('transport')=='wifi'
        proof_session=camera.get('camera_session_id')
        proof_id=camera.get('camera_frame_id')
        if wifi:
            valid=valid and isinstance(proof_session,str) and bool(re.fullmatch(r'[A-Za-z0-9_.-]{1,96}',proof_session)) and type(proof_id)is int and 1<=proof_id<=0xffffffff
        if not valid:
            return self._stop_once(fault=True)
        session = camera.get('capture_session_id')
        if isinstance(session, str) and session and session != self.last_session:
            self.last_session = session
            self.last_capture = -1
            self.deadline = 0
        if capture > self.last_capture:
            self.last_capture = capture
            self.gesture = label
            lease = max(100, min(600, int(600 - age)))
            if age > 500:
                return self._stop_once(fault=True)
            self.deadline = now + lease / 1000
            payload=self._payload(lease)
            if wifi:
                payload.update(camera_session_id=proof_session,camera_frame_id=proof_id,
                               frame_age_ms=int(math.ceil(age)))
            return payload
        if now >= self.deadline:
            return self._stop_once(fault=True)
        return None

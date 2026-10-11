# 手势规则层：只分析模型已给出的节点，不采集摄像头、不直接驱动舵机。
# 阈值保存在 Config；距离除以掌长，减小摄像距离变化对判断的影响。
"""Deterministic landmark rules. No camera, ML runtime, or actuator dependencies."""
from dataclasses import asdict, dataclass, field
import math


@dataclass
class Config:
    pinch_enter: float = .25
    pinch_exit: float = .35
    pinch_spread_min: float = .7
    folded_angle: float = 145.
    extended_angle: float = 150.
    extended_reach_ratio: float = 1.1
    extended_tip_length_min: float = .6
    palm_min_px: float = 30.
    thumb_open_min: float = .15
    thumb_open_max: float = 1.25
    pound_thumb_enter: float = 1.00
    pound_thumb_hold: float = 1.05
    knead_static_thumb_enter: float = 1.15
    knead_static_thumb_hold: float = 1.10
    knead_static_thumb_length_max: float = 2.4
    thumb_length_max: float = 1.95
    back_normal_min: float = .45
    knead_closed: float = .55
    knead_open: float = .85
    knead_outlier_margin: float = .4
    knead_motion_min: float = .35
    knead_angle_change_min: float = 10.
    knead_curl_tip_max: float = .65
    knead_curl_spread_max: float = 1.
    knead_curl_motion_min: float = .4
    cycle_min_ms: int = 400
    cycle_max_ms: int = 2500
    phase_min_ms: int = 80
    confirm_ms: int = 300
    confirm_frames: int = 3
    lost_ms: int = 800
    back_sign_by_hand: dict = field(default_factory=lambda: {'Left': 0, 'Right': 0})

    def validate(self):
        for name, value in asdict(self).items():
            if name == 'back_sign_by_hand':
                if set(value) != {'Left', 'Right'} or any(type(v) is not int or v not in (-1, 0, 1) for v in value.values()):
                    raise ValueError('手背校准值无效')
            elif isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError('参数必须为有限正数：' + name)
        if not self.pinch_enter < self.pinch_exit < self.knead_closed < self.knead_open:
            raise ValueError('捏合进入、退出、五指聚拢和松开阈值须依次递增')
        if not 0 < self.folded_angle < self.extended_angle < 180:
            raise ValueError('关节角度阈值无效')
        if not self.cycle_min_ms < self.cycle_max_ms or self.phase_min_ms >= self.cycle_min_ms:
            raise ValueError('揉搓周期范围无效')
        if self.confirm_ms >= self.lost_ms or not 2 <= self.confirm_frames <= 20:
            raise ValueError('确认与停止参数无效')
        if not self.thumb_open_min < self.thumb_open_max or self.back_normal_min > 1:
            raise ValueError('拇指或掌面参数无效')
        if not (self.pound_thumb_enter <= self.pound_thumb_hold < self.knead_static_thumb_hold <= self.knead_static_thumb_enter):
            raise ValueError('捶打与静态揉搓的拇指阈值须分离')
        for name in ('cycle_min_ms', 'cycle_max_ms', 'phase_min_ms', 'confirm_ms', 'confirm_frames', 'lost_ms'):
            if type(getattr(self, name)) is not int:
                raise ValueError('时间与帧数须为整数：' + name)
        return self


def distance(a, b, dimensions=3):
    return math.sqrt(sum((a[i]-b[i])**2 for i in range(dimensions)))


def angle(a, b, c):
    u, v = [a[i]-b[i] for i in range(3)], [c[i]-b[i] for i in range(3)]
    denominator = distance(a,b)*distance(c,b)
    if denominator < 1e-9:
        raise ValueError('重复节点无法计算角度')
    return math.degrees(math.acos(max(-1, min(1, sum(x*y for x,y in zip(u,v))/denominator))))


def valid_points(points):
    return (isinstance(points, list) and len(points) == 21 and
            all(isinstance(p, (list, tuple)) and len(p) == 3 and
                all(isinstance(v, (int,float)) and not isinstance(v,bool) and math.isfinite(v) for v in p) for p in points))


# 先验证 21 节点，再还原图像尺度；指尖距离、弯曲角度和掌面法向用于不同手势规则。
def features(observation, width, height, config):
    landmarks = observation.get('landmarks')
    if not valid_points(landmarks):
        raise ValueError('缺少有效的 21 个节点')
    if any(not -.05 <= p[0] <= 1.05 or not -.05 <= p[1] <= 1.05 for p in landmarks):
        raise ValueError('请将整只手放入画面')
    # Normalized x and y have different scales in a 640x480 image.
    p = [[x*width,y*height,z*width] for x,y,z in landmarks]
    palm = distance(p[0],p[9],2)
    if palm < config.palm_min_px:
        raise ValueError('手掌太小，请靠近摄像头')
    world = observation.get('world_landmarks')
    geometry = world if valid_points(world) else p
    angles = [angle(geometry[i],geometry[i+1],geometry[i+2]) for i in (5,9,13,17)]
    folded = [a < config.folded_angle and distance(p[i+3],p[0],2) < distance(p[i+1],p[0],2) for a,i in zip(angles,(5,9,13,17))]
    extended = [a > config.extended_angle and
                distance(p[i+3],p[0],2) > config.extended_reach_ratio*distance(p[i+1],p[0],2) and
                distance(p[i+3],p[i],2) > config.extended_tip_length_min*palm for a,i in zip(angles,(5,9,13,17))]
    u,v = [[p[j][i]-p[0][i] for i in range(3)] for j in (5,17)]
    normal = [u[1]*v[2]-u[2]*v[1],u[2]*v[0]-u[0]*v[2],u[0]*v[1]-u[1]*v[0]]
    length = math.sqrt(sum(n*n for n in normal))
    normal_z = normal[2]/length if length > 1e-6 else 0.
    return {'palm_px':palm,'angles':angles,'folded':folded,'extended':extended,
            'pinch_ratio':distance(p[4],p[8],2)/palm,
            'thumb_open_ratio':distance(p[4],p[5],2)/palm,
            'thumb_length_ratio':distance(p[4],p[0],2)/palm,
            'tip_thumb_ratios':[distance(p[4],p[i],2)/palm for i in (8,12,16,20)],
            'tip_mcp_ratios':[distance(p[i+3],p[i],2)/palm for i in (5,9,13,17)],
            'tip_cluster_ratio':max(distance(p[a],p[b],2)/palm
                                    for a in (8,12,16,20) for b in (8,12,16,20)),
            'normal_z':normal_z}


# 每只手单独保存开合阶段与确认帧，避免把两只手或两次入镜的动作拼成揉搓周期。
class HandState:
    def __init__(self):
        self.pinching = False
        self.pounding = False
        self.static_kneading = False
        self.confirmation_label = 'stop'
        self.confirmation_times = []
        self.phase = 'waiting'
        self.cycle_start = None
        self.phase_at = None
        self.completed_at = None
        self.active_until = -1
        self.last_seen = -1
        self.open_ratios = None
        self.open_angles = None
        self.open_lengths = None

    def classify(self, f, side, t, c):
        # 轻捏：拇指与食指靠近，且其他手指有足够展开；进入/退出阈值不同，减少抖动。
        threshold = c.pinch_exit if self.pinching else c.pinch_enter
        self.pinching = (f['pinch_ratio'] < threshold and
                        sum(extended and ratio >= c.pinch_spread_min
                            for extended,ratio in zip(f['extended'][1:],f['tip_thumb_ratios'][1:])) >= 2)
        sign = c.back_sign_by_hand.get(side,0)
        back = bool(sign) and f['normal_z']*sign >= c.back_normal_min
        # 捶打保留手背校准；四指握拳且拇指微开，不能仅凭指尖接近来认定。
        pound_threshold = c.pound_thumb_hold if self.pounding else c.pound_thumb_enter
        pounding = (back and all(f['folded']) and
                    c.thumb_open_min <= f['thumb_open_ratio'] <= min(c.thumb_open_max, pound_threshold) and
                    f['thumb_length_ratio'] <= c.thumb_length_max and f['pinch_ratio'] > c.pinch_exit)
        ratios = f['tip_thumb_ratios']
        # Require index/thumb contact and three converging fingertips. One
        # bounded pinky estimate may lag during the user's gradual gathering.
        gathered = (f['pinch_ratio'] <= c.pinch_exit and
                  sum(r <= c.knead_closed for r in ratios) >= 3 and
                  max(ratios) <= c.knead_closed+c.knead_outlier_margin)
        lengths = f.get('tip_mcp_ratios')
        curled = (lengths is not None and sum(r <= c.knead_curl_tip_max for r in lengths) >= 3
                  and sum(f['folded']) >= 2 and not any(f['extended'])
                  and f.get('tip_cluster_ratio', float('inf')) <= c.knead_curl_spread_max)
        # 静态揉搓：四指收拢且拇指明显伸出，不限定掌面朝向；与捶打拇指阈值分离。
        static_threshold = c.knead_static_thumb_hold if self.static_kneading else c.knead_static_thumb_enter
        self.static_kneading = (curled and f['thumb_open_ratio'] >= static_threshold and
                                f['thumb_length_ratio'] <= c.knead_static_thumb_length_max)
        # 动态揉搓必须有新完成的开合周期；静止收拢和旧周期不会产生新的动作确认。
        completed_this_frame = False
        completed_cycle_start = None
        closed = gathered or curled
        # A thumb held to the side makes all tip-to-thumb distances large even
        # with four curled fingers. Such a hand must not count as open as well.
        opened = not closed and (sum(f['extended']) >= 3 or
                    (sum(f['folded']) <= 1 and sum(r >= c.knead_open for r in ratios) >= 3))
        def moving_count():
            gathering = sum(a-b >= c.knead_motion_min for a,b in zip(self.open_ratios or [],ratios))
            curling = sum(a-b >= c.knead_curl_motion_min for a,b in zip(self.open_lengths or [],lengths or []))
            # A thumb moving toward an otherwise stationary fist is not a
            # four-finger curl. Only genuine tip-to-thumb gathering may use
            # the distance-to-thumb motion test.
            return gathering if gathered else curling if curled else max(gathering, curling)
        if self.phase == 'opened' and self.cycle_start is None and self.open_ratios:
            moving=moving_count()
            if moving >= 3:
                # Movement started between the last observation and this one.
                # Holding an open hand during preparation consumes no cycle time.
                self.cycle_start=max(self.phase_at,self.last_seen)
        if self.cycle_start is not None and t-self.cycle_start > c.cycle_max_ms:
            self.phase = 'waiting'; self.cycle_start = None
            self.open_ratios = self.open_angles = None
            self.open_lengths = None
        if self.phase == 'waiting' and closed:
            self.phase='closed';self.cycle_start=t;self.phase_at=t
        elif self.phase == 'waiting' and opened:
            self.phase='opened';self.cycle_start=None;self.phase_at=t
            self.open_ratios=list(ratios);self.open_angles=list(f['angles'])
            self.open_lengths=list(lengths) if lengths is not None else None
        elif self.phase == 'closed' and opened and t-self.phase_at >= c.phase_min_ms:
            self.phase='opened';self.cycle_start=max(self.phase_at,self.last_seen);self.phase_at=t
            self.open_ratios=list(ratios);self.open_angles=list(f['angles'])
            self.open_lengths=list(lengths) if lengths is not None else None
        elif self.phase == 'opened' and closed and t-self.phase_at >= c.phase_min_ms:
            duration=0 if self.cycle_start is None else t-self.cycle_start
            moving_fingers=moving_count()
            bending_fingers=sum(a-b >= c.knead_angle_change_min for a,b in zip(self.open_angles,f['angles']))
            if c.cycle_min_ms <= duration <= c.cycle_max_ms and moving_fingers >= 3 and bending_fingers >= 2:
                self.completed_at=t;self.active_until=t+c.lost_ms
                completed_this_frame = True
                completed_cycle_start = self.cycle_start
            self.phase='closed';self.cycle_start=t;self.phase_at=t
            self.open_ratios = self.open_angles = None
            self.open_lengths = None
        # Only the closing frame of a newly completed cycle is an event.
        # Old cycle history must neither refresh a lease nor hide a new target.
        kneading = self.static_kneading or completed_this_frame
        self.pounding = pounding and not completed_this_frame
        candidates = [name for name,yes in [('pounding',self.pounding),('kneading',kneading),('pinch',self.pinching)] if yes]
        self.last_seen=t
        f.update(back_calibrated=bool(sign), back_facing=back, knead_phase=self.phase,
                 all_fingers_closed=closed, all_fingers_open=opened, candidates=candidates,
                 knead_closed_kind='curl' if curled else 'gather' if gathered else 'none',
                 knead_completed_at_ms=self.completed_at, knead_completed_this_frame=completed_this_frame,
                 knead_cycle_start_ms=completed_cycle_start,
                 knead_kind='cycle' if completed_this_frame else 'static_curl' if self.static_kneading else 'none')
        return candidates


class GestureEngine:
    def __init__(self, config=None):
        self.config=(config or Config()).validate()
        self.states={}
        self.frame_id=-1;self.timestamp_ms=-1;self.last_valid_ms=None
        self.raw='stop';self.stable='stop';self.reason='等待摄像头画面'
        self.candidate='stop';self.candidate_at=0;self.candidate_frames=0
        self.hands=[]
        self.candidate_ids=set();self.stable_ids=set()
        self._observation('error')

    def _observation(self, state, gesture='stop', hand_present=False, knead_kind='none', confirmed=False, confirmation_age_ms=0):
        self.observation_state=state
        self.hand_present=hand_present
        self.confirmed_this_frame=confirmed
        self.observation_gesture=gesture if confirmed else 'stop'
        self.knead_kind=knead_kind
        self.confirmation_age_ms=confirmation_age_ms if confirmed else 0

    def stop(self, reason, preserve_motion=False, observation_state='error', hand_present=False):
        self.raw=self.stable=self.candidate='stop';self.candidate_frames=0
        self.last_valid_ms=None;self.reason=reason
        if preserve_motion:
            for state in self.states.values():
                state.completed_at=None;state.active_until=-1
        else:
            self.states.clear()
        self.candidate_ids=set();self.stable_ids=set()
        self._observation(observation_state,hand_present=hand_present)

    # 一帧只接受一次；静态确认需至少三个不同帧和 300ms，冲突或异常不启动动作。
    def process(self, frame_id, timestamp_ms, hands, now_ms, width=640, height=480):
        self.snapshot(now_ms)
        if now_ms < timestamp_ms or now_ms-timestamp_ms >= self.config.lost_ms:
            self.stop('画面或识别结果已过期');return
        if frame_id <= self.frame_id:
            # A repeated callback is not a newly confirmed observation.
            self._observation('unrecognized',hand_present=self.hand_present)
            return
        if timestamp_ms <= self.timestamp_ms:
            self.stop('画面时间异常');return
        if self.timestamp_ms >= 0 and timestamp_ms-self.timestamp_ms >= self.config.lost_ms:
            self.stop('画面间隔过长')
        self.frame_id=frame_id;self.timestamp_ms=timestamp_ms;self.hands=[]
        all_candidates=[];ambiguous=False;current_ids=set();valid_ids=set()
        for observation in hands[:2]:
            identity=str(observation.get('id',''))
            current_ids.add(identity)
            try:
                f=features(observation,width,height,self.config)
                state=self.states.setdefault(identity,HandState())
                candidates=state.classify(f,observation.get('handedness'),timestamp_ms,self.config)
                valid_ids.add(identity)
                ambiguous |= len(candidates)>1
                all_candidates.extend(candidates)
                reason=('揉搓：已收拢，请松开后再次收拢' if f['knead_phase']=='closed' and f['all_fingers_closed'] else
                        '请先校准这只手的手背朝向' if all(f['folded']) and not f['back_calibrated'] else
                        '揉搓：已张开，请逐渐收拢手指' if f['knead_phase']=='opened' else '未满足目标手势规则')
                self.hands.append(dict(observation,id=identity,metrics=f,raw_gesture=candidates[0] if len(candidates)==1 else 'stop',reason='' if candidates else reason))
            except (ValueError,TypeError,IndexError) as e:
                self.states.pop(identity,None)
                self.hands.append(dict(observation,id=identity,raw_gesture='stop',reason=str(e),metrics={}))
        # A missing hand must not combine movements across separate appearances.
        self.states={key:value for key,value in self.states.items() if key in current_ids}
        choices=set(all_candidates)
        if ambiguous or len(choices)>1:
            self.stop('手势规则或双手结果冲突',observation_state='conflict',hand_present=bool(valid_ids));return
        self.raw=next(iter(choices),'stop')
        if self.raw == 'stop':
            self.candidate='stop';self.candidate_frames=0;self.candidate_ids=set()
            self.reason=(self.hands[0]['reason'] if len(self.hands)==1 else '未识别到目标手势') if hands else '未检测到手'
            for state in self.states.values():
                state.confirmation_label='stop';state.confirmation_times=[]
            self._observation('unrecognized' if valid_ids else 'error' if hands else 'no_hand',hand_present=bool(valid_ids))
            return
        self.last_valid_ms=timestamp_ms
        qualifying=[h for h in self.hands if h['raw_gesture']==self.raw]
        qualifying_ids={h['id'] for h in qualifying}
        cycle_completed=any(h['metrics'].get('knead_completed_this_frame') for h in qualifying)
        kind='cycle' if cycle_completed else 'static_curl' if self.raw=='kneading' else 'none'
        if self.raw == 'kneading' and cycle_completed:
            self.stable='kneading';self.stable_ids=qualifying_ids
            self.candidate='stop';self.candidate_frames=0;self.candidate_ids=set()
            self.reason='已完成新的揉搓开合周期'
            cycle_ages=[timestamp_ms-h['metrics']['knead_cycle_start_ms'] for h in qualifying
                        if h['metrics'].get('knead_completed_this_frame')]
            for state in self.states.values():
                state.confirmation_label='stop';state.confirmation_times=[]
            self._observation('confirmed','kneading',True,kind,True,min(cycle_ages))
            return
        if self.stable != 'stop' and self.stable != self.raw:
            self.stable='stop'
        if self.stable==self.raw and not self.stable_ids.intersection(qualifying_ids):
            self.stable='stop'
        # Every hand owns its own latest complete confirmation window. Once
        # confirmed, the window slides; an old first frame cannot grow its age
        # indefinitely or be reused across an ARM barrier.
        eligible={}
        for identity,state in self.states.items():
            if identity not in qualifying_ids:
                state.confirmation_label='stop';state.confirmation_times=[];continue
            if state.confirmation_label!=self.raw:
                state.confirmation_label=self.raw;state.confirmation_times=[]
            samples=state.confirmation_times
            samples.append(timestamp_ms)
            while samples and timestamp_ms-samples[0]>=self.config.lost_ms:
                samples.pop(0)
            while (len(samples)>self.config.confirm_frames and
                   timestamp_ms-samples[1]>=self.config.confirm_ms):
                samples.pop(0)
            if len(samples)>=self.config.confirm_frames and timestamp_ms-samples[0]>=self.config.confirm_ms:
                eligible[identity]=timestamp_ms-samples[0]
        self.candidate=self.raw;self.candidate_ids=qualifying_ids
        self.candidate_frames=max((len(self.states[i].confirmation_times) for i in qualifying_ids),default=0)
        if eligible:
            self.stable=self.raw;self.stable_ids=set(eligible);self.reason='手势已稳定确认'
            self._observation('confirmed',self.raw,True,kind,True,min(eligible.values()))
        else:
            self.reason='正在确认手势'
            self._observation('confirming',hand_present=True,knead_kind=kind)

    def snapshot(self, now_ms):
        age=None if self.timestamp_ms<0 else max(0,now_ms-self.timestamp_ms)
        if age is not None and age>=self.config.lost_ms:
            self.stop('摄像头画面超时')
        elif self.last_valid_ms is not None and now_ms-self.last_valid_ms>=self.config.lost_ms:
            # Expire only the compatibility stable label; preserve the latest
            # no-hand / unrecognized result that explains why it disappeared.
            observation=(self.observation_state,self.hand_present,self.knead_kind)
            self.stop('有效手势已消失',preserve_motion=True)
            self._observation(observation[0],hand_present=observation[1],knead_kind=observation[2])
        return {'frame_id':self.frame_id,'capture_monotonic_ms':self.timestamp_ms,
                'frame_age_ms':age,'raw_gesture':self.raw,'gesture':self.stable,
                'reason':self.reason,'confirm_frames':self.candidate_frames,'hands':self.hands,
                'observation_version':2,'observation_state':self.observation_state,
                'confirmed_this_frame':self.confirmed_this_frame,'hand_present':self.hand_present,
                'observation_gesture':self.observation_gesture,'knead_kind':self.knead_kind,
                'confirmation_age_ms':self.confirmation_age_ms,
                'actuator_enabled':False}

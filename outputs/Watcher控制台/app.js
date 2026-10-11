(() => {
  'use strict';
  const $ = (id) => document.getElementById(id);
  const names = { stop: '停止', pounding: '捶打', kneading: '揉搓', pinch: '轻捏' };
  const modes = ['stop', 'pounding', 'kneading', 'pinch'];
  const state = { status: null, backendOnline: false, pollPromise: null, busy: false, calibrating: false, actionId: 0, actionController: null, logs: [], frameId: null, expression: null, hands: [], profileDirty: false, profileSignature: null, testPulsePristine: true, observation: null, lastTestId: null };
  const handConnections = [[0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [5, 9], [9, 10], [10, 11], [11, 12], [9, 13], [13, 14], [14, 15], [15, 16], [13, 17], [0, 17], [17, 18], [18, 19], [19, 20]];

  function text(id, value) { $(id).textContent = value; }
  function setConnection(id, label, kind = '') { const el = $(id); el.textContent = label; el.className = `connection ${kind}`; }
  function feedback(message, kind = '', target = 'control-feedback') { const el = $(target); el.textContent = message; el.className = `${target === 'control-feedback' ? 'control-feedback' : 'inline-feedback'} ${kind}`; }
  function setError(id, message) { const el = $(id); el.hidden = !message; el.textContent = message || ''; }
  function timeLabel(value) { const date = new Date(value); return Number.isNaN(date.getTime()) ? String(value || '—') : date.toLocaleTimeString('zh-CN', { hour12: false }); }
  function gestureName(value) { return names[value] || '未识别'; }

  function watcherAwake() { return WatcherUI.powerAllowsActions(state.status?.watcher?.data); }
  function powerHint() {
    const power = state.status?.watcher?.data?.power_state;
    return power === 'standby' ? '小智已待机；长按滚轮 3 秒并松手恢复。' : power === 'shutting_down' ? '小智正在关机，停止请求仍可使用。' : '';
  }

  function expression(kind, animation = 'blink', display = {}) {
    const allowedAnimations = ['blink', 'breathe', 'nod', 'shake', 'pulse', 'thinking', 'none'];
    const gestureAnimations = { waiting: 'blink', pounding: 'nod', kneading: 'breathe', pinch: 'pulse', stop: 'breathe', error: 'thinking' };
    const selected = animation === true ? (gestureAnimations[kind] || 'blink') : animation === false ? 'none' : animation;
    const motion = allowedAnimations.includes(selected) ? selected : 'none';
    const gesture = {pounding: 1, kneading: 2, pinch: 3}[kind] || 0;
    const displayState = {waiting:'neutral',pounding:'angry',kneading:'relaxed',pinch:'happy',stop:'neutral',error:'thinking'}[kind] || 'neutral';
    const snapshot = {...display, expression_gesture: gesture, display_state: displayState};
    const key = `${kind}:${motion}:${display.power_state || 'active'}:${display.display_page || 'expression'}`;
    if (state.expression === key) return;
    state.expression = key;
    const preview = WatcherUI.applyPreview($('expression'), snapshot);
    $('expression').dataset.animation = preview.power === 'active' ? motion : 'none';
    $('expression').dataset.animate = String(preview.animate && motion !== 'none');
    text('expression-label', preview.label);
  }

  function servoProfile(status = state.status) {
    const profile = status?.servo?.profile;
    if (!profile || !Array.isArray(profile.neutral_us) || !Array.isArray(profile.run_us) || profile.neutral_us.length !== 3 || profile.run_us.length !== 3) return null;
    const valid = profile.neutral_us.every((neutral, index) => Number.isInteger(neutral) && neutral >= 1400 && neutral <= 1600 && neutral % 10 === 0 && Number.isInteger(profile.run_us[index]) && profile.run_us[index] > neutral && profile.run_us[index] <= 2000 && profile.run_us[index] % 10 === 0);
    return valid ? profile : null;
  }

  function servoGuards() {
    const status = state.status || {}, data = status.watcher?.data || {};
    const version2 = status.api_version === 2;
    const simulation = status.source === 'simulation' && status.observer_only !== true;
    const armed = status.servo?.armed === true;
    const stopped = status.requested_gesture === 'stop' && data.requested_mode === 0 && data.applied_mode === 0 && data.test_active !== true;
    const profileMatches = data.profile_match === true && !!servoProfile(status);
    const peerReady = status.watcher?.online === true && data.client_connected === true && data.hold_protocol === 2 && Number.isFinite(data.ack_age_ms) && data.ack_age_ms >= 0 && data.ack_age_ms < 600;
    const camera = status.camera?.data || {};
    const cameraReady = status.source === 'camera' && status.observer_only !== true && status.camera?.online === true && camera.ready === true && camera.observation_version === 2 && Number.isFinite(camera.frame_age_ms) && camera.frame_age_ms >= 0 && camera.frame_age_ms < 800 && !['error', 'conflict'].includes(camera.observation_state) && (data.camera_observation_version ?? data.mac_observation_version) === 2;
    const awake = watcherAwake();
    const canArm = awake && version2 && state.backendOnline && !state.busy && !armed && profileMatches && peerReady && (simulation || cameraReady);
    return { awake, version2, simulation, cameraReady, peerReady, canArm, armed, stopped, profileMatches, canTest: awake && version2 && state.backendOnline && !state.busy && simulation && armed && profileMatches && peerReady, canEdit: awake && version2 && state.backendOnline && !state.busy && simulation && stopped && !armed };
  }

  function servoConnectionHint(guards = servoGuards()) {
    const status = state.status || {}, data = status.watcher?.data || {};
    if (!state.backendOnline) return '控制服务未连接，请等待服务恢复。';
    if (!watcherAwake()) return powerHint();
    if (!guards.version2) return '当前控制服务不支持舵机校准，请等待新版服务。';
    if (status.watcher?.online !== true) return '小智未连接，请等待小智上线。';
    if (data.client_connected !== true) return '黑色板未连接小智，请检查 Wi-Fi 和连接状态，等待连接恢复。';
    if (data.hold_protocol !== 2) return '黑色板通信协议未就绪，请等待两块板完成协议确认。';
    if (!Number.isFinite(data.ack_age_ms) || data.ack_age_ms < 0) return '等待黑色板的有效回执，暂不可短测。';
    if (data.ack_age_ms >= 600) return '黑色板回执已过期，请等待通信恢复。';
    if (!servoProfile(status)) return '舵机配置尚不可用，请等待有效参数回报。';
    if (!guards.profileMatches) return '舵机配置未同步到黑色板，请等待配置同步。';
    return '';
  }

  function servoInactiveHint() {
    const status = state.status || {};
    const reason = status.output_enable_reason;
    if (status.watcher?.data?.output_policy_revision === 'continuous-enable-1' && status.watcher.data.default_output_enabled === true) {
      return reason === 'stopped' ? '已回中立；持续默认启用，等待新手势。' : '持续默认启用；设备和新鲜画面就绪后自动恢复，无需重复点击。';
    }
    if (reason === 'firmware_update') return '小智固件待更新，暂可手动启用输出；点击“启用输出”后，正常手势和短测无需重复启用。';
    if (status.default_enable_pending === true) return '设备已就绪，等待默认启用输出的设备确认；正常手势和短测无需重复启用。';
    if (reason === 'enabling') return '正在启用输出，等待黑色板确认。';
    if (reason === 'manual_disable') return '输出已手动禁用；需要恢复时点击“启用输出”，恢复后正常手势和短测无需重复启用。';
    if (reason === 'explicit_stop') return '已停止并禁用输出；如需继续，点击“启用输出”恢复。';
    if (reason === 'fault') return '输出因故障被禁用；连接与配置恢复后，点击“启用输出”继续。';
    if (reason === 'observer' || reason === 'source_changed') return '当前未启用输出；请在“控制与模拟”选择“模拟手势”或“Mac 摄像头诊断”。';
    return '当前输出未启用；设备就绪后可点击“启用输出”恢复。';
  }

  function servoEnableHint(guards = servoGuards()) {
    const connection = servoConnectionHint(guards);
    if (connection) return connection;
    if (state.status?.observer_only === true || state.status?.source === 'onboard') return '当前仅观察；请在“控制与模拟”选择“模拟手势”或“Mac 摄像头诊断”。';
    if (state.status?.source === 'camera' && !guards.cameraReady) return '摄像头观察尚未就绪，请等待有效画面和识别状态。';
    if (state.busy) return '正在处理指令，请等待设备确认。';
    if (!guards.armed) return servoInactiveHint();
    return state.status?.watcher?.data?.outputs_enabled === true ? (state.status.watcher.data.output_policy_revision === 'continuous-enable-1' ? '持续默认启用；动作结束或点击停止后回中立，下一次手势可直接运行。' : '输出已启用；正常手势和短测无需重复启用，可随时停止或禁用。') : '启用状态待同步，等待黑色板确认。';
  }

  function servoTestHint(guards = servoGuards()) {
    const connection = servoConnectionHint(guards);
    if (connection) return connection;
    if (state.status?.observer_only === true) return '当前仅观察；进入模拟诊断后可使用单路短测。';
    if (!guards.simulation) return '单路短测仅支持模拟来源；请到“控制与模拟”切换到“模拟手势”。';
    if (state.busy) return '正在处理指令，请等待设备确认后再短测。';
    if (!guards.armed) return servoInactiveHint();
    const profile = servoProfile(), index = Number($('servo-test-channel').value) - 1;
    const neutral = profile?.neutral_us[index], run = profile?.run_us[index];
    return `当前通道中立值为 ${neutral} µs，用于停转校准；要测试转动，点击“填入运行值”（${run} µs）。短测结束后自动回中立。`;
  }

  function servoProfileHint(guards = servoGuards()) {
    const connection = servoConnectionHint(guards);
    if (connection) return `${connection}${guards.canEdit ? ' 当前可编辑本地参数，保存后等待黑色板连接并同步，输出保持禁用。' : ''}`;
    if (state.status?.observer_only === true) return '当前仅观察；进入模拟诊断后可修改舵机配置。';
    if (!guards.simulation) return '请到“控制与模拟”切换到“模拟手势”，再修改配置。';
    if (state.busy) return '正在处理指令，请等待设备确认后再修改配置。';
    if (guards.armed) return '请到“控制与模拟”点击“禁用输出”，等待设备确认后再修改配置。';
    if (!guards.stopped) return '请先点击“停止 / 全部回中立”，等待中立确认后再修改配置。';
    return '当前输出已禁用，可修改配置；中立值 1400–1600 µs，按 10 µs 调整。';
  }

  function validTestId(id) { return (typeof id === 'string' && id.trim().length > 0) || (Number.isInteger(id) && id > 0); }
  function updateProfileRunValues() {}

  function renderServo(status) {
    const guards = servoGuards(), profile = servoProfile(status), data = status.watcher?.data || {};
    $('servo-arm-enable').hidden = data.output_policy_revision === 'continuous-enable-1' && data.default_output_enabled === true;
    setConnection('servo-arm-state', !watcherAwake() ? (data.power_state === 'standby' ? '待机' : '正在关机') : status.watcher?.online !== true ? '等待设备' : !guards.version2 ? '等待新版服务' : guards.armed ? (data.outputs_enabled === true ? '已启用' : '启用待同步') : data.output_policy_revision === 'continuous-enable-1' && data.default_output_enabled === true ? '等待就绪' : '已禁用', guards.armed && data.outputs_enabled === true ? 'online' : '');
    setConnection('servo-profile-state', profile ? (data.profile_match === true ? '配置已同步' : '配置待同步') : '等待配置', profile && data.profile_match === true ? 'online' : '');
    const signature = profile ? JSON.stringify(profile) : null;
    if (profile && !state.profileDirty && signature !== state.profileSignature) {
      for (let index = 0; index < 3; index++) { $(`profile-neutral-${index}`).value = profile.neutral_us[index]; $(`profile-run-${index}`).value = profile.run_us[index]; }
      state.profileSignature = signature;
      updateProfileRunValues();
      if (state.testPulsePristine) $('servo-test-pulse').value = profile.neutral_us[Number($('servo-test-channel').value) - 1];
    }
    const testId = status.servo?.test_id;
    if (testId !== state.lastTestId) { state.lastTestId = testId; state.observation = null; feedback('', '', 'servo-observation-feedback'); }
    const remaining = Math.max(0, Number(status.servo?.test_remaining_ms) || 0);
    text('observation-test-id', validTestId(testId) ? `最近短测 ${testId}${remaining > 0 ? ` · ${remaining} ms 后回中立` : ''}` : '尚无短测记录');
    text('ack-latency', Number.isFinite(data.ack_latency_ms) && data.ack_latency_ms >= 0 ? `指令往返：${Math.round(data.ack_latency_ms)} ms` : '指令往返：—');
    text('output-profile-match', data.profile_match === true ? '配置：已同步' : data.profile_match === false ? '配置：待同步' : '配置：等待回报');
    const led = data.led_color;
    const isGreen = typeof led === 'string' ? ['green', '#00ff00', '00ff00', '0x00ff00', '#008000'].includes(led.toLowerCase()) : Array.isArray(led) && led.length === 3 && led[1] > 0 && led[0] === 0 && led[2] === 0;
    const cameraFresh = status.watcher?.online === true && data.camera_active === true && Number.isFinite(data.camera_age_ms) && data.camera_age_ms >= 0 && data.camera_age_ms <= 800;
    const green = watcherAwake() && cameraFresh && isGreen;
    $('camera-lamp-dot').className = `lamp-dot${green ? ' active' : ''}`;
    text('camera-lamp-text', status.watcher?.online !== true ? '小智摄像头灯：状态未知' : !watcherAwake() ? '小智摄像头灯：已关闭（待机）' : green ? '小智摄像头灯：绿色 · 使用中（设备回报）' : cameraFresh ? '小智摄像头灯：等待绿色灯回报' : '小智摄像头灯：待机（设备回报）');
    const displayNames = { waiting: '等待手势', neutral: '等待手势', idle: '待机', stopped: '停止指令', stop: '停止指令', pounding: '捶打', angry: '捶打', kneading: '揉搓', relaxed: '揉搓', pinch: '轻捏', happy: '轻捏', thinking: '等待连接', error: '等待连接', test: '单路短测', calibrating: '校准中' };
    text('display-state', !watcherAwake() ? powerHint() : data.display_state ? `实体屏：${data.display_page === 'data' ? '数据页' : '表情页'} · ${displayNames[data.display_state] || '已更新'}${data.execution_pending === true ? ' · 等待回执' : ''}` : '等待设备回报');
  }

  function updateButtons() {
    const source = state.status?.source || 'simulation';
    document.querySelectorAll('[data-gesture]').forEach((button) => {
      button.disabled = !watcherAwake() || state.busy || !state.backendOnline || state.status?.api_version !== 2 || source !== 'simulation' || state.status?.observer_only === true;
      button.classList.toggle('selected', state.backendOnline && state.status?.requested_gesture === button.dataset.gesture);
    });
    document.querySelectorAll('[data-source]').forEach((button) => {
      button.disabled = !watcherAwake() || state.busy || !state.backendOnline || state.status?.api_version !== 2;
      button.setAttribute('aria-pressed', String(button.dataset.source === source));
    });
    $('export-logs').disabled = !state.logs.length;
    $('calibrate-back').disabled = !watcherAwake() || state.calibrating || !state.backendOnline || state.status?.camera?.online !== true || state.status?.camera?.data?.ready === false || (source === 'onboard' && state.status?.camera?.data?.model_ready !== true);
    const guards = servoGuards();
    $('servo-arm-enable').disabled = !guards.canArm;
    $('servo-test-fields').disabled = !guards.canTest;
    $('servo-profile-fields').disabled = !guards.canEdit;
    text('servo-enable-policy', servoEnableHint(guards));
    text('servo-test-guard', servoTestHint(guards));
    text('servo-profile-guard', servoProfileHint(guards));
    document.querySelectorAll('[data-observation]').forEach((button) => { button.disabled = state.busy || !state.backendOnline || !guards.version2 || !validTestId(state.status?.servo?.test_id); button.setAttribute('aria-pressed', String(state.observation?.test_id === state.status?.servo?.test_id && state.observation?.result === button.dataset.observation)); });
    text('control-help', !watcherAwake() ? powerHint() : source === 'camera' ? '稳定手势保持 5 秒；新手势立即切换，失去手 800ms 停止运动。输出禁用时只显示表情。' : guards.armed ? '点击一个手势，温和测试 2 秒后自动回中立。' : '当前输出禁用；模拟手势仅验证识别、通信与表情。');
  }

  function renderLogs(logs) {
    const next = Array.isArray(logs) ? logs : [];
    const previousSignature = JSON.stringify(state.logs);
    state.logs = next;
    text('logs-count', next.length ? `当前 ${next.length} 条记录` : '暂无记录');
    if (JSON.stringify(next) === previousSignature) return;
    const target = $('log-list');
    target.replaceChildren();
    if (!next.length) { const empty = document.createElement('p'); empty.className = 'empty-logs'; empty.textContent = '还没有日志。连接设备或发送模拟指令后会显示在这里。'; target.append(empty); return; }
    [...next].reverse().forEach((log) => {
      const row = document.createElement('div'); row.className = `log-row ${log.level === 'error' ? 'error' : ''}`;
      [['log-time', timeLabel(log.time)], ['log-event', log.event || '记录']].forEach(([className, value]) => { const el = document.createElement('span'); el.className = className; el.textContent = value; row.append(el); });
      const message = document.createElement('div'); message.className = 'log-message';
      const label = document.createElement('span'); label.textContent = log.message || ''; message.append(label);
      if (log.details != null) { const details = document.createElement('details'); details.className = 'log-details'; const summary = document.createElement('summary'); summary.textContent = '查看详情'; const body = document.createElement('pre'); body.textContent = typeof log.details === 'string' ? log.details : JSON.stringify(log.details, null, 2); details.append(summary, body); message.append(details); }
      row.append(message);
      target.append(row);
    });
  }

  function landmarkPoint(point) {
    const x = Array.isArray(point) ? point[0] : point?.x;
    const y = Array.isArray(point) ? point[1] : point?.y;
    return typeof x === 'number' && typeof y === 'number' && Number.isFinite(x) && Number.isFinite(y) ? { x, y } : null;
  }

  function clearHandNodes() {
    state.hands = [];
    text('hand-node-count', '0 只手 · 0 节点');
    const canvas = $('hand-overlay');
    canvas.getContext('2d')?.clearRect(0, 0, canvas.width, canvas.height);
    canvas.hidden = true;
  }

  function drawHandNodes() {
    const canvas = $('hand-overlay');
    const image = $('camera-frame');
    const stage = $('camera-stage');
    const context = canvas.getContext('2d');
    if (!context) return;
    if (image.hidden || !$('show-hand-nodes').checked || !state.hands.length) { context.clearRect(0, 0, canvas.width, canvas.height); canvas.hidden = true; return; }
    const originalWidth = image.naturalWidth || Number(state.status?.camera?.data?.width) || 416;
    const originalHeight = image.naturalHeight || Number(state.status?.camera?.data?.height) || 416;
    const scale = Math.min(stage.clientWidth / originalWidth, stage.clientHeight / originalHeight);
    const width = originalWidth * scale;
    const height = originalHeight * scale;
    if (!(width > 0 && height > 0)) { canvas.hidden = true; return; }
    const ratio = Math.min(window.devicePixelRatio || 1, 3);
    const pixelWidth = Math.round(width * ratio), pixelHeight = Math.round(height * ratio);
    if (canvas.width !== pixelWidth || canvas.height !== pixelHeight) { canvas.width = pixelWidth; canvas.height = pixelHeight; }
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    canvas.style.left = `${(stage.clientWidth - width) / 2}px`;
    canvas.style.top = `${(stage.clientHeight - height) / 2}px`;
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);
    context.lineWidth = 2.5;
    context.lineCap = 'round';
    const colors = ['#55efb5', '#f3d575'];
    state.hands.forEach((hand, handIndex) => {
      const points = hand.landmarks.map(landmarkPoint);
      context.strokeStyle = colors[handIndex % colors.length];
      context.fillStyle = colors[handIndex % colors.length];
      context.beginPath();
      handConnections.forEach(([from, to]) => { if (points[from] && points[to]) { context.moveTo(points[from].x * width, points[from].y * height); context.lineTo(points[to].x * width, points[to].y * height); } });
      context.stroke();
      points.forEach((point) => { if (!point) return; context.beginPath(); context.arc(point.x * width, point.y * height, 3.5, 0, Math.PI * 2); context.fill(); });
    });
    canvas.hidden = false;
  }

  function renderCamera(camera) {
    const data = camera?.data || {};
    const online = state.backendOnline && camera?.online === true && data.ready !== false;
    const age = Number(data.frame_age_ms);
    const fresh = online && data.frame_age_ms != null && Number.isFinite(age) && age >= 0 && age < 800;
    setConnection('camera-connection', fresh ? '画面已连接' : online ? '等待新画面' : '摄像头未连接', fresh ? 'online' : '');
    const raw = data.raw_gesture || data.gesture;
    const phaseHint = raw === 'stop' && /^揉搓：/.test(data.reason || '') ? data.reason : '';
    text('camera-result', fresh ? (phaseHint || `实时姿态：${gestureName(raw)}`) : '画面已过期 / 等待更新');
    const observations = { confirmed: `已确认：${gestureName(data.observation_gesture)}`, confirming: `确认中：${gestureName(raw)}`, unrecognized: '未识别到目标手势', no_hand: '未检测到手', conflict: '双手或规则冲突，停止运动', error: '观察无效，等待恢复' };
    text('camera-confirmation', fresh ? (observations[data.observation_state] || '识别服务待更新') : '确认暂停：等待有效画面');
    const fps = Number(data.inference_fps || data.capture_fps);
    text('camera-fps', online && Number.isFinite(fps) ? `${fps.toFixed(1)} 帧 / 秒` : '— 帧 / 秒');
    text('camera-age', fresh ? `画面 ${Math.round(age)} ms 前` : '等待更新');
    if (data.transport === 'sscma_spi') {
      state.frameId = null;
      clearHandNodes();
      $('camera-frame').hidden = true;
      $('camera-frame-mark').hidden = true;
      $('camera-placeholder').hidden = false;
      const hands = fresh && Array.isArray(data.hands) ? data.hands : [];
      text('hand-node-count', `${hands.length} 只手 · 每只 21 节点 · 小智板上提取`);
      text('camera-placeholder-text', fresh ? '板上摄像头正在运行；当前仅传输节点与状态，未传输预览图像' : (camera?.error || '等待板上摄像头和节点模型'));
      setConnection('camera-connection', fresh ? '板上采集运行中' : '等待板上采集', fresh ? 'online' : '');
      return;
    }
    if (fresh && data.frame_id != null) {
      state.hands = Array.isArray(data.hands) ? data.hands.filter((hand) => Array.isArray(hand?.landmarks) && hand.landmarks.some((point) => landmarkPoint(point))) : [];
      const counts = state.hands.map((hand) => hand.landmarks.filter((point) => landmarkPoint(point)).length);
      text('hand-node-count', `${counts.length} 只手 · ${counts.length ? counts.join(' / ') : '0'} 节点`);
      if (state.frameId !== data.frame_id) {
        state.frameId = data.frame_id;
        $('camera-frame').src = `/api/frame?frame=${encodeURIComponent(data.frame_id)}`;
      }
      drawHandNodes();
    } else {
      clearHandNodes();
      $('camera-frame').hidden = true;
      $('camera-frame-mark').hidden = true;
      $('camera-placeholder').hidden = false;
      text('camera-placeholder-text', camera?.error || (online ? '等待最新摄像头画面' : '等待 Watcher 摄像头连接'));
    }
  }

  function render(status) {
    state.status = status;
    state.backendOnline = true;
    $('service-dot').className = 'status-dot online';
    text('service-text', '控制台已连接');
    const watcher = status.watcher || {};
    const data = watcher.data || {};
    const watcherOnline = watcher.online === true;
    const age = Number(data.ack_age_ms);
    const clientConnected = watcherOnline && data.client_connected === true;
    const clientFresh = clientConnected && data.ack_age_ms != null && Number.isFinite(age) && age <= 1000;
    const commandKnown = Number.isInteger(data.last_command_seq) && Number.isInteger(data.last_applied_seq);
    const modeKnown = Number.isInteger(data.requested_mode) && Number.isInteger(data.applied_mode) && data.applied_mode >= 0 && data.applied_mode <= 3;
    const enabled = watcherAwake() && data.outputs_enabled === true;
    const profile = servoProfile(status);
    const profileMatches = status.api_version === 2 ? data.profile_match === true && !!profile : data.profile_match !== false;
    const confirmed = clientFresh && profileMatches && commandKnown && modeKnown && data.last_command_seq === data.last_applied_seq && (enabled ? data.requested_mode : 0) === data.applied_mode;
    setConnection('watcher-connection', watcherOnline ? '在线' : '离线', watcherOnline ? 'online' : 'error');
    setConnection('client-connection', clientFresh ? '在线' : clientConnected ? '回报超时' : '离线', clientFresh ? 'online' : '');
    text('watcher-ip', data.wifi_ip || '—');
    text('watcher-firmware', data.firmware || '—');
    text('client-ip', data.client_ip || '—');
    text('client-firmware', data.client_firmware || '—');
    setError('watcher-error', watcherOnline ? '' : watcher.error || '等待小智重新连接');
    setError('client-error', clientConnected ? (clientFresh ? '' : '尚未收到最新输出回报') : '等待黑色板连接小智');
    const source = ['camera', 'simulation', 'onboard'].includes(status.source) ? status.source : 'onboard';
    const wifiCamera = status.recognition_mode === 'mac_wifi';
    const requested = Object.hasOwn(names, status.requested_gesture) ? status.requested_gesture : 'stop';
    text('power-state', !watcherOnline ? '电源状态未知' : data.power_state === 'standby' ? '待机' : data.power_state === 'shutting_down' ? '正在关机' : `运行中 · ${data.display_page === 'data' ? '数据页' : '表情页'}`);
    text('runtime-mode', !watcherAwake() ? (data.power_state === 'standby' ? '小智待机' : '小智正在关机') : status.standalone_ready === true ? '板上独立识别' : source === 'onboard' ? '板上诊断 · 模型待验证' : source === 'simulation' ? '模拟诊断' : wifiCamera ? 'Wi-Fi / Mac 识别' : 'USB / Mac 验证模式');
    text('runtime-detail', !watcherAwake() ? powerHint() : status.standalone_ready === true ? '摄像头识别在 Watcher 本机完成。' : source === 'onboard' ? `板上模型尚未通过验证，执行保持禁用。${data.model_error || ''}` : source === 'camera' ? wifiCamera ? '小智可用电池供电，无线传图；Mac 仍须运行识别服务。' : '手节点由 Mac 提取，此诊断模式依赖 USB 与电脑。' : '当前为模拟诊断，测试数据不代表摄像头识别结果。');
    text('node-origin', source === 'onboard' ? '小智板上提取' : wifiCamera ? 'Mac 提取节点 · Wi-Fi 画面' : 'Mac 提取节点 · USB 画面');
    text('runtime-path', source === 'onboard' ? '小智摄像头 → 小智板上手节点 → Wi-Fi → 黑色板' : source === 'camera' ? '小智摄像头 → Mac 手节点 → 小智 → Wi-Fi → 黑色板' : '模拟数据 → 小智 → Wi-Fi → 黑色板');
    text('link-blocker', !watcherAwake() ? '摄像头、表情动画和舵机启动已暂停。' : !watcherOnline ? '小智离线，手势无法送达。' : source === 'onboard' && data.model_ready !== true ? '正在验证板上节点模型；尚无可用手势输入，舵机保持禁用。' : source === 'onboard' && status.standalone_ready !== true ? '板上模型正在诊断；表情可预览，动作控制尚未开放。' : source === 'simulation' ? '当前为模拟诊断，模拟数据不代表摄像头识别。' : !enabled ? '稳定手势用于表情预览；舵机输出已禁用。' : !clientFresh ? '正在等待黑色板连接和回执。' : '摄像头手势联动已启用；请观察实物运动。');
    text('current-source', source === 'onboard' ? '小智板上识别' : source === 'camera' ? 'Mac 摄像头诊断' : '模拟诊断');
    text('source-detail', status.observer_only === true ? '当前仅观察；小智本机决定表情与舵机控制' : source === 'camera' ? 'Mac 提取稳定手势并发给 Watcher' : '每次测试 2 秒后回中立');
    text('requested-gesture', !watcherAwake() ? (data.power_state === 'standby' ? '待机' : '正在关机') : gestureName(requested));
    const remaining = Math.max(0, Number(status.simulation_remaining_ms) || 0);
    const heldRemaining = Math.max(0, Number(status.hold_remaining_ms ?? data.hold_remaining_ms) || 0);
    text('request-detail', !watcherAwake() ? '已清除动作，等待唤醒后的新鲜识别' : source === 'camera' && requested !== 'stop' && heldRemaining > 0 ? `${data.observation_state === 'confirmed' ? '已确认 · ' : ''}保持中 ${(heldRemaining / 1000).toFixed(1)} 秒${!enabled ? ' · 舵机禁用' : Number(data.servo_hold_remaining_ms) <= 0 ? ' · 运动已停止' : ''}` : source === 'simulation' && requested !== 'stop' && remaining > 0 ? `${(remaining / 1000).toFixed(1)} 秒后自动回中立` : requested === 'stop' ? '三路已请求回中立' : '等待设备确认');

    let label = '等待设备确认', detail = '正在等待当前指令的回报';
    if (!watcherAwake()) { label = '动作已暂停'; detail = '待机期间禁止新动作，停止请求可重复执行'; }
    else if (!watcherOnline) { label = '等待小智上线'; detail = '当前输出未知'; }
    else if (!clientConnected) { label = '等待黑色板'; detail = '当前输出未知'; }
    else if (!clientFresh) { label = '等待最新回报'; detail = '回报超时，当前输出未知'; }
    else if (!profileMatches) { label = '配置待同步'; detail = '等待黑色板确认当前配置'; }
    else if (!enabled) { label = '输出禁用'; detail = '表情预览 / 舵机禁用'; }
    else if (data.execution_pending === true) { label = '等待执行回执'; detail = '表情已切换；实物运动请观察确认'; }
    else if (confirmed) { label = data.applied_mode === 0 ? '中立已确认' : gestureName(modes[data.applied_mode]); detail = data.applied_mode === 0 ? '三路中立指令已确认' : `已确认 MOD${data.applied_mode} 舵机指令`; }
    text('confirmed-gesture', label);
    text('confirmation-detail', detail);
    $('confirmed-gesture').closest('.confirmation').classList.toggle('unconfirmed', !(confirmed && enabled));
    const pulses = Array.isArray(data.client_pulse_us) ? data.client_pulse_us : [];
    const validPulse = (value) => Number.isInteger(value) && value >= 1000 && value <= 2000;
    const selectedPulse = pulses[data.applied_mode - 1];
    const neutrals = profile?.neutral_us || [1500, 1500, 1500];
    text('outputs-summary', !watcherAwake() ? '动作已暂停' : !enabled && clientFresh ? '表情预览 / 舵机禁用' : confirmed ? (data.applied_mode === 0 ? '三路中立已确认' : `MOD${data.applied_mode} 指令已确认`) : '等待设备确认');
    $('outputs-summary').classList.toggle('active', confirmed && enabled && data.applied_mode > 0 && validPulse(selectedPulse) && selectedPulse !== neutrals[data.applied_mode - 1]);
    for (let index = 0; index < 3; index++) {
      const row = $(`output-${index + 1}`);
      const value = pulses[index];
      const valueKnown = enabled && clientFresh && confirmed && validPulse(value);
      const active = enabled && confirmed && valueKnown && data.applied_mode === index + 1 && value !== neutrals[index];
      row.classList.toggle('active', active);
      row.querySelector('.pulse-value').textContent = valueKnown ? String(value) : !watcherAwake() && validPulse(value) ? `${value}（上次回报）` : '—';
      row.querySelector('.output-state').textContent = !watcherAwake() ? '动作已暂停 · 上次回报' : !enabled && clientFresh ? '未启用输出' : active ? (data.test_active === true ? '短测指令已确认' : '转动指令已确认') : valueKnown ? (value === neutrals[index] ? '中立' : '回报待核查') : '等待回报';
    }
    const reportedEmotion = String(data.emotion || '');
    const aliases = { neutral: 'waiting', idle: 'waiting', waiting: 'waiting', angry: 'pounding', relaxed: 'kneading', happy: 'pinch', thinking: 'error', focused: 'pounding', sleepy: 'stop', stop: 'stop', pounding: 'pounding', kneading: 'kneading', pinch: 'pinch', error: 'error' };
    const gestureValue = typeof data.expression_gesture === 'number' ? modes[data.expression_gesture] : data.expression_gesture;
    const gestureFace = Object.hasOwn(names, gestureValue) && gestureValue !== 'stop' ? gestureValue : null;
    expression(watcherOnline ? (gestureFace || aliases[data.display_state] || aliases[reportedEmotion] || (confirmed && data.applied_mode > 0 ? modes[data.applied_mode] : 'waiting')) : 'error', watcherOnline ? (data.display_animation ?? true) : false, watcherOnline ? data : {});
    renderServo(status);
    if (!watcherAwake()) state.frameId = null;
    renderCamera(watcherAwake() ? status.camera : { online: false, error: powerHint(), data: { ready: false, frame_age_ms: null } });
    renderLogs(status.logs);
    text('last-update', `最近更新 ${new Date().toLocaleTimeString('zh-CN', { hour12: false })}`);
    updateButtons();
  }

  function disconnected(error) {
    state.backendOnline = false;
    text('power-state', '电源状态未知');
    $('service-dot').className = 'status-dot error';
    text('service-text', '控制台连接中断');
    setConnection('watcher-connection', '未知', 'error');
    setConnection('client-connection', '未知', 'error');
    setConnection('camera-connection', '等待连接');
    text('confirmed-gesture', '连接中断');
    text('confirmation-detail', '当前输出未知，请检查设备');
    $('confirmed-gesture').closest('.confirmation').classList.add('unconfirmed');
    text('outputs-summary', '当前输出未知');
    $('outputs-summary').classList.remove('active');
    document.querySelectorAll('.pulse-value').forEach((el) => { el.textContent = '—'; });
    document.querySelectorAll('.output-state').forEach((el) => { el.textContent = '等待回报'; });
    document.querySelectorAll('tr.active').forEach((el) => el.classList.remove('active'));
    setError('watcher-error', error || '无法获取设备状态，正在自动重试');
    $('camera-frame').hidden = true;
    $('camera-frame-mark').hidden = true;
    $('camera-placeholder').hidden = false;
    clearHandNodes();
    text('camera-placeholder-text', '等待控制台恢复连接');
    $('camera-lamp-dot').className = 'lamp-dot';
    text('camera-lamp-text', '小智摄像头灯：状态未知');
    setConnection('servo-arm-state', '状态未知', 'error');
    setConnection('servo-profile-state', '状态未知');
    text('ack-latency', '指令往返：—');
    expression('error');
    updateButtons();
  }

  function poll() {
    if (state.pollPromise) return state.pollPromise;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 3000);
    state.pollPromise = (async () => {
      try {
        const response = await fetch('/api/status', { cache: 'no-store', signal: controller.signal });
        if (!response.ok) throw new Error(`状态读取失败（${response.status}）`);
        const status = await response.json();
        if (!status || typeof status !== 'object' || Array.isArray(status)) throw new Error('状态数据暂时不可用');
        render(status);
        return true;
      } catch (error) { disconnected(error.name === 'AbortError' ? '读取状态超时，正在自动重试' : error.message); return false; }
      finally { clearTimeout(timeout); state.pollPromise = null; }
    })();
    return state.pollPromise;
  }

  async function control(path, body, pending, success, target = 'control-feedback') {
    const safeWhileAsleep = path === '/api/stop' || (path === '/api/servo/arm' && body.enabled === false) || path === '/api/servo/observation';
    if (!watcherAwake() && !safeWhileAsleep) { feedback(powerHint(), 'error', target); return null; }
    const id = ++state.actionId;
    state.actionController?.abort();
    const controller = new AbortController();
    state.actionController = controller;
    state.busy = true;
    if (path === '/api/stop' || path === '/api/source' || (path === '/api/servo/arm' && body.enabled === false)) {
      if (state.status) state.status = { ...state.status, requested_gesture: 'stop', ...(body.source ? { source: body.source } : {}) };
      text('requested-gesture', '停止');
      text('request-detail', '正在提交停止请求');
    }
    feedback(pending, '', target);
    updateButtons();
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: controller.signal });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || result.ok !== true) throw new Error(result.error || result.message || `控制未成功（${response.status}）`);
      if (id === state.actionId) { feedback(success, 'success', target); await poll(); return result; }
    } catch (error) { if (id === state.actionId) feedback(error.name === 'AbortError' ? '指令提交超时。请查看设备回报，必要时点击停止。' : error.message, 'error', target); }
    finally { clearTimeout(timeout); if (id === state.actionId) { state.busy = false; state.actionController = null; updateButtons(); } }
    return null;
  }

  document.querySelectorAll('[data-gesture]').forEach((button) => {
    button.addEventListener('click', () => control('/api/simulate', { gesture: button.dataset.gesture, duration_ms: 2000 }, `正在提交${gestureName(button.dataset.gesture)}…`, `已提交${gestureName(button.dataset.gesture)}温和测试，等待设备确认；2 秒后自动回中立。`));
  });
  $('stop-button').addEventListener('click', () => control('/api/stop', {}, '正在提交三路中立指令…', '三路中立请求已提交，等待黑色板确认。'));
  document.querySelectorAll('[data-source]').forEach((button) => {
    button.addEventListener('click', () => control('/api/source', { source: button.dataset.source }, '正在切换来源并停止当前输出…', button.dataset.source === 'onboard' ? '已回到板上识别，等待设备状态同步。' : button.dataset.source === 'camera' ? '已切换至 Mac 摄像头诊断，等待设备状态同步。' : '已切换至模拟诊断，等待设备状态同步。'));
  });
  $('servo-arm-enable').addEventListener('click', async () => {
    const guards = servoGuards();
    if (!guards.canArm) { feedback(servoConnectionHint(guards) || '当前不能启用，请检查来源、摄像头状态和正在处理的指令。', 'error', 'servo-arm-feedback'); return; }
    await control('/api/servo/arm', { enabled: true }, '正在请求启用舵机输出…', '启用请求已提交；以设备回报为准。', 'servo-arm-feedback');
  });
  $('servo-arm-disable').addEventListener('click', () => control('/api/servo/arm', { enabled: false }, '正在禁用舵机输出…', '禁用请求已提交，等待设备确认。', 'servo-arm-feedback'));
  function fillTestPulse(kind) {
    const profile = servoProfile();
    if (!profile) { feedback('当前配置还未读取，请等待配置同步。', 'error', 'servo-test-feedback'); return; }
    const index = Number($('servo-test-channel').value) - 1;
    $('servo-test-pulse').value = profile[kind][index];
    state.testPulsePristine = kind === 'neutral_us';
  }
  $('servo-test-channel').addEventListener('change', () => fillTestPulse('neutral_us'));
  $('servo-test-pulse').addEventListener('input', () => { state.testPulsePristine = false; });
  $('servo-use-neutral').addEventListener('click', () => fillTestPulse('neutral_us'));
  $('servo-use-run').addEventListener('click', () => fillTestPulse('run_us'));
  $('servo-test-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!servoGuards().canTest) { feedback(servoTestHint(), 'error', 'servo-test-feedback'); return; }
    const payload = { channel: Number($('servo-test-channel').value), pulse_us: Number($('servo-test-pulse').value), duration_ms: Number($('servo-test-duration').value) };
    if (!Number.isInteger(payload.channel) || payload.channel < 1 || payload.channel > 3 || !Number.isInteger(payload.pulse_us) || payload.pulse_us < 1000 || payload.pulse_us > 2000 || !Number.isInteger(payload.duration_ms) || payload.duration_ms < 100 || payload.duration_ms > 500) { feedback('通道须为 1–3，脉宽 1000–2000 µs，时长 100–500 ms，均使用整数。', 'error', 'servo-test-feedback'); return; }
    const result = await control('/api/servo/test', payload, `正在提交通道 ${payload.channel} 短测…`, `短测请求已提交（${payload.duration_ms} ms）；请观察实物后记录表现。`, 'servo-test-feedback');
    const testId = result?.test_id ?? result?.servo?.test_id;
    if (validTestId(testId) && state.status) { state.status = { ...state.status, servo: { ...state.status.servo, test_id: testId } }; renderServo(state.status); updateButtons(); }
  });
  for (let index = 0; index < 3; index++) {
    const edit = () => { state.profileDirty = true; updateProfileRunValues(); };
    $(`profile-neutral-${index}`).addEventListener('input', edit);
    $(`profile-run-${index}`).addEventListener('input', edit);
  }
  $('servo-profile-form').addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!servoGuards().canEdit) { feedback(servoProfileHint(), 'error', 'servo-profile-feedback'); return; }
    const neutral_us = [], run_us = [];
    for (let index = 0; index < 3; index++) {
      const neutral = Number($(`profile-neutral-${index}`).value), run = Number($(`profile-run-${index}`).value);
      if (!Number.isInteger(neutral) || neutral < 1400 || neutral > 1600 || neutral % 10 !== 0 || !Number.isInteger(run) || run <= neutral || run > 2000 || run % 10 !== 0) { feedback('中立值须为 1400–1600 µs、按 10 µs 调整；运行值须大于中立且不超过 2000 µs，按 10 µs 调整。', 'error', 'servo-profile-feedback'); return; }
      neutral_us.push(neutral); run_us.push(run);
    }
    const result = await control('/api/servo/profile', { neutral_us, run_us }, '正在保存三路配置…', '配置已提交；等待黑色板同步及启用状态确认。', 'servo-profile-feedback');
    if (result) { state.profileDirty = false; state.profileSignature = null; if (state.status) renderServo(state.status); }
  });
  const observationNames = { moving: '已转动', stopped: '已停止', no_response: '无响应', abnormal: '异常' };
  document.querySelectorAll('[data-observation]').forEach((button) => {
    button.addEventListener('click', async () => {
      const test_id = state.status?.servo?.test_id, result = button.dataset.observation;
      if (!validTestId(test_id) || !Object.hasOwn(observationNames, result)) { feedback('请先完成一次短测，再记录实物表现。', 'error', 'servo-observation-feedback'); return; }
      const saved = await control('/api/servo/observation', { test_id, result }, '正在记录实物表现…', `已记录：${observationNames[result]}。`, 'servo-observation-feedback');
      if (saved) { state.observation = { test_id, result }; updateButtons(); }
    });
  });
  $('camera-frame').addEventListener('load', () => {
    const camera = state.status?.camera;
    if (watcherAwake() && state.backendOnline && camera?.online && camera.data?.transport !== 'sscma_spi' && camera.data?.image_available !== false && camera.data?.frame_age_ms != null && camera.data.frame_age_ms < 800) { $('camera-frame').hidden = false; $('camera-frame-mark').hidden = false; $('camera-placeholder').hidden = true; drawHandNodes(); } else { clearHandNodes(); }
  });
  $('camera-frame').addEventListener('error', () => { $('camera-frame').hidden = true; $('camera-frame-mark').hidden = true; $('camera-placeholder').hidden = false; clearHandNodes(); text('camera-placeholder-text', '画面暂时不可用，等待下一帧'); });
  $('show-hand-nodes').addEventListener('change', drawHandNodes);
  if (typeof ResizeObserver !== 'undefined') new ResizeObserver(drawHandNodes).observe($('camera-stage'));
  else window.addEventListener('resize', drawHandNodes);
  $('calibrate-back').addEventListener('click', async () => {
    if (!watcherAwake()) { feedback(powerHint(), 'error', 'calibration-feedback'); return; }
    if (state.calibrating) return;
    state.calibrating = true;
    const feedbackElement = $('calibration-feedback');
    feedbackElement.className = 'calibration-feedback';
    feedbackElement.textContent = '正在校准当前手的手背方向…';
    updateButtons();
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    try {
      const response = await fetch('/api/calibrate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}', signal: controller.signal });
      const result = await response.json().catch(() => ({}));
      if (!response.ok || result.ok !== true) throw new Error(result.error || result.message || `校准未成功（${response.status}）`);
      feedbackElement.className = 'calibration-feedback success';
      feedbackElement.textContent = '捶打手背已校准。换另一只手时，请重新校准。';
      await poll();
    } catch (error) {
      feedbackElement.className = 'calibration-feedback error';
      feedbackElement.textContent = error.name === 'AbortError' ? '校准超时，请保持手背正对镜头后重试。' : `校准未成功：${error.message}`;
    } finally { clearTimeout(timeout); state.calibrating = false; updateButtons(); }
  });
  $('refresh-logs').addEventListener('click', async () => { $('refresh-logs').disabled = true; text('logs-feedback', '正在刷新日志…'); const ok = await poll(); text('logs-feedback', ok ? '日志已更新' : '刷新未成功，正在自动重试'); $('refresh-logs').disabled = false; });
  $('export-logs').addEventListener('click', () => {
    const blob = new Blob([JSON.stringify({ exported_at: new Date().toISOString(), logs: state.logs }, null, 2)], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a'); link.href = url; link.download = `Watcher日志-${new Date().toISOString().replace(/[:.]/g, '-')}.json`; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    text('logs-feedback', `已导出 ${state.logs.length} 条日志`);
  });
  $('print-logs').addEventListener('click', () => window.print());
  window.addEventListener('beforeprint', () => { document.querySelectorAll('.log-details').forEach((detail) => { detail.dataset.printOpened = String(!detail.open); detail.open = true; }); });
  window.addEventListener('afterprint', () => { document.querySelectorAll('.log-details').forEach((detail) => { if (detail.dataset.printOpened === 'true') detail.open = false; delete detail.dataset.printOpened; }); });

  expression('waiting');
  updateButtons();
  async function loop() { await poll(); setTimeout(loop, 500); }
  loop();
})();

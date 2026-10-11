'use strict';
const assert=require('node:assert/strict'), fs=require('node:fs'), vm=require('node:vm'), path=require('node:path');
const root=path.resolve(__dirname,'..'), html=fs.readFileSync(path.join(root,'index.html'),'utf8');
class Element {
  constructor(id=''){this.id=id;this.textContent='';this.innerHTML='';this.dataset={};this.disabled=false;this.hidden=false;this.checked=false;this.value='1';this.style={};this.events={};this.attributes={};this.children=[];this.classes=new Set();this.classList={toggle:(n,on)=>{if(on)this.classes.add(n);else this.classes.delete(n)},add:n=>this.classes.add(n),remove:n=>this.classes.delete(n)};}
  setAttribute(k,v){this.attributes[k]=v} addEventListener(k,fn){this.events[k]=fn} append(...items){this.children.push(...items)} replaceChildren(...items){this.children=items} closest(){return this} querySelector(k){return this.children.find(e=>e.id===k)||this.children[this.children.push(new Element(k))-1]} getContext(){return new Proxy({}, {get:()=>()=>{}})}
}
const elements=new Map([...html.matchAll(/id="([^"]+)"/g)].map(m=>[m[1],new Element(m[1])]));
assert.equal(elements.has('power-confirmed'),false,'power confirmation checkbox must be removed');
assert(elements.has('servo-arm-disable')&&elements.has('stop-button'),'stop and disable controls must remain available');
elements.get('show-hand-nodes').checked=true;
const selectors={};for(const attr of ['source','gesture','observation'])selectors[`[data-${attr}]`]=[...html.matchAll(new RegExp(`data-${attr}="([^"]+)"`,'g'))].map(m=>{const e=new Element();e.dataset[attr]=m[1];return e});
const document={getElementById(id){assert(elements.has(id),'missing HTML element '+id);return elements.get(id)},querySelectorAll(s){return selectors[s]||[]},createElement(){return new Element()},body:new Element()};
const sandbox={document,window:{addEventListener(){},devicePixelRatio:1,print(){}},ResizeObserver:class{observe(){}},setTimeout(){return 1},clearTimeout(){},AbortController,Blob,URL,console,fetch(){throw Error('UI rendering must not issue a request');}};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync(path.join(root,'watcher_ui.js'),'utf8'),sandbox);
const source=fs.readFileSync(path.join(root,'app.js'),'utf8').replace('  loop();\n})();','  globalThis.__app={render,state,servoGuards,updateButtons,disconnected};\n})();');
assert.doesNotMatch(source,/power-confirmed|power_confirmed/,'power confirmation must not remain as a hidden execution prerequisite');
vm.runInContext(source,sandbox);const {render}=sandbox.__app;
assert.doesNotThrow(()=>sandbox.__app.disconnected('offline'),'network failure must render unknown state without a reference error');
assert.equal(elements.get('servo-arm-state').textContent,'状态未知');
function status(){return {api_version:2,source:'camera',observer_only:false,recognition_mode:'mac_wifi',requested_gesture:'pinch',hold_remaining_ms:4800,expression_gesture:'pinch',servo:{armed:false,profile:{neutral_us:[1500,1500,1500],run_us:[2000,2000,2000]}},watcher:{online:true,data:{firmware:'watcher-servo-controller-v8-wifi',client_firmware:'esp8266-servo-controller-v7',client_connected:true,hold_protocol:2,outputs_enabled:false,profile_match:true,ack_age_ms:20,last_command_seq:4,last_applied_seq:4,requested_mode:0,applied_mode:0,expression_gesture:'pinch',held_gesture:'pinch',hold_remaining_ms:4800,expression_remaining_ms:4800,servo_hold_remaining_ms:0,execution_pending:true,display_state:'neutral',mac_observation_version:2,camera_observation_version:2,camera_active:true,camera_age_ms:10,led_color:'green'}},camera:{online:true,data:{ready:true,transport:'wifi',frame_id:1,frame_age_ms:600,raw_gesture:'pinch',gesture:'pinch',observation_version:2,observation_state:'confirmed',confirmed_this_frame:true,hand_present:true,observation_gesture:'pinch',hands:[],inference_fps:5}},logs:[]};}
let s=status();render(s);
assert.equal(elements.get('requested-gesture').textContent,'轻捏');
assert.equal(elements.get('expression-label').textContent,'轻捏','execution receipt must not override gesture expression');
assert.match(elements.get('request-detail').textContent,/保持中.*4\.8/);
assert.match(elements.get('camera-result').textContent,/实时姿态.*轻捏/);
assert.match(elements.get('camera-confirmation')?.textContent||'',/已确认.*轻捏/);
assert.equal(elements.get('servo-arm-enable').disabled,false,'fresh camera diagnostics can arm without a power checkbox');
s=status();s.watcher.data.hold_protocol=0;render(s);assert.equal(elements.get('servo-arm-enable').disabled,true,'old black protocol is preview only');
s=status();s.camera.data.observation_state='no_hand';s.camera.data.confirmed_this_frame=false;s.camera.data.observation_gesture='stop';s.camera.data.raw_gesture='stop';render(s);
assert.equal(elements.get('requested-gesture').textContent,'轻捏');assert.equal(elements.get('expression-label').textContent,'轻捏');assert.match(elements.get('camera-confirmation')?.textContent||'',/未检测到手/);
s=status();s.camera.data.frame_age_ms=947;render(s);assert.doesNotMatch(elements.get('camera-result').textContent,/实时姿态.*轻捏/);assert.equal(elements.get('servo-arm-enable').disabled,true);
for(const [gesture,motion] of [['pounding','nod'],['kneading','breathe'],['pinch','pulse']]) {
  s=status();s.requested_gesture=gesture;s.watcher.data.expression_gesture=gesture;s.watcher.data.held_gesture=gesture;s.watcher.data.display_animation=true;render(s);
  assert.equal(elements.get('expression').dataset.animation,motion,'boolean animation enabled must animate the accepted '+gesture+' expression');
  assert.equal(elements.get('expression-label').textContent,{pounding:'捶打',kneading:'揉搓',pinch:'轻捏'}[gesture]);
}
s=status();s.watcher.data.expression_gesture='stop';s.watcher.data.held_gesture='stop';s.watcher.data.display_animation=true;render(s);assert.equal(elements.get('expression').dataset.animation,'blink','waiting state blinks');
s=status();s.watcher.data.display_animation=false;render(s);assert.equal(elements.get('expression').dataset.animation,'none','explicit false disables webpage animation');
s=status();s.watcher.data.display_animation='shake';render(s);assert.equal(elements.get('expression').dataset.animation,'shake','legacy named animation stays supported');
s=status();s.watcher.online=false;s.watcher.data.display_animation=true;render(s);assert.equal(elements.get('expression').dataset.animation,'none','offline expression remains static');
function simulationStatus() { const value=status();value.source='simulation';value.requested_gesture='stop';return value; }
function testHint() { return elements.get('servo-test-guard').textContent; }
function profileHint() { return elements.get('servo-profile-guard').textContent; }
s=simulationStatus();s.watcher.data.client_connected=false;s.watcher.data.profile_match=false;s.watcher.data.hold_protocol=0;s.watcher.data.ack_age_ms=null;render(s);
assert.match(testHint(),/黑色板.*未连接/,'disconnected peer must precede power/arming instructions');
assert.match(profileHint(),/黑色板.*未连接/,'profile guidance must expose the disconnected peer');
assert.equal(elements.get('servo-test-fields').disabled,true);
assert.equal(elements.get('servo-profile-fields').disabled,false,'local profile editing guard must remain unchanged');
s.watcher.online=false;render(s);assert.match(testHint(),/小智.*未连接/,'Watcher offline takes priority over peer state');
assert.equal(elements.get('servo-arm-state').textContent,'等待设备','offline output status must not claim disabled or enabled');
sandbox.__app.state.backendOnline=false;sandbox.__app.updateButtons();assert.match(testHint(),/控制服务.*未连接/,'backend offline takes priority');
s=simulationStatus();s.watcher.data.hold_protocol=0;render(s);assert.match(testHint(),/通信协议.*未就绪/);
s=simulationStatus();s.watcher.data.ack_age_ms=800;render(s);assert.match(testHint(),/回执.*过期/);
s=simulationStatus();s.watcher.data.ack_age_ms=null;render(s);assert.match(testHint(),/等待.*回执/);
s=simulationStatus();s.watcher.data.profile_match=false;render(s);assert.match(testHint(),/配置.*未同步/);
s=simulationStatus();s.default_output_enabled=true;s.default_enable_pending=true;s.output_enable_reason='pending';render(s);
assert.match(testHint(),/默认启用.*设备确认/,'healthy devices await actual default-enable confirmation, not a repeated manual step');
assert.doesNotMatch(testHint(),/供电|勾选|点击.*启用输出/);
assert.equal(elements.get('servo-arm-enable').disabled,false,'healthy readiness permits manual recovery without a checkbox');
assert.equal(elements.get('servo-test-fields').disabled,true,'short tests must still wait for a real armed report');
s=simulationStatus();s.default_output_enabled=true;s.default_enable_pending=true;s.output_enable_reason='firmware_update';render(s);
assert.match(testHint(),/小智固件待更新.*手动启用输出/,'old firmware guidance must take precedence over pending default enable');
assert.doesNotMatch(testHint(),/等待默认启用/,'old firmware cannot wait indefinitely for an unsupported automatic enable');
assert.match(elements.get('servo-enable-policy')?.textContent||'',/小智固件待更新.*手动启用输出/);
assert.equal(elements.get('servo-arm-enable').disabled,false,'compatible manual recovery remains available');
assert.equal(elements.get('servo-test-fields').disabled,true,'firmware hint cannot enable tests without an armed report');
for(const [reason,expected] of [['manual_disable',/手动禁用.*启用输出/],['explicit_stop',/已停止.*启用输出/],['fault',/故障.*启用输出/],['source_changed',/选择.*模拟手势/],['observer',/选择.*模拟手势/],['enabling',/正在启用.*确认/]]) {
  s=simulationStatus();s.default_output_enabled=true;s.default_enable_pending=false;s.output_enable_reason=reason;render(s);
  assert.match(testHint(),expected,'disabled guidance must reflect '+reason);
  assert.doesNotMatch(testHint(),/等待默认启用/,'default-enable waiting is only valid while pending');
  assert.match(elements.get('servo-enable-policy')?.textContent||'',expected,'output policy guidance must reflect '+reason);
  assert.equal(elements.get('servo-test-fields').disabled,true,'output reason alone cannot enable tests');
}
s=simulationStatus();s.servo.armed=true;s.watcher.data.outputs_enabled=true;render(s);
assert.match(testHint(),/填入运行值.*2000/);assert.match(testHint(),/中立值.*1500/);
assert.equal(elements.get('servo-test-pulse').value,1500,'default neutral pulse must remain unchanged');
assert.equal(elements.get('servo-test-fields').disabled,false);assert.match(profileHint(),/禁用/);
s=simulationStatus();s.observer_only=true;render(s);assert.match(testHint(),/仅观察/);
console.log('v8 UI held expression, live recognition, camera ARM, stale guards and boolean animations: PASS');
console.log('servo calibration readiness, no power checkbox, actual enable confirmation and no automatic UI requests: PASS');

s=status();s.watcher.data.output_policy_revision='continuous-enable-1';s.watcher.data.default_output_enabled=true;s.default_enable_pending=true;render(s);
assert.match(elements.get('servo-enable-policy').textContent, /持续默认启用/);
assert.equal(elements.get('servo-arm-enable').hidden,true,'continuous policy needs no repeated enable button');
s.default_enable_pending=false;s.output_enable_reason='stopped';render(s);
assert.doesNotMatch(elements.get('servo-enable-policy').textContent,/点击.*启用输出/);
s.output_enable_reason='fault';render(s);
assert.doesNotMatch(elements.get('servo-enable-policy').textContent,/点击.*启用输出/);
s.watcher.data.default_output_enabled=false;s.output_enable_reason='manual_disable';render(s);
assert.equal(elements.get('servo-arm-enable').hidden,false,'manual disable can still be reversed explicitly');
console.log('Continuous output UI checks passed.');

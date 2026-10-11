'use strict';
const assert = require('node:assert/strict');
const { previewState, powerAllowsActions, applyPreview } = require('../watcher_ui.js');

assert.equal(powerAllowsActions({power_state:'active'}), true);
assert.equal(powerAllowsActions({}), true, 'old devices remain preview compatible');
for (const power_state of ['standby', 'shutting_down']) {
  assert.equal(powerAllowsActions({power_state}), false);
  const state=previewState({power_state, expression_gesture:3, execution_pending:true});
  assert.equal(state.mode, 'sleep');
  assert.equal(state.label, power_state==='standby'?'待机':'正在关机');
  assert.equal(state.animate, false);
}
for (const [gesture,mode,label] of [[1,'angry','捶打'],[2,'relaxed','揉搓'],[3,'happy','轻捏']]) {
  const state=previewState({power_state:'active',expression_gesture:gesture,execution_pending:true,client_connected:true});
  assert.equal(state.mode,mode);
  assert.equal(state.label,label);
  assert.equal(state.pending,true,'receipt state is separate from gesture expression');
}
assert.equal(previewState({display_page:'data',expression_gesture:3}).page,'data');
assert.equal(previewState({display_page:'data',expression_gesture:3}).animate,false,'hidden physical expression must not be animated');
assert.equal(previewState({display_page:'expression',expression_gesture:3}).animate,true);
assert.equal(previewState({display_page:'expression',expression_gesture:0,client_connected:false}).mode,'thinking');
assert.equal(previewState({expression_gesture:0,client_connected:true}).mode,'neutral');
assert.equal(previewState({expression_gesture:3,client_connected:false}).mode,'happy','confirmed gesture is never replaced by receipt/link state');
assert.equal(previewState({expression_gesture:0,display_state:'relaxed',client_connected:true}).mode,'relaxed','legacy display fallback remains available');
assert.equal(previewState({expression_gesture:'pinch',execution_pending:true}).mode,'happy','dashboard gesture names match firmware numeric modes');
const face={dataset:{},classList:{add(){}},hasFace:false,writes:0,
  querySelector(){return this.hasFace?{}:null;},setAttribute(name,value){this[name]=value;},
  set innerHTML(value){this.markup=value;this.hasFace=true;this.writes++;}};
applyPreview(face,{expression_gesture:3,client_connected:true});
assert.equal(face.dataset.face,'happy');
assert.equal(face.dataset.animate,'true');
assert.equal(face['aria-label'],'小智表情：轻捏');
assert.equal((face.markup.match(/class="eye-bar /g)||[]).length,10);
applyPreview(face,{expression_gesture:2,display_page:'data'});
assert.equal(face.dataset.face,'relaxed');
assert.equal(face.dataset.page,'data');
assert.equal(face.dataset.animate,'false');
assert.equal(face.writes,1,'reuse fixed eye objects rather than replacing on each status tick');
console.log('wheel UI status and preview tests passed');

'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const base=fs.readFileSync(path.join(__dirname,'test_v8_ui.cjs'),'utf8');
const additional=`
for (const power of ['standby','shutting_down']) {
  s=simulationStatus();s.requested_gesture='pinch';s.servo.armed=true;
  s.watcher.data.power_state=power;s.watcher.data.display_page='expression';
  s.watcher.data.outputs_enabled=true;render(s);
  assert.equal(elements.get('expression').dataset.face,'sleep');
  assert.equal(elements.get('requested-gesture').textContent,power==='standby'?'待机':'正在关机');
  assert.equal(elements.get('servo-test-fields').disabled,true);
  assert.equal(elements.get('servo-profile-fields').disabled,true);
  assert.equal(elements.get('servo-arm-enable').disabled,true);
  assert.equal(elements.get('calibrate-back').disabled,true);
  for (const selector of ['[data-gesture]','[data-source]']) {
    assert(selectors[selector].every(button=>button.disabled));
  }
  assert.equal(elements.get('stop-button').disabled,false,'STOP remains available while standby');
  assert.match(elements.get('display-state').textContent,power==='standby'?/待机/:/关机/);
  assert.match(elements.get('servo-test-guard').textContent,power==='standby'?/待机/:/关机/);
  assert.equal(elements.get('camera-frame').hidden,true,'cached online frame cannot appear in standby');
  assert.equal(elements.get('output-1').classes.has('active'),false,'cached enabled flag is not current motion in standby');
  assert.match(elements.get('output-1').querySelector('.output-state').textContent,/暂停.*上次回报/);
  let writes=0;sandbox.fetch=()=>{writes++;throw Error('standby action must not make an HTTP request');};
  selectors['[data-gesture]'][0].events.click();
  selectors['[data-source]'][0].events.click();
  elements.get('calibrate-back').events.click();
  assert.equal(writes,0,'power admission rechecked even if a disabled handler is invoked');
}
s=status();s.watcher.data.power_state='active';s.watcher.data.display_page='data';render(s);
assert.equal(elements.get('expression').dataset.page,'data');
assert.equal(elements.get('expression').dataset.animate,'false');
assert.match(elements.get('display-state').textContent,/数据页/);
assert.equal(elements.get('servo-arm-enable').disabled,false,'viewing data does not change control admission');
s.watcher.data.display_page='expression';render(s);
assert.equal(elements.get('expression').dataset.animate,'true');
assert.match(elements.get('display-state').textContent,/表情页/);
console.log('Wheel page, power guards, cached state suppression and direct-handler admission: PASS');
`;
vm.runInNewContext(base+additional,{require,__dirname,__filename,console,AbortController,Blob,URL});

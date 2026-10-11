(function (root, factory) {
  const api = factory();
  if (typeof module === 'object' && module.exports) module.exports = api;
  else root.WatcherUI = api;
})(typeof globalThis !== 'undefined' ? globalThis : this, function () {
  'use strict';
  const names = ['等待', '捶打', '揉搓', '轻捏'];
  const modes = ['neutral', 'angry', 'relaxed', 'happy'];
  const knownModes = new Set([...modes, 'thinking']);
  function powerAllowsActions(watcher) {
    const power = (watcher || {}).power_state;
    return !power || power === 'active';
  }
  function previewState(watcher) {
    watcher = watcher || {};
    const power = watcher.power_state || 'active';
    const page = watcher.display_page === 'data' ? 'data' : 'expression';
    if (!powerAllowsActions(watcher)) {
      return {mode: 'sleep', label: power === 'standby' ? '待机' : '正在关机',
        page, power, pending: false, animate: false};
    }
    const gesture = ({pounding:1,kneading:2,pinch:3})[watcher.expression_gesture] || Number(watcher.expression_gesture) || 0;
    let mode = gesture >= 1 && gesture <= 3 ? modes[gesture] :
      (knownModes.has(watcher.display_state) ? watcher.display_state : 'neutral');
    if (!gesture && mode === 'neutral' && watcher.client_connected === false) mode = 'thinking';
    return {mode, label: gesture >= 1 && gesture <= 3 ? names[gesture] :
      ({angry:'捶打',relaxed:'揉搓',happy:'轻捏',thinking:'连接异常',neutral:'等待'})[mode],
      page, power, pending: Boolean(watcher.execution_pending), animate: page === 'expression'};
  }
  function faceMarkup() {
    const eye = side => `<span class="bar-eye ${side}">${Array.from({length:5}, (_,i) =>
      `<i class="eye-bar bar-${i}"></i>`).join('')}</span>`;
    return `<span class="bar-face"><span class="face-brow left-brow"></span>` +
      `<span class="face-brow right-brow"></span>${eye('left-eye')}${eye('right-eye')}` +
      `<svg class="bar-mouth" viewBox="0 0 160 60" aria-hidden="true"><path class="smile-mouth" d="M25 18 Q80 64 135 18"/>` +
      `<path class="flat-mouth" d="M55 32 H105"/></svg></span>`;
  }
  function applyPreview(element, watcher) {
    const state = previewState(watcher);
    if (!element) return state;
    if (!element.querySelector('.bar-face')) element.innerHTML = faceMarkup();
    element.classList.add('watcher-bar-preview');
    element.dataset.face = state.mode;
    element.dataset.page = state.page;
    element.dataset.animate = String(state.animate);
    element.setAttribute('aria-label', `小智表情：${state.label}`);
    return state;
  }
  return {powerAllowsActions, previewState, faceMarkup, applyPreview};
});

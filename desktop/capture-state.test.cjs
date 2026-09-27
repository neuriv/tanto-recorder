const assert = require('node:assert/strict');
const path = require('node:path');
const vm = require('node:vm');
const { buildSync } = require('esbuild');
function load(file, globals = {}) {
  const module = { exports: {} };
  const code = buildSync({ entryPoints: [path.join(__dirname, file)], bundle: true, platform: 'node', format: 'cjs', write: false }).outputFiles[0].text;
  vm.runInNewContext(code, { module, exports: module.exports, ...globals });
  return module.exports;
}
const { workerHealth, finishedHealth, coverage } = load('capture-state.ts');
const health = { state: 'recording', actions: 4, detail: '', tail: [], last_t: 2, bytes: 10 };
assert.equal(workerHealth(health, true).state, 'stopping');
assert.equal(workerHealth({ ...health, state: 'error' }, true).state, 'error');
assert.equal(finishedHealth(health, 0, null, '').state, 'error');
assert.equal(finishedHealth(health, 0, { ...health, state: 'stopped', actions: 0 }, '').state, 'error');
assert.equal(finishedHealth(health, 1, { ...health, state: 'stopped' }, '').state, 'error');
assert.equal(finishedHealth(health, 0, { ...health, state: 'stopped' }, '').state, 'stopped');
assert.match(coverage({ ...health, quality: { counter_gaps: 3, recovered_previous: 1, snapshot_races: 2, actor_changes: 4, dropped_events: 0, longest_sample_ms: 9, discovery_complete: false } }), /3 missed increments.*discovery incomplete/);
const partial = { ...health, state: 'stopped', quality: { counter_gaps: 0, recovered_previous: 0, snapshot_races: 0, actor_changes: 0, dropped_events: 0, metadata_failures: 1, longest_sample_ms: 10, discovery_complete: true } };
assert.match(coverage(partial), /1 metadata failures/);
assert.equal(finishedHealth(health, 0, partial, '').state, 'stopped');
assert.match(finishedHealth(health, 0, partial, '').detail, /Partial evidence saved/);
const nodes = new Map();
function node(id) {
  if (!nodes.has(id)) nodes.set(id, { textContent: '', value: '', dataset: {}, classList: { toggle() {}, remove() {} }, replaceChildren() {}, append() {}, addEventListener() {}, focus() {}, blur() { this.onchange?.(); } });
  return nodes.get(id);
}
const document = { getElementById: node, activeElement: null, body: node('body'), querySelectorAll: () => [], addEventListener() {}, createElement: tag => node(Symbol(tag)) };
let render;
const calls = [];
let view = { version: 'test', settings: { cue_volume: 0, boss_draft: 'Jin', tutorial_version: 5, changelog_seen: 'test', motion: false }, health, running: true, exporting: false, folder: 'test', session: { boss_name: 'Jin', takes: [{ id: 'take1' }], annotations: [], draft: { text: '' } }, bosses: [], changelog: '' };
const window = { addEventListener() {}, recorder: { onState(fn) { render = fn; }, onCue() {}, async call(name, value) { calls.push(name); if (name === 'context-commit') view.settings.boss_draft = value; return view; } } };
load('renderer.ts', { document, window });
(async () => {
  await Promise.resolve();
  render({ ...view, health: { ...health, state: 'starting' } });
  assert.equal(node('headline').textContent, 'Starting capture.');
  render({ ...view, health: workerHealth(health, true) });
  assert.equal(node('toggle').disabled, true);
  render({ ...view, running: false, health: finishedHealth(health, 0, null, '') });
  assert.match(node('footer-status').textContent, /needs review/);
  render({ ...view, running: false, health: { ...health, state: 'stopped' } });
  assert.equal(node('toggle-label').textContent, 'Start next take');
  assert.equal(node('footer-status').textContent, 'Take saved locally');
  node('boss').value = 'Okatsu'; node('boss').oninput();
  assert.match(node('boss-state').textContent, /Editing/);
  node('boss').onkeydown({ key: 'Enter', preventDefault() {} });
  await window.flushRecorderDraft();
  assert.ok(calls.includes('context-commit'));
  assert.equal(node('boss-state').textContent, 'Selected · Okatsu');
  console.log('Recorder lifecycle and renderer regressions passed.');
})().catch(error => { console.error(error); process.exitCode = 1; });

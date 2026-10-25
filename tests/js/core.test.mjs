import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {
  LEAD_S, TAIL_S, buildVisits, slotTime, nextFreeSlot, alignOrigin,
  createSession, step, progress, toSessionLog, FIELD_RULES, parseField,
} from '../../src/audio_zones_delay/player/core.mjs';

const fx = JSON.parse(readFileSync(new URL('../fixtures/session-example.json', import.meta.url), 'utf8'));
const fresh = () => createSession({profile: fx.profile, label: fx.label, sampleRate: 48000, signatureParams: fx.signature, createdAt: fx.created_at, originS: 0});

test('constants', () => {
  assert.equal(LEAD_S, 0.25);
  assert.equal(TAIL_S, 0.3);
});
test('slotTime', () => {
  assert.equal(slotTime(10, 3, 2), 16);
});
test('nextFreeSlot respects lead and last slot', () => {
  assert.equal(nextFreeSlot(10.0, 10.0, 2.0, -1), 1);
  assert.equal(nextFreeSlot(13.75, 10.0, 2.0, -1), 2);
  assert.equal(nextFreeSlot(10.0, 10.0, 2.0, 5), 6);
});
test('alignOrigin lands on a sample frame', () => {
  const o = alignOrigin(1.23456, 48000);
  assert.ok(Math.abs(o * 48000 - Math.round(o * 48000)) < 1e-6); assert.ok(o >= 1.73456 && o < 1.73456 + 1 / 48000);
});
test('buildVisits matches the fixture', () => {
  assert.deepEqual(buildVisits(fx.profile), fx.visits);
});
test('buildVisits throws without measured speakers', () => {
  const p = {...fx.profile, speakers: fx.profile.speakers.map((s) => ({...s, measured: false}))};
  assert.throws(() => buildVisits(p));
});
test('full session with a redo produces the fixture log shape', () => {
  let s = fresh();
  const run = (e) => ({state: s} = step(s, e));
  run({type:'click', nowS: 5.5});  assert.deepEqual(s.attempts[0].slots, [3,4,5,6,7]);
  run({type:'click', nowS: 6.0});  assert.equal(s.attempts.length, 1);           // ignored while holding
  run({type:'tick',  nowS: 14.7}); assert.equal(s.phase, 'holding');             // holdUntil = 14 + 0.5 + 0.3
  run({type:'tick',  nowS: 14.9}); assert.equal(s.phase, 'move'); assert.equal(s.visitIndex, 1);
  run({type:'click', nowS: 21.5}); run({type:'tick', nowS: 30.9});
  run({type:'redo'});              assert.equal(s.visitIndex, 1);
  run({type:'click', nowS: 33.5}); run({type:'tick', nowS: 42.9});
  run({type:'click', nowS: 49.5}); const last = step(s, {type:'tick', nowS: 58.9});
  assert.equal(last.state.phase, 'done'); assert.deepEqual(last.effects, [{type:'save'}]);
  const log = toSessionLog(last.state, fx.session_id);
  assert.deepEqual(log, fx);
});
test('click effects: play at slot times, then save', () => {
  const {effects} = step(fresh(), {type:'click', nowS: 5.5});
  assert.deepEqual(effects, [{type:'play', timesS: [6, 8, 10, 12, 14]}, {type:'save'}]);
});
test('step does not mutate its input and ignored events change nothing', () => {
  const s0 = fresh();
  const snap = JSON.stringify(s0);
  const s1 = step(s0, {type:'click', nowS: 5.5}).state;
  assert.equal(JSON.stringify(s0), snap);
  const snap1 = JSON.stringify(s1);
  const r = step(s1, {type:'click', nowS: 6.0});
  assert.deepEqual(r.effects, []);
  assert.equal(JSON.stringify(r.state), snap1);
  assert.deepEqual(step(s1, {type:'redo'}).effects, []);
  assert.equal(step(s1, {type:'redo'}).state.visitIndex, 0);
  assert.deepEqual(step(s1, {type:'tick', nowS: 7}).effects, []);
});
test('redo at visit 0 stays at 0; redo from done keeps the closure visit', () => {
  const s0 = fresh();
  assert.equal(step(s0, {type:'redo'}).state.visitIndex, 0);
  let s = s0;
  for (const [c, t] of [[5.5, 14.9], [21.5, 30.9], [49.5, 58.9]]) {
    s = step(s, {type:'click', nowS: c}).state; s = step(s, {type:'tick', nowS: t}).state;
  }
  assert.equal(s.phase, 'done');
  const r = step(s, {type:'redo'}).state;
  assert.equal(r.phase, 'move'); assert.equal(r.visitIndex, 2);
});
test('redo from done re-records the closure visit and finishes again', () => {
  let s = fresh();
  for (const [c, t] of [[5.5, 14.9], [21.5, 30.9], [49.5, 58.9]]) {
    s = step(s, {type:'click', nowS: c}).state; s = step(s, {type:'tick', nowS: t}).state;
  }
  s = step(s, {type:'redo'}).state;
  assert.equal(toSessionLog(s, 'x').completed, false);
  const clicked = step(s, {type:'click', nowS: 65.5});
  assert.deepEqual(clicked.effects.map((e) => e.type), ['play', 'save']);
  s = clicked.state;
  const end = step(s, {type:'tick', nowS: 200});
  assert.equal(end.state.phase, 'done');
  assert.deepEqual(end.effects, [{type:'save'}]);
  const closure = end.state.attempts.filter((a) => a.visit === 2);
  assert.deepEqual(closure.map((a) => a.attempt), [1, 2]);
  assert.equal(toSessionLog(end.state, 'x').completed, true);
});
test('progress counts started signatures', () => {
  let {state} = step(fresh(), {type:'click', nowS: 5.5});
  assert.deepEqual(progress(state, 8.1), {current: 2, total: 5});   // slots 3,4 start at 6.0 and 8.0
  assert.deepEqual(progress(fresh(), 8.1), {current: 0, total: 5});
});
test('parseField accepts numbers inside the model limits', () => {
  assert.deepEqual(parseField(' 343 ', FIELD_RULES.speed_of_sound_m_s), {value: 343});
  assert.deepEqual(parseField('300', FIELD_RULES.speed_of_sound_m_s), {value: 300});
  assert.deepEqual(parseField('0', FIELD_RULES.device_latency_ms), {value: 0});
  assert.deepEqual(parseField('1000', FIELD_RULES.device_latency_ms), {value: 1000});
  assert.deepEqual(parseField('20', FIELD_RULES.signatures_per_visit), {value: 20});
  assert.deepEqual(parseField('2.5', FIELD_RULES.period_s), {value: 2.5});
  assert.deepEqual(parseField('50', FIELD_RULES.distance_m), {value: 50});
});
test('parseField: an empty optional field is null, an empty required field is an error', () => {
  assert.deepEqual(parseField('', FIELD_RULES.distance_m), {value: null});
  assert.deepEqual(parseField('  ', FIELD_RULES.distance_m), {value: null});
  for (const key of ['speed_of_sound_m_s', 'device_latency_ms', 'signatures_per_visit', 'period_s']) {
    assert.ok(parseField('', FIELD_RULES[key]).error, key);
    assert.equal(parseField('', FIELD_RULES[key]).value, undefined, key);
  }
});
test('parseField rejects values the model rejects', () => {
  const bad = [
    ['speed_of_sound_m_s', ['0', '299.9', '400.1', 'abc', 'Infinity', 'NaN']],
    ['device_latency_ms', ['-1', '1000.1', 'Infinity']],
    ['signatures_per_visit', ['4.5', '2', '21']],
    ['period_s', ['0.99', '10.01', 'Infinity']],
    ['distance_m', ['0', '-2', '50.01', 'Infinity']],
  ];
  for (const [key, values] of bad) {
    for (const text of values) {
      const result = parseField(text, FIELD_RULES[key]);
      assert.ok(result.error, `${key} ${text}`);
      assert.equal(result.value, undefined, `${key} ${text}`);
    }
  }
  assert.match(parseField('4.5', FIELD_RULES.signatures_per_visit).error, /whole number from 3 to 20/);
  assert.match(parseField('0', FIELD_RULES.distance_m).error, /above 0 and at most 50, or leave empty/);
});

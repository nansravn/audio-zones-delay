// Player UI: setup screen, Web Audio scheduling and the session screens.
// The session logic itself lives in core.mjs; this file only wires it to the DOM,
// Web Audio and the HTTP API.

import {
  FIELD_RULES,
  alignOrigin,
  createSession,
  parseField,
  progress,
  step,
  toSessionLog,
} from './core.mjs';

const $ = (id) => document.getElementById(id);

function h(tag, props = {}, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(props)) {
    if (key === 'class') el.className = value;
    else if (key.startsWith('on')) el.addEventListener(key.slice(2), value);
    else if (key in el) el[key] = value;
    else el.setAttribute(key, value);
  }
  for (const child of children.flat()) {
    if (child == null) continue;
    el.append(child);
  }
  return el;
}

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body === undefined ? {} : {'Content-Type': 'application/json'},
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let payload = null;
  try {
    payload = await res.json();
  } catch {
    // Non-JSON body: fall through to the status text.
  }
  if (!res.ok) throw new Error((payload && payload.error) || `${res.status} ${res.statusText}`);
  return payload;
}

// ---------------------------------------------------------------- banner

const problems = {};

function setProblem(key, text) {
  if (text) problems[key] = text;
  else delete problems[key];
  const texts = Object.values(problems);
  const banner = $('banner');
  banner.hidden = texts.length === 0;
  banner.textContent = texts.join(' · ');
}

// ----------------------------------------------------------------- setup

let profile = null;
let label = '';
const ui = {};
const invalid = new Map(); // number input element -> error text

// A number input that only commits valid values; an invalid one shows an
// inline error and blocks Save and Start until it is fixed.
function numberInput(initial, rule, commit, props = {}) {
  const error = h('span', {class: 'field-error'});
  const input = h('input', {type: 'number', step: 'any', value: initial ?? '', ...props});
  const validate = () => {
    const result = parseField(input.value, rule);
    if ('error' in result) invalid.set(input, result.error);
    else invalid.delete(input);
    input.classList.toggle('invalid', 'error' in result);
    input.setAttribute('aria-invalid', String('error' in result));
    error.textContent = result.error || '';
    return result;
  };
  input.addEventListener('input', () => {
    const result = validate();
    if (!('error' in result)) commit(result.value);
    if (ui.start) updateStart();
  });
  if (!input.disabled) validate();
  return [input, error];
}

function nextSpeakerId() {
  const ids = new Set(profile.speakers.map((s) => s.id));
  let n = profile.speakers.length + 1;
  while (ids.has(`speaker-${n}`)) n += 1;
  return `speaker-${n}`;
}

function startBlocker() {
  for (const zone of [1, 2]) {
    if (!profile.speakers.some((s) => s.zone === zone && s.measured)) {
      return `Mark at least one measured speaker in zone ${zone}.`;
    }
  }
  return null;
}

function updateStart() {
  for (const el of [...invalid.keys()]) {
    if (!el.isConnected) invalid.delete(el);
  }
  const reason = invalid.size > 0 ? 'Fix the highlighted fields.' : startBlocker();
  ui.start.disabled = reason !== null || ui.starting === true;
  ui.save.disabled = invalid.size > 0;
  ui.reason.textContent = reason || '';
}

function moveSpeaker(index, delta) {
  const target = index + delta;
  if (target < 0 || target >= profile.speakers.length) return;
  const list = profile.speakers;
  [list[index], list[target]] = [list[target], list[index]];
  renderSpeakers();
}

function speakerRow(s, index) {
  const last = profile.speakers.length - 1;
  const nameInput = h('input', {
    type: 'text', value: s.name, 'aria-label': 'Speaker name',
    oninput: (e) => { s.name = e.target.value; },
  });
  const zoneSelect = h('select', {
    'aria-label': 'Zone',
    onchange: (e) => {
      s.zone = Number(e.target.value);
      if (s.zone === 1) {
        s.seat_distance_m = null;
        s.delay_channel = null;
      } else {
        s.anthem_distance_m = null;
      }
      renderSpeakers();
    },
  }, h('option', {value: '1', selected: s.zone === 1}, 'Zone 1'),
  h('option', {value: '2', selected: s.zone === 2}, 'Zone 2'));
  const measured = h('input', {
    type: 'checkbox', checked: s.measured, 'aria-label': 'Measured',
    onchange: (e) => { s.measured = e.target.checked; updateStart(); },
  });
  const distance = (field, enabled, name) => numberInput(
    s[field], FIELD_RULES.distance_m, (value) => { s[field] = value; },
    {min: '0', max: '50', disabled: !enabled, 'aria-label': name});
  const channel = h('input', {
    type: 'text', value: s.delay_channel ?? '', disabled: s.zone !== 2,
    'aria-label': 'Delay channel', size: 6,
    oninput: (e) => { s.delay_channel = e.target.value.trim() === '' ? null : e.target.value.trim(); },
  });
  return h('tr', {},
    h('td', {}, nameInput),
    h('td', {}, zoneSelect),
    h('td', {}, measured),
    h('td', {}, distance('anthem_distance_m', s.zone === 1, 'Anthem distance (m)')),
    h('td', {}, distance('seat_distance_m', s.zone === 2, 'Seat distance (m)')),
    h('td', {}, channel),
    h('td', {},
      h('button', {class: 'small', title: 'Move up', disabled: index === 0, onclick: () => moveSpeaker(index, -1)}, '↑'),
      ' ',
      h('button', {class: 'small', title: 'Move down', disabled: index === last, onclick: () => moveSpeaker(index, 1)}, '↓'),
      ' ',
      h('button', {
        class: 'small', title: 'Delete',
        onclick: () => { profile.speakers.splice(index, 1); renderSpeakers(); },
      }, '✕')));
}

function renderSpeakers() {
  ui.tbody.replaceChildren(...profile.speakers.map(speakerRow));
  updateStart();
}

function numberField(text, field, props = {}) {
  const rule = FIELD_RULES[field];
  const [input, error] = numberInput(profile[field], rule, (value) => { profile[field] = value; },
    {min: String(rule.min), max: String(rule.max), ...props});
  return h('label', {}, text, input, error);
}

function buildSetup(root) {
  ui.tbody = h('tbody');
  ui.status = h('span');
  ui.reason = h('span', {class: 'reason'});
  ui.start = h('button', {class: 'primary', onclick: startSession}, 'Start session');
  ui.save = h('button', {onclick: saveProfile}, 'Save profile');

  root.replaceChildren(
    h('h1', {}, 'Audio Zones Delay'),
    h('p', {}, 'Measure how much later the zone 2 speakers need to play so both zones arrive together at the seat.'),
    h('h2', {}, 'Speakers'),
    h('table', {},
      h('thead', {}, h('tr', {},
        ['Name', 'Zone', 'Measured', 'Anthem distance (m)', 'Seat distance (m)', 'Delay channel', '']
          .map((t) => h('th', {}, t)))),
      ui.tbody),
    h('div', {class: 'actions'}, h('button', {
      onclick: () => {
        profile.speakers.push({
          id: nextSpeakerId(), name: `Speaker ${profile.speakers.length + 1}`, zone: 1,
          measured: true, anthem_distance_m: null, seat_distance_m: null, delay_channel: null,
        });
        renderSpeakers();
      },
    }, 'Add speaker')),
    h('h2', {}, 'Session'),
    h('div', {class: 'grid'},
      h('label', {}, 'Session label (free text)', h('input', {
        type: 'text', value: label, placeholder: 'e.g. All Channel Stereo, ARC on',
        oninput: (e) => { label = e.target.value; },
      })),
      numberField('Signatures per visit', 'signatures_per_visit', {step: '1'}),
      numberField('Period (s)', 'period_s'),
      numberField('Speed of sound (m/s)', 'speed_of_sound_m_s'),
      numberField('Device latency (ms)', 'device_latency_ms')),
    h('h2', {}, 'Phone recording tips'),
    h('ul', {},
      h('li', {}, 'Start the recorder first, and keep it running for the whole session.'),
      h('li', {}, 'Point the phone’s bottom edge at the grille, one hand-span away.'),
      h('li', {}, 'Turn off “enhance” or noise reduction if the recorder has it.')),
    h('div', {class: 'actions'}, ui.save, ui.start, ui.reason),
    h('p', {class: 'error', id: 'setup-error'}),
    ui.status);
  renderSpeakers();
}

function showError(text) {
  $('setup-error').textContent = text || '';
}

async function saveProfile() {
  showError('');
  ui.status.textContent = '';
  if (invalid.size > 0) {
    showError('Fix the highlighted fields first.');
    return false;
  }
  try {
    await api('PUT', '/api/profile', profile);
    ui.status.className = 'ok';
    ui.status.textContent = 'Profile saved.';
    return true;
  } catch (err) {
    showError(`Profile not saved: ${err.message}`);
    return false;
  }
}

// --------------------------------------------------------------- session

let S = null; // {ctx, buffer, keepAlive, state, sessionId, finalSave, saveChain}

function enqueueSave(snapshotState) {
  const s = S;
  const log = toSessionLog(snapshotState, s.sessionId);
  const isFinal = snapshotState.phase === 'done';
  const token = {};
  if (isFinal) {
    s.finalSave = 'saving';
    s.finalToken = token;
  }
  s.saveChain = s.saveChain.then(async () => {
    try {
      await api('PUT', `/api/sessions/${s.sessionId}`, log);
      setProblem('save', null);
      if (isFinal && s.finalToken === token) s.finalSave = 'ok';
    } catch (err) {
      setProblem('save', `Session not saved: ${err.message}`);
      if (isFinal && s.finalToken === token) s.finalSave = `failed: ${err.message}`;
    }
  });
}

function playAt(timesS) {
  for (const t of timesS) {
    const src = S.ctx.createBufferSource();
    src.buffer = S.buffer;
    src.connect(S.ctx.destination);
    src.start(t);
  }
}

function dispatch(event) {
  if (!S) return;
  const {state, effects} = step(S.state, event);
  S.state = state;
  for (const effect of effects) {
    if (effect.type === 'play') playAt(effect.timesS);
    else if (effect.type === 'save') enqueueSave(state);
  }
  if (event.type === 'redo' && state.phase === 'move') {
    // Leaving DONE: the last "saved" status no longer applies.
    S.finalSave = 'none';
    S.finalToken = null;
  }
}

function speakerLabel(speakerId) {
  const s = S.state.profile.speakers.find((x) => x.id === speakerId);
  return s ? `Zone ${s.zone} · ${s.name}` : speakerId;
}

function buildSessionDom() {
  const el = {
    kicker: h('div', {class: 'kicker'}),
    speaker: h('div', {class: 'speaker'}),
    big: h('div', {class: 'big'}),
    line1: h('div', {class: 'line'}),
    line2: h('div', {class: 'line'}),
    barFill: h('div'),
    hint: h('div', {class: 'hint'}),
    command: h('code'),
    retry: h('button', {onclick: () => enqueueSave(S.state)}, 'Retry save'),
  };
  el.bar = h('div', {class: 'bar'}, el.barFill);
  $('session').replaceChildren(
    el.kicker, el.speaker, el.big, el.line1, el.bar, el.line2, el.command, el.retry, el.hint);
  return el;
}

let dom = null;

function render() {
  const st = S.state;
  const nowS = S.ctx.currentTime;
  setProblem('audio', S.ctx.state !== 'running'
    ? `Audio is not running (state: ${S.ctx.state}). Click the page or restart the session.` : null);

  const total = st.visits.length;
  const visit = st.visits[Math.min(st.visitIndex, total - 1)];
  const name = speakerLabel(visit.speaker_id);
  const isRedo = st.attempts.some((a) => a.visit === st.visitIndex);
  const show = (node, visible) => { node.hidden = !visible; };

  show(dom.bar, st.phase === 'holding');
  show(dom.command, st.phase === 'done');
  show(dom.retry, st.phase === 'done' && S.finalSave.startsWith('failed'));
  dom.line2.textContent = '';
  dom.big.className = 'big';

  if (st.phase === 'move') {
    dom.big.classList.add('move');
    dom.big.textContent = 'MOVE';
    if (st.visitIndex > 0 && !isRedo) {
      dom.kicker.textContent = `✔ ${speakerLabel(st.visits[st.visitIndex - 1].speaker_id)} captured`;
    } else {
      dom.kicker.textContent = isRedo ? 'Redo' : 'Ready';
    }
    dom.speaker.textContent = '';
    dom.line1.textContent = `${isRedo ? 'Redo' : 'Next'}: ${name}${visit.closure ? ' (closing check)' : ''}`;
    dom.line2.textContent = 'Hold the phone one hand-span from the grille, then click (or press Space).';
    dom.hint.textContent = `Speaker ${st.visitIndex + 1} of ${total} · phone keeps recording the whole time`;
  } else if (st.phase === 'holding') {
    const {current, total: n} = progress(st, nowS);
    dom.kicker.textContent = `Speaker ${st.visitIndex + 1} of ${total}`;
    dom.speaker.textContent = name;
    dom.big.classList.add('hold');
    dom.big.textContent = 'HOLD STILL';
    dom.line1.textContent = `Signature ${Math.max(1, current)} of ${n}`;
    dom.barFill.style.width = `${(current / n) * 100}%`;
    dom.hint.textContent = 'Clicks are ignored while playing · after this speaker finishes, press R to redo it';
  } else {
    dom.kicker.textContent = 'All speakers captured';
    dom.speaker.textContent = '';
    dom.big.classList.add('done');
    dom.big.textContent = 'DONE';
    const id = S.sessionId;
    const closure = speakerLabel(st.visits[total - 1].speaker_id);
    dom.line1.textContent = `Press R to redo ${closure} before stopping the recorder.`;
    if (S.finalSave === 'ok') {
      dom.line2.textContent = `Stop the phone recording. Session saved as ${id}.`;
    } else if (S.finalSave === 'saving') {
      dom.line2.textContent = 'Saving…';
    } else {
      dom.line2.textContent = `Session not saved: ${S.finalSave.replace(/^failed: /, '')}`;
    }
    dom.command.textContent = `uv run azd analyze data/sessions/${id} <path-to-recording>`;
    dom.hint.textContent = 'Copy the recording to the PC, then run the command above.';
  }
}

function frame() {
  if (!S) return;
  dispatch({type: 'tick', nowS: S.ctx.currentTime});
  render();
  requestAnimationFrame(frame);
}

function onKeyDown(event) {
  if (!S) return;
  if (event.code === 'Space' || event.key === ' ') {
    event.preventDefault();
    if (!event.repeat) dispatch({type: 'click', nowS: S.ctx.currentTime});
  } else if ((event.key === 'r' || event.key === 'R') && !event.repeat) {
    dispatch({type: 'redo'});
  }
}

function onPointerDown(event) {
  if (!S || event.target.closest('button')) return;
  dispatch({type: 'click', nowS: S.ctx.currentTime});
}

async function loadSignature(ctx) {
  const params = await api('GET', '/api/signature/params');
  const res = await fetch(`/api/signature?sample_rate=${ctx.sampleRate}`);
  if (!res.ok) throw new Error(`signature request failed: ${res.status}`);
  const samples = new Float32Array(await res.arrayBuffer());
  const buffer = ctx.createBuffer(2, samples.length, ctx.sampleRate);
  buffer.copyToChannel(samples, 0);
  buffer.copyToChannel(samples, 1);
  return {params, buffer};
}

async function startSession() {
  showError('');
  ui.starting = true;
  updateStart();
  // The AudioContext must be created inside the click handler.
  const ctx = new AudioContext();
  let keepAlive = null;
  try {
    if (!(await saveProfile())) throw new Error('save the profile first');
    await ctx.resume();
    keepAlive = ctx.createConstantSource();
    // About -120 dBFS, inaudible: Chromium suspends a sink after 30 s of exact zeros,
    // and resuming shifts the output timing.
    keepAlive.offset.value = 1e-6;
    keepAlive.connect(ctx.destination);
    keepAlive.start();

    const {params, buffer} = await loadSignature(ctx);
    const originS = alignOrigin(ctx.currentTime, ctx.sampleRate);
    const state = createSession({
      profile: JSON.parse(JSON.stringify(profile)),
      label: label.trim() || 'Untitled session',
      sampleRate: ctx.sampleRate,
      signatureParams: params,
      createdAt: new Date().toISOString(),
      originS,
    });
    const {session_id: sessionId} = await api('POST', '/api/sessions', toSessionLog(state, ''));
    S = {ctx, buffer, keepAlive, state, sessionId, finalSave: 'none', finalToken: null, saveChain: Promise.resolve()};
  } catch (err) {
    if (keepAlive) keepAlive.stop();
    ctx.close();
    ui.starting = false;
    updateStart();
    showError(`Could not start the session: ${err.message}`);
    return;
  }
  $('setup').hidden = true;
  $('session').hidden = false;
  dom = buildSessionDom();
  try {
    await document.documentElement.requestFullscreen();
  } catch {
    // Fullscreen is optional.
  }
  requestAnimationFrame(frame);
}

async function init() {
  const root = $('setup');
  try {
    profile = await api('GET', '/api/profile');
  } catch (err) {
    root.textContent = `Could not load the profile: ${err.message}`;
    return;
  }
  buildSetup(root);
  document.addEventListener('keydown', onKeyDown);
  $('session').addEventListener('pointerdown', onPointerDown);
}

init();

// Pure session logic for the player: no DOM, no Web Audio, no fetch.

export const LEAD_S = 0.25;
export const TAIL_S = 0.3;

// Setup form limits, the same as the Python model's (model.py).
export const FIELD_RULES = {
  signatures_per_visit: {min: 3, max: 20, integer: true},
  period_s: {min: 1, max: 10},
  speed_of_sound_m_s: {min: 300, max: 400},
  device_latency_ms: {min: 0, max: 1000},
  distance_m: {min: 0, max: 50, minExclusive: true, optional: true},
};

// Parse a number field's text: {value} when valid (null for an empty optional
// field), otherwise {error}. An invalid field never turns into 0.
export function parseField(text, rule) {
  const trimmed = String(text).trim();
  if (trimmed === '') return rule.optional ? {value: null} : {error: 'Required.'};
  const value = Number(trimmed);
  const ok = Number.isFinite(value)
    && (!rule.integer || Number.isInteger(value))
    && (rule.minExclusive ? value > rule.min : value >= rule.min)
    && value <= rule.max;
  if (ok) return {value};
  const kind = rule.integer ? 'a whole number' : 'a number';
  const range = rule.minExclusive
    ? `above ${rule.min} and at most ${rule.max}` : `from ${rule.min} to ${rule.max}`;
  return {error: `Enter ${kind} ${range}${rule.optional ? ', or leave empty' : ''}.`};
}

export function buildVisits(profile) {
  const measured = profile.speakers.filter((s) => s.measured);
  if (measured.length === 0) throw new Error('profile has no measured speakers');
  const visits = measured.map((s, index) => ({index, speaker_id: s.id, closure: false}));
  visits.push({index: measured.length, speaker_id: measured[0].id, closure: true});
  return visits;
}

export function slotTime(originS, slot, periodS) {
  return originS + slot * periodS;
}

export function nextFreeSlot(nowS, originS, periodS, lastSlot) {
  return Math.max(lastSlot + 1, Math.ceil((nowS + LEAD_S - originS) / periodS));
}

export function alignOrigin(nowS, sampleRate) {
  return Math.ceil((nowS + 0.5) * sampleRate) / sampleRate;
}

export function createSession({profile, label, sampleRate, signatureParams, createdAt, originS}) {
  return {
    profile,
    label,
    sampleRate,
    signatureParams,
    createdAt,
    originS,
    visits: buildVisits(profile),
    phase: 'move',
    visitIndex: 0,
    attempts: [],
    lastSlot: -1,
    holdUntilS: 0,
    currentSlots: [],
  };
}

export function step(state, event) {
  const {profile, signatureParams, originS} = state;
  const periodS = profile.period_s;
  switch (event.type) {
    case 'click': {
      if (state.phase !== 'move') return {state, effects: []};
      const first = nextFreeSlot(event.nowS, originS, periodS, state.lastSlot);
      const slots = Array.from({length: profile.signatures_per_visit}, (_, i) => first + i);
      const lastSlot = slots[slots.length - 1];
      const count = state.attempts.filter((a) => a.visit === state.visitIndex).length;
      const next = {
        ...state,
        phase: 'holding',
        attempts: [...state.attempts, {visit: state.visitIndex, attempt: count + 1, slots}],
        lastSlot,
        currentSlots: slots,
        holdUntilS: slotTime(originS, lastSlot, periodS) + signatureParams.duration_s + TAIL_S,
      };
      const timesS = slots.map((k) => slotTime(originS, k, periodS));
      return {state: next, effects: [{type: 'play', timesS}, {type: 'save'}]};
    }
    case 'tick': {
      if (state.phase !== 'holding' || !(event.nowS >= state.holdUntilS)) {
        return {state, effects: []};
      }
      if (state.visitIndex === state.visits.length - 1) {
        return {state: {...state, phase: 'done'}, effects: [{type: 'save'}]};
      }
      return {state: {...state, phase: 'move', visitIndex: state.visitIndex + 1}, effects: []};
    }
    case 'redo': {
      if (state.phase === 'holding') return {state, effects: []};
      // From DONE, redo re-records the last (closure) visit; from MOVE it goes back one visit.
      const visitIndex = state.phase === 'done' ? state.visitIndex : Math.max(0, state.visitIndex - 1);
      return {state: {...state, phase: 'move', visitIndex}, effects: []};
    }
    default:
      return {state, effects: []};
  }
}

export function progress(state, nowS) {
  const total = state.profile.signatures_per_visit;
  if (state.phase !== 'holding') return {current: 0, total};
  const started = state.currentSlots.filter(
    (k) => slotTime(state.originS, k, state.profile.period_s) <= nowS,
  ).length;
  return {current: started, total};
}

export function toSessionLog(state, sessionId) {
  return {
    schema: 1,
    session_id: sessionId,
    label: state.label,
    created_at: state.createdAt,
    sample_rate: state.sampleRate,
    period_s: state.profile.period_s,
    signatures_per_visit: state.profile.signatures_per_visit,
    signature: state.signatureParams,
    profile: state.profile,
    visits: state.visits,
    attempts: state.attempts,
    completed: state.phase === 'done',
  };
}

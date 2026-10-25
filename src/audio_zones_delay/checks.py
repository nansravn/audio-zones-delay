"""Pass/warn/fail consistency checks on an analysis, and whether its verdict is reliable."""

from __future__ import annotations

from dataclasses import dataclass

from .answers import Answers
from .assign import Assignment
from .model import SessionLog
from .timeline import Timeline

PASS, WARN, FAIL = "pass", "warn", "fail"

MAX_DRIFT_PPM = 200.0
# The closure limits widen with the stage-1 noise of the closure residual,
# which grows with session length.
CLOSURE_PASS_MS, CLOSURE_WARN_MS = 0.5, 1.0
CLOSURE_PASS_SE, CLOSURE_WARN_SE = 3.0, 4.0
REPEAT_PASS_MS, REPEAT_WARN_MS = 0.2, 0.5
A1_PASS_MS, A1_WARN_MS = 1.0, 2.0
DOMINANCE_PASS, DOMINANCE_WARN = 2.0, 1.4


@dataclass(frozen=True)
class Check:
    key: str
    status: str  # "pass", "warn" or "fail"
    message: str


def _grade(value: float, pass_max: float, warn_max: float) -> str:
    """Status of a value for which smaller is better."""
    if value <= pass_max:
        return PASS
    return WARN if value <= warn_max else FAIL


def _names(session: SessionLog, ids) -> str:
    return ", ".join(session.profile.speaker(i).name for i in ids)


def _drift(timeline: Timeline) -> Check:
    ppm = timeline.drift_ppm
    status = _grade(abs(ppm), MAX_DRIFT_PPM, MAX_DRIFT_PPM)
    message = f"clock drift {ppm:+.1f} ppm"
    if status == FAIL:
        message += (f" is beyond ±{MAX_DRIFT_PPM:.0f} ppm: "
                    "check that the recording belongs to this session")
    return Check("drift", status, message)


def _closure(assignment: Assignment, timeline: Timeline, session: SessionLog) -> Check:
    r = timeline.closure_residual_ms
    if r is None:
        closure = next((v for v in session.visits if v.closure), None)
        if closure is not None and closure.speaker_id in timeline.no_signal:
            # Re-recording the same way would not help: the speaker is silent in this mode.
            return Check("closure", FAIL, f"closure speaker {_names(session, [closure.speaker_id])} "
                         "has no signal in this mode, so playback stability cannot be checked; "
                         "start the speaker list with a speaker that plays in this mode and "
                         "record again")
        if assignment.shift_ambiguous:
            return Check("closure", FAIL, "closure visit not captured: the phone may have started "
                         "recording late or stopped early; record the whole session")
        return Check("closure", FAIL, "closure visit not captured: record the whole session")
    se = timeline.closure_se_ms or 0.0
    status = _grade(abs(r), max(CLOSURE_PASS_MS, CLOSURE_PASS_SE * se),
                    max(CLOSURE_WARN_MS, CLOSURE_WARN_SE * se))
    message = f"closure residual {r:+.2f} ms (noise {se:.2f} ms)"
    if status == FAIL:
        message += (": the timeline shifted between the first and closure visits (playback "
                    "glitch, or phone held at another distance); record the session again")
    return Check("closure", status, message)


def _repeat_spread(timeline: Timeline, session: SessionLog) -> Check:
    if not timeline.visits:
        return Check("repeat_spread", WARN, "no captures to check")
    worst = max(timeline.visits, key=lambda v: v.spread_ms)
    status = _grade(worst.spread_ms, REPEAT_PASS_MS, REPEAT_WARN_MS)
    message = f"worst repeat spread {worst.spread_ms:.2f} ms ({_names(session, [worst.speaker_id])})"
    if status == FAIL:
        message += ": keep the phone still and the room quiet during each capture"
    return Check("repeat_spread", status, message)


def _zone1_consistency(answers: Answers) -> Check:
    if answers.mode == "raw":
        if answers.raw_gap_ms is None:
            return Check("zone1_consistency", WARN,
                         "not checked: no zone 1 or no zone 2 speaker has signal")
        return Check("zone1_consistency", WARN, "raw mode: enter distances for per-speaker delays")
    if len(answers.a1_ms) < 2:
        return Check("zone1_consistency", WARN,
                     "only one zone 1 speaker has signal: Anthem distances not cross-checked")
    spread = answers.a1_spread_ms
    status = _grade(spread, A1_PASS_MS, A1_WARN_MS)
    message = f"zone 1 arrival spread {spread:.2f} ms"
    if status == FAIL:
        message += ": check the Anthem distances entered"
    return Check("zone1_consistency", status, message)


def _coverage(assignment: Assignment, timeline: Timeline, session: SessionLog) -> Check:
    zone = {s.id: s.zone for s in session.profile.speakers}
    failures = [f"no zone {z} speaker has signal" for z in (1, 2)
                if not any(zone[k] == z for k in timeline.emission_ms)]

    # A speaker with no signal is reported as such, not as missing signatures.
    slot_speaker = {s: session.visits[a.visit].speaker_id
                    for a in session.used_attempts().values() for s in a.slots}
    missing = [s for s in assignment.missing_slots if slot_speaker[s] not in timeline.no_signal]
    warnings = []
    if missing:
        warnings.append(f"{len(missing)} expected signature{'s' if len(missing) > 1 else ''} "
                        "not detected")
    silent2 = [k for k in timeline.no_signal if zone[k] == 2]
    if silent2:
        warnings.append(f"no signal from zone 2: {_names(session, silent2)}")

    parts = (failures + warnings) or ["all expected signatures detected"]
    silent1 = [k for k in timeline.no_signal if zone[k] == 1]
    if silent1:
        parts.append(f"no signal from zone 1: {_names(session, silent1)}")
    status = FAIL if failures else WARN if warnings else PASS
    return Check("coverage", status, "; ".join(parts))


def _dominance(timeline: Timeline, session: SessionLog) -> Check:
    if not timeline.visits:
        return Check("dominance", WARN, "no captures to check")
    worst = min(timeline.visits, key=lambda v: v.dominance)
    d = worst.dominance
    status = PASS if d >= DOMINANCE_PASS else WARN if d >= DOMINANCE_WARN else FAIL
    if status == FAIL:
        weak = dict.fromkeys(v.speaker_id for v in timeline.visits if v.dominance < DOMINANCE_WARN)
        return Check("dominance", FAIL, f"worst target dominance {d:.1f}: "
                     f"hold the phone closer to {_names(session, weak)}")
    return Check("dominance", status,
                 f"worst target dominance {d:.1f} ({_names(session, [worst.speaker_id])})")


def run_checks(assignment: Assignment, timeline: Timeline, answers: Answers,
               session: SessionLog) -> list[Check]:
    return [
        _drift(timeline),
        _closure(assignment, timeline, session),
        _repeat_spread(timeline, session),
        _zone1_consistency(answers),
        _coverage(assignment, timeline, session),
        _dominance(timeline, session),
    ]


def is_reliable(checks: list[Check]) -> bool:
    return all(c.status != FAIL for c in checks)

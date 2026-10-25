"""Assign detections to grid slots, visits and attempts of a session."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .detect import Detection
from .model import SessionLog

_MIN_MATCH_RATIO = 0.8
_MIN_MATCHED = 3
# A detection counts as evidence only within this level of the typical signature.
# Walk and lead-in noise sits 40 dB or more below the signatures; other speakers
# heard at a silent speaker's visit sit about 23-31 dB below.
_STRONG_DB = -30.0


class AlignmentError(Exception):
    pass


@dataclass
class Assigned:
    detection: Detection
    slot: int
    visit: int
    attempt: int


@dataclass
class Assignment:
    assigned: list[Assigned]
    spurious: list[Detection]   # weak detections, plus strong ones the log cannot explain
    missing_slots: list[int]
    match_ratio: float          # strong matched / strong total
    shift_ambiguous: bool = False


def _phase(times: np.ndarray, period: float) -> float:
    z = np.exp(2j * np.pi * times / period).mean()
    return float(period / (2 * np.pi) * np.angle(z)) % period


def _circular_distance(times: np.ndarray, phase: float, period: float) -> np.ndarray:
    d = (times - phase) % period
    return np.minimum(d, period - d)


def _split_by_strength(detections: list[Detection], n_expected: int):
    """(strong, weak): strong detections are within _STRONG_DB of the typical signature,
    the median of the ``n_expected`` strongest detections."""
    strengths = sorted((d.strength for d in detections), reverse=True)
    ref = float(np.median(strengths[:max(1, n_expected)]))
    floor = ref * 10 ** (_STRONG_DB / 20)
    strong = [d for d in detections if d.strength >= floor]
    weak = [d for d in detections if d.strength < floor]
    return strong, weak


def assign_detections(detections: list[Detection], session: SessionLog) -> Assignment:
    period = session.period_s
    if not detections:
        raise AlignmentError("recording does not match this session")
    n_expected = sum(len(a.slots) for a in session.used_attempts().values())
    # Weak detections (noise while walking, handling) are never assigned and are not
    # evidence for or against the alignment.
    strong, weak = _split_by_strength(detections, n_expected)
    times = np.array([d.time_s for d in strong])

    phase = _phase(times, period)
    near = times[_circular_distance(times, phase, period) <= 0.25 * period]
    if near.size:
        phase = _phase(near, period)

    n = np.round((times - phase) / period).astype(int)
    on_grid = np.abs(times - phase - n * period) <= 0.25 * period

    slot_owner = {}
    for attempt in session.attempts:
        for s in attempt.slots:
            slot_owner[s] = attempt
    logged = set(slot_owner)

    grid_indices = {int(i) for i in n[on_grid]}
    # Strong on-grid detections at unlogged indices count as unexplained (conservative).
    scores = {
        k: len({i + k for i in grid_indices} & logged)
        for k in {s - i for s in logged for i in grid_indices}
    }
    if not scores:
        raise AlignmentError("recording does not match this session")
    top = max(scores.values())
    tied = sorted(k for k, v in scores.items() if v == top)
    shift_ambiguous = len(tied) > 1
    if shift_ambiguous and top < len(grid_indices):
        # Tied partial fits are genuinely ambiguous.
        raise AlignmentError("ambiguous alignment")
    # A recording cropped at either end fits several shifts equally well when
    # every grid index is explained. Recordings are assumed to start with the
    # session, so take the smallest shift (k = slot - n), the earliest slot.
    shift = tied[0]

    best: dict[int, Detection] = {}
    spurious: list[Detection] = list(weak)
    for det, idx, ok in zip(strong, n, on_grid):
        slot = int(idx) + shift
        if not ok or slot not in logged:
            spurious.append(det)
        elif slot in best:
            if det.strength > best[slot].strength:
                spurious.append(best[slot])
                best[slot] = det
            else:
                spurious.append(det)
        else:
            best[slot] = det

    assigned = [
        Assigned(det, slot, slot_owner[slot].visit, slot_owner[slot].attempt)
        for slot, det in best.items()
    ]
    assigned.sort(key=lambda a: a.detection.time_s)
    spurious.sort(key=lambda d: d.time_s)

    match_ratio = len(assigned) / len(strong)
    if match_ratio < _MIN_MATCH_RATIO or len(assigned) < _MIN_MATCHED:
        raise AlignmentError("recording does not match this session")

    used_slots = [s for a in session.used_attempts().values() for s in a.slots]
    missing = sorted(s for s in used_slots if s not in best)
    return Assignment(assigned, spurious, missing, match_ratio, shift_ambiguous)

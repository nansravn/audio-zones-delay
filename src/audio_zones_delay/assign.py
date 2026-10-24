"""Assign detections to grid slots, visits and attempts of a session."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import numpy as np

from .detect import Detection
from .model import SessionLog

_MIN_MATCH_RATIO = 0.8
_MIN_MATCHED = 3


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
    spurious: list[Detection]
    missing_slots: list[int]
    match_ratio: float


def _phase(times: np.ndarray, period: float) -> float:
    z = np.exp(2j * np.pi * times / period).mean()
    return float(period / (2 * np.pi) * np.angle(z)) % period


def _circular_distance(times: np.ndarray, phase: float, period: float) -> np.ndarray:
    d = (times - phase) % period
    return np.minimum(d, period - d)


def assign_detections(detections: list[Detection], session: SessionLog) -> Assignment:
    period = session.period_s
    if not detections:
        raise AlignmentError("recording does not match this session")
    times = np.array([d.time_s for d in detections])

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
    scores = Counter()
    for s in logged:
        for i in grid_indices:
            scores[s - i] += 0
    for k in scores:
        scores[k] = len({i + k for i in grid_indices} & logged)
    if not scores:
        raise AlignmentError("recording does not match this session")
    top = max(scores.values())
    tied = sorted(k for k, v in scores.items() if v == top)
    if len(tied) > 1:
        # A recording cropped at the end fits several shifts equally well when
        # every grid index is explained. Recordings are assumed to start with
        # the session, so take the shift that places the first slot earliest.
        # Partial fits that tie are genuinely ambiguous.
        if top < len(grid_indices):
            raise AlignmentError("ambiguous alignment")
        shift = tied[0]  # k = slot - n, so the smallest k gives the earliest slot
    else:
        shift = tied[0]

    best: dict[int, Detection] = {}
    spurious: list[Detection] = []
    for det, idx, ok in zip(detections, n, on_grid):
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

    match_ratio = len(assigned) / len(detections)
    if match_ratio < _MIN_MATCH_RATIO or len(assigned) < _MIN_MATCHED:
        raise AlignmentError("recording does not match this session")

    used_slots = [s for a in session.used_attempts().values() for s in a.slots]
    missing = sorted(s for s in used_slots if s not in best)
    return Assignment(assigned, spurious, missing, match_ratio)

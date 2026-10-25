"""Fit drift and per-speaker emission times from assigned detections."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .assign import Assigned, Assignment
from .model import SessionLog


@dataclass
class VisitStats:
    visit: int
    speaker_id: str
    n: int
    mean_residual_ms: float
    spread_ms: float
    dominance: float


@dataclass
class Timeline:
    emission_ms: dict[str, float]
    emission_se_ms: dict[str, float]
    drift_ppm: float
    closure_residual_ms: float | None
    visits: list[VisitStats]
    no_signal: list[str]
    closure_se_ms: float | None = None  # stage-1 standard error of closure_residual_ms


def _fit(s: np.ndarray, t: np.ndarray, groups: np.ndarray, n_groups: int):
    """Least squares t = b*s + c[group]. Returns (b, c, covariance, residuals)."""
    x = np.zeros((s.size, n_groups + 1))
    x[:, 0] = s
    x[np.arange(s.size), groups + 1] = 1.0
    beta, *_ = np.linalg.lstsq(x, t, rcond=None)
    resid = t - x @ beta
    dof = s.size - x.shape[1]
    sigma2 = float(resid @ resid) / dof if dof > 0 else 0.0
    cov = sigma2 * np.linalg.inv(x.T @ x)
    return float(beta[0]), beta[1:], cov, resid


def fit_timeline(assignment: Assignment, session: SessionLog,
                 min_detections: int = 3, min_relative_level: float = 0.1) -> Timeline:
    used = session.used_attempts()
    by_visit: dict[int, list[Assigned]] = {}
    for a in assignment.assigned:
        if a.visit in used and used[a.visit].attempt == a.attempt:
            by_visit.setdefault(a.visit, []).append(a)

    alive = {v: items for v, items in by_visit.items() if len(items) >= min_detections}
    medians = {v: float(np.median([i.detection.strength for i in items])) for v, items in alive.items()}
    if medians:
        floor = min_relative_level * float(np.median(list(medians.values())))
        alive = {v: items for v, items in alive.items() if medians[v] >= floor}

    visit_speaker = {v.index: v.speaker_id for v in session.visits}
    measured: list[str] = []
    for v in session.visits:
        if v.speaker_id not in measured:
            measured.append(v.speaker_id)
    surviving = {visit_speaker[v] for v in alive}
    no_signal = [k for k in measured if k not in surviving]
    if not alive:
        return Timeline({}, {}, 0.0, None, [], no_signal)

    order = sorted(alive)
    slot = np.array([i.slot for v in order for i in alive[v]], dtype=float) * session.period_s
    time = np.array([i.detection.time_s for v in order for i in alive[v]])
    visit_of = np.array([v for v in order for _ in alive[v]])
    visit_pos = {v: p for p, v in enumerate(order)}
    groups1 = np.array([visit_pos[v] for v in visit_of])

    b, c, cov, resid = _fit(slot, time, groups1, len(order))

    closure = next((v for v in session.visits if v.closure), None)
    closure_residual = closure_se = None
    speakers = [visit_speaker[v] for v in order]
    first_of: dict[str, int] = {}
    for v in session.visits:
        if not v.closure:
            first_of.setdefault(v.speaker_id, v.index)
    if closure is not None and closure.index in visit_pos and first_of.get(closure.speaker_id) in visit_pos:
        pc, pf = visit_pos[closure.index], visit_pos[first_of[closure.speaker_id]]
        closure_residual = float((c[pc] - c[pf]) * 1000.0)
        # cov index 0 is the drift, so intercept p sits at p + 1.
        var = cov[pc + 1, pc + 1] + cov[pf + 1, pf + 1] - 2.0 * cov[pc + 1, pf + 1]
        closure_se = float(np.sqrt(max(var, 0.0)) / b * 1000.0)
        # Stage 2: one intercept per speaker, the closure visit shares the first one's.
        names = list(dict.fromkeys(speakers))
        groups2 = np.array([names.index(visit_speaker[v]) for v in visit_of])
        b, c2, cov, resid = _fit(slot, time, groups2, len(names))
    else:
        names, c2, keep = [], [], []
        for p, v in enumerate(order):
            k = speakers[p]
            if k not in names:
                names.append(k)
                keep.append(p)
                c2.append(c[p])
        c2 = np.array(c2)
        idx = [0] + [1 + p for p in keep]
        cov = cov[np.ix_(idx, idx)]
    cov_c = cov[1:, 1:]

    emission_ms = {k: float((c2[i] - c2.min()) / b * 1000.0) for i, k in enumerate(names)}
    emission_se = {k: float(np.sqrt(max(cov_c[i, i], 0.0)) / b * 1000.0) for i, k in enumerate(names)}

    stats = []
    for v in order:
        r = resid[visit_of == v] * 1000.0
        stats.append(VisitStats(
            visit=v, speaker_id=visit_speaker[v], n=int(r.size),
            mean_residual_ms=float(r.mean()),
            spread_ms=float(r.std(ddof=1)) if r.size > 1 else 0.0,
            dominance=float(np.median([i.detection.dominance for i in alive[v]])),
        ))
    return Timeline(emission_ms, emission_se, (b - 1.0) * 1e6, closure_residual, stats, no_signal,
                    closure_se)

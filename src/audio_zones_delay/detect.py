"""Matched-filter detection of the signature in a recording."""
from dataclasses import dataclass

import numpy as np
from scipy.signal import correlate, find_peaks, hilbert

NEIGHBOURHOOD_S = 0.060
EXCLUSION_S = 0.001
NO_COMPETITOR_DOMINANCE = 1000.0


@dataclass(frozen=True)
class Detection:
    time_s: float      # time at which the template starts in the recording
    strength: float    # envelope peak / median envelope
    dominance: float   # peak / strongest competing local maximum nearby


def matched_envelope(recording: np.ndarray, template: np.ndarray) -> np.ndarray:
    """Envelope of the cross-correlation; index i means the template starts at sample i."""
    rec = np.concatenate([np.asarray(recording, dtype=np.float64), np.zeros(len(template))])
    corr = correlate(rec, np.asarray(template, dtype=np.float64), mode="valid", method="fft")
    return np.abs(hilbert(corr))[: len(recording)]


def _parabolic_offset(env: np.ndarray, p: int) -> float:
    if p <= 0 or p >= len(env) - 1:
        return 0.0
    y0, y1, y2 = env[p - 1], env[p], env[p + 1]
    denom = y0 - 2.0 * y1 + y2
    return 0.0 if denom == 0 else float(0.5 * (y0 - y2) / denom)


def _dominance(env: np.ndarray, p: int, sample_rate: int) -> float:
    reach = int(round(NEIGHBOURHOOD_S * sample_rate))
    excl = int(round(EXCLUSION_S * sample_rate))
    lo = max(0, p - reach)
    local, _ = find_peaks(env[lo:p + reach + 1])
    rivals = [env[lo + i] for i in local if abs(lo + i - p) > excl]
    return float(env[p] / max(rivals)) if rivals else NO_COMPETITOR_DOMINANCE


def detect_signatures(recording, sample_rate: int, template, period_s: float,
                      snr: float = 10.0) -> list[Detection]:
    env = matched_envelope(recording, template)
    floor = float(np.median(env))
    peaks, _ = find_peaks(env, height=snr * floor,
                          distance=max(1, int(0.5 * period_s * sample_rate)))
    return [
        Detection(
            time_s=(p + _parabolic_offset(env, int(p))) / sample_rate,
            strength=float(env[p] / floor),
            dominance=_dominance(env, int(p), sample_rate),
        )
        for p in peaks
    ]

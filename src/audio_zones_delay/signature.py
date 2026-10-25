"""The test signature: a linear sine sweep with raised-cosine fades."""

from dataclasses import dataclass

import numpy as np

ANALYSIS_RATE = 48000


@dataclass(frozen=True)
class SignatureParams:
    f_start_hz: float = 300.0
    f_end_hz: float = 12000.0
    duration_s: float = 0.5
    fade_s: float = 0.005
    peak_dbfs: float = -6.0


SIGNATURE_PARAMS = SignatureParams()


def signature_waveform(
    t_s: np.ndarray, params: SignatureParams = SIGNATURE_PARAMS
) -> np.ndarray:
    """Evaluate the signature at times ``t_s`` (seconds); zero outside [0, duration_s)."""
    t = np.asarray(t_s, dtype=np.float64)
    T = params.duration_s
    phase = 2 * np.pi * (
        params.f_start_hz * t + (params.f_end_hz - params.f_start_hz) * t**2 / (2 * T)
    )
    fade_in = 0.5 * (1 - np.cos(np.pi * np.clip(t / params.fade_s, 0.0, 1.0)))
    fade_out = 0.5 * (1 - np.cos(np.pi * np.clip((T - t) / params.fade_s, 0.0, 1.0)))
    wave = np.sin(phase) * fade_in * fade_out * 10 ** (params.peak_dbfs / 20)
    return np.where((t >= 0) & (t < T), wave, 0.0)


def make_signature(
    sample_rate: int, params: SignatureParams = SIGNATURE_PARAMS
) -> np.ndarray:
    """Sample the signature at ``sample_rate`` as float32."""
    n = round(params.duration_s * sample_rate)
    return signature_waveform(np.arange(n) / sample_rate, params).astype(np.float32)

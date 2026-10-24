import numpy as np
import pytest
from audio_zones_delay.detect import detect_signatures
from audio_zones_delay.signature import make_signature, signature_waveform


def place(rec, t, gain=1.0, sr=48000):
    n0 = int(np.floor(t * sr)); n = np.arange(n0, n0 + 24002)
    rec[n0:n0 + 24002] += gain * signature_waveform(n / sr - t)


def noisy(seconds, seed=0):
    return np.random.default_rng(seed).normal(0, 10 ** (-60 / 20), int(seconds * 48000))


def test_detects_fractional_positions():
    rec = noisy(8)
    for t in (1.0, 3.0001234, 5.5):
        place(rec, t)
    d = detect_signatures(rec, 48000, make_signature(48000), 2.0)
    assert [x.time_s for x in d] == pytest.approx([1.0, 3.0001234, 5.5], abs=1e-5)


def test_strongest_arrival_wins_and_reports_dominance():
    rec = noisy(4); place(rec, 2.0); place(rec, 1.98, gain=0.05)
    d = detect_signatures(rec, 48000, make_signature(48000), 2.0)
    assert len(d) == 1 and d[0].time_s == pytest.approx(2.0, abs=1e-5)
    assert d[0].dominance > 10


def test_noise_only_has_no_detections():
    assert detect_signatures(noisy(6), 48000, make_signature(48000), 2.0) == []


def test_signature_at_end_is_detected():
    rec = noisy(3); place(rec, 3.0 - 0.5 - 0.001 - 2 / 48000)
    assert len(detect_signatures(rec, 48000, make_signature(48000), 2.0)) == 1

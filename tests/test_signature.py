import numpy as np
import pytest
from scipy.signal import correlate, hilbert
from audio_zones_delay.signature import make_signature, signature_waveform

def test_length_dtype_and_peak_level():
    s = make_signature(48000)
    assert s.dtype == np.float32
    assert len(s) == 24000
    assert np.max(np.abs(s)) == pytest.approx(10 ** (-6 / 20), abs=1e-3)

def test_length_at_44100():
    assert len(make_signature(44100)) == 22050

def test_starts_and_ends_silent():
    s = make_signature(48000)
    assert abs(s[0]) < 1e-6 and abs(s[-1]) < 1e-3

def test_energy_stays_in_band():
    s = make_signature(48000).astype(np.float64)
    power = np.abs(np.fft.rfft(s)) ** 2
    f = np.fft.rfftfreq(len(s), 1 / 48000)
    assert power[f < 200].sum() / power.sum() < 0.01
    assert power[f > 13000].sum() / power.sum() < 0.01

def test_autocorrelation_envelope_is_sharp():
    s = make_signature(48000).astype(np.float64)
    env = np.abs(hilbert(correlate(s, s, method="fft")))
    above = np.flatnonzero(env > env.max() / 2)
    assert (above.max() - above.min()) / 48000 < 0.25e-3

def test_waveform_matches_sampled_signature():
    t = np.arange(24000) / 48000
    np.testing.assert_allclose(signature_waveform(t), make_signature(48000), atol=1e-6)
    assert signature_waveform(np.array([-0.001, 0.5, 0.7])).tolist() == [0.0, 0.0, 0.0]

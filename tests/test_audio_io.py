import shutil

import numpy as np
import pytest

from audio_zones_delay.audio_io import RecordingError, load_recording
from synth import encode_m4a, write_wav


def test_wav_44100_is_resampled_to_48000(tmp_path):
    tone = 0.5 * np.sin(2 * np.pi * 1000 * np.arange(44100 * 2) / 44100)
    x = load_recording(write_wav(tone, 44100, tmp_path / "a.wav"))
    assert x.dtype == np.float64 and x.ndim == 1
    assert abs(len(x) - 96000) <= 96000 * 0.01


def test_stereo_is_downmixed(tmp_path):
    st = np.stack([np.ones(4800) * 0.25, np.ones(4800) * 0.25], axis=1)
    assert load_recording(write_wav(st, 48000, tmp_path / "s.wav")).ndim == 1


def test_m4a_round_trip(tmp_path):
    tone = 0.5 * np.sin(2 * np.pi * 1000 * np.arange(48000) / 48000)
    x = load_recording(encode_m4a(tone, 48000, tmp_path / "t.m4a"))
    assert abs(len(x) - 48000) <= 48000 * 0.05


def test_missing_ffmpeg_raises(tmp_path, monkeypatch):
    wav = write_wav(np.zeros(4800), 48000, tmp_path / "z.wav")
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(RecordingError, match="apt-get install ffmpeg"):
        load_recording(wav)


@pytest.mark.parametrize("name, content", [("missing.wav", None), ("bad.m4a", b"not audio")])
def test_bad_input_raises(tmp_path, name, content):
    p = tmp_path / name
    if content is not None:
        p.write_bytes(content)
    with pytest.raises(RecordingError):
        load_recording(p)

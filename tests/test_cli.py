import json

import numpy as np
import pytest
import synth
from audio_zones_delay.analysis import analyze
from audio_zones_delay.audio_io import load_recording
from audio_zones_delay.cli import main
from audio_zones_delay.model import load_session, session_to_dict
from synth import SynthOptions, emissions_for, encode_m4a, synth_session


def make_session_dir(tmp_path, opts=SynthOptions()):
    log, rec = synth_session(synth.test_profile(), emissions_for(synth.test_profile()), opts)
    d = tmp_path / "s"
    d.mkdir()
    (d / "session.json").write_text(json.dumps(session_to_dict(log)))
    return d, encode_m4a(rec, 48000, tmp_path / "rec.m4a")


def test_analyze_writes_report_and_exits_0(tmp_path, capsys):
    d, rec = make_session_dir(tmp_path)
    assert main(["analyze", str(d), str(rec)]) == 0
    assert (d / "report.html").exists() and "earlier than zone 1" in capsys.readouterr().out


def test_device_latency_override(tmp_path, capsys):
    d, rec = make_session_dir(tmp_path)
    before = (d / "session.json").read_text()
    main(["analyze", str(d), str(rec), "--device-latency-ms", "2"])
    session = load_session(d / "session.json")
    session.profile.device_latency_ms = 2.0
    left = next(c for c in analyze(session, load_recording(rec)).answers.channels if c.channel == "L")
    assert left.dial_ms == pytest.approx(34.052187, abs=0.3)
    out = capsys.readouterr().out
    assert f"{left.dial_ms:.1f} ms" in out and "2.0 ms of device latency" in out
    assert (d / "session.json").read_text() == before


def test_withheld_exits_2(tmp_path):
    d, rec = make_session_dir(tmp_path, SynthOptions(glitch_after_visit=2, glitch_ms=1.5))
    assert main(["analyze", str(d), str(rec)]) == 2
    assert (d / "report.html").exists()


def test_missing_recording_exits_1(tmp_path, capsys):
    d, _ = make_session_dir(tmp_path)
    assert main(["analyze", str(d), str(tmp_path / "nope.m4a")]) == 1
    assert "nope.m4a" in capsys.readouterr().err
    assert not (d / "report.html").exists()


def test_missing_session_exits_1(tmp_path, capsys):
    _, rec = make_session_dir(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["analyze", str(empty), str(rec)]) == 1
    assert "session.json" in capsys.readouterr().err


def test_invalid_session_exits_1(tmp_path, capsys):
    d, rec = make_session_dir(tmp_path)
    (d / "session.json").write_text("{not json")
    assert main(["analyze", str(d), str(rec)]) == 1
    assert capsys.readouterr().err.strip()


def test_mismatched_recording_exits_1(tmp_path, capsys):
    d, _ = make_session_dir(tmp_path)
    other = encode_m4a(np.zeros(48000 * 60), 48000, tmp_path / "silence.m4a")
    assert main(["analyze", str(d), str(other)]) == 1
    assert "does not match" in capsys.readouterr().err
    assert not (d / "report.html").exists()

import pytest
import synth
from audio_zones_delay.analysis import analyze
from audio_zones_delay.assign import AlignmentError
from synth import SynthOptions, emissions_for, synth_session
from synth import run_analysis as run


def delays(r):
    return {c.channel: c.delay_ms for c in r.answers.channels}


def check(r, key):
    return next(c for c in r.checks if c.key == key)


def test_clean_session_aac_44k(tmp_path):
    r = run(SynthOptions(drift_ppm=40.0), via_m4a=tmp_path)
    assert r.reliable
    assert delays(r) == pytest.approx({"L": 36.052187, "R": 35.177551}, abs=0.3)
    assert r.answers.headline_ms == pytest.approx(41.3, abs=0.3)
    assert r.timeline.drift_ppm == pytest.approx(40.0, abs=2.0)


def test_checks_come_in_order():
    r = run(SynthOptions())
    assert [c.key for c in r.checks] == [
        "drift", "closure", "repeat_spread", "zone1_consistency", "coverage", "dominance",
    ]
    assert r.reliable == all(c.status != "fail" for c in r.checks)


def test_redo_and_claps_do_not_change_result():
    r = run(SynthOptions(redo_visits=frozenset({3}), clap_times_s=(6.0, 30.0, 52.0)))
    assert r.reliable and delays(r) == pytest.approx({"L": 36.052187, "R": 35.177551}, abs=0.3)


def test_silent_center_is_no_signal():
    r = run(SynthOptions(silent_speakers=frozenset({"center"})))
    assert r.reliable and r.timeline.no_signal == ["center"]
    assert delays(r) == pytest.approx({"L": 36.052187, "R": 35.177551}, abs=0.3)


def test_playback_glitch_withholds_verdict():
    r = run(SynthOptions(glitch_after_visit=2, glitch_ms=1.5))
    assert not r.reliable and check(r, "closure").status == "fail"


def test_phone_started_late_withholds_verdict():
    r = run(SynthOptions(drop_visits=frozenset({0})))
    assert not r.reliable and check(r, "closure").status == "fail"
    assert "started recording late or stopped early" in check(r, "closure").message


def test_all_zone2_silent_withholds_verdict():
    r = run(SynthOptions(silent_speakers=frozenset({"rear-left", "rear-right"})))
    assert not r.reliable and check(r, "coverage").status == "fail"


def test_wrong_anthem_distance_fails_consistency():
    p = synth.test_profile()
    p.speaker("center").anthem_distance_m = 2.0  # real setting is 3.4 m
    r = run(SynthOptions(), profile=p)
    assert not r.reliable and check(r, "zone1_consistency").status == "fail"


def test_wrong_session_raises():
    log_b, _ = synth_session(synth.test_profile(), emissions_for(synth.test_profile()), SynthOptions(walk_s=7.0))
    _, rec_a = synth_session(synth.test_profile(), emissions_for(synth.test_profile()), SynthOptions())
    with pytest.raises(AlignmentError):
        analyze(log_b, rec_a)

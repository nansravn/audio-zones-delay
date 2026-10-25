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
        "drift", "closure", "repeat_spread", "zone1_consistency", "zone2_consistency", "distances",
        "coverage", "dominance", "level",
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


def test_silent_closure_speaker_withholds_verdict():
    r = run(SynthOptions(silent_speakers=frozenset({"front-left"})))
    assert r.reliable is False
    assert check(r, "closure").status == "fail" and "no signal" in check(r, "closure").message


def test_single_zone1_speaker_warns_but_stays_reliable():
    r = run(SynthOptions(silent_speakers=frozenset({"center", "surround-back-left"})))
    assert r.reliable is True
    c = check(r, "zone1_consistency")
    assert (c.status, c.message) == (
        "warn", "only one zone 1 speaker has signal: Anthem distances not cross-checked")


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


TRUE_DELAYS = {"L": 36.052187, "R": 35.177551}


def test_noisy_walks_stay_reliable():
    r = run(SynthOptions(noise_dbfs=-70.0, walk_noise_dbfs=-50.0))
    assert len(r.assignment.spurious) >= 10  # the walks do produce noise detections
    assert r.reliable and delays(r) == pytest.approx(TRUE_DELAYS, abs=0.3)


def test_noisy_long_lead_in_stays_reliable():
    r = run(SynthOptions(noise_dbfs=-70.0, lead_in_s=40.0, lead_in_noise_dbfs=-55.0))
    assert len(r.assignment.spurious) >= 10
    assert r.reliable and delays(r) == pytest.approx(TRUE_DELAYS, abs=0.3)


@pytest.mark.parametrize("noise_dbfs", [-70.0, -60.0])
def test_phone_agc_boosting_walks_stays_reliable(noise_dbfs):
    r = run(SynthOptions(noise_dbfs=noise_dbfs, agc_max_gain_db=20.0))
    assert r.reliable and delays(r) == pytest.approx(TRUE_DELAYS, abs=0.3)


def test_wrong_session_with_noisy_walks_raises():
    p = synth.test_profile()
    log_b, _ = synth_session(p, emissions_for(p), SynthOptions(walk_s=7.0))
    _, rec_a = synth_session(p, emissions_for(p), SynthOptions(noise_dbfs=-70.0, walk_noise_dbfs=-50.0))
    with pytest.raises(AlignmentError):
        analyze(log_b, rec_a)


def test_silent_speaker_visit_is_assigned_then_no_signal():
    r = run(SynthOptions(silent_speakers=frozenset({"center"})))
    assert any(a.visit == 1 for a in r.assignment.assigned)
    assert r.timeline.no_signal == ["center"]


def neighbour_of_rear_left(metres):
    return (("rear-left", "surround-back-left", metres),)


def test_zone1_neighbour_heard_instead_of_quiet_zone2_withholds_verdict():
    # Zone 2 18 dB below zone 1, Surround Back Left 1.0 m from Rear Left: the Rear Left
    # capture locks onto the zone 1 neighbour (delay about -7.6 ms instead of +36.1 ms).
    r = run(SynthOptions(zone2_gain_db=-18.0, neighbours=neighbour_of_rear_left(1.0)))
    assert r.reliable is False
    c = check(r, "zone2_consistency")
    assert c.status == "fail" and "raise Zone 2 volume to match zone 1" in c.message
    assert check(r, "level").status == "fail"


def test_reviewer_quiet_zone2_scenario_withholds_verdict():
    # The reviewer's scenario: zone 2 24 dB down and the neighbour at 1.5 m. Rear Right falls
    # below the no-signal floor, so nothing cross-checks zone 2; the quiet Rear Left capture
    # (locked onto the zone 1 neighbour, delay -9.0 ms instead of +36.1 ms) fails the level check.
    r = run(SynthOptions(zone2_gain_db=-24.0, neighbours=neighbour_of_rear_left(1.5)))
    assert r.timeline.no_signal == ["rear-right"]
    assert check(r, "zone2_consistency").status == "warn"
    level = check(r, "level")
    assert level.status == "fail" and level.message.startswith("Rear Left captured 18 dB below")
    assert r.reliable is False

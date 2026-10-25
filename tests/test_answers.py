import pytest
import synth
from audio_zones_delay.answers import compute_answers
from audio_zones_delay.model import Speaker
from audio_zones_delay.timeline import Timeline
from synth import emissions_for


def timeline_with(emissions, se=0.01, closure=0.0):
    return Timeline(
        emission_ms=dict(emissions),
        emission_se_ms={k: se for k in emissions},
        drift_ppm=0.0,
        closure_residual_ms=closure,
        visits=[],
        no_signal=[],
    )


def test_full_mode_matches_spec_example():
    p = synth.test_profile()
    ans = compute_answers(timeline_with(emissions_for(p)), p)
    assert ans.mode == "full"
    assert ans.speaker_delay_ms["rear-left"] == pytest.approx(36.052187, abs=1e-5)
    assert ans.speaker_delay_ms["rear-right"] == pytest.approx(35.177551, abs=1e-5)
    assert ans.headline_ms == pytest.approx(41.3, abs=1e-6)
    assert ans.a1_spread_ms == pytest.approx(0.0, abs=1e-9)
    left = next(c for c in ans.channels if c.channel == "L")
    assert (left.fits_30, left.fits_80) == (False, True)


def test_shared_channel_gets_compromise_and_residuals():
    p = synth.test_profile()
    p.speaker("rear-right").delay_channel = "L"
    (ch,) = compute_answers(timeline_with(emissions_for(p)), p).channels
    assert ch.delay_ms == pytest.approx(35.614869, abs=1e-5)
    assert ch.residual_ms == pytest.approx({"rear-left": 0.437318, "rear-right": -0.437318}, abs=1e-5)


def test_device_latency_is_subtracted():
    p = synth.test_profile()
    p.device_latency_ms = 2.0
    left = next(c for c in compute_answers(timeline_with(emissions_for(p)), p).channels if c.channel == "L")
    assert left.dial_ms == pytest.approx(34.052187, abs=1e-5)


def test_zone2_late_gives_negative_delay_that_fits_nothing():
    p = synth.test_profile()
    ans = compute_answers(timeline_with(emissions_for(p, zone2_ms=60.0)), p)
    assert all(c.delay_ms < 0 and not c.fits_30 and not c.fits_80 for c in ans.channels)
    assert ans.headline_ms == pytest.approx(41.3 - 60.0, abs=1e-6)


def test_unmeasured_sub_moves_headline_but_not_delays():
    p = synth.test_profile()
    p.speakers.append(Speaker("subwoofer-1", "Sub 1", 1, measured=False, anthem_distance_m=4.5))
    ans = compute_answers(timeline_with(emissions_for(synth.test_profile())), p)
    assert ans.headline_ms == pytest.approx(40.425364, abs=1e-5)
    assert ans.speaker_delay_ms["rear-left"] == pytest.approx(36.052187, abs=1e-5)


def test_missing_distances_fall_back_to_raw():
    p = synth.test_profile()
    p.speaker("rear-left").seat_distance_m = None
    ans = compute_answers(timeline_with(emissions_for(synth.test_profile())), p)
    assert ans.mode == "raw" and ans.channels == [] and ans.raw_gap_ms == pytest.approx(41.3, abs=1e-6)
    assert ans.headline_ms is None and ans.a1_spread_ms is None


def test_uncertainty_takes_the_largest_source():
    p = synth.test_profile()
    ans = compute_answers(timeline_with(emissions_for(p), closure=0.7), p)
    assert ans.uncertainty_ms == pytest.approx(0.7)


def test_raw_uncertainty_is_never_below_closure():
    p = synth.test_profile()
    p.speaker("rear-left").seat_distance_m = None
    ans = compute_answers(timeline_with(emissions_for(p), closure=-0.9), p)
    assert ans.uncertainty_ms == pytest.approx(0.9)


def test_no_zone2_speaker_counted_gives_empty_raw_answers():
    p = synth.test_profile()
    em = {k: v for k, v in emissions_for(p).items() if k not in ("rear-left", "rear-right")}
    ans = compute_answers(timeline_with(em, closure=0.4), p)
    assert ans.mode == "raw" and ans.headline_ms is None and ans.raw_gap_ms is None
    assert ans.channels == [] and ans.speaker_delay_ms == {}
    assert ans.uncertainty_ms == pytest.approx(0.4)

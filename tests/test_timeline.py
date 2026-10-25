import numpy as np
import pytest
import synth
from audio_zones_delay.assign import Assigned, Assignment
from audio_zones_delay.detect import Detection
from audio_zones_delay.timeline import fit_timeline
from synth import SynthOptions, emissions_for, ideal_arrivals, synth_session


def assignment_from(log, opts, jitter_s=2e-5, keep=None, strength=lambda a: 50.0):
    slot_to_attempt = {s: a for a in log.attempts for s in a.slots}
    rng = np.random.default_rng(3)
    arrivals = ideal_arrivals(log, emissions_for(synth.test_profile()), opts)
    assigned = []
    for t, slot in arrivals:
        a = slot_to_attempt[slot]
        item = Assigned(Detection(t + rng.normal(0, jitter_s), 0.0, 20.0), slot, a.visit, a.attempt)
        item.detection = Detection(item.detection.time_s, strength(item), 20.0)
        if keep is None or keep(item):
            assigned.append(item)
    return Assignment(assigned=assigned, spurious=[], missing_slots=[], match_ratio=1.0)


def test_recovers_drift_and_emissions():
    opts = SynthOptions(drift_ppm=40.0)
    log, _ = synth_session(synth.test_profile(), emissions_for(synth.test_profile()), opts)
    tl = fit_timeline(assignment_from(log, opts), log)
    assert tl.drift_ppm == pytest.approx(40.0, abs=0.5)
    truth = emissions_for(synth.test_profile())
    for k in truth:
        assert tl.emission_ms[k] - tl.emission_ms["rear-left"] == pytest.approx(truth[k] - truth["rear-left"], abs=0.03)
    assert abs(tl.closure_residual_ms) < 0.1
    assert max(tl.emission_se_ms.values()) < 0.05


def test_playback_glitch_shows_in_closure():
    opts = SynthOptions(glitch_after_visit=2, glitch_ms=1.5)
    log, _ = synth_session(synth.test_profile(), emissions_for(synth.test_profile()), opts)
    tl = fit_timeline(assignment_from(log, opts), log)
    assert tl.closure_residual_ms == pytest.approx(1.5, abs=0.2)


def test_visit_with_too_few_detections_is_no_signal():
    opts = SynthOptions()
    log, _ = synth_session(synth.test_profile(), emissions_for(synth.test_profile()), opts)
    tl = fit_timeline(assignment_from(log, opts, keep=lambda a: not (a.visit == 1 and a.slot > log.attempts[1].slots[1])), log)
    assert tl.no_signal == ["center"] and "center" not in tl.emission_ms


def test_quiet_visit_is_no_signal():
    opts = SynthOptions()
    log, _ = synth_session(synth.test_profile(), emissions_for(synth.test_profile()), opts)
    tl = fit_timeline(assignment_from(log, opts, strength=lambda a: 2.0 if a.visit == 1 else 50.0), log)
    assert tl.no_signal == ["center"] and "center" not in tl.emission_ms


def test_missing_closure_gives_none():
    opts = SynthOptions()
    log, _ = synth_session(synth.test_profile(), emissions_for(synth.test_profile()), opts)
    tl = fit_timeline(assignment_from(log, opts, keep=lambda a: a.visit != 5), log)
    assert tl.closure_residual_ms is None
    assert tl.closure_se_ms is None


def test_closure_se_is_small_and_positive_on_clean_session():
    opts = SynthOptions(drift_ppm=40.0)
    log, _ = synth_session(synth.test_profile(), emissions_for(synth.test_profile()), opts)
    tl = fit_timeline(assignment_from(log, opts), log)
    assert 0.0 < tl.closure_se_ms < 0.2

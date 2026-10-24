import numpy as np
import pytest
import synth
from audio_zones_delay.assign import AlignmentError, assign_detections
from audio_zones_delay.detect import Detection
from synth import SynthOptions, emissions_for, ideal_arrivals, synth_session


def dets(log, opts, extra_times=()):
    arr = ideal_arrivals(log, emissions_for(synth.test_profile()), opts)
    rng = np.random.default_rng(1)
    ds = [Detection(t + rng.normal(0, 2e-5), 50.0, 20.0) for t, _ in arr]
    return sorted(ds + [Detection(t, 12.0, 1.5) for t in extra_times], key=lambda d: d.time_s)


def make(opts):
    profile = synth.test_profile()
    log, _ = synth_session(profile, emissions_for(profile), opts)
    return log


def test_clean_session_assigns_every_detection():
    opts = SynthOptions(lead_in_s=7.3, drift_ppm=80.0)
    log = make(opts)
    a = assign_detections(dets(log, opts), log)
    assert a.match_ratio == 1.0 and a.spurious == [] and a.missing_slots == []
    assert [x.slot for x in a.assigned] == [s for at in log.attempts for s in at.slots]


def test_redo_uses_last_attempt():
    opts = SynthOptions(redo_visits=frozenset({3}))
    log = make(opts)
    a = assign_detections(dets(log, opts), log)
    assert {x.attempt for x in a.assigned if x.visit == 3} == {1, 2}
    assert log.used_attempts()[3].attempt == 2 and a.missing_slots == []


def test_off_grid_noise_is_spurious():
    opts = SynthOptions()
    log = make(opts)
    a = assign_detections(dets(log, opts, extra_times=(6.1, 21.9)), log)
    assert len(a.spurious) == 2 and a.match_ratio == pytest.approx(30 / 32)


def test_cropped_recording_reports_missing_closure():
    opts = SynthOptions()
    log = make(opts)
    a = assign_detections(dets(log, opts)[:-5], log)  # phone stopped before the closure visit
    assert a.missing_slots == log.attempts[-1].slots


def test_wrong_session_raises():
    profile = synth.test_profile()
    log_a, _ = synth_session(profile, emissions_for(profile), SynthOptions(walk_s=4.0))
    log_b, _ = synth_session(profile, emissions_for(profile), SynthOptions(walk_s=7.0))
    with pytest.raises(AlignmentError):
        assign_detections(dets(log_a, SynthOptions(walk_s=4.0)), log_b)

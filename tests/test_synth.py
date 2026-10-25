import numpy as np
import pytest

import synth
from audio_zones_delay.model import session_from_dict, session_to_dict
from synth import SynthOptions, emissions_for, ideal_arrivals, synth_session


def test_synth_logs_one_attempt_per_visit_plus_redo():
    p = synth.test_profile()
    log, rec = synth_session(p, emissions_for(p), SynthOptions(redo_visits=frozenset({1})))
    assert [v.speaker_id for v in log.visits] == ["front-left", "center", "surround-back-left", "rear-left", "rear-right", "front-left"]
    assert [a.visit for a in log.attempts] == [0, 1, 1, 2, 3, 4, 5]
    assert rec.ndim == 1 and np.max(np.abs(rec)) < 1.0
    session_from_dict(session_to_dict(log))


def test_ideal_arrivals_follow_drift():
    p = synth.test_profile()
    opts = SynthOptions(drift_ppm=100.0)
    log, _ = synth_session(p, emissions_for(p), opts)
    t, slot = ideal_arrivals(log, emissions_for(p), opts)[-1]
    assert t == pytest.approx(3.0 + (slot * 2.0 + 43.049271e-3 + 0.2 / 343) * (1 + 100e-6), abs=1e-9)


def test_emissions_follow_anthem_distances():
    e = emissions_for(synth.test_profile())
    assert e["front-left"] == pytest.approx(41.3 + 0.6 / 343 * 1000)
    assert e["center"] == pytest.approx(41.3 + 0.8 / 343 * 1000)
    assert e["surround-back-left"] == pytest.approx(41.3)
    assert e["rear-left"] == 0.0


def test_dropped_and_silent_visits_have_no_arrivals():
    p = synth.test_profile()
    opts = SynthOptions(drop_visits=frozenset({0}), silent_speakers=frozenset({"center"}))
    log, _ = synth_session(p, emissions_for(p), opts)
    assert len(log.attempts) == 6
    assert len(ideal_arrivals(log, emissions_for(p), opts)) == 4 * 5

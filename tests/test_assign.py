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
    assert a.shift_ambiguous is False
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
    assert a.shift_ambiguous is True


def test_late_start_resolves_to_smallest_shift_and_flags_it():
    opts = SynthOptions()
    log = make(opts)
    a = assign_detections(dets(log, opts)[5:], log)  # phone started after the first visit
    assert set(log.attempts[-1].slots) <= set(a.missing_slots)
    assert a.shift_ambiguous is True


def test_partial_fit_tie_raises():
    log = make(SynthOptions())
    # Grid indices 0-4 fit slots 3-7 (or 10-14) but index 20 fits neither: two tied partial fits.
    ds = [Detection(2.0 * i + 0.3, 50.0, 20.0) for i in (0, 1, 2, 3, 4, 20)]
    with pytest.raises(AlignmentError, match="ambiguous"):
        assign_detections(ds, log)


def test_wrong_session_raises():
    profile = synth.test_profile()
    log_a, _ = synth_session(profile, emissions_for(profile), SynthOptions(walk_s=4.0))
    log_b, _ = synth_session(profile, emissions_for(profile), SynthOptions(walk_s=7.0))
    with pytest.raises(AlignmentError):
        assign_detections(dets(log_a, SynthOptions(walk_s=4.0)), log_b)


def with_slots(log, opts):
    """Detections of ``dets`` paired with the slot each one belongs to."""
    arrivals = ideal_arrivals(log, emissions_for(synth.test_profile()), opts)
    return list(zip(dets(log, opts), [slot for _, slot in arrivals]))


def test_weak_detections_are_spurious_and_not_counted():
    opts = SynthOptions()
    log = make(opts)
    dropped = log.attempts[2].slots
    pairs = with_slots(log, opts)
    kept = [d for d, slot in pairs if slot not in dropped]
    # Weak noise peaks (40 dB below the signatures), on the dropped slots and on unlogged grid indices.
    d0, slot0 = pairs[0]
    weak = [Detection(d0.time_s + 2.0 * (k - slot0), 0.5, 1.2)
            for k in dropped + [0, 1, 2, 8, 9, 15, 16, 45, 46]]
    a = assign_detections(sorted(kept + weak, key=lambda d: d.time_s), log)
    assert len(a.assigned) == 25 and a.match_ratio == 1.0
    assert set(weak) <= set(a.spurious)
    assert a.missing_slots == dropped


def test_quiet_visit_of_a_silent_speaker_is_still_assigned():
    opts = SynthOptions()
    log = make(opts)
    owner = {s: a.visit for a in log.attempts for s in a.slots}
    # Visit 1 (a silent speaker) only picks up the other speakers, about 23 dB down.
    quiet = 50.0 * 10 ** (-23 / 20)
    ds = [Detection(d.time_s, quiet if owner[slot] == 1 else 50.0, 20.0)
          for d, slot in with_slots(log, opts)]
    a = assign_detections(ds, log)
    assert sum(x.visit == 1 for x in a.assigned) == 5 and a.spurious == []

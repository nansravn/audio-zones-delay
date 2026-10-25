import copy
from dataclasses import replace
from functools import cache

import pytest
import synth
from audio_zones_delay.answers import Answers, compute_answers
from audio_zones_delay.assign import Assignment
from audio_zones_delay.checks import is_reliable, run_checks
from audio_zones_delay.timeline import Timeline, VisitStats
from synth import emissions_for, synth_session


@cache
def session():
    # Visits: 0 front-left, 1 center, 2 surround-back-left, 3 rear-left, 4 rear-right, 5 front-left (closure).
    log, _ = synth_session(synth.test_profile(), emissions_for(synth.test_profile()))
    return log


def clean_timeline():
    log = session()
    return Timeline(
        emission_ms=emissions_for(log.profile),
        emission_se_ms={s.id: 0.01 for s in log.profile.speakers},
        drift_ppm=40.0,
        closure_residual_ms=0.1,
        visits=[VisitStats(v.index, v.speaker_id, 5, 0.0, 0.05, 20.0, 50.0) for v in log.visits],
        no_signal=[],
        closure_se_ms=0.05,
    )


def without(tl, *speakers):
    return replace(
        tl,
        emission_ms={k: v for k, v in tl.emission_ms.items() if k not in speakers},
        visits=[v for v in tl.visits if v.speaker_id not in speakers],
        no_signal=list(speakers),
    )


def checks(tl=None, answers=None, assignment=None, log=None):
    log = log or session()
    tl = tl or clean_timeline()
    answers = answers or compute_answers(tl, log.profile)
    assignment = assignment or Assignment([], [], [], 1.0)
    return {c.key: c for c in run_checks(assignment, tl, answers, log)}


def test_clean_inputs_pass_in_order():
    tl = clean_timeline()
    result = run_checks(Assignment([], [], [], 1.0), tl, compute_answers(tl, session().profile), session())
    assert [c.key for c in result] == [
        "drift", "closure", "repeat_spread", "zone1_consistency", "zone2_consistency", "distances",
        "coverage", "dominance", "level",
    ]
    assert all(c.status == "pass" for c in result) and is_reliable(result)


@pytest.mark.parametrize("ppm, status", [(-150.0, "pass"), (200.0, "pass"), (250.0, "fail")])
def test_drift(ppm, status):
    assert checks(replace(clean_timeline(), drift_ppm=ppm))["drift"].status == status


@pytest.mark.parametrize("r, se, status", [
    (0.4, 0.05, "pass"),
    (-0.8, 0.05, "warn"),
    (1.2, 0.05, "fail"),
    (1.2, 0.35, "warn"),   # pass limit 3*se = 1.05, warn limit 4*se = 1.4
    (1.2, 0.5, "pass"),    # pass limit 3*se = 1.5
    (2.0, 0.45, "fail"),   # warn limit 4*se = 1.8
])
def test_closure_thresholds_follow_noise(r, se, status):
    c = checks(replace(clean_timeline(), closure_residual_ms=r, closure_se_ms=se))["closure"]
    assert c.status == status
    assert f"{abs(r):.2f} ms" in c.message and f"{se:.2f} ms" in c.message


def test_missing_closure_fails():
    c = checks(replace(clean_timeline(), closure_residual_ms=None, closure_se_ms=None))["closure"]
    assert (c.status, c.message) == ("fail", "closure visit not captured: record the whole session")


def test_missing_closure_after_ambiguous_shift_suggests_late_start():
    tl = replace(clean_timeline(), closure_residual_ms=None, closure_se_ms=None)
    c = checks(tl, assignment=Assignment([], [], [], 1.0, shift_ambiguous=True))["closure"]
    assert c.status == "fail"
    assert c.message == ("closure visit not captured: the phone may have started recording late "
                         "or stopped early; record the whole session")


@pytest.mark.parametrize("ambiguous", [False, True])
def test_silent_closure_speaker_fails_naming_it(ambiguous):
    tl = replace(without(clean_timeline(), "front-left"), closure_residual_ms=None, closure_se_ms=None)
    c = checks(tl, assignment=Assignment([], [], [], 1.0, shift_ambiguous=ambiguous))["closure"]
    assert c.status == "fail"
    assert c.message == ("closure speaker Front Left has no signal in this mode, so playback "
                         "stability cannot be checked; start the speaker list with a speaker that "
                         "plays in this mode and record again")


@pytest.mark.parametrize("spread, status", [(0.2, "pass"), (0.3, "warn"), (0.6, "fail")])
def test_repeat_spread_uses_worst_visit(spread, status):
    tl = clean_timeline()
    tl.visits[3] = replace(tl.visits[3], spread_ms=spread)
    c = checks(tl)["repeat_spread"]
    assert c.status == status and "Rear Left" in c.message


@pytest.mark.parametrize("spread, status", [(1.0, "pass"), (1.5, "warn"), (2.5, "fail")])
def test_zone1_consistency_grades_a1_spread(spread, status):
    a1 = {"front-left": 52.0, "center": 52.0 + spread}
    answers = Answers("full", 41.3, None, a1, {}, {}, [], 0.1, spread)
    c = checks(answers=answers)["zone1_consistency"]
    assert c.status == status
    if status == "fail":
        assert "check the Anthem distances entered" in c.message


def test_zone1_consistency_warns_with_one_zone1_speaker():
    answers = Answers("full", 41.3, None, {"front-left": 52.0}, {}, {}, [], 0.1, 0.0)
    c = checks(answers=answers)["zone1_consistency"]
    assert (c.status, c.message) == (
        "warn", "only one zone 1 speaker has signal: Anthem distances not cross-checked")


def test_zone1_consistency_warns_in_raw_mode():
    answers = Answers("raw", None, 41.3, {}, {}, {}, [], 0.1, None)
    c = checks(answers=answers)["zone1_consistency"]
    assert c.status == "warn" and "enter distances for per-speaker delays" in c.message


def test_zone1_speaker_without_signal_is_info_only():
    log = session()
    center_slots = [s for a in log.attempts if a.visit == 1 for s in a.slots]
    c = checks(without(clean_timeline(), "center"),
               assignment=Assignment([], [], center_slots, 1.0))["coverage"]
    assert c.status == "pass" and "Center" in c.message


def test_missing_signatures_warn():
    missing = [session().attempts[0].slots[2]]
    c = checks(assignment=Assignment([], [], missing, 1.0))["coverage"]
    assert c.status == "warn" and "1 expected signature" in c.message


def test_zone2_speaker_without_signal_warns():
    c = checks(without(clean_timeline(), "rear-right"))["coverage"]
    assert c.status == "warn" and "Rear Right" in c.message


@pytest.mark.parametrize("silent, zone", [
    (("rear-left", "rear-right"), 2),
    (("front-left", "center", "surround-back-left"), 1),
])
def test_zone_without_signal_fails(silent, zone):
    c = checks(without(clean_timeline(), *silent))["coverage"]
    assert c.status == "fail" and f"no zone {zone} speaker has signal" in c.message


@pytest.mark.parametrize("dominance, status", [(2.0, "pass"), (1.6, "warn"), (1.2, "fail")])
def test_dominance_uses_worst_visit(dominance, status):
    tl = clean_timeline()
    tl.visits[1] = replace(tl.visits[1], dominance=dominance)
    c = checks(tl)["dominance"]
    assert c.status == status
    if status == "fail":
        assert "hold the phone closer to Center" in c.message


def with_rear_right_at(tl, ms):
    return replace(tl, emission_ms={**tl.emission_ms, "rear-right": ms})


@pytest.mark.parametrize("spread, status", [(1.0, "pass"), (1.5, "warn"), (2.5, "fail")])
def test_zone2_consistency_grades_emission_spread(spread, status):
    tl = clean_timeline()
    c = checks(with_rear_right_at(tl, tl.emission_ms["rear-left"] + spread))["zone2_consistency"]
    assert c.status == status
    if status == "fail":
        assert c.message == ("zone 2 speakers disagree by 2.5 ms: a capture may have picked up a "
                             "zone 1 speaker; raise Zone 2 volume to match zone 1 and record again")


def test_zone2_consistency_works_in_raw_mode():
    tl = with_rear_right_at(clean_timeline(), 5.0)
    answers = Answers("raw", None, 41.3, {}, {}, {}, [], 0.1, None)
    assert checks(tl, answers=answers)["zone2_consistency"].status == "fail"


def test_zone2_consistency_warns_with_one_zone2_speaker():
    c = checks(without(clean_timeline(), "rear-right"))["zone2_consistency"]
    assert (c.status, c.message) == (
        "warn", "only one zone 2 speaker has signal: zone 2 timing not cross-checked")


def test_zone2_consistency_without_zone2_signal_warns():
    c = checks(without(clean_timeline(), "rear-left", "rear-right"))["zone2_consistency"]
    assert c.status == "warn" and "no zone 2 speaker has signal" in c.message


def quiet(tl, visit, db):
    tl.visits[visit] = replace(tl.visits[visit], median_strength=50.0 * 10 ** (db / 20))
    return tl


@pytest.mark.parametrize("db, status", [(-11.0, "pass"), (-13.0, "fail")])
def test_level_fails_a_quiet_capture(db, status):
    c = checks(quiet(clean_timeline(), 3, db))["level"]
    assert c.status == status
    if status == "fail":
        assert c.message == ("Rear Left captured 13 dB below the other speakers: hold the phone "
                             "closer or match that zone's volume, then record again")


@pytest.mark.parametrize("visit", [1, 3])  # a zone 1 (Center) and a zone 2 (Rear Left) visit
def test_level_fails_in_either_zone(visit):
    tl = quiet(clean_timeline(), visit, -13.0)
    result = run_checks(Assignment([], [], [], 1.0), tl, compute_answers(tl, session().profile), session())
    assert next(c for c in result if c.key == "level").status == "fail"
    assert not is_reliable(result)


def test_level_names_every_quiet_speaker():
    c = checks(quiet(quiet(clean_timeline(), 3, -18.0), 4, -14.0))["level"]
    assert c.status == "fail"
    assert c.message.startswith("Rear Left, Rear Right captured up to 18 dB below")


def profile_with(speaker, field, value):
    log = copy.deepcopy(session())
    setattr(log.profile.speaker(speaker), field, value)
    return log


@pytest.mark.parametrize("speaker, field", [("center", "anthem_distance_m"),
                                            ("rear-right", "seat_distance_m")])
def test_distance_in_feet_warns(speaker, field):
    log = profile_with(speaker, field, 20.67)
    c = checks(log=log)["distances"]
    name = log.profile.speaker(speaker).name
    assert (c.status, c.message) == (
        "warn", f"distance 20.7 m ({name}) looks too large — enter metres, not feet")


def test_distance_of_15_m_passes():
    assert checks(log=profile_with("center", "anthem_distance_m", 15.0))["distances"].status == "pass"

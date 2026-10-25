import json
import re
from pathlib import Path

import pytest

from audio_zones_delay.model import (
    RoomProfile,
    Speaker,
    Visit,
    build_visits,
    default_profile,
    load_session,
    profile_from_dict,
    profile_to_dict,
    session_from_dict,
    session_to_dict,
)

FIXTURE = Path(__file__).parent / "fixtures" / "session-example.json"


def test_session_round_trip():
    d = json.loads(FIXTURE.read_text())
    assert session_to_dict(session_from_dict(d)) == d


def test_used_attempts_takes_last_attempt_per_visit():
    s = load_session(FIXTURE)
    assert {v: a.attempt for v, a in s.used_attempts().items()} == {0: 1, 1: 2, 2: 1}


@pytest.mark.parametrize("mutate, field", [
    (lambda d: d["profile"]["speakers"].append(dict(d["profile"]["speakers"][0])), "id"),
    (lambda d: d["profile"]["speakers"][0].update(zone=3), "zone"),
    (lambda d: d["profile"]["speakers"][0].update(id="Front Left"), "id"),
    (lambda d: d["profile"]["speakers"][0].update(anthem_distance_m=-1), "anthem_distance_m"),
    (lambda d: d["profile"].update(signatures_per_visit=2), "signatures_per_visit"),
    (lambda d: d["attempts"][1].update(slots=[11, 12, 13, 14]), "slots"),
    (lambda d: d["attempts"][2].update(slots=[1, 2, 3, 4, 5]), "slots"),
    (lambda d: d["visits"][1].update(speaker_id="nope"), "speaker_id"),
])
def test_invalid_session_raises(mutate, field):
    d = json.loads(FIXTURE.read_text()); mutate(d)
    with pytest.raises(ValueError, match=field):
        session_from_dict(d)


NAN, INF = float("nan"), float("inf")


def _set(path, value):
    """Mutator that sets d[path[0]][path[1]]... to ``value`` (a missing last key is added)."""
    def mutate(d):
        for key in path[:-1]:
            d = d[key]
        d[path[-1]] = value
    return mutate


def _drop_signature_field(d):
    del d["signature"]["fade_s"]


@pytest.mark.parametrize("path, value", [
    (("profile", "speed_of_sound_m_s"), v) for v in (0, -343.0, None, 299.9, 400.1, NAN, INF, "343", True)
] + [
    (("profile", "device_latency_ms"), v) for v in (NAN, -1, -0.1, 1000.1, INF, None, "0")
] + [
    ((level, "signatures_per_visit"), v) for level in ("profile", None)
    for v in (4.5, 5.0, True, 2, 21, None, "5")
] + [
    ((level, "period_s"), v) for level in ("profile", None)
    for v in (INF, NAN, 0.99, 10.01, 0, None, "2")
] + [
    (("profile", "speakers", 0, "anthem_distance_m"), v) for v in (0, -1, 50.01, NAN, INF, "3")
] + [
    (("profile", "speakers", 1, "seat_distance_m"), v) for v in (0, 50.5, NAN, INF, "6")
])
def test_out_of_range_numbers_raise_naming_the_field(path, value):
    d = json.loads(FIXTURE.read_text())
    path = tuple(p for p in path if p is not None)
    _set(path, value)(d)
    with pytest.raises(ValueError, match=str(path[-1])):
        session_from_dict(d)


@pytest.mark.parametrize("mutate", [
    _drop_signature_field,
    _set(("signature", "extra_hz"), 1.0),
    _set(("signature", "duration_s"), NAN),
    _set(("signature", "peak_dbfs"), "-6"),
    _set(("signature", "f_end_hz"), None),
    _set(("signature", "fade_s"), True),
])
def test_bad_signature_raises(mutate):
    d = json.loads(FIXTURE.read_text())
    mutate(d)
    with pytest.raises(ValueError, match="signature"):
        session_from_dict(d)


FREQS = "signature frequencies must satisfy 0 < f_start_hz < f_end_hz"


@pytest.mark.parametrize("field, value, message", [
    ("f_start_hz", 0.0, FREQS), ("f_start_hz", -300.0, FREQS), ("f_start_hz", 12000.0, FREQS),
    ("f_start_hz", 13000.0, FREQS), ("f_end_hz", 300.0, FREQS), ("f_end_hz", 0.0, FREQS),
    ("duration_s", 0.0, "signature duration_s"), ("duration_s", -0.5, "signature duration_s"),
    ("duration_s", 2.0, "signature duration_s"), ("duration_s", 2.5, "signature duration_s"),
    ("fade_s", -0.001, "signature fade_s"), ("fade_s", 0.25, "signature fade_s"),
    ("fade_s", 0.3, "signature fade_s"),
])
def test_signature_params_out_of_range_raise(field, value, message):
    d = json.loads(FIXTURE.read_text())  # period_s 2.0, duration_s 0.5
    d["signature"][field] = value
    with pytest.raises(ValueError, match=re.escape(message)):
        session_from_dict(d)


@pytest.mark.parametrize("field, value", [
    ("f_start_hz", 1.0), ("f_end_hz", 300.5), ("duration_s", 1.99), ("fade_s", 0.0),
    ("fade_s", 0.249),
])
def test_signature_params_inside_the_range_are_accepted(field, value):
    d = json.loads(FIXTURE.read_text())
    d["signature"][field] = value
    session_from_dict(d)


@pytest.mark.parametrize("path, value", [
    (("profile", "speed_of_sound_m_s"), 300), (("profile", "speed_of_sound_m_s"), 400.0),
    (("profile", "device_latency_ms"), 0), (("profile", "device_latency_ms"), 1000.0),
    (("profile", "signatures_per_visit"), 3), (("profile", "signatures_per_visit"), 20),
    (("profile", "period_s"), 1), (("profile", "period_s"), 10.0), (("period_s",), 1.0),
    (("profile", "speakers", 0, "anthem_distance_m"), 50.0),
    (("profile", "speakers", 1, "seat_distance_m"), None),
])
def test_boundary_numbers_are_accepted(path, value):
    d = json.loads(FIXTURE.read_text())
    _set(path, value)(d)
    session_from_dict(d)


def test_build_visits_skips_unmeasured_and_appends_closure():
    p = RoomProfile(speakers=[Speaker("fl", "FL", 1), Speaker("sub", "Sub", 1, measured=False), Speaker("rl", "RL", 2)])
    assert build_visits(p) == [Visit(0, "fl"), Visit(1, "rl"), Visit(2, "fl", closure=True)]


def test_build_visits_without_measured_speakers_raises():
    with pytest.raises(ValueError):
        build_visits(RoomProfile(speakers=[Speaker("sub", "Sub", 1, measured=False)]))


def test_default_profile_matches_owner_layout():
    p = default_profile()
    assert sum(s.measured and s.zone == 1 for s in p.speakers) == 11
    assert sum(not s.measured for s in p.speakers) == 2
    assert sum(s.zone == 2 for s in p.speakers) == 4
    assert profile_from_dict(profile_to_dict(p)) == p

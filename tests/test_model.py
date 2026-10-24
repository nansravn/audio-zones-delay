import json
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

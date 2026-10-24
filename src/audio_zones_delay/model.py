"""Room profile and session log model: plain dataclasses and JSON conversion."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")


@dataclass
class Speaker:
    id: str
    name: str
    zone: int
    measured: bool = True
    anthem_distance_m: float | None = None
    seat_distance_m: float | None = None
    delay_channel: str | None = None


@dataclass
class RoomProfile:
    speakers: list[Speaker]
    speed_of_sound_m_s: float = 343.0
    device_latency_ms: float = 0.0
    signatures_per_visit: int = 5
    period_s: float = 2.0
    schema: int = 1

    def speaker(self, id: str) -> Speaker:
        for s in self.speakers:
            if s.id == id:
                return s
        raise KeyError(id)


@dataclass
class Visit:
    index: int
    speaker_id: str
    closure: bool = False


@dataclass
class Attempt:
    visit: int
    attempt: int
    slots: list[int]


@dataclass
class SessionLog:
    session_id: str
    label: str
    created_at: str
    sample_rate: int
    period_s: float
    signatures_per_visit: int
    signature: dict
    profile: RoomProfile
    visits: list[Visit]
    attempts: list[Attempt]
    completed: bool
    schema: int = 1

    def used_attempts(self) -> dict[int, Attempt]:
        """Last attempt per visit, keyed by visit index."""
        used: dict[int, Attempt] = {}
        for a in self.attempts:
            used[a.visit] = a
        return used


def _validate_profile(p: RoomProfile) -> None:
    seen: set[str] = set()
    for s in p.speakers:
        if not isinstance(s.id, str) or not _ID_RE.match(s.id):
            raise ValueError(f"speaker id {s.id!r} must be a lowercase slug")
        if s.id in seen:
            raise ValueError(f"speaker id {s.id!r} is duplicated")
        seen.add(s.id)
        if s.zone not in (1, 2):
            raise ValueError(f"speaker {s.id!r}: zone must be 1 or 2, got {s.zone!r}")
        for name in ("anthem_distance_m", "seat_distance_m"):
            v = getattr(s, name)
            if v is not None and not v > 0:
                raise ValueError(f"speaker {s.id!r}: {name} must be None or > 0, got {v!r}")
    if p.signatures_per_visit < 3:
        raise ValueError(f"signatures_per_visit must be >= 3, got {p.signatures_per_visit!r}")
    if p.period_s < 1.0:
        raise ValueError(f"period_s must be >= 1.0, got {p.period_s!r}")


def profile_from_dict(d: dict) -> RoomProfile:
    try:
        speakers = [
            Speaker(
                id=s["id"],
                name=s["name"],
                zone=s["zone"],
                measured=s.get("measured", True),
                anthem_distance_m=s.get("anthem_distance_m"),
                seat_distance_m=s.get("seat_distance_m"),
                delay_channel=s.get("delay_channel"),
            )
            for s in d["speakers"]
        ]
        p = RoomProfile(
            speakers=speakers,
            speed_of_sound_m_s=d.get("speed_of_sound_m_s", 343.0),
            device_latency_ms=d.get("device_latency_ms", 0.0),
            signatures_per_visit=d.get("signatures_per_visit", 5),
            period_s=d.get("period_s", 2.0),
            schema=d.get("schema", 1),
        )
    except KeyError as e:
        raise ValueError(f"profile is missing field {e.args[0]!r}") from e
    _validate_profile(p)
    return p


def profile_to_dict(p: RoomProfile) -> dict:
    return {
        "schema": p.schema,
        "speed_of_sound_m_s": p.speed_of_sound_m_s,
        "device_latency_ms": p.device_latency_ms,
        "signatures_per_visit": p.signatures_per_visit,
        "period_s": p.period_s,
        "speakers": [
            {
                "id": s.id,
                "name": s.name,
                "zone": s.zone,
                "measured": s.measured,
                "anthem_distance_m": s.anthem_distance_m,
                "seat_distance_m": s.seat_distance_m,
                "delay_channel": s.delay_channel,
            }
            for s in p.speakers
        ],
    }


def _validate_session(s: SessionLog) -> None:
    for i, v in enumerate(s.visits):
        if v.index != i:
            raise ValueError(f"visits: index must be {i}, got {v.index!r}")
        if not any(sp.id == v.speaker_id for sp in s.profile.speakers):
            raise ValueError(f"visit {i}: speaker_id {v.speaker_id!r} is not in the profile")
    last_slot = -1
    for a in s.attempts:
        if not 0 <= a.visit < len(s.visits):
            raise ValueError(f"attempt: visit {a.visit!r} does not exist")
        if len(a.slots) != s.signatures_per_visit:
            raise ValueError(
                f"attempt {a.attempt} of visit {a.visit}: slots must have "
                f"{s.signatures_per_visit} entries, got {len(a.slots)}"
            )
        if any(b - x != 1 for x, b in zip(a.slots, a.slots[1:])):
            raise ValueError(f"attempt {a.attempt} of visit {a.visit}: slots must be consecutive")
        if a.slots[0] <= last_slot:
            raise ValueError(
                f"attempt {a.attempt} of visit {a.visit}: slots must increase across attempts"
            )
        last_slot = a.slots[-1]


def session_from_dict(d: dict) -> SessionLog:
    try:
        s = SessionLog(
            session_id=d["session_id"],
            label=d["label"],
            created_at=d["created_at"],
            sample_rate=d["sample_rate"],
            period_s=d["period_s"],
            signatures_per_visit=d["signatures_per_visit"],
            signature=dict(d["signature"]),
            profile=profile_from_dict(d["profile"]),
            visits=[Visit(v["index"], v["speaker_id"], v.get("closure", False)) for v in d["visits"]],
            attempts=[Attempt(a["visit"], a["attempt"], list(a["slots"])) for a in d["attempts"]],
            completed=d["completed"],
            schema=d.get("schema", 1),
        )
    except KeyError as e:
        raise ValueError(f"session is missing field {e.args[0]!r}") from e
    _validate_session(s)
    return s


def session_to_dict(s: SessionLog) -> dict:
    return {
        "schema": s.schema,
        "session_id": s.session_id,
        "label": s.label,
        "created_at": s.created_at,
        "sample_rate": s.sample_rate,
        "period_s": s.period_s,
        "signatures_per_visit": s.signatures_per_visit,
        "signature": dict(s.signature),
        "profile": profile_to_dict(s.profile),
        "visits": [{"index": v.index, "speaker_id": v.speaker_id, "closure": v.closure} for v in s.visits],
        "attempts": [{"visit": a.visit, "attempt": a.attempt, "slots": list(a.slots)} for a in s.attempts],
        "completed": s.completed,
    }


def load_session(path: Path) -> SessionLog:
    return session_from_dict(json.loads(Path(path).read_text()))


def build_visits(profile: RoomProfile) -> list[Visit]:
    """One visit per measured speaker, plus a closure revisit of the first."""
    measured = [s for s in profile.speakers if s.measured]
    if not measured:
        raise ValueError("profile has no measured speakers")
    visits = [Visit(i, s.id) for i, s in enumerate(measured)]
    visits.append(Visit(len(measured), measured[0].id, closure=True))
    return visits


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def default_profile() -> RoomProfile:
    zone1 = [
        "Front Left", "Center", "Front Right", "Surround Left", "Surround Right",
        "Surround Back Left", "Surround Back Right", "Top Front Left", "Top Front Right",
        "Top Rear Left", "Top Rear Right",
    ]
    subs = ["Subwoofer 1", "Subwoofer 2"]
    zone2 = [f"Zone 2 Speaker {i}" for i in range(1, 5)]
    speakers = (
        [Speaker(_slug(n), n, 1) for n in zone1]
        + [Speaker(_slug(n), n, 1, measured=False) for n in subs]
        + [Speaker(_slug(n), n, 2) for n in zone2]
    )
    return RoomProfile(speakers=speakers)

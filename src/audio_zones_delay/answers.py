"""Turn fitted emission times into zone 2 delays, channel settings and the headline."""

from __future__ import annotations

import math
from dataclasses import dataclass

from .model import RoomProfile
from .timeline import Timeline

FIT_30_MS = 30.0
FIT_80_MS = 80.0


@dataclass
class ChannelDelay:
    channel: str
    speaker_ids: list[str]
    delay_ms: float
    dial_ms: float
    residual_ms: dict[str, float]
    fits_30: bool
    fits_80: bool


@dataclass
class Answers:
    mode: str  # "full" or "raw"
    headline_ms: float | None
    raw_gap_ms: float | None
    a1_ms: dict[str, float]
    a2_ms: dict[str, float]
    speaker_delay_ms: dict[str, float]
    channels: list[ChannelDelay]
    uncertainty_ms: float
    a1_spread_ms: float | None


def _mean(values) -> float:
    values = list(values)
    return sum(values) / len(values)


def _se_of_mean(ses) -> float:
    ses = list(ses)
    return math.sqrt(sum(s * s for s in ses)) / len(ses)


def _channels(profile: RoomProfile, delays: dict[str, float]) -> list[ChannelDelay]:
    groups: dict[str, list[str]] = {}
    for s in profile.speakers:
        if s.id in delays:
            groups.setdefault(s.delay_channel or s.id, []).append(s.id)
    out = []
    for channel, ids in groups.items():
        delay = _mean(delays[i] for i in ids)
        dial = delay - profile.device_latency_ms
        out.append(ChannelDelay(
            channel=channel,
            speaker_ids=ids,
            delay_ms=delay,
            dial_ms=dial,
            residual_ms={i: delays[i] - delay for i in ids},
            fits_30=0.0 <= dial <= FIT_30_MS,
            fits_80=0.0 <= dial <= FIT_80_MS,
        ))
    return out


def compute_answers(timeline: Timeline, profile: RoomProfile) -> Answers:
    e = timeline.emission_ms
    se = timeline.emission_se_ms
    # The closure residual is the only witness of a playback glitch, which the
    # timeline fit folds into the emissions: it is a floor for the uncertainty.
    closure = abs(timeline.closure_residual_ms or 0.0)
    z1 = [s for s in profile.speakers if s.zone == 1 and s.id in e]
    z2 = [s for s in profile.speakers if s.zone == 2 and s.id in e]

    if not z1 or not z2:
        # Nothing to compare: the coverage check withholds the verdict.
        return Answers("raw", None, None, {}, {}, {}, [], closure, None)

    ms_per_m = 1000.0 / profile.speed_of_sound_m_s
    full = (all(s.anthem_distance_m is not None for s in z1)
            and all(s.seat_distance_m is not None for s in z2))
    se_mean_1 = _se_of_mean(se[s.id] for s in z1)

    if not full:
        se_mean_2 = _se_of_mean(se[s.id] for s in z2)
        gap = min(e[s.id] for s in z1) - _mean(e[s.id] for s in z2)
        unc = max(2.0 * math.hypot(se_mean_1, se_mean_2), closure)
        return Answers("raw", None, gap, {}, {}, {}, [], unc, None)

    a1 = {s.id: e[s.id] + s.anthem_distance_m * ms_per_m for s in z1}
    a2 = {s.id: e[s.id] + s.seat_distance_m * ms_per_m for s in z2}
    mean_a1 = _mean(a1.values())
    delays = {j: mean_a1 - a for j, a in a2.items()}

    d_max = max(s.anthem_distance_m for s in profile.speakers
                if s.zone == 1 and s.anthem_distance_m is not None)
    headline = (_mean(e[s.id] - (d_max - s.anthem_distance_m) * ms_per_m for s in z1)
                - _mean(e[s.id] for s in z2))
    spread = max(a1.values()) - min(a1.values())
    se_delay = max(math.hypot(se_mean_1, se[s.id]) for s in z2)
    unc = max(2.0 * se_delay, closure, spread / 2.0)
    return Answers("full", headline, None, a1, a2, delays, _channels(profile, delays), unc, spread)

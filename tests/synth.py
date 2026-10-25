"""Synthetic session generator: test infrastructure shared by the analysis tests."""

from __future__ import annotations

import math
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import fftconvolve

from audio_zones_delay.analysis import AnalysisResult, analyze
from audio_zones_delay.audio_io import ffmpeg_path, load_recording
from audio_zones_delay.model import (
    Attempt, RoomProfile, SessionLog, Speaker, build_visits,
)
from audio_zones_delay.signature import SIGNATURE_PARAMS, signature_waveform

C = 343.0
NEAR_PATH_M = 0.2
CLICK_LEAD_S = 0.25
HOLD_TAIL_S = 0.3
REDO_WALK_S = 1.0


@dataclass(frozen=True)
class SynthOptions:
    drift_ppm: float = 0.0
    lead_in_s: float = 3.0
    walk_s: float = 4.0
    noise_dbfs: float = -60.0
    reverb: bool = True
    redo_visits: frozenset = frozenset()
    silent_speakers: frozenset = frozenset()
    glitch_after_visit: int | None = None
    glitch_ms: float = 0.0
    clap_times_s: tuple = ()
    drop_visits: frozenset = frozenset()
    sample_rate: int = 48000
    seed: int = 0


def test_profile() -> RoomProfile:
    return RoomProfile(speakers=[
        Speaker("front-left", "Front Left", 1, anthem_distance_m=3.6),
        Speaker("center", "Center", 1, anthem_distance_m=3.4),
        Speaker("surround-back-left", "Surround Back Left", 1, anthem_distance_m=4.2),
        Speaker("rear-left", "Rear Left", 2, seat_distance_m=6.0, delay_channel="L"),
        Speaker("rear-right", "Rear Right", 2, seat_distance_m=6.3, delay_channel="R"),
    ])


test_profile.__test__ = False  # not a pytest test, wherever it is imported


def emissions_for(profile: RoomProfile, processing_ms: float = 41.3,
                  zone2_ms: float = 0.0) -> dict[str, float]:
    d_max = max(s.anthem_distance_m for s in profile.speakers
                if s.zone == 1 and s.anthem_distance_m is not None)
    c = profile.speed_of_sound_m_s
    out: dict[str, float] = {}
    for s in profile.speakers:
        if s.zone == 1:
            out[s.id] = processing_ms + (d_max - (s.anthem_distance_m or d_max)) / c * 1000.0
        else:
            out[s.id] = zone2_ms
    return out


def _plan(profile: RoomProfile, options: SynthOptions) -> list[Attempt]:
    """Slot plan as the player would log it."""
    period, n = profile.period_s, profile.signatures_per_visit
    attempts: list[Attempt] = []
    cursor, last = 1.0, -1
    for visit in build_visits(profile):
        walks = [options.walk_s]
        if visit.index in options.redo_visits:
            walks.append(REDO_WALK_S)
        for number, walk in enumerate(walks, start=1):
            click = cursor + walk
            first = max(last + 1, math.ceil((click + CLICK_LEAD_S) / period))
            attempts.append(Attempt(visit.index, number, list(range(first, first + n))))
            last = first + n - 1
            cursor = last * period + 0.5 + HOLD_TAIL_S
    return attempts


def _glitch_s(visit: int, options: SynthOptions) -> float:
    g = options.glitch_after_visit
    return options.glitch_ms / 1000.0 if g is not None and visit > g else 0.0


def _recording_time(slot: int, offset_s: float, period: float, options: SynthOptions) -> float:
    return options.lead_in_s + (slot * period + offset_s) * (1 + options.drift_ppm * 1e-6)


def _active(session: SessionLog, visit: int, options: SynthOptions) -> bool:
    speaker = session.visits[visit].speaker_id
    return visit not in options.drop_visits and speaker not in options.silent_speakers


def ideal_arrivals(session: SessionLog, emissions_ms: dict[str, float],
                   options: SynthOptions) -> list[tuple[float, int]]:
    out: list[tuple[float, int]] = []
    for a in session.attempts:
        if not _active(session, a.visit, options):
            continue
        e = emissions_ms[session.visits[a.visit].speaker_id]
        offset = e / 1000.0 + NEAR_PATH_M / C + _glitch_s(a.visit, options)
        out.extend((_recording_time(s, offset, session.period_s, options), s) for s in a.slots)
    return out


def synth_session(profile: RoomProfile, emissions_ms: dict[str, float],
                  options: SynthOptions = SynthOptions()) -> tuple[SessionLog, np.ndarray]:
    rng = np.random.default_rng(options.seed)
    rate = options.sample_rate
    visits = build_visits(profile)
    attempts = _plan(profile, options)
    log = SessionLog(
        session_id="synth", label="synthetic", created_at="2026-01-01T00:00:00+00:00",
        sample_rate=rate, period_s=profile.period_s,
        signatures_per_visit=profile.signatures_per_visit,
        signature=asdict(SIGNATURE_PARAMS), profile=profile, visits=visits,
        attempts=attempts, completed=True,
    )

    # Distance of every other speaker, drawn once per (visit, speaker).
    dist = {(v.index, s.id): rng.uniform(3.0, 9.0)
            for v in visits for s in profile.speakers if s.id != v.speaker_id}

    copies: list[tuple[float, float]] = []  # (arrival in recording time, gain)
    for a in attempts:
        if a.visit in options.drop_visits:
            continue
        near = visits[a.visit].speaker_id
        glitch = _glitch_s(a.visit, options)
        for slot in a.slots:
            for s in profile.speakers:
                if s.id in options.silent_speakers:
                    continue
                if s.id == near:
                    path, gain = NEAR_PATH_M / C, 1.0
                else:
                    r = dist[(a.visit, s.id)]
                    path, gain = r / C, NEAR_PATH_M / r
                offset = emissions_ms[s.id] / 1000.0 + path + glitch
                copies.append((_recording_time(slot, offset, profile.period_s, options), gain))

    end = max([t + SIGNATURE_PARAMS.duration_s for t, _ in copies]
              + [t + 0.005 for t in options.clap_times_s] + [options.lead_in_s])
    n_total = int(math.ceil((end + 2.0) * rate))
    rec = np.zeros(n_total)
    for t, gain in copies:
        lo = max(0, int(t * rate))
        hi = min(n_total, int((t + SIGNATURE_PARAMS.duration_s) * rate) + 2)
        rec[lo:hi] += gain * signature_waveform(np.arange(lo, hi) / rate - t)

    if options.reverb:
        unit_energy = float(np.sum(signature_waveform(np.arange(int(0.5 * rate)) / rate) ** 2))
        k = np.arange(int(0.6 * rate))
        tail = rng.standard_normal(k.size) * np.exp(-6.9 * (k / rate) / 0.4)
        tail *= math.sqrt(10 ** (-14 / 10) / np.sum(tail**2))
        tail[0] = 0.0  # the direct path is the original recording itself
        rec = rec + fftconvolve(rec, tail)[:n_total]

    rec += rng.standard_normal(n_total) * 10 ** (options.noise_dbfs / 20)
    for t in options.clap_times_s:
        lo = int(t * rate)
        burst = rng.standard_normal(int(0.005 * rate))
        burst *= 0.5 / np.max(np.abs(burst))
        rec[lo:lo + burst.size] += burst[: n_total - lo]
    return log, rec


def write_wav(samples: np.ndarray, sample_rate: int, path: Path) -> Path:
    path = Path(path)
    wavfile.write(path, sample_rate, np.asarray(samples, dtype=np.float32))
    return path


def encode_m4a(samples: np.ndarray, sample_rate: int, path: Path, out_rate: int = 44100) -> Path:
    path = Path(path)
    with tempfile.TemporaryDirectory() as tmp:
        wav = write_wav(samples, sample_rate, Path(tmp) / "in.wav")
        subprocess.run([ffmpeg_path(), "-nostdin", "-y", "-loglevel", "error", "-i", str(wav),
                        "-c:a", "aac", "-b:a", "128k", "-ar", str(out_rate), str(path)],
                       check=True)
    return path


def run_analysis(opts: SynthOptions, profile: RoomProfile | None = None,
                 via_m4a: Path | None = None) -> AnalysisResult:
    """Synthesize a session and analyze it.

    The true emissions always come from ``test_profile()``; ``profile`` is what
    the owner entered. With ``via_m4a`` (a directory), the recording goes
    through AAC at 44.1 kHz first.
    """
    p = profile or test_profile()
    log, rec = synth_session(p, emissions_for(test_profile()), opts)
    if via_m4a:
        rec = load_recording(encode_m4a(rec, 48000, via_m4a / "r.m4a", out_rate=44100))
    return analyze(log, rec)

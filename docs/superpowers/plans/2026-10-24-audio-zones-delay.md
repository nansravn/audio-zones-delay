# Audio Zones Delay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a guided two-zone timing test: a browser player that plays a repeating signature at each speaker on a fixed audio-clock grid, and a Python analysis that turns a phone recording of that session into a per-speaker zone 2 delay report.

**Architecture:** One `uv` Python package, `audio_zones_delay`. It contains a pure-numpy analysis pipeline (detect → assign → fit → answers → checks → report), a stdlib HTTP server that serves the player and stores profiles and sessions under `data/`, and a static player (`player/*.mjs`) that runs in the Windows browser and schedules audio with Web Audio. A shared JSON session log is the contract between player and analysis.

**Tech Stack:** Python ≥3.12 (3.14 pinned), uv with the `uv_build` backend, numpy, scipy, the system `ffmpeg` (8.0.1 installed via apt, with AAC encode and decode), pytest. Browser: vanilla ES modules and Web Audio, no npm dependencies. Node (via nvm) only runs `node --test` on the player's pure logic.

**Spec:** `docs/superpowers/specs/2026-10-24-audio-zones-delay-design.md`

## Global Constraints

- Everything in the repo is English: code, identifiers, comments, UI text, docs, commit messages.
- Every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Runtime deps are exactly `numpy>=2.3` and `scipy>=1.16`. The dev group is `pytest>=8`. Audio decoding shells out to the system `ffmpeg`, found with `shutil.which("ffmpeg")`; it is a documented prerequisite (`sudo apt-get install ffmpeg`), not a Python dependency. The web server is stdlib `http.server`. There is no npm and no `package.json`.
- Test audio never plays through WSL. The player is a page served on `127.0.0.1` from WSL and opened in the Windows browser (Chrome or Edge).
- Signature defaults (`SignatureParams`): **linear** sine sweep from 300 Hz to 12 000 Hz, 0.5 s long, 5 ms raised-cosine fades, peak −6 dBFS. Identical on L and R. Linear rather than exponential: its flat spectrum gives a narrow matched-filter envelope with low sidelobes, which is what timing needs.
- Grid: period P defaults to 2.000 s on the AudioContext clock. Slot k starts at `origin + k·P`, and the origin sits on an integer sample frame.
- Defaults: 5 signatures per visit. The click lead is 0.25 s. The hold tail is 0.3 s after the last signature ends. The closure visit (the first measured speaker revisited at the end) is appended automatically.
- Speed of sound defaults to 343.0 m/s, and device latency to 0.0 ms (both in the profile). Fit thresholds are 30 ms and 80 ms.
- The analysis sample rate is 48 000 Hz. Every recording is decoded and resampled to it.
- `data/` (profiles, sessions, recordings, reports) is gitignored. Recordings are never committed.
- Commands: `uv sync`, `uv run pytest`, `uv run azd serve`, `uv run azd analyze <session-dir> <recording>`. JS tests: `bash -lc 'source ~/.nvm/nvm.sh && node --test tests/js/'`.

## Review Focus

1. **The recording belongs to a different session, or the phone started late or stopped early.** Expect a clear error or a withheld verdict, never a confident number. Tests: Task 5 `test_wrong_session_raises`, Task 8 `test_phone_started_late_withholds_verdict`.
2. **The owner pressed R, so an abandoned attempt's signatures are in the recording.** Only the last attempt per visit may count. Tests: Task 5 `test_redo_uses_last_attempt`, Task 8 `test_redo_and_claps_do_not_change_result`.
3. **Loud noises while walking (claps, doors, voices).** They must be discarded as spurious, not attributed to a speaker. Tests: Task 5 `test_off_grid_noise_is_spurious`, Task 8 `test_redo_and_claps_do_not_change_result`.
4. **A speaker the stereo mode leaves silent.** It is reported as "no signal" and the verdict comes from the rest. If no zone 2 speaker has signal, the verdict is withheld. Tests: Task 6 `test_visit_with_too_few_detections_is_no_signal` and `test_quiet_visit_is_no_signal`, Task 8 `test_silent_center_is_no_signal` and `test_all_zone2_silent_withholds_verdict`.
5. **44.1 kHz on either side (browser AudioContext or phone m4a).** Results must be identical within tolerance. Tests: Task 1 `test_length_at_44100`, Task 8 `test_clean_session_aac_44k`, Task 10 `test_signature_endpoint_44100`.

---

## File Structure

```
pyproject.toml, .python-version            project + pinned Python (Task 1)
src/audio_zones_delay/
  __init__.py
  signature.py      signature definition, single source of truth (Task 1)
  model.py          RoomProfile / SessionLog dataclasses, JSON, validation, visits (Task 2)
  audio_io.py       decode any recording to mono float64 @ 48 kHz via bundled ffmpeg (Task 3)
  detect.py         matched filter, strongest-peak detection, dominance (Task 4)
  assign.py         map detections to grid slots, visits, attempts (Task 5)
  timeline.py       drift + per-speaker emission fit, closure residual (Task 6)
  answers.py        A1/A2, per-speaker and per-channel delays, headline (Task 7)
  checks.py         pass/warn/fail checks, reliability (Task 8)
  analysis.py       analyze(): the whole pipeline (Task 8)
  report.py         HTML report + terminal summary (Task 9)
  cli.py            `azd analyze`, `azd serve` (Tasks 9, 10)
  server.py         stdlib HTTP server: player files + JSON API (Task 10)
  player/core.mjs   pure session logic: visits, grid, state machine, log (Task 11)
  player/app.mjs    DOM, Web Audio, fetch (Task 12)
  player/index.html, player/style.css (Task 12)
tests/
  conftest.py, synth.py (synthetic sessions/recordings), fixtures/session-example.json
  test_*.py per module, js/core.test.mjs
```

---

### Task 1: Project scaffold and the signature

**Files:**
- Create: `pyproject.toml`, `.python-version`, `src/audio_zones_delay/__init__.py`, `src/audio_zones_delay/signature.py`, `tests/conftest.py`, `tests/test_signature.py`
- Modify: `.gitignore`, `CLAUDE.md`

**Interfaces:**
- Produces: `SignatureParams` (frozen dataclass: `f_start_hz: float = 300.0, f_end_hz: float = 12000.0, duration_s: float = 0.5, fade_s: float = 0.005, peak_dbfs: float = -6.0`), `SIGNATURE_PARAMS = SignatureParams()`, `ANALYSIS_RATE = 48000`, `signature_waveform(t_s: np.ndarray, params: SignatureParams = SIGNATURE_PARAMS) -> np.ndarray` (float64, zero outside `[0, duration_s)`), `make_signature(sample_rate: int, params: SignatureParams = SIGNATURE_PARAMS) -> np.ndarray` (float32, `round(duration_s·sample_rate)` samples, equal to `signature_waveform(np.arange(n)/sample_rate)`).

- [ ] **Step 1: Scaffold**

`pyproject.toml`: name `audio-zones-delay`, version `0.1.0`, `requires-python = ">=3.12"`, deps from Global Constraints, `[dependency-groups] dev = ["pytest>=8"]`, `[project.scripts] azd = "audio_zones_delay.cli:main"`, `[build-system] requires = ["uv_build>=0.11,<0.12"], build-backend = "uv_build"`, `[tool.pytest.ini_options] testpaths = ["tests"], pythonpath = ["tests"]`. `.python-version`: `3.14`. Append to `.gitignore`: `data/`, `__pycache__/`, `.venv/`, `.pytest_cache/`. Add a "Commands" table to `CLAUDE.md` with the commands from Global Constraints (the analyze/serve rows can say "available from Task 9/10"). Run `uv sync`. Expected: it resolves and creates `.venv`.

- [ ] **Step 2: Write the failing tests** in `tests/test_signature.py`

```python
import numpy as np
import pytest
from scipy.signal import correlate, hilbert
from audio_zones_delay.signature import make_signature, signature_waveform

def test_length_dtype_and_peak_level():
    s = make_signature(48000)
    assert s.dtype == np.float32
    assert len(s) == 24000
    assert np.max(np.abs(s)) == pytest.approx(10 ** (-6 / 20), abs=1e-3)

def test_length_at_44100():
    assert len(make_signature(44100)) == 22050

def test_starts_and_ends_silent():
    s = make_signature(48000)
    assert abs(s[0]) < 1e-6 and abs(s[-1]) < 1e-3

def test_energy_stays_in_band():
    s = make_signature(48000).astype(np.float64)
    power = np.abs(np.fft.rfft(s)) ** 2
    f = np.fft.rfftfreq(len(s), 1 / 48000)
    assert power[f < 200].sum() / power.sum() < 0.01
    assert power[f > 13000].sum() / power.sum() < 0.01

def test_autocorrelation_envelope_is_sharp():
    s = make_signature(48000).astype(np.float64)
    env = np.abs(hilbert(correlate(s, s, method="fft")))
    above = np.flatnonzero(env > env.max() / 2)
    assert (above.max() - above.min()) / 48000 < 0.25e-3

def test_waveform_matches_sampled_signature():
    t = np.arange(24000) / 48000
    np.testing.assert_allclose(signature_waveform(t), make_signature(48000), atol=1e-6)
    assert signature_waveform(np.array([-0.001, 0.5, 0.7])).tolist() == [0.0, 0.0, 0.0]
```

- [ ] **Step 3: Run them to verify they fail**

Run: `uv run pytest tests/test_signature.py -v`. Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 4: Implement `signature.py`**

Sweep: with `T = duration_s`, use `x(t) = sin(2π·(f_start·t + (f_end − f_start)·t²/(2T)))`. Multiply by raised-cosine fades of `fade_s` at both ends, scale by `10**(peak_dbfs/20)`, and output zero outside `[0, T)`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_signature.py -v`. Expected: 6 passed.

- [ ] **Step 6: Commit**

`git add pyproject.toml .python-version uv.lock .gitignore CLAUDE.md src tests && git commit -m "Add project scaffold and test signature"`

---

### Task 2: Room profile and session log model

**Files:**
- Create: `src/audio_zones_delay/model.py`, `tests/fixtures/session-example.json`, `tests/test_model.py`

**Interfaces:**
- Produces (all in `model.py`):
  - `Speaker(id: str, name: str, zone: int, measured: bool = True, anthem_distance_m: float | None = None, seat_distance_m: float | None = None, delay_channel: str | None = None)`
  - `RoomProfile(speakers: list[Speaker], speed_of_sound_m_s: float = 343.0, device_latency_ms: float = 0.0, signatures_per_visit: int = 5, period_s: float = 2.0, schema: int = 1)` with `speaker(id) -> Speaker`
  - `Visit(index: int, speaker_id: str, closure: bool = False)`, `Attempt(visit: int, attempt: int, slots: list[int])`
  - `SessionLog(session_id: str, label: str, created_at: str, sample_rate: int, period_s: float, signatures_per_visit: int, signature: dict, profile: RoomProfile, visits: list[Visit], attempts: list[Attempt], completed: bool, schema: int = 1)` with `used_attempts() -> dict[int, Attempt]` (last attempt per visit, keyed by visit index)
  - `profile_from_dict(d) -> RoomProfile`, `profile_to_dict(p) -> dict`, `session_from_dict(d) -> SessionLog`, `session_to_dict(s) -> dict`, `load_session(path: Path) -> SessionLog`, `build_visits(profile) -> list[Visit]`, `default_profile() -> RoomProfile`
  - All validation errors raise `ValueError` with a message naming the field.
- JSON shape: exactly `tests/fixtures/session-example.json` below. It is the contract with the player (Task 11 tests read the same file).

- [ ] **Step 1: Write the fixture** `tests/fixtures/session-example.json`

```json
{
  "schema": 1, "session_id": "20261024-211400", "label": "All Channel Stereo, ARC on",
  "created_at": "2026-10-24T21:14:00Z", "sample_rate": 48000, "period_s": 2.0, "signatures_per_visit": 5,
  "signature": {"f_start_hz": 300.0, "f_end_hz": 12000.0, "duration_s": 0.5, "fade_s": 0.005, "peak_dbfs": -6.0},
  "profile": {
    "schema": 1, "speed_of_sound_m_s": 343.0, "device_latency_ms": 0.0, "signatures_per_visit": 5, "period_s": 2.0,
    "speakers": [
      {"id": "front-left", "name": "Front Left", "zone": 1, "measured": true, "anthem_distance_m": 3.6, "seat_distance_m": null, "delay_channel": null},
      {"id": "rear-left", "name": "Rear Left", "zone": 2, "measured": true, "anthem_distance_m": null, "seat_distance_m": 6.0, "delay_channel": "L"}
    ]
  },
  "visits": [
    {"index": 0, "speaker_id": "front-left", "closure": false},
    {"index": 1, "speaker_id": "rear-left", "closure": false},
    {"index": 2, "speaker_id": "front-left", "closure": true}
  ],
  "attempts": [
    {"visit": 0, "attempt": 1, "slots": [3, 4, 5, 6, 7]},
    {"visit": 1, "attempt": 1, "slots": [11, 12, 13, 14, 15]},
    {"visit": 1, "attempt": 2, "slots": [17, 18, 19, 20, 21]},
    {"visit": 2, "attempt": 1, "slots": [25, 26, 27, 28, 29]}
  ],
  "completed": true
}
```

- [ ] **Step 2: Write the failing tests** in `tests/test_model.py`

```python
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
```

Validation rules: ids match `^[a-z0-9]+(-[a-z0-9]+)*$` and are unique. `zone ∈ {1, 2}`. Distances are `None` or `> 0`. `signatures_per_visit ≥ 3`. `period_s ≥ 1.0`. Visit indices are `0..n−1` and their `speaker_id` exists. Every attempt's `visit` exists. `len(slots) == signatures_per_visit`, slots are consecutive within an attempt, and they strictly increase across attempts in list order.

`default_profile()`: zone 1 measured = Front Left, Center, Front Right, Surround Left, Surround Right, Surround Back Left, Surround Back Right, Top Front Left, Top Front Right, Top Rear Left, Top Rear Right. Unmeasured = Subwoofer 1, Subwoofer 2. Zone 2 = Zone 2 Speaker 1–4. Ids are the slugged names. Distances and channels are `None`.

- [ ] **Step 3: Run them to verify they fail.** Run: `uv run pytest tests/test_model.py -v`. Expected: FAIL (import error).
- [ ] **Step 4: Implement `model.py`** with plain dataclasses and hand-written `*_from_dict` / `*_to_dict` (no extra deps).
- [ ] **Step 5: Run them to verify they pass.** Run: `uv run pytest tests/test_model.py -v`. Expected: all pass.
- [ ] **Step 6: Commit** `git commit -m "Add room profile and session log model"`

---

### Task 3: Recording I/O and synthetic sessions

**Files:**
- Create: `src/audio_zones_delay/audio_io.py`, `tests/synth.py`, `tests/test_audio_io.py`, `tests/test_synth.py`

**Interfaces:**
- Consumes: `signature_waveform`, `SIGNATURE_PARAMS`, `ANALYSIS_RATE` (Task 1); model types, `build_visits` (Task 2).
- Produces:
  - `audio_io.RecordingError(Exception)`, `audio_io.ffmpeg_path() -> str` (`shutil.which("ffmpeg")`, or raises `RecordingError("ffmpeg not found: install it with sudo apt-get install ffmpeg")`), `audio_io.load_recording(path: Path, sample_rate: int = ANALYSIS_RATE) -> np.ndarray`: mono float64, decoded with `ffmpeg -nostdin -i <path> -vn -ac 1 -ar <rate> -f f32le pipe:1`. Raises `RecordingError` when ffmpeg is missing, the file is missing, ffmpeg fails, or the output is empty.
  - `tests/synth.py`: `SynthOptions` (fields below), `test_profile() -> RoomProfile`, `emissions_for(profile, processing_ms: float = 41.3, zone2_ms: float = 0.0) -> dict[str, float]`, `synth_session(profile, emissions_ms, options=SynthOptions()) -> tuple[SessionLog, np.ndarray]` (the recording is at 48 kHz), `ideal_arrivals(session, emissions_ms, options) -> list[tuple[float, int]]` (recording time in seconds and slot of the near speaker's arrival for every played signature of every attempt, noise-free: `lead_in_s + (slot·P + e_v/1000 + 0.2/343 + glitch)·(1 + drift_ppm·1e-6)`. Visits in `drop_visits` and visits to `silent_speakers` are excluded.), `encode_m4a(samples, sample_rate, path, out_rate=44100) -> Path`, `write_wav(samples, sample_rate, path) -> Path`.

`test_profile()`: zone 1 has `front-left` (Anthem 3.6 m), `center` (3.4 m) and `surround-back-left` (4.2 m). Zone 2 has `rear-left` (seat 6.0 m, channel `"L"`) and `rear-right` (seat 6.3 m, channel `"R"`). With 343 m/s, `emissions_for` returns zone 1 `e_i = processing_ms + (D_max − D_i)/c·1000` (D_max over zone 1 entries) and zone 2 `e_j = zone2_ms`. Truth for later tasks: `rear-left` delay 36.052187 ms, `rear-right` 35.177551 ms, headline 41.3 ms.

`SynthOptions` fields and defaults: `drift_ppm=0.0, lead_in_s=3.0, walk_s=4.0, noise_dbfs=-60.0, reverb=True, redo_visits=frozenset(), silent_speakers=frozenset(), glitch_after_visit=None, glitch_ms=0.0, clap_times_s=(), drop_visits=frozenset(), sample_rate=48000, seed=0`.

Synthesis model (decided here; later e2e tolerances depend on it):
- **PC timeline:** slot k at `k·P` s. The cursor starts at 1.0 s. For each visit in `build_visits(profile)`, `click = cursor + walk_s` and `first = max(last+1, ceil((click + 0.25)/P))`, with N consecutive slots. Then `cursor = (first+N−1)·P + 0.5 + 0.3`. Visits in `redo_visits` get a second attempt with `walk_s = 1.0` after the first. Attempts are logged as the player would log them (`session_id="synth"`, `completed=True`).
- **Each played signature at slot time s while visiting speaker v:** add one copy per speaker k that is not silent, at PC time `s + e_k/1000 + path_k`, using `signature_waveform` for fractional placement. For v: `path = 0.2/343`, gain 1.0. For the others: distance `r_k` drawn once per (visit, k) from U(3, 9) m with the seeded RNG, `path = r_k/343`, gain `0.2/r_k`. After `glitch_after_visit`, add `glitch_ms/1000` to every PC time.
- **Recording time** = `lead_in_s + pc_time·(1 + drift_ppm·1e-6)`. Visits in `drop_visits` contribute nothing (phone not recording). Total length = last event + 2 s.
- **Reverb** (if on): convolve the whole recording once with seeded white noise × `exp(−6.9·t/0.4)` over 0.6 s, scaled so its energy is −14 dB relative to a unit-gain signature. Then add white noise at `noise_dbfs`, plus 5 ms broadband bursts at `clap_times_s` with peak 0.5.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_audio_io.py
def test_wav_44100_is_resampled_to_48000(tmp_path):
    tone = 0.5 * np.sin(2 * np.pi * 1000 * np.arange(44100 * 2) / 44100)
    x = load_recording(write_wav(tone, 44100, tmp_path / "a.wav"))
    assert x.dtype == np.float64 and x.ndim == 1
    assert abs(len(x) - 96000) <= 96000 * 0.01

def test_stereo_is_downmixed(tmp_path):
    st = np.stack([np.ones(4800) * 0.25, np.ones(4800) * 0.25], axis=1)
    assert load_recording(write_wav(st, 48000, tmp_path / "s.wav")).ndim == 1

def test_m4a_round_trip(tmp_path):
    tone = 0.5 * np.sin(2 * np.pi * 1000 * np.arange(48000) / 48000)
    x = load_recording(encode_m4a(tone, 48000, tmp_path / "t.m4a"))
    assert abs(len(x) - 48000) <= 48000 * 0.05

def test_missing_ffmpeg_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(RecordingError, match="apt-get install ffmpeg"):
        load_recording(write_wav(np.zeros(4800), 48000, tmp_path / "z.wav"))

@pytest.mark.parametrize("name, content", [("missing.wav", None), ("bad.m4a", b"not audio")])
def test_bad_input_raises(tmp_path, name, content):
    p = tmp_path / name
    if content is not None: p.write_bytes(content)
    with pytest.raises(RecordingError):
        load_recording(p)

# tests/test_synth.py
def test_synth_logs_one_attempt_per_visit_plus_redo():
    log, rec = synth_session(test_profile(), emissions_for(test_profile()), SynthOptions(redo_visits=frozenset({1})))
    assert [v.speaker_id for v in log.visits] == ["front-left", "center", "surround-back-left", "rear-left", "rear-right", "front-left"]
    assert [a.visit for a in log.attempts] == [0, 1, 1, 2, 3, 4, 5]
    assert rec.ndim == 1 and np.max(np.abs(rec)) < 1.0

def test_ideal_arrivals_follow_drift():
    opts = SynthOptions(drift_ppm=100.0)
    log, _ = synth_session(test_profile(), emissions_for(test_profile()), opts)
    t, slot = ideal_arrivals(log, emissions_for(test_profile()), opts)[-1]
    assert t == pytest.approx(3.0 + (slot * 2.0 + 43.049271e-3 + 0.2 / 343) * (1 + 100e-6), abs=1e-9)
```

- [ ] **Step 2: Run them to verify they fail.** `uv run pytest tests/test_audio_io.py tests/test_synth.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `audio_io.py` and `tests/synth.py`** following the model above. `write_wav` uses `scipy.io.wavfile.write` with float32. `encode_m4a` writes a temporary wav, then runs `ffmpeg_path()` with `-c:a aac -b:a 128k -ar <out_rate>`.
- [ ] **Step 4: Run them to verify they pass.** Same command. Expected: all pass.
- [ ] **Step 5: Commit** `git commit -m "Add recording loader and synthetic session generator"`

---

### Task 4: Signature detection

**Files:**
- Create: `src/audio_zones_delay/detect.py`, `tests/test_detect.py`

**Interfaces:**
- Consumes: `make_signature`, `signature_waveform` (Task 1).
- Produces: `Detection(time_s: float, strength: float, dominance: float)` (frozen dataclass), `matched_envelope(recording: np.ndarray, template: np.ndarray) -> np.ndarray`, `detect_signatures(recording, sample_rate: int, template: np.ndarray, period_s: float, snr: float = 10.0) -> list[Detection]` (sorted by time).

Algorithm:
- `matched_envelope`: zero-pad the recording at the end by `len(template)`, then `scipy.signal.correlate(rec, template, mode="valid", method="fft")` and `np.abs(hilbert(...))`. Index i means "the template starts at sample i".
- Noise floor = `median(env)`. Peaks = `find_peaks(env, height=snr·floor, distance=int(0.5·period_s·sample_rate))`, which keeps the strongest peak per half-period.
- Sub-sample time comes from parabolic interpolation on `env[p−1..p+1]`. `strength = env[p]/floor`.
- `dominance = env[p] / max(local maxima of env within ±60 ms of p, excluding ±1 ms)`. Use 1000.0 when there are none.

- [ ] **Step 1: Write the failing tests**

```python
def place(rec, t, gain=1.0, sr=48000):
    n0 = int(np.floor(t * sr)); n = np.arange(n0, n0 + 24002)
    rec[n0:n0 + 24002] += gain * signature_waveform(n / sr - t)

def noisy(seconds, seed=0):
    return np.random.default_rng(seed).normal(0, 10 ** (-60 / 20), int(seconds * 48000))

def test_detects_fractional_positions():
    rec = noisy(8)
    for t in (1.0, 3.0001234, 5.5): place(rec, t)
    d = detect_signatures(rec, 48000, make_signature(48000), 2.0)
    assert [x.time_s for x in d] == pytest.approx([1.0, 3.0001234, 5.5], abs=1e-5)

def test_strongest_arrival_wins_and_reports_dominance():
    rec = noisy(4); place(rec, 2.0); place(rec, 1.98, gain=0.05)
    d = detect_signatures(rec, 48000, make_signature(48000), 2.0)
    assert len(d) == 1 and d[0].time_s == pytest.approx(2.0, abs=1e-5)
    assert d[0].dominance > 10

def test_noise_only_has_no_detections():
    assert detect_signatures(noisy(6), 48000, make_signature(48000), 2.0) == []

def test_signature_at_end_is_detected():
    rec = noisy(3); place(rec, 3.0 - 0.5 - 0.001 - 2 / 48000)
    assert len(detect_signatures(rec, 48000, make_signature(48000), 2.0)) == 1
```

- [ ] **Step 2: Run them to verify they fail.** `uv run pytest tests/test_detect.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `detect.py`.**
- [ ] **Step 4: Run them to verify they pass.** Expected: 4 passed.
- [ ] **Step 5: Commit** `git commit -m "Add matched-filter signature detection"`

---

### Task 5: Assign detections to slots, visits and attempts

**Files:**
- Create: `src/audio_zones_delay/assign.py`, `tests/test_assign.py`

**Interfaces:**
- Consumes: `Detection` (Task 4), `SessionLog` (Task 2), `ideal_arrivals`, `synth_session`, `SynthOptions`, `test_profile`, `emissions_for` (Task 3, tests only).
- Produces: `AlignmentError(Exception)`, `Assigned(detection: Detection, slot: int, visit: int, attempt: int)`, `Assignment(assigned: list[Assigned], spurious: list[Detection], missing_slots: list[int], match_ratio: float)`, `assign_detections(detections: list[Detection], session: SessionLog) -> Assignment`.

Algorithm (P = `session.period_s`):
1. **Phase:** φ = circular mean of `t mod P`. Refine once using only the detections within 0.25·P (circular) of φ.
2. **Grid index:** `n = round((t − φ)/P)`. A detection with `|t − φ − n·P| > 0.25·P` is spurious.
3. **Shift:** S = every logged slot from all attempts. For each candidate shift `k ∈ {s − n}`, score = number of distinct slots `n + k ∈ S`. Pick the best k. If the runner-up ties it, raise `AlignmentError("ambiguous alignment")`.
4. **Collisions:** when two detections land on the same slot, keep the stronger one. The other is spurious.
5. **Missing slots:** slots of `session.used_attempts()` with no detection.
6. **Match ratio:** `match_ratio = matched / len(detections)`. If `< 0.8` or `matched < 3`, raise `AlignmentError("recording does not match this session")`.

- [ ] **Step 1: Write the failing tests** (build `Detection`s from `ideal_arrivals` plus Gaussian jitter of σ = 0.02 ms, with `strength=50, dominance=20`)

```python
def dets(log, opts, extra_times=()):
    arr = ideal_arrivals(log, emissions_for(test_profile()), opts)
    rng = np.random.default_rng(1)
    ds = [Detection(t + rng.normal(0, 2e-5), 50.0, 20.0) for t, _ in arr]
    return sorted(ds + [Detection(t, 12.0, 1.5) for t in extra_times], key=lambda d: d.time_s)

def test_clean_session_assigns_every_detection():
    opts = SynthOptions(lead_in_s=7.3, drift_ppm=80.0)
    log, _ = synth_session(test_profile(), emissions_for(test_profile()), opts)
    a = assign_detections(dets(log, opts), log)
    assert a.match_ratio == 1.0 and a.spurious == [] and a.missing_slots == []
    assert [x.slot for x in a.assigned] == [s for at in log.attempts for s in at.slots]

def test_redo_uses_last_attempt():
    opts = SynthOptions(redo_visits=frozenset({3}))
    log, _ = synth_session(test_profile(), emissions_for(test_profile()), opts)
    a = assign_detections(dets(log, opts), log)
    assert {x.attempt for x in a.assigned if x.visit == 3} == {1, 2}
    assert log.used_attempts()[3].attempt == 2 and a.missing_slots == []

def test_off_grid_noise_is_spurious():
    opts = SynthOptions()
    log, _ = synth_session(test_profile(), emissions_for(test_profile()), opts)
    a = assign_detections(dets(log, opts, extra_times=(6.1, 21.9)), log)
    assert len(a.spurious) == 2 and a.match_ratio == pytest.approx(30 / 32)

def test_cropped_recording_reports_missing_closure():
    opts = SynthOptions()
    log, _ = synth_session(test_profile(), emissions_for(test_profile()), opts)
    a = assign_detections(dets(log, opts)[:-5], log)   # phone stopped before the closure visit
    assert a.missing_slots == log.attempts[-1].slots

def test_wrong_session_raises():
    log_a, _ = synth_session(test_profile(), emissions_for(test_profile()), SynthOptions(walk_s=4.0))
    log_b, _ = synth_session(test_profile(), emissions_for(test_profile()), SynthOptions(walk_s=7.0))
    with pytest.raises(AlignmentError):
        assign_detections(dets(log_a, SynthOptions(walk_s=4.0)), log_b)
```

- [ ] **Step 2: Run them to verify they fail.** `uv run pytest tests/test_assign.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `assign.py`.**
- [ ] **Step 4: Run them to verify they pass.** Expected: 5 passed.
- [ ] **Step 5: Commit** `git commit -m "Assign detections to grid slots and visits"`

---

### Task 6: Timeline fit (drift, emissions, closure)

**Files:**
- Create: `src/audio_zones_delay/timeline.py`, `tests/test_timeline.py`

**Interfaces:**
- Consumes: `Assignment`, `Assigned` (Task 5), `SessionLog` (Task 2).
- Produces: `VisitStats(visit: int, speaker_id: str, n: int, mean_residual_ms: float, spread_ms: float, dominance: float)`, `Timeline(emission_ms: dict[str, float], emission_se_ms: dict[str, float], drift_ppm: float, closure_residual_ms: float | None, visits: list[VisitStats], no_signal: list[str])`, `fit_timeline(assignment: Assignment, session: SessionLog, min_detections: int = 3, min_relative_level: float = 0.1) -> Timeline`.

Algorithm. Use only detections from `used_attempts()`. Slot time is `s = slot·P`.

A visit is dropped in two cases:
- it has fewer than `min_detections`;
- its median `strength` is below `min_relative_level` × the median of all visits' median strengths (−20 dB).

The second rule matters when the owner stands at a speaker the mode leaves silent. The phone then still picks up *other* speakers 3 m or more away, about 20 dB quieter than a near-field capture. Those arrivals must not be attributed to the silent speaker. If none of a speaker's visits survive, the speaker goes in `no_signal`.
1. **Stage 1 (closure check):** least squares for `t = b·s + c_v` with one intercept per visit and a common slope b. `closure_residual_ms = (c_closure − c_first)·1000`, or `None` if either visit was dropped.
2. **Stage 2 (final):** if the closure is available, fit `t = b·s + c_k` with one intercept per speaker, so the closure visit shares the first speaker's intercept. Otherwise keep stage 1, using the first visit for each speaker.
3. **Outputs:** `drift_ppm = (b − 1)·1e6`. `emission_ms[k] = (c_k − min c)/b·1000`. `emission_se_ms` comes from the stage-2 covariance (`σ²·(XᵀX)⁻¹`). `VisitStats` uses the stage-2 residuals: the visit's mean residual, its sample standard deviation (`spread_ms`) and the median `dominance` of its detections.

- [ ] **Step 1: Write the failing tests** (helper `assignment_from(log, opts, jitter_s=2e-5, keep=None, strength=lambda a: 50.0)`. It builds an `Assignment` from `ideal_arrivals`: Gaussian jitter, `dominance=20`, `strength=strength(assigned)`, visit and attempt looked up from the log by slot. `keep` filters `Assigned` items.)

```python
def test_recovers_drift_and_emissions():
    opts = SynthOptions(drift_ppm=40.0)
    log, _ = synth_session(test_profile(), emissions_for(test_profile()), opts)
    tl = fit_timeline(assignment_from(log, opts), log)
    assert tl.drift_ppm == pytest.approx(40.0, abs=0.5)
    truth = emissions_for(test_profile())
    for k in truth:
        assert tl.emission_ms[k] - tl.emission_ms["rear-left"] == pytest.approx(truth[k] - truth["rear-left"], abs=0.03)
    assert abs(tl.closure_residual_ms) < 0.1
    assert max(tl.emission_se_ms.values()) < 0.05

def test_playback_glitch_shows_in_closure():
    opts = SynthOptions(glitch_after_visit=2, glitch_ms=1.5)
    log, _ = synth_session(test_profile(), emissions_for(test_profile()), opts)
    tl = fit_timeline(assignment_from(log, opts), log)
    assert tl.closure_residual_ms == pytest.approx(1.5, abs=0.2)

def test_visit_with_too_few_detections_is_no_signal():
    opts = SynthOptions()
    log, _ = synth_session(test_profile(), emissions_for(test_profile()), opts)
    tl = fit_timeline(assignment_from(log, opts, keep=lambda a: not (a.visit == 1 and a.slot > log.attempts[1].slots[1])), log)
    assert tl.no_signal == ["center"] and "center" not in tl.emission_ms

def test_quiet_visit_is_no_signal():
    opts = SynthOptions()
    log, _ = synth_session(test_profile(), emissions_for(test_profile()), opts)
    tl = fit_timeline(assignment_from(log, opts, strength=lambda a: 2.0 if a.visit == 1 else 50.0), log)
    assert tl.no_signal == ["center"] and "center" not in tl.emission_ms

def test_missing_closure_gives_none():
    opts = SynthOptions()
    log, _ = synth_session(test_profile(), emissions_for(test_profile()), opts)
    tl = fit_timeline(assignment_from(log, opts, keep=lambda a: a.visit != 5), log)
    assert tl.closure_residual_ms is None
```

- [ ] **Step 2: Run them to verify they fail.** `uv run pytest tests/test_timeline.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `timeline.py`** with `numpy.linalg.lstsq` on explicit design matrices.
- [ ] **Step 4: Run them to verify they pass.** Expected: 5 passed.
- [ ] **Step 5: Commit** `git commit -m "Fit drift and per-speaker emission times"`

---

### Task 7: Answers (delays, channels, headline)

**Files:**
- Create: `src/audio_zones_delay/answers.py`, `tests/test_answers.py`

**Interfaces:**
- Consumes: `Timeline` (Task 6), `RoomProfile` (Task 2).
- Produces: `ChannelDelay(channel: str, speaker_ids: list[str], delay_ms: float, dial_ms: float, residual_ms: dict[str, float], fits_30: bool, fits_80: bool)` and `Answers(mode: str, headline_ms: float | None, raw_gap_ms: float | None, a1_ms: dict[str, float], a2_ms: dict[str, float], speaker_delay_ms: dict[str, float], channels: list[ChannelDelay], uncertainty_ms: float, a1_spread_ms: float | None)`. `mode` is `"full"` or `"raw"`. Also `compute_answers(timeline: Timeline, profile: RoomProfile) -> Answers`.

Formulas (spec 6.6). c = `profile.speed_of_sound_m_s`. Distances are converted to ms as `m/c·1000`. Only speakers in `timeline.emission_ms` count.
- **Mode:** `"full"` when every counted zone 1 speaker has `anthem_distance_m` and every counted zone 2 speaker has `seat_distance_m`. Otherwise `"raw"`.
- **Full mode:** `a1_ms[i] = e_i + D_i`, `a2_ms[j] = e_j + d_j`, and `speaker_delay_ms[j] = mean(a1) − a2[j]`. Group by `delay_channel or speaker id`: channel `delay_ms = mean(speaker delays)`, `residual_ms[j] = delay_j − channel delay`, and `dial_ms = delay_ms − device_latency_ms`. `fits_30 = 0 ≤ dial ≤ 30`, `fits_80 = 0 ≤ dial ≤ 80`. `headline_ms = mean_i(e_i − (D_max − D_i)) − mean_j(e_j)`, where `D_max` is the largest `anthem_distance_m` among **all** zone 1 speakers in the profile, measured or not. `a1_spread_ms = max(a1) − min(a1)`.
- **Raw mode:** `raw_gap_ms = min(e zone 1) − mean(e zone 2)`. Channels are empty, and `headline_ms` and `a1_spread_ms` are `None`.
- **Uncertainty:** `se_delay_j = sqrt(se(mean a1)² + se_j²)` with `se(mean a1) = sqrt(Σ se_i²)/n`. `uncertainty_ms = max(2·max_j se_delay_j, |closure_residual_ms or 0|, (a1_spread_ms or 0)/2)`.

- [ ] **Step 1: Write the failing tests** (`timeline_with(emissions, se=0.01, closure=0.0)` builds a `Timeline` directly)

```python
def test_full_mode_matches_spec_example():
    ans = compute_answers(timeline_with(emissions_for(test_profile())), test_profile())
    assert ans.mode == "full"
    assert ans.speaker_delay_ms["rear-left"] == pytest.approx(36.052187, abs=1e-5)
    assert ans.speaker_delay_ms["rear-right"] == pytest.approx(35.177551, abs=1e-5)
    assert ans.headline_ms == pytest.approx(41.3, abs=1e-6)
    assert ans.a1_spread_ms == pytest.approx(0.0, abs=1e-9)
    left = next(c for c in ans.channels if c.channel == "L")
    assert (left.fits_30, left.fits_80) == (False, True)

def test_shared_channel_gets_compromise_and_residuals():
    p = test_profile(); p.speaker("rear-right").delay_channel = "L"
    (ch,) = compute_answers(timeline_with(emissions_for(p)), p).channels
    assert ch.delay_ms == pytest.approx(35.614869, abs=1e-5)
    assert ch.residual_ms == pytest.approx({"rear-left": 0.437318, "rear-right": -0.437318}, abs=1e-5)

def test_device_latency_is_subtracted():
    p = test_profile(); p.device_latency_ms = 2.0
    left = next(c for c in compute_answers(timeline_with(emissions_for(p)), p).channels if c.channel == "L")
    assert left.dial_ms == pytest.approx(34.052187, abs=1e-5)

def test_zone2_late_gives_negative_delay_that_fits_nothing():
    ans = compute_answers(timeline_with(emissions_for(test_profile(), zone2_ms=60.0)), test_profile())
    assert all(c.delay_ms < 0 and not c.fits_30 and not c.fits_80 for c in ans.channels)
    assert ans.headline_ms == pytest.approx(41.3 - 60.0, abs=1e-6)

def test_unmeasured_sub_moves_headline_but_not_delays():
    p = test_profile(); p.speakers.append(Speaker("subwoofer-1", "Sub 1", 1, measured=False, anthem_distance_m=4.5))
    ans = compute_answers(timeline_with(emissions_for(test_profile())), p)
    assert ans.headline_ms == pytest.approx(40.425364, abs=1e-5)
    assert ans.speaker_delay_ms["rear-left"] == pytest.approx(36.052187, abs=1e-5)

def test_missing_distances_fall_back_to_raw():
    p = test_profile(); p.speaker("rear-left").seat_distance_m = None
    ans = compute_answers(timeline_with(emissions_for(test_profile())), p)
    assert ans.mode == "raw" and ans.channels == [] and ans.raw_gap_ms == pytest.approx(41.3, abs=1e-6)

def test_uncertainty_takes_the_largest_source():
    assert compute_answers(timeline_with(emissions_for(test_profile()), closure=0.7), test_profile()).uncertainty_ms == pytest.approx(0.7)
```

- [ ] **Step 2: Run them to verify they fail.** `uv run pytest tests/test_answers.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `answers.py`.**
- [ ] **Step 4: Run them to verify they pass.** Expected: 7 passed.
- [ ] **Step 5: Commit** `git commit -m "Compute zone 2 delays, channels and headline"`

---

### Task 8: Checks and the analysis pipeline

**Files:**
- Create: `src/audio_zones_delay/checks.py`, `src/audio_zones_delay/analysis.py`, `tests/test_analysis.py`
- Modify: `tests/synth.py` (add `run_analysis`)

**Interfaces:**
- Consumes: everything from Tasks 1–7.
- Produces: `Check(key: str, status: str, message: str)` (status is `"pass"`, `"warn"` or `"fail"`), `run_checks(assignment, timeline, answers, session) -> list[Check]`, `AnalysisResult(session: SessionLog, assignment: Assignment, timeline: Timeline, answers: Answers, checks: list[Check], reliable: bool)`, `analyze(session: SessionLog, recording: np.ndarray, sample_rate: int = ANALYSIS_RATE) -> AnalysisResult`. `analyze` builds the template from `SignatureParams(**session.signature)` at `sample_rate`. It lets `AlignmentError` propagate. `reliable` = no check has `"fail"`.

Checks, in this order:

| key | pass | warn | fail |
|---|---|---|---|
| `drift` | \|ppm\| ≤ 200 | — | otherwise |
| `closure` | \|r\| ≤ 0.5 ms | ≤ 1.0 ms | > 1.0 ms, or `None` ("closure visit not captured: record the whole session") |
| `repeat_spread` | worst visit ≤ 0.2 ms | ≤ 0.5 ms | > 0.5 ms |
| `zone1_consistency` | `a1_spread` ≤ 1.0 ms | ≤ 2.0 ms, or raw mode ("enter distances for per-speaker delays") | > 2.0 ms ("check the Anthem distances entered") |
| `coverage` | nothing missing; zone 1 `no_signal` speakers listed as info | missing signatures, or any zone 2 speaker with no signal | no zone 1 or no zone 2 speaker has signal |
| `dominance` | worst visit median ≥ 2.0 | ≥ 1.4 | < 1.4 ("hold the phone closer to <speaker>") |

- [ ] **Step 1: Write the failing end-to-end tests.** Add `run_analysis` to `tests/synth.py` (Task 9 reuses it). The true emissions always come from `test_profile()`, and `profile` is what the owner "entered".

```python
# tests/synth.py
def run_analysis(opts, profile=None, via_m4a=None):
    p = profile or test_profile()
    log, rec = synth_session(p, emissions_for(test_profile()), opts)
    if via_m4a: rec = load_recording(encode_m4a(rec, 48000, via_m4a / "r.m4a", out_rate=44100))
    return analyze(log, rec)

# tests/test_analysis.py
from synth import run_analysis as run
def delays(r): return {c.channel: c.delay_ms for c in r.answers.channels}

def test_clean_session_aac_44k(tmp_path):
    r = run(SynthOptions(drift_ppm=40.0), via_m4a=tmp_path)
    assert r.reliable
    assert delays(r) == pytest.approx({"L": 36.052187, "R": 35.177551}, abs=0.3)
    assert r.answers.headline_ms == pytest.approx(41.3, abs=0.3)
    assert r.timeline.drift_ppm == pytest.approx(40.0, abs=2.0)

def test_redo_and_claps_do_not_change_result():
    r = run(SynthOptions(redo_visits=frozenset({3}), clap_times_s=(6.0, 30.0, 52.0)))
    assert r.reliable and delays(r) == pytest.approx({"L": 36.052187, "R": 35.177551}, abs=0.3)

def test_silent_center_is_no_signal():
    r = run(SynthOptions(silent_speakers=frozenset({"center"})))
    assert r.reliable and r.timeline.no_signal == ["center"]
    assert delays(r) == pytest.approx({"L": 36.052187, "R": 35.177551}, abs=0.3)

def test_playback_glitch_withholds_verdict():
    r = run(SynthOptions(glitch_after_visit=2, glitch_ms=1.5))
    assert not r.reliable and next(c for c in r.checks if c.key == "closure").status == "fail"

def test_phone_started_late_withholds_verdict():
    r = run(SynthOptions(drop_visits=frozenset({0})))
    assert not r.reliable and next(c for c in r.checks if c.key == "closure").status == "fail"

def test_all_zone2_silent_withholds_verdict():
    r = run(SynthOptions(silent_speakers=frozenset({"rear-left", "rear-right"})))
    assert not r.reliable and next(c for c in r.checks if c.key == "coverage").status == "fail"

def test_wrong_anthem_distance_fails_consistency():
    p = test_profile(); p.speaker("center").anthem_distance_m = 2.0   # real setting is 3.4 m
    r = run(SynthOptions(), profile=p)
    assert not r.reliable and next(c for c in r.checks if c.key == "zone1_consistency").status == "fail"

def test_wrong_session_raises():
    log_b, _ = synth_session(test_profile(), emissions_for(test_profile()), SynthOptions(walk_s=7.0))
    _, rec_a = synth_session(test_profile(), emissions_for(test_profile()), SynthOptions())
    with pytest.raises(AlignmentError):
        analyze(log_b, rec_a)
```

The silent-speaker tests depend on Task 6's relative-level rule. A visit to a silent speaker still picks up the other speakers about 23 dB down, and that rule is what keeps them from being attributed to it.

- [ ] **Step 2: Run them to verify they fail.** `uv run pytest tests/test_analysis.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `checks.py` and `analysis.py`** (pipeline: `detect_signatures` → `assign_detections` → `fit_timeline` → `compute_answers` → `run_checks`).
- [ ] **Step 4: Run the full suite.** `uv run pytest -v`. Expected: all pass. If an e2e tolerance fails, fix the algorithm, not the tolerance.
- [ ] **Step 5: Commit** `git commit -m "Add consistency checks and end-to-end analysis"`

---

### Task 9: Report and `azd analyze`

**Files:**
- Create: `src/audio_zones_delay/report.py`, `src/audio_zones_delay/cli.py`, `tests/test_report.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `AnalysisResult`, `analyze` (Task 8), `load_session` (Task 2), `load_recording`, `RecordingError` (Task 3), `AlignmentError` (Task 5).
- Produces: `render_html(result: AnalysisResult) -> str`, `render_summary(result: AnalysisResult, report_path: Path | None = None) -> str`, `cli.main(argv: list[str] | None = None) -> int`. Subcommand: `analyze SESSION_DIR RECORDING [--device-latency-ms X]`. The option overrides the profile copy inside the session before computing. It reads `SESSION_DIR/session.json`, writes `SESSION_DIR/report.html` and prints the summary. Exit codes: 0 = reliable, 2 = verdict withheld, 1 = error (message on stderr, no traceback).

Verdict copy (all numbers to 1 decimal):
- Reliable, full mode, headline > 0: `Zone 2 plays {h:.1f} ms earlier than zone 1 (±{u:.1f} ms)`. When headline < 0: `Zone 2 plays {|h|:.1f} ms later than zone 1 (±{u:.1f} ms)`. Add a line per channel with `delay_ms < 0`: `A delay device on zone 2 cannot fix channel {ch}: zone 2 is already late there.` Add a line per channel with `dial_ms < 0 ≤ delay_ms`: `The delay device's own latency already over-delays channel {ch}.`
- Reliable, raw mode: `Zone 2 fires at least {g:.1f} ms before zone 1 (raw estimate: enter Anthem and seat distances for per-speaker delays)`. Use the "after" wording when the gap is negative.
- Not reliable: `Verdict withheld`, followed by the message of each failed check. The verdict sentence must not appear.

HTML (one self-contained file with inline CSS and an inline SVG, light and dark via `prefers-color-scheme`) follows spec 6.8: verdict, the per-channel table (channel, speakers, delay, dial, 30 ms ✔/✘, 80 ms ✔/✘, leftover misalignment), the timeline SVG (emission per speaker, colored by zone), per-speaker detail, and the checks. Every owner-entered string goes through `html.escape`.

- [ ] **Step 1: Write the failing tests**

Measured values carry ±0.3 ms of noise, so tests build expected strings from the result itself rather than from hard-coded decimals.

```python
# tests/test_report.py (uses run_analysis from tests/synth.py)
def test_reliable_report_has_verdict_and_table():
    r = run_analysis(SynthOptions())
    html, text = render_html(r), render_summary(r)
    verdict = f"Zone 2 plays {r.answers.headline_ms:.1f} ms earlier than zone 1"
    left = next(c for c in r.answers.channels if c.channel == "L")
    assert verdict in text and f"{left.dial_ms:.1f} ms" in text
    assert verdict in html and "<svg" in html

def test_withheld_report_hides_verdict():
    r = run_analysis(SynthOptions(glitch_after_visit=2, glitch_ms=1.5))
    assert "Verdict withheld" in render_summary(r) and "earlier than zone 1" not in render_html(r)

def test_names_are_escaped():
    p = test_profile(); p.speaker("rear-left").name = "<b>Rear</b>"
    assert "<b>Rear</b>" not in render_html(run_analysis(SynthOptions(), profile=p))

# tests/test_cli.py
def make_session_dir(tmp_path, opts=SynthOptions()):
    log, rec = synth_session(test_profile(), emissions_for(test_profile()), opts)
    d = tmp_path / "s"; d.mkdir(); (d / "session.json").write_text(json.dumps(session_to_dict(log)))
    return d, encode_m4a(rec, 48000, tmp_path / "rec.m4a")

def test_analyze_writes_report_and_exits_0(tmp_path, capsys):
    d, rec = make_session_dir(tmp_path)
    assert main(["analyze", str(d), str(rec)]) == 0
    assert (d / "report.html").exists() and "earlier than zone 1" in capsys.readouterr().out

def test_device_latency_override(tmp_path, capsys):
    d, rec = make_session_dir(tmp_path)
    main(["analyze", str(d), str(rec), "--device-latency-ms", "2"])
    session = load_session(d / "session.json"); session.profile.device_latency_ms = 2.0
    left = next(c for c in analyze(session, load_recording(rec)).answers.channels if c.channel == "L")
    assert left.dial_ms == pytest.approx(34.052187, abs=0.3)
    assert f"{left.dial_ms:.1f} ms" in capsys.readouterr().out

def test_withheld_exits_2(tmp_path):
    d, rec = make_session_dir(tmp_path, SynthOptions(glitch_after_visit=2, glitch_ms=1.5))
    assert main(["analyze", str(d), str(rec)]) == 2

def test_missing_recording_exits_1(tmp_path, capsys):
    d, _ = make_session_dir(tmp_path)
    assert main(["analyze", str(d), str(tmp_path / "nope.m4a")]) == 1
    assert "nope.m4a" in capsys.readouterr().err
```

- [ ] **Step 2: Run them to verify they fail.** `uv run pytest tests/test_report.py tests/test_cli.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `report.py` and `cli.py`** (argparse with subparsers; `serve` arrives in Task 10).
- [ ] **Step 4: Run them to verify they pass.** Expected: all pass.
- [ ] **Step 5: Commit** `git commit -m "Add HTML report and azd analyze command"`

---

### Task 10: Local server and `azd serve`

**Files:**
- Create: `src/audio_zones_delay/server.py`, `src/audio_zones_delay/player/index.html` (placeholder `<!doctype html><title>Audio Zones Delay</title>`, replaced in Task 12), `tests/test_server.py`
- Modify: `src/audio_zones_delay/cli.py`

**Interfaces:**
- Consumes: model functions (Task 2), `make_signature`, `SIGNATURE_PARAMS` (Task 1).
- Produces: `make_server(data_dir: Path, port: int = 8765, host: str = "127.0.0.1") -> ThreadingHTTPServer` and the CLI `serve [--port 8765] [--data-dir data]`, which prints `Open http://localhost:<port>/ in the Windows browser (Chrome or Edge).` and serves until Ctrl+C.
- HTTP API (JSON errors are `{"error": "..."}` with status 400 or 404):
  - `GET /` → `player/index.html`. `GET /static/<name>` for `name ∈ {index.html, style.css, core.mjs, app.mjs}` (`.mjs` as `text/javascript`). Anything else is 404.
  - `GET /api/profile` → `data/profile.json`, or `profile_to_dict(default_profile())` when missing. `PUT /api/profile` → validate with `profile_from_dict`, then write it.
  - `GET /api/signature/params` → `asdict(SIGNATURE_PARAMS)`. `GET /api/signature?sample_rate=N` (8000 ≤ N ≤ 192000) → raw float32 little-endian bytes of `make_signature(N)`, as `application/octet-stream`.
  - `POST /api/sessions` (a session log with any `session_id`) → the server assigns `YYYYMMDD-HHMMSS` (adding `-2`, `-3`… if the folder exists), validates, writes `data/sessions/<id>/session.json` and returns `{"session_id": id}`. `PUT /api/sessions/<id>` → `<id>` must match `^\d{8}-\d{6}(-\d+)?$` and already exist. The body is validated and overwritten.
- Load player files with `importlib.resources.files("audio_zones_delay") / "player"`.

- [ ] **Step 1: Write the failing tests** (fixture: `make_server(tmp_path, port=0)` running in a daemon thread, using `http.client`)

```python
def test_profile_defaults_then_round_trips(server):
    assert len(get_json(server, "/api/profile")["speakers"]) == 17
    p = json.loads(FIXTURE.read_text())["profile"]
    assert request(server, "PUT", "/api/profile", p).status == 200
    assert get_json(server, "/api/profile") == p

def test_invalid_profile_is_rejected(server):
    bad = json.loads(FIXTURE.read_text())["profile"]; bad["speakers"][0]["zone"] = 7
    r = request(server, "PUT", "/api/profile", bad)
    assert r.status == 400 and "zone" in json.loads(r.read())["error"]

def test_signature_endpoint_44100(server):
    body = request(server, "GET", "/api/signature?sample_rate=44100").read()
    assert len(body) == 22050 * 4
    np.testing.assert_allclose(np.frombuffer(body, "<f4"), make_signature(44100))

def test_session_create_and_update(server, tmp_path):
    log = json.loads(FIXTURE.read_text())
    sid = json.loads(request(server, "POST", "/api/sessions", log).read())["session_id"]
    assert re.fullmatch(r"\d{8}-\d{6}", sid)
    log["session_id"] = sid; log["completed"] = False
    assert request(server, "PUT", f"/api/sessions/{sid}", log).status == 200
    assert json.loads((tmp_path / "sessions" / sid / "session.json").read_text())["completed"] is False

@pytest.mark.parametrize("path", ["/api/sessions/..%2F..%2Fx", "/api/sessions/20261024-211400"])
def test_bad_or_unknown_session_id(server, path):
    assert request(server, "PUT", path, json.loads(FIXTURE.read_text())).status in (400, 404)

def test_static_whitelist(server):
    assert request(server, "GET", "/").status == 200
    assert request(server, "GET", "/static/../server.py").status == 404
```

- [ ] **Step 2: Run them to verify they fail.** `uv run pytest tests/test_server.py -v`. Expected: FAIL.
- [ ] **Step 3: Implement `server.py`** and wire `serve` into `cli.py`.
- [ ] **Step 4: Run them to verify they pass.** Expected: all pass.
- [ ] **Step 5: Commit** `git commit -m "Add local server and azd serve command"`

---

### Task 11: Player session logic (pure JS)

**Files:**
- Create: `src/audio_zones_delay/player/core.mjs`, `tests/js/core.test.mjs`

**Interfaces:**
- Consumes: the JSON shapes from Task 2 (the fixture is the contract).
- Produces (ES module exports, no DOM, no Web Audio):
  - `LEAD_S = 0.25`, `TAIL_S = 0.3`
  - `buildVisits(profile) -> [{index, speaker_id, closure}]`. Same rule as Python `build_visits`. Throws if no speaker is measured.
  - `slotTime(originS, slot, periodS) -> number`, `nextFreeSlot(nowS, originS, periodS, lastSlot) -> int` = `max(lastSlot + 1, ceil((nowS + LEAD_S − originS) / periodS))`
  - `alignOrigin(nowS, sampleRate) -> number` = `ceil((nowS + 0.5)·sampleRate)/sampleRate`
  - `createSession({profile, label, sampleRate, signatureParams, createdAt, originS}) -> state`, whose state holds `phase ∈ {'move','holding','done'}`, `visitIndex`, `attempts`, `lastSlot`, `holdUntilS`, `currentSlots` and the inputs
  - `step(state, event) -> {state, effects}`. Events: `{type:'click', nowS}`, `{type:'redo'}`, `{type:'tick', nowS}`. Effects: `{type:'play', timesS:[...]}`, `{type:'save'}`.
  - `progress(state, nowS) -> {current, total}`
  - `toSessionLog(state, sessionId) -> object`, in exactly the fixture's shape. `signatures_per_visit` and `period_s` come from the profile.
- Transitions:
  - **click in `move`:** N slots from `nextFreeSlot`; append `{visit, attempt: count+1, slots}`; `holdUntilS = slotTime(last) + signatureParams.duration_s + TAIL_S`; go to `holding`; effects `play` and `save`.
  - **click in `holding` or `done`:** no change, no effects.
  - **tick in `holding` with `nowS ≥ holdUntilS`:** go to `done` with effect `save` if this was the last visit. Otherwise `visitIndex + 1` and `move`.
  - **redo in `move` or `done`:** `visitIndex − 1` (not below 0) and `move`.
  - **`completed`** in `toSessionLog` is `phase === 'done'`.

- [ ] **Step 1: Write the failing tests** with `node:test` and `node:assert/strict`. They read `tests/fixtures/session-example.json` with `fs` (`readFileSync(new URL('../fixtures/session-example.json', import.meta.url))`).

```js
test('nextFreeSlot respects lead and last slot', () => {
  assert.equal(nextFreeSlot(10.0, 10.0, 2.0, -1), 1);
  assert.equal(nextFreeSlot(13.75, 10.0, 2.0, -1), 2);
  assert.equal(nextFreeSlot(10.0, 10.0, 2.0, 5), 6);
});
test('alignOrigin lands on a sample frame', () => {
  const o = alignOrigin(1.23456, 48000);
  assert.ok(Math.abs(o * 48000 - Math.round(o * 48000)) < 1e-6); assert.ok(o >= 1.73456 && o < 1.73456 + 1 / 48000);
});
test('buildVisits matches the fixture', () => {
  assert.deepEqual(buildVisits(fx.profile), fx.visits);
});
test('full session with a redo produces the fixture log shape', () => {
  let s = createSession({profile: fx.profile, label: fx.label, sampleRate: 48000, signatureParams: fx.signature, createdAt: fx.created_at, originS: 0});
  const run = (e) => ({state: s} = step(s, e));
  run({type:'click', nowS: 5.5});  assert.deepEqual(s.attempts[0].slots, [3,4,5,6,7]);
  run({type:'click', nowS: 6.0});  assert.equal(s.attempts.length, 1);           // ignored while holding
  run({type:'tick',  nowS: 14.7}); assert.equal(s.phase, 'holding');             // holdUntil = 14 + 0.5 + 0.3
  run({type:'tick',  nowS: 14.9}); assert.equal(s.phase, 'move'); assert.equal(s.visitIndex, 1);
  run({type:'click', nowS: 21.5}); run({type:'tick', nowS: 30.9});
  run({type:'redo'});              assert.equal(s.visitIndex, 1);
  run({type:'click', nowS: 33.5}); run({type:'tick', nowS: 42.9});
  run({type:'click', nowS: 49.5}); const last = step(s, {type:'tick', nowS: 58.9});
  assert.equal(last.state.phase, 'done'); assert.deepEqual(last.effects, [{type:'save'}]);
  const log = toSessionLog(last.state, fx.session_id);
  assert.deepEqual(log, fx);
});
test('progress counts started signatures', () => {
  let {state} = step(createSession({profile: fx.profile, label:'', sampleRate:48000, signatureParams: fx.signature, createdAt:'', originS:0}), {type:'click', nowS: 5.5});
  assert.deepEqual(progress(state, 8.1), {current: 2, total: 5});   // slots 3,4 start at 6.0 and 8.0
});
```

(The clicks at 5.5, 21.5, 33.5 and 49.5 s give slots 3, 11, 17 and 25 with origin 0, P = 2 and lead 0.25, which matches the fixture.)

- [ ] **Step 2: Run them to verify they fail.** `bash -lc 'source ~/.nvm/nvm.sh && node --test tests/js/'`. Expected: FAIL (module not found).
- [ ] **Step 3: Implement `core.mjs`.**
- [ ] **Step 4: Run them to verify they pass.** Same command. Expected: all pass. Also run `uv run pytest` (still green).
- [ ] **Step 5: Commit** `git commit -m "Add player session state machine"`

---

### Task 12: Player UI, Web Audio and README

**Files:**
- Create: `src/audio_zones_delay/player/app.mjs`, `src/audio_zones_delay/player/style.css`
- Modify: `src/audio_zones_delay/player/index.html`, `README.md`, `CLAUDE.md`, `tests/test_server.py` (one smoke test)

**Interfaces:**
- Consumes: the `core.mjs` exports (Task 11) and the HTTP API (Task 10).

Behavior (mockups: `.superpowers/brainstorm/*/content/session-flow-v2.html`):
- **Setup screen:** an editable speaker table with name, zone, measured, Anthem distance (zone 1), seat distance and delay channel (zone 2), move up/down, delete and add (new ids `speaker-<n>`, unique). Fields for session label, signatures per visit, period, speed of sound and device latency. Phone tips: start the recorder first; point the phone's bottom edge at the grille, one hand-span away; turn off "enhance"/noise reduction if the recorder has it. **Save profile** sends `PUT /api/profile`. **Start session** is enabled only with at least 1 measured speaker in each zone.
- **Start:** `new AudioContext()` inside the click handler. Fetch `/api/signature?sample_rate=${ctx.sampleRate}` into an `AudioBuffer` (the same samples on both channels). Start a keep-alive `ConstantSourceNode` (offset 0) that runs for the whole session. `originS = alignOrigin(ctx.currentTime, ctx.sampleRate)`. `createSession`, `POST /api/sessions`, then `requestFullscreen()`.
- **Events:** a click anywhere or Space → `click` with `ctx.currentTime`. Key R → `redo`. A `requestAnimationFrame` loop sends `tick` and re-renders. Effect `play` → one `AudioBufferSourceNode.start(t)` per time. Effect `save` → `PUT /api/sessions/<id>` with `toSessionLog`.
- **Screens** (large text, dark background, readable from across the room): **MOVE** (green, "Next: <name>", hand-span instruction, "Speaker i of n"; on a redo, "Redo: <name>"), **HOLD STILL** (red, "Signature k of N", progress bar, "Clicks are ignored while playing · R = redo this speaker"), and **DONE** ("Stop the phone recording. Session saved as <id>." plus the exact `uv run azd analyze data/sessions/<id> <path-to-recording>` command). If `ctx.state !== 'running'`, show a red banner.
- **README:** what the tool does and why (one paragraph), prerequisites (`uv`, `sudo apt-get install ffmpeg`), setup (`uv sync`), the workflow (set Windows' default output to the receiver; set the Anthem to the plain stereo all-speaker mode you use; `uv run azd serve`; open the URL in the Windows browser; fill in the setup; start the phone recorder; run the session; copy the recording to the PC; `uv run azd analyze …`; open `report.html`), how to read the report, and a note that the delay is only valid for the measured mode. Update the `CLAUDE.md` Commands table.

- [ ] **Step 1: Add a smoke test** in `tests/test_server.py`: `GET /static/app.mjs` returns 200 with `text/javascript`, and its body contains `from './core.mjs'`. `GET /` contains `app.mjs`.
- [ ] **Step 2: Run it to verify it fails.** `uv run pytest tests/test_server.py -v`. Expected: the new test FAILS.
- [ ] **Step 3: Implement `index.html`, `style.css` and `app.mjs`, then update the README and CLAUDE.md.**
- [ ] **Step 4: Run all automated tests.** `uv run pytest` and `bash -lc 'source ~/.nvm/nvm.sh && node --test tests/js/'`. Expected: all pass.
- [ ] **Step 5: Manual check in the Windows browser** (no audio hardware needed). Run `uv run azd serve`, open `http://localhost:8765/`, edit and save the profile, and reload: the edits persist. Start a session with 2 measured speakers, click through all visits and press R once. Confirm that `data/sessions/<id>/session.json` has `completed: true`, a redo attempt and slots that strictly increase. Paste the file contents and a screenshot description into the task report. The real-room acceptance run (spec 6.11) belongs to the owner.
- [ ] **Step 6: Commit** `git commit -m "Add player UI and usage docs"`

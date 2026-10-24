# Audio Zones Delay: Design

Status: approved by the owner
Date: 2026-10-24

## 1. Intent

The owner has a roughly rectangular room of about 80 m² with two audio zones
fed by an Anthem MRX 1140 receiver:

- **Zone 1 (main zone):** 11 speakers (7 ear-level plus 4 height) and 2
  subwoofers, powered and processed by the Anthem.
- **Zone 2:** 4 extra speakers at the far ends of the room, outside the main
  system's coverage. They are driven from the Anthem's Zone 2 pre-outs
  through a separate Emotiva amplifier, because Zone 2 is not amplified by the
  receiver.

When both zones play the same audio, they are audibly out of sync. The owner
suspects that zone 1 is delayed by the Anthem's DSP while zone 2 bypasses
it, but this is not confirmed.

The owner is deciding whether to buy a delay device (for example a miniDSP)
and which one, since some models cap the delay at 30 ms and others at 80 ms.
To decide, the owner needs to know:

1. **Which zone is late** relative to the other.
2. **By how many milliseconds.**
3. **What delay to dial in** for each zone 2 speaker, and whether it fits a
   30 ms or an 80 ms device.

This repo builds a tool that answers those questions using only equipment the
owner already has: the PC connected to the receiver over HDMI, and a phone
voice recorder. There is no measurement microphone.

## 2. Goals

- Report which zone leads and by how many ms, with a stated uncertainty.
  About ±1 ms is enough for the purchase decision; sub-millisecond is
  expected.
- Suggest a delay per zone 2 speaker, and flag whether each value fits a
  30 ms device and an 80 ms device.
- Measure the real scenario: **both zones play simultaneously** for the whole
  session.
- Keep recording and analysis independent. Phase 1: the PC plays a guided
  test while the phone records. Phase 2: the owner copies the recording to
  the PC and runs the analysis.

## 3. Non-goals

- A live phone app or a phone-side web page. Possible later, out of scope now.
- Clock sync between phone and PC over Wi-Fi. Network jitter makes it useless
  at the 1 ms scale.
- Configuring the delay device automatically.
- Room EQ, frequency response, levels, or any correction beyond timing.
- Subwoofer timing. Subwoofers are not measured.

## 4. Anti-goals

- **A confident wrong number.** If the measurement is poor or the
  consistency checks fail, the report must say so and flag or withhold the
  verdict. It must never present a doubtful number as reliable.

## 5. Constraints

- **Everything in the repo is in English:** code, identifiers, comments, UI
  text, docs, commit messages, issues and PRs.
- **Platform:** Windows PC with WSL2. The repo lives in WSL. Audio reaches
  the receiver through Windows' HDMI output. Test audio must **not** be
  played through WSL's audio bridge (WSLg/PulseAudio), which is prone to
  glitches, and glitches corrupt the timing.
- **Tooling:** Python via `uv`, following the owner's other repos. Python 3.14
  and `uv` are installed in WSL. The Windows browser reaches servers in WSL
  at `localhost`.
- **Signal path:** in real use, the audio for both zones comes from this same
  PC over HDMI, so the test measures the real path. The PC sends stereo PCM
  over HDMI. Whenever both zones
  play together, the owner uses a plain stereo mode that spreads the same
  stereo content over every speaker, with Atmos and upmixing off. The goal is
  only to fill the whole room with sound. Sessions are run in that mode.
  See section 6.9 on why the mode matters.
- **No shared clock** between the phone and the PC.
- **The PC's display is probably the TV,** so the test screen must be
  readable from across the room.

## 6. Decided design

### 6.1 Measurement principle: near-field capture per speaker

The owner holds the phone **one hand-span (~20 cm) from each speaker's
grille**. At that distance the target speaker is roughly 20 dB louder than
any other speaker, so the **strongest** arrival in that capture belongs to it.
(The *first* arrival is not reliable: a far speaker that fires much earlier
can arrive first.)

All captures are placed on one common timeline (section 6.4). That yields
the time at which each speaker *emits* the signature. Comparing emission
times answers the questions in section 1.

The hand-span acoustic delay (~0.6 ms) is about the same for every speaker,
so it cancels in the comparisons.

**Rejected alternative:** recording both zones at one fixed spot in the room
and separating the two arrival clusters. Away from the main seat, the 11
zone 1 speakers arrive spread over about 10 to 20 ms, plus reflections, so
the zone 1 and zone 2 clusters cannot be separated reliably.

### 6.2 Guided session flow

The test player is a full-screen page with large text, readable from across
the room. It walks the owner through an ordered speaker list:

1. The owner starts the phone recorder, then starts the session on the PC.
2. Screen **MOVE**: "Next: <speaker name>. Hold the phone one hand-span from
   the grille, then click (or press Space)."
3. The owner reaches the speaker, holds the phone and clicks. The owner
   carries a wireless mouse, so clicking works from anywhere in the room.
   Space works too.
4. Screen **HOLD STILL**: "Signature k of N", with a progress bar. The app
   plays the signature N times (default 5) on the timing grid (section 6.3).
   Clicks are ignored while it is playing.
5. Back to **MOVE** with the next speaker. Repeat.
6. **Key R** redoes the current speaker (after a noise, a stumble, or a
   phone that moved). The analysis uses the last attempt for each speaker.
7. **Closure:** the session automatically ends by revisiting the first
   speaker. Comparing the first and last captures of that speaker validates
   the whole timeline (section 6.6).
8. At the end, the screen says the session is done and tells the owner to
   stop the phone recording.

The phone records **continuously** for the whole session. Signatures play
only while the owner stands still. Walking periods are silent and are never
analyzed.

Mockups from the brainstorming session (gitignored, local only):
`.superpowers/brainstorm/*/content/session-flow-v2.html` and `report-v1.html`.

### 6.3 Timing grid on the audio output clock

- Signatures start only on a fixed grid of slots spaced by a period P
  (default **2.000 s**). P is counted in **audio output samples** from the
  session origin: slot `k` starts at sample `k × P × sample_rate`.
- The grid follows the **audio output clock**, not the Windows wall clock.
  The wall clock is corrected over the network and jumps; converting
  between the two clocks would add milliseconds of jitter.
- After a click, the first signature waits for the next free slot (at most P
  later).
- The audio output stays open and **continuously renders digital silence**
  for the whole session, so the HDMI link never sleeps. A sleeping link
  makes receivers clip the start of the audio, and a resync could change the
  latency.
- The signature is identical on the left and right channels (mono content),
  so every speaker that receives a downmix or stereo content plays it.

### 6.4 Session log

The player writes a session log (JSON) that the analysis reads together with
the recording. It contains at least:

- schema version, session label (free text, for example
  `"All Channel Stereo, ARC on"`), creation time, output sample rate, period
  P, and a description of the signature (or a copy of it);
- the speaker list with its metadata (section 6.7);
- every attempt: speaker id, attempt number, and the slot indices of each
  signature played.

### 6.5 Analysis

Input: the session log plus the phone recording in any common format (m4a,
mp3, wav and so on).

1. Decode the recording to mono at its declared sample rate.
2. Detect every signature occurrence with a matched filter against the known
   signature. Estimate the arrival time of the **strongest** peak with
   sub-sample precision.
3. Assign detections to attempts and slot indices. Bursts are separated by
   walking silence, and gaps between detections are multiples of P. Use the
   log's attempt order and slot pattern; do not rely on counting alone.
4. Fit, jointly over all detections: arrival time in the recording =
   `a + b × slot_time + offset_speaker`. There is one common drift `b`
   (phone clock vs. PC audio clock) and one offset per speaker. The closure
   speaker's two attempts constrain the drift over the full session.
5. The offset of speaker `i` is its emission time `e_i` on the common
   timeline (up to a constant, which cancels).

### 6.6 From emission times to answers

Let `c` be the speed of sound (343 m/s at ~20 °C; builder may make it
configurable).

- **Zone 1:** the Anthem delays nearer speakers so that all of them arrive
  together at the main seat. With `D_i` the Anthem distance setting for zone 1
  speaker `i`, the quantity `A1_i = e_i + D_i / c` is the zone 1 arrival time
  at the main seat. **It should be the same for every zone 1 speaker.** That
  is a consistency check on both the measurement and the distances entered.
- **Zone 2:** with `d_j` the tape-measured distance from the main seat to
  zone 2 speaker `j`, the quantity `A2_j = e_j + d_j / c` is that speaker's
  arrival time at the main seat.
- **Suggested delay** for zone 2 speaker `j`: `delay_j = mean(A1) − A2_j`.
  This makes each zone 2 speaker behave like one more Anthem channel, using
  the same alignment rule the Anthem applies to zone 1. It does not depend on
  which speaker is the Anthem's reference (farthest) speaker.
- **If `delay_j` is negative,** zone 2 is late. A delay device on zone 2
  cannot fix that, and the report must say so explicitly.
- **Delay channels (designer's call):** the wiring of the 4 zone 2 speakers
  to amplifier channels is not known. Each zone 2 speaker therefore has a
  "delay channel" label in the setup. Speakers that share a label (for
  example a pair on one amplifier channel) get one compromise value, the mean
  of their `delay_j`, plus the leftover misalignment of each speaker. The
  report also gives the number of distinct delay channels, which is the
  number of outputs the device needs.
- **Device latency (designer's call):** a delay device adds a fixed
  pass-through latency of its own (A/D, DSP, D/A). The setup has a "delay
  device latency" field (default 0 ms). The value to dial in is
  `delay_j − device_latency`. If that is negative, the device alone already
  over-delays zone 2, and the report must say so.
- **Fit flags:** for each value to dial in, report whether it is ≤ 30 ms and
  ≤ 80 ms.
- **Headline "zone 2 is X ms earlier/later than zone 1":** the
  processing-latency difference, `X = mean_i(e_i − (D_max − D_i)/c) − mean_j(e_j)`,
  where `D_max` is the largest Anthem distance entered for zone 1 (the
  speaker the Anthem does not delay). This headline depends on `D_max`
  matching the Anthem's real reference speaker, which may include the subs.
  The per-speaker suggestions do not depend on it, so the report should label
  the headline as context and the per-speaker delays as the actionable
  numbers.
- If Anthem distances or tape distances are missing, the report gives only
  what it can: the raw emission times, which zone fires first, and by how
  much. No per-speaker suggestion.

### 6.7 Setup (room profile)

A setup screen in the player page, before the session:

- Speaker list, editable: name, zone (1 or 2), Anthem distance (zone 1), tape
  distance to the main seat and delay channel (zone 2), and whether it is
  measured in this session. Order in the list = visiting order.
- Delay device latency (default 0 ms).
- Zone 1 channels that are not measured (for example subwoofers) may still
  be listed with their Anthem distance, so that `D_max` can be computed.
- Session label (the Anthem mode in use), signatures per speaker (default 5),
  period P (default 2 s).
- The profile is saved locally and reused across sessions.

### 6.8 Report

An HTML report opened in the browser, plus a short summary in the terminal:

1. **Verdict:** which zone leads, by how many ms, with uncertainty, and
   whether a zone 2 delay device can fix it.
2. **Suggested delay per zone 2 speaker,** with 30 ms and 80 ms fit flags.
3. **Timeline chart** of each speaker's emission time, colored by zone.
4. **Per-speaker detail:** emission time, Anthem/tape distance, `A1_i` or
   `A2_j`, repeat spread, detection quality.
5. **Checks,** each pass/warn/fail: drift (ppm, plausible range), closure
   residual, repeat spread within each attempt, zone 1 consistency (spread of
   `A1_i`), all expected signatures detected, target-speaker dominance in
   each capture. Measured speakers with no detectable signature are reported
   as "no signal", not as errors (see section 6.9).

When a check fails in a way that undermines the verdict, the report says so
prominently and does not present the verdict as reliable (section 4).

### 6.9 Listening mode matters

The Anthem's processing latency can differ between listening modes (upmixers,
room correction and so on). **The measured delay is only valid for the mode
used during the session.** The owner's real two-zone use is a plain stereo
mode spread over every speaker (section 5), so that is the mode to measure
in. The session label records the mode anyway, so later sessions in other
modes can be compared.

Because the signature is identical on L and R, every zone 1 speaker should
play it in that mode. Still, a speaker that gets little or no signature (for
example a center channel that the mode leaves silent, or a session run in an
upmix mode, where identical L/R content goes mostly to the center) is
reported as "no signal", not as an error. One well-captured zone 1 speaker is
enough for a verdict.

### 6.10 Architecture

- **One Python project managed with `uv`.**
- **Player:** a local web page served by the Python app from WSL and opened
  in the Windows browser (`localhost`). Audio uses Web Audio, scheduled
  against the AudioContext clock, which is the audio output clock. This keeps
  test audio on Windows' native audio path.
- **Session storage:** sessions (log, recording, report) live under a local
  folder that is gitignored, because recordings are large and personal.
- **Analysis:** Python (numpy/scipy or similar), run from the command line
  against a session.

### 6.11 Verification

- **Automated end-to-end tests** with synthetic sessions: generate a session
  log, then synthesize a "phone recording" by summing delayed and attenuated
  copies of the signature for every speaker. Add a dominant near speaker per
  capture, room reverb, noise, a sample-rate mismatch, clock drift, and lossy
  (AAC) encoding. Assert that the analysis recovers the known emission times
  and suggested delays within tolerance, and that the checks fail when they
  should (glitch, wrong distances, missing speaker).
- **Owner acceptance:** a real session in the room producing a report whose
  checks pass, with a closure residual well under 1 ms.

## 7. Left to the builder

- Signature design: type (for example a log sweep), band, length, level, and
  fade. Requirements: a sharp matched-filter peak (sub-millisecond), robust
  to phone recorder processing and AAC encoding, audible but not unpleasant,
  no subwoofer-only content, and short enough to decay well within P.
- Detection and peak-picking algorithm, sub-sample interpolation, and check
  thresholds.
- Web server framework, page structure and styling, how the session log
  reaches disk (server endpoint or download), and the CLI shape and names.
- How the player keeps the output alive (for example a continuous silent
  source) and how it detects or guards against output glitches.
- Room profile and session folder formats, and file naming.
- Owner-facing instructions in the README and on screen: recorder settings
  (turn off "enhance" or noise reduction where possible), which edge of the
  phone to point at the speaker, and so on.

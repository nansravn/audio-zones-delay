# audio-zones-delay

A home theater receiver can feed two speaker zones, for example front speakers plus rear or surround speakers, and a separate delay device can hold back the second zone so that sound from both zones reaches the listening seat together. This tool measures the delay to dial in. A browser page plays a short test sweep a few times while you hold a phone one hand-span from one speaker, then again at the next speaker, and so on. Every speaker plays each sweep; holding the phone that close to one speaker is what makes it stand out in the recording. The phone records everything. A command-line analysis then finds each sweep in the recording, works out when each speaker actually emitted its sound, and reports the delay each zone 2 channel needs.

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/)
- `ffmpeg`, used to decode the phone recording: `sudo apt-get install ffmpeg`
- A Windows browser (Chrome or Edge) to play the test signal. The server runs in WSL and the page is opened from Windows.

## Setup

```
uv sync
```

Before each measuring session:

- Set Windows' default audio output to the receiver, and set that HDMI/receiver output device to **Stereo** (Sound control panel → the receiver device → Configure → Speaker setup → Stereo).
- Set the Anthem to the plain stereo all-speaker mode you use for listening.
- Set the Zone 2 volume close to zone 1's for the test. If zone 2 is much quieter, the phone at a zone 2 speaker can pick up a nearby zone 1 speaker instead, and the report then withholds the result.
- Bypass any zone 2 delay device, or set all its outputs to 0 ms, while measuring. The zone 2 timing check expects every zone 2 speaker to emit together, so a session recorded through per-channel delays fails it by design.

## Workflow

1. Start the server: `uv run azd serve`.
2. Open the URL it prints (`http://localhost:8765/`) in the Windows browser.
3. Fill in the setup: the speakers (zone, measured or not, Anthem distance for zone 1, seat distance and delay channel for zone 2), a session label, and the timing fields. Distances are in metres. Start the list with a speaker that surely plays in this mode, such as Front Left: the session starts and ends with it, and the closing check needs it. Click **Save profile**.
4. Start the phone recorder and leave it running. If you restart a session, restart the recorder too: each session needs its own recording.
5. Click **Start session** and follow the screen: **MOVE** to the next speaker, click or press Space, **HOLD STILL** while the signatures play, repeat. After a speaker finishes, press R to go back and redo it.
6. At **DONE**, press R first if you want to redo the last (closure) speaker. Then stop the recorder right away: long recordings use a lot of memory in the analysis.
7. Copy the recording to the PC, for example to `C:\Users\<you>\Downloads`. From WSL that folder is `/mnt/c/Users/<you>/Downloads`.
8. Run the command shown on the DONE screen with the recording's path, for example `uv run azd analyze data/sessions/<id> /mnt/c/Users/<you>/Downloads/<file>.m4a`.
9. Open `data/sessions/<id>/report.html`.

Profiles, sessions, recordings and reports live under `data/`, which is not committed.

### `azd analyze`

```
uv run azd analyze <session-dir> <recording> [--device-latency-ms MS]
```

- `--device-latency-ms MS` replaces the profile's delay device latency (0 to 1000 ms) for this analysis only; `session.json` is not changed.
- Exit code 0: report written, verdict reliable.
- Exit code 2: report written, verdict withheld because a check failed.
- Exit code 1: nothing analyzed (missing or invalid session, unreadable recording, a recording that does not match the session, an invalid option, or a report that cannot be written). The message says which.

### Phone recording tips

- Start the recorder before the session, and stop it only after DONE.
- Point the phone's bottom edge at the grille, one hand-span away.
- Turn off "enhance" or noise reduction if the recorder has it.
- Stay still while the screen says HOLD STILL.

### First real session checklist

- Include one pause longer than 60 s mid-session (wait at a MOVE screen); the closure check must still pass.
- All checks pass, and the closure residual is well under 1 ms.

## Reading the report

- **Verdict.** The first line says whether zone 2 plays earlier or later than zone 1, with its uncertainty. It is context only: it depends on the farthest Anthem distance entered (subwoofers included). The dial values in the delay table are the numbers to act on. If a delay device cannot fix a channel because zone 2 is already late there, or its own latency already over-delays it, the verdict says so.
- **Delay table.** One row per delay device output, counting every zone 2 speaker in the profile. Each row gives the delay needed, the value to dial in (device latency already subtracted), whether it fits a device whose maximum delay is 30 ms or 80 ms, and the leftover misalignment of each speaker on that output. A fit shown as "borderline" is within the uncertainty of the limit (or of zero), so it could go either way. Without distances in the profile you get a raw zone gap instead of per-speaker delays.
- **Partial channels.** If some speakers on a channel had no signal in the recording, or were not measured in this session, the row is marked "partial" and names them. The value uses the speakers that were heard, so check it before trusting it. A channel with no measured speaker is listed as "not measured".
- **Per-speaker detail.** Each speaker's emission time, its Anthem or seat distance, its arrival time at the seat (A1 for zone 1, A2 for zone 2), and capture quality. Zone 1 arrival times should all agree; when the zone 1 check fails, look for the A1 value that is off.
- **Checks.** A list of pass, warn and fail checks on the recording: clock drift between phone and PC, the closure visit, spread between repeated signatures, zone 1 distance consistency, zone 2 timing consistency (zone 2 speakers share one amplifier, so they must emit together), distances that look like feet, coverage of the speakers, how clearly each speaker was heard, and captures much quieter than the rest (a capture more than 12 dB below the others fails, because it has likely picked up another speaker).
- **Verdict withheld.** When a check fails in a way that makes the numbers unreliable, no delay is given. The report shows the failing checks and diagnostics only; fix the cause (usually the recording or the room) and run the session again.

The delay is only valid for the Anthem mode measured. Another mode, other processing or a different ARC setting can change timing, so measure again after changing it.

# audio-zones-delay

A home theater receiver can feed two speaker zones, for example front speakers plus rear or surround speakers, and a separate delay device can hold back the second zone so that sound from both zones reaches the listening seat together. This tool measures the delay to dial in. A browser page plays a short test sweep through each speaker, one at a time, while you stand at the speaker with a phone recording everything. A command-line analysis then finds each sweep in the recording, works out when each speaker actually emitted its sound, and reports the delay each zone 2 channel needs.

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/)
- `ffmpeg`, used to decode the phone recording: `sudo apt-get install ffmpeg`
- A Windows browser (Chrome or Edge) to play the test signal. The server runs in WSL and the page is opened from Windows.

## Setup

```
uv sync
```

## Workflow

1. Set Windows' default audio output to the receiver.
2. Set the Anthem to the plain stereo all-speaker mode you use for listening.
3. Start the server: `uv run azd serve`.
4. Open the URL it prints (`http://localhost:8765/`) in the Windows browser.
5. Fill in the setup: the speakers (zone, measured or not, Anthem distance for zone 1, seat distance and delay channel for zone 2), a session label, and the timing fields. Click **Save profile**.
6. Start the phone recorder and leave it running.
7. Click **Start session** and follow the screen: **MOVE** to the next speaker, click or press Space, **HOLD STILL** while the signatures play, repeat. Press R to redo a speaker. When the screen says **DONE**, stop the recording.
8. Copy the recording to the PC.
9. Run the command shown on the DONE screen, for example `uv run azd analyze data/sessions/<id> <path-to-recording>`.
10. Open `data/sessions/<id>/report.html`.

Profiles, sessions, recordings and reports live under `data/`, which is not committed.

### Phone recording tips

- Start the recorder before the session, and stop it only after DONE.
- Point the phone's bottom edge at the grille, one hand-span away.
- Turn off "enhance" or noise reduction if the recorder has it.
- Stay still while the screen says HOLD STILL.

## Reading the report

- **Verdict.** The headline says whether zone 2 plays earlier or later than zone 1, with its uncertainty. If a delay device cannot fix a channel because zone 2 is already late there, or its own latency already over-delays it, the verdict says so.
- **Delay table.** One row per delay device channel: the delay needed, the value to dial in (device latency already subtracted), whether it fits a 30 ms and an 80 ms device, and the leftover misalignment of each speaker on that channel. Without distances in the profile you get a raw zone gap instead of per-speaker delays.
- **Partial channels.** If some speakers on a channel had no signal in the recording, the row is marked "partial" and names them. The value uses the speakers that were heard, so check it before trusting it.
- **Checks.** A list of pass, warn and fail checks on the recording (clock drift between phone and PC, the closure visit, spread between repeated signatures, zone 1 distance consistency, coverage of the speakers, and how clearly each speaker was heard).
- **Verdict withheld.** When a check fails in a way that makes the numbers unreliable, no delay is given. The report shows the failing checks and diagnostics only; fix the cause (usually the recording or the room) and run the session again.

The delay is only valid for the Anthem mode measured. Another mode, other processing or a different ARC setting can change timing, so measure again after changing it.

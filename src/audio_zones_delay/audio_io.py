"""Recording loader: decodes any ffmpeg-readable file to mono float64 at the analysis rate."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np

from audio_zones_delay.signature import ANALYSIS_RATE


class RecordingError(Exception):
    """The recording could not be located or decoded."""


def ffmpeg_path() -> str:
    path = shutil.which("ffmpeg")
    if path is None:
        raise RecordingError("ffmpeg not found: install it with sudo apt-get install ffmpeg")
    return path


def load_recording(path: Path, sample_rate: int = ANALYSIS_RATE) -> np.ndarray:
    """Decode ``path`` to a mono float64 array resampled to ``sample_rate``."""
    exe = ffmpeg_path()
    path = Path(path)
    if not path.is_file():
        raise RecordingError(f"recording not found: {path}")
    cmd = [exe, "-nostdin", "-i", str(path), "-vn", "-ac", "1", "-ar", str(sample_rate),
           "-f", "f32le", "pipe:1"]
    try:
        proc = subprocess.run(cmd, capture_output=True, check=False)
    except OSError as e:
        raise RecordingError(f"could not run ffmpeg: {e}") from e
    if proc.returncode != 0:
        tail = proc.stderr.decode(errors="replace").strip().splitlines()[-1:]
        raise RecordingError(f"ffmpeg could not decode {path.name}: {' '.join(tail)}")
    samples = np.frombuffer(proc.stdout, dtype="<f4")
    if samples.size == 0:
        raise RecordingError(f"{path.name} contains no audio")
    return samples.astype(np.float64)

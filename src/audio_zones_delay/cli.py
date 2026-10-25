"""The ``azd`` command line."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analysis import analyze
from .assign import AlignmentError
from .audio_io import RecordingError, load_recording
from .model import load_session
from .report import render_html, render_summary


def _fail(message: str) -> int:
    print(f"azd: {message}", file=sys.stderr)
    return 1


def _cmd_analyze(args: argparse.Namespace) -> int:
    session_dir = Path(args.session_dir)
    try:
        session = load_session(session_dir / "session.json")
    except FileNotFoundError:
        return _fail(f"no session.json in {session_dir}")
    except (ValueError, TypeError, AttributeError, json.JSONDecodeError) as e:
        return _fail(f"invalid session.json in {session_dir}: {e}")
    if args.device_latency_ms is not None:
        session.profile.device_latency_ms = args.device_latency_ms
    try:
        recording = load_recording(Path(args.recording))
        result = analyze(session, recording)
    except RecordingError as e:
        return _fail(str(e))
    except AlignmentError as e:
        return _fail(f"the recording does not match this session ({e})")
    report_path = session_dir / "report.html"
    try:
        report_path.write_text(render_html(result), encoding="utf-8")
    except OSError as e:
        return _fail(f"cannot write {report_path}: {e}")
    print(render_summary(result, report_path))
    return 0 if result.reliable else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="azd", description="Audio zones delay tool")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("analyze", help="analyze a recording of a session")
    p.add_argument("session_dir")
    p.add_argument("recording")
    p.add_argument("--device-latency-ms", type=float, default=None,
                   help="override the profile's delay device latency")
    p.set_defaults(func=_cmd_analyze)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

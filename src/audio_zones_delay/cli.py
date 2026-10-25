"""The ``azd`` command line."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analysis import analyze
from .assign import AlignmentError
from .audio_io import RecordingError, load_recording
from .model import DEVICE_LATENCY_RANGE_MS, is_finite_number, load_session
from .report import render_html, render_summary


def _fail(message: str) -> int:
    print(f"azd: {message}", file=sys.stderr)
    return 1


def _cmd_analyze(args: argparse.Namespace) -> int:
    latency = args.device_latency_ms
    lo, hi = DEVICE_LATENCY_RANGE_MS
    if latency is not None and not (is_finite_number(latency) and lo <= latency <= hi):
        return _fail(f"--device-latency-ms must be a number from {lo:g} to {hi:g}, got {latency:g}")
    session_dir = Path(args.session_dir)
    try:
        session = load_session(session_dir / "session.json")
    except FileNotFoundError:
        return _fail(f"no session.json in {session_dir}")
    except (ValueError, TypeError, AttributeError, json.JSONDecodeError) as e:
        return _fail(f"invalid session.json in {session_dir}: {e}")
    if latency is not None:
        session.profile.device_latency_ms = latency
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


def _cmd_serve(args: argparse.Namespace) -> int:
    from .server import make_server

    data_dir = Path(args.data_dir)
    try:
        server = make_server(data_dir, port=args.port)
    except OSError as e:
        return _fail(f"cannot start the server on port {args.port}: {e}")
    port = server.server_address[1]
    print(f"Open http://localhost:{port}/ in the Windows browser (Chrome or Edge).")
    print(f"Profiles and sessions are stored in {data_dir.resolve()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print()
    finally:
        server.server_close()
    return 0


class _Parser(argparse.ArgumentParser):
    """Usage errors exit 1: exit code 2 means "verdict withheld"."""

    def error(self, message: str):
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="azd", description="Audio zones delay tool")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("analyze", help="analyze a recording of a session")
    p.add_argument("session_dir")
    p.add_argument("recording")
    p.add_argument("--device-latency-ms", type=float, default=None,
                   help="override the profile's delay device latency")
    p.set_defaults(func=_cmd_analyze)
    p = sub.add_parser("serve", help="serve the player page on localhost")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--data-dir", default="data")
    p.set_defaults(func=_cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

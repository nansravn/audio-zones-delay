"""Local HTTP server: serves the player page and stores profiles and sessions."""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .model import (
    default_profile,
    profile_from_dict,
    profile_to_dict,
    session_from_dict,
    session_to_dict,
)
from .signature import SIGNATURE_PARAMS, make_signature

MAX_BODY = 1024 * 1024
SESSION_ID = re.compile(r"\d{8}-\d{6}(-\d+)?")
STATIC_TYPES = {
    "index.html": "text/html; charset=utf-8",
    "style.css": "text/css; charset=utf-8",
    "core.mjs": "text/javascript; charset=utf-8",
    "app.mjs": "text/javascript; charset=utf-8",
}
CLIENT_ERRORS = (ValueError, TypeError, KeyError, AttributeError)


class _HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


class _Handler(BaseHTTPRequestHandler):
    server: "_Server"

    def log_message(self, format: str, *args) -> None:  # noqa: A002
        pass

    # -- responses -------------------------------------------------------
    def _send(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, obj) -> None:
        self._send(status, json.dumps(obj).encode("utf-8"), "application/json")

    def _read_json(self) -> dict:
        raw = self.headers.get("Content-Length")
        try:
            length = int(raw)
        except (TypeError, ValueError):
            raise _HttpError(400, "missing or invalid Content-Length") from None
        if length < 0:
            raise _HttpError(400, "missing or invalid Content-Length")
        if length > MAX_BODY:
            # Drain a bounded amount so the client can read the response.
            remaining = min(length, 16 * MAX_BODY)
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
            self.close_connection = True
            raise _HttpError(413, "request body too large")
        try:
            data = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError) as e:
            raise _HttpError(400, f"invalid JSON: {e}") from None
        if not isinstance(data, dict):
            raise _HttpError(400, "request body must be a JSON object")
        return data

    # -- dispatch --------------------------------------------------------
    def _dispatch(self, method: str) -> None:
        try:
            self._route(method)
        except _HttpError as e:
            self._json(e.status, {"error": e.message})
        except CLIENT_ERRORS as e:
            self._json(400, {"error": f"invalid request: {e}"})

    def do_GET(self) -> None:
        self._dispatch("GET")

    def do_PUT(self) -> None:
        self._dispatch("PUT")

    def do_POST(self) -> None:
        self._dispatch("POST")

    def do_DELETE(self) -> None:
        self._dispatch("DELETE")

    def do_PATCH(self) -> None:
        self._dispatch("PATCH")

    def _route(self, method: str) -> None:
        parts = urlsplit(self.path)
        path = parts.path
        data_dir = self.server.data_dir

        def allow(*methods: str) -> None:
            if method not in methods:
                raise _HttpError(405, f"method {method} not allowed")

        if path == "/" or path.startswith("/static/"):
            name = "index.html" if path == "/" else path[len("/static/"):]
            if name not in STATIC_TYPES:
                raise _HttpError(404, "not found")
            allow("GET")
            body = (files("audio_zones_delay") / "player" / name).read_bytes()
            self._send(200, body, STATIC_TYPES[name])
        elif path == "/api/profile":
            allow("GET", "PUT")
            profile_path = data_dir / "profile.json"
            if method == "GET":
                if profile_path.exists():
                    body = profile_path.read_bytes()
                else:
                    body = json.dumps(profile_to_dict(default_profile())).encode()
                self._send(200, body, "application/json")
            else:
                profile = profile_from_dict(self._read_json())
                _write_atomic(profile_path, json.dumps(profile_to_dict(profile), indent=2))
                self._json(200, {"ok": True})
        elif path == "/api/signature/params":
            allow("GET")
            self._json(200, asdict(SIGNATURE_PARAMS))
        elif path == "/api/signature":
            allow("GET")
            values = parse_qs(parts.query).get("sample_rate", [])
            try:
                rate = int(values[0])
            except (IndexError, ValueError):
                raise _HttpError(400, "sample_rate must be an integer") from None
            if not 8000 <= rate <= 192000:
                raise _HttpError(400, "sample_rate must be between 8000 and 192000")
            body = make_signature(rate).astype("<f4").tobytes()
            self._send(200, body, "application/octet-stream")
        elif path == "/api/sessions":
            allow("POST")
            self._create_session()
        elif path.startswith("/api/sessions/"):
            sid = path[len("/api/sessions/"):]
            allow("PUT")
            if not SESSION_ID.fullmatch(sid):
                raise _HttpError(400, "invalid session id")
            session_path = data_dir / "sessions" / sid / "session.json"
            if not session_path.parent.is_dir():
                raise _HttpError(404, "unknown session")
            body = self._read_json()
            body["session_id"] = sid
            session = session_from_dict(body)
            _write_atomic(session_path, json.dumps(session_to_dict(session), indent=2))
            self._json(200, {"session_id": sid})
        else:
            raise _HttpError(404, "not found")

    def _create_session(self) -> None:
        body = self._read_json()
        sessions = self.server.data_dir / "sessions"
        sessions.mkdir(parents=True, exist_ok=True)
        base = datetime.now().strftime("%Y%m%d-%H%M%S")
        sid, n = base, 1
        while True:
            try:
                (sessions / sid).mkdir()
                break
            except FileExistsError:
                n += 1
                sid = f"{base}-{n}"
        body["session_id"] = sid
        try:
            session = session_from_dict(body)
            _write_atomic(sessions / sid / "session.json",
                          json.dumps(session_to_dict(session), indent=2))
        except BaseException:
            (sessions / sid / "session.json").unlink(missing_ok=True)
            (sessions / sid).rmdir()
            raise
        self._json(201, {"session_id": sid})


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    data_dir: Path


def make_server(data_dir: Path, port: int = 8765, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    server = _Server((host, port), _Handler)
    server.data_dir = Path(data_dir)
    return server

import http.client
import json
import re
import threading
from pathlib import Path

import numpy as np
import pytest

from audio_zones_delay.server import make_server
from audio_zones_delay.signature import make_signature

FIXTURE = Path(__file__).parent / "fixtures" / "session-example.json"


@pytest.fixture
def server(tmp_path):
    srv = make_server(tmp_path, port=0)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()
    thread.join()


def request(server, method, path, body=None, raw=None, headers=None):
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
    hdrs = dict(headers or {})
    data = raw
    if body is not None:
        data = json.dumps(body).encode()
    if data is not None:
        hdrs.setdefault("Content-Type", "application/json")
    conn.request(method, path, body=data, headers=hdrs)
    resp = conn.getresponse()
    payload = resp.read()
    resp.read = lambda: payload
    conn.close()
    return resp


def get_json(server, path):
    return json.loads(request(server, "GET", path).read())


def test_profile_defaults_then_round_trips(server):
    assert len(get_json(server, "/api/profile")["speakers"]) == 17
    p = json.loads(FIXTURE.read_text())["profile"]
    assert request(server, "PUT", "/api/profile", p).status == 200
    assert get_json(server, "/api/profile") == p


def test_invalid_profile_is_rejected(server):
    bad = json.loads(FIXTURE.read_text())["profile"]
    bad["speakers"][0]["zone"] = 7
    r = request(server, "PUT", "/api/profile", bad)
    assert r.status == 400 and "zone" in json.loads(r.read())["error"]


@pytest.mark.parametrize("body", [[], {"speakers": "x"}])
def test_malformed_profile_bodies_are_400(server, body):
    r = request(server, "PUT", "/api/profile", body)
    assert r.status == 400 and "error" in json.loads(r.read())


def test_invalid_json_and_bad_content_length(server):
    assert request(server, "PUT", "/api/profile", raw=b"{nope").status == 400
    conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1])
    conn.putrequest("PUT", "/api/profile")
    conn.endheaders()
    assert conn.getresponse().status == 400
    conn.close()


def test_oversized_body_is_413(server):
    r = request(server, "PUT", "/api/profile", raw=b" " * (1024 * 1024 + 1))
    assert r.status == 413


def test_signature_endpoint_44100(server):
    body = request(server, "GET", "/api/signature?sample_rate=44100").read()
    assert len(body) == 22050 * 4
    np.testing.assert_allclose(np.frombuffer(body, "<f4"), make_signature(44100))


@pytest.mark.parametrize("q", ["", "?sample_rate=abc", "?sample_rate=100", "?sample_rate=999999"])
def test_signature_bad_sample_rate(server, q):
    assert request(server, "GET", "/api/signature" + q).status == 400


def test_signature_params(server):
    assert isinstance(get_json(server, "/api/signature/params"), dict)


def test_session_create_and_update(server, tmp_path):
    log = json.loads(FIXTURE.read_text())
    sid = json.loads(request(server, "POST", "/api/sessions", log).read())["session_id"]
    assert re.fullmatch(r"\d{8}-\d{6}(-\d+)?", sid)
    log["session_id"] = sid
    log["completed"] = False
    assert request(server, "PUT", f"/api/sessions/{sid}", log).status == 200
    saved = json.loads((tmp_path / "sessions" / sid / "session.json").read_text())
    assert saved["completed"] is False


def test_session_ids_do_not_collide(server):
    log = json.loads(FIXTURE.read_text())
    ids = {json.loads(request(server, "POST", "/api/sessions", log).read())["session_id"]
           for _ in range(3)}
    assert len(ids) == 3


def test_invalid_session_post_leaves_nothing(server, tmp_path):
    r = request(server, "POST", "/api/sessions", {"profile": "x"})
    assert r.status == 400
    assert list((tmp_path / "sessions").iterdir()) == []


@pytest.mark.parametrize("path", ["/api/sessions/..%2F..%2Fx", "/api/sessions/20261024-211400"])
def test_bad_or_unknown_session_id(server, path):
    assert request(server, "PUT", path, json.loads(FIXTURE.read_text())).status in (400, 404)


def test_static_whitelist(server):
    assert request(server, "GET", "/").status == 200
    assert request(server, "GET", "/?x=1").status == 200
    assert request(server, "GET", "/static/../server.py").status == 404
    assert request(server, "GET", "/static/index.html").status == 200


def test_unknown_route_and_method(server):
    r = request(server, "GET", "/nope")
    assert r.status == 404 and "error" in json.loads(r.read())
    assert request(server, "DELETE", "/api/profile").status == 405
    assert request(server, "POST", "/api/signature").status == 405


def test_deeply_nested_json_is_400(server):
    r = request(server, "PUT", "/api/profile", raw=b"[" * 200000)
    assert r.status == 400 and "error" in json.loads(r.read())

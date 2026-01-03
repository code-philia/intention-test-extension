"""
Tests for backend/server.py endpoints and cancellation support.
"""

from __future__ import annotations

import http.client
import json
import socketserver
import threading
import time

import pytest


@pytest.fixture
def http_server(monkeypatch):
    import server

    def fake_start_query(self):
        while not self.should_stop():
            time.sleep(0.01)

    monkeypatch.setattr(server.ModelQuerySession, "start_query", fake_start_query)

    for session_id in server._session_registry.list_active_ids():
        server._session_registry.remove(session_id)

    httpd = socketserver.ThreadingTCPServer(("localhost", 0), server.QueryHandler)
    httpd.daemon_threads = True
    httpd.allow_reuse_address = True

    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()

    try:
        yield httpd.server_address[1], server
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)
        for session_id in server._session_registry.list_active_ids():
            server._session_registry.remove(session_id)


def _post_json(port: int, path: str, payload: dict) -> http.client.HTTPResponse:
    body = json.dumps(payload).encode("utf-8")
    conn = http.client.HTTPConnection("localhost", port, timeout=2)
    conn.request(
        "POST",
        path,
        body=body,
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        },
    )
    return conn.getresponse()


class TestJunitVersionEndpoint:
    def test_junit_version_updates_global(self, http_server):
        port, server = http_server
        res = _post_json(port, "/junitVersion", {"type": "change_junit_version", "data": 5})
        assert res.status == 200
        res.read()
        assert server._global_junit_version == 5


class TestStopEndpoint:
    def test_stop_unknown_session_returns_404(self, http_server):
        port, _server = http_server
        res = _post_json(port, "/session/stop", {"session_id": "does-not-exist"})
        assert res.status == 404
        res.read()


class TestSessionStopFlow:
    def test_stop_request_cancels_session(self, http_server):
        port, server = http_server

        query_payload = {
            "type": "query",
            "data": {
                "target_focal_method": "test",
                "target_focal_file": "Test.java",
                "test_desc": "description",
                "project_path": "/path",
                "focal_file_path": "/path/Test.java",
            },
        }

        body = json.dumps(query_payload).encode("utf-8")
        conn = http.client.HTTPConnection("localhost", port, timeout=2)
        conn.request(
            "POST",
            "/session",
            body=body,
            headers={
                "Content-Type": "application/json",
                "Content-Length": str(len(body)),
            },
        )
        res = conn.getresponse()
        assert res.status == 200

        start_line = res.readline()
        start_msg = json.loads(start_line.decode("utf-8"))
        session_id = start_msg["data"]["message"]["session_id"]

        stop_res = _post_json(port, "/session/stop", {"session_id": session_id})
        assert stop_res.status == 200
        stop_res.read()

        finish_seen = False
        for _ in range(200):
            line = res.readline()
            if not line:
                break
            msg = json.loads(line.decode("utf-8"))
            if msg.get("type") == "status" and msg.get("data", {}).get("status") == "finish":
                finish_seen = True
                break
        assert finish_seen is True

        assert session_id not in server._session_registry.list_active_ids()

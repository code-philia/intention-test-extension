"""
Tests for backend/server.py session utilities.
"""

from __future__ import annotations

import json
import io

import pytest


class DummyWriter:
    def __init__(self):
        self.written: list[bytes] = []

    def __call__(self, data: bytes):
        self.written.append(data)


def _minimal_raw_data():
    return {
        "target_focal_method": "test",
        "target_focal_file": "Test.java",
        "test_desc": "desc",
        "project_path": "/path",
        "focal_file_path": "/path/Test.java",
    }


class TestModelQuerySession:
    def test_required_fields(self):
        from modules.session import ModelQuerySession

        assert "target_focal_method" in ModelQuerySession.required_fields
        assert "test_desc" in ModelQuerySession.required_fields
        assert len(ModelQuerySession.required_fields) == 5

    def test_request_stop_and_should_stop(self):
        from modules.session import ModelQuerySession

        writer = DummyWriter()
        session = ModelQuerySession("sess-1", _minimal_raw_data(), writer, lambda *_: None, 4)

        assert session.should_stop() is False
        session.request_stop()
        assert session.should_stop() is True

    def test_write_start_message(self):
        from modules.session import ModelQuerySession

        writer = DummyWriter()
        session = ModelQuerySession("sess-2", _minimal_raw_data(), writer, lambda *_: None, 4)
        session.write_start_message()

        parsed = json.loads(writer.written[0].decode("utf-8"))
        assert parsed["type"] == "status"
        assert parsed["data"]["status"] == "start"
        assert parsed["data"]["message"]["session_id"] == "sess-2"

    def test_write_finish_message(self):
        from modules.session import ModelQuerySession

        writer = DummyWriter()
        session = ModelQuerySession("sess-3", _minimal_raw_data(), writer, lambda *_: None, 4)
        session.write_finish_message()

        parsed = json.loads(writer.written[0].decode("utf-8"))
        assert parsed["type"] == "status"
        assert parsed["data"]["status"] == "finish"
        assert parsed["data"]["message"]["session_id"] == "sess-3"

    def test_update_messages(self):
        from modules.session import ModelQuerySession

        writer = DummyWriter()
        session = ModelQuerySession("sess-4", _minimal_raw_data(), writer, lambda *_: None, 4)

        messages = [{"role": "assistant", "content": "Hello"}]
        session.update_messages(messages)

        parsed = json.loads(writer.written[0].decode("utf-8"))
        assert parsed["type"] == "msg"
        assert parsed["data"]["session_id"] == "sess-4"
        assert parsed["data"]["messages"] == messages


class DummyHandler:
    def __init__(self):
        self.wfile = io.BytesIO()


class TestValidateQueryPayload:
    def test_validate_query_payload(self):
        import server

        payload = {"type": "query", "data": _minimal_raw_data()}
        result = server.validate_query_payload(payload)

        assert result["data"] == _minimal_raw_data()
        assert result["session_id"]

    def test_validate_query_payload_missing_fields(self):
        import server

        payload = {"type": "query", "data": {}}
        with pytest.raises(ValueError):
            server.validate_query_payload(payload)


class TestBuildSession:
    def test_build_session_returns_session(self):
        import server
        from modules.session import ModelQuerySession

        handler = DummyHandler()
        payload = {"session_id": "sess-5", "data": _minimal_raw_data()}

        session = server.build_session(payload, handler)

        assert isinstance(session, ModelQuerySession)
        assert session.session_id == "sess-5"

"""
Tests for server.py message serialization classes.
"""
import json


class TestStatusMessage:
    """Test StatusMessage serialization."""

    def test_to_bytes_with_string_message(self):
        """Test serialization with a string message."""
        from modules.messages import StatusMessage

        msg = StatusMessage(status="running", message="Processing...")
        result = msg.to_bytes()

        assert isinstance(result, bytes)
        parsed = json.loads(result.decode())
        assert parsed["type"] == "status"
        assert parsed["data"]["status"] == "running"
        assert parsed["data"]["message"] == "Processing..."

    def test_to_bytes_with_empty_message(self):
        """Test serialization with default empty message."""
        from modules.messages import StatusMessage

        msg = StatusMessage(status="done")
        result = msg.to_bytes()

        parsed = json.loads(result.decode())
        assert parsed["data"]["message"] == ""

    def test_to_bytes_with_dict_message(self):
        """Test serialization with a dict message."""
        from modules.messages import StatusMessage

        msg = StatusMessage(status="error", message={"code": 500, "reason": "Internal"})
        result = msg.to_bytes()

        parsed = json.loads(result.decode())
        assert parsed["data"]["message"]["code"] == 500


class TestModelMessage:
    """Test ModelMessage serialization."""

    def test_to_bytes(self):
        """Test basic serialization."""
        from modules.messages import ModelMessage

        msg = ModelMessage(data={"content": "Hello", "role": "assistant"})
        result = msg.to_bytes()

        parsed = json.loads(result.decode())
        assert parsed["type"] == "msg"
        assert parsed["data"]["content"] == "Hello"


class TestNoRefMessage:
    """Test NoRefMessage serialization."""

    def test_to_bytes(self):
        """Test basic serialization."""
        from modules.messages import NoRefMessage

        msg = NoRefMessage(data={"reason": "No references found"})
        result = msg.to_bytes()

        parsed = json.loads(result.decode())
        assert parsed["type"] == "noreference"
        assert parsed["data"]["reason"] == "No references found"

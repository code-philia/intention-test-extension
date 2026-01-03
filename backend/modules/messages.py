from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Union


def _to_bytes(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload).encode()


@dataclass
class StatusMessage:
    status: str
    message: Union[str, Dict[str, Any]] = ""

    def to_bytes(self) -> bytes:
        return _to_bytes(
            {
                "type": "status",
                "data": {
                    "status": self.status,
                    "message": self.message,
                },
            }
        )


@dataclass
class ModelMessage:
    data: Dict[str, Any]

    def to_bytes(self) -> bytes:
        return _to_bytes({"type": "msg", "data": self.data})


@dataclass
class NoRefMessage:
    data: Dict[str, Any]

    def to_bytes(self) -> bytes:
        return _to_bytes({"type": "noreference", "data": self.data})

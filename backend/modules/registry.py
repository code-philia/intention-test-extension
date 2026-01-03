from __future__ import annotations

import threading
from typing import Dict, Iterable, Optional

from .session import ModelQuerySession


class SessionRegistry:
    """线程安全的会话注册表。"""

    def __init__(self) -> None:
        self._sessions: Dict[str, ModelQuerySession] = {}
        self._lock = threading.Lock()

    def register(self, session: ModelQuerySession) -> None:
        with self._lock:
            self._sessions[session.session_id] = session

    def remove(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def get(self, session_id: str) -> Optional[ModelQuerySession]:
        with self._lock:
            return self._sessions.get(session_id)

    def list_active_ids(self) -> Iterable[str]:
        with self._lock:
            return tuple(self._sessions.keys())

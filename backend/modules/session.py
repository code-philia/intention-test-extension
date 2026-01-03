from __future__ import annotations

import logging
import threading
from typing import Any, Callable, Dict, List

from .exceptions import GenerationCancelled
from .messages import ModelMessage, NoRefMessage, StatusMessage

logger = logging.getLogger(__name__)

ResponseWriter = Callable[[bytes], None]
QueryExecutor = Callable[[Dict[str, Any], "ModelQuerySession"], None]


class ModelQuerySession:
    """封装单次生成流程的上下文与与客户端通信能力。"""

    required_fields = [
        "target_focal_method",
        "target_focal_file",
        "test_desc",
        "project_path",
        "focal_file_path",
    ]

    def __init__(
        self,
        session_id: str,
        raw_data: Dict[str, Any],
        writer: ResponseWriter,
        executor: QueryExecutor,
        junit_version: int,
    ) -> None:
        self.session_id = session_id
        self.raw_data = raw_data
        self._writer = writer
        self._executor = executor
        self.junit_version = junit_version

        self.messages: List[Dict[str, Any]] = []
        self.query_data = {field: self.raw_data[field] for field in self.required_fields}
        self._session_running = False
        self._cancel_event = threading.Event()

    def start_query(self) -> None:
        if self._session_running:
            logger.warning("Session %s already running", self.session_id)
            return
        self._session_running = True
        logger.info("Starting query session %s", self.session_id)
        try:
            self._executor(self.query_data, self)
        except GenerationCancelled:
            logger.info("Query session %s cancelled by user", self.session_id)
        finally:
            self._session_running = False

    def update_messages(self, messages: List[Dict[str, Any]]) -> None:
        self.messages = messages
        data_to_send = {"session_id": self.session_id, "messages": messages}
        self._safe_write(ModelMessage(data_to_send).to_bytes())

    def write_start_message(self) -> None:
        self._safe_write(StatusMessage("start", {"session_id": self.session_id}).to_bytes())

    def write_noref_message(self) -> None:
        payload = {"session_id": self.session_id, "junit_version": self.junit_version}
        self._safe_write(NoRefMessage(payload).to_bytes())

    def write_finish_message(self) -> None:
        self._safe_write(StatusMessage("finish", {"session_id": self.session_id}).to_bytes())

    def request_stop(self) -> None:
        self._cancel_event.set()

    def should_stop(self) -> bool:
        return self._cancel_event.is_set()

    def _safe_write(self, payload: bytes) -> None:
        try:
            self._writer(payload)
        except BrokenPipeError:
            logger.warning("Connection closed for session %s", self.session_id)
            self.request_stop()

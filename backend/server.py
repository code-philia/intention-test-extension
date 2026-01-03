from __future__ import annotations

import argparse
import json
import logging
import socketserver
import threading
from http.server import BaseHTTPRequestHandler
from typing import Any, Dict

try:
    from backend import main as generation_entry_module  # when run as package
except ImportError:
    import main as generation_entry_module  # when invoked from backend directory
from modules.registry import SessionRegistry
from modules.session import ModelQuerySession

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
)

DEFAULT_PORT = 8080
_global_junit_version = 4
_session_registry = SessionRegistry()


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True


class ResponseStream:
    """封装 Handler 的写操作，确保线程安全。"""

    def __init__(self, handler: BaseHTTPRequestHandler) -> None:
        self._handler = handler
        self._lock = threading.Lock()

    def __call__(self, data: bytes) -> None:
        with self._lock:
            self._handler.wfile.write(data + b"\n")
            self._handler.wfile.flush()


def run_generation(query_data: Dict[str, Any], session: ModelQuerySession) -> None:
    generation_entry_module.main(**query_data, query_session=session)


def build_session(payload: Dict[str, Any], handler: BaseHTTPRequestHandler) -> ModelQuerySession:
    session_id = payload["session_id"]
    response_stream = ResponseStream(handler)
    return ModelQuerySession(
        session_id=session_id,
        raw_data=payload["data"],
        writer=response_stream,
        executor=run_generation,
        junit_version=_global_junit_version,
    )


def validate_query_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if payload.get("type") != "query":
        raise ValueError("Unsupported request type")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("Query data must be a JSON object")
    missing = [field for field in ModelQuerySession.required_fields if field not in data]
    if missing:
        raise ValueError(f"Missing required fields: {', '.join(missing)}")
    return {"session_id": payload.get("session_id") or payload.get("id") or handler_uuid(), "data": data}


def handler_uuid() -> str:
    import uuid

    return uuid.uuid4().hex


class QueryHandler(BaseHTTPRequestHandler):
    server_version = "IntentionTestHTTP/1.0"

    def do_POST(self) -> None:  # noqa: N802
        if self.path == "/session":
            self._handle_session_request()
        elif self.path == "/session/stop":
            self._handle_stop_request()
        elif self.path == "/junitVersion":
            self._handle_junit_version()
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_session_request(self) -> None:
        try:
            payload = self._read_json_body()
            request_payload = validate_query_payload(payload)
            session = build_session(request_payload, self)
        except Exception as exc:  # broad catch to surface payload issues
            logger.error("Invalid session request: %s", exc, exc_info=True)
            self._end_with_error(400, "Bad Request", str(exc))
            return

        try:
            _session_registry.register(session)
            self._send_keep_alive_header()
            session.write_start_message()
            session.start_query()
            session.write_finish_message()
        except Exception as exc:
            logger.error("Error processing session: %s", exc, exc_info=True)
            self._end_with_error(500, "Internal Server Error", str(exc))
        finally:
            _session_registry.remove(session.session_id)
            self._end_session()

    def _handle_stop_request(self) -> None:
        try:
            payload = self._read_json_body()
            session_id = payload.get("session_id")
            if not session_id:
                raise ValueError("Missing session_id")
            session = _session_registry.get(session_id)
            if not session:
                self.send_response(404, "Session Not Found")
                self.end_headers()
                return
            session.request_stop()
            self.send_response(200, "Stopping")
            self.end_headers()
        except ValueError as exc:
            self._end_with_error(400, "Bad Request", str(exc))
        except Exception as exc:
            logger.error("Failed to stop session: %s", exc, exc_info=True)
            self._end_with_error(500, "Internal Server Error", str(exc))

    def _handle_junit_version(self) -> None:
        global _global_junit_version

        try:
            payload = self._read_json_body()
            version = int(payload["data"])
        except Exception as exc:
            self._end_with_error(400, "Bad Request", f"Invalid payload: {exc}")
            return

        _global_junit_version = version
        self.send_response(200, "Success")
        self.end_headers()

    def _send_keep_alive_header(self) -> None:
        self.send_response(200, "Success")
        self.send_header("Content-type", "application/json")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

    def _end_with_error(self, code: int, error_msg: str, _: str) -> None:
        self.send_response(code, error_msg)
        self.end_headers()
        self._end_session()

    def _end_session(self) -> None:
        self.close_connection = True

    def _read_json_body(self) -> Dict[str, Any]:
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")
        return json.loads(body) if body else {}


def start_http_server(port: int) -> None:
    logger.info("Starting HTTP server on port %s", port)
    httpd = ThreadedTCPServer(("", port), QueryHandler)
    actual_port = httpd.server_address[1]
    logger.info("HTTP server is listening on %s", actual_port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down HTTP server")
    finally:
        httpd.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Start the model server")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to start the server on")
    args = parser.parse_args()
    start_http_server(args.port)


if __name__ == "__main__":
    main()

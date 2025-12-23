import argparse
import atexit
import json
import logging
import queue
import sys
import threading
import time
import traceback
import uuid
from threading import Lock, RLock
from typing import Dict, List, Optional, Union

from flask import Flask, Response, jsonify, request, stream_with_context
from type import AbstractMessageSyncHandler
from core import run_test_generation_chat
import os
from tools.extension_api.collect_pairs.main import dump_collect_pairs
from tools.extension_api.generate_test_descs.main import generate_test_descriptions

app = Flask(__name__)

# a standard python logger
logger = logging.getLogger(__name__)
# basicConfig can only be called once
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
)

# Global dictionary to store active sessions with thread safety
active_sessions: Dict[str, "ExtensionQuerySession"] = {}
sessions_lock = RLock()  # Reentrant lock for session access

# Session cleanup tracking
_session_cleanup_thread = None
cleanup_interval = 300  # 5 minutes
session_timeout = 3600  # 1 hour


def cleanup_expired_sessions():
    """Cleanup expired sessions periodically."""
    while True:
        try:
            current_time = time.time()
            expired_sessions = []
            
            with sessions_lock:
                for session_id, session in list(active_sessions.items()):
                    # Check if session is expired
                    if (current_time - session.last_activity > session_timeout or
                        session.finished):
                        expired_sessions.append(session_id)
                
                # Remove expired sessions
                for session_id in expired_sessions:
                    if session_id in active_sessions:
                        session = active_sessions[session_id]
                        session.cleanup_session()
                        logger.info("Cleaned up expired session: %s", session_id)
            
            if expired_sessions:
                logger.info("Cleaned up %d expired sessions", len(expired_sessions))
                
        except (OSError, RuntimeError) as e:
            logger.error("Error in session cleanup: %s", e)
        
        time.sleep(cleanup_interval)


def start_cleanup_thread():
    """Start the session cleanup thread."""
    global _session_cleanup_thread
    if _session_cleanup_thread is None or not _session_cleanup_thread.is_alive():
        _session_cleanup_thread = threading.Thread(
            target=cleanup_expired_sessions, 
            daemon=True,
            name="SessionCleanup"
        )
        _session_cleanup_thread.start()
        logger.info("Started session cleanup thread")


def stop_cleanup_thread():
    """Stop the session cleanup thread gracefully."""
    # Cleanup thread is daemon, so it will stop when main thread stops
    logger.info("Session cleanup thread will stop with main process")


# Centralized error handling
class APIError(Exception):
    """Custom API error with status code."""
    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(self.message)


@app.errorhandler(APIError)
def handle_api_error(error):
    """Handle custom API errors."""
    logger.error("API Error: %s", error.message)
    return jsonify(error=error.message), error.status_code


@app.errorhandler(Exception)
def handle_unexpected_error(error):
    """Handle unexpected errors."""
    logger.error("Unexpected error: %s\n%s", error, traceback.format_exc())
    return jsonify(error="Internal server error"), 500


def validate_request_data(data: Optional[dict], required_fields: List[str]) -> None:
    """Validate request data has required fields."""
    if not data:
        raise APIError("Missing request body", 400)
    
    if not isinstance(data, dict):
        raise APIError("Request body must be a JSON object", 400)
    
    missing_fields = [field for field in required_fields if field not in data]
    if missing_fields:
        raise APIError(f"Missing required fields: {missing_fields}", 400)
    
    # Validate that required fields are not None or empty strings
    empty_fields = []
    for field in required_fields:
        value = data.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            empty_fields.append(field)
    
    if empty_fields:
        raise APIError(f"Required fields cannot be empty: {empty_fields}", 400)


class AppConfig:
    def __init__(self):
        self.junit_version = 4

    def get_junit_version(self):
        return self.junit_version

    def set_junit_version(self, version):
        self.junit_version = version


# Global app configuration instance
app_config = AppConfig()


class StatusMessage:
    def __init__(self, status: str, message: Union[str, dict] = ""):
        self.status = status
        self.message = message

    def response(self) -> bytes:
        return json.dumps(
            {"type": "status", "data": {"status": self.status, "message": self.message}}
        ).encode()


class ModelMessage:
    def __init__(self, data: dict):
        self.data = data

    def response(self) -> dict:
        return {"type": "msg", "data": self.data}


class NoRefMessage:
    def __init__(self, data: dict):
        self.data = data

    def response(self) -> bytes:
        return json.dumps({"type": "noreference", "data": self.data}).encode()


class ExtensionQuerySession(AbstractMessageSyncHandler):
    """Session persistent data with improved resource management."""

    required_fields = [
        "target_focal_method",
        "target_focal_file",
        "test_desc",
        "project_path",
        "focal_file_path",
    ]

    def __init__(self, session_id: str, raw_data: dict, flask_request):
        self.session_id = session_id
        self.raw_data = raw_data
        self.request = flask_request  # not used for writing responses anymore
        self.messages = []
        self.messages_dict = {}
        self.messages_lock = Lock()  # Protect messages list
        self.junit_version = app_config.get_junit_version()
        self.message_id_counter = 0  # Counter for unique message IDs
        self.created_at = time.time()  # Track session creation time
        self.last_activity = time.time()  # Track last activity for cleanup

        # Queue for receiving client responses
        self.client_responses = queue.Queue()
        self.awaiting_response = False
        self.response_timeout = 120  # 120 seconds timeout for client responses

        self.query_data = self.prepare_query_arguments()
        self.session_running = False
        self.finished = False  # Flag to indicate the session is finished

        # Register this session globally with thread safety
        with sessions_lock:
            active_sessions[self.session_id] = self

    def prepare_query_arguments(self):
        # Validate required fields
        missing_fields = [
            field for field in self.required_fields if field not in self.raw_data
        ]
        if missing_fields:
            raise ValueError(f"Missing required fields: {missing_fields}")

        # Validate field types and values
        query_data = {}
        for field in self.required_fields:
            value = self.raw_data[field]
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"Field '{field}' must be a non-empty string")
            query_data[field] = value.strip()

        return query_data

    def start_query(self):
        if not self.session_running:
            self.session_running = True
            logger.info("Starting query session %s", self.session_id)
            try:
                # Execute the main query
                run_test_generation_chat(**self.query_data, query_session=self)
                self.write_finish_message()
            except (ValueError, KeyError, TypeError) as e:
                logger.error("Error in session %s: %s\n%s", self.session_id, e, traceback.format_exc())
                self.write_error_message(str(e))
            finally:
                self.session_running = False
                self.finished = True  # Mark the session as finished
                # Clean up the session from active sessions with thread safety
                self.cleanup_session()

    def cleanup_session(self):
        """Clean up session resources and remove from active sessions."""
        with sessions_lock:
            if self.session_id in active_sessions:
                del active_sessions[self.session_id]
        
        # # Clear messages to free memory, keeping only the last few for debugging
        # with self.messages_lock:
        #     if len(self.messages) > 10:
        #         self.messages = self.messages[-5:]  # Keep last 5 messages
        
        logger.info("Session %s cleaned up", self.session_id)

    def update_messages(self, messages):
        """Sync all messages to the client with unique IDs and thread safety"""
        if messages is None:
            messages = []

        self.last_activity = time.time()  # Update activity timestamp

        msg_id_cnt = 0
        messages_copy = list(map(lambda msg: {**msg}, messages))
        for msg in messages_copy:
            msg_id_cnt += 1
            msg["id"] = f"{self.session_id}_msg_{msg_id_cnt}"
        data = {"session_id": self.session_id, "messages": messages_copy}
        
        with self.messages_lock:
            self.messages.append(ModelMessage(data).response())

    def write_start_message(self):
        self.last_activity = time.time()
        self.message_id_counter += 1
        data = {
            "status": "start",
            "session_id": self.session_id,
            "id": f"{self.session_id}_status_{self.message_id_counter}",
        }
        message = {"type": "status", "data": data}
        with self.messages_lock:
            self.messages.append(message)

    def write_noref_message(self):
        self.last_activity = time.time()
        self.message_id_counter += 1
        data = {
            "session_id": self.session_id,
            "junit_version": self.junit_version,
            "id": f"{self.session_id}_noref_{self.message_id_counter}",
        }
        message = {"type": "noreference", "data": data}
        with self.messages_lock:
            self.messages.append(message)

    def write_finish_message(self):
        self.last_activity = time.time()
        self.message_id_counter += 1
        data = {
            "status": "finish",
            "session_id": self.session_id,
            "id": f"{self.session_id}_finish_{self.message_id_counter}",
        }
        message = {"type": "status", "data": data}
        with self.messages_lock:
            self.messages.append(message)

    def write_error_message(self, error_msg: str):
        """Write an error message to the session."""
        self.last_activity = time.time()
        self.message_id_counter += 1
        data = {
            "status": "error",
            "session_id": self.session_id,
            "error": error_msg,
            "id": f"{self.session_id}_error_{self.message_id_counter}",
        }
        message = {"type": "status", "data": data}
        with self.messages_lock:
            self.messages.append(message)

    def request_client_response(
        self, prompt: str, response_type: str = "text", options: list[str] | None = None
    ) -> str | None:
        """
        Request a response from the client. This will send a message to the client
        asking for input and then wait for the client to respond.

        Args:
            prompt: The message/question to display to the client
            response_type: Type of response expected ("text", "choice", "confirm")
            options: List of options for choice-type responses

        Returns:
            The client's response or None if timeout/error
        """
        self.last_activity = time.time()
        request_id = f"{self.session_id}_{int(time.time())}"

        # Send request message to client
        self.message_id_counter += 1
        request_data = {
            "session_id": self.session_id,
            "request_id": request_id,
            "prompt": prompt,
            "response_type": response_type,
            "options": options or [],
            "id": f"{self.session_id}_request_{self.message_id_counter}",
        }

        request_message = {"type": "client_request", "data": request_data}

        with self.messages_lock:
            self.messages.append(request_message)
        
        self.awaiting_response = True

        logger.info("Session %s: Requesting client response - %s", self.session_id, prompt)

        # Wait for client response
        try:
            response = self.client_responses.get(timeout=self.response_timeout)
            logger.info("Session %s: Received client response -\n%s", self.session_id, response)
            self.last_activity = time.time()
            return response
        except queue.Empty:
            logger.warning("Session %s: Client response timeout after %ds", self.session_id, self.response_timeout)
            return None
        finally:
            self.awaiting_response = False

    def handle_client_response(self, response_data: dict) -> bool:
        """
        Handle a response received from the client.

        Args:
            response_data: Dictionary containing the client's response
        """
        if not self.awaiting_response:
            logger.warning("Session %s: Received unexpected client response", self.session_id)
            return False

        try:
            # Validate response data
            required_fields = ["request_id", "response"]
            if not all(field in response_data for field in required_fields):
                logger.error("Session %s: Invalid response data format", self.session_id)
                return False

            # Put response in the queue for the waiting thread
            self.client_responses.put(response_data["response"])
            logger.info("Session %s: Client response queued successfully", self.session_id)
            return True

        except (KeyError, TypeError, ValueError) as e:
            logger.error("Session %s: Error handling client response - %s", self.session_id, e)
            return False


# Generator function for streaming events with improved thread safety


def event_stream(session: ExtensionQuerySession):
    last_index = 0
    # Continue streaming until session is finished and all messages have been sent
    while not session.finished or (isinstance(session.messages, list) and last_index < len(session.messages)):
        with session.messages_lock:
            messages_to_send = []
            
            if isinstance(session.messages, list):
                current_message_count = len(session.messages)
                while last_index < current_message_count:
                    message = session.messages[last_index]
                    messages_to_send.append(message)
                    if not ("streaming" in message and message["streaming"] == True):
                        last_index += 1
                    else:
                        break  # Don't increment for streaming messages
            else:
                messages_to_send.append(session.messages)
        
        # Send messages outside the lock
        for message in messages_to_send:
            # print(f"data: {json.dumps(message)}\n\n")
            yield f"data: {json.dumps(message)}\n\n"
            
        time.sleep(0.1)


# Updated assign_to_session to work with Flask's request


def assign_to_session(query_text: str, flask_request) -> Optional[ExtensionQuerySession]:
    try:
        query_data = json.loads(query_text)
        if query_data["type"] != "query":
            raise ValueError('Request type must be "query"')

        # Generate secure session ID using UUID
        session_id = str(uuid.uuid4())
        new_session = ExtensionQuerySession(session_id, query_data["data"], flask_request)
        return new_session
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        logger.error("Error creating session: %s", e)
        return None


# Flask route for handling /session POST requests


@app.route("/session", methods=["POST"])
def session_route():
    # Validate request
    if not request.data:
        raise APIError("Empty request body", 400)

    query_text = request.get_data(as_text=True)
    if not query_text.strip():
        raise APIError("Empty query text", 400)

    # Parse and validate JSON
    try:
        query_data = json.loads(query_text)
    except json.JSONDecodeError as e:
        raise APIError(f"Invalid JSON: {e}", 400) from e

    if query_data.get("type") != "query":
        raise APIError("Request type must be 'query'", 400)

    if "data" not in query_data:
        raise APIError("Missing 'data' field in request", 400)

    query_session = assign_to_session(query_text, request)
    if query_session is None:
        raise APIError("Failed to create query session", 500)

    query_session.write_start_message()
    # Run the query in a separate thread so we can stream events concurrently
    threading.Thread(target=query_session.start_query, daemon=True).start()
    return Response(
        stream_with_context(event_stream(query_session)),
        mimetype="text/event-stream",
    )


# Flask route for handling /junitVersion POST requests


@app.route("/junitVersion", methods=["POST"])
def junit_version_route():
    data = request.get_json()
    validate_request_data(data, ["version"])

    version = data["version"]
    if not isinstance(version, int) or version not in [4, 5]:
        raise APIError("Version must be 4 or 5", 400)

    app_config.set_junit_version(version)
    logger.info("JUnit version set to %d", version)
    return jsonify(success=True, version=version)


# Flask route for handling client responses


@app.route("/response", methods=["POST"])
def client_response_route():
    """
    Handle responses from clients back to active sessions.
    Expected JSON format:
    {
        "session_id": "session_identifier",
        "request_id": "request_identifier", 
        "response": "client_response_data"
    }
    """
    data = request.get_json()
    validate_request_data(data, ["session_id", "request_id", "response"])

    session_id = data["session_id"]

    # Find the active session with thread safety
    with sessions_lock:
        session = active_sessions.get(session_id)

    if session is None:
        raise APIError(f"Session {session_id} not found or expired", 404)

    # Handle the response
    success = session.handle_client_response(data)

    if not success:
        raise APIError("Failed to process response", 500)

    return jsonify(success=True, message="Response received")


@app.route('/generate_data', methods=['POST'])
def generate_data():
    data = request.json
    project_path = data.get('project_path')
    use_jacoco = data.get('use_jacoco', False)
    test_suffix = data.get('test_suffix', 'Test')
    if not project_path:
        return jsonify({'error': 'project_path is required'}), 400
    
    project_name = os.path.basename(project_path)
    workspace_dir = project_path 
    
    # Paths
    intention_test_dir = os.path.join(workspace_dir, '.intention-test')
    collected_coverages_dir = os.path.join(intention_test_dir, 'collected_coverages')
    test_desc_dataset_dir = os.path.join(intention_test_dir, 'test_desc_dataset')
    
    # 1. Collect Pairs
    try:
        logger.info(f"Starting collect_pairs for {project_name} (use_jacoco={use_jacoco}, test_suffix={test_suffix})")
        dump_collect_pairs(
            project_path=project_path,
            test_suffix=test_suffix, 
            output_path=collected_coverages_dir,
            do_dynamic_analysis=use_jacoco
        )
    except Exception as e:
        logger.error(f"Error in collect_pairs: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
        
    # 2. Generate Test Descriptions
    coverage_file = os.path.join(collected_coverages_dir, f'{project_name}.json')
    try:
        logger.info(f"Starting generate_test_descriptions for {project_name}")
        generate_test_descriptions(
            project_name=project_name,
            coverage_path=coverage_file,
            llm_name='gpt-4o', 
            output_path=test_desc_dataset_dir
        )
    except Exception as e:
        logger.error(f"Error in generate_test_descriptions: {e}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500
        
    return jsonify({'status': 'success'})


# Removed the old start_http_server function


def cleanup_all_sessions():
    """Clean up all active sessions on shutdown."""
    logger.info("Cleaning up all active sessions...")
    with sessions_lock:
        for session_id, session in list(active_sessions.items()):
            try:
                session.cleanup_session()
            except (RuntimeError, AttributeError) as e:
                logger.error("Error cleaning up session %s: %s", session_id, e)
        active_sessions.clear()
    logger.info("Session cleanup completed")


def graceful_shutdown():
    """Perform graceful shutdown cleanup."""
    logger.info("Performing graceful shutdown...")
    cleanup_all_sessions()
    stop_cleanup_thread()
    logger.info("Graceful shutdown completed")


# Register cleanup function to run on exit
atexit.register(graceful_shutdown)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Start the model server")
    parser.add_argument(
        "--port", type=int, default=8080, help="Port to start the server on"
    )
    args = parser.parse_args()
    
    # Start the cleanup thread
    start_cleanup_thread()
    
    logger.info("Starting Flask server on port %d", args.port)
    try:
        app.run(host="127.0.0.1", port=args.port)
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    finally:
        graceful_shutdown()

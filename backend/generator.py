import re
import os

from agents import TestGenAgent, TestRefineAgent
from type import AbstractMessageSyncHandler
from configs import Configs
from test_case_runner import TestCaseRunner


class IntentionTester:
    def __init__(
        self, configs: Configs, max_round=3, skip_deepseek_think: bool = False
    ):
        self.configs = configs
        self.max_round = max_round
        self.max_line_error_msg = 20

        self.test_gen_agent = TestGenAgent(
            configs.llm_name,
            configs.project_name,
            configs.project_url,
            n_responses=1,
            skip_deepseek_think=skip_deepseek_think,
        )
        self.test_refine_agent = TestRefineAgent(
            configs.llm_name,
            configs.project_name,
            configs.project_url,
            n_responses=1,
            skip_deepseek_think=skip_deepseek_think,
        )
        self.test_runner = TestCaseRunner(configs, configs.test_case_run_log_dir)
        self.generation_with_refine_log = []  # [(test_status, prompt, test_case)]
        self.messages = []  # Store messages for each step
        self.extension_query_session = None
        self.stream_callback = self.update_messages_to_remote

    def connect_to_request_session(self, query_session: AbstractMessageSyncHandler):
        self.extension_query_session = query_session

    def append_message(self, message, update_message = True):
        """
        Append a message to the internal message list.
        Optionally update the remote client via query session.
        """
        self.messages.append(message)
        return self.update_messages_to_remote(self.messages) if update_message else None
    
    def extend_messages(self, messages, update_message = True):
        """
        Extend the internal message list with multiple messages.
        Optionally update the remote client via query session.
        """
        self.messages.extend(messages)
        return self.update_messages_to_remote(self.messages) if update_message else None

    def update_messages_to_remote(self, messages = None):
        """
        Update messages to the remote client via query session.
        Note: The underlying update_messages method performs a full sync of all messages
        to ensure client state consistency, rather than incremental updates.
        """
        if self.extension_query_session:
            self.extension_query_session.update_messages(messages)

    def update_extended_messages_to_remote(self, messages: list[str] = []):
        """
        Update messages to the remote client via query session.
        Note: The underlying update_messages method performs a full sync of all messages
        to ensure client state consistency, rather than incremental updates.
        """
        if self.extension_query_session:
            self.extension_query_session.update_messages(self.messages + messages)

    def request_referable_test_case_from_client(self, target_focal_method):
        """
        Request a referable test case from the client when query session is available.
        This allows users to provide an existing test case as a reference for generation.
        Optimized to batch messages and reduce the number of sync calls.
        """
        if not self.extension_query_session:
            return None

        # Send initial message to inform the user about the request
        self.append_message(
            {
                "role": "assistant",
                "content": f"🔍 Looking for reference test cases for method:\n```\n{target_focal_method}\n```",
            }
        )

        # Request the client to provide a referable test case
        referable_test_case = self.extension_query_session.request_client_response(
            f"Would you like to provide a reference test case for method '{target_focal_method}'? This can help improve the quality of the generated test.",
            response_type="text",
        )

        # Handle empty or missing test case input
        if not referable_test_case or not referable_test_case.strip():
            self.append_message(
                {
                    "role": "assistant",
                    "content": "ℹ️ No reference test case provided. Proceeding with standard generation.",
                }
            )
            return None

        # Handle valid test case input
        if self.is_valid_test_case(referable_test_case):
            self.append_message(
                {
                    "role": "assistant",
                    "content": f"✅ Reference test case received and will be used to guide test generation: \n```\n{referable_test_case.strip()}\n```",
                }
            )
            return referable_test_case.strip()

        # Handle potential file path input
        return self._load_test_case_from_file(referable_test_case)

    def is_valid_test_case(self, content):
        """
        Simple validation to check if the content looks like a Java test case.
        """
        if not content or not content.strip():
            return False

        content = content.strip()

        # Check for basic test case indicators
        test_indicators = [
            "@Test",
            "public void test",
            "public class",
            "import org.junit",
            "junit.framework",
            "Assert.",
            "assertEquals",
            "assertTrue",
            "assertFalse",
        ]

        # Check if at least one test indicator is present
        return any(indicator in content for indicator in test_indicators)

    def _load_test_case_from_file(self, file_path):
        """
        Attempt to load and validate a test case from a file path.
        """
        if self.extension_query_session is None:
            return None
        
        answer = self.extension_query_session.request_client_response(
            "The provided input doesn't appear to be a test case. Is it a file path to a test case file?",
            response_type="confirm",
        )

        if not answer or answer.lower() not in ["yes", "y", "true", "1"]:
            self.append_message(
                {
                    "role": "assistant",
                    "content": "⚠️ Invalid test case format. Proceeding without reference.",
                }
            )
            return None

        try:
            if not os.path.exists(file_path.strip()):
                self.messages.append(
                    {
                        "role": "assistant",
                        "content": "⚠️ File not found. Proceeding without reference test case.",
                    }
                )
                self.extension_query_session.update_messages(self.messages)
                return None

            with open(file_path.strip(), "r", encoding="utf-8") as f:
                file_content = f.read()

            if not self.is_valid_test_case(file_content):
                self.messages.append(
                    {
                        "role": "assistant",
                        "content": "⚠️ The file doesn't appear to contain a valid test case. Proceeding without reference.",
                    }
                )
                self.extension_query_session.update_messages(self.messages)
                return None

            self.messages.append(
                {
                    "role": "assistant",
                    "content": f"✅ Test case loaded from file: {file_path.strip()}",
                }
            )
            self.extension_query_session.update_messages(self.messages)
            return file_content

        except Exception as e:
            self.messages.append(
                {
                    "role": "assistant",
                    "content": f"⚠️ Error reading file: {str(e)}. Proceeding without reference.",
                }
            )
            self.extension_query_session.update_messages(self.messages)
            return None

    def generate_test_case_with_refine(
        self,
        target_focal_method: str,
        target_context: str,
        target_test_case_desc: str,
        target_test_case_path: str,
        referable_test_case: str | None,
        facts: list[str],
        junit_version: str,
        prohibit_fact: bool = False,
    ):
        self.generation_with_refine_log = []
        self.messages = []  # Reset messages for new generation

        # Request referable test case from client if query session is available
        if self.extension_query_session and not referable_test_case:
            referable_test_case = self.request_referable_test_case_from_client(
                target_focal_method
            )

        target_test_class_name = target_test_case_path.split("/")[-1].replace(
            ".java", ""
        )
        gen_test_case, prompt = self.generate_test_case(
            target_focal_method,
            target_context,
            target_test_class_name,
            target_test_case_desc,
            referable_test_case,
            facts,
            junit_version,
            prohibit_fact,
        )
        error_msg, test_status = self.run_test_case(
            gen_test_case, target_test_case_path
        )
        self.generation_with_refine_log.append((test_status, prompt, gen_test_case))

        if test_status == "success":
            self.finish_generation()
            return gen_test_case, test_status, self.messages

        for iteration in range(self.max_round):
            gen_test_case, prompt = self.refine(
                gen_test_case,
                error_msg,
                target_focal_method,
                target_context,
                target_test_case_desc,
                target_test_case_path,
                facts,
                prohibit_fact,
            )
            error_msg, test_status = self.run_test_case(
                gen_test_case, target_test_case_path
            )
            self.generation_with_refine_log.append((test_status, prompt, gen_test_case))

            if test_status == "success":
                self.finish_generation()
                break

        self.finish_generation()
        return gen_test_case, test_status, self.messages

    def finish_generation(self):
        finish_messages = self.test_gen_agent.generate_finish()
        self.extend_messages(finish_messages)

    def generate_test_case(
        self,
        target_focal_method,
        target_context,
        target_test_class_name,
        target_test_case_desc,
        referable_test_case,
        facts,
        junit_version,
        prohibit_fact,
    ):
        gen_test_case, prompt, messages = self.test_gen_agent.generate_test_case(
            target_focal_method,
            target_context,
            target_test_class_name,
            target_test_case_desc,
            referable_test_case,
            facts,
            junit_version,
            prohibit_fact,
            stream_callback=self.update_extended_messages_to_remote,
        )
        self.messages.extend(messages)
        return gen_test_case, prompt

    def refine(
        self,
        gen_test_case,
        error_msg,
        target_focal_method,
        target_context,
        target_test_case_desc,
        target_test_case_path,
        facts: list,
        prohibit_fact,
    ):
        error_msg_lines = error_msg.split("\n")
        error_msg_cut = "\n".join(error_msg_lines[: self.max_line_error_msg])

        refined_tc, prompt, messages = self.test_refine_agent.refine(
            gen_test_case,
            error_msg_cut,
            target_focal_method,
            target_context,
            target_test_case_desc,
            facts,
            prohibit_fact,
            stream_callback=self.update_extended_messages_to_remote
        )
        self.messages.extend(messages)
        self.update_messages_to_remote(self.messages)
        return refined_tc, prompt

    def run_test_case(self, test_case, test_case_path):
        def _extract_error_msg(log):
            error_msg = []
            stop_flag = False
            for each_line in log.split("\n"):
                if each_line.strip().startswith("[INFO]"):
                    continue
                if each_line.strip().startswith("[main]"):
                    continue
                if each_line.strip().startswith("[WARNING]"):
                    continue

                if each_line.strip().startswith("[ERROR] Tests run:"):
                    if stop_flag:
                        break
                    else:
                        stop_flag = True

                if each_line.strip().startswith("[ERROR] To see the full stack trace"):
                    break

                error_msg.append(each_line)

            error_msg = "\n".join(error_msg)
            return error_msg

        compile_log, test_log, compile_success, execute_success = (
            self.test_runner.compile_and_execute_test_case(test_case, test_case_path)
        )

        if not compile_success:
            error_msg = _extract_error_msg(compile_log)
            test_status = "fail_compile"
        elif not execute_success:
            error_msg = _extract_error_msg(test_log)
            test_status = "fail_execute"

            test_run_info = re.search(
                r"Tests run: (\d+), Failures: (\d+), Errors: (\d+), Skipped: (\d+)",
                test_log,
            )
            if test_run_info is not None:
                test_run_info = test_run_info.groups()

                if int(test_run_info[0]) > 1:
                    print(
                        f"[INFO] Multiple test methods in a single test case: {test_case_path}"
                    )

                success = (
                    int(test_run_info[0])
                    - int(test_run_info[1])
                    - int(test_run_info[2])
                    - int(test_run_info[3])
                )
                if success > 0:
                    test_status = "success"
                    error_msg = ""
                elif int(test_run_info[1]) > 0:
                    test_status = "fail_pass"
                else:
                    test_status = "fail_execute"

        else:
            error_msg = ""
            test_status = "success"

        return error_msg, test_status

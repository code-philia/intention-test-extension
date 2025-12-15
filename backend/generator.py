import re
import logging
logger = logging.getLogger(__name__)

from agents import TestGenAgent, TestRefineAgent
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
        self.query_session = None
        self.stream_callback = self.update_messages_to_remote
        # self.stream_callback = None

    def connect_to_request_session(self, query_session):
        self.query_session = query_session

    def update_messages_to_remote(self, messages):
        """
        Update messages to the remote client via query session.
        Note: The underlying update_messages method performs a full sync of all messages
        to ensure client state consistency, rather than incremental updates.
        """
        if self.query_session:
            self.query_session.update_messages(messages)

    def request_referable_test_case_from_client(self, target_focal_method):
        """
        Request a referable test case from the client when query session is available.
        This allows users to provide an existing test case as a reference for generation.
        Optimized to batch messages and reduce the number of sync calls.
        """
        if not self.query_session:
            return None

        # Collect messages to send in batches to minimize sync calls
        pending_messages = []

        # Send initial message to inform the user about the request
        pending_messages.append(
            {
                "role": "assistant",
                "content": f"🔍 Looking for reference test cases for method:\n```\n{target_focal_method}\n```",
            }
        )

        # Send the batch of messages (in this case, just one)
        self.query_session.update_messages(pending_messages)
        pending_messages.clear()

        # Request the client to provide a referable test case
        referable_test_case = self.query_session.request_client_response(
            f"Would you like to provide a reference test case for method '{target_focal_method}'? This can help improve the quality of the generated test.",
            response_type="text",
        )

        if referable_test_case and referable_test_case.strip():
            # Validate that the response looks like a test case
            if self.is_valid_test_case(referable_test_case):
                pending_messages.append(
                    {
                        "role": "assistant",
                        "content": f"✅ Reference test case received and will be used to guide test generation: \n```\n{referable_test_case.strip()}\n```",
                    }
                )
                # Send final message and return result
                self.query_session.update_messages(pending_messages)
                return referable_test_case.strip()
            else:
                # If it doesn't look like a test case, ask for confirmation or file path
                is_file_path = self.query_session.request_client_response(
                    "The provided input doesn't appear to be a test case. Is it a file path to a test case file?",
                    response_type="confirm",
                )

                if is_file_path and is_file_path.lower() in ["yes", "y", "true", "1"]:
                    # Try to read the file content
                    try:
                        import os

                        if os.path.exists(referable_test_case.strip()):
                            with open(
                                referable_test_case.strip(), "r", encoding="utf-8"
                            ) as f:
                                file_content = f.read()

                            if self.is_valid_test_case(file_content):
                                pending_messages.append(
                                    {
                                        "role": "assistant",
                                        "content": f"✅ Test case loaded from file: {referable_test_case.strip()}",
                                    }
                                )
                                # Send final message and return result
                                self.query_session.update_messages(pending_messages)
                                return file_content
                            else:
                                pending_messages.append(
                                    {
                                        "role": "assistant",
                                        "content": "⚠️ The file doesn't appear to contain a valid test case. Proceeding without reference.",
                                    }
                                )
                        else:
                            pending_messages.append(
                                {
                                    "role": "assistant",
                                    "content": "⚠️ File not found. Proceeding without reference test case.",
                                }
                            )
                    except Exception as e:
                        pending_messages.append(
                            {
                                "role": "assistant",
                                "content": f"⚠️ Error reading file: {str(e)}. Proceeding without reference.",
                            }
                        )
                else:
                    pending_messages.append(
                        {
                            "role": "assistant",
                            "content": "⚠️ Invalid test case format. Proceeding without reference.",
                        }
                    )
        else:
            pending_messages.append(
                {
                    "role": "assistant",
                    "content": "ℹ️ No reference test case provided. Proceeding with standard generation.",
                }
            )

        # Send any remaining messages in a final batch
        if pending_messages:
            self.query_session.update_messages(pending_messages)

        return None

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

    def extract_method_name(self, test_case_code):
        """
        Extracts a descriptive name for the test case, preferably ClassName::methodName(args).
        """
        class_name = None
        method_signature = None
        
        # Try to find class name
        class_match = re.search(r'class\s+(\w+)', test_case_code)
        if class_match:
            class_name = class_match.group(1)
            
        # Helper to clean and format signature
        def format_sig(name, args):
            args = args.strip()
            # Collapse whitespace and newlines into single space
            args = re.sub(r'\s+', ' ', args)
            return f"{name}({args})"

        # Try to find method name
        # Priority 1: @Test or @ParameterizedTest annotated methods
        # We look for @Test/@ParameterizedTest followed by optional whitespace/newlines/modifiers, then void, then method name
        # Using [\s\S]*? to skip annotations, modifiers (public, private, etc.)
        test_method_match = re.search(r'@(?:Test|ParameterizedTest)[\s\S]*?\bvoid\s+(\w+)\s*\(([^)]*)\)', test_case_code)
        
        if test_method_match:
            method_name = test_method_match.group(1)
            method_args = test_method_match.group(2)
            method_signature = format_sig(method_name, method_args)
        else:
            # Fallback to any void method that starts with 'test'
            test_prefix_match = re.search(r'\bvoid\s+(test\w+)\s*\(([^)]*)\)', test_case_code, re.IGNORECASE)
            if test_prefix_match:
                method_name = test_prefix_match.group(1)
                method_args = test_prefix_match.group(2)
                method_signature = format_sig(method_name, method_args)
            else:
                # Fallback to any void method
                method_match = re.search(r'\bvoid\s+(\w+)\s*\(([^)]*)\)', test_case_code)
                if method_match:
                    method_name = method_match.group(1)
                    method_args = method_match.group(2)
                    method_signature = format_sig(method_name, method_args)

        if class_name and method_signature:
            return f"{class_name}::{method_signature}"
        elif method_signature:
            return method_signature
        else:
            logger.warning("Unable to extract method or class name from test case code.")
            return "Unknown Test Case"

    def generate_test_case_with_refine(
        self,
        target_focal_method,
        target_context,
        target_test_case_desc,
        target_test_case_path,
        referable_test_cases,
        facts,
        junit_version,
        prohibit_fact: bool = False,
    ):
        self.generation_with_refine_log = []
        
        referable_test_case = None

        if self.query_session:
            if referable_test_cases and len(referable_test_cases) > 0:
                # generate options and ask
                options = []
                for i, tc in enumerate(referable_test_cases):
                    name = self.extract_method_name(tc)
                    options.append(f"{i+1}. {name}")
                options.append("Provide my own reference")
                
                selection = self.query_session.request_client_response(
                    "Select a reference test case:",
                    response_type="choice",
                    options=options
                )
                
                if selection == "Provide my own reference":
                    referable_test_case = self.request_referable_test_case_from_client(target_focal_method)
                elif selection in options:
                    index = options.index(selection)
                    referable_test_case = referable_test_cases[index]
            else:
                # no references found, ask user directly
                referable_test_case = self.request_referable_test_case_from_client(target_focal_method)
        else:
            logger.warning("No query session available when selecting referable test case!")
            if referable_test_cases and len(referable_test_cases) > 0:
                referable_test_case = referable_test_cases[0]

        target_test_class_name = target_test_case_path.split("/")[-1].replace(
            ".java", ""
        )
        gen_test_case, prompt, messages = self.generate_test_case(
            target_focal_method,
            target_context,
            target_test_class_name,
            target_test_case_desc,
            referable_test_case,
            facts,
            junit_version,
            prohibit_fact,
        )
        self.update_messages_to_remote(messages)
        error_msg, test_status = self.run_test_case(
            gen_test_case, target_test_case_path
        )
        self.generation_with_refine_log.append((test_status, prompt, gen_test_case))

        if test_status == "success":
            messages = self.finish_generate()
            return gen_test_case, test_status, messages

        for round in range(self.max_round):
            gen_test_case, prompt, refine_messages = self.refine(
                gen_test_case,
                error_msg,
                target_focal_method,
                target_context,
                target_test_case_desc,
                target_test_case_path,
                facts,
                prohibit_fact,
            )
            messages += refine_messages
            self.update_messages_to_remote(messages)
            error_msg, test_status = self.run_test_case(
                gen_test_case, target_test_case_path
            )
            self.generation_with_refine_log.append((test_status, prompt, gen_test_case))

            if test_status == "success":
                messages = self.finish_generate()
                self.update_messages_to_remote(messages)
                break

        messages = self.finish_generate()
        self.update_messages_to_remote(messages)
        return gen_test_case, test_status, messages

    def finish_generate(self):
        messages = self.test_gen_agent.generate_finish()
        return messages

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
        if self.stream_callback:
            gen_test_case, prompt, messages = self.test_gen_agent.generate_test_case(
                target_focal_method,
                target_context,
                target_test_class_name,
                target_test_case_desc,
                referable_test_case,
                facts,
                junit_version,
                prohibit_fact,
                stream_callback=self.stream_callback,
            )
        else:
            gen_test_case, prompt, messages = self.test_gen_agent.generate_test_case(
                target_focal_method,
                target_context,
                target_test_class_name,
                target_test_case_desc,
                referable_test_case,
                facts,
                junit_version,
                prohibit_fact,
            )
        return gen_test_case, prompt, messages

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
        )
        return refined_tc, prompt, messages

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

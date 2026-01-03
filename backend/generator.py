import json
import os
import re

from pyexpat.errors import messages

from modules.session import ModelQuerySession
from modules.exceptions import GenerationCancelled
from configs import Configs
from agents import TestGenAgent, TestRefineAgent
from test_case_runner import TestCaseRunner


class IntentionTester:
    def __init__(self, configs: Configs, max_round=3, skip_deepseek_think: bool = False):
        self.configs = configs
        self.max_round = max_round
        self.max_line_error_msg = 20

        self.test_gen_agent = TestGenAgent(configs.llm_name, configs.project_name, configs.project_url, n_responses=1, skip_deepseek_think=skip_deepseek_think)
        self.test_refine_agent = TestRefineAgent(configs.llm_name, configs.project_name, configs.project_url, n_responses=1, skip_deepseek_think=skip_deepseek_think)
        self.test_runner = TestCaseRunner(configs, configs.test_case_run_log_dir)
        self.generation_with_refine_log = []  # [(test_status, prompt, test_case)]
        self.query_session: ModelQuerySession | None = None
        self._cancel_check = lambda: False
        self._message_prefix: list[dict] = []
        self._apply_cancel_hook()

    def connect_to_request_session(self, query_session: ModelQuerySession):
        self.query_session = query_session
        self._apply_cancel_hook()

    def set_message_prefix(self, prefix: list[dict] | None) -> None:
        self._message_prefix = list(prefix or [])

    def update_messages_to_remote(self, messages):
        # TODO notify front-end for messages, maybe trasmit full (instead of transmit update only)?
        if self.query_session:
            self.query_session.update_messages(self._message_prefix + messages)

    def _ensure_not_cancelled(self):
        if self.query_session and self.query_session.should_stop():
            raise GenerationCancelled()

    def generate_test_case_with_refine(self, 
                                       target_focal_method, target_context, target_test_case_desc, target_test_case_path,
                                       referable_test_case, facts, junit_version,
                                       prohibit_fact: bool = False, query_session: ModelQuerySession | None = None):
        self.generation_with_refine_log = []
        self.query_session = query_session
        self._apply_cancel_hook()
        self._ensure_not_cancelled()

        target_test_class_name = target_test_case_path.split('/')[-1].replace('.java', '')
        gen_test_case, prompt, messages = self.generate_test_case(target_focal_method, target_context, target_test_class_name, target_test_case_desc, referable_test_case, facts, junit_version, prohibit_fact)
        self.update_messages_to_remote(messages)
        self._ensure_not_cancelled()
        error_msg, test_status = self.run_test_case(gen_test_case, target_test_case_path)
        self.generation_with_refine_log.append((test_status, prompt, gen_test_case))

        if test_status == 'success':
            messages = self.finish_generate()
            return gen_test_case, test_status, messages

        for round in range(self.max_round):
            self._ensure_not_cancelled()
            gen_test_case, prompt, refine_messages = self.refine(gen_test_case, error_msg, target_focal_method, target_context, target_test_case_desc, target_test_case_path, facts, prohibit_fact)
            messages += refine_messages
            self.update_messages_to_remote(messages)
            self._ensure_not_cancelled()
            error_msg, test_status = self.run_test_case(gen_test_case, target_test_case_path)
            self.generation_with_refine_log.append((test_status, prompt, gen_test_case))

            if test_status == 'success':
                messages = self.finish_generate()
                self.update_messages_to_remote(messages)
                break

        return gen_test_case, test_status, messages

    def finish_generate(self):
        self._ensure_not_cancelled()
        messages = self.test_gen_agent.generate_finish()
        return messages

    def generate_test_case(self, target_focal_method, target_context, target_test_class_name, target_test_case_desc, referable_test_case, facts, junit_version, prohibit_fact):
        self._ensure_not_cancelled()
        gen_test_case, prompt, messages = self.test_gen_agent.generate_test_case(target_focal_method, target_context, target_test_class_name, target_test_case_desc, referable_test_case, facts, junit_version, prohibit_fact)
        return gen_test_case, prompt, messages
    
    def refine(self, gen_test_case, error_msg, target_focal_method, target_context, target_test_case_desc, target_test_case_path, facts: list, prohibit_fact):
        self._ensure_not_cancelled()
        error_msg_lines = error_msg.split('\n')
        error_msg_cut = '\n'.join(error_msg_lines[:self.max_line_error_msg])

        refined_tc, prompt, messages = self.test_refine_agent.refine(gen_test_case, error_msg_cut, target_focal_method, target_context, target_test_case_desc, facts, prohibit_fact)
        return refined_tc, prompt, messages

    def run_test_case(self, test_case, test_case_path):
        self._ensure_not_cancelled()
        def _extract_error_msg(log):
            error_msg = []
            stop_flag = False
            for each_line in log.split('\n'):
                if each_line.strip().startswith('[INFO]'):
                    continue
                if each_line.strip().startswith('[main]'):
                    continue
                if each_line.strip().startswith('[WARNING]'):
                    continue
                
                if each_line.strip().startswith('[ERROR] Tests run:'):
                    if stop_flag:
                        break
                    else:
                        stop_flag = True
                
                if each_line.strip().startswith('[ERROR] To see the full stack trace'):
                    break

                error_msg.append(each_line)

            error_msg = '\n'.join(error_msg)
            return error_msg

        compile_log, test_log, compile_success, execute_success = self.test_runner.compile_and_execute_test_case(test_case, test_case_path) 

        if not compile_success:
            error_msg = _extract_error_msg(compile_log)
            test_status = 'fail_compile'
        elif not execute_success:
            error_msg = _extract_error_msg(test_log)
            test_status = 'fail_execute'

            test_run_info = re.search(r'Tests run: (\d+), Failures: (\d+), Errors: (\d+), Skipped: (\d+)', test_log)
            if test_run_info is not None:
                test_run_info = test_run_info.groups()

                if int(test_run_info[0]) > 1:
                    print(f'[INFO] Multiple test methods in a single test case: {test_case_path}')

                success = int(test_run_info[0]) - int(test_run_info[1]) - int(test_run_info[2]) - int(test_run_info[3])
                if success > 0:
                    test_status = 'success'
                    error_msg = ""
                elif int(test_run_info[1]) > 0:
                    test_status = 'fail_pass'
                else:
                    test_status = 'fail_execute'

        else:
            error_msg = ""
            test_status = 'success'

        return error_msg, test_status

    def _apply_cancel_hook(self):
        def cancel_check() -> bool:
            return bool(self.query_session and self.query_session.should_stop())

        self._cancel_check = cancel_check
        self.test_gen_agent.set_cancel_check(cancel_check)
        self.test_refine_agent.set_cancel_check(cancel_check)

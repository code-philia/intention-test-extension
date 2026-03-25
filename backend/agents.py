import os
import re
import time
import logging

from openai import OpenAI
from dataclasses import dataclass, field

from exp_feature import create_unlearning_prompt
from chat_text_utils import construct_test_description_prompt, create_general_tester_prompt, create_test_description_polish_prompt, create_test_generation_instruction, create_test_refinement_instruction, extract_code_from_response

from user_config import global_config

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self, llm_name: str, system_prompt = None):
        self.model_name = llm_name
        self.system_prompt = system_prompt

        self.client = OpenAI(
            api_key=global_config['openai']['apikey'],
            base_url=global_config['openai']['url']
            )
        self.temp = 0.3  # for GPT-4o. For DeepSeek-R1-Distill-Qwen-7B, the temperature is fixed to 0.5
        self.top_p = 0.1
        self.seed = 1203
        self.max_completion_tokens = 5120

    def get_response(self, messages, n=1, skip_deepseek_think: bool=False, stream_callback=None) -> list[str] | str:
        if self.model_name in ('gpt-4o', 'gpt-3.5-turbo'):
            if self.system_prompt:
                messages = [{'role': 'system', 'content': self.system_prompt}] + messages
            response = self._get_gpt_response(messages, n=n, stream_callback=stream_callback)
        elif self.model_name in ('deepseek-7B', 'deepseek-32B', 'deepseek-ai/DeepSeek-R1-Distill-Qwen-32B'):
            if self.system_prompt:
                messages[0]['content'] = self.system_prompt + '\n\n\n' + messages[0]['content']
            response = self._get_deepseek_qwen_response(messages, n=n, skip_deepseek_think=skip_deepseek_think)
        elif self.model_name == 'o1-mini-2024-09-12':
            if self.system_prompt:
                messages = [{'role': 'user', 'content': self.system_prompt}] + messages
            while True:
                response = self._get_gpt_o1_mini_response(messages, n=n)
                if len(response) > 0:
                    break
                print('\nsleeping for 10 seconds... Then retrying...\n\n')
                time.sleep(10)
        else:
            raise ValueError(f"Unknown LLM name: {self.model_name}")
        return response

    def _get_gpt_response(self, messages, n=1, stream_callback=None) -> list[str]:
        response = []
        max_tries = n + 2
        n_tries = 0
        
        # For streaming with callback, we can only process one response at a time
        if stream_callback and n > 1:
            logger.warning("Streaming with callback only supports n=1, adjusting n to 1")
            n = 1
            
        while len(response) < n:
            s_time = time.time()
            try:
                logger.debug(f'Sending request to {self.model_name} with {len(messages)} messages')
                if stream_callback:
                    stream = self.client.chat.completions.create(
                        model=self.model_name,
                        messages=messages,
                        temperature=self.temp,
                        top_p=self.top_p,
                        seed=self.seed,
                        stream=True,
                        max_tokens=self.max_completion_tokens,
                        n=1,  # streaming only supports n=1
                    )
                    
                    # Process streaming response
                    collected_content = ""
                    # Create the assistant message that will be updated
                    assistant_message = {"role": "assistant", "content": ""}
                    
                    stream_callback({'type': 'start_streaming'})

                    for chunk in stream:
                        if chunk.choices and len(chunk.choices) > 0 and chunk.choices[0].delta.content is not None:
                            delta_content = chunk.choices[0].delta.content
                            collected_content += delta_content
                            # Call the update callback with the updated messages
                            stream_callback({'type': 'content_delta', 'delta': delta_content})
                            logger.debug(f'Streaming update: {collected_content[-50:]}')

                    stream_callback({'type': 'finish_streaming', 'total': collected_content})
                    
                    assistant_message["content"] = collected_content
                    each_response = StreamResponse(choices=[StreamChoice(message=StreamMessage(content=collected_content))])
                else:
                    each_response = self.client.chat.completions.create(
                        model="openai/o4-mini",
                        messages=messages,
                        temperature=1.0,
                        top_p=1.0,
                        stream=False,
                        max_completion_tokens=self.max_completion_tokens,
                        n=1,
                    )
            except Exception as e:
                logger.error(f'Error calling {self.model_name} API: {e}')
                n_tries += 1
                if n_tries > max_tries:
                    logger.error(f'Failed to generate after {max_tries} attempts')
                    # Create an error response object
                    
                    each_response = ErrorResponse()
                    break
                continue
            
            logger.info(f'Generation completed in {time.time()-s_time:.2f} seconds')

            # response.append(each_response.choices[0].message.content)
            response.extend([choice.message.content for choice in each_response.choices])

        if n == 1:
            response = response[0]

        return response

    def _get_gpt_o1_mini_response(self, messages, n=1):
        response = []
        max_tries = n + 2
        n_tries = 0
        while len(response) < n:
            s_time = time.time()
            try:
                print(f'\n\n{messages}\n\n')
                each_response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    temperature=self.temp,
                    seed=self.seed,
                    stream=False,
                    max_tokens=self.max_completion_tokens,
                    n=n,
                )
            except Exception as e:
                print(f'\nError: {e}\n\n')
                if "无可用渠道" in str(e):
                    time.sleep(2)
                    continue

                if "potentially violating our usage policy" in str(e) or 'bad response status' in str(e):  # triggered by o1-mini
                    content = messages[1]['content']
                    print(f'Content: {content}\n\n')
                    part_1, part_2 = content.split('(with some details omitted):\n```\n')
                    part_2 = part_2.split('\n```')
                    part_2_1, part_2_2 = part_2[0], '\n```'.join(part_2[1:])

                    part_2_1_lines = part_2_1.split('\n')
                    if len(part_2_1_lines) > 10:
                        part_2_1_lines = part_2_1_lines[:len(part_2_1_lines)-10]
                    else:
                        raise ValueError(f"Failed to reduce the length of the input: {part_2_1} to address:\n{e}") from e
                    
                    part_2_1 = '\n'.join(part_2_1_lines)
                    messages[1]['content'] = part_1 + '(with some details omitted):\n```\n' + part_2_1 + '\n```' + part_2_2

                    continue

                if "quota is not enough" in str(e):
                    time.sleep(10)
                    continue
                
                n_tries += 1
                if n_tries > max_tries:
                    response.append('```\n\n[ERROR] Failed to generate\n\n```')
                    break
                continue

            print(f'\nTime consuming for one generation: {time.time()-s_time:.2f} seconds\n\n\n')

            response.append(each_response.choices[0].message.content)

        if n == 1:
            response = response[0]

        return response

    def _get_deepseek_qwen_response(self, messages, n=1, skip_deepseek_think: bool=False):
        response = []
        max_tries = 2
        n_tries = 0

        if skip_deepseek_think:
            messages[0]['content'] += '\n\n<think>\nSkip Thinking\n</think>\n\n'

        while len(response) < n:
            s_time = time.time()
            try:
                each_response_raw = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=messages,
                    temperature=0.6,
                    seed=self.seed,
                    stream=False,
                    max_completion_tokens=self.max_completion_tokens,
                    n=1
                )
                logger.info(f'Time consuming for one generation: {time.time()-s_time:.2f} seconds\n\n')
                logger.info(f'Response:\n{each_response_raw.choices[0].message.content}\n\n\n')
                
                each_response = self.remove_thinking(each_response_raw.choices[0].message.content)
                if each_response is None:
                    messages[0]['content'] += '\n\n<think>\n\n</think>\n\n'
                    logger.info('Seems a too long thinking. Enforcing the model to skip thinking.\n')
                    logger.info('Messages (after modified):' + str(messages) + '\n\n\n')
                    logger.info('Response:\n' + (each_response_raw.choices[0].message.content or '') + '\n\n\n')
                    n_tries += 1

                    if n_tries <= max_tries:
                        continue
                    each_response = '```\nFailed to generate\n```'

                response.append(each_response)

            except Exception as e:
                # the input is too long
                if 'Please reduce the length' in str(e):
                    context_part = messages[0]['content'].split('(with some details omitted):')[1]
                    context_part = re.findall(r'```(.+?)```', context_part, re.DOTALL)[0]
                    assert len(context_part) > 0
                    # get the idx of the line whose length is the largest among all lines. can use argmax?
                    context_lines = context_part.split('\n')
                    context_lengths = [len(line.split()) for line in context_lines]
                    max_len_idx = context_lengths.index(max(context_lengths))
                    # remove the line whose length is the largest
                    context_lines.pop(max_len_idx)
                    reduced_context_part = '\n'.join(context_lines)
                    messages[0]['content'] = messages[0]['content'].replace(context_part, reduced_context_part)

                    continue

        if n == 1:
            response = response[0]

        return response

    def remove_thinking(self, response):
        if '</think>' not in response:
            return None
        answer = response.split('</think>')[-1].strip()
        return answer

    def add_line_numbers(self, content):
        lines = content.split('\n')
        for i in range(len(lines)):
            lines[i] = f'{i+1}:{lines[i]}'
        return '\n'.join(lines)
    
    def remove_line_numbers(self, content):
        lines = content.split('\n')
        removed_lines = []
        for line in lines:
            removed_lines.append(self.remove_single_line_number(line))
        return '\n'.join(removed_lines)
    
    def remove_single_line_number(self, line):
        marker_index = line.find(':')
        return line[marker_index+1:]

class Agent:
    def __init__(self, llm_name: str, project_name: str, n_responses: int=1, skip_deepseek_think: bool=False, enable_experimental_unlearning: bool=False):
        self.n_responses = n_responses
        self.skip_deepseek_think = skip_deepseek_think
        self.gen_prefix = '```package '
        self.gen_suffix = '```'

        self.system_prompt = ''
        if enable_experimental_unlearning:
            self.system_prompt += create_unlearning_prompt(project_name)
        self.system_prompt += create_general_tester_prompt()
        self.system_prompt = self.system_prompt.strip()

        self.llm_client = LLMClient(llm_name, self.system_prompt)

class TestDescAgent(Agent):
    def generate_test_desc(self, test_case, focal_method):
        prompt = construct_test_description_prompt(test_case, focal_method)
        messages = [{'role': 'user', 'content': prompt}]

        is_success = False
        response = ''
        for _ in range(3):
            response = self.llm_client.get_response(messages)
            is_success = self.check_generation(response)
            if is_success:
                break
        if is_success:
            response = self.polish_test_desc(response)
        else:
            print(f'WARNING: The generated test description does not follow the expected format:\n{response}\n\n')

        return response

    def polish_test_desc(self, test_desc):
        prompt = create_test_description_polish_prompt(test_desc)
        messages = [{'role': 'user', 'content': prompt}]

        new_test_desc = test_desc
        for _ in range(2):
            response = self.llm_client.get_response(messages)
            is_success = self.check_generation(response)
            if is_success:
                new_test_desc = response
                break
        return new_test_desc

    def check_generation(self, desc):
        n_obj = desc.count('# Objective')
        n_pre = desc.count('# Preconditions')
        n_exp = desc.count('# Expected Results')
        if n_obj == 1 and n_pre == 1 and n_exp == 1:
            return True
        else:
            return False

class TestGenAgent(Agent):
    def generate_test_case(self, target_focal_method, target_context, target_test_class_name, target_test_desc, referable_test: str, facts: list[str], junit_version: str, forbid_using_facts: bool=False, stream_callback=None, append_chat_message_callback=None):
        prompt = create_test_generation_instruction(target_focal_method, target_context, target_test_class_name, target_test_desc, referable_test, facts, junit_version, forbid_using_facts)
        messages = [{'role': 'user', 'content': prompt}]
        if append_chat_message_callback is not None:
            append_chat_message_callback(messages[-1])
            
        raw_response = self.llm_client.get_response(messages, n=self.n_responses, skip_deepseek_think=self.skip_deepseek_think, stream_callback=stream_callback)
        if isinstance(raw_response, list):
            raw_response = raw_response[0]

        messages.append({"role": "assistant", "content": raw_response})
        if append_chat_message_callback is not None:
            append_chat_message_callback(messages[-1])
        
        generated_tc = extract_code_from_response(raw_response)
        return generated_tc, prompt, messages

    def generate_finish(self, previous_messages):
        prompt = "The Target Test Case has been successfully compiled and executed.\nPlease check whether its test method executes the Target Focal Method and aligns with the intention.\n- If so, output only \"FINISH GENERATION\",\n- Otherwise, please output only the analysis."
        messages = [*previous_messages, {'role': 'user', 'content': prompt}]

        raw_response = self.llm_client.get_response(messages, n=self.n_responses, skip_deepseek_think=self.skip_deepseek_think)
        if isinstance(raw_response, list):
            raw_response = raw_response[0]
        messages.append({"role": "assistant", "content": raw_response})

        return messages

class TestRefineAgent(Agent):
    def refine(self, gen_test_case, error_msg, target_focal_method, target_context, target_test_case_desc, facts: list, forbid_using_facts: bool=False, stream_callback=None, append_chat_message_callback=None):
        prompt = create_test_refinement_instruction(gen_test_case, error_msg, target_focal_method, target_context, target_test_case_desc, facts, forbid_using_facts)
        messages = [{'role': 'user', 'content': prompt}]
        if append_chat_message_callback is not None:
            append_chat_message_callback(messages[-1])

        raw_response = self.llm_client.get_response(messages, n=3, skip_deepseek_think=self.skip_deepseek_think, stream_callback=None)
        # if isinstance(raw_response, list):
        #     raw_response = raw_response[0]

        generated_tc = list(map(extract_code_from_response, raw_response))

        messages.append({"role": "assistant", "content": raw_response[0]})
        return generated_tc, prompt, messages

@dataclass
class StreamMessage:
    content: str

@dataclass
class StreamChoice:
    message: StreamMessage

@dataclass
class StreamResponse:
    choices: list[StreamChoice]

@dataclass
class ErrorMessage:
    content: str = '```\n\n[ERROR] Failed to generate\n\n```'

@dataclass
class ErrorChoice:
    message: ErrorMessage = field(default_factory=ErrorMessage)

@dataclass
class ErrorResponse:
    choices: list[ErrorChoice] = field(default_factory=lambda: [ErrorChoice()])

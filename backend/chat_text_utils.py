import re


# Pre-defined prompts


def construct_test_description_prompt(test_case, focal_method):
    instruction = f"""# Test Case\n```\n{test_case}\n```\n\n# Focal Method\n```\n{focal_method}\n```\n\n# Objective\n// Identifies and briefly describes the special focus or objective of #Test Case#. \n\n# Preconditions\n// Describes the required state of the test environment and test data and any special constraints pertaining to the execution of #Test Case#. Also, specifies each action required to bring the test item into a state where the expected result can be compared to the actual results. The level of detail provided by the descriptions should be tailored to fit the knowledge of the test executors.\n\n# Expected Results\n// Specifies the expected outputs and behavior required of the test item in response to the inputs that are given to the test item when it is in its precondition state. Provides the expected values (with tolerances where appropriate) for each required output.\n\n# Instruction\nPlease generate the #Objective#, #Preconditions#, and #Expected Results# of #Test Case#.\nEnsure that the output follows the expected format:\n```\n# Objective\n...\n\n# Preconditions\n1. ...\n2. ...\n...\n\n# Expected Results\n1. ...\n2. ...\n...\n```\n\n# Requirements\n1. The length of #Objective# must be less than fifty words.\n2. The total length of #Preconditions# and #Expected Results# must be less than two hundred words.\n3. The program elements in #Objective#, #Preconditions#, and #Expected Results# must be enclosed by a pair of backticks, such as `ClassA` and `methodInov()`.\n4. Ensure the #Objective#, #Preconditions#, and #Expected Results# are written in a natural, human-like manner. MUST avoid containing many program elements; instead, use clear and natural language."""

    return instruction


def create_test_description_polish_prompt(test_desc: str):
    return f"""# Test Case Description\n```\n{test_desc}\n```\n\n# Instruction\nRewrite the #Test Case Description# to make it more natural and human-like by translating the program elements (enclosed by `) to natural language description.\nFor example:\n1. Split the camel words and then transform them from program elements to natural language descriptions (such as `IpAddress` -> ip address).\n2. Using natural language to describe invocation (such as `Obj.getPrefix(Param)` -> get the prefix of Param, and `program.version=0.1` -> version of program is 0.1).\n\nAdditionally, ensure that the output follows the expected format:\n```\n# Objective\n...\n\n# Preconditions\n1. ...\n2. ...\n...\n\n# Expected Results\n1. ...\n2. ...\n...\n```\n\n# Requirements\n1. The length of #Objective# must be less than fifty words.\n2. The total length of #Preconditions# and #Expected Results# must be less than two hundred words."""


def create_general_tester_prompt():
    return '''You are an expert software quality assurance agent specialized in the automated generation of comprehensive, robust, and maintainable test suites based on provided code, logic, or functional requirements. Your primary objective is to systematically identify all successful execution paths, boundary conditions, and potential failure states, outputting structured test cases that specify precise inputs, clear assertions, and any necessary environmental setup using the `Arrange-Act-Assert` pattern. You must prioritize high code coverage and logical rigor, ensuring that for every input, the generated assertions verify that the output adheres to specified constraints and invariant properties while maximizing the detection of edge-case anomalies. Your responses should be formatted for immediate integration into industry-standard testing frameworks, maintaining clear documentation for each test's purpose and the specific logic it validates.\n\n'''


def create_test_generation_instruction(target_focal_method, target_context, target_test_class_name, target_test_desc, referable_test: str, facts: list, junit_version: str, forbid_using_facts: bool = False):
    instruction = f"""# Target Focal Method\n```\n{target_focal_method}\n```\n\n# Target Focal Method Context\nThe Target Focal Method belongs to the following class (with some details omitted):\n```\n{target_context}\n```\n\n# Target Test Case\n// A JUnit {junit_version} test case to be generated, whose class name is {target_test_class_name}.\n\n# Target Test Case Description\n```\n{target_test_desc}\n```\n\n"""

    if referable_test:
        instruction += f"""# Referable Test Case\n```\n{referable_test}\n```\n\n"""

    if facts:
        facts_str = '\n\n'.join(
            [f'## Fact {i+1}:\n{each}' for i, each in enumerate(facts)])
        if forbid_using_facts:
            facts_str = facts_str.replace('## Fact ', '## API ')
            instruction += f"""# Prohibited APIs\nMUST NOT include the following APIs in the generated #Target Test Case#\n```\n{facts_str}\n```\n\n"""
        else:
            instruction += f"""# Relevant Project Information\n```\n{facts_str}\n```\n\n"""

    instruction += """# Instruction\nPlease generate ONE #Target Test Case# for #Target Focal Method# by strictly following #Target Test Case Description#"""

    if referable_test or (facts and not forbid_using_facts):
        instruction += """ and referring to """

    if referable_test:
        instruction += """#Referable Test Case#"""

    if facts:
        instruction = instruction + " and " if referable_test else instruction
        if forbid_using_facts:
            instruction += """#Prohibited APIs#.\nNOTE: #Prohibited APIs# contains the APIs that MUST NOT be included in your generated #Target Test Case#.\n\n"""
        else:
            instruction += """#Relevant Project Information#.\nNOTE: #Relevant Project Information# contains key facts about the project. These facts MUST be FULLY reflected in your generated #Target Test Case#.\n\n"""

    else:
        instruction += ".\n\n"

    instruction += f"""# Output Requirements\nYour final output must contain only ONE test method annotated `@Test` and strictly adhere to the following format:\n1: Begin with the exact prefix: "```package".\n2: End with the exact suffix: "```".\nEnsure that no additional text appears before the prefix or after the suffix."""

    return instruction


def create_test_refinement_instruction(gen_test_case, error_msg, target_focal_method, target_context, target_test_desc, facts: list, forbid_using_facts: bool = False):
    instruction = f"""# Target Focal Method\n```\n{target_focal_method}\n```\n\n# Target Focal Method Context\nThe Target Focal Method belongs to the following class (with some details omitted):\n```\n{target_context}\n```\n\n# Target Test Case Description\n```\n{target_test_desc}\n```\n\n"""

    if facts:
        facts_str = '\n\n'.join(
            [f'## Fact {i+1}:\n{each}' for i, each in enumerate(facts)])
        if forbid_using_facts:
            facts_str = facts_str.replace('## Fact ', '## API ')
            instruction += f"""# Prohibited APIs\nMUST NOT include the following APIs in the generated #Target Test Case#\n```\n{facts_str}\n```\n\n"""
        else:
            instruction += f"""# Relevant Project Information\n```\n{facts_str}\n```\n\n"""

    instruction += f"""# Generated Target Test Case\n```\n{gen_test_case}\n```\n\n# Error Message\nWhen compiling and executing #Generated Target Test Case#, encounter the following errors:\n```\n{error_msg}\n```\n\n"""

    instruction += """# Instruction\nPlease modify #Generated Target Test Case# to resolve the errors shown in #Error Message#. """

    if facts:
        if forbid_using_facts:
            instruction += """NOTE: #Prohibited APIs# contains the APIs that MUST NOT be included in your generated #Target Test Case#.\n\n"""
        else:
            instruction += """#Relevant Project Information# provides some key facts in the project that MUST be considered to resolve the errors.\n\n"""
    else:
        instruction += "\n\n"

    instruction += """# Output Requirements\nYour final output must strictly adhere to the following format:\n1: Begin with the exact prefix: "```package".\n2: End with the exact suffix: "```".\nEnsure that no additional text appears before the prefix or after the suffix."""

    return instruction


# Text processing


def extract_code_from_response(response: str):
    code = re.findall(r'```java(.*)```', response, re.DOTALL)
    if len(code) == 0:
        code = re.findall(r'```(.*)```', response, re.DOTALL)
        if len(code) == 0:
            print(
                f"[Warning] The response does not contain any code: {response}")
            return " "  # TODO: refine this process

    if len(code) > 1:
        print(
            f'WARNING: The response contains multiple code blocks:\n{response}\n\n')

    code = code[0].strip()
    return code

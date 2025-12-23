import json
import sys
import os
import re
from collections import namedtuple
import argparse
from tqdm import tqdm
from pathlib import Path
import logging
logger = logging.getLogger(__name__)

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../../..')))
from agents import TestDescAgent
from user_config import global_config

# ========== DATA STRUCTURES ==========

# for coverage, we only need 2 fields here
CoveragePair = namedtuple(
    "CoveragePair",
    [
        "focal_method",
        "test_case",
        "test_case_name" # kept for debug
    ],
)

# ========== UTILS ==========

def remove_import_statements(java_code: str):
    lines = java_code.split('\n')
    new_lines = []
    for line in lines:
        if line.startswith('import ') or line.startswith('package '):
            continue
        
        new_lines.append(line)

    return '\n'.join(new_lines)

def add_newline_char(string):
    if not string.endswith('\n'):
        string += '\n'
    return string

# simplified method for test description generation
def load_coverage_data_jacoco(project_name: str, path: str):
    coverage_data = []
    with open(path, 'r') as f:
        data = json.load(f)
    for each_focal_file_path, coverages in data.items():
        for each_fm_name, tc_cov_pairs in coverages.items():
            for each_pair in tc_cov_pairs:
                tc_name, tc, cov, context, focal_file_skeleton = each_pair

                # check data, will be removed after standardising the format of dataset
                tc = [add_newline_char(each_line) for each_line in tc]
                cov = [add_newline_char(each_line) for each_line in cov]

                if '::::' in tc_name:
                    tc_name = tc_name.split('::::')[1]
                    tc_name = tc_name.split('(')[0]

                fm = ''.join(cov).replace('<COVER>', '')
                
                is_extend_clss = False
                test_case_class_name = None
                for each_line in tc:
                    tc_class_name = re.findall(r'public class (\w+)\s*{', each_line)
                    if len(tc_class_name) == 1:
                        test_case_class_name = tc_class_name[0]
                        break

                    tc_class_name = re.findall(r'public class (\w+) extends \w+\s*{', each_line)
                    if len(tc_class_name) == 1:
                        test_case_class_name = tc_class_name[0]
                        is_extend_clss = True
                        break
                    
                    tc_class_name = re.findall(r'class (\w+)\s*{', each_line)
                    if len(tc_class_name) == 1:
                        test_case_class_name = tc_class_name[0]
                        break

                    tc_class_name = re.findall(r'public class (\$\w+)\s*{', each_line)  # project lambda
                    if len(tc_class_name) == 1:
                        test_case_class_name = tc_class_name[0]
                        break
                
                # NOTE: for blade, we skip the test cases that extend other classes
                if project_name == 'blade' and is_extend_clss:
                    continue
                
                if test_case_class_name is None:
                    raise ValueError(f'Test case class name is not found.\nTest case:\n{tc}\n')

                # with open(f"{self.configs.project_dir_no_test_file}/{each_focal_file_path}", 'r') as f:
                #     focal_file = f.read()
                # focal_file_skeleton = skeletonize_java_code(focal_file)
                # if len(focal_file_skeleton) == 0:
                #     raise ValueError(f'Focal file skeleton is empty.\nFocal file:\n{each_focal_file_path}\n')

                coverage_pair = CoveragePair(
                    focal_method=fm, 
                    test_case=''.join(tc), 
                    test_case_name=tc_name
                )
                coverage_data.append(coverage_pair)
    return coverage_data

# ========== MAIN FUNCTION ==========

def generate_test_descriptions(project_name: str, coverage_path: str, llm_name: str, output_path: str):
    coverage_data = load_coverage_data_jacoco(project_name, coverage_path)

    os.environ['OPEN_AI_KEY'] = global_config['openai']['apikey']
    os.environ['OPENAI_BASE_URL'] = global_config['openai']['url']

    test_desc_agent = TestDescAgent(llm_name)

    save_path = Path(output_path) / f'{project_name}.json'

    test_desc_dataset = []
    for target_pair_idx, each_target_pair in tqdm(enumerate(coverage_data), total=len(coverage_data), ncols=80, desc='Generating test descriptions'):
        tar_fm = each_target_pair.focal_method
        tar_tc = each_target_pair.test_case
        tar_tc_no_import_stat = remove_import_statements(tar_tc)

        test_desc = test_desc_agent.generate_test_desc(tar_tc_no_import_stat.strip(), tar_fm)

        data = {
            'coverage_idx': target_pair_idx,
            'target_test_case': tar_tc,
            'target_focal_method': tar_fm,
            'test_desc': test_desc
        }

        test_desc_dataset.append(data)

        if not os.path.exists(os.path.dirname(save_path)):
            os.makedirs(os.path.dirname(save_path))

        with open(save_path, 'w') as f:
            json.dump(test_desc_dataset, f, indent=4)
            

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Generate test case descriptions.')
    parser.add_argument('--project_name', type=str, help='Name of the project.')
    parser.add_argument('--coverage_path', type=str, help='Path to the coverage data JSON file.')
    parser.add_argument('--llm_name', type=str, default='gpt-4o', help='Name of the LLM used for generation.')
    parser.add_argument('--output_path', type=str, help='Path to save the generated test descriptions.')
    args = parser.parse_args()

    logger.debug(f'Running test description generation for project {args.project_name}')
    generate_test_descriptions(args.project_name, args.coverage_path, args.llm_name, args.output_path)
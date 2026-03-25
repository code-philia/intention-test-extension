import os
import json
import re
import shutil
from tqdm import tqdm
from bs4 import BeautifulSoup
import subprocess
import asyncio
import threading
import logging
logger = logging.getLogger(__name__)

# Not provided setting JAVA_HOME for Maven at runtime yet, to be implemented
# JAVA_ENVS = {
#     'JAVA_HOME': ''
# }
# env_vars = os.environ.copy()
# env_vars.update(JAVA_ENVS)


def run_maven_command(
    mvn_args: list[str],
    cwd_path: str,
    encoding: str = 'utf-8',
) -> tuple[str, int]:
    mvn_exe = shutil.which('mvn.cmd') or shutil.which('mvn')
    if not mvn_exe:
        raise FileNotFoundError('Maven not found in PATH. Install Maven or add it to PATH.')

    result = subprocess.run(
        [mvn_exe, *mvn_args],
        cwd=cwd_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=False,
        check=False,
        text=False,
    )

    stdout_text = result.stdout.decode(encoding, errors='replace')
    stderr_text = result.stderr.decode(encoding, errors='replace')
    log = f'{stdout_text}\n\n{stderr_text}'
    return log, result.returncode


class Buffer:
    def __init__(self):
        self.stdout = ''
        self.stderr = ''

def stream_output(pipe, buffer, out_type):
    for line in iter(pipe.readline, ''):
        print(line, end='')
        if out_type == 'stdout':
            buffer.stdout += line
        elif out_type == 'stderr':
            buffer.stderr += line
    pipe.close()

class TestCaseRunner():
    def __init__(self, configs, test_case_run_log_dir):
        self.configs = configs
        self.test_case_run_log_dir = test_case_run_log_dir
        self.cur_no_ref_log_name = None
        self.cur_human_ref_log_name = None
        self.cur_rag_ref_log_name = None

        self.focal_file_coverage = dict()  # e.g., {'Base64_1_no_ref': cov_no_ref, 'Base64_1_with_rag_ref': cov_with_rag_ref}

    def run_with_std_out(self, *args, **kwargs):
        return asyncio.run(self.__run_with_std_out(*args, **kwargs))
    
    async def __run_with_std_out(self, *args, **kwargs):
        process = subprocess.Popen(*args, **kwargs)

        buffer = Buffer()

        # Create threads for stdout and stderr
        stdout_thread = threading.Thread(target=stream_output, args=(process.stdout, buffer, 'stdout'))
        stderr_thread = threading.Thread(target=stream_output, args=(process.stderr, buffer, 'stderr'))

        # Start the threads
        stdout_thread.start()
        stderr_thread.start()

        # Wait for both threads to finish
        stdout_thread.join()
        stderr_thread.join()
        process.wait()

        return buffer
    
    def run_with_err_out(self, *args, **kwargs):
        process = subprocess.run(*args, **kwargs, check=False)
        if process.returncode != 0:
            def get_str(byte_or_str):
                return byte_or_str.decode('utf-8') if type(byte_or_str) == bytes else byte_or_str
            stderr_str = get_str(process.stderr)
            stdout_str = get_str(process.stdout)
            # TODO write stderr and stdout to sparated logging files (named with hash, providing a link), not to the CLI
            logger.error(f'Error running "{args}". The outputs are: \nstderr:\n{stderr_str}stdout:\n{stdout_str}')
        return process

    def run_all_test_cases(self, test_cases, is_ref):
        test_case_with_log_coverage = []
        # run the generated test cases
        for each_test_case in tqdm(test_cases, ncols=80, desc='Running test cases'):
            focal_file_path = each_test_case['focal_path']

            generation_relative_path = each_test_case['test_case_path']
            tc_path = f"{self.configs.project_with_test_workspace}/{generation_relative_path}"
            tc = each_test_case['generated_test_case']
            fm_name_param = each_test_case['focal_method_name'].split('::::')[1]

            log_path, focal_file_coverage, fm_cov_statistic_by_jacoco = self.run_test_case_and_get_coverage(tc, tc_path, focal_file_path, fm_name_param, is_ref=is_ref)
            each_test_case[f'log_path_{is_ref}'] = log_path
            each_test_case['coverage_focal_file'] = focal_file_coverage  # used for analyze_coverage_with_target_coverage()
            each_test_case['coverage_focal_method'] = fm_cov_statistic_by_jacoco  # used for analyze_coverage_with_target_focal_method()

            test_case_with_log_coverage.append(each_test_case)
        return test_case_with_log_coverage

    def save_log_coverage(self, log_coverage, save_path):
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        with open(save_path, 'w', encoding='utf8') as f:
            json.dump(log_coverage, f, indent=4)
            logger.debug(f'Saved the generated test cases log and coverage to {save_path}')

    def run_test_case(self, test_case_path, focal_file_path, is_ref):
        assert is_ref in ('no_ref', 'human_ref', 'rag_ref')
        test_case_relative_path = self.get_test_case_relative_path(test_case_path)

        focal_method_name = focal_file_path.split('/')[-1].split('.')[0]

        suffix = is_ref
        index = 1
        log_file_path = f'{self.test_case_run_log_dir}/{focal_method_name}_{index}_{suffix}.log'
        while os.path.exists(log_file_path):
            index += 1
            log_file_path = f'{self.test_case_run_log_dir}/{focal_method_name}_{index}_{suffix}.log'
        setattr(self, f'cur_{is_ref}_ref_log_name', f'{focal_method_name}_{index}_{suffix}')

        cwd_path = test_case_path.split('/src/test/')[0]
        cmd = f'mvn clean verify -Dtest={test_case_relative_path} -Dcheckstyle.skip=true'

        logger.debug(f'Running test case: {cmd}')
        os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
        with open(log_file_path, 'w', encoding='utf8') as log_f:
            subprocess.run(cmd, cwd=cwd_path, stdout=log_f, stderr=log_f, shell=True, universal_newlines=True)
        return log_file_path

    def run_test_case_and_get_coverage(self, test_case, test_case_path, focal_file_path, focal_method_name_parameter, is_ref):
        logger.debug(f'Running the test case with = {is_ref} = reference...')
        # remove the folder of test cases
        tc_rel_path = test_case_path.split('/src/test/')[1]
        tc_base_dir = test_case_path.replace(tc_rel_path, '')
        os.makedirs(os.path.dirname(test_case_path), exist_ok=True)
        with open(test_case_path, 'w', encoding='utf8') as f:
            f.write(test_case)

        tc_run_log_path = self.run_test_case(test_case_path, focal_file_path, is_ref)

        focal_file_coverage, fm_cov_statistic_by_jacoco = self.get_focal_file_coverage(focal_file_path, test_case_path, focal_method_name_parameter)  # used for analyze_coverage_with_target_coverage()
        focal_file_coverage = ''.join(focal_file_coverage) if focal_file_coverage is not None else None

        os.remove(test_case_path)

        return tc_run_log_path, focal_file_coverage, fm_cov_statistic_by_jacoco

    def get_coverage_jacoco(self, test_case_path, focal_file_path, focal_method_name_parameter):

        focal_file_coverage, fm_cov_statistic_by_jacoco = self.get_focal_file_coverage(focal_file_path, test_case_path, focal_method_name_parameter)  # used for analyze_coverage_with_target_coverage()
        focal_file_coverage = ''.join(focal_file_coverage) if focal_file_coverage is not None else None

        return focal_file_coverage, fm_cov_statistic_by_jacoco

    def compile_and_execute_test_case(self, test_case, test_case_path):
        compile_success, execute_success = False, False
        compile_log, test_log = '', ''

        tc_rel_path = test_case_path.split('/src/test/')[1]
        tc_base_dir = test_case_path.replace(tc_rel_path, '')
        os.makedirs(os.path.dirname(test_case_path), exist_ok=True)
        with open(test_case_path, 'w', encoding='utf8') as f:
            f.write(test_case)

        test_case_relative_path = self.get_test_case_relative_path(test_case_path)

        cwd_path = test_case_path.split('/src/test/')[0]
        compile_log, _ = run_maven_command(
            ['clean', f'-Dtest={test_case_relative_path}', 'test-compile', '-Dcheckstyle.skip=true'],
            cwd_path,
        )

        if "BUILD SUCCESS" in compile_log:
            compile_success = True

            test_log, _ = run_maven_command(
                ['clean', 'verify', f'-Dtest={test_case_relative_path}', '-Dcheckstyle.skip=true'],
                cwd_path,
            )

            if "BUILD SUCCESS" in test_log:
                execute_success = True

        return compile_log, test_log, compile_success, execute_success

    def get_test_case_relative_path(self, test_case_path):
        test_case_relative_path = test_case_path.split('/src/test/java/')[1]
        test_case_relative_path = test_case_relative_path.split('/')[1:]
        test_case_relative_path = '/'.join(test_case_relative_path)
        test_case_relative_path = test_case_relative_path.replace('.java', '')
        test_case_relative_path = test_case_relative_path.replace('/', '.')
        return test_case_relative_path

    def get_focal_file_coverage(self, focal_file_path, test_case_path, focal_method_name_parameter):
        # base_path = f'{self.configs.project_dir}/{self.configs.project_name}'
        base_path = test_case_path.split('/src/test/java/')[0]
        org_name = test_case_path.split('/src/test/java/')[1].split('/')[0]
        test_suffix = 'Test'
        test_case_relative_path = self.get_test_case_relative_path(test_case_path)

        # jacoco java.html report contains java code lines with tags.
        jacoco_java_html_report_path = self.get_jacoco_java_html_report_path(base_path, test_case_relative_path, org_name, test_suffix)

        if not os.path.exists(jacoco_java_html_report_path):
            logger.warning(f'[WARNING] Jacoco report not found: {jacoco_java_html_report_path}')
            return None, None

        # will be used for analyze_coverage_with_target_coverage(). will be used to count the target coverage's coverage
        cov_lines, uncov_lines = self.get_lines_coverage(jacoco_java_html_report_path)
        with open(f'{self.configs.project_dir}/{focal_file_path}', 'r', encoding='utf8') as f:
            focal_file = f.readlines()
        for line in cov_lines:
            if focal_file[line - 1].strip() != '}':
                focal_file[line - 1] = "<COVER>" + focal_file[line - 1]

        # will be used for analyze_coverage_with_target_focal_method(). directly use the focal method's coverage counted by jacoco
        jacoco_html_report_path = jacoco_java_html_report_path.replace('.java.html', '.html')

        # TODO: optimize this. here, in lambda, target_coverage_idx=171, focal method name is 'Index.Z::::get(com.jnape.palatable.lambda.adt.hlist.HList.HCons<Target, ?>)'. will throw "/evosuite_pp/rag_tester/data/raw_data/repos_removing_test/lambda/target/site/jacoco/com.jnape.palatable.lambda.adt.hlist/Index.html" not such file.
        if not os.path.exists(jacoco_html_report_path):
            logger.warning(f'[WARNING] Jacoco report not found: {jacoco_html_report_path}. But Jacoco java.html report is found: {jacoco_java_html_report_path}')
            return None, None
        #

        fm_cov_statistic_by_jacoco = self.get_focal_method_coverage_statistic_by_jacoco(focal_method_name_parameter, jacoco_html_report_path)

        return focal_file, fm_cov_statistic_by_jacoco

    # copy from /bernard/dataset_construction/human_written_tests/v2/utils.py
    def get_jacoco_java_html_report_path(self, base_path, test_class_name, org_name, test_suffix):
        # get jacoco report
        # append_path = "spark/" if '.' not in test_class_name else "spark." + '.'.join(test_class_name.split(".")[:-1]) + '/'
        append_path = org_name + "/" if '.' not in test_class_name else org_name + "." + '.'.join(test_class_name.split(".")[:-1]) + '/'
        suff_len = len(test_suffix)
        html_name = test_class_name.split(".")[-1][:suff_len * -1] + ".java.html" # changes from -4 to -5 depending on whether it's Test or Tests
        
        jacoco_path = base_path + "/target/site/jacoco/" + append_path + html_name
        return jacoco_path

    # copy from /bernard/dataset_construction/human_written_tests/v2/utils.py
    def get_lines_coverage(self, jacoco_java_html_report_path):
        with open(jacoco_java_html_report_path, encoding='utf8') as f:
            soup = BeautifulSoup(f.read(), 'html.parser')
            # find all spans with class 'fc' or 'pc' or 'bpc', and extract the ID
            cov_lines = []
            uncov_lines = []
            for span in soup.find_all('span', class_=['fc', 'pc', 'bpc', 'nc']):
                if span['class'][0] == 'nc':
                    uncov_lines.append(int(span['id'][1:]))
                else:
                    cov_lines.append(int(span['id'][1:]))
        
        return cov_lines, uncov_lines
    

    def get_focal_method_coverage_statistic_by_jacoco(self, focal_method_name_param, jacoco_html_report_path):
        with open(jacoco_html_report_path, encoding='utf8') as f:
            soup = BeautifulSoup(f.read(), 'html.parser')

        # example: focal_method_name_param is intersectionDistinct(java.util.Collection<T>,java.util.Collection<T>,java.util.Collection<T>[]). to match intersectionDistinct(Collection, Collection, Collection[])
        # example: valuesOfKeys(java.util.Map<K, V>,K[]) to match valuesOfKeys(Map, Object[])
        # example: groupingBy(java.util.function.Function<? super T, ? extends K>,java.util.function.Function<? super T, ? extends R>) to match groupingBy(Function, Function)
        # example: filter(java.util.Map<K, V>,cn.hutool.core.lang.Filter<java.util.Map.Entry<K, V>>) to match filter(Map, Filter)
        target_fm_name = focal_method_name_param.strip().split('(')[0]
        target_fm_params_str = focal_method_name_param.strip().split('(')[1][:-1]
        target_fm_params_str = self.remove_angle_brackets_substrings(target_fm_params_str)
        target_fm_params = [each_param.strip() for each_param in target_fm_params_str.split(',')]
        target_fm_params = [each_param.split('.')[-1] if '.' in each_param else each_param for each_param in target_fm_params]

        cov_stat = {}

        candidates = []
        table = soup.find('tbody')
        if table is not None:
            for each_tr in table.find_all('tr'):
                # check the method name
                candidate_all_column = each_tr.find_all('td')

                method_name = candidate_all_column[0].text
                candidate_fm_name = method_name.strip().split('(')[0]
                if candidate_fm_name != target_fm_name:
                    continue
                
                candidates.append(candidate_all_column)

        if len(candidates) == 0:
            logger.warning('[WARNING] Cannot find the focal method in the jacoco report. Need manual check\n' + f'focal_method_name: {focal_method_name_param}\n\n')
            cov_stat['raw_html'] = str(soup)
            return cov_stat        

        if len(candidates) > 1:
            all_column = self.select_focal_method_coverage_statistic_by_jacoco(target_fm_params, candidates)
        else:
            all_column = candidates[0]

        if all_column is not None:
            # parse the result
            cov_stat['number_of_lines'] = int(all_column[8].text.strip())
            cov_stat['number_of_branches'] = int(all_column[6].text.strip()) - 1
            cov_stat['line_coverage'] = float(all_column[2].text.strip()[:-1])  # remove the '%'
            branch_cov = all_column[4].text.strip()
            cov_stat['branch_coverage'] = float(branch_cov[:-1]) if branch_cov != 'n/a' else branch_cov
        else:
            logger.warning('[WARNING] Cannot find the focal method in the jacoco report. Need manual check\n' + f'focal_method_name: {focal_method_name_param}\n\n')
            cov_stat['raw_html'] = str(soup)

        return cov_stat

    def select_focal_method_coverage_statistic_by_jacoco(self, target_fm_params, candidates):
        # filter according to the number of parameters
        filter_candidates = []
        for each_candidate in candidates:
            method_name = each_candidate[0].text

            candidate_fm_params = [each_param.strip() for each_param in method_name.strip().split('(')[1][:-1].split(',')]
            if len(target_fm_params) == len(candidate_fm_params):
                filter_candidates.append(each_candidate)
        
        if len(filter_candidates) == 1:
            all_column = filter_candidates[0]
            return all_column

        # filter according to the detailed parameters
        all_column = None

        for each_candidate in filter_candidates:
            method_name = each_candidate[0].text

            candidate_fm_params = [each_param.strip() for each_param in method_name.strip().split('(')[1][:-1].split(',')]
            is_match = True
            for idx in range(len(target_fm_params)):
                if target_fm_params[idx] != candidate_fm_params[idx]:
                    is_match = False
                    break

            if is_match:
                all_column = each_candidate
                return all_column

        # for corner case such as: valuesOfKeys(java.util.Map<K, V>,K[]) to match valuesOfKeys(Map, Object[]). need to transform K to Object
        if all_column is None:  
            for each_candidate in filter_candidates:
                method_name = each_candidate[0].text

                candidate_fm_params = [each_param.strip() for each_param in method_name.strip().split('(')[1][:-1].split(',')]
                is_match = True
                for idx in range(len(target_fm_params)): 
                    if target_fm_params[idx] != candidate_fm_params[idx]:
                        change_to_object = re.sub(r'[A-Za-z]', 'Object', target_fm_params[idx])
                        if change_to_object == candidate_fm_params[idx]:  # add this to check the corner case
                            continue
                        else:
                            is_match = False
                            break

                if is_match:
                    all_column = each_candidate
                    break

        return all_column

    def remove_angle_brackets_substrings(self, input_string):
        # Define the regular expression pattern to match substrings within angle brackets, including nested ones
        pattern = re.compile(r"<[^<>]*>")
        
        while True:
            # Remove all substrings that match the pattern
            input_string, count = pattern.subn('', input_string)
            if count == 0:
                break
        
        return input_string
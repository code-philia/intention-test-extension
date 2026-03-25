from user_config import global_config
import os
import pathlib

class Configs:
    def __init__(self, project_name, project_root_dir, tester_path = '') -> None:
        self.root_dir = os.path.abspath(os.path.dirname(__file__))
        self.project_root_dir = project_root_dir
        self.openai_api_key = global_config['openai']['apikey']
        self.openai_url = global_config['openai']['url']
        # TODO don't set globals here
        os.environ['OPEN_AI_KEY'] = self.openai_api_key
        os.environ['OPENAI_BASE_URL'] = self.openai_url

        self.project_name = project_name
        self.llm_name = 'gpt-4o'

        self.max_context_len = 1024
        self.max_input_len = 4096
        self.max_num_generated_tokens = 1024
        self.verbose = True

        if tester_path.strip():
            self.workspace = tester_path
        else:
            self.workspace = f'{self.root_dir}/intention_test_extension'

        self.corpus_path =  f'{self.workspace}/data/{project_name}.json'
        self.project_without_test_file_path = f'{self.workspace}/data/repos_removing_test/{project_name}'
        self.project_with_test_file_path = f'{self.workspace}/data/repos_with_test/{project_name}'
        
        self.generation_log_dir = f'{self.workspace}/data/generation_logs/{project_name}'
        self.test_case_run_log_dir = f'{self.workspace}/data/test_case_running_logs/{project_name}'

        # dataset relevant paths
        self.coverage_human_labeled_dir = f'{self.root_dir}/data/collected_coverages'
        self.test_desc_dataset_path = f'{self.root_dir}/data/test_desc_dataset/{project_name}.json'
        # self.fact_set_dir = f'{self.root_dir}/data/fact_set/{project_name}'

        # collected coverages
        self.collected_coverages_json = f'{self.project_root_dir}/.intention-test/collected_coverages/{project_name}.json'
        self.test_desc_json = f'{self.project_root_dir}/.intention-test/test_desc_dataset/{project_name}.json'
        self.fact_set_dir = f'{self.project_root_dir}/.intention-test/fact_set/{project_name}'

    def is_corpus_prepared(self):
        return os.path.exists(self.corpus_path)

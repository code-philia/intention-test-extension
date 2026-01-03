from user_config import global_config
import os

class Configs:
    def __init__(self, project_name, tester_path = '') -> None:
        self.root_dir = os.path.abspath(os.path.dirname(__file__))
        self.openai_api_key = global_config['openai']['apikey']
        self.openai_url = global_config['openai']['url']
        os.environ['OPEN_AI_KEY'] = self.openai_api_key
        os.environ['OPENAI_BASE_URL'] = self.openai_url

        self.project_name = project_name
        # allow overriding model via config.ini -> [openai] model = ...
        self.llm_name = global_config['openai'].get('model', 'gpt-4o')

        self.max_context_len = 1024
        self.max_input_len = 4096
        self.max_num_generated_tokens = 1024
        self.verbose = True

        if tester_path.strip():
            self.workspace = tester_path
        else:
            self.workspace = f'{self.root_dir}/intention_test_extension'

        # Align with dump_collect_pairs: it writes to backend/data/{project}.json
        self.corpus_path =  f'{self.root_dir}/data/{project_name}.json'
        self.project_without_test_file_path = f'{self.workspace}/data/repos_removing_test/{project_name}'
        self.project_with_test_file_path = f'{self.workspace}/data/repos_with_test/{project_name}'
        
        self.generation_log_dir = f'{self.workspace}/data/generation_logs/{project_name}'
        self.test_case_run_log_dir = f'{self.workspace}/data/test_case_running_logs/{project_name}'

        # dataset relevant paths
        self.coverage_human_labeled_dir = f'{self.root_dir}/data/collected_coverages'
        self.test_desc_dataset_path = f'{self.root_dir}/data/test_desc_dataset/{project_name}.json'
        self.fact_set_dir = f'{self.root_dir}/data/fact_set/{project_name}'

        # project url used for system prompt
        self.project_url = {
            "itext-java": 'https://github.com/itext/itext-java',
            "hutool": 'https://github.com/chinabugotech/hutool',
            "yavi": 'https://github.com/making/yavi',
            "lambda": 'https://github.com/palatable/lambda',
            "truth": 'https://github.com/google/truth',
            "cron-utils": 'https://github.com/jmrozanec/cron-utils',
            "imglib": 'https://github.com/nackily/imglib',
            "ofdrw": 'https://github.com/ofdrw/ofdrw',
            "RocketMQC": 'https://github.com/ProgrammerAnthony/RocketMQC',
            "blade": 'https://github.com/lets-blade/blade',
            "spark": 'https://github.com/perwendel/spark',
            "awesome-algorithm": 'https://github.com/codeartx/awesome-algorithm',
            "jInstagram": 'https://github.com/sachin-handiekar/jInstagram'
        }[project_name]


    def is_corpus_prepared(self):
        return os.path.exists(self.corpus_path)

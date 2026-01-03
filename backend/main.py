import json
import os
import re
import shutil
from generator import IntentionTester
from dataset import Dataset
from configs import Configs
from modules.session import ModelQuerySession
from typing import Optional
import pathlib
from extension_api.collect_pairs.main import dump_collect_pairs

import logging
logger = logging.getLogger(__name__)

import sys
logger.warning('UTF-8 mode is enabled' if sys.flags.utf8_mode else 'UTF-8 mode is not enabled and I/O error may occur')

# WARNING remember to replace the built-in open() to use UTF-8
# because project file should be opened using UTF-8, but subprocess.run() (for Java, but CodeQL should still use UTF-8) output should still be decoded in local encoding
# both would cause error if not set properly

class IntentionTest:
    def __init__(self, project_path, configs):
        self.project_path = project_path
        self.corpus = None

        self.corpus_path =  configs.corpus_path
        self.generator = IntentionTester(configs)

    def load_corpus(self):
        # collect pairs
        assert os.path.exists(self.corpus_path)
        with open(self.corpus_path, 'r', encoding='utf8') as f:
            all_data = json.load(f)

        corpus_fm, corpus_fm_name, corpus_context, corpus_tc_name, corpus_test_case_path = [], [], [], [], []

        for each_data in all_data:
            if 'target_coverage' in each_data:
                # original expected format
                corpus_fm.append(''.join(each_data['target_coverage']).replace('<COVER>', ''))
                corpus_fm_name.append(each_data.get('focal_method_name', ''))
                corpus_context.append(each_data.get('target_context', ''))
                tc_name = each_data.get('target_test_case_name', '')
                corpus_tc_name.append(tc_name.split('::::')[-1].split('(')[0] if tc_name else '')
                focal_file_path = each_data.get('focal_file_path', '')
                if focal_file_path:
                    corpus_test_case_path.append(focal_file_path.replace('src/main/java', 'src/test/java').replace('.java', 'Test.java'))
                else:
                    corpus_test_case_path.append('')
            else:
                # fallback to collect_pairs schema
                # focal method text
                fm = each_data.get('focal_method', [])
                corpus_fm.append(''.join(fm) if isinstance(fm, list) else str(fm))
                # focal method name
                corpus_fm_name.append(each_data.get('focal_method_name', ''))
                # use focal method content as context (best available without re-reading files)
                corpus_context.append(''.join(fm) if isinstance(fm, list) else str(fm))
                # derive test case simple name from test_name or test_path
                test_name = each_data.get('test_name', '')
                if test_name:
                    corpus_tc_name.append(test_name.split('(')[0].split('::::')[-1])
                else:
                    test_path = each_data.get('test_path', '')
                    corpus_tc_name.append(os.path.splitext(os.path.basename(test_path))[0] if test_path else '')
                # test case path provided directly
                corpus_test_case_path.append(each_data.get('test_path', ''))

        self.corpus = {
            'corpus_fm': corpus_fm,
            'corpus_fm_name': corpus_fm_name,
            'corpus_context': corpus_context,
            'corpus_tc_name': corpus_tc_name,
            'corpus_test_case_path': corpus_test_case_path
        }


def main(target_focal_method, target_focal_file, test_desc, project_path, focal_file_path, query_session: Optional[ModelQuerySession] = None):
    # project_name = project_path.split('/')[-1]     not compatible with Windows path
    project_name = pathlib.Path(project_path).stem
    # replace the disk letter to upper case to match CodeQL path 
    tester_path = re.sub(r'[a-z]:/', lambda s: s[0].upper(), pathlib.Path(__file__).parent.absolute().as_posix())
    configs = Configs(project_name, tester_path)

    class_name = os.path.splitext(os.path.basename(focal_file_path))[0]
    focal_method_name = f"{class_name}::::"
    method_signature_match = re.search(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^)]*\)', target_focal_method)
    if method_signature_match:
        method_signature = method_signature_match.group(0)
        focal_method_name += method_signature

    intention_test = IntentionTest(project_path, configs)

    # Connect to query session
    intention_test.generator.connect_to_request_session(query_session)

    logger.info('Checking test-focal corpus file')
    # prepare test-focal pairs
    if not configs.is_corpus_prepared():
        logger.warning('The test-focal corpus file does not exists, start collecting pairs')
        dump_collect_pairs(project_path)

    intention_test.load_corpus()

    # prepare two copies of the project in repos_with_test and repos_removing_test. the former is used to create the initial codeql database, while the latter is used to wirte the referable and generated test case during the generation process.
    # shutil.copytree(project_path, configs.project_with_test_file_path, dirs_exist_ok=True, ignore=shutil.ignore_patterns('.git'))
    # shutil.copytree(project_path, configs.project_without_test_file_path, dirs_exist_ok=True, ignore=shutil.ignore_patterns('.git'))

    # /intention_test_extension/data/repos_removing_test/spark/src/test/java/spark/embeddedserver/jetty/EmbeddedJettyFactoryTest.java
    project_without_test_file_dir = os.path.dirname(configs.project_without_test_file_path)

    # focal_file_path = f"{project_without_test_file_dir}/{focal_file_path[focal_file_path.index(project_name):]}" 
    # TODO fix all path incompatibility
    focal_file_path = (pathlib.Path(project_without_test_file_dir) / focal_file_path[focal_file_path.index(project_name):]).as_posix()
    target_test_case_path = focal_file_path.replace('src/main/java', 'src/test/java').replace('.java', 'Test.java')

    # prepare the datasets
    dataset = Dataset(configs)
    print('Loading datasets...')

    test_desc_data = dataset.load_test_desc(test_desc)
    target_test_case_desc = test_desc_data['test_desc']['under_setting']

    # TODO LSP now cannot run in Windows
    try:
        offline_fact_ref_data = dataset.load_offline_fact_ref_data()
    except FileNotFoundError:
        # Fallback: construct empty facts/references with proper length
        corpus_len = len(intention_test.corpus['corpus_fm_name']) if intention_test.corpus else 0
        offline_fact_ref_data = [
            {
                'target_coverage_idx': i,
                'rag_references': [],
                'disc_facts': [],
                'disc_facts_sim': [],
                'top_usages': [],
                'top_usages_sim': []
            }
            for i in range(corpus_len)
        ]

    # start generating test case(s)

    # TODO extract context from local java files
    target_pair_idx = 0
    for i in range(0, len(intention_test.corpus['corpus_fm_name'])):
        if focal_method_name.split("(")[0] == intention_test.corpus['corpus_fm_name'][i].split("(")[0]:
            target_pair_idx = i
            target_focal_file = intention_test.corpus['corpus_context'][i]
            break

    ref_score, ref_focal_method, ref_test_case = retrieve_reference_offline(target_pair_idx, offline_fact_ref_data,
                                                                            focal_method_name)
    references_tc_rag = [ref_test_case]

    if len(references_tc_rag) > 0:
        top_1_reference_tc_rag = references_tc_rag[0]
    else:
        top_1_reference_tc_rag = None

    # collect facts
    facts, facts_sim, usages, usages_sim = get_crucial_facts_offline(target_pair_idx, offline_fact_ref_data, focal_method_name)

    logger.info('Starting a multi-round chat for generating test case')
    messages: list[dict] = []
    generated_test_case = None
    for model_name in configs.llm_names:
        model_configs = Configs(project_name, tester_path, llm_name_override=model_name)
        dtester = IntentionTester(model_configs)
        dtester.connect_to_request_session(query_session)

        messages.append({"role": "system", "content": f"### Model: {model_name}"})
        dtester.set_message_prefix(messages)

        # generate the test case
        generated_test_case, test_status, model_messages = dtester.generate_test_case_with_refine(
            target_focal_method=target_focal_method,
            target_context=target_focal_file,
            target_test_case_desc=target_test_case_desc,
            target_test_case_path=target_test_case_path,
            referable_test_case=top_1_reference_tc_rag,
            facts=facts,
            junit_version=str(query_session.junit_version),
            query_session=query_session
        )
        messages = messages + model_messages

    return messages, generated_test_case


def retrieve_reference_offline(coverage_idx, offline_ref_data, focal_method_name, top_k=1):
    info = offline_ref_data[coverage_idx]
    assert info['target_coverage_idx'] == coverage_idx
    # assert focal_method_name == info['focal_method_name']
    assert top_k == 1  # for now, only consider the top 1

    if len(info['rag_references']) == 0:
        return [], [], []
    else:
        ref_score, ref_focal_method, ref_test_case = info['rag_references'][0]
        return ref_score, ref_focal_method, ref_test_case


def get_crucial_facts_offline(coverage_idx: int, offline_facts, focal_method_name: str, threshold = 0.4, top_k = 5):
    info = offline_facts[coverage_idx]
    # assert info[
    #            'target_coverage_idx'] == coverage_idx, f'Inconsistent coverage_idx: {coverage_idx} vs {info["target_coverage_idx"]}'
    # assert focal_method_name == info[
    #     'focal_method_name'], f'Inconsistent focal_method_name: {focal_method_name} vs {info["focal_method_name"]}'

    disc_facts = info['disc_facts']
    disc_facts_sim = info['disc_facts_sim']
    top_usages = info['top_usages']
    top_usages_sim = info['top_usages_sim']

    top_disc_facts, top_disc_facts_sim = [], []
    for i, each_disc_fact in enumerate(disc_facts):
        if disc_facts_sim[i] >= threshold:
            top_disc_facts.append(each_disc_fact)
            top_disc_facts_sim.append(disc_facts_sim[i])
    top_disc_facts = top_disc_facts[:top_k]
    top_disc_facts_sim = top_disc_facts_sim[:top_k]

    # provide signature rather the full body
    # TODO: should also modify the online version
    top_disc_facts_sig = []
    for each_fact in top_disc_facts:
        class_name, signature = each_fact.split('{')[0], each_fact.split('{')[1].strip()
        top_disc_facts_sig.append(class_name + '{\n' + signature + '\n}')
    top_disc_facts = top_disc_facts_sig

    return top_disc_facts, top_disc_facts_sim, top_usages, top_usages_sim

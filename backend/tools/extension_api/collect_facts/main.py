import json
import os
import argparse
from collections import namedtuple
from tqdm import tqdm
import re
from transformers import AutoModel, AutoTokenizer
import logging
logger = logging.getLogger(__name__)

from LSPs.java_lsp import JavaLanguageServer
from fact_discriminator.discriminator import FactDiscriminator
from retriever import Retriever
from graph_explorer import GraphExplorer

# ========== DATA STRUCTURES ==========

# edited CoveragePair, only used for fact collection
CoveragePair = namedtuple(
    'CoveragePair',
    [
        'focal_file_path',
        'focal_method_name',
        'coverage',
        'focal_method',
        'context',
        'focal_file_skeleton',
        'test_case',
        'test_case_name',
        'test_case_path',
        'references'
    ]
)


# ========== UTILS ==========

# COVERAGE

def add_newline_char(string):
    if not string.endswith('\n'):
        string += '\n'
    return string

def load_coverage_data_jacoco(path: str):
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
                context = [add_newline_char(each_line) for each_line in context]

                if '::::' in tc_name:
                    tc_name = tc_name.split('::::')[1]
                    tc_name = tc_name.split('(')[0]
                # 

                fm = ''.join(cov).replace('<COVER>', '')

                focal_case_dir = each_focal_file_path[:each_focal_file_path.rfind('/')]
                test_case_dir = focal_case_dir.replace('/main/', '/test/')
                
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
                
                if args.project_name == 'blade' and is_extend_clss:
                    continue    
                
                if test_case_class_name is None:
                    raise ValueError(f'Test case class name is not found.\nTest case:\n{tc}\n')

                test_case_path = f'{test_case_dir}/{test_case_class_name}.java'
                
                if len(focal_file_skeleton) == 0:
                    raise ValueError(f'Focal file skeleton is empty.\nFocal file:\n{each_focal_file_path}\n')

                coverage_pair = CoveragePair(
                    focal_file_path=each_focal_file_path,
                    focal_method=fm,
                    coverage=''.join(cov),
                    context=''.join(context),
                    focal_file_skeleton=focal_file_skeleton,
                    test_case=''.join(tc),
                    test_case_name = tc_name,
                    test_case_path = test_case_path,
                    focal_method_name=each_fm_name,
                    references=None
                )
                coverage_data.append(coverage_pair)
    return coverage_data


# TEST DESC

def divide_desc(desc):
    """
    each desc data is like:
        # Objective
        To verify that the `parse` method correctly throws an `IllegalArgumentException` when given an empty cron expression.

        # Preconditions
        1. The `CronDefinition` mock returns an empty set when `getCronNicknames` is called.
        2. The `CronParser` instance is created with the mocked `CronDefinition`.
        3. The `parse` method is called with an empty string as input.

        # Expected Results
        1. The `parse` method throws an `IllegalArgumentException` with the message "Empty expression!".
    need to divide it into Objective, Preconditions, Expected Results
    """
    desc_lines = desc.split('\n')
    obj_line_idx, precondictions_line_idx, expected_results_line_idx = None, None, None
    for line_idx, each_line in enumerate(desc_lines):
        if each_line.strip().startswith('#'):
            if '# Obj' in each_line:
                obj_line_idx = line_idx
            elif '# Precondition' in each_line:
                precondictions_line_idx = line_idx
            elif '# Expected' in each_line:
                expected_results_line_idx = line_idx
            else:
                raise ValueError(f'Unknown desc line: {each_line}')
    assert None not in (obj_line_idx, precondictions_line_idx, expected_results_line_idx), f'Incompleted Test Desc:\n{desc}\n\n'
    assert obj_line_idx < precondictions_line_idx < expected_results_line_idx, f'Invalid order of desc:\n{desc}\n\n'
    obj = desc_lines[obj_line_idx+1:precondictions_line_idx]
    precondictions = desc_lines[precondictions_line_idx+1:expected_results_line_idx]
    expected_results = desc_lines[expected_results_line_idx+1:]

    desc_dict = {
        'Objective': '\n'.join(obj).strip(),
        'Preconditions': '\n'.join(precondictions).strip(),
        'Expected Results': '\n'.join(expected_results).strip()
    }

    # Check the total number of lines
    total_lines_origin = len([each_line for each_line in desc_lines if each_line.strip()])
    total_lines_divided = len([each_line for each_line in obj + precondictions + expected_results if each_line.strip()]) + 3
    if total_lines_origin != total_lines_divided:
        print(f'WARNING: The total number of lines is not equal after dividing the desc.\nOriginal:\n{desc}\n--------------------\nDivided three parts\n{obj + precondictions + expected_results}\n\n')

    return desc_dict

def load_test_desc(test_desc_path: str, setting: str):
    with open(test_desc_path, 'r') as f:
        test_desc_data = json.load(f)

    test_desc_data_reformat = []
    for each in test_desc_data:
        test_desc = each['test_desc']
        test_desc = test_desc[3:] if test_desc.startswith('```') else test_desc
        test_desc = test_desc[:-3] if test_desc.endswith('```') else test_desc
        test_desc = test_desc.strip()
        test_desc = divide_desc(test_desc)

        if setting == 'none':
            test_desc_under_setting = ''
        elif setting == 'obj':
            test_desc_under_setting = '# Objective\n' + test_desc['Objective']
        elif setting == 'obj_pre':
            test_desc_under_setting = '# Objective\n' + test_desc['Objective'] + '\n\n# Preconditions\n' + test_desc['Preconditions']
        elif setting == 'obj_exp':
            test_desc_under_setting = '# Objective\n' + test_desc['Objective'] + '\n\n# Expected Results\n' + test_desc['Expected Results']
        elif setting == 'full':
            test_desc_under_setting = '# Objective\n' + test_desc['Objective'] + '\n\n# Preconditions\n' + test_desc['Preconditions'] + '\n\n# Expected Results\n' + test_desc['Expected Results']
        else:
            raise ValueError(f'Unknown setting: {setting}')

        test_desc['under_setting'] = test_desc_under_setting
        each['test_desc'] = test_desc
        test_desc_data_reformat.append(each)
    return test_desc_data_reformat


# FACT

def retrieve_reference(corpus_code, corpus_desc, target_focal_method, target_test_case, target_test_desc, threshold, retriever_tokenizer, retriever_embedding_model, setting, top_k=3):
    corpus_cov, corpus_fm, corpus_fm_name, corpus_tc, corpus_tc_desc, corpus_test_case_path = [], [], [], [], [], []
    
    for idx, each_pair_cor in enumerate(corpus_code):
        corpus_cov.append(each_pair_cor.coverage)
        corpus_fm.append(each_pair_cor.focal_method)
        corpus_fm_name.append(each_pair_cor.focal_method_name)
        corpus_tc.append(each_pair_cor.test_case)
        corpus_test_case_path.append(each_pair_cor.test_case_path)
        
        assert corpus_desc[idx]['target_test_case'] == each_pair_cor.test_case
        corpus_tc_desc.append(corpus_desc[idx]['test_desc']['under_setting'])
    
    retriever = Retriever(corpus_cov, corpus_fm, corpus_fm_name, corpus_tc, corpus_tc_desc, corpus_test_case_path, retriever_embedding_model, retriever_tokenizer)

    if setting == 'golden':
        references_cov_rag, references_fm_rag, references_fm_name_rag, references_tc_rag, reference_tc_desc_rag, references_score, references_tc_path = retriever.ideal_retrieve(
            target_tc=target_test_case, 
            threshold=threshold,
            top_k=top_k
            )
    elif setting == 'retrieve':
        references_cov_rag, references_fm_rag, references_fm_name_rag, references_tc_rag, reference_tc_desc_rag, references_score, references_tc_path = retriever.retrieve_with_threshold(
            target_fm=target_focal_method, 
            target_tc_desc=target_test_desc, 
            threshold=threshold,
            top_k=top_k
            )
    else:
        raise ValueError
    return references_cov_rag, references_fm_rag, references_fm_name_rag, references_tc_rag, reference_tc_desc_rag, references_score, references_tc_path


# ========== MAIN FUNCTION ==========

def collect_facts(workspace_path: str, coverage_path: str, test_desc_path: str, fact_set_dir: str, top_k: int =3):
    coverage_data = load_coverage_data_jacoco(coverage_path)
    test_desc_data = load_test_desc(test_desc_path, setting=args.test_desc_setting)

    # prepare LSP server
    lsp_workspace = workspace_path
    lsp_server = JavaLanguageServer(lsp_workspace, log=False)
    lsp_server.initialize(lsp_workspace)
    file_paths = lsp_server.get_all_file_paths(lsp_workspace)
    lsp_server.open_in_batch(file_paths)

    # prepare embedding model and tokenizer used by retriever
    embedding_model = AutoModel.from_pretrained("Salesforce/codet5p-110m-embedding", trust_remote_code=True).eval().to('cuda')
    embedding_model_tokenizer = AutoTokenizer.from_pretrained("Salesforce/codet5p-110m-embedding", trust_remote_code=True)

    # prepare the fact discriminator
    if args.fact_setting == 'golden':
        fact_discriminator = FactDiscriminator(embedding_model=None, tokenizer=None, is_golden=True)
    elif args.fact_setting == 'disc':
        fact_discriminator = FactDiscriminator(embedding_model=embedding_model, tokenizer=embedding_model_tokenizer, is_golden=False)
        graph_explorer = GraphExplorer(lsp_server, max_depth=args.max_exploration_depth, efficieny_mode=True if args.project_name == 'lambda' else False)
    elif args.fact_setting == 'none':
        pass
    else:
        raise ValueError
    
    # prepare the save path
    os.makedirs(fact_set_dir, exist_ok=True)
    save_path = f'{fact_set_dir}/ref_{args.reference_setting}_fact_{args.fact_setting}_desc_{args.test_desc_setting}_depth_{args.max_exploration_depth}_refThres_{args.retrieval_threshold}.json'

    if args.resume_generation_at > 0:
        save_path = save_path.replace('.json', f'_resume_{args.resume_generation_at}.json')

    collected_facts = []
    # start collection
    for target_pair_idx, each_target_pair in tqdm(enumerate(coverage_data), total=len(coverage_data), ncols=80, desc='Generating test cases'):
        if target_pair_idx < args.resume_generation_at:
            continue
            
        if args.specify_test_cov_idx and target_pair_idx not in args.specify_test_cov_idx:
            continue
        
        focal_file_path = each_target_pair.focal_file_path
        focal_method_name = each_target_pair.focal_method_name
        target_focal_method = each_target_pair.focal_method
        target_coverage = each_target_pair.coverage
        context = each_target_pair.focal_file_skeleton
        target_test_case = each_target_pair.test_case
        target_test_case_name = each_target_pair.test_case_name
        target_test_case_path = each_target_pair.test_case_path
        
        focal_method_pure_name = focal_method_name.split('::::')[1].split('(')[0]

        assert test_desc_data[target_pair_idx]['target_test_case'] == target_test_case
        target_test_case_desc = test_desc_data[target_pair_idx]['test_desc']['under_setting']

        if args.reference_setting == 'none':
            references_tc_rag, references_fm_rag, references_score = [], [], []
        else:
            # prepare retriever and retrieve the reference
            # prepare corpus. remove the target pair from the corpus
            corpus_coverage_data = coverage_data[:target_pair_idx] + coverage_data[target_pair_idx+1:]
            corpus_desc_data = test_desc_data[:target_pair_idx] + test_desc_data[target_pair_idx+1:]

            references_cov_rag, references_fm_rag, references_fm_name_rag, references_tc_rag, reference_tc_desc_rag, references_score, references_tc_path = retrieve_reference(
                corpus_coverage_data, corpus_desc_data, target_focal_method, target_test_case, target_test_case_desc, args.retrieval_threshold, embedding_model_tokenizer, embedding_model, args.reference_setting, top_k=top_k
                )
            
        # collect facts
        if args.fact_setting == 'golden':
            facts, target_tc_for_verify = fact_discriminator.get_golden_facts(target_pair_idx)
            if target_tc_for_verify is not None and target_tc_for_verify != target_test_case:
                print(f'WARNING: The target test case for verification is different from the target test case for generation.')
                print(f'# Target test case from coverage dataset:\n{target_test_case}')
                print(f'# Target test case from fact dataset:\n{target_tc_for_verify}')
                raise ValueError
        elif args.fact_setting == 'none':
            raise ValueError
        elif args.fact_setting == 'disc':
            all_candidate_facts, facts, facts_sim, all_usages, usages, usages_sim = discriminate_cruical_facts(graph_explorer, fact_discriminator, focal_file_path, target_focal_method, target_test_case_desc, focal_method_pure_name)
        else:
            raise ValueError

        rag_references = [(references_score[i], references_fm_rag[i], references_tc_rag[i]) for i in range(len(references_fm_rag))]

        collected_facts.append({
            'target_coverage_idx': target_pair_idx,
            'focal_file_path': focal_file_path,
            'focal_method_name': focal_method_name,
            'test_desc': target_test_case_desc,
            'rag_references': rag_references,
            'target_test_case': target_test_case,
            'candidate_facts': all_candidate_facts,
            'disc_facts': facts,
            'disc_facts_sim': facts_sim,
            'all_usages': all_usages,
            'top_usages': usages,
            'top_usages_sim': usages_sim,
            'target_coverage': target_coverage,
        })

        with open(save_path, 'w') as f:
            json.dump(collected_facts, f, indent=4)


def discriminate_cruical_facts(graph_explorer, fact_discriminator, focal_file_path, target_focal_method, target_test_case_desc, focal_method_name):
    candidate_facts, focal_method_usages = graph_explorer.explore(focal_file_path, target_focal_method, focal_method_name)

    if len(candidate_facts) == 0:
        facts_string, facts_sim, usages_string, usages_sim = [], [], [], []
    else:
        # preprocess the candidate_facts and focal_method_usages
        candidate_facts_proc = [(each[0], each[1], each[2]) for each in candidate_facts if len(each[2]) > 0]  # [(class_name, signature, body)]
        candidate_facts_proc = list(set(candidate_facts_proc))

        usage_proc = []  # [(usage_body, [(fact_class_name, fact_signature)])]
        for each_usage in focal_method_usages:
            usage_proc.append(
                (
                    each_usage[2], 
                    set([(each_fact_in_usage[0], each_fact_in_usage[1]) for each_fact_in_usage in each_usage[3]])
                )
            )

        facts, facts_sim, usages, usages_sim = fact_discriminator.get_crucial_facts_v2(candidate_facts_proc, usage_proc, target_test_case_desc, threshold=0.1, top_k=10)  # relax the threshold to returen more discriminated facts with similarity score
        facts_string = [each[0] + '{\n' + each[1] + each[2] + '\n}' for each in facts]
        usages_string = [each[0] for each in usages]
    return candidate_facts, facts_string, facts_sim, focal_method_usages, usages_string, usages_sim


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Collect facts.')
    parser.add_argument('--project_name', type=str)
    parser.add_argument('--llm_name', type=str, default='gpt-4o')
    parser.add_argument('--retrieval_threshold', type=float, default=0.2)
    parser.add_argument('--resume_generation_at', type=int, default=0)
    parser.add_argument('--specify_test_cov_idx', type=lambda s: [int(x) for x in s.split(',')], default=[])
    parser.add_argument('--fact_setting', type=str, default='disc', choices=['none', 'disc', 'golden'])
    parser.add_argument('--test_desc_setting', type=str, default='full', choices=['none', 'obj', 'obj_pre', 'obj_exp', 'full'])
    parser.add_argument('--reference_setting', type=str, default='retrieve', choices=['none', 'retrieve', 'golden'])
    parser.add_argument('--max_exploration_depth', type=int, default=5)
    
    parser.add_argument('--workspace_path', type=str)
    
    parser.add_argument('--coverage_path', type=str, help='Path to the coverage data directory')   # input dir
    parser.add_argument('--test_desc_path', type=str, help='Path to the test description directory')  # input dir
    parser.add_argument('--fact_set_dir', type=str, help='Path to the fact set output directory')    # output dir
    parser.add_argument('--top_k', type=int, default=3, help='Number of top references to retrieve')

    args = parser.parse_args()

    logger.debug(f'Colleting facts for project {args.project_name}')
    collect_facts(args.workspace_path, args.coverage_path, args.test_desc_path, args.fact_set_dir, args.top_k)
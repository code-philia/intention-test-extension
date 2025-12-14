import os
import json
import pathlib
import logging
import argparse
import tqdm
logger = logging.getLogger(__name__)
# logger.setLevel(logging.DEBUG)

if __name__ == '__main__':
    import utils
else:
    from . import utils

module_path_str = os.path.dirname(__file__)
tester_path = pathlib.Path(module_path_str, '..', '..')
os.chdir(module_path_str)


def posix_path(*paths: str):
    return pathlib.Path(*paths).as_posix()


def collect_pairs(repo_path, test_suffix: str, do_dynamic_analysis: bool):
    all_data = {}

    test_focal_path_list = []

    for root, dirs, files in os.walk(repo_path):
        root = posix_path(root)
        if 'src/main/java' not in root:
            continue

        for file in files:
            if not file.endswith('.java'):
                continue

            test_name = file[:-5] + test_suffix + '.java'
            test_root = root.replace('src/main/java', 'src/test/java')
            full_test_path = posix_path(test_root, test_name)
            full_focal_path = posix_path(root, file)

            if not os.path.exists(full_test_path):
                continue

            test_focal_path_list.append((root, full_test_path, full_focal_path))

    logger.info('Detected %s Java files to collect', len(test_focal_path_list))
    tqdm_progress = tqdm.tqdm(total=len(
        test_focal_path_list), desc='Collecting test-focal pairs', unit='file')

    for root, full_test_path, full_focal_path in test_focal_path_list:
        with open(full_test_path, encoding='utf-8') as f:
            test_content = f.readlines()

        with open(full_focal_path, encoding='utf-8') as f:
            focal_content = f.readlines()

        test_method_lines_dic, test_reverse_method_lines_dic = utils.get_method_lines(
            full_test_path)
        foc_method_lines_dic, foc_reverse_method_lines_dic = utils.get_method_lines(
            full_focal_path)
        old_foc_method_lines_dic, old_foc_reverse_method_lines_dic = utils.get_method_lines(
            full_focal_path, False)
        cross_calls_map = utils.get_method_calls_cross_map(full_test_path)
        foc_calls_map = utils.get_method_calls_map(full_focal_path)
        test_calls_map = utils.get_method_calls_map(full_test_path)
        unused_classes_lines = utils.get_unused_classes_lines(
            full_focal_path)
        unused_classes_test_lines = utils.get_unused_classes_lines(
            full_test_path)

        possible_focal_methods = list(old_foc_method_lines_dic.keys())

        for method_name, method_lines in test_method_lines_dic.items():
            start_line = method_lines[0]
            end_line = method_lines[1]

            if test_content[start_line - 1].strip() == '@Test':
                expected_focal_method_name = utils.get_expected_focal_method_name(
                    method_name, possible_focal_methods)
                if expected_focal_method_name == "":
                    continue

                # path is the path before "/src/main/java"
                path = root.split("/src/main/java")[0]

                # org_name is the name of the organization
                org_name = root.split("/src/main/java/")[1].split("/")[0]

                # test_class_name_formatted example: 'utils.CollectionUtilsTest'
                test_class_name_formatted = full_focal_path.split(
                    '/src/main/java/' + org_name + '/')[1][:-5].replace("/", ".") + test_suffix

                test_method_name = method_name.split("(")[0]

                cov_lines, uncov_lines = [], []

                if do_dynamic_analysis:
                    jacoco_path = utils.get_jacoco_report(
                        path, test_class_name_formatted, test_method_name[test_method_name.index("::::") + 4:], org_name, test_suffix)

                    if not os.path.exists(jacoco_path):
                        continue

                    cov_lines, uncov_lines = utils.get_lines_coverage(
                        jacoco_path)

                called_methods = cross_calls_map[method_name] if method_name in cross_calls_map else [
                ]

                foc_start, foc_end = None, None

                foc_method_final = None

                for called_method in called_methods:
                    if called_method.split("(")[0] == expected_focal_method_name:
                        foc_start, foc_end = foc_method_lines_dic[called_method]

                        if not do_dynamic_analysis:
                            foc_method_final = called_method
                            break

                        for i in range(foc_start, foc_end + 1):
                            if i in cov_lines:
                                foc_method_final = called_method
                                break

                if foc_method_final is None or foc_start is None or foc_end is None:
                    continue
                if foc_method_final not in foc_calls_map or method_name not in test_calls_map:
                    continue

                test_method_full = test_content[start_line - 1: end_line]
                focal_method_full = focal_content[foc_start - 1: foc_end]

                # santinize focal method
                irrelevant_methods = utils.get_irrelevant_methods(
                    foc_calls_map, foc_method_final)

                comment_lines = utils.get_comment_lines(full_focal_path)
                if foc_method_final not in unused_classes_lines:
                    logger.error(
                        f'Method {foc_method_final} not found in unused_classes_lines {unused_classes_lines}')
                    raise ValueError(
                        f'Method {foc_method_final} not found in unused_classes_lines {unused_classes_lines}')

                unused_classes_lines_specific = unused_classes_lines[foc_method_final]

                sanitised_class_content = utils.annotate_deleted_classes(
                    focal_content, unused_classes_lines_specific)
                sanitised_class_content = utils.delete_irrelevant_methods_and_comments(
                    sanitised_class_content, irrelevant_methods, foc_method_lines_dic, comment_lines)
                sanitised_class_content = utils.delete_consecutive_empty_lines(sanitised_class_content)

                # santinize test method
                irrelevant_methods_test = utils.get_irrelevant_methods(
                    test_calls_map, method_name)

                comment_lines_test = utils.get_comment_lines(
                    full_test_path)
                if method_name not in unused_classes_test_lines:
                    logger.error(
                        f'Method {method_name} not found in unused_classes_test_lines {unused_classes_test_lines}')
                    raise ValueError(
                        f'Method {method_name} not found in unused_classes_test_lines {unused_classes_test_lines}')

                unused_classes_lines_specific_test = unused_classes_test_lines[method_name]

                sanitised_test_content = utils.annotate_deleted_classes(
                    test_content, unused_classes_lines_specific_test)
                sanitised_test_content = utils.delete_irrelevant_methods_and_comments(
                    sanitised_test_content, irrelevant_methods_test, test_method_lines_dic, comment_lines_test, True)
                sanitised_test_content = utils.delete_consecutive_empty_lines(
                    sanitised_test_content)
                
                focal_file_skeleton = utils.skeletonize_java_code("".join(focal_content))

                if '::::' in method_name:
                    tc_name = method_name.split('::::')[1]
                    tc_name = tc_name.split('(')[0]

                if full_focal_path not in all_data:
                    all_data[full_focal_path] = {}
                if foc_method_final not in all_data[full_focal_path]:
                    all_data[full_focal_path][foc_method_final] = []
                all_data[full_focal_path][foc_method_final].append([
                    tc_name, # tc_name
                    sanitised_test_content, # tc
                    focal_method_full, # cov
                    sanitised_class_content, # context
                    focal_file_skeleton, # focal_file_skeleton
                ])

                # print(json.dumps(all_data[-1], indent=4))
        tqdm_progress.update(1)

    return all_data


def dump_collect_pairs(project_path: str, test_suffix: str, output_path: str, do_dynamic_analysis=False):
    save_dir = pathlib.Path(output_path)
    os.makedirs(save_dir, exist_ok=True)

    project_path_object = pathlib.Path(project_path)
    project_name = project_path_object.stem
    all_data = collect_pairs(project_path_object.as_posix(), test_suffix, do_dynamic_analysis)
    assert len(all_data) > 0
    with open((save_dir / f'{project_name}.json').as_posix(), 'w', encoding='utf-8') as f:
        json.dump(all_data, f, indent=4)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Collect test-focal method pairs from a Java project to build a dataset.')
    parser.add_argument('--project_path', type=str, help='Path to the Java repository.')
    parser.add_argument('--test_suffix', type=str, default='Test', help='Suffix for test classes.')
    parser.add_argument('--output_path', type=str, help='Path to save the collected dataset.')
    parser.add_argument('--dynamic_analysis', action='store_true', help='Whether to perform dynamic analysis using JaCoCo.')
    args = parser.parse_args()

    dump_collect_pairs(args.project_path, args.test_suffix, args.output_path, args.dynamic_analysis)

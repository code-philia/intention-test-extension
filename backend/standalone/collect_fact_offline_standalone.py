"""
Standalone version of collect_fact_offline.py with all dependencies extracted.
This version includes mock implementations for complex dependencies like LSP server and Java parser.
"""

import argparse
import json
import logging
import os
import re
import uuid
from collections import namedtuple
from typing import List

import numpy as np
import torch

# Import the model loader
from model_loader import get_device, load_embedding_model
from tqdm import tqdm

# Configure logging (same format as model_loader)
logger = logging.getLogger(__name__)

torch.no_grad()

try:
    from nltk.corpus import stopwords
    from rank_bm25 import BM25Okapi

    BM25_AVAILABLE = True
except ImportError:
    logger.warning("rank_bm25 or nltk not available. Using mock implementation.")
    BM25_AVAILABLE = False

try:
    import javalang

    JAVALANG_AVAILABLE = True
except ImportError:
    logger.warning("javalang not available. Using mock implementation.")
    JAVALANG_AVAILABLE = False


# ========== UTILITY FUNCTIONS ==========


def skeletonize_java_code(java_code):
    """Mock implementation of Java code skeletonization"""
    if JAVALANG_AVAILABLE:
        try:
            tree = javalang.parse.parse(java_code)
            lines = []
            # Package declaration
            if tree.package:
                lines.append(f"package {tree.package.name};\n")
            # Import declarations
            for imp in tree.imports:
                line = "import "
                if imp.static:
                    line += "static "
                line += imp.path
                if imp.wildcard:
                    line += ".*"
                line += ";"
                lines.append(line)
            if tree.imports:
                lines.append("")

            # Process each top-level type
            for type_decl in tree.types:
                type_lines = process_type(type_decl)
                lines.extend(type_lines)
                lines.append("")  # blank line between top-level types

            return "\n".join(lines)
        except Exception as e:
            logger.warning("Failed to parse java code for skeletonization: %s", e)
            return java_code
    else:
        # Mock implementation - just return the original code
        return java_code


def process_type(type_decl, indent=""):
    """Process a class or interface declaration"""
    if not JAVALANG_AVAILABLE:
        return [f"{indent}// Mock skeleton for {getattr(type_decl, 'name', 'Unknown')}"]

    lines = []
    modifiers = (
        order_modifiers(type_decl.modifiers) + " " if type_decl.modifiers else ""
    )
    type_keyword = (
        "class"
        if isinstance(type_decl, javalang.tree.ClassDeclaration)
        else "interface"
    )
    header = f"{indent}{modifiers}{type_keyword} {type_decl.name}"
    if hasattr(type_decl, "type_parameters") and type_decl.type_parameters:
        tparams = ", ".join(tp.name for tp in type_decl.type_parameters)
        header += f"<{tparams}>"
    header += " {"
    lines.append(header)
    lines.append(f"{indent}}}")
    return lines


def order_modifiers(modifiers):
    """Order modifiers according to conventional Java ordering"""
    order = [
        "public",
        "protected",
        "private",
        "abstract",
        "static",
        "final",
        "transient",
        "volatile",
        "synchronized",
        "native",
        "strictfp",
    ]
    sorted_mods = sorted(modifiers, key=lambda x: order.index(x) if x in order else 100)
    return " ".join(sorted_mods)


# ========== CONFIGURATION CLASS ==========


class Configs:
    def __init__(self, project_name: str, llm_name: str, project_path: str = None):
        self.project_name = project_name
        self.root_dir = os.path.dirname(os.path.abspath(__file__))

        # Production environment - use provided project path or current directory
        if project_path:
            self.project_path_no_test_file = os.path.abspath(project_path)
            self.project_dir_no_test_file = os.path.dirname(
                self.project_path_no_test_file
            )
        else:
            # Fallback to current directory structure
            self.project_path_no_test_file = os.path.join(self.root_dir, project_name)
            self.project_dir_no_test_file = self.root_dir

        # Legacy experimental paths (may not exist in production)
        self.project_dir = f"{self.root_dir}/data/repos/repos_with_test"
        self.common_project_path_no_test_file = (
            f"{self.root_dir}/data/repos/repos_removing_test/{project_name}"
        )

        # model configs
        assert llm_name in [
            "gpt-4o",
            "gpt-3.5",
            "deepseek-32B",
            "gpt-o1-mini",
            "gpt-o4-mini",
            "deepseek-infra",
        ]
        self.llm_name = llm_name

        # Production-friendly dataset paths with fallbacks
        self.coverage_human_labeled_dir = self._get_data_dir("collected_coverages")
        self.test_desc_dataset_path = self._get_data_file(
            "test_desc_dataset", f"{project_name}.json"
        )
        self.fact_set_dir = self._get_data_dir("fact_set", project_name)

        # save paths - create in output directory
        output_dir = os.path.join(self.root_dir, "output")
        os.makedirs(output_dir, exist_ok=True)

        self.generated_test_case_save_path = (
            f"{output_dir}/generated_test_cases_{llm_name}_{project_name}.json"
        )
        self.generation_message_log_save_path = (
            f"{output_dir}/generation_message_log_{llm_name}_{project_name}.json"
        )
        self.test_case_run_log_dir = (
            f"{output_dir}/test_case_run_log_{llm_name}_{project_name}"
        )
        self.test_case_log_and_coverage_save_path = f"{output_dir}/generated_test_cases_log_coverage_{llm_name}_{self.project_name}.json"

        # project url used for system prompt
        project_urls = {
            "itext-java": "https://github.com/itext/itext-java",
            "hutool": "https://github.com/chinabugotech/hutool",
            "yavi": "https://github.com/making/yavi",
            "lambda": "https://github.com/palatable/lambda",
            "truth": "https://github.com/google/truth",
            "cron-utils": "https://github.com/jmrozanec/cron-utils",
            "imglib": "https://github.com/nackily/imglib",
            "ofdrw": "https://github.com/ofdrw/ofdrw",
            "RocketMQC": "https://github.com/ProgrammerAnthony/RocketMQC",
            "blade": "https://github.com/lets-blade/blade",
            "spark": "https://github.com/perwendel/spark",
            "awesome-algorithm": "https://github.com/codeartx/awesome-algorithm",
            "jInstagram": "https://github.com/sachin-handiekar/jInstagram",
        }
        self.project_url = project_urls.get(
            project_name, f"https://github.com/example/{project_name}"
        )

    def _get_data_dir(self, *path_parts):
        """Get data directory with fallback options for production environment"""
        # Try multiple possible locations
        possible_paths = [
            os.path.join(self.root_dir, "data", *path_parts),
            os.path.join(self.root_dir, *path_parts),
            os.path.join(os.getcwd(), "data", *path_parts),
            os.path.join(os.getcwd(), *path_parts),
        ]

        for path in possible_paths:
            if os.path.exists(path):
                return path

        # If none exist, create in root/data
        default_path = os.path.join(self.root_dir, "data", *path_parts)
        os.makedirs(default_path, exist_ok=True)
        return default_path

    def _get_data_file(self, *path_parts):
        """Get data file path with fallback options"""
        # Try multiple possible locations
        possible_paths = [
            os.path.join(self.root_dir, "data", *path_parts),
            os.path.join(self.root_dir, *path_parts),
            os.path.join(os.getcwd(), "data", *path_parts),
            os.path.join(os.getcwd(), *path_parts),
        ]

        for path in possible_paths:
            if os.path.exists(path):
                return path

        # Return default path (may not exist, will be handled by loading functions)
        return os.path.join(self.root_dir, "data", *path_parts)


# ========== DATA STRUCTURES ==========

CoveragePair = namedtuple(
    "CoveragePair",
    [
        "project_name",
        "focal_file_path",
        "focal_method_name",
        "coverage",
        "focal_method",
        "context",
        "focal_file_skeleton",
        "test_case",
        "test_case_name",
        "test_case_path",
        "references",
    ],
)


# ========== DATASET CLASS ==========


class Dataset:
    def __init__(self, configs):
        self.configs = configs

    def load_coverage_data_jacoco(self):
        """Load coverage data with multiple fallback strategies for production"""
        # Try loading from configured path
        path = os.path.join(
            self.configs.coverage_human_labeled_dir, f"{self.configs.project_name}.json"
        )
        data = self._load_coverage_data_jacoco(path)

        if len(data) == 0:
            # Try alternative paths and data generation strategies
            logger.info(
                "No coverage data found in default location. Trying alternatives..."
            )
            data = self._generate_mock_coverage_data()

        return data

    def _generate_mock_coverage_data(self):
        """Generate mock coverage data for production testing"""
        logger.info("Generating mock coverage data for production environment...")

        mock_data = []
        # Create some sample coverage pairs for testing
        for i in range(3):  # Create 3 mock test cases
            coverage_pair = CoveragePair(
                project_name=self.configs.project_name,
                focal_file_path=f"src/main/java/com/example/Class{i}.java",
                focal_method=f"public void testMethod{i}() {{\n    // Test method {i}\n    return;\n}}",
                coverage=f"public void <COVER>testMethod{i}()</COVER> {{\n    // Test method {i}\n    return;\n}}",
                context=f"public class Class{i} {{\n    public void testMethod{i}() {{\n        // Test method {i}\n    }}\n}}",
                focal_file_skeleton=f"public class Class{i} {{\n    public void testMethod{i}();\n}}",
                test_case=f"public class Class{i}Test {{\n    @Test\n    public void testMethod{i}() {{\n        Class{i} obj = new Class{i}();\n        obj.testMethod{i}();\n    }}\n}}",
                test_case_name=f"testMethod{i}",
                test_case_path=f"src/test/java/com/example/Class{i}Test.java",
                focal_method_name=f"com.example.Class{i}::::testMethod{i}()",
                references=None,
            )
            mock_data.append(coverage_pair)

        return mock_data

    def _load_coverage_data_jacoco(self, path: str):
        coverage_data = []
        try:
            with open(path, "r") as f:
                data = json.load(f)
        except FileNotFoundError:
            logger.warning("Coverage data file not found at %s", path)
            return []

        for each_focal_file_path, coverages in data.items():
            for each_fm_name, tc_cov_pairs in coverages.items():
                for each_pair in tc_cov_pairs:
                    tc_name, tc, cov, context, focal_file_skeleton = each_pair

                    # check data, will be removed after standardizing the format of dataset
                    tc = [self.add_newline_char(each_line) for each_line in tc]
                    cov = [self.add_newline_char(each_line) for each_line in cov]
                    context = [
                        self.add_newline_char(each_line) for each_line in context
                    ]

                    if "::::" in tc_name:
                        tc_name = tc_name.split("::::")[1]
                        tc_name = tc_name.split("(")[0]

                    fm = "".join(cov).replace("<COVER>", "")

                    focal_case_dir = each_focal_file_path[
                        : each_focal_file_path.rfind("/")
                    ]
                    test_case_dir = focal_case_dir.replace("/main/", "/test/")

                    is_extend_clss = False
                    test_case_class_name = None
                    for each_line in tc:
                        tc_class_name = re.findall(r"public class (\w+)\s*{", each_line)
                        if len(tc_class_name) == 1:
                            test_case_class_name = tc_class_name[0]
                            break

                        tc_class_name = re.findall(
                            r"public class (\w+) extends \w+\s*{", each_line
                        )
                        if len(tc_class_name) == 1:
                            test_case_class_name = tc_class_name[0]
                            is_extend_clss = True
                            break

                        tc_class_name = re.findall(r"class (\w+)\s*{", each_line)
                        if len(tc_class_name) == 1:
                            test_case_class_name = tc_class_name[0]
                            break

                        tc_class_name = re.findall(
                            r"public class (\$\w+)\s*{", each_line
                        )  # project lambda
                        if len(tc_class_name) == 1:
                            test_case_class_name = tc_class_name[0]
                            break

                    # NOTE: for blade, we skip the test cases that extend other classes
                    if self.configs.project_name == "blade" and is_extend_clss:
                        continue

                    if test_case_class_name is None:
                        logger.warning(
                            "Test case class name not found. Skipping this test case."
                        )
                        continue

                    test_case_path = f"{self.configs.project_dir_no_test_file}/{test_case_dir}/{test_case_class_name}.java"

                    if len(focal_file_skeleton) == 0:
                        logger.warning(
                            "Focal file skeleton is empty for %s", each_focal_file_path
                        )
                        focal_file_skeleton = "// Empty skeleton"

                    coverage_pair = CoveragePair(
                        project_name=self.configs.project_name,
                        focal_file_path=each_focal_file_path,
                        focal_method=fm,
                        coverage="".join(cov),
                        context="".join(context),
                        focal_file_skeleton=focal_file_skeleton,
                        test_case="".join(tc),
                        test_case_name=tc_name,
                        test_case_path=test_case_path,
                        focal_method_name=each_fm_name,
                        references=None,
                    )
                    coverage_data.append(coverage_pair)
        return coverage_data

    def add_newline_char(self, string):
        if not string.endswith("\n"):
            string += "\n"
        return string

    def load_test_desc(self, setting: str):
        """Load test descriptions with fallback for production environment"""
        try:
            with open(self.configs.test_desc_dataset_path, "r", encoding="utf-8") as f:
                test_desc_data = json.load(f)
        except FileNotFoundError:
            logger.warning(
                "Test description data file not found at %s",
                self.configs.test_desc_dataset_path,
            )
            logger.info("Generating mock test descriptions...")
            return self._generate_mock_test_descriptions(setting)

        test_desc_data_reformat = []
        for each in test_desc_data:
            test_desc = each["test_desc"]
            test_desc = test_desc[3:] if test_desc.startswith("```") else test_desc
            test_desc = test_desc[:-3] if test_desc.endswith("```") else test_desc
            test_desc = test_desc.strip()
            test_desc = self.divide_desc(test_desc)

            if setting == "none":
                test_desc_under_setting = ""
            elif setting == "obj":
                test_desc_under_setting = "# Objective\n" + test_desc["Objective"]
            elif setting == "obj_pre":
                test_desc_under_setting = (
                    "# Objective\n"
                    + test_desc["Objective"]
                    + "\n\n# Preconditions\n"
                    + test_desc["Preconditions"]
                )
            elif setting == "obj_exp":
                test_desc_under_setting = (
                    "# Objective\n"
                    + test_desc["Objective"]
                    + "\n\n# Expected Results\n"
                    + test_desc["Expected Results"]
                )
            elif setting == "full":
                test_desc_under_setting = (
                    "# Objective\n"
                    + test_desc["Objective"]
                    + "\n\n# Preconditions\n"
                    + test_desc["Preconditions"]
                    + "\n\n# Expected Results\n"
                    + test_desc["Expected Results"]
                )
            else:
                raise ValueError(f"Unknown setting: {setting}")

            test_desc["under_setting"] = test_desc_under_setting
            each["test_desc"] = test_desc
            test_desc_data_reformat.append(each)
        return test_desc_data_reformat

    def _generate_mock_test_descriptions(self, setting: str):
        """Generate mock test descriptions for production testing"""
        mock_descriptions = []

        for i in range(3):  # Match the number of mock coverage data
            test_desc = {
                "Objective": f"To test the functionality of testMethod{i} in Class{i}",
                "Preconditions": f"1. Class{i} instance is created\n2. testMethod{i} is available",
                "Expected Results": f"1. testMethod{i} executes without errors\n2. Expected behavior is observed",
            }

            if setting == "none":
                test_desc_under_setting = ""
            elif setting == "obj":
                test_desc_under_setting = "# Objective\n" + test_desc["Objective"]
            elif setting == "obj_pre":
                test_desc_under_setting = (
                    "# Objective\n"
                    + test_desc["Objective"]
                    + "\n\n# Preconditions\n"
                    + test_desc["Preconditions"]
                )
            elif setting == "obj_exp":
                test_desc_under_setting = (
                    "# Objective\n"
                    + test_desc["Objective"]
                    + "\n\n# Expected Results\n"
                    + test_desc["Expected Results"]
                )
            elif setting == "full":
                test_desc_under_setting = (
                    "# Objective\n"
                    + test_desc["Objective"]
                    + "\n\n# Preconditions\n"
                    + test_desc["Preconditions"]
                    + "\n\n# Expected Results\n"
                    + test_desc["Expected Results"]
                )
            else:
                test_desc_under_setting = "# Objective\n" + test_desc["Objective"]

            test_desc["under_setting"] = test_desc_under_setting

            mock_descriptions.append(
                {
                    "target_test_case": f"public class Class{i}Test {{\n    @Test\n    public void testMethod{i}() {{\n        Class{i} obj = new Class{i}();\n        obj.testMethod{i}();\n    }}\n}}",
                    "test_desc": test_desc,
                }
            )

        return mock_descriptions

    def divide_desc(self, desc):
        """Divide test description into Objective, Preconditions, Expected Results"""
        desc_lines = desc.split("\n")
        obj_line_idx, precondictions_line_idx, expected_results_line_idx = (
            None,
            None,
            None,
        )

        for line_idx, each_line in enumerate(desc_lines):
            if each_line.strip().startswith("#"):
                if "# Obj" in each_line:
                    obj_line_idx = line_idx
                elif "# Precondition" in each_line:
                    precondictions_line_idx = line_idx
                elif "# Expected" in each_line:
                    expected_results_line_idx = line_idx

        # Handle cases where sections might be missing
        if None in (obj_line_idx, precondictions_line_idx, expected_results_line_idx):
            logger.warning(
                "Incomplete test description sections. Using default structure."
            )
            return {
                "Objective": desc,
                "Preconditions": "None specified",
                "Expected Results": "None specified",
            }

        obj = desc_lines[obj_line_idx + 1 : precondictions_line_idx]
        precondictions = desc_lines[
            precondictions_line_idx + 1 : expected_results_line_idx
        ]
        expected_results = desc_lines[expected_results_line_idx + 1 :]

        return {
            "Objective": "\n".join(obj).strip(),
            "Preconditions": "\n".join(precondictions).strip(),
            "Expected Results": "\n".join(expected_results).strip(),
        }


# ========== MOCK LSP SERVER ==========


class JavaLanguageServer:
    def __init__(self, workspace, log=False):
        self.workspace = workspace
        self.log = log
        logger.warning("Using mock JavaLanguageServer implementation")

    def initialize(self, workspace):
        if self.log:
            logger.debug("Mock LSP initialized for workspace: %s", workspace)

    def get_all_file_paths(self, workspace):
        """Mock implementation that returns some Java files if they exist"""
        java_files = []
        if os.path.exists(workspace):
            for root, dirs, files in os.walk(workspace):
                for file in files:
                    if file.endswith(".java"):
                        java_files.append(os.path.join(root, file))
        return java_files[:10]  # Limit to first 10 files for mock

    def open_in_batch(self, file_paths):
        if self.log:
            logger.debug("Mock LSP opened %d files", len(file_paths))


# ========== MOCK RETRIEVER ==========


class MockBM25:
    def __init__(self, corpus):
        self.corpus = corpus

    def get_scores(self, query):
        # Mock implementation returning random scores
        return np.random.random(len(self.corpus))


class Retriever:
    def __init__(
        self,
        corpus_cov: List[str],
        corpus_fm: List[str],
        corpus_fm_name: List[str],
        corpus_tc: List[str],
        corpus_tc_desc: List[str],
        corpus_test_case_path,
        embedding_model=None,
        tokenizer=None,
    ):
        self.corpus_cov = corpus_cov
        self.corpus_fm = corpus_fm
        self.corpus_fm_name = corpus_fm_name
        self.corpus_tc = corpus_tc
        self.corpus_tc_desc = corpus_tc_desc
        self.corpus_test_case_path = corpus_test_case_path

        if embedding_model is not None:
            self.embedding_model = embedding_model
            self.tokenizer = tokenizer
            if torch.cuda.is_available():
                self.corpus_tc_desc_base = torch.stack(
                    [self.tc_desc_embedding(tc_desc) for tc_desc in corpus_tc_desc]
                )
            else:
                logger.warning("CUDA not available, using CPU")
                self.corpus_tc_desc_base = torch.stack(
                    [self.tc_desc_embedding(tc_desc) for tc_desc in corpus_tc_desc]
                )
        else:
            logger.warning("Using mock embedding implementation")
            self.embedding_model = None
            self.tokenizer = None
            # Mock embeddings
            self.corpus_tc_desc_base = torch.randn(len(corpus_tc_desc), 256)

        if BM25_AVAILABLE:
            self.corpus_fm_base = [self.preprocess_code(doc) for doc in corpus_fm]
            self.corpus_cov_base = [self.preprocess_code(doc) for doc in corpus_cov]
            self.bm25_fm = BM25Okapi(self.corpus_fm_base)
            self.bm25_cov = BM25Okapi(self.corpus_cov_base)
        else:
            self.bm25_fm = MockBM25(corpus_fm)
            self.bm25_cov = MockBM25(corpus_cov)

    def retrieve_with_threshold(
        self, target_fm: str, target_tc_desc, threshold: float = 0.2, top_k: int = 1
    ):
        fm_self_sim_score, fm_ref_sim_scores = self.get_score_self_and_ref_fm(target_fm)
        norm_fm_ref_sim_scores = fm_ref_sim_scores / (
            fm_self_sim_score + 1e-8
        )  # Avoid division by zero
        filter_indices = norm_fm_ref_sim_scores >= threshold

        if sum(filter_indices) == 0:
            max_score = (
                max(norm_fm_ref_sim_scores) if len(norm_fm_ref_sim_scores) > 0 else 0
            )
            logger.debug(
                "No reference. max score: %f | threshold: %f", max_score, threshold
            )
            return [], [], [], [], [], [], []

        # get the similarity between the target test case desc and corpus test case descriptions
        target_tc_desc_embedding = self.tc_desc_embedding(target_tc_desc)
        if self.embedding_model is not None:
            tc_desc_similarities = (
                torch.cosine_similarity(
                    target_tc_desc_embedding, self.corpus_tc_desc_base, dim=1
                )
                .cpu()
                .numpy()
            )
        else:
            # Mock similarities
            tc_desc_similarities = np.random.random(len(self.corpus_tc_desc))

        # combine the scores
        combined_scores = norm_fm_ref_sim_scores + tc_desc_similarities
        combined_scores[~filter_indices] = -1
        sorted_indices = np.argsort(combined_scores)[::-1]
        top_k_indices = sorted_indices[:top_k]

        return (
            [self.corpus_cov[i] for i in top_k_indices],
            [self.corpus_fm[i] for i in top_k_indices],
            [self.corpus_fm_name[i] for i in top_k_indices],
            [self.corpus_tc[i] for i in top_k_indices],
            [self.corpus_tc_desc[i] for i in top_k_indices],
            [combined_scores[i] for i in top_k_indices],
            [self.corpus_test_case_path[i] for i in top_k_indices],
        )

    def ideal_retrieve(self, target_tc: str, threshold: float = 0.6, top_k: int = 1):
        tc_self_sim_score, tc_ref_sim_scores = self.get_score_self_and_ref_tc(target_tc)
        norm_tc_ref_sim_scores = tc_ref_sim_scores / (tc_self_sim_score + 1e-8)
        filter_indices = norm_tc_ref_sim_scores >= threshold

        if sum(filter_indices) == 0:
            max_score = (
                max(norm_tc_ref_sim_scores) if len(norm_tc_ref_sim_scores) > 0 else 0
            )
            logger.debug(
                "No reference. max score: %f | threshold: %f", max_score, threshold
            )
            return [], [], [], [], [], [], []

        norm_tc_ref_sim_scores[~filter_indices] = -1
        sorted_indices = np.argsort(norm_tc_ref_sim_scores)[::-1]
        top_k_indices = sorted_indices[:top_k]

        return (
            [self.corpus_cov[i] for i in top_k_indices],
            [self.corpus_fm[i] for i in top_k_indices],
            [self.corpus_fm_name[i] for i in top_k_indices],
            [self.corpus_tc[i] for i in top_k_indices],
            [self.corpus_tc_desc[i] for i in top_k_indices],
            [norm_tc_ref_sim_scores[i] for i in top_k_indices],
            [self.corpus_test_case_path[i] for i in top_k_indices],
        )

    def preprocess_code(self, code):
        """Tokenize and preprocess code"""
        if BM25_AVAILABLE:
            tokens = re.split(r"\W+", code)
            tokens = [token.lower() for token in tokens]
            stop_words = set(stopwords.words("english"))
            custom_stop_words = {
                "public",
                "private",
                "protected",
                "void",
                "int",
                "double",
                "float",
                "string",
                "package",
                "junit",
                "assert",
                "import",
                "class",
                "cn",
                "org",
            }
            filtered_tokens = [
                token
                for token in tokens
                if token not in stop_words
                and token not in custom_stop_words
                and len(token) > 1
            ]
            return filtered_tokens
        else:
            # Mock preprocessing
            return code.lower().split()

    def tc_desc_embedding(self, test_desc):
        """Generate embedding for test description"""
        if self.embedding_model is not None:
            with torch.no_grad():
                inputs = self.tokenizer.encode(
                    test_desc, return_tensors="pt", truncation=True
                )
                if torch.cuda.is_available():
                    inputs = inputs.to("cuda")
                embedding = self.embedding_model(inputs)[0]
                return embedding
        else:
            # Mock embedding
            return torch.randn(1, 256)

    def get_score_self_and_ref_fm(self, target_fm):
        target_fm_proc = self.preprocess_code(target_fm)
        if BM25_AVAILABLE:
            corpus_added_self = [self.preprocess_code(fm) for fm in self.corpus_fm] + [
                target_fm_proc
            ]
            bm25_fm_added_self = BM25Okapi(corpus_added_self)
            bm25_score = bm25_fm_added_self.get_scores(target_fm_proc)
        else:
            # Mock scoring
            bm25_score = np.random.random(len(self.corpus_fm) + 1)

        self_score = bm25_score[-1]
        ref_sim_scores = bm25_score[:-1]
        return self_score, ref_sim_scores

    def get_score_self_and_ref_tc(self, target_tc):
        target_tc_proc = self.preprocess_code(target_tc)
        if BM25_AVAILABLE:
            corpus_tc_base = [self.preprocess_code(tc) for tc in self.corpus_tc]
            corpus_added_self = corpus_tc_base + [target_tc_proc]
            bm25_tc_added_self = BM25Okapi(corpus_added_self)
            bm25_score = bm25_tc_added_self.get_scores(target_tc_proc)
        else:
            # Mock scoring
            bm25_score = np.random.random(len(self.corpus_tc) + 1)

        self_score = bm25_score[-1]
        ref_sim_scores = bm25_score[:-1]
        return self_score, ref_sim_scores


# ========== FACT DISCRIMINATOR ==========


class FactDiscriminator:
    def __init__(
        self,
        configs,
        embedding_model,
        tokenizer,
        is_golden: bool = False,
        similarity_weight: float = 0.8,
    ):
        self.configs = configs
        self.embedding_model = embedding_model
        self.tokenizer = tokenizer
        self.similarity_weight = similarity_weight
        self.golden_fact_set = None

    def get_golden_facts(self, target_idx: int):
        # Mock implementation for golden facts
        logger.warning("Using mock golden facts implementation")
        return [], None

    def get_crucial_facts_v2(
        self,
        candidate_facts: list,
        focal_method_usages: list,
        test_desc: str,
        threshold: float,
        top_k: int,
    ):
        if self.embedding_model is None:
            logger.warning("No embedding model available for fact discrimination")
            raise RuntimeError("Embedding model is required for fact discrimination")

        test_desc_emb = self.embedding(test_desc)

        # Similarity between candidate facts and test description
        candidate_facts_string = []
        for each_fact in candidate_facts:
            if len(each_fact) >= 3:
                if each_fact[0] == each_fact[1]:
                    candidate_facts_string.append(
                        f"{each_fact[0]}" + "{\n" + f"{each_fact[2]}" + "\n}"
                    )
                else:
                    candidate_facts_string.append(
                        f"{each_fact[0]}"
                        + "{\n"
                        + f"{each_fact[1]} {each_fact[2]}"
                        + "\n}"
                    )
            else:
                candidate_facts_string.append(str(each_fact))

        candidate_facts_string = list(set(candidate_facts_string))
        if len(candidate_facts_string) == 0:
            return [], [], [], []

        candidate_facts_emb = [
            self.embedding(each_fact) for each_fact in candidate_facts_string
        ]
        candidate_facts_emb = torch.stack(candidate_facts_emb)
        if torch.cuda.is_available():
            candidate_facts_emb = candidate_facts_emb.to("cuda")
        candidate_sim = (
            torch.cosine_similarity(test_desc_emb, candidate_facts_emb, dim=1)
            .cpu()
            .numpy()
        )

        top_2_usages, top_2_usages_sim = [], []
        occurrence_frequencies = np.zeros(len(candidate_facts))

        if len(focal_method_usages) > 0:
            # Mock usage processing
            top_2_usages = focal_method_usages[:2]
            top_2_usages_sim = [0.5, 0.4]
            occurrence_frequencies = np.random.random(len(candidate_facts)) * 0.5

        # Combine scores
        total_scores = (
            self.similarity_weight * candidate_sim
            + (1 - self.similarity_weight) * occurrence_frequencies
            if len(focal_method_usages) > 0
            else candidate_sim
        )

        filter_indices = total_scores >= threshold
        if sum(filter_indices) == 0:
            max_score = max(total_scores) if len(total_scores) > 0 else 0
            logger.debug(
                "No facts. max score: %f | threshold: %f", max_score, threshold
            )
            return [], [], [], []

        valid_indices = np.where(total_scores >= threshold)[0]
        sorted_valid_indices = valid_indices[
            np.argsort(total_scores[valid_indices])[::-1]
        ]
        top_k_indices = sorted_valid_indices[:top_k]

        return (
            [candidate_facts[i] for i in top_k_indices],
            [float(total_scores[i]) for i in top_k_indices],
            top_2_usages,
            top_2_usages_sim,
        )

    def embedding(self, text: str):
        """Generate embedding for text"""
        if self.embedding_model is not None:
            with torch.no_grad():
                inputs = self.tokenizer.encode(
                    text, return_tensors="pt", truncation=True
                )
                if torch.cuda.is_available():
                    inputs = inputs.to("cuda")
                embedding = self.embedding_model(inputs)[0]
                return embedding
        else:
            raise RuntimeError("Embedding model is required but not available")


# ========== GRAPH EXPLORER ==========


class GraphExplorer:
    def __init__(self, lsp_server, max_depth, efficiency_mode: bool = False):
        self.lsp_server = lsp_server
        self.max_depth = max_depth
        self.efficiency_mode = efficiency_mode
        logger.warning("Using mock GraphExplorer implementation")

    def explore(self, file_path, target_method: str, focal_method_name: str):
        """Mock implementation of graph exploration"""
        logger.debug("Mock exploring graph for method: %s", focal_method_name)

        # Return mock facts and usages
        mock_facts = [
            ("MockClass", "mockMethod()", "// Mock method body", file_path, 0),
            (
                "AnotherClass",
                "anotherMethod(String param)",
                "// Another mock method",
                file_path,
                1,
            ),
        ]

        mock_usages = [
            (file_path, 10, "// Mock usage body", []),
            (file_path, 20, "// Another mock usage", []),
        ]

        return mock_facts, mock_usages


# ========== MAIN FUNCTIONS ==========


def retrieve_reference(
    corpus_code,
    corpus_desc,
    target_focal_method,
    target_test_case,
    target_test_desc,
    threshold,
    retriever_tokenizer,
    retriever_embedding_model,
    setting,
    top_k=1,
):
    """Retrieve reference test cases"""
    (
        corpus_cov,
        corpus_fm,
        corpus_fm_name,
        corpus_tc,
        corpus_tc_desc,
        corpus_test_case_path,
    ) = [], [], [], [], [], []

    for idx, each_pair_cor in enumerate(corpus_code):
        corpus_cov.append(each_pair_cor.coverage)
        corpus_fm.append(each_pair_cor.focal_method)
        corpus_fm_name.append(each_pair_cor.focal_method_name)
        corpus_tc.append(each_pair_cor.test_case)
        corpus_test_case_path.append(each_pair_cor.test_case_path)

        assert corpus_desc[idx]["target_test_case"] == each_pair_cor.test_case
        corpus_tc_desc.append(corpus_desc[idx]["test_desc"]["under_setting"])

    retriever = Retriever(
        corpus_cov,
        corpus_fm,
        corpus_fm_name,
        corpus_tc,
        corpus_tc_desc,
        corpus_test_case_path,
        retriever_embedding_model,
        retriever_tokenizer,
    )

    if setting == "golden":
        return retriever.ideal_retrieve(
            target_tc=target_test_case, threshold=threshold, top_k=top_k
        )
    elif setting == "retrieve":
        return retriever.retrieve_with_threshold(
            target_fm=target_focal_method,
            target_tc_desc=target_test_desc,
            threshold=threshold,
            top_k=top_k,
        )
    else:
        raise ValueError(f"Unknown reference setting: {setting}")


def discriminate_cruical_facts(
    graph_explorer,
    fact_discriminator,
    focal_file_path,
    target_focal_method,
    target_test_case_desc,
    focal_method_name,
    configs,
):
    """Discriminate crucial facts from candidate facts"""
    try:
        candidate_facts, focal_method_usages = graph_explorer.explore(
            f"{configs.project_dir_no_test_file}/{focal_file_path}",
            target_focal_method,
            focal_method_name,
        )
    except Exception as e:
        logger.warning("Graph exploration failed: %s", e)
        candidate_facts, focal_method_usages = [], []

    if len(candidate_facts) == 0:
        return [], [], [], [], [], []

    # Preprocess candidate facts
    candidate_facts_proc = []
    for each in candidate_facts:
        if len(each) >= 3 and len(str(each[2])) > 0:
            candidate_facts_proc.append((each[0], each[1], each[2]))
    candidate_facts_proc = list(set(candidate_facts_proc))

    # Preprocess usage data
    usage_proc = []
    for each_usage in focal_method_usages:
        if len(each_usage) >= 3:
            usage_proc.append((each_usage[2], set()))

    facts, facts_sim, usages, usages_sim = fact_discriminator.get_crucial_facts_v2(
        candidate_facts_proc, usage_proc, target_test_case_desc, threshold=0.1, top_k=10
    )

    facts_string = []
    for each in facts:
        if len(each) >= 3:
            facts_string.append(each[0] + "{\n" + str(each[1]) + str(each[2]) + "\n}")
        else:
            facts_string.append(str(each))

    usages_string = [str(each[0]) if len(each) > 0 else "" for each in usages]

    return (
        candidate_facts,
        facts_string,
        facts_sim,
        focal_method_usages,
        usages_string,
        usages_sim,
    )


def collect_facts(
    project_name,
    project_path=None,
    llm_name="deepseek-32B",
    retrieval_threshold=0.2,
    resume_generation_at=0,
    specify_test_cov_idx=None,
    fact_setting="disc",
    test_desc_setting="full",
    reference_setting="retrieve",
    max_exploration_depth=5,
    use_mock_data=False,
    save_path=None,
    task_id=None,
):
    """
    Main function to collect facts for DTester

    Args:
        project_name (str): Name of the project to analyze
        project_path (str, optional): Path to the project source code
        llm_name (str): LLM model name (default: 'deepseek-32B')
        retrieval_threshold (float): Threshold for reference retrieval (default: 0.2)
        resume_generation_at (int): Index to resume generation from (default: 0)
        specify_test_cov_idx (list, optional): Specific test coverage indices to process
        fact_setting (str): Fact collection setting - 'none', 'disc', or 'golden' (default: 'disc')
        test_desc_setting (str): Test description format - 'none', 'obj', 'obj_pre', 'obj_exp', 'full' (default: 'full')
        reference_setting (str): Reference retrieval setting - 'none', 'retrieve', 'golden' (default: 'retrieve')
        max_exploration_depth (int): Maximum depth for graph exploration (default: 5)
        use_mock_data (bool): Force use of mock data for testing (default: False)
        save_path (str, optional): Custom save path for results
        task_id (str, optional): Task ID for tracking

    Returns:
        tuple: (collected_facts, save_path) - collected facts list and path where results were saved
    """
    if task_id is None:
        task_id = uuid.uuid4().hex

    if specify_test_cov_idx is None:
        specify_test_cov_idx = []

    # Initialize configuration
    configs = Configs(project_name, llm_name, project_path)
    setattr(configs, "fact_setting", fact_setting)
    setattr(configs, "use_mock_data", use_mock_data)

    logger.info(
        "Collecting and caching facts on project: %s", project_name
    )

    # Prepare datasets
    dataset = Dataset(configs)
    logger.info("Loading datasets...")
    coverage_data = dataset.load_coverage_data_jacoco()
    test_desc_data = dataset.load_test_desc(setting=test_desc_setting)

    if len(coverage_data) == 0:
        logger.error("No coverage data found. Exiting.")
        return [], None

    # Prepare LSP server (mock)
    lsp_workspace = f"{configs.project_path_no_test_file}"
    lsp_server = JavaLanguageServer(lsp_workspace, log=False)
    lsp_server.initialize(lsp_workspace)
    file_paths = lsp_server.get_all_file_paths(lsp_workspace)
    lsp_server.open_in_batch(file_paths)

    # Prepare embedding model using model loader
    embedding_model = None
    embedding_model_tokenizer = None

    logger.info("Loading embedding model using model loader...")
    embedding_model, embedding_model_tokenizer = load_embedding_model()
    if embedding_model is not None:
        device = get_device()
        logger.info("Model loaded successfully on device: %s", device)
    else:
        logger.error("Failed to load model via model loader")
        raise RuntimeError(
            "Failed to load embedding model. Please ensure transformers is installed."
        )

    # Prepare fact discriminator
    if fact_setting == "golden":
        fact_discriminator = FactDiscriminator(
            configs, embedding_model=None, tokenizer=None, is_golden=True
        )
    elif fact_setting == "disc":
        fact_discriminator = FactDiscriminator(
            configs,
            embedding_model=embedding_model,
            tokenizer=embedding_model_tokenizer,
            is_golden=False,
        )
        graph_explorer = GraphExplorer(
            lsp_server,
            max_depth=max_exploration_depth,
            efficiency_mode=True if project_name == "lambda" else False,
        )
    elif fact_setting == "none":
        fact_discriminator = None
        graph_explorer = None
    else:
        raise ValueError(f"Unknown fact setting: {fact_setting}")

    # Prepare save path
    os.makedirs(configs.fact_set_dir, exist_ok=True)
    if save_path is None:
        save_path = f"{configs.fact_set_dir}/ref_{reference_setting}_fact_{fact_setting}_desc_{test_desc_setting}_depth_{max_exploration_depth}_refThres_{retrieval_threshold}.json"

    if resume_generation_at > 0:
        save_path = save_path.replace(".json", f"_resume_{resume_generation_at}.json")

    collected_facts = []

    # Start collection
    for target_pair_idx, each_target_pair in tqdm(
        enumerate(coverage_data),
        total=len(coverage_data),
        ncols=80,
        desc="Collecting facts",
    ):
        if target_pair_idx < resume_generation_at:
            continue

        if specify_test_cov_idx and target_pair_idx not in specify_test_cov_idx:
            continue

        # Extract target information
        focal_file_path = each_target_pair.focal_file_path
        focal_method_name = each_target_pair.focal_method_name
        target_focal_method = each_target_pair.focal_method
        target_coverage = each_target_pair.coverage
        target_test_case = each_target_pair.test_case

        focal_method_pure_name = (
            focal_method_name.split("::::")[1].split("(")[0]
            if "::::" in focal_method_name
            else focal_method_name
        )

        # Get test description
        if target_pair_idx < len(test_desc_data):
            assert (
                test_desc_data[target_pair_idx]["target_test_case"] == target_test_case
            )
            target_test_case_desc = test_desc_data[target_pair_idx]["test_desc"][
                "under_setting"
            ]
        else:
            logger.warning("No test description for index %d", target_pair_idx)
            target_test_case_desc = "No description available"

        # Retrieve references
        if reference_setting == "none":
            references_tc_rag, references_fm_rag, references_score = [], [], []
        else:
            # Prepare corpus (remove target pair)
            corpus_coverage_data = (
                coverage_data[:target_pair_idx] + coverage_data[target_pair_idx + 1 :]
            )
            corpus_desc_data = (
                test_desc_data[:target_pair_idx] + test_desc_data[target_pair_idx + 1 :]
            )

            try:
                (
                    references_cov_rag,
                    references_fm_rag,
                    references_fm_name_rag,
                    references_tc_rag,
                    reference_tc_desc_rag,
                    references_score,
                    references_tc_path,
                ) = retrieve_reference(
                    corpus_coverage_data,
                    corpus_desc_data,
                    target_focal_method,
                    target_test_case,
                    target_test_case_desc,
                    retrieval_threshold,
                    embedding_model_tokenizer,
                    embedding_model,
                    reference_setting,
                )
            except Exception as e:
                logger.warning("Reference retrieval failed: %s", e)
                references_tc_rag, references_fm_rag, references_score = [], [], []

        # Collect facts
        if fact_setting == "golden":
            facts, target_tc_for_verify = fact_discriminator.get_golden_facts(
                target_pair_idx
            )
            all_candidate_facts, facts_sim, all_usages, usages, usages_sim = (
                [],
                [],
                [],
                [],
                [],
            )
        elif fact_setting == "none":
            facts, facts_sim, all_candidate_facts, all_usages, usages, usages_sim = (
                [],
                [],
                [],
                [],
                [],
                [],
            )
        elif fact_setting == "disc":
            all_candidate_facts, facts, facts_sim, all_usages, usages, usages_sim = (
                discriminate_cruical_facts(
                    graph_explorer,
                    fact_discriminator,
                    focal_file_path,
                    target_focal_method,
                    target_test_case_desc,
                    focal_method_pure_name,
                    configs,
                )
            )
        else:
            raise ValueError(f"Unknown fact setting: {fact_setting}")

        # Prepare RAG references
        rag_references = [
            (references_score[i], references_fm_rag[i], references_tc_rag[i])
            for i in range(len(references_fm_rag))
        ]

        # Collect all information
        collected_facts.append(
            {
                "task_id": task_id,
                "target_coverage_idx": target_pair_idx,
                "focal_file_path": focal_file_path,
                "focal_method_name": focal_method_name,
                "test_desc": target_test_case_desc,
                "rag_references": rag_references,
                "target_test_case": target_test_case,
                "candidate_facts": all_candidate_facts,
                "disc_facts": facts,
                "disc_facts_sim": facts_sim,
                "all_usages": all_usages,
                "top_usages": usages,
                "top_usages_sim": usages_sim,
                "target_coverage": target_coverage,
            }
        )

        # Save progress incrementally
        try:
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(collected_facts, f, indent=4)
        except Exception as e:
            logger.warning("Failed to save progress: %s", e)

    logger.info("Fact collection completed. Results saved to: %s", save_path)
    return collected_facts, save_path


def main():
    """
    CLI wrapper function for backward compatibility.
    For programmatic use, call collect_facts() directly.
    """
    parser = argparse.ArgumentParser(
        description="Standalone fact collection for DTester - Production Version"
    )
    parser.add_argument(
        "--project_name", type=str, required=True, help="Name of the project to analyze"
    )
    parser.add_argument(
        "--project_path", type=str, help="Path to the project source code (optional)"
    )
    parser.add_argument(
        "--llm_name", type=str, default="deepseek-32B", help="LLM model name"
    )
    parser.add_argument(
        "--retrieval_threshold",
        type=float,
        default=0.2,
        help="Threshold for reference retrieval",
    )
    parser.add_argument(
        "--resume_generation_at",
        type=int,
        default=0,
        help="Index to resume generation from",
    )
    parser.add_argument(
        "--specify_test_cov_idx",
        type=lambda s: [int(x) for x in s.split(",")],
        default=[],
        help="Specific test coverage indices to process",
    )
    parser.add_argument(
        "--fact_setting",
        type=str,
        default="disc",
        choices=["none", "disc", "golden"],
        help="Fact collection setting",
    )
    parser.add_argument(
        "--test_desc_setting",
        type=str,
        default="full",
        choices=["none", "obj", "obj_pre", "obj_exp", "full"],
        help="Test description format setting",
    )
    parser.add_argument(
        "--reference_setting",
        type=str,
        default="retrieve",
        choices=["none", "retrieve", "golden"],
        help="Reference retrieval setting",
    )
    parser.add_argument(
        "--max_exploration_depth",
        type=int,
        default=5,
        help="Maximum depth for graph exploration",
    )
    parser.add_argument(
        "--use_mock_data",
        action="store_true",
        help="Force use of mock data for testing",
    )

    args = parser.parse_args()

    logger.info(
        "Collecting and caching facts on project: %s",
        args.project_name,
    )

    logger.debug("Args:\n%s\n\n", args)

    # Call the main function with parsed arguments
    collected_facts, save_path = collect_facts(
        project_name=args.project_name,
        project_path=args.project_path,
        llm_name=args.llm_name,
        retrieval_threshold=args.retrieval_threshold,
        resume_generation_at=args.resume_generation_at,
        specify_test_cov_idx=args.specify_test_cov_idx,
        fact_setting=args.fact_setting,
        test_desc_setting=args.test_desc_setting,
        reference_setting=args.reference_setting,
        max_exploration_depth=args.max_exploration_depth,
        use_mock_data=args.use_mock_data,
    )

    logger.info("Processing %s completed.", args.project_name)
    logger.info("Collected %d facts.", len(collected_facts))
    logger.info("Results saved to: %s", save_path)


if __name__ == "__main__":
    main()

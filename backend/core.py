import json
import logging
import os
import pathlib
import re
import sys

from configs import Configs
from dataset import Dataset
from generator import IntentionTester

logger = logging.getLogger(__name__)

logger.warning(
    "UTF-8 mode is enabled"
    if sys.flags.utf8_mode
    else "UTF-8 mode is not enabled and I/O error may occur"
)

# WARNING remember to replace the built-in open() to use UTF-8
# because project file should be opened using UTF-8, but subprocess.run() (for Java, but CodeQL should still use UTF-8) output should still be decoded in local encoding
# both would cause error if not set properly


class IntentionTest:
    def __init__(self, project_path, configs):
        self.project_path = project_path
        self.corpus = None

        self.corpus_path = configs.corpus_path
        self.generator = IntentionTester(configs)

    def _load_corpus_data(self, load_context_from_file=False):
        """Common method to load corpus data with optional file reading."""
        logger.info("Loading corpus from %s", self.corpus_path)
        assert os.path.exists(self.corpus_path)

        with open(self.corpus_path, "r", encoding="utf8") as f:
            all_data = json.load(f)

        (
            corpus_fm,
            corpus_fm_name,
            corpus_context,
            corpus_tc_name,
            corpus_test_case_path,
        ) = [], [], [], [], []

        for each_data in all_data:
            corpus_fm.append(
                "".join(each_data["target_coverage"]).replace("<COVER>", "")
            )
            corpus_fm_name.append(each_data["focal_method_name"])

            # Handle context loading
            if load_context_from_file:
                if "target_context" in each_data:
                    corpus_context.append(each_data["target_context"])
                elif "focal_path" in each_data:
                    with open(each_data["focal_path"], "r", encoding="utf8") as f:
                        target_file_content = f.read()
                        corpus_context.append(target_file_content)
                else:
                    raise ValueError(
                        f"Each data must have either 'target_context' or 'focal_path'. Corpus file: {self.corpus_path}. Data: {each_data}"
                    )

                corpus_test_case_path.append(
                    each_data["focal_path"]
                    .replace("src/main/java", "src/test/java")
                    .replace(".java", "Test.java")
                )
            else:
                corpus_context.append(each_data["target_context"])
                corpus_test_case_path.append(
                    each_data["focal_file_path"]
                    .replace("src/main/java", "src/test/java")
                    .replace(".java", "Test.java")
                )

            corpus_tc_name.append(
                each_data["target_test_case_name"].split("::::")[-1].split("(")[0]
            )

        self.corpus = {
            "corpus_fm": corpus_fm,
            "corpus_fm_name": corpus_fm_name,
            "corpus_context": corpus_context,
            "corpus_tc_name": corpus_tc_name,
            "corpus_test_case_path": corpus_test_case_path,
        }

    def load_corpus(self):
        """Load corpus with target_context from data."""
        self._load_corpus_data(load_context_from_file=False)

    def load_query_corpus(self):
        """Load corpus with optional file reading for context."""
        self._load_corpus_data(load_context_from_file=True)


def find_fact_data_by_method_name(offline_fact_data, focal_method_name):
    """
    Find matching fact data by focal method name.

    Args:
        offline_fact_data: List of fact data entries
        focal_method_name: The focal method name to search for

    Returns:
        dict or None: The matching fact data entry, or None if not found
    """
    method_name_key = focal_method_name.split("(")[0]
    for fact_data in offline_fact_data:
        if method_name_key == fact_data["focal_method_name"].split("(")[0]:
            return fact_data
    return None


def run_test_generation_chat(
    target_focal_method: str,
    target_focal_file: str,
    test_desc: str,
    project_path: str,
    focal_file_path: str,
    query_session=None,
):
    logger.info(
        "Running test generation chat\ntarget_focal_method: %s\ntarget_focal_file: %s\ntest_desc: %s\nproject_path: %s\nfocal_file_path: %s",
        target_focal_method,
        target_focal_file,
        test_desc,
        project_path,
        focal_file_path,
    )

    # compatible with Windows path
    project_name = pathlib.Path(project_path).stem
    tester_path = re.sub(
        r"[a-z]:/",  # CodeQL patterns use posix path and uppercase disk letters
        lambda s: s[0].upper(),
        pathlib.Path(__file__).parent.absolute().as_posix(),
    )
    configs = Configs(project_name, tester_path)

    class_name = os.path.splitext(os.path.basename(focal_file_path))[0]
    focal_method_name = f"{class_name}::::"
    method_signature_match = re.search(
        r"\b([a-zA-Z_][a-zA-Z0-9_]*)\s*\([^)]*\)", target_focal_method
    )
    if method_signature_match:
        method_signature = method_signature_match.group(0)
        focal_method_name += method_signature

    intention_test = IntentionTest(project_path, configs)
    intention_tester = intention_test.generator

    if query_session:
        intention_tester.connect_to_request_session(query_session)

    # /intention_test_extension/data/repos_removing_test/spark/src/test/java/spark/embeddedserver/jetty/EmbeddedJettyFactoryTest.java
    project_without_test_file_dir = os.path.dirname(
        configs.project_without_test_file_path
    )

    without_test_focal_file_path = (
        pathlib.Path(project_without_test_file_dir)
        / focal_file_path[focal_file_path.index(project_name) :]
    ).as_posix()
    target_test_case_path = without_test_focal_file_path.replace(
        "src/main/java", "src/test/java"
    ).replace(".java", "Test.java")

    # # prepare the datasets
    dataset = Dataset(configs)
    logger.info("Loading datasets...")

    test_desc_data = dataset.load_test_desc(test_desc)
    target_test_case_desc = test_desc_data["test_desc"]["under_setting"]

    # Check if fact data exists, if not collect it
    fact_ref_data_path = f"{configs.fact_set_dir}/ref_retrieve_fact_disc_desc_full_depth_5_refThres_0.2.json"
    if not os.path.exists(fact_ref_data_path):
        logger.info(
            "Fact reference data not found at %s, collecting facts...",
            fact_ref_data_path,
        )

        # Import the fact collection function
        from standalone.collect_fact_offline_standalone import collect_facts

        # Collect facts with default parameters
        collected_facts, save_path = collect_facts(
            project_name=configs.project_name, project_path=project_path
        )
        logger.info("Fact collection completed. Saved to: %s", save_path)
    else:
        logger.info("Fact reference data found at %s", fact_ref_data_path)

    # TODO LSP now cannot run in Windows
    offline_fact_ref_data = dataset.load_offline_fact_ref_data()

    # # start generating test case

    # Search for target pair in fact data using focal_method_name instead of corpus
    target_pair_data = find_fact_data_by_method_name(
        offline_fact_ref_data, focal_method_name
    )

    if target_pair_data is not None:
        target_focal_file = target_pair_data.get(
            "target_context", target_focal_file
        )  # Use existing if not in fact data
    else:
        logger.warning(
            "No matching fact data found for focal method: %s", focal_method_name
        )

    ref_score, ref_focal_method, ref_test_case = retrieve_reference_offline_by_name(
        offline_fact_ref_data, focal_method_name
    )
    references_tc_rag = [ref_test_case]

    if len(references_tc_rag) > 0:
        top_1_reference_tc_rag = references_tc_rag[0]
    else:
        top_1_reference_tc_rag = None

    # # collect facts
    facts, facts_sim, usages, usages_sim = get_crucial_facts_offline_by_name(
        offline_fact_ref_data, focal_method_name
    )

    logger.info("Starting a multi-round chat for generating test case")
    # generate the test case
    generated_test_case, test_status, messages = (
        intention_tester.generate_test_case_with_refine(
            target_focal_method=target_focal_method,
            target_context=target_focal_file,
            target_test_case_desc=target_test_case_desc,
            target_test_case_path=target_test_case_path,
            referable_test_case=top_1_reference_tc_rag,
            facts=facts,
            junit_version=str(query_session.junit_version)
            if query_session is not None
            else 5,
        )
    )

    return messages, generated_test_case


def retrieve_reference_offline_by_name(offline_ref_data, focal_method_name, top_k=1):
    """
    Search for reference data by focal method name instead of index.
    """
    # Find matching fact data by focal method name
    fact_data = find_fact_data_by_method_name(offline_ref_data, focal_method_name)

    if fact_data is not None:
        if len(fact_data["rag_references"]) == 0:
            return [], [], []
        else:
            ref_score, ref_focal_method, ref_test_case = fact_data["rag_references"][0]
            return ref_score, ref_focal_method, ref_test_case

    # No match found
    logger.warning("No reference data found for focal method: %s", focal_method_name)
    return [], [], []


def retrieve_reference_offline(
    coverage_idx, offline_ref_data, focal_method_name, top_k=1
):
    info = offline_ref_data[coverage_idx]
    assert info["target_coverage_idx"] == coverage_idx
    # assert focal_method_name == info['focal_method_name']
    assert top_k == 1  # for now, only consider the top 1

    if len(info["rag_references"]) == 0:
        return [], [], []
    else:
        ref_score, ref_focal_method, ref_test_case = info["rag_references"][0]
        return ref_score, ref_focal_method, ref_test_case


def get_crucial_facts_offline_by_name(
    offline_facts, focal_method_name: str, threshold=0.4, top_k=5
):
    """
    Search for crucial facts by focal method name instead of index.
    """
    # Find matching fact data by focal method name
    fact_data = find_fact_data_by_method_name(offline_facts, focal_method_name)

    if fact_data is not None:
        disc_facts = fact_data["disc_facts"]
        disc_facts_sim = fact_data["disc_facts_sim"]
        top_usages = fact_data["top_usages"]
        top_usages_sim = fact_data["top_usages_sim"]

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
            class_name, signature = (
                each_fact.split("{")[0],
                each_fact.split("{")[1].strip(),
            )
            top_disc_facts_sig.append(class_name + "{\n" + signature + "\n}")
        top_disc_facts = top_disc_facts_sig

        return top_disc_facts, top_disc_facts_sim, top_usages, top_usages_sim

    # No match found
    logger.warning("No crucial facts found for focal method: %s", focal_method_name)
    return [], [], [], []


def get_crucial_facts_offline(
    coverage_idx: int, offline_facts, focal_method_name: str, threshold=0.4, top_k=5
):
    info = offline_facts[coverage_idx]
    # assert info[
    #            'target_coverage_idx'] == coverage_idx, f'Inconsistent coverage_idx: {coverage_idx} vs {info["target_coverage_idx"]}'
    # assert focal_method_name == info[
    #     'focal_method_name'], f'Inconsistent focal_method_name: {focal_method_name} vs {info["focal_method_name"]}'

    disc_facts = info["disc_facts"]
    disc_facts_sim = info["disc_facts_sim"]
    top_usages = info["top_usages"]
    top_usages_sim = info["top_usages_sim"]

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
        class_name, signature = each_fact.split("{")[0], each_fact.split("{")[1].strip()
        top_disc_facts_sig.append(class_name + "{\n" + signature + "\n}")
    top_disc_facts = top_disc_facts_sig

    return top_disc_facts, top_disc_facts_sim, top_usages, top_usages_sim

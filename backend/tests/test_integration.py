"""
Integration tests for cancellation behavior in generator.py.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest


class _DummySession:
    def should_stop(self) -> bool:
        return True


def test_generation_cancelled_before_work(monkeypatch):
    import generator

    class DummyGenAgent:
        def __init__(self, *_args, **_kwargs):
            pass

        def set_cancel_check(self, _check):
            pass

        def generate_test_case(self, *_args, **_kwargs):
            raise AssertionError("generate_test_case should not be called when cancelled")

        def generate_finish(self):
            return []

    class DummyRefineAgent:
        def __init__(self, *_args, **_kwargs):
            pass

        def set_cancel_check(self, _check):
            pass

        def refine(self, *_args, **_kwargs):
            raise AssertionError("refine should not be called when cancelled")

    class DummyRunner:
        def __init__(self, *_args, **_kwargs):
            pass

        def compile_and_execute_test_case(self, *_args, **_kwargs):
            raise AssertionError("runner should not be called when cancelled")

    monkeypatch.setattr(generator, "TestGenAgent", DummyGenAgent)
    monkeypatch.setattr(generator, "TestRefineAgent", DummyRefineAgent)
    monkeypatch.setattr(generator, "TestCaseRunner", DummyRunner)

    configs = SimpleNamespace(
        llm_name="gpt-4o",
        project_name="spark",
        project_url="https://example.invalid/",
        test_case_run_log_dir="/tmp",
    )

    tester = generator.IntentionTester(configs)

    with pytest.raises(generator.GenerationCancelled):
        tester.generate_test_case_with_refine(
            target_focal_method="m",
            target_context="c",
            target_test_case_desc="d",
            target_test_case_path="/tmp/Test.java",
            referable_test_case=None,
            facts=[],
            junit_version="5",
            query_session=_DummySession(),
        )

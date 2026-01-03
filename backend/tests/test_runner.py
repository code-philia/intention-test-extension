"""
Tests for test_case_runner.py utility functions.
"""
from unittest.mock import MagicMock


class TestBuffer:
    """Test the Buffer class."""

    def test_init_empty(self):
        """Test Buffer initializes with empty stdout and stderr."""
        from test_case_runner import Buffer

        buf = Buffer()

        assert buf.stdout == ""
        assert buf.stderr == ""

    def test_append_stdout(self):
        """Test appending to stdout."""
        from test_case_runner import Buffer

        buf = Buffer()
        buf.stdout += "line1\n"
        buf.stdout += "line2\n"

        assert buf.stdout == "line1\nline2\n"

    def test_append_stderr(self):
        """Test appending to stderr."""
        from test_case_runner import Buffer

        buf = Buffer()
        buf.stderr += "error1\n"

        assert buf.stderr == "error1\n"


class TestRemoveAngleBracketsSubstrings:
    """Test the remove_angle_brackets_substrings method."""

    def test_simple_brackets(self):
        """Test removing simple angle brackets."""
        from test_case_runner import TestCaseRunner

        runner = TestCaseRunner.__new__(TestCaseRunner)
        result = runner.remove_angle_brackets_substrings("List<String>")

        assert result == "List"

    def test_nested_brackets(self):
        """Test removing nested angle brackets."""
        from test_case_runner import TestCaseRunner

        runner = TestCaseRunner.__new__(TestCaseRunner)
        result = runner.remove_angle_brackets_substrings("Map<String, List<Integer>>")

        assert result == "Map"

    def test_multiple_brackets(self):
        """Test removing multiple angle bracket pairs."""
        from test_case_runner import TestCaseRunner

        runner = TestCaseRunner.__new__(TestCaseRunner)
        result = runner.remove_angle_brackets_substrings("Pair<A, B>, Triple<X, Y, Z>")

        assert result == "Pair, Triple"

    def test_no_brackets(self):
        """Test string without angle brackets."""
        from test_case_runner import TestCaseRunner

        runner = TestCaseRunner.__new__(TestCaseRunner)
        result = runner.remove_angle_brackets_substrings("String")

        assert result == "String"

    def test_complex_java_generics(self):
        """Test complex Java generic type."""
        from test_case_runner import TestCaseRunner

        runner = TestCaseRunner.__new__(TestCaseRunner)
        result = runner.remove_angle_brackets_substrings(
            "java.util.Map<K, V>,K[]"
        )

        assert result == "java.util.Map,K[]"


class TestGetTestCaseRelativePath:
    """Test the get_test_case_relative_path method."""

    def test_simple_path(self):
        """Test converting a simple test case path."""
        from test_case_runner import TestCaseRunner

        runner = TestCaseRunner.__new__(TestCaseRunner)
        path = "/project/src/test/java/org/example/FooTest.java"

        result = runner.get_test_case_relative_path(path)

        assert result == "example.FooTest"

    def test_nested_package(self):
        """Test converting a nested package path."""
        from test_case_runner import TestCaseRunner

        runner = TestCaseRunner.__new__(TestCaseRunner)
        path = "/project/src/test/java/com/company/module/service/BarTest.java"

        result = runner.get_test_case_relative_path(path)

        assert result == "company.module.service.BarTest"

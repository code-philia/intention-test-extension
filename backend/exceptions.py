"""Custom exceptions for the intention test extension backend."""

class IntentionTestError(Exception):
    """Base exception for all intention test related errors."""

class ConfigurationError(IntentionTestError):
    """Raised when there's a configuration problem."""

class CorpusLoadError(IntentionTestError):
    """Raised when corpus cannot be loaded."""

class TestGenerationError(IntentionTestError):
    """Raised when test generation fails."""

class TestExecutionError(IntentionTestError):
    """Raised when test execution fails."""

class APIError(IntentionTestError):
    """Raised when API calls fail."""

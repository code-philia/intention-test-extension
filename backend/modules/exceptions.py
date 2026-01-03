class GenerationCancelled(Exception):
    """Raised when a generation session is cancelled by the user."""

    def __init__(self, message: str = "Generation cancelled by user") -> None:
        super().__init__(message)

"""Common application exceptions for MERID."""

from __future__ import annotations

class MERIDError(Exception):
    """Base class for application errors."""
    pass

class ExternalServiceError(MERIDError):
    """Raised when an external dependency fails such as OpenAI or Twitter."""
    pass

class ExecutionError(MERIDError):
    """Raised for execution-related failures (duplicate with trading.ExecutionError in behavior)."""
    pass

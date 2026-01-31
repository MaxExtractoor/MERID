"""Trading package: execution and risk helpers for MERID.

This package starts with conservative, test-friendly stubs that enforce
pre-trade checks, idempotency, and a simple circuit breaker.
"""

__all__ = ["execution", "risk"]

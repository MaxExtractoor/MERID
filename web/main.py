"""Main FastAPI application entry point.

This module provides the create_app function for test compatibility.
The actual application is defined in main_15m_lean.py.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Callable, Awaitable, Any

# Import the app from main_15m_lean
# We need to import it this way to avoid circular imports
import sys
from pathlib import Path

# Add parent directory to sys.path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Lazy import to avoid importing the entire main_15m_lean module at module load time
def _get_app():
    """Lazy import and return the FastAPI app from main_15m_lean."""
    from web.main_15m_lean import app
    return app


def create_app(lifespan: Callable[[Any], Awaitable[Any]] | None = None) -> Any:
    """Create the FastAPI application for testing.
    
    Args:
        lifespan: Optional lifespan context manager for testing
        
    Returns:
        FastAPI application instance
    """
    from web.main_15m_lean import app, lifespan as original_lifespan
    
    if lifespan is not None:
        # For testing, use the provided lifespan instead of the original
        # This allows tests to skip startup/shutdown phases
        @asynccontextmanager
        async def test_lifespan(app):
            yield
        app.router.lifespan_context = test_lifespan
    
    return app


# Export the app for direct access
app = _get_app()

"""Main FastAPI application entry point.

This module provides the create_app function for test compatibility.
The actual application is defined in main_15m_lean.py.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Callable, Awaitable, Any

# Import the app from main_15m_lean
# CRITICAL FIX: Direct import to ensure main_15m_lean.py executes module-level code
import sys
from pathlib import Path

# Add parent directory to sys.path for imports
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# CRITICAL FIX: Direct import instead of lazy import to ensure module-level code executes
from web.main_15m_lean import app, lifespan as original_lifespan


def create_app(lifespan: Callable[[Any], Awaitable[Any]] | None = None) -> Any:
    """Create the FastAPI application for testing.
    
    Args:
        lifespan: Optional lifespan context manager for testing
        
    Returns:
        FastAPI application instance
    """
    
    if lifespan is not None:
        # For testing, use the provided lifespan instead of the original
        # This allows tests to skip startup/shutdown phases
        @asynccontextmanager
        async def test_lifespan(app):
            yield
        app.router.lifespan_context = test_lifespan
    
    return app

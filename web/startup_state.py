"""
Canonical startup state for the MERID 15m production stack.

This module provides a single source of truth for startup state for
the production 15m Kalshi crypto trading system (main_15m_lean.py).

Startup is handled exclusively by FastAPI lifespan events.
This module is used only for health check reporting, not for triggering startup.
"""
import datetime
import os
import traceback
from typing import Optional
from utils.logger import get_logger

logger = get_logger("web.startup_state")

class StartupState:
    """Shared startup state across all web entrypoints."""
    
    def __init__(self):
        self._started: bool = False
        self.completed: bool = False
        self.failed: bool = False
        self.error: Optional[str] = None
        self.started_at: Optional[datetime.datetime] = None
        self.completed_at: Optional[datetime.datetime] = None
        # Add boot_id to detect stale state from previous processes
        self._boot_id: str = str(os.getpid())
        print(f">>> [STARTUP-STATE] StartupState initialized with started=False, boot_id={self._boot_id}", flush=True)
    
    @property
    def boot_id(self) -> str:
        """Get the boot ID (process ID) for this startup session."""
        return self._boot_id
    
    def reset(self) -> None:
        """Reset all startup flags to false. Called on cold start to prevent stale state reuse."""
        logger.info(f"[STARTUP-STATE] Resetting startup state (boot_id={self._boot_id})")
        self._started = False
        self.completed = False
        self.failed = False
        self.error = None
        self.started_at = None
        self.completed_at = None
        print(f">>> [STARTUP-STATE] StartupState reset (boot_id={self._boot_id})", flush=True)

    @property
    def started(self) -> bool:
        return self._started

    @started.setter
    def started(self, value: bool) -> None:
        # Simplified setter - no file writes or stack traces to avoid blocking
        logger.info("[STARTUP-STATE] started setter called with value=%s", value)
        self._started = value


# Global singleton - the single source of truth for startup state
startup_state = StartupState()

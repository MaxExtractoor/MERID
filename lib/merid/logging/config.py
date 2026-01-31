"""Logging configuration and helper for MERID.

Provides a simple initializer `init_logging(level)` that configures a consistent
format (timestamp, level, logger, message) and returns a module-level logger
factory `get_logger(name)`.
"""
from __future__ import annotations

import logging
import sys
from typing import Optional


def init_logging(level: Optional[str] = None) -> None:
    level = level or "INFO"
    lvl = getattr(logging, level.upper(), logging.INFO)
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(logging.Formatter(fmt))
    root = logging.getLogger()
    root.setLevel(lvl)
    # Avoid adding multiple handlers during repeated init calls
    if not root.handlers:
        root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)

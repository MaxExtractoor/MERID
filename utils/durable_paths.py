"""Durable-state path resolution with pytest isolation.

Production durable state lives under ``data/``.  ``tests/conftest.py``
redirects the ``MERID_*`` path overrides to a per-process scratch dir, but
that only applies when pytest loads the ``tests/`` conftest chain —
``--noconftest``, ``--confcutdir``, out-of-tree runners, and ``pytest.main()``
callers all bypass it.  Observed 2026-11-07: a fills-ledger test run without
the conftest chain ingested synthetic unmatched fills that persisted
``data/trading_circuit_breaker_halt.json`` and advanced
``data/trading_circuit_breaker_http_watermark.json``, gating live entries on
every subsequent server boot.

``pytest`` is always in ``sys.modules`` for any pytest-driven process and is
never imported by the production server, so it is a reliable test-context
signal; ``PYTEST_CURRENT_TEST`` covers embedded runners.  Explicit ``MERID_*``
env overrides always win, so conftest-managed runs are unaffected.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Optional

_PYTEST_STATE_DIR: Optional[Path] = None


def running_under_pytest() -> bool:
    """True when the current process is pytest-driven (conftest or not)."""
    return "pytest" in sys.modules or bool(os.environ.get("PYTEST_CURRENT_TEST"))


def pytest_state_dir() -> Path:
    """Per-process scratch dir for durable state under pytest (created once)."""
    global _PYTEST_STATE_DIR
    if _PYTEST_STATE_DIR is None:
        _PYTEST_STATE_DIR = Path(tempfile.mkdtemp(prefix="merid_pytest_state_"))
    return _PYTEST_STATE_DIR


def durable_state_path(env_key: str, filename: str, *, prod_dir: str = "data") -> Path:
    """Resolve a durable-state file path.

    Priority: explicit ``env_key`` override > pytest scratch dir > ``prod_dir``.
    """
    override = os.environ.get(env_key)
    if override:
        return Path(override)
    if running_under_pytest():
        return pytest_state_dir() / filename
    return Path(prod_dir) / filename

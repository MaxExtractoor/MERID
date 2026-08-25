"""Pytest collection shim for the legacy top-level ``risk`` package.

``tests/`` is on ``sys.path`` during test collection, and ``tests/risk/__init__.py``
would otherwise shadow the canonical top-level ``risk`` package (which is a
legacy re-export of ``merid.risk``).  Forwarding ``__path__`` to the real ``risk``
package lets tests in the top-level ``tests/`` directory continue to import
``risk.portfolio_optimizer``, ``risk.risk_guard``, ``risk.risk_monitor``, etc.

The tests/risk subdirectory is kept in the search path so that tests under
``tests/risk/probability/`` still collect normally.
"""
from pathlib import Path

_tests_risk_dir = Path(__file__).parent
_real_risk_dir = _tests_risk_dir.parent.parent / "risk"

__path__ = [str(_real_risk_dir), str(_tests_risk_dir)]

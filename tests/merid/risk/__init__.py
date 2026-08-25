"""Pytest collection shim for ``merid.risk``.

``tests/`` is on ``sys.path`` during collection, and this empty file would
otherwise shadow the canonical ``merid.risk`` package.  Forwarding ``__path__``
to the real ``merid/risk`` package lets tests in ``tests/merid/risk/`` keep the
same dotted name while still resolving the source modules (``kill_switches``,
``portfolio_optimizer``, etc.).
"""
from pathlib import Path

_tests_dir = Path(__file__).parent
_real_dir = _tests_dir.parent.parent.parent / "merid" / "risk"

__path__ = [str(_real_dir), str(_tests_dir)]

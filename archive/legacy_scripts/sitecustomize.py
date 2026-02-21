"""Site customizations to keep MERID tests isolated and deterministic."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    _hardening_pkg = importlib.import_module("hardening")
except ModuleNotFoundError:  # pragma: no cover - best-effort guard
    _hardening_pkg = None
else:
    sys.modules.setdefault("hardening", _hardening_pkg)

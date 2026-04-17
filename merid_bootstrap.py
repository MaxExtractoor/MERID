"""Bootstrap helpers to ensure the MERID project root is importable."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Final


def ensure_project_root() -> Path:
    """Add the repository root to ``sys.path`` once."""
    root = Path(__file__).resolve().parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    return root


def configure_utf8() -> None:
    """Guarantee UTF-8 mode regardless of host defaults."""
    os.environ.setdefault("PYTHONUTF8", "1")
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")


PROJECT_ROOT: Final[Path] = ensure_project_root()
configure_utf8()

__all__ = ["PROJECT_ROOT", "ensure_project_root", "configure_utf8"]

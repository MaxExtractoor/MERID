#!/usr/bin/env python3
"""Repo / CI guardrail: committed kill-switch persistence must not arm trading halt.

The file ``data/risk_kill_switch.json`` is **runtime state** (survives restarts), not a
config default. The repository copy must stay ``"active": false`` so deploys and
fresh clones do not start with a global kill.

Run locally or in CI::

    python scripts/check_kill_switch_default.py

Exit codes: 0 = OK, 1 = policy violation.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import List


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def check_committed_kill_switch_json(root: Path | None = None) -> List[str]:
    """Return human-readable errors; empty list means OK."""
    root = root or _repo_root()
    rel = os.environ.get("MERID_RISK_KS_FILE", "data/risk_kill_switch.json")
    path = Path(rel) if Path(rel).is_absolute() else (root / rel)

    errors: List[str] = []
    if not path.exists():
        return errors

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        errors.append(f"{path}: invalid JSON ({exc})")
        return errors

    if data.get("active") is True:
        errors.append(
            f"{path}: committed file must not have \"active\": true — "
            "that restores a global kill on every startup. "
            "Clear via dashboard or risk_controller.reset('operator')."
        )
    return errors


def main() -> int:
    errs = check_committed_kill_switch_json()
    if errs:
        for e in errs:
            print(e, file=sys.stderr)
        return 1
    print("OK: kill-switch persistence policy (active != true in committed JSON)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

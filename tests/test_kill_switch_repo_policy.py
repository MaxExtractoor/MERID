"""Repo policy: persisted kill switch file must not ship with active=true."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_committed_risk_kill_switch_json_not_armed() -> None:
    root = Path(__file__).resolve().parent.parent
    p = root / "data" / "risk_kill_switch.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data.get("active") is not True, (
        f"{p} must not commit active=true — restores global kill on every startup"
    )


def test_check_script_exits_zero() -> None:
    root = Path(__file__).resolve().parent.parent
    r = subprocess.run(
        [sys.executable, str(root / "scripts" / "check_kill_switch_default.py")],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stderr + r.stdout

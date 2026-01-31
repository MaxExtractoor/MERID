"""Snapshot testing helpers."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


SNAPSHOT_ROOT = Path(__file__).resolve().parent
GOLDEN_DIR = SNAPSHOT_ROOT / "golden"
GOLDEN_DIR.mkdir(parents=True, exist_ok=True)

UPDATE_FLAG = os.getenv("UPDATE_SNAPSHOTS", "0") == "1"


def _canonicalize(value: Any) -> Any:
    """Normalize nested structures for stable comparison."""

    if isinstance(value, dict):
        return {key: _canonicalize(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonicalize(item) for item in value]
    if isinstance(value, float):
        return round(value, 6)
    return value


def load_golden_snapshot(name: str) -> Any:
    path = GOLDEN_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"Golden snapshot {name!r} not found at {path}. Run with UPDATE_SNAPSHOTS=1 to create it."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def assert_matches_snapshot(name: str, payload: Any) -> None:
    canonical = _canonicalize(payload)
    path = GOLDEN_DIR / f"{name}.json"

    if UPDATE_FLAG:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(canonical, indent=2), encoding="utf-8")
        return

    golden = load_golden_snapshot(name)
    assert canonical == golden, (
        "Snapshot mismatch for "
        f"{name}. Run UPDATE_SNAPSHOTS=1 pytest tests/snapshots to regenerate."
    )

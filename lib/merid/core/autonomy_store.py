"""Simple helper to read portfolio limits from `data/autonomy_store.json`.

This is deliberately small and sync to keep tests simple. In production this
should be an interface to a configuration service or DB and include caching
and validation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

_DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "autonomy_store.json"


def _load_store() -> dict:
    try:
        return json.loads(_DATA_PATH.read_text())
    except Exception:
        return {}


def get_portfolio_limits(portfolio_id: str) -> Optional[dict]:
    s = _load_store()
    portfolios = s.get("portfolios") or {}
    return portfolios.get(portfolio_id)

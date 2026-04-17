"""PM strategy profiles (MERID_PM_PROFILE) — YAML-driven defaults merged into StrategyConfig.

Profiles live in ``config/pm_profiles.yaml``. Merge order for each agent:

1. ``StrategyConfig`` defaults
2. Per-agent ``strategy:`` block in ``kalshi_agent_grid.yaml``
3. Named profile (this module) when ``MERID_PM_PROFILE`` is set
4. Process-wide env overrides via ``_apply_global_pm_strategy_env`` in ``trading_agent``
"""

from __future__ import annotations

import os
from dataclasses import fields
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from utils.logger import get_logger

logger = get_logger("merid.prediction.pm_profiles")

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "config" / "pm_profiles.yaml"
_profiles_cache: Optional[Dict[str, Dict[str, Any]]] = None


def _load_raw_profiles() -> Dict[str, Dict[str, Any]]:
    global _profiles_cache
    if _profiles_cache is not None:
        return _profiles_cache
    path = os.environ.get("MERID_PM_PROFILES_PATH", str(_DEFAULT_PATH))
    p = Path(path)
    if not p.is_file():
        logger.debug("PM profiles file not found at %s — no named profiles", p)
        _profiles_cache = {}
        return _profiles_cache
    try:
        with open(p, "rb") as f:
            raw = yaml.safe_load(f.read())
        prof = (raw or {}).get("profiles") or {}
        if not isinstance(prof, dict):
            prof = {}
        _profiles_cache = {str(k): dict(v) for k, v in prof.items() if isinstance(v, dict)}
        logger.info("Loaded %d PM profile(s) from %s", len(_profiles_cache), p)
    except Exception as exc:
        logger.warning("Failed to load PM profiles from %s: %s", p, exc)
        _profiles_cache = {}
    return _profiles_cache


def get_pm_profile_strategy_overrides(profile_name: Optional[str] = None) -> Dict[str, Any]:
    """Return strategy field overrides for ``profile_name``, or {} if missing."""
    name = (profile_name or os.getenv("MERID_PM_PROFILE") or "").strip()
    if not name:
        return {}
    raw = _load_raw_profiles()
    block = raw.get(name)
    if not block:
        logger.warning("MERID_PM_PROFILE=%s not found in pm_profiles.yaml — ignoring", name)
        return {}
    # Filter to valid StrategyConfig keys
    from merid.prediction.strategy import StrategyConfig

    allowed = {f.name for f in fields(StrategyConfig)}
    out: Dict[str, Any] = {}
    for key, val in block.items():
        if key in allowed and val is not None:
            out[key] = val
    logger.info("PM profile %r applied: %d strategy field(s)", name, len(out))
    return out


def merge_profile_into_strategy_config(
    sc: Any,
    profile_name: Optional[str] = None,
) -> None:
    """Merge profile overrides into an existing ``StrategyConfig`` in-place."""
    overrides = get_pm_profile_strategy_overrides(profile_name)
    if not overrides:
        return
    from decimal import Decimal

    for key, val in overrides.items():
        if not hasattr(sc, key):
            continue
        cur = getattr(sc, key)
        if isinstance(cur, Decimal):
            setattr(sc, key, val if isinstance(val, Decimal) else Decimal(str(val)))
        elif isinstance(cur, int):
            setattr(sc, key, int(val))
        elif isinstance(cur, float):
            setattr(sc, key, float(val))
        else:
            setattr(sc, key, val)


def effective_strategy_config_snapshot(sc: Any) -> Dict[str, str]:
    """Human-readable flat dict for startup logging."""
    from dataclasses import asdict
    from decimal import Decimal

    try:
        d = asdict(sc)
    except Exception:
        return {}
    out: Dict[str, str] = {}
    for k, v in d.items():
        if isinstance(v, Decimal):
            out[k] = str(v)
        elif v is None:
            out[k] = ""
        else:
            out[k] = str(v)
    return out

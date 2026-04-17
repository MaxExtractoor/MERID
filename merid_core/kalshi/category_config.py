"""
Kalshi Category Trading Config

Controls which market categories agents are allowed to trade.
Categories can be set to: "live", "read-only", or "blocked".

  - live:      agents may place orders
  - read-only: agents can observe/analyze but NOT trade
  - blocked:   completely hidden from agents

Persists to a JSON file so config survives restarts.
"""

import json
from utils.logger import get_logger
import os
import threading
from pathlib import Path
from typing import Dict, List, Optional

logger = get_logger(__name__)

# Known Kalshi categories — must stay in sync with universe.KNOWN_CATEGORIES.
# Sub-categories like "fed", "inflation", "rates", "weather" are not canonical;
# those markets map to "economics" and "climate" respectively (FLAW-04 fix).
KNOWN_CATEGORIES = [
    "cross_category",
    "crypto",
    "economics",
    "macro",
    "financials",
    "politics",
    "climate",
    "sports",
    "tech",
    "culture",
    "science",
    "equities",
    "other",
]

CategoryMode = str  # "live" | "read-only" | "blocked"

_CONFIG_PATH = Path(os.environ.get(
    "KALSHI_CATEGORY_CONFIG",
    str(Path(__file__).resolve().parent.parent.parent / ".kalshi" / "category_config.json"),
))

_lock = threading.Lock()
_category_modes: Dict[str, CategoryMode] = {}


def _default_modes() -> Dict[str, CategoryMode]:
    """Default: core trading categories live, everything else read-only."""
    modes: Dict[str, CategoryMode] = {}
    for cat in KNOWN_CATEGORIES:
        if cat in ("crypto", "economics", "macro", "financials", "equities"):
            modes[cat] = "live"
        else:
            modes[cat] = "read-only"
    return modes


def _load() -> None:
    global _category_modes
    if _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH) as f:
                _category_modes = json.load(f)
            logger.info("Category config loaded from %s (%d categories)", _CONFIG_PATH, len(_category_modes))
            return
        except Exception as exc:
            logger.warning("Failed to load category config: %s", exc)
    _category_modes = _default_modes()
    _save()


def _save() -> None:
    try:
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_CONFIG_PATH, "w") as f:
            json.dump(_category_modes, f, indent=2)
    except Exception as exc:
        logger.warning("Failed to save category config: %s", exc)


# Load on import
_load()


def get_category_modes() -> Dict[str, CategoryMode]:
    """Return current category → mode mapping."""
    with _lock:
        return dict(_category_modes)


def get_category_mode(category: str) -> CategoryMode:
    """Return mode for a single category (default: read-only)."""
    with _lock:
        return _category_modes.get(category, "read-only")


def set_category_mode(category: str, mode: CategoryMode) -> None:
    """Set mode for a category and persist."""
    if mode not in ("live", "read-only", "blocked"):
        raise ValueError(f"Invalid mode: {mode}")
    with _lock:
        _category_modes[category] = mode
        _save()
    logger.info("Category '%s' set to '%s'", category, mode)


def set_bulk_modes(updates: Dict[str, CategoryMode]) -> None:
    """Set multiple categories at once and persist."""
    with _lock:
        for cat, mode in updates.items():
            if mode not in ("live", "read-only", "blocked"):
                raise ValueError(f"Invalid mode for {cat}: {mode}")
            _category_modes[cat] = mode
        _save()
    logger.info("Bulk category update: %d categories", len(updates))


def is_trading_allowed(category: Optional[str]) -> bool:
    """Return True if trading is allowed for the given category."""
    if category is None:
        return True  # unknown category → allow (conservative)
    with _lock:
        mode = _category_modes.get(category, "read-only")
    return mode == "live"


def get_tradeable_categories() -> List[str]:
    """Return list of categories with mode == 'live'."""
    with _lock:
        return [c for c, m in _category_modes.items() if m == "live"]


def get_blocked_categories() -> List[str]:
    """Return list of categories with mode == 'blocked'."""
    with _lock:
        return [c for c, m in _category_modes.items() if m == "blocked"]

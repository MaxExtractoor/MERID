"""Track how long swarm consensus stays neutral/unusable per (asset, timeframe)."""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

# In-process state (best-effort; resets on restart)
_last_cell_neutral: Dict[str, Tuple[bool, float]] = {}  # key -> (was_neutral, streak_minutes)


def _cell_key(asset: str, tf: str) -> str:
    return f"{asset.upper()}:{tf.lower()}"


def advance_neutral_streak(
    asset: str,
    timeframe: str,
    *,
    consensus_usable: bool,
    is_probability_neutral: bool,
    dt_minutes: float,
    warn_after_minutes: float = 30.0,
) -> Dict[str, Any]:
    """Update streak state for one cell; return streak info and optional warning."""
    key = _cell_key(asset, timeframe)
    effectively_neutral = (not consensus_usable) or is_probability_neutral
    prev = _last_cell_neutral.get(key)
    streak = 0.0
    if prev is None:
        streak = dt_minutes if effectively_neutral else 0.0
    else:
        _was_n, prev_streak = prev
        if effectively_neutral:
            streak = prev_streak + dt_minutes
        else:
            streak = 0.0
    _last_cell_neutral[key] = (effectively_neutral, streak)
    warn = effectively_neutral and streak >= warn_after_minutes
    return {
        "asset": asset,
        "timeframe": timeframe,
        "neutral_streak_minutes": round(streak, 2),
        "warn_long_neutral": warn,
    }


def reset_streak_state() -> None:
    """Test helper."""
    _last_cell_neutral.clear()

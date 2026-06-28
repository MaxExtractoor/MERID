# LEGACY: not used by kalshi_crypto_15m_v2 profile
# This module is for paper trading sessions and is only used by legacy profiles
# The lean 15m stack uses live bankroll service (merid.event_venues.kalshi.bankroll_service_v2)

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import uuid
from typing import Dict, List, Optional


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PaperSessionState:
    mode: str = "paper"
    lifecycle: str = "OFFLINE"
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    symbols: List[str] = field(default_factory=list)
    strategies: List[str] = field(default_factory=list)
    venues: List[str] = field(default_factory=list)
    started_at: Optional[str] = None
    duration_seconds: int = 0
    remaining_seconds: int = 0

    def to_dict(self) -> Dict[str, object]:
        return {
            "mode": self.mode,
            "lifecycle": self.lifecycle,
            "symbols": self.symbols,
            "strategies": self.strategies,
            "venues": self.venues,
            "started_at": self.started_at,
            "duration_seconds": self.duration_seconds,
            "remaining_seconds": self.remaining_seconds,
        }


_state = PaperSessionState()


def get_paper_session_state() -> Dict[str, object]:
    return _state.to_dict()


def update_paper_session_state(**kwargs) -> None:
    for key, value in kwargs.items():
        if not hasattr(_state, key):
            continue
        if key == "started_at" and isinstance(value, datetime):
            setattr(_state, key, value.astimezone(timezone.utc).isoformat())
        else:
            setattr(_state, key, value)


def mark_session_start(symbols: List[str], strategies: List[str], venues: List[str], duration_seconds: int) -> None:
    _state.mode = "paper"
    _state.lifecycle = "LIVE"
    _state.symbols = symbols
    _state.strategies = strategies
    _state.venues = venues
    _state.started_at = _utc_now_iso()
    _state.duration_seconds = duration_seconds
    _state.remaining_seconds = duration_seconds


def mark_session_state(lifecycle: str, remaining_seconds: Optional[int] = None) -> None:
    _state.lifecycle = lifecycle
    if remaining_seconds is not None:
        _state.remaining_seconds = max(remaining_seconds, 0)


def reset_session_state() -> None:
    global _state
    _state = PaperSessionState()

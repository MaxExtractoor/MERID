"""Autonomy control helpers for swarm and risk loops."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional, Tuple

DEFAULT_AUTONOMY_FILE = Path("data/autonomy_store.json")
VALID_GLOBAL_STATES = {"running", "paused", "draining"}
VALID_MODES = {"full", "supervised"}
DEFAULT_PORTFOLIO_ID = "core"


@dataclass
class AutonomyGlobal:
    global_state: str = "running"
    mode: str = "full"
    updated_at: str = "1970-01-01T00:00:00Z"
    updated_by: str = "system"
    reason: Optional[str] = None


@dataclass
class AutonomyPortfolio:
    portfolio_id: str = DEFAULT_PORTFOLIO_ID
    enabled: bool = True
    mandate: str = "full"
    max_notional: float = 1_000_000.0
    max_daily_loss: float = 50_000.0
    max_open_orders: int = 25
    allowed_symbols: Tuple[str, ...] = ("BTC-USD", "ETH-USD")
    allowed_venues: Tuple[str, ...] = ("binance_futures", "okx")
    allowed_hours: str = "00:00-23:59"


class AutonomyStore:
    """Simple JSON-backed persistence for autonomy settings."""

    def __init__(self, path: Path = DEFAULT_AUTONOMY_FILE) -> None:
        self.path = path
        self.lock = Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            self._save(self._default_payload())

    def _default_payload(self) -> Dict[str, object]:
        timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        default_global = AutonomyGlobal(updated_at=timestamp)
        default_portfolio = AutonomyPortfolio()
        return {
            "global": self._serialize_global(default_global),
            "portfolios": {
                default_portfolio.portfolio_id: self._serialize_portfolio(default_portfolio)
            },
        }

    def _load(self) -> Dict[str, object]:
        with self.lock:
            data = json.loads(self.path.read_text())
        return data

    def _save(self, data: Dict[str, object]) -> None:
        with self.lock:
            self.path.write_text(json.dumps(data, indent=2))

    def _serialize_global(self, payload: AutonomyGlobal) -> Dict[str, object]:
        return {
            "global_state": payload.global_state,
            "mode": payload.mode,
            "updated_at": payload.updated_at,
            "updated_by": payload.updated_by,
            "reason": payload.reason,
        }

    def _serialize_portfolio(self, payload: AutonomyPortfolio) -> Dict[str, object]:
        return {
            "portfolio_id": payload.portfolio_id,
            "enabled": payload.enabled,
            "mandate": payload.mandate,
            "max_notional": payload.max_notional,
            "max_daily_loss": payload.max_daily_loss,
            "max_open_orders": payload.max_open_orders,
            "allowed_symbols": list(payload.allowed_symbols),
            "allowed_venues": list(payload.allowed_venues),
            "allowed_hours": payload.allowed_hours,
        }

    def get_global(self) -> AutonomyGlobal:
        data = self._load()["global"]
        return AutonomyGlobal(**data)

    def set_global(self, payload: Dict[str, object]) -> AutonomyGlobal:
        data = self._load()
        data["global"] = payload
        self._save(data)
        return AutonomyGlobal(**payload)

    def list_portfolios(self) -> List[AutonomyPortfolio]:
        portfolios = self._load()["portfolios"]
        return [AutonomyPortfolio(**values) for values in portfolios.values()]

    def get_portfolio(self, portfolio_id: str = DEFAULT_PORTFOLIO_ID) -> AutonomyPortfolio:
        portfolios = self._load()["portfolios"]
        if portfolio_id not in portfolios:
            raise KeyError(portfolio_id)
        return AutonomyPortfolio(**portfolios[portfolio_id])

    def upsert_portfolio(self, payload: Dict[str, object]) -> AutonomyPortfolio:
        if "portfolio_id" not in payload:
            raise ValueError("portfolio_id is required")
        data = self._load()
        portfolio_data = data.setdefault("portfolios", {})
        existing = portfolio_data.get(payload["portfolio_id"], {})
        existing.update(payload)
        portfolio_data[payload["portfolio_id"]] = existing
        self._save(data)
        return AutonomyPortfolio(**existing)


autonomy_store = AutonomyStore()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_global_autonomy() -> AutonomyGlobal:
    """Return current global autonomy state."""
    return autonomy_store.get_global()


def update_global_autonomy(global_state: Optional[str] = None, mode: Optional[str] = None, *, reason: Optional[str] = None, updated_by: str = "system") -> AutonomyGlobal:
    current = autonomy_store.get_global()
    next_state = global_state or current.global_state
    next_mode = mode or current.mode
    _validate_state_value(next_state)
    _validate_mode_value(next_mode)
    if next_state != current.global_state:
        _validate_transition(current.global_state, next_state)
    new_payload = {
        "global_state": next_state,
        "mode": next_mode,
        "updated_at": _utc_now(),
        "updated_by": updated_by,
        "reason": reason if reason is not None else current.reason,
    }
    return autonomy_store.set_global(new_payload)


def list_portfolio_limits() -> List[AutonomyPortfolio]:
    return autonomy_store.list_portfolios()


def upsert_portfolio_limits(payload: Dict[str, object]) -> AutonomyPortfolio:
    cleaned = _clean_portfolio_payload(payload)
    return autonomy_store.upsert_portfolio(cleaned)


def get_portfolio_limits(portfolio_id: str = DEFAULT_PORTFOLIO_ID) -> AutonomyPortfolio:
    try:
        return autonomy_store.get_portfolio(portfolio_id)
    except KeyError:
        # If not found, create default entry for the requested portfolio
        return upsert_portfolio_limits({"portfolio_id": portfolio_id})


def can_execute_decision(*, portfolio_id: str = DEFAULT_PORTFOLIO_ID, estimated_notional: float = 0.0) -> bool:
    """Basic guard used by execution to honor autonomy flags."""
    global_state = get_global_autonomy()
    if global_state.global_state != "running":
        return False
    portfolio = get_portfolio_limits(portfolio_id)
    if not portfolio.enabled:
        return False
    if estimated_notional and estimated_notional > portfolio.max_notional:
        return False
    return True


def _validate_state_value(value: str) -> None:
    if value not in VALID_GLOBAL_STATES:
        raise ValueError(f"Invalid global_state '{value}'. Allowed: {sorted(VALID_GLOBAL_STATES)}")


def _validate_mode_value(value: str) -> None:
    if value not in VALID_MODES:
        raise ValueError(f"Invalid mode '{value}'. Allowed: {sorted(VALID_MODES)}")


def _validate_transition(current: str, new: str) -> None:
    if current == new:
        return
    if current == "paused" and new == "draining":
        raise ValueError("Cannot transition directly from paused to draining. Resume running first.")


def _clean_portfolio_payload(payload: Dict[str, object]) -> Dict[str, object]:
    cleaned = dict(payload)
    if "mandate" in cleaned and cleaned["mandate"] not in VALID_MODES:
        raise ValueError("mandate must be 'full' or 'supervised'")
    if "allowed_symbols" in cleaned and cleaned["allowed_symbols"] is not None:
        cleaned["allowed_symbols"] = list(cleaned["allowed_symbols"])
    if "allowed_venues" in cleaned and cleaned["allowed_venues"] is not None:
        cleaned["allowed_venues"] = list(cleaned["allowed_venues"])
    return cleaned

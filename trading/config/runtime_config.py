"""Runtime trading configuration service for the unified trading suite."""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, Optional

from utils.logger import get_logger

logger = get_logger("trading.config.runtime")


class GlobalTradingMode(str, Enum):
    OFFLINE = "offline"
    SIM = "sim"
    PAPER = "paper"
    LIVE = "live"
    HYBRID = "hybrid"


class VenueMode(str, Enum):
    DISABLED = "disabled"
    SIM = "sim"
    PAPER = "paper"
    LIVE = "live"


@dataclass
class VenueConfig:
    venue_id: str
    label: str
    mode: VenueMode = VenueMode.DISABLED
    enabled: bool = False
    max_notional_usd: float = 0.0
    daily_limit_usd: float = 0.0
    credentials_present: bool = False
    telemetry: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TradingRuntimeState:
    mode: GlobalTradingMode = GlobalTradingMode.OFFLINE
    allow_live_trades: bool = False
    spectator_mode: bool = True
    last_updated: float = field(default_factory=time.time)
    venues: Dict[str, VenueConfig] = field(default_factory=dict)
    traders: Dict[str, Dict[str, Any]] = field(default_factory=dict)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "mode": self.mode.value,
            "allow_live_trades": self.allow_live_trades,
            "spectator_mode": self.spectator_mode,
            "last_updated": self.last_updated,
            "venues": {vid: cfg.to_dict() for vid, cfg in self.venues.items()},
            "traders": self.traders.copy(),
        }


class TradingRuntimeConfig:
    """Thread-safe runtime config shared by guards, router, and APIs."""

    def __init__(self) -> None:
        self._state = TradingRuntimeState()
        self._lock = threading.RLock()
        self._load_from_env()

    # ------------------------------------------------------------------ #
    # Load + initialization
    # ------------------------------------------------------------------ #
    def _load_from_env(self) -> None:
        mode = os.getenv("MERID_TRADING_MODE", "offline").lower()
        allow_live = _env_bool("MERID_ALLOW_LIVE_TRADES", False)
        spectator = _env_bool("MERID_SPECTATOR_MODE", True)
        allowed = os.getenv("MERID_TRADING_ALLOWED_VENUES", "")
        venue_ids = [v.strip() for v in allowed.split(",") if v.strip()]

        with self._lock:
            self._state.mode = GlobalTradingMode(mode) if mode in GlobalTradingMode._value2member_map_ else GlobalTradingMode.OFFLINE
            self._state.allow_live_trades = allow_live
            self._state.spectator_mode = spectator
            for venue_id in venue_ids:
                self._state.venues[venue_id] = self._build_venue_from_env(venue_id)
            self._state.last_updated = time.time()
        logger.info(
            "Runtime trading config initialized: mode=%s live=%s spectator=%s venues=%d",
            self._state.mode.value,
            allow_live,
            spectator,
            len(self._state.venues),
        )

    def _build_venue_from_env(self, venue_id: str) -> VenueConfig:
        prefix = f"MERID_{venue_id.upper()}"
        mode_value = os.getenv(f"{prefix}_MODE", "disabled").lower()
        mode = VenueMode(mode_value) if mode_value in VenueMode._value2member_map_ else VenueMode.DISABLED
        enabled = mode != VenueMode.DISABLED
        max_notional = float(os.getenv(f"{prefix}_MAX_NOTIONAL_USD", "0"))
        daily_limit = float(os.getenv(f"{prefix}_DAILY_LIMIT_USD", "0"))
        credentials_present = bool(os.getenv(f"{prefix}_API_KEY") or os.getenv(f"{prefix}_WALLET_SECRET"))
        label = os.getenv(f"{prefix}_LABEL", venue_id)
        return VenueConfig(
            venue_id=venue_id,
            label=label,
            mode=mode,
            enabled=enabled,
            max_notional_usd=max_notional,
            daily_limit_usd=daily_limit,
            credentials_present=credentials_present,
        )

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return self._state.snapshot()

    def update_global_mode(
        self,
        *,
        mode: Optional[str] = None,
        allow_live_trades: Optional[bool] = None,
        spectator_mode: Optional[bool] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            if mode:
                try:
                    self._state.mode = GlobalTradingMode(mode.lower())
                except ValueError:
                    raise ValueError(f"Invalid trading mode: {mode}")
            if allow_live_trades is not None:
                self._state.allow_live_trades = allow_live_trades
            if spectator_mode is not None:
                self._state.spectator_mode = spectator_mode
            self._state.last_updated = time.time()
            snapshot = self._state.snapshot()
        logger.info("Global trading config updated: %s", snapshot)
        return snapshot

    def upsert_venue(self, venue_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            cfg = self._state.venues.get(venue_id) or VenueConfig(venue_id=venue_id, label=payload.get("label", venue_id))
            if "label" in payload:
                cfg.label = str(payload["label"])
            if "mode" in payload:
                try:
                    cfg.mode = VenueMode(payload["mode"].lower())
                except ValueError:
                    raise ValueError(f"Invalid venue mode for {venue_id}")
                cfg.enabled = cfg.mode != VenueMode.DISABLED
            if "max_notional_usd" in payload:
                cfg.max_notional_usd = float(payload["max_notional_usd"])
            if "daily_limit_usd" in payload:
                cfg.daily_limit_usd = float(payload["daily_limit_usd"])
            if "credentials_present" in payload:
                cfg.credentials_present = bool(payload["credentials_present"])
            self._state.venues[venue_id] = cfg
            self._state.last_updated = time.time()
            snapshot = cfg.to_dict()
        logger.info("Venue config updated: %s -> %s", venue_id, snapshot)
        return snapshot

    def get_venue(self, venue_id: str) -> Optional[VenueConfig]:
        with self._lock:
            return self._state.venues.get(venue_id)

    def upsert_trader(self, trader_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock:
            record = self._state.traders.get(trader_id, {}).copy()
            if "mode" in payload:
                record["mode"] = str(payload["mode"]).lower()
            if "spectator_only" in payload:
                record["spectator_only"] = bool(payload["spectator_only"])
            if "metadata" in payload:
                record["metadata"] = payload["metadata"]
            self._state.traders[trader_id] = record
            self._state.last_updated = time.time()
            snapshot = record.copy()
        logger.info("Trader config updated: %s -> %s", trader_id, snapshot)
        return snapshot

    def get_trader(self, trader_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            trader = self._state.traders.get(trader_id)
            return trader.copy() if trader else None


_runtime_config: Optional[TradingRuntimeConfig] = None


def get_runtime_config() -> TradingRuntimeConfig:
    global _runtime_config
    if _runtime_config is None:
        _runtime_config = TradingRuntimeConfig()
    return _runtime_config


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


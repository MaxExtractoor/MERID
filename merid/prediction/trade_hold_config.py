"""Loader for config/trade_hold_config.yaml — trade-vs-hold thresholds.

Provides a thread-safe singleton ``get_trade_hold_config()`` that:
1. Reads config/trade_hold_config.yaml once at first call.
2. Allows env-var overrides (``MERID_TH_<KEY>``).
3. Falls back to sane defaults if the YAML is missing or malformed.

Usage::

    from merid.prediction.trade_hold_config import get_trade_hold_config
    cfg = get_trade_hold_config()
    if cfg.enabled:
        ...
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional

from utils.logger import get_logger

logger = get_logger("merid.prediction.trade_hold_config")

_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "trade_hold_config.yaml"


@dataclass
class WarmupConfig:
    min_seconds: float = 15.0
    max_seconds: float = 90.0
    max_stagger_seconds: float = 30.0
    min_cycles_for_data_ready: int = 1


@dataclass
class EntryWindowConfig:
    expiry_proximity_guard_seconds: float = 90.0
    expiry_caution_zone_seconds: float = 120.0


@dataclass
class StrategyThresholds:
    min_edge_early: Decimal = Decimal("0.08")
    min_edge_mid: Decimal = Decimal("0.07")
    min_edge_late: Decimal = Decimal("0.06")
    min_edge_terminal: Decimal = Decimal("0.06")
    min_arb_edge: Decimal = Decimal("0.005")
    min_confidence: Decimal = Decimal("0.60")
    min_volume: Decimal = Decimal("0")
    min_open_interest: Decimal = Decimal("0")
    snapshot_stale_seconds: int = 120


@dataclass
class ConsensusConfig:
    solo_wait_seconds: float = 0.0
    solo_trades_cap: int = 3
    solo_wall_seconds: float = 1800.0
    consensus_wait_timeout_ms: int = 500


@dataclass
class RiskThresholds:
    max_contracts_per_order: int = 50
    max_contracts_per_market: int = 500
    min_order_size: int = 1
    max_order_size: int = 100
    max_notional_per_market_usd: Decimal = Decimal("500.0")
    max_notional_per_event_usd: Decimal = Decimal("1000.0")
    max_total_notional_usd: Decimal = Decimal("5000.0")
    max_daily_loss_usd: Decimal = Decimal("500.0")
    max_open_markets: int = 50
    max_orders_per_minute: int = 30
    max_orders_per_hour: int = 200
    min_post_fee_edge: Decimal = Decimal("0.01")
    tick_size_cents: int = 1
    max_spread_cents: int = 10
    max_slippage_cents: int = 3
    min_depth_contracts: int = 1


@dataclass
class LoggingConfig:
    log_every_decision: bool = True
    log_hold_detail: bool = True
    log_config_snapshot: bool = False
    cycle_trace_no_action: bool = True
    cycle_trace_consensus: bool = True


@dataclass
class ErrorHandlingConfig:
    max_consecutive_errors: int = 5


@dataclass
class TradeHoldConfig:
    """Top-level trade-vs-hold configuration."""
    enabled: bool = True
    warmup: WarmupConfig = field(default_factory=WarmupConfig)
    entry_window: EntryWindowConfig = field(default_factory=EntryWindowConfig)
    strategy: StrategyThresholds = field(default_factory=StrategyThresholds)
    consensus: ConsensusConfig = field(default_factory=ConsensusConfig)
    risk: RiskThresholds = field(default_factory=RiskThresholds)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    error_handling: ErrorHandlingConfig = field(default_factory=ErrorHandlingConfig)
    max_orders_per_window: int = 10


def _env_override(key: str, default: Any) -> Any:
    """Check ``MERID_TH_<KEY>`` env var and coerce to type of *default*."""
    env_key = f"MERID_TH_{key.upper()}"
    val = os.getenv(env_key)
    if val is None:
        return default
    try:
        if isinstance(default, bool):
            return val.lower() in ("1", "true", "yes", "on")
        if isinstance(default, int):
            return int(val)
        if isinstance(default, float):
            return float(val)
        if isinstance(default, Decimal):
            return Decimal(val)
        return val
    except (ValueError, TypeError):
        logger.warning("Invalid env override %s=%s — using default %s", env_key, val, default)
        return default


def _load_yaml_dict() -> Dict[str, Any]:
    """Load the raw YAML dict; return empty dict on failure."""
    try:
        import yaml  # type: ignore[import-untyped]
        if _CONFIG_PATH.exists():
            with open(_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            if isinstance(data, dict):
                return data
    except Exception as exc:
        logger.warning("trade_hold_config.yaml load failed: %s — using defaults", exc)
    return {}


def _parse_sub(raw: Dict[str, Any], cls: type, env_prefix: str = "") -> Any:
    """Instantiate *cls* from *raw* dict with env overrides."""
    obj = cls()
    for fld_name in obj.__dataclass_fields__:
        default_val = getattr(obj, fld_name)
        yaml_val = raw.get(fld_name, default_val)
        # Coerce YAML value to field type
        if isinstance(default_val, Decimal) and not isinstance(yaml_val, Decimal):
            yaml_val = Decimal(str(yaml_val))
        elif isinstance(default_val, int) and not isinstance(yaml_val, int):
            yaml_val = int(yaml_val)
        elif isinstance(default_val, float) and not isinstance(yaml_val, float):
            yaml_val = float(yaml_val)
        elif isinstance(default_val, bool) and not isinstance(yaml_val, bool):
            yaml_val = str(yaml_val).lower() in ("1", "true", "yes", "on")
        env_key = f"{env_prefix}_{fld_name}" if env_prefix else fld_name
        final = _env_override(env_key, yaml_val)
        setattr(obj, fld_name, final)
    return obj


def _build_config() -> TradeHoldConfig:
    raw = _load_yaml_dict()
    cfg = TradeHoldConfig()
    cfg.enabled = _env_override("ENABLED", raw.get("enabled", True))
    cfg.warmup = _parse_sub(raw.get("warmup", {}), WarmupConfig, "WARMUP")
    cfg.entry_window = _parse_sub(raw.get("entry_window", {}), EntryWindowConfig, "ENTRY_WINDOW")
    cfg.strategy = _parse_sub(raw.get("strategy", {}), StrategyThresholds, "STRATEGY")
    cfg.consensus = _parse_sub(raw.get("consensus", {}), ConsensusConfig, "CONSENSUS")
    cfg.risk = _parse_sub(raw.get("risk", {}), RiskThresholds, "RISK")
    cfg.logging = _parse_sub(raw.get("logging", {}), LoggingConfig, "LOGGING")
    cfg.error_handling = _parse_sub(raw.get("error_handling", {}), ErrorHandlingConfig, "ERROR_HANDLING")
    cfg.max_orders_per_window = _env_override(
        "MAX_ORDERS_PER_WINDOW",
        raw.get("order_limits", {}).get("max_orders_per_window", 10),
    )
    return cfg


_lock = threading.Lock()
_singleton: Optional[TradeHoldConfig] = None


def get_trade_hold_config() -> TradeHoldConfig:
    """Return the global TradeHoldConfig singleton (thread-safe, lazy)."""
    global _singleton
    if _singleton is not None:
        return _singleton
    with _lock:
        if _singleton is not None:
            return _singleton
        _singleton = _build_config()
        logger.info(
            "trade_hold_config loaded: enabled=%s warmup_min=%.0fs strategy_min_edge_early=%s",
            _singleton.enabled,
            _singleton.warmup.min_seconds,
            _singleton.strategy.min_edge_early,
        )
        return _singleton


def reload_trade_hold_config() -> TradeHoldConfig:
    """Force-reload (for tests or hot-reload)."""
    global _singleton
    with _lock:
        _singleton = _build_config()
        return _singleton

"""Market Regime Gate — evaluates crypto basket flatness.

The gate evaluates per-asset metrics and returns ALLOW, REDUCE, or BLOCK
based on configured thresholds. Designed for integration at two points:
1. Strategy output time (before order intent creation)
2. Execution adapter ingress (safety net)
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any

from utils.logger import get_logger

from merid.market_regime.config import MarketRegimeConfig, get_regime_config

logger = get_logger("merid.market_regime.gate")


class RegimeAction(str, Enum):
    """Gate decision actions."""

    ALLOW = "allow"
    REDUCE = "reduce"
    BLOCK = "block"


@dataclass(frozen=True)
class AssetMetrics:
    """Per-asset market metrics for regime evaluation."""

    return_pct: float
    atr_pct: float
    vol_ratio: float
    adx: Optional[float] = None
    price: Optional[float] = None
    volume_24h: Optional[float] = None


@dataclass(frozen=True)
class BasketSnapshot:
    """Complete basket snapshot for evaluation."""

    timestamp: float
    assets: Dict[str, AssetMetrics]
    source: str = "unknown"

    def get(self, asset: str) -> Optional[AssetMetrics]:
        return self.assets.get(asset.upper())


@dataclass(frozen=True)
class RegimeDecision:
    """Gate decision result."""

    action: RegimeAction
    flat_count: int
    total_assets: int
    reason_codes: List[str] = field(default_factory=list)
    per_asset_flat: Dict[str, bool] = field(default_factory=dict)
    metrics: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    shadow_mode: bool = False
    config_source: str = "default"

    @property
    def allowed(self) -> bool:
        return self.action == RegimeAction.ALLOW

    @property
    def blocked(self) -> bool:
        return self.action == RegimeAction.BLOCK

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action.value,
            "flat_count": self.flat_count,
            "total_assets": self.total_assets,
            "reason_codes": self.reason_codes,
            "per_asset_flat": self.per_asset_flat,
            "timestamp": self.timestamp,
            "shadow_mode": self.shadow_mode,
            "config_source": self.config_source,
        }


class MarketRegimeGate:
    """Evaluates crypto basket flatness and returns trading decisions.

    Thread-safe. Designed as singleton via ``get_regime_gate()``.
    """

    def __init__(self, config: Optional[MarketRegimeConfig] = None):
        self.cfg = config or get_regime_config()
        self._lock = threading.Lock()
        self._last_decision: Optional[RegimeDecision] = None
        self._decision_history: List[RegimeDecision] = []
        self._max_history = 1000

        # Counters for observability
        self._counters = {
            "allow": 0,
            "reduce": 0,
            "block": 0,
            "evaluations": 0,
        }

        if self.cfg.enabled:
            logger.info(
                "[market-regime-gate] initialized | enabled=%s | universe=%s | "
                "block_if_flat_gte=%d | reduce_if_flat_gte=%d | shadow=%s",
                self.cfg.enabled,
                self.cfg.universe,
                self.cfg.basket_rules.block_if_flat_count_gte,
                self.cfg.basket_rules.reduce_if_flat_count_gte,
                self.cfg.shadow_mode,
            )
        else:
            logger.info("[market-regime-gate] initialized | enabled=False (bypass mode)")

    def evaluate(self, snapshot: Dict[str, Any]) -> RegimeDecision:
        """Evaluate basket snapshot and return decision.

        Args:
            snapshot: Dict mapping asset symbol (BTC, ETH, etc.) to metrics dict.
                     Each metrics dict should have:
                     - return_pct: float (absolute return %)
                     - atr_pct: float (ATR as % of price)
                     - vol_ratio: float (current vol / avg vol)
                     - adx: optional float (ADX value)

        Returns:
            RegimeDecision with action, flat_count, reason_codes, etc.
        """
        self._counters["evaluations"] += 1

        if not self.cfg.enabled:
            return RegimeDecision(
                action=RegimeAction.ALLOW,
                flat_count=0,
                total_assets=len(snapshot),
                reason_codes=["gate_disabled"],
                shadow_mode=False,
                config_source="disabled",
            )

        # Normalize snapshot to AssetMetrics
        assets_evaluated = {}
        per_asset_flat = {}
        flat_count = 0
        missing_assets = []

        for asset in self.cfg.universe:
            asset_upper = asset.upper()
            raw = snapshot.get(asset_upper) or snapshot.get(asset.lower())
            if raw is None:
                missing_assets.append(asset_upper)
                continue

            metrics = self._normalize_metrics(raw)
            assets_evaluated[asset_upper] = metrics

            is_flat = self._is_asset_flat(metrics)
            per_asset_flat[asset_upper] = is_flat
            if is_flat:
                flat_count += 1

        total_evaluated = len(assets_evaluated)

        # Handle missing assets: if >20% missing, fail-closed (block)
        if missing_assets:
            missing_pct = len(missing_assets) / (len(self.cfg.universe) or 1)
            if missing_pct > 0.2:
                return self._make_decision(
                    RegimeAction.BLOCK,
                    flat_count,
                    total_evaluated,
                    per_asset_flat,
                    ["insufficient_data", f"missing_{len(missing_assets)}_assets"],
                    {"missing_assets": missing_assets, "missing_pct": missing_pct},
                )

        # Determine action based on basket rules
        cfg_rules = self.cfg.basket_rules

        if flat_count >= cfg_rules.block_if_flat_count_gte:
            action = RegimeAction.BLOCK
            reason_codes = ["basket_flat", f"{flat_count}_of_{total_evaluated}_flat"]
        elif flat_count >= cfg_rules.reduce_if_flat_count_gte:
            action = RegimeAction.REDUCE
            reason_codes = ["low_activity", f"{flat_count}_of_{total_evaluated}_flat"]
        else:
            action = RegimeAction.ALLOW
            reason_codes = []

        return self._make_decision(
            action, flat_count, total_evaluated, per_asset_flat, reason_codes,
            {"missing_assets": missing_assets} if missing_assets else {}
        )

    def evaluate_simple(
        self,
        return_pct_map: Dict[str, float],
        atr_pct_map: Dict[str, float],
        vol_ratio_map: Dict[str, float],
        adx_map: Optional[Dict[str, float]] = None,
    ) -> RegimeDecision:
        """Convenience method for simple dict-based evaluation.

        Args:
            return_pct_map: Asset -> return %
            atr_pct_map: Asset -> ATR %
            vol_ratio_map: Asset -> volume ratio
            adx_map: Optional asset -> ADX

        Returns:
            RegimeDecision
        """
        snapshot: Dict[str, Any] = {}
        all_assets = set(return_pct_map.keys()) | set(atr_pct_map.keys()) | set(vol_ratio_map.keys())

        for asset in all_assets:
            snapshot[asset] = {
                "return_pct": return_pct_map.get(asset, 0.0),
                "atr_pct": atr_pct_map.get(asset, 0.0),
                "vol_ratio": vol_ratio_map.get(asset, 1.0),
                "adx": adx_map.get(asset) if adx_map else None,
            }

        return self.evaluate(snapshot)

    def _normalize_metrics(self, raw: Any) -> AssetMetrics:
        """Normalize various input formats to AssetMetrics."""
        if isinstance(raw, AssetMetrics):
            return raw
        if isinstance(raw, dict):
            return AssetMetrics(
                return_pct=float(raw.get("return_pct", 0.0)),
                atr_pct=float(raw.get("atr_pct", 0.0)),
                vol_ratio=float(raw.get("vol_ratio", 1.0)),
                adx=float(raw.get("adx")) if raw.get("adx") is not None else None,
                price=float(raw.get("price")) if raw.get("price") is not None else None,
                volume_24h=float(raw.get("volume_24h")) if raw.get("volume_24h") is not None else None,
            )
        # Fallback: treat as tuple/list (return_pct, atr_pct, vol_ratio)
        try:
            vals = list(raw)
            return AssetMetrics(
                return_pct=float(vals[0]) if len(vals) > 0 else 0.0,
                atr_pct=float(vals[1]) if len(vals) > 1 else 0.0,
                vol_ratio=float(vals[2]) if len(vals) > 2 else 1.0,
            )
        except Exception:
            logger.warning("[market-regime-gate] Could not normalize metrics: %r", raw)
            return AssetMetrics(return_pct=0.0, atr_pct=0.0, vol_ratio=1.0)

    def _is_asset_flat(self, m: AssetMetrics) -> bool:
        """Determine if a single asset is 'flat' based on thresholds."""
        ft = self.cfg.flatness

        # All three conditions must be true to be considered flat
        return (
            abs(m.return_pct) < ft.max_abs_return_pct
            and m.atr_pct < ft.min_atr_pct
            and m.vol_ratio < ft.min_volume_ratio
        )

    def _make_decision(
        self,
        action: RegimeAction,
        flat_count: int,
        total_assets: int,
        per_asset_flat: Dict[str, bool],
        reason_codes: List[str],
        extra_metrics: Dict[str, Any],
    ) -> RegimeDecision:
        """Create and store decision."""
        decision = RegimeDecision(
            action=action,
            flat_count=flat_count,
            total_assets=total_assets,
            reason_codes=reason_codes,
            per_asset_flat=per_asset_flat,
            metrics=extra_metrics,
            shadow_mode=self.cfg.shadow_mode,
            config_source=_get_config_source(),
        )

        with self._lock:
            self._last_decision = decision
            self._decision_history.append(decision)
            if len(self._decision_history) > self._max_history:
                self._decision_history.pop(0)

        # Update counters
        self._counters[action.value] += 1

        # Log structured decision
        log_fn = logger.warning if action == RegimeAction.BLOCK else (
            logger.info if action == RegimeAction.REDUCE else logger.debug
        )
        log_fn(
            "[REGIME] action=%s flat=%d/%d reasons=%s shadow=%s",
            action.value,
            flat_count,
            total_assets,
            reason_codes,
            self.cfg.shadow_mode,
        )

        return decision

    def get_last_decision(self) -> Optional[RegimeDecision]:
        """Return the most recent decision."""
        with self._lock:
            return self._last_decision

    def get_counters(self) -> Dict[str, int]:
        """Return evaluation counters."""
        return self._counters.copy()

    def get_decision_history(self, limit: int = 100) -> List[RegimeDecision]:
        """Return recent decision history."""
        with self._lock:
            return list(self._decision_history)[-limit:]

    def should_allow_new_entries(self) -> bool:
        """Quick check: should we allow new entry orders?"""
        last = self.get_last_decision()
        if last is None:
            return True  # No evaluation yet → allow (fail-open for first cycle)
        if last.shadow_mode:
            return True  # Shadow mode doesn't actually block
        return last.action != RegimeAction.BLOCK

    def should_reduce_position_size(self) -> bool:
        """Quick check: should we reduce position sizing?"""
        last = self.get_last_decision()
        if last is None:
            return False
        return last.action == RegimeAction.REDUCE or last.action == RegimeAction.BLOCK


# ── Singleton ─────────────────────────────────────────────────────────────

_regime_gate: Optional[MarketRegimeGate] = None
_regime_gate_lock = threading.Lock()


def get_regime_gate() -> MarketRegimeGate:
    """Thread-safe singleton accessor."""
    global _regime_gate
    if _regime_gate is None:
        with _regime_gate_lock:
            if _regime_gate is None:
                _regime_gate = MarketRegimeGate()
    return _regime_gate


def _reset_regime_gate() -> None:
    """Test helper — clears cached gate."""
    global _regime_gate
    with _regime_gate_lock:
        _regime_gate = None


def _get_config_source() -> str:
    """Determine config source for observability."""
    import os
    env_path = os.getenv("MERID_MARKET_REGIME_CONFIG_PATH")
    if env_path:
        return f"env:{env_path}"
    return "default:config/market_regime.yaml"

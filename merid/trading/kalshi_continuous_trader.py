"""
Kalshi Continuous Crypto Trader — Async Server Module
=====================================================
Wraps the standalone continuous trader logic for integration with the
MERID server lifespan.  Targets BTC, ETH, SOL, XRP, DOGE across
15-minute, hourly, and other timescales.  Each asset is filtered
against its own spot price.  All blocking HTTP calls (CoinGecko,
Kalshi REST) are offloaded to a thread executor so the asyncio
event loop stays free.

Environment (safety / exits):

- ``KALSHI_CT_AUTO_EXIT`` — set true to submit REST sells on profit-take / stop-loss zones.
- ``KALSHI_CT_BYPASS_PM_LIVE_GATE`` — allow live Kalshi orders when ``MERID_PM_*`` is not live (CT-only).
- ``KALSHI_CT_PROFILE`` — ``production`` | ``initial_live`` | ``diagnostic`` (permissive min-edge for wiring checks; pair with tiny caps).
- ``KALSHI_CT_DIAGNOSTIC_MIN_EDGE`` — overrides default diagnostic min edge (default ``0.008``).
- ``KALSHI_TRADER_SMOKE_ALLOW_NO_SETTINGS`` — allow smoke test if ``merid.settings`` cannot be imported.

Exposure (this module, **cents**): per-asset and global skip gates use ``KALSHI_TRADER_EXPOSURE_*``,
``KALSHI_TRADER_GLOBAL_EXPOSURE``, ``KALSHI_TRADER_MIN_ASSET_CAP_CENTS``. ``series_exposure_multiplier``
is a CT-only timeframe scaler (code defaults; not env-driven unless extended). Correlated-stack **USD**
caps live in ``category_exposure`` / ``MERID_ASSET_CAP_*_USD`` and do **not** gate this loop — see
``docs/trader_tracker_exposure_layers.md``.

Usage from lifespan:
    from merid.trading.kalshi_continuous_trader import get_continuous_trader
    trader = get_continuous_trader()
    task = asyncio.create_task(trader.run())
    # ... on shutdown:
    trader.stop()
"""

from __future__ import annotations

import asyncio
import base64
import json
import math
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

# CT → Router adapter for migration (Phase 1: Shadow Mode)
from merid.trading.ct_execution_adapter import get_ct_execution_adapter

from merid.prediction.risk.kalshi_risk_engine import KalshiRiskConfig, KalshiRiskEngine
from config.kalshi_universe import KALSHI_CRYPTO_PRODUCTS, kalshi_ct_default_series_tickers
from utils.logger import get_logger
from merid.trading.kalshi_filter_pipeline import FilterPipeline, FilterPipelineConfig
from merid.guards import TradingGuardian, GoLiveChecklist, TradingMode
from merid.formulas import generate_correlation_id, FORMULAS_VERSION, AUDIT_SPEC_VERSION

logger = get_logger(__name__)

# Local transport/connection failures — not an HTTP status from Kalshi (avoid 503 confusion).
_CT_TRANSPORT_FAILURE_STATUS = 0

# When ``MarketCandidate.asset`` is missing: logging/sizing fallback only (spot fetch stays per-asset).
# Centralized so ``_run_cycle*`` avoids scattered ``"BTC"`` literals that static audits flag as BTC-only.
_CT_ASSET_KEY_FALLBACK = "BTC"

# ═══════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════

_instance: Optional["KalshiContinuousTrader"] = None
_instance_lock = threading.Lock()


def get_continuous_trader() -> "KalshiContinuousTrader":
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = KalshiContinuousTrader()
    return _instance


def reset_continuous_trader() -> None:
    """Reset the singleton (BUG-F2 fix). Use for config changes or testing."""
    global _instance
    with _instance_lock:
        if _instance is not None:
            _instance.stop()
        _instance = None


# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════


def _resolve_trader_min_edge(smoke_test: bool) -> Decimal:
    """Bankroll base min_edge (fees/slippage scaling builds on this)."""
    if smoke_test:
        return Decimal("0.01")
    env_me = os.getenv("KALSHI_TRADER_MIN_EDGE")
    if env_me:
        return Decimal(env_me)
    profile = os.getenv("KALSHI_CT_PROFILE", "production").strip().lower() or "production"
    if profile == "initial_live":
        return Decimal("0.012")
    # Wiring / telemetry probe: permissive edge with tiny caps via env (not smoke-test bypass).
    if profile == "diagnostic":
        return Decimal(os.getenv("KALSHI_CT_DIAGNOSTIC_MIN_EDGE", "0.008"))
    # Use canonical EDGE_MIN_THRESHOLD from trading_constants (aligns with StrategyConfig floor).
    from config.trading_constants import EDGE_MIN_THRESHOLD
    return Decimal(str(EDGE_MIN_THRESHOLD))


@dataclass
class TraderConfig:
    interval_seconds: int = 60
    dry_run: bool = False

    # ── Bankroll management (capital-preservation-first) ──────────────
    initial_bankroll_cents: int = 1400   # $14.00 - calibrated to match user's $12.97 Kalshi cash + buffer
    max_risk_per_trade_pct: float = 0.015 # risk max 1.5% of bankroll per trade (tightened from 2%)
    kelly_fraction: float = 0.20         # fifth-Kelly (more conservative, survival-first)
    max_contract_price_cents: int = 65   # Allow mid-curve markets up to 65¢ (was 35¢)
    min_contract_price_cents: int = 2    # skip penny contracts (no liquidity)
    max_position_per_market: int = 3     # max contracts held per ticker (reduced from 5)
    max_open_positions: int = 3          # max simultaneous markets (reduced from 5)
    max_total_exposure_pct: float = 0.15 # never have >15% of bankroll at risk (tightened from 20%)

    # ── Per-asset exposure limits ────────────────────────────────────
    # Maximum fraction of bankroll each crypto asset may consume.
    # Independent buckets — BTC at its cap does NOT block ETH/SOL/XRP/DOGE.
    # Assets capped 20-25% — tighter for high-vol alts (SOL/XRP/DOGE), moderate for majors (BTC/ETH).
    asset_max_exposure_pct: Dict[str, float] = field(default_factory=lambda: {
        "BTC":  0.25,  # tightened from 30%
        "ETH":  0.25,  # tightened from 30%
        "SOL":  0.20,  # tightened from 30% (higher vol asset)
        "XRP":  0.20,  # tightened from 30% (higher vol asset)
        "DOGE": 0.20,  # tightened from 30% (highest vol asset)
    })
    asset_exposure_default_pct: float = 0.10   # fallback for any unlisted asset
    # CT-only: scales each asset's cent cap by timeframe (15m / 1h / daily / weekly). Not read from env
    # in ``from_env()`` — change here or wire env explicitly if needed.
    series_exposure_multiplier: Dict[str, float] = field(default_factory=lambda: {
        "15m":    0.40,
        "1h":     0.70,
        "daily":  1.00,
        "weekly": 1.00,
        "monthly": 0.80,
        "annual":  0.60,
    })
    # Global portfolio guardrail: total exposure across ALL crypto assets combined.
    global_max_exposure_pct: float = 0.50    # 50% of bankroll across all crypto
    # Minimum per-asset-series cap (cents). Prevents micro-account lockout.
    min_asset_cap_cents: int = 100           # $1.00 floor

    # ── Drawdown protection ──────────────────────────────────────────
    drawdown_halt_pct: float = 0.15      # HALT if bankroll drops 15% from peak (tightened from 20%)
    drawdown_reduce_pct: float = 0.08    # reduce sizing at 8% drawdown (tightened from 10%)
    min_balance_cents: int = 300         # never trade below $3.00 reserve (raised from $2.00)

    # ── Edge requirements (very strict) ──────────────────────────────
    min_edge: Decimal = Decimal("0.06")  # 6% net edge after fees+slippage — mirrors EDGE_MIN_THRESHOLD; from_env() uses the constant
    # Directional (15m up/down) markets: max |P_yes − 0.5| from indicator confidence
    directional_max_tilt: float = 0.15
    fee_per_contract: Decimal = Decimal("0.02")  # ~2¢ Kalshi taker fee (= 0.07 * P*(1-P) at 50¢)
    slippage: Decimal = Decimal("0.01")  # 1% slippage

    # ── CT -> Router Migration (Phase 2: Canary Flip) ────────────────
    # Percentage of orders to route through canonical router vs direct HTTP.
    # 0 = all HTTP (Phase 1 shadow mode)
    # 1-99 = canary flip (random selection)
    # 100 = all router (Phase 3 complete)
    # Env: CT_USE_ROUTER_PERCENT (default 0 until parity validated)
    use_router_percent: int = 0

    # ── Market selection ─────────────────────────────────────────────
    # Default: 15m–weekly from kalshi_universe (excludes monthly/annual); see kalshi_ct_default_series_tickers
    series_tickers: List[str] = field(default_factory=kalshi_ct_default_series_tickers)
    max_markets_to_scan: int = 10
    max_strike_distance_pct: float = 0.125  # 12.5% - tightened from 25%

    # ── Fee-aware edge scaling ───────────────────────────────────────
    # Kalshi fee = ceil(0.07 * C * P * (1-P)); worst at mid-curve
    # Require higher edge at mid-curve prices where fee drag is worst
    fee_edge_multiplier_midcurve: float = 1.75  # 1.75x min_edge for 40-60¢ contracts (tightened from 1.5x)
    fee_edge_multiplier_penny: float = 2.0      # 2x min_edge for ≤5¢ contracts (rounding kills)

    # ── Anti-churn hysteresis ────────────────────────────────────────
    churn_cooldown_cycles: int = 3       # don't flip direction on same ticker for 3 cycles
    churn_edge_improvement: float = 0.05 # unless edge improved by 5% absolute

    # ── Fee drag monitoring ──────────────────────────────────────────
    max_fee_drag_pct: float = 0.25       # tighten filters if fees > 25% of gross edge (tightened from 30%)
    fee_drag_lookback: int = 30          # base rolling window (overridden by vol-adaptive)

    # ── Volatility-adaptive fee-drag window ────────────────────────
    # Realized vol of BTC spot (log-return stdev) mapped to window size.
    # Band thresholds are annualized vol (BTC typically 40-80%).
    vol_lookback_bars: int = 20          # bars of spot history for vol calc
    vol_low_threshold: float = 0.40      # annualized vol < 40% = calm
    vol_high_threshold: float = 0.80     # annualized vol > 80% = stressed
    fee_window_low_vol: int = 50         # calm: longer window, smooth
    fee_window_mid_vol: int = 30         # typical: balanced
    fee_window_high_vol: int = 20        # stressed: fast adaptation

    # ── Order management ─────────────────────────────────────────────
    stale_order_seconds: int = 120       # cancel stale orders after 2 min
    max_orders_per_cycle: int = 1        # conservative: 1 order per cycle

    # ── Per-cycle spend cap ──────────────────────────────────────────
    # Never spend more than this fraction of current balance in a single cycle.
    # Env: KALSHI_TRADER_CYCLE_SPEND_PCT (default 0.15 = 15%)
    max_cycle_spend_pct: float = 0.10    # max 10% of balance per cycle (tightened from 15%)

    # ── Exit thresholds (auto-exit, fractional price 0–1) ────────────
    # Env: KALSHI_TRADER_YES_STOP_CENTS / KALSHI_TRADER_YES_PROFIT_CENTS
    yes_stop_loss_cents: int = 8         # exit YES position if bid ≤ 8¢
    yes_profit_take_cents: int = 85      # exit YES position if bid ≥ 85¢

    def to_risk_config(self) -> KalshiRiskConfig:
        """Map trader config risk fields to the shared KalshiRiskConfig."""
        return KalshiRiskConfig(
            initial_bankroll_cents=self.initial_bankroll_cents,
            max_risk_per_trade_pct=self.max_risk_per_trade_pct,
            kelly_fraction=self.kelly_fraction,
            max_contract_price_cents=self.max_contract_price_cents,
            min_contract_price_cents=self.min_contract_price_cents,
            max_position_per_market=self.max_position_per_market,
            max_open_positions=self.max_open_positions,
            max_total_exposure_pct=self.max_total_exposure_pct,
            drawdown_halt_pct=self.drawdown_halt_pct,
            drawdown_reduce_pct=self.drawdown_reduce_pct,
            min_balance_cents=self.min_balance_cents,
            min_edge=self.min_edge,
            fee_per_contract=self.fee_per_contract,
            slippage=self.slippage,
            fee_edge_multiplier_midcurve=self.fee_edge_multiplier_midcurve,
            fee_edge_multiplier_penny=self.fee_edge_multiplier_penny,
            churn_cooldown_cycles=self.churn_cooldown_cycles,
            churn_edge_improvement=self.churn_edge_improvement,
            max_fee_drag_pct=self.max_fee_drag_pct,
            fee_drag_lookback=self.fee_drag_lookback,
            vol_lookback_bars=self.vol_lookback_bars,
            vol_low_threshold=self.vol_low_threshold,
            vol_high_threshold=self.vol_high_threshold,
            fee_window_low_vol=self.fee_window_low_vol,
            fee_window_mid_vol=self.fee_window_mid_vol,
            fee_window_high_vol=self.fee_window_high_vol,
            max_orders_per_cycle=self.max_orders_per_cycle,
            interval_seconds=self.interval_seconds,
        )

    @classmethod
    def from_env(cls) -> "TraderConfig":
        """Build config from environment variables."""
        # Smoke test mode: temporarily relaxes constraints to prove e2e path
        smoke_test = os.getenv("KALSHI_TRADER_SMOKE_TEST", "false").lower() in ("true", "1", "yes")

        # CRITICAL INTERLOCK: Smoke test mode bypasses safety limits
        if smoke_test:
            try:
                from merid.settings import settings
            except ImportError:
                allow = os.getenv("KALSHI_TRADER_SMOKE_ALLOW_NO_SETTINGS", "").lower() in (
                    "1", "true", "yes",
                )
                if not allow:
                    raise RuntimeError(
                        "KALSHI_TRADER_SMOKE_TEST=true but merid.settings could not be imported; "
                        "refusing to start smoke mode (fail-closed). Fix the environment, or set "
                        "KALSHI_TRADER_SMOKE_ALLOW_NO_SETTINGS=true only in isolated test VMs."
                    ) from None
                logger.warning(
                    "SMOKE TEST: settings import failed — live interlock skipped "
                    "(KALSHI_TRADER_SMOKE_ALLOW_NO_SETTINGS is set)"
                )
            else:
                if settings.MERID_PM_TRADING_MODE == "live" and settings.MERID_PM_LIVE_ENABLED:
                    raise RuntimeError(
                        "CRITICAL SAFETY VIOLATION: KALSHI_TRADER_SMOKE_TEST=true with "
                        "MERID_PM_TRADING_MODE=live. This bypasses safety limits "
                        "(8% edge → 1%, 35¢ max → 99¢). Remove smoke test flag before live deployment."
                    )

            logger.warning(
                "SMOKE TEST MODE ENABLED: min_edge=0.01, max_contract_price=99¢, "
                "max_orders_per_cycle=1, size capped at 1 contract"
            )
        
        return cls(
            interval_seconds=int(os.getenv("KALSHI_TRADER_INTERVAL", "60")),
            dry_run=os.getenv("KALSHI_TRADER_DRY_RUN", "false").lower() in ("true", "1", "yes"),
            initial_bankroll_cents=int(os.getenv("KALSHI_TRADER_BANKROLL", "1400")),  # $14.00 default matches calibrated bankroll
            max_risk_per_trade_pct=float(os.getenv("KALSHI_TRADER_RISK_PCT", "0.015")),  # 1.5% - calibrated
            kelly_fraction=float(os.getenv("KALSHI_TRADER_KELLY_FRAC", "0.20")),  # fifth-Kelly - calibrated
            max_contract_price_cents=99 if smoke_test else int(os.getenv("KALSHI_TRADER_MAX_PRICE", "65")),
            min_contract_price_cents=int(os.getenv("KALSHI_TRADER_MIN_PRICE", "2")),
            max_position_per_market=1 if smoke_test else int(os.getenv("KALSHI_TRADER_MAX_POSITION", "5")),
            max_open_positions=int(os.getenv("KALSHI_TRADER_MAX_OPEN", "3")),  # calibrated
            max_total_exposure_pct=float(os.getenv("KALSHI_TRADER_MAX_EXPOSURE", "0.15")),  # 15% - calibrated
            asset_max_exposure_pct={
                "BTC":  float(os.getenv("KALSHI_TRADER_EXPOSURE_BTC",  "0.25")),  # calibrated
                "ETH":  float(os.getenv("KALSHI_TRADER_EXPOSURE_ETH",  "0.25")),  # calibrated
                "SOL":  float(os.getenv("KALSHI_TRADER_EXPOSURE_SOL",  "0.20")),  # high vol - tighter
                "XRP":  float(os.getenv("KALSHI_TRADER_EXPOSURE_XRP",  "0.20")),  # high vol - tighter
                "DOGE": float(os.getenv("KALSHI_TRADER_EXPOSURE_DOGE", "0.20")),  # highest vol - tightest
            },
            asset_exposure_default_pct=float(os.getenv("KALSHI_TRADER_EXPOSURE_DEFAULT", "0.10")),
            global_max_exposure_pct=float(os.getenv("KALSHI_TRADER_GLOBAL_EXPOSURE", "0.50")),
            min_asset_cap_cents=int(os.getenv("KALSHI_TRADER_MIN_ASSET_CAP_CENTS", "100")),
            drawdown_halt_pct=float(os.getenv("KALSHI_TRADER_DD_HALT", "0.15")),  # 15% - calibrated
            drawdown_reduce_pct=float(os.getenv("KALSHI_TRADER_DD_REDUCE", "0.08")),  # 8% - calibrated
            min_balance_cents=int(os.getenv("KALSHI_TRADER_MIN_BALANCE", "300")),  # $3.00 - calibrated
            min_edge=_resolve_trader_min_edge(smoke_test),
            directional_max_tilt=float(os.getenv("KALSHI_CT_DIRECTIONAL_MAX_TILT", "0.15")),
            max_markets_to_scan=int(os.getenv("KALSHI_TRADER_MAX_SCAN", "10")),
            max_strike_distance_pct=float(os.getenv("KALSHI_TRADER_MAX_DISTANCE", "0.20")),  # 20% default per v2 calibration
            stale_order_seconds=int(os.getenv("KALSHI_TRADER_STALE_ORDER_SEC", "120")),
            max_orders_per_cycle=1 if smoke_test else int(os.getenv("KALSHI_TRADER_MAX_ORDERS_CYCLE", "1")),
            fee_edge_multiplier_midcurve=float(os.getenv("KALSHI_TRADER_FEE_MULT_MID", "1.75")),  # 1.75x - calibrated
            fee_edge_multiplier_penny=float(os.getenv("KALSHI_TRADER_FEE_MULT_PENNY", "2.0")),
            churn_cooldown_cycles=int(os.getenv("KALSHI_TRADER_CHURN_COOLDOWN", "3")),
            churn_edge_improvement=float(os.getenv("KALSHI_TRADER_CHURN_EDGE_IMPROV", "0.05")),
            max_fee_drag_pct=float(os.getenv("KALSHI_TRADER_MAX_FEE_DRAG", "0.25")),  # 25% - calibrated
            fee_drag_lookback=int(os.getenv("KALSHI_TRADER_FEE_DRAG_LOOKBACK", "30")),
            vol_lookback_bars=int(os.getenv("KALSHI_TRADER_VOL_LOOKBACK", "20")),
            vol_low_threshold=float(os.getenv("KALSHI_TRADER_VOL_LOW", "0.40")),
            vol_high_threshold=float(os.getenv("KALSHI_TRADER_VOL_HIGH", "0.80")),
            fee_window_low_vol=int(os.getenv("KALSHI_TRADER_FEE_WIN_LOW", "50")),
            fee_window_mid_vol=int(os.getenv("KALSHI_TRADER_FEE_WIN_MID", "30")),
            fee_window_high_vol=int(os.getenv("KALSHI_TRADER_FEE_WIN_HIGH", "20")),
            max_cycle_spend_pct=float(os.getenv("KALSHI_TRADER_CYCLE_SPEND_PCT", "0.10")),  # 10% - calibrated
            yes_stop_loss_cents=int(os.getenv("KALSHI_TRADER_YES_STOP_CENTS", "8")),
            yes_profit_take_cents=int(os.getenv("KALSHI_TRADER_YES_PROFIT_CENTS", "85")),
            # Phase 2: CT -> Router migration canary flip
            use_router_percent=int(os.getenv("CT_USE_ROUTER_PERCENT", "0")),
        )

    def __post_init__(self) -> None:
        _suppress = False
        try:
            from merid.prediction.pm_ct_policy import ct_loop_suppressed

            _suppress = bool(ct_loop_suppressed())
        except Exception:
            pass
        _ct_on = os.getenv("MERID_ENABLE_KALSHI_CT", "").lower() in ("1", "true", "yes", "on")
        _tag = "[CT-LEGACY/DEV] " if (_ct_on and not _suppress) else ""

        _default_bankroll = 574
        if (
            not _suppress
            and self.initial_bankroll_cents == _default_bankroll
            and not os.getenv("KALSHI_TRADER_BANKROLL")
        ):
            logger.warning(
                "%sTraderConfig: KALSHI_TRADER_BANKROLL not set — using placeholder $%.2f. "
                "Set this env var for legacy CT / research; AgentGrid PM uses KalshiRiskManager equity.",
                _tag,
                _default_bankroll / 100,
            )
        # Warn if CT min_edge is below the market_filter global floor so the
        # divergence is visible in logs at startup rather than at trade time.
        if not _suppress:
            try:
                from config.kalshi_ct_risk_profiles import effective_global_min_edge_floor

                _floor = effective_global_min_edge_floor()
                if self.min_edge < _floor:
                    logger.warning(
                        "%sTraderConfig: min_edge=%s is below effective global min-edge floor=%s "
                        "(KALSHI_CT_PROFILE). CT NearSpotSelector may diverge from PM strategy thresholds.",
                        _tag,
                        self.min_edge,
                        _floor,
                    )
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════════════════
# Bankroll manager — thin alias over the shared KalshiRiskEngine
# ═══════════════════════════════════════════════════════════════════════════

class BankrollManager(KalshiRiskEngine):
    """Backward-compatible alias: all logic now lives in
    ``merid.prediction.risk.kalshi_risk_engine.KalshiRiskEngine``.

    Accepts a ``TraderConfig`` (or ``KalshiRiskConfig``) so existing
    call-sites (status_snapshot, notifier, etc.) keep working unchanged.
    """

    def __init__(self, config: TraderConfig) -> None:
        risk_cfg = config.to_risk_config() if hasattr(config, "to_risk_config") else config
        _quiet = False
        try:
            from merid.prediction.pm_ct_policy import ct_loop_suppressed

            _quiet = bool(ct_loop_suppressed())
        except Exception:
            pass
        super().__init__(risk_cfg, name="continuous-trader", quiet_bankroll_log=_quiet)


# ═══════════════════════════════════════════════════════════════════════════
# Order tracker
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class OrderTracker:
    total_spent_cents: int = 0
    total_fees_cents: int = 0
    orders_placed: int = 0
    orders_filled: int = 0
    orders_cancelled: int = 0
    resting_orders: Dict[str, dict] = field(default_factory=dict)

    def record_order(self, order: dict, cost_cents: int) -> None:
        oid = order.get("order_id", "?")
        status = order.get("status", "")
        self.orders_placed += 1
        self.total_spent_cents += cost_cents
        fee = int(float(order.get("taker_fees_dollars", "0")) * 100)
        self.total_fees_cents += fee
        if status == "executed":
            self.orders_filled += 1
        elif status == "resting":
            self.resting_orders[oid] = {
                "ticker": order.get("ticker"),
                "placed_at": time.time(),
                "price_cents": cost_cents,
                "contracts": order.get("quantity", 1),
                "estimated_fee_cents": fee,  # Store for adjustment on fill
            }

    def record_cancel(self, order_id: str) -> None:
        self.orders_cancelled += 1
        self.resting_orders.pop(order_id, None)

    def record_fill(self, order_id: str, fill_price_cents: Optional[int] = None) -> bool:
        """Record a fill for a previously resting order.

        Called when a resting order fills via WebSocket or polling.
        Increments orders_filled and removes from resting_orders.

        Args:
            order_id: The order that filled
            fill_price_cents: Optional fill price for fee recalculation

        Returns:
            True if the order was found in resting_orders and recorded as filled
        """
        if order_id in self.resting_orders:
            # Update fee based on actual fill price if provided
            if fill_price_cents is not None:
                from merid.event_venues.kalshi.kalshi_risk import kalshi_fee_cents
                contracts = self.resting_orders[order_id].get("contracts", 1)
                actual_fee = kalshi_fee_cents(fill_price_cents, contracts)
                # Adjust fee: actual - estimated (estimated was added in record_order)
                estimated_fee = int(
                    float(self.resting_orders[order_id].get("estimated_fee_cents", actual_fee))
                )
                self.total_fees_cents += (actual_fee - estimated_fee)
            else:
                # Fee already accounted in record_order, no adjustment needed
                pass

            self.resting_orders.pop(order_id, None)
            self.orders_filled += 1
            return True

        # Order not in resting_orders - may have been placed as immediate executed
        # or already cancelled. Fee was already recorded in record_order for immediate fills.
        self.orders_filled += 1
        return False

    def summary(self) -> str:
        return (
            f"Orders: {self.orders_placed} placed, {self.orders_filled} filled, "
            f"{self.orders_cancelled} cancelled | "
            f"Spent: {self.total_spent_cents}c + {self.total_fees_cents}c fees"
        )


# ═══════════════════════════════════════════════════════════════════════════
# Market candidate — unified with canonical definition from market_filter
# ═══════════════════════════════════════════════════════════════════════════

# Import canonical MarketCandidate from market_filter (single source of truth)
from merid.event_venues.kalshi.market_filter import (
    MarketCandidate as _BaseMarketCandidate,
    get_price_band,
    get_tiered_min_edge,
    parse_strike_from_ticker,
)


@dataclass
class TradingCandidate(_BaseMarketCandidate):
    """Backward-compatible name for the canonical enriched ``MarketCandidate``.

    Orderbook and edge fields live on ``merid.event_venues.kalshi.market_filter.MarketCandidate``
    so filter-pipeline instances always define ``best_side``, ``close_time``, etc.
    """


# Backward compatibility alias
MarketCandidate = TradingCandidate


def ct_reference_price_cents(c: MarketCandidate) -> int:
    """Executable or diagnostic reference price when ``limit_price_cents`` is unset."""
    if getattr(c, "limit_price_cents", 0) and c.limit_price_cents > 0:
        return max(1, min(99, int(c.limit_price_cents)))
    if getattr(c, "mid_price_cents", 0) and c.mid_price_cents > 0:
        return max(1, min(99, int(c.mid_price_cents)))
    ip = getattr(c, "implied_yes_prob", None)
    if ip is not None:
        return max(1, min(99, int(round(float(ip) * 100))))
    return 50


def _load_strike_band_pct() -> Dict[Tuple[str, str], float]:
    """Load strike distance bands from kalshi_strike_selector (single source of truth).

    Falls back to inline defaults if the import fails.
    """
    try:
        from merid.prediction.kalshi_strike_selector import DEFAULT_MAX_DISTANCE
        return dict(DEFAULT_MAX_DISTANCE)
    except ImportError:
        # Fallback values matching v2 calibration (2026-04-17)
        return {
            ("BTC", "15m"):   0.15, ("BTC", "1h"):   0.20,
            ("BTC", "daily"): 0.25, ("BTC", "weekly"): 0.35,
            ("BTC", "monthly"): 0.50, ("BTC", "annual"): 0.50,
            ("ETH", "15m"):   0.15, ("ETH", "1h"):   0.20,
            ("ETH", "daily"): 0.25, ("ETH", "weekly"): 0.35,
            ("ETH", "monthly"): 0.50, ("ETH", "annual"): 0.50,
            ("SOL", "15m"):   0.20, ("SOL", "1h"):   0.25,
            ("SOL", "daily"): 0.30, ("SOL", "weekly"): 0.40,
            ("SOL", "monthly"): 0.60, ("SOL", "annual"): 0.60,
            ("XRP", "15m"):   0.20, ("XRP", "1h"):   0.25,
            ("XRP", "daily"): 0.30, ("XRP", "weekly"): 0.40,
            ("XRP", "monthly"): 0.60, ("XRP", "annual"): 0.60,
            ("DOGE", "15m"):  0.30, ("DOGE", "1h"):  0.35,
            ("DOGE", "daily"):0.40, ("DOGE", "weekly"):0.50,
            ("DOGE", "monthly"):0.70, ("DOGE", "annual"):0.70,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Main class
# ═══════════════════════════════════════════════════════════════════════════

class KalshiContinuousTrader:
    """Legacy / research / optional service — **not** part of the live AgentGrid PM path.

    Production prediction-market execution is owned by ``KalshiTradingAgent`` / AgentGrid
    (PortfolioRiskAgent, VenueGate, ExecutionGate, ``order_router``). CT remains available
    behind ``MERID_ENABLE_KALSHI_CT`` for experiments and parity checks; do not wire it
    back in as a parallel trading loop.

    Async continuous multi-asset crypto trader for Kalshi, designed to run inside the
    MERID server event loop. Supports BTC, ETH, SOL, XRP, DOGE — each asset is filtered
    against its own spot price so non-BTC markets are not rejected by BTC strike distance
    calculations.
    """

    def __init__(self) -> None:
        self.config = TraderConfig.from_env()
        self.tracker = OrderTracker()
        self.bankroll = BankrollManager(self.config)
        self._shutdown = False
        self._cycle = 0
        self._task: Optional[asyncio.Task] = None
        self._cycle_lock = threading.Lock()

        # Cached portfolio value (updated each cycle from positions total_cost).
        # Used by status_snapshot so it doesn't need to re-fetch positions on every poll.
        self._last_portfolio_cents: int = 0

        # Per-asset spot metadata for observability
        self._last_spots: Dict[str, dict] = {}
        self._indicator_last_updated: Dict[str, float] = {}
        # Execution gate snapshot (used to keep paper rehearsal faithful).
        self._last_execution_gate: Optional[Dict[str, Any]] = None
        # CoinGecko rate-limit backoff
        self._cg_backoff_until: float = 0.0
        
        # Schema drift detection counters (3+ consecutive missing cycles triggers alert)
        self._schema_missing_streak: Dict[str, int] = {}
        self._schema_missing_flag: Dict[str, bool] = {}

        # Build per-asset series map: {"BTC": ["KXBTC15M", "KXBTC"], "ETH": [...], ...}
        self._asset_series_map: Dict[str, List[str]] = {}
        for series in self.config.series_tickers:
            asset, _ = self._infer_asset_timeframe(series)
            self._asset_series_map.setdefault(asset, []).append(series)

        # Per-asset indicator stacks with asset-specific configs from registry
        self._indicator_stacks: Dict[str, Any] = {}
        try:
            from merid.signals.crypto_15m_indicators import Crypto15mIndicatorStack, IndicatorConfig
            from merid.sentiment.crypto_registry import get_crypto_registry
            
            registry = get_crypto_registry()
            
            for asset in self._asset_series_map:
                # Get asset config from registry
                asset_config = registry.get_config(asset)
                if asset_config:
                    # Build IndicatorConfig from registry overrides
                    overrides = asset_config.indicator_overrides
                    cfg = IndicatorConfig(
                        vol_low_threshold=overrides.vol_low_threshold or 0.15,
                        vol_high_threshold=overrides.vol_high_threshold or 1.20,
                        atr_min_move_pct=overrides.atr_min_move_pct or 0.0003,
                        rsi_oversold=overrides.rsi_oversold or 30.0,
                        rsi_overbought=overrides.rsi_overbought or 70.0,
                        # FVG config from registry
                        fvg_enabled=asset_config.fvg_config.enabled,
                        fvg_min_gap_size_atr=asset_config.fvg_config.min_gap_size_atr,
                        fvg_min_gap_size_pct=asset_config.fvg_config.min_gap_size_pct,
                        fvg_max_age_bars=asset_config.fvg_config.max_age_bars,
                        fvg_max_zones_tracked=asset_config.fvg_config.max_zones_tracked,
                        fvg_pressure_weight=asset_config.fvg_config.pressure_weight,
                        fvg_relevance_distance_atr=asset_config.fvg_config.relevance_distance_atr,
                        fvg_ignore_immediate_fill=asset_config.fvg_config.ignore_immediate_fill,
                    )
                    
                    # Apply additional override fields if set
                    if overrides.consecutive_closes_required:
                        cfg.consecutive_closes_required = overrides.consecutive_closes_required
                    if overrides.distance_overextended_atrs:
                        cfg.distance_overextended_atrs = overrides.distance_overextended_atrs
                else:
                    # Fallback to defaults
                    cfg = IndicatorConfig()
                
                self._indicator_stacks[asset] = Crypto15mIndicatorStack(config=cfg)
                self._indicator_stacks[asset].set_asset_symbol(asset)
                logger.debug(
                    "Initialized FVG-enabled indicator stack for %s (fvg=%s, zones=%d)",
                    asset, cfg.fvg_enabled, cfg.fvg_max_zones_tracked
                )
        except Exception as _ie:
            logger.warning("Crypto15mIndicatorStack unavailable (flat 50/50 fallback): %s", _ie)

        # Pre-populate last_updated to 0.0 for all assets so staleness checks have a defined
        # starting point.  Real timestamps are written when stack.update(spot) succeeds.
        for _a in self._asset_series_map:
            self._indicator_last_updated.setdefault(_a, 0.0)

        # Telegram trade notifications (lazy import to avoid circular deps)
        try:
            from merid.alerts.trade_notifier import TradeNotifier
            digest_n = int(os.environ.get("CT_TG_DIGEST_EVERY", "4"))
            self._notifier: Optional["TradeNotifier"] = TradeNotifier(
                digest_every_n_cycles=digest_n,
                quiet_cycles=True,
            )
        except Exception:
            self._notifier = None

        # Load RSA credentials (guarded — failure disables trading but keeps instance alive)
        kalshi_env = os.environ.get("KALSHI_ENV", "demo").lower()
        if kalshi_env == "live":
            self._base_url = os.environ.get(
                "KALSHI_API_BASE_URL",
                "https://api.elections.kalshi.com/trade-api/v2",
            )
        else:
            self._base_url = os.environ.get(
                "KALSHI_API_BASE_URL",
                "https://demo-api.kalshi.co/trade-api/v2",
            )
        self._api_key_id = os.environ.get("KALSHI_API_KEY_ID", "")
        self._key_error: Optional[str] = None
        key_path = Path(os.environ.get("KALSHI_PRIVATE_KEY_PATH", "kalshi_private_key.pem"))
        if not key_path.is_absolute():
            key_path = Path(__file__).resolve().parent.parent.parent / key_path
        try:
            self._private_key = serialization.load_pem_private_key(
                key_path.read_bytes(), password=None
            )
        except Exception as _ke:
            self._private_key = None
            self._key_error = f"Key load failed ({key_path}): {_ke}"
            logger.error("KalshiContinuousTrader: %s — trading disabled", self._key_error)

        # Agent identity for unified logging and reporting
        self.series_ticker = self._resolve_series_ticker(self.config.series_tickers)
        self.asset_symbol = "CRYPTO"
        self.timeframe_label = "multi"
        self._active_assets = sorted(self._asset_series_map.keys())
        self.pct_band = self.config.max_strike_distance_pct * 100
        self.dollar_band = None
        # Pre-compute unique asset prefixes for position filtering (BUG-SM3 fix: dedup)
        _seen_prefixes: set = set()
        self._asset_prefixes: List[str] = []
        for series in self.config.series_tickers:
            prefix = (series.split("-")[0] if "-" in series else series).upper()
            if prefix not in _seen_prefixes:
                _seen_prefixes.add(prefix)
                self._asset_prefixes.append(prefix)

        # BTC-anchored cross-asset move model (feeds spot each cycle)
        self._btc_anchored_model: Optional[Any] = None
        try:
            from merid.signals.btc_anchored_move import get_btc_anchored_model
            self._btc_anchored_model = get_btc_anchored_model()
            logger.info("BtcAnchoredMoveModel attached to continuous trader")
        except Exception as _bam_exc:
            logger.warning("BtcAnchoredMoveModel unavailable (independent vol fallback): %s", _bam_exc)

        # BUG-SP4 fix: validate CoinGecko IDs cover all active assets
        _missing_cg = set(self._active_assets) - set(self._CG_IDS.keys())
        if _missing_cg:
            logger.warning("CoinGecko IDs missing for assets: %s — spot fetch will use fallback ID", _missing_cg)

        _ct_init_msg = (
            "KalshiContinuousTrader initialised: assets=%s, interval=%ds, min_edge=%s, "
            "bankroll=$%.2f, kelly=%.0f%%, max_price=%d¢, dry_run=%s, series_per_asset=%s"
        )
        _ct_init_args = (
            self._active_assets,
            self.config.interval_seconds,
            self.config.min_edge,
            self.config.initial_bankroll_cents / 100,
            self.config.kelly_fraction * 100,
            self.config.max_contract_price_cents,
            self.config.dry_run,
            {a: len(s) for a, s in self._asset_series_map.items()},
        )
        _suppress_ct_init = False
        try:
            from merid.prediction.pm_ct_policy import ct_loop_suppressed

            _suppress_ct_init = bool(ct_loop_suppressed())
        except Exception:
            pass
        if _suppress_ct_init:
            logger.debug(
                _ct_init_msg + " [PM mode: TraderConfig bankroll is legacy/dev — sizing uses KalshiRiskManager]",
                *_ct_init_args,
            )
        else:
            logger.info(_ct_init_msg, *_ct_init_args)

        # UPSTREAM INVARIANTS: Validate 5-asset wiring at startup (fail-fast)
        self._validate_asset_wiring()

        # GUARD SYSTEM: Pre-go-live checklist and runtime guards
        self._guardian: Optional[TradingGuardian] = None
        self._last_guard_check: float = 0.0  # Epoch timestamp of last guard re-check
        self._init_guard_system()

        # CONFIG FINGERPRINT: One-line summary of all critical trading parameters
        # This is the canonical truth for debugging - grep for [KALSHI_CT_CONFIG] to verify
        # Placed AFTER guard init so we can capture guard mode/status
        _guard_mode = "unknown"
        _can_trade = "unknown"
        _vol_anchor = "BTC"
        _caps_telemetry = None
        if self._guardian:
            _guard_mode = getattr(self._guardian.checklist, 'mode', 'unknown')
            _report = self._guardian.run_all_checks()
            _can_trade = getattr(_report, 'can_trade', 'unknown')
            _vol_anchor = getattr(self._guardian.checklist, 'vol_anchor_asset', 'BTC')
            # Get caps with full telemetry (raw vs effective, override status)
            try:
                bankroll = self.config.initial_bankroll_cents
                _caps_telemetry = self._guardian.get_caps_with_telemetry(
                    bankroll,
                    getattr(self._guardian.checklist, 'target_vol_annual', 0.65)
                )
            except Exception:
                _caps_telemetry = None
        
        # Format caps for logging - show both raw and effective when override is present
        if _caps_telemetry:
            _raw_caps = _caps_telemetry['raw_caps']
            _effective_caps = _caps_telemetry['effective_caps']
            _override_enabled = _caps_telemetry['override_enabled']
            _floor_cents = _caps_telemetry['floor_cents']
            
            # Format raw and effective caps
            _raw_str = ",".join([f"{k}={v:.4f}" for k, v in _raw_caps.items()])
            _effective_str = ",".join([f"{k}={v:.4f}" for k, v in _effective_caps.items()])
            
            # Log main config line
            _gn_cap = None
            try:
                from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk

                _gn_cap = getattr(get_kalshi_risk().config, "group_notional_cap_usd", None)
            except Exception:
                pass
            _trade_mode = os.getenv("MERID_TRADE_MODE", "")
            _allow_live = os.getenv("MERID_ALLOW_LIVE_TRADES", "")
            _log_ct_cfg = logger.debug if _suppress_ct_init else logger.info
            _log_ct_cfg(
                "[KALSHI_CT_CONFIG] dry_run=%s min_edge=%s max_price=%d¢ min_price=%d¢ "
                "kelly=%.2f max_pos_per_market=%d max_open=%d bankroll=%d¢ "
                "ct_profile=%s dir_tilt=%.2f guard_mode=%s can_trade=%s vol_anchor=%s env=%s "
                "base_url=%s MERID_TRADE_MODE=%s MERID_ALLOW_LIVE_TRADES=%s "
                "group_notional_cap_usd=%s universe_assets=%s",
                self.config.dry_run,
                self.config.min_edge,
                self.config.max_contract_price_cents,
                self.config.min_contract_price_cents,
                self.config.kelly_fraction,
                self.config.max_position_per_market,
                self.config.max_open_positions,
                self.config.initial_bankroll_cents,
                os.environ.get("KALSHI_CT_PROFILE", "production"),
                self.config.directional_max_tilt,
                _guard_mode,
                _can_trade,
                _vol_anchor,
                os.environ.get("KALSHI_ENV", "demo"),
                self._base_url,
                _trade_mode or "(default)",
                _allow_live or "false",
                _gn_cap,
                ",".join(self._active_assets),
            )
            
            # Log caps telemetry line (raw vs effective, override status)
            if _override_enabled:
                _override_applied = _caps_telemetry.get('override_applied', {})
                _applied_assets = [k for k, v in _override_applied.items() if v]
                _log_ct_cfg(
                    "[KALSHI_CT_CAPS] raw_caps={%s} tiny_bankroll_override=True floor=%d¢ "
                    "effective_caps={%s} override_applied_to=%s",
                    _raw_str,
                    _floor_cents,
                    _effective_str,
                    ",".join(_applied_assets) if _applied_assets else "none"
                )
            else:
                _log_ct_cfg(
                    "[KALSHI_CT_CAPS] caps={%s} tiny_bankroll_override=False",
                    _raw_str
                )
        else:
            # Fallback: simple caps logging without telemetry
            _trade_mode = os.getenv("MERID_TRADE_MODE", "")
            _allow_live = os.getenv("MERID_ALLOW_LIVE_TRADES", "")
            _log_ct_cfg_fb = logger.debug if _suppress_ct_init else logger.info
            _log_ct_cfg_fb(
                "[KALSHI_CT_CONFIG] dry_run=%s min_edge=%s max_price=%d¢ min_price=%d¢ "
                "kelly=%.2f max_pos_per_market=%d max_open=%d bankroll=%d¢ "
                "ct_profile=%s dir_tilt=%.2f guard_mode=%s can_trade=%s vol_anchor=%s env=%s caps=N/A "
                "MERID_TRADE_MODE=%s MERID_ALLOW_LIVE_TRADES=%s universe_assets=%s",
                self.config.dry_run,
                self.config.min_edge,
                self.config.max_contract_price_cents,
                self.config.min_contract_price_cents,
                self.config.kelly_fraction,
                self.config.max_position_per_market,
                self.config.max_open_positions,
                self.config.initial_bankroll_cents,
                os.environ.get("KALSHI_CT_PROFILE", "production"),
                self.config.directional_max_tilt,
                _guard_mode,
                _can_trade,
                _vol_anchor,
                os.environ.get("KALSHI_ENV", "demo"),
                _trade_mode or "(default)",
                _allow_live or "false",
                ",".join(self._active_assets),
            )

    def _init_guard_system(self) -> None:
        """Initialize trading guard system from go-live checklist."""
        try:
            checklist_path = Path("go_live_checklist.yaml")
            if checklist_path.exists():
                checklist = GoLiveChecklist.from_yaml(checklist_path)
                logger.info("[GUARD] Loaded go-live checklist from %s", checklist_path)
            else:
                checklist = GoLiveChecklist()
                checklist.save_default(checklist_path)
                logger.info("[GUARD] Created default go-live checklist at %s", checklist_path)
            
            self._guardian = TradingGuardian(checklist)

            # Promote assets to LIVE_SMALL when MERID_ALLOW_LIVE_TRADES is set.
            # KALSHI_CT_INITIAL_LIVE_ASSETS overrides the default asset list.
            # Without promotion all assets stay in OBSERVATION (size_cap=0%) and
            # no orders can be submitted regardless of edge or gate state.
            _allow_live = os.getenv("MERID_ALLOW_LIVE_TRADES", "false").lower() in ("1", "true", "yes")
            _promote_mode_str = os.getenv("KALSHI_CT_INITIAL_LIVE_MODE", "LIVE_SMALL").upper()
            _promote_mode = TradingMode.LIVE_FULL if _promote_mode_str == "LIVE_FULL" else TradingMode.LIVE_SMALL
            if _allow_live:
                _cap_val = 1.0 if _promote_mode == TradingMode.LIVE_FULL else 0.25
                _assets_to_promote_env = os.getenv("KALSHI_CT_INITIAL_LIVE_ASSETS", "")
                if _assets_to_promote_env.strip():
                    _assets_to_promote = [a.strip().upper() for a in _assets_to_promote_env.split(",") if a.strip()]
                else:
                    _assets_to_promote = list(self._active_assets)
                for _asset in _assets_to_promote:
                    # promote_asset_to_live() requires 10+ prior trades — on a fresh system
                    # that gate will never pass.  When the operator has set
                    # MERID_ALLOW_LIVE_TRADES=true we trust that explicit intent and force
                    # the caps directly, bypassing the eligibility check.
                    self._guardian.checklist.live_size_caps[_asset] = _cap_val
                    logger.info("[GUARD] Force-promoted %s → cap=%.0f%% (operator override)", _asset, _cap_val * 100)
                # The global mode must also be upgraded — compute_live_cap() returns 0
                # for any asset whenever checklist.mode == OBSERVATION regardless of caps.
                self._guardian.checklist.mode = _promote_mode
                logger.info("[GUARD] Global mode → %s (MERID_ALLOW_LIVE_TRADES override)", _promote_mode.value)
                # Switch to static caps — the computed formula assumes $1/contract risk
                # and produces 0 for small bankrolls; the static live_size_caps (set above)
                # are the correct Kelly fraction to apply on a small live account.
                self._guardian.checklist.use_computed_caps = False
                logger.info("[GUARD] use_computed_caps → False (static Kelly caps active)")

            # Run initial guard check
            report = self._guardian.run_all_checks()

            if not report.can_trade:
                logger.warning(
                    "[GUARD] Trading DISABLED on startup - mode=%s, status=%s",
                    checklist.mode.value,
                    report.overall_status.value
                )
                if checklist.observation_reason:
                    logger.warning("[GUARD] Observation reason: %s", checklist.observation_reason)
            else:
                logger.info(
                    "[GUARD] Trading ENABLED - mode=%s, assets=%s",
                    checklist.mode.value,
                    checklist.upstream.get("market_sanity", {}).get("required_assets", [])
                )
                
        except Exception as e:
            logger.warning("[GUARD] Failed to initialize guard system: %s", e)
            # Continue without guards - trading will use default safe mode
            self._guardian = None

    def _validate_asset_wiring(self) -> None:
        """Validate that all expected assets are properly wired into configs and mappings.
        
        Invariants checked (all hard errors except strike bands):
        - Asset universe: active assets must equal expected AssetSymbol set
        - External ID: all assets have CoinGecko IDs and spot fallback maps
        - Strike bands: all assets have distance bands (warning only)
        - Exposure: all assets have exposure caps; detect unused caps
        - Series resolution: all series tickers resolve to known assets
        
        Logs [CRYPTO-WIRING-BUG] on violations and raises ValueError for hard failures.
        """
        # Import expected universe from canonical config (single source of truth)
        from config.kalshi_universe import EXPECTED_CRYPTO_UNIVERSE
        
        active_assets = set(self._active_assets)
        
        # 1) Asset universe invariant: active assets must match expected set from config
        if active_assets != EXPECTED_CRYPTO_UNIVERSE:
            configured_sorted = sorted(active_assets)
            expected_sorted = sorted(EXPECTED_CRYPTO_UNIVERSE)
            logger.error(
                "[CRYPTO-WIRING-BUG] asset_universe "
                "configured=%s expected=%s",
                configured_sorted, expected_sorted
            )
            raise ValueError(
                f"Asset universe mismatch: configured={configured_sorted} expected={expected_sorted}"
            )
        
        # 2) External ID invariant: all active assets must have CoinGecko IDs
        for asset in active_assets:
            if asset not in self._CG_IDS:
                logger.error(
                    "[CRYPTO-WIRING-BUG] external_id "
                    "asset=%s reason=missing_coingecko_id",
                    asset
                )
                raise ValueError(f"Missing CoinGecko id for {asset}")
        
        # 3) Spot source invariant: Coinbase USD-denominated pairs only.
        # Binance USDT fallback removed — USDT is a different price series and
        # causes systematic drift vs USD-settled Kalshi contracts.
        _cb_map = {"BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD",
                   "XRP": "XRP-USD", "DOGE": "DOGE-USD"}
        for asset in active_assets:
            if asset not in _cb_map:
                logger.error(
                    "[CRYPTO-WIRING-BUG] external_id "
                    "asset=%s reason=missing_coinbase_usd_pair",
                    asset
                )
                raise ValueError(f"Missing Coinbase USD pair for {asset}")
        
        # 4) Strike band invariant: all active assets should have distance bands (warning only)
        for asset in active_assets:
            if (asset, "15m") not in self._STRIKE_BAND_PCT and (asset, "1h") not in self._STRIKE_BAND_PCT:
                logger.warning(
                    "[CRYPTO-WIRING-WARN] strike_bands "
                    "asset=%s reason=missing_strike_band_pct",
                    asset
                )
        
        # 5) Exposure invariant: all active assets have exposure caps
        cfg = self.config
        for asset in active_assets:
            if asset not in cfg.asset_max_exposure_pct:
                logger.error(
                    "[CRYPTO-WIRING-BUG] exposure "
                    "asset=%s reason=missing_exposure_cap",
                    asset
                )
                raise ValueError(f"Missing exposure cap for {asset}")
        
        # 5b) Detect unused exposure caps (assets with caps but no markets configured)
        assets_with_markets = set(self._asset_series_map.keys())
        for asset, cap in cfg.asset_max_exposure_pct.items():
            if asset not in active_assets or asset not in assets_with_markets:
                logger.warning(
                    "[CRYPTO-WIRING-WARN] exposure "
                    "asset=%s cap=%s reason=unused_cap_no_markets",
                    asset, cap
                )
        
        # 6) Series resolution invariant: verify all series resolve to known assets
        for series in cfg.series_tickers:
            asset, tf = self._infer_asset_timeframe(series)
            if asset == "UNK" or asset not in active_assets:
                logger.error(
                    "[CRYPTO-WIRING-BUG] series_resolution "
                    "series=%s asset=%s",
                    series, asset
                )
                raise ValueError(f"Series {series} resolves to unsupported asset {asset}")
        
        # Success log
        logger.info(
            "[CRYPTO-WIRING-OK] upstream_invariants "
            "assets=%s coingecko=%d/%d coinbase_pairs=%d/%d exposure=%d/%d series=%d",
            sorted(active_assets),
            len([a for a in active_assets if a in self._CG_IDS]),
            len(active_assets),
            len([a for a in active_assets if a in _cb_map]),
            len(active_assets),
            len([a for a in active_assets if a in cfg.asset_max_exposure_pct]),
            len(active_assets),
            len(cfg.series_tickers)
        )

    # ── Agent identity & logging helpers ─────────────────────────────────

    @staticmethod
    def _resolve_series_ticker(series_tickers: List[str]) -> str:
        if not series_tickers:
            return ""
        for series in series_tickers:
            if "-" in series:
                return series
        return series_tickers[0]

    @staticmethod
    def _infer_asset_timeframe(series_ticker: str) -> tuple[str, str]:
        """Extract (asset, timeframe) from a **series** ticker string.

        This is the canonical entry point for series-level strings in the continuous
        trader; do not duplicate parallel regex maps elsewhere—extend
        ``kalshi_crypto_series_meta`` instead.

        Returns timeframes: 15m, 1h, daily, weekly (catalog format).

        Resolution order: ``infer_asset_timeframe_from_ticker`` (exact meta match),
        then legacy heuristics for non-catalog spellings (e.g. KXETH1H, BTUPDOWN).
        """
        if not series_ticker:
            return "UNK", "UNK"

        from config.kalshi_crypto_series_meta import infer_asset_timeframe_from_ticker

        series_prefix = series_ticker.upper().split("-")[0].strip()
        asset, tf = infer_asset_timeframe_from_ticker(series_prefix)
        if asset != "UNK":
            return asset, tf

        cleaned = series_ticker.upper().removeprefix("KX")
        timeframe = "daily"  # default
        underlying = cleaned

        # Extract timeframe if separated by dash: SYMBOL-TIMEFRAME
        if "-" in cleaned:
            underlying, tf_suffix = cleaned.split("-", 1)
            # Normalize suffix to catalog format
            if tf_suffix in ("15M", "15"):
                timeframe = "15m"
            elif tf_suffix in ("1H", "H1", "1"):
                timeframe = "1h"
            elif tf_suffix in ("D1", "1D", "D"):
                timeframe = "daily"
            elif tf_suffix in ("W1", "1W", "W"):
                timeframe = "weekly"
            else:
                timeframe = tf_suffix.lower()
        # Try to extract trailing timeframe (e.g., KXETH1H → underlying=ETH, timeframe=1h)
        # Use greedy alpha + specific suffix pattern to avoid DOGED1→(D, OGED1) misparse
        elif len(cleaned) > 3:
            match = re.search(r"([A-Z]+)(15M|1H|H1|D1|1D|W1|1W|\d+[MHDW])$", cleaned)
            if match:
                underlying, tf_suffix = match.groups()
                # Normalize to catalog format
                if tf_suffix in ("15M", "15"):
                    timeframe = "15m"
                elif tf_suffix in ("1H", "H1", "1"):
                    timeframe = "1h"
                elif tf_suffix in ("D1", "1D"):
                    timeframe = "daily"
                elif tf_suffix in ("W1", "1W"):
                    timeframe = "weekly"
                else:
                    timeframe = tf_suffix.lower()

        # Strip directional keywords to recover base asset (BTUPDOWN → BTC, ETHUPDOWN → ETH)
        for keyword in ["UPDOWN", "UP-DOWN", "DIRECTION"]:
            if underlying.endswith(keyword):
                underlying = underlying[:-len(keyword)]
                break

        # Expand short token codes to standard names (BT→BTC, ET→ETH, etc.)
        token_map = {"BT": "BTC", "ET": "ETH", "SO": "SOL", "XR": "XRP", "DO": "DOGE"}
        if underlying in token_map:
            underlying = token_map[underlying]

        underlying = underlying.strip("-").strip() or "UNK"

        return underlying, timeframe

    @staticmethod
    def evaluate_entry_exposure_skip(
        balance_cents: int,
        current_total_exposure_cents: int,
        per_asset_exposure_cents: Dict[str, int],
        cost_cents: int,
        candidate_asset: str,
        candidate_tf: str,
        config: TraderConfig,
    ) -> Optional[str]:
        """Return ``per_asset`` or ``global`` if a buy should be skipped; else ``None``.

        Single source for the two-stage exposure gate (per-asset first, then global).
        All monetary arguments are **integer cents** of bankroll / notional (CT convention).
        """
        asset_max_pct = config.asset_max_exposure_pct.get(
            candidate_asset, config.asset_exposure_default_pct
        )
        mult = config.series_exposure_multiplier.get(candidate_tf, 1.0)
        asset_cap = max(
            config.min_asset_cap_cents,
            int(balance_cents * asset_max_pct * mult),
        )
        asset_cur = per_asset_exposure_cents.get(candidate_asset, 0)
        if asset_cur + cost_cents > asset_cap:
            return "per_asset"
        global_cap = int(balance_cents * config.global_max_exposure_pct)
        if current_total_exposure_cents + cost_cents > global_cap:
            return "global"
        return None

    @staticmethod
    def _vol_benchmark_spot_and_asset(
        spot_prices: Dict[str, float],
        active_assets: List[str],
    ) -> tuple[Optional[float], Optional[str]]:
        """Return (spot, asset_key) for bankroll vol; prefer MERID_CT_VOL_BENCHMARK then defaults."""
        env_b = (os.environ.get("MERID_CT_VOL_BENCHMARK") or "").strip().upper()
        if env_b:
            v = spot_prices.get(env_b)
            if v is not None:
                return (v, env_b)
            logger.warning(
                "MERID_CT_VOL_BENCHMARK=%s has no spot this cycle (active_assets=%s, spot_keys=%s) — falling back",
                env_b,
                active_assets,
                sorted(spot_prices.keys()),
            )
        for sym in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
            if sym in active_assets and spot_prices.get(sym) is not None:
                return (spot_prices[sym], sym)
        for a in sorted(active_assets):
            if spot_prices.get(a) is not None:
                return (spot_prices[a], a)
        if spot_prices.get("BTC") is not None:
            return (spot_prices["BTC"], "BTC")
        if spot_prices.get("ETH") is not None:
            return (spot_prices["ETH"], "ETH")
        return (None, None)

    @staticmethod
    def _vol_benchmark_spot(
        spot_prices: Dict[str, float],
        active_assets: List[str],
    ) -> Optional[float]:
        """Pick one spot price for bankroll vol; see ``_vol_benchmark_spot_and_asset``."""
        v, _ = KalshiContinuousTrader._vol_benchmark_spot_and_asset(spot_prices, active_assets)
        return v

    def _format_band(self, pct_band: float | None = None, dollar_band: float | None = None) -> str:
        if pct_band is not None:
            return f"±{pct_band:.1f}%"
        if dollar_band is not None:
            return f"±{dollar_band:.2f}"
        return "±N/A"

    def _log_markets_near_spot(
        self,
        markets_near_spot: list,
        asset_symbol: str,
        timeframe_label: str,
        spot_price: float,
        series_ticker: str,
        status: str = "open",
        selector: str = "top_by_distance",
        pct_band: float | None = None,
        dollar_band: float | None = None,
    ) -> None:
        band_str = self._format_band(pct_band=pct_band, dollar_band=dollar_band)
        asset_series = f"{asset_symbol}-{timeframe_label}"
        logger.info(
            "Scanning %d %s Kalshi markets within %s of spot %.2f "
            "(series=%s, status=%s, selector=%s)...",
            len(markets_near_spot),
            asset_series,
            band_str,
            spot_price,
            series_ticker,
            status,
            selector,
        )

    # ── Auth ──────────────────────────────────────────────────────────

    def _sign(self, method: str, path: str) -> dict:
        if self._private_key is None:
            raise RuntimeError(self._key_error or "RSA private key not loaded")
        ts_ms = str(int(time.time() * 1000))
        # BUG-40 fix: derive path prefix from base_url instead of hardcoding
        _prefix = "/trade-api/v2"
        try:
            from urllib.parse import urlparse
            _parsed = urlparse(self._base_url)
            if _parsed.path:
                _prefix = _parsed.path.rstrip("/")
        except Exception:
            pass
        full_path = _prefix + path
        msg = ts_ms + method.upper() + full_path
        sig = self._private_key.sign(
            msg.encode(),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self._api_key_id,
            "KALSHI-ACCESS-TIMESTAMP": ts_ms,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
            "Content-Type": "application/json",
        }

    @staticmethod
    def _transport_failure_response() -> requests.Response:
        """Return a response object for local/network failures (status 0 — not from Kalshi)."""
        r = requests.models.Response()
        r.status_code = _CT_TRANSPORT_FAILURE_STATUS
        return r

    def _get(self, path: str, params: dict | None = None) -> requests.Response:
        try:
            return requests.get(
                self._base_url + path, headers=self._sign("GET", path),
                params=params, timeout=15,
            )
        except requests.exceptions.RequestException as exc:
            logger.warning(
                "GET %s failed (local/transport, status=%s): %s",
                path, _CT_TRANSPORT_FAILURE_STATUS, exc,
            )
            return self._transport_failure_response()

    def _post(self, path: str, data: dict) -> requests.Response:
        try:
            return requests.post(
                self._base_url + path, headers=self._sign("POST", path),
                json=data, timeout=15,
            )
        except requests.exceptions.RequestException as exc:
            logger.warning(
                "POST %s failed (local/transport, status=%s): %s",
                path, _CT_TRANSPORT_FAILURE_STATUS, exc,
            )
            return self._transport_failure_response()

    def _delete(self, path: str) -> requests.Response:
        try:
            return requests.delete(
                self._base_url + path, headers=self._sign("DELETE", path), timeout=15,
            )
        except requests.exceptions.RequestException as exc:
            logger.warning(
                "DELETE %s failed (local/transport, status=%s): %s",
                path, _CT_TRANSPORT_FAILURE_STATUS, exc,
            )
            return self._transport_failure_response()

    def _build_synthetic_response(
        self,
        router_result: "OrderResult",
        order_data: dict,
    ) -> requests.Response:
        """Build synthetic HTTP-like response from router OrderResult for compatibility.

        Phase 2/3 migration: Converts router result to response object that
        downstream code expects (status_code, .json() method, etc).
        """
        from requests import Response

        resp = Response()
        resp.status_code = 201 if "filled" in router_result.status else 200

        # Build order dict matching Kalshi API format
        order_payload = {
            "order_id": router_result.order_id or str(uuid.uuid4()),
            "client_order_id": order_data.get("client_order_id"),
            "status": router_result.status,
            "ticker": order_data.get("ticker"),
            "action": order_data.get("action"),
            "side": order_data.get("side"),
            "count": order_data.get("count"),
            "price": order_data.get("yes_price") or order_data.get("no_price"),
            "fill_count_fp": router_result.fill.get("count", 0) if router_result.fill else 0,
            "taker_fees_dollars": "0.00",  # Router handles fee accounting separately
        }

        # Manually set _content for json() method to work
        import json
        resp._content = json.dumps({"order": order_payload}).encode("utf-8")
        resp.headers["Content-Type"] = "application/json"

        return resp

    # ── Data helpers (all sync, called via run_in_executor) ──────────

    _CG_IDS = {
        "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
        "XRP": "ripple", "DOGE": "dogecoin",
    }

    def _get_all_spots(self) -> Dict[str, float]:
        """Batch-fetch all crypto spot prices using unified CryptoSpotService.

        Priority: Coinbase (primary) -> BinanceUS (fallback) -> CoinGecko (final fallback)
        Features: TTL caching, rate limit awareness, source tracking for observability.

        IMPORTANT: These spot feeds are PROXIES for market context, NOT the
        CF Benchmarks RTIs that Kalshi uses for settlement.
        """
        from merid.trading.crypto_spot_service import get_crypto_spot_service

        service = get_crypto_spot_service()
        result = service.get_all_spots(self._active_assets, use_cache=True)

        # Track metadata for observability
        now = time.time()
        _stale_count = 0
        _failed_count = len(result.failed)
        for asset, spot in result.prices.items():
            self._last_spots[asset] = {
                "price": spot.price,
                "fetched_at": spot.timestamp,
                "source": spot.source,
                "age_seconds": spot.age_seconds,
                "is_stale": spot.is_stale,
            }
            if spot.is_stale:
                _stale_count += 1

        # Log source distribution
        if result.by_source.get("coinbase"):
            logger.debug("  Spot sources - Coinbase: %s", result.by_source["coinbase"])
        if result.by_source.get("binanceus"):
            logger.debug("  Spot sources - BinanceUS: %s", result.by_source["binanceus"])
        if result.by_source.get("coingecko"):
            logger.debug("  Spot sources - CoinGecko: %s", result.by_source["coingecko"])
        if result.by_source.get("stale_cache"):
            logger.warning("  Spot sources - STALE CACHE: %s", result.by_source["stale_cache"])
        if result.failed:
            logger.warning("  Spot sources - FAILED: %s", result.failed)

        # Spot feed degraded: local heuristics + CryptoSpotService venue streaks
        _total_assets = len(self._active_assets)
        _available_assets = len(result.prices)
        _venue_degraded = bool(getattr(result, "spot_feed_degraded", False))
        if getattr(result, "venue_health", None):
            logger.debug("  Spot venue health: %s", result.venue_health)
        _spot_feed_degraded = _venue_degraded or (_failed_count > _total_assets * 0.5) or (
            _available_assets > 0 and _stale_count == _available_assets
        )
        if _spot_feed_degraded:
            logger.warning(
                "[SPOT-FEED-DEGRADED] assets=%d failed=%d stale=%d venue_flag=%s — blocking new trades",
                _total_assets, _failed_count, _stale_count, _venue_degraded,
            )
            # Store degraded flag for this cycle (trading logic checks this)
            self._spot_feed_degraded_this_cycle = True
        else:
            self._spot_feed_degraded_this_cycle = False

        # Return dict of asset -> price for backward compatibility
        return {asset: spot.price for asset, spot in result.prices.items()}

    def _get_spot(self, asset: str = "BTC") -> Optional[float]:
        """Single-asset spot fetch (backward-compat). Prefer _get_all_spots()."""
        results = self._get_all_spots()
        return results.get(asset.upper())

    @staticmethod
    def _avg_price_cents_from_position_payload(p: dict) -> int:
        """Best-effort entry price in cents from Kalshi portfolio position dict."""
        raw = p.get("avg_price_cents")
        if raw is not None:
            try:
                return max(0, int(float(raw)))
            except (TypeError, ValueError):
                pass
        for key in ("avg_price", "average_price", "avg_entry_price"):
            if p.get(key) is None:
                continue
            try:
                return max(0, int(float(p[key])))
            except (TypeError, ValueError):
                continue
        return 0

    def _position_cost_basis_cents(self, info: dict) -> int:
        """Capital at risk for exposure caps.

        Prefers total_cost_cents (real Kalshi API field, populated by _get_positions)
        over the estimated qty × avg_price fallback.
        """
        q = abs(int(info.get("qty", 0)))
        if q == 0:
            return 0
        # Use Kalshi-provided total_cost when available (most accurate)
        tc = int(info.get("total_cost_cents", 0) or 0)
        if tc > 0:
            return tc
        # Fallback: qty × avg entry price; unknown entry → 100¢/contract (conservative)
        ap = int(info.get("avg_price_cents", 0) or 0)
        if ap <= 0:
            ap = 100
        return q * ap

    def _aggregate_position_exposure_cents(self, positions: Dict[str, dict]) -> int:
        return sum(self._position_cost_basis_cents(v) for v in positions.values() if v.get("qty", 0) != 0)

    def _per_asset_exposure_cents(self, positions: Dict[str, dict]) -> Dict[str, int]:
        """Break down current position exposure by underlying asset.

        Returns a dict mapping asset symbol (BTC, ETH, SOL, XRP, DOGE, …) to
        total estimated capital at risk in cents across all series/timeframes.
        Zero-qty positions are excluded.
        """
        result: Dict[str, int] = {}
        for ticker, info in positions.items():
            if info.get("qty", 0) == 0:
                continue
            series_prefix = ticker.split("-")[0] if "-" in ticker else ticker
            asset, _ = self._infer_asset_timeframe(series_prefix)
            result[asset] = result.get(asset, 0) + self._position_cost_basis_cents(info)
        return result

    def _warn_if_unk_asset_for_exposure(self, ticker: str, series_key: str, candidate_asset: str) -> None:
        """Log when series inference yields UNK so new tickers are visible in ops logs."""
        if candidate_asset != "UNK":
            return
        logger.warning(
            "    %s: series prefix %r → UNK asset; using default exposure pct %.2f",
            ticker,
            series_key,
            self.config.asset_exposure_default_pct,
        )

    def _live_api_orders_allowed(self) -> Tuple[bool, str]:
        """Block real orders to Kalshi live API unless PM live mode is explicitly enabled.

        Demo/sandbox (KALSHI_ENV != live) is always allowed. Set
        KALSHI_CT_BYPASS_PM_LIVE_GATE=true only if you run CT-only live without the loop.
        """
        # CRITICAL: OBSERVATION mode always blocks live orders regardless of bypass settings
        if self._guardian and self._guardian.checklist.mode == TradingMode.OBSERVATION:
            # Even with bypass, log a clear warning
            if os.getenv("KALSHI_CT_BYPASS_GUARD", "").lower() in ("1", "true", "yes"):
                logger.critical(
                    "[GUARD-BYPASS-WARNING] KALSHI_CT_BYPASS_GUARD is set but guard mode is OBSERVATION — "
                    "live orders STILL BLOCKED. Use SHADOW or LIVE_SMALL mode to trade."
                )
            return False, "Guard mode is OBSERVATION - live orders disabled"

        if self.config.dry_run:
            return True, ""
        allow_live = os.getenv("MERID_ALLOW_LIVE_TRADES", "false").lower()
        if allow_live not in ("1", "true", "yes", "on"):
            return False, "MERID_ALLOW_LIVE_TRADES not set — global live gate is off"
        kalshi_env = os.environ.get("KALSHI_ENV", "demo").lower()
        if kalshi_env != "live":
            logger.warning(
                "_live_api_orders_allowed: KALSHI_ENV=%r — orders route to DEMO/sandbox (%s). "
                "Set KALSHI_ENV=live to submit real orders.",
                kalshi_env, self._base_url,
            )
            return True, ""
        if os.getenv("KALSHI_CT_BYPASS_PM_LIVE_GATE", "").lower() in ("1", "true", "yes"):
            logger.warning(
                "KALSHI_CT_BYPASS_PM_LIVE_GATE set — live CT orders without MERID PM live interlock",
            )
            return True, ""
        try:
            from merid.prediction.pm_ct_policy import ct_legacy_must_not_trade

            _blocked, _bmsg = ct_legacy_must_not_trade()
            if _blocked:
                return False, _bmsg
        except Exception as _pol:
            logger.debug("pm_ct_policy check skipped: %s", _pol)
        # Check MERID_PM settings — prefer live env vars directly so a stale
        # settings singleton (created before dotenv loads) cannot veto live orders
        # when the operator has explicitly set the env vars in .env.
        try:
            from merid.settings import settings
            pm_mode = settings.MERID_PM_TRADING_MODE
            pm_live = settings.MERID_PM_LIVE_ENABLED
        except Exception:
            pm_mode = None
            pm_live = None

        # Fall back to direct env reads when the singleton still holds defaults
        if not pm_mode or pm_mode == "paper":
            pm_mode = os.getenv("MERID_PM_TRADING_MODE", "paper")
        if not pm_live:
            pm_live = os.getenv("MERID_PM_LIVE_ENABLED", "false").lower() in ("1", "true", "yes")

        if pm_mode == "live" and pm_live:
            return True, ""
        return False, (
            "KALSHI_ENV=live requires MERID_PM_TRADING_MODE=live and MERID_PM_LIVE_ENABLED=true "
            f"(got mode={pm_mode!r}, live_enabled={pm_live})"
        )

    def _sync_execution_guard_kalshi_exposure(self, exposure_cents: int) -> None:
        try:
            from merid.execution_guard import get_execution_guard

            get_execution_guard().sync_venue_exposure("kalshi", exposure_cents / 100.0)
        except Exception as exc:
            logger.warning(
                "[CT_EXECUTION_GUARD_SYNC_FAILED] execution_guard.sync_venue_exposure failed: %s — "
                "exposure data may be stale", exc
            )

    def _auto_exit_enabled(self) -> bool:
        return os.getenv("KALSHI_CT_AUTO_EXIT", "").lower() in ("1", "true", "yes")

    def _submit_sell_yes_limit(
        self,
        ticker: str,
        qty: int,
        limit_yes_cents: int,
        *,
        dry_run: bool,
        live_ok: bool,
        live_block_reason: str,
    ) -> bool:
        """Submit sell YES to close a long. Returns True if order accepted (201) or dry-run."""
        if qty <= 0:
            return False
        # Deterministic client_order_id so Kalshi deduplicates retries for exit orders.
        # Key = ticker + side + price so the same exit attempt always maps to the same ID.
        _exit_coid_key = f"exit-{ticker}-yes-{max(1, min(99, limit_yes_cents))}"
        order_data = {
            "ticker": ticker,
            "action": "sell",
            "side": "yes",
            "count": qty,
            "type": "limit",
            "yes_price": max(1, min(99, limit_yes_cents)),
            "client_order_id": str(uuid.uuid5(uuid.NAMESPACE_DNS, _exit_coid_key)),
        }
        logger.info(
            "  -> EXIT ORDER: SELL YES %dx %s @ %d¢",
            qty, ticker, order_data["yes_price"],
        )
        if dry_run:
            logger.info("    [DRY RUN] %s", json.dumps(order_data))
            return True
        if not live_ok:
            logger.warning("    EXIT blocked: %s", live_block_reason)
            return False
        resp = self._post("/portfolio/orders", order_data)
        if resp.status_code == 201:
            order = resp.json().get("order", resp.json())
            status = order.get("status", "?")
            oid = order.get("order_id", "?")
            fee = int(float(order.get("taker_fees_dollars", "0")) * 100)
            logger.info("    EXIT %s | id=%s", status.upper(), oid)
            cost_est = order_data["yes_price"] * qty
            self.tracker.record_order(order, cost_est)
            if self._notifier:
                self._notifier.record_fill(
                    ticker=ticker,
                    side="yes",
                    contracts=qty,
                    price_cents=order_data["yes_price"],
                    fee_cents=fee,
                    edge=0.0,
                    status=status,
                    order_id=oid,
                )
            return True
        if resp.status_code == _CT_TRANSPORT_FAILURE_STATUS:
            logger.warning("    EXIT FAILED: local/transport error (see prior POST warning)")
        else:
            logger.warning("    EXIT FAILED %d: %s", resp.status_code, resp.text[:200])
        return False

    def _get_balance(self) -> Tuple[int, int]:
        """Return (available_balance_cents, portfolio_value_cents).

        Kalshi /portfolio/balance returns:
          {"balance": <available_cents>, "locked_balance": <locked_cents>}
        There is no 'portfolio_value' field — open position value is derived
        by summing total_cost across positions fetched separately.
        """
        for attempt in range(2):
            r = self._get("/portfolio/balance")
            if r.status_code == 200:
                d = r.json()
                available = int(d.get("balance", 0))
                # portfolio_value is not returned by /portfolio/balance.
                # It is computed from _get_positions() total_cost sums.
                # We return 0 here; the cycle reconciles using _current_exposure_cents
                # which is computed from live positions below.
                return available, 0
            if attempt == 0 and r.status_code in (429, 503):
                logger.warning(
                    "[BALANCE-FETCH-RETRY] HTTP %d on attempt 1 — sleeping 2s before retry",
                    r.status_code,
                )
                time.sleep(2)
                continue
            break
        logger.warning(
            "[BALANCE-FETCH-FAIL] HTTP %d — returning (0,0); all trades will be skipped this cycle",
            r.status_code,
        )
        return 0, 0

    def _get_positions(self) -> Dict[str, dict]:
        """Fetch positions from Kalshi.

        Returns {ticker: {"qty": int, "side": str, "avg_price_cents": int, "total_cost_cents": int}}.

        BUG-34 fix: tracks side (yes/no) alongside quantity.
        BUG-35 fix: captures total_cost per position so the caller can derive
        portfolio_value_cents = sum(pos["total_cost_cents"] for pos in positions.values())
        without relying on the non-existent /portfolio/balance.portfolio_value field.
        """
        r = self._get("/portfolio/positions")
        positions: Dict[str, dict] = {}
        if r.status_code == 200:
            data = r.json()
            items = data.get("market_positions", data.get("positions", []))
            if isinstance(items, list):
                for p in items:
                    ticker = p.get("ticker", "")
                    pos = int(float(p.get("position_fp", p.get("position", p.get("count", 0)))))
                    side = p.get("side", "yes")
                    avg_c = self._avg_price_cents_from_position_payload(p)
                    total_cost_c = int(p.get("total_cost", 0))
                    positions[ticker] = {
                        "qty": pos, "side": side,
                        "avg_price_cents": avg_c, "total_cost_cents": total_cost_c,
                    }
            elif isinstance(items, dict):
                for ticker, p in items.items():
                    pos = int(float(p.get("position_fp", p.get("position", p.get("count", 0)))))
                    side = p.get("side", "yes")
                    avg_c = self._avg_price_cents_from_position_payload(p)
                    total_cost_c = int(p.get("total_cost", 0))
                    positions[ticker] = {
                        "qty": pos, "side": side,
                        "avg_price_cents": avg_c, "total_cost_cents": total_cost_c,
                    }
        return positions

    def _fetch_markets(self, series: str, limit: int = 200) -> List[dict]:
        r = self._get("/markets", params={"limit": limit, "status": "open", "series_ticker": series})
        if r.status_code == 200:
            return r.json().get("markets", [])
        return []

    def _fetch_orderbook(self, ticker: str) -> Optional[dict]:
        r = self._get(f"/markets/{ticker}/orderbook", params={"depth": 5})
        if r.status_code == 200:
            return r.json().get("orderbook", r.json())
        return None

    @staticmethod
    def _parse_strike(ticker: str) -> Optional[float]:
        """Parse strike price from Kalshi ticker.

        Handles three formats observed in live data:
        - Threshold: KXBTC-26MAR2501-T80199.99 → 80199.99
        - Bracket:   KXBTC-26MAR2501-B80150    → 80150.0
        - Legacy:    KXBTC-26MAR-T95000        → 95000.0

        Does NOT match:
        - Directional 15m: KXBTC15M-26MAR250015-15 → None (the -15 is a time marker)

        BUG-58 fix: Handles -B (bracket) prefix, not just -T (threshold).
        """
        # Primary: -T or -B followed by a number at end of ticker
        m = re.search(r"-[TB](\d+(?:\.\d+)?)$", ticker)
        if m:
            return float(m.group(1))
        # No fallback for ambiguous formats — require explicit -T or -B prefix
        # to avoid misinterpreting time markers (-15, -30) as strikes.
        return None

    @staticmethod
    def _is_directional_market(ticker: str) -> bool:
        """Return True for directional markets (no strike/bracket price).

        Matches:
        - Explicit UPDOWN/DIRECTION keywords
        - 15-minute series tickers (KXBTC15M-...) that have no -T/-B strike suffix
        """
        t = ticker.upper()
        if "UPDOWN" in t or "UP-DOWN" in t or "DIRECTION" in t:
            return True
        # 15m series tickers without -T or -B are directional
        if "15M" in t and not re.search(r"-[TB]\d", t):
            return True
        return False

    # ── Per-asset × timeframe strike distance bands ────────────────────
    # Single source of truth: merid.prediction.kalshi_strike_selector.DEFAULT_MAX_DISTANCE
    # Imported once at class level; NearSpotSelector receives these as per_asset_max_distance_pct.
    # Rule of thumb: band ≈ 5–10× expected move for that timeframe.
    # vol_map in edge_model: 15m=0.3%, 1h=0.8%, daily=2.5%, weekly=6%.
    _STRIKE_BAND_PCT: Dict[Tuple[str, str], float] = _load_strike_band_pct()

    # ── Per-asset spend / contract caps (Section 2 of risk config) ───────
    # MAX_SPEND_PER_CONTRACT: maximum USD we spend per single order (i.e. the
    # total notional for one market entry), regardless of what Kelly suggests.
    # Named "per-contract" to match the ops spec but semantically per-ORDER.
    MAX_SPEND_PER_CONTRACT: Dict[str, float] = {
        "BTC":  12.50,   # $10–15 range → midpoint $12.50
        "ETH":   8.50,   # $7–10  range → midpoint $8.50
        "SOL":   6.00,   # $5–7   range → midpoint $6.00
        "XRP":   6.00,   # $5–7   range → midpoint $6.00
        "DOGE":  4.00,   # $3–5   range → midpoint $4.00
    }
    # MAX_CONTRACTS_PER_MARKET: hard cap on contracts per ticker per order.
    # Applied AFTER Kelly sizing, BEFORE exposure checks.
    MAX_CONTRACTS_PER_MARKET: Dict[str, int] = {
        "BTC":  5,
        "ETH":  4,
        "SOL":  4,
        "XRP":  4,
        "DOGE": 5,
    }

    def _max_strike_distance_for(self, asset: str, timeframe: str) -> float:
        """Return the max strike distance % for a given asset/timeframe, with fallback."""
        return self._STRIKE_BAND_PCT.get(
            (asset, timeframe), self.config.max_strike_distance_pct,
        )

    # ── Edge computation (BUG-EM1/EM2/EM3/RE3 fixes) ─────────────────

    def _compute_edge(self, c: MarketCandidate) -> MarketCandidate:
        _math = math

        # Defensive: use getattr with default to avoid AttributeError if a path
        # somehow still passes an unenriched candidate (e.g., from NearSpotSelector
        # before orderbook data is attached).
        spot = Decimal(str(getattr(c, "spot", 0) or 0))
        strike = Decimal(str(getattr(c, "strike", 0) or 0))
        is_directional = getattr(c, "is_directional", False)

        if is_directional:
            yes_prob = Decimal("0.50")
            # Gate on indicator staleness (BUG-SP3 fix)
            last_update = self._indicator_last_updated.get(c.asset or "BTC", 0)
            stack_stale = (time.time() - last_update) > 180 if last_update > 0 else True
            stack = self._indicator_stacks.get(c.asset or "BTC") if (self._indicator_stacks and not stack_stale) else None
            if stack is not None:
                try:
                    snap = stack.snapshot()
                    confidence = Decimal(str(snap.bias_confidence))
                    max_tilt = Decimal(str(self.config.directional_max_tilt))
                    if snap.bias == "up":
                        yes_prob = Decimal("0.50") + confidence * max_tilt
                    elif snap.bias == "down":
                        yes_prob = Decimal("0.50") - confidence * max_tilt
                    logger.debug(
                        "    directional bias=%s conf=%.3f → yes_prob=%s (asset=%s)",
                        snap.bias, snap.bias_confidence, yes_prob, c.asset,
                    )
                except Exception:
                    pass
            elif stack_stale and last_update > 0:
                # Stale directional indicators must not create new entries.
                logger.warning(
                    "    %s indicator stack stale (%ds) — skipping directional entries (no edge)",
                    c.asset, int(time.time() - last_update),
                )
                c.best_side = ""
                c.best_edge = Decimal("-1")  # Negative edge ensures rejection
                c.limit_price_cents = 0  # Invalid price prevents downstream processing
                c.model_yes_prob = Decimal("0.50")
                return c
        elif strike <= 0:
            # Non-directional market with no valid strike — set safe defaults so
            # the trace log shows 0.50/-1 sentinel rather than a bare None, and
            # so downstream callers that read model_yes_prob don't hit AttributeErrors.
            c.model_yes_prob = Decimal("0.50")
            c.implied_yes_prob = Decimal("0.50")
            c.best_side = ""
            c.best_edge = Decimal("0")
            return c
        else:
            # Vol-aware logistic model (BUG-EM1 fix)
            dist_pct = float(spot - strike) / float(spot) if float(spot) > 0 else 0.0

            # Get per-asset realized vol from indicator stack
            vol_ann = 0.50
            stack = self._indicator_stacks.get(c.asset)
            if stack is not None:
                try:
                    snap = stack.snapshot()
                    if snap.realized_vol_annualized > 0:
                        vol_ann = snap.realized_vol_annualized
                except Exception:
                    pass

            # Time-to-expiry from close_time (BUG-EM3 fix)
            try:
                _ct = c.close_time
                if _ct and _ct != "?":
                    expiry = datetime.fromisoformat(_ct.replace("Z", "+00:00"))
                    tte_hours = max(0.01, (expiry - datetime.now(timezone.utc)).total_seconds() / 3600)
                else:
                    tte_hours = 1.0
            except Exception:
                tte_hours = 1.0

            hourly_vol = vol_ann / _math.sqrt(365.25 * 24)
            expected_move = hourly_vol * _math.sqrt(tte_hours)

            # BTC-anchored adjustment: blend BTC-beta-implied move into expected_move
            # so alts with high β get wider expected moves when BTC is volatile.
            if getattr(self, "_btc_anchored_model", None) is not None and c.asset and c.asset != "BTC":
                try:
                    _btc_stack = self._indicator_stacks.get("BTC")
                    if _btc_stack is not None:
                        _btc_snap = _btc_stack.snapshot()
                        _btc_atr = _btc_snap.atr if _btc_snap.atr else 0.0
                        _btc_price = _btc_snap.price if _btc_snap.price else 0.0
                        if _btc_price > 0 and _btc_atr > 0:
                            _btc_ret_current = _btc_atr / _btc_price
                            _, _inferred_tf = self._infer_asset_timeframe(
                                getattr(c, "series_ticker", "") or c.ticker or ""
                            )
                            expected_move = self._btc_anchored_model.adjusted_expected_move(
                                asset=c.asset,
                                timeframe=_inferred_tf,
                                base_expected_move=expected_move,
                                btc_return_current=_btc_ret_current,
                            )
                except Exception:
                    pass  # Fall through to base expected_move

            if expected_move > 0.0001:
                z = dist_pct / expected_move
                yes_prob_f = 1.0 / (1.0 + _math.exp(-z))
            else:
                yes_prob_f = 0.50

            yes_prob = Decimal(str(max(0.05, min(0.95, round(yes_prob_f, 6)))))
        c.model_yes_prob = yes_prob

        # Defensive: use getattr for orderbook fields that may be None on unenriched candidates
        best_no_bid = getattr(c, "best_no_bid", None)
        best_yes_ask = getattr(c, "best_yes_ask", None)
        mid_cents = int(getattr(c, "mid_price_cents", 0) or 0)
        mid_frac: Optional[Decimal] = (
            Decimal(str(mid_cents / 100.0)) if mid_cents > 0 else None
        )
        if best_no_bid is not None:
            implied_yes = Decimal("1") - Decimal(str(best_no_bid))
        elif best_yes_ask is not None:
            implied_yes = Decimal(str(best_yes_ask))
        elif mid_frac is not None:
            # NearSpot / enrich path has no orderbook yet — use REST mid so edge
            # matches the live loop (previously defaulted to 0.5 and mis-ranked).
            implied_yes = mid_frac
        else:
            implied_yes = Decimal("0.5")
        c.implied_yes_prob = implied_yes

        # Use actual parabolic fee instead of flat estimate (BUG-RE3 fix)
        _price_cents = max(1, min(99, int(implied_yes * 100)))
        cfg = self.config
        try:
            _actual_fee = Decimal(str(self.bankroll.kalshi_fee_cents(1, _price_cents))) / Decimal("100")
        except Exception:
            _actual_fee = cfg.fee_per_contract

        yes_edge = yes_prob - implied_yes - _actual_fee - cfg.slippage
        no_prob = Decimal("1") - yes_prob
        # Defensive: use getattr for orderbook fields
        best_no_ask = getattr(c, "best_no_ask", None)
        best_yes_bid = getattr(c, "best_yes_bid", None)
        if best_no_ask is not None:
            implied_no = Decimal(str(best_no_ask))
        elif best_yes_bid is not None:
            implied_no = Decimal("1") - Decimal(str(best_yes_bid))
        elif mid_frac is not None:
            implied_no = Decimal("1") - mid_frac
        else:
            implied_no = Decimal("0.5")
        _no_price_cents = max(1, min(99, int(implied_no * 100)))
        try:
            _no_fee = Decimal(str(self.bankroll.kalshi_fee_cents(1, _no_price_cents))) / Decimal("100")
        except Exception:
            _no_fee = cfg.fee_per_contract
        no_edge = no_prob - implied_no - _no_fee - cfg.slippage

        c.yes_edge = yes_edge
        c.no_edge = no_edge

        if yes_edge > no_edge and yes_edge > Decimal("0"):
            c.best_side = "yes"
            c.best_edge = yes_edge
            c.limit_price_cents = max(1, min(99, int(implied_yes * 100)))
        elif no_edge > Decimal("0"):
            c.best_side = "no"
            c.best_edge = no_edge
            c.limit_price_cents = max(1, min(99, int(implied_no * 100)))
        else:
            c.best_side = ""
            c.best_edge = max(yes_edge, no_edge)

        return c

    # ── Core cycle (sync, runs in executor) ──────────────────────────

    def _run_cycle(self) -> None:
        """Run one trading cycle.  This is synchronous and MUST be called
        via ``run_in_executor`` to avoid blocking the event loop.
        Thread-safe: guarded by _cycle_lock (BUG-F1 fix)."""
        with self._cycle_lock:
            self._init_ua_cycle_trace()
            try:
                self._run_cycle_inner()
            except Exception as exc:
                logger.warning(
                    "[UA-TRACE] cycle_inner_failed cycle=%s error=%s",
                    getattr(self, "_cycle", 0),
                    exc,
                    exc_info=True,
                )
                tr = getattr(self, "_ua_cycle_trace", None) or {}
                tr["trace_error"] = str(exc)[:500]
                self._ua_cycle_trace = tr
            finally:
                self._finalize_ua_cycle_trace()

    def _init_ua_cycle_trace(self) -> None:
        self._ua_cycle_trace = {
            "catalog_markets": 0,
            "universe_markets": 0,
            "evaluated": 0,
            "approved": 0,
            "vetoed": 0,
            "orders_submitted": 0,
        }

    def _finalize_ua_cycle_trace(self) -> None:
        """Emit ``[UA-TRACE]`` and push metrics for the Universal Agent dashboard."""
        tr = getattr(self, "_ua_cycle_trace", None) or {}
        try:
            from merid.prediction.ua_ct_metrics import record_ct_cycle

            cycle = int(getattr(self, "_cycle", 0) or 0)
            record_ct_cycle(
                cycle=cycle,
                catalog_markets=int(tr.get("catalog_markets", 0)),
                universe_markets=int(tr.get("universe_markets", 0)),
                evaluated=int(tr.get("evaluated", 0)),
                approved=int(tr.get("approved", 0)),
                vetoed=int(tr.get("vetoed", 0)),
                orders_submitted=int(tr.get("orders_submitted", 0)),
            )
            logger.info(
                "[UA-TRACE] cycle=%d catalog_markets=%d universe_markets=%d evaluated=%d "
                "approved=%d vetoed=%d orders_submitted=%d trace_error=%s",
                cycle,
                tr.get("catalog_markets", 0),
                tr.get("universe_markets", 0),
                tr.get("evaluated", 0),
                tr.get("approved", 0),
                tr.get("vetoed", 0),
                tr.get("orders_submitted", 0),
                (tr.get("trace_error") or "none")[:200],
            )
        except Exception as _ua_exc:
            logger.debug("ua cycle trace finalize skipped: %s", _ua_exc)

    def _run_cycle_inner(self) -> None:
        # Unified execution gate — authoritative state machine for
        # "blocked" vs "reduce-only (limited)" mode. This prevents CT from
        # diverging from KalshiTradingAgent behavior in paper/demo rehearsals.
        allow_new_entries: bool = True
        allow_exits: bool = True
        gate_state: str = "unknown"
        gate_reasons: str = ""
        try:
            from core.execution_gate import check_execution_gate

            _gate = check_execution_gate()
            self._last_execution_gate = _gate.to_dict()
            gate_state = _gate.gate_state
            gate_reasons = "; ".join(r.message for r in (_gate.reasons or []))

            logger.info(
                "  execution_gate: state=%s blocked=%s safe_to_trade=%s reasons=[%s]",
                gate_state,
                _gate.blocked,
                _gate.safe_to_trade,
                gate_reasons,
            )
            if _gate.blocked:
                logger.warning("  BLOCKED by execution_gate: %s", gate_reasons or "unknown")
                return

            # LIMITED = warning-only gate state (``blocked`` stays false). Only BLOCKED
            # stops new entries. Modern crypto profile may also force entries on
            # LIMITED when an integrity overlay cleared safe_to_trade (see
            # ``crypto_pm_live_execution_blocked`` on the order router).
            allow_new_entries = not _gate.blocked
            try:
                from core.execution_gate import GateState
                from merid.prediction.crypto_edge_production import is_modern_crypto_production_profile
                from merid.settings import settings as _sett

                if (
                    _gate.gate_state == GateState.LIMITED.value
                    and is_modern_crypto_production_profile()
                    and bool(getattr(_sett, "MERID_CRYPTO_MODERN_LIMITED_OVERRIDES_SAFE_TO_TRADE", True))
                ):
                    allow_new_entries = True
            except Exception:
                pass
            allow_exits = _gate.allows_reduce()
        except Exception as exc:
            logger.warning(
                "  BLOCKED: execution_gate evaluation failed (%s) — fail-closed",
                exc,
                exc_info=True,
            )
            return

        # Pre-flight: honour global kill switches so CT respects the same
        # safety infrastructure as order_router (risk_controller + KalshiRiskManager).
        try:
            from merid.risk.kill_switches import risk_controller as _rc
        except ImportError:
            logger.debug("  risk_controller unavailable — global kill-switch check skipped")
        else:
            try:
                if not _rc.can_trade():
                    logger.warning("  BLOCKED by global risk_controller: %s", _rc.get_kill_reason())
                    return
            except Exception as exc:
                logger.warning(
                    "  BLOCKED: risk_controller check failed (%s) — fail-closed",
                    exc,
                )
                return

        try:
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        except ImportError:
            logger.debug("  get_kalshi_risk unavailable — KalshiRiskManager kill-switch check skipped")
        else:
            try:
                _krm = get_kalshi_risk()
                if _krm.kill_switch_active:
                    logger.warning(
                        "  BLOCKED by KalshiRiskManager kill switch: %s",
                        _krm.state.kill_switch_reason,
                    )
                    return
            except Exception as exc:
                logger.warning(
                    "  BLOCKED: KalshiRiskManager check failed (%s) — fail-closed",
                    exc,
                )
                return

        self._cycle += 1
        cycle = self._cycle
        try:
            from merid.event_venues.kalshi.market_catalog import get_market_catalog

            self._ua_cycle_trace["catalog_markets"] = len(get_market_catalog().get_all_markets())
        except Exception:
            pass
        self.bankroll.advance_cycle()
        
        # Generate correlation ID for this cycle's trace chain
        correlation_id = generate_correlation_id(
            asset="MULTI",
            timeframe="15m",
            timestamp=datetime.now(timezone.utc),
        )
        
        # [CT-TRACE] discover — Continuous Trader market discovery
        logger.info(
            "[CT-TRACE] stage=discover | corr_id=%s | cycle=%d | assets=%s | formulas=%s | audit_spec=%s",
            correlation_id,
            cycle,
            self._active_assets,
            FORMULAS_VERSION,
            AUDIT_SPEC_VERSION,
        )
        
        # PATCH 3: Spot feed degraded guard — initialize per-cycle flag
        self._spot_feed_degraded_this_cycle = False

        # Warn once per cycle when indicator stacks are missing for any active asset.
        # Directional (15m UP/DOWN) markets are 50/50 without them; threshold markets still trade.
        _missing_stacks = [a for a in self._active_assets if a not in self._indicator_stacks]
        if _missing_stacks:
            logger.warning(
                "[INDICATOR-STACKS-MISSING] assets=%s — directional markets will be skipped "
                "(threshold/strike markets unaffected). Check Crypto15mIndicatorStack init.",
                _missing_stacks,
            )

        logger.info("═══ Continuous Trader Cycle %d ═══ (assets=%s)", cycle, self._active_assets)
        logger.info(
            "  Config: churn=%d cyc/%.0f%% | fee_drag=%.0f%% window=%d | "
            "eff_orders=%d eff_exposure=%.0f%% | vol=%s %.0f%%%s",
            self.config.churn_cooldown_cycles,
            self.config.churn_edge_improvement * 100,
            self.bankroll.get_fee_drag_pct() * 100,
            self.bankroll._fee_history.maxlen,
            self.bankroll.effective_max_orders_per_cycle(),
            self.bankroll.effective_max_exposure_pct() * 100,
            self.bankroll.vol_band,
            self.bankroll.annualized_vol * 100,
            " [TIGHT]" if self.bankroll.fee_drag_tightening else "",
        )

        # 1. Batch-fetch spot prices for ALL configured assets (BUG-SP1 fix)
        spot_prices = self._get_all_spots()
        if not spot_prices:
            logger.warning("  No spot prices available for any asset — skipping cycle")
            return
        logger.info("  Spot prices: %s", {a: f"${p:,.2f}" for a, p in spot_prices.items()})
        _vol_proxy, _vol_bm_asset = self._vol_benchmark_spot_and_asset(spot_prices, self._active_assets)
        if _vol_proxy is not None and _vol_bm_asset is not None:
            self.bankroll.record_spot(_vol_proxy)
            logger.info(
                "  Vol benchmark: asset=%s spot=%.2f (governing bankroll vol track)",
                _vol_bm_asset,
                _vol_proxy,
            )
        # Update per-asset indicator stacks and track freshness
        for asset, spot in spot_prices.items():
            stack = self._indicator_stacks.get(asset)
            if stack is not None:
                stack.update(spot)
                self._indicator_last_updated[asset] = time.time()

        # Bankroll vol from `_vol_benchmark_spot` is one print per cycle — often ~0%
        # until many cycles. Vol-benchmark stack already aggregates 5+ intrastack bars; mirror
        # its annualized vol so status_snapshot / fee band match traded sizing reality.
        try:
            _bs = self._indicator_stacks.get(_vol_bm_asset or _CT_ASSET_KEY_FALLBACK)
            if _bs is not None:
                _snap = _bs.snapshot()
                _rv = float(getattr(_snap, "realized_vol_annualized", 0.0) or 0.0)
                if _rv > 0:
                    self.bankroll.apply_external_annualized_vol(_rv)
        except Exception:
            pass

        # Feed spot prices to BTC-anchored model (auto-derives returns on 2nd+ call).
        # Include daily so alt agents on daily timeframe get proper beta estimates.
        if self._btc_anchored_model is not None:
            try:
                for tf in ("15m", "1h", "daily"):
                    self._btc_anchored_model.record_prices(spot_prices, timeframe=tf)
            except Exception as _bam_exc:
                logger.debug("BtcAnchoredMoveModel price feed failed: %s", _bam_exc)

        # 2. Account state + bankroll management
        balance_cents, portfolio_cents = self._get_balance()
        total_value_cents = balance_cents + portfolio_cents
        logger.info(
            "  Balance: $%.2f | Portfolio: $%.2f | Total: $%.2f",
            balance_cents / 100, portfolio_cents / 100, total_value_cents / 100,
        )

        # Recalibrate risk limits when balance moves >5% (best-effort)
        try:
            from merid.event_venues.kalshi.balance_calibrator import get_balance_calibrator
            get_balance_calibrator().update(balance_cents)
        except Exception as _cal_exc:
            logger.debug("BalanceCalibrator update skipped: %s", _cal_exc)

        # Update peak for drawdown tracking (compounding uses total value)
        self.bankroll.update_peak(total_value_cents)
        self.bankroll.record_cycle_snapshot(total_value_cents)

        # ── Cycle drawdown update ─────────────────────────────────────────
        # Update 15-minute cycle drawdown state with current equity
        try:
            from merid.event_venues.kalshi.cycle_drawdown import get_cycle_drawdown_manager
            cdm = get_cycle_drawdown_manager()
            cdm.update_cycle_state(total_value_cents / 100.0)  # Convert cents to USD
            
            # Log cycle status for observability
            cycle_metrics = cdm.get_cycle_metrics()
            if cycle_metrics.get("cycle_id") != getattr(self, "_last_logged_cycle_id", None):
                self._last_logged_cycle_id = cycle_metrics.get("cycle_id")
                logger.info(
                    "[CYCLE-DRAWDOWN] id=%d status=%s dd=%.2f%% risk_mult=%.3f",
                    cycle_metrics.get("cycle_id", 0),
                    cycle_metrics.get("status"),
                    cycle_metrics.get("cycle_drawdown_pct", 0),
                    cycle_metrics.get("risk_multiplier", 1.0),
                )
        except Exception as exc:
            logger.debug("Cycle drawdown update failed (non-critical): %s", exc)

        # Drawdown check — HALT if we've lost too much from peak
        if self.bankroll.is_halted:
            logger.warning("  HALTED: %s", self.bankroll.halt_reason)
            if self._notifier:
                self._notifier.notify_halt(self.bankroll.halt_reason, self._cycle)
            return
        if not self.bankroll.check_drawdown(total_value_cents):
            if self._notifier and self.bankroll.is_halted:
                self._notifier.notify_halt(self.bankroll.halt_reason, self._cycle)
            return

        if balance_cents < self.config.min_balance_cents:
            # balance_cents=0 almost always means the API call failed (see BALANCE-FETCH-FAIL above);
            # a genuinely $0 balance would be unusual.  Logged at WARNING (retried next cycle).
            logger.warning(
                "  [BALANCE-GATE] Balance $%.2f below $%.2f reserve — skipping cycle "
                "(if this repeats, check API connectivity / auth)",
                balance_cents / 100, self.config.min_balance_cents / 100,
            )
            return

        # 3. Existing positions - filter by asset series prefixes
        _raw_positions = self._get_positions()
        asset_positions = {k: v for k, v in _raw_positions.items()
                         if any(prefix in k.upper() for prefix in self._asset_prefixes)}
        total_open = sum(1 for v in asset_positions.values() if v["qty"] != 0)
        # Aggregate exposure: qty × entry (avg_price from REST); unknown entry → 100¢/contract (conservative)
        _current_exposure_cents = self._aggregate_position_exposure_cents(asset_positions)

        # BUG-35 fix: derive portfolio_cents from real Kalshi total_cost fields.
        # /portfolio/balance does not return a portfolio_value field — sum
        # total_cost_cents across all (not just crypto) positions to get the
        # true open-position cost basis, then recompute total_value_cents.
        _all_pos_total_cost = sum(
            v.get("total_cost_cents", 0) for v in _raw_positions.values()
        )
        if _all_pos_total_cost > 0:
            portfolio_cents = _all_pos_total_cost
            total_value_cents = balance_cents + portfolio_cents
            # Rerun peak update with corrected total now that we know portfolio value
            self.bankroll.update_peak(total_value_cents)
            logger.info(
                "  Balance: $%.2f | Portfolio(cost): $%.2f | Total: $%.2f",
                balance_cents / 100, portfolio_cents / 100, total_value_cents / 100,
            )
        # Cache for status_snapshot (avoids re-fetching positions on every poll)
        self._last_portfolio_cents = portfolio_cents

        if asset_positions:
            _pos_summary = {k: f"{v['qty']}×{v['side']}" for k, v in asset_positions.items() if v["qty"] != 0}
            logger.info("  Existing crypto positions: %s (total=%d, est_notional=%d¢)",
                        _pos_summary, total_open, _current_exposure_cents)

        _live_ok, _live_reason = self._live_api_orders_allowed()

        # 3b. Exit evaluation: profit-take / stop-loss on YES longs; optional auto-exit via REST sell.
        # Enable with KALSHI_CT_AUTO_EXIT=true (default off — avoids surprise sells).
        for ticker, pos_info in list(asset_positions.items()):
            if pos_info["qty"] == 0:
                continue
            try:
                ob = self._fetch_orderbook(ticker)
                if ob is None:
                    continue
                fp = ob.get("orderbook_fp", ob)
                yes_levels = fp.get("yes_dollars", [])
                if not yes_levels:
                    continue
                current_bid = float(yes_levels[0][0]) if yes_levels else 0
                exit_reason = None
                _profit_take_frac = self.config.yes_profit_take_cents / 100.0
                _stop_loss_frac = self.config.yes_stop_loss_cents / 100.0
                if pos_info["side"] == "yes" and current_bid >= _profit_take_frac:
                    exit_reason = "profit-take"
                    logger.info(
                        "  EXIT SIGNAL: %s YES position bid=%d¢ — profit-taking zone (threshold=%d¢)",
                        ticker, int(current_bid * 100), self.config.yes_profit_take_cents,
                    )
                elif pos_info["side"] == "yes" and current_bid <= _stop_loss_frac and current_bid > 0:
                    exit_reason = "stop-loss"
                    logger.info(
                        "  EXIT SIGNAL: %s YES position bid=%d¢ — stop-loss zone",
                        ticker, int(current_bid * 100),
                    )
                if exit_reason and self._auto_exit_enabled():
                    qty = abs(int(pos_info["qty"]))
                    limit_cents = max(1, min(99, int(round(current_bid * 100))))
                    _live_ok_effective = _live_ok and allow_exits
                    _live_reason_effective = _live_reason
                    if not allow_exits:
                        _live_reason_effective = f"execution_gate_reduce_only_blocked:{gate_state}"
                    # [CT-TRACE] execute — Order submission (exit)
                    logger.info(
                        "[CT-TRACE] stage=execute | corr_id=%s | cycle=%d | market=%s | asset=%s | side=%s | size=%d | price=%d¢ | formulas=%s | audit_spec=%s",
                        correlation_id,
                        cycle,
                        ticker,
                        ticker.split("-")[0],
                        pos_info["side"],
                        qty,
                        limit_cents,
                        FORMULAS_VERSION,
                        AUDIT_SPEC_VERSION,
                    )
                    
                    if self._submit_sell_yes_limit(
                        ticker,
                        qty,
                        limit_cents,
                        dry_run=self.config.dry_run,
                        live_ok=_live_ok_effective,
                        live_block_reason=_live_reason_effective,
                    ):
                        # Mark exit pending rather than zeroing — a 201 means the sell
                        # was ACCEPTED, not filled.  Zeroing here risks opening a new
                        # position on the same ticker next cycle before Kalshi confirms
                        # the fill.  _get_positions() will correct qty on the next REST
                        # fetch.  Tag qty as negative to suppress further exit signals
                        # without discarding the position entirely.
                        pos_info["qty"] = -qty  # sentinel: exit submitted but not confirmed
                        # [CT-TRACE] execute — Exit order placed successfully
                        logger.info(
                            "[CT-TRACE] stage=execute | corr_id=%s | cycle=%d | market=%s | side=%s | size=%d | price=%d¢ | status=exit_%s | formulas=%s | audit_spec=%s",
                            correlation_id,
                            cycle,
                            ticker,
                            pos_info["side"],
                            qty,
                            limit_cents,
                            exit_reason,
                            FORMULAS_VERSION,
                            AUDIT_SPEC_VERSION,
                        )
                        # Record close in AgentPerformanceTracker so wins/losses are tracked.
                        # Uses limit_cents as approximate exit price (FillsPoller confirms later).
                        try:
                            from decimal import Decimal as _Dec
                            from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
                            _apt_close = get_agent_performance_tracker()
                            _entry_cents = int(pos_info.get("avg_price_cents", 50))
                            _side = pos_info.get("side", "yes")
                            if _side == "yes":
                                _pnl_cents = (limit_cents - _entry_cents) * qty
                            else:
                                _pnl_cents = (_entry_cents - limit_cents) * qty
                            _pnl_usd = _Dec(str(round(_pnl_cents / 100.0, 4)))
                            _apt_agent_id = f"kalshi_ct_{self.asset_symbol.lower()}"
                            _apt_close.record_close(
                                agent_id=_apt_agent_id,
                                market_id=ticker,
                                exit_price_cents=limit_cents,
                                profit_usd=_pnl_usd,
                            )
                            logger.info(
                                "APT record_close: %s %s exit=%d¢ pnl=$%.2f reason=%s",
                                _apt_agent_id, ticker, limit_cents, float(_pnl_usd), exit_reason,
                            )
                        except Exception as _apt_exc:
                            logger.debug("APT record_close skipped for %s: %s", ticker, _apt_exc)
            except Exception as _exit_exc:
                logger.warning(
                    "Exit evaluation failed for %s — stop-loss/profit-take may not have fired: %s",
                    ticker, _exit_exc, exc_info=True,
                )

        _current_exposure_cents = self._aggregate_position_exposure_cents(asset_positions)
        total_open = sum(1 for v in asset_positions.values() if v["qty"] != 0)
        _per_asset_exp: Dict[str, int] = self._per_asset_exposure_cents(asset_positions)

        # 4. Multi-asset discovery + filtering: each asset uses its OWN spot price
        raw_by_asset: Dict[str, List[dict]] = {}
        fp_result = None  # Initialize for coverage summary
        candidates = []  # Initialize for coverage summary
        for asset, series_list in self._asset_series_map.items():
            # Fetch markets for this asset's series (BUG-SM4 fix: validate series match)
            asset_markets: List[dict] = []
            for series in series_list:
                fetched = self._fetch_markets(series)
                validated = [
                    m for m in fetched
                    if m.get("series_ticker", "").upper() == series.upper() or not m.get("series_ticker")
                ]
                if len(validated) < len(fetched):
                    logger.debug(
                        "  Series %s: filtered %d/%d non-matching markets",
                        series, len(fetched) - len(validated), len(fetched),
                    )
                for m in validated:
                    if not m.get("series_ticker"):
                        m["series_ticker"] = series
                asset_markets.extend(validated)
            raw_by_asset[asset] = asset_markets

        _n_assets = max(1, len(self._asset_series_map))
        fp_cfg = FilterPipelineConfig(
            assets=list(self._asset_series_map.keys()),
            max_candidates_per_asset=max(1, self.config.max_markets_to_scan),
            # Global cap = per-asset limit × number of active assets so every
            # asset gets a fair share — prevents BTC crowding out SOL/XRP/DOGE.
            max_candidates_global=max(1, self.config.max_markets_to_scan) * _n_assets,
            # Distance filter DISABLED (moved to NearSpotSelector)
            default_max_strike_distance_pct=1.0,  # 100% = no-op
            asset_timeframe_max_strike_distance_pct={},  # Empty = no overrides
        )
        fp = FilterPipeline(fp_cfg)
        # FIX 3: Use canonical spot source with set_spot_prices (float -> Decimal internally)
        fp.set_spot_prices(spot_prices)
        fp_result = fp.filter_markets(raw_by_asset)

        # FIX 1: Now returns rich MarketCandidate directly - no manual conversion needed
        # NOTE: Do NOT re-slice by max_markets_to_scan here — FilterPipeline already enforces
        # per-asset and global caps so every asset gets fair representation.  Slicing here
        # undoes the Phase 19b multi-asset starvation fix (max_candidates_global = per × n_assets).
        # NearSpotSelector's max_per_bucket controls final candidate counts downstream.
        candidates = fp_result.final_candidates

        # FIX 4: NearSpotSelector + Overlap grouping on final selection
        from merid.event_venues.kalshi.market_filter import NearSpotSelector, MarketFilter, Direction
        
        selector = NearSpotSelector(spot_source=spot_prices.get)
        
        # Define edge compute function for selector
        def _compute_edge_for_selector(c: MarketCandidate, spot: float, strike: float) -> Decimal:
            # Create a temporary enriched candidate with required fields.
            # Use c.is_directional (set by FilterPipeline) rather than strike==0:
            # the selector passes strike=0.0 for ALL candidates before enrichment,
            # so strike==0 would misclassify every strike-based market as directional.
            from dataclasses import replace
            c_enriched = replace(
                c,
                spot=spot,
                strike=strike,
                is_directional=c.is_directional,
            )
            c_computed = self._compute_edge(c_enriched)
            return Decimal(str(c_computed.best_edge)) if c_computed.best_edge else Decimal("0")
        
        # Apply near-spot selection with per-asset distance bands, price bands,
        # and tiered edge/max-price thresholds.
        # max_distance_pct=0.25 is the outer fence; per_asset_max_distance_pct
        # provides the actual per-(asset,tf) limits from _STRIKE_BAND_PCT.
        # When BTC ATR is elevated the anchor model may widen alt bands dynamically.
        _runtime_bands = dict(self._STRIKE_BAND_PCT)  # mutable copy
        if self._btc_anchored_model is not None:
            try:
                _btc_spot = spot_prices.get(_CT_ASSET_KEY_FALLBACK, 0.0)
                _btc_stack = self._indicator_stacks.get(_CT_ASSET_KEY_FALLBACK)
                if _btc_spot > 0 and _btc_stack is not None:
                    _btc_snap = _btc_stack.snapshot()
                    _btc_atr = float(getattr(_btc_snap, "atr", 0.0) or 0.0)
                    if _btc_atr > 0:
                        _btc_atr_pct = _btc_atr / _btc_spot
                        for _alt in ("ETH", "SOL", "XRP", "DOGE"):
                            for _tf in ("15m", "1h", "daily"):
                                _base = _runtime_bands.get((_alt, _tf), 0.10)
                                _suggested = self._btc_anchored_model.suggested_strike_distance_pct(
                                    asset=_alt, timeframe=_tf,
                                    btc_atr_pct=_btc_atr_pct,
                                    base_distance_pct=_base,
                                )
                                _runtime_bands[(_alt, _tf)] = _suggested
            except Exception as _band_exc:
                logger.debug("BTC anchor band adjustment failed (using static): %s", _band_exc)

        near_spot_candidates = selector.select_near_spot(
            candidates,
            compute_edge=_compute_edge_for_selector,
            max_per_bucket=2,
            max_distance_pct=0.25,          # outer fence — per-asset dict takes precedence
            per_asset_max_distance_pct=_runtime_bands,  # BTC-anchor-adjusted bands
            min_edge=self.config.min_edge,  # fallback flat threshold (ignored when tiered)
            use_tiered_min_edge=True,       # MIN_EDGE_GRID per asset/tf
            use_tiered_max_price=True,      # MAX_PRICE_GRID upper caps per asset/tf
            # PRICE_BANDS: off by default (disabled after all-market-dropout bug).
            # Set KALSHI_PRICE_BANDS_MODE=enforce to re-enable with safe per-bucket fallback.
            use_price_bands=(os.getenv("KALSHI_PRICE_BANDS_MODE", "off") != "off"),
        )
        
        # Group overlapping markets
        market_filter = MarketFilter()
        overlap_groups = market_filter.group_overlapping(near_spot_candidates)
        logger.info(
            "  Near-spot selection: %d candidates, %d overlap groups",
            len(near_spot_candidates), len(overlap_groups),
        )
        
        # Flatten groups back to candidates (or size per-group if desired)
        grouped_candidates: List[MarketCandidate] = []
        for g in overlap_groups:
            grouped_candidates.extend(g.markets)
        
        # Use grouped candidates for trading
        candidates = grouped_candidates if grouped_candidates else near_spot_candidates
        self._ua_cycle_trace["universe_markets"] = len(candidates)

        if not candidates:
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            try:
                catalog = get_market_catalog()
                snapshot = catalog.snapshot()
                logger.info(
                    "  No tradeable markets found across any asset "
                    "(assets_scanned=%s, catalog_assets=%s, filter_stats=%s)",
                    self._active_assets,
                    list(snapshot.by_asset.keys()),
                    {a: st.__dict__ for a, st in fp_result.per_asset.items()},
                )
            except Exception as _diag_err:
                logger.info(
                    "  No tradeable markets found (assets=%s, filter_stats=%s, "
                    "catalog_diag_failed=%s)",
                    self._active_assets,
                    {a: st.__dict__ for a, st in fp_result.per_asset.items()},
                    _diag_err,
                )
            return

        # Per-asset scan logging
        assets_with_candidates = sorted({c.asset for c in candidates if c.asset})
        _skipped_assets_missing_spot = []
        for asset in assets_with_candidates:
            asset_cands = [c for c in candidates if c.asset == asset]
            if asset_cands:
                spot = spot_prices.get(asset)
                if spot is None:
                    _skipped_assets_missing_spot.append(asset)
                    logger.warning(
                        "  Skip logging for %s: spot price unavailable (fetch failed)",
                        asset
                    )
                    continue
                self._log_markets_near_spot(
                    markets_near_spot=asset_cands,
                    asset_symbol=asset,
                    timeframe_label="multi",
                    spot_price=spot,
                    series_ticker=",".join(self._asset_series_map.get(asset, [])),
                    status="open",
                    selector="top_by_distance",
                    pct_band=self.pct_band,
                    dollar_band=self.dollar_band,
                )
        
        # Log summary of assets skipped due to missing spots
        if _skipped_assets_missing_spot:
            logger.warning(
                "[SPOT-SKIP-SUMMARY] cycle=%d assets=%s reason=no_spot_price",
                self._cycle, _skipped_assets_missing_spot
            )

        # 5. Fetch orderbooks and compute edge with diagnostics
        tradeable = []
        ob_stats = {"fetched": 0, "empty": 0, "no_levels": 0, "edge_too_low": 0, "no_side": 0}
        for c in candidates:
            ob = self._fetch_orderbook(c.ticker)
            if ob is None:
                logger.debug("    %s: orderbook fetch failed", c.ticker)
                continue
            ob_stats["fetched"] += 1

            fp = ob.get("orderbook_fp", ob)
            yes_levels = fp.get("yes_dollars", [])
            no_levels = fp.get("no_dollars", [])
            if not yes_levels and not no_levels:
                ob_stats["no_levels"] += 1
                logger.debug("    %s: no orderbook levels", c.ticker)
                continue
            if yes_levels:
                c.best_yes_bid = float(yes_levels[0][0])
            if no_levels:
                c.best_no_bid = float(no_levels[0][0])
            if c.best_no_bid is not None:
                c.best_yes_ask = round(1.0 - c.best_no_bid, 4)
            if c.best_yes_bid is not None:
                c.best_no_ask = round(1.0 - c.best_yes_bid, 4)
            
            # DRY-RUN INSTRUMENTATION: Market microstructure snapshot
            _has_both_sides = bool(c.best_yes_bid and c.best_yes_ask)
            if _has_both_sides:
                _spread = abs(c.best_yes_ask - c.best_yes_bid)
                _spread_pct = _spread / c.best_yes_bid if c.best_yes_bid > 0 else 0
                _book_degenerate = False
            else:
                # One or both sides missing — treat as degenerate, NOT as a tight spread.
                # Downstream logic must not interpret this as a valid two-sided market.
                _spread = 0
                _spread_pct = 0
                _book_degenerate = True
            _crossing_spread = False  # We join, don't cross

            # MICROSTRUCTURE INVARIANT: crossing=true implies spread≤0
            if _crossing_spread and _spread > 0:
                logger.warning(
                    "[MICROSTRUCTURE-INVARIANT-FAIL] crossing=true but spread=%.4f>0 | ticker=%s "
                    "yes_bid=%.4f yes_ask=%.4f — data inconsistent",
                    _spread, c.ticker, c.best_yes_bid or 0, c.best_yes_ask or 0
                )

            logger.info(
                "[DRY-RUN-TRACE] microstructure_snapshot | cycle=%d asset=%s market=%s side=%s | "
                "yes_bid=%.4f yes_ask=%.4f no_bid=%.4f no_ask=%.4f | "
                "spread=%.4f (%.2f%%) crossing=%s degenerate=%s",
                self._cycle, c.asset or "unknown", c.ticker, c.best_side or "none",
                c.best_yes_bid or 0, c.best_yes_ask or 0, c.best_no_bid or 0, c.best_no_ask or 0,
                _spread, _spread_pct * 100, _crossing_spread, _book_degenerate
            )

            if _book_degenerate:
                # One or both sides of the book are missing (bid=0 or ask=0 on yes/no).
                # Any edge computed from such a phantom price is meaningless and can
                # produce extreme Kelly fractions — skip this market entirely.
                logger.debug("[SKIP-DEGENERATE] %s: order book has no two-sided price — skip", c.ticker)
                continue

            # Enrich candidate with live spot and parsed strike so _compute_edge
            # uses the correct logistic model instead of the strike<=0 early-return.
            # NearSpotSelector returns the original MarketCandidate (spot=0, strike=0
            # defaults) — set them here from the live feed before edge computation.
            _enrich_spot = spot_prices.get(c.asset or "", 0.0)
            _enrich_strike = parse_strike_from_ticker(c.ticker)
            if _enrich_strike is not None:
                c.spot = _enrich_spot
                c.strike = _enrich_strike
                c.is_directional = False
            else:
                # Directional market (15m UP/DOWN — no numeric strike in ticker)
                c.spot = _enrich_spot
                c.strike = _enrich_spot  # neutral reference; bias comes from indicator stack
                c.is_directional = True

            self._compute_edge(c)

            # [CT-TRACE] analyze — Edge computation for candidate
            logger.info(
                "[CT-TRACE] stage=analyze | corr_id=%s | cycle=%d | market=%s | asset=%s | edge=%.4f | formulas=%s | audit_spec=%s",
                correlation_id,
                cycle,
                c.ticker,
                c.asset or "unknown",
                float(c.best_edge) if c.best_edge else 0.0,
                FORMULAS_VERSION,
                AUDIT_SPEC_VERSION,
            )
            
            # DRY-RUN INSTRUMENTATION: Signal → Sizing translation
            _edge_f = float(c.best_edge) if c.best_edge else 0.0
            _edge_pct = _edge_f * 100.0  # human-readable; same unit as min_edge (probability points)
            _mp = getattr(c, "model_yes_prob", None)
            if _mp is not None:
                _win_prob = float(_mp)
            else:
                _win_prob = min(0.95, max(0.05, 0.5 + _edge_f))
            _ref_pc = ct_reference_price_cents(c)
            _payout_ratio = (
                (100 - _ref_pc) / max(1, _ref_pc) if _ref_pc > 0 else 0.0
            )
            _q = 1.0 - _win_prob
            _raw_kelly = (_win_prob * _payout_ratio - _q) / _payout_ratio if _payout_ratio > 0 else 0
            _raw_kelly = max(0.0, _raw_kelly)
            _frac_kelly = _raw_kelly * float(self.config.kelly_fraction)
            
            # INPUT VALIDATION: Assert Kelly values are finite (not NaN/inf)
            if not math.isfinite(_raw_kelly) or not math.isfinite(_frac_kelly):
                logger.error(
                    "[INPUT-VALIDATION-FAIL] NaN/Inf in Kelly calc | ticker=%s edge=%s win_prob=%s payout=%s | "
                    "raw_kelly=%s frac_kelly=%s — SKIPPING",
                    c.ticker, _edge_f, _win_prob, _payout_ratio, _raw_kelly, _frac_kelly
                )
                continue
            
            # Resolve current filter params for TRACE log (all four constraint layers)
            # c.timeframe is set by FilterPipeline on every MarketCandidate; use it directly.
            _asset_key_trace = c.asset or _CT_ASSET_KEY_FALLBACK
            _tf_key_trace = c.timeframe or "unknown"
            _spot_band_pct = self._STRIKE_BAND_PCT.get(
                (_asset_key_trace, _tf_key_trace),
                self.config.max_strike_distance_pct,
            )
            _pb_min, _pb_max = get_price_band(_asset_key_trace, c.ticker)
            _max_ctr_trace = self.MAX_CONTRACTS_PER_MARKET.get(
                _asset_key_trace, self.config.max_position_per_market
            )
            _max_spend_trace = self.MAX_SPEND_PER_CONTRACT.get(_asset_key_trace, 0.0)
            _bankroll_usd_trace = balance_cents / 100.0
            _asset_max_pct_trace = self.config.asset_max_exposure_pct.get(
                _asset_key_trace, self.config.asset_exposure_default_pct
            )
            _global_max_pct_trace = self.config.global_max_exposure_pct

            logger.info(
                "[DRY-RUN-TRACE] signal_to_sizing | cycle=%d asset=%s tf=%s market=%s side=%s | "
                "spot_band_pct=%.0f%% price_band=(%.2f,%.2f) | "
                "edge=%.4f edge_pct=%.2f win_prob=%.4f payout=%.2f | "
                "kelly_raw=%.4f kelly_frac=%.4f (k=%.2f%%) | "
                "bankroll=$%.2f asset_cap=%.0f%% global_cap=%.0f%% | "
                "max_contracts=%d max_spend=$%.2f",
                self._cycle, _asset_key_trace, _tf_key_trace, c.ticker, c.best_side or "none",
                _spot_band_pct * 100, _pb_min, _pb_max,
                _edge_f, _edge_pct, _win_prob, _payout_ratio,
                _raw_kelly, _frac_kelly, float(self.config.kelly_fraction) * 100,
                _bankroll_usd_trace, _asset_max_pct_trace * 100, _global_max_pct_trace * 100,
                _max_ctr_trace, _max_spend_trace,
            )

            # Per-candidate diagnostics: indicator freshness + model vs tiered bar
            _ind_age = None
            _lu = self._indicator_last_updated.get(_asset_key_trace, 0.0)
            if _lu:
                _ind_age = time.time() - _lu
            _tiered_me = float(get_tiered_min_edge(_asset_key_trace, c.ticker))
            _bias_s = ""
            _conf_s = 0.0
            _vol_b = ""
            _stk = self._indicator_stacks.get(_asset_key_trace) if self._indicator_stacks else None
            if _stk is not None:
                try:
                    _sn = _stk.snapshot()
                    _bias_s = getattr(_sn, "bias", "") or ""
                    _conf_s = float(getattr(_sn, "bias_confidence", 0.0) or 0.0)
                    _vol_b = getattr(_sn, "vol_band", "") or ""
                except Exception:
                    pass
            _best_edge_f = float(c.best_edge) if c.best_edge is not None else 0.0
            _best_edge_pct = _best_edge_f * 100.0
            logger.info(
                "[CT-TRACE] market=%s asset=%s tf=%s | ind_age_s=%s bias=%s conf=%.3f vol_band=%s | "
                "model_yes=%.4f implied_yes=%.4f best_edge=%.4f edge_pct=%.2f yes_edge=%s no_edge=%s | "
                "tiered_min_edge=%.4f ref_price_cents=%d veto=%s",
                c.ticker,
                _asset_key_trace,
                _tf_key_trace,
                f"{_ind_age:.1f}" if _ind_age is not None else "none",
                _bias_s or "n/a",
                _conf_s,
                _vol_b or "n/a",
                float(c.model_yes_prob) if c.model_yes_prob is not None else -1.0,
                float(c.implied_yes_prob) if c.implied_yes_prob is not None else -1.0,
                _best_edge_f,
                _best_edge_pct,
                str(c.yes_edge) if c.yes_edge is not None else "n/a",
                str(c.no_edge) if c.no_edge is not None else "n/a",
                _tiered_me,
                _ref_pc,
                "stale_stack" if (_ind_age is not None and _ind_age > 180) else "none",
            )

            # Check edge vs minimum threshold (tiered grid ∪ fee-band bankroll floor)
            min_edge_required = max(
                Decimal(str(_tiered_me)),
                self.bankroll.min_edge_for_price(_ref_pc),
            )
            if c.best_edge < min_edge_required:
                try:
                    from merid.prediction.crypto_edge_production import maybe_log_shadow_edge_near_miss

                    maybe_log_shadow_edge_near_miss(
                        ticker=c.ticker,
                        asset=_asset_key_trace,
                        best_edge=float(c.best_edge) if c.best_edge is not None else 0.0,
                        min_required=float(min_edge_required),
                        side=str(c.best_side or "yes"),
                    )
                except Exception:
                    pass
                ob_stats["edge_too_low"] += 1
                logger.debug(
                    "    %s: edge %.4f < min %.4f (price=%d¢)",
                    c.ticker, c.best_edge, min_edge_required, c.limit_price_cents,
                )
                continue
            if not c.best_side:
                ob_stats["no_side"] += 1
                continue

            tradeable.append(c)
            # Rate limit between orderbook fetches - use non-blocking approach
            # Since we're in executor thread, we can't asyncio.sleep directly
            # The 100ms delay is accumulated and the executor handles it
            time.sleep(0.05)  # Reduced from 100ms to 50ms to cut cumulative delay

        _ob_fetched = int(ob_stats["fetched"])
        _tradeable_n = len(tradeable)
        self._ua_cycle_trace["evaluated"] = _ob_fetched
        self._ua_cycle_trace["approved"] = _tradeable_n
        self._ua_cycle_trace["vetoed"] = max(0, _ob_fetched - _tradeable_n)

        if not tradeable:
            logger.info(
                "  No markets with sufficient edge (candidates=%d, orderbooks_fetched=%d, "
                "no_levels=%d, edge_too_low=%d, no_side=%d)",
                len(candidates), ob_stats["fetched"], ob_stats["no_levels"],
                ob_stats["edge_too_low"], ob_stats["no_side"],
            )
            return

        tradeable.sort(key=lambda c: c.best_edge, reverse=True)
        logger.info("  %d tradeable market(s)", len(tradeable))

        # [BUG-007] Swarm consensus integration — query TaCo consensus for each
        # tradeable candidate and apply a consensus-weighted score adjustment.
        # Markets vetoed by consensus (score < threshold) are dropped entirely.
        _CONSENSUS_VETO_THRESHOLD = float(os.getenv("KALSHI_CT_CONSENSUS_VETO", "0.0"))
        _CONSENSUS_WEIGHT = float(os.getenv("KALSHI_CT_CONSENSUS_WEIGHT", "0.20"))
        _consensus_applied = False
        try:
            from consensus.consensus_coordinator import EnhancedConsensusCoordinator
            from schemas.swarm_events import OpinionDirection as _OpDir
            _coordinator = EnhancedConsensusCoordinator.get_instance()
            _post_consensus: list = []
            for _tc in tradeable:
                _asset_key = (_tc.asset or _CT_ASSET_KEY_FALLBACK).upper()
                _ticker_key = _tc.ticker
                _opinions = _coordinator.get_pending_opinions_for_symbol(_asset_key)
                if not _opinions:
                    # No consensus opinions — fall through (edge-only ranking)
                    _post_consensus.append(_tc)
                    continue
                # Aggregate: convert direction+confidence → YES-side probability signal.
                # LONG/UP/BULLISH → p > 0.5; SHORT/DOWN/BEARISH → p < 0.5; FLAT → 0.5
                # Use confidence as the weight (0.0–1.0, default 1.0 if zero).
                _sum_w = 0.0
                _sum_wp = 0.0
                for _op in _opinions:
                    _dir = getattr(_op, "direction", _OpDir.FLAT)
                    _conf = float(getattr(_op, "confidence", 0.5) or 0.5)
                    _op_w = max(_conf, 0.1)  # never zero weight
                    # Map direction to an implied YES probability
                    _dir_val = (_dir.value if hasattr(_dir, "value") else str(_dir)).lower()
                    if _dir_val == "long":
                        _op_p = 0.5 + 0.5 * _conf  # scales 0.5 → 1.0 with confidence
                    elif _dir_val == "short":
                        _op_p = 0.5 - 0.5 * _conf  # scales 0.5 → 0.0 with confidence
                    else:
                        _op_p = 0.5  # FLAT
                    _sum_w += _op_w
                    _sum_wp += _op_w * _op_p
                _consensus_p = _sum_wp / _sum_w if _sum_w > 0 else 0.5
                # Compute consensus-adjusted edge: blend edge with consensus signal
                _raw_edge = float(_tc.best_edge) if _tc.best_edge else 0.0
                # Side-aware: YES consensus boosts YES-side edge, penalises NO-side
                if _tc.best_side == "yes":
                    _side_signal = _consensus_p - 0.5  # positive = consensus agrees
                else:
                    _side_signal = 0.5 - _consensus_p  # positive = consensus agrees with NO
                _adj_edge = _raw_edge + _CONSENSUS_WEIGHT * _side_signal
                if _adj_edge < _CONSENSUS_VETO_THRESHOLD:
                    logger.info(
                        "  [CONSENSUS-VETO] %s: adj_edge=%.4f < threshold=%.4f "
                        "(raw=%.4f consensus_p=%.3f side=%s opinions=%d)",
                        _ticker_key, _adj_edge, _CONSENSUS_VETO_THRESHOLD,
                        _raw_edge, _consensus_p, _tc.best_side, len(_opinions),
                    )
                    try:
                        from merid.metrics.cell_metrics import record_veto as _rcm_veto
                        _tc_tf = _tc.timeframe if hasattr(_tc, "timeframe") and _tc.timeframe else "15m"
                        _rcm_veto(_tc.asset or "unknown", _tc_tf, "consensus_veto")
                    except Exception:
                        pass
                    continue
                # Persist adjusted edge back onto candidate for downstream sizing.
                # Clamp to 0 so a consensus-penalised edge cannot go negative and
                # slip past the min_edge check as a near-zero positive.
                _tc.best_edge = max(0.0, _adj_edge)  # type: ignore[assignment]
                _post_consensus.append(_tc)
                logger.debug(
                    "  [CONSENSUS-PASS] %s: adj_edge=%.4f (raw=%.4f, consensus_p=%.3f)",
                    _ticker_key, _adj_edge, _raw_edge, _consensus_p,
                )
            tradeable = _post_consensus
            _consensus_applied = True
        except Exception as _cons_exc:
            logger.debug("[BUG-007] Consensus integration skipped (non-fatal): %s", _cons_exc)

        # Re-sort after consensus adjustments
        tradeable.sort(key=lambda c: c.best_edge, reverse=True)

        # [CT-TRACE] consensus
        if tradeable:
            logger.info(
                "[CT-TRACE] stage=consensus | corr_id=%s | cycle=%d | top_market=%s | top_edge=%.4f | candidates=%d | method=%s | formulas=%s | audit_spec=%s",
                correlation_id,
                cycle,
                tradeable[0].ticker if tradeable else "none",
                float(tradeable[0].best_edge) if tradeable and tradeable[0].best_edge else 0.0,
                len(tradeable),
                "swarm_consensus" if _consensus_applied else "edge_ranking",
                FORMULAS_VERSION,
                AUDIT_SPEC_VERSION,
            )

        # 6. Place orders — BankrollManager controls sizing
        if not allow_new_entries:
            # HARD BLOCKED only (not LIMITED). Misleading historical log text removed.
            logger.warning(
                "  Execution gate blocked: skipping new entries (gate_state=%s)",
                gate_state,
            )
            tradeable = []

        # PATCH 3: Spot feed degraded guard — block new entries if spot data is junk
        if self._spot_feed_degraded_this_cycle:
            logger.warning("  SPOT-FEED-DEGRADED: blocking new entries — trading on stale/missing data")
            tradeable = []

        orders_placed = 0
        # BUG-F3 fix: per-cycle spend cap — configurable via KALSHI_TRADER_CYCLE_SPEND_PCT
        _max_cycle_spend = int(balance_cents * self.config.max_cycle_spend_pct)
        _cycle_spent = 0
        # CROSS-TIMEFRAME DUPLICATE GUARD: track which assets have already received
        # an order this cycle. This prevents placing both a 1h and a 15m order on the
        # same underlying in a single cycle — the cap wouldn't catch this because each
        # individual order is small relative to the per-asset exposure cap.
        _assets_ordered_this_cycle: set = set()
        # LEAK-009: per-cycle in-flight dedup set — prevents placing two orders for
        # the exact same (ticker, side) within one cycle (e.g. if the same market
        # appears in multiple overlap groups or candidate lists after filtering).
        _inflight_this_cycle: set = set()
        for c in tradeable:
            if self._shutdown or orders_placed >= self.bankroll.effective_max_orders_per_cycle():
                break

            # Stale indicator stacks must not create new entries.
            asset_key = c.asset or (self._active_assets[0] if self._active_assets else "")
            if not asset_key:
                logger.warning("    Skip %s: could not resolve asset for indicator check", c.ticker)
                continue
            last_update = self._indicator_last_updated.get(asset_key, 0.0)
            indicators_stale = (last_update <= 0.0) or ((time.time() - last_update) > 180.0)
            if indicators_stale:
                # Directional markets (15m UP/DOWN) require fresh indicator bias — skip them.
                # Threshold/strike markets use a logistic vol model and do NOT require indicator
                # data for a valid edge signal; only skip those if indicators are stale.
                if c.is_directional:
                    logger.warning(
                        "    Skip %s: directional market — indicator stack stale for %s (age=%.0fs)",
                        c.ticker,
                        asset_key,
                        max(0.0, time.time() - last_update),
                    )
                    continue
                # Threshold market: indicators improve the vol estimate but are not required.
                # Log at DEBUG so ops can see it without it being alarming.
                logger.debug(
                    "    %s: indicator stack stale for %s (age=%.0fs) — using default vol for logistic model",
                    c.ticker,
                    asset_key,
                    max(0.0, time.time() - last_update),
                )

            # Anti-churn: block direction flips within cooldown window
            if not self.bankroll.check_churn(c.ticker, c.best_side, float(c.best_edge)):
                continue

            # Infer asset/timeframe early (needed for debug assertions and exposure checks)
            _series_key = c.ticker.split("-")[0] if "-" in c.ticker else c.ticker
            _candidate_asset, _candidate_tf = self._infer_asset_timeframe(_series_key)
            self._warn_if_unk_asset_for_exposure(c.ticker, _series_key, _candidate_asset)
            
            # DRY-RUN INSTRUMENTATION: Asset/Timeframe Inference
            logger.info(
                "[DRY-RUN-TRACE] asset_inference | cycle=%d asset=%s market=%s side=%s | "
                "ticker=%s series_key=%s -> asset=%s timeframe=%s prefix_map=%s",
                self._cycle, _candidate_asset, c.ticker, c.best_side or "none",
                c.ticker, _series_key, _candidate_asset, _candidate_tf,
                self._asset_series_map.get(_candidate_asset, [])
            )

            # Sanity assertions (dev-only) to catch wiring regressions early
            _debug_asserts = os.getenv("KALSHI_CT_DEBUG_ASSERTS", "false").lower() in ("true", "1", "yes")
            if _debug_asserts:
                # Calculate distance for assertion
                _assert_spot = spot_prices.get(_candidate_asset, 0.0)
                _assert_strike = float(c.strike) if hasattr(c, 'strike') and c.strike else 0.0
                _assert_distance_abs = abs(_assert_strike - _assert_spot) if _assert_strike > 0 else 0.0
                _assert_distance_pct = _assert_distance_abs / _assert_spot if _assert_spot > 0 else 0.0
                
                # Per-asset max distance (use config or fallback)
                _assert_max_dist_pct = self._STRIKE_BAND_PCT.get(
                    (_candidate_asset, _candidate_tf), 
                    self.config.max_strike_distance_pct
                )
                
                # Assert: edge must be >= min_edge (with small epsilon for float comparison)
                _min_edge_float = float(self.config.min_edge)
                if c.best_edge < _min_edge_float - 0.0001:  # epsilon = 0.01%
                    logger.error(
                        "ASSERT FAIL: edge %.4f < min_edge %.4f for %s (wiring regression)",
                        c.best_edge, _min_edge_float, c.ticker
                    )
                    assert False, f"Unexpected low-edge candidate slipped through: {c.ticker}"
                
                # Assert: distance must be within allowed band
                if _assert_distance_pct > _assert_max_dist_pct + 0.001:  # epsilon = 0.1%
                    logger.error(
                        "ASSERT FAIL: distance %.2f%% > max %.2f%% for %s (wiring regression)",
                        _assert_distance_pct * 100, _assert_max_dist_pct * 100, c.ticker
                    )
                    assert False, f"Far OTM candidate slipped through: {c.ticker}"

            _pos_info = asset_positions.get(
                c.ticker, {"qty": 0, "side": "", "avg_price_cents": 0},
            )
            existing = _pos_info["qty"]

            # BankrollManager decides how many contracts (or 0 = skip)
            order_count = self.bankroll.calculate_order_size(
                balance_cents=balance_cents,
                edge=c.best_edge,
                contract_price_cents=c.limit_price_cents,
                existing_position=existing,
                total_open_positions=total_open,
            )

            if order_count <= 0:
                logger.debug(
                    "    Skip %s: bankroll says 0 (price=%d¢, edge=%.4f, pos=%d, open=%d)",
                    c.ticker, c.limit_price_cents, c.best_edge, existing, total_open,
                )
                continue

            # ── Section 2 sizing caps — applied in order, all logged ─────────
            _caps_fired: list = []

            # Cap 1: per-market contract count
            _max_contracts = self.MAX_CONTRACTS_PER_MARKET.get(
                _candidate_asset, self.config.max_position_per_market
            )
            if order_count > _max_contracts:
                _caps_fired.append(f"contracts_per_market({order_count}->{_max_contracts})")
                order_count = _max_contracts

            # Cap 2: per-order notional (USD)
            _max_spend_usd = self.MAX_SPEND_PER_CONTRACT.get(_candidate_asset)
            if _max_spend_usd is not None:
                _max_spend_cents = int(_max_spend_usd * 100)
                _notional_cents_raw = order_count * c.limit_price_cents
                if _notional_cents_raw > _max_spend_cents and c.limit_price_cents > 0:
                    _capped_contracts = max(1, _max_spend_cents // c.limit_price_cents)
                    if _capped_contracts < order_count:
                        _caps_fired.append(
                            f"spend_per_order(${_notional_cents_raw/100:.2f}"
                            f"->${_capped_contracts * c.limit_price_cents/100:.2f})"
                        )
                        order_count = _capped_contracts

            if _caps_fired:
                logger.info(
                    "[SIZE-CAP] %s | %s/%s | kelly_raw→final: caps=%s | contracts=%d price=%d¢",
                    c.ticker, _candidate_asset, _candidate_tf,
                    ",".join(_caps_fired), order_count, c.limit_price_cents,
                )

            # [CT-TRACE] size — Position sizing decision (after all caps)
            logger.info(
                "[CT-TRACE] stage=size | corr_id=%s | cycle=%d | market=%s | asset=%s | edge=%.4f | price=%d¢ | contracts=%d | caps=%s | formulas=%s | audit_spec=%s",
                correlation_id,
                cycle,
                c.ticker,
                c.asset or "unknown",
                float(c.best_edge) if c.best_edge else 0.0,
                c.limit_price_cents,
                order_count,
                ",".join(_caps_fired) if _caps_fired else "none",
                FORMULAS_VERSION,
                AUDIT_SPEC_VERSION,
            )

            if order_count <= 0:
                logger.debug(
                    "    Skip %s: all contracts clipped by sizing caps (price=%d¢)",
                    c.ticker, c.limit_price_cents,
                )
                continue

            # GUARD: Per-asset size cap from guardian (fail-closed: 0.0 if missing)
            # Uses computed caps if enabled, otherwise falls back to static live_size_caps
            if self._guardian:
                # Get effective caps (computed or static)
                effective_caps = self._guardian.get_effective_live_caps(
                    bankroll_cents=balance_cents,
                    btc_vol_annual=getattr(self._guardian.checklist, 'target_vol_annual', 0.65)
                )
                _asset_cap = effective_caps.get(_candidate_asset, 0.0)
                
                if _asset_cap <= 0.0:
                    logger.info(
                        "    Skip %s: asset %s has guardian cap=0 (OBSERVATION or computed cap is zero)",
                        c.ticker, _candidate_asset,
                    )
                    continue
                if _asset_cap < 1.0:
                    _capped = max(1, int(order_count * _asset_cap))
                    if _capped < order_count:
                        logger.info(
                            "[SIZE-CAP-CT] %s | %s cap=%.0f%% | orders: %d -> %d",
                            c.ticker, _candidate_asset, _asset_cap * 100,
                            order_count, _capped,
                        )
                        order_count = _capped

            # CROSS-TIMEFRAME DUPLICATE GUARD: one order per underlying per cycle.
            # Candidates are sorted best-edge-first; the first hit for each asset wins.
            if _candidate_asset in _assets_ordered_this_cycle:
                logger.info(
                    "    Skip %s: asset %s already ordered this cycle (cross-TF dedup)",
                    c.ticker, _candidate_asset,
                )
                continue

            cost_cents = order_count * c.limit_price_cents
            if cost_cents + 1 > balance_cents:
                logger.debug("    Skip %s: can't afford %d¢", c.ticker, cost_cents)
                continue
            # BUG-F3 fix: per-cycle spend cap
            if _cycle_spent + cost_cents > _max_cycle_spend:
                logger.info("    Skip %s: cycle spend cap reached (%d¢ + %d¢ > %d¢)",
                            c.ticker, _cycle_spent, cost_cents, _max_cycle_spend)
                break
            # Stage 1–2 — per-asset cap first, then global (see ``evaluate_entry_exposure_skip``).
            _global_cap_cents = int(balance_cents * self.config.global_max_exposure_pct)
            _asset_max_pct = self.config.asset_max_exposure_pct.get(
                _candidate_asset, self.config.asset_exposure_default_pct
            )
            _series_mult = self.config.series_exposure_multiplier.get(_candidate_tf, 1.0)
            _asset_cap_cents = max(
                self.config.min_asset_cap_cents,
                int(balance_cents * _asset_max_pct * _series_mult),
            )
            _asset_current = _per_asset_exp.get(_candidate_asset, 0)

            logger.info(
                "[DRY-RUN-TRACE] exposure_caps_post_sizing | cycle=%d asset=%s market=%s side=%s | "
                "tf=%s order_count=%d cost=%d¢ | asset_current=%d¢ -> asset_after=%d¢ "
                "(cap=%d¢) | global_current=%d¢ -> global_after=%d¢ (cap=%d¢)",
                self._cycle, _candidate_asset, c.ticker, c.best_side or "none",
                _candidate_tf, order_count, cost_cents,
                _asset_current, _asset_current + cost_cents, _asset_cap_cents,
                _current_exposure_cents, _current_exposure_cents + cost_cents, _global_cap_cents
            )
            
            # DRY-RUN INSTRUMENTATION: Exposure caps BEFORE sizing
            logger.info(
                "[DRY-RUN-TRACE] exposure_caps_pre | cycle=%d asset=%s market=%s side=%s | "
                "tf=%s balance=%d¢ global_cap=%d¢ asset_cap=%d¢ asset_current=%d¢ | "
                "multipliers: asset_pct=%.2f%% series_mult=%.2f",
                self._cycle, _candidate_asset, c.ticker, c.best_side or "none",
                _candidate_tf, balance_cents, _global_cap_cents, _asset_cap_cents, _asset_current,
                _asset_max_pct * 100, _series_mult
            )
            _exp_skip = self.evaluate_entry_exposure_skip(
                balance_cents,
                _current_exposure_cents,
                _per_asset_exp,
                cost_cents,
                _candidate_asset,
                _candidate_tf,
                self.config,
            )
            if _exp_skip == "per_asset":
                # DRY-RUN INSTRUMENTATION: CAP-BIND tracepoint for per-asset cap binding
                logger.info(
                    "[CAP-BIND] cap_type=per_asset cycle=%d asset=%s market=%s side=%s | "
                    "cap_value=%d¢ requested_exposure=%d¢ clipped_exposure=0 | "
                    "asset_current=%d¢ cost=%d¢",
                    self._cycle, _candidate_asset, c.ticker, c.best_side or "none",
                    _asset_cap_cents, cost_cents,
                    _asset_current, cost_cents
                )
                logger.info(
                    "    Skip %s: per-asset cap [%s/%s] reached (%d¢ + %d¢ > %d¢) "
                    "| global: %d¢ + %d¢ vs %d¢ cap",
                    c.ticker,
                    _candidate_asset,
                    _candidate_tf,
                    _asset_current,
                    cost_cents,
                    _asset_cap_cents,
                    _current_exposure_cents,
                    cost_cents,
                    _global_cap_cents,
                )
                continue
            if _exp_skip == "global":
                # DRY-RUN INSTRUMENTATION: CAP-BIND tracepoint for global cap binding
                logger.info(
                    "[CAP-BIND] cap_type=global cycle=%d asset=%s market=%s side=%s | "
                    "cap_value=%d¢ requested_exposure=%d¢ clipped_exposure=0 | "
                    "global_current=%d¢ cost=%d¢",
                    self._cycle, _candidate_asset, c.ticker, c.best_side or "none",
                    _global_cap_cents, cost_cents,
                    _current_exposure_cents, cost_cents
                )
                logger.info(
                    "    Skip %s: global portfolio cap reached (%d¢ + %d¢ > %d¢) "
                    "| per-asset [%s/%s]: %d¢ + %d¢ vs %d¢ cap",
                    c.ticker,
                    _current_exposure_cents,
                    cost_cents,
                    _global_cap_cents,
                    _candidate_asset,
                    _candidate_tf,
                    _asset_current,
                    cost_cents,
                    _asset_cap_cents,
                )
                continue

            # FIX 5: Pre-order logging (sanity harness)
            # Calculate distance and direction for logging
            _spot_for_log = spot_prices.get(_candidate_asset, 0.0)
            _strike_for_log = float(c.strike) if hasattr(c, 'strike') and c.strike else 0.0
            _distance_abs = abs(_strike_for_log - _spot_for_log) if _strike_for_log > 0 else 0.0
            _direction = "directional" if _strike_for_log == 0 else ("above" if _strike_for_log > _spot_for_log else "below")
            _risk_dollars = cost_cents / 100.0
            
            logger.info(
                "  [PRE-ORDER] %s/%s/%s | ticker=%s spot=%.2f strike=%.2f dist=%.2f edge=%.4f "
                "size=%d risk=$%.2f | caps: %s=%.0f/%.0f, global=%.0f/%.0f",
                _candidate_asset,
                _candidate_tf,
                _direction,
                c.ticker,
                _spot_for_log,
                _strike_for_log,
                _distance_abs,
                c.best_edge,
                order_count,
                _risk_dollars,
                _candidate_asset,
                _asset_current / 100,
                _asset_cap_cents / 100,
                _current_exposure_cents / 100,
                _global_cap_cents / 100,
            )

            # DRY-RUN INSTRUMENTATION: Detailed fee computation using canonical kalshi_fee_cents
            expected_fee = self.bankroll.kalshi_fee_cents(order_count, c.limit_price_cents)
            
            # Derive raw fee components for trace logging (from canonical formula: ceil(0.07 * C * P * (1-P)))
            _price_dollars = c.limit_price_cents / 100.0
            _raw_fee_dollars = 0.07 * order_count * _price_dollars * (1.0 - _price_dollars)
            _raw_fee_cents = _raw_fee_dollars * 100
            _rounded_fee = max(1, math.ceil(_raw_fee_cents))
            
            # Fee schedule branch detection (for informational tracing)
            if c.limit_price_cents <= 5:
                _fee_branch = "penny"
            elif c.limit_price_cents <= 39:
                _fee_branch = "sweet_spot"
            elif c.limit_price_cents <= 60:
                _fee_branch = "midcurve"
            else:
                _fee_branch = "standard"
            
            # Fee sanity: % of notional and anomaly detection
            _notional_cents = order_count * c.limit_price_cents
            _fee_pct_of_notional = (expected_fee / _notional_cents * 100) if _notional_cents > 0 else 0
            
            # NOTIONAL-AWARE FEE ANOMALY: Small contracts naturally have higher fee %.
            # Kalshi fee = ceil(0.07 * C * P * (1-P)), min 1¢. For small notionals, this
            # yields higher % (e.g., 2¢ on 16¢ = 12.5%). Scale bounds by notional tier.
            if _notional_cents < 25:
                _max_fee_pct = 15.0  # 15% for small (<25¢) contracts
            elif _notional_cents < 50:
                _max_fee_pct = 10.0  # 10% for medium (25-50¢) contracts
            else:
                _max_fee_pct = 5.0   # 5% for larger (>50¢) contracts
            _min_fee_pct = 0.001
            _fee_anomaly = _fee_pct_of_notional > _max_fee_pct or _fee_pct_of_notional < _min_fee_pct
            
            # ACTIONABLE FEE ANOMALY: Skip this specific candidate only.
            # Do NOT set _hard_mode_block_live — a fee anomaly on one ticker is not a
            # signal that the entire cycle is corrupted.  Subsequent candidates are valid.
            if _fee_anomaly:
                logger.warning(
                    "[FEE-ANOMALY-SKIP] ticker=%s fee_pct=%.4f%% outside bounds [%.3f, %.1f] (notional=%d¢) — "
                    "SKIPPING this order only (broken quote on this ticker, not cycle-wide)",
                    c.ticker, _fee_pct_of_notional, _min_fee_pct, _max_fee_pct, _notional_cents
                )
                continue
            
            logger.info(
                "[DRY-RUN-TRACE] fee_computation | cycle=%d asset=%s market=%s side=%s | "
                "P=%d¢ ($%.2f) C=%d notional=%d¢ | "
                "raw_fee=%.4f¢ rounded=%d¢ schedule=%s expected=%d¢ | "
                "fee_pct_notional=%.4f%% fee_anomaly=%s",
                self._cycle, _candidate_asset, c.ticker, c.best_side or "none",
                c.limit_price_cents, _price_dollars, order_count, _notional_cents,
                _raw_fee_cents, _rounded_fee, _fee_branch, expected_fee,
                _fee_pct_of_notional, _fee_anomaly
            )

            # Entries: REST buy (same path as exits when KALSHI_CT_AUTO_EXIT=true).
            if not self.config.dry_run and not _live_ok:
                logger.warning("    Skip %s: live entry blocked — %s", c.ticker, _live_reason)
                continue

            # BUG-CT-3 fix: per-order risk gate (mirrors order_router.py:588-607)
            try:
                from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
                _rm_allowed, _rm_reason = get_kalshi_risk().check_order(
                    ticker=c.ticker,
                    category="crypto",
                    contracts=order_count,
                    price_cents=c.limit_price_cents,
                    edge=float(c.best_edge),
                    asset=_candidate_asset,
                    timeframe=_candidate_tf,
                    group_id=c.group_id,
                )
                if not _rm_allowed:
                    logger.warning("  Skip %s: KalshiRiskManager — %s", c.ticker, _rm_reason)
                    continue
            except Exception as _rm_exc:
                # In LIVE mode a failed risk check is FAIL-CLOSED — skip the order.
                # We cannot allow a live trade without risk gate coverage.
                if not self.config.dry_run and _live_ok:
                    logger.warning(
                        "check_order pre-flight unavailable (LIVE) — SKIPPING order %s: %s",
                        c.ticker, _rm_exc,
                    )
                    continue  # fail-closed in live mode
                else:
                    logger.debug("check_order pre-flight unavailable: %s", _rm_exc)

            # ═══════════════════════════════════════════════════════════════════════
            # DISTANCE SANITY INVARIANTS (v3 fix) — Second line of defense
            # These invariants run AFTER risk manager approval but BEFORE order
            # submission. They enforce that strikes are within sensible distance
            # from spot, regardless of what the selection pipeline allowed.
            # ═══════════════════════════════════════════════════════════════════════
            try:
                _spot_check = spot_prices.get(_candidate_asset, 0.0)
                _strike_check = float(c.strike) if hasattr(c, 'strike') and c.strike else 0.0

                # Only apply distance check for strike-based markets (not directional)
                if _strike_check > 0 and _spot_check > 0:
                    _distance_abs_check = abs(_strike_check - _spot_check)
                    _distance_pct_check = _distance_abs_check / _spot_check

                    # Get the max allowed distance for this asset/timeframe
                    from merid.prediction.kalshi_strike_selector import DEFAULT_MAX_DISTANCE
                    _max_allowed_pct = DEFAULT_MAX_DISTANCE.get(
                        (_candidate_asset, _candidate_tf),
                        self.config.max_strike_distance_pct  # fallback
                    )

                    # INVARIANT 1: Strike must be within max distance band
                    if _distance_pct_check > _max_allowed_pct:
                        logger.error(
                            "[DISTANCE-INVARIANT-VIOLATION] %s/%s: strike %.2f is %.2f%% from spot %.2f, "
                            "exceeds max %.2f%% — REJECTING (wiring bug, pipeline should have filtered this)",
                            c.ticker, _candidate_tf, _strike_check,
                            _distance_pct_check * 100, _spot_check,
                            _max_allowed_pct * 100,
                        )
                        # Record metric for observability
                        try:
                            from monitoring.metrics import get_metrics_registry
                            get_metrics_registry().counter(
                                "merid_ct_distance_invariant_violation",
                                "Contract selection allowed far-OTM contract through pipeline",
                                ["asset", "timeframe", "ticker"],
                            ).inc(labels={
                                "asset": _candidate_asset,
                                "timeframe": _candidate_tf,
                                "ticker": c.ticker,
                            })
                        except Exception:
                            pass
                        continue  # Skip this order — far OTM

                    # INVARIANT 2: Extreme distance warning (within band but far)
                    _target_band_pct = _max_allowed_pct * 0.5  # 50% of max = target band
                    if _distance_pct_check > _target_band_pct:
                        logger.warning(
                            "[DISTANCE-WARNING] %s/%s: strike %.2f is %.2f%% from spot (beyond target %.2f%%) — "
                            "allowing but monitoring",
                            c.ticker, _candidate_tf, _strike_check,
                            _distance_pct_check * 100, _target_band_pct * 100,
                        )

                    # TRACE LOG: Structured contract selection log
                    logger.info(
                        "[CONTRACT-SELECTION-TRACE] ticker=%s asset=%s tf=%s spot=%.2f strike=%.2f "
                        "distance_pct=%.3f%% max_allowed=%.3f%% target_band=%.3f%% in_target=%s",
                        c.ticker, _candidate_asset, _candidate_tf, _spot_check, _strike_check,
                        _distance_pct_check * 100, _max_allowed_pct * 100, _target_band_pct * 100,
                        str(_distance_pct_check <= _target_band_pct).lower(),
                    )
            except Exception as _dist_inv_exc:
                # Fail-open for the invariant check itself (don't block on metric/logging errors)
                logger.debug("Distance invariant check failed (non-fatal): %s", _dist_inv_exc)

            # LEAK-009: in-cycle duplicate guard — same (ticker, side) already submitted
            # this cycle (e.g. duplicate from overlap-group flattening).
            _inflight_key = (c.ticker, c.best_side)
            if _inflight_key in _inflight_this_cycle:
                logger.info(
                    "  Skip %s/%s: already submitted this cycle (in-flight dedup)",
                    c.ticker, c.best_side,
                )
                continue

            # CROSS-CYCLE DUPLICATE GUARD: skip if a resting (unfilled) order for this
            # ticker already exists in the live registry from a prior cycle.  Prevents
            # stacking duplicate orders on the same market while waiting for a fill.
            try:
                from merid.event_venues.kalshi.live_open_order_registry import (
                    get_live_open_order_registry as _get_reg,
                )
                if _get_reg().has_open_for_market(c.ticker):
                    logger.info(
                        "  Skip %s: resting order already in live registry — not reordering",
                        c.ticker,
                    )
                    continue
            except Exception:
                pass

            # BUG-016: record candidate cell metric (asset × timeframe)
            try:
                from merid.metrics.cell_metrics import record_candidate as _rcm_cand
                _rcm_cand(_candidate_asset, _candidate_tf)
            except Exception:
                pass

            # ── Pre-trade gate: lease + dedup + fill-awareness ────────────
            # Replaces old BUG-CT-2 uuid5 approach with the centralized gate
            # that also enforces single ownership and fill-awareness.
            _ct_coid: Optional[str] = None
            try:
                from merid.event_venues.kalshi.contract_lease import (
                    get_contract_lease_registry as _get_clr,
                    LeaseKey as _LK,
                )
                from merid.event_venues.kalshi.order_gate import get_pre_trade_gate as _get_ptg

                _ct_agent = f"kalshi_ct_{self.asset_symbol.lower()}"
                _ct_strategy = c.group_id or f"ct_{self.asset_symbol.lower()}"

                _lease_key = _LK(
                    venue="kalshi",
                    contract_id=c.ticker,
                    side=c.best_side or "yes",
                    strategy_group=_ct_strategy,
                )
                _ct_lease = _get_clr().acquire(_lease_key, owner_agent_id=_ct_agent)
                if _ct_lease is None:
                    logger.warning(
                        "  Skip %s: lease conflict — another agent owns this contract",
                        c.ticker,
                    )
                    continue

                _ct_verdict = _get_ptg().check(
                    agent_id=_ct_agent,
                    strategy_group=_ct_strategy,
                    contract_id=c.ticker,
                    side=c.best_side or "yes",
                    action="buy",
                    target_count=order_count,
                    price_cents=c.limit_price_cents,
                    decision_ts=time.time(),
                    existing_filled=existing,
                )
                if not _ct_verdict.allowed:
                    logger.info(
                        "  Skip %s: gate blocked — %s",
                        c.ticker, _ct_verdict.reason,
                    )
                    continue
                _ct_coid = _ct_verdict.client_order_id
            except Exception as _gate_exc:
                logger.debug("  pre_trade_gate check skipped (non-fatal): %s", _gate_exc)

            # Fallback: deterministic uuid5 if gate didn't produce a coid
            if not _ct_coid:
                _coid_key = f"{c.ticker}-{c.best_side}-{c.limit_price_cents}-{self._cycle}"
                _ct_coid = str(uuid.uuid5(uuid.NAMESPACE_DNS, _coid_key))

            order_data = {
                "ticker": c.ticker,
                "action": "buy",
                "side": c.best_side,
                "count": order_count,
                "type": "limit",
                f"{c.best_side}_price": c.limit_price_cents,
                "client_order_id": _ct_coid,
                "group_id": c.group_id,  # Propagate canonical group_id from FilterPipeline
            }

            # GROUP_ID TRACE: Log propagation of canonical group_id through pipeline
            logger.info(
                "[GROUP-ID-TRACE] ct_to_executor | cycle=%d ticker=%s group_id=%s "
                "source=FilterPipeline.MarketCandidate",
                self._cycle, c.ticker, c.group_id
            )

            logger.info(
                "  -> ORDER: %s %dx %s @ %d¢  edge=%.4f  cost=%d¢  est_fee=%d¢",
                c.best_side.upper(), order_count,
                c.ticker, c.limit_price_cents, c.best_edge, cost_cents, expected_fee,
            )

            # GUARD CHECK: Observation mode - log what we would do but don't execute
            if self._guardian and self._guardian.checklist.mode == TradingMode.OBSERVATION:
                logger.info(
                    "[OBSERVATION-MODE] Would place order: %s %dx %s @ %d¢ edge=%.4f | "
                    "conviction_components would be logged here",
                    c.best_side.upper(), order_count,
                    c.ticker, c.limit_price_cents, c.best_edge
                )
                orders_placed += 1  # Count as "placed" for metrics
                continue  # Skip actual execution

            if self.config.dry_run:
                logger.info("    [DRY RUN] %s", json.dumps(order_data))
                self.bankroll.record_trade_direction(c.ticker, c.best_side, float(c.best_edge))
                orders_placed += 1
                # [CT-TRACE] execute — Dry run order recorded
                logger.info(
                    "[CT-TRACE] stage=execute | corr_id=%s | cycle=%d | market=%s | side=%s | size=%d | price=%d¢ | status=dry_run | formulas=%s | audit_spec=%s",
                    correlation_id,
                    cycle,
                    c.ticker,
                    c.best_side or "none",
                    order_count,
                    c.limit_price_cents,
                    FORMULAS_VERSION,
                    AUDIT_SPEC_VERSION,
                )
                continue

            # [CT-TRACE] execute — Submitting live order
            logger.info(
                "[CT-TRACE] stage=execute | corr_id=%s | cycle=%d | market=%s | side=%s | size=%d | price=%d¢ | formulas=%s | audit_spec=%s",
                correlation_id,
                cycle,
                c.ticker,
                c.best_side or "none",
                order_count,
                c.limit_price_cents,
                FORMULAS_VERSION,
                AUDIT_SPEC_VERSION,
            )

            logger.info(
                "[KALSHI_ORDER_INTENT] ticker=%s side=%s action=buy count=%d price_cents=%d "
                "edge=%.4f source=kalshi_ct cycle=%d",
                c.ticker,
                c.best_side or "none",
                order_count,
                c.limit_price_cents,
                float(c.best_edge),
                cycle,
            )

            # CANARY FLIP: Route to HTTP or canonical router based on config
            # Phase 1 (0%): HTTP only + shadow mode logging
            # Phase 2 (1-99%): Random selection for gradual migration
            # Phase 3 (100%): Router only, HTTP path removed
            import random

            router_pct = self.config.use_router_percent
            rand_val = random.randint(1, 100)
            use_router = rand_val <= router_pct

            # [AUDIT] Log canary routing decision for monitoring
            logger.info(
                "[AUDIT] ct_route_decision | routed_via=%s | pct=%d | rand=%d | ticker=%s",
                "router" if use_router else "http",
                router_pct,
                rand_val,
                c.ticker,
            )

            if use_router:
                # Phase 2/3: Use canonical router (live execution)
                try:
                    adapter = get_ct_execution_adapter()
                    router_result = asyncio.get_event_loop().run_until_complete(
                        adapter.execute_live(order_data)
                    )
                    # Build synthetic HTTP-like response for downstream compatibility
                    resp = self._build_synthetic_response(router_result, order_data)
                    logger.info(
                        "[CT-CANARY] Routed via canonical router | ticker=%s | status=%s | pct=%d%%",
                        c.ticker, router_result.status, router_pct,
                    )
                except Exception as _router_exc:
                    logger.error("[CT-CANARY] Router execution failed, falling back to HTTP: %s", _router_exc)
                    resp = self._post("/portfolio/orders", order_data)
            else:
                # Phase 1: Direct HTTP (current behavior)
                resp = self._post("/portfolio/orders", order_data)

            # SHADOW MODE: Call canonical router for parity comparison (when in Phase 1 or 2)
            # This runs in parallel but does not affect live state
            if router_pct < 100:
                try:
                    adapter = get_ct_execution_adapter()
                    http_result = resp.json() if resp.status_code == 201 else {"status": "failed", "code": resp.status_code}
                    # Fire-and-forget shadow call (async, don't block cycle)
                    _shadow_task = asyncio.create_task(adapter.execute_shadow(order_data, http_result), name="ct-shadow-router")
                    _shadow_task.add_done_callback(
                        lambda t: logger.warning("CT shadow task failed: %s", t.exception()) if not t.cancelled() and t.exception() else None
                    )
                except Exception as _shadow_exc:
                    logger.debug("[CT-SHADOW] Shadow router call skipped (non-fatal): %s", _shadow_exc)

            if resp.status_code == 201:
                order = resp.json().get("order", resp.json())
                status = order.get("status", "?")
                oid = order.get("order_id", "?")
                fill = order.get("fill_count_fp", "0")
                fee = int(float(order.get("taker_fees_dollars", "0")) * 100)

                # [CT-TRACE] execute — Order placed successfully
                logger.info(
                    "[CT-TRACE] stage=execute | corr_id=%s | cycle=%d | market=%s | side=%s | size=%d | price=%d¢ | status=%s | order_id=%s | formulas=%s | audit_spec=%s",
                    correlation_id,
                    cycle,
                    c.ticker,
                    c.best_side or "none",
                    order_count,
                    c.limit_price_cents,
                    status,
                    oid,
                    FORMULAS_VERSION,
                    AUDIT_SPEC_VERSION,
                )
                
                # Update pre-trade gate: submitted → filled
                try:
                    from merid.event_venues.kalshi.order_gate import get_pre_trade_gate as _get_ptg
                    _ptg = _get_ptg()
                    _ptg.mark_submitted(_ct_coid, oid if oid != "?" else None)
                    _ct_fill_n = int(float(fill)) if fill else 0
                    if _ct_fill_n > 0:
                        _ptg.mark_filled(_ct_coid, _ct_fill_n)
                except Exception:
                    pass

                # DRY-RUN INSTRUMENTATION: Fill reconciliation
                _filled_count = int(float(fill)) if fill else 0
                _avg_fill_price = c.limit_price_cents  # Assume limit fill for now
                _partial = _filled_count < order_count
                logger.info(
                    "[DRY-RUN-TRACE] fill_reconcile | cycle=%d asset=%s market=%s side=%s | "
                    "requested_C=%d filled_C=%s avg_price=%d¢ partial=%s | "
                    "fee_expected=%d¢ fee_actual=%d¢",
                    self._cycle, _candidate_asset, c.ticker, c.best_side or "none",
                    order_count, fill, _avg_fill_price, _partial,
                    expected_fee, fee
                )
                logger.info(
                    "    %s | id=%s | filled=%s/%d",
                    status.upper(), oid, fill, order_count,
                )
                self.tracker.record_order(order, cost_cents)
                self.bankroll.record_trade_direction(c.ticker, c.best_side, float(c.best_edge))
                orders_placed += 1
                logger.info(
                    "[KALSHI_ORDER_RESULT] ticker=%s status=%s order_id=%s filled=%s "
                    "http=201 source=kalshi_ct",
                    c.ticker,
                    status,
                    oid,
                    fill,
                )
                try:
                    from merid.prediction.crypto_edge_production import log_execution_decision
                    from core.execution_gate import check_execution_gate

                    _eg_ct = check_execution_gate()
                    _safe_ct = bool(
                        getattr(_eg_ct, "safe_to_trade", True) and not getattr(_eg_ct, "blocked", False)
                    )
                    log_execution_decision(
                        market=c.ticker,
                        side=str(c.best_side or ""),
                        size=int(order_count),
                        consensus_value={
                            "best_edge": float(c.best_edge) if c.best_edge else 0.0,
                            "method": "taco_or_edge_ranking",
                        },
                        safe_to_trade=_safe_ct,
                        risk_state=getattr(_eg_ct, "gate_state", "unknown"),
                        actual_order_submitted=True,
                        block_reason="none",
                        source="kalshi_ct",
                    )
                except Exception:
                    pass
                try:
                    from merid.prediction.ua_ct_metrics import record_order_accept

                    record_order_accept()
                except Exception:
                    pass

                # GAP-3 fix: register with LiveOpenOrderRegistry for reconciliation
                try:
                    from decimal import Decimal as _Dec
                    from merid.event_venues.base import PlacedOrder as _PO
                    from merid.event_venues.kalshi.live_open_order_registry import (
                        get_live_open_order_registry,
                    )
                    get_live_open_order_registry().record_placed(
                        _PO(
                            order_id=oid,
                            market_id=c.ticker,
                            side=c.best_side,
                            size=_Dec(str(order_count)),
                            price=_Dec(str(c.limit_price_cents)) / _Dec("100"),
                            filled_size=_Dec(str(_filled_count)),
                            status=status,
                            venue="kalshi",
                        )
                    )
                except Exception as _reg_exc:
                    logger.debug("live_open_order_registry.record_placed skipped: %s", _reg_exc)
                _cycle_spent += cost_cents
                _current_exposure_cents += cost_cents
                _per_asset_exp[_candidate_asset] = _per_asset_exp.get(_candidate_asset, 0) + cost_cents
                _assets_ordered_this_cycle.add(_candidate_asset)
                _inflight_this_cycle.add((c.ticker, c.best_side))  # LEAK-009
                # BUG-016: record per-cell order metric
                try:
                    from merid.metrics.cell_metrics import record_order as _rcm_o
                    _rcm_o(
                        _candidate_asset,
                        _candidate_tf,
                        float(c.best_edge) if c.best_edge else 0.0,
                        cost_cents,
                    )
                except Exception:
                    pass
                
                # EXPOSURE MATH ASSERTION: running total must not exceed asset cap
                _actual_asset_exp = _per_asset_exp[_candidate_asset]
                if _actual_asset_exp > _asset_cap_cents + cost_cents:
                    logger.error(
                        "[EXPOSURE-MATH-FAIL] asset=%s | running=%d¢ exceeds cap=%d¢ | "
                        "pre=%d¢ cost=%d¢",
                        _candidate_asset, _actual_asset_exp, _asset_cap_cents,
                        _asset_current, cost_cents
                    )
                
                # DRY-RUN INSTRUMENTATION: Post-fill exposure update
                logger.info(
                    "[DRY-RUN-TRACE] exposure_post_fill | cycle=%d asset=%s market=%s side=%s | "
                    "filled_cost=%d¢ fee=%d¢ | asset_total=%d¢ global_total=%d¢ cycle_spent=%d¢",
                    self._cycle, _candidate_asset, c.ticker, c.best_side or "none",
                    cost_cents, fee,
                    _per_asset_exp[_candidate_asset], _current_exposure_cents, _cycle_spent
                )
                if existing == 0:
                    total_open += 1
                balance_cents -= cost_cents
                # Record trade entry so total_trades is accurate for any accepted order
                # (resting or immediately executed). PnL is deferred to settlement.
                self.bankroll.record_trade_entry()
                if status == "executed":
                    balance_cents -= fee
                    # Record fee vs gross edge for fee drag monitoring
                    gross_edge_cents = int(float(c.best_edge) * order_count * c.limit_price_cents)
                    self.bankroll.record_fee(fee, gross_edge_cents)
                # Record fill in agent_performance_tracker for UI trade counts
                try:
                    from merid.prediction.agent_performance_tracker import get_agent_performance_tracker
                    _apt = get_agent_performance_tracker()
                    _apt.record_fill(
                        agent_id=f"kalshi_ct_{self.asset_symbol.lower()}",
                        market_id=c.ticker,
                        side=c.best_side,
                        price_cents=c.limit_price_cents,
                        contracts=order_count,
                        predicted_edge=float(c.best_edge),
                        confidence=0.7,
                    )
                except Exception as _apt_exc:
                    logger.debug("agent_performance_tracker record_fill skipped: %s", _apt_exc)
                # Telegram: record fill for end-of-cycle notification
                if self._notifier:
                    self._notifier.record_fill(
                        ticker=c.ticker, side=c.best_side,
                        contracts=order_count, price_cents=c.limit_price_cents,
                        fee_cents=fee, edge=float(c.best_edge),
                        status=status, order_id=oid,
                    )
            elif resp.status_code == _CT_TRANSPORT_FAILURE_STATUS:
                logger.warning(
                    "    ORDER FAILED: local/transport error (see prior POST warning)",
                )
                logger.info(
                    "[KALSHI_ORDER_RESULT] ticker=%s status=transport_error http=%s source=kalshi_ct",
                    c.ticker,
                    resp.status_code,
                )
                try:
                    from merid.prediction.crypto_edge_production import log_execution_decision
                    from core.execution_gate import check_execution_gate

                    _eg_f = check_execution_gate()
                    log_execution_decision(
                        market=c.ticker,
                        side=str(c.best_side or ""),
                        size=int(order_count),
                        consensus_value={"best_edge": float(c.best_edge) if c.best_edge else 0.0},
                        safe_to_trade=bool(
                            getattr(_eg_f, "safe_to_trade", True)
                            and not getattr(_eg_f, "blocked", False)
                        ),
                        risk_state=getattr(_eg_f, "gate_state", "unknown"),
                        actual_order_submitted=False,
                        block_reason="transport_error",
                        source="kalshi_ct",
                    )
                except Exception:
                    pass
                try:
                    from merid.prediction.ua_ct_metrics import record_order_reject

                    record_order_reject()
                except Exception:
                    pass
            else:
                logger.warning("    ORDER FAILED %d: %s", resp.status_code, resp.text[:200])
                logger.info(
                    "[KALSHI_ORDER_RESULT] ticker=%s status=rejected http=%s detail=%s source=kalshi_ct",
                    c.ticker,
                    resp.status_code,
                    (resp.text[:200] if resp.text else ""),
                )
                try:
                    from merid.prediction.crypto_edge_production import log_execution_decision
                    from core.execution_gate import check_execution_gate

                    _eg_f = check_execution_gate()
                    log_execution_decision(
                        market=c.ticker,
                        side=str(c.best_side or ""),
                        size=int(order_count),
                        consensus_value={"best_edge": float(c.best_edge) if c.best_edge else 0.0},
                        safe_to_trade=bool(
                            getattr(_eg_f, "safe_to_trade", True)
                            and not getattr(_eg_f, "blocked", False)
                        ),
                        risk_state=getattr(_eg_f, "gate_state", "unknown"),
                        actual_order_submitted=False,
                        block_reason=f"http_{resp.status_code}",
                        source="kalshi_ct",
                    )
                except Exception:
                    pass
                try:
                    from merid.prediction.ua_ct_metrics import record_order_reject

                    record_order_reject()
                except Exception:
                    pass

        self._sync_execution_guard_kalshi_exposure(_current_exposure_cents)

        # ── Hedge pass: compute and route hedge orders after alpha fills ──
        try:
            from merid.hedging.engine import get_hedge_engine
            from merid.hedging.config import get_hedge_config
            from merid.hedging.exposure import build_exposure_snapshot

            _hcfg = get_hedge_config()
            if _hcfg.enabled:
                _h_snap = build_exposure_snapshot()
                _h_engine = get_hedge_engine()
                _h_result = _h_engine.compute_hedge_orders(
                    _h_snap, _hcfg, bankroll_cents=total_value_cents,
                )
                if _h_result.orders:
                    logger.info(
                        "[HEDGE-PASS] cycle=%d generated %d hedge orders",
                        self._cycle, len(_h_result.orders),
                    )
                    for ho in _h_result.orders:
                        if ho.target_ticker and allow_new_entries:
                            logger.info(
                                "[HEDGE-ORDER] asset=%s tf=%s side=%s count=%d price=%d¢ reason=%s ticker=%s",
                                ho.asset, ho.timeframe, ho.side, ho.count,
                                ho.price_cents, ho.hedge_reason, ho.target_ticker,
                            )
        except Exception as _hedge_exc:
            logger.debug("[HEDGE-PASS] hedge pass skipped: %s", _hedge_exc)

        # DRY-RUN INSTRUMENTATION: Position state and PnL drift at cycle end
        if _per_asset_exp:
            _total_exposure = sum(_per_asset_exp.values())
            _bankroll_health = {
                "bankroll_cents": balance_cents + portfolio_cents,
                "cash_cents": balance_cents,
                # Use portfolio_cents (all positions, same basis as bankroll_cents) not
                # _total_exposure (crypto-only).  Mixing the two double-counts any
                # non-crypto positions in _actual, causing spurious invariant failures.
                "exposure_cents": portfolio_cents,
                "realized_pnl_cents": self.bankroll.total_pnl_cents,
                "total_fees_cents": self.bankroll.total_fees_cents,
                # Keep the crypto-only figure for per-asset logging below
                "crypto_exposure_cents": _total_exposure,
            }
            # Invariant: cash + realized_pnl ≈ total_value - cost_basis
            # With exposure_cents == portfolio_cents this simplifies to:
            #   _actual = balance_cents,  _expected = balance_cents + realized_pnl
            _expected = _bankroll_health["cash_cents"] + _bankroll_health["realized_pnl_cents"]
            _actual = _bankroll_health["bankroll_cents"] - _bankroll_health["exposure_cents"]
            _invariant_satisfied = abs(_actual - _expected) <= max(100, int(_expected * 0.01))
            _bankroll_health["invariant_satisfied"] = _invariant_satisfied
            _bankroll_health["invariant_delta_cents"] = _actual - _expected
            
            # BUG-021: BANKROLL INVARIANT KILL SWITCH
            # Hard threshold = 10% of expected (env-configurable); soft threshold = 1%.
            _INV_KILL_PCT = float(os.getenv("KALSHI_CT_INVARIANT_KILL_PCT", "0.10"))
            _INV_WARN_PCT = float(os.getenv("KALSHI_CT_INVARIANT_WARN_PCT", "0.01"))
            _inv_delta = abs(_actual - _expected)
            _inv_kill_threshold = max(100, int(abs(_expected) * _INV_KILL_PCT))
            _inv_warn_threshold = max(50, int(abs(_expected) * _INV_WARN_PCT))
            if not _invariant_satisfied:
                logger.error(
                    "[BANKROLL-INVARIANT-FAIL] cycle=%d | expected=%d¢ actual=%d¢ delta=%d¢ | "
                    "cash=%d¢ exposure=%d¢ pnl=%+d¢",
                    self._cycle, _expected, _actual, _actual - _expected,
                    _bankroll_health["cash_cents"], _bankroll_health["exposure_cents"],
                    _bankroll_health["realized_pnl_cents"]
                )
                # DIAGNOSTIC DUMP: Last known state for bisect
                logger.error(
                    "[DIAGNOSTIC-DUMP] cycle=%d last_balance=%d¢ last_portfolio=%d¢ "
                    "total_fees=%d¢ total_trades=%d pnl=%+d¢",
                    self._cycle, balance_cents, portfolio_cents,
                    self.bankroll.total_fees_cents, self.bankroll.total_trades,
                    self.bankroll.total_pnl_cents
                )
                if _inv_delta >= _inv_kill_threshold:
                    # Hard kill: delta exceeds kill threshold — halt all new entries
                    # and activate the KalshiRiskManager kill switch.
                    logger.critical(
                        "[BANKROLL-INVARIANT-KILL] cycle=%d | delta=%d¢ >= kill_threshold=%d¢ "
                        "(%.1f%%) — activating kill switch",
                        self._cycle, _inv_delta, _inv_kill_threshold, _INV_KILL_PCT * 100,
                    )
                    try:
                        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
                        get_kalshi_risk().fire_kill_switch(
                            f"bankroll_invariant_delta_{_inv_delta}c_cycle_{self._cycle}"
                        )
                    except Exception as _ks_exc:
                        logger.error(
                            "[BANKROLL-INVARIANT-KILL] fire_kill_switch failed: %s — "
                            "halting CT via bankroll._halt_reason",
                            _ks_exc,
                        )
                        # KalshiRiskEngine has no halt() method; set _halt_reason directly
                        # so the existing halted check at cycle entry stops new entries.
                        try:
                            self.bankroll._halt_reason = (
                                f"bankroll_invariant_delta_{_inv_delta}c_cycle_{self._cycle}"
                            )
                        except Exception:
                            pass
                else:
                    # Soft warning only — delta within acceptable drift range
                    logger.warning(
                        "[BANKROLL-INVARIANT-WARN] cycle=%d | delta=%d¢ "
                        "(realized_pnl deferred to settlement — total_pnl_cents reflects settled trades only)",
                        self._cycle, _actual - _expected,
                    )
            
            for _asset, _exp_cents in _per_asset_exp.items():
                logger.info(
                    "[DRY-RUN-TRACE] position_state | cycle=%d asset=%s market=%s side=%s | "
                    "exposure=%d¢ total_fees=%d¢ pnl=%+d¢ | bankroll_health=%s",
                    self._cycle, _asset, "multi", "multi",
                    _exp_cents, self.bankroll.total_fees_cents, self.bankroll.total_pnl_cents,
                    _bankroll_health
                )

        # 7. Manage stale resting orders
        stale_ids = [
            oid for oid, info in self.tracker.resting_orders.items()
            if time.time() - info["placed_at"] > self.config.stale_order_seconds
        ]
        for oid in stale_ids:
            logger.info("  Cancelling stale order %s...", oid[:12])
            r = self._delete(f"/portfolio/orders/{oid}")
            if r.status_code in (200, 204):
                self.tracker.record_cancel(oid)
            elif r.status_code == _CT_TRANSPORT_FAILURE_STATUS:
                logger.warning("    Cancel failed: local/transport error")
            elif r.status_code in (404, 400, 409):
                # 404 = already filled or cancelled; 400/409 = terminal state.
                # Purge from resting_orders regardless — the order is gone from Kalshi.
                logger.info("    Cancel %s: status=%d (already settled/filled) — purging from resting", oid[:12], r.status_code)
                self.tracker.record_cancel(oid)
            else:
                logger.warning("    Cancel failed: %d", r.status_code)

        # CRYPTO COVERAGE SUMMARY: Verify all 5 assets are discovered and active
        # DOWNSTREAM INVARIANTS: Track per-asset sets through pipeline stages
        _assets_discovered = set(fp_result.per_asset.keys()) if fp_result else set()
        _assets_with_candidates = set(c.asset for c in candidates if c.asset)
        _assets_with_tradeable = set(c.asset for c in tradeable if c.asset)
        _assets_traded = set(_per_asset_exp.keys()) if _per_asset_exp else set()
        
        # Compute missing assets from expected universe
        expected_assets = set(self._active_assets)
        _missing_assets = expected_assets - _assets_discovered
        
        # WIRING BUG DETECTION: Unknown assets in discovered markets
        unknown_discovered = _assets_discovered - expected_assets
        if unknown_discovered:
            # Find tickers causing the unknown asset detection
            unknown_tickers = []
            for asset in unknown_discovered:
                if fp_result and asset in fp_result.per_asset:
                    stats = fp_result.per_asset[asset]
                    unknown_tickers.extend(getattr(stats, 'sample_tickers', []))
            logger.error(
                "[CRYPTO-WIRING-BUG] unknown_assets_in_discovered | assets=%s tickers=%s "
                "| series not in KALSHI_CRYPTO_PRODUCTS or SERIES_META_LIST",
                ",".join(sorted(unknown_discovered)),
                ",".join(unknown_tickers[:5]) if unknown_tickers else "none"
            )
        
        # TIMEFRAME SANITY: Check expected timeframes per asset
        if fp_result:
            for asset in _assets_discovered:
                if asset not in expected_assets:
                    continue
                stats = fp_result.per_asset.get(asset)
                if not stats:
                    continue
                # Expected series for this asset
                expected_series = set(self._asset_series_map.get(asset, []))
                # Discovered series (approximate from ticker prefixes)
                discovered_tickers = getattr(stats, 'sample_tickers', [])
                discovered_tfs = set()
                for ticker in discovered_tickers:
                    series_prefix = ticker.split("-")[0] if "-" in ticker else ticker
                    _, tf = self._infer_asset_timeframe(series_prefix)
                    if tf != "UNK":
                        discovered_tfs.add(tf)
                
                # Map series to expected timeframes
                expected_tfs = set()
                for series in expected_series:
                    _, tf = self._infer_asset_timeframe(series)
                    if tf != "UNK":
                        expected_tfs.add(tf)
                
                missing_tfs = expected_tfs - discovered_tfs
                if missing_tfs and len(discovered_tickers) > 0:
                    logger.warning(
                        "[CRYPTO-TF-MISSING] asset=%s missing_timeframes=%s "
                        "| Kalshi may have changed ticker format or no markets open",
                        asset, ",".join(sorted(missing_tfs))
                    )
        
        # PRICING SANITY: Force asset to missing if all spot sources failed
        _failed_spot_assets = set()
        for asset in expected_assets:
            if asset not in spot_prices:
                _failed_spot_assets.add(asset)
                if asset in _assets_discovered:
                    logger.error(
                        "[CRYPTO-PRICE-FALLBACK-FAIL] asset=%s | "
                        "CoinGecko + Coinbase + Binance all failed — "
                        "forcing into missing set for safety",
                        asset
                    )
        
        # Update missing to include pricing failures
        _missing_assets = _missing_assets | _failed_spot_assets
        
        # EXPOSURE SANITY ASSERTION: Verify per-asset exposure never exceeds caps
        if _per_asset_exp and balance_cents is not None:
            for asset, exposure_cents in _per_asset_exp.items():
                if asset not in expected_assets:
                    continue
                cap_pct = self.config.asset_max_exposure_pct.get(
                    asset, self.config.asset_exposure_default_pct
                )
                cap_cents = int(balance_cents * cap_pct)
                if exposure_cents > cap_cents + 1:  # 1¢ tolerance
                    logger.error(
                        "[EXPOSURE-CAP-VIOLATION] asset=%s exposure=%d¢ cap=%d¢ "
                        "| post-trade exposure exceeds configured cap!",
                        asset, exposure_cents, cap_cents
                    )
        
        # SCHEMA DRIFT / RECOVERY TRACKING (3+ consecutive missing cycles)
        ACTIVE_ASSETS_SET = set(self._active_assets)
        for asset in ACTIVE_ASSETS_SET:
            if asset in _assets_discovered:
                # Asset is discovered — check for recovery
                if self._schema_missing_streak.get(asset, 0) >= 3 and self._schema_missing_flag.get(asset, False):
                    logger.info(
                        "[CRYPTO-SCHEMA-RECOVER] asset=%s cycle=%d",
                        asset, self._cycle
                    )
                    self._schema_missing_flag[asset] = False
                self._schema_missing_streak[asset] = 0
            else:
                # Asset is missing — increment streak
                self._schema_missing_streak[asset] = self._schema_missing_streak.get(asset, 0) + 1
                if self._schema_missing_streak[asset] == 3:
                    self._schema_missing_flag[asset] = True
                    logger.error(
                        "[CRYPTO-SCHEMA-DRIFT] asset=%s missing_streak=%d cycle=%d "
                        "| possible venue-side ticker/format change — "
                        "verify Kalshi public pages still show %s markets",
                        asset, self._schema_missing_streak[asset], self._cycle, asset
                    )
        
        logger.info(
            "[CRYPTO-COVERAGE] cycle=%d discovered={%s} candidates={%s} tradeable={%s} traded={%s} | "
            "missing={%s} pricing_failures={%s}",
            self._cycle,
            ",".join(sorted(_assets_discovered)) if _assets_discovered else "none",
            ",".join(sorted(_assets_with_candidates)) if _assets_with_candidates else "none",
            ",".join(sorted(_assets_with_tradeable)) if _assets_with_tradeable else "none",
            ",".join(sorted(_assets_traded)) if _assets_traded else "none",
            ",".join(sorted(_missing_assets)) if _missing_assets else "none",
            ",".join(sorted(_failed_spot_assets)) if _failed_spot_assets else "none",
        )
        
        # DETAILED PER-ASSET COVERAGE: Explicitly iterate canonical asset list
        # This ensures all 5 assets (BTC, ETH, SOL, XRP, DOGE) always appear in logs
        _summary_asset_count = 0
        for asset in self._active_assets:
            _asset_discovered = asset in _assets_discovered
            _asset_candidates = sum(1 for c in candidates if c.asset == asset)
            _asset_tradeable = sum(1 for c in tradeable if c.asset == asset)
            _asset_exposure = _per_asset_exp.get(asset, 0) if _per_asset_exp else 0
            _asset_has_spot = asset in spot_prices
            _series_list = self._asset_series_map.get(asset, [])
            logger.info(
                "[CRYPTO-COVERAGE-DETAIL] cycle=%d asset=%s discovered=%s candidates=%d "
                "tradeable=%d exposure=%d¢ has_spot=%s series=%s",
                self._cycle, asset, _asset_discovered, _asset_candidates, _asset_tradeable,
                _asset_exposure, _asset_has_spot, ",".join(_series_list) if _series_list else "none"
            )
            _summary_asset_count += 1
            
            # WIRING BUG DETECTION: discovered > 0 but no candidates/tradeable without explicit reason
            if _asset_discovered and _asset_candidates == 0 and _asset_tradeable == 0:
                # Check if we have a logged reason (spot failure, filter result, etc.)
                if not _asset_has_spot:
                    logger.warning(
                        "[CRYPTO-FILTER-NO-TRADEABLE] asset=%s cycle=%d reason=no_spot "
                        "| markets discovered but spot price unavailable",
                        asset, self._cycle
                    )
                elif asset in _missing_assets:
                    logger.warning(
                        "[CRYPTO-FILTER-NO-TRADEABLE] asset=%s cycle=%d reason=schema_missing "
                        "| markets discovered but filtered out by schema check",
                        asset, self._cycle
                    )
                else:
                    # DEBUG: Log detailed filter stats for SOL diagnostics
                    _fp_stats = fp_result.per_asset.get(asset) if fp_result else None
                    if _fp_stats:
                        _all_directional = (
                            _fp_stats.raw > 0
                            and _fp_stats.directional >= _fp_stats.raw
                        )
                        if _all_directional:
                            # Only 15-minute UP/DOWN markets available for this asset —
                            # no strike-based markets exist right now.  Not a wiring bug.
                            logger.info(
                                "[CRYPTO-NO-STRIKE-MARKETS] asset=%s cycle=%d: "
                                "all %d available market(s) are directional (no numeric strike) — "
                                "no candidates this cycle",
                                asset, self._cycle, _fp_stats.raw,
                            )
                        else:
                            logger.error(
                                "[CRYPTO-WIRING-BUG] asset=%s cycle=%d discovered=%s candidates=0 tradeable=0 "
                                "| filter_stats: raw=%d no_spot=%d parsed_strike=%d directional=%d "
                                "unknown_type=%d illiquid=%d expiry_out=%d rti_q=%d pre_cap=%d post_cap=%d",
                                asset, self._cycle, _asset_discovered,
                                _fp_stats.raw, _fp_stats.no_spot, _fp_stats.parsed_strike,
                                _fp_stats.directional, _fp_stats.unknown_type, _fp_stats.illiquid,
                                _fp_stats.expiry_out_of_bounds, _fp_stats.rti_quarantined,
                                _fp_stats.candidates_pre_cap, _fp_stats.candidates_post_cap
                            )
                    else:
                        logger.error(
                            "[CRYPTO-WIRING-BUG] asset=%s cycle=%d discovered=%s candidates=0 tradeable=0 "
                            "| markets exist but nothing tradeable without logged reason",
                            asset, self._cycle, _asset_discovered
                        )
            
            # EXPOSURE CAP ALIGNMENT: Verify exposure never exceeds configured cap
            if balance_cents is not None:
                cap_pct = self.config.asset_max_exposure_pct.get(
                    asset, self.config.asset_exposure_default_pct
                )
                cap_cents = int(balance_cents * cap_pct)
                if _asset_exposure > cap_cents + 1:  # 1¢ tolerance
                    logger.error(
                        "[EXPOSURE-CAP-VIOLATION] asset=%s cycle=%d exposure=%d¢ cap=%d¢ "
                        "| post-trade exposure exceeds configured cap!",
                        asset, self._cycle, _asset_exposure, cap_cents
                    )
        
        # RUNTIME INVARIANT: Every active asset must appear exactly once in summary
        if _summary_asset_count != len(self._active_assets):
            logger.error(
                "[CRYPTO-COVERAGE-INVARIANT-FAIL] cycle=%d summary_count=%d active_count=%d "
                "| not all active assets appeared in coverage summary",
                self._cycle, _summary_asset_count, len(self._active_assets)
            )

        self._ua_cycle_trace["orders_submitted"] = orders_placed

        try:
            from merid.prediction.crypto_edge_production import maybe_log_ct_execution_invariant

            maybe_log_ct_execution_invariant(
                cycle=cycle,
                tradeable_start_count=_n_tradeable_start,
                orders_placed=orders_placed,
                allow_new_entries=allow_new_entries,
                dry_run=bool(self.config.dry_run),
                observation_mode=bool(
                    self._guardian and self._guardian.checklist.mode == TradingMode.OBSERVATION
                ),
                spot_feed_degraded=bool(self._spot_feed_degraded_this_cycle),
                live_ok=bool(_live_ok),
            )
        except Exception as _inv_exc:
            logger.debug("ct execution invariant skipped: %s", _inv_exc)

        # [CT-TRACE] monitor — Cycle monitoring complete
        logger.info(
            "[CT-TRACE] stage=monitor | corr_id=%s | cycle=%d | orders_placed=%d | balance=%d¢ | exposure=%d¢ | drawdown=%.2f%% | halted=%s | formulas=%s | audit_spec=%s",
            correlation_id,
            cycle,
            orders_placed,
            balance_cents,
            _current_exposure_cents,
            self.bankroll.get_drawdown_pct(total_value_cents) * 100,
            self.bankroll.is_halted,
            FORMULAS_VERSION,
            AUDIT_SPEC_VERSION,
        )

        # [CT-TRACE] protect — Risk protection layer check
        _protect_mode = "normal"
        _protect_reason = None
        if self.bankroll.is_halted:
            _protect_mode = "halt"
            _protect_reason = self.bankroll.halt_reason
        elif self.bankroll.get_drawdown_pct(total_value_cents) > self.config.drawdown_reduce_pct:
            _protect_mode = "reduce"
            _protect_reason = f"drawdown_above_{self.config.drawdown_reduce_pct:.0%}"
        
        logger.info(
            "[CT-TRACE] stage=protect | corr_id=%s | cycle=%d | mode=%s | reason=%s | formulas=%s | audit_spec=%s",
            correlation_id,
            cycle,
            _protect_mode,
            _protect_reason or "none",
            FORMULAS_VERSION,
            AUDIT_SPEC_VERSION,
        )

        logger.info("  %s", self.bankroll.summary(balance_cents))

        # Slow-cadence PnL reconciliation — compares internal bankroll state
        # against /portfolio/settlements + /portfolio/positions every N cycles.
        try:
            from merid.trading.ct_pnl_reconciler import maybe_reconcile
            maybe_reconcile(self)
        except Exception as _rec_exc:
            logger.debug("ct_pnl_reconcile skipped: %s", _rec_exc)

        # Telegram: flush cycle notification (fills + optional digest)
        if self._notifier:
            from merid.alerts.trade_notifier import CycleDigest
            self._notifier.flush_cycle(CycleDigest(
                cycle=self._cycle,
                balance_cents=balance_cents,
                portfolio_cents=portfolio_cents,
                total_value_cents=total_value_cents,
                peak_cents=self.bankroll.peak_balance_cents,
                drawdown_pct=round(self.bankroll.get_drawdown_pct(total_value_cents) * 100, 2),
                pnl_cents=self.bankroll.total_pnl_cents,
                fee_drag_pct=round(self.bankroll.get_fee_drag_pct() * 100, 1),
                vol_band=self.bankroll.vol_band,
                annualized_vol_pct=round(self.bankroll.annualized_vol * 100, 1),
                orders_placed=orders_placed,
                orders_filled=self.tracker.orders_filled,
                positions={k: v["qty"] for k, v in asset_positions.items()},
                halted=self.bankroll.is_halted,
                halt_reason=self.bankroll.halt_reason,
                dry_run=self.config.dry_run,
                fee_drag_tightening=self.bankroll.fee_drag_tightening,
            ))

    # ── Async loop (called by server lifespan) ───────────────────────

    async def run(self) -> None:
        """Async entry point — runs cycles in a thread executor forever."""
        if self._private_key is None:
            logger.error("KalshiContinuousTrader: %s — not starting", self._key_error)
            return

        try:
            from merid.prediction.pm_ct_policy import ct_loop_suppressed

            if ct_loop_suppressed():
                logger.warning(
                    "[CT-LEGACY] KalshiContinuousTrader.run() skipped — AgentGrid PM / live execution owns "
                    "this process (set MERID_CT_RESEARCH_ALLOW_LOOP=true for research-only CT)."
                )
                return
        except Exception as _pol:
            logger.debug("pm_ct_policy check skipped: %s", _pol)
        
        # GUARD CHECK: Validate guards on startup
        if self._guardian:
            report = self._guardian.run_all_checks()
            if not report.can_trade:
                logger.error(
                    "[GUARD-STARTUP-BLOCK] Trading blocked by guards: %s | Mode: %s",
                    report.overall_status.value,
                    report.mode.value
                )
                if self._notifier:
                    self._notifier.notify_error(
                        f"GUARD BLOCK: {report.overall_status.value} - {report.mode.value}",
                        0
                    )
                # Still run but in observation-only mode
                if self._guardian.checklist.mode == TradingMode.DISABLED:
                    logger.error("[GUARD] Mode is DISABLED - not starting")
                    return
        
        self._task = asyncio.current_task()
        # Reset stale lag-halt counter so a prior crash/restart does not immediately re-block.
        try:
            from core.execution_gate import reset_lag_halt_counter
            reset_lag_halt_counter()
        except Exception as _lhr:
            logger.debug("Could not reset lag-halt counter: %s", _lhr)
        logger.info("KalshiContinuousTrader starting (interval=%ds)", self.config.interval_seconds)
        
        # Log guard status in start notification
        _guard_status = "N/A"
        if self._guardian:
            _guard_status = f"{self._guardian.checklist.mode.value}"
        
        if self._notifier:
            cfg = self.config
            self._notifier.notify_start(
                f"Interval: {cfg.interval_seconds}s | Edge: {cfg.min_edge} | "
                f"Bankroll: ${cfg.initial_bankroll_cents / 100:.2f} | "
                f"Kelly: {cfg.kelly_fraction:.0%} | Max price: {cfg.max_contract_price_cents}¢\n"
                f"Dry run: {cfg.dry_run} | DD halt: {cfg.drawdown_halt_pct:.0%} | "
                f"Max fee drag: {cfg.max_fee_drag_pct:.0%}\n"
                f"Guard mode: {_guard_status}",
            )
        
        loop = asyncio.get_running_loop()
        _guard_check_interval = 300  # Re-check guards every 5 minutes

        while not self._shutdown:
            try:
                # Periodic guard re-check
                if self._guardian and (time.time() - self._last_guard_check) > _guard_check_interval:
                    report = self._guardian.run_all_checks()
                    self._last_guard_check = time.time()
                    if not report.can_trade and self._guardian.checklist.mode != TradingMode.OBSERVATION:
                        logger.warning("[GUARD-RUNTIME-BLOCK] Guards now blocking trades")
                
                await loop.run_in_executor(None, self._run_cycle)
            except Exception as e:
                logger.warning("Continuous trader cycle error: %s", e, exc_info=True)
                if self._notifier:
                    self._notifier.notify_error(str(e)[:200], self._cycle)

            if self._shutdown:
                break

            # Sleep in 1s increments for responsive shutdown
            for _ in range(self.config.interval_seconds):
                if self._shutdown:
                    break
                await asyncio.sleep(1)

        self._task = None  # clear so is_running reflects reality
        logger.info("KalshiContinuousTrader stopped. %s", self.tracker.summary())
        # Final state + stop notification
        try:
            bal, port = await loop.run_in_executor(None, self._get_balance)
            positions = await loop.run_in_executor(None, self._get_positions)
            asset_pos = {k: v for k, v in positions.items()
                       if any(k.upper().startswith(prefix) for prefix in self._asset_prefixes)}
            logger.info("Final balance: %dc | Portfolio: %dc | crypto positions: %s", bal, port,
                        {k: f"{v['qty']}×{v['side']}" for k, v in asset_pos.items()})
            if self._notifier:
                pos_str = ", ".join(f"{t}={v['qty']}×{v['side']}" for t, v in asset_pos.items()) if asset_pos else "none"
                self._notifier.notify_stop(
                    f"Cycles: {self._cycle} | {self.tracker.summary()}\n"
                    f"Balance: ${bal / 100:.2f} | Portfolio: ${port / 100:.2f}\n"
                    f"Positions: {pos_str}",
                    self._cycle,
                )
        except Exception:
            if self._notifier:
                self._notifier.notify_stop(
                    f"Cycles: {self._cycle} | {self.tracker.summary()}",
                    self._cycle,
                )

    async def status_snapshot_async(self) -> Dict[str, Any]:
        """Async version of status_snapshot — returns JSON-serialisable snapshot.
        
        Thread-safe: guarded by _cycle_lock (BUG-F1 fix).
        This is the preferred version when called from async contexts (APIs).
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._status_snapshot_sync)

    def _status_snapshot_sync(self) -> Dict[str, Any]:
        """Synchronous version - use status_snapshot_async from async contexts."""
        with self._cycle_lock:
            return self._status_snapshot_inner()

    def status_snapshot(self) -> Dict[str, Any]:
        """Return a JSON-serialisable snapshot of trader + bankroll state.
        
        WARNING: This method is synchronous and may block if called from
        async contexts. Prefer status_snapshot_async() in async code.
        
        Thread-safe: guarded by _cycle_lock (BUG-F1 fix).
        """
        with self._cycle_lock:
            return self._status_snapshot_inner()

    def _status_snapshot_inner(self) -> Dict[str, Any]:
        bm = self.bankroll
        cfg = self.config
        try:
            bal, _ = self._get_balance()
        except Exception:
            bal = 0
        # Use cached portfolio value from last cycle — _get_balance() does not return
        # portfolio_value (non-existent Kalshi API field); the real value is derived
        # from positions total_cost and cached in _last_portfolio_cents each cycle.
        port = self._last_portfolio_cents
        total = bal + port
        _pm_gate_ok, _pm_gate_reason = self._live_api_orders_allowed()
        _eg = self._last_execution_gate or {}
        ct_profile = os.environ.get("KALSHI_CT_PROFILE", "production").strip().lower() or "production"
        return {
            # Trader identity
            "asset_symbol": self.asset_symbol,
            "active_assets": self._active_assets,
            "asset_series_map": {a: list(s) for a, s in self._asset_series_map.items()},
            "timeframe_label": self.timeframe_label,
            "series_tickers": self.config.series_tickers,
            "running": self.is_running,
            "key_error": self._key_error,
            "cycle": self._cycle,
            "dry_run": cfg.dry_run,
            "smoke_test": cfg.min_edge == Decimal("0.01") and cfg.max_contract_price_cents == 99,
            "kalshi_ct_pm_live_gate_ok": _pm_gate_ok,
            "kalshi_ct_pm_live_gate_reason": _pm_gate_reason if not _pm_gate_ok else None,
            "execution_gate_state": _eg.get("gate_state"),
            "execution_gate_blocked": _eg.get("blocked"),
            "execution_gate_safe_to_trade": _eg.get("safe_to_trade"),
            "execution_gate_reasons": _eg.get("reasons", []),
            "kalshi_ct_profile": ct_profile,
            "kalshi_ct_auto_exit_enabled": self._auto_exit_enabled(),
            "interval_seconds": cfg.interval_seconds,
            # Bankroll
            "balance_cents": bal,
            "portfolio_cents": port,
            "total_value_cents": total,
            "peak_balance_cents": bm.peak_balance_cents,
            "drawdown_pct": round(bm.get_drawdown_pct(total) * 100, 2),
            "halted": bm.is_halted,
            "halt_reason": bm.halt_reason,
            # Performance — total_trades counts executed fills (entry recorded at fill
            # time via record_trade_entry()).  total_pnl_cents is updated at market
            # settlement by OutcomeResolver._notify_bankroll_of_settlement().
            "total_trades": bm.total_trades,
            "total_wins": bm.total_wins,
            "total_losses": bm.total_losses,
            "win_rate_pct": round(bm.win_rate * 100, 1),
            "total_pnl_cents": bm.total_pnl_cents,
            "total_fees_cents": bm.total_fees_cents,
            # Fee drag
            "fee_drag_pct": round(bm.get_fee_drag_pct() * 100, 1),
            "fee_drag_tightening": bm.fee_drag_tightening,
            "fee_drag_window": bm._fee_history.maxlen,
            # Volatility
            "vol_band": bm.vol_band,
            "annualized_vol_pct": round(bm.annualized_vol * 100, 1),
            # Effective limits
            "eff_max_orders_per_cycle": bm.effective_max_orders_per_cycle(),
            "eff_max_exposure_pct": round(bm.effective_max_exposure_pct() * 100, 1),
            # Config summary
            "config": {
                "initial_bankroll_cents": cfg.initial_bankroll_cents,
                "kelly_fraction": cfg.kelly_fraction,
                "max_risk_per_trade_pct": cfg.max_risk_per_trade_pct,
                "max_contract_price_cents": cfg.max_contract_price_cents,
                "min_edge": str(cfg.min_edge),
                "drawdown_halt_pct": cfg.drawdown_halt_pct,
                "drawdown_reduce_pct": cfg.drawdown_reduce_pct,
                "churn_cooldown_cycles": cfg.churn_cooldown_cycles,
                "churn_edge_improvement": cfg.churn_edge_improvement,
                "max_fee_drag_pct": cfg.max_fee_drag_pct,
                "vol_low_threshold": cfg.vol_low_threshold,
                "vol_high_threshold": cfg.vol_high_threshold,
                "fee_window_low_vol": cfg.fee_window_low_vol,
                "fee_window_mid_vol": cfg.fee_window_mid_vol,
                "fee_window_high_vol": cfg.fee_window_high_vol,
            },
            # Orders
            "orders_placed": self.tracker.orders_placed,
            "orders_filled": self.tracker.orders_filled,
            "orders_cancelled": self.tracker.orders_cancelled,
            "resting_orders": len(self.tracker.resting_orders),
            # Per-asset observability (BUG-L1/OB1 fix)
            "spot_prices": {
                asset: {
                    "price": info.get("price"),
                    "age_seconds": int(time.time() - info.get("fetched_at", 0)),
                    "source": info.get("source", "unknown"),
                    "is_stale": info.get("is_stale", False),
                }
                for asset, info in self._last_spots.items()
            },
            "spot_feed_degraded": getattr(self, "_spot_feed_degraded_this_cycle", False),
            # Guard system status
            "guard_status": {
                "mode": self._guardian.checklist.mode.value if self._guardian else "N/A",
                "can_trade": self._guardian.can_trade() if self._guardian else False,
                "last_check": self._last_guard_check if self._last_guard_check > 0 else None,
            } if self._guardian else None,
            "per_asset_indicators": {
                asset: {
                    "bars": stack.snapshot().bars_available if (stack := self._indicator_stacks.get(asset)) else 0,
                    "last_updated_ago_s": int(time.time() - self._indicator_last_updated.get(asset, 0))
                        if self._indicator_last_updated.get(asset) else None,
                }
                for asset in self._active_assets
            },
            # Sparkline series (last 60 cycles)
            "cycle_history": list(bm._cycle_history),
            # 15-minute cycle drawdown metrics
            "cycle_drawdown": self._get_cycle_drawdown_metrics(),
        }

    def _get_cycle_drawdown_metrics(self) -> Dict[str, Any]:
        """Get 15-minute cycle drawdown metrics for status snapshot."""
        try:
            from merid.event_venues.kalshi.cycle_drawdown import get_cycle_drawdown_manager
            cdm = get_cycle_drawdown_manager()
            return cdm.get_cycle_metrics()
        except Exception as exc:
            logger.debug("Cycle drawdown metrics unavailable: %s", exc)
            return {}

    def stop(self) -> None:
        """Signal graceful shutdown."""
        self._shutdown = True
        logger.info("KalshiContinuousTrader shutdown requested")

    @property
    def is_running(self) -> bool:
        return not self._shutdown and self._task is not None

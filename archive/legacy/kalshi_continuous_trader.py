# LEGACY / DEMO: Not used by kalshi_crypto_15m_v2 15m stack.
# Do not import from 15m code paths.
# This module is archived and superseded by LeanAgentGrid15m and Kalshi15mLoop.

"""
Kalshi Continuous Crypto Trader — Async Server Module
=====================================================
Wraps the standalone continuous trader logic for integration with the
MERID server lifespan.  Targets BTC, ETH, SOL, XRP, DOGE across
15-minute, hourly, and other timescales.  Each asset is filtered
against its own spot price.  All blocking HTTP calls (Kalshi REST)
are offloaded to a thread executor so the asyncio event loop stays free.

Spot price priority (aligned with Kalshi's CFB RTI):
1. Coinbase (primary) - USD spot
2. Kraken (secondary) - USD spot
3. BinanceUS (tertiary) - USD pairs

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
import concurrent.futures
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

from merid.constants import CRYPTO_15M_ASSETS
# DEPRECATED: PM risk config superseded by venue config (kalshi_risk.py)
# Using venue KalshiRiskConfig for single source of truth
from merid.event_venues.kalshi.kalshi_risk import KalshiRiskConfig as VenueKalshiRiskConfig
from config.kalshi_universe import KALSHI_CRYPTO_PRODUCTS, kalshi_ct_default_series_tickers
from utils.logger import get_logger
from merid.trading.kalshi_filter_pipeline import FilterPipeline, FilterPipelineConfig
from merid.guards import TradingGuardian, GoLiveChecklist, TradingMode
from merid.formulas import generate_correlation_id, FORMULAS_VERSION, AUDIT_SPEC_VERSION

# Market Regime Gate — crypto basket flatness filter
from merid.market_regime import get_regime_gate, RegimeAction

# Trading State Machine — scalping + hedging states (A/B/C/D)
from merid.trading.trading_state import (
    TradingState,
    TradingStateMachine,
    TransitionReason,
    get_state_machine,
)

# Hedging Engine — exposure-based hedge computation
from merid.hedging.engine import CryptoHedgeEngine, HedgeOrder, get_hedge_engine
from merid.hedging.config import get_hedge_config
from merid.hedging.exposure import ExposureSnapshot

# Unified Drawdown Config — single source of truth
from merid.risk.drawdown_config import get_drawdown_config, validate_existing_configs

# Top-3 Edge Selector & Allocator — cross-agent selection and sizing
from merid.trading.top3_edge_allocator import (
    EdgeCandidate as Top3EdgeCandidate,  # Legacy alias
    Top3Allocation,
    Top3Batch,
    BatchStatus,
    get_top3_allocator,
)
from merid.trading.top3_batch_manager import (
    get_top3_batch_manager,
    REJECT_NO_ACTIVE_BATCH,
    REJECT_ASSET_NOT_IN_TOP3,
    REJECT_NOTIONAL_LIMIT_REACHED,
)
from merid.guards.global_execution_guard import get_global_execution_guard

# Module-level logger (must be defined before feature flag logging)
logger = get_logger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# Top-N Allocator (NEW) — Fixed fractional risk per cycle
# ═══════════════════════════════════════════════════════════════════════════
# Import canonical settings (single source of truth)
# These come from environment via core/settings.py
from core.settings import USE_TOPN_ALLOCATOR, MAX_CYCLE_RISK_PCT, MAX_TOTAL_RISK_PCT

# Module-level alias for backwards compatibility in this file
_USE_TOPN_ALLOCATOR = USE_TOPN_ALLOCATOR

# Log on module load (startup verification)
if _USE_TOPN_ALLOCATOR:
    logger.info("[RISK-MODE] Using new TopNEdgeAllocator with fixed fractional risk (1-2% per cycle)")
    logger.info("[RISK-CONFIG] USE_TOPN_ALLOCATOR=true, max_cycle_risk_pct=%.2f%%, max_total_risk_pct=%.2f%%",
                MAX_CYCLE_RISK_PCT * 100, MAX_TOTAL_RISK_PCT * 100)
else:
    logger.warning("[RISK-MODE] Using legacy Kelly sizing (per-trade risk) — DANGEROUS, can cause oversizing!")
    logger.warning("[RISK-CONFIG] USE_TOPN_ALLOCATOR=false — Set to 'true' to enable safe sizing")

from merid.trading.topn_allocator import (
    EdgeCandidate as TopNEdgeCandidate,
    TopNEdgeAllocator,
    TopNAllocatorConfig,
    get_topn_allocator,
)

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

# Track if bankroll config has been logged (prevents spam in multi-worker deployments)
_bankroll_config_logged = False
_bankroll_config_log_lock = threading.Lock()


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
    """Bankroll base min_edge (fees/slippage scaling builds on this).
    
    P0-004 FIX: Now reads from kalshi_distance.yaml as primary source,
    with env overrides for runtime tuning.
    """
    if smoke_test:
        return Decimal("0.01")
    env_me = os.getenv("KALSHI_TRADER_MIN_EDGE")
    if env_me:
        return Decimal(env_me)
    
    # P0-004: Load from kalshi_distance.yaml (canonical source)
    try:
        import yaml
        config_path = Path(__file__).parent.parent.parent / "config" / "kalshi_distance.yaml"
        if config_path.exists():
            with open(config_path, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
            min_edge_near = config.get("min_edge_near", {})
            # Use BTC as base (most liquid, tightest edge requirement)
            # CONSERVATIVE ALIGNMENT (2026-05-10): Fallback to 5% instead of 2.5%
            base_edge = min_edge_near.get("BTC", 0.050)
            logger.info(f"[CT-CONFIG] Loaded min_edge from kalshi_distance.yaml: {base_edge}")
            return Decimal(str(base_edge))
    except Exception as e:
        logger.warning(f"[CT-CONFIG] Failed to load kalshi_distance.yaml: {e}, using fallback")
    
    # Fallback chain
    profile = os.getenv("KALSHI_CT_PROFILE", "production").strip().lower() or "production"
    if profile == "initial_live":
        return Decimal("0.012")
    if profile == "diagnostic":
        return Decimal(os.getenv("KALSHI_CT_DIAGNOSTIC_MIN_EDGE", "0.008"))
    from config.trading_constants import EDGE_MIN_THRESHOLD
    return Decimal(str(EDGE_MIN_THRESHOLD))


@dataclass
class TraderConfig:
    interval_seconds: int = 60
    dry_run: bool = False

    # ── Bankroll management (capital-preservation-first) ──────────────
    # initial_bankroll_cents is a STATIC REFERENCE for performance reporting only.
    # It should be set once at the start of a trading epoch (e.g., $10,000 = 1_000_000 cents).
    # It is NOT used for live sizing — live sizing uses actual Kalshi balance with max_riskable_usd cap.
    initial_bankroll_cents: int = 0  # 0 = no reference set (performance % returns will be relative to 0)

    # Live equity risk controls
    # max_riskable_usd: Cap on how much of live Kalshi balance can be used for sizing.
    #   If live_balance > max_riskable_usd, effective_equity = max_riskable_usd
    #   If live_balance <= max_riskable_usd, effective_equity = live_balance
    #   0 = no cap (use full live balance)
    max_riskable_usd: float = 0.0  # 0 = unlimited (use full Kalshi balance)

    # min_operational_balance_usd: Floor below which trading halts (safety reserve)
    #   If live_balance < min_operational_balance_usd: no new orders, existing positions may be reduced
    #   0 = no minimum (trade with any balance)
    min_operational_balance_usd: float = 0.0  # 0 = no minimum reserve

    # ═════════════════════════════════════════════════════════════════
    # CYCLE RISK CAP (configurable via KALSHI_TRADER_RISK_PCT env var)
    # CRITICAL: Unified to 3% for all modes - no exceptions
    # Default: 3% per cycle (aligned with MAX_CYCLE_RISK_PCT)
    # ═════════════════════════════════════════════════════════════════
    max_risk_per_trade_pct: float = 0.03  # 3% unified cycle risk (optimized 2026-05-07)
    kelly_fraction: float = 0.20         # fifth-Kelly (more conservative, survival-first)
    max_contract_price_cents: int = 65   # Allow mid-curve markets up to 65¢ (was 35¢)
    min_contract_price_cents: int = 2    # skip penny contracts (no liquidity)
    max_position_per_market: int = 3     # max contracts per ticker (reduced for 2% risk)
    max_open_positions: int = 3          # max simultaneous markets (reduced for 2% risk)
    max_total_exposure_pct: float = 0.06 # 6% total exposure aligned with cluster stop (was 15%)

    # ── Per-asset exposure limits ────────────────────────────────────
    # Maximum fraction of bankroll each crypto asset may consume.
    # Unified 3% cycle risk across all assets - aligned with MAX_CYCLE_RISK_PCT.
    # No per-asset differentiation - top-3 edge allocation is the single source of truth.
    # Legacy per-asset caps (25%/20%/10%) removed - all assets now use 3% unified risk.
    # Built from canonical CRYPTO_15M_ASSETS to enforce the 5-asset invariant.
    asset_max_exposure_pct: Dict[str, float] = field(default_factory=lambda: {
        asset: 0.03 for asset in CRYPTO_15M_ASSETS  # 3% unified cycle risk
    })
    asset_exposure_default_pct: float = 0.10   # fallback for any unlisted asset
    # CT-only: scales each asset's cent cap by timeframe (15m / 1h / daily / weekly). Not read from env
    # in ``from_env()`` — change here or wire env explicitly if needed.
    series_exposure_multiplier: Dict[str, float] = field(default_factory=lambda: {
        "15m":    0.80,  # Increased to 0.80 for 15m scalper (was 0.40)
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
    min_balance_cents: int = 150         # $1.50 for 15m scalper (was $3.00) - more tradeable capital

    # ── Edge requirements ─────────────────────────────────────────────
    # P0-005 FIX: Now loaded dynamically from kalshi_distance.yaml via _resolve_trader_min_edge()
    min_edge: Decimal = field(default_factory=lambda: _resolve_trader_min_edge(False))
    # Directional (15m up/down) markets: max |P_yes − 0.5| from indicator confidence
    directional_max_tilt: float = 0.15
    fee_per_contract: Decimal = Decimal("0.02")  # ~2¢ Kalshi taker fee (= 0.07 * P*(1-P) at 50¢)
    slippage: Decimal = Decimal("0.01")  # 1% slippage

    # ── CT -> Router Migration (Phase 3: Canonical Chokepoint) ───────
    # SECURITY FIX: Hard-coded to 100 (router-only). The direct HTTP bypass
    # has been removed to enforce single-execution-authority.
    # All orders MUST flow through the canonical router and unified risk guard.
    # See: docs/security/single_execution_authority.md
    use_router_percent: int = field(default=100, init=False)

    # ── Market selection ─────────────────────────────────────────────
    # Default: 15m–weekly from kalshi_universe (excludes monthly/annual); see kalshi_ct_default_series_tickers
    series_tickers: List[str] = field(default_factory=kalshi_ct_default_series_tickers)
    max_markets_to_scan: int = 20      # 20 for 15m scalper (was 10) - more opportunities
    max_strike_distance_pct: float = 0.125  # 12.5% - tightened from 25%

    # ── Fee-aware edge scaling ───────────────────────────────────────
    # Kalshi fee = ceil(0.07 * C * P * (1-P)); worst at mid-curve
    # Require higher edge at mid-curve prices where fee drag is worst
    fee_edge_multiplier_midcurve: float = 1.25  # 1.25x for 15m scalper (was 1.75x) - allow mid-curve
    fee_edge_multiplier_penny: float = 2.0      # 2x min_edge for ≤5¢ contracts (rounding kills)

    # ── Anti-churn hysteresis ────────────────────────────────────────
    churn_cooldown_cycles: int = 1       # 1 cycle for 15m scalper (was 3) - faster flips
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
    # Env: KALSHI_TRADER_NO_STOP_CENTS / KALSHI_TRADER_NO_PROFIT_CENTS
    yes_stop_loss_cents: int = 8         # exit YES position if bid ≤ 8¢
    yes_profit_take_cents: int = 85      # exit YES position if bid ≥ 85¢
    no_stop_loss_cents: int = 92         # exit NO position if ask ≥ 92¢ (symmetric: 100-8)
    no_profit_take_cents: int = 15       # exit NO position if ask ≤ 15¢ (symmetric: 100-85)

    def to_risk_config(self) -> VenueKalshiRiskConfig:
        """Map trader config risk fields to the shared KalshiRiskConfig."""
        return VenueKalshiRiskConfig(
            max_total_notional_usd=self.initial_bankroll_cents / 100.0 * self.max_total_exposure_pct,
            max_daily_loss_usd=self.initial_bankroll_cents / 100.0 * self.drawdown_halt_pct,
            max_single_order_contracts=self.max_position_per_market,
            max_single_order_notional_usd=self.initial_bankroll_cents / 100.0 * self.max_risk_per_trade_pct,
            drawdown_halt_pct=self.drawdown_halt_pct,
            drawdown_unwind_pct=self.drawdown_reduce_pct,
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
            # initial_bankroll_cents: static reference for performance reporting (not live sizing)
            initial_bankroll_cents=int(os.getenv("KALSHI_TRADER_BANKROLL", "0")),  # 0 = no reference epoch set
            # Live equity caps for safety
            max_riskable_usd=float(os.getenv("KALSHI_TRADER_MAX_RISKABLE_USD", "0.0")),  # 0 = use full Kalshi balance
            min_operational_balance_usd=float(os.getenv("KALSHI_TRADER_MIN_OP_BALANCE_USD", "0.0")),  # 0 = no minimum
            max_risk_per_trade_pct=float(os.getenv("KALSHI_TRADER_RISK_PCT", "0.03")),  # 3% unified cycle risk
            kelly_fraction=float(os.getenv("KALSHI_TRADER_KELLY_FRAC", "0.20")),  # fifth-Kelly - calibrated
            max_contract_price_cents=99 if smoke_test else int(os.getenv("KALSHI_TRADER_MAX_PRICE", "65")),
            min_contract_price_cents=int(os.getenv("KALSHI_TRADER_MIN_PRICE", "2")),
            max_position_per_market=1 if smoke_test else int(os.getenv("KALSHI_TRADER_MAX_POSITION", "3")),  # 3 for 2% risk regime
            max_open_positions=int(os.getenv("KALSHI_TRADER_MAX_OPEN", "3")),  # 3 for 2% risk regime
            max_total_exposure_pct=float(os.getenv("KALSHI_TRADER_MAX_EXPOSURE", "0.06")),  # 6% aligned with cluster stop
            asset_max_exposure_pct={
                asset: float(os.getenv(f"KALSHI_TRADER_EXPOSURE_{asset}", "0.03"))  # 3% unified cycle risk
                for asset in CRYPTO_15M_ASSETS
            },
            asset_exposure_default_pct=float(os.getenv("KALSHI_TRADER_EXPOSURE_DEFAULT", "0.03")),  # 3% unified cycle risk
            global_max_exposure_pct=float(os.getenv("KALSHI_TRADER_GLOBAL_EXPOSURE", "0.06")),  # 6% aligned with cluster stop
            min_asset_cap_cents=int(os.getenv("KALSHI_TRADER_MIN_ASSET_CAP_CENTS", "100")),
            drawdown_halt_pct=float(os.getenv("KALSHI_TRADER_DD_HALT", "0.15")),  # 15% - calibrated
            drawdown_reduce_pct=float(os.getenv("KALSHI_TRADER_DD_REDUCE", "0.08")),  # 8% - calibrated
            min_balance_cents=int(os.getenv("KALSHI_TRADER_MIN_BALANCE", "150")),  # $1.50 for scalper (was $3.00)
            min_edge=_resolve_trader_min_edge(smoke_test),
            directional_max_tilt=float(os.getenv("KALSHI_CT_DIRECTIONAL_MAX_TILT", "0.15")),
            max_markets_to_scan=int(os.getenv("KALSHI_TRADER_MAX_SCAN", "20")),  # 20 for 15m scalper (was 10)
            max_strike_distance_pct=float(os.getenv("KALSHI_TRADER_MAX_DISTANCE", "0.20")),  # 20% default per v2 calibration
            stale_order_seconds=int(os.getenv("KALSHI_TRADER_STALE_ORDER_SEC", "120")),
            max_orders_per_cycle=1 if smoke_test else int(os.getenv("KALSHI_TRADER_MAX_ORDERS_CYCLE", "8")),  # 8 for 15m scalper
            fee_edge_multiplier_midcurve=float(os.getenv("KALSHI_TRADER_FEE_MULT_MID", "1.25")),  # 1.25x for scalper (was 1.75x)
            fee_edge_multiplier_penny=float(os.getenv("KALSHI_TRADER_FEE_MULT_PENNY", "2.0")),
            churn_cooldown_cycles=int(os.getenv("KALSHI_TRADER_CHURN_COOLDOWN", "1")),  # 1 for 15m scalper (was 3)
            churn_edge_improvement=float(os.getenv("KALSHI_TRADER_CHURN_EDGE_IMPROV", "0.05")),
            max_fee_drag_pct=float(os.getenv("KALSHI_TRADER_MAX_FEE_DRAG", "0.25")),  # 25% - calibrated
            fee_drag_lookback=int(os.getenv("KALSHI_TRADER_FEE_DRAG_LOOKBACK", "30")),
            vol_lookback_bars=int(os.getenv("KALSHI_TRADER_VOL_LOOKBACK", "20")),
            vol_low_threshold=float(os.getenv("KALSHI_TRADER_VOL_LOW", "0.40")),
            vol_high_threshold=float(os.getenv("KALSHI_TRADER_VOL_HIGH", "0.80")),
            fee_window_low_vol=int(os.getenv("KALSHI_TRADER_FEE_WIN_LOW", "50")),
            fee_window_mid_vol=int(os.getenv("KALSHI_TRADER_FEE_WIN_MID", "30")),
            fee_window_high_vol=int(os.getenv("KALSHI_TRADER_FEE_WIN_HIGH", "20")),
            max_cycle_spend_pct=float(os.getenv("KALSHI_TRADER_CYCLE_SPEND_PCT", "0.03")),  # 3% unified cycle spend
            yes_stop_loss_cents=int(os.getenv("KALSHI_TRADER_YES_STOP_CENTS", "8")),
            yes_profit_take_cents=int(os.getenv("KALSHI_TRADER_YES_PROFIT_CENTS", "85")),
            no_stop_loss_cents=int(os.getenv("KALSHI_TRADER_NO_STOP_CENTS", "92")),
            no_profit_take_cents=int(os.getenv("KALSHI_TRADER_NO_PROFIT_CENTS", "15")),
            # SECURITY: use_router_percent is hard-coded to 100 (router-only)
            # Direct HTTP bypass has been removed. See use_router_percent field definition.
        )

    def __post_init__(self) -> None:
        _suppress = False
        try:
            from merid.prediction.pm_ct_policy import ct_loop_suppressed

            _suppress = bool(ct_loop_suppressed())
        except (ImportError, AttributeError, TypeError):
            pass
        _ct_on = os.getenv("MERID_ENABLE_KALSHI_CT", "").lower() in ("1", "true", "yes", "on")
        _tag = "[CT-LEGACY/DEV] " if (_ct_on and not _suppress) else ""

        # ═══════════════════════════════════════════════════════════════════════════
        # BANKROLL CONFIGURATION AUDIT (once per process to prevent multi-worker spam)
        # ═══════════════════════════════════════════════════════════════════════════
        global _bankroll_config_logged, _bankroll_config_log_lock
        with _bankroll_config_log_lock:
            if not _bankroll_config_logged:
                _bankroll_config_logged = True
                
                if self.initial_bankroll_cents > 0:
                    logger.info(
                        "[BANKROLL-CONFIG] Static reference bankroll set: $%.2f USD (%d cents). "
                        "This is used for performance reporting only, not live sizing.",
                        self.initial_bankroll_cents / 100,
                        self.initial_bankroll_cents
                    )
                else:
                    logger.info(
                        "[BANKROLL-CONFIG] No static reference bankroll set. "
                        "Performance %% returns will be relative to 0. "
                        "To set a reference, use KALSHI_TRADER_BANKROLL env var."
                    )

                # Log live equity risk controls
                if self.max_riskable_usd > 0:
                    logger.info(
                        "[BANKROLL-CONFIG] max_riskable_usd=$%.2f — capping live Kalshi balance at this amount for sizing",
                        self.max_riskable_usd
                    )
                else:
                    logger.info(
                        "[BANKROLL-CONFIG] max_riskable_usd=0 (default) — "
                        "Using FULL live Kalshi API balance for sizing. "
                        "Set KALSHI_TRADER_MAX_RISKABLE_USD to add a cap."
                    )

                if self.min_operational_balance_usd > 0:
                    logger.info(
                        "[BANKROLL-CONFIG] min_operational_balance_usd=$%.2f (explicit) — "
                        "trading will halt below this absolute floor",
                        self.min_operational_balance_usd
                    )
                else:
                    logger.info(
                        "[BANKROLL-CONFIG] min_operational_balance_usd=0 (default) — "
                        "Will derive from LIVE balance each cycle (1-2%% default = MAX_CYCLE_RISK_PCT)."
                    )

        # PRODUCTION AUDIT (Step 2): NO fallback bankroll values - must use KalshiPortfolio.get_balance
        # Legacy default removed to prevent silent trading with fake bankroll
        # NOTE: initial_bankroll_cents is a STATIC REFERENCE for performance reporting only.
        # Trading uses live bankroll from bankroll_service_v2, so we don't block if this is 0.
        if self.initial_bankroll_cents <= 0:
            logger.warning(
                f"[{_tag}] initial_bankroll_cents={self.initial_bankroll_cents} (no static reference set). "
                "Performance % returns will be relative to 0. "
                "Live trading uses bankroll_service_v2 for actual balance."
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

class BankrollManager:
    """Backward-compatible alias for KalshiContinuousTrader risk management.

    DEPRECATED: PM risk engine (kalshi_risk_engine.py) superseded by venue config (kalshi_risk.py).
    This class now provides a thin wrapper around venue KalshiRiskManager.

    Accepts a ``TraderConfig`` (or ``KalshiRiskConfig``) so existing
    call-sites (status_snapshot, notifier, etc.) keep working unchanged.
    """

    def __init__(self, config: TraderConfig) -> None:
        risk_cfg = config.to_risk_config() if hasattr(config, "to_risk_config") else config
        # Store config for later use with venue KalshiRiskManager
        self._config = risk_cfg
        _quiet = False
        try:
            from merid.prediction.pm_ct_policy import ct_loop_suppressed

            _quiet = bool(ct_loop_suppressed())
        except (ImportError, AttributeError, TypeError):
            pass
        # Initialize venue KalshiRiskManager
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        self._risk_manager = get_kalshi_risk()


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
# GLOBAL RISK GUARD — Re-exported from the shared singleton module.
# ═══════════════════════════════════════════════════════════════════════════
# Canonical definition now lives in ``merid.guards.global_risk_guard``.
# CT imports the shared types so every order flow (CT, agent grid, lanes,
# web) shares the same per-cycle / total risk envelope on a unified
# ``equity_cents``.  See ``docs/TRADING_OWNERSHIP_DECISION.md`` and
# ``docs/ORDER_FLOW_AND_OVERTRADING_AUDIT.md``.
# ═══════════════════════════════════════════════════════════════════════════
from merid.guards.global_risk_guard import (  # noqa: E402
    PendingOrderRisk as PendingOrderRisk,
    GlobalRiskGuard as _SharedGlobalRiskGuard,
    get_global_risk_guard as _get_global_risk_guard,
)


# Keep the local symbol name so existing tests/imports continue to work.
class GlobalRiskGuard(_SharedGlobalRiskGuard):  # type: ignore[misc]
    """Last-line global risk guard — enforces hard caps before any order submit.
    
    This code enforces a hard 1-2% per-cycle and total risk cap. No orders may bypass this.
    
    Invariants enforced:
    1. Sum of max loss for all new orders in a cycle ≤ cycle_risk_cents
    2. Total open risk (existing + new) ≤ max_total_risk_cents
    3. Each asset's total risk ≤ asset_max_risk_cents
    
    If any invariant would be violated, the guard logs CRITICAL and returns (allowed=False).

    Implementation lives in ``merid.guards.global_risk_guard.GlobalRiskGuard``;
    this subclass exists only to preserve the ``merid.trading.kalshi_continuous_trader.GlobalRiskGuard``
    import path for existing tests.  No additional behavior.
    """
    pass


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
        # Built from canonical CRYPTO_15M_ASSETS to enforce the 5-asset invariant.
        _DISTANCE_FALLBACK = {}
        for asset in CRYPTO_15M_ASSETS:
            if asset in ("BTC", "ETH"):
                # Major assets: tighter distance caps
                _DISTANCE_FALLBACK.update({
                    (asset, "15m"): 0.15, (asset, "1h"): 0.20,
                    (asset, "daily"): 0.25, (asset, "weekly"): 0.35,
                    (asset, "monthly"): 0.50, (asset, "annual"): 0.50,
                })
            elif asset == "SOL":
                # SOL: moderate distance caps
                _DISTANCE_FALLBACK.update({
                    (asset, "15m"): 0.20, (asset, "1h"): 0.25,
                    (asset, "daily"): 0.30, (asset, "weekly"): 0.40,
                    (asset, "monthly"): 0.60, (asset, "annual"): 0.60,
                })
            elif asset in ("XRP", "DOGE"):
                # Alt assets: wider distance caps
                _DISTANCE_FALLBACK.update({
                    (asset, "15m"): 0.30 if asset == "DOGE" else 0.20,
                    (asset, "1h"): 0.35 if asset == "DOGE" else 0.25,
                    (asset, "daily"): 0.40, (asset, "weekly"): 0.50,
                    (asset, "monthly"): 0.70, (asset, "annual"): 0.70,
                })
        return _DISTANCE_FALLBACK


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
        # ═════════════════════════════════════════════════════════════════
        # PROFILE COMPATIBILITY CHECK
        # ═════════════════════════════════════════════════════════════════
        # CT is legacy/research-only for kalshi_crypto_15m_v2.
        # Removed hard-block to allow CT for research/parity checks.
        # AgentGrid PM is the canonical live path for this profile.
        current_profile = os.getenv("MERID_PROFILE", "")
        if current_profile == "kalshi_crypto_15m_v2":
            logger.warning(
                "[CT-DEPRECATION] KalshiContinuousTrader is legacy/research-only for profile=%s. "
                "Use KalshiTradingAgent via AgentGrid for live trading. CT may be used for research "
                "or parity checks, but is not the primary execution path.",
                current_profile
            )

        # ═════════════════════════════════════════════════════════════════
        # GLOBAL KILL SWITCH - Check before any initialization
        # ═════════════════════════════════════════════════════════════════
        enabled = os.getenv("KALSHI_TRADER_ENABLED", "true").lower() in ("true", "1", "yes")
        if not enabled:
            logger.critical("[CT-KILL-SWITCH] KALSHI_TRADER_ENABLED=false - CT disabled at startup")
            raise RuntimeError("KALSHI_TRADER_ENABLED=false - Continuous Trader disabled by kill switch")
        
        self.config = TraderConfig.from_env()
        self.tracker = OrderTracker()
        self.bankroll = BankrollManager(self.config)
        self._shutdown = False
        self._cycle = 0
        self._task: Optional[asyncio.Task] = None
        self._auto_exit_task: Optional[asyncio.Task] = None  # hedge TP/SL auto-exit loop
        self._cycle_lock = threading.Lock()

        # ═════════════════════════════════════════════════════════════════
        # GLOBAL RISK GUARD — Last-line defense (NEW for Top-N allocator)
        # ═════════════════════════════════════════════════════════════════
        # This enforces hard 1-2% per-cycle risk cap at the final order submission point.
        # No orders may bypass this. See GlobalRiskGuard class for details.
        # Uses canonical settings from core.settings (env -> settings -> here)
        # Shared process-wide singleton — same guard is invoked by
        # route_order_async for agent-grid / lane / web callers, so the
        # 1-2% envelope is enforced across every order source.  The
        # singleton loads the same MAX_*_RISK_PCT values lazily.
        self._risk_guard = _get_global_risk_guard()
        # Note: CT computes ``total_value_cents`` (cash + MTM) per cycle and
        # passes it explicitly to ``check_order``.  The default equity
        # provider used by ``route_order_async`` for agent-grid / lane / web
        # callers reads from ``KalshiPositionCache.total_value_cents`` with
        # ``MERID_INITIAL_CAPITAL`` as fallback — see
        # ``merid.guards.global_risk_guard.default_equity_cents``.
        logger.info(
            "[RISK-GUARD] Initialized | max_cycle_risk_pct=%.2f%%, max_total_risk_pct=%.2f%%",
            MAX_CYCLE_RISK_PCT * 100, MAX_TOTAL_RISK_PCT * 100
        )
        
        # Top-N allocator instance (used when USE_TOPN_ALLOCATOR=true)
        self._topn_allocator: Optional[TopNEdgeAllocator] = None
        if _USE_TOPN_ALLOCATOR:
            self._topn_allocator = get_topn_allocator()
            logger.info(
                "[CT-INIT] Top-N allocator enabled | max_cycle_risk=%.2f%% | "
                "max_edges=%d | min_contracts=%d",
                self._risk_guard.max_cycle_risk_pct * 100,
                self._topn_allocator.config.max_edges_per_cycle,
                self._topn_allocator.config.min_contracts,
            )

        # Cached portfolio value (updated each cycle from positions total_cost).
        # Used by status_snapshot so it doesn't need to re-fetch positions on every poll.
        self._last_portfolio_cents: int = 0

        # Last effective equity USD (capped by max_riskable_usd, set each cycle).
        # Used for order placement portfolio risk limits. Initialize to 0 until first cycle.
        self._last_effective_equity_usd: float = 0.0

        # Per-asset spot metadata for observability
        self._last_spots: Dict[str, dict] = {}
        self._indicator_last_updated: Dict[str, float] = {}
        # Execution gate snapshot (used to keep paper rehearsal faithful).
        self._last_execution_gate: Optional[Dict[str, Any]] = None
        
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
        
        # DYNAMIC PRICING v10 (2026-04-26): Initialize real-time max price calculator
        # Uses WebSocket orderbook data (sub-200ms) for volatility-adjusted pricing
        from merid.pricing.dynamic_max_price import get_dynamic_max_price_calculator
        self._dynamic_price_calc = get_dynamic_max_price_calculator()
        self._dynamic_price_calc.set_indicator_stacks(self._indicator_stacks)
        logger.info("[DYNAMIC_PRICE] Initialized calculator for assets: %s", list(self._asset_series_map.keys()))

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

        # Market Regime Gate — crypto basket flatness filter
        try:
            self._regime_gate = get_regime_gate()
            self._regime_gate_enabled = self._regime_gate.cfg.enabled
        except Exception as _rg_exc:
            logger.warning("[REGIME-GATE-INIT-FAILED] %s — continuing without gate", _rg_exc)
            self._regime_gate = None
            self._regime_gate_enabled = False
        # Per-cycle regime state (set in _run_cycle_inner, checked before new entries)
        self._regime_block_new_entries: bool = False
        self._regime_reduce_sizing: bool = False
        self._last_regime_decision: Optional[Any] = None

        # Load RSA credentials (guarded — failure disables trading but keeps instance alive)
        kalshi_env = os.environ.get("KALSHI_ENV", "demo").lower()
        if kalshi_env == "live":
            self._base_url = os.environ.get(
                "KALSHI_API_BASE_URL",
                "https://trading-api.kalshi.com/trade-api/v2",
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
        except (ImportError, AttributeError, TypeError):
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

        # ═════════════════════════════════════════════════════════════════
        # STATE MACHINE: Trading state management (A/B/C/D)
        # ═════════════════════════════════════════════════════════════════
        self._state_machine: TradingStateMachine = get_state_machine()
        logger.info(
            "[STATE-MACHINE] Initialized | current_state=%s | hedge_target=%.0f%% | size_mult=%.0f%%",
            self._state_machine.current_state.value,
            self._state_machine.get_hedge_target_ratio() * 100,
            self._state_machine.get_position_size_multiplier() * 100,
        )

        # ═════════════════════════════════════════════════════════════════
        # HEDGE ENGINE: Exposure-based hedge computation
        # ═════════════════════════════════════════════════════════════════
        self._hedge_engine: CryptoHedgeEngine = get_hedge_engine()
        self._hedge_config = get_hedge_config()
        if self._hedge_config.enabled:
            logger.info("[HEDGE-ENGINE] Initialized | enabled=true")
        else:
            logger.warning("[HEDGE-ENGINE] Initialized | enabled=false — hedging disabled")

        # Validate unified drawdown config alignment
        _dd_issues = validate_existing_configs()
        if _dd_issues:
            for issue in _dd_issues:
                logger.warning("[DRAWDOWN-CONFIG] %s", issue)

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
                # Use live bankroll for telemetry if available, otherwise use static reference
                # Static reference may be 0 if KALSHI_TRADER_BANKROLL not set
                try:
                    from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
                    live_equity = get_equity_for_risk_calc_sync()
                    if live_equity is not None and live_equity > 0:
                        bankroll = int(live_equity * 100)
                    else:
                        bankroll = self.config.initial_bankroll_cents
                except Exception as e:
                    logger.debug("[KALSHI-CT] Failed to get live equity, using initial bankroll: %s", e)
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
        - External ID: all assets have USD spot pair mappings (Coinbase/Kraken/BinanceUS)
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

        # 2) External ID invariant: all active assets must have USD spot pair mappings
        # (Coinbase/Kraken/BinanceUS - already validated in crypto_spot_service.py)
        # This is now handled by CryptoSpotService which enforces USD-only pairs
        
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
            "assets=%s coinbase_pairs=%d/%d exposure=%d/%d series=%d/%d",
            sorted(active_assets),
            len(active_assets),
            len([a for a in active_assets if a in _cb_map]),
            len([a for a in active_assets if a in cfg.asset_max_exposure_pct]),
            len(active_assets),
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

    def _build_regime_snapshot(self, spot_prices: Dict[str, float]) -> Dict[str, Any]:
        """Build basket snapshot for MarketRegimeGate evaluation.

        Derives per-asset metrics from indicator stacks (ATR, returns, volume profile).
        Returns dict mapping asset -> metrics for gate evaluation.
        """
        snapshot: Dict[str, Any] = {}
        for asset, stack in self._indicator_stacks.items():
            try:
                snap = stack.snapshot()
                # Derive return from recent price action (vs prior close)
                current = getattr(snap, "current_price", spot_prices.get(asset, 0))
                prior = getattr(snap, "prior_close", current)
                return_pct = ((current - prior) / prior * 100) if prior and prior > 0 else 0.0

                # ATR as % of price
                atr = getattr(snap, "atr", 0.0)
                atr_pct = (atr / current * 100) if current and current > 0 else 0.0

                # Volume ratio (current vs average) — approximate from stack internals
                vol_ratio = getattr(snap, "volume_ratio", 1.0)
                if not vol_ratio or vol_ratio <= 0:
                    vol_ratio = 1.0  # neutral if unknown

                # ADX if available
                adx = getattr(snap, "adx", None)

                snapshot[asset] = {
                    "return_pct": return_pct,
                    "atr_pct": atr_pct,
                    "vol_ratio": vol_ratio,
                    "adx": adx,
                    "price": current,
                }
            except Exception as _snap_exc:
                logger.debug("[REGIME-SNAPSHOT] Failed for %s: %s", asset, _snap_exc)
                continue
        return snapshot

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
        except (ValueError, TypeError, AttributeError):
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

    # ═══════════════════════════════════════════════════════════════════════════
    # LEGACY HTTP METHODS REMOVED (Phase 3 Migration Complete)
    # ═══════════════════════════════════════════════════════════════════════════
    # The following methods were removed as part of Phase 3 migration:
    #   - _transport_failure_response() - No longer needed (no direct HTTP calls)
    #   - _get() - Replaced by canonical router via CT execution adapter
    #   - _post() - Replaced by canonical router via CT execution adapter
    #   - _delete() - Replaced by canonical router via CT execution adapter
    #
    # All orders now flow through route_order_async() in order_router.py,
    # which provides unified risk guards, dedup, pre-trade gates, and
    # caller module authorization. See: docs/security/single_execution_authority.md
    # ═══════════════════════════════════════════════════════════════════════════

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

    def _build_synthetic_rejection(
        self,
        order_data: dict,
        reason: str,
    ) -> requests.Response:
        """Build a synthetic HTTP-like rejection response (router failure path).

        Used when the canonical router path errors — we refuse to fall back
        to the legacy direct ``_post`` bypass, so downstream code sees a
        rejected-order response instead.
        """
        from requests import Response

        resp = Response()
        resp.status_code = 409  # conflict/blocked — not 2xx, not a transport failure
        order_payload = {
            "order_id": "",
            "client_order_id": order_data.get("client_order_id"),
            "status": "rejected",
            "reason": reason,
            "ticker": order_data.get("ticker"),
            "action": order_data.get("action"),
            "side": order_data.get("side"),
            "count": order_data.get("count"),
            "price": order_data.get("yes_price") or order_data.get("no_price"),
            "fill_count_fp": 0,
            "taker_fees_dollars": "0.00",
        }
        import json
        resp._content = json.dumps({"order": order_payload, "error": reason}).encode("utf-8")
        resp.headers["Content-Type"] = "application/json"
        return resp

    # ── Data helpers (all sync, called via run_in_executor) ──────────

    def _get_all_spots(self) -> Dict[str, float]:
        """Batch-fetch all crypto spot prices using unified CryptoSpotService.

        Priority (aligned with Kalshi's CFB RTI): Coinbase (primary) -> Kraken (secondary) -> BinanceUS (tertiary)
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
        if result.by_source.get("kraken"):
            logger.debug("  Spot sources - Kraken: %s", result.by_source["kraken"])
        if result.by_source.get("binanceus"):
            logger.debug("  Spot sources - BinanceUS: %s", result.by_source["binanceus"])
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
        except (ImportError, AttributeError):
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
        """Submit sell YES to close a long via canonical router. Returns True if order accepted or dry-run."""
        if qty <= 0:
            return False
        
        order_data = {
            "ticker": ticker,
            "action": "sell",
            "side": "yes",
            "count": qty,
            "type": "limit",
            "yes_price": max(1, min(99, limit_yes_cents)),
            # client_order_id generated by pre-trade gate via adapter
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
        
        # Route through canonical router (security fix: no direct HTTP)
        try:
            from merid.trading.ct_execution_adapter import get_ct_execution_adapter
            adapter = get_ct_execution_adapter()
            # BUG-FIX: Cannot use run_until_complete in thread with running loop.
            # Use run_coroutine_threadsafe to schedule on main event loop and wait.
            _main_loop = asyncio.get_event_loop()
            _future = asyncio.run_coroutine_threadsafe(
                adapter.execute_live(order_data, self._last_effective_equity_usd),
                _main_loop
            )
            # OLD-HARDWARE FIX: Increased from 30s to 60s for slow execution on weak hardware
            router_result = _future.result(timeout=60)

            if router_result.status in ("filled_live", "submitted_live"):
                fill = router_result.fill or {}
                oid = fill.get("order_id", "?")
                status = "filled" if router_result.status == "filled_live" else "submitted"
                logger.info("    EXIT %s | id=%s", status.upper(), oid)
                
                # Record via tracker/notifier
                self.tracker.record_order({
                    "order_id": oid,
                    "ticker": ticker,
                    "status": status,
                    "filled_count": fill.get("filled_count", 0),
                }, order_data["yes_price"] * qty)
                
                if self._notifier:
                    self._notifier.record_fill(
                        ticker=ticker,
                        side="yes",
                        contracts=qty,
                        price_cents=order_data["yes_price"],
                        fee_cents=0,  # Fee tracked by router
                        edge=0.0,
                        status=status,
                        order_id=oid,
                    )
                return True
            else:
                logger.warning(
                    "    EXIT FAILED via router: %s | %s",
                    router_result.status,
                    router_result.reason or "unknown"
                )
                return False
                
        except Exception as exc:
            logger.error("    EXIT FAILED (router error): %s", exc)
            return False

    def _get_balance(self) -> Tuple[int, int]:
        """Get balance from unified bankroll service.
        
        Returns (available_balance_cents, portfolio_value_cents) from cached v2 summary.
        Uses BankrollServiceV2 as single source of truth for bankroll data.
        """
        import asyncio
        from merid.event_venues.kalshi.bankroll_service_v2 import (
            get_summary_sync,
            get_bankroll_service,
        )
        
        try:
            # Get cached summary from v2 service (single source of truth)
            summary = get_summary_sync(caller_module="kalshi_continuous_trader")
            
            if summary and summary.state.name == "FRESH" and summary.available_cash_usd is not None:
                balance_cents = int(summary.available_cash_usd * 100)
                
                # Use centralized portfolio value calculation from v2 service
                portfolio_cents = 0
                try:
                    service = asyncio.run(get_bankroll_service())
                    portfolio_cents = service.get_portfolio_value_cents_sync()
                except Exception as exc:
                    logger.debug("[_get_balance] Failed to fetch portfolio value from v2 service: %s", exc)
                
                return balance_cents, portfolio_cents
            else:
                logger.error("[_get_balance] Bankroll unavailable or stale: state=%s", summary.state if summary else "None")
                return 0, 0
        except Exception as exc:
            logger.error("[_get_balance] Error fetching bankroll: %s", exc)
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

    def _reconcile_positions_with_fills_ledger(self, rest_positions: Dict[str, dict]) -> Dict[str, Any]:
        """Reconcile Kalshi REST positions with fills ledger positions.
        
        This is critical for detecting discrepancies between:
        1. Kalshi REST API positions (ground truth from exchange)
        2. Fills ledger positions (computed from fill history)
        
        When positions are manually closed outside the system, the fills ledger
        may not reflect this, leading to double-exit attempts.
        
        Args:
            rest_positions: Positions from _get_positions() (Kalshi REST)
            
        Returns:
            Dict with reconciliation results:
            - mismatches: List of tickers with divergent position sizes
            - fills_only: List of tickers in fills ledger but not in REST
            - rest_only: List of tickers in REST but not in fills ledger
        """
        result = {
            "mismatches": [],
            "fills_only": [],
            "rest_only": [],
            "status": "ok"
        }
        
        try:
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
            fills_ledger = get_fills_ledger()
            
            # Get all markets with fills
            fills_markets = fills_ledger._fills_by_market.keys()
            
            # Check for mismatches in positions
            for ticker in fills_markets:
                # Only check crypto markets
                if not any(prefix in ticker.upper() for prefix in self._asset_prefixes):
                    continue
                    
                ledger_pos = fills_ledger.compute_position_from_fills(ticker)
                ledger_contracts = ledger_pos.get("contracts", 0) if ledger_pos else 0
                rest_contracts = rest_positions.get(ticker, {}).get("qty", 0)
                
                # Check for significant divergence (>1 contract)
                if abs(ledger_contracts - rest_contracts) > 1:
                    result["mismatches"].append({
                        "ticker": ticker,
                        "rest_contracts": rest_contracts,
                        "ledger_contracts": ledger_contracts,
                        "difference": ledger_contracts - rest_contracts
                    })
                    logger.warning(
                        "[CT-RECONCILE] Position mismatch for %s: REST=%s, fills_ledger=%s",
                        ticker, rest_contracts, ledger_contracts
                    )
            
            # Check for positions in REST but not in fills ledger
            for ticker, pos_info in rest_positions.items():
                # Only check crypto markets
                if not any(prefix in ticker.upper() for prefix in self._asset_prefixes):
                    continue
                    
                if ticker not in fills_markets and pos_info.get("qty", 0) > 0:
                    result["rest_only"].append({
                        "ticker": ticker,
                        "rest_contracts": pos_info.get("qty", 0)
                    })
                    logger.warning(
                        "[CT-RECONCILE] Position %s in REST but not in fills ledger. "
                        "May be a position opened outside system.",
                        ticker
                    )
            
            if result["mismatches"] or result["rest_only"]:
                result["status"] = "mismatch"
                
        except Exception as e:
            logger.error("[CT-RECONCILE] Error reconciling positions: %s", e)
            result["status"] = "error"
            result["error"] = str(e)
        return result

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
                    # CONSERVATIVE ALIGNMENT (2026-05-10): Boost directional max_tilt
                    # from 0.05 to 0.10 to ensure prob_edge >= 0.05 with confidence >= 0.30
                    # 0.50 + (0.30 * 0.10) = 0.530 → prob_edge = 0.030 (above 0.05 gate)
                    max_tilt = Decimal(str(getattr(self.config, 'directional_max_tilt', 0.05)))
                    # Auto-boost for 15m markets to ensure micro-edge signals pass
                    _, _inferred_tf = self._infer_asset_timeframe(
                        getattr(c, "series_ticker", "") or c.ticker or ""
                    )
                    if _inferred_tf == "15m":
                        max_tilt = Decimal("0.10")  # CONSERVATIVE: Higher tilt for 5% edge gate
                    if snap.bias == "up":
                        yes_prob = Decimal("0.50") + confidence * max_tilt
                    elif snap.bias == "down":
                        yes_prob = Decimal("0.50") - confidence * max_tilt
                    
                    # DIRECTIONAL EDGE AMPLIFICATION v9: Boost prob_edge if structural signals are strong
                    prob_edge = float(abs(yes_prob - Decimal("0.50")))
                    if prob_edge < 0.05 and hasattr(snap, 'structural_score'):
                        struct_score = float(getattr(snap, 'structural_score', 0.0))
                        if struct_score > 0.6:  # Strong structural signal
                            # Boost up to meet 0.05 threshold
                            boost = min(0.025, 0.05 - prob_edge)
                            yes_prob = yes_prob + (Decimal(str(boost)) if yes_prob > Decimal("0.50") else Decimal(str(-boost)))
                            logger.debug(
                                "    directional_amp: asset=%s edge=%.4f struct=%.2f boost=%.4f → yes_prob=%s",
                                c.asset, prob_edge, struct_score, boost, yes_prob,
                            )
                    
                    logger.debug(
                        "    directional bias=%s conf=%.3f tilt=%.3f → yes_prob=%s (asset=%s)",
                        snap.bias, snap.bias_confidence, max_tilt, yes_prob, c.asset,
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
                
                # CALIBRATION FIX v8 (2026-04-26): Edge amplification for weak z-scores
                # When z is small (< 0.5), boost it based on indicator confidence and trend alignment
                # This prevents "p ≈ 0.5" lock when strikes are close to spot but structurally sound
                if abs(z) < 0.5:
                    try:
                        stack = self._indicator_stacks.get(c.asset)
                        if stack is not None:
                            snap = stack.snapshot()
                            # Amplification factors:
                            # 1. Bias confidence (0-1): how strong is the directional signal
                            # 2. Trend alignment (0/1): is price action aligned with strike direction
                            confidence = getattr(snap, 'bias_confidence', 0.0)
                            bias = getattr(snap, 'bias', 'neutral')
                            
                            # Direction alignment: positive z (strike < spot) + up bias = YES boost
                            #                     negative z (strike > spot) + down bias = YES boost
                            direction_aligned = False
                            if z < 0 and bias == 'up':   # Strike above spot, bias up = bullish for YES
                                direction_aligned = True
                            elif z > 0 and bias == 'down':  # Strike below spot, bias down = bearish for YES
                                direction_aligned = True
                            
                            # Amplification formula: boost z up to 0.3 based on confidence
                            # Max boost at confidence=1.0 when direction_aligned
                            boost = confidence * 0.3 if direction_aligned else confidence * 0.15
                            z = z + (boost if z >= 0 else -boost)
                            
                            logger.debug(
                                "    edge_amp: asset=%s z=%.3f boost=%.3f conf=%.2f aligned=%s",
                                c.asset, z, boost, confidence, direction_aligned
                            )
                    except Exception as e:
                        logger.debug("[KALSHI-CT] Failed to amplify z-score: %s", e)
                        pass  # Fall through to unamplified z
                
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
        except (ValueError, TypeError, ArithmeticError, AttributeError):
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
        except (ValueError, TypeError, ArithmeticError, AttributeError):
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

        # ═════════════════════════════════════════════════════════════════
        # PHASE 8: Integration Validator Health Check
        # ═════════════════════════════════════════════════════════════════
        try:
            from merid.safety.integration_validator import get_integration_validator
            
            _validator = get_integration_validator()
            _safety_report = _validator.run_health_check()
            
            if not _safety_report.is_safe_to_trade:
                logger.warning(
                    "  BLOCKED by IntegrationValidator: %s (status=%s)",
                    _safety_report.blocked_reason or "unknown",
                    _safety_report.overall_status.value,
                )
                return
            
            logger.debug(
                "  IntegrationValidator: status=%s, violations=%d",
                _safety_report.overall_status.value,
                len(_safety_report.active_violations),
            )
        except Exception as exc:
            logger.error(
                "  BLOCKED: IntegrationValidator check failed (%s) — fail-closed",
                exc,
                exc_info=True,
            )
            return
        
        self._cycle += 1
        cycle = self._cycle
        
        # ═════════════════════════════════════════════════════════════════
        # RESET GLOBAL RISK GUARD for new cycle
        # ═════════════════════════════════════════════════════════════════
        # This ensures the per-cycle risk accumulation starts fresh each cycle.
        self._risk_guard.reset_cycle()
        if _USE_TOPN_ALLOCATOR:
            logger.debug("[RISK-GUARD] Cycle %d: risk guard reset", cycle)
        
        try:
            from merid.event_venues.kalshi.market_catalog import get_market_catalog

            self._ua_cycle_trace["catalog_markets"] = len(get_market_catalog().get_all_markets())
        except (ImportError, AttributeError):
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
        except (AttributeError, TypeError, ValueError):
            pass

        # ═══════════════════════════════════════════════════════════════════════
        # MARKET REGIME GATE — Evaluate basket flatness before trading
        # ═══════════════════════════════════════════════════════════════════════
        _regime_decision = None
        if self._regime_gate_enabled and self._regime_gate:
            try:
                _regime_snapshot = self._build_regime_snapshot(spot_prices)
                if _regime_snapshot:
                    _regime_decision = self._regime_gate.evaluate(_regime_snapshot)
                    _regime_action = _regime_decision.action

                    # Log structured regime state
                    logger.info(
                        "[REGIME-GATE] action=%s flat=%d/%d reasons=%s shadow=%s",
                        _regime_action.value,
                        _regime_decision.flat_count,
                        _regime_decision.total_assets,
                        _regime_decision.reason_codes,
                        _regime_decision.shadow_mode,
                    )

                    # Store regime state for downstream sizing decisions
                    self._last_regime_decision = _regime_decision

                    # If BLOCK (and not shadow mode), skip trading this cycle
                    if _regime_action == RegimeAction.BLOCK and not _regime_decision.shadow_mode:
                        logger.warning(
                            "[REGIME-BLOCK] Basket too flat (%d/%d assets) — skipping new entries",
                            _regime_decision.flat_count,
                            _regime_decision.total_assets,
                        )
                        # Allow the cycle to continue for exits/position management,
                        # but set a flag that will be checked before new entries
                        self._regime_block_new_entries = True
                    else:
                        self._regime_block_new_entries = False

                    # If REDUCE, mark for position sizing reduction
                    if _regime_action == RegimeAction.REDUCE:
                        self._regime_reduce_sizing = True
                    else:
                        self._regime_reduce_sizing = False
            except Exception as _rg_eval_exc:
                logger.warning("[REGIME-GATE-EVAL-FAILED] %s — continuing without gate", _rg_eval_exc)
                self._regime_block_new_entries = False
                self._regime_reduce_sizing = False
        else:
            self._regime_block_new_entries = False
            self._regime_reduce_sizing = False

        # Feed spot prices to BTC-anchored model (auto-derives returns on 2nd+ call).
        # Include daily so alt agents on daily timeframe get proper beta estimates.
        if self._btc_anchored_model is not None:
            try:
                for tf in ("15m", "1h", "daily"):
                    self._btc_anchored_model.record_prices(spot_prices, timeframe=tf)
            except Exception as _bam_exc:
                logger.debug("BtcAnchoredMoveModel price feed failed: %s", _bam_exc)

        # ═══════════════════════════════════════════════════════════════════════════
        # 2. LIVE KALSHI BANKROLL - Single Source of Truth (v2 Unified Service)
        # ═══════════════════════════════════════════════════════════════════════════
        # ONLY source of "real money": Kalshi /portfolio/balance API via v2 service
        # No fake data, no fallbacks, no constructed values allowed
        from merid.event_venues.kalshi import get_bankroll_service, BalanceState
        
        live_equity_usd = 0.0
        raw_balance_cents = 0
        portfolio_cents = 0
        total_value_cents = 0
        _br_state = BalanceState.UNKNOWN
        
        try:
            # Use v2 unified bankroll service - async in sync context
            import asyncio
            _service = asyncio.run(get_bankroll_service())
            _summary = asyncio.run(_service.get_summary())
            _br_state = _summary.state
            
            if _summary.equity_usd is not None:
                live_equity_usd = float(_summary.equity_usd)
                raw_balance_cents = int(live_equity_usd * 100)
                portfolio_cents = raw_balance_cents  # v2 doesn't track separately
                total_value_cents = raw_balance_cents
        except Exception as _br_err:
            logger.critical(
                "[BANKROLL-HALT] Kalshi bankroll service failed: %s. "
                "HALTING cycle - cannot trade without real bankroll.",
                _br_err
            )
            if self._notifier:
                self._notifier.notify_halt(
                    f"bankroll_unavailable: {_br_err}",
                    self._cycle
                )
            return
        
        if _br_state == BalanceState.ERROR or live_equity_usd <= 0:
            # HARD HALT: Cannot trade without real bankroll from Kalshi API
            logger.critical(
                "[BANKROLL-HALT] Kalshi /portfolio/balance unavailable: state=%s. "
                "HALTING cycle - cannot trade without real bankroll.",
                _br_state.value
            )
            if self._notifier:
                self._notifier.notify_halt(
                    f"bankroll_unavailable: state={_br_state.value}",
                    self._cycle
                )
            return
        
        # Live equity from ACTUAL Kalshi API via v2 unified service
        logger.debug("[BANKROLL] state=%s equity=$%.2f", _br_state.value, live_equity_usd)

        # ═══════════════════════════════════════════════════════════════════════════
        # DYNAMIC EFFECTIVE EQUITY COMPUTATION (drawdown-scaled max_riskable)
        # ═══════════════════════════════════════════════════════════════════════════

        # Compute current drawdown from peak
        _peak_equity = self.bankroll.peak_balance_cents / 100.0
        _current_drawdown_pct = 0.0
        if _peak_equity > 0 and live_equity_usd < _peak_equity:
            _current_drawdown_pct = (_peak_equity - live_equity_usd) / _peak_equity

        # DYNAMIC max_riskable_usd: Scales down as drawdown increases
        # At 0% DD: full live equity | At 15% DD: 85% of equity | floor at 50%
        if self.config.max_riskable_usd > 0:
            # Static cap configured - use it as ceiling
            _base_max_riskable = min(live_equity_usd, self.config.max_riskable_usd)
        else:
            # No static cap - use live equity as base
            _base_max_riskable = live_equity_usd

        # Apply drawdown scaling: linear reduction from 100% to 50% as DD goes 0% → 15%
        _dd_scale_factor = max(0.5, 1.0 - (_current_drawdown_pct / 0.30))  # 30% DD = 50% scale
        _dynamic_max_riskable = _base_max_riskable * _dd_scale_factor

        effective_equity_usd = min(live_equity_usd, _dynamic_max_riskable)

        # Store for order placement (passed to router for portfolio risk limits)
        self._last_effective_equity_usd = effective_equity_usd

        # Convert back to cents for internal calculations
        effective_total_cents = int(effective_equity_usd * 100)
        effective_balance_cents = int((raw_balance_cents / 100.0) * (effective_equity_usd / max(live_equity_usd, 0.01)) * 100)

        # Log equity state with dynamic scaling transparency
        logger.info(
            "  Live: $%.2f | Peak: $%.2f | DD: %.1f%% | Dynamic cap: $%.2f (scale: %.0f%%) | Effective: $%.2f",
            live_equity_usd, _peak_equity, _current_drawdown_pct * 100,
            _dynamic_max_riskable, _dd_scale_factor * 100, effective_equity_usd
        )

        # ═══════════════════════════════════════════════════════════════════════════
        # STATE MACHINE: Evaluate and transition trading state based on drawdown
        # ═══════════════════════════════════════════════════════════════════════════
        # Update state machine with current drawdown and check for transitions
        try:
            # Get consecutive losses from bankroll tracking
            _consecutive_losses = getattr(self.bankroll, '_consecutive_losses', 0)
            
            # Evaluate state transition
            _transition = self._state_machine.evaluate_transition(
                drawdown_pct=_current_drawdown_pct,
                consecutive_losses=_consecutive_losses,
                all_positions_closed=(total_open == 0),
                liquidity_degraded=self._regime_reduce_sizing if hasattr(self, '_regime_reduce_sizing') else False,
                vol_spike=False,  # Could be derived from bankroll vol_band
            )
            
            if _transition:
                logger.warning(
                    "[STATE-TRANSITION] %s → %s | reason=%s | dd=%.2f%% | time_in_prev=%.1fs",
                    _transition.from_state.value,
                    _transition.to_state.value,
                    _transition.reason.value,
                    _transition.drawdown_pct * 100,
                    _transition.time_in_previous_state
                )
                if self._notifier:
                    self._notifier.notify_state_change(
                        from_state=_transition.from_state.value,
                        to_state=_transition.to_state.value,
                        reason=_transition.reason.value,
                        cycle=self._cycle
                    )
            
            # Log current state for observability
            logger.info(
                "[STATE-MACHINE] state=%s | hedge_target=%.0f%% | size_mult=%.0f%% | can_scalp=%s",
                self._state_machine.current_state.value,
                self._state_machine.get_hedge_target_ratio() * 100,
                self._state_machine.get_position_size_multiplier() * 100,
                self._state_machine.can_enter_new_scalp_positions()
            )
        except Exception as _sm_exc:
            logger.warning("[STATE-MACHINE] Evaluation failed (non-critical): %s", _sm_exc)

        # ═══════════════════════════════════════════════════════════════════════════
        # DYNAMIC MIN OPERATIONAL BALANCE (drawdown halt threshold)
        # ═══════════════════════════════════════════════════════════════════════════
        # min_op_balance = peak * (1 - drawdown_halt_pct) — unified with drawdown halt
        _dynamic_min_op_balance = _peak_equity * (1.0 - self.config.drawdown_halt_pct)

        if live_equity_usd < _dynamic_min_op_balance:
            logger.critical(
                "[SAFETY-HALT] Live equity $%.2f below dynamic min (peak $%.2f × (1 - %.1f%%) = $%.2f). "
                "HALTING new order placement. Existing positions maintained.",
                live_equity_usd, _peak_equity, self.config.drawdown_halt_pct * 100,
                _dynamic_min_op_balance
            )
            if self._notifier:
                self._notifier.notify_halt(
                    f"drawdown_halt: ${live_equity_usd:.2f} < ${_dynamic_min_op_balance:.2f} "
                    f"(peak ${_peak_equity:.2f}, dd {_current_drawdown_pct:.1%})",
                    self._cycle
                )
            return

        # ═══════════════════════════════════════════════════════════════════════════
        # ABSOLUTE MIN OPERATIONAL BALANCE FLOOR (live balance derived)
        # ═══════════════════════════════════════════════════════════════════════════
        # Calculate min operational balance dynamically from LIVE equity (not config).
        # Aligned with unified risk system: 1-3% of live equity (default 3% = MAX_CYCLE_RISK_PCT).
        try:
            from core.settings import MAX_CYCLE_RISK_PCT
            _default_min_op_pct = MAX_CYCLE_RISK_PCT  # 2% from unified system
        except (ImportError, AttributeError):
            _default_min_op_pct = 0.03  # 3% fallback
        _min_op_balance_pct = float(os.getenv("KALSHI_CT_MIN_OP_BALANCE_PCT", str(_default_min_op_pct)))
        _calculated_min_op_balance = live_equity_usd * _min_op_balance_pct

        # Allow explicit env override to take precedence
        _effective_min_op_balance = self.config.min_operational_balance_usd
        if _effective_min_op_balance <= 0:
            _effective_min_op_balance = _calculated_min_op_balance

        if live_equity_usd < _effective_min_op_balance:
            logger.critical(
                "[SAFETY-HALT] Live equity $%.2f below min_operational_balance floor $%.2f "
                "(%.1f%% of live equity). HALTING new order placement. Existing positions maintained.",
                live_equity_usd, _effective_min_op_balance, _min_op_balance_pct * 100
            )
            if self._notifier:
                self._notifier.notify_halt(
                    f"min_op_balance_halt: ${live_equity_usd:.2f} < ${_effective_min_op_balance:.2f}",
                    self._cycle
                )
            return

        # Recalibrate risk limits when balance moves >5% (best-effort)
        try:
            from merid.event_venues.kalshi.balance_calibrator import get_balance_calibrator
            get_balance_calibrator().update(effective_balance_cents)
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

        if effective_balance_cents < self.config.min_balance_cents:
            # effective_balance_cents=0 almost always means the API call failed (see BALANCE-FETCH-FAIL above);
            # a genuinely $0 balance would be unusual.  Logged at WARNING (retried next cycle).
            logger.warning(
                "  [BALANCE-GATE] Effective balance $%.2f below $%.2f reserve — skipping cycle "
                "(if this repeats, check API connectivity / auth)",
                effective_balance_cents / 100, self.config.min_balance_cents / 100,
            )
            return

        # 3. Existing positions - filter by asset series prefixes
        _raw_positions = self._get_positions()
        asset_positions = {k: v for k, v in _raw_positions.items()
                         if any(prefix in k.upper() for prefix in self._asset_prefixes)}
        total_open = sum(1 for v in asset_positions.values() if v["qty"] != 0)
        
        # CRITICAL: Reconcile REST positions with fills ledger to detect discrepancies
        # This prevents double-exits and ensures position consistency
        self._reconcile_positions_with_fills_ledger(_raw_positions)
        
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
                no_levels = fp.get("no_dollars", [])
                if not yes_levels and not no_levels:
                    continue
                exit_reason = None
                if pos_info["side"] == "yes":
                    current_bid = float(yes_levels[0][0]) if yes_levels and yes_levels[0] else 0
                    _profit_take_frac = self.config.yes_profit_take_cents / 100.0
                    _stop_loss_frac = self.config.yes_stop_loss_cents / 100.0
                    if current_bid >= _profit_take_frac:
                        exit_reason = "profit-take"
                        logger.info(
                            "  EXIT SIGNAL: %s YES position bid=%d¢ — profit-taking zone (threshold=%d¢)",
                            ticker, int(current_bid * 100), self.config.yes_profit_take_cents,
                        )
                    elif current_bid <= _stop_loss_frac and current_bid > 0:
                        exit_reason = "stop-loss"
                        logger.info(
                            "  EXIT SIGNAL: %s YES position bid=%d¢ — stop-loss zone (threshold=%d¢)",
                            ticker, int(current_bid * 100), self.config.yes_stop_loss_cents,
                        )
                elif pos_info["side"] == "no":
                    current_ask = float(no_levels[0][0]) if no_levels and no_levels[0] else 0
                    _profit_take_frac = self.config.no_profit_take_cents / 100.0
                    _stop_loss_frac = self.config.no_stop_loss_cents / 100.0
                    if current_ask <= _profit_take_frac:
                        exit_reason = "profit-take"
                        logger.info(
                            "  EXIT SIGNAL: %s NO position ask=%d¢ — profit-taking zone (threshold=%d¢)",
                            ticker, int(current_ask * 100), self.config.no_profit_take_cents,
                        )
                    elif current_ask >= _stop_loss_frac and current_ask < 1.0:
                        exit_reason = "stop-loss"
                        logger.info(
                            "  EXIT SIGNAL: %s NO position ask=%d¢ — stop-loss zone (threshold=%d¢)",
                            ticker, int(current_ask * 100), self.config.no_stop_loss_cents,
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
            default_max_strike_distance_pct=1.0,  # 100% = no-op, filtering moved to NearSpotSelector
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
            use_price_bands=(os.getenv("KALSHI_PRICE_BANDS_MODE", "off") != "off"),
            # DYNAMIC PRICING v10: Real-time WebSocket-driven max pricing
            dynamic_max_price_calc=getattr(self, '_dynamic_price_calc', None),
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
            if yes_levels and yes_levels[0]:
                c.best_yes_bid = float(yes_levels[0][0])
            if no_levels and no_levels[0]:
                c.best_no_bid = float(no_levels[0][0])
            if c.best_no_bid is not None:
                c.best_yes_ask = round(1.0 - c.best_no_bid, 4)
            if c.best_yes_bid is not None:
                c.best_no_ask = round(1.0 - c.best_yes_bid, 4)
            
            # DYNAMIC PRICING v10: Feed WebSocket orderbook data to calculator
            # PRO TIP: Using real-time data (not REST) for sub-200ms spread analysis
            if c.best_yes_bid is not None and c.best_yes_ask is not None:
                try:
                    bid_cents = int(c.best_yes_bid * 100)
                    ask_cents = int(c.best_yes_ask * 100)
                    self._dynamic_price_calc.update_ws_orderbook(c.ticker, bid_cents, ask_cents)
                except Exception:
                    pass  # Non-blocking - calculator has fallback logic
            
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
                except (ImportError, AttributeError, TypeError):
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

        # ═══════════════════════════════════════════════════════════════════════
        # TOP-3 SELECTION: Create candidates and compute allocations
        # ═══════════════════════════════════════════════════════════════════════
        _top3_enabled = os.getenv("TOP3_ENABLED", "true").lower() in ("true", "1", "yes")
        _top3_batch = None
        _top3_allocations: dict = {}
        
        if _top3_enabled and tradeable:
            # Build edge candidates from tradeable markets
            # Aggregate by asset, taking the best edge per asset
            _asset_best_edge: dict = {}
            _asset_candidates: dict = {}
            for c in tradeable:
                asset = c.asset or _CT_ASSET_KEY_FALLBACK
                edge = float(c.best_edge) if c.best_edge else 0.0
                if asset not in _asset_best_edge or edge > _asset_best_edge[asset]:
                    _asset_best_edge[asset] = edge
                    _asset_candidates[asset] = c
            
            # Create EdgeCandidate list
            _edge_candidates = []
            _topn_candidates = []  # For new allocator when USE_TOPN_ALLOCATOR=true
            for asset, candidate in _asset_candidates.items():
                # Compute per-asset max notional cap from config
                _asset_max_pct = self.config.asset_max_exposure_pct.get(
                    asset, self.config.asset_exposure_default_pct
                )
                _max_notional = int(balance_cents * _asset_max_pct)
                
                # Determine direction from best_side
                _direction = "long" if candidate.best_side == "yes" else "short"
                
                # For binary contracts, entry price is limit_price_cents
                _entry_price = candidate.limit_price_cents
                
                # For binary contracts, stop is at settlement boundary:
                # - Long: max loss = entry price (if settles NO at 0)
                # - Short: max loss = 100 - entry (if settles YES at 100)
                _stop_price = 0 if _direction == "long" else 100
                
                _edge_candidates.append(Top3EdgeCandidate(
                    asset=asset,
                    edge=_asset_best_edge[asset],
                    max_notional_cap=_max_notional,
                    metadata={
                        "ticker": candidate.ticker,
                        "best_side": candidate.best_side,
                        "limit_price_cents": candidate.limit_price_cents,
                    }
                ))
                
                # Build candidates for new Top-N allocator (when enabled)
                if _USE_TOPN_ALLOCATOR:
                    _topn_candidates.append(TopNEdgeCandidate(
                        asset=asset,
                        edge=_asset_best_edge[asset],
                        direction=_direction,
                        entry_price_cents=_entry_price,
                        stop_price_cents=_stop_price,
                        max_notional_cap=_max_notional,
                        metadata={
                            "ticker": candidate.ticker,
                            "best_side": candidate.best_side,
                            "timeframe": getattr(candidate, "timeframe", "15m"),
                        }
                    ))
            
            # Get batch manager and check/create batch
            _batch_mgr = get_top3_batch_manager()
            _top3_batch = _batch_mgr.get_current_batch()
            
            # Create new batch if none active
            if _top3_batch is None or _top3_batch.status != BatchStatus.ACTIVE:
                _top3_batch = _batch_mgr.maybe_create_new_batch(
                    bankroll_notional=balance_cents,
                    candidates=_edge_candidates,
                )
            
            # Build allocation lookup
            if _top3_batch:
                _top3_allocations = {
                    a.asset: a for a in _top3_batch.allocations
                }
                
                # ═══════════════════════════════════════════════════════════════════
                # TOP 1 PRIORITY EXECUTION: Always execute top edge first
                # ═══════════════════════════════════════════════════════════════════
                # The batch is created with priority sequential fill (top edge first).
                # Log explicit confirmation of TOP 1 execution priority.
                if _top3_batch.allocations and _top3_batch.allocations[0]:
                    _top1 = _top3_batch.allocations[0]  # First allocation is TOP 1
                    logger.info(
                        "[TOP1-PRIORITY] Executing TOP 1 edge first | asset=%s edge=%.4f notional=%d¢ | "
                        "Total batch: %d assets, %.2f%% of bankroll",
                        _top1.asset, _top1.edge, _top1.target_notional,
                        len(_top3_batch.allocations),
                        (_top3_batch.total_target_notional / balance_cents) * 100 if balance_cents > 0 else 0
                    )
                
                logger.info(
                    "[TOP3-BATCH] Active batch %s with %d assets: %s",
                    _top3_batch.batch_id,
                    len(_top3_batch.allocations),
                    list(_top3_allocations.keys())
                )
            else:
                logger.info("[TOP3-BATCH] No active batch (no valid allocations)")
            
            # ═════════════════════════════════════════════════════════════════
            # TOP-N ALLOCATOR (NEW) — Fixed fractional risk per cycle
            # ═════════════════════════════════════════════════════════════════
            # When USE_TOPN_ALLOCATOR=true, use the new allocator that enforces
            # 1-2% cycle-wide risk cap with max-loss-based sizing.
            # This replaces the per-trade Kelly sizing.
            #
            # CRITICAL: Use effective_total_cents (capped by max_riskable_usd) for bankroll.
            # This ensures the 1-2% risk cap is computed from the same equity used for sizing,
            # respecting the max_riskable_usd safety cap configured by the operator.
            if _USE_TOPN_ALLOCATOR and self._topn_allocator and _topn_candidates:
                # Use EFFECTIVE equity (capped) as bankroll_B per bankroll refactor spec
                # This ensures consistent risk % calculations across all risk layers.
                _bankroll_cents = effective_total_cents  # CAPPED equity, NOT raw total_value_cents
                
                # HARD GUARD: Never allow 0 or negative bankroll
                # Derive from live Kalshi balance if computed value is invalid
                if _bankroll_cents <= 0:
                    try:
                        from merid.event_venues.kalshi.order_router import _derive_live_bankroll_usd
                        _live_bankroll = _derive_live_bankroll_usd()
                        if _live_bankroll is not None and _live_bankroll > 0:
                            _bankroll_cents = int(_live_bankroll * 100)
                            logger.warning(
                                "[BANKROLL-FALLBACK] effective_total_cents=%d, using live bankroll=%d cents",
                                effective_total_cents, _bankroll_cents
                            )
                        else:
                            # FAIL CLOSED: Cannot get live bankroll - skip this cycle
                            logger.error(
                                "[BANKROLL-FAILCLOSED] Cannot determine live Kalshi balance. "
                                "Skipping cycle - no trades will be sized."
                            )
                            return
                    except Exception as _e:
                        # FAIL CLOSED: Cannot get live bankroll - skip this cycle
                        logger.error(
                            "[BANKROLL-FAILCLOSED] Failed to get live bankroll: %s. "
                            "Skipping cycle - no trades will be sized.",
                            _e
                        )
                        return

                # Log both sources for observability and verification
                if abs(effective_balance_cents - effective_total_cents) > 100:  # >$1 difference
                    logger.info(
                        "[BANKROLL-SOURCES] topn_B=$%.2f (effective equity, capped=%s), "
                        "cash_B=$%.2f (effective), portfolio=$%.2f | raw_live=$%.2f",
                        _bankroll_cents / 100,
                        "yes" if self.config.max_riskable_usd > 0 else "no",
                        effective_balance_cents / 100,
                        portfolio_cents / 100,
                        total_value_cents / 100
                    )

                _cycle = self._topn_allocator.compute_allocations(
                    equity_cents=_bankroll_cents,
                    candidates=_topn_candidates,
                    current_open_risk_usd=_current_exposure_cents / 100.0,  # Actual open risk
                )
                
                # Build lookup from asset to TradeAllocation
                _topn_allocations = {a.asset: a for a in _cycle.allocations}
                
                logger.info(
                    "[TOPN-ALLOCATOR] Cycle %s | equity=$%.2f | risk_pct=%.2f%% | "
                    "risk_budget=$%.2f | N=%d | sum_risk=$%.2f | assets=%s",
                    _cycle.cycle_id,
                    _cycle.equity_cents / 100,
                    _cycle.cycle_risk_pct * 100,
                    _cycle.cycle_risk_usd,
                    _cycle.num_edges_traded,
                    _cycle.sum_risk_usd,
                    list(_topn_allocations.keys()),
                )
                
                # Validate invariants (should always pass, but log if not)
                _is_valid, _violations = _cycle.validate_invariants()
                if not _is_valid:
                    logger.critical(
                        "[TOPN-INVARIANT-VIOLATION] Cycle %s | violations=%s",
                        _cycle.cycle_id, _violations
                    )
        else:
            logger.debug("[TOP3-BATCH] Top-3 selector disabled or no tradeable candidates")

        # LEGACY REMOVAL: Swarm consensus integration removed - consensus module deleted
        # Markets now use edge-only ranking without consensus veto

        # Re-sort after consensus adjustments (no-op since consensus removed)
        tradeable.sort(key=lambda c: c.best_edge, reverse=True)

        # [CT-TRACE] consensus
        if tradeable:
            logger.info(
                "[CT-TRACE] stage=consensus | corr_id=%s | cycle=%d | top_market=%s | top_edge=%.4f | candidates=%d | method=%s | formulas=%s | audit_spec=%s",
                correlation_id,
                cycle,
                tradeable[0].ticker if tradeable else "none",
                float(tradeable[0].best_edge) if tradeable and tradeable[0] and tradeable[0].best_edge else 0.0,
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
        # EDGE #1 PRIORITY: Track which assets have been executed this cycle for strict priority enforcement
        self._executed_this_cycle: set = set()
        # LEAK-009: per-cycle in-flight dedup set — prevents placing two orders for
        # the exact same (ticker, side) within one cycle (e.g. if the same market
        # appears in multiple overlap groups or candidate lists after filtering).
        _inflight_this_cycle: set = set()
        for c in tradeable:
            if self._shutdown or orders_placed >= self.bankroll.effective_max_orders_per_cycle():
                break

            # Stale indicator stacks must not create new entries.
            asset_key = c.asset or (self._active_assets[0] if self._active_assets else "")
            if remaining_spend <= 0:
                logger.info("[CYCLE-%d] No budget remaining after position sizing. Cycle complete.", self._cycle)
                break
            
            # Log config compliance at start of each cycle
            logger.info(
                "[CYCLE-%d-CONFIG] risk_pct=%.1f%%, max_pos=%d, max_orders=%d, kelly_frac=%.2f, exposure_mult_15m=%.2f",
                self._cycle,
                self.config.max_risk_per_trade_pct * 100,
                self.config.max_position_per_market,
                self.config.max_orders_per_cycle,
                self.config.kelly_fraction,
                self.config.series_exposure_multiplier.get("15m", 0.80)
            )
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
            
            # ═══════════════════════════════════════════════════════════════════
            # TOP-3 ENFORCEMENT GATE: Only allow assets in current batch allocation
            # ═══════════════════════════════════════════════════════════════════
            # CRITICAL: Strict Edge #1 Priority Enforcement
            # Edge #1 must ALWAYS be executed before Edge #2 or #3
            # If Edge #1 is in the batch but not yet executed, all other edges are blocked
            # ═══════════════════════════════════════════════════════════════════
            _edge1_priority_enforced = os.getenv("EDGE1_PRIORITY_STRICT", "true").lower() in ("true", "1", "yes")

            if _top3_enabled and _top3_allocations:
                if _candidate_asset not in _top3_allocations:
                    logger.info(
                        "    Skip %s: asset %s not in top-3 allocation (batch assets: %s)",
                        c.ticker, _candidate_asset, list(_top3_allocations.keys())
                    )
                    continue

                # Determine rank of this asset in the batch
                _alloc = _top3_allocations[_candidate_asset]
                _asset_rank = next(
                    (i for i, a in enumerate(_top3_batch.allocations if _top3_batch else []) if a.asset == _candidate_asset),
                    -1
                )
                _rank_label = ["TOP1", "TOP2", "TOP3"][_asset_rank] if _asset_rank >= 0 else "BATCH"

                # STRICT EDGE #1 PRIORITY CHECK
                if _edge1_priority_enforced and _asset_rank > 0:
                    # This is Edge #2 or #3 - check if Edge #1 has been executed
                    _edge1_asset = _top3_batch.allocations[0].asset if _top3_batch and _top3_batch.allocations else None
                    _edge1_executed = _edge1_asset in getattr(self, '_executed_this_cycle', set())

                    if _edge1_asset and not _edge1_executed:
                        # Edge #1 exists but hasn't been executed - BLOCK Edge #2/#3
                        logger.warning(
                            "[EDGE#1-PRIORITY-BLOCK] %s | %s blocked | Edge#1 (%s) must execute first | "
                            "rank=%d | executed_this_cycle=%s",
                            c.ticker, _rank_label, _edge1_asset, _asset_rank + 1,
                            list(getattr(self, '_executed_this_cycle', set()))
                        )
                        continue

                logger.info(
                    "[%s-EXECUTE] %s | asset=%s edge=%.4f target=%d¢ weight=%.1f%% | priority=%d/%d",
                    _rank_label, c.ticker, _candidate_asset, _alloc.edge,
                    _alloc.target_notional, _alloc.weight * 100,
                    _asset_rank + 1, len(_top3_allocations)
                )
            
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
                    raise RuntimeError(f"Unexpected low-edge candidate slipped through: {c.ticker}")
                
                # Assert: distance must be within allowed band
                if _assert_distance_pct > _assert_max_dist_pct + 0.001:  # epsilon = 0.1%
                    logger.error(
                        "ASSERT FAIL: distance %.2f%% > max %.2f%% for %s (wiring regression)",
                        _assert_distance_pct * 100, _assert_max_dist_pct * 100, c.ticker
                    )
                    raise RuntimeError(f"Far OTM candidate slipped through: {c.ticker}")

            _pos_info = asset_positions.get(
                c.ticker, {"qty": 0, "side": "", "avg_price_cents": 0},
            )
            existing = _pos_info["qty"]

            # ═══════════════════════════════════════════════════════════════════════
            # POSITION SIZING: Kelly (legacy) vs Top-N Allocator (new)
            # ═══════════════════════════════════════════════════════════════════════
            if _USE_TOPN_ALLOCATOR and _topn_allocations and _candidate_asset in _topn_allocations:
                # Use new Top-N allocator output (max-loss-based sizing)
                _tn_alloc = _topn_allocations[_candidate_asset]
                order_count = _tn_alloc.target_contracts
                
                # Verify ticker matches (should always match, but safety check)
                if _tn_alloc.metadata.get("ticker") != c.ticker:
                    logger.warning(
                        "[TOPN-MISMATCH] Asset %s ticker mismatch: allocation=%s vs candidate=%s",
                        _candidate_asset, _tn_alloc.metadata.get("ticker"), c.ticker
                    )
                
                logger.info(
                    "[TOPN-SIZE] %s | asset=%s | contracts=%d | max_loss=$%.2f | "
                    "allocated_risk=$%.2f | edge=%.4f",
                    c.ticker, _candidate_asset, order_count,
                    _tn_alloc.max_loss_usd, _tn_alloc.risk_budget_usd, _tn_alloc.edge
                )
            else:
                # Legacy: BankrollManager Kelly sizing (per-trade risk)
                if _USE_TOPN_ALLOCATOR:
                    logger.debug(
                        "[TOPN-SKIP] %s | asset=%s not in top-n allocations, skipping",
                        c.ticker, _candidate_asset
                    )
                    continue
                
                order_count = self.bankroll.calculate_order_size(
                    balance_cents=effective_balance_cents,
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

            # ═══════════════════════════════════════════════════════════════════════
            # MARKET REGIME GATE — Reduce position size when basket shows low activity
            # ═══════════════════════════════════════════════════════════════════════
            if self._regime_reduce_sizing and order_count > 1:
                _reduced = max(1, order_count // 2)
                logger.info(
                    "[REGIME-REDUCE] %s | contracts: %d -> %d (50%% reduction for low-activity regime)",
                    c.ticker, order_count, _reduced,
                )
                order_count = _reduced

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
                    bankroll_cents=effective_balance_cents,
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
            if cost_cents + 1 > effective_balance_cents:
                logger.debug("    Skip %s: can't afford %d¢", c.ticker, cost_cents)
                continue
            # BUG-F3 fix: per-cycle spend cap
            if _cycle_spent + cost_cents > _max_cycle_spend:
                logger.info("    Skip %s: cycle spend cap reached (%d¢ + %d¢ > %d¢)",
                            c.ticker, _cycle_spent, cost_cents, _max_cycle_spend)
                break
            # Stage 1–2 — per-asset cap first, then global (see ``evaluate_entry_exposure_skip``).
            _global_cap_cents = int(effective_balance_cents * self.config.global_max_exposure_pct)
            _asset_max_pct = self.config.asset_max_exposure_pct.get(
                _candidate_asset, self.config.asset_exposure_default_pct
            )
            _series_mult = self.config.series_exposure_multiplier.get(_candidate_tf, 1.0)
            _asset_cap_cents = max(
                self.config.min_asset_cap_cents,
                int(effective_balance_cents * _asset_max_pct * _series_mult),
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
                _candidate_tf, effective_balance_cents, _global_cap_cents, _asset_cap_cents, _asset_current,
                _asset_max_pct * 100, _series_mult
            )
            _exp_skip = self.evaluate_entry_exposure_skip(
                effective_balance_cents,
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

            # ═══════════════════════════════════════════════════════════════════════
            # MARKET REGIME GATE — Block new entries when basket is flat
            # ═══════════════════════════════════════════════════════════════════════
            if self._regime_block_new_entries:
                logger.warning(
                    "  [REGIME-BLOCK-ORDER] Skip %s: market regime gate BLOCK (basket too flat)",
                    c.ticker,
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
            # FILLS LEDGER POSITION VALIDATION — Prevent double-entries
            # Check if we already have a position in this ticker according to fills ledger
            # This prevents double-entries when there's a delay in fill ingestion
            # ═══════════════════════════════════════════════════════════════════════
            try:
                from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
                fills_ledger = get_fills_ledger()
                ledger_pos = fills_ledger.compute_position_from_fills(c.ticker)
                ledger_contracts = ledger_pos.get("contracts", 0) if ledger_pos else 0
                
                if ledger_contracts > 0:
                    logger.warning(
                        "[CT-ENTRY-SKIP] %s: Fills ledger shows %d contracts already. "
                        "Skipping entry to prevent double-position.",
                        c.ticker, ledger_contracts
                    )
                    continue
            except Exception as e:
                logger.debug("[CT-ENTRY] Could not validate fills ledger position for %s: %s", c.ticker, e)

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

            # ═══════════════════════════════════════════════════════════════════════
            # GLOBAL RISK GUARD — Last-line defense before order submission
            # ═══════════════════════════════════════════════════════════════════════
            # This enforces hard 1-2% per-cycle risk cap. No orders may bypass this.
            # Compute max loss for this order
            _direction = "long" if c.best_side == "yes" else "short"
            if _direction == "long":
                _max_loss_cents = order_count * c.limit_price_cents
            else:
                _max_loss_cents = order_count * (100 - c.limit_price_cents)
            
            _pending_order = PendingOrderRisk(
                ticker=c.ticker,
                asset=_candidate_asset,
                contracts=order_count,
                entry_price_cents=c.limit_price_cents,
                direction=_direction,
                max_loss_cents=_max_loss_cents,
                edge=float(c.best_edge) if c.best_edge else 0.0,
            )
            
            # ═════════════════════════════════════════════════════════════════
            # PHASE 7: Q-Inline Policy Evaluation
            # ═════════════════════════════════════════════════════════════════
            try:
                from merid.policy.qinline_policy import get_qinline_policy
                
                _policy = get_qinline_policy()
                
                # Compute mid price from orderbook (best_yes_bid/ask are probabilities 0-1)
                _mid_cents = c.limit_price_cents  # Use limit price as mid proxy
                if hasattr(c, 'best_yes_bid') and hasattr(c, 'best_yes_ask'):
                    _bid = int((c.best_yes_bid or 0) * 100)
                    _ask = int((c.best_yes_ask or 0) * 100)
                    # Validate: bid must be positive and ask >= bid for valid market
                    if _bid > 0 and _ask >= _bid:
                        _mid_cents = (_bid + _ask) // 2
                
                # Get current position for this ticker
                _current_pos = 0
                if hasattr(self, 'cache') and self.cache is not None:
                    _current_pos = self.cache.get_position_contracts(c.ticker)
                
                # Get remaining risk budget (default to conservative 100% if unavailable)
                _remaining_risk = 1.0
                if hasattr(self, '_risk_guard') and self._risk_guard is not None:
                    if hasattr(self._risk_guard, 'get_remaining_budget_pct'):
                        _remaining_risk = self._risk_guard.get_remaining_budget_pct()
                
                # Evaluate policy
                _policy_decision = _policy.evaluate(
                    ticker=c.ticker,
                    mid_price_cents=_mid_cents,
                    current_position=_current_pos,
                    remaining_risk_budget_pct=_remaining_risk,
                )
                
                # Log policy decision
                logger.debug(
                    "  Q-Inline Policy: %s %s (conf=%.2f, urgency=%s, contracts=%d, regime_mult=%.2f)",
                    c.ticker,
                    _policy_decision.decision.value,
                    _policy_decision.confidence,
                    _policy_decision.urgency.value,
                    _policy_decision.target_contracts,
                    _policy_decision.regime_multiplier,
                )
                
                # Check if policy blocks execution
                if not _policy_decision.should_execute:
                    logger.info(
                        "  [POLICY-VETO] %s: decision=%s (confidence=%.2f, macro=%.2f, momentum=%.2f, btc=%.2f)",
                        c.ticker,
                        _policy_decision.decision.value,
                        _policy_decision.confidence,
                        _policy_decision.macro_contribution,
                        _policy_decision.momentum_contribution,
                        _policy_decision.btc_anchor_contribution,
                    )
                    continue  # Skip this candidate
                
                # Use policy-adjusted sizing (respects both increases and decreases)
                if _policy_decision.target_contracts > 0:
                    if _policy_decision.target_contracts != order_count:
                        logger.debug(
                            "  [POLICY-SIZE] %s: Kelly=%d → Policy=%d (regime_mult=%.2f)",
                            c.ticker,
                            order_count,
                            _policy_decision.target_contracts,
                            _policy_decision.regime_multiplier,
                        )
                    order_count = _policy_decision.target_contracts
                    
            except Exception as exc:
                logger.error(
                    "  [POLICY-FAIL] %s: Q-Inline evaluation failed (%s) — skipping candidate",
                    c.ticker,
                    exc,
                    exc_info=True,
                )
                continue  # Skip candidate if policy evaluation fails
            
            # Calculate existing open risk (simplified: cost basis of open positions)
            _existing_risk_cents = _current_exposure_cents  # From earlier in the loop

            # CRITICAL: Use EFFECTIVE total equity (capped by max_riskable_usd) for guard check
            # This ensures the 1-2% per-cycle risk cap is computed from the same equity
            # used for sizing, not the raw live balance which might exceed max_riskable_usd.
            _guard_equity_cents = effective_total_cents  # NOT total_value_cents (raw)

            _guard_allowed, _guard_reason = self._risk_guard.check_order(
                equity_cents=_guard_equity_cents,
                existing_risk_cents=_existing_risk_cents,
                pending_order=_pending_order,
            )
            
            if not _guard_allowed:
                logger.critical(
                    "[GLOBAL-RISK-GUARD] BLOCKED | %s | reason=%s | "
                    "This order would exceed the 1-2%% per-cycle risk cap. "
                    "Skipping and logging for audit.",
                    c.ticker, _guard_reason
                )
                continue  # Skip this order - don't submit
            
            # GUARD CHECK: Observation mode - log what we would do but don't execute
            if self._guardian and self._guardian.checklist.mode == TradingMode.OBSERVATION:
                logger.info(
                    "[OBSERVATION-MODE] Would place order: %s %dx %s @ %d¢ edge=%.4f | "
                    "conviction_components would be logged here",
                    c.best_side.upper(), order_count,
                    c.ticker, c.limit_price_cents, c.best_edge
                )
                orders_placed += 1  # Count as "placed" for metrics
                # EDGE #1 PRIORITY: Track for observation mode as well
                self._executed_this_cycle.add(_candidate_asset)
                continue  # Skip actual execution

            if self.config.dry_run:
                logger.info("    [DRY RUN] %s", json.dumps(order_data))
                self.bankroll.record_trade_direction(c.ticker, c.best_side, float(c.best_edge))
                orders_placed += 1
                # EDGE #1 PRIORITY: Track for dry-run mode
                self._executed_this_cycle.add(_candidate_asset)
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

            # Phase 3 (canonical): All orders flow through route_order_async
            # via the CT execution adapter. Shared GlobalRiskGuard, dedup,
            # pre-trade gate, sanity checks, caller audit all apply.
            # SECURITY: Direct HTTP bypass has been permanently removed.
            try:
                adapter = get_ct_execution_adapter()
                # BUG-FIX: Cannot use run_until_complete in thread with running loop.
                # Use run_coroutine_threadsafe to schedule on main event loop and wait.
                _main_loop = asyncio.get_event_loop()
                _future = asyncio.run_coroutine_threadsafe(
                    adapter.execute_live(order_data, self._last_effective_equity_usd),
                    _main_loop
                )
                # OLD-HARDWARE FIX: Increased from 30s to 60s for slow execution on weak hardware
                router_result = _future.result(timeout=60)
                resp = self._build_synthetic_response(router_result, order_data)
                logger.info(
                    "[CT-CANONICAL] Routed via canonical router | ticker=%s | status=%s",
                    c.ticker, router_result.status,
                )
            except Exception as _router_exc:
                logger.error(
                    "[CT-CANONICAL] Router execution FAILED (terminal, no HTTP fallback): %s",
                    _router_exc,
                )
                # Synthesize a rejected response; no direct venue submit.
                resp = self._build_synthetic_rejection(order_data, f"router_error:{_router_exc}")

            # Note: Shadow mode removed. All orders flow through canonical router.
            # The use_router_percent field is hard-coded to 100 (Phase 3 canonical chokepoint).

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
                
                # Update pre-trade gate: submitted → filled.
                # When routing through the canonical router the gate is already
                # advanced internally (route_order_async -> mark_submitted +
                # mark_filled using intent.client_tag), so this block is a
                # best-effort idempotent no-op for the legacy HTTP path.
                # Warn-level logging here so silent leaks don't recur.
                try:
                    from merid.event_venues.kalshi.order_gate import get_pre_trade_gate as _get_ptg
                    _ptg = _get_ptg()
                    _ptg.mark_submitted(_ct_coid, oid if oid != "?" else None)
                    _ct_fill_n = int(float(fill)) if fill else 0
                    if _ct_fill_n > 0:
                        _ptg.mark_filled(_ct_coid, _ct_fill_n)
                except Exception as _gate_update_exc:
                    logger.warning(
                        "[CT] pre_trade_gate update failed coid=%s: %s",
                        (_ct_coid or "")[:16], _gate_update_exc,
                    )

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
                
                # ═══════════════════════════════════════════════════════════════════
                # TOP-3 BATCH TRACKING: Mark asset as filled in current batch
                # ═══════════════════════════════════════════════════════════════════
                if _top3_enabled and _top3_batch:
                    try:
                        _batch_mgr = get_top3_batch_manager()
                        _batch_mgr.mark_asset_filled(_top3_batch.batch_id, _candidate_asset, cost_cents)
                    except Exception as _top3_exc:
                        logger.debug("[TOP3-BATCH] Mark filled tracking skipped: %s", _top3_exc)
                
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
                # EDGE #1 PRIORITY: Track this asset as executed for strict priority enforcement
                self._executed_this_cycle.add(_candidate_asset)
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
        # Enhanced with state machine integration for SCALP+HEDGE mode
        try:
            from merid.hedging.engine import get_hedge_engine
            from merid.hedging.config import get_hedge_config
            from merid.hedging.exposure import build_exposure_snapshot

            # Check state machine to determine if hedging should be active
            _current_state = self._state_machine.current_state
            _hedge_target_ratio = self._state_machine.get_hedge_target_ratio()
            _can_maintain_hedge = self._state_machine.can_maintain_hedges()

            # Only proceed if hedging is enabled and state allows it
            if _can_maintain_hedge and _hedge_target_ratio > 0:
                _hcfg = get_hedge_config()
                if _hcfg.enabled:
                    # Build exposure snapshot from current positions
                    _h_snap = build_exposure_snapshot()
                    _h_engine = get_hedge_engine()

                    # Compute hedge orders with state-machine adjusted ratio
                    # Scale hedge ratio by state (50% for SCALP+HEDGE, 100% for HEDGE-ONLY)
                    _state_adjusted_ratio = _hedge_target_ratio  # Already scaled by state machine

                    _h_result = _h_engine.compute_hedge_orders(
                        exposure=_h_snap,
                        config=_hcfg,
                        bankroll_cents=total_value_cents,
                        # The engine uses target_hedge_ratio from config, 
                        # but we can adjust via a custom config instance if needed
                    )

                    if _h_result.orders:
                        logger.info(
                            "[HEDGE-PASS] cycle=%d state=%s hedge_ratio=%.0f%% generated %d hedge orders",
                            self._cycle, _current_state.value, _hedge_target_ratio * 100,
                            len(_h_result.orders),
                        )

                        # Execute hedge orders through canonical router
                        for ho in _h_result.orders:
                            if not ho.target_ticker:
                                continue

                            logger.info(
                                "[HEDGE-ORDER] asset=%s tf=%s side=%s count=%d price=%d¢ reason=%s ticker=%s",
                                ho.asset, ho.timeframe, ho.side, ho.count,
                                ho.price_cents, ho.hedge_reason, ho.target_ticker,
                            )

                            # Build hedge order data for router
                            _hedge_order_data = {
                                "ticker": ho.target_ticker,
                                "action": "buy",
                                "side": ho.side,
                                "count": ho.count,
                                "type": "limit",
                                f"{ho.side}_price": ho.price_cents,
                                "client_order_id": f"HEDGE_{ho.hedge_reason}_{uuid.uuid4().hex[:8]}",
                                "source": "HEDGE_ENGINE",
                                "strategy_group": "hedge",
                            }

                            # Route hedge order through canonical router
                            try:
                                _h_adapter = get_ct_execution_adapter()
                                _h_loop = asyncio.get_event_loop()
                                _h_future = asyncio.run_coroutine_threadsafe(
                                    _h_adapter.execute_live(_hedge_order_data, self._last_effective_equity_usd),
                                    _h_loop
                                )
                                _h_result_resp = _h_future.result(timeout=60)

                                if _h_result_resp.status == "filled_live" or _h_result_resp.status == "filled_resting":
                                    logger.info(
                                        "[HEDGE-EXECUTED] ticker=%s side=%s count=%d price=%d¢ status=%s",
                                        ho.target_ticker, ho.side, ho.count,
                                        ho.price_cents, _h_result_resp.status
                                    )
                                else:
                                    logger.warning(
                                        "[HEDGE-FAILED] ticker=%s status=%s reason=%s",
                                        ho.target_ticker, _h_result_resp.status,
                                        _h_result_resp.reason or "unknown"
                                    )
                            except Exception as _h_exec_exc:
                                logger.error(
                                    "[HEDGE-EXEC-ERROR] ticker=%s error=%s",
                                    ho.target_ticker, _h_exec_exc
                                )
                    else:
                        logger.debug(
                            "[HEDGE-PASS] cycle=%d state=%s no hedge orders needed (exposure within limits)",
                            self._cycle, _current_state.value
                        )
                else:
                    logger.debug("[HEDGE-PASS] hedging disabled in config")
            else:
                logger.debug(
                    "[HEDGE-PASS] cycle=%d state=%s hedge_target=%.0f%% — hedging not active",
                    self._cycle, _current_state.value, _hedge_target_ratio * 100
                )

        except Exception as _hedge_exc:
            logger.warning("[HEDGE-PASS] hedge pass failed: %s", _hedge_exc, exc_info=True)

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
                        "Coinbase + Kraken + BinanceUS all failed — "
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
        # CT-specific reconciler removed - using portfolio reconciliation system instead.
        try:
            from merid.event_venues.kalshi.portfolio_reconciliation import get_portfolio_reconciliation_engine
            reconciler = get_portfolio_reconciliation_engine()
            if reconciler:
                reconciler.reconcile_once()
        except Exception as _rec_exc:
            logger.debug("portfolio_reconcile skipped: %s", _rec_exc)

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

    # ── Hedge auto-exit loop ─────────────────────────────────────────

    def _build_hedge_price_provider(self):
        """Build a callable that returns {asset: price_cents} from KalshiMarketStateStore.

        Returns a closure suitable for `CryptoHedgeEngine.run_auto_exit_loop`.
        Resolves a representative ticker per asset via ``kalshi_ticker_to_asset``
        and reads the latest mid_cents from ``KalshiMarketStateStore``.
        """
        from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS, kalshi_ticker_to_asset

        def _resolve_price_cents(state) -> int:
            """Resolve a usable price for a market state, with REST fallback.

            P2 Task 9: Order of preference:
              1. WS-derived mid_cents (when book_initialized)
              2. Average of best_bid_cents and best_ask_cents if both present
              3. Single side if only one is present
              4. 0 if no source has a valid price (caller skips the asset)
            """
            mid = getattr(state, "mid_cents", 0) or 0
            if 1 <= mid <= 99:
                return int(mid)
            bid = getattr(state, "best_bid_cents", None)
            ask = getattr(state, "best_ask_cents", None)
            if isinstance(bid, int) and isinstance(ask, int) and 1 <= bid <= 99 and 1 <= ask <= 99:
                return int((bid + ask) / 2)
            if isinstance(bid, int) and 1 <= bid <= 99:
                return int(bid)
            if isinstance(ask, int) and 1 <= ask <= 99:
                return int(ask)
            return 0

        def _provider() -> Dict[str, int]:
            prices: Dict[str, int] = {}
            try:
                from merid.event_venues.kalshi.market_state import (
                    get_kalshi_market_state_store,
                )
                store = get_kalshi_market_state_store()
                # Iterate over all known states and bucket by asset; pick the most
                # recently-updated state per asset to use as the reference price.
                # Track both WS book and REST update timestamps so REST-only assets
                # still surface a price when WS is degraded.
                latest_per_asset: Dict[str, tuple] = {}  # asset -> (last_update, price_cents)
                for ticker, state in store.get_all().items():
                    asset = kalshi_ticker_to_asset(ticker)
                    if asset not in ACTIVE_CRYPTO_ASSETS:
                        continue
                    p = _resolve_price_cents(state)
                    if p <= 0:
                        continue
                    last_book = getattr(state, "last_book_update_ts", 0.0) or 0.0
                    last_rest = getattr(state, "last_rest_update_ts", 0.0) or 0.0
                    last_ts = max(last_book, last_rest)
                    cur = latest_per_asset.get(asset)
                    if cur is None or last_ts > cur[0]:
                        latest_per_asset[asset] = (last_ts, int(p))
                for asset, (_ts, p) in latest_per_asset.items():
                    prices[asset] = p
            except Exception as exc:
                logger.debug("[HEDGE-AUTO-EXIT] price provider error: %s", exc)
            return prices

        return _provider

    async def _run_hedge_auto_exit_loop(self) -> None:
        """Background task: drive CryptoHedgeEngine.run_auto_exit_loop.

        Pulls hedge config + price provider and delegates the actual TP / SL /
        max-hold-time monitoring to the hedge engine. Restart-safe: any
        exception is logged and the loop sleeps then retries.
        """
        try:
            from merid.hedging.config import get_hedge_config
            from merid.hedging.engine import get_hedge_engine
        except Exception as imp_exc:
            logger.warning("[HEDGE-AUTO-EXIT] hedge modules unavailable: %s", imp_exc)
            return

        cfg = get_hedge_config()
        if not cfg.enabled or not cfg.auto_exit.enabled:
            logger.info(
                "[HEDGE-AUTO-EXIT] auto-exit disabled (hedge.enabled=%s, auto_exit.enabled=%s)",
                cfg.enabled, cfg.auto_exit.enabled,
            )
            return

        engine = get_hedge_engine()
        provider = self._build_hedge_price_provider()
        # Poll every 5s by default — short enough to react to TP/SL on 15m markets
        # while keeping load on KalshiMarketStateStore minimal.
        interval_s = float(os.getenv("MERID_HEDGE_AUTO_EXIT_INTERVAL_S", "5"))

        # P1 Task 6: Spawn a sibling task that periodically persists the
        # HedgePnLTracker so a process restart can rehydrate hedge state
        # rather than losing all in-flight TP/SL coverage.
        persist_task = asyncio.create_task(
            self._persist_hedge_pnl_periodic(),
            name="hedge_pnl_persist_loop",
        )

        try:
            await engine.run_auto_exit_loop(
                config=cfg,
                price_provider=provider,
                interval_seconds=interval_s,
            )
        except asyncio.CancelledError:
            logger.info("[HEDGE-AUTO-EXIT] cancelled (clean shutdown)")
            raise
        except Exception as exc:
            logger.error("[HEDGE-AUTO-EXIT] loop crashed: %s", exc, exc_info=True)
        finally:
            persist_task.cancel()
            try:
                await persist_task
            except (asyncio.CancelledError, Exception):
                pass
            # Final flush so we don't lose work on graceful shutdown
            try:
                from merid.hedging.pnl_tracker import persist_hedge_pnl_tracker
                persist_hedge_pnl_tracker()
            except Exception as flush_exc:
                logger.debug("[HEDGE-PNL-PERSIST] final flush failed: %s", flush_exc)

    async def _persist_hedge_pnl_periodic(self) -> None:
        """Periodically save HedgePnLTracker state so restarts don't lose hedges."""
        from merid.hedging.pnl_tracker import persist_hedge_pnl_tracker

        interval_s = float(os.getenv("MERID_HEDGE_PNL_PERSIST_INTERVAL_S", "60"))
        while True:
            try:
                await asyncio.sleep(interval_s)
                persist_hedge_pnl_tracker()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.debug("[HEDGE-PNL-PERSIST] periodic save error: %s", exc)

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

        # Start the hedge auto-exit loop (TP / SL / max-hold) as a background task.
        # Reads live market mid-prices from KalshiMarketStateStore and submits exits
        # via route_order_async when configured TP/SL thresholds hit.
        try:
            self._auto_exit_task = asyncio.create_task(
                self._run_hedge_auto_exit_loop(),
                name="hedge_auto_exit_loop",
            )
            logger.info("[HEDGE-AUTO-EXIT] background TP/SL/max-hold loop started")
        except Exception as _ae_exc:
            logger.warning("[HEDGE-AUTO-EXIT] failed to start auto-exit loop: %s", _ae_exc)
        
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

        # Cancel hedge auto-exit loop cleanly on shutdown
        if self._auto_exit_task and not self._auto_exit_task.done():
            self._auto_exit_task.cancel()
            try:
                await self._auto_exit_task
            except (asyncio.CancelledError, Exception) as _ae_cancel:
                logger.debug("[HEDGE-AUTO-EXIT] task cancelled: %s", _ae_cancel)
        self._auto_exit_task = None

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

        # Compute effective equity (with max_riskable_usd cap applied)
        live_equity_usd = total / 100.0
        if cfg.max_riskable_usd > 0:
            effective_equity_usd = min(live_equity_usd, cfg.max_riskable_usd)
        else:
            effective_equity_usd = live_equity_usd
        effective_total_cents = int(effective_equity_usd * 100)

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
            # Bankroll — raw Kalshi balance (for reference)
            "balance_cents": bal,
            "portfolio_cents": port,
            "total_value_cents": total,
            # Effective equity — what we're actually trading with (capped)
            "live_equity_usd": live_equity_usd,
            "max_riskable_usd": cfg.max_riskable_usd,
            "effective_equity_usd": effective_equity_usd,
            "effective_total_cents": effective_total_cents,
            "min_operational_balance_usd": cfg.min_operational_balance_usd,
            "equity_cap_active": cfg.max_riskable_usd > 0 and live_equity_usd > cfg.max_riskable_usd,
            # Peak, drawdown, halt state (computed from effective equity in cycle loop)
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
                "max_riskable_usd": cfg.max_riskable_usd,
                "min_operational_balance_usd": cfg.min_operational_balance_usd,
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
        return not self._shutdown and self._task is not None

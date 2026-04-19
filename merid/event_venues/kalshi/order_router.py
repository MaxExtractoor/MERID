"""Kalshi Order Router — Mode-aware order dispatch (mock/paper/live).

Routes ``OrderIntent`` through risk checks and dispatches to the
appropriate execution path based on ``TradingMode``.

Usage::

    from merid.event_venues.kalshi.order_router import (
        OrderIntent, OrderResult, route_order,
    )

    intent = OrderIntent(
        ticker="KXBTCD-25JUN-T100000",
        side="yes",
        action="buy",
        price_cents=55,
        count=10,
    )
    result = route_order(intent)
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import random
import time
from dataclasses import dataclass, field, replace as _dc_replace
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from merid.prediction.venue_gate import TradingMode, get_venue_gate
from trading.trade_mode import get_trade_mode
from utils.logger import get_logger
from merid.event_venues.kalshi.market_filter import (
    generate_group_id,
    extract_asset_from_ticker,
    _normalize_timeframe,
    group_id_from_ticker,
    get_series_timeframe_bucket,
)
from merid.event_venues.kalshi.ticker_utils import is_valid_kalshi_ticker

logger = get_logger("merid.event_venues.kalshi.order_router")

# ═══════════════════════════════════════════════════════════════════════════
# Agent Wiring Audit — Caller Module Tracking (AGENT_WIRING_AUDIT.md)
# ═══════════════════════════════════════════════════════════════════════════

# Whitelist of modules allowed to call route_order_async()
_ALLOWED_CALLER_PREFIXES = (
    "merid.prediction.kalshi_tools",
    "merid.prediction.trading_agent",
    "tests.",
    "test_",
    "merid.event_venues.kalshi.order_router",  # self
    # Package init re-exports
    "merid.event_venues.kalshi",
    "merid.kalshi",
    # Legitimate production callers
    "core.constitution_enforcer",  # Governance/risk enforcement
    "merid.event_venues.kalshi.execution_audit",
    "merid.event_venues.kalshi.maker_taker_policy",
    "merid.event_venues.kalshi.take_profit",
    "merid.event_venues.kalshi.universe",
    "merid.lanes.btc15m_lane",
    "merid.prediction.universal_agent",
    "web.api.kalshi_api",  # API endpoints
    "web.api.kalshi_grid_api",
    # Test modules that legitimately test the router
    "core.test_kalshi_gate_truth_table",
    "event_venues.kalshi.test_kalshi_sprint_a",
    "event_venues.kalshi.test_kalshi_universe",
    "kalshi.test_kalshi_paper_trading_e2e",
    "kalshi.test_kalshi_stress_scenarios",
    "kalshi.test_signal_to_order_pipeline",
    "prediction.test_kalshi_tools_order_intent",
    "trading.test_lifecycle_bug_regressions",
    "web.test_kalshi_place_order_router_only",
    "test_order_router_caller_restrictions",  # this test file
)

# Known bypasses documented in AGENT_WIRING_AUDIT.md
_KNOWN_BYPASS_PATHS = {
    "merid.trading.kalshi_continuous_trader",  # Uses direct HTTP; tracked for migration
}


def _get_caller_module() -> str:
    """Return the calling module name (first non-router caller in stack)."""
    import inspect
    import sys

    frame = inspect.currentframe()
    try:
        # Walk up stack to find first caller outside this module
        for f in inspect.getouterframes(frame):
            mod = inspect.getmodule(f.frame)
            if mod is None:
                continue
            mod_name = mod.__name__
            # Skip router internals
            if mod_name.startswith("merid.event_venues.kalshi.order_router"):
                continue
            # Skip asyncio internals (asyncio.run wraps callers)
            if mod_name.startswith(("asyncio", "_asyncio")):
                continue
            return mod_name
    finally:
        del frame
    return "unknown"


def _is_authorized_caller(caller_module: str) -> bool:
    """Check if caller is in the authorized whitelist or known bypass set."""
    if caller_module in _KNOWN_BYPASS_PATHS:
        return True  # Known, documented bypass
    if any(caller_module.startswith(p) for p in _ALLOWED_CALLER_PREFIXES):
        return True
    return False


PAPER_SLIPPAGE_BPS = float(os.getenv("MERID_KALSHI_PAPER_SLIPPAGE_BPS", "8.0"))
PAPER_PARTIAL_FILL_PROB = float(os.getenv("MERID_KALSHI_PAPER_PARTIAL_FILL_PROB", "0.35"))
PAPER_MIN_FILL_RATIO = float(os.getenv("MERID_KALSHI_PAPER_MIN_FILL_RATIO", "0.4"))

# ── WS / event bus channel constants ──────────────────────────────────────

KALSHI_CHANNEL_PRICE = "kalshi:price_update"
KALSHI_CHANNEL_TRADE = "kalshi:trade"
KALSHI_CHANNEL_ORDERBOOK = "kalshi:orderbook_delta"
KALSHI_CHANNEL_ORDER_FILL = "kalshi:order_fill"
KALSHI_CHANNEL_ORDER_REJECT = "kalshi:order_reject"
KALSHI_CHANNEL_ORDER_GROUP_TRIGGERED = "kalshi:order_group_triggered"


# ── Order Group Auto-Cancel Handler ─────────────────────────────────────

async def handle_order_group_triggered(group_id: str, group_data: Dict[str, Any]) -> Dict[str, Any]:
    """Handle order group triggered event - cancel all orders in the group.

    Called when WebSocket receives a triggered status for an order group.
    Fetches all open orders in the group and cancels them.

    Args:
        group_id: The order group ID that was triggered
        group_data: Full group data from the WebSocket message

    Returns:
        Dict with canceled order IDs and status
    """
    from merid.event_venues.kalshi.client import get_kalshi_client

    logger.info(f"[order-router] Order group {group_id} triggered - initiating auto-cancel (normal operation)")

    client = get_kalshi_client()
    if not client:
        return {"error": "Kalshi client not available", "canceled": []}

    try:
        await client.connect()

        # Get all open orders
        result = await client.get_open_orders_result()
        if not result.success:
            return {"error": str(result.error), "canceled": []}

        all_orders = result.data or []

        # Filter orders by group_id
        group_orders = [
            o for o in all_orders
            if o.get("order_group_id") == group_id or o.get("group_id") == group_id
        ]

        if not group_orders:
            logger.info(f"[order-router] No open orders found for triggered group {group_id}")
            return {"group_id": group_id, "canceled": [], "message": "No orders to cancel"}

        # Cancel each order
        canceled = []
        failed = []

        for order in group_orders:
            order_id = order.get("order_id")
            if not order_id:
                continue

            try:
                cancel_result = await client.cancel_order_result(order_id)
                if cancel_result.success:
                    canceled.append(order_id)
                    logger.info(f"[order-router] Auto-canceled order {order_id} from triggered group {group_id}")
                else:
                    failed.append({"order_id": order_id, "error": str(cancel_result.error)})
            except Exception as e:
                failed.append({"order_id": order_id, "error": str(e)})

        # Publish event for other components
        try:
            from core.events import publish_event
            publish_event(KALSHI_CHANNEL_ORDER_GROUP_TRIGGERED, {
                "group_id": group_id,
                "canceled_orders": canceled,
                "failed_cancels": failed,
                "group_data": group_data,
                "ts": datetime.now(timezone.utc).isoformat(),
            })
        except ImportError:
            logger.debug("[order-router] event publish unavailable for group trigger notification")

        return {
            "group_id": group_id,
            "canceled": canceled,
            "failed": failed,
            "total_orders": len(group_orders),
        }

    except Exception as exc:
        logger.error(f"[order-router] Auto-cancel failed for triggered group {group_id}: {exc}")
        return {"error": str(exc), "group_id": group_id, "canceled": []}


# ── OrderIntent ───────────────────────────────────────────────────────────

@dataclass
class OrderIntent:
    """Typed order intent for Kalshi markets.

    Attributes:
        ticker: Kalshi market ticker
        side: ``"yes"`` or ``"no"``
        action: ``"buy"`` or ``"sell"``
        price_cents: Limit price in cents (1-99)
        count: Number of contracts
        mode: Override trading mode (None = use VenueGate default)
        order_type: ``"limit"`` or ``"market"``
        time_in_force: ``"fill_or_kill"`` | ``"gtc"`` | ``"ioc"``
        edge_pct: Optional edge estimate for risk checks
        source: Originating agent/strategy name
        order_group_id: Optional order group ID for aggregate limits
        self_trade_prevention_type: Optional STP mode (e.g., "taker_at_cross")
        intent_id: Unique intent identifier (auto-generated)
        client_tag: Idempotency key for dedup on retry (BUG-2 fix)
        snapshot_ts: Wall-clock epoch when market snapshot was captured (BUG-3 fix)
        data_version: Model/schema version tag tied to snapshot (BUG-3 fix)
        agent_id: Originating agent identifier
        session_id: Trading session identifier
        confidence: Model confidence estimate (0-1)
        rationale: Human-readable signal rationale (<=200 chars)
        parent_intent_id: Parent intent ID for legs of a multi-leg trade (BUG-4 fix)
        leg_index: Leg position in a multi-leg trade: 0=YES, 1=NO (BUG-4 fix)
        group_id: Canonical group ID from FilterPipeline for downstream consistency
    """
    ticker: str
    side: str
    action: str
    price_cents: int
    count: int
    mode: Optional[TradingMode] = None
    order_type: str = "limit"
    time_in_force: str = "gtc"
    edge_pct: Optional[float] = None
    source: str = "manual"
    order_group_id: Optional[str] = None
    self_trade_prevention_type: Optional[str] = None
    post_only: bool = False
    # BUG-1/BUG-2: canonical context + idempotency fields
    intent_id: str = field(default_factory=lambda: f"intent_{__import__('uuid').uuid4().hex}")
    client_tag: Optional[str] = None
    snapshot_ts: float = field(default_factory=time.time)
    data_version: str = "v1"
    agent_id: Optional[str] = None
    session_id: Optional[str] = None
    confidence: Optional[float] = None
    rationale: Optional[str] = None
    parent_intent_id: Optional[str] = None
    leg_index: Optional[int] = None
    # Canonical group_id from FilterPipeline for downstream consistency
    group_id: Optional[str] = None
    # Good-till-time: Unix epoch seconds; router maps intent to GTT + expiration_ts
    order_expiration_ts: Optional[int] = None
    # Sentiment / audit trail (propagate to paper fills & ledger metadata)
    decision_trace_id: Optional[str] = None
    sentiment_asset: Optional[str] = None
    sentiment_timeframe: Optional[str] = None
    sentiment_driven: bool = False


def _resolve_tif(intent: OrderIntent) -> tuple[str, Optional[int]]:
    """Resolve Kalshi time-in-force and optional GTT expiration.

    Uses ``KalshiMarketState.seconds_to_expiry`` when near expiry forces IOC.
    Public helper (imported by tests); keep signature stable.
    """
    from merid.event_venues.kalshi.market_state import (
        get_kalshi_market_state_store,
        IOC_AUTO_BELOW_SECONDS,
    )

    raw = (intent.time_in_force or "gtc").strip().lower()
    exp_ts = intent.order_expiration_ts

    if raw == "fill_or_kill":
        norm = "fok"
    elif raw in ("gtc", "ioc", "fok"):
        norm = raw
    else:
        norm = "gtc"

    secs: Optional[float] = None
    try:
        store = get_kalshi_market_state_store()
        st = store.get(intent.ticker)
        if st is not None and st.seconds_to_expiry is not None:
            secs = float(st.seconds_to_expiry)
    except Exception:
        secs = None

    near = secs is not None and secs <= float(IOC_AUTO_BELOW_SECONDS)

    if norm == "ioc":
        return "IOC", None
    if norm == "fok":
        return "FOK", None

    if near:
        return "IOC", None
    if exp_ts is not None:
        return "GTT", int(exp_ts)
    return "GTC", None


@dataclass
class OrderResult:
    """Result of order routing.

    Attributes:
        status: ``"filled_mock"`` | ``"filled_paper"`` | ``"filled_live"`` | ``"rejected"``
        mode: Resolved trading mode
        fill: Fill details (if filled)
        reason: Rejection reason (if rejected)
        latency_ms: Routing latency
    """
    status: str
    mode: TradingMode
    fill: Optional[Dict[str, Any]] = None
    reason: Optional[str] = None
    latency_ms: float = 0.0


# ── Paper fill simulation ─────────────────────────────────────────────────

def _resolve_mode(override: Optional[TradingMode]) -> TradingMode:
    """Resolve mode from explicit override or canonical process-wide mode."""
    if override is not None:
        return override
    try:
        return TradingMode(get_trade_mode().value)
    except Exception as _e:
        logger.debug("_resolve_mode: get_trade_mode failed, falling back to venue_gate: %s", _e)
        return get_venue_gate().mode


def _mode_value(mode: TradingMode) -> str:
    return getattr(mode, "value", str(mode)).lower()


def _is_mock_mode(mode: TradingMode) -> bool:
    # Keep legacy "sim" compatibility while canonical mode is "mock"
    return _mode_value(mode) in {"mock", "sim"}


def _is_paper_mode(mode: TradingMode) -> bool:
    return _mode_value(mode) == "paper"


def _is_live_mode(mode: TradingMode) -> bool:
    return _mode_value(mode) == "live"


def _kalshi_fee_cents(price_cents: int, contracts: int) -> int:
    """Canonical Kalshi fee calculation using kalshi_risk_engine.
    
    Formula: ceil(0.07 * C * P * (1-P)) where:
    - C = contracts
    - P = price in dollars (price_cents / 100)
    """
    from merid.prediction.risk.kalshi_risk_engine import KalshiRiskEngine
    return KalshiRiskEngine.kalshi_fee_cents(contracts, price_cents)


def simulate_paper_fill(
    intent: OrderIntent,
    _rng: Optional["random.Random"] = None,
) -> Dict[str, Any]:
    """Simulate a paper/mock fill with slippage, partial-fill probability, and fees.

    Args:
        intent: The order intent to simulate.
        _rng: Optional seeded ``random.Random`` instance.  Pass one for
              deterministic gauntlet/promotion evaluation; omit for live
              paper sessions (uses the module-level RNG).
    """
    import random as _random_module
    rng = _rng if _rng is not None else _random_module

    requested_count = max(0, int(intent.count))
    requested_price = max(1, min(99, int(intent.price_cents)))

    # Basic side-aware slippage in cents from configured basis points.
    slippage_cents = max(0, int(round(requested_price * PAPER_SLIPPAGE_BPS / 10_000)))
    if intent.order_type == "market":
        slippage_cents = max(slippage_cents, 1)

    # Buy pays up; sell receives down.
    side_sign = 1 if intent.action == "buy" else -1
    fill_price = max(1, min(99, requested_price + (side_sign * slippage_cents)))

    # Partial fill simulation when size > 1 contract.
    partial_fill = False
    fill_count = requested_count
    if requested_count > 1 and rng.random() < PAPER_PARTIAL_FILL_PROB:
        partial_fill = True
        min_fill = max(1, int(round(requested_count * PAPER_MIN_FILL_RATIO)))
        fill_count = rng.randint(min_fill, requested_count)

    remaining_count = max(0, requested_count - fill_count)
    # Bug 8 fix: fee is computed on the decision price (requested_price), not
    # the slipped fill_price.  Using fill_price understates fees for buys
    # (slippage raises fill_price → reduces payout → reduces fee) and
    # overstates them for sells, diverging from the exchange's actual charge.
    fee_cents = _kalshi_fee_cents(requested_price, fill_count)

    # Build v1 hash preimage for deterministic fill_id and forensic traceability
    import hashlib
    hash_preimage = f"{intent.intent_id}:{intent.ticker}:{intent.side}:{intent.action}:{fill_count}:{fill_price}"
    # M1-FIX: Use SHA256 for deterministic fill_id (hash() is randomized per process)
    fill_id = f"paper_{hashlib.sha256(hash_preimage.encode()).hexdigest()[:16]}"
    logger.debug(f"[order-router] Paper fill hash_preimage: {hash_preimage} -> {fill_id}")

    return {
        "fill_id": fill_id,
        "hash_preimage": hash_preimage,
        "source": "paper",
        "idempotency_key": intent.client_tag or intent.intent_id,
        "canonical_hash_version": "v1",
        "ticker": intent.ticker,
        "side": intent.side,
        "action": intent.action,
        "price_cents": fill_price,
        "requested_price_cents": requested_price,
        "count": fill_count,
        "requested_count": requested_count,
        "remaining_count": remaining_count,
        "partial_fill": partial_fill,
        "fee_cents": fee_cents,
        "ts": datetime.now(timezone.utc).isoformat(),
        "simulated": True,
        "decision_trace_id": intent.decision_trace_id,
        "sentiment_asset": intent.sentiment_asset,
        "sentiment_timeframe": intent.sentiment_timeframe,
        "sentiment_driven": intent.sentiment_driven,
    }


# ── Risk check ────────────────────────────────────────────────────────────

def _check_intent_risk(intent: OrderIntent) -> Optional[str]:
    """Basic pre-flight risk checks on an OrderIntent.

    Returns rejection reason string, or None if OK.
    """
    if intent.count <= 0:
        return "non_positive_size"
    if intent.price_cents <= 0 or intent.price_cents >= 100:
        return "invalid_price"
    if intent.side not in ("yes", "no"):
        return "invalid_side"
    if intent.action not in ("buy", "sell"):
        return "invalid_action"
    return None


def _check_ticker_valid(intent: OrderIntent) -> Optional[str]:
    """Validate Kalshi ticker format before routing order.
    
    This guardrail prevents 404 errors from malformed tickers like
    KXDOGE15M-26APR191645-45 which have invalid time formats or
    synthetic suffixes that don't exist in Kalshi's canonical symbols.
    
    Returns rejection reason string, or None if OK.
    """
    if not intent.ticker:
        return "missing_ticker"
    
    is_valid, error_msg = is_valid_kalshi_ticker(intent.ticker, require_cached=False)
    if not is_valid:
        logger.error(
            "[ORDER_ROUTER_TICKER_REJECT] %s: %s",
            intent.ticker, error_msg
        )
        return f"invalid_ticker: {error_msg}"
    
    return None


# ── Ticker helpers ────────────────────────────────────────────────────────

# Ordered: longer/more-specific prefixes first to avoid false matches.
_TICKER_UNDERLYING_MAP: List[tuple] = [
    # Crypto
    ("BITCOIN", "BTC"),  ("KXBTC", "BTC"),    ("KXETH", "ETH"),
    ("KXSOL", "SOL"),    ("KXXRP", "XRP"),    ("KXDOGE", "DOGE"),
    ("KXPEPE", "PEPE"),  ("KXAVAX", "AVAX"),  ("KXLINK", "LINK"),
    ("KXADA", "ADA"),    ("KXLTC", "LTC"),    ("KXPOL", "POL"),
    # Macroeconomics
    ("KXCPI", "CPI"),    ("KXGDP", "GDP"),    ("KXJOBS", "JOBS"),
    ("KXNFP", "JOBS"),   ("KXNONFARM", "JOBS"),("KXPAYROLL", "JOBS"),
    ("KXUNEMPLOYMENT", "JOBS"), ("KXFOMC", "RATES"), ("KXFED", "RATES"),
    ("KXRATE", "RATES"),
    # Financials / indices
    ("KXSPX", "SPX"),    ("KXSPY", "SPX"),    ("KXSP500", "SPX"),
    ("KXNDX", "NDX"),    ("KXQQQ", "NDX"),    ("KXNASDAQ", "NDX"),
    ("KXDJI", "DJI"),    ("KXDJIA", "DJI"),   ("KXDOW", "DJI"),
    ("KXRUSSELL", "RUT"),("KXRUT", "RUT"),    ("KXIWM", "RUT"),
    # Politics
    ("KXELECTION", "ELECTION"), ("KXPRES", "ELECTION"),
    ("KXSENATE", "SENATE"),     ("KXCONGRESS", "CONGRESS"),
    ("KXSCOTUS", "SCOTUS"),     ("KXTRUMP", "ELECTION"),
    ("KXBIDEN", "ELECTION"),    ("KXGOV", "GOV"),
    # Climate / weather
    ("KXWEATHER", "WEATHER"),   ("KXTEMP", "WEATHER"),
    ("KXHURRICANE", "WEATHER"), ("KXTORNADO", "WEATHER"),
    ("KXCLIMATE", "CLIMATE"),   ("KXCARBON", "CLIMATE"),
    # Sports
    ("KXNBA", "NBA"),    ("KXNFL", "NFL"),    ("KXMLB", "MLB"),
    ("KXNHL", "NHL"),    ("KXSOCCER", "SOCCER"),("KXMLS", "SOCCER"),
    ("KXEPL", "SOCCER"), ("KXTENNIS", "TENNIS"),("KXGOLF", "GOLF"),
    ("KXMMA", "MMA"),    ("KXUFC", "MMA"),
    # Tech / AI
    ("KXAI", "AI"),      ("KXOPENAI", "AI"),   ("KXNVDA", "NVDA"),
    ("KXAPPLE", "AAPL"), ("KXMETA", "META"),   ("KXGOOGLE", "GOOGL"),
    ("KXMSFT", "MSFT"),  ("KXTECH", "TECH"),
]


# Import public get_underlying from shared utilities (moved from private function)
# Backward compatibility: _get_underlying is now an alias for the public function
from merid.event_venues.kalshi.kalshi_market_utils import get_underlying as _get_underlying


# ── Sanity check gate (A6) ────────────────────────────────────────────────

_SANITY_PORTFOLIO_USD = float(os.getenv("MERID_PM_MAX_TOTAL_NOTIONAL", "5000.0"))


def _check_sentiment_notional_cap(intent: OrderIntent) -> Optional[str]:
    """Enforce per-asset sentiment notional caps (see :mod:`merid.risk.sentiment_risk`)."""
    try:
        from merid.risk.sentiment_risk import sentiment_order_rejection_reason

        return sentiment_order_rejection_reason(intent)
    except Exception as exc:
        logger.debug("[order-router] sentiment cap check skipped: %s", exc)
        return None


def _check_sanity(intent: OrderIntent, t0: float, mode: TradingMode) -> Optional[OrderResult]:
    """Run OrderSanityChecker on the intent.  Returns a rejection OrderResult or None."""
    try:
        from core.order_sanity_check import get_order_sanity_checker
        checker = get_order_sanity_checker()
        notional_usd = intent.count * intent.price_cents / 100.0
        _min_n: Optional[float] = None
        _min_src = "default_config"
        _thr_mode = ""
        try:
            from merid.prediction.crypto_edge_production import get_crypto_edge_runtime

            _thr_mode = str(get_crypto_edge_runtime().threshold_mode or "")
        except Exception as _thr_exc:
            logger.debug("[order-router] threshold_mode lookup: %s", _thr_exc)
            _thr_mode = ""
        try:
            from merid.prediction.crypto_threshold_matrix import get_min_order_notional_for_intent

            _min_n = get_min_order_notional_for_intent(intent.agent_id, intent.ticker)
        except Exception as _san_exc:
            logger.debug("[order-router] get_min_order_notional_for_intent: %s", _san_exc)
            _min_n = None
            _min_src = "matrix_lookup_error"
        else:
            if _min_n is not None:
                _min_src = f"crypto_matrix(threshold_mode={_thr_mode})"
            elif intent.agent_id:
                _min_src = "matrix_unresolved(fallback_to_default_min)"
                logger.warning(
                    "[CRYPTO_MIN_NOTION_MATRIX] min_order_notional_usd not resolved for "
                    "agent_id=%r ticker=%s threshold_mode=%s — using OrderSanityChecker "
                    "default min_order_notional_usd=%.4f (fix agent_id/grid/matrix row)",
                    intent.agent_id,
                    intent.ticker,
                    _thr_mode,
                    float(checker.config.min_order_notional_usd),
                )
            else:
                _min_src = "no_agent_id(fallback_to_default_min)"
        _effective_floor = float(_min_n) if _min_n is not None else float(checker.config.min_order_notional_usd)
        result = checker.check(
            symbol=intent.ticker,
            quantity=intent.count,
            price=intent.price_cents / 100.0,
            portfolio_value=_SANITY_PORTFOLIO_USD,
            side=intent.action,
            min_order_notional_usd=_min_n,
        )
        if result.passed:
            logger.debug(
                "[order-router] sanity ok: %s notional_usd=%.4f min_floor_usd=%.4f src=%s agent_id=%s",
                intent.ticker,
                notional_usd,
                _effective_floor,
                _min_src,
                intent.agent_id,
            )
        if not result.passed:
            latency = (time.monotonic() - t0) * 1000
            reasons = "; ".join(v["check"] for v in result.violations)
            logger.warning(
                "[order-router] Order rejected by sanity check: %s — %s | "
                "notional_usd=%.4f min_floor_usd=%.4f src=%s threshold_mode=%s agent_id=%s violations=%s",
                intent.ticker,
                reasons,
                notional_usd,
                _effective_floor,
                _min_src,
                _thr_mode,
                intent.agent_id,
                result.violations,
            )
            return OrderResult(
                status="rejected",
                mode=mode,
                reason=f"sanity_check:{reasons}",
                latency_ms=round(latency, 2),
            )
    except Exception as exc:
        latency = (time.monotonic() - t0) * 1000
        logger.error("[order-router] Sanity checker error (fail-closed): %s", exc)
        return OrderResult(
            status="rejected",
            mode=mode,
            reason=f"sanity_check_error:{exc}",
            latency_ms=round(latency, 2),
        )
    return None


# ── Router ────────────────────────────────────────────────────────────────

def _update_gate_on_fill(intent: OrderIntent, fill_count: int) -> None:
    """Transition the gate record through submitted→filled for mock/paper fills.

    Without this, the PENDING record inserted by _run_pre_trade_gate is never
    moved to a terminal state, causing an unbounded memory leak (PENDING
    records are excluded from prune_old).
    """
    if not intent.client_tag:
        return
    try:
        from merid.event_venues.kalshi.order_gate import get_pre_trade_gate
        _ptg = get_pre_trade_gate()
        _ptg.mark_submitted(intent.client_tag)
        _ptg.mark_filled(intent.client_tag, fill_count)
    except Exception as e:
        logger.debug(f"Failed to update gate on fill: {e}")


def _route_sync_non_live(intent: OrderIntent, mode: TradingMode, t0: float) -> OrderResult:
    """Route MOCK/PAPER intents synchronously."""
    if _is_mock_mode(mode):
        fill = simulate_paper_fill(intent)
        latency = (time.monotonic() - t0) * 1000
        logger.info(
            f"[order-router] MOCK fill {intent.ticker} {intent.action} "
            f"{intent.count}x @ {intent.price_cents}c"
        )
        _update_gate_on_fill(intent, fill.get("count", intent.count))
        return OrderResult(
            status="filled_mock",
            mode=mode,
            fill=fill,
            latency_ms=round(latency, 2),
        )

    if _is_paper_mode(mode):
        fill = simulate_paper_fill(intent)
        latency = (time.monotonic() - t0) * 1000
        logger.info(
            f"[order-router] PAPER fill {intent.ticker} {intent.action} "
            f"{intent.count}x @ {intent.price_cents}c"
        )
        _update_gate_on_fill(intent, fill.get("count", intent.count))
        return OrderResult(
            status="filled_paper",
            mode=mode,
            fill=fill,
            latency_ms=round(latency, 2),
        )

    latency = (time.monotonic() - t0) * 1000
    _release_gate_record(intent, f"sync_route_unsupported_mode_{_mode_value(mode)}")
    return OrderResult(
        status="rejected",
        mode=mode,
        reason=f"sync_route_unsupported_mode_{_mode_value(mode)}",
        latency_ms=round(latency, 2),
    )


def _release_gate_record(intent: OrderIntent, reason: str = "") -> None:
    """Mark the pre-trade gate record as REJECTED so the slot is freed.

    Must be called on every early-exit path in _route_live that rejects
    AFTER _run_pre_trade_gate already inserted a PENDING record.
    
    CRASH-013: Uses intent_id as fallback when client_tag is missing to ensure
    cleanup happens even if gate stamping failed.
    """
    # CRASH-013: Use intent_id as fallback for gate cleanup
    tag = intent.client_tag or intent.intent_id
    if not tag:
        logger.warning(
            "[CRASH-013] Cannot release gate record: both client_tag and intent_id are empty for %s",
            intent.ticker
        )
        return
    try:
        from merid.event_venues.kalshi.order_gate import get_pre_trade_gate
        get_pre_trade_gate().mark_rejected(tag, reason or "unknown")
        logger.debug("[order-router] Released gate record for %s: %s", tag[:32], reason[:50])
    except Exception as e:
        logger.debug(f"[CRASH-013] Failed to release gate record for {tag[:32]}: {e}")


async def _route_live(intent: OrderIntent, mode: TradingMode, t0: float) -> OrderResult:
    """Route LIVE intents through the canonical KalshiVenueClient."""
    # Snapshot staleness gate — refuse stale intents regardless of caller path.
    # KalshiTradingAgent already checks this, but direct route_order_async() callers
    # (tools, tests, future agents) previously bypassed it entirely (BUG-3b fix).
    _SNAPSHOT_MAX_AGE_S = float(os.getenv("KALSHI_ORDER_SNAPSHOT_MAX_AGE_S", "90"))
    _snap_age = time.time() - intent.snapshot_ts
    if _snap_age > _SNAPSHOT_MAX_AGE_S:
        latency = (time.monotonic() - t0) * 1000
        logger.warning(
            "[order-router] Live order rejected — stale snapshot: ticker=%s age=%.1fs > %.0fs",
            intent.ticker, _snap_age, _SNAPSHOT_MAX_AGE_S,
        )
        _release_gate_record(intent, f"stale_snapshot:{intent.ticker}")
        return OrderResult(
            status="rejected",
            mode=mode,
            reason=f"stale_snapshot:{intent.ticker}:age={_snap_age:.1f}s",
            latency_ms=round(latency, 2),
        )

    # Kill switch hard gate — must be checked before any live execution
    try:
        from merid.risk.kill_switches import risk_controller
        if not risk_controller.can_trade():
            latency = (time.monotonic() - t0) * 1000
            reason = risk_controller.get_kill_reason() or "kill_switch_active"
            logger.warning(f"[order-router] Live order blocked by kill switch: {reason}")
            _release_gate_record(intent, f"kill_switch:{reason}")
            return OrderResult(
                status="rejected",
                mode=mode,
                reason=f"kill_switch:{reason}",
                latency_ms=round(latency, 2),
            )
    except ImportError as exc:
        # Fail-closed: if risk_controller unavailable, block live orders for safety
        latency = (time.monotonic() - t0) * 1000
        logger.error(f"[order-router] Risk controller unavailable - blocking live order: {exc}")
        _release_gate_record(intent, "risk_controller_unavailable")
        return OrderResult(
            status="rejected",
            mode=mode,
            reason="risk_controller_unavailable",
            latency_ms=round(latency, 2),
        )
    except Exception as exc:
        # Fail-closed: any unexpected error in risk check should block order
        latency = (time.monotonic() - t0) * 1000
        logger.error(f"[order-router] Risk check failed - blocking live order: {exc}")
        _release_gate_record(intent, f"risk_check_error:{str(exc)}")
        return OrderResult(
            status="rejected",
            mode=mode,
            reason=f"risk_check_error:{str(exc)}",
            latency_ms=round(latency, 2),
        )

    gate = get_venue_gate()
    if not gate.live_enabled:
        latency = (time.monotonic() - t0) * 1000
        gate.log_order_decision(
            decision="deny",
            reason="live_not_enabled",
            venue="Kalshi",
            size=int(intent.count),
            notional_usd=float(intent.count * intent.price_cents) / 100.0,
            caps=f"mode={gate.mode.value} live_enabled={gate.live_enabled}",
        )
        try:
            from merid.prediction.ua_ct_metrics import record_order_reject

            record_order_reject()
        except Exception as e:
            logger.debug(f"Order reject metric failed: {e}")
        _release_gate_record(intent, "live_not_enabled")
        return OrderResult(
            status="rejected",
            mode=mode,
            reason="live_not_enabled",
            latency_ms=round(latency, 2),
        )

    # Unified execution gate (loop lag, feeds, exchange, reconciliation, etc.) — before client IO
    try:
        from core.execution_gate import check_execution_gate, live_execution_blocked

        _eg = check_execution_gate()
    except Exception as exc:
        latency = (time.monotonic() - t0) * 1000
        logger.error("[order-router] execution gate check failed (fail-closed): %s", exc)
        _release_gate_record(intent, f"execution_gate_error:{exc}")
        return OrderResult(
            status="rejected",
            mode=mode,
            reason=f"execution_gate_error:{exc}",
            latency_ms=round(latency, 2),
        )
    _gate_close = live_execution_blocked(_eg)
    try:
        from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS, kalshi_ticker_to_asset
        from merid.prediction.crypto_edge_production import crypto_pm_live_execution_blocked

        _ga = kalshi_ticker_to_asset(intent.ticker)
        if _ga and _ga in ACTIVE_CRYPTO_ASSETS:
            _gate_close = crypto_pm_live_execution_blocked(_eg)
    except Exception as _gate_check_err:
        logger.warning("[order-router] Execution gate check error (proceeding with caution): %s", _gate_check_err)
    if _gate_close:
        latency = (time.monotonic() - t0) * 1000
        _first = _eg.reasons[0] if _eg.reasons else None
        _msg = (_first.message if _first else "blocked") or "blocked"
        _srcs = [r.source for r in (_eg.reasons or [])]
        if "loop_lag" in _srcs:
            _msg = f"execution_gate_loop_lag:{_msg}"
        logger.warning("[order-router] Live order blocked by execution gate: %s", _msg)
        try:
            from merid.prediction.ua_ct_metrics import record_order_reject

            record_order_reject()
        except Exception as _metric_err:
            logger.debug("[order-router] Order reject metric recording failed: %s", _metric_err)
        _release_gate_record(intent, f"execution_gate_blocked:{_msg}")
        return OrderResult(
            status="rejected",
            mode=mode,
            reason=f"execution_gate_blocked:{_msg}",
            latency_ms=round(latency, 2),
        )

    # KalshiRiskManager — position limits, category caps, drawdown, rate limiting
    try:
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
        from merid.event_venues.kalshi.category_exposure import infer_category as _infer_cat
        risk = get_kalshi_risk()
        _rm_category = _infer_cat(_get_underlying(intent.ticker))
        # Look up existing position so per-contract limit check is accurate
        # CRASH-004: Use sentinel value for cache failure, never poison calculation
        _POSITION_UNKNOWN = -1
        _existing_pos = 0
        _position_cache_ok = True
        try:
            from merid.event_venues.kalshi.position_cache import get_position_cache
            _cached = get_position_cache().get_position(intent.ticker)
            if _cached is not None:
                _existing_pos = _cached.contracts
        except Exception as _pos_err:
            _position_cache_ok = False
            # CRASH-004: Log and emit metric, but don't poison the position value
            logger.error(
                "[order-router] Position cache lookup failed for %s: %s — rejecting order (fail-closed)",
                intent.ticker,
                _pos_err,
            )
            try:
                from monitoring.metrics import get_metrics_registry
                get_metrics_registry().counter(
                    "kalshi_position_cache_failure",
                    "Position cache lookup failed, order rejected",
                    ["ticker"]
                ).inc(labels={"ticker": intent.ticker})
            except Exception:
                pass
            # CRASH-004: Explicit rejection instead of poisoned value
            return OrderResult(
                status="rejected",
                mode=mode,
                reason=f"position_cache_unavailable:{_pos_err}",
                latency_ms=round((time.monotonic() - t0) * 1000, 2),
            )
        
        # Derive asset/timeframe for group-level risk aggregation using canonical helper
        # Prefer upstream group_id from OrderIntent (propagated from FilterPipeline), fallback to canonical helper
        _group_id = intent.group_id
        # Generate trace event_id for cross-stage correlation
        _trace_event_id = f"gid-{intent.ticker}-{int(time.monotonic()*1000)%100000}"
        if _group_id is not None:
            # GROUP_ID TRACE: Structured logging with event_id for traceability
            logger.info(
                "[GROUP-ID-TRACE] event_id=%s stage=router ticker=%s group_id=%s "
                "source=OrderIntent.upstream",
                _trace_event_id, intent.ticker, _group_id,
                extra={
                    "event_id": _trace_event_id,
                    "stage": "router",
                    "ticker": intent.ticker,
                    "group_id": _group_id,
                    "source": "OrderIntent.upstream",
                }
            )
            # STRICT MODE: Log and metric on mismatch, but never crash the router.
            # Use recomputed value and continue with visibility.
            _strict_mode = os.getenv("KALSHI_STRICT_GROUP_ID", "false").lower() in ("true", "1", "yes")
            _recomputed = group_id_from_ticker(intent.ticker)
            if _strict_mode and _group_id != _recomputed:
                # Log error with full context
                logger.error(
                    "[GROUP-ID-MISMATCH] upstream=%s recomputed=%s ticker=%s "
                    "| FilterPipeline and router disagree on canonical group_id! "
                    "Using recomputed value and continuing.",
                    _group_id, _recomputed, intent.ticker
                )
                # Emit metric for monitoring
                try:
                    from monitoring.metrics import get_metrics_registry
                    get_metrics_registry().counter(
                        "kalshi_group_id_mismatch",
                        "Group ID mismatch between FilterPipeline and router",
                        ["ticker", "upstream_id", "recomputed_id"]
                    ).inc(labels={
                        "ticker": intent.ticker,
                        "upstream_id": str(_group_id),
                        "recomputed_id": str(_recomputed)
                    })
                except Exception as e:
                    logger.debug(f"Metric increment failed: {e}")
                # Use recomputed value (safer) and continue
                _group_id = _recomputed
        else:
            _group_id = group_id_from_ticker(intent.ticker)
            # GROUP_ID TRACE: Structured logging for fallback case
            logger.info(
                "[GROUP-ID-TRACE] event_id=%s stage=router ticker=%s group_id=%s "
                "source=local_recompute",
                _trace_event_id, intent.ticker, _group_id,
                extra={
                    "event_id": _trace_event_id,
                    "stage": "router",
                    "ticker": intent.ticker,
                    "group_id": _group_id,
                    "source": "local_recompute",
                }
            )
        _asset = extract_asset_from_ticker(intent.ticker)
        _timeframe = get_series_timeframe_bucket(intent.ticker)
        
        allowed, reason = risk.check_order(
            ticker=intent.ticker,
            category=_rm_category,
            contracts=intent.count,
            price_cents=intent.price_cents,
            edge=intent.edge_pct or 0.0,
            existing_position=_existing_pos,
            asset=_asset,
            timeframe=_timeframe,
            group_id=_group_id,
        )
        if not allowed:
            latency = (time.monotonic() - t0) * 1000
            logger.warning(f"[order-router] Live order blocked by KalshiRiskManager: {reason}")
            try:
                from merid.prediction.ua_ct_metrics import record_order_reject

                record_order_reject()
            except Exception as e:
                logger.debug(f"Order reject metric failed: {e}")
            _release_gate_record(intent, f"risk_check:{reason}")
            return OrderResult(
                status="rejected",
                mode=mode,
                reason=f"risk_check:{reason}",
                latency_ms=round(latency, 2),
            )
    except Exception as exc:
        latency = (time.monotonic() - t0) * 1000
        logger.error(f"[order-router] KalshiRiskManager unavailable — blocking live order: {exc}")
        _release_gate_record(intent, f"risk_manager_unavailable:{exc}")
        return OrderResult(
            status="rejected",
            mode=mode,
            reason=f"risk_manager_unavailable:{exc}",
            latency_ms=round(latency, 2),
        )

    # ── A3/A4: Cross-agent category cap + correlated-market stacking guard ──
    # BUG-03 fix: use atomic check_and_reserve() instead of the non-atomic
    # two-call sequence (check_category_cap + check_correlated_cap) which had a
    # TOCTOU race allowing concurrent agents to jointly exceed the cap.
    # The reserved notional is released further down if the order is rejected
    # or fails at the exchange.
    #
    # BUG-B fix: sell/close orders REDUCE exposure — skip check_and_reserve
    # (which adds notional) and instead call release() after a successful fill
    # so the tracker reflects the reduced open position.
    _exp_tracker = None
    _reserved_category: Optional[str] = None
    _reserved_underlying: Optional[str] = None
    _reserved_notional: float = 0.0
    _is_sell = intent.action == "sell"
    # A3/RISK-05: Initialize order group tracking variables BEFORE any client calls
    # so exception handlers can safely check them even if early errors occur.
    _og_manager: Optional[OrderGroupRiskManager] = None
    _og_debited: bool = False
    
    try:
        from merid.event_venues.kalshi.category_exposure import (
            get_category_exposure_tracker,
            infer_category,
        )
        _underlying = _get_underlying(intent.ticker)
        _category = infer_category(_underlying)
        _notional_usd = intent.count * intent.price_cents / 100.0
        _exp_tracker = get_category_exposure_tracker()

        if _is_sell:
            # Sell: skip cap check (closing reduces exposure), tag for post-fill release.
            _reserved_category = _category
            _reserved_underlying = _underlying
            _reserved_notional = _notional_usd
        else:
            _cap_ok, _cap_reason = _exp_tracker.check_and_reserve(
                _category, _underlying, _notional_usd
            )
            if not _cap_ok:
                latency = (time.monotonic() - t0) * 1000
                logger.warning("[order-router] Exposure cap rejected %s: %s", intent.ticker, _cap_reason)
                try:
                    from merid.prediction.ua_ct_metrics import record_order_reject

                    record_order_reject()
                except Exception as e:
                    logger.error(f"Order reject metric failed: {e}")
                _release_gate_record(intent, _cap_reason)
                return OrderResult(
                    status="rejected", mode=mode, reason=_cap_reason, latency_ms=round(latency, 2),
                )
            # Track what was reserved so we can release on downstream rejection.
            _reserved_category = _category
            _reserved_underlying = _underlying
            _reserved_notional = _notional_usd
    except Exception as _exc:
        latency = (time.monotonic() - t0) * 1000
        logger.error("[order-router] Category exposure check error (fail-closed): %s", _exc)
        _release_gate_record(intent, f"category_cap_check_error:{_exc}")
        return OrderResult(
            status="rejected",
            mode=mode,
            reason=f"category_cap_check_error:{_exc}",
            latency_ms=round(latency, 2),
        )

    # ── B5: Sentiment-based size scalar ─────────────────────────────────────
    try:
        from merid.sentiment.sentiment_bus import get_sentiment_bus
        _asset = _get_underlying(intent.ticker)
        if _asset != "OTHER":
            _sent_bus = get_sentiment_bus()
            if _sent_bus is None:
                logger.debug("[order-router] Sentiment bus unavailable — skipping scaling")
            else:
                _sent = _sent_bus.get_sentiment(_asset)
                # CRASH-008: Defensive attribute checking
                if _sent is not None and hasattr(_sent, 'should_reduce_size') and callable(getattr(_sent, 'should_reduce_size')):
                    try:
                        if _sent.should_reduce_size():
                            _scaled = max(1, int(intent.count * 0.5))
                            if _scaled != intent.count:
                                logger.info(
                                    "[order-router] Sentiment scaling %s: %d→%d (regime=%s)",
                                    intent.ticker, intent.count, _scaled, 
                                    getattr(_sent, 'trend_regime', 'unknown'),
                                )
                                intent = _dc_replace(intent, count=_scaled)
                    except Exception as _sent_exc:
                        logger.debug("[order-router] Sentiment should_reduce_size() failed: %s", _sent_exc)
                else:
                    logger.debug("[order-router] Sentiment object missing should_reduce_size method")
    except Exception as _exc:
        logger.debug("[order-router] Sentiment scaling skipped: %s", _exc)

    try:
        from merid.event_venues.base import VenueOrder
        from merid.event_venues.kalshi.client import get_kalshi_client
        from merid.event_venues.kalshi.order_group_manager import OrderGroupRiskManager

        client = get_kalshi_client()
        await client.connect()

        # ── A5: Re-validate market conditions per-order ───────────────────
        _market_check_passed = False
        try:
            from merid.event_venues.kalshi.market_filter import DEFAULT_FILTER_CONFIG
            _market_result = await client.get_market(intent.ticker)
            if not _market_result.success:
                # Handle 404 / market not found (BUG-404 fix)
                _error_str = str(_market_result.error or "").lower()
                if "404" in _error_str or "not found" in _error_str or "client error" in _error_str:
                    latency = (time.monotonic() - t0) * 1000
                    logger.warning("[order-router] A5: market %s not found (404), rejecting order", intent.ticker)
                    _release_gate_record(intent, f"market_not_found:{intent.ticker}")
                    return OrderResult(
                        status="rejected",
                        mode=mode,
                        reason=f"market_not_found:{intent.ticker}",
                        latency_ms=round(latency, 2),
                    )
            elif _market_result.value is not None:
                _market_check_passed = True
                _mkt = _market_result.value
                _bid = int(getattr(_mkt, "best_bid", 0) or 0)
                _ask = int(getattr(_mkt, "best_ask", 0) or 0)
                _spread = (_ask - _bid) if (_bid > 0 and _ask > 0) else 0
                _vol = int(getattr(_mkt, "volume", 0) or 0)
                _oi = int(getattr(_mkt, "open_interest", 0) or 0)
                _cfg = DEFAULT_FILTER_CONFIG

                def _a5_reject(reason: str) -> OrderResult:
                    if _reserved_category and _exp_tracker:
                        _exp_tracker.release(_reserved_category, _reserved_underlying, _reserved_notional)
                    _release_gate_record(intent, reason)
                    latency = (time.monotonic() - t0) * 1000
                    return OrderResult(status="rejected", mode=mode, reason=reason, latency_ms=round(latency, 2))

                if _bid > 0 and _bid < _cfg.min_price_cents:
                    logger.warning("[order-router] A5: market %s below min_price (%d < %d)", intent.ticker, _bid, _cfg.min_price_cents)
                    return _a5_reject(f"market_condition:price_too_low:{_bid}")
                if _bid > 0 and _bid > _cfg.max_price_cents:
                    logger.warning("[order-router] A5: market %s above max_price (%d > %d)", intent.ticker, _bid, _cfg.max_price_cents)
                    return _a5_reject(f"market_condition:price_too_high:{_bid}")
                if _spread > 0 and _spread > _cfg.max_spread_cents:
                    logger.warning("[order-router] A5: market %s spread too wide (%d > %d)", intent.ticker, _spread, _cfg.max_spread_cents)
                    return _a5_reject(f"market_condition:spread_too_wide:{_spread}")
                if _vol > 0 and _vol < _cfg.min_volume:
                    logger.warning("[order-router] A5: market %s volume too low (%d < %d)", intent.ticker, _vol, _cfg.min_volume)
                    return _a5_reject(f"market_condition:volume_too_low:{_vol}")
        except Exception as _exc:
            # Only skip check if market was found but check failed; fail-closed on 404
            _exc_str = str(_exc).lower()
            if "404" in _exc_str or "not found" in _exc_str or "client error" in _exc_str:
                latency = (time.monotonic() - t0) * 1000
                logger.warning("[order-router] A5: market %s not found (404 from exception), rejecting order: %s", intent.ticker, _exc)
                _release_gate_record(intent, f"market_not_found:{intent.ticker}")
                return OrderResult(
                    status="rejected",
                    mode=mode,
                    reason=f"market_not_found:{intent.ticker}",
                    latency_ms=round(latency, 2),
                )
            logger.debug("[order-router] A5: market condition check skipped (market found but check failed): %s", _exc)

        # ── Order Group Risk Check ─────────────────────────────────────────
        # A3/RISK-05: track og_manager and whether a debit was recorded so we
        # can reverse it if the exchange rejects the order.
        # Note: _og_manager and _og_debited are initialized at function start

        if intent.order_group_id:
            _og_manager = OrderGroupRiskManager(client)
            # P0-5 FIX: Populate cache before lookup so group is found and rollbacks work
            try:
                await _og_manager.refresh_all()
            except Exception as _refresh_err:
                logger.warning(f"[order-router] Failed to refresh order groups: {_refresh_err}")
            group = _og_manager.get_group(intent.order_group_id)

            if not group:
                latency = (time.monotonic() - t0) * 1000
                _release_gate_record(intent, f"order_group_not_found:{intent.order_group_id}")
                return OrderResult(
                    status="rejected",
                    mode=mode,
                    reason=f"order_group_not_found:{intent.order_group_id}",
                    latency_ms=round(latency, 2),
                )

            if not group.is_active():
                latency = (time.monotonic() - t0) * 1000
                _release_gate_record(intent, f"order_group_not_active:{intent.order_group_id}")
                return OrderResult(
                    status="rejected",
                    mode=mode,
                    reason=f"order_group_not_active:{intent.order_group_id}:status={group.status}",
                    latency_ms=round(latency, 2),
                )

            if not group.can_add_contracts(intent.count):
                latency = (time.monotonic() - t0) * 1000
                _release_gate_record(intent, f"order_group_limit_exceeded:{intent.order_group_id}")
                return OrderResult(
                    status="rejected",
                    mode=mode,
                    reason=f"order_group_limit_exceeded:{intent.order_group_id}:used={group.used_contracts}:limit={group.contracts_limit}:requested={intent.count}",
                    latency_ms=round(latency, 2),
                )

            # Record optimistic usage — must be reversed if exchange rejects
            _og_manager.record_new_order(intent.order_group_id, intent.count)
            _og_debited = True

        # client_tag was already set by _run_pre_trade_gate (called by
        # route_order_async before _route_live).  Fallback only if caller
        # invoked _route_live directly without the gate (e.g. tests).
        # CRASH-003: client_tag MUST use original decision timestamp to prevent
        # duplicate orders on bucket rollover during retries.
        if not intent.client_tag:
            # Lock to original decision timestamp, never use current time
            decision_ts = intent.snapshot_ts
            ts_bucket = int(decision_ts) // 60
            idempotency_preimage = (
                f"{intent.agent_id or 'none'}|{intent.ticker}|{intent.side}|{intent.action}|"
                f"{intent.price_cents}|{intent.count}|{ts_bucket}|{intent.order_group_id or 'none'}"
            )
            id_hash = hashlib.sha256(idempotency_preimage.encode()).hexdigest()[:16]
            intent.client_tag = f"merid-{id_hash}-{ts_bucket}"
            logger.debug(
                "[CRASH-003] Generated client_tag=%s using locked snapshot_ts=%s (bucket=%s)",
                intent.client_tag, decision_ts, ts_bucket
            )

        tif, gtt_exp = _resolve_tif(intent)

        order = VenueOrder(
            market_id=intent.ticker,
            side=intent.action,
            size=Decimal(intent.count),
            price=(Decimal(intent.price_cents) / Decimal("100")) if intent.order_type == "limit" else None,
            order_type="limit" if intent.order_type == "limit" else "market",
            outcome_id=intent.side,
            time_in_force=tif,
            expiration_ts=gtt_exp,
            client_order_id=intent.client_tag,
        )

        _pre_notional_usd = float(intent.count * intent.price_cents) / 100.0
        gate.log_order_decision(
            decision="approve",
            reason="live_order_admitted",
            venue="Kalshi",
            size=int(intent.count),
            notional_usd=_pre_notional_usd,
            caps=f"mode={mode.value} source={getattr(intent, 'source', '')}",
        )

        logger.info(
            "[KALSHI_ORDER_INTENT] ticker=%s side=%s action=%s count=%d price_cents=%d "
            "mode=%s source=%s",
            intent.ticker,
            intent.side,
            intent.action,
            int(intent.count),
            int(intent.price_cents),
            mode.value,
            getattr(intent, "source", "") or "",
        )

        # DRY-RUN-TRACE: Fee computation using canonical kalshi_fee_cents
        # CRASH-007: Validate inputs before fee calculation
        if intent.price_cents <= 0 or intent.count <= 0:
            logger.error(
                "[CRASH-007] Invalid order parameters for %s: price_cents=%s count=%s — rejecting",
                intent.ticker, intent.price_cents, intent.count
            )
            return OrderResult(
                status="rejected",
                mode=mode,
                reason=f"invalid_order_params:price={intent.price_cents}:count={intent.count}",
                latency_ms=round((time.monotonic() - t0) * 1000, 2),
            )
        _fee_pre = _kalshi_fee_cents(intent.price_cents, intent.count)
        _price_dollars = intent.price_cents / 100.0
        _notional_cents = intent.count * intent.price_cents
        _fee_pct = (_fee_pre / _notional_cents * 100) if _notional_cents > 0 else 0
        logger.info(
            "[DRY-RUN-TRACE] fee_computation | router_path=order_router ticker=%s side=%s action=%s | "
            "P=%d¢ ($%.2f) C=%d notional=%d¢ | expected_fee=%d¢ fee_pct_notional=%.4f%%",
            intent.ticker, intent.side, intent.action,
            intent.price_cents, _price_dollars, intent.count, _notional_cents,
            _fee_pre, _fee_pct
        )

        # DRY-RUN-TRACE: Pre-fill state before order submission
        _underlying = _get_underlying(intent.ticker)
        logger.info(
            "[DRY-RUN-TRACE] pre_fill | router_path=order_router ticker=%s side=%s action=%s | "
            "price=%d¢ count=%d notional=%d¢ underlying=%s",
            intent.ticker, intent.side, intent.action,
            intent.price_cents, intent.count, _notional_cents, _underlying
        )

        placed_res = await client.place_order_result(
            order,
            order_group_id=intent.order_group_id,
            self_trade_prevention_type=intent.self_trade_prevention_type,
        )
        latency = (time.monotonic() - t0) * 1000
        
        # Handle idempotent duplicate responses from Kalshi (our order already accepted)
        reason = getattr(placed_res, "error_message", None) or str(placed_res.error) if placed_res.error else "live_order_failed"
        is_duplicate_error = reason and ("gate:duplicate" in reason.lower() or "duplicate" in reason.lower())
        
        if is_duplicate_error:
            # Idempotent success: our order was already accepted by Kalshi on a prior attempt.
            # Look up the order by client_order_id to confirm it's resting.
            logger.info(
                "[KALSHI_DUPLICATE_SUCCESS] ticker=%s client_tag=%s — order already accepted, treating as success",
                intent.ticker,
                intent.client_tag,
            )
            try:
                # Query Kalshi to get current order state
                lookup_res = await client.get_order_by_client_id_result(intent.client_tag)
                if lookup_res.success and lookup_res.data:
                    order_data = lookup_res.data
                    logger.info(
                        "[KALSHI_DUPLICATE_LOOKUP] ticker=%s order_id=%s status=%s — confirmed resting",
                        intent.ticker,
                        getattr(order_data, "order_id", "unknown"),
                        getattr(order_data, "status", "unknown"),
                    )
                    # Treat as success: update gate and return filled/submitted result
                    try:
                        from merid.event_venues.kalshi.order_gate import get_pre_trade_gate
                        _ptg = get_pre_trade_gate()
                        _ptg.mark_submitted(intent.client_tag, getattr(order_data, "order_id", None))
                        _filled = getattr(order_data, "filled_size", 0) or getattr(order_data, "filled_count", 0)
                        if _filled:
                            _ptg.mark_filled(intent.client_tag, int(_filled))
                    except Exception as _dup_gate_err:
                        logger.debug("[order-router] duplicate gate update failed: %s", _dup_gate_err)
                    
                    # Return synthetic success result (not a rejection)
                    return OrderResult(
                        status="filled_live" if getattr(order_data, "filled_size", 0) else "submitted_live",
                        mode=mode,
                        fill={
                            "order_id": getattr(order_data, "order_id", None),
                            "filled_count": getattr(order_data, "filled_size", 0),
                            "remaining_count": getattr(order_data, "remaining_size", 0),
                            "price_cents": int((getattr(order_data, "price", Decimal(0)) * 100)),
                            "client_tag": intent.client_tag,
                        } if lookup_res.data else None,
                        latency_ms=round(latency, 2),
                    )
            except Exception as _dup_lookup_err:
                logger.debug("[order-router] duplicate lookup failed: %s", _dup_lookup_err)
            
            # If lookup fails, we cannot confirm order status. Return ambiguous status
            # so upstream can handle conservatively. Do NOT release exposure or rollback
            # order group — the order may still be resting on the exchange.
            # Emit metric for monitoring and trigger background reconciliation.
            try:
                from monitoring.metrics import get_metrics_registry
                get_metrics_registry().counter(
                    "kalshi_duplicate_lookup_failure",
                    "Failed to resolve duplicate order status from exchange",
                    ["ticker"]
                ).inc(labels={"ticker": intent.ticker})
            except Exception as e:
                logger.debug(f"Metric increment failed: {e}")
            logger.warning(
                "[KALSHI_DUPLICATE_UNKNOWN] ticker=%s client_tag=%s — "
                "lookup failed, status unknown. Exposure NOT released. "
                "Background reconciliation required.",
                intent.ticker,
                intent.client_tag,
            )
            return OrderResult(
                status="duplicate_unknown",  # Ambiguous — upstream must handle conservatively
                mode=mode,
                reason=f"duplicate_unknown:{reason[:50]}",
                latency_ms=round(latency, 2),
            )
        
        if not placed_res.success or placed_res.data is None:
            # BUG-03 fix: release the reserved exposure notional on exchange rejection.
            if _exp_tracker and _reserved_category and _reserved_underlying:
                try:
                    _exp_tracker.release(_reserved_category, _reserved_underlying, _reserved_notional)
                except Exception as _re:
                    logger.debug("[order-router] exposure release failed: %s", _re)
            # A3/RISK-05: reverse the optimistic order-group debit on exchange rejection.
            # CRITICAL: Use release_reservation (not record_fill) to avoid inflating matched_contracts.
            if _og_debited and _og_manager and intent.order_group_id:
                try:
                    _og_manager.release_reservation(intent.order_group_id, intent.count)
                    logger.debug(
                        "[order-router] Released order-group reservation for %s: %d contracts",
                        intent.order_group_id, intent.count
                    )
                except Exception as _ogr:
                    logger.warning("[order-router] og debit rollback failed: %s", _ogr)
            logger.info(
                "[KALSHI_ORDER_RESULT] ticker=%s status=rejected reason=%s source=order_router",
                intent.ticker,
                (reason or "")[:200],
            )
            # Update gate store so the coid slot is freed for future retries
            try:
                from merid.event_venues.kalshi.order_gate import get_pre_trade_gate
                get_pre_trade_gate().mark_rejected(intent.client_tag or "", reason or "")
            except Exception as e:
                logger.debug(f"Gate mark rejected failed: {e}")
            try:
                from merid.prediction.ua_ct_metrics import record_order_reject

                record_order_reject()
            except Exception as e:
                logger.debug(f"Order reject metric failed: {e}")
            return OrderResult(
                status="rejected",
                mode=mode,
                reason=reason,
                latency_ms=round(latency, 2),
            )

        placed = placed_res.data
        requested_count = int(placed.size)
        filled_count = int(placed.filled_size)
        remaining_count = int(placed.remaining_size) if placed.remaining_size is not None else max(0, requested_count - filled_count)
        fill_price_cents = int((placed.price or Decimal(intent.price_cents) / Decimal("100")) * 100)
        fee_cents = _kalshi_fee_cents(fill_price_cents, filled_count)
        _venue_oid = getattr(placed, "order_id", None) or "unknown"

        # Register order intent with position sanity checker for duplicate fill detection
        try:
            from merid.event_venues.kalshi.position_sanity_checker import get_position_sanity_checker
            _sanity = get_position_sanity_checker()
            _sanity.register_order_intent(
                client_order_id=intent.client_tag or f"coid-{_venue_oid}",
                ticker=intent.ticker,
                side=intent.side,
                intended_count=requested_count,
            )
            # If immediate fill, apply it idempotently through sanity checker
            if filled_count > 0:
                _fill_id = f"{_venue_oid}-0"  # sequence 0 for initial fill
                _ok, _err = _sanity.apply_fill(
                    order_id=_venue_oid,
                    fill_id=_fill_id,
                    ticker=intent.ticker,
                    side=intent.side,
                    filled_count=filled_count,
                    price_cents=fill_price_cents,
                    strategy_group=intent.source or "default",
                )
                if not _ok:
                    # CRITICAL: Sanity violation detected - duplicate fill or overfill
                    logger.critical(
                        "[SANITY_VIOLATION] fill_rejected ticker=%s coid=%s error=%s "
                        "filled=%d requested=%d strategy=%s",
                        intent.ticker, intent.client_tag, _err,
                        filled_count, requested_count, intent.source or "default"
                    )
                    # Halt strategy on critical violation (prevent further orders)
                    if _err and ("duplicate_fill" in _err or "overfill" in _err or "POSITION_LIMIT" in _err):
                        try:
                            from merid.risk.kill_switches import risk_controller
                            _strategy = intent.source or intent.agent_id or "unknown"
                            risk_controller.halt_strategy(
                                _strategy,
                                reason=f"sanity_violation:{_err}:ticker={intent.ticker}"
                            )
                            logger.critical(
                                "[STRATEGY_HALT] strategy=%s halted due to %s",
                                _strategy, _err
                            )
                        except Exception as _halt_err:
                            logger.error("[STRATEGY_HALT] Failed to halt strategy: %s", _halt_err)
        except Exception as _sanity_exc:
            # Non-blocking: log but don't fail the order
            logger.debug("[order-router] Sanity checker registration failed: %s", _sanity_exc)

        # Update idempotent order store: submitted → filled/live
        try:
            from merid.event_venues.kalshi.order_gate import get_pre_trade_gate as _get_ptg
            _ptg = _get_ptg()
            _venue_oid = getattr(placed, "order_id", None)
            _ptg.mark_submitted(intent.client_tag or "", _venue_oid)
            if filled_count > 0:
                _ptg.mark_filled(intent.client_tag or "", filled_count)
        except Exception as e:
            logger.debug(f"Gate mark submitted/filled failed: {e}")

        # DRY-RUN-TRACE: Fill reconciliation
        _partial = filled_count < requested_count and filled_count > 0
        _fill_pct = (filled_count / requested_count * 100) if requested_count > 0 else 0.0
        logger.info(
            "[DRY-RUN-TRACE] fill_reconcile | router_path=order_router ticker=%s side=%s action=%s | "
            "requested_C=%d filled_C=%d avg_price=%d¢ partial=%s fill_pct=%.1f%% | fee_expected=%d¢ fee_actual=%d¢",
            intent.ticker, intent.side, intent.action,
            requested_count, filled_count, fill_price_cents, _partial, _fill_pct,
            _fee_pre, fee_cents
        )

        if filled_count >= requested_count and requested_count > 0:
            status = "filled_live"
        elif filled_count > 0:
            status = "partial_live"
            # PARTIAL FILL: Release reserved exposure for UNFILLED portion
            # The unfilled contracts never became actual position, so release their notional
            if _exp_tracker and _reserved_category and _reserved_underlying and not _is_sell:
                try:
                    _unfilled = requested_count - filled_count
                    _unfilled_notional = _unfilled * fill_price_cents / 100.0
                    _exp_tracker.release(_reserved_category, _reserved_underlying, _unfilled_notional)
                    logger.info(
                        "[order-router] Partial fill: released %s %s reserved notional for %d unfilled contracts",
                        _reserved_category, _reserved_underlying, _unfilled
                    )
                except Exception as _partial_re:
                    logger.warning("[order-router] Partial fill exposure release failed: %s", _partial_re)
        else:
            status = "accepted_live"

        # Record fill in KalshiRiskManager for rate-limit counters only.
        # Notional exposure (record_order/record_close) is handled by the calling
        # agent in _execute_signal_body or the stop-loss handler with the correct
        # category and action direction.  Calling record_order here with category=None
        # would double-count total_notional_usd for every buy fill (BUG-A fix).
        if filled_count > 0:
            try:
                from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
                get_kalshi_risk().record_rate_only()
            except Exception as _rr:
                logger.debug("record_rate_only after live fill failed (non-fatal): %s", _rr)

            # A2/RISK-03: Update ExecutionGuard daily-cap counters and cooldown.
            # Without this call, domain notional caps and cooldown never advance.
            try:
                from merid.execution_guard import get_execution_guard
                _notional_filled = filled_count * fill_price_cents / 100.0
                _domain = _get_underlying(intent.ticker)  # e.g. "BTC" → use "prediction"
                get_execution_guard().record_execution("prediction", _notional_filled)
            except Exception as _ge:
                logger.warning("[order-router] guard.record_execution failed (non-fatal): %s", _ge)

        # BUG-B fix: sell fills reduce open exposure — release the notional from the
        # tracker so category caps reflect the true remaining open position.
        if _is_sell and filled_count > 0 and _exp_tracker and _reserved_category and _reserved_underlying:
            try:
                _fill_notional = filled_count * fill_price_cents / 100.0
                _exp_tracker.release(_reserved_category, _reserved_underlying, _fill_notional)
                # DRY-RUN-TRACE: Post-fill exposure update for sells
                logger.info(
                    "[DRY-RUN-TRACE] exposure_post_fill | router_path=order_router ticker=%s side=%s action=%s | "
                    "filled_cost=%.2f fee=%d¢ | released_notional=%.2f",
                    intent.ticker, intent.side, intent.action,
                    _fill_notional, fee_cents, _fill_notional
                )
            except Exception as _sell_re:
                logger.debug("[order-router] sell exposure release failed: %s", _sell_re)

        logger.info(
            "[KALSHI_ORDER_RESULT] ticker=%s status=%s order_id=%s filled=%d source=order_router",
            intent.ticker,
            status,
            getattr(placed, "order_id", ""),
            filled_count,
        )
        try:
            from merid.prediction.ua_ct_metrics import record_order_accept

            record_order_accept()
        except Exception as e:
            logger.debug(f"Order accept metric failed: {e}")

        return OrderResult(
            status=status,
            mode=mode,
            fill={
                "ticker": intent.ticker,
                "side": intent.side,
                "action": intent.action,
                "price_cents": fill_price_cents,
                "count": filled_count,
                "requested_count": requested_count,
                "remaining_count": remaining_count,
                "fee_cents": fee_cents,
                "order_id": placed.order_id,
                "status": placed.status,
                "ts": datetime.now(timezone.utc).isoformat(),
                "simulated": False,
            },
            latency_ms=round(latency, 2),
        )
    except Exception as exc:
        latency = (time.monotonic() - t0) * 1000
        logger.error(f"[order-router] LIVE execution failed: {exc}")
        # BUG-03 fix: release reserved exposure on unexpected exception.
        if _exp_tracker and _reserved_category and _reserved_underlying:
            try:
                _exp_tracker.release(_reserved_category, _reserved_underlying, _reserved_notional)
            except Exception as _re:
                logger.debug("[order-router] exposure release failed: %s", _re)
        # BUG-11 fix: reverse the og debit on unexpected exception (was missing here).
        # CRITICAL: Use release_reservation (not record_fill) to avoid inflating matched_contracts.
        if _og_debited and _og_manager and intent.order_group_id:
            try:
                _og_manager.release_reservation(intent.order_group_id, intent.count)
                logger.debug(
                    "[order-router] Released order-group reservation on exception for %s: %d contracts",
                    intent.order_group_id, intent.count
                )
            except Exception as _ogr:
                logger.warning("[order-router] og debit rollback (exception path) failed: %s", _ogr)
        _release_gate_record(intent, f"live_execution_error:{exc}")
        return OrderResult(
            status="rejected",
            mode=mode,
            reason=f"live_execution_error:{exc}",
            latency_ms=round(latency, 2),
        )


def route_order(intent: OrderIntent) -> OrderResult:
    """Sync order routing (MOCK/PAPER only).

    LIVE mode requires ``route_order_async`` so the real Kalshi client can be
    called without blocking hacks.
    """
    t0 = time.monotonic()

    # ── Caller module audit (AGENT_WIRING_AUDIT.md) ─────────────────────
    _caller = _get_caller_module()
    _caller_allowed = _is_authorized_caller(_caller)

    # Structured audit log for production traceability
    logger.info(
        "[AUDIT] caller_check | module=%s | intent=%s | action=%s | count=%d | "
        "authorized=%s | is_known_bypass=%s",
        _caller,
        intent.ticker,
        intent.action,
        intent.count,
        _caller_allowed,
        _caller in _KNOWN_BYPASS_PATHS,
    )

    if not _caller_allowed:
        logger.error(
            "[AUDIT] UNAUTHORIZED_CALLER_REJECTED | module=%s | intent=%s | "
            "reason=not_in_allowlist_or_bypass",
            _caller, intent.ticker,
        )
        return OrderResult(
            status="rejected",
            mode=_resolve_mode(intent.mode),
            reason=f"unauthorized_caller:{_caller}",
            latency_ms=0.0,
        )
    if _caller in _KNOWN_BYPASS_PATHS:
        logger.info(
            "[AUDIT] KNOWN_BYPASS_CALLER | module=%s | intent=%s | "
            "note=documented_bypass_see_AGENT_WIRING_AUDIT",
            _caller, intent.ticker,
        )

    mode = _resolve_mode(intent.mode)

    # Risk check
    reject_reason = _check_intent_risk(intent)
    if reject_reason:
        latency = (time.monotonic() - t0) * 1000
        logger.warning(
            f"[order-router] REJECTED {intent.ticker} {intent.action} "
            f"{intent.count}x @ {intent.price_cents}c: {reject_reason}"
        )
        return OrderResult(
            status="rejected",
            mode=mode,
            reason=reject_reason,
            latency_ms=round(latency, 2),
        )

    _sent_cap = _check_sentiment_notional_cap(intent)
    if _sent_cap:
        latency = (time.monotonic() - t0) * 1000
        return OrderResult(
            status="rejected",
            mode=mode,
            reason=_sent_cap,
            latency_ms=round(latency, 2),
        )

    sanity_rejection = _check_sanity(intent, t0, mode)
    if sanity_rejection:
        return sanity_rejection

    # ── Pre-trade gate: lease + dedup + fill-awareness ────────────────
    gate_rejection = _run_pre_trade_gate(intent, mode, t0)
    if gate_rejection:
        return gate_rejection

    if _is_live_mode(mode):
        latency = (time.monotonic() - t0) * 1000
        # Fail-loud: sync route_order() must never be called in live mode.
        # The caller (CT) should use self._post() directly or route_order_async().
        logger.error(
            "[ORDER-ROUTER-BUG] route_order() called in LIVE mode for ticker=%s — "
            "live orders require route_order_async() or direct REST POST; rejecting",
            intent.ticker,
        )
        _release_gate_record(intent, "live_requires_async_route_order")
        return OrderResult(
            status="rejected",
            mode=mode,
            reason="live_requires_async_route_order",
            latency_ms=round(latency, 2),
        )

    return _route_sync_non_live(intent, mode, t0)


def _run_pre_trade_gate(
    intent: OrderIntent, mode: TradingMode, t0: float
) -> Optional[OrderResult]:
    """Run lease + dedup + fill-awareness gate.  Returns rejection or None.

    On success, mutates ``intent.client_tag`` to the deterministic
    ``client_order_id`` produced by the gate so downstream paths
    (live submission, paper simulation) use it consistently.
    """
    try:
        from merid.event_venues.kalshi.contract_lease import (
            get_contract_lease_registry,
            LeaseKey,
        )
        from merid.event_venues.kalshi.order_gate import get_pre_trade_gate

        _agent = intent.agent_id or intent.source or "unknown"
        _strategy = intent.group_id or intent.source or "default"

        # ── 1. Lease acquisition ──────────────────────────────────────
        registry = get_contract_lease_registry()
        lease_key = LeaseKey(
            venue="kalshi",
            contract_id=intent.ticker,
            side=intent.side,
            strategy_group=_strategy,
        )
        lease = registry.acquire(lease_key, owner_agent_id=_agent)
        if lease is None:
            latency = (time.monotonic() - t0) * 1000
            logger.warning(
                "[order-router] LEASE CONFLICT: %s tried to trade %s %s but "
                "another agent owns it",
                _agent, intent.ticker, intent.side,
            )
            return OrderResult(
                status="rejected",
                mode=mode,
                reason=f"lease_conflict:{intent.ticker}:{intent.side}",
                latency_ms=round(latency, 2),
            )

        # ── 2. Pre-trade gate (dedup + fill-awareness) ────────────────
        gate = get_pre_trade_gate()
        verdict = gate.check(
            agent_id=_agent,
            strategy_group=_strategy,
            contract_id=intent.ticker,
            side=intent.side,
            action=intent.action,
            target_count=intent.count,
            price_cents=intent.price_cents,
            decision_ts=intent.snapshot_ts,
            intent_id=intent.intent_id,
        )
        if not verdict.allowed:
            latency = (time.monotonic() - t0) * 1000
            logger.warning(
                "[order-router] GATE BLOCKED: %s — %s",
                intent.ticker, verdict.reason,
            )
            return OrderResult(
                status="rejected",
                mode=mode,
                reason=f"gate:{verdict.reason}",
                latency_ms=round(latency, 2),
            )

        # ── 3. Stamp the deterministic client_order_id onto intent ────
        intent.client_tag = verdict.client_order_id

    except Exception as exc:
        # Gate infrastructure failure → fail-closed
        latency = (time.monotonic() - t0) * 1000
        logger.error("[order-router] pre_trade_gate error (fail-closed): %s", exc)
        return OrderResult(
            status="rejected",
            mode=mode,
            reason=f"gate_error:{exc}",
            latency_ms=round(latency, 2),
        )

    return None  # all clear


async def route_order_async(intent: OrderIntent) -> OrderResult:
    """Async order routing that supports true LIVE execution."""
    t0 = time.monotonic()

    # ── Caller module audit (AGENT_WIRING_AUDIT.md) ─────────────────────
    _caller = _get_caller_module()
    _caller_allowed = _is_authorized_caller(_caller)

    # Structured audit log for production traceability
    logger.info(
        "[AUDIT] caller_check | module=%s | intent=%s | action=%s | count=%d | "
        "authorized=%s | is_known_bypass=%s",
        _caller,
        intent.ticker,
        intent.action,
        intent.count,
        _caller_allowed,
        _caller in _KNOWN_BYPASS_PATHS,
    )

    if not _caller_allowed:
        logger.error(
            "[AUDIT] UNAUTHORIZED_CALLER_REJECTED | module=%s | intent=%s | "
            "reason=not_in_allowlist_or_bypass",
            _caller, intent.ticker,
        )
        # Fail-closed: reject unauthorized callers
        return OrderResult(
            status="rejected",
            mode=_resolve_mode(intent.mode),
            reason=f"unauthorized_caller:{_caller}",
            latency_ms=0.0,
        )
    # Log known bypasses for audit visibility
    if _caller in _KNOWN_BYPASS_PATHS:
        logger.info(
            "[AUDIT] KNOWN_BYPASS_CALLER | module=%s | intent=%s | "
            "note=documented_bypass_see_AGENT_WIRING_AUDIT",
            _caller, intent.ticker,
        )

    mode = _resolve_mode(intent.mode)

    reject_reason = _check_intent_risk(intent)
    if reject_reason:
        latency = (time.monotonic() - t0) * 1000
        logger.warning(
            f"[order-router] REJECTED {intent.ticker} {intent.action} "
            f"{intent.count}x @ {intent.price_cents}c: {reject_reason}"
        )
        return OrderResult(
            status="rejected",
            mode=mode,
            reason=reject_reason,
            latency_ms=round(latency, 2),
        )

    _sent_cap = _check_sentiment_notional_cap(intent)
    if _sent_cap:
        latency = (time.monotonic() - t0) * 1000
        logger.warning("[order-router] REJECTED sentiment cap: %s — %s", intent.ticker, _sent_cap)
        return OrderResult(
            status="rejected",
            mode=mode,
            reason=_sent_cap,
            latency_ms=round(latency, 2),
        )

    sanity_rejection = _check_sanity(intent, t0, mode)
    if sanity_rejection:
        return sanity_rejection

    # ── Pre-trade gate: lease + dedup + fill-awareness ────────────────
    gate_rejection = _run_pre_trade_gate(intent, mode, t0)
    if gate_rejection:
        return gate_rejection

    if _is_live_mode(mode):
        return await _route_live(intent, mode, t0)

    return _route_sync_non_live(intent, mode, t0)


# ═══════════════════════════════════════════════════════════════════════════
# Hedge Engine Integration — SIZE→EXECUTE seam
# ═══════════════════════════════════════════════════════════════════════════


def compute_hedge_intents(bankroll_cents: int = 0) -> List[OrderIntent]:
    """Compute hedge OrderIntents based on current exposure snapshot.

    Safe to call from any context (sync).  Returns empty list if hedge
    engine is disabled, unavailable, or produces no orders.  Hedge orders
    carry ``source=HEDGE_ENGINE`` and ``client_tag`` prefixed ``HEDGE_``.
    """
    try:
        from merid.hedging.config import get_hedge_config
        from merid.hedging.engine import get_hedge_engine
        from merid.hedging.exposure import build_exposure_snapshot

        cfg = get_hedge_config()
        if not cfg.enabled:
            return []

        snap = build_exposure_snapshot()
        engine = get_hedge_engine()

        # Try to get market catalog for ticker resolution
        catalog = None
        try:
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            catalog = get_market_catalog()
        except Exception as e:
            logger.debug(f"Market catalog unavailable for hedge: {e}")

        result = engine.compute_hedge_orders(
            snap, cfg, bankroll_cents=bankroll_cents, market_catalog=catalog,
        )
        if not result.orders:
            return []

        intents = engine.to_order_intents(result)
        logger.info(
            "[hedge-router] Generated %d hedge intents from %d cells",
            len(intents), len(result.orders),
        )
        return intents
    except Exception as exc:
        logger.debug("[hedge-router] compute_hedge_intents failed: %s", exc)
        return []


# ═══════════════════════════════════════════════════════════════════════════
# Batch Order Placement with Order Group Assignment
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class BatchOrderIntent:
    """Batch of orders with shared order group."""
    orders: List[OrderIntent]
    order_group_id: Optional[str] = None
    self_trade_prevention_type: Optional[str] = None
    mode: Optional[TradingMode] = None


@dataclass
class BatchOrderResult:
    """Result of batch order placement."""
    total: int
    successful: int
    failed: int
    results: List[OrderResult]
    latency_ms: float
    order_group_id: Optional[str] = None


async def route_batch_orders_async(
    batch: BatchOrderIntent,
    max_concurrent: int = 5,
) -> BatchOrderResult:
    """Route multiple orders with optional shared order group.

    All orders in the batch share the same order_group_id and STP type
    if specified at the batch level. Individual order settings override
    batch-level defaults.

    Args:
        batch: Batch of orders to place
        max_concurrent: Max concurrent order placements

    Returns:
        BatchOrderResult with aggregated results
    """
    t0 = time.monotonic()

    # Apply batch-level defaults to each order
    orders: List[OrderIntent] = []
    for intent in batch.orders:
        # Merge batch-level settings
        order_group_id = intent.order_group_id or batch.order_group_id
        stp_type = intent.self_trade_prevention_type or batch.self_trade_prevention_type
        mode = intent.mode or batch.mode

        orders.append(OrderIntent(
            ticker=intent.ticker,
            side=intent.side,
            action=intent.action,
            price_cents=intent.price_cents,
            count=intent.count,
            mode=mode,
            order_type=intent.order_type,
            time_in_force=intent.time_in_force,
            edge_pct=intent.edge_pct,
            source=intent.source,
            order_group_id=order_group_id,
            self_trade_prevention_type=stp_type,
            post_only=intent.post_only,
            intent_id=intent.intent_id,
            client_tag=intent.client_tag,
            snapshot_ts=intent.snapshot_ts,
            agent_id=intent.agent_id,
            confidence=intent.confidence,
            rationale=intent.rationale,
            group_id=intent.group_id,
            parent_intent_id=intent.parent_intent_id,
            leg_index=intent.leg_index,
            decision_trace_id=intent.decision_trace_id,
            sentiment_asset=intent.sentiment_asset,
            sentiment_timeframe=intent.sentiment_timeframe,
            sentiment_driven=intent.sentiment_driven,
            data_version=intent.data_version,
        ))

    # Validate all orders first
    valid_orders: List[OrderIntent] = []
    pre_validated_results: List[OrderResult] = []

    for intent in orders:
        reject_reason = _check_intent_risk(intent)
        if reject_reason:
            pre_validated_results.append(OrderResult(
                status="rejected",
                mode=_resolve_mode(intent.mode),
                reason=f"pre_validation_failed:{reject_reason}",
                latency_ms=0.0,
            ))
        else:
            valid_orders.append(intent)

    # Route valid orders with concurrency limit
    semaphore = asyncio.Semaphore(max_concurrent)

    async def route_with_limit(intent: OrderIntent) -> OrderResult:
        async with semaphore:
            return await route_order_async(intent)

    # Execute all valid orders concurrently
    route_tasks = [route_with_limit(intent) for intent in valid_orders]
    route_results = await asyncio.gather(*route_tasks, return_exceptions=True)

    # CRASH-005: Harden result handling against None or unexpected types
    def _normalize_route_result(r, intent_ref: OrderIntent) -> OrderResult:
        if isinstance(r, OrderResult):
            return r
        if r is None:
            logger.error(
                "[CRASH-005] route_order_async returned None for %s — treating as rejection",
                intent_ref.ticker
            )
            return OrderResult(
                status="rejected",
                mode=_resolve_mode(intent_ref.mode),
                reason="routing_returned_none",
                latency_ms=0.0,
            )
        if isinstance(r, Exception):
            return OrderResult(
                status="rejected",
                mode=_resolve_mode(intent_ref.mode),
                reason=f"routing_exception:{type(r).__name__}:{str(r)[:100]}",
                latency_ms=0.0,
            )
        logger.error(
            "[CRASH-005] Unexpected route result type %s for %s — treating as rejection",
            type(r), intent_ref.ticker
        )
        return OrderResult(
            status="rejected",
            mode=_resolve_mode(intent_ref.mode),
            reason=f"unexpected_result_type:{type(r).__name__}",
            latency_ms=0.0,
        )

    # Combine pre-validation failures with routing results
    all_results = pre_validated_results + [
        _normalize_route_result(r, intent) for r, intent in zip(route_results, valid_orders)
    ]

    latency = (time.monotonic() - t0) * 1000

    successful = sum(1 for r in all_results if "filled" in r.status or "accepted" in r.status)
    failed = len(all_results) - successful

    return BatchOrderResult(
        total=len(batch.orders),
        successful=successful,
        failed=failed,
        results=all_results,
        latency_ms=round(latency, 2),
        order_group_id=batch.order_group_id,
    )

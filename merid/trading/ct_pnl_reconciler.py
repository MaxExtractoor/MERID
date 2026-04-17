"""CT PnL Reconciler — slow-cadence cross-check of CT internal state vs Kalshi API.

Compares the Continuous Trader's internal bankroll metrics against values
recomputed directly from Kalshi's /portfolio/settlements and /portfolio/positions
endpoints, then logs a structured [CT-PNL-RECONCILE] record whenever any delta
exceeds a configured threshold.

Design goals:
- **Read-only**: never mutates CT state; purely observational.
- **Fail-open**: all errors are logged at DEBUG and silently skipped — the
  reconciler must never block or disrupt the trading cycle.
- **Slow cadence**: intended to run every N cycles (default: every 30 cycles ≈
  30 minutes at a 60s interval), configurable via KALSHI_CT_RECONCILE_CYCLES.
- **Structured output**: all findings use the [CT-PNL-RECONCILE] prefix so they
  can be extracted by log parsers / alerting pipelines.

Thresholds (all configurable via env):
- KALSHI_CT_RECONCILE_PNL_DELTA_CENTS   — cents delta that triggers a WARN (default 100 = $1)
- KALSHI_CT_RECONCILE_VALUE_DELTA_CENTS — portfolio value delta threshold (default 500 = $5)
- KALSHI_CT_RECONCILE_TRADE_DELTA       — trade count delta that triggers a WARN (default 3)

Usage (called from KalshiContinuousTrader._run_cycle_inner at the end of each cycle):

    from merid.trading.ct_pnl_reconciler import maybe_reconcile
    maybe_reconcile(ct_instance)

"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, Optional

import requests

from utils.logger import get_logger

if TYPE_CHECKING:
    from merid.trading.kalshi_continuous_trader import KalshiContinuousTrader

logger = get_logger("merid.trading.ct_pnl_reconciler")

# ── Configuration ──────────────────────────────────────────────────────────────

_RECONCILE_EVERY_N_CYCLES: int = int(os.getenv("KALSHI_CT_RECONCILE_CYCLES", "30"))
_PNL_DELTA_THRESHOLD_CENTS: int = int(os.getenv("KALSHI_CT_RECONCILE_PNL_DELTA_CENTS", "100"))
_VALUE_DELTA_THRESHOLD_CENTS: int = int(os.getenv("KALSHI_CT_RECONCILE_VALUE_DELTA_CENTS", "500"))
_TRADE_DELTA_THRESHOLD: int = int(os.getenv("KALSHI_CT_RECONCILE_TRADE_DELTA", "3"))

# Lookback window for /portfolio/settlements (seconds).  30 days is generous;
# Kalshi only returns positions that are currently open, so this matters mainly
# for settlement PnL aggregation.
_SETTLEMENTS_LOOKBACK_SECONDS: int = int(
    os.getenv("KALSHI_CT_RECONCILE_LOOKBACK_S", str(30 * 24 * 3600))
)

# ── Public entry point ─────────────────────────────────────────────────────────


def maybe_reconcile(ct: "KalshiContinuousTrader") -> None:
    """Run reconciliation if the cycle counter indicates it is time.

    Safe to call unconditionally at the end of every CT cycle — it returns
    immediately on non-reconcile cycles, and swallows all exceptions.
    """
    try:
        cycle = getattr(ct, "_cycle", 0)
        if _RECONCILE_EVERY_N_CYCLES <= 0:
            return
        if cycle == 0 or (cycle % _RECONCILE_EVERY_N_CYCLES) != 0:
            return
        _run_reconcile(ct)
    except Exception as exc:
        logger.debug("[CT-PNL-RECONCILE] reconcile dispatcher error (ignored): %s", exc)


# ── Core reconciliation logic ──────────────────────────────────────────────────


def _run_reconcile(ct: "KalshiContinuousTrader") -> None:
    """Fetch Kalshi API state and compare against CT internal metrics."""
    t0 = time.monotonic()
    bm = ct.bankroll
    cycle = ct._cycle

    # ── Internal CT state ────────────────────────────────────────────
    internal_pnl_cents: int = bm.total_pnl_cents
    internal_trades: int = bm.total_trades
    # portfolio_cents is cached each cycle from positions total_cost (BUG-35 fix);
    # available balance is fetched live below — store it here after the API call.
    internal_portfolio_cents: int = ct._last_portfolio_cents

    # ── API calls (all synchronous via CT _get / _sign) ────────────
    api_balance_cents: Optional[int] = _fetch_available_balance_cents(ct)
    api_portfolio_cents: Optional[int] = _fetch_portfolio_cents(ct)
    api_realized_pnl_cents: Optional[int] = _fetch_realized_pnl_cents(ct)

    elapsed_ms = int((time.monotonic() - t0) * 1000)

    # ── Derive internal total value (balance from API + cached portfolio) ──
    # BankrollManager does not store available balance — it is fetched live.
    # Use the freshly fetched api_balance_cents as the balance component so
    # internal_value_cents and api_total_value_cents share the same balance
    # source (eliminating a timing skew in the comparison).
    internal_value_cents: Optional[int] = (
        api_balance_cents + internal_portfolio_cents
        if api_balance_cents is not None
        else None
    )

    # ── Derive API-side total value ──────────────────────────────────
    api_total_value_cents: Optional[int] = (
        api_balance_cents + api_portfolio_cents
        if api_balance_cents is not None and api_portfolio_cents is not None
        else None
    )

    # ── Compute deltas ───────────────────────────────────────────────
    pnl_delta: Optional[int] = (
        abs(internal_pnl_cents - api_realized_pnl_cents)
        if api_realized_pnl_cents is not None
        else None
    )
    value_delta: Optional[int] = (
        abs(internal_value_cents - api_total_value_cents)
        if internal_value_cents is not None and api_total_value_cents is not None
        else None
    )

    # ── Determine severity ───────────────────────────────────────────
    pnl_exceeded = pnl_delta is not None and pnl_delta > _PNL_DELTA_THRESHOLD_CENTS
    value_exceeded = value_delta is not None and value_delta > _VALUE_DELTA_THRESHOLD_CENTS
    any_exceeded = pnl_exceeded or value_exceeded

    log_fn = logger.warning if any_exceeded else logger.info

    log_fn(
        "[CT-PNL-RECONCILE] cycle=%d fetch_ms=%d | "
        "internal: pnl=%+d¢ trades=%d portfolio=%d¢ value=%s¢ | "
        "api: pnl=%s¢ balance=%s¢ portfolio=%s¢ total_value=%s¢ | "
        "delta: pnl=%s¢%s value=%s¢%s",
        cycle,
        elapsed_ms,
        # internal
        internal_pnl_cents,
        internal_trades,
        internal_portfolio_cents,
        _fmt(internal_value_cents),
        # api
        _fmt(api_realized_pnl_cents),
        _fmt(api_balance_cents),
        _fmt(api_portfolio_cents),
        _fmt(api_total_value_cents),
        # deltas
        _fmt(pnl_delta),
        " \u26a0 EXCEEDS THRESHOLD" if pnl_exceeded else "",
        _fmt(value_delta),
        " \u26a0 EXCEEDS THRESHOLD" if value_exceeded else "",
    )

    if any_exceeded:
        logger.warning(
            "[CT-PNL-RECONCILE] THRESHOLDS: pnl_threshold=%d¢ value_threshold=%d¢ — "
            "investigate settlement gaps or duplicate records in RealizedEdgeStore",
            _PNL_DELTA_THRESHOLD_CENTS,
            _VALUE_DELTA_THRESHOLD_CENTS,
        )


# ── Kalshi API fetchers (synchronous, reuse CT _get / _sign) ──────────────────


def _fetch_available_balance_cents(ct: "KalshiContinuousTrader") -> Optional[int]:
    """Fetch available balance from /portfolio/balance."""
    try:
        r: requests.Response = ct._get("/portfolio/balance")
        if r.status_code == 200:
            d = r.json()
            return int(d.get("balance", 0))
        logger.debug("[CT-PNL-RECONCILE] /portfolio/balance HTTP %d", r.status_code)
    except Exception as exc:
        logger.debug("[CT-PNL-RECONCILE] balance fetch error: %s", exc)
    return None


def _fetch_portfolio_cents(ct: "KalshiContinuousTrader") -> Optional[int]:
    """Fetch portfolio value (total_cost) from /portfolio/positions.

    Sums total_cost across all market_positions — matches BUG-35 logic used in
    the run cycle so the two numbers are directly comparable.
    """
    try:
        total_cost = 0
        cursor: Optional[str] = None
        for _page in range(10):  # safety cap
            params: dict = {"limit": 200}
            if cursor:
                params["cursor"] = cursor
            r: requests.Response = ct._get("/portfolio/positions", params=params)
            if r.status_code != 200:
                logger.debug("[CT-PNL-RECONCILE] /portfolio/positions HTTP %d", r.status_code)
                break
            data = r.json()
            for p in data.get("market_positions", data.get("positions", [])):
                total_cost += int(p.get("total_cost", 0))
            cursor = data.get("cursor")
            if not cursor:
                break
        return total_cost
    except Exception as exc:
        logger.debug("[CT-PNL-RECONCILE] positions fetch error: %s", exc)
    return None


def _fetch_realized_pnl_cents(ct: "KalshiContinuousTrader") -> Optional[int]:
    """Fetch realized PnL from /portfolio/settlements.

    Sums realized_profit across all settlement records within the lookback
    window.  Kalshi returns realized_profit in cents for binary markets.
    """
    try:
        from datetime import datetime, timezone, timedelta

        now = datetime.now(timezone.utc)
        lookback_start = (now - timedelta(seconds=_SETTLEMENTS_LOOKBACK_SECONDS)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        total_pnl = 0
        cursor: Optional[str] = None
        for _page in range(20):  # safety cap — 200 items/page × 20 = 4000 settlements
            params: dict = {
                "limit": 200,
                "settled_after": lookback_start,
            }
            if cursor:
                params["cursor"] = cursor
            r: requests.Response = ct._get("/portfolio/settlements", params=params)
            if r.status_code != 200:
                logger.debug("[CT-PNL-RECONCILE] /portfolio/settlements HTTP %d", r.status_code)
                break
            data = r.json()
            for s in data.get("settlements", []):
                # realized_profit is the net PnL in cents for that settlement
                total_pnl += int(s.get("realized_profit", 0))
            cursor = data.get("cursor")
            if not cursor:
                break
        return total_pnl
    except Exception as exc:
        logger.debug("[CT-PNL-RECONCILE] settlements fetch error: %s", exc)
    return None


# ── Helpers ───────────────────────────────────────────────────────────────────


def _fmt(v: Optional[int]) -> str:
    return str(v) if v is not None else "n/a"

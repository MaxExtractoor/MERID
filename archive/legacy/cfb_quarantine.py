"""CFB RTI metadata and settlement awareness for Kalshi crypto markets.

CF Benchmarks settlement methodology
-------------------------------------
Kalshi crypto contracts (BTC/ETH/SOL/XRP/DOGE across 15m, hourly, daily, weekly)
settle to CF Benchmarks Real-Time Indices (BRTI, ETHUSD_RTI, XRPUSD_RTI, etc.).
CFB uses a time-weighted, partitioned-median approach:

  1. Relevant transactions from pre-qualified Constituent exchanges during a
     defined TWAP window (e.g. 16:00-16:30 London time for daily settlement).
  2. The window is split into equal time bins; each bin produces a
     volume-weighted median price across all eligible exchanges.
  3. The final CF Settlement Price is the equally weighted average of these
     per-bin volume-weighted medians.
  4. Per-bin outlier detection: exchanges deviating beyond tolerance from the
     cross-exchange median are excluded for that bin.
  5. Fallback: if all exchanges flagged or data missing, prior day price used.

For RTI-based products (Kalshi 15m/hourly), CF applies a similar TWAP over the
RTI feed before settlement time, producing Options Settlement Rates aligned with
EU BMR and CFTC-style rules.

Quarantine status: DISABLED
---------------------------
The quarantine is permanently disabled.  Kalshi handles official settlement via
CFB indices — MERID does not need a separate licensed RTI feed to trade these
markets.  The ``is_cfb_anchored_market()`` and related detection functions are
preserved for informational tagging (e.g. marking markets as CFB-settled in the
UI) but no longer gate order flow.

Env vars (informational only — no longer gate trading):
  MERID_CFB_RTI_ADAPTER   — "live" if a local RTI adapter is running
  MERID_CFB_RTI_POLL_URL  — RTI adapter poll endpoint
  MERID_CFB_RTI_API_KEY   — RTI adapter auth token
"""
from __future__ import annotations

import os
from typing import Any, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.cfb_quarantine")

_QUARANTINE_LOGGED = False

# ── CFB index token list ──────────────────────────────────────────────────────
# Matched case-insensitively against the joined text blob of a market's
# title / description / rules / resolution_source / category fields.
# Ordered: longer / more-specific tokens first to reduce false-positive risk.
_CFB_TOKENS: List[str] = [
    "cf benchmarks",       # full brand name in rules text
    "cfbenchmarks",        # URL / compact form
    "real-time index",     # generic RTI description
    "real time index",
    "brti",                # Bitcoin Real-Time Index
    "ethusd_rti",
    "ethusd_rr",
    "xrpusd_rti",
    "xrpusd_rr",
    "solusd_rti",
    "dogeusd_rti",
    "_rti",                # catch-all <ASSET>USD_RTI suffix
    "_rr",                 # catch-all <ASSET>USD_RR  suffix
    "brr",                 # Bitcoin Reference Rate
]

# Category shortcut: Kalshi tags all these crypto-related series under "crypto".
# Treat any market whose category field contains "crypto" as CFB-anchored.
_CFB_CATEGORIES = frozenset({"crypto"})


# ── Adapter / mode helpers ────────────────────────────────────────────────────

def is_cfb_rti_live() -> bool:
    """True only when adapter is explicitly ``live`` with a configured poll URL."""
    mode = os.environ.get("MERID_CFB_RTI_ADAPTER", "null").strip().lower()
    if mode != "live":
        return False
    poll_url = os.environ.get("MERID_CFB_RTI_POLL_URL", "").strip()
    sim = os.environ.get("MERID_CFB_RTI_SIMULATE", "").strip() == "1"
    return bool(poll_url) or sim


def cfb_rti_mode() -> str:
    """Return normalized adapter mode string."""
    return os.environ.get("MERID_CFB_RTI_ADAPTER", "null").strip().lower() or "null"


def should_quarantine_rti_markets() -> bool:
    """Always returns False — quarantine is permanently disabled.

    Kalshi crypto markets settle to CF Benchmarks indices (BRTI, ETHUSD_RTI,
    etc.) which are public and transparent.  Kalshi handles official settlement;
    MERID does not need a separate licensed RTI feed to trade.

    The detection functions (``is_cfb_anchored_market``, etc.) are preserved for
    informational tagging but no longer gate order flow.
    """
    return False


# ── Metadata-based detection ─────────────────────────────────────────────────

def _market_text_blob(market: Any) -> str:
    """Extract a single lowercase text blob from any market representation.

    Handles:
    - ``dict`` (raw Kalshi API response, FilterPipeline input)
    - ``EventMarket`` dataclass (from ``merid.event_venues.base``)
    - ``CatalogMarket`` wrapper (from ``market_catalog``)
    """
    if isinstance(market, dict):
        parts = [
            market.get("title", ""),
            market.get("question", ""),
            market.get("description", ""),
            market.get("category", ""),
            market.get("rules", ""),
            market.get("rules_primary", ""),
            market.get("rules_secondary", ""),
            market.get("resolution_source", ""),
            market.get("ticker", ""),
            market.get("market_id", ""),
            market.get("event_ticker", ""),
            market.get("series_ticker", ""),
        ]
    else:
        # CatalogMarket has a nested .market (EventMarket); EventMarket is direct.
        em = getattr(market, "market", market)
        raw = getattr(em, "raw_data", None) or {}
        parts = [
            getattr(em, "question", "") or "",
            getattr(em, "description", "") or "",
            getattr(em, "category", "") or "",
            getattr(em, "market_id", "") or "",
            raw.get("rules_primary", "") or "",
            raw.get("rules_secondary", "") or "",
            raw.get("resolution_source", "") or "",
            raw.get("event_ticker", "") or "",
            raw.get("series_ticker", "") or "",
            # CatalogMarket exposes .category/.asset at the wrapper level too
            getattr(market, "category", "") or "",
            getattr(market, "asset", "") or "",
        ]
    return " ".join(str(p) for p in parts if p).lower()


def is_cfb_anchored_market(market: Any) -> bool:
    """True if *market* is a Kalshi contract that settles to a CFB RTI.

    Uses full metadata string-matching (primary) with no dependency on ticker
    patterns — catches any new Kalshi series that references CF Benchmarks.

    Quick shortcut: category == "crypto" is treated as CFB-anchored because
    all current Kalshi crypto series (BTC/ETH/SOL/XRP/DOGE) settle to CFB RTIs.
    """
    blob = _market_text_blob(market)

    # Fast path: category field
    if isinstance(market, dict):
        cat = (market.get("category") or "").lower()
    else:
        em = getattr(market, "market", market)
        cat = (getattr(market, "category", None) or getattr(em, "category", None) or "").lower()
    if cat in _CFB_CATEGORIES:
        return True

    # Slower path: scan full text blob for CFB index tokens
    return any(tok in blob for tok in _CFB_TOKENS)


def filter_out_cfb_markets(markets: List[Any]) -> List[Any]:
    """Return *markets* with all CFB-anchored entries removed.

    Applies regardless of quarantine state — callers decide when to invoke this.
    """
    return [m for m in markets if not is_cfb_anchored_market(m)]


def enforce_cfb_safety(markets: List[Any]) -> List[Any]:
    """Drop CFB-anchored markets from *markets* when quarantine is active.

    Safety invariant:
      KALSHI_ENV=live + no live CFB adapter → crypto RTI markets removed.
      KALSHI_ENV=live + live CFB adapter    → markets untouched.

    Call this at startup / catalog ingest, not on every order.
    """
    if not should_quarantine_rti_markets():
        return markets
    filtered = filter_out_cfb_markets(markets)
    removed = len(markets) - len(filtered)
    if removed:
        logger.warning(
            "CFB_RTI_QUARANTINE: enforce_cfb_safety removed %d CFB-anchored markets "
            "(adapter=%r); set MERID_CFB_RTI_ADAPTER=live to trade crypto",
            removed,
            cfb_rti_mode(),
        )
    return filtered


# ── Ticker-based secondary check (kept for execution-guard path) ─────────────

def evaluate_rti_quarantine(ticker: str) -> Optional[str]:
    """Always returns None — quarantine is permanently disabled.

    Preserved for API compatibility.  All crypto tickers are tradeable.
    """
    return None


# ── Startup log ───────────────────────────────────────────────────────────────

def log_quarantine_status() -> None:
    """Emit a single startup log line describing the active quarantine posture."""
    global _QUARANTINE_LOGGED
    if _QUARANTINE_LOGGED:
        return
    _QUARANTINE_LOGGED = True

    kalshi_env = os.environ.get("KALSHI_ENV", "demo").strip().lower()
    logger.info(
        "CFB settlement: quarantine=DISABLED kalshi_env=%s — "
        "all crypto markets (BTC/ETH/SOL/XRP/DOGE) tradeable across all timeframes. "
        "Settlement via CF Benchmarks TWAP partitioned-median methodology.",
        kalshi_env,
    )


def reset_quarantine_log() -> None:
    """Reset boot-logged flag (test helper)."""
    global _QUARANTINE_LOGGED
    _QUARANTINE_LOGGED = False

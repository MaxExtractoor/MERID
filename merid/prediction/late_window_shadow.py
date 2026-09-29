"""Read-only late-window (30-90s TTE) shadow scorer — research only.

The live engine hard-stops new entries inside ``MERID_ENTRY_MIN_SECONDS_TO_EXPIRY``
/ the regime TTE floor.  Before any live relaxation of that cutoff is even
considered, the counterfactual has to be measured: what would a dedicated
late-window regime have done, at the *executable* quotes actually available?

Every TTE-floor signal rejection inside the shadow band emits one JSONL
record carrying the observable state at rejection time:

- asset / ticker / side(s) that would have been evaluated,
- TTE bucketed into 10-second bands,
- executable YES/NO asks (and bids when available) — the real entry prices,
- spread where derivable,
- spot / strike / resolved annualized vol (the Bachelier inputs needed to
  reprice the contract offline),
- which gate rejected it and why.

An offline replay joins these records to ``logs/settlement_outcomes.jsonl``
by ticker, reconstructs the Bachelier settlement probability for each side,
prices a post-only maker fill at the recorded quotes, and reports realized
settlement P&L with a 1-2c execution/adverse-selection stress applied.

This module NEVER touches order routing, position state, or the bankroll.
It is appended to the signal-rejection path only.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

ROOT = Path(__file__).resolve().parents[2]

# Reasons produced by the TTE floor at each layer: the regime classifier's
# time bound, the min-entry-TTE gate, and the final-minute exit-only cutoff.
LATE_TTE_REASONS = frozenset({
    "tte_entry_cutoff",
    "min_tte_entry_disabled",
    "final_minute_entry_disabled",
})


def enabled() -> bool:
    return os.environ.get("MERID_LATE_WINDOW_SHADOW", "1").strip().lower() in (
        "1", "true", "yes",
    )


def band_lo_s() -> float:
    return float(os.environ.get("MERID_LATE_SHADOW_MIN_TTE_S", "30"))


def band_hi_s() -> float:
    return float(os.environ.get("MERID_LATE_SHADOW_MAX_TTE_S", "90"))


def _log_path() -> Path:
    custom = os.environ.get("MERID_LATE_WINDOW_SHADOW_LOG_PATH")
    if custom:
        return Path(custom)
    return ROOT / "logs" / "late_window_shadow.jsonl"


def tte_band_10s(tte_seconds: Optional[float]) -> Optional[str]:
    """10-second TTE band label, e.g. '50-60s'."""
    if tte_seconds is None:
        return None
    t = float(tte_seconds)
    lo = int(t // 10) * 10
    return f"{lo}-{lo + 10}s"


def in_band(tte_seconds: Optional[float]) -> bool:
    if tte_seconds is None:
        return False
    return band_lo_s() <= float(tte_seconds) < band_hi_s()


def asset_from_ticker(ticker: Optional[str]) -> Optional[str]:
    if not ticker:
        return None
    t = str(ticker).upper()
    for a in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
        if t.startswith(f"KX{a}"):
            return a
    return None


def build_record(
    reason: str,
    *,
    ticker: Optional[str],
    asset: Optional[str],
    spot_price: Optional[float],
    strike: Optional[float],
    seconds_to_expiry: Optional[float],
    yes_ask_cents: Optional[float],
    no_ask_cents: Optional[float],
    yes_bid_cents: Optional[float] = None,
    no_bid_cents: Optional[float] = None,
    annualized_vol: Optional[float] = None,
    annualized_vol_source: Optional[str] = None,
    run_id: Optional[str] = None,
    decision_id: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Assemble one shadow record; None if outside the band or unusable."""
    if not in_band(seconds_to_expiry):
        return None
    tte = float(seconds_to_expiry)
    spread_cents = None
    if yes_ask_cents is not None and yes_bid_cents is not None:
        try:
            spread_cents = round(float(yes_ask_cents) - float(yes_bid_cents), 2)
        except (TypeError, ValueError):
            spread_cents = None
    return {
        "schema": "late_window_shadow_v1",
        "ts_utc": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()),
        "run_id": run_id,
        "decision_id": decision_id,
        "ticker": ticker,
        "asset": asset or asset_from_ticker(ticker),
        "seconds_to_expiry": round(tte, 1),
        "tte_band_10s": tte_band_10s(tte),
        "rejection_reason": reason,
        # A late-window entry would be a passive post-only quote; the replay
        # evaluates maker fills at the recorded ask/bid, not taker sweeps.
        "hypothetical_mode": "post_only_maker",
        "yes_ask_cents": yes_ask_cents,
        "no_ask_cents": no_ask_cents,
        "yes_bid_cents": yes_bid_cents,
        "no_bid_cents": no_bid_cents,
        "spread_cents": spread_cents,
        "spot_price": spot_price,
        "strike": strike,
        "annualized_vol": annualized_vol,
        "annualized_vol_source": annualized_vol_source,
        "extra": extra or {},
    }


def write_record(record: Dict[str, Any]) -> None:
    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, default=str) + "\n")

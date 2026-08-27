#!/usr/bin/env python3
"""Exit-strategy A/B replay harness for Kalshi 15m crypto.

Replays recorded fills, EXIT_EVAL telemetry, and settlement outcomes to compare
three exit policies on real market paths:

    1. PURE_HOLD       - never exit; hold every position to settlement
    2. SAFETY_RAILS    - exit only on risk/time/settlement/99c safety reasons
    3. FULL_ACTIVE     - use every recorded live trigger (take-profit, trailing,
                         ratchet, etc.)

The harness is intentionally standalone and read-only: it never touches the
exchange, the live database, or the order router.  It writes its report to
``reports/exit_strategy_replay.json`` by default.

Inputs
------
- ``data/kalshi_fills.db``         SQLite fills ledger (canonical position side/action)
- ``logs/full.log``                Application log containing ``[EXIT_EVAL]`` JSON lines
- ``logs/settlement_outcomes.jsonl`` Kalshi settlement outcomes exported by
  ``merid.analysis.settlement_outcome_exporter``

Outputs
-------
- ``reports/exit_strategy_replay.json``   Structured per-round-trip and aggregate stats
- stdout                                 Markdown summary table

Usage
-----
    python analysis/exit_strategy_replay.py
    python analysis/exit_strategy_replay.py --fee-model conservative --correlation-cap 2.0
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sqlite3
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Allow the script to be run from the repo root as ``python analysis/exit_strategy_replay.py``.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── Configuration constants ─────────────────────────────────────────────────

CRYPTO_ASSETS = ("BTC", "ETH", "SOL", "XRP", "DOGE")

# Exit reasons considered *active* profit/ratchet/trailing/model-driven exits.
ACTIVE_EXIT_REASONS = frozenset({
    "take_profit",
    "dynamic_take_profit",
    "trail",
    "trailing_stop",
    "ratchet_trim",
    "ratchet_floor",
    "scale_out",
    "opportunity_cost",
    "adaptive_timing",
    "candle_reversal",
    "edge_decay",
    "current_edge_reversal",
    "extreme_profit",
})

# Exit reasons considered *safety* rails.  Everything else is hold-to-settlement.
SAFETY_EXIT_REASONS = frozenset({
    "risk",
    "stale_data",
    "stop_loss",
    "hard_stop",
    "soft_stop",
    "settlement_guard",
    "market_expired",
    "auto_exit_99c",
    "manual",
    "time_stop",
    "loss_cut_40pct",
    "loss_cap",
    "model_invalidation_loss_exit",
    "continuation_stop",
})

# Maximum time between an EXIT_EVAL trigger and an actual fill for us to treat
# the fill as the execution of that trigger.
TRIGGER_FILL_MATCH_WINDOW_SECONDS = 10.0

# Conservative fee / slippage assumptions for the sensitivity band.
CONSERVATIVE_FEE_RATE = Decimal("0.07")
CONSERVATIVE_SLIPPAGE_CENTS = 2


# ── Data classes ────────────────────────────────────────────────────────────

@dataclass
class Fill:
    fill_id: str
    market_ticker: str
    side: str          # 'yes' or 'no' (canonical position side)
    action: str        # 'buy' or 'sell' (canonical position action)
    quantity_cc: int   # absolute centi-contracts
    signed_yes_delta: float  # signed contracts in YES space (positive = long YES)
    price_cents: float
    fee_cents: float
    created_time: datetime
    client_order_id: Optional[str] = None
    order_id: Optional[str] = None


@dataclass
class ExitEval:
    ts: datetime
    ticker: str
    position_id: Optional[str]
    side: str
    qty: float
    avg_entry_price_cents: float
    current_price_cents: float
    executable_close_price_cents: Optional[float]
    target_hit: bool
    exit_reason: Optional[str]
    decision: str
    reason_code: str
    book_valid: bool
    book_age_ms: Optional[float]
    data_source: Optional[str]
    data_quality: Optional[str]


@dataclass
class RoundTrip:
    market_ticker: str
    side: str
    size: float
    entry_price_cents: float
    entry_fee_cents: float
    entry_time: datetime
    exit_time: Optional[datetime] = None
    exit_price_cents: Optional[float] = None
    exit_fee_cents: float = 0.0
    exit_reason: Optional[str] = None
    filled: bool = True
    unfilled_reason: Optional[str] = None
    rescue_trigger_time: Optional[datetime] = None
    settlement_price_cents: Optional[float] = None
    outcome: Optional[str] = None
    gross_pnl_cents: float = 0.0
    net_pnl_cents: float = 0.0
    total_fees_cents: float = 0.0
    hold_time_seconds: float = 0.0
    strategy: str = ""
    actual_exit: bool = False  # True if this round-trip was actually closed by a fill
    expected_close_time: Optional[datetime] = None
    excluded_by_cap: bool = False


@dataclass
class StrategyResult:
    name: str
    round_trips: List[RoundTrip] = field(default_factory=list)
    gross_pnl_cents: float = 0.0
    net_pnl_cents: float = 0.0
    total_fees_cents: float = 0.0
    wins: int = 0
    losses: int = 0
    exits: int = 0
    unfilled_exits: int = 0
    avg_hold_time_seconds: float = 0.0
    max_drawdown_cents: float = 0.0
    correlation_cap: Optional[float] = None


@dataclass
class TriggerMatch:
    """A single comparison between an actual fill and its nearest EXIT_EVAL trigger."""
    market_ticker: str
    side: str
    size: float
    actual_exit_time: datetime
    actual_exit_price_cents: float
    actual_exit_fee_cents: float
    trigger_time: Optional[datetime]
    trigger_price_cents: Optional[float]
    trigger_reason: Optional[str]
    active_exit_time: Optional[datetime]
    active_exit_price_cents: Optional[float]
    active_reason: Optional[str]
    active_filled: bool
    active_rescued: bool
    price_gap_cents: Optional[float]
    time_gap_seconds: Optional[float]
    active_price_gap_cents: Optional[float]
    active_time_gap_seconds: Optional[float]
    status: str
    actual_gross_pnl_cents: float = 0.0
    actual_net_pnl_cents: float = 0.0


# ── Helpers ─────────────────────────────────────────────────────────────────

def parse_iso_ts(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        # Handle 'Z' suffix and common ISO variants.
        s = s.replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except Exception:
        return None


def fee_dollars_to_cents(d: Any) -> float:
    if d is None:
        return 0.0
    try:
        dec = Decimal(str(d))
        return float((dec * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except Exception:
        return 0.0


def _row_value(row: sqlite3.Row, key: str, default: Any = None) -> Any:
    """Return a SQLite row value, defaulting if the column does not exist."""
    try:
        return row[key]
    except (KeyError, IndexError):
        return default


def safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except Exception:
        return default


def extract_json_after_tag(line: str, tag: str) -> Optional[Dict[str, Any]]:
    """Extract a JSON object from a log line after a marker like ``[EXIT_EVAL]``.

    Works with both text-format logs and JSON-format logs where the message
    field already contains the tag.
    """
    idx = line.find(tag)
    if idx < 0:
        return None
    payload = line[idx + len(tag):].strip()
    # Text-format logs may have leading log metadata; find the first '{'.
    start = payload.find("{")
    if start < 0:
        return None
    payload = payload[start:]
    try:
        return json.loads(payload)
    except Exception:
        return None


def calculate_fee_at_rate(contracts: float, price_cents: float, rate: Decimal) -> float:
    """Kalshi fee formula with an explicit rate (used by conservative sensitivity)."""
    if contracts <= 0 or price_cents <= 0 or price_cents >= 100:
        return 0.0
    p = Decimal(str(price_cents)) / Decimal("100")
    raw = rate * Decimal(str(contracts)) * p * (Decimal("1") - p)
    fee_cents = float((raw * Decimal("100")).quantize(Decimal("1"), rounding="ROUND_CEILING"))
    return max(fee_cents, 1.0) if fee_cents > 0 else 0.0


# ── Data loading ────────────────────────────────────────────────────────────

def load_settlements(path: Path) -> Dict[str, Dict[str, Any]]:
    """Load settlement outcomes keyed by ticker."""
    outcomes: Dict[str, Dict[str, Any]] = {}
    if not path.exists():
        print(f"[WARN] settlement outcomes not found: {path}")
        return outcomes
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except Exception:
                continue
            ticker = record.get("ticker") or record.get("market_id")
            if not ticker:
                continue
            ticker = str(ticker).upper()
            outcome = record.get("outcome")
            if outcome:
                outcome = str(outcome).lower().strip()
            resolved_yes = record.get("resolved_yes")
            if resolved_yes is None and outcome:
                resolved_yes = 1 if outcome == "yes" else 0
            settle_ts = parse_iso_ts(record.get("settlement_timestamp_utc"))
            outcomes[ticker] = {
                "outcome": outcome,
                "resolved_yes": resolved_yes,
                "settlement_timestamp_utc": settle_ts,
                "source": record.get("settlement_source", "unknown"),
            }
    return outcomes


def _row_to_fill(row: sqlite3.Row) -> Optional[Fill]:
    """Convert a raw fills DB row into a canonical Fill."""
    market_ticker = str(row["market_ticker"]).upper().strip() if row["market_ticker"] else None
    if not market_ticker:
        return None

    # Canonical side / action are the position-effect fields.  Fall back to raw.
    side = _row_value(row, "canonical_position_side") or _row_value(row, "side")
    action = _row_value(row, "canonical_position_action") or _row_value(row, "action")
    if side is None or action is None:
        return None
    side = str(side).lower().strip()
    action = str(action).lower().strip()

    # Signed YES exposure: positive = long YES, negative = long NO.
    signed_delta_cc = _row_value(row, "canonical_yes_delta_cc")
    if signed_delta_cc is None:
        qty_cc = safe_int(_row_value(row, "quantity_cc"))
        # quantity_cc is absolute; derive sign from side/action.
        if side == "yes" and action == "buy":
            signed_delta_cc = qty_cc
        elif side == "yes" and action == "sell":
            signed_delta_cc = -qty_cc
        elif side == "no" and action == "buy":
            signed_delta_cc = -qty_cc
        elif side == "no" and action == "sell":
            signed_delta_cc = qty_cc
        else:
            return None
    else:
        signed_delta_cc = int(signed_delta_cc)

    # Price in own-side cents.
    price_cents = _row_value(row, "canonical_leg_price_cents")
    if price_cents is None:
        if side == "yes":
            price_dollars = _row_value(row, "yes_price_dollars")
        else:
            price_dollars = _row_value(row, "no_price_dollars")
        price_cents = int(float(price_dollars) * 100) if price_dollars else 0
    price_cents = safe_float(price_cents)

    fee_cents = _row_value(row, "fee_cents")
    if fee_cents is None:
        fee_cents = fee_dollars_to_cents(_row_value(row, "fee_cost"))
    else:
        fee_cents = safe_float(fee_cents)

    created = parse_iso_ts(_row_value(row, "created_time"))
    if created is None:
        return None

    return Fill(
        fill_id=str(_row_value(row, "fill_id")),
        market_ticker=market_ticker,
        side=side,
        action=action,
        quantity_cc=abs(signed_delta_cc),
        signed_yes_delta=signed_delta_cc / 100.0,
        price_cents=price_cents,
        fee_cents=fee_cents,
        created_time=created,
        client_order_id=_row_value(row, "client_order_id"),
        order_id=_row_value(row, "order_id"),
    )


def load_fills(db_path: Path) -> List[Fill]:
    """Load non-hedge alpha fills from the fills ledger."""
    fills: List[Fill] = []
    if not db_path.exists():
        print(f"[WARN] fills db not found: {db_path}")
        return fills
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        # Filter out hedge fills.  Side/action fallback happens in _row_to_fill.
        cur.execute(
            """
            SELECT *
            FROM kalshi_fills
            WHERE (fill_source IS NULL OR fill_source != 'hedge')
            ORDER BY created_time ASC
            """
        )
        for row in cur:
            f = _row_to_fill(row)
            if f:
                fills.append(f)
    except Exception as exc:
        print(f"[WARN] failed to read fills db: {exc}")
    return fills


def _resolve_log_paths(log_path: Path, since: Optional[datetime] = None) -> List[Path]:
    """Expand a single log path into a list of files (supports glob and rotated logs)."""
    if not log_path.exists() and any(c in str(log_path) for c in "*?["):
        # Treat as glob relative to the parent directory.
        matches = sorted(log_path.parent.glob(log_path.name))
    elif log_path.is_dir():
        matches = sorted(log_path.glob("full.log*"))
    elif log_path.is_file():
        matches = [log_path]
    else:
        # Plain pattern like 'logs/full.log*' without glob metacharacters: try glob anyway.
        matches = sorted(log_path.parent.glob(log_path.name))

    if since is None:
        return matches

    # Filter out files whose last-modified time is well before the lookback cutoff.
    buffer_seconds = 3600.0
    cutoff_ts = since.timestamp() - buffer_seconds
    filtered = [p for p in matches if p.stat().st_mtime >= cutoff_ts]
    return filtered


def parse_exit_eval_log(log_path: Path, since: Optional[datetime] = None) -> List[ExitEval]:
    """Parse ``[EXIT_EVAL]`` records from one or more log files (glob/rotated logs supported)."""
    records: List[ExitEval] = []
    paths = _resolve_log_paths(log_path, since=since)
    if not paths:
        print(f"[WARN] no log files found for: {log_path}")
        return records

    for path in paths:
        with path.open("r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue

                # Support both JSON-format and text-format logs.
                envelope_ts: Optional[datetime] = None
                if line.startswith("{"):
                    try:
                        envelope = json.loads(line)
                        message = envelope.get("message", "")
                        envelope_ts = parse_iso_ts(envelope.get("ts"))
                    except Exception:
                        continue
                    if "[EXIT_EVAL]" not in message:
                        continue
                    payload = extract_json_after_tag(message, "[EXIT_EVAL]")
                else:
                    if "[EXIT_EVAL]" not in line:
                        continue
                    payload = extract_json_after_tag(line, "[EXIT_EVAL]")

                if not payload:
                    continue

                ts = parse_iso_ts(payload.get("ts") or payload.get("timestamp")) or envelope_ts
                if ts is None:
                    ts = parse_iso_ts(payload.get("@timestamp"))
                if ts is None:
                    continue
                if since is not None and ts < since:
                    continue

                side = str(payload.get("position_side", "")).lower().strip()
                qty = safe_float(payload.get("position_qty_fp"))
                avg_entry = safe_float(payload.get("avg_entry_price_cents"))
                unrealized = safe_float(payload.get("unrealized_pnl_cents"))
                current_price = avg_entry
                if qty != 0:
                    current_price = avg_entry + (unrealized / qty)

                executable = payload.get("executable_close_price_cents")
                if executable is None or executable == "None":
                    executable = None
                else:
                    executable = safe_float(executable)

                records.append(ExitEval(
                    ts=ts,
                    ticker=str(payload.get("ticker", "")).upper().strip(),
                    position_id=str(payload.get("position_id")) if payload.get("position_id") else None,
                    side=side,
                    qty=qty,
                    avg_entry_price_cents=avg_entry,
                    current_price_cents=current_price,
                    executable_close_price_cents=executable,
                    target_hit=bool(payload.get("target_hit", False)),
                    exit_reason=str(payload.get("exit_reason")).lower().strip() if payload.get("exit_reason") else None,
                    decision=str(payload.get("decision", "")),
                    reason_code=str(payload.get("reason_code", "")),
                    book_valid=bool(payload.get("book_valid", False)),
                    book_age_ms=safe_float(payload.get("book_age_ms")) or None,
                    data_source=str(payload.get("data_source")) if payload.get("data_source") else None,
                    data_quality=str(payload.get("data_quality")) if payload.get("data_quality") else None,
                ))

    records.sort(key=lambda x: x.ts)
    return records


# ── Position reconstruction ─────────────────────────────────────────────────

def reconstruct_round_trips(fills: List[Fill]) -> List[RoundTrip]:
    """Reconstruct FIFO round trips from the fills ledger.

    Each entry lot is tracked separately.  When a sell reduces the position,
    the oldest entry lots are closed first.  Round trips with no closing fill
    are left open (they will be closed at settlement in the simulation).
    """
    by_ticker: Dict[str, List[Fill]] = defaultdict(list)
    for f in fills:
        by_ticker[f.market_ticker].append(f)

    round_trips: List[RoundTrip] = []
    unmatched_sell_count = 0
    unmatched_sell_examples: List[str] = []

    for ticker, ticker_fills in by_ticker.items():
        ticker_fills.sort(key=lambda f: f.created_time)
        lots: List[Fill] = []  # open lots (each is a buy fill)

        for fill in ticker_fills:
            if fill.action == "buy":
                lots.append(fill)
                continue

            # Sell: close lots FIFO.
            remaining = abs(fill.signed_yes_delta)
            total_exit_size = remaining
            while remaining > 1e-9 and lots:
                lot = lots[0]
                if lot.side != fill.side:
                    break
                lot_size = abs(lot.signed_yes_delta)
                close_size = min(remaining, lot_size)

                entry_fee = lot.fee_cents * (close_size / lot_size) if lot_size > 0 else 0
                # Attribute exit fee proportionally to the amount of this fill that closes this lot.
                exit_fee = fill.fee_cents * (close_size / total_exit_size) if total_exit_size > 0 else 0

                rt = RoundTrip(
                    market_ticker=ticker,
                    side=lot.side,
                    size=close_size,
                    entry_price_cents=lot.price_cents,
                    entry_fee_cents=entry_fee,
                    entry_time=lot.created_time,
                    exit_time=fill.created_time,
                    exit_price_cents=fill.price_cents,
                    exit_fee_cents=exit_fee,
                    exit_reason="ACTUAL_FILL",
                    actual_exit=True,
                )
                round_trips.append(rt)

                lot_size -= close_size
                if lot_size <= 1e-9:
                    lots.pop(0)
                else:
                    lot.signed_yes_delta = lot_size if lot.side == "yes" else -lot_size
                remaining -= close_size

            if remaining > 1e-9:
                # A sell with no matching long lot is either a short/hedge, stale
                # data, or a cross-leg fill.  Ignore it so it does not distort the
                # replay.  (Hedge fills are already filtered out at load time.)
                unmatched_sell_count += 1
                if len(unmatched_sell_examples) < 3:
                    unmatched_sell_examples.append(
                        f"{remaining:.2f} {fill.side} {ticker}"
                    )

        # Any lots still open at the end of the fill stream are held to settlement
        # in the actual active path (or the DB snapshot is from before settlement).
        for lot in lots:
            round_trips.append(RoundTrip(
                market_ticker=ticker,
                side=lot.side,
                size=abs(lot.signed_yes_delta),
                entry_price_cents=lot.price_cents,
                entry_fee_cents=lot.fee_cents,
                entry_time=lot.created_time,
                actual_exit=False,
            ))

    round_trips.sort(key=lambda x: x.entry_time)
    if unmatched_sell_count:
        print(
            f"[INFO] ignored {unmatched_sell_count} unmatched/hedge sells; "
            f"examples: {', '.join(unmatched_sell_examples)}"
        )
    return round_trips


# ── Simulation ─────────────────────────────────────────────────────────────-

def find_exit_trigger(
    rt: RoundTrip,
    exit_evals: List[ExitEval],
    allowed_reasons: Optional[frozenset],
    min_time_after_entry: float = 0.0,
) -> Optional[ExitEval]:
    """Find the first EXIT_EVAL trigger for this round trip matching allowed reasons."""
    for ev in exit_evals:
        if ev.ticker != rt.market_ticker:
            continue
        if ev.ts < rt.entry_time:
            continue
        if (ev.ts - rt.entry_time).total_seconds() < min_time_after_entry:
            continue
        if not ev.target_hit:
            continue
        if allowed_reasons is not None and ev.exit_reason not in allowed_reasons:
            continue
        return ev
    return None


def find_next_valid_trigger(
    rt: RoundTrip,
    exit_evals: List[ExitEval],
    allowed_reasons: Optional[frozenset],
    after: datetime,
    max_age_seconds: float = 60.0,
    rescue: bool = True,
) -> Optional[ExitEval]:
    if not rescue:
        return None
    """Look for a later trigger that has a valid book for rescue."""
    for ev in exit_evals:
        if ev.ticker != rt.market_ticker:
            continue
        if ev.ts <= after:
            continue
        if (ev.ts - after).total_seconds() > max_age_seconds:
            return None
        if not ev.target_hit:
            continue
        if allowed_reasons is not None and ev.exit_reason not in allowed_reasons:
            continue
        if not ev.book_valid or ev.executable_close_price_cents is None:
            continue
        if ev.executable_close_price_cents <= 0:
            continue
        return ev
    return None


def simulate_exit(
    rt: RoundTrip,
    ev: Optional[ExitEval],
    exit_evals: List[ExitEval],
    allowed_reasons: Optional[frozenset],
    settlement: Optional[Dict[str, Any]],
    fee_model: str,
    rescue: bool = True,
    fill_price_haircut_cents: float = 0.0,
) -> RoundTrip:
    """Return a new RoundTrip with simulated exit PnL for a single trigger."""
    sim = RoundTrip(
        market_ticker=rt.market_ticker,
        side=rt.side,
        size=rt.size,
        entry_price_cents=rt.entry_price_cents,
        entry_fee_cents=rt.entry_fee_cents,
        entry_time=rt.entry_time,
        actual_exit=rt.actual_exit,
    )

    outcome = settlement.get("outcome") if settlement else None
    settle_ts = settlement.get("settlement_timestamp_utc") if settlement else None
    sim.outcome = outcome
    sim.settlement_price_cents = 0.0

    if not ev:
        # Hold to settlement.
        sim.exit_reason = "HOLD_TO_SETTLEMENT"
        sim.exit_time = settle_ts
        own_settlement = _own_settlement_cents(sim.side, outcome)
        sim.settlement_price_cents = own_settlement
        sim.exit_price_cents = own_settlement
        sim.exit_fee_cents = 0.0
        sim.gross_pnl_cents = (own_settlement - sim.entry_price_cents) * sim.size
    else:
        sim.exit_time = ev.ts
        sim.exit_reason = ev.exit_reason

        if not ev.book_valid or ev.executable_close_price_cents is None or ev.executable_close_price_cents <= 0:
            # Trigger fired but the book was not executable.  Try a rescue within 60s.
            rescue_ev = find_next_valid_trigger(rt, exit_evals, allowed_reasons, after=ev.ts, rescue=rescue)
            if rescue_ev:
                sim.rescue_trigger_time = rescue_ev.ts
                sim.exit_time = rescue_ev.ts
                ev = rescue_ev
            else:
                # Could not rescue: record unfilled and hold to settlement.
                sim.filled = False
                sim.unfilled_reason = _unfilled_reason(ev)
                sim.exit_time = settle_ts
                sim.exit_reason = f"UNFILLED_{ev.exit_reason}"
                own_settlement = _own_settlement_cents(sim.side, outcome)
                sim.settlement_price_cents = own_settlement
                sim.exit_price_cents = own_settlement
                sim.exit_fee_cents = 0.0
                sim.gross_pnl_cents = (own_settlement - sim.entry_price_cents) * sim.size

        if sim.filled:
            exit_price = ev.executable_close_price_cents
            exit_price = max(0.0, exit_price - fill_price_haircut_cents)
            if fee_model == "conservative":
                exit_price = max(0.0, exit_price - CONSERVATIVE_SLIPPAGE_CENTS)
                fee_rate = CONSERVATIVE_FEE_RATE
            else:
                # Live schedule: for the 1-2 contract sizes in this product the small
                # tier (7%) is the only relevant tier, so we use a flat 7% estimate.
                fee_rate = Decimal("0.07")
            sim.exit_fee_cents = calculate_fee_at_rate(sim.size, exit_price, fee_rate)
            sim.exit_price_cents = exit_price
            sim.gross_pnl_cents = (exit_price - sim.entry_price_cents) * sim.size

    sim.total_fees_cents = sim.entry_fee_cents + sim.exit_fee_cents
    sim.net_pnl_cents = sim.gross_pnl_cents - sim.total_fees_cents
    if sim.exit_time and sim.entry_time:
        sim.hold_time_seconds = (sim.exit_time - sim.entry_time).total_seconds()
    return sim


def _own_settlement_cents(side: str, outcome: Optional[str]) -> float:
    if outcome is None:
        return 0.0
    if (side == "yes" and outcome == "yes") or (side == "no" and outcome == "no"):
        return 100.0
    return 0.0


def _unfilled_reason(ev: ExitEval) -> str:
    if not ev.book_valid:
        return "book_invalid"
    if ev.executable_close_price_cents is None:
        return "no_executable_price"
    if ev.executable_close_price_cents <= 0:
        return "zero_bid"
    if ev.data_quality in ("stale", "expired", "synthetic"):
        return f"stale_or_synthetic_data:{ev.data_quality}"
    return "unknown"


# Global variable used by simulate_exit for rescue lookups (set in run_replay).
all_exit_evals: List[ExitEval] = []


def apply_correlation_cap(
    round_trips: List[RoundTrip],
    cap_usd: float,
) -> List[RoundTrip]:
    """Return only round trips that would have been accepted under a crypto-correlated cap.

    A new position is accepted only if total notional of all currently open
    crypto positions is below ``cap_usd`` after the trade.  Positions are
    considered open until ``expected_close_time`` (actual exit fill or settlement).
    """
    if cap_usd <= 0:
        return round_trips

    accepted: List[RoundTrip] = []
    open_positions: List[RoundTrip] = []
    rejected_count = 0

    for rt in sorted(round_trips, key=lambda x: x.entry_time):
        # Evict positions that have already closed by this entry time.
        open_positions = [
            o for o in open_positions
            if o.expected_close_time is None or o.expected_close_time >= rt.entry_time
        ]
        open_notional = sum(o.size * o.entry_price_cents / 100.0 for o in open_positions)
        new_notional = rt.size * rt.entry_price_cents / 100.0
        if open_notional + new_notional <= cap_usd + 1e-9:
            accepted.append(rt)
            open_positions.append(rt)
        else:
            # Position would be rejected by the cap.
            rt.excluded_by_cap = True
            rejected_count += 1

    if rejected_count:
        print(f"[INFO] correlation cap rejected {rejected_count} / {len(round_trips)} round trips")
    return accepted


def run_strategy(
    name: str,
    round_trips: List[RoundTrip],
    exit_evals: List[ExitEval],
    settlements: Dict[str, Dict[str, Any]],
    allowed_reasons: Optional[frozenset],
    fee_model: str,
    cap: Optional[float],
    rescue: bool = True,
    fill_price_haircut_cents: float = 0.0,
) -> StrategyResult:
    """Simulate one exit strategy over a set of round trips."""
    if cap is not None:
        round_trips = apply_correlation_cap(round_trips, cap)

    result = StrategyResult(name=name, correlation_cap=cap)
    for rt in round_trips:
        settlement = settlements.get(rt.market_ticker)
        ev = find_exit_trigger(rt, exit_evals, allowed_reasons)
        sim = simulate_exit(rt, ev, exit_evals, allowed_reasons, settlement, fee_model, rescue=rescue, fill_price_haircut_cents=fill_price_haircut_cents)
        sim.strategy = name
        result.round_trips.append(sim)
        result.gross_pnl_cents += sim.gross_pnl_cents
        result.net_pnl_cents += sim.net_pnl_cents
        result.total_fees_cents += sim.total_fees_cents
        if sim.gross_pnl_cents > 0:
            result.wins += 1
        elif sim.gross_pnl_cents < 0:
            result.losses += 1
        if sim.filled and sim.exit_reason != "HOLD_TO_SETTLEMENT":
            result.exits += 1
        elif not sim.filled:
            result.unfilled_exits += 1

    if result.round_trips:
        result.avg_hold_time_seconds = sum(rt.hold_time_seconds for rt in result.round_trips) / len(result.round_trips)
    return result


def compute_drawdown(round_trips: List[RoundTrip]) -> float:
    """Very simple drawdown: worst cumulative net PnL trough in realized-time order."""
    peak = 0.0
    dd = 0.0
    running = 0.0
    for rt in sorted(round_trips, key=lambda x: x.exit_time or x.entry_time):
        running += rt.net_pnl_cents
        if running > peak:
            peak = running
        dd = max(dd, peak - running)
    return dd


def compute_actual_active_result(
    name: str,
    round_trips: List[RoundTrip],
    settlements: Dict[str, Dict[str, Any]],
    cap: Optional[float],
) -> StrategyResult:
    """Compute the realized active PnL directly from recorded fills and settlements.

    This is the actual production path: entries and exits as they occurred.  It is
    a validation reference for the full_active simulation.
    """
    if cap is not None:
        round_trips = apply_correlation_cap(round_trips, cap)

    result = StrategyResult(name=name, correlation_cap=cap)
    for rt in round_trips:
        settlement = settlements.get(rt.market_ticker)
        outcome = settlement.get("outcome") if settlement else None

        if rt.actual_exit and rt.exit_price_cents is not None:
            # Realized exit from an actual fill.
            gross = (rt.exit_price_cents - rt.entry_price_cents) * rt.size
            fees = rt.entry_fee_cents + rt.exit_fee_cents
            exit_time = rt.exit_time
        else:
            # Held to settlement (or the DB snapshot is before settlement).
            settle_price = _own_settlement_cents(rt.side, outcome)
            gross = (settle_price - rt.entry_price_cents) * rt.size
            fees = rt.entry_fee_cents
            exit_time = settlement.get("settlement_timestamp_utc") if settlement else None

        sim = RoundTrip(
            market_ticker=rt.market_ticker,
            side=rt.side,
            size=rt.size,
            entry_price_cents=rt.entry_price_cents,
            entry_fee_cents=rt.entry_fee_cents,
            entry_time=rt.entry_time,
            exit_time=exit_time,
            exit_price_cents=rt.exit_price_cents if rt.actual_exit else settle_price,
            exit_fee_cents=rt.exit_fee_cents if rt.actual_exit else 0.0,
            exit_reason="ACTUAL_ACTIVE" if rt.actual_exit else "HOLD_TO_SETTLEMENT",
            filled=True,
            settlement_price_cents=settle_price,
            outcome=outcome,
            gross_pnl_cents=gross,
            total_fees_cents=fees,
            net_pnl_cents=gross - fees,
            hold_time_seconds=(exit_time - rt.entry_time).total_seconds() if exit_time else 0.0,
            strategy=name,
            actual_exit=rt.actual_exit,
        )
        result.round_trips.append(sim)
        result.gross_pnl_cents += gross
        result.total_fees_cents += fees
        result.net_pnl_cents += gross - fees
        if gross > 0:
            result.wins += 1
        elif gross < 0:
            result.losses += 1
        if rt.actual_exit:
            result.exits += 1

    if result.round_trips:
        result.avg_hold_time_seconds = sum(r.hold_time_seconds for r in result.round_trips) / len(result.round_trips)
    return result


def _assign_expected_close_times(
    round_trips: List[RoundTrip],
    settlements: Dict[str, Dict[str, Any]],
    default_hold_seconds: float = 900.0,
) -> None:
    """Pre-compute an expected close time for each round trip for cap accounting.

    This is intentionally approximate: it lets the cap simulation use real exit
    fills and settlement times when known, and falls back to the 15m contract
    lifetime otherwise.
    """
    for rt in round_trips:
        if rt.exit_time is not None:
            rt.expected_close_time = rt.exit_time
            continue
        settlement = settlements.get(rt.market_ticker)
        if settlement and settlement.get("settlement_timestamp_utc"):
            rt.expected_close_time = settlement["settlement_timestamp_utc"]
        else:
            rt.expected_close_time = rt.entry_time + timedelta(seconds=default_hold_seconds)


def compute_worst_case_drawdown(round_trips: List[RoundTrip]) -> Tuple[float, float]:
    """Sweep open positions and return peak notional and worst-case crash loss.

    A correlated crash is modeled as every open position immediately going to 0,
    so the worst-case loss at any instant is the sum of entry notional of all
    open positions.  ``peak_notional`` is the worst such number in dollars.
    """
    if not round_trips:
        return 0.0, 0.0

    events = []
    for rt in round_trips:
        if rt.expected_close_time is None:
            continue
        notional = rt.size * rt.entry_price_cents / 100.0
        events.append((rt.entry_time, +1, notional))
        events.append((rt.expected_close_time, -1, notional))

    events.sort(key=lambda x: (x[0], -x[1]))  # closes before opens at same timestamp
    peak = 0.0
    open_notional = 0.0
    for _, delta, notional in events:
        open_notional += delta * notional
        peak = max(peak, open_notional)
    return peak, -peak


def run_cap_stress(
    round_trips: List[RoundTrip],
    exit_evals: List[ExitEval],
    settlements: Dict[str, Dict[str, Any]],
    cap: float,
    fee_model: str,
    default_hold_seconds: float = 900.0,
) -> Dict[str, Any]:
    """Run pure-hold with every position held to the full 15m expiry under the cap.

    This gives the cap-stress PnL and the worst-case correlated-crash loss with
    and without the cap binding.
    """
    # Copy and reset expected close times to the full hold period.
    stress_rts = [
        RoundTrip(
            market_ticker=rt.market_ticker,
            side=rt.side,
            size=rt.size,
            entry_price_cents=rt.entry_price_cents,
            entry_fee_cents=rt.entry_fee_cents,
            entry_time=rt.entry_time,
            exit_time=rt.exit_time,
            exit_price_cents=rt.exit_price_cents,
            exit_fee_cents=rt.exit_fee_cents,
            exit_reason=rt.exit_reason,
            filled=rt.filled,
            actual_exit=rt.actual_exit,
            expected_close_time=rt.entry_time + timedelta(seconds=default_hold_seconds),
        )
        for rt in round_trips
    ]

    # No-cap baseline.
    all_peak, all_drawdown = compute_worst_case_drawdown(stress_rts)
    pure_nocap = run_strategy(
        "pure_hold_stress_nocap", stress_rts, exit_evals, settlements,
        frozenset(), fee_model, cap=None,
    )

    # With cap.
    accepted = apply_correlation_cap(stress_rts, cap)
    accepted_peak, accepted_drawdown = compute_worst_case_drawdown(accepted)
    pure_cap = run_strategy(
        "pure_hold_stress_cap", accepted, exit_evals, settlements,
        frozenset(), fee_model, cap=None,
    )

    return {
        "cap_usd": cap,
        "hold_seconds": default_hold_seconds,
        "total_positions": len(stress_rts),
        "accepted_positions": len(accepted),
        "rejected_positions": len(stress_rts) - len(accepted),
        "peak_open_notional_nocap_usd": all_peak,
        "worst_case_drawdown_nocap_usd": all_drawdown,
        "peak_open_notional_cap_usd": accepted_peak,
        "worst_case_drawdown_cap_usd": accepted_drawdown,
        "pure_hold_nocap_net_pnl_cents": pure_nocap.net_pnl_cents,
        "pure_hold_cap_net_pnl_cents": pure_cap.net_pnl_cents,
    }


def print_cap_stress_report(report: Dict[str, Any]) -> None:
    print("\n## Correlated-Exposure Cap Stress: 15m Hold-to-Settlement\n")
    print(f"Positions total: {report['total_positions']:<3}  accepted under ${report['cap_usd']} cap: {report['accepted_positions']:<3}  rejected: {report['rejected_positions']}")
    print()
    print(f"{'Scenario':<30} {'Peak Notional':>14} {'Worst-Case DD':>16} {'Net PnL':>12}")
    print("-" * 78)
    print(
        f"{'No cap':<30} {fmt_dollars(report['peak_open_notional_nocap_usd']):>14} "
        f"{fmt_dollars(report['worst_case_drawdown_nocap_usd']):>16} "
        f"{fmt_cents(report['pure_hold_nocap_net_pnl_cents']):>12}"
    )
    print(
        f"{'With $2 cap':<30} {fmt_dollars(report['peak_open_notional_cap_usd']):>14} "
        f"{fmt_dollars(report['worst_case_drawdown_cap_usd']):>16} "
        f"{fmt_cents(report['pure_hold_cap_net_pnl_cents']):>12}"
    )
    print()


def fmt_dollars(v: float) -> str:
    return f"${v:,.2f}"


def find_nearest_trigger(
    ticker: str,
    anchor: datetime,
    exit_evals: List[ExitEval],
    window_before: float = 30.0,
    window_after: float = 10.0,
) -> Optional[ExitEval]:
    """Find the nearest target-hit EXIT_EVAL trigger around an actual fill time."""
    best: Optional[ExitEval] = None
    best_gap = float("inf")
    for ev in exit_evals:
        if ev.ticker != ticker or not ev.target_hit:
            continue
        if ev.executable_close_price_cents is None or ev.executable_close_price_cents <= 0:
            continue
        gap = (ev.ts - anchor).total_seconds()
        if gap < -window_before or gap > window_after:
            continue
        abs_gap = abs(gap)
        if abs_gap < best_gap:
            best_gap = abs_gap
            best = ev
    return best


def active_exit_triggered(sim: RoundTrip) -> bool:
    """Return True if the simulated round trip exited (not hold, not unfilled)."""
    return (
        sim.filled
        and sim.exit_reason is not None
        and sim.exit_reason != "HOLD_TO_SETTLEMENT"
        and not sim.exit_reason.startswith("UNFILLED_")
    )


def actual_fill_slippage(
    actual_round_trips: List[RoundTrip],
    sim_round_trips: List[RoundTrip],
    exit_evals: List[ExitEval],
) -> Tuple[List[TriggerMatch], Dict[str, Any]]:
    """Compare actual fills to their nearest EXIT_EVAL trigger and to the active simulation."""
    matches: List[TriggerMatch] = []

    for actual, sim in zip(actual_round_trips, sim_round_trips):
        if not actual.actual_exit:
            continue

        trigger = find_nearest_trigger(
            actual.market_ticker,
            actual.exit_time or actual.entry_time,
            exit_evals,
        )

        price_gap = None
        time_gap = None
        if trigger and trigger.executable_close_price_cents is not None:
            price_gap = (actual.exit_price_cents or 0.0) - trigger.executable_close_price_cents
            if actual.exit_time and trigger.ts:
                time_gap = (actual.exit_time - trigger.ts).total_seconds()

        active_price_gap = None
        active_time_gap = None
        active_triggered = active_exit_triggered(sim)
        if active_triggered and sim.exit_time and actual.exit_time:
            active_price_gap = (actual.exit_price_cents or 0.0) - (sim.exit_price_cents or 0.0)
            active_time_gap = (actual.exit_time - sim.exit_time).total_seconds()

        if trigger is None:
            status = "no_exit_eval"
        elif not active_triggered:
            status = "active_held_or_unfilled"
        elif active_time_gap is not None and abs(active_time_gap) <= 15.0:
            status = "aligned"
        else:
            status = "active_different_time"

        matches.append(TriggerMatch(
            market_ticker=actual.market_ticker,
            side=actual.side,
            size=actual.size,
            actual_exit_time=actual.exit_time or actual.entry_time,
            actual_exit_price_cents=actual.exit_price_cents or 0.0,
            actual_exit_fee_cents=actual.exit_fee_cents or 0.0,
            trigger_time=trigger.ts if trigger else None,
            trigger_price_cents=trigger.executable_close_price_cents if trigger else None,
            trigger_reason=trigger.exit_reason if trigger else None,
            active_exit_time=sim.exit_time if active_triggered else None,
            active_exit_price_cents=sim.exit_price_cents if active_triggered else None,
            active_reason=sim.exit_reason if active_triggered else None,
            active_filled=sim.filled,
            active_rescued=sim.rescue_trigger_time is not None,
            price_gap_cents=price_gap,
            time_gap_seconds=time_gap,
            active_price_gap_cents=active_price_gap,
            active_time_gap_seconds=active_time_gap,
            status=status,
            actual_gross_pnl_cents=((actual.exit_price_cents or 0.0) - actual.entry_price_cents) * actual.size,
            actual_net_pnl_cents=(((actual.exit_price_cents or 0.0) - actual.entry_price_cents) * actual.size) - (actual.entry_fee_cents + (actual.exit_fee_cents or 0.0)),
        ))

    summary = _summarize_slippage(matches, actual_round_trips)
    return matches, summary


def _summarize_slippage(matches: List[TriggerMatch], actual_round_trips: List[RoundTrip]) -> Dict[str, Any]:
    """Compute aggregate slippage statistics."""
    if not matches:
        return {}

    by_status: Dict[str, int] = {}
    for m in matches:
        by_status[m.status] = by_status.get(m.status, 0) + 1

    # Aggregate actual PnL by the reason of the matched trigger (production path by reason).
    reason_pnl: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"count": 0, "gross_pnl_cents": 0.0, "net_pnl_cents": 0.0, "fees_cents": 0.0}
    )
    for m in matches:
        reason = m.trigger_reason or "no_exit_eval"
        reason_pnl[reason]["count"] += 1
        reason_pnl[reason]["gross_pnl_cents"] += m.actual_gross_pnl_cents
        reason_pnl[reason]["net_pnl_cents"] += m.actual_net_pnl_cents
        reason_pnl[reason]["fees_cents"] += m.actual_exit_fee_cents + (m.actual_exit_fee_cents or 0.0)

    # Holds (no actual exit) attributed to HOLD_TO_SETTLEMENT.
    hold_gross = 0.0
    hold_net = 0.0
    hold_fees = 0.0
    hold_count = 0
    for rt in actual_round_trips:
        if rt.actual_exit:
            continue
        hold_count += 1
        # Settlement PnL will be computed elsewhere; here we leave placeholders.
        # We omit from this breakdown because it requires settlement mapping.
        # Instead, we record count only.
    if hold_count:
        reason_pnl["HOLD_TO_SETTLEMENT"] = {
            "count": hold_count,
            "gross_pnl_cents": hold_gross,
            "net_pnl_cents": hold_net,
            "fees_cents": hold_fees,
            "note": "settlement PnL omitted; see actual_active result for full hold PnL",
        }

    # Stats over every actual exit that found a trigger (nearest to the fill).
    with_trigger = [m for m in matches if m.price_gap_cents is not None]
    price_gaps = [m.price_gap_cents for m in with_trigger]
    time_gaps = [m.time_gap_seconds for m in with_trigger if m.time_gap_seconds is not None]
    active_price_gaps = [m.active_price_gap_cents for m in with_trigger if m.active_price_gap_cents is not None]
    active_time_gaps = [m.active_time_gap_seconds for m in with_trigger if m.active_time_gap_seconds is not None]

    def _stats(values: List[float]) -> Dict[str, float]:
        if not values:
            return {}
        return {
            "n": len(values),
            "mean": sum(values) / len(values),
            "median": sorted(values)[len(values) // 2] if values else 0.0,
            "min": min(values),
            "max": max(values),
        }

    # Where a real fill exists, the median gap between the nearest trigger price
    # and the actual fill is the data-driven execution slippage.  A positive gap
    # means the actual fill was better than the trigger; we only apply a haircut
    # when the actual fill was worse (negative gap).
    trigger_gap_stats = _stats(price_gaps)
    median_nearest_gap = trigger_gap_stats.get("median", 0.0)
    empirical_slippage_haircut_cents = max(0.0, -median_nearest_gap)

    return {
        "total_actual_exits": len(matches),
        "by_status": by_status,
        "actual_pnl_by_matched_reason": dict(reason_pnl),
        "trigger_vs_actual_price_gap_cents": trigger_gap_stats,
        "trigger_vs_actual_time_gap_seconds": _stats(time_gaps),
        "active_sim_vs_actual_price_gap_cents": _stats(active_price_gaps),
        "active_sim_vs_actual_time_gap_seconds": _stats(active_time_gaps),
        "median_nearest_price_gap_cents": median_nearest_gap,
        "empirical_slippage_haircut_cents": empirical_slippage_haircut_cents,
    }


def per_exit_reason_breakdown(result: StrategyResult) -> Dict[str, Dict[str, Any]]:
    """Aggregate PnL by exit reason for a strategy."""
    groups: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {
            "count": 0,
            "wins": 0,
            "losses": 0,
            "unfilled": 0,
            "holds": 0,
            "gross_pnl_cents": 0.0,
            "net_pnl_cents": 0.0,
            "fees_cents": 0.0,
            "avg_hold_time_seconds": 0.0,
        }
    )
    for rt in result.round_trips:
        reason = rt.exit_reason or "HOLD_TO_SETTLEMENT"
        if not rt.filled and not reason.startswith("HOLD_TO_SETTLEMENT"):
            if not reason.startswith("UNFILLED_"):
                reason = f"UNFILLED_{reason}"
        g = groups[reason]
        g["count"] += 1
        g["gross_pnl_cents"] += rt.gross_pnl_cents
        g["net_pnl_cents"] += rt.net_pnl_cents
        g["fees_cents"] += rt.total_fees_cents
        g["avg_hold_time_seconds"] += rt.hold_time_seconds
        if not rt.filled and not reason.startswith("HOLD_TO_SETTLEMENT"):
            g["unfilled"] += 1
        if reason == "HOLD_TO_SETTLEMENT":
            g["holds"] += 1
        if rt.gross_pnl_cents > 0:
            g["wins"] += 1
        elif rt.gross_pnl_cents < 0:
            g["losses"] += 1

    for g in groups.values():
        if g["count"]:
            g["avg_hold_time_seconds"] /= g["count"]
    return dict(groups)


# ── Reporting ───────────────────────────────────────────────────────────────

def fmt_cents(c: float) -> str:
    return f"${c / 100.0:,.2f}"


def print_summary_table(results: List[StrategyResult]) -> None:
    print("\n## Exit Strategy A/B Replay Results\n")
    header = (
        f"{'Strategy':<18} {'Trades':>7} {'Wins':>5} {'Losses':>7} "
        f"{'Exits':>6} {'Unfilled':>9} {'Gross PnL':>11} {'Fees':>10} {'Net PnL':>11} "
        f"{'Avg Hold(s)':>12} {'Max DD':>10}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r.name:<18} {len(r.round_trips):>7} {r.wins:>5} {r.losses:>7} "
            f"{r.exits:>6} {r.unfilled_exits:>9} {fmt_cents(r.gross_pnl_cents):>11} "
            f"{fmt_cents(r.total_fees_cents):>10} {fmt_cents(r.net_pnl_cents):>11} "
            f"{r.avg_hold_time_seconds:>12.1f} {fmt_cents(r.max_drawdown_cents):>10}"
        )
    print()


def build_report(
    pure: StrategyResult,
    safety: StrategyResult,
    active: StrategyResult,
    actual_active: StrategyResult,
    safety_no_rescue: StrategyResult,
    active_no_rescue: StrategyResult,
    safety_calibrated: StrategyResult,
    active_calibrated: StrategyResult,
    fee_model: str,
    cap: Optional[float],
    diagnostics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    for r in (pure, safety, active, actual_active, safety_no_rescue, active_no_rescue, safety_calibrated, active_calibrated):
        r.max_drawdown_cents = compute_drawdown(r.round_trips)

    report: Dict[str, Any] = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "fee_model": fee_model,
            "correlation_cap_usd": cap,
            "active_exit_reasons": sorted(ACTIVE_EXIT_REASONS),
            "safety_exit_reasons": sorted(SAFETY_EXIT_REASONS),
        },
        "summary": {
            "pure_hold": _strategy_summary(pure),
            "safety_rails": _strategy_summary(safety),
            "full_active": _strategy_summary(active),
            "actual_active": _strategy_summary(actual_active),
            "safety_rails_no_rescue": _strategy_summary(safety_no_rescue),
            "full_active_no_rescue": _strategy_summary(active_no_rescue),
            "safety_rails_calibrated": _strategy_summary(safety_calibrated),
            "full_active_calibrated": _strategy_summary(active_calibrated),
        },
        "round_trips": {
            "pure_hold": [asdict(rt) for rt in pure.round_trips],
            "safety_rails": [asdict(rt) for rt in safety.round_trips],
            "full_active": [asdict(rt) for rt in active.round_trips],
            "actual_active": [asdict(rt) for rt in actual_active.round_trips],
            "safety_rails_no_rescue": [asdict(rt) for rt in safety_no_rescue.round_trips],
            "full_active_no_rescue": [asdict(rt) for rt in active_no_rescue.round_trips],
            "safety_rails_calibrated": [asdict(rt) for rt in safety_calibrated.round_trips],
            "full_active_calibrated": [asdict(rt) for rt in active_calibrated.round_trips],
        },
    }
    if diagnostics:
        report["diagnostics"] = diagnostics
    return report


def _strategy_summary(r: StrategyResult) -> Dict[str, Any]:
    return {
        "trades": len(r.round_trips),
        "wins": r.wins,
        "losses": r.losses,
        "exits": r.exits,
        "unfilled_exits": r.unfilled_exits,
        "gross_pnl_cents": r.gross_pnl_cents,
        "fees_cents": r.total_fees_cents,
        "net_pnl_cents": r.net_pnl_cents,
        "avg_hold_time_seconds": r.avg_hold_time_seconds,
        "max_drawdown_cents": r.max_drawdown_cents,
    }


def _make_rt_key(rt: RoundTrip) -> Tuple[str, str, float]:
    """Stable key for aligning a round trip across simulations."""
    return (rt.market_ticker, rt.entry_time.isoformat(), rt.size)


def print_slippage_diagnostics(
    actual_round_trips: List[RoundTrip],
    active_result: StrategyResult,
    exit_evals: List[ExitEval],
    actual_active: StrategyResult,
) -> Tuple[List[TriggerMatch], Dict[str, Any]]:
    """Print and return actual-fill vs EXIT_EVAL slippage diagnostics."""
    sim_by_key = {_make_rt_key(rt): rt for rt in active_result.round_trips}
    aligned_actual: List[RoundTrip] = []
    aligned_sim: List[RoundTrip] = []
    for rt in actual_round_trips:
        sim = sim_by_key.get(_make_rt_key(rt))
        if sim is not None:
            aligned_actual.append(rt)
            aligned_sim.append(sim)

    matches, summary = actual_fill_slippage(aligned_actual, aligned_sim, exit_evals)

    # Backfill actual hold-to-settlement PnL into the reason breakdown.
    reason_pnl = summary.get("actual_pnl_by_matched_reason", {})
    hold_entries = [rt for rt in actual_active.round_trips if not rt.actual_exit]
    if hold_entries:
        reason_pnl["HOLD_TO_SETTLEMENT"] = {
            "count": len(hold_entries),
            "gross_pnl_cents": sum(rt.gross_pnl_cents for rt in hold_entries),
            "net_pnl_cents": sum(rt.net_pnl_cents for rt in hold_entries),
            "fees_cents": sum(rt.total_fees_cents for rt in hold_entries),
        }

    if not matches:
        print("\n## Actual-Fill vs EXIT_EVAL Slippage\n\nNo actual exits found in the lookback.")
        return matches, summary

    print("\n## Actual-Fill vs EXIT_EVAL Slippage\n")
    print(f"Total actual exits in replay: {summary.get('total_actual_exits', 0)}")
    print("Status distribution:")
    for status, count in (summary.get("by_status") or {}).items():
        print(f"  {status:<30} {count:>4}")
    print()

    def _print_stats(label: str, stats: Dict[str, float]) -> None:
        if not stats:
            return
        print(
            f"{label:45} n={stats.get('n',0):>3}  "
            f"mean={stats.get('mean',0):>7.2f}  "
            f"median={stats.get('median',0):>7.2f}  "
            f"min={stats.get('min',0):>7.2f}  "
            f"max={stats.get('max',0):>7.2f}"
        )

    _print_stats(
        "EXIT_EVAL trigger price vs actual fill price (cents)",
        summary.get("trigger_vs_actual_price_gap_cents", {}),
    )
    _print_stats(
        "EXIT_EVAL trigger time vs actual fill time (seconds)",
        summary.get("trigger_vs_actual_time_gap_seconds", {}),
    )
    _print_stats(
        "Active sim exit price vs actual fill price (cents)",
        summary.get("active_sim_vs_actual_price_gap_cents", {}),
    )
    _print_stats(
        "Active sim exit time vs actual fill time (seconds)",
        summary.get("active_sim_vs_actual_time_gap_seconds", {}),
    )
    print()

    reason_pnl = summary.get("actual_pnl_by_matched_reason", {})
    if reason_pnl:
        print("Actual production net PnL by matched EXIT_EVAL reason:")
        print(f"{'Reason':<25} {'Count':>6} {'Gross PnL':>11} {'Fees':>10} {'Net PnL':>11}")
        print("-" * 73)
        for reason, g in sorted(reason_pnl.items(), key=lambda kv: -kv[1]["net_pnl_cents"]):
            print(
                f"{reason:<25} {g['count']:>6} "
                f"{fmt_cents(g.get('gross_pnl_cents', 0)):>11} "
                f"{fmt_cents(g.get('fees_cents', 0)):>10} "
                f"{fmt_cents(g.get('net_pnl_cents', 0)):>11}"
            )
        print()

    return matches, summary


def print_reason_breakdown(result: StrategyResult, title: str = "full_active") -> None:
    """Print per-exit-reason net-PnL breakdown."""
    breakdown = per_exit_reason_breakdown(result)
    if not breakdown:
        return

    print(f"\n## Per-Exit-Reason Net-PnL Breakdown: {title}\n")
    header = (
        f"{'Reason':<25} {'Count':>6} {'Wins':>5} {'Losses':>7} "
        f"{'Gross PnL':>11} {'Fees':>10} {'Net PnL':>11} {'Avg Hold(s)':>12}"
    )
    print(header)
    print("-" * len(header))

    rows = sorted(
        breakdown.items(),
        key=lambda kv: kv[1]["net_pnl_cents"],
        reverse=True,
    )
    for reason, g in rows:
        print(
            f"{reason:<25} {g['count']:>6} {g['wins']:>5} {g['losses']:>7} "
            f"{fmt_cents(g['gross_pnl_cents']):>11} {fmt_cents(g['fees_cents']):>10} "
            f"{fmt_cents(g['net_pnl_cents']):>11} {g['avg_hold_time_seconds']:>12.1f}"
        )
    print()


def print_no_rescue_bound(results: List[StrategyResult]) -> None:
    """Print a table comparing baseline (with rescue) to no-rescue pessimistic bound."""
    if not results:
        return
    print("\n## Pessimistic Bound: No Rescue for Unfilled IOCs\n")
    header = (
        f"{'Strategy':<22} {'Trades':>7} {'Exits':>6} {'Unfilled':>9} "
        f"{'Gross PnL':>11} {'Fees':>10} {'Net PnL':>11}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r.name:<22} {len(r.round_trips):>7} {r.exits:>6} {r.unfilled_exits:>9} "
            f"{fmt_cents(r.gross_pnl_cents):>11} {fmt_cents(r.total_fees_cents):>10} "
            f"{fmt_cents(r.net_pnl_cents):>11}"
        )
    print()


# ── Main ────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fills-db", type=Path, default=Path("data/kalshi_fills.db"))
    parser.add_argument("--full-log", type=Path, default=Path("logs"))
    parser.add_argument("--settlement-outcomes", type=Path, default=Path("logs/settlement_outcomes.jsonl"))
    parser.add_argument("--fee-model", choices=("live", "conservative"), default="live")
    parser.add_argument("--correlation-cap", type=float, default=2.0,
                        help="If >0, enforce a total crypto-correlated notional cap in USD.")
    parser.add_argument("--output", type=Path, default=Path("reports/exit_strategy_replay.json"))
    parser.add_argument("--lookback-hours", type=float, default=72.0)
    args = parser.parse_args()

    global all_exit_evals

    # Trim all inputs to the same lookback window.
    lookback = timedelta(hours=args.lookback_hours)
    cutoff = datetime.now(timezone.utc) - lookback

    settlements = load_settlements(args.settlement_outcomes)
    fills = load_fills(args.fills_db)
    all_exit_evals = parse_exit_eval_log(args.full_log, since=cutoff)

    print(f"[INFO] loaded {len(settlements)} settlements, {len(fills)} fills, {len(all_exit_evals)} EXIT_EVAL records")

    if not fills:
        print("[ERROR] no fills loaded; nothing to replay")
        return 1

    fills = [f for f in fills if f.created_time >= cutoff]

    # Reconstruct actual round trips from fills.
    round_trips = reconstruct_round_trips(fills)
    print(f"[INFO] reconstructed {len(round_trips)} round trips")

    # Assign an expected close time for the correlation-cap calculation.
    # Uses actual exit > settlement > 15-minute expiry fallback.
    _assign_expected_close_times(round_trips, settlements)

    # Run the three strategies.
    cap = args.correlation_cap if args.correlation_cap > 0 else None
    pure = run_strategy("pure_hold", round_trips, all_exit_evals, settlements, frozenset(), args.fee_model, cap)
    safety = run_strategy("safety_rails", round_trips, all_exit_evals, settlements, SAFETY_EXIT_REASONS, args.fee_model, cap)
    active = run_strategy("full_active", round_trips, all_exit_evals, settlements, None, args.fee_model, cap)

    # Reference: actual production path from recorded fills (validation ground truth).
    actual_active = compute_actual_active_result("actual_active", round_trips, settlements, cap)

    # Pessimistic no-rescue bounds for the two exit strategies.
    safety_nr = run_strategy("safety_rails_no_rescue", round_trips, all_exit_evals, settlements, SAFETY_EXIT_REASONS, args.fee_model, cap, rescue=False)
    active_nr = run_strategy("full_active_no_rescue", round_trips, all_exit_evals, settlements, None, args.fee_model, cap, rescue=False)

    # Diagnostics: actual-fill vs EXIT_EVAL slippage and per-reason PnL breakdown.
    matches, slippage_summary = print_slippage_diagnostics(round_trips, active, all_exit_evals, actual_active)

    print_reason_breakdown(active, title="full_active")
    print_reason_breakdown(safety, title="safety_rails")

    # A: correlated-exposure cap stress (all positions held to full 15m).
    cap_stress: Dict[str, Any] = {}
    if cap is not None:
        cap_stress = run_cap_stress(round_trips, all_exit_evals, settlements, cap, args.fee_model)
        print_cap_stress_report(cap_stress)

    # C: calibrate counterfactual exit prices using the empirical slippage hair-cut.
    # A positive empirical value means actual fills were worse than the trigger price.
    haircut = slippage_summary.get("empirical_slippage_haircut_cents", 0.0)
    if haircut > 0:
        print(f"[INFO] empirical fill-price haircut: {haircut:.2f} cents; re-running safety_rails and full_active with calibrated prices")
        safety_cal = run_strategy("safety_rails_calibrated", round_trips, all_exit_evals, settlements, SAFETY_EXIT_REASONS, args.fee_model, cap, fill_price_haircut_cents=haircut)
        active_cal = run_strategy("full_active_calibrated", round_trips, all_exit_evals, settlements, None, args.fee_model, cap, fill_price_haircut_cents=haircut)
    else:
        print("[INFO] empirical fill-price haircut is 0 cents; calibrated results are identical to baseline")
        safety_cal = safety
        active_cal = active

    diagnostics: Dict[str, Any] = {
        "slippage_summary": slippage_summary,
        "slippage_matches": [asdict(m) for m in matches],
        "full_active_reason_breakdown": per_exit_reason_breakdown(active),
        "safety_rails_reason_breakdown": per_exit_reason_breakdown(safety),
        "cap_stress_15m_hold": cap_stress,
    }

    report = build_report(pure, safety, active, actual_active, safety_nr, active_nr, safety_cal, active_cal, args.fee_model, cap, diagnostics)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"[INFO] wrote report to {args.output}")

    print_summary_table([pure, safety, active, actual_active])
    if safety_cal is not safety:
        print_summary_table([safety, safety_cal, active, active_cal])
    print_no_rescue_bound([safety, active, safety_nr, active_nr])
    return 0


if __name__ == "__main__":
    sys.exit(main())

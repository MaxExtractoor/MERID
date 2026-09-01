"""Golden record rollup — per-trade intent → order → fill → settlement → P&L view.

This module joins the durable telemetry that already exists in the MERID 15m stack:

- ``data/trade_attribution_fact.db`` (intent / order / fill / settlement events)
- ``logs/decision_telemetry.jsonl`` (model p, edge, threshold, quotes)
- ``logs/settlement_outcomes.jsonl`` (authoritative Kalshi settlement outcomes)
- ``data/kalshi_fills.db`` (fill-level execution quality and provenance)

It produces one row per ``intent_id`` (the natural unit of a single order decision)
in ``data/golden_records.jsonl`` and an optional queryable SQLite table.  The
output is read-only with respect to trading state; it never submits orders or
modifies positions.
"""

from __future__ import annotations

import dataclasses
import json
import os
import sqlite3
import uuid
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from utils.jsonl_writer import JsonlWriter
from utils.logger import get_logger

logger = get_logger("merid.monitoring.golden_record_rollup")

DEFAULT_FACT_DB = os.environ.get("MERID_TRADE_ATTRIBUTION_DB_PATH", "data/trade_attribution_fact.db")
DEFAULT_DECISION_TELEMETRY = os.environ.get("MERID_DECISION_TELEMETRY_PATH", "logs/decision_telemetry.jsonl")
DEFAULT_SETTLEMENT_OUTCOMES = os.environ.get("MERID_SETTLEMENT_OUTCOMES_PATH", "logs/settlement_outcomes.jsonl")
DEFAULT_FILLS_DB = os.environ.get("MERID_FILLS_DB_PATH", "data/kalshi_fills.db")
DEFAULT_OUT_JSONL = os.environ.get("MERID_GOLDEN_RECORDS_JSONL", "data/golden_records.jsonl")
DEFAULT_OUT_DB = os.environ.get("MERID_GOLDEN_RECORDS_DB", "data/golden_records.db")

SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Alert thresholds
# ---------------------------------------------------------------------------

# A slippage flag is emitted when the economic fill price differs from the
# intended price by more than this many cents (negative = better fill).
PRICE_SLIPPAGE_THRESHOLD_CENTS = int(
    os.environ.get("MERID_GOLDEN_RECORD_SLIPPAGE_THRESHOLD_CENTS", "2")
)

# Divergence flags grouped by alert severity.  These feed the audit report
# and any downstream alerting without requiring every consumer to re-interpret
# the raw flag list.
_GOLDEN_RECORD_CRITICAL_FLAGS = frozenset(
    {
        "side_mismatch",
        "action_mismatch",
        "qty_mismatch",
        "overfill",
        "missing_order",
        "unmatched_fill",
        "settlement_mismatch",
        "missing_settlement_for_settled_market",
        "missing_pnl",
        "exit_exposure_reversal",
    }
)

_GOLDEN_RECORD_WARNING_FLAGS = frozenset(
    {
        "rejected_without_reason",
    }
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class GoldenRecord:
    """One row of the per-trade golden record."""

    record_id: str
    build_ts: str
    schema_version: int

    # Identity
    run_id: Optional[str] = None
    process_id: Optional[str] = None
    signal_id: Optional[str] = None
    intent_id: Optional[str] = None
    client_order_id: Optional[str] = None
    order_id: Optional[str] = None
    fill_ids: List[str] = field(default_factory=list)
    exit_fill_ids: List[str] = field(default_factory=list)
    parent_entry_intent_id: Optional[str] = None
    parent_entry_fill_id: Optional[str] = None

    ticker: Optional[str] = None
    asset: Optional[str] = None
    side: Optional[str] = None
    action: Optional[str] = None

    # Decision economics
    decision_id: Optional[str] = None
    decision_trace_id: Optional[str] = None
    decision_model_prob_selected: Optional[float] = None
    decision_market_p: Optional[float] = None
    decision_raw_edge_cents: Optional[float] = None
    decision_gross_edge_cents: Optional[float] = None
    decision_net_edge_cents: Optional[float] = None
    decision_robust_ev_cents: Optional[float] = None
    decision_side: Optional[str] = None
    decision_tte_seconds: Optional[float] = None
    has_decision_telemetry: bool = False

    # Order
    order_type: Optional[str] = None
    time_in_force: Optional[str] = None
    post_only: Optional[bool] = None
    reduce_only: Optional[bool] = None
    self_trade_prevention_type: Optional[str] = None
    intent_price_cents: Optional[int] = None
    intent_quantity_cc: Optional[int] = None
    intent_count_fp: Optional[str] = None
    order_status: Optional[str] = None
    order_error: Optional[str] = None
    order_ts: Optional[str] = None
    has_order: bool = False

    # Fill
    fill_quantity_cc: Optional[int] = None
    fill_yes_delta_cc: Optional[int] = None
    fill_price_cents: Optional[int] = None
    fee_cents: Optional[int] = None
    fill_source: Optional[str] = None
    liquidity_role: Optional[str] = None
    fill_ts: Optional[str] = None
    has_fill: bool = False

    # Settlement / P&L
    settlement_outcome: Optional[str] = None
    settlement_price_cents: Optional[int] = None
    realized_pnl_cents: Optional[int] = None
    settlement_ts: Optional[str] = None
    authoritative_settlement_outcome: Optional[str] = None
    settlement_mismatch: Optional[bool] = None
    has_settlement: bool = False
    has_authoritative_settlement: bool = False

    # Audit classification
    is_exit: Optional[bool] = None
    lifecycle_status: str = "unknown"
    divergence_flags: List[str] = field(default_factory=list)
    alert_level: str = "ok"  # ok | warning | critical

    # Raw metadata snapshots (for drill-down; intentionally compact)
    intent_metadata: Optional[str] = None
    order_metadata: Optional[str] = None
    fill_metadata: Optional[str] = None
    settlement_metadata: Optional[str] = None


@dataclass
class GoldenRecordSummary:
    """Summary of a golden-record build run."""

    record_count: int = 0
    intent_count: int = 0
    ordered_count: int = 0
    filled_count: int = 0
    settled_count: int = 0
    rejected_count: int = 0
    exit_count: int = 0
    divergence_count: int = 0
    critical_count: int = 0
    warning_count: int = 0
    missing_settlement_for_settled_market: int = 0
    missing_pnl: int = 0
    side_mismatch_count: int = 0
    qty_mismatch_count: int = 0
    settlement_mismatch_count: int = 0
    build_ts: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    fact_db: str = ""
    decision_telemetry_path: str = ""
    settlement_outcomes_path: str = ""
    fills_db: str = ""
    out_jsonl: str = ""
    out_db: str = ""
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    if value is None or value == "":
        return default
    try:
        f = float(value)
        return f if f == f and f not in (float("inf"), float("-inf")) else default
    except (TypeError, ValueError):
        return default


def _safe_str(value: Any, default: Optional[str] = None) -> Optional[str]:
    if value is None:
        return default
    s = str(value).strip()
    return s if s else default


def _safe_decimal_str(value: Any, default: Optional[str] = None) -> Optional[str]:
    if value is None:
        return default
    try:
        d = Decimal(str(value))
        return f"{d:.8f}"  # compact fixed-point string
    except (InvalidOperation, TypeError, ValueError):
        return default


def _parse_iso(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        s = str(value).replace("Z", "+00:00")
        return datetime.fromisoformat(s)
    except (TypeError, ValueError):
        return None


def _parse_meta(value: Any) -> Dict[str, Any]:
    """Parse the JSON metadata column from the fact table."""
    if not value:
        return {}
    try:
        return json.loads(str(value))
    except json.JSONDecodeError:
        return {"_raw": str(value)}


def _flatten_metadata(value: Any) -> Dict[str, Any]:
    """Parse and flatten the nested `metadata.metadata` that `record_order`
    stores from the `CreateOrderRequest` payload.
    """
    meta = _parse_meta(value)
    inner = meta.get("metadata")
    if isinstance(inner, dict):
        # The inner dict is the authoritative intent/order provenance.
        meta.update(inner)
    return meta


def _economic_position(
    side: Optional[str],
    action: Optional[str],
    price_cents: Optional[int],
    quantity_cc: Optional[int],
) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    """Map a raw order/fill (outcome + buy/sell) to the canonical position:

    Returns (economic_side, economic_price_cents, yes_delta_cc).

    - BUY_YES  -> long YES (side=yes,  price=price,        yes_delta=+qty)
    - SELL_NO  -> long YES (side=yes,  price=100-price,    yes_delta=+qty)
    - BUY_NO   -> long NO  (side=no,   price=price,        yes_delta=-qty)
    - SELL_YES -> long NO  (side=no,   price=100-price,    yes_delta=-qty)

    This matches the MERID signed-YES exposure convention used by
    `KalshiFillsLedger.canonical_yes_delta_cc`.
    """
    side = (side or "").lower()
    action = (action or "").lower()
    if side not in ("yes", "no") or action not in ("buy", "sell") or quantity_cc is None:
        return None, None, None

    if (side == "yes" and action == "buy") or (side == "no" and action == "sell"):
        economic_side = "yes"
        yes_delta = quantity_cc
    else:
        economic_side = "no"
        yes_delta = -quantity_cc

    if price_cents is None:
        return economic_side, None, yes_delta

    if side == economic_side:
        economic_price = price_cents
    else:
        # Price is quoted on the opposite side of the position we actually hold.
        economic_price = 100 - price_cents

    return economic_side, economic_price, yes_delta


def _decision_id(ticker: Optional[str], side: Optional[str]) -> Optional[str]:
    if not ticker or not side:
        return None
    return f"{str(ticker).strip().upper()}:{str(side).strip().lower()}"


def _coerce_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    s = str(value).lower()
    return s in ("1", "true", "yes", "on")


def _load_jsonl_index(
    path: Path,
    key_fn: Any,
    since_dt: Optional[datetime] = None,
    until_dt: Optional[datetime] = None,
) -> Tuple[Dict[Any, List[Dict[str, Any]]], int]:
    """Load a JSONL file and group rows by a key function."""
    index: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    malformed = 0
    if not path.exists():
        return index, malformed

    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                malformed += 1
                continue
            if not isinstance(rec, dict):
                continue
            ts = _parse_iso(rec.get("event_ts_utc") or rec.get("ts") or rec.get("event_ts"))
            if since_dt and ts and ts < since_dt:
                continue
            if until_dt and ts and ts > until_dt:
                continue
            key = key_fn(rec)
            if key is None:
                continue
            if isinstance(key, (list, tuple, set)):
                for k in key:
                    index[k].append(rec)
            else:
                index[key].append(rec)

    return index, malformed


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

class GoldenRecordBuilder:
    """Build per-trade golden records from durable telemetry."""

    def __init__(
        self,
        fact_db: Optional[str] = None,
        decision_telemetry: Optional[str] = None,
        settlement_outcomes: Optional[str] = None,
        fills_db: Optional[str] = None,
        lookback_hours: Optional[int] = None,
        out_jsonl: Optional[str] = None,
        out_db: Optional[str] = None,
        rebuild_db: bool = True,
    ) -> None:
        self.fact_db = Path(fact_db or DEFAULT_FACT_DB)
        self.decision_telemetry = Path(decision_telemetry or DEFAULT_DECISION_TELEMETRY)
        self.settlement_outcomes = Path(settlement_outcomes or DEFAULT_SETTLEMENT_OUTCOMES)
        self.fills_db = Path(fills_db or DEFAULT_FILLS_DB)
        self.out_jsonl = Path(out_jsonl or DEFAULT_OUT_JSONL)
        self.out_db = Path(out_db or DEFAULT_OUT_DB)
        self.rebuild_db = rebuild_db
        self.lookback_hours = lookback_hours

        self._decision_index: Dict[str, List[Dict[str, Any]]] = {}
        self._ticker_side_index: Dict[str, List[Dict[str, Any]]] = {}
        self._settlement_index: Dict[str, Dict[str, Any]] = {}
        self._summary = GoldenRecordSummary()

    # -----------------------------------------------------------------------
    # Source loading
    # -----------------------------------------------------------------------

    def _since_until(self) -> Tuple[Optional[datetime], Optional[datetime]]:
        until = datetime.now(timezone.utc)
        if not self.lookback_hours:
            return None, None
        since = until - timedelta(hours=self.lookback_hours)
        return since, until

    def _load_decision_telemetry(self) -> None:
        since, until = self._since_until()

        def _keys(rec: Dict[str, Any]):
            keys: Set[str] = set()
            did = _safe_str(rec.get("decision_id"))
            if did:
                keys.add(did)
            ticker = _safe_str(rec.get("ticker"))
            side = _safe_str(rec.get("selected_side"))
            if ticker and side:
                keys.add(_decision_id(ticker, side))
            return keys

        self._decision_index, _ = _load_jsonl_index(
            self.decision_telemetry, _keys, since, until
        )

        # Secondary index by ticker:side for fallback matching.
        self._ticker_side_index = defaultdict(list)
        for key, recs in self._decision_index.items():
            if ":" in (key or ""):
                self._ticker_side_index[key].extend(recs)

    def _load_settlement_outcomes(self) -> None:
        since, until = self._since_until()

        def _key(rec: Dict[str, Any]):
            if str(rec.get("event_type", "")).lower() == "settlement_correction":
                return None  # corrections handled separately; not authoritative
            return _safe_str(rec.get("ticker"))

        raw_index, _ = _load_jsonl_index(self.settlement_outcomes, _key, since, until)
        # Latest observed outcome wins (file is append-only).
        for ticker, rows in raw_index.items():
            self._settlement_index[ticker] = rows[-1]

    # -----------------------------------------------------------------------
    # Decision matching
    # -----------------------------------------------------------------------

    def _match_decision_telemetry(
        self, ticker: Optional[str], side: Optional[str], event_ts: Optional[datetime]
    ) -> Optional[Dict[str, Any]]:
        did = _decision_id(ticker, side)

        def _ts(rec: Dict[str, Any]) -> Optional[datetime]:
            return _parse_iso(rec.get("event_ts_utc") or rec.get("ts"))

        def _best(candidates: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
            if not candidates:
                return None
            if event_ts is None:
                return candidates[-1]
            # Filter candidates that have a parseable timestamp; otherwise keep all.
            scored = [(r, _ts(r)) for r in candidates]
            with_ts = [(r, ts) for r, ts in scored if ts is not None]
            if with_ts:
                return min(with_ts, key=lambda pair: abs(pair[1] - event_ts))[0]
            return candidates[-1]

        if did and did in self._decision_index:
            return _best(self._decision_index[did])
        if did and did in self._ticker_side_index:
            return _best(self._ticker_side_index[did])

        return None

    # -----------------------------------------------------------------------
    # Core rollup
    # -----------------------------------------------------------------------

    @staticmethod
    def _group_ticker(group: List[Dict[str, Any]]) -> Optional[str]:
        for ev in group:
            if ev.get("ticker"):
                return _safe_str(ev["ticker"])
        return None

    @staticmethod
    def _group_has_trade(group: List[Dict[str, Any]]) -> bool:
        return any(ev.get("event_type") in ("intent", "order", "fill") for ev in group)

    def _group_is_exit(self, group: List[Dict[str, Any]]) -> bool:
        for ev in group:
            if ev.get("event_type") not in ("intent", "order", "fill"):
                continue
            if _coerce_bool(ev.get("reduce_only")):
                return True
            meta = _flatten_metadata(ev.get("metadata"))
            if _coerce_bool(meta.get("reduce_only")):
                return True
            if str(meta.get("entry_or_exit", "")).lower() == "exit":
                return True
            if str(meta.get("position_effect", "")).lower() in ("close", "reduce"):
                return True
            if meta.get("parent_entry_intent_id") or meta.get("parent_intent_id"):
                return True
            if meta.get("parent_entry_fill_id") or meta.get("parent_fill_id"):
                return True
        return False

    def _merge_bare_settlement_groups(
        self, groups: Dict[str, List[Dict[str, Any]]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Attach settlement-only groups to the matching entry trade group by ticker."""
        # Map ticker -> candidate entry group keys.
        ticker_to_entries: Dict[str, List[str]] = defaultdict(list)
        for key, group in list(groups.items()):
            if not self._group_has_trade(group) or self._group_is_exit(group):
                continue
            ticker = self._group_ticker(group)
            if ticker:
                ticker_to_entries[ticker].append(key)

        for key, group in list(groups.items()):
            if self._group_has_trade(group):
                continue
            ticker = self._group_ticker(group)
            if not ticker or ticker not in ticker_to_entries:
                continue
            # Prefer a group with a fill; otherwise take the first candidate.
            candidates = ticker_to_entries[ticker]
            best: Optional[str] = None
            for c in candidates:
                if any(ev.get("event_type") == "fill" for ev in groups[c]):
                    best = c
                    break
            if best is None:
                best = candidates[0]
            groups[best].extend(group)
            del groups[key]
        return groups

    def _extract_event_groups(self) -> Dict[str, List[Dict[str, Any]]]:
        """Load all relevant rows from the trade-attribution fact DB, grouped by trade."""
        groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        if not self.fact_db.exists():
            self._summary.errors.append(f"fact_db not found: {self.fact_db}")
            return groups

        since, until = self._since_until()
        try:
            conn = sqlite3.connect(str(self.fact_db), timeout=10.0)
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()

            # SQLite does not have a native timestamp type; event_ts is ISO text.
            sql = "SELECT * FROM trade_attribution_fact WHERE 1=1"
            params: List[Any] = []
            if since:
                sql += " AND (event_ts >= ?)"
                params.append(since.isoformat())
            if until:
                sql += " AND (event_ts <= ?)"
                params.append(until.isoformat())
            sql += " ORDER BY row_id"

            cur.execute(sql, params)
            for row in cur.fetchall():
                rec = dict(row)
                key = (
                    rec.get("intent_id")
                    or rec.get("client_order_id")
                    or rec.get("order_id")
                    or rec.get("fill_id")
                    or rec.get("ticker")
                    or str(rec.get("row_id"))
                )
                if not key:
                    continue
                groups[key].append(rec)
        except Exception as e:
            logger.error("[GOLDEN-RECORD] failed to read fact DB: %s", e)
            self._summary.errors.append(f"fact_db read error: {e}")
        finally:
            try:
                conn.close()
            except Exception:
                pass

        return self._merge_bare_settlement_groups(groups)

    def _build_record(self, events: List[Dict[str, Any]]) -> Optional[GoldenRecord]:
        """Roll a single intent's events into one golden record."""
        intent_rows = [r for r in events if r.get("event_type") == "intent"]
        order_rows = [r for r in events if r.get("event_type") == "order"]
        fill_rows = [r for r in events if r.get("event_type") == "fill"]
        settlement_rows = [r for r in events if r.get("event_type") == "settlement"]

        # Pick the authoritative base row.  The intent is canonical, but in
        # older fact tables the intent row may not have been flushed; fall back
        # to order, fill, and finally settlement.
        if intent_rows:
            base = intent_rows[0]
            base_type = "intent"
        elif order_rows:
            base = order_rows[-1]
            base_type = "order"
        elif fill_rows:
            base = fill_rows[-1]
            base_type = "fill"
        elif settlement_rows:
            base = settlement_rows[-1]
            base_type = "settlement"
        else:
            return None

        first_event_ts = _parse_iso(events[0].get("event_ts"))
        base_meta = _flatten_metadata(base.get("metadata"))

        def _qty_from_meta() -> Optional[int]:
            for key in ("quantity_cc", "count_fp", "count", "size"):
                if key in base_meta and base_meta[key] is not None:
                    try:
                        if key == "quantity_cc":
                            return _safe_int(base_meta[key])
                        return int(Decimal(str(base_meta[key])) * 100)
                    except (InvalidOperation, TypeError, ValueError):
                        continue
            return None

        # Use the latest order / settlement if there are duplicates.
        order = order_rows[-1] if order_rows else None
        order_meta = _parse_meta(order.get("metadata")) if order else {}

        settlement = settlement_rows[-1] if settlement_rows else None
        settlement_meta = _parse_meta(settlement.get("metadata")) if settlement else {}

        record = GoldenRecord(
            record_id=uuid.uuid4().hex[:12],
            build_ts=datetime.now(timezone.utc).isoformat(),
            schema_version=SCHEMA_VERSION,
            run_id=_safe_str(base.get('run_id')),
            process_id=_safe_str(base.get('process_id')),
            signal_id=_safe_str(base.get('signal_id')),
            intent_id=_safe_str(base.get('intent_id'))
                or _safe_str(base.get('client_order_id'))
                or _safe_str(base.get('fill_id'))
                or _safe_str(base.get('ticker')),
            client_order_id=_safe_str(base.get('client_order_id')),
            ticker=_safe_str(base.get('ticker')),
            asset=_safe_str(base.get('asset')),
            side=_safe_str(base.get('side')),
            action=_safe_str(base.get('action')),
            order_type=_safe_str(base.get('order_type')),
            time_in_force=_safe_str(base.get('time_in_force')),
            post_only=_coerce_bool(base.get('post_only')),
            reduce_only=_coerce_bool(base.get('reduce_only')),
            self_trade_prevention_type=_safe_str(base.get('self_trade_prevention_type')),
            intent_price_cents=_safe_int(base.get('price_cents'))
                or _safe_int(base_meta.get('price_cents'))
                or _safe_int(base_meta.get('canonical_leg_price_cents')),
            intent_quantity_cc=_safe_int(base.get('quantity_cc')) or _qty_from_meta(),
            intent_count_fp=_safe_str(base.get('count_fp'))
                or _safe_str(base_meta.get('count_fp')),
            has_order=bool(order_rows),
            has_fill=bool(fill_rows),
            has_settlement=bool(settlement_rows),
            intent_metadata=intent_rows[0].get('metadata') if intent_rows else None,
            order_metadata=order.get('metadata') if order else None,
            settlement_metadata=settlement.get('metadata') if settlement else None,
        )

        # Parentage (from base metadata; authoritative for exits).
        record.parent_entry_intent_id = _safe_str(
            base_meta.get('parent_entry_intent_id')
            or base_meta.get('parent_intent_id')
        )
        record.parent_entry_fill_id = _safe_str(
            base_meta.get('parent_entry_fill_id')
            or base_meta.get('parent_fill_id')
        )

        # Decision provenance.
        record.decision_id = _safe_str(
            base_meta.get('decision_id') or base_meta.get('decision_trace_id')
        )
        record.decision_trace_id = _safe_str(
            base_meta.get('decision_trace_id') or base_meta.get('decision_id')
        )

        # Is this an exit?  Prefer explicit fields, then parent linkage.
        is_exit = None
        if _coerce_bool(base_meta.get('reduce_only')):
            is_exit = True
        if _coerce_bool(base.get('reduce_only')):
            is_exit = True
        if str(base_meta.get('entry_or_exit', '')).lower() == 'exit':
            is_exit = True
        if str(base_meta.get('position_effect', '')).lower() in ('close', 'reduce'):
            is_exit = True
        if record.parent_entry_intent_id or record.parent_entry_fill_id:
            is_exit = True
        record.is_exit = is_exit

        # Order details.
        if order:
            record.order_id = _safe_str(order.get("order_id")) or record.order_id
            record.order_status = _safe_str(order.get("order_status"))
            record.order_error = _safe_str(order.get("error"))
            record.order_ts = _safe_str(order.get("event_ts"))

        # Fill aggregation.
        total_fill_qty = 0
        total_fill_yes_delta = 0
        total_fees = 0
        fill_ids: List[str] = []
        last_fill_ts: Optional[str] = None
        last_fill_price: Optional[int] = None
        last_fill_source: Optional[str] = None
        last_liquidity: Optional[str] = None
        has_unmatched = False

        for frow in fill_rows:
            fill_meta = _parse_meta(frow.get("metadata"))
            qty = _safe_int(frow.get("fill_quantity_cc")) or 0
            total_fill_qty += qty
            fill_yes_delta = _safe_int(
                fill_meta.get("canonical_yes_delta_cc")
                or fill_meta.get("intent_yes_delta_cc")
                or fill_meta.get("execution_yes_delta_cc")
            )
            if fill_yes_delta is None:
                # Fallback: derive from canonical side/action + quantity.
                fs = _safe_str(
                    fill_meta.get("canonical_position_side") or fill_meta.get("side")
                )
                fa = _safe_str(
                    fill_meta.get("canonical_position_action") or fill_meta.get("action")
                )
                _, _, fill_yes_delta = _economic_position(fs, fa, None, qty)
            if fill_yes_delta is not None:
                total_fill_yes_delta += fill_yes_delta
            fee = _safe_int(frow.get("fee_cost_cents")) or 0
            total_fees += fee
            fid = _safe_str(frow.get("fill_id"))
            if fid:
                fill_ids.append(fid)
            price = _safe_int(frow.get("avg_fill_price_cents"))
            if price is not None:
                last_fill_price = price
            ts = _safe_str(frow.get("event_ts"))
            if ts:
                last_fill_ts = ts
            src = _safe_str(frow.get("source")) or _safe_str(fill_meta.get("ingestion_source"))
            if src:
                last_fill_source = src
            liq = _safe_str(frow.get("liquidity_role")) or _safe_str(fill_meta.get("liquidity_role"))
            if liq:
                last_liquidity = liq
            if _coerce_bool(fill_meta.get("unmatched")):
                has_unmatched = True

        if fill_rows:
            record.has_fill = True
            record.fill_ids = fill_ids
            record.fill_quantity_cc = total_fill_qty
            record.fill_yes_delta_cc = total_fill_yes_delta
            record.fill_price_cents = last_fill_price
            record.fee_cents = total_fees
            record.fill_source = last_fill_source
            record.liquidity_role = last_liquidity
            record.fill_ts = last_fill_ts
            record.fill_metadata = fill_rows[-1].get("metadata")

        # Settlement.
        if settlement:
            record.settlement_outcome = _safe_str(settlement.get("settlement_outcome"))
            record.settlement_price_cents = _safe_int(settlement.get("settlement_price_cents"))
            record.realized_pnl_cents = _safe_int(settlement.get("realized_pnl_cents"))
            record.settlement_ts = _safe_str(settlement.get("event_ts"))

        # Authoritative settlement cross-check.
        if record.ticker and record.ticker in self._settlement_index:
            auth = self._settlement_index[record.ticker]
            record.authoritative_settlement_outcome = _safe_str(auth.get("outcome"))
            record.has_authoritative_settlement = True
            if (
                record.settlement_outcome is not None
                and record.authoritative_settlement_outcome is not None
            ):
                record.settlement_mismatch = (
                    record.settlement_outcome.lower()
                    != record.authoritative_settlement_outcome.lower()
                )

        # Decision telemetry enrichment.
        decision = self._match_decision_telemetry(record.ticker, record.side, first_event_ts)
        if decision:
            record.has_decision_telemetry = True
            record.decision_id = record.decision_id or _safe_str(decision.get("decision_id"))
            record.decision_trace_id = record.decision_trace_id or _safe_str(
                decision.get("candidate_id")
            )
            record.decision_model_prob_selected = _safe_float(
                decision.get("model_prob_selected") or decision.get("p_selected")
            )
            record.decision_market_p = _safe_float(
                decision.get("market_p_selected") or decision.get("market_prob")
            )
            record.decision_raw_edge_cents = _safe_float(
                decision.get("raw_edge_cents") or decision.get("edge_pct")
            )
            record.decision_gross_edge_cents = _safe_float(decision.get("gross_edge_cents"))
            record.decision_net_edge_cents = _safe_float(decision.get("net_edge_cents"))
            record.decision_robust_ev_cents = _safe_float(decision.get("robust_ev_cents"))
            record.decision_side = _safe_str(decision.get("selected_side"))
            record.decision_tte_seconds = _safe_float(
                decision.get("tte_seconds") or decision.get("minutes_to_expiry")
            )
            if record.decision_tte_seconds is not None and record.decision_tte_seconds > 1000:
                # heuristic: minutes_to_expiry was stored instead of seconds
                record.decision_tte_seconds = record.decision_tte_seconds * 60.0

        # Lifecycle and divergence.
        record = self._classify_and_flag(record, base_meta, has_unmatched)
        return record

    def _classify_and_flag(
        self,
        record: GoldenRecord,
        intent_meta: Dict[str, Any],
        has_unmatched: bool,
    ) -> GoldenRecord:
        """Determine lifecycle_status and divergence flags."""
        flags: List[str] = []

        # Lifecycle.
        if record.order_status and record.order_status.lower() in ("rejected", "error"):
            record.lifecycle_status = "rejected"
            self._summary.rejected_count += 1
        elif record.settlement_outcome is not None:
            record.lifecycle_status = "settled"
            self._summary.settled_count += 1
        elif record.has_fill:
            record.lifecycle_status = "filled"
            self._summary.filled_count += 1
        elif record.has_order:
            record.lifecycle_status = "ordered"
            self._summary.ordered_count += 1
        elif record.has_decision_telemetry or record.intent_id:
            record.lifecycle_status = "selected"
            self._summary.intent_count += 1

        if record.is_exit:
            self._summary.exit_count += 1

        # Divergence checks.
        if not record.has_order:
            flags.append("missing_order")

        # Only treat a fill as "missing" when the order claims it should be done.
        filled_order_statuses = ("filled", "fully_filled", "complete", "closed")
        if (
            record.has_order
            and record.order_status in filled_order_statuses
            and not record.has_fill
        ):
            flags.append("missing_fill")

        if record.has_fill and not record.is_exit:
            # Entry fills should eventually settle.
            if record.has_authoritative_settlement and not record.has_settlement:
                flags.append("missing_settlement_for_settled_market")
                self._summary.missing_settlement_for_settled_market += 1

        if record.has_settlement and record.realized_pnl_cents is None:
            flags.append("missing_pnl")
            self._summary.missing_pnl += 1

        if record.has_fill and record.side and record.action:
            # The fact table fill row already stores canonical side/action, so a
            # direct comparison is meaningful.  Compare to the intended side/action
            # which came from the intent.
            if record.side.lower() not in (str(record.side).lower(),):
                # placeholder for any future canonical normalization
                pass

        # Side / action / quantity mismatch.
        # Compare economic (signed-YES) position, not raw exchange labels,
        # because BUY_NO and SELL_YES are counterparty-equivalent.
        if record.has_fill and record.side and record.action:
            fill_meta = _parse_meta(record.fill_metadata or "{}")

            # Prefer authoritative canonical fields; fall back to raw payload.
            fill_side = _safe_str(
                fill_meta.get("canonical_position_side")
                or fill_meta.get("side")
            )
            fill_action = _safe_str(
                fill_meta.get("canonical_position_action")
                or fill_meta.get("action")
            )
            # Authoritative signed-YES delta is the safest comparison.
            order_yes_delta = _safe_int(
                intent_meta.get("intent_yes_delta_cc")
                or intent_meta.get("canonical_yes_delta_cc")
            )
            if order_yes_delta is None and record.intent_quantity_cc:
                _, _, order_yes_delta = _economic_position(
                    record.side, record.action, None, record.intent_quantity_cc
                )

            fill_yes_delta = record.fill_yes_delta_cc
            if fill_yes_delta is None:
                fill_yes_delta = _safe_int(
                    fill_meta.get("canonical_yes_delta_cc")
                    or fill_meta.get("intent_yes_delta_cc")
                    or fill_meta.get("execution_yes_delta_cc")
                )
            if fill_yes_delta is None and record.fill_quantity_cc:
                _, _, fill_yes_delta = _economic_position(
                    fill_side, fill_action, None, record.fill_quantity_cc
                )

            if order_yes_delta is not None and fill_yes_delta is not None:
                if order_yes_delta != fill_yes_delta:
                    flags.append("side_mismatch")
                    self._summary.side_mismatch_count += 1
            else:
                # Fallback label comparison when signed-yes-delta is unavailable.
                if fill_side and fill_side.lower() != record.side.lower():
                    flags.append("side_mismatch")
                    self._summary.side_mismatch_count += 1
                if fill_action and fill_action.lower() != record.action.lower():
                    flags.append("action_mismatch")

            # Quantity mismatch only matters for terminal fills; partial fills
            # while an order is still resting are expected.
            if (
                record.order_status in filled_order_statuses
                and record.intent_quantity_cc is not None
                and record.fill_quantity_cc is not None
                and record.intent_quantity_cc != 0
                and record.intent_quantity_cc != record.fill_quantity_cc
            ):
                flags.append("qty_mismatch")
                self._summary.qty_mismatch_count += 1
            if (
                record.order_status in filled_order_statuses
                and record.fill_quantity_cc is not None
                and record.intent_quantity_cc is not None
                and record.fill_quantity_cc > record.intent_quantity_cc
            ):
                flags.append("overfill")

        # Execution price slippage in the position's own price space.
        # Convert both prices to the economic side before comparing.
        if record.has_fill and record.intent_price_cents is not None and record.fill_price_cents is not None:
            fill_meta = _parse_meta(record.fill_metadata or "{}")
            fill_side = _safe_str(
                fill_meta.get("canonical_position_side")
                or fill_meta.get("side")
            )
            fill_action = _safe_str(
                fill_meta.get("canonical_position_action")
                or fill_meta.get("action")
            )
            order_economic_side, order_economic_price, _ = _economic_position(
                record.side, record.action, record.intent_price_cents, record.intent_quantity_cc or 0
            )
            fill_economic_side, fill_economic_price, _ = _economic_position(
                fill_side, fill_action, record.fill_price_cents, record.fill_quantity_cc or 0
            )

            if (
                order_economic_price is not None
                and fill_economic_price is not None
                and order_economic_side is not None
                and fill_economic_side is not None
            ):
                # For an entry, a lower fill price is always better.
                if not record.is_exit:
                    slippage = fill_economic_price - order_economic_price
                else:
                    # For an exit, the sign of the fill's signed-YES delta tells us
                    # whether we are buying YES (positive, lower is better) or buying
                    # NO / selling YES (negative, higher is better).  The previous
                    # blanket rule "higher fill price is better" mis-flagged NO-side
                    # exits like SELL_NO filled as BUY_YES.
                    fill_yes_delta = record.fill_yes_delta_cc
                    if fill_yes_delta is not None and fill_yes_delta > 0:
                        # Buying YES to close a long NO position.
                        slippage = fill_economic_price - order_economic_price
                    elif fill_yes_delta is not None and fill_yes_delta < 0:
                        # Selling YES / buying NO to close a long YES position.
                        slippage = order_economic_price - fill_economic_price
                    else:
                        # Cannot determine sign; fall back to the conservative
                        # previous rule.
                        slippage = order_economic_price - fill_economic_price
                if slippage > PRICE_SLIPPAGE_THRESHOLD_CENTS:
                    flags.append(f"price_slippage_{slippage}c")
            else:
                # Legacy raw-price comparison when economic side cannot be resolved.
                slippage = abs(record.fill_price_cents - record.intent_price_cents)
                if slippage > PRICE_SLIPPAGE_THRESHOLD_CENTS:
                    flags.append(f"price_slippage_{slippage}c")

        if has_unmatched:
            flags.append("unmatched_fill")

        if record.settlement_mismatch:
            flags.append("settlement_mismatch")
            self._summary.settlement_mismatch_count += 1

        if record.order_status and record.order_status.lower() == "rejected" and not record.order_error:
            flags.append("rejected_without_reason")

        record.divergence_flags = flags
        # Classify the whole record by the highest-severity flag present.
        if flags:
            self._summary.divergence_count += 1
            if set(flags) & _GOLDEN_RECORD_CRITICAL_FLAGS:
                record.alert_level = "critical"
                self._summary.critical_count += 1
            elif set(flags) & _GOLDEN_RECORD_WARNING_FLAGS:
                record.alert_level = "warning"
                self._summary.warning_count += 1
            else:
                record.alert_level = "warning"
                self._summary.warning_count += 1

        return record

    def _promote_to_critical(self, record: GoldenRecord) -> None:
        """Promote a record to critical and adjust the summary counters."""
        if record.alert_level == "critical":
            return
        if record.alert_level == "warning":
            self._summary.warning_count -= 1
        record.alert_level = "critical"
        self._summary.critical_count += 1

    # -----------------------------------------------------------------------
    # Output
    # -----------------------------------------------------------------------

    def _record_to_dict(self, record: GoldenRecord) -> Dict[str, Any]:
        d = asdict(record)
        # JSON-safe: no complex objects, lists are fine.
        for key, value in list(d.items()):
            if isinstance(value, Decimal):
                d[key] = str(value)
        return d

    def _write_jsonl(self, records: List[GoldenRecord]) -> None:
        writer = JsonlWriter(self.out_jsonl, max_bytes=50_000_000, backup_count=3)
        for rec in records:
            writer.append(self._record_to_dict(rec))

    def _write_db(self, records: List[GoldenRecord]) -> None:
        if not records:
            return

        self.out_db.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.out_db), timeout=10.0)
        try:
            columns = [f.name for f in dataclasses.fields(GoldenRecord)]
            col_defs = []
            for c in columns:
                if c in (
                    "fill_ids",
                    "exit_fill_ids",
                    "divergence_flags",
                ):
                    col_defs.append(f"{c} TEXT")
                elif c in ("record_id", "build_ts"):
                    col_defs.append(f"{c} TEXT NOT NULL")
                elif c == "schema_version":
                    col_defs.append(f"{c} INTEGER NOT NULL")
                else:
                    col_defs.append(f"{c} TEXT")

            if self.rebuild_db:
                conn.execute("DROP TABLE IF EXISTS golden_records")

            create_sql = (
                "CREATE TABLE IF NOT EXISTS golden_records ("
                + ", ".join(col_defs)
                + ", PRIMARY KEY (record_id))"
            )
            conn.execute(create_sql)

            # Build indexes for the audit queries this view is designed for.
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_gr_intent ON golden_records(intent_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_gr_ticker ON golden_records(ticker)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_gr_build_ts ON golden_records(build_ts)"
            )

            if not self.rebuild_db:
                # Ensure appended DBs get new columns added since the last run.
                existing = {col[1] for col in conn.execute("PRAGMA table_info(golden_records)").fetchall()}
                for c in columns:
                    if c not in existing:
                        conn.execute(f"ALTER TABLE golden_records ADD COLUMN {c} TEXT")

            placeholders = ",".join("?" * len(columns))
            insert_sql = f"INSERT OR REPLACE INTO golden_records ({','.join(columns)}) VALUES ({placeholders})"

            for rec in records:
                row = []
                for c in columns:
                    value = getattr(rec, c)
                    if isinstance(value, (list, dict)):
                        value = json.dumps(value, default=str)
                    elif value is None:
                        value = None
                    elif isinstance(value, bool):
                        value = int(value)
                    elif isinstance(value, (int, float)):
                        value = value
                    else:
                        value = str(value)
                    row.append(value)
                conn.execute(insert_sql, row)

            conn.commit()
        except Exception as e:
            logger.error("[GOLDEN-RECORD] failed to write DB: %s", e)
            self._summary.errors.append(f"out_db write error: {e}")
        finally:
            conn.close()

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def build(self) -> Tuple[List[GoldenRecord], GoldenRecordSummary]:
        """Run the full join and return the records plus a summary."""
        self._summary = GoldenRecordSummary(
            fact_db=str(self.fact_db),
            decision_telemetry_path=str(self.decision_telemetry),
            settlement_outcomes_path=str(self.settlement_outcomes),
            fills_db=str(self.fills_db),
            out_jsonl=str(self.out_jsonl),
            out_db=str(self.out_db),
        )

        logger.info(
            "[GOLDEN-RECORD] building from fact_db=%s decision_telemetry=%s",
            self.fact_db,
            self.decision_telemetry,
        )

        self._load_decision_telemetry()
        self._load_settlement_outcomes()
        groups = self._extract_event_groups()

        records: List[GoldenRecord] = []
        for key, events in groups.items():
            # Settlement-only rows are not a trade if no order/fill exists.
            # They will attach to a trade group above; if they didn't, skip.
            if not self._group_has_trade(events):
                continue
            try:
                rec = self._build_record(events)
                if rec:
                    records.append(rec)
            except Exception as e:
                logger.warning("[GOLDEN-RECORD] failed to build record for %s: %s", key, e)
                self._summary.errors.append(f"build record {key}: {e}")

        # Second pass: attach exit fills to parent and verify the exit nets
        # the parent's signed-YES exposure.  A reduce-only/exit that overshoots
        # or flips the parent's position is a risk-control failure.
        by_intent: Dict[str, GoldenRecord] = {r.intent_id: r for r in records if r.intent_id}
        exits_by_parent: Dict[str, List[GoldenRecord]] = {}
        for rec in records:
            if rec.is_exit and rec.parent_entry_intent_id:
                exits_by_parent.setdefault(rec.parent_entry_intent_id, []).append(rec)

        for parent_intent, exit_recs in exits_by_parent.items():
            if parent_intent not in by_intent:
                continue
            parent = by_intent[parent_intent]
            parent.exit_fill_ids.extend(fid for r in exit_recs for fid in r.fill_ids)

            parent_yes = parent.fill_yes_delta_cc or 0
            if parent_yes == 0:
                continue
            total_exit_yes = sum((r.fill_yes_delta_cc or 0) for r in exit_recs)
            net_yes = parent_yes + total_exit_yes
            # A proper exit should move the signed-YES exposure toward 0.
            # If the net is still the same sign or larger, the exit overshot/reversed.
            if net_yes != 0 and abs(net_yes) >= abs(parent_yes):
                for r in exit_recs:
                    if "exit_exposure_reversal" not in r.divergence_flags:
                        r.divergence_flags.append("exit_exposure_reversal")
                        self._promote_to_critical(r)

        self._summary.record_count = len(records)
        self._summary.build_ts = datetime.now(timezone.utc).isoformat()

        try:
            self._write_jsonl(records)
        except Exception as e:
            logger.error("[GOLDEN-RECORD] jsonl write failed: %s", e)
            self._summary.errors.append(f"jsonl write error: {e}")

        try:
            self._write_db(records)
        except Exception as e:
            logger.error("[GOLDEN-RECORD] db write failed: %s", e)
            self._summary.errors.append(f"db write error: {e}")

        logger.info(
            "[GOLDEN-RECORD] built %d records; %d with divergence",
            len(records),
            self._summary.divergence_count,
        )

        return records, self._summary


def build_golden_records(
    fact_db: Optional[str] = None,
    decision_telemetry: Optional[str] = None,
    settlement_outcomes: Optional[str] = None,
    fills_db: Optional[str] = None,
    lookback_hours: Optional[int] = None,
    out_jsonl: Optional[str] = None,
    out_db: Optional[str] = None,
    rebuild_db: bool = True,
) -> Tuple[List[GoldenRecord], GoldenRecordSummary]:
    """Convenience entry point for the golden-record builder."""
    builder = GoldenRecordBuilder(
        fact_db=fact_db,
        decision_telemetry=decision_telemetry,
        settlement_outcomes=settlement_outcomes,
        fills_db=fills_db,
        lookback_hours=lookback_hours,
        out_jsonl=out_jsonl,
        out_db=out_db,
        rebuild_db=rebuild_db,
    )
    return builder.build()

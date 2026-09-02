"""Immutable point-in-time decision/audit ledger.

A SQLite-backed, append-only decision table that records every trade and no-trade
before any order is submitted, together with a point-in-time market snapshot and a
per-side executable-EV decomposition.  Outcomes are joined later from settlement
events so the ledger can produce calibration, Brier, reliability, and
counterfactual-PnL reports.

The recorder is fail-open: a SQLite write error must never block or delay the
live trading path.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.execution.decision_audit_ledger")

_DB_PATH = Path(os.environ.get("MERID_DECISION_AUDIT_DB_PATH", "data/decision_audit.db"))
_WAL = os.environ.get("MERID_DECISION_AUDIT_LEDGER_WAL", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)


def _is_enabled() -> bool:
    """Read the enable flag at call time so tests and env changes are honored."""
    return os.environ.get("MERID_DECISION_AUDIT_LEDGER_ENABLED", "1").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _is_test_context() -> bool:
    """Detect pytest/test runtime so research rows are never marked as live."""
    return (
        "PYTEST_CURRENT_TEST" in os.environ
        or os.environ.get("MERID_ENV", "").lower() in ("test", "ci")
    )


def _is_production_db(path: Path) -> bool:
    """Return True if ``path`` is the live production decision-audit database."""
    return path.resolve() == _DB_PATH.resolve()


_SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA synchronous = FULL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;

CREATE TABLE IF NOT EXISTS strategy_decisions (
    decision_id TEXT PRIMARY KEY,
    parent_decision_id TEXT,
    decision_ts REAL NOT NULL,
    observed_at_ts REAL NOT NULL,
    decision_ts_iso TEXT NOT NULL,
    strategy_name TEXT NOT NULL,
    strategy_version TEXT NOT NULL,
    model_version TEXT NOT NULL,
    calibration_version TEXT,
    config_version TEXT NOT NULL,
    ticker TEXT NOT NULL,
    asset TEXT NOT NULL,
    market_open_ts REAL,
    close_ts REAL NOT NULL,
    close_ts_iso TEXT NOT NULL,
    seconds_to_close REAL NOT NULL,
    strike REAL,
    settlement_reference TEXT NOT NULL,
    settlement_rule_version TEXT NOT NULL,
    selected_side TEXT,
    decision TEXT NOT NULL,
    primary_reason_code TEXT NOT NULL,
    reason_codes TEXT NOT NULL DEFAULT '[]',
    record_environment TEXT NOT NULL DEFAULT 'production',
    record_source TEXT NOT NULL DEFAULT 'live',
    is_eligible_for_research INTEGER NOT NULL DEFAULT 1,
    exclusion_reason TEXT,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_decisions_ts ON strategy_decisions(decision_ts);
CREATE INDEX IF NOT EXISTS idx_decisions_ticker ON strategy_decisions(ticker, decision_ts);
CREATE INDEX IF NOT EXISTS idx_decisions_reason ON strategy_decisions(primary_reason_code, decision_ts);

CREATE TABLE IF NOT EXISTS strategy_decision_snapshots (
    decision_id TEXT PRIMARY KEY,
    spot_price REAL,
    spot_source TEXT,
    spot_source_ts REAL,
    spot_age_ms INTEGER,
    settlement_reference_price REAL,
    settlement_reference_source TEXT,
    settlement_reference_ts REAL,
    settlement_reference_age_ms INTEGER,
    spot_settlement_basis REAL,
    yes_bid_cents INTEGER,
    yes_ask_cents INTEGER,
    no_bid_cents INTEGER,
    no_ask_cents INTEGER,
    book_age_ms INTEGER,
    book_sequence TEXT,
    book_snapshot_id TEXT,
    book_is_crossed INTEGER NOT NULL DEFAULT 0,
    book_is_executable INTEGER NOT NULL DEFAULT 0,
    yes_depth TEXT NOT NULL DEFAULT '[]',
    no_depth TEXT NOT NULL DEFAULT '[]',
    raw_p_yes REAL,
    raw_p_no REAL,
    calibrated_p_yes REAL,
    calibrated_p_no REAL,
    vol_forecast REAL,
    vol_source TEXT,
    vol_age_ms INTEGER,
    realized_vol_1s REAL,
    realized_vol_5s REAL,
    realized_vol_1m REAL,
    realized_vol_5m REAL,
    zscore REAL,
    distance_to_strike REAL,
    log_moneyness REAL,
    velocity REAL,
    velocity_source TEXT,
    velocity_age_ms INTEGER,
    confidence REAL,
    confidence_reasons TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS strategy_decision_side_ev (
    decision_id TEXT NOT NULL,
    side TEXT NOT NULL,
    eligible_for_model INTEGER NOT NULL DEFAULT 0,
    eligible_for_policy INTEGER NOT NULL DEFAULT 0,
    exclusion_reason TEXT,
    model_evaluated INTEGER NOT NULL DEFAULT 0,
    policy_eligible INTEGER NOT NULL DEFAULT 0,
    executable INTEGER NOT NULL DEFAULT 0,
    passed_net_ev INTEGER NOT NULL DEFAULT 0,
    selected INTEGER NOT NULL DEFAULT 0,
    executable_entry_price_cents INTEGER,
    executable_entry_depth_fp REAL,
    expected_entry_fill_cents INTEGER,
    expected_entry_slippage_cents REAL,
    raw_probability REAL,
    calibrated_probability REAL,
    gross_edge_cents REAL,
    entry_fee_cents REAL,
    exit_or_settlement_fee_cents REAL,
    adverse_selection_haircut_cents REAL,
    model_uncertainty_haircut_cents REAL,
    expected_net_ev_cents REAL,
    lower_confidence_bound_ev_cents REAL,
    required_edge_cents REAL,
    passed_edge_gate INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (decision_id, side)
);

CREATE UNIQUE INDEX IF NOT EXISTS strategy_decision_side_once ON strategy_decision_side_ev(decision_id, side);

CREATE TABLE IF NOT EXISTS strategy_decision_outcomes (
    decision_id TEXT PRIMARY KEY,
    settled_at REAL,
    settled_yes INTEGER,
    settlement_value_cents INTEGER,
    counterfactual_yes_pnl_cents REAL,
    counterfactual_no_pnl_cents REAL,
    order_intent_id TEXT,
    exchange_order_id TEXT,
    fill_id TEXT,
    actual_fill_price_cents INTEGER,
    actual_entry_fee_cents REAL,
    actual_exit_price_cents INTEGER,
    actual_exit_fee_cents REAL,
    realized_net_pnl_cents REAL,
    outcome_status TEXT NOT NULL DEFAULT 'PENDING'
);

CREATE INDEX IF NOT EXISTS idx_outcomes_status ON strategy_decision_outcomes(outcome_status);

CREATE TABLE IF NOT EXISTS decision_audit_gaps (
    gap_id TEXT PRIMARY KEY,
    start_ts REAL NOT NULL,
    end_ts REAL NOT NULL,
    cause TEXT NOT NULL,
    disposition TEXT NOT NULL,
    affected_decisions_estimate INTEGER,
    process_version TEXT,
    detected_ts REAL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_gaps_ts ON decision_audit_gaps(start_ts, end_ts);

CREATE TABLE IF NOT EXISTS decision_audit_heartbeats (
    cycle_id TEXT PRIMARY KEY,
    tick INTEGER,
    assets_evaluated INTEGER,
    decisions_expected INTEGER,
    decisions_persisted INTEGER,
    snapshots_persisted INTEGER,
    side_ev_expected INTEGER,
    side_ev_persisted INTEGER,
    ledger_write_latency_ms REAL,
    ledger_error_count INTEGER,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_heartbeats_tick ON decision_audit_heartbeats(tick, created_at);
"""

# Canonical 10c-75c entry range used by the live strategy.  The floor may be
# raised further by MERID_TAIL_CALIBRATION_PRICE_FLOOR, but the snapshot table
# only records the raw executable price; the side-EV table records the policy
# eligibility for this canonical band.
_CANONICAL_MIN_CENTS = 10
_CANONICAL_MAX_CENTS = 75


@dataclass(frozen=True)
class DecisionAuditClassification:
    decision: str
    primary_reason_code: str
    reason_codes: List[str] = field(default_factory=list)


class DecisionAuditLedger:
    """SQLite-backed, append-only decision audit ledger.

    All writes are serialized through a single process lock.  Failures are
    logged but never raised to callers.
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path) if db_path else _DB_PATH
        self._lock = threading.Lock()
        self._db_ready = False
        self._cycle_stats: Dict[str, Dict[str, Any]] = {}

    def _ensure_db(self) -> None:
        """Create parent directory, schema, and run migrations on first use."""
        if self._db_ready:
            return
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self._lock, self._conn(isolation_level=None) as conn:
                conn.executescript(_SCHEMA)
                self._migrate(conn)
                self._register_known_gaps(conn)
            self._db_ready = True
        except Exception as exc:
            logger.warning("[DECISION-AUDIT-LEDGER] schema init failed: %s", exc)

    def _conn(self, isolation_level: Optional[str] = "IMMEDIATE") -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.isolation_level = isolation_level
        conn.row_factory = sqlite3.Row
        if isolation_level is not None:
            conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Idempotent migrations for the point-in-time audit ledger."""
        # Provenance / research-eligibility columns on the decision table.
        _add_column(conn, "strategy_decisions", "record_environment", "TEXT NOT NULL DEFAULT 'production'")
        _add_column(conn, "strategy_decisions", "record_source", "TEXT NOT NULL DEFAULT 'live'")
        _add_column(conn, "strategy_decisions", "is_eligible_for_research", "INTEGER NOT NULL DEFAULT 1")
        _add_column(conn, "strategy_decisions", "exclusion_reason", "TEXT")
        _add_column(conn, "strategy_decisions", "shadow_cohort_json", "TEXT")

        # Add the research/environment index now that the column is guaranteed to exist.
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_decisions_environment "
            "ON strategy_decisions(record_environment, decision_ts)"
        )

        # Evaluation / eligibility dimensions on side-EV rows.
        _add_column(conn, "strategy_decision_side_ev", "model_evaluated", "INTEGER NOT NULL DEFAULT 0")
        _add_column(conn, "strategy_decision_side_ev", "policy_eligible", "INTEGER NOT NULL DEFAULT 0")
        _add_column(conn, "strategy_decision_side_ev", "executable", "INTEGER NOT NULL DEFAULT 0")
        _add_column(conn, "strategy_decision_side_ev", "passed_net_ev", "INTEGER NOT NULL DEFAULT 0")
        _add_column(conn, "strategy_decision_side_ev", "selected", "INTEGER NOT NULL DEFAULT 0")

        # Enforce exactly one row per (decision_id, side).
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS strategy_decision_side_once "
            "ON strategy_decision_side_ev(decision_id, side)"
        )

        # Backfill new side-EV columns from the existing eligibility/edge fields.
        conn.execute(
            "UPDATE strategy_decision_side_ev "
            "SET model_evaluated = eligible_for_model "
            "WHERE model_evaluated = 0 AND eligible_for_model = 1"
        )
        conn.execute(
            "UPDATE strategy_decision_side_ev "
            "SET policy_eligible = eligible_for_policy "
            "WHERE policy_eligible = 0 AND eligible_for_policy = 1"
        )
        conn.execute(
            "UPDATE strategy_decision_side_ev "
            "SET passed_net_ev = passed_edge_gate "
            "WHERE passed_net_ev = 0 AND passed_edge_gate = 1"
        )
        conn.execute(
            "UPDATE strategy_decision_side_ev "
            "SET executable = 1 "
            "WHERE executable = 0 "
            "  AND executable_entry_price_cents IS NOT NULL "
            "  AND executable_entry_depth_fp > 0"
        )
        conn.execute(
            "UPDATE strategy_decision_side_ev "
            "SET selected = 1 "
            "WHERE rowid IN ("
            "    SELECT ev.rowid "
            "    FROM strategy_decision_side_ev ev "
            "    JOIN strategy_decisions d ON d.decision_id = ev.decision_id "
            "    WHERE d.decision = 'ENTER' AND d.selected_side = ev.side"
            ")"
        )

        # Quarantine the known pre-production test fixture leak.
        conn.execute(
            "UPDATE strategy_decisions "
            "SET record_environment = 'test', "
            "    record_source = 'test_fixture_leak', "
            "    is_eligible_for_research = 0, "
            "    exclusion_reason = 'pre-production default-db test artifact' "
            "WHERE decision_id = 'run_no_edge_below_threshold'"
        )

    def _register_known_gaps(self, conn: sqlite3.Connection) -> None:
        """Record known, verified collection discontinuities.

        These are permanent operational metadata, not research rows, and must not
        be removed or backfilled with synthetic data.
        """
        _KNOWN_GAPS = [
            {
                "gap_id": "ledger_migration_2026_09_01_0341_0346",
                "start_ts": 1788320481.0,
                "end_ts": 1788320813.0,
                "cause": "schema migration failure: missing provenance column / index ordering in _SCHEMA",
                "disposition": "exclude from completeness-rate denominator; no synthetic backfill",
                "affected_decisions_estimate": None,
                "process_version": os.environ.get("MERID_BUILD_SHA", "unknown"),
                "detected_ts": 1788320813.0,
            },
        ]
        for gap in _KNOWN_GAPS:
            conn.execute(
                """
                INSERT OR IGNORE INTO decision_audit_gaps (
                    gap_id, start_ts, end_ts, cause, disposition, affected_decisions_estimate,
                    process_version, detected_ts, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    gap["gap_id"],
                    gap["start_ts"],
                    gap["end_ts"],
                    gap["cause"],
                    gap["disposition"],
                    gap["affected_decisions_estimate"],
                    gap["process_version"],
                    gap["detected_ts"],
                    time.time(),
                ),
            )

    # ── Public recording API ───────────────────────────────────────────────

    def record_trade_decision(
        self,
        decision: Any,
        *,
        cycle_id: Optional[str] = None,
        market_state: Optional[Any] = None,
        spot_source: Optional[str] = None,
        spot_source_ts: Optional[float] = None,
        spot_age_ms: Optional[int] = None,
        settlement_reference_price: Optional[float] = None,
        settlement_reference_source: Optional[str] = None,
        settlement_reference_ts: Optional[float] = None,
        settlement_reference_age_ms: Optional[int] = None,
        quote_age_ms: Optional[int] = None,
        vol_age_ms: Optional[int] = None,
        realized_vol_1s: Optional[float] = None,
        realized_vol_5s: Optional[float] = None,
        realized_vol_1m: Optional[float] = None,
        realized_vol_5m: Optional[float] = None,
        velocity: Optional[float] = None,
        velocity_source: Optional[str] = None,
        velocity_age_ms: Optional[int] = None,
    ) -> bool:
        """Persist a full trade/no-trade decision with snapshot and side-EV.

        The ``decision`` object is expected to expose the same fields as
        :class:`merid.prediction.trade_decision.TradeDecision`.  Extra market
        provenance (spot source/age, quote age, etc.) is supplied as kwargs.

        Returns True if the bundle was durably committed, False otherwise.
        Fail-open: any exception is logged and not re-raised.
        """
        if not _is_enabled():
            return False
        if _is_test_context() and _is_production_db(self.db_path):
            logger.critical(
                "[DECISION-AUDIT-LEDGER] test context is writing to production db %s; refusing",
                self.db_path,
            )
            return False

        self._ensure_db()
        start = time.perf_counter()
        try:
            self._insert_trade_decision(
                decision,
                market_state,
                spot_source,
                spot_source_ts,
                spot_age_ms,
                settlement_reference_price,
                settlement_reference_source,
                settlement_reference_ts,
                settlement_reference_age_ms,
                quote_age_ms,
                vol_age_ms,
                realized_vol_1s,
                realized_vol_5s,
                realized_vol_1m,
                realized_vol_5m,
                velocity,
                velocity_source,
                velocity_age_ms,
            )
            latency_ms = (time.perf_counter() - start) * 1000.0
            self._bump_cycle_stats(
                cycle_id,
                expected=1,
                persisted=1,
                snapshots=1,
                side_ev=2,
                latency_ms=latency_ms,
            )
            return True
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            self._bump_cycle_stats(
                cycle_id,
                expected=1,
                persisted=0,
                snapshots=0,
                side_ev=0,
                latency_ms=latency_ms,
                is_error=True,
            )
            logger.warning(
                "[DECISION-AUDIT-LEDGER] record_trade_decision failed for %s: %s",
                getattr(decision, "decision_id", None),
                exc,
            )
            return False

    def record_pre_decision_rejection(
        self,
        *,
        cycle_id: Optional[str] = None,
        run_id: str,
        ticker: str,
        asset: str,
        reason: str,
        seconds_to_expiry: Optional[float] = None,
        spot_price: Optional[float] = None,
        strike_price: Optional[float] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Persist a rejection that occurs before a TradeDecision is created.

        Examples: market not entry-ready, missing strike, feed precision
        insufficient.  These carry no side-EV but still become settled
        counterfactuals for calibration/segmentation analysis.

        Returns True if the bundle was durably committed, False otherwise.
        Fail-open: any exception is logged and not re-raised.
        """
        if not _is_enabled():
            return False
        if _is_test_context() and _is_production_db(self.db_path):
            logger.critical(
                "[DECISION-AUDIT-LEDGER] test context is writing to production db %s; refusing",
                self.db_path,
            )
            return False

        self._ensure_db()
        start = time.perf_counter()
        try:
            decision_id = f"{run_id}_{ticker}_{uuid.uuid4().hex[:8]}"
            classification = _classify_no_trade_reason(reason)
            now = time.time()
            now_dt = datetime.fromtimestamp(now, tz=timezone.utc)
            close_ts = (
                now + float(seconds_to_expiry)
                if seconds_to_expiry is not None
                else now
            )
            close_dt = datetime.fromtimestamp(close_ts, tz=timezone.utc)
            strategy_name = os.environ.get("MERID_PROFILE", "kalshi_crypto_15m_v2")

            test_context = _is_test_context()
            if test_context and self.db_path == _DB_PATH:
                logger.critical(
                    "[DECISION-AUDIT-LEDGER] test context is writing to production db %s",
                    self.db_path,
                )
            record_environment = "test" if test_context else "production"
            record_source = "test_pre_decision" if test_context else "pre_decision_rejection"
            is_eligible_for_research = 0 if test_context else 1
            exclusion_reason = reason

            with self._lock, self._conn() as conn:
                # Atomic bundle for pre-decision rejections: decision + snapshot + pending outcome.
                conn.execute("BEGIN IMMEDIATE")
                conn.execute(
                    """
                    INSERT INTO strategy_decisions (
                        decision_id, parent_decision_id, decision_ts, observed_at_ts,
                        decision_ts_iso, strategy_name, strategy_version, model_version,
                        calibration_version, config_version, ticker, asset, market_open_ts,
                        close_ts, close_ts_iso, seconds_to_close, strike, settlement_reference,
                        settlement_rule_version, selected_side, decision, primary_reason_code,
                        reason_codes, record_environment, record_source, is_eligible_for_research,
                        exclusion_reason, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision_id,
                        None,
                        now,
                        now,
                        now_dt.isoformat(),
                        strategy_name,
                        "pre_decision_rejection",
                        "pre_decision_rejection",
                        None,
                        (extra.get("config_hash") if extra else None) or "unknown",
                        ticker,
                        asset,
                        None,
                        close_ts,
                        close_dt.isoformat(),
                        seconds_to_expiry or 0.0,
                        strike_price,
                        extra.get("settlement_reference", "unknown") if extra else "unknown",
                        "unknown",
                        None,
                        classification.decision,
                        classification.primary_reason_code,
                        json.dumps(classification.reason_codes),
                        record_environment,
                        record_source,
                        is_eligible_for_research,
                        exclusion_reason,
                        now,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO strategy_decision_snapshots (
                        decision_id, spot_price, spot_source, spot_source_ts, spot_age_ms,
                        settlement_reference_price, settlement_reference_source,
                        settlement_reference_ts, settlement_reference_age_ms,
                        yes_bid_cents, yes_ask_cents, no_bid_cents, no_ask_cents,
                        book_age_ms, yes_depth, no_depth
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision_id,
                        spot_price,
                        extra.get("spot_source") if extra else None,
                        extra.get("spot_source_ts") if extra else None,
                        extra.get("spot_age_ms") if extra else None,
                        None,
                        None,
                        None,
                        None,
                        extra.get("yes_bid_cents") if extra else None,
                        extra.get("yes_ask_cents") if extra else None,
                        extra.get("no_bid_cents") if extra else None,
                        extra.get("no_ask_cents") if extra else None,
                        extra.get("quote_age_ms") if extra else None,
                        "[]",
                        "[]",
                    ),
                )
                conn.execute(
                    "INSERT INTO strategy_decision_outcomes (decision_id) VALUES (?)",
                    (decision_id,),
                )
            latency_ms = (time.perf_counter() - start) * 1000.0
            self._bump_cycle_stats(
                cycle_id,
                expected=1,
                persisted=1,
                snapshots=1,
                side_ev=0,
                latency_ms=latency_ms,
            )
            return True
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            self._bump_cycle_stats(
                cycle_id,
                expected=1,
                persisted=0,
                snapshots=0,
                side_ev=0,
                latency_ms=latency_ms,
                is_error=True,
            )
            logger.warning(
                "[DECISION-AUDIT-LEDGER] record_pre_decision_rejection failed for %s: %s",
                ticker,
                exc,
            )
            return False

    def record_outcome(
        self,
        *,
        decision_id: str,
        order_intent_id: Optional[str] = None,
        exchange_order_id: Optional[str] = None,
        fill_id: Optional[str] = None,
        actual_fill_price_cents: Optional[int] = None,
        actual_entry_fee_cents: Optional[float] = None,
        actual_exit_price_cents: Optional[int] = None,
        actual_exit_fee_cents: Optional[float] = None,
        realized_net_pnl_cents: Optional[float] = None,
    ) -> None:
        """Append execution outcome to a previously recorded decision."""
        if not _is_enabled():
            return

        self._ensure_db()
        try:
            with self._lock, self._conn() as conn:
                conn.execute(
                    """
                    UPDATE strategy_decision_outcomes
                    SET order_intent_id = COALESCE(?, order_intent_id),
                        exchange_order_id = COALESCE(?, exchange_order_id),
                        fill_id = COALESCE(?, fill_id),
                        actual_fill_price_cents = COALESCE(?, actual_fill_price_cents),
                        actual_entry_fee_cents = COALESCE(?, actual_entry_fee_cents),
                        actual_exit_price_cents = COALESCE(?, actual_exit_price_cents),
                        actual_exit_fee_cents = COALESCE(?, actual_exit_fee_cents),
                        realized_net_pnl_cents = COALESCE(?, realized_net_pnl_cents)
                    WHERE decision_id = ?
                    """,
                    (
                        order_intent_id,
                        exchange_order_id,
                        fill_id,
                        actual_fill_price_cents,
                        actual_entry_fee_cents,
                        actual_exit_price_cents,
                        actual_exit_fee_cents,
                        realized_net_pnl_cents,
                        decision_id,
                    ),
                )
        except Exception as exc:
            logger.warning(
                "[DECISION-AUDIT-LEDGER] record_outcome failed for %s: %s",
                decision_id,
                exc,
            )

    def record_settlement(
        self,
        ticker: str,
        close_ts: float,
        settled_yes: bool,
        settlement_value_cents: int,
    ) -> None:
        """Join a market settlement to all pending decisions for this ticker/window.

        Computes conservative counterfactual PnL for both the YES and NO side of
        every decision using the recorded side-EV costs.  Outcomes that already
        have an execution fill are left untouched except for the settlement flag.
        """
        if not _is_enabled():
            return

        self._ensure_db()
        try:
            with self._lock, self._conn() as conn:
                rows = conn.execute(
                    """
                    SELECT d.decision_id, d.close_ts
                    FROM strategy_decisions d
                    JOIN strategy_decision_outcomes o ON d.decision_id = o.decision_id
                    WHERE d.ticker = ?
                      AND o.outcome_status = 'PENDING'
                      AND ABS(d.close_ts - ?) <= 900.0
                    """,
                    (ticker, close_ts),
                ).fetchall()

                for row in rows:
                    decision_id = row["decision_id"]
                    side_rows = conn.execute(
                        "SELECT * FROM strategy_decision_side_ev WHERE decision_id = ?",
                        (decision_id,),
                    ).fetchall()

                    yes_pnl: Optional[float] = None
                    no_pnl: Optional[float] = None
                    for srow in side_rows:
                        side = srow["side"]
                        entry_cents = srow["executable_entry_price_cents"]
                        entry_fee = srow["entry_fee_cents"] or 0.0
                        exit_fee = srow["exit_or_settlement_fee_cents"] or 0.0
                        if entry_cents is None:
                            continue
                        if side == "yes":
                            if settlement_value_cents is not None:
                                yes_pnl = (
                                    settlement_value_cents
                                    - entry_cents
                                    - entry_fee
                                    - exit_fee
                                )
                        elif side == "no":
                            if settlement_value_cents is not None:
                                no_pnl = (
                                    (100 - settlement_value_cents)
                                    - entry_cents
                                    - entry_fee
                                    - exit_fee
                                )

                    conn.execute(
                        """
                        UPDATE strategy_decision_outcomes
                        SET settled_at = ?, settled_yes = ?, settlement_value_cents = ?,
                            counterfactual_yes_pnl_cents = ?,
                            counterfactual_no_pnl_cents = ?,
                            outcome_status = ?
                        WHERE decision_id = ?
                        """,
                        (
                            time.time(),
                            1 if settled_yes else 0,
                            settlement_value_cents,
                            yes_pnl,
                            no_pnl,
                            "SETTLED",
                            decision_id,
                        ),
                    )
        except Exception as exc:
            logger.warning(
                "[DECISION-AUDIT-LEDGER] record_settlement failed for %s: %s",
                ticker,
                exc,
            )

    def record_data_gap(
        self,
        *,
        gap_id: str,
        start_ts: float,
        end_ts: float,
        cause: str,
        disposition: str,
        affected_decisions_estimate: Optional[int] = None,
        process_version: Optional[str] = None,
    ) -> None:
        """Record a verified collection discontinuity.

        Gap rows are operational metadata; they are surfaced by the audit report but
        are never eligible for research or backfill.
        """
        if not _is_enabled():
            return
        self._ensure_db()
        try:
            with self._lock, self._conn() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO decision_audit_gaps (
                        gap_id, start_ts, end_ts, cause, disposition, affected_decisions_estimate,
                        process_version, detected_ts, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        gap_id,
                        start_ts,
                        end_ts,
                        cause,
                        disposition,
                        affected_decisions_estimate,
                        process_version,
                        time.time(),
                        time.time(),
                    ),
                )
        except Exception as exc:
            logger.warning("[DECISION-AUDIT-LEDGER] record_data_gap failed for %s: %s", gap_id, exc)

    def record_heartbeat(
        self,
        *,
        cycle_id: str,
        tick: int,
        assets_evaluated: int,
        decisions_expected: int,
        decisions_persisted: int,
        snapshots_persisted: int,
        side_ev_expected: int,
        side_ev_persisted: int,
        ledger_write_latency_ms: float,
        ledger_error_count: int,
    ) -> None:
        """Persist a per-cycle write-completeness heartbeat.

        Operational counterpart to the append-only decision stream; used for
        detecting collection gaps without blocking the trading loop.
        """
        if not _is_enabled():
            return
        self._ensure_db()
        try:
            with self._lock, self._conn() as conn:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO decision_audit_heartbeats (
                        cycle_id, tick, assets_evaluated, decisions_expected, decisions_persisted,
                        snapshots_persisted, side_ev_expected, side_ev_persisted,
                        ledger_write_latency_ms, ledger_error_count, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cycle_id,
                        tick,
                        assets_evaluated,
                        decisions_expected,
                        decisions_persisted,
                        snapshots_persisted,
                        side_ev_expected,
                        side_ev_persisted,
                        ledger_write_latency_ms,
                        ledger_error_count,
                        time.time(),
                    ),
                )
        except Exception as exc:
            logger.warning("[DECISION-AUDIT-LEDGER] record_heartbeat failed for %s: %s", cycle_id, exc)

    def _bump_cycle_stats(
        self,
        cycle_id: Optional[str],
        *,
        expected: int,
        persisted: int,
        snapshots: int,
        side_ev: int,
        latency_ms: float,
        is_error: bool = False,
    ) -> None:
        """Increment per-cycle write counters for the trading loop heartbeat."""
        if cycle_id is None:
            return
        with self._lock:
            stats = self._cycle_stats.setdefault(
                cycle_id,
                {
                    "expected": 0,
                    "persisted": 0,
                    "snapshots": 0,
                    "side_ev": 0,
                    "latency_ms": 0.0,
                    "error_count": 0,
                },
            )
            stats["expected"] += expected
            stats["persisted"] += persisted
            stats["snapshots"] += snapshots
            stats["side_ev"] += side_ev
            stats["latency_ms"] += latency_ms
            if is_error:
                stats["error_count"] += 1

    def log_cycle_heartbeat(
        self,
        cycle_id: str,
        *,
        tick: int,
        assets_evaluated: int,
    ) -> None:
        """Log and persist the write-completeness heartbeat for a completed cycle.

        This should be called once per agent-grid cycle after all recording
        attempts for that cycle have finished.
        """
        with self._lock:
            stats = self._cycle_stats.pop(cycle_id, None)
        if stats is None:
            stats = {
                "expected": 0,
                "persisted": 0,
                "snapshots": 0,
                "side_ev": 0,
                "latency_ms": 0.0,
                "error_count": 0,
            }
        decisions_expected = stats["expected"]
        decisions_persisted = stats["persisted"]
        snapshots_persisted = stats["snapshots"]
        side_ev_expected = decisions_persisted * 2
        side_ev_persisted = stats["side_ev"]
        ledger_write_latency_ms = stats["latency_ms"]
        ledger_error_count = stats["error_count"]
        self.record_heartbeat(
            cycle_id=cycle_id,
            tick=tick,
            assets_evaluated=assets_evaluated,
            decisions_expected=decisions_expected,
            decisions_persisted=decisions_persisted,
            snapshots_persisted=snapshots_persisted,
            side_ev_expected=side_ev_expected,
            side_ev_persisted=side_ev_persisted,
            ledger_write_latency_ms=ledger_write_latency_ms,
            ledger_error_count=ledger_error_count,
        )
        logger.info(
            "[DECISION-AUDIT-HEARTBEAT] cycle_id=%s tick=%d assets=%d "
            "decisions_expected=%d decisions_persisted=%d "
            "side_ev_expected=%d side_ev_persisted=%d "
            "latency_ms=%.2f errors=%d",
            cycle_id,
            tick,
            assets_evaluated,
            decisions_expected,
            decisions_persisted,
            side_ev_expected,
            side_ev_persisted,
            ledger_write_latency_ms,
            ledger_error_count,
        )

    # ── Internal helpers ───────────────────────────────────────────────────

    def _insert_trade_decision(
        self,
        decision: Any,
        market_state: Optional[Any],
        spot_source: Optional[str],
        spot_source_ts: Optional[float],
        spot_age_ms: Optional[int],
        settlement_reference_price: Optional[float],
        settlement_reference_source: Optional[str],
        settlement_reference_ts: Optional[float],
        settlement_reference_age_ms: Optional[int],
        quote_age_ms: Optional[int],
        vol_age_ms: Optional[int],
        realized_vol_1s: Optional[float],
        realized_vol_5s: Optional[float],
        realized_vol_1m: Optional[float],
        realized_vol_5m: Optional[float],
        velocity: Optional[float],
        velocity_source: Optional[str],
        velocity_age_ms: Optional[int],
    ) -> None:
        decision_id = str(getattr(decision, "decision_id", ""))
        if not decision_id:
            return

        timestamp_utc = getattr(decision, "timestamp_utc", None)
        if isinstance(timestamp_utc, datetime):
            decision_ts = timestamp_utc.timestamp()
        else:
            decision_ts = time.time()

        seconds_to_expiry = _to_float(getattr(decision, "seconds_to_expiry", None))
        close_ts = decision_ts + (seconds_to_expiry or 0.0)
        close_dt = datetime.fromtimestamp(close_ts, tz=timezone.utc)

        classification = _classify_trade_decision(decision)
        indicators = dict(getattr(decision, "indicators", None) or {})

        selected_side = getattr(decision, "selected_outcome", None)
        decision_type = classification.decision
        primary_reason = classification.primary_reason_code
        reason_codes = classification.reason_codes

        strategy_name = os.environ.get("MERID_PROFILE", "kalshi_crypto_15m_v2")
        strategy_version = getattr(decision, "policy_version", "trade_decision_v2")
        model_version = getattr(decision, "policy_version", "trade_decision_v2")
        calibration_version = _tail_calibration_version(indicators)
        config_hash = (
            getattr(decision, "config_hash", None)
            or getattr(decision, "build_sha", None)
            or "unknown"
        )

        market_open_ts = None
        try:
            market_open_ts = close_ts - 900.0
        except Exception:
            pass

        strike = _to_float(indicators.get("strike"))
        spot_price = _to_float(
            settlement_reference_price
            or indicators.get("bachelier_spot")
            or getattr(decision, "spot_price", None)
        )

        # Market-state derived BBO and depth.
        yes_bid, yes_ask, no_bid, no_ask = _best_bid_ask(market_state)
        yes_depth, no_depth = _depth_levels(market_state)
        book_age_ms = _book_age_ms(market_state, decision_ts)
        book_is_crossed = _book_is_crossed(market_state)
        book_is_executable = _book_is_executable(market_state)
        book_sequence = _safe_attr(market_state, "book_sequence")
        book_snapshot_id = _safe_attr(market_state, "book_snapshot_id")

        # Executable reference provenance.
        if settlement_reference_source is None:
            settlement_reference_source = str(getattr(decision, "settlement_reference", "unknown"))
        if settlement_reference_price is None:
            settlement_reference_price = spot_price
        basis = None
        if spot_price is not None and settlement_reference_price is not None:
            basis = spot_price - settlement_reference_price

        # Probability features.
        p_yes_raw = _to_float(getattr(decision, "p_yes_raw", None))
        p_no_raw = _to_float(indicators.get("p_no_raw"))
        if p_no_raw is None and p_yes_raw is not None:
            p_no_raw = 1.0 - p_yes_raw
        p_yes_cal = _to_float(getattr(decision, "p_yes_calibrated", None))
        p_no_cal = _to_float(getattr(decision, "p_no_calibrated", None))

        # Volatility and feature provenance.
        vol_forecast = _to_float(indicators.get("annualized_vol"))
        vol_source = indicators.get("annualized_vol_source")
        zscore = _to_float(indicators.get("z_score"))
        log_moneyness = _to_float(indicators.get("log_moneyness"))
        confidence = _to_float(getattr(decision, "confidence", None))
        confidence_reasons = list(getattr(decision, "confidence_reasons", None) or [])

        if velocity is None:
            velocity = _to_float(indicators.get("velocity"))
        if velocity_source is None:
            velocity_source = indicators.get("velocity_source")

        # Provenance: never let a test run be marked as live research data.
        test_context = _is_test_context()
        if test_context and self.db_path == _DB_PATH:
            logger.critical(
                "[DECISION-AUDIT-LEDGER] test context is writing to production db %s",
                self.db_path,
            )
        record_environment = "test" if test_context else "production"
        record_source = "test" if test_context else "live"
        is_eligible_for_research = 0 if test_context else 1
        exclusion_reason: Optional[str] = None
        if decision_type == "NO_TRADE":
            exclusion_reason = getattr(decision, "no_trade_reason", None) or primary_reason

        # Insert core decision row.
        with self._lock, self._conn() as conn:
            # One atomic bundle: decision, snapshot, both side-EV rows, pending outcome.
            conn.execute("BEGIN IMMEDIATE")
            shadow_cohort = (indicators or {}).get("shadow_cohort")
            shadow_cohort_json = json.dumps(shadow_cohort, default=str) if shadow_cohort is not None else None

            conn.execute(
                """
                INSERT INTO strategy_decisions (
                    decision_id, parent_decision_id, decision_ts, observed_at_ts,
                    decision_ts_iso, strategy_name, strategy_version, model_version,
                    calibration_version, config_version, ticker, asset, market_open_ts,
                    close_ts, close_ts_iso, seconds_to_close, strike, settlement_reference,
                    settlement_rule_version, selected_side, decision, primary_reason_code,
                    reason_codes, record_environment, record_source, is_eligible_for_research,
                    exclusion_reason, shadow_cohort_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    None,
                    decision_ts,
                    decision_ts,
                    datetime.fromtimestamp(decision_ts, tz=timezone.utc).isoformat(),
                    strategy_name,
                    strategy_version,
                    model_version,
                    calibration_version,
                    config_hash or "unknown",
                    str(getattr(decision, "ticker", "")),
                    str(getattr(decision, "asset", "")),
                    market_open_ts,
                    close_ts,
                    close_dt.isoformat(),
                    seconds_to_expiry or 0.0,
                    strike,
                    settlement_reference_source,
                    settlement_reference_source,
                    selected_side,
                    decision_type,
                    primary_reason,
                    json.dumps(reason_codes),
                    record_environment,
                    record_source,
                    is_eligible_for_research,
                    exclusion_reason,
                    shadow_cohort_json,
                    time.time(),
                ),
            )

            # Insert point-in-time snapshot.
            conn.execute(
                """
                INSERT INTO strategy_decision_snapshots (
                    decision_id, spot_price, spot_source, spot_source_ts, spot_age_ms,
                    settlement_reference_price, settlement_reference_source,
                    settlement_reference_ts, settlement_reference_age_ms,
                    spot_settlement_basis, yes_bid_cents, yes_ask_cents, no_bid_cents,
                    no_ask_cents, book_age_ms, book_sequence, book_snapshot_id,
                    book_is_crossed, book_is_executable, yes_depth, no_depth,
                    raw_p_yes, raw_p_no, calibrated_p_yes, calibrated_p_no,
                    vol_forecast, vol_source, vol_age_ms, realized_vol_1s,
                    realized_vol_5s, realized_vol_1m, realized_vol_5m, zscore,
                    distance_to_strike, log_moneyness, velocity, velocity_source,
                    velocity_age_ms, confidence, confidence_reasons
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    spot_price,
                    spot_source,
                    spot_source_ts,
                    spot_age_ms,
                    settlement_reference_price,
                    settlement_reference_source,
                    settlement_reference_ts,
                    settlement_reference_age_ms,
                    basis,
                    yes_bid,
                    yes_ask,
                    no_bid,
                    no_ask,
                    quote_age_ms or book_age_ms,
                    book_sequence,
                    book_snapshot_id,
                    1 if book_is_crossed else 0,
                    1 if book_is_executable else 0,
                    json.dumps(yes_depth),
                    json.dumps(no_depth),
                    p_yes_raw,
                    p_no_raw,
                    p_yes_cal,
                    p_no_cal,
                    vol_forecast,
                    vol_source,
                    vol_age_ms,
                    realized_vol_1s,
                    realized_vol_5s,
                    realized_vol_1m,
                    realized_vol_5m,
                    zscore,
                    _distance_to_strike(spot_price, strike),
                    log_moneyness,
                    velocity,
                    velocity_source,
                    velocity_age_ms,
                    confidence,
                    json.dumps(confidence_reasons),
                ),
            )

            # Insert per-side EV rows for both YES and NO.
            for side in ("yes", "no"):
                side_row = _build_side_ev_row(
                    decision,
                    side,
                    indicators,
                    quote_age_ms,
                    market_state,
                )
                conn.execute(
                    """
                    INSERT INTO strategy_decision_side_ev (
                        decision_id, side, eligible_for_model, eligible_for_policy,
                        exclusion_reason, model_evaluated, policy_eligible, executable,
                        passed_net_ev, selected, executable_entry_price_cents,
                        executable_entry_depth_fp, expected_entry_fill_cents,
                        expected_entry_slippage_cents, raw_probability, calibrated_probability,
                        gross_edge_cents, entry_fee_cents, exit_or_settlement_fee_cents,
                        adverse_selection_haircut_cents, model_uncertainty_haircut_cents,
                        expected_net_ev_cents, lower_confidence_bound_ev_cents,
                        required_edge_cents, passed_edge_gate
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision_id,
                        side,
                        1 if side_row["eligible_for_model"] else 0,
                        1 if side_row["eligible_for_policy"] else 0,
                        side_row["exclusion_reason"],
                        1 if side_row["model_evaluated"] else 0,
                        1 if side_row["policy_eligible"] else 0,
                        1 if side_row["executable"] else 0,
                        1 if side_row["passed_net_ev"] else 0,
                        1 if side_row["selected"] else 0,
                        side_row["executable_entry_price_cents"],
                        side_row["executable_entry_depth_fp"],
                        side_row["expected_entry_fill_cents"],
                        side_row["expected_entry_slippage_cents"],
                        side_row["raw_probability"],
                        side_row["calibrated_probability"],
                        side_row["gross_edge_cents"],
                        side_row["entry_fee_cents"],
                        side_row["exit_or_settlement_fee_cents"],
                        side_row["adverse_selection_haircut_cents"],
                        side_row["model_uncertainty_haircut_cents"],
                        side_row["expected_net_ev_cents"],
                        side_row["lower_confidence_bound_ev_cents"],
                        side_row["required_edge_cents"],
                        1 if side_row["passed_edge_gate"] else 0,
                    ),
                )

            # Insert a PENDING outcome row for the settlement joiner to fill later.
            conn.execute(
                "INSERT INTO strategy_decision_outcomes (decision_id) VALUES (?)",
                (decision_id,),
            )


# ── Singleton ──────────────────────────────────────────────────────────────

_ledger_instance: Optional[DecisionAuditLedger] = None
_ledger_lock = threading.Lock()


def get_decision_audit_ledger() -> DecisionAuditLedger:
    """Return the process-wide decision audit ledger singleton."""
    global _ledger_instance
    if _ledger_instance is None:
        with _ledger_lock:
            if _ledger_instance is None:
                _ledger_instance = DecisionAuditLedger()
    return _ledger_instance


def reset_decision_audit_ledger(db_path: Optional[Path] = None) -> DecisionAuditLedger:
    """Reset the singleton; useful for tests and process restarts."""
    global _ledger_instance
    _ledger_instance = DecisionAuditLedger(db_path=db_path)
    return _ledger_instance


# ── Extraction / classification helpers ────────────────────────────────────


def _classify_trade_decision(decision: Any) -> DecisionAuditClassification:
    selected = getattr(decision, "selected_outcome", None)
    no_trade_reason = getattr(decision, "no_trade_reason", None)
    if selected is not None and not no_trade_reason:
        selection_reason = getattr(decision, "selection_reason", "selected")
        return DecisionAuditClassification(
            decision="ENTER",
            primary_reason_code="selected",
            reason_codes=["selected", selection_reason],
        )
    return _classify_no_trade_reason(no_trade_reason)


def _classify_no_trade_reason(no_trade_reason: Optional[str]) -> DecisionAuditClassification:
    reason = no_trade_reason or "unknown"
    lower = reason.lower()

    data_veto_prefixes = (
        "expired_or_no_time",
        "final_minute_entry_disabled",
        "data_state_not_healthy",
        "regime_unclassified",
        "regime_uncertain",
        "non_finite_",
        "invalid_executable_asks",
        "bachelier_vol_resolution_failed",
        "invalid_confidence",
    )
    if lower.startswith(data_veto_prefixes):
        return DecisionAuditClassification(
            decision="NO_TRADE",
            primary_reason_code="DATA_QUALITY_VETO",
            reason_codes=["DATA_QUALITY_VETO", reason],
        )

    policy_prefixes = (
        "both_sides_out_of_range",
        "both_sides_out_of_canonical",
        "thesis_side_out_of_range",
        "held_entry_price_below_floor",
    )
    if lower.startswith(policy_prefixes):
        return DecisionAuditClassification(
            decision="NO_TRADE",
            primary_reason_code="POLICY_EXCLUDED",
            reason_codes=["POLICY_EXCLUDED", reason],
        )

    risk_veto_prefixes = ("portfolio_heat", "rolling_pnl", "risk_")
    if lower.startswith(risk_veto_prefixes):
        return DecisionAuditClassification(
            decision="NO_TRADE",
            primary_reason_code="RISK_VETO",
            reason_codes=["RISK_VETO", reason],
        )

    # Edge / threshold / confidence / EV-gate rejections are all NO_EDGE.
    return DecisionAuditClassification(
        decision="NO_TRADE",
        primary_reason_code="NO_EDGE",
        reason_codes=["NO_EDGE", reason],
    )



def _build_side_ev_row(
    decision: Any,
    side: str,
    indicators: Dict[str, Any],
    quote_age_ms: Optional[int],
    market_state: Optional[Any],
) -> Dict[str, Any]:
    """Build one side-EV row from a TradeDecision and its EdgeBreakdown."""
    breakdown = getattr(decision, f"{side}_edge_breakdown", None)

    # Fallback to legacy net-edge fields if the breakdown dataclass is missing.
    if breakdown is None:
        return _legacy_side_ev_row(decision, side, indicators, market_state)

    entry_price = _to_float(breakdown.executable_entry_price)
    entry_fee = _to_float(breakdown.entry_fee)
    exit_cost = _to_float(breakdown.exit_cost_reserve)
    model_risk = _to_float(breakdown.model_risk_reserve)
    p_selected = _to_float(breakdown.p_selected)
    p_opposite = _to_float(breakdown.p_opposite)
    gross_edge = _to_float(breakdown.gross_edge)
    net_edge = _to_float(breakdown.net_edge)

    entry_price_cents = int(round(entry_price * 100)) if entry_price is not None else None
    entry_fee_cents = entry_fee * 100.0 if entry_fee is not None else 0.0
    exit_fee_cents = exit_cost * 100.0 if exit_cost is not None else 0.0
    model_risk_cents = model_risk * 100.0 if model_risk is not None else 0.0
    gross_edge_cents = gross_edge * 100.0 if gross_edge is not None else 0.0
    expected_net_ev_cents = net_edge * 100.0 if net_edge is not None else 0.0

    # Required edge per side when available, otherwise the decision's floor.
    side_min_edge = _to_float(indicators.get(f"{side}_min_edge"))
    if side_min_edge is None:
        side_min_edge = _to_float(getattr(decision, "min_required_edge", None)) or 0.0
    required_edge_cents = side_min_edge * 100.0

    # A side is "model eligible" when it has a finite, complete EV decomposition.
    eligible_for_model = (
        entry_price is not None
        and math.isfinite(gross_edge or 0.0)
        and math.isfinite(net_edge or 0.0)
    )

    # Policy eligibility: executable price inside the canonical 10c-75c band.
    in_canonical = (
        entry_price_cents is not None
        and _CANONICAL_MIN_CENTS <= entry_price_cents <= _CANONICAL_MAX_CENTS
    )
    eligible_for_policy = eligible_for_model and in_canonical

    # Edge gate: net edge clears the per-side dynamic threshold.
    passed_edge = (
        eligible_for_model
        and math.isfinite(net_edge)
        and net_edge * 100.0 >= required_edge_cents - 1e-9
    )

    # Infer an exclusion reason for the side when the no-trade reason applies.
    no_trade_reason = getattr(decision, "no_trade_reason", None) or ""
    best_side = getattr(decision, "best_side", None)
    exclusion_reason: Optional[str] = None
    if not passed_edge and best_side == side:
        exclusion_reason = no_trade_reason or "edge_below_threshold"
    elif not in_canonical:
        exclusion_reason = "out_of_canonical_range"
    elif not passed_edge:
        exclusion_reason = "edge_below_threshold"

    # Conservative lower-confidence bound: subtract uncertainty/reserves again.
    # This is intentionally conservative because the net edge already subtracted
    # these once; the LCB gives a stress estimate for downstream segmentation.
    lcb = None
    if math.isfinite(expected_net_ev_cents):
        lcb = expected_net_ev_cents - model_risk_cents

    depth_cc = _to_float(getattr(decision, f"{side}_depth_cc", None)) or 0.0
    expected_fill = entry_price_cents

    selected_outcome = getattr(decision, "selected_outcome", None)
    selected = (
        selected_outcome == side
        and not no_trade_reason
    )
    executable = (
        entry_price is not None
        and depth_cc > 0
        and _book_is_executable(market_state)
    )

    return {
        "eligible_for_model": bool(eligible_for_model),
        "eligible_for_policy": bool(eligible_for_policy),
        "exclusion_reason": exclusion_reason,
        "model_evaluated": bool(eligible_for_model),
        "policy_eligible": bool(eligible_for_policy),
        "executable": bool(executable),
        "passed_net_ev": bool(passed_edge),
        "selected": bool(selected),
        "executable_entry_price_cents": entry_price_cents,
        "executable_entry_depth_fp": float(depth_cc),
        "expected_entry_fill_cents": expected_fill,
        "expected_entry_slippage_cents": None,
        "raw_probability": p_selected,
        "calibrated_probability": p_opposite,
        "gross_edge_cents": gross_edge_cents,
        "entry_fee_cents": entry_fee_cents,
        "exit_or_settlement_fee_cents": exit_fee_cents,
        "adverse_selection_haircut_cents": 0.0,
        "model_uncertainty_haircut_cents": model_risk_cents,
        "expected_net_ev_cents": expected_net_ev_cents,
        "lower_confidence_bound_ev_cents": lcb,
        "required_edge_cents": required_edge_cents,
        "passed_edge_gate": bool(passed_edge),
    }


def _legacy_side_ev_row(
    decision: Any,
    side: str,
    indicators: Dict[str, Any],
    market_state: Optional[Any],
) -> Dict[str, Any]:
    """Fallback for older TradeDecision objects without EdgeBreakdown."""
    entry_price = _to_float(getattr(decision, f"{side}_entry_vwap", None))
    gross_edge = _to_float(getattr(decision, f"gross_edge_{side}", None))
    net_edge = _to_float(getattr(decision, f"{side}_net_edge", None))
    entry_fee = _to_float(getattr(decision, f"entry_fee_{side}", None))
    exit_cost = _to_float(getattr(decision, f"exit_cost_reserve_{side}", None))
    model_risk = _to_float(getattr(decision, f"model_risk_reserve_{side}", None))

    entry_price_cents = int(round(entry_price * 100)) if entry_price is not None else None
    gross_edge_cents = gross_edge * 100.0 if gross_edge is not None else None
    expected_net_ev_cents = net_edge * 100.0 if net_edge is not None else None
    entry_fee_cents = (entry_fee or 0.0) * 100.0
    exit_fee_cents = (exit_cost or 0.0) * 100.0
    model_risk_cents = (model_risk or 0.0) * 100.0

    side_min_edge = _to_float(indicators.get(f"{side}_min_edge"))
    if side_min_edge is None:
        side_min_edge = _to_float(getattr(decision, "min_required_edge", None)) or 0.0
    required_edge_cents = side_min_edge * 100.0

    passed_edge = (
        expected_net_ev_cents is not None
        and math.isfinite(expected_net_ev_cents)
        and expected_net_ev_cents >= required_edge_cents - 1e-9
    )

    in_canonical = (
        entry_price_cents is not None
        and _CANONICAL_MIN_CENTS <= entry_price_cents <= _CANONICAL_MAX_CENTS
    )

    lcb = None
    if expected_net_ev_cents is not None and math.isfinite(expected_net_ev_cents):
        lcb = expected_net_ev_cents - model_risk_cents

    selected_outcome = getattr(decision, "selected_outcome", None)
    no_trade_reason = getattr(decision, "no_trade_reason", None) or ""
    selected = (
        selected_outcome == side
        and not no_trade_reason
    )
    depth_cc = _to_float(getattr(decision, f"{side}_depth_cc", None)) or 0.0
    executable = (
        entry_price is not None
        and depth_cc > 0
        and _book_is_executable(market_state)
    )

    return {
        "eligible_for_model": entry_price is not None,
        "eligible_for_policy": entry_price is not None and in_canonical,
        "exclusion_reason": None,
        "model_evaluated": entry_price is not None,
        "policy_eligible": entry_price is not None and in_canonical,
        "executable": bool(executable),
        "passed_net_ev": bool(passed_edge),
        "selected": bool(selected),
        "executable_entry_price_cents": entry_price_cents,
        "executable_entry_depth_fp": float(depth_cc),
        "expected_entry_fill_cents": entry_price_cents,
        "expected_entry_slippage_cents": None,
        "raw_probability": _to_float(getattr(decision, f"p_{side}_calibrated", None)),
        "calibrated_probability": None,
        "gross_edge_cents": gross_edge_cents,
        "entry_fee_cents": entry_fee_cents,
        "exit_or_settlement_fee_cents": exit_fee_cents,
        "adverse_selection_haircut_cents": 0.0,
        "model_uncertainty_haircut_cents": model_risk_cents,
        "expected_net_ev_cents": expected_net_ev_cents,
        "lower_confidence_bound_ev_cents": lcb,
        "required_edge_cents": required_edge_cents,
        "passed_edge_gate": passed_edge,
    }



def _best_bid_ask(market_state: Optional[Any]) -> Tuple[Optional[int], ...]:
    """Return (yes_bid, yes_ask, no_bid, no_ask) in cents from market state."""
    if market_state is None:
        return (None, None, None, None)
    yes_bid = _to_int(getattr(market_state, "best_bid_cents", None))
    yes_ask = _to_int(getattr(market_state, "best_ask_cents", None))
    no_bid = _to_int(getattr(market_state, "best_no_bid_cents", None))
    no_ask = _to_int(getattr(market_state, "best_no_ask_cents", None))
    return (yes_bid, yes_ask, no_bid, no_ask)


def _depth_levels(market_state: Optional[Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Return top-of-book depth levels as JSON-serializable dicts."""
    if market_state is None:
        return ([], [])

    def _convert(levels: Any) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if not levels:
            return out
        for level in levels[:5]:
            if isinstance(level, (list, tuple)) and len(level) >= 2:
                out.append({"price_cents": _to_int(level[0]), "size_cc": _to_float(level[1])})
            elif isinstance(level, dict):
                out.append({
                    "price_cents": _to_int(level.get("price")),
                    "size_cc": _to_float(level.get("size")),
                })
        return out

    yes = _convert(getattr(market_state, "yes_bids", None))
    no = _convert(getattr(market_state, "no_bids", None))
    return (yes, no)


def _book_age_ms(market_state: Optional[Any], decision_ts: float) -> Optional[int]:
    """Estimate book age in milliseconds from market state's last update."""
    if market_state is None:
        return None
    last_update = getattr(market_state, "last_book_update_ts", None)
    if last_update is None:
        last_update = getattr(market_state, "last_book_update_wall_ts", None)
    if last_update is None:
        return None
    try:
        age_s = decision_ts - float(last_update)
        if age_s < 0:
            return 0
        return int(age_s * 1000.0)
    except Exception:
        return None


def _book_is_crossed(market_state: Optional[Any]) -> bool:
    if market_state is None:
        return False
    bid = _to_int(getattr(market_state, "best_bid_cents", None))
    ask = _to_int(getattr(market_state, "best_ask_cents", None))
    if bid is not None and ask is not None:
        return bid > ask
    return False


def _book_is_executable(market_state: Optional[Any]) -> bool:
    if market_state is None:
        return False
    if getattr(market_state, "book_initialized", False) is not True:
        return False
    if getattr(market_state, "data_quality", None) != "GOOD":
        return False
    if _book_is_crossed(market_state):
        return False
    return True


def _tail_calibration_version(indicators: Dict[str, Any]) -> Optional[str]:
    """Build a version fingerprint from the tail calibration fields in the decision."""
    parts = [
        "yes" if indicators.get("tail_calibration_yes_applied") else "no",
        "no" if indicators.get("tail_calibration_no_applied") else "no",
    ]
    return f"tail_calibration_v2:{':'.join(parts)}"


def _distance_to_strike(spot: Optional[float], strike: Optional[float]) -> Optional[float]:
    if spot is None or strike is None or strike == 0:
        return None
    try:
        return (spot - strike) / strike
    except Exception:
        return None


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        value = float(value)
    try:
        f = float(value)
        if not math.isfinite(f):
            return None
        return f
    except Exception:
        return None


def _to_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except Exception:
        return None


def _safe_attr(obj: Any, name: str) -> Optional[str]:
    if obj is None:
        return None
    value = getattr(obj, name, None)
    if value is None:
        return None
    return str(value)


def _add_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    """Add a column to a table if it does not already exist."""
    existing = {
        row[1]
        for row in conn.execute(f"PRAGMA table_info({table})")
    }
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

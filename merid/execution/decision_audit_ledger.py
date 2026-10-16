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

import atexit
import hashlib
import json
import logging
import math
import os
import queue
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.execution.decision_audit_ledger")

_DB_PATH = Path(os.environ.get("MERID_DECISION_AUDIT_DB_PATH", "data/decision_audit.db"))
_WAL = os.environ.get("MERID_DECISION_AUDIT_LEDGER_WAL", "1").strip().lower() in (
    "1",
    "true",
    "yes",
)
# Sentinel distinguishing "caller precomputed this" from "compute inline".
_PRECOMPUTE_UNSET = object()


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


def _latency_snapshot_field() -> str:
    """Compact latency-budget summary for the audit heartbeat.

    When latency is degraded we emit only the reasons (not full stats) —
    under load the heartbeat sheds verbose extras itself.
    """
    try:
        from merid.observability import latency_budget as _lat

        snap = _lat.snapshot()
        if not snap:
            return "-"
        if snap.get("degraded"):
            return "DEGRADED:" + ";".join(snap.get("degraded_reasons") or [])
        return ",".join(
            "%s=%sms" % (k.replace("_ms", ""), v["p95_ms"])
            for k, v in snap.items()
            if isinstance(v, dict)
        )
    except Exception:
        return "err"


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
    confidence_reasons TEXT NOT NULL DEFAULT '[]',
    quote_owner TEXT,
    degraded_mode INTEGER NOT NULL DEFAULT 0,
    ws_last_seq INTEGER,
    ws_last_event_age_ms REAL,
    ws_last_queue_wait_ms REAL,
    ws_rest_bid_diff_ticks INTEGER,
    ws_rest_ask_diff_ticks INTEGER,
    ws_parity_healthy INTEGER,
    rest_age_ms INTEGER
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
    gate_ev_cents REAL,
    enforced_edge_bound_cents REAL,
    decision_lane TEXT,
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
CREATE INDEX IF NOT EXISTS idx_outcomes_settled_at ON strategy_decision_outcomes(settled_at);

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

# Canonical entry range used by the live strategy (10c-95c since 2026-09-24;
# the old 75c ceiling banned every favorite-side buy).  The floor may be
# raised further by MERID_TAIL_CALIBRATION_PRICE_FLOOR, but the snapshot table
# only records the raw executable price; the side-EV table records the policy
# eligibility for this canonical band.
_CANONICAL_MIN_CENTS = 10
_CANONICAL_MAX_CENTS = 95

# ── Lifecycle events ───────────────────────────────────────────────────────
#
# ``strategy_decision_events`` is the append-only state-transition truth for the
# candidate lifecycle.  ``strategy_decisions.primary_reason_code`` remains the
# first decision-stage outcome and is never overwritten by downstream events.
#
# Event types (stable semantic names):
DECISION_EVENT_CANDIDATE_OBSERVED = "CANDIDATE_OBSERVED"
DECISION_EVENT_PRE_DECISION_REJECTED = "PRE_DECISION_REJECTED"
DECISION_EVENT_MODEL_REJECTED = "MODEL_REJECTED"
DECISION_EVENT_MODEL_SELECTED = "MODEL_SELECTED"
# A bounded lane's own emission budget (daily cap / per-asset-window dedupe)
# suppressed a model selection before a candidate was emitted — distinct from
# ALLOCATION_REJECTED because the allocator never saw it.
DECISION_EVENT_LANE_SUPPRESSED = "LANE_SUPPRESSED"
DECISION_EVENT_ALLOCATION_REJECTED = "ALLOCATION_REJECTED"
DECISION_EVENT_RISK_REJECTED = "RISK_REJECTED"
DECISION_EVENT_COOLDOWN_REJECTED = "COOLDOWN_REJECTED"
DECISION_EVENT_ROUTER_REJECTED = "ROUTER_REJECTED"
DECISION_EVENT_ORDER_SUBMITTED = "ORDER_SUBMITTED"
DECISION_EVENT_ORDER_FILLED = "ORDER_FILLED"
DECISION_EVENT_SETTLEMENT_RESOLVED = "SETTLEMENT_RESOLVED"
DECISION_EVENT_OUTCOME_UNRESOLVED = "OUTCOME_UNRESOLVED"
DECISION_EVENT_INSTRUMENTATION_GAP = "INSTRUMENTATION_GAP"

# Lifecycle stages.
DECISION_STAGE_DISCOVERY = "DISCOVERY"
DECISION_STAGE_PRE_DECISION = "PRE_DECISION"
DECISION_STAGE_MODEL = "MODEL"
DECISION_STAGE_ALLOCATION = "ALLOCATION"
DECISION_STAGE_RISK = "RISK"
DECISION_STAGE_COOLDOWN = "COOLDOWN"
DECISION_STAGE_ROUTER = "ROUTER"
DECISION_STAGE_EXECUTION = "EXECUTION"
DECISION_STAGE_SETTLEMENT = "SETTLEMENT"
DECISION_STAGE_OUTCOME = "OUTCOME"

DECISION_EVENT_SCHEMA_VERSION = 1

# Counterfactual model version tags persisted per side-EV row so the hourly
# report can restate P&L under a different assumption set without ambiguity.
COUNTERFACTUAL_FEE_MODEL_VERSION = "kalshi_contract_fee_v1"
COUNTERFACTUAL_SLIPPAGE_MODEL_VERSION = "decision_time_quote_v1"
COUNTERFACTUAL_FILL_MODEL_VERSION = "top_of_book_depth_cap_v1"

# Executability classifications for counterfactual P&L rows.
CF_FULLY_EXECUTABLE = "FULLY_EXECUTABLE"
CF_PARTIALLY_EXECUTABLE = "PARTIALLY_EXECUTABLE"
CF_NOT_EXECUTABLE_NO_DEPTH = "NOT_EXECUTABLE_NO_DEPTH"
CF_NOT_EXECUTABLE_STALE_BOOK = "NOT_EXECUTABLE_STALE_BOOK"
CF_NOT_EXECUTABLE_NO_PRICE = "NOT_EXECUTABLE_NO_PRICE"
CF_UNKNOWN_EXECUTABILITY = "UNKNOWN_EXECUTABILITY"
CF_NOT_APPLICABLE = "NOT_APPLICABLE"

# Scheduled WAL maintenance cadence (seconds).  The decision writer and any
# analytics readers share the multi-GB WAL; without periodic checkpoints the
# -wal grows unboundedly and every analytic scan pays merge + contention cost
# on the live file.  PASSIVE checkpoints never wait for readers, so this is
# safe to run from the serialized writer path.  Override with
# MERID_AUDIT_WAL_CHECKPOINT_S; <=0 disables scheduled checkpoints.
_WAL_CHECKPOINT_INTERVAL_S = float(
    os.environ.get("MERID_AUDIT_WAL_CHECKPOINT_S", "900")
)


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
        self._shared_conn: Optional[sqlite3.Connection] = None
        self._cycle_stats: Dict[str, Dict[str, Any]] = {}
        self._last_wal_checkpoint = 0.0
        self._startup_checkpoint_done = False
        self._last_evidence_refresh = 0.0
        self._evidence_refresh_guard = threading.Lock()
        self._evidence_refresh_inflight = False
        # Write offload: public record_* calls enqueue closures drained by a
        # single daemon writer thread.  The event loop calls these on the hot
        # decision path; one slow commit/WAL checkpoint on the multi-GB audit
        # DB otherwise serializes the pipeline and starves asyncio
        # (faulthandler samples: loop thread parked in _insert_trade_decision
        # / record_pre_decision_rejection).  FIFO ordering is preserved and
        # every write still runs under self._lock on the shared connection.
        self._write_queue: "queue.Queue[Callable[[], None]]" = queue.Queue()
        self._writer_started = False
        self._writer_thread: Optional[threading.Thread] = None
        # 2026-10-13: queue admission control.  When a long reader (startup
        # reconcile, evidence rebuild) starves the single writer, arrivals
        # outpace drains and the unbounded queue grows until process exit
        # (observed: ~4.7k pending, ~45min of audit records held in memory).
        # Shed by declared priority, never FIFO-collapse: HIGH (fills,
        # settlements, order/risk events) is never dropped; NORMAL (decision
        # rows, heartbeats) is sampled past the critical depth; LOW
        # (pre-decision rejection telemetry, maintenance) is sampled past the
        # soft depth and dropped past critical.
        self._shed_seq = 0
        self._shed_stats = {
            "low_sampled": 0,
            "low_dropped": 0,
            "normal_dropped": 0,
            "rejection_sampled": 0,
        }
        self._last_shed_log = 0.0
        # 2026-10-14 (HDD-aware): per-key sampling for noise-class
        # pre-decision rejections under queue pressure.  Keeps the first N
        # full records per (reason, asset, minute) plus aggregate drop
        # counts; beyond N the insert is skipped entirely, which is the
        # real currency on a ~10-IOPS spindle.  Counterfactual-bearing
        # reasons (edge gates, price band, evidence blocks) are NOT in the
        # sample-eligible set — they keep full records.
        self._sample_counts: Dict[tuple, int] = {}
        self._sample_last_minute = -1
        self._sample_reasons = frozenset(
            r.strip()
            for r in os.getenv(
                "MERID_AUDIT_SAMPLE_REASONS",
                "market_time,tte_entry_cutoff,book_not_trusted,"
                "market_unavailable,book_stale,quote_stale",
            ).split(",")
            if r.strip()
        )
        # Graceful shutdown: close() stops admitting new writes then drains the
        # queue so a planned restart cannot silently discard queued decisions/
        # fills/outcomes (observed loss: ~5.1k records on the 2026-10-13
        # restart).  Drain is bounded by MERID_AUDIT_DRAIN_TIMEOUT_S.
        self._closed = False
        self._closed_drop_logged = False

    def submit_write(self, fn: Callable[[], None], *, priority: str = "normal") -> None:
        """Public offload API: enqueue ``fn`` (a bound ledger write) onto the
        dedicated writer thread.  Call sites on the asyncio event loop use
        this when they do not need the write's return value — the ledger's
        sync methods keep their bool/row semantics for fail-closed callers
        and tests.  ``priority`` selects the admission-control tier:
        "high" is never shed, "normal" is sampled at critical depth, "low"
        is sampled at soft depth and dropped at critical depth.
        """
        self._submit_write(fn, priority=priority)

    def _shed_admit(self, priority: str, depth: int) -> bool:
        """Return False when a queued write should be dropped for load."""
        if priority == "high":
            return True
        soft = int(os.environ.get("MERID_AUDIT_SHED_DEPTH", "1500"))
        crit = int(os.environ.get("MERID_AUDIT_SHED_CRIT_DEPTH", "5000"))
        if depth < soft:
            return True
        self._shed_seq += 1
        keep = True
        if priority == "low":
            if depth >= crit:
                keep = False
            else:
                div = max(1, int(os.environ.get("MERID_AUDIT_LOW_SAMPLE_DIV", "10")))
                keep = self._shed_seq % div == 0
                if keep:
                    self._shed_stats["low_sampled"] += 1
        elif depth >= crit:
            div = max(1, int(os.environ.get("MERID_AUDIT_NORMAL_SAMPLE_DIV", "4")))
            keep = self._shed_seq % div == 0
        if not keep:
            self._shed_stats[
                "low_dropped" if priority == "low" else "normal_dropped"
            ] += 1
            now = time.time()
            if now - self._last_shed_log >= 30.0:
                self._last_shed_log = now
                logger.warning(
                    "[AUDIT-Q-SHED] depth=%d: dropping %s-priority audit "
                    "write; cumulative=%s",
                    depth,
                    priority,
                    self._shed_stats,
                )
        return keep

    def _sampled_out_rejection(self, reason: str, asset: str) -> bool:
        """Cap noise-class rejection telemetry under queue pressure.

        Active only when the write queue is at/above the soft shed depth.
        Eligible reasons keep the first ``MERID_AUDIT_SAMPLE_PER_MIN``
        (default 10) full records per (reason, asset, minute); further
        records are counted and skipped.  Reasons not in
        ``MERID_AUDIT_SAMPLE_REASONS`` — edge gates, price-band, evidence
        blocks, anything counterfactual-bearing — are never sampled.
        """
        if reason not in self._sample_reasons:
            return False
        soft = int(os.environ.get("MERID_AUDIT_SHED_DEPTH", "1500"))
        if self._write_queue.qsize() < soft:
            return False
        minute = int(time.time() // 60)
        if minute != self._sample_last_minute:
            # Minute rollover: drop stale keys so the map stays tiny.
            self._sample_counts = {k: v for k, v in self._sample_counts.items() if k[2] >= minute}
            self._sample_last_minute = minute
        key = (reason, asset, minute)
        cap = max(1, int(os.environ.get("MERID_AUDIT_SAMPLE_PER_MIN", "10")))
        seen = self._sample_counts.get(key, 0)
        self._sample_counts[key] = seen + 1
        if seen < cap:
            return False
        self._shed_stats["rejection_sampled"] += 1
        now = time.time()
        if now - self._last_shed_log >= 30.0:
            self._last_shed_log = now
            logger.warning(
                "[AUDIT-Q-SAMPLE] depth=%d: capped rejection telemetry "
                "reason=%s asset=%s (>=%d/min); cumulative_sampled=%d",
                self._write_queue.qsize(),
                reason,
                asset,
                cap,
                self._shed_stats["rejection_sampled"],
            )
        return True

    def drain_write_queue(self, timeout_s: Optional[float] = None) -> bool:
        """Best-effort bounded flush of pending audit writes.

        Returns True when the queue fully drained within ``timeout_s``
        (default: ``MERID_AUDIT_DRAIN_TIMEOUT_S``, 60s).  Called on graceful
        shutdown paths; a killed process still drops the queue, this only
        covers the planned-restart case.
        """
        if timeout_s is None:
            timeout_s = float(os.environ.get("MERID_AUDIT_DRAIN_TIMEOUT_S", "60"))
        if not self._writer_started:
            return True
        done = threading.Event()

        def _wait_for_drain() -> None:
            self._write_queue.join()
            done.set()

        waiter = threading.Thread(
            target=_wait_for_drain, daemon=True, name="audit-drain-waiter"
        )
        waiter.start()
        flushed = done.wait(timeout_s)
        if flushed:
            logger.info(
                "[DECISION-AUDIT-LEDGER] write queue drained (timeout=%.1fs)",
                timeout_s,
            )
        else:
            logger.warning(
                "[DECISION-AUDIT-LEDGER] write queue drain timed out after "
                "%.1fs; depth=%d remaining",
                timeout_s,
                self._write_queue.qsize(),
            )
        return flushed

    def close(self, timeout_s: Optional[float] = None) -> bool:
        """Stop admitting new writes, then drain pending ones."""
        if self._closed:
            return True
        self._closed = True
        return self.drain_write_queue(timeout_s)

    def _submit_write(self, fn: Callable[[], None], *, priority: str = "normal") -> None:
        """Run a ledger write on the dedicated writer thread.

        Writes are append-only, callers ignore return values, and failures are
        already logged-and-swallowed, so FIFO offload preserves ordering and
        durability modulo the process-crash tail — the same guarantee the
        class gives today.  Under pytest/CI the write runs inline so tests
        can assert on rows immediately.
        """
        if self._closed:
            if not self._closed_drop_logged:
                self._closed_drop_logged = True
                logger.warning(
                    "[DECISION-AUDIT-LEDGER] ledger closed; dropping queued "
                    "audit writes (shutdown in progress)"
                )
            return
        if _is_test_context():
            try:
                fn()
            except Exception:
                pass
            return
        if not self._writer_started:
            with self._lock:
                if not self._writer_started:
                    self._writer_thread = threading.Thread(
                        target=self._writer_main,
                        name="decision-audit-ledger-writer",
                        daemon=True,
                    )
                    self._writer_thread.start()
                    self._writer_started = True
        if not self._shed_admit(priority, self._write_queue.qsize()):
            return
        self._write_queue.put_nowait((fn, time.monotonic(), priority))

    def _writer_main(self) -> None:
        from merid.observability import latency_budget as _lat
        while True:
            fn, enqueued_mono, _prio = self._write_queue.get()
            try:
                _lat.record(
                    "audit_write_wait_ms",
                    (time.monotonic() - enqueued_mono) * 1000.0,
                )
                _t0 = time.monotonic()
                fn()
                _lat.record(
                    "audit_write_exec_ms",
                    (time.monotonic() - _t0) * 1000.0,
                )
            except Exception as exc:  # defensive; impls already swallow
                logger.warning("[DECISION-AUDIT-LEDGER] writer error: %s", exc)
            finally:
                self._write_queue.task_done()

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
            if not self._startup_checkpoint_done:
                self._startup_checkpoint_done = True
                # Drain the WAL once at startup: the only moment a TRUNCATE
                # checkpoint is cheap (no analytics readers yet).  Runs on the
                # writer thread, never the event loop, and gives up fast via
                # busy_timeout if a reader does hold the WAL.
                self._submit_write(
                    lambda: self.wal_checkpoint("TRUNCATE"), priority="low"
                )
        except Exception as exc:
            logger.warning("[DECISION-AUDIT-LEDGER] schema init failed: %s", exc)

    def _conn(self, isolation_level: Optional[str] = "IMMEDIATE") -> sqlite3.Connection:
        # Reuse a single persistent connection for writes.  Opening a fresh
        # connection to the 400MB+ audit DB measured ~30s on this host (cold
        # file-cache/AV scan), and because every writer holds ``self._lock``
        # across the connect, the whole decision pipeline serialized behind
        # it (faulthandler: all decision threads parked at ``with self._lock``).
        # The shared connection is guarded by the same lock and created with
        # check_same_thread=False.  ``with conn:`` still commits/rolls back per
        # call; only the connect itself is amortized.  ``isolation_level=None``
        # (schema init) keeps a one-shot connection so autocommit DDL semantics
        # are unchanged.
        if isolation_level is None:
            conn = sqlite3.connect(str(self.db_path), timeout=10)
            conn.isolation_level = None
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout = 5000")
            return conn
        if self._shared_conn is None:
            conn = sqlite3.connect(
                str(self.db_path), timeout=30, check_same_thread=False
            )
            conn.isolation_level = isolation_level
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA busy_timeout = 5000")
            # 2026-10-14 (HDD-aware tiering): this DB is audit/telemetry —
            # decisions, side-EV, rejection records, and re-healable
            # settlement attribution.  Trading-critical state (fills,
            # orders, positions) lives in separate DBs.  synchronous=NORMAL
            # keeps WAL atomicity/consistency and survives process crashes;
            # only OS crash / power loss can roll back commits since the
            # last checkpoint.  On the production spindle (~100-200ms per
            # fsync) per-commit FULL syncs were the dominant writer cost.
            conn.execute("PRAGMA synchronous = NORMAL")
            # Larger autocheckpoint amortizes checkpoint bursts on slow disk.
            conn.execute(
                "PRAGMA wal_autocheckpoint = %d"
                % int(os.getenv("MERID_AUDIT_WAL_AUTOCHECKPOINT", "2000"))
            )
            self._shared_conn = conn
        return self._shared_conn

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Idempotent migrations for the point-in-time audit ledger."""
        # Provenance / research-eligibility columns on the decision table.
        _add_column(conn, "strategy_decisions", "record_environment", "TEXT NOT NULL DEFAULT 'production'")
        _add_column(conn, "strategy_decisions", "record_source", "TEXT NOT NULL DEFAULT 'live'")
        _add_column(conn, "strategy_decisions", "is_eligible_for_research", "INTEGER NOT NULL DEFAULT 1")
        _add_column(conn, "strategy_decisions", "exclusion_reason", "TEXT")
        _add_column(conn, "strategy_decisions", "shadow_cohort_json", "TEXT")

        # Current-build evidence provenance: the audit DB must segment fills
        # by admitting lane and build without re-deriving from logs — the
        # provisional lane's evidence is never merged with legacy rows.
        _add_column(conn, "strategy_decisions", "admission_lane", "TEXT")
        _add_column(conn, "strategy_decisions", "admission_owner", "TEXT")
        _add_column(conn, "strategy_decisions", "provisional_cell_id", "TEXT")
        _add_column(conn, "strategy_decisions", "build_sha", "TEXT")
        _add_column(conn, "strategy_decisions", "policy_epoch", "TEXT")
        _add_column(conn, "strategy_decisions", "dir_regime", "TEXT")
        _add_column(conn, "strategy_decision_outcomes", "policy_epoch", "TEXT")
        # 2026-10-13: realized_net_pnl_cents is the THESIS value (hold to
        # settlement, entry-vs-settle) and keeps feeding evidence.  The
        # capital-realized value — exit proceeds for exited quantity plus
        # settlement for the residual — feeds the capital-protection counters
        # (lane suspension, cell/provisional windows, side loss streaks).
        _add_column(conn, "strategy_decision_outcomes", "capital_realized_pnl_cents", "REAL")
        _add_column(conn, "strategy_decision_outcomes", "exit_attribution", "TEXT")
        _add_column(conn, "strategy_decision_side_ev", "admission_owner", "TEXT")
        _add_column(conn, "strategy_decision_side_ev", "threshold_source", "TEXT")
        _add_column(conn, "strategy_decision_side_ev", "legacy_risk_label", "TEXT")
        # 2026-10-06 (EV reconciliation): the quantities the live economics
        # gate actually compared — gate_ev_cents (EPC-adjusted effective
        # edge) vs enforced_edge_bound_cents (post-caution, post-slack
        # bound).  expected_net_ev_cents/required_edge_cents remain the raw
        # decomposition; the delta between the two pairs is attributable to
        # named components (marginal-band slack, EPC lift).
        _add_column(conn, "strategy_decision_side_ev", "gate_ev_cents", "REAL")
        _add_column(conn, "strategy_decision_side_ev", "enforced_edge_bound_cents", "REAL")
        # 2026-10-06: the lane that admitted the candidate (decision-level).
        # selected=1 & passed_edge_gate=0 is legible once the admission lane
        # is recorded — a bounded lane (canary_maker, threshold_cell, ...)
        # can admit a side below the full enforced-route bound.
        _add_column(conn, "strategy_decision_side_ev", "decision_lane", "TEXT")
        # 2026-10-13: evidence-health tier per candidate side — makes "why
        # was this side blocked/downsized?" queryable when the evidence
        # artifact is DEGRADED/STALE/UNUSABLE.
        _add_column(conn, "strategy_decision_side_ev", "evidence_state", "TEXT")
        _add_column(conn, "strategy_decision_side_ev", "evidence_age_s", "REAL")
        _add_column(conn, "strategy_decision_side_ev", "evidence_action", "TEXT")
        _add_column(conn, "strategy_decision_side_ev", "evidence_binding_gate", "TEXT")
        _add_column(conn, "strategy_decision_side_ev", "evidence_artifact_mtime", "REAL")
        _add_column(conn, "strategy_decision_side_ev", "evidence_last_refresh_success_at", "REAL")

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

        # Quote provenance: which feed owned the executable quote at decision
        # time plus the raw WS/REST divergence and per-hop latency evidence.
        _add_column(conn, "strategy_decision_snapshots", "quote_owner", "TEXT")
        _add_column(conn, "strategy_decision_snapshots", "degraded_mode", "INTEGER NOT NULL DEFAULT 0")
        _add_column(conn, "strategy_decision_snapshots", "ws_last_seq", "INTEGER")
        _add_column(conn, "strategy_decision_snapshots", "ws_last_event_age_ms", "REAL")
        _add_column(conn, "strategy_decision_snapshots", "ws_last_queue_wait_ms", "REAL")
        _add_column(conn, "strategy_decision_snapshots", "ws_rest_bid_diff_ticks", "INTEGER")
        _add_column(conn, "strategy_decision_snapshots", "ws_rest_ask_diff_ticks", "INTEGER")
        _add_column(conn, "strategy_decision_snapshots", "ws_parity_healthy", "INTEGER")
        _add_column(conn, "strategy_decision_snapshots", "rest_age_ms", "INTEGER")

        # ── Lifecycle event attribution (append-only) ────────────────────
        # The decision row records the *first* decision-stage outcome; every
        # later state transition (allocator/risk/cooldown/router rejection,
        # submission, fill, settlement resolution) is a separate immutable
        # event so reporting can distinguish e.g. "model selected but the
        # allocator blocked it" from "the model rejected it".
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS strategy_decision_events (
                event_id TEXT PRIMARY KEY,
                decision_id TEXT NOT NULL,
                candidate_id TEXT,
                event_ts_utc TEXT NOT NULL,
                event_ts REAL NOT NULL,
                event_type TEXT NOT NULL,
                stage TEXT NOT NULL,
                reason_code TEXT,
                reason_detail_json TEXT NOT NULL DEFAULT '{}',
                trace_id TEXT,
                run_id TEXT,
                ticker TEXT,
                asset TEXT,
                schema_version INTEGER NOT NULL DEFAULT 1,
                created_at_utc TEXT NOT NULL,
                UNIQUE(decision_id, event_type, stage, event_ts_utc)
            );

            CREATE INDEX IF NOT EXISTS idx_sde_decision_ts
                ON strategy_decision_events(decision_id, event_ts_utc);
            CREATE INDEX IF NOT EXISTS idx_sde_run_type
                ON strategy_decision_events(run_id, event_type);
            CREATE INDEX IF NOT EXISTS idx_sde_reason
                ON strategy_decision_events(reason_code);
            CREATE INDEX IF NOT EXISTS idx_sde_candidate
                ON strategy_decision_events(candidate_id);
            """
        )

        # Stable candidate/decision identity + complete gate-vector evidence.
        # ``candidate_id`` groups every evaluation attempt (taker/maker/shadow)
        # of one market observation; ``decision_id`` remains per-pass
        # (``<candidate_id>:<route>`` for instrumented writers).
        _add_column(conn, "strategy_decisions", "candidate_id", "TEXT")
        _add_column(conn, "strategy_decisions", "run_id", "TEXT")
        _add_column(conn, "strategy_decisions", "gate_results_json", "TEXT NOT NULL DEFAULT '{}'")
        _add_column(conn, "strategy_decisions", "all_failed_gates_json", "TEXT NOT NULL DEFAULT '[]'")
        _add_column(conn, "strategy_decisions", "gate_evaluation_schema_version", "INTEGER NOT NULL DEFAULT 0")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sd_candidate_id "
            "ON strategy_decisions(candidate_id)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_sd_run_id "
            "ON strategy_decisions(run_id, decision_ts)"
        )

        # Counterfactual executability: requested vs visible top-of-book depth,
        # fill ratio, and the versioned fill/fee/slippage assumptions used so a
        # rejected candidate is never silently treated as a full fill.
        _add_column(conn, "strategy_decision_side_ev", "requested_contracts", "REAL")
        _add_column(conn, "strategy_decision_side_ev", "top_of_book_executable_contracts", "REAL")
        _add_column(conn, "strategy_decision_side_ev", "counterfactual_assumed_filled_contracts", "REAL")
        _add_column(conn, "strategy_decision_side_ev", "counterfactual_fill_ratio", "REAL")
        _add_column(conn, "strategy_decision_side_ev", "counterfactual_full_fill_possible", "INTEGER")
        _add_column(conn, "strategy_decision_side_ev", "counterfactual_execution_status", "TEXT")
        _add_column(conn, "strategy_decision_side_ev", "counterfactual_entry_source", "TEXT")
        _add_column(conn, "strategy_decision_side_ev", "counterfactual_fee_model_version", "TEXT")
        _add_column(conn, "strategy_decision_side_ev", "counterfactual_slippage_model_version", "TEXT")
        _add_column(conn, "strategy_decision_side_ev", "counterfactual_fill_model_version", "TEXT")

        # Terminal failure bookkeeping for outcomes that never resolve.
        _add_column(conn, "strategy_decision_outcomes", "unresolved_reason", "TEXT")
        _add_column(conn, "strategy_decision_outcomes", "unresolved_at", "REAL")

        # One-time data backfills for rows written before the columns above
        # existed.  On the production DB (hundreds of MB) the selected=1
        # UPDATE/JOIN below scans the full side-EV table and runs for minutes
        # while _ensure_db() holds self._lock, serialising every decision
        # thread behind it (faulthandler: all threads parked at
        # ``with self._lock`` in log_cycle_heartbeat, run_cycle exceeding the
        # 150s hang threshold, and repeated interpreter crashes during the
        # wedge).  New rows populate these columns at insert time, so the
        # backfills are only needed once - gate them on PRAGMA user_version
        # instead of re-running the full-table writes on every process start.
        if conn.execute("PRAGMA user_version").fetchone()[0] < 1:
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
                "WHERE selected = 0 AND rowid IN ("
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
            conn.execute("PRAGMA user_version = 1")

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
                side_ev_expected=2,
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
                side_ev_expected=2,
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
        decision_id: Optional[str] = None,
        candidate_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        event_type: str = DECISION_EVENT_PRE_DECISION_REJECTED,
        event_stage: str = DECISION_STAGE_PRE_DECISION,
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

        if self._sampled_out_rejection(reason, asset):
            return False

        self._ensure_db()
        start = time.perf_counter()
        try:
            if not decision_id:
                if candidate_id:
                    decision_id = f"{candidate_id}:pre"
                else:
                    decision_id = f"{run_id}_{ticker}_{uuid.uuid4().hex[:8]}"
            if not candidate_id:
                candidate_id = _candidate_id_from_decision_id(decision_id)
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

            # Minimal gate vector for pre-decision rows: the evaluation never
            # reached the model, so a single pre-decision gate records the
            # failure and downstream gates are honestly "not_evaluated".
            _pre_gate_results = {
                "pre_decision_pipeline": {
                    "gate_name": "pre_decision_pipeline",
                    "gate_code": classification.primary_reason_code,
                    "stage": DECISION_STAGE_PRE_DECISION,
                    "passed": False,
                    "observed": {"raw_reason": reason},
                    "threshold": {},
                    "blocking_in_live_path": True,
                }
            }
            _pre_failed = ["pre_decision_pipeline"]

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
                        exclusion_reason, created_at,
                        candidate_id, run_id, gate_results_json, all_failed_gates_json,
                        gate_evaluation_schema_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        candidate_id,
                        run_id,
                        json.dumps(_pre_gate_results),
                        json.dumps(_pre_failed),
                        1,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO strategy_decision_snapshots (
                        decision_id, spot_price, spot_source, spot_source_ts, spot_age_ms,
                        settlement_reference_price, settlement_reference_source,
                        settlement_reference_ts, settlement_reference_age_ms,
                        yes_bid_cents, yes_ask_cents, no_bid_cents, no_ask_cents,
                        book_age_ms, yes_depth, no_depth,
                        quote_owner, degraded_mode, ws_last_seq,
                        ws_last_event_age_ms, ws_last_queue_wait_ms,
                        ws_rest_bid_diff_ticks, ws_rest_ask_diff_ticks,
                        ws_parity_healthy, rest_age_ms
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        extra.get("quote_owner") if extra else None,
                        1 if (extra or {}).get("degraded_mode") else 0,
                        _to_int((extra or {}).get("ws_last_seq")),
                        _to_float((extra or {}).get("ws_last_event_age_ms")),
                        _to_float((extra or {}).get("ws_last_queue_wait_ms")),
                        _to_int((extra or {}).get("ws_rest_bid_diff_ticks")),
                        _to_int((extra or {}).get("ws_rest_ask_diff_ticks")),
                        (
                            None
                            if (extra or {}).get("ws_parity_healthy") is None
                            else (1 if (extra or {}).get("ws_parity_healthy") else 0)
                        ),
                        _to_int((extra or {}).get("rest_age_ms")),
                    ),
                )
                if ticker and str(ticker).strip():
                    conn.execute(
                        "INSERT INTO strategy_decision_outcomes (decision_id) VALUES (?)",
                        (decision_id,),
                    )
                else:
                    # No resolvable contract was bound to this rejection, so no
                    # settlement can ever arrive — writing PENDING would park the
                    # row in the orphan sweep forever (empty ticker yields a
                    # /markets/ call that 301s every poll cycle).
                    conn.execute(
                        """INSERT INTO strategy_decision_outcomes
                           (decision_id, outcome_status, unresolved_reason, unresolved_at)
                           VALUES (?, 'UNRESOLVED', 'no_contract_at_decision', ?)""",
                        (decision_id, now),
                    )
                self._append_decision_event_locked(
                    conn,
                    decision_id=decision_id,
                    candidate_id=candidate_id,
                    event_type=event_type,
                    stage=event_stage,
                    event_ts=now,
                    reason_code=classification.primary_reason_code,
                    reason_detail={
                        "raw_reason": reason,
                        "cycle_id": cycle_id,
                        **(dict(extra) if extra else {}),
                    },
                    trace_id=trace_id or candidate_id,
                    run_id=run_id,
                    ticker=ticker,
                    asset=asset,
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

    # ── Lifecycle event API ──────────────────────────────────────────────

    @staticmethod
    def _event_id(
        decision_id: str,
        event_type: str,
        stage: str,
        reason_code: Optional[str],
        event_ts: float,
        seq: int = 0,
    ) -> str:
        """Deterministic idempotency key for a lifecycle event.

        Built from the stable identity fields so a replay/retried delivery
        collapses onto the same row instead of double-counting.
        """
        material = "|".join(
            [
                str(decision_id),
                str(event_type),
                str(stage),
                str(reason_code or ""),
                f"{float(event_ts):.3f}",
                str(int(seq)),
            ]
        )
        return "evt_" + hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]

    def _append_decision_event_locked(
        self,
        conn: sqlite3.Connection,
        *,
        decision_id: str,
        event_type: str,
        stage: str,
        event_ts: Optional[float] = None,
        reason_code: Optional[str] = None,
        reason_detail: Optional[Mapping[str, Any]] = None,
        trace_id: Optional[str] = None,
        run_id: Optional[str] = None,
        ticker: Optional[str] = None,
        asset: Optional[str] = None,
        candidate_id: Optional[str] = None,
        seq: int = 0,
    ) -> Optional[str]:
        """Insert one lifecycle event inside the caller's transaction.

        Idempotent: a duplicate (same deterministic ``event_id`` or the same
        ``decision_id/event_type/stage/event_ts_utc`` tuple) is ignored.
        Returns the event_id, or None when the insert was deduplicated/failed.
        """
        try:
            ts = float(event_ts) if event_ts is not None else time.time()
            now_dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            event_id = self._event_id(
                decision_id, event_type, stage, reason_code, ts, seq
            )
            if candidate_id is None:
                candidate_id = _candidate_id_from_decision_id(decision_id)
            cur = conn.execute(
                """
                INSERT OR IGNORE INTO strategy_decision_events (
                    event_id, decision_id, candidate_id, event_ts_utc, event_ts,
                    event_type, stage, reason_code, reason_detail_json,
                    trace_id, run_id, ticker, asset, schema_version,
                    created_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    str(decision_id),
                    candidate_id,
                    now_dt.isoformat(),
                    ts,
                    str(event_type),
                    str(stage),
                    reason_code,
                    json.dumps(dict(reason_detail or {}), default=str),
                    trace_id,
                    run_id,
                    ticker,
                    asset,
                    DECISION_EVENT_SCHEMA_VERSION,
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            return event_id if cur.rowcount > 0 else None
        except Exception as exc:
            logger.debug(
                "[DECISION-AUDIT-LEDGER] event append failed for %s/%s: %s",
                decision_id,
                event_type,
                exc,
            )
            return None

    def append_decision_event(
        self,
        *,
        decision_id: str,
        event_type: str,
        stage: str,
        event_ts_utc: Optional[Any] = None,
        reason_code: Optional[str] = None,
        reason_detail: Optional[Mapping[str, Any]] = None,
        trace_id: Optional[str] = None,
        run_id: Optional[str] = None,
        ticker: Optional[str] = None,
        asset: Optional[str] = None,
        candidate_id: Optional[str] = None,
        seq: int = 0,
    ) -> Optional[str]:
        """Append one immutable lifecycle event for ``decision_id``.

        ``event_ts_utc`` may be a float epoch, a datetime, or None (now).
        Fail-open: errors are logged, never raised; returns the event_id or
        None on failure/dedup.
        """
        if not _is_enabled() or not decision_id:
            return None
        self._ensure_db()
        try:
            if isinstance(event_ts_utc, datetime):
                ts = event_ts_utc.timestamp()
            elif event_ts_utc is None:
                ts = time.time()
            else:
                ts = float(event_ts_utc)
            with self._lock, self._conn() as conn:
                conn.execute("BEGIN IMMEDIATE")
                return self._append_decision_event_locked(
                    conn,
                    decision_id=decision_id,
                    event_type=event_type,
                    stage=stage,
                    event_ts=ts,
                    reason_code=reason_code,
                    reason_detail=reason_detail,
                    trace_id=trace_id,
                    run_id=run_id,
                    ticker=ticker,
                    asset=asset,
                    candidate_id=candidate_id,
                    seq=seq,
                )
        except Exception as exc:
            logger.warning(
                "[DECISION-AUDIT-LEDGER] append_decision_event failed for %s/%s: %s",
                decision_id,
                event_type,
                exc,
            )
            return None

    def mark_outcome_unresolved(
        self,
        ticker: str,
        close_ts: float,
        *,
        reason: str = "settlement_unresolved_after_grace",
    ) -> int:
        """Mark still-PENDING outcomes for ``ticker`` as terminally UNRESOLVED.

        Called by the settlement sweep after its retry budget is exhausted
        (market never produced a definitive exchange result).  Emits one
        ``OUTCOME_UNRESOLVED`` event per affected decision.  Returns the number
        of outcomes transitioned.
        """
        if not _is_enabled():
            return 0
        self._ensure_db()
        try:
            with self._lock, self._conn() as conn:
                conn.execute("BEGIN IMMEDIATE")
                rows = conn.execute(
                    """
                    SELECT d.decision_id, d.asset, d.run_id
                    FROM strategy_decisions d
                    JOIN strategy_decision_outcomes o ON d.decision_id = o.decision_id
                    WHERE d.ticker = ?
                      AND o.outcome_status = 'PENDING'
                      AND ABS(d.close_ts - ?) <= 900.0
                    """,
                    (ticker, close_ts),
                ).fetchall()
                now = time.time()
                for row in rows:
                    conn.execute(
                        """
                        UPDATE strategy_decision_outcomes
                        SET outcome_status = 'UNRESOLVED',
                            unresolved_reason = ?,
                            unresolved_at = ?
                        WHERE decision_id = ?
                        """,
                        (reason, now, row["decision_id"]),
                    )
                    self._append_decision_event_locked(
                        conn,
                        decision_id=row["decision_id"],
                        event_type=DECISION_EVENT_OUTCOME_UNRESOLVED,
                        stage=DECISION_STAGE_OUTCOME,
                        event_ts=now,
                        reason_code=reason,
                        run_id=row["run_id"],
                        ticker=ticker,
                        asset=row["asset"],
                    )
                return len(rows)
        except Exception as exc:
            logger.warning(
                "[DECISION-AUDIT-LEDGER] mark_outcome_unresolved failed for %s: %s",
                ticker,
                exc,
            )
            return 0

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
                # Lifecycle checkpoints for the execution stage.  The caller
                # supplies whichever fields it observed; events are dedup-safe
                # so overlapping deliveries (submit response + fills ledger)
                # collapse instead of double-counting.
                if order_intent_id or exchange_order_id:
                    self._append_decision_event_locked(
                        conn,
                        decision_id=decision_id,
                        event_type=DECISION_EVENT_ORDER_SUBMITTED,
                        stage=DECISION_STAGE_EXECUTION,
                        reason_detail={
                            "order_intent_id": order_intent_id,
                            "exchange_order_id": exchange_order_id,
                        },
                    )
                if fill_id or actual_fill_price_cents is not None:
                    self._append_decision_event_locked(
                        conn,
                        decision_id=decision_id,
                        event_type=DECISION_EVENT_ORDER_FILLED,
                        stage=DECISION_STAGE_EXECUTION,
                        reason_detail={
                            "fill_id": fill_id,
                            "actual_fill_price_cents": actual_fill_price_cents,
                            "actual_entry_fee_cents": actual_entry_fee_cents,
                        },
                    )
        except Exception as exc:
            logger.warning(
                "[DECISION-AUDIT-LEDGER] record_outcome failed for %s: %s",
                decision_id,
                exc,
            )

    def record_entry_fill(
        self,
        *,
        decision_id: str,
        fill_id: Optional[str] = None,
        exchange_order_id: Optional[str] = None,
        execution_outcome_side: Optional[str] = None,
        execution_action: Optional[str] = None,
        execution_price_cents: Optional[int] = None,
        entry_fee_cents: Optional[float] = None,
    ) -> bool:
        """Persist an asynchronously-detected venue fill onto the outcome row.

        The order-router only calls ``record_outcome`` for fills visible in the
        synchronous submit response; post-only resting orders fill later and
        arrive via the fills ledger instead.  This method performs the
        venue-leg -> selected-side price conversion the settlement math expects:

        - ``buy`` on leg L costs ``execution_price_cents`` in L space.
        - ``sell`` on leg L is economically buying the opposite outcome at
          ``100 - execution_price_cents``.

        The implied exposure side must match the decision's ``selected_side``;
        on mismatch the row is left untouched (fail-closed) rather than
        writing a wrong-space price.  Returns True when a fill price was
        written.
        """
        if not _is_enabled():
            return False
        if not decision_id or execution_price_cents is None:
            return False
        action = (execution_action or "").lower()
        leg = (execution_outcome_side or "").lower()
        if action not in ("buy", "sell") or leg not in ("yes", "no"):
            logger.warning(
                "[DECISION-AUDIT-LEDGER] entry fill for %s has undetermined "
                "direction (outcome_side=%r action=%r) - skipping",
                decision_id,
                execution_outcome_side,
                execution_action,
            )
            return False

        self._ensure_db()
        try:
            with self._lock, self._conn() as conn:
                return self._record_entry_fill_locked(
                    conn,
                    decision_id=decision_id,
                    fill_id=fill_id,
                    exchange_order_id=exchange_order_id,
                    execution_outcome_side=execution_outcome_side,
                    execution_action=execution_action,
                    execution_price_cents=execution_price_cents,
                    entry_fee_cents=entry_fee_cents,
                )
        except Exception as exc:
            logger.warning(
                "[DECISION-AUDIT-LEDGER] record_entry_fill failed for %s: %s",
                decision_id,
                exc,
            )
            return False

    def _record_entry_fill_locked(
        self,
        conn: Any,
        *,
        decision_id: str,
        fill_id: Optional[str] = None,
        exchange_order_id: Optional[str] = None,
        execution_outcome_side: Optional[str] = None,
        execution_action: Optional[str] = None,
        execution_price_cents: Optional[int] = None,
        entry_fee_cents: Optional[float] = None,
    ) -> bool:
        """Lock-free core of ``record_entry_fill`` for in-transaction callers."""
        action = (execution_action or "").lower()
        leg = (execution_outcome_side or "").lower()
        if not decision_id or execution_price_cents is None:
            return False
        if action not in ("buy", "sell") or leg not in ("yes", "no"):
            logger.warning(
                "[DECISION-AUDIT-LEDGER] entry fill for %s has undetermined "
                "direction (outcome_side=%r action=%r) - skipping",
                decision_id,
                execution_outcome_side,
                execution_action,
            )
            return False
        drow = conn.execute(
            "SELECT selected_side FROM strategy_decisions WHERE decision_id = ?",
            (decision_id,),
        ).fetchone()
        if drow is None or not drow["selected_side"]:
            return False
        selected = str(drow["selected_side"]).lower()
        exposure_side = (
            leg if action == "buy" else ("no" if leg == "yes" else "yes")
        )
        if exposure_side != selected:
            logger.warning(
                "[DECISION-AUDIT-LEDGER] entry fill side mismatch for %s: "
                "exposure=%s (leg=%s action=%s) vs selected=%s - skipping",
                decision_id, exposure_side, leg, action, selected,
            )
            return False
        fill_price_selected = (
            int(execution_price_cents)
            if action == "buy"
            else 100 - int(execution_price_cents)
        )
        cur = conn.execute(
            """
            UPDATE strategy_decision_outcomes
            SET exchange_order_id = COALESCE(?, exchange_order_id),
                fill_id = COALESCE(?, fill_id),
                actual_fill_price_cents = COALESCE(?, actual_fill_price_cents),
                actual_entry_fee_cents = COALESCE(?, actual_entry_fee_cents)
            WHERE decision_id = ?
            """,
            (
                exchange_order_id,
                fill_id,
                fill_price_selected,
                entry_fee_cents,
                decision_id,
            ),
        )
        if cur.rowcount > 0:
            self._append_decision_event_locked(
                conn,
                decision_id=decision_id,
                event_type=DECISION_EVENT_ORDER_FILLED,
                stage=DECISION_STAGE_EXECUTION,
                reason_detail={
                    "fill_id": fill_id,
                    "exchange_order_id": exchange_order_id,
                    "execution_outcome_side": leg,
                    "execution_action": action,
                    "fill_price_selected_side_cents": fill_price_selected,
                    "entry_fee_cents": entry_fee_cents,
                    "source": "fills_ledger",
                },
            )
        return cur.rowcount > 0

    def _fills_db_path(self) -> Path:
        return Path(
            os.environ.get("MERID_FILLS_DB_PATH", "data/kalshi_fills.db")
        )

    def _resolve_entry_fill_from_fills_db(
        self, decision_id: str
    ) -> Optional[Dict[str, Any]]:
        """Look up the venue fill for ``decision_id`` in the Kalshi fills DB.

        Post-only fills are recorded there with ``decision_trace_id`` equal to
        the audit ``decision_id``.  Returns the newest entry fill's execution
        fields, or None when absent/unreadable.
        """
        path = self._fills_db_path()
        if not path.exists():
            return None
        try:
            conn = sqlite3.connect(
                f"file:{path}?mode=ro", uri=True, timeout=5.0
            )
            try:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    """
                    SELECT fill_id, order_id, execution_outcome_side,
                           execution_action, execution_price_cents, fee_cost
                    FROM kalshi_fills
                    WHERE decision_trace_id = ?
                      AND COALESCE(is_exit, 0) = 0
                      AND COALESCE(reduce_only, 0) = 0
                      AND COALESCE(entry_or_exit, 'entry') = 'entry'
                      AND execution_price_cents IS NOT NULL
                      AND COALESCE(canonicalization_state, 'UNTRUSTED_LEGACY')
                          NOT IN ('UNTRUSTED_LEGACY', 'UNTRUSTED_RAW',
                                  'UNTRUSTED_SIDE_CONFLICT')
                    ORDER BY created_time DESC
                    LIMIT 1
                    """,
                    (decision_id,),
                ).fetchone()
                return dict(row) if row is not None else None
            finally:
                conn.close()
        except Exception as exc:
            logger.debug(
                "[DECISION-AUDIT-LEDGER] fills-DB fill lookup failed for %s: %s",
                decision_id,
                exc,
            )
            return None

    def _capital_realized_from_fills_db(
        self,
        *,
        ticker: Optional[str],
        fill_id: Optional[str],
        held_side: str,
        settle_value_yes_cents: Optional[float],
    ) -> Optional[Dict[str, Any]]:
        """Capital-realized P&L for one entry lot from the Kalshi fills DB.

        Returns None (callers fall back to the thesis value) when the fills
        DB, the ticker's fills, or the lot cannot be resolved.
        """
        path = self._fills_db_path()
        if not ticker or not fill_id or not path.exists():
            return None
        try:
            fconn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=5.0)
            try:
                fconn.row_factory = sqlite3.Row
                placeholders = ",".join("?" for _ in _UNTRUSTED_FILL_STATES)
                rows = [
                    dict(r)
                    for r in fconn.execute(
                        "SELECT fill_id, created_time, execution_outcome_side, "
                        "execution_action, execution_price_cents, quantity_cc, "
                        "fee_cost FROM kalshi_fills WHERE market_ticker = ? "
                        "AND COALESCE(canonicalization_state, 'UNTRUSTED_LEGACY') "
                        f"NOT IN ({placeholders})",
                        (ticker, *_UNTRUSTED_FILL_STATES),
                    )
                ]
            finally:
                fconn.close()
        except Exception as exc:
            logger.debug(
                "[DECISION-AUDIT-LEDGER] capital-realized fills lookup failed "
                "for %s/%s: %s", ticker, fill_id, exc,
            )
            return None
        return compute_capital_realized_pnl(
            fills=rows,
            target_fill_id=fill_id,
            held_side=held_side,
            settle_value_yes_cents=settle_value_yes_cents,
        )

    def _reconcile_state_path(self) -> Path:
        return Path(
            os.environ.get(
                "MERID_RECONCILE_STATE_PATH",
                str(self.db_path.parent / "reconcile_fill_outcomes_state.json"),
            )
        )

    def _reconcile_state_load(self) -> Dict[str, Any]:
        try:
            return json.loads(self._reconcile_state_path().read_text())
        except Exception:
            return {}

    def _reconcile_state_save(self, **fields: Any) -> None:
        """Persist reconcile progress atomically (tmp file + os.replace)."""
        state = self._reconcile_state_load()
        state.update(fields)
        state["updated_at"] = time.time()
        path = self._reconcile_state_path()
        try:
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(state))
            os.replace(tmp, path)
        except Exception as exc:
            logger.debug(
                "[DECISION-AUDIT-LEDGER] reconcile state save failed: %s", exc
            )

    def _prepare_settlement_attr(
        self,
        *,
        decision_id: str,
        selected_side: Optional[str],
        ticker: Optional[str],
        actual_fill_price_cents: Any,
        fill_id: Optional[str],
        settle_value_yes_cents: Optional[float],
    ) -> Any:
        """Fills-DB reads for ``_attribute_settlement``, outside ``self._lock``.

        Returns ``(entry_fill, capital)``.  ``entry_fill`` is the resolved
        entry fill dict (or None) to hand to ``pre_entry_fill``; ``capital``
        is the ``_capital_realized_from_fills_db`` result (dict or None) for
        ``pre_capital``, or ``_PRECOMPUTE_UNSET`` when attribution is moot
        (no selected side / no resolvable fill id).
        """
        entry_fill = None
        if actual_fill_price_cents is None:
            entry_fill = self._resolve_entry_fill_from_fills_db(decision_id)
        held = str(selected_side or "").lower()
        fid = fill_id or (entry_fill or {}).get("fill_id")
        if held not in ("yes", "no") or not fid:
            return entry_fill, _PRECOMPUTE_UNSET
        return entry_fill, self._capital_realized_from_fills_db(
            ticker=ticker,
            fill_id=fid,
            held_side=held,
            settle_value_yes_cents=settle_value_yes_cents,
        )

    def _attribute_settlement(
        self,
        conn: Any,
        *,
        decision_id: str,
        settlement_value_cents: Optional[int],
        allow_lane_attribution: bool = True,
        pre_entry_fill: Any = _PRECOMPUTE_UNSET,
        pre_capital: Any = _PRECOMPUTE_UNSET,
    ) -> None:
        """Resolve the entry fill (if missing) and persist realized PnL.

        Runs inside the caller's transaction.  For decisions that actually
        filled and held to settlement, realized PnL is
        ``settle_leg - fill - fee`` in selected-side space; the fill row is
        first backfilled from the Kalshi fills ledger when the ingest-time
        bridge missed it.  Lane (threshold-cell / current-build-provisional)
        settlement attribution fires only when ``allow_lane_attribution`` and
        a cell binding exists.
        """
        orow = conn.execute(
            "SELECT actual_fill_price_cents, actual_entry_fee_cents, "
            "realized_net_pnl_cents, settlement_value_cents, fill_id "
            "FROM strategy_decision_outcomes WHERE decision_id = ?",
            (decision_id,),
        ).fetchone()
        if orow is None:
            return
        settle_val = settlement_value_cents
        if settle_val is None:
            settle_val = orow["settlement_value_cents"]
        if settle_val is None:
            return

        if orow["actual_fill_price_cents"] is None:
            f = (
                self._resolve_entry_fill_from_fills_db(decision_id)
                if pre_entry_fill is _PRECOMPUTE_UNSET
                else pre_entry_fill
            )
            if f is not None:
                try:
                    self._record_entry_fill_locked(
                        conn,
                        decision_id=decision_id,
                        fill_id=f.get("fill_id"),
                        exchange_order_id=f.get("order_id"),
                        execution_outcome_side=f.get("execution_outcome_side"),
                        execution_action=f.get("execution_action"),
                        execution_price_cents=f.get("execution_price_cents"),
                        entry_fee_cents=float(f.get("fee_cost") or 0.0) * 100.0,
                    )
                except Exception as exc:
                    logger.debug(
                        "[DECISION-AUDIT-LEDGER] settlement fill backfill "
                        "failed for %s: %s",
                        decision_id,
                        exc,
                    )
                orow = conn.execute(
                    "SELECT actual_fill_price_cents, actual_entry_fee_cents, "
                    "realized_net_pnl_cents, fill_id FROM strategy_decision_outcomes "
                    "WHERE decision_id = ?",
                    (decision_id,),
                ).fetchone()
        if orow is None or orow["actual_fill_price_cents"] is None:
            return
        if orow["realized_net_pnl_cents"] is not None:
            return

        drow = conn.execute(
            "SELECT selected_side, asset, ticker FROM strategy_decisions "
            "WHERE decision_id = ?",
            (decision_id,),
        ).fetchone()
        if drow is None or not drow["selected_side"]:
            return
        _held = str(drow["selected_side"]).lower()
        _fill = float(orow["actual_fill_price_cents"])
        _fee = float(orow["actual_entry_fee_cents"] or 0.0)
        _settle_leg = float(settle_val if _held == "yes" else (100 - settle_val))
        # Thesis P&L: entry vs settlement, as if held.  Persisted in
        # realized_net_pnl_cents (legacy name) — evidence keeps learning from
        # this; it says whether the entry thesis was right.
        _net_pnl_cents = _settle_leg - _fill - _fee

        # Capital-realized P&L: what the account actually booked for this
        # lot (exit proceeds for exited qty + settlement for the residual).
        # Capital-protection counters consume this; falls back to thesis when
        # the lot's fills can't be resolved, so attribution never goes silent.
        _cap = (
            self._capital_realized_from_fills_db(
                ticker=drow["ticker"],
                fill_id=orow["fill_id"],
                held_side=_held,
                settle_value_yes_cents=settle_val,
            )
            if pre_capital is _PRECOMPUTE_UNSET
            else pre_capital
        )
        if _cap is not None and _cap["attribution"] == "held_to_settlement":
            # Held lots realize exactly the thesis value; keep one number.
            _cap["realized_pnl_cents"] = _net_pnl_cents
        _capital_pnl = _cap["realized_pnl_cents"] if _cap is not None else None
        _attribution = _cap["attribution"] if _cap is not None else "unresolved"
        conn.execute(
            "UPDATE strategy_decision_outcomes "
            "SET realized_net_pnl_cents = ?, capital_realized_pnl_cents = ?, "
            "exit_attribution = ? WHERE decision_id = ?",
            (_net_pnl_cents, _capital_pnl, _attribution, decision_id),
        )

        _source = _safety_pnl_source()
        if _source == "realized" and _capital_pnl is not None:
            _safety_pnl = float(_capital_pnl)
        else:
            _safety_pnl = _net_pnl_cents
            if _source == "realized":
                _source = "thesis_fallback"
        _diverged = _capital_pnl is not None and (
            (_capital_pnl < 0.0) != (_net_pnl_cents < 0.0)
        )
        logger.log(
            logging.WARNING if _diverged else logging.INFO,
            "[%s] decision=%s ticker=%s side=%s attribution=%s "
            "thesis_pnl=%.1fc capital_realized_pnl=%s safety_pnl=%.1fc "
            "safety_source=%s exited_qty=%s exit_vwap=%s",
            "SAFETY-PNL-DIVERGENCE" if _diverged else "SAFETY-PNL",
            decision_id,
            drow["ticker"],
            _held,
            _attribution,
            _net_pnl_cents,
            f"{_capital_pnl:.1f}c" if _capital_pnl is not None else "n/a",
            _safety_pnl,
            _source,
            (f"{_cap['exited_qty']:.2f}" if _cap is not None else "n/a"),
            (
                f"{_cap['exit_vwap_cents']:.1f}c"
                if _cap is not None and _cap["exit_vwap_cents"] is not None
                else "n/a"
            ),
        )

        if not allow_lane_attribution:
            return
        try:
            from merid.prediction.threshold_cells import (
                cell_for_decision,
                record_cell_settlement,
            )
            from merid.prediction.current_build_provisional import (
                provisional_cell_for_decision,
                record_provisional_settlement,
            )
            from merid.prediction.marginal_band_lane import (
                marginal_band_for_decision,
                record_settlement as _mb_record_settlement,
            )
            _tc_cell = cell_for_decision(decision_id)
            _cbp_cell = provisional_cell_for_decision(decision_id)
            if _tc_cell:
                record_cell_settlement(
                    decision_id=decision_id,
                    net_pnl_cents=_safety_pnl,
                )
            if _cbp_cell:
                record_provisional_settlement(
                    decision_id=decision_id,
                    net_pnl_cents=_safety_pnl,
                    cell_id=_cbp_cell,
                )
            # 2026-10-12: marginal-band release lane — feed realized PnL into
            # the lane's daily loss / consecutive-loss suspension counters.
            # ``marginal_band_for_decision`` only binds submissions the lane
            # gate recorded, so primary-lane fills are never attributed here.
            if marginal_band_for_decision(decision_id):
                _mb_record_settlement(
                    decision_id=decision_id,
                    net_pnl_cents=_safety_pnl,
                )
        except Exception as exc:
            logger.debug(
                "[DECISION-AUDIT-LEDGER] lane settlement attribution failed "
                "for %s: %s",
                decision_id,
                exc,
            )

        # 2026-10-01 (post_drawdown epoch): feed the same-side loss-streak
        # throttle.  Every settled decision funnels through here, so the
        # directional streak tracker sees all lanes without per-lane wiring.
        try:
            from merid.prediction.directional_regime import (
                record_side_settlement,
            )
            record_side_settlement(
                _held,
                _safety_pnl,
                ts=time.time(),
                decision_id=decision_id,
                asset=(str(drow["asset"]).lower() if drow["asset"] else None),
            )
        except Exception as exc:
            logger.debug(
                "[DECISION-AUDIT-LEDGER] side-throttle settlement record "
                "failed for %s: %s",
                decision_id,
                exc,
            )

    def reconcile_fill_outcomes(self) -> int:
        """Backfill missing entry fills + realized PnL on settled outcomes.

        Heals outcome rows whose fills arrived before the ingest-time audit
        bridge existed (or were missed): resolves each from the fills DB,
        recomputes realized PnL where settlement already landed, and fires the
        lane settlement attribution the original pass skipped.  Returns the
        number of outcome rows updated.
        """
        if not _is_enabled():
            return 0
        self._ensure_db()
        healed = 0
        try:
            fills_path = self._fills_db_path()
            if not fills_path.exists():
                return 0
            # Fresh autocommit connection: ATTACH/DETACH cannot run inside the
            # shared writer's transaction, and this one-shot scan must not
            # serialize against live decision writes anyway (WAL allows a
            # concurrent reader).
            scan_conn = sqlite3.connect(str(self.db_path), timeout=10)
            scan_conn.isolation_level = None
            scan_conn.row_factory = sqlite3.Row
            scan_conn.execute("PRAGMA busy_timeout = 5000")
            try:
                scan_conn.execute(
                    "ATTACH DATABASE ? AS fillsdb", (str(fills_path),)
                )
                # 2026-10-13: keyset-paginate the candidate scan.  One giant
                # fetchall() held a single read transaction across the whole
                # ~1h scan on the 17GB live db — pinning the WAL read-mark
                # (checkpoints deferred, -wal unshrinkable) and starving the
                # audit writer (observed: ~75min of queued decisions before
                # drain).  Autocommit + one page per statement means the read
                # txn is only held for the page's duration, so writers and
                # checkpoints get slots between pages.
                #
                # Paginate on rowid, not decision_id: idx_outcomes_status is
                # effectively (outcome_status, rowid), so this is an ordered
                # index scan whose table probes arrive in storage order —
                # sequential I/O.  decision_id's alphabetical order instead
                # randomizes the probes (one disk seek per row — unworkable
                # at 2M rows on a cold file).
                #
                # Trusted fills ids are materialized once into a temp table:
                # the fill-side predicates then reduce to a single O(1) temp
                # PK probe per outcome row instead of re-evaluating the
                # fills join predicates row-by-row.
                scan_conn.execute(
                    """
                    CREATE TEMP TABLE _fill_ids AS
                    SELECT DISTINCT decision_trace_id
                    FROM fillsdb.kalshi_fills
                    WHERE decision_trace_id IS NOT NULL
                      AND COALESCE(is_exit, 0) = 0
                      AND COALESCE(reduce_only, 0) = 0
                      AND COALESCE(entry_or_exit, 'entry') = 'entry'
                      AND execution_price_cents IS NOT NULL
                      AND COALESCE(canonicalization_state,
                                   'UNTRUSTED_LEGACY')
                          NOT IN ('UNTRUSTED_LEGACY',
                                  'UNTRUSTED_RAW',
                                  'UNTRUSTED_SIDE_CONFLICT')
                    """
                )
                scan_conn.execute(
                    "CREATE UNIQUE INDEX _fill_ids_pk"
                    " ON _fill_ids(decision_trace_id)"
                )
                # 2026-10-13: durable resume watermark.  Three process
                # restarts in one day each restarted this ~40min scan from
                # rowid 0.  resume_rowid is persisted after each healed page
                # so a killed scan continues where it stopped; on completion
                # complete_through_rowid becomes the floor for future boots.
                # Rows below the floor can still become candidates later if a
                # fills-ledger repair backfills an old fill — a full rescan
                # runs every MERID_RECONCILE_FULL_EVERY_S (default 24h) or on
                # MERID_RECONCILE_FULL_SCAN=1 to catch those.
                state = self._reconcile_state_load()
                full_every_s = float(
                    os.environ.get("MERID_RECONCILE_FULL_EVERY_S", str(24 * 3600))
                )
                force_full = os.environ.get(
                    "MERID_RECONCILE_FULL_SCAN", "0"
                ).strip().lower() in ("1", "true", "yes")
                full_due = force_full or (
                    time.time() - float(state.get("last_full_scan_ts") or 0.0)
                    > full_every_s
                )
                last_rowid = 0 if full_due else max(
                    int(state.get("resume_rowid") or 0),
                    int(state.get("complete_through_rowid") or 0),
                )
                started_full = last_rowid == 0
                logger.info(
                    "[DECISION-AUDIT-LEDGER] reconcile_fill_outcomes starting "
                    "at rowid %d (full_scan=%s)",
                    last_rowid,
                    started_full,
                )
                _last_progress_log = 0.0
                while True:
                    rows = scan_conn.execute(
                        """
                        SELECT DISTINCT o.decision_id,
                               o.settlement_value_cents, o.rowid AS _rid,
                               o.fill_id, o.actual_fill_price_cents,
                               d.selected_side, d.ticker
                        FROM strategy_decision_outcomes o
                        LEFT JOIN temp._fill_ids f
                          ON f.decision_trace_id = o.decision_id
                        LEFT JOIN strategy_decisions d
                          ON d.decision_id = o.decision_id
                        WHERE o.outcome_status = 'SETTLED'
                          AND o.realized_net_pnl_cents IS NULL
                          AND o.rowid > ?
                          AND (
                              o.actual_fill_price_cents IS NOT NULL
                              OR f.decision_trace_id IS NOT NULL
                          )
                        ORDER BY o.rowid
                        LIMIT 500
                        """,
                        (last_rowid,),
                    ).fetchall()
                    if not rows:
                        break
                    last_rowid = rows[-1]["_rid"]
                    for row in rows:
                        decision_id = row["decision_id"]
                        # Fills-DB reads outside self._lock: under disk
                        # contention each lookup inside the lock stalled the
                        # whole writer queue behind a fills scan.
                        entry_fill, capital = self._prepare_settlement_attr(
                            decision_id=decision_id,
                            selected_side=row["selected_side"],
                            ticker=row["ticker"],
                            actual_fill_price_cents=row[
                                "actual_fill_price_cents"
                            ],
                            fill_id=row["fill_id"],
                            settle_value_yes_cents=row[
                                "settlement_value_cents"
                            ],
                        )
                        with self._lock, self._conn() as conn:
                            before = conn.execute(
                                "SELECT actual_fill_price_cents, realized_net_pnl_cents "
                                "FROM strategy_decision_outcomes WHERE decision_id = ?",
                                (decision_id,),
                            ).fetchone()
                            self._attribute_settlement(
                                conn,
                                decision_id=decision_id,
                                settlement_value_cents=row["settlement_value_cents"],
                                pre_entry_fill=entry_fill,
                                pre_capital=capital,
                            )
                            after = conn.execute(
                                "SELECT actual_fill_price_cents, realized_net_pnl_cents "
                                "FROM strategy_decision_outcomes WHERE decision_id = ?",
                                (decision_id,),
                            ).fetchone()
                            if (
                                after is not None
                                and before is not None
                                and (
                                    after["actual_fill_price_cents"]
                                    != before["actual_fill_price_cents"]
                                    or after["realized_net_pnl_cents"]
                                    != before["realized_net_pnl_cents"]
                                )
                            ):
                                healed += 1
                    self._reconcile_state_save(resume_rowid=last_rowid)
                    now = time.time()
                    if now - _last_progress_log >= 60.0:
                        _last_progress_log = now
                        logger.info(
                            "[DECISION-AUDIT-LEDGER] reconcile_fill_outcomes "
                            "progress: rowid=%d healed=%d",
                            last_rowid,
                            healed,
                        )
                self._reconcile_state_save(
                    resume_rowid=last_rowid,
                    complete_through_rowid=last_rowid,
                    last_full_scan_ts=(
                        time.time()
                        if started_full
                        else state.get("last_full_scan_ts")
                    ),
                )
                logger.info(
                    "[DECISION-AUDIT-LEDGER] reconcile_fill_outcomes scan "
                    "complete: floor=%d healed=%d",
                    last_rowid,
                    healed,
                )
            finally:
                try:
                    scan_conn.execute("DETACH DATABASE fillsdb")
                except Exception:
                    pass
                scan_conn.close()
        except Exception as exc:
            logger.warning(
                "[DECISION-AUDIT-LEDGER] reconcile_fill_outcomes failed: %s", exc
            )
        if healed:
            logger.info(
                "[DECISION-AUDIT-LEDGER] reconcile_fill_outcomes healed %d rows",
                healed,
            )
        return healed

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
                    SELECT d.decision_id, d.close_ts, d.asset, d.run_id, d.candidate_id,
                           d.selected_side, d.ticker,
                           o.fill_id, o.actual_fill_price_cents,
                           o.realized_net_pnl_cents
                    FROM strategy_decisions d
                    JOIN strategy_decision_outcomes o ON d.decision_id = o.decision_id
                    WHERE d.ticker = ?
                      AND o.outcome_status = 'PENDING'
                      AND ABS(d.close_ts - ?) <= 900.0
                    """,
                    (ticker, close_ts),
                ).fetchall()

            # Phase A (no lock): fills-DB reads for settlement attribution.
            # _resolve_entry_fill / _capital_realized open their own read-only
            # connections to kalshi_fills.db; keeping them inside self._lock
            # serialized the audit writer behind per-ticker fills scans under
            # disk contention (observed 2026-10-13).
            prepared = []
            for row in rows:
                entry_fill = None
                capital = _PRECOMPUTE_UNSET
                if row["realized_net_pnl_cents"] is None:
                    entry_fill, capital = self._prepare_settlement_attr(
                        decision_id=row["decision_id"],
                        selected_side=row["selected_side"],
                        ticker=row["ticker"],
                        actual_fill_price_cents=row["actual_fill_price_cents"],
                        fill_id=row["fill_id"],
                        settle_value_yes_cents=settlement_value_cents,
                    )
                prepared.append((row, entry_fill, capital))

            with self._lock, self._conn() as conn:
                for row, entry_fill, capital in prepared:
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
                        # Conservative fill assumption: only the quantity that
                        # was actually visible at top-of-book at decision time
                        # earns counterfactual P&L.  Rows written before the
                        # executability columns existed keep the historical
                        # one-contract convention (q=1.0).
                        _srow_keys = set(srow.keys())
                        q_assumed = (
                            srow["counterfactual_assumed_filled_contracts"]
                            if "counterfactual_assumed_filled_contracts" in _srow_keys
                            else None
                        )
                        if q_assumed is None:
                            q_assumed = 1.0
                        if side == "yes":
                            if settlement_value_cents is not None:
                                yes_pnl = q_assumed * (
                                    settlement_value_cents
                                    - entry_cents
                                    - entry_fee
                                    - exit_fee
                                )
                        elif side == "no":
                            if settlement_value_cents is not None:
                                no_pnl = q_assumed * (
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
                            outcome_status = ?, policy_epoch = ?
                        WHERE decision_id = ?
                        """,
                        (
                            time.time(),
                            1 if settled_yes else 0,
                            settlement_value_cents,
                            yes_pnl,
                            no_pnl,
                            "SETTLED",
                            _policy_epoch(),
                            decision_id,
                        ),
                    )

                    # 2026-09-30: for a decision that actually filled,
                    # settlement IS the realized PnL when no exit order
                    # already booked it (held-to-settlement).  Backfills the
                    # entry fill from the Kalshi fills ledger when the
                    # ingest-time bridge missed it (post-only async fills),
                    # persists realized_net_pnl_cents, then attributes to the
                    # bound threshold-cell / current-build-provisional lane.
                    try:
                        self._attribute_settlement(
                            conn,
                            decision_id=decision_id,
                            settlement_value_cents=settlement_value_cents,
                            pre_entry_fill=entry_fill,
                            pre_capital=capital,
                        )
                    except Exception:
                        pass

                    # Terminal lifecycle event: official exchange outcome joined
                    # to this decision.  Emitted once per resolved decision;
                    # duplicate settlement deliveries dedupe on event_id.
                    self._append_decision_event_locked(
                        conn,
                        decision_id=decision_id,
                        candidate_id=row["candidate_id"],
                        event_type=DECISION_EVENT_SETTLEMENT_RESOLVED,
                        stage=DECISION_STAGE_OUTCOME,
                        event_ts=time.time(),
                        reason_code="settled_yes" if settled_yes else "settled_no",
                        reason_detail={
                            "settled_yes": bool(settled_yes),
                            "settlement_value_cents": settlement_value_cents,
                            "counterfactual_yes_pnl_cents": yes_pnl,
                            "counterfactual_no_pnl_cents": no_pnl,
                        },
                        run_id=row["run_id"],
                        ticker=ticker,
                        asset=row["asset"],
                    )
        except Exception as exc:
            logger.warning(
                "[DECISION-AUDIT-LEDGER] record_settlement failed for %s: %s",
                ticker,
                exc,
            )
        try:
            self._maybe_refresh_live_entry_evidence(background=True)
        except Exception as exc:
            logger.debug("[DECISION-AUDIT-LEDGER] live evidence refresh failed: %s", exc)

    def _maybe_refresh_live_entry_evidence(self, background: bool = False) -> None:
        """Rebuild the trailing-window live entry-evidence artifact.

        The static tail-calibration artifact is only refit offline, so when a
        regime breaks — an asset+side cohort whose realized win rate collapses
        below its entry prices — the frozen evidence floor keeps passing the
        cell for days.  On every settlement (throttled by
        ``MERID_LIVE_EVIDENCE_REFRESH_S``) this recomputes per (asset, side)
        and per (asset, side, 10c price bucket) settled win rates over
        ``MERID_LIVE_EVIDENCE_WINDOW_HOURS`` and atomically rewrites
        ``MERID_LIVE_EVIDENCE_PATH`` so ``compute_trade_decision`` can gate on
        live evidence between refits.  The v2 artifact additionally stores
        time-decayed, per-ticker-normalized aggregates at
        asset x side x price-bucket x TTE-bucket granularity (``cells``,
        keyed by configured half-life) consumed by the cell-aware evidence
        policy in ``merid/prediction/evidence_policy.py``.
        Fail-open per the ledger contract:
        errors are logged and swallowed.
        """
        if os.environ.get("MERID_LIVE_EVIDENCE_EXPORT", "1").strip().lower() not in (
            "1",
            "true",
            "yes",
        ):
            return
        # Hermetic-test guard (same convention as _load_live_evidence in
        # trade_decision): under pytest a test-scoped ledger must never
        # rewrite the production evidence artifact — only an explicit
        # MERID_LIVE_EVIDENCE_PATH redirect may write during tests.
        if "MERID_LIVE_EVIDENCE_PATH" not in os.environ and _is_test_context():
            return
        now = time.time()
        refresh_s = float(os.environ.get("MERID_LIVE_EVIDENCE_REFRESH_S", "120"))
        if now - self._last_evidence_refresh < refresh_s:
            return
        self._last_evidence_refresh = now
        window_hours = float(os.environ.get("MERID_LIVE_EVIDENCE_WINDOW_HOURS", "48"))
        if not background:
            self._refresh_live_entry_evidence(now, window_hours)
            return
        # 2026-10-05: single-flight background refresh.  The query previously
        # ran inline on the settlement thread while holding ``self._lock``;
        # on the multi-GB audit DB it took 10+ minutes, and every decision
        # write (``record_trade_decision`` -> ``_bump_cycle_stats``) parked
        # behind the lock — the strategy loop froze after each settlement.
        with self._evidence_refresh_guard:
            if self._evidence_refresh_inflight:
                return
            self._evidence_refresh_inflight = True

        def _run() -> None:
            try:
                self._refresh_live_entry_evidence(now, window_hours)
            except Exception as exc:
                logger.warning(
                    "[DECISION-AUDIT-LEDGER] live evidence refresh failed: %s", exc
                )
            finally:
                with self._evidence_refresh_guard:
                    self._evidence_refresh_inflight = False

        threading.Thread(
            target=_run, name="live-evidence-refresh", daemon=True
        ).start()

    def _refresh_live_entry_evidence(self, now: float, window_hours: float) -> None:
        """Query settled ENTER outcomes and atomically rewrite the artifact.

        Runs on its own query-only connection and never takes ``self._lock``:
        WAL readers don't block the ledger's writer, so a slow read can no
        longer stall the decision pipeline.
        """
        since = now - window_hours * 3600.0
        t0 = time.time()
        from merid.prediction import evidence_health as _evh

        _evh.record_refresh_attempt(t0)
        conn: Optional[sqlite3.Connection] = None
        try:
            conn = sqlite3.connect(str(self.db_path), timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA query_only = 1")
            # Drive from o.settled_at: the outcomes index range stays selective
            # (only settled rows in the window), and each decision row is then a
            # PK point lookup.  The inverse (decision_ts range) scans ~48h of the
            # 19GB decisions table — measured 505s vs 5.8s on 2026-10-14.  The
            # earlier comment favoring decision_ts pre-dated the table growth.
            # A decision always precedes its settlement; the one-hour pad on
            # decision_ts still covers decisions made just before the window.
            rows = conn.execute(
                """
                SELECT d.asset AS asset,
                       d.selected_side AS side,
                       d.ticker AS ticker,
                       d.decision_id AS decision_id,
                       d.seconds_to_close AS seconds_to_close,
                       COALESCE(o.actual_fill_price_cents,
                                se.executable_entry_price_cents) AS entry_cents,
                       o.actual_fill_price_cents AS fill_px_cents,
                       se.executable_entry_price_cents AS decision_px_cents,
                       se.expected_entry_slippage_cents AS exp_slip_cents,
                       COALESCE(se.decision_lane, d.admission_lane) AS lane,
                       se.calibrated_probability AS calibrated_probability,
                       o.settled_yes AS settled_yes,
                       o.settled_at AS settled_at,
                       'fill' AS src,
                       d.decision_ts AS decision_ts,
                       d.ticker AS mkey
                FROM strategy_decision_outcomes o
                JOIN strategy_decisions d ON d.decision_id = o.decision_id
                LEFT JOIN strategy_decision_side_ev se
                  ON se.decision_id = d.decision_id
                 AND se.side = d.selected_side
                WHERE o.outcome_status = 'SETTLED'
                  AND o.settled_at >= ?
                  AND d.decision_ts >= ?
                  AND d.decision = 'ENTER'
                  AND d.selected_side IN ('yes', 'no')
                  AND d.is_eligible_for_research = 1
                """,
                (since, since - 3600.0),
            ).fetchall()
            # 2026-10-15: survivorship-bias repair.  Vetoed candidates are
            # evidence too — scoring only ENTER fills filters the cohort to
            # whatever yesterday's gates already allowed, so a bad gate can
            # never accumulate the evidence that would clear it and a good
            # gate's cost is invisible.  Every settled NO_TRADE decision
            # contributes each side_ev row that carried an executable price:
            # "would this side have won at the quoted entry?"  Normalization
            # keys on (ticker, side) inside build_cells so repeated evals of
            # one market-side pair collapse to ~1 observation.  Disable with
            # MERID_EVIDENCE_INCLUDE_VETOES=0.
            if os.environ.get(
                "MERID_EVIDENCE_INCLUDE_VETOES", "1"
            ).strip().lower() in ("1", "true", "yes", "on"):
                veto_rows = conn.execute(
                    """
                    SELECT d.asset AS asset,
                           se.side AS side,
                           d.ticker AS ticker,
                           d.decision_id AS decision_id,
                           d.seconds_to_close AS seconds_to_close,
                           se.executable_entry_price_cents AS entry_cents,
                           NULL AS fill_px_cents,
                           NULL AS decision_px_cents,
                           NULL AS exp_slip_cents,
                           NULL AS lane,
                           se.calibrated_probability AS calibrated_probability,
                           o.settled_yes AS settled_yes,
                           o.settled_at AS settled_at,
                           d.decision_ts AS decision_ts,
                           se.exclusion_reason AS exclusion_reason,
                           se.passed_edge_gate AS passed_edge_gate,
                           'veto' AS src,
                           d.ticker || '|' || se.side AS mkey
                    FROM strategy_decision_outcomes o
                    JOIN strategy_decisions d ON d.decision_id = o.decision_id
                    JOIN strategy_decision_side_ev se
                      ON se.decision_id = d.decision_id
                    WHERE o.outcome_status = 'SETTLED'
                      AND o.settled_at >= ?
                      AND d.decision_ts >= ?
                      AND d.decision = 'NO_TRADE'
                      AND se.side IN ('yes', 'no')
                      AND se.executable_entry_price_cents IS NOT NULL
                      AND se.executable_entry_price_cents BETWEEN 1 AND 100
                      AND d.is_eligible_for_research = 1
                    """,
                    (since, since - 3600.0),
                ).fetchall()
                rows = list(rows) + list(veto_rows)
        except Exception as exc:
            logger.warning(
                "[DECISION-AUDIT-LEDGER] live evidence query failed: %s", exc
            )
            _evh.record_refresh_result(False, f"query: {exc}")
            return
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
        logger.info(
            "[DECISION-AUDIT-LEDGER] live evidence query rows=%d elapsed_s=%.1f",
            len(rows), time.time() - t0,
        )

        # The coarse asset rollup is a *fills tripwire*: its consumers
        # hard-block an asset x side cohort when the EXECUTED entry cohort's
        # win rate no longer covers its cost basis.  Vetoed candidates must
        # not enter it — the unconditional candidate-surface win rate sits
        # at ~price/100 by market efficiency, which would read as -EV and
        # block every cohort.  Vetoed candidates feed the normalized v2
        # cells (below) instead, and get their own audit rollup under
        # ``veto_assets`` so gate-leak analysis can compare the cohorts.
        assets: Dict[str, Dict[str, Any]] = {}
        veto_assets: Dict[str, Dict[str, Any]] = {}
        # Veto rollup is deduped to the newest eval per (ticker, side) so a
        # market sampled 200x contributes one candidate observation — eval
        # density must not overweight volatile markets in the audit numbers.
        _veto_latest: Dict[str, Any] = {}
        for row in rows:
            if row["src"] == "veto":
                _mk = str(row["mkey"])
                _prev = _veto_latest.get(_mk)
                if _prev is None or float(
                    row["decision_ts"] or 0.0
                ) >= float(_prev["decision_ts"] or 0.0):
                    _veto_latest[_mk] = row
                continue
        _veto_rows = list(_veto_latest.values())
        # Gate-level veto calibration: per (blocking reason, side, 10c price
        # bucket) cohort stats on deduped vetoed candidates.  ``reason`` is
        # ``passed_not_selected`` for candidates that cleared every gate but
        # lost argmax — the missed-opportunity cohort.
        veto_reasons: Dict[str, Dict[str, Any]] = {}
        for row in _veto_rows:
            entry_cents = row["entry_cents"]
            if entry_cents is None or not (0 < int(entry_cents) <= 100):
                continue
            asset = (str(row["asset"] or "").upper()) or "UNKNOWN"
            side = str(row["side"]).lower()
            reason = row["exclusion_reason"]
            if not reason:
                reason = (
                    "passed_not_selected"
                    if row["passed_edge_gate"]
                    else "unscored"
                )
            won = 1.0 if ((side == "yes") == bool(row["settled_yes"])) else 0.0
            bucket = min(int(entry_cents) // 10 * 10, 90)
            rec = veto_reasons.setdefault(str(reason), {}).setdefault(
                f"{asset}|{side}|{bucket}", {"n": 0, "wins": 0.0, "px_sum": 0.0}
            )
            rec["n"] += 1
            rec["wins"] += won
            rec["px_sum"] += float(entry_cents)
        for row in _veto_rows + [
            r for r in rows if r["src"] != "veto"
        ]:
            entry_cents = row["entry_cents"]
            if entry_cents is None or not (0 < int(entry_cents) <= 100):
                continue
            asset = (str(row["asset"] or "").upper()) or "UNKNOWN"
            side = str(row["side"]).lower()
            won = 1 if ((side == "yes") == bool(row["settled_yes"])) else 0
            target = veto_assets if row["src"] == "veto" else assets
            rec = target.setdefault(asset, {}).setdefault(
                side, {"n": 0, "wins": 0, "entry_cents_sum": 0.0, "buckets": {}}
            )
            rec["n"] += 1
            rec["wins"] += won
            rec["entry_cents_sum"] += float(entry_cents)
            bucket = min(int(entry_cents) // 10 * 10, 90)
            b = rec["buckets"].setdefault(str(bucket), {"n": 0, "wins": 0})
            b["n"] += 1
            b["wins"] += won

        # Cell-aware v2 aggregates: decayed, per-ticker-normalized win/loss
        # sums keyed "ASSET|side|price_bucket|tte_bucket".  Per-ticker
        # normalization caps one market's total contribution at its newest
        # observation's decay weight, so a ticker sampled 50 times is ~1
        # effective market, not 50 samples.
        try:
            from merid.prediction import evidence_policy as _ep
        except Exception:
            _ep = None
        cells_by_halflife: Dict[str, Dict[str, Dict[str, Any]]] = {}
        h1 = float(os.environ.get("MERID_EVIDENCE_HALFLIFE_DAYS", "7"))
        h2 = float(os.environ.get("MERID_EVIDENCE_HALFLIFE_DAYS_ALT", "21"))
        recent_days = float(os.environ.get("MERID_EVIDENCE_RECENT_DAYS", "14"))
        if _ep is not None:
            dict_rows = [{k: r[k] for k in r.keys()} for r in rows]
            for h in (h1, h2):
                cells_by_halflife[f"{h:g}"] = _ep.build_cells(
                    dict_rows, h, now=now, recent_days=recent_days
                )

        # Rolling calibration monitor: per-asset ECE / Brier / signed bias on
        # deduped candidates (one obs per market-side).  Vetoes count the
        # same as fills — a candidate's calibrated_probability is scored
        # against the settlement outcome regardless of whether a gate
        # admitted it.  This is the drift signal: when an asset's ECE or
        # bias climbs, its cells are stale before any audit reads them.
        cal_rows = [
            r for r in _veto_rows + [x for x in rows if x["src"] != "veto"]
            if r["calibrated_probability"] is not None
        ]
        cal_monitor: Dict[str, Any] = {}
        cal_by_asset: Dict[str, list] = {}
        for r in cal_rows:
            cal_by_asset.setdefault(
                (str(r["asset"] or "").upper()) or "UNKNOWN", []
            ).append(r)
        for asset, arows in sorted(cal_by_asset.items()):
            bins: Dict[int, list] = {}
            brier = 0.0
            bias = 0.0
            n = 0
            for r in arows:
                p = float(r["calibrated_probability"])
                if not (0.0 <= p <= 1.0):
                    continue
                y = 1.0 if (
                    (str(r["side"]).lower() == "yes") == bool(r["settled_yes"])
                ) else 0.0
                b = min(int(p * 10), 9)
                bb = bins.setdefault(b, [0.0, 0.0, 0])
                bb[0] += p
                bb[1] += y
                bb[2] += 1
                brier += (p - y) ** 2
                bias += p - y
                n += 1
            if not n:
                continue
            ece = sum(
                (bb[2] / n) * abs(bb[0] / bb[2] - bb[1] / bb[2])
                for bb in bins.values()
                if bb[2]
            )
            cal_monitor[asset] = {
                "n": n,
                "ece": round(ece, 4),
                "brier": round(brier / n, 4),
                "mean_bias": round(bias / n, 4),
                "bins": {
                    str(b): {
                        "n": bb[2],
                        "mean_p": round(bb[0] / bb[2], 4),
                        "wr": round(bb[1] / bb[2], 4),
                    }
                    for b, bb in sorted(bins.items())
                    if bb[2]
                },
            }

        # 2026-10-15 (FIX 13): implementation shortfall — the realized gap
        # between the executable price the EV gate assumed
        # (``executable_entry_price_cents``) and the exchange fill
        # (``actual_fill_price_cents``), positive = we paid more than
        # modeled.  Per asset x side x admission lane, plus a coarse
        # price-basis rollup (post-only lanes -> "bid", the rest -> "ask")
        # so the decision path can charge the matching cohort at gate time.
        # Expected-vs-realized slippage (``exp_slip_cents``) is emitted for
        # audit of the slippage model itself.
        _MAKER_LANES = frozenset({
            "maker_bid", "canary_maker", "empirical_marginal_maker",
            "threshold_cell", "current_build_provisional",
            "evidence_cell_escape",
        })
        impl_by_lane: Dict[str, list] = {}
        impl_by_basis: Dict[str, list] = {}
        slippage_model_err: Dict[str, list] = {}
        for r in rows:
            if r["src"] != "fill":
                continue
            fp = r["fill_px_cents"]
            dp = r["decision_px_cents"]
            if fp is None or dp is None:
                continue
            asset = (str(r["asset"] or "").upper()) or "UNKNOWN"
            side = str(r["side"] or "").lower()
            lane = str(r["lane"] or "core")
            basis = "bid" if lane in _MAKER_LANES else "ask"
            gap = float(fp) - float(dp)
            impl_by_lane.setdefault(f"{asset}|{side}|{lane}", []).append(gap)
            # Exact cohort plus coarser fallbacks so a sparse asset/side can
            # still charge the measured asset-level or global price gap.
            impl_by_basis.setdefault(f"{asset}|{side}|{basis}", []).append(gap)
            impl_by_basis.setdefault(f"{asset}|*|{basis}", []).append(gap)
            impl_by_basis.setdefault(f"*|*|{basis}", []).append(gap)
            es = r["exp_slip_cents"]
            if es is not None:
                slippage_model_err.setdefault(
                    f"{asset}|{side}|{basis}", []
                ).append(float(es) - gap)

        def _q75(vals: list) -> float:
            s = sorted(vals)
            return s[min(len(s) - 1, max(0, int(round(0.75 * (len(s) - 1)))))]

        # 2026-10-15 (FIX 14): fold this settled cohort (fills AND vetoed
        # candidates — same rows the cells/monitor just consumed) into the
        # streaming calibration overlay.  One observation per market-side,
        # watermark-deduped so repeated window scans don't re-apply rows.
        try:
            from merid.prediction import streaming_calibration as _sc
            _sc.update_from_rows(
                [{k: r[k] for k in r.keys()} for r in rows], now=now
            )
        except Exception as exc:
            logger.warning(
                "[DECISION-AUDIT-LEDGER] streaming calibration update failed: %s",
                exc,
            )

        implementation_shortfall: Dict[str, Any] = {
            "definition": "actual_fill_price_cents - executable_entry_price_cents; positive = overpaid vs decision price",
            "by_lane": {
                k: {
                    "n": len(v),
                    "mean_cents": round(sum(v) / len(v), 3),
                    "q75_cents": round(_q75(v), 3),
                }
                for k, v in sorted(impl_by_lane.items())
            },
            "by_basis": {
                k: {
                    "n": len(v),
                    "mean_cents": round(sum(v) / len(v), 3),
                    "q75_cents": round(_q75(v), 3),
                }
                for k, v in sorted(impl_by_basis.items())
            },
            # positive => the modeled slippage expectation was optimistic
            "slippage_model_error": {
                k: {
                    "n": len(v),
                    "mean_cents": round(sum(v) / len(v), 3),
                }
                for k, v in sorted(slippage_model_err.items())
            },
        }

        def _rollup(src_map: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
            rolled: Dict[str, Any] = {}
            for asset, sides in src_map.items():
                asset_rec: Dict[str, Any] = {}
                for side, rec in sides.items():
                    n = rec["n"]
                    asset_rec[side] = {
                        "n": n,
                        "wr": rec["wins"] / n if n else 0.0,
                        "avg_entry_cents": (
                            rec["entry_cents_sum"] / n if n else 0.0
                        ),
                        "buckets": {
                            k: {
                                "n": b["n"],
                                "wr": (b["wins"] / b["n"] if b["n"] else 0.0),
                            }
                            for k, b in rec["buckets"].items()
                        },
                    }
                rolled[asset] = asset_rec
            return rolled

        out: Dict[str, Any] = {
            "version": 2,
            "generated_at": now,
            "window_hours": window_hours,
            "halflife_days_primary": h1,
            "halflife_days_alt": h2,
            "assets": _rollup(assets),
            # Candidate-surface (vetoed) rollup, deduped per market-side.
            # Audit-only: compare ``wr`` against ``avg_entry_cents`` per
            # cohort — a vetoed cohort that beats its quoted price is a
            # gate leaking +EV candidates, the inverse is a working gate.
            "veto_assets": _rollup(veto_assets),
            "calibration_monitor": cal_monitor,
            "implementation_shortfall": implementation_shortfall,
            # Gate-level veto calibration: reason -> "ASSET|side|bucket" ->
            # {n, wr, avg_px}; compare wr vs avg_px to price each gate's
            # ex-post cost per cohort.
            "veto_reasons": {
                reason: {
                    cell: {
                        "n": rec["n"],
                        "wr": rec["wins"] / rec["n"] if rec["n"] else 0.0,
                        "avg_px": rec["px_sum"] / rec["n"] if rec["n"] else 0.0,
                    }
                    for cell, rec in cells_rec.items()
                }
                for reason, cells_rec in veto_reasons.items()
            },
            "cells": cells_by_halflife,
        }

        path = Path(
            os.environ.get("MERID_LIVE_EVIDENCE_PATH", "data/live_entry_evidence.json")
        )
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(out))
            os.replace(tmp, path)
            _evh.record_refresh_result(True)
        except Exception as exc:
            logger.warning(
                "[DECISION-AUDIT-LEDGER] live evidence write failed: %s", exc
            )
            _evh.record_refresh_result(False, f"write: {exc}")

    def pending_unsettled_tickers(
        self,
        now: Optional[float] = None,
        grace_s: float = 120.0,
        lookback_s: float = 12 * 3600.0,
        limit: int = 60,
    ) -> List[Tuple[str, float]]:
        """Tickers whose decisions are still PENDING though the market closed.

        ``/portfolio/settlements`` only reports markets the account held a
        position in, so markets we evaluated but never entered never produce
        settlement events — their decision outcomes would stay PENDING
        forever.  The settlement poller sweeps these via a direct
        ``/markets/{ticker}`` lookup.  Bounded to recent tickers so the sweep
        never walks the full history.
        """
        if not _is_enabled():
            return []
        self._ensure_db()
        now_ts = now if now is not None else time.time()
        cutoff = now_ts - grace_s
        floor = now_ts - lookback_s
        try:
            with self._lock, self._conn() as conn:
                rows = conn.execute(
                    """
                    SELECT d.ticker AS ticker, MAX(d.close_ts) AS close_ts
                    FROM strategy_decisions d
                    JOIN strategy_decision_outcomes o
                      ON d.decision_id = o.decision_id
                    WHERE o.outcome_status = 'PENDING'
                      AND d.close_ts < ?
                      AND d.close_ts > ?
                      AND d.ticker IS NOT NULL
                      AND d.ticker != ''
                    GROUP BY d.ticker
                    ORDER BY close_ts DESC
                    LIMIT ?
                    """,
                    (cutoff, floor, limit),
                ).fetchall()
            return [(r["ticker"], float(r["close_ts"])) for r in rows]
        except Exception as exc:
            logger.warning(
                "[DECISION-AUDIT-LEDGER] pending_unsettled_tickers failed: %s", exc
            )
            return []

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

        # Scheduled WAL maintenance.  Heartbeats fire every cycle, so gate the
        # checkpoint on wall-clock interval.  TRUNCATE first so the -wal file
        # actually shrinks (PASSIVE merges frames but leaves the file at its
        # high-water size — observed: a 1.8GB container of already-merged
        # frames).  TRUNCATE defers to readers via busy_timeout; on busy the
        # PASSIVE fallback still merges what it can.  Both run on this writer
        # thread, never the event loop.
        if _WAL_CHECKPOINT_INTERVAL_S > 0:
            now = time.time()
            if now - self._last_wal_checkpoint >= _WAL_CHECKPOINT_INTERVAL_S:
                self._last_wal_checkpoint = now
                if self.wal_checkpoint("TRUNCATE"):
                    self.wal_checkpoint("PASSIVE")

    def wal_checkpoint(self, mode: str = "PASSIVE") -> bool:
        """Best-effort WAL checkpoint for the audit DB.

        The decision writer and analytics readers share the multi-GB WAL; an
        unchecked WAL grows unboundedly (observed: 1.5 GB alongside a 17 GB
        db) and turns every analytic scan into a writer-contending merge.
        PASSIVE copies every frame it can without waiting for readers, so it
        is safe on the serialized writer path.  Failures are logged, never
        raised to callers.

        Returns True when the checkpoint was deferred (busy readers) or
        failed, so callers can fall back to a weaker mode.
        """
        if not _is_enabled() or not self.db_path.exists():
            return False
        if mode not in ("PASSIVE", "FULL", "RESTART", "TRUNCATE"):
            mode = "PASSIVE"
        try:
            with self._lock:
                conn = self._conn()
                busy, wal_frames, ckpt_frames = conn.execute(
                    "PRAGMA wal_checkpoint(%s)" % mode
                ).fetchone()
            if busy:
                logger.info(
                    "[DECISION-AUDIT-LEDGER] wal_checkpoint(%s) deferred by readers "
                    "(wal=%s frames, ckpt=%s)",
                    mode, wal_frames, ckpt_frames,
                )
            else:
                logger.info(
                    "[DECISION-AUDIT-LEDGER] wal_checkpoint(%s): %s/%s frames merged",
                    mode, ckpt_frames, wal_frames,
                )
            return bool(busy)
        except Exception as exc:
            logger.warning(
                "[DECISION-AUDIT-LEDGER] wal_checkpoint(%s) failed: %s", mode, exc
            )
            return True

    def _bump_cycle_stats(
        self,
        cycle_id: Optional[str],
        *,
        expected: int,
        persisted: int,
        snapshots: int,
        side_ev: int,
        latency_ms: float,
        side_ev_expected: int = 0,
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
                    "side_ev_expected": 0,
                    "latency_ms": 0.0,
                    "error_count": 0,
                },
            )
            stats["expected"] += expected
            stats["persisted"] += persisted
            stats["snapshots"] += snapshots
            stats["side_ev"] += side_ev
            stats["side_ev_expected"] += side_ev_expected
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
                "side_ev_expected": 0,
                "latency_ms": 0.0,
                "error_count": 0,
            }
        decisions_expected = stats["expected"]
        decisions_persisted = stats["persisted"]
        snapshots_persisted = stats["snapshots"]
        # Only full trade decisions emit side-EV rows (2 per decision);
        # pre-decision rejections persist a decision row with no side-EV, so
        # deriving expectation from persisted count overstates it.
        side_ev_expected = stats["side_ev_expected"]
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
        # Backlog observability: the heartbeat itself runs on the writer
        # thread, so qsize() here is the queue remaining at write time.  A
        # sustained nonzero depth means writes are landing late (observed:
        # ~75min of silence under disk saturation before draining).  Warn at
        # depth so the gap is loud instead of inferred after the fact.
        queue_depth = self._write_queue.qsize()
        if queue_depth > 200:
            logger.warning(
                "[DECISION-AUDIT-LEDGER] writer backlog: %d queued writes "
                "pending; audit rows will land late",
                queue_depth,
            )
        logger.info(
            "[DECISION-AUDIT-HEARTBEAT] cycle_id=%s tick=%d assets=%d "
            "decisions_expected=%d decisions_persisted=%d "
            "side_ev_expected=%d side_ev_persisted=%d "
            "latency_ms=%.2f errors=%d queue_depth=%d shed=%s lat=%s",
            cycle_id,
            tick,
            assets_evaluated,
            decisions_expected,
            decisions_persisted,
            side_ev_expected,
            side_ev_persisted,
            ledger_write_latency_ms,
            ledger_error_count,
            queue_depth,
            self._shed_stats,
            _latency_snapshot_field(),
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

        # Stable identity: ``candidate_id`` groups all evaluation attempts of
        # one market observation; instrumented writers mint decision_id as
        # ``<candidate_id>:<route>`` (taker/maker/shadow).  Legacy ids pass
        # through unchanged.
        candidate_id = _candidate_id_from_decision_id(decision_id)
        run_id = _safe_attr(decision, "run_id")

        # Complete gate vector: pure projection of the already-evaluated
        # decision evidence.  Read-only — never re-runs gates, never mutates
        # live state; the live path still short-circuits on first failure.
        gate_results_json = "{}"
        all_failed_gates_json = "[]"
        gate_eval_version = 0
        _gate_eval_error: Optional[str] = None
        try:
            from merid.prediction.gate_evaluation import evaluate_all_gates

            _gate_eval = evaluate_all_gates(
                decision, market_state=market_state
            )
            if _gate_eval is not None:
                gate_results_json = json.dumps(
                    _gate_eval.gate_results_dict(), default=str
                )
                all_failed_gates_json = json.dumps(
                    list(_gate_eval.all_failed_gates)
                )
                gate_eval_version = _gate_eval.evaluation_schema_version
            else:
                _gate_eval_error = "evaluate_all_gates returned None"
        except Exception as exc:
            _gate_eval_error = f"{type(exc).__name__}: {exc}"
            logger.debug(
                "[DECISION-AUDIT-LEDGER] gate evaluation failed for %s: %s",
                decision_id,
                exc,
            )

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
        # spot_price is the instantaneous price the model consumed (the latest
        # CF RTI tick recorded as indicators["bachelier_spot"]).  The 60-second
        # settlement reference is stored in its own column and must not be
        # conflated with the model input.
        spot_price = _to_float(
            indicators.get("bachelier_spot")
            or getattr(decision, "spot_price", None)
        )
        if spot_price is not None and spot_price <= 0:
            spot_price = None

        # Market-state derived BBO and depth.
        yes_bid, yes_ask, no_bid, no_ask = _best_bid_ask(market_state)
        yes_depth, no_depth = _depth_levels(market_state)
        book_age_ms = _book_age_ms(market_state, decision_ts)
        book_is_crossed = _book_is_crossed(market_state)
        book_is_executable = _book_is_executable(market_state)
        book_sequence = _safe_attr(market_state, "book_sequence")
        book_snapshot_id = _safe_attr(market_state, "book_snapshot_id")

        # Quote provenance: which feed owned the effective executable quote and
        # the raw feed health/divergence observed at decision time.  Prefer the
        # values frozen into decision.indicators at decision creation; fall
        # back to the live market_state object for decisions that predate the
        # indicator stamping.
        quote_owner = (
            str(indicators.get("quote_owner"))
            if indicators.get("quote_owner") is not None
            else _safe_attr(market_state, "quote_owner")
        )
        _degraded_ind = indicators.get("quote_degraded_mode")
        degraded_mode = (
            bool(_degraded_ind)
            if _degraded_ind is not None
            else (bool(getattr(market_state, "degraded_mode", False)) if market_state is not None else False)
        )
        ws_last_seq = _to_int(getattr(market_state, "ws_last_seq", None))
        ws_last_event_age_ms = _to_float(
            indicators.get("ws_last_event_age_ms")
            if indicators.get("ws_last_event_age_ms") is not None
            else getattr(market_state, "ws_last_event_age_ms", None)
        )
        ws_last_queue_wait_ms = _to_float(
            indicators.get("ws_last_queue_wait_ms")
            if indicators.get("ws_last_queue_wait_ms") is not None
            else getattr(market_state, "ws_last_queue_wait_ms", None)
        )
        ws_rest_bid_diff_ticks = _to_int(
            indicators.get("ws_rest_bid_diff_ticks")
            if indicators.get("ws_rest_bid_diff_ticks") is not None
            else getattr(market_state, "ws_rest_bid_diff_ticks", None)
        )
        ws_rest_ask_diff_ticks = _to_int(
            indicators.get("ws_rest_ask_diff_ticks")
            if indicators.get("ws_rest_ask_diff_ticks") is not None
            else getattr(market_state, "ws_rest_ask_diff_ticks", None)
        )
        _ws_parity = (
            indicators.get("ws_parity_healthy")
            if indicators.get("ws_parity_healthy") is not None
            else getattr(market_state, "ws_parity_healthy", None)
        )
        ws_parity_healthy = None if _ws_parity is None else (1 if _ws_parity else 0)
        rest_age_ms = _rest_age_ms(market_state, decision_ts)

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

            _sel_for_owner = str(
                getattr(decision, "selected_outcome", "") or ""
            ).lower()
            conn.execute(
                """
                INSERT INTO strategy_decisions (
                    decision_id, parent_decision_id, decision_ts, observed_at_ts,
                    decision_ts_iso, strategy_name, strategy_version, model_version,
                    calibration_version, config_version, ticker, asset, market_open_ts,
                    close_ts, close_ts_iso, seconds_to_close, strike, settlement_reference,
                    settlement_rule_version, selected_side, decision, primary_reason_code,
                    reason_codes, record_environment, record_source, is_eligible_for_research,
                    exclusion_reason, shadow_cohort_json, created_at,
                    admission_lane, admission_owner, provisional_cell_id, build_sha,
                    policy_epoch, dir_regime,
                    candidate_id, run_id, gate_results_json, all_failed_gates_json,
                    gate_evaluation_schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    indicators.get("decision_lane"),
                    indicators.get(f"{_sel_for_owner}_admission_owner"),
                    indicators.get("provisional_cell_id"),
                    getattr(decision, "build_sha", None),
                    indicators.get("policy_epoch")
                    or _policy_epoch(),
                    indicators.get("dir_regime"),
                    candidate_id,
                    run_id,
                    gate_results_json,
                    all_failed_gates_json,
                    gate_eval_version,
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
                    velocity_age_ms, confidence, confidence_reasons,
                    quote_owner, degraded_mode, ws_last_seq, ws_last_event_age_ms,
                    ws_last_queue_wait_ms, ws_rest_bid_diff_ticks,
                    ws_rest_ask_diff_ticks, ws_parity_healthy, rest_age_ms
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    quote_owner,
                    1 if degraded_mode else 0,
                    ws_last_seq,
                    ws_last_event_age_ms,
                    ws_last_queue_wait_ms,
                    ws_rest_bid_diff_ticks,
                    ws_rest_ask_diff_ticks,
                    ws_parity_healthy,
                    rest_age_ms,
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
                        required_edge_cents, passed_edge_gate,
                        admission_owner, threshold_source, legacy_risk_label,
                        requested_contracts, top_of_book_executable_contracts,
                        counterfactual_assumed_filled_contracts,
                        counterfactual_fill_ratio, counterfactual_full_fill_possible,
                        counterfactual_execution_status, counterfactual_entry_source,
                        counterfactual_fee_model_version,
                        counterfactual_slippage_model_version,
                        counterfactual_fill_model_version,
                        gate_ev_cents, enforced_edge_bound_cents,
                        decision_lane,
                        evidence_state, evidence_age_s, evidence_action,
                        evidence_binding_gate, evidence_artifact_mtime,
                        evidence_last_refresh_success_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                        side_row.get("admission_owner"),
                        side_row.get("threshold_source"),
                        side_row.get("legacy_risk_label"),
                        side_row.get("requested_contracts"),
                        side_row.get("top_of_book_executable_contracts"),
                        side_row.get("counterfactual_assumed_filled_contracts"),
                        side_row.get("counterfactual_fill_ratio"),
                        side_row.get("counterfactual_full_fill_possible"),
                        side_row.get("counterfactual_execution_status"),
                        side_row.get("counterfactual_entry_source"),
                        side_row.get("counterfactual_fee_model_version"),
                        side_row.get("counterfactual_slippage_model_version"),
                        side_row.get("counterfactual_fill_model_version"),
                        side_row.get("gate_ev_cents"),
                        side_row.get("enforced_edge_bound_cents"),
                        side_row.get("decision_lane"),
                        side_row.get("evidence_state"),
                        side_row.get("evidence_age_s"),
                        side_row.get("evidence_action"),
                        side_row.get("evidence_binding_gate"),
                        side_row.get("evidence_artifact_mtime"),
                        side_row.get("evidence_last_refresh_success_at"),
                    ),
                )

            # Insert a PENDING outcome row for the settlement joiner to fill later.
            conn.execute(
                "INSERT INTO strategy_decision_outcomes (decision_id) VALUES (?)",
                (decision_id,),
            )

            # First decision-stage lifecycle event: the model either emitted an
            # executable candidate or ended NO_TRADE.  ``primary_reason_code``
            # preserves this first-stage outcome; any later allocator/risk/
            # router rejection is appended as a separate event, never written
            # over this one.
            self._append_decision_event_locked(
                conn,
                decision_id=decision_id,
                candidate_id=candidate_id,
                event_type=(
                    DECISION_EVENT_MODEL_SELECTED
                    if decision_type == "ENTER"
                    else DECISION_EVENT_MODEL_REJECTED
                ),
                stage=DECISION_STAGE_MODEL,
                event_ts=decision_ts,
                reason_code=primary_reason,
                reason_detail={
                    "decision": decision_type,
                    "reason_codes": list(reason_codes),
                    "selected_side": selected_side,
                    "route": _route_from_decision_id(decision_id),
                },
                trace_id=candidate_id,
                run_id=run_id,
                ticker=str(getattr(decision, "ticker", "")) or None,
                asset=str(getattr(decision, "asset", "")) or None,
            )

            # The spec's invariant is "gate vector OR an explicit
            # instrumentation-gap event" — never a silent {}.
            if _gate_eval_error is not None:
                self._append_decision_event_locked(
                    conn,
                    decision_id=decision_id,
                    candidate_id=candidate_id,
                    event_type=DECISION_EVENT_INSTRUMENTATION_GAP,
                    stage=DECISION_STAGE_MODEL,
                    event_ts=decision_ts,
                    reason_code="gate_evaluation_unavailable",
                    reason_detail={"error": _gate_eval_error},
                    trace_id=candidate_id,
                    run_id=run_id,
                    ticker=str(getattr(decision, "ticker", "")) or None,
                    asset=str(getattr(decision, "asset", "")) or None,
                )


# ── Singleton ──────────────────────────────────────────────────────────────

_ledger_instance: Optional[DecisionAuditLedger] = None
_ledger_lock = threading.Lock()


def _drain_ledger_at_exit() -> None:
    """atexit backstop: flush queued audit writes on non-lifespan exits
    (Ctrl+C, sys.exit, interpreter teardown).  The uvicorn lifespan calls
    close() earlier; this covers every other graceful path."""
    inst = _ledger_instance
    if inst is None:
        return
    try:
        inst.close()
    except Exception:
        pass


atexit.register(_drain_ledger_at_exit)


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

    # Policy eligibility: executable price inside the canonical 10c-95c band.
    in_canonical = (
        entry_price_cents is not None
        and _CANONICAL_MIN_CENTS <= entry_price_cents <= _CANONICAL_MAX_CENTS
    )
    eligible_for_policy = eligible_for_model and in_canonical

    # Edge gate verdict = the comparison the live gate actually enforced:
    # the EPC-adjusted effective edge vs the post-caution, post-slack bound
    # (stamped as {side}_gate_ev_cents / {side}_effective_gate_edge_cents).
    # When those stamps are absent (legacy decisions) fall back to the raw
    # net-edge vs policy-bound check.  The raw pair stays in
    # expected_net_ev_cents / required_edge_cents so the strict economics
    # view is still derivable and any rescue/lift is attributable to the
    # named slack or EPC components.
    _gate_ev_cents = _to_float(indicators.get(f"{side}_gate_ev_cents"))
    _enforced_bound_cents = _to_float(
        indicators.get(f"{side}_effective_gate_edge_cents")
    )
    if _gate_ev_cents is not None and _enforced_bound_cents is not None:
        passed_edge = (
            eligible_for_model
            and math.isfinite(_gate_ev_cents)
            and _gate_ev_cents >= _enforced_bound_cents - 1e-9
        )
    else:
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

    if side == "yes":
        side_raw_probability = _to_float(getattr(decision, "p_yes_raw", None))
    else:
        side_raw_probability = _to_float(indicators.get("p_no_raw"))
        if side_raw_probability is None:
            _p_yes_raw = _to_float(getattr(decision, "p_yes_raw", None))
            if _p_yes_raw is not None:
                side_raw_probability = 1.0 - _p_yes_raw

    # Counterfactual executability: the size the policy would have requested
    # (approved_size_cc when present, else the canonical one-contract unit)
    # versus what the recorded top-of-book could actually absorb.
    _approved_cc = _to_float(getattr(decision, "approved_size_cc", None))
    _requested_contracts = (
        _approved_cc / 100.0
        if _approved_cc is not None and _approved_cc > 0
        else 1.0
    )
    _exec = _counterfactual_executability(
        entry_price_cents=entry_price_cents,
        depth_cc=depth_cc,
        requested_contracts=_requested_contracts,
        market_state=market_state,
        side=side,
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
        "raw_probability": side_raw_probability,
        "calibrated_probability": p_selected,
        "gross_edge_cents": gross_edge_cents,
        "entry_fee_cents": entry_fee_cents,
        "exit_or_settlement_fee_cents": exit_fee_cents,
        # Per-side reserve actually charged in this side's EdgeBreakdown —
        # not the decision-level scalar (which is the selected side's value).
        "adverse_selection_haircut_cents": (
            _to_float(getattr(breakdown, "adverse_selection_reserve", None))
            or 0.0
        ) * 100.0,
        "model_uncertainty_haircut_cents": model_risk_cents,
        "expected_net_ev_cents": expected_net_ev_cents,
        "lower_confidence_bound_ev_cents": lcb,
        "required_edge_cents": required_edge_cents,
        "passed_edge_gate": bool(passed_edge),
        "gate_ev_cents": _gate_ev_cents,
        "enforced_edge_bound_cents": _enforced_bound_cents,
        # The admission lane is decision-level (a canary/bounded lane admits
        # the selected side below the full enforced-route bound) — stamping it
        # per row makes `selected=1 AND passed_edge_gate=0` interpretable
        # instead of contradictory.
        "decision_lane": indicators.get("decision_lane"),
        "admission_owner": indicators.get(f"{side}_admission_owner"),
        "threshold_source": indicators.get(f"{side}_threshold_source"),
        "legacy_risk_label": indicators.get(f"{side}_legacy_risk_label"),
        **_exec,
        **_evidence_health_cols(indicators, side),
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

    if side == "yes":
        side_raw_probability = _to_float(getattr(decision, "p_yes_raw", None))
    else:
        side_raw_probability = _to_float(indicators.get("p_no_raw"))
        if side_raw_probability is None:
            _p_yes_raw = _to_float(getattr(decision, "p_yes_raw", None))
            if _p_yes_raw is not None:
                side_raw_probability = 1.0 - _p_yes_raw

    _approved_cc = _to_float(getattr(decision, "approved_size_cc", None))
    _requested_contracts = (
        _approved_cc / 100.0
        if _approved_cc is not None and _approved_cc > 0
        else 1.0
    )
    _exec = _counterfactual_executability(
        entry_price_cents=entry_price_cents,
        depth_cc=depth_cc,
        requested_contracts=_requested_contracts,
        market_state=market_state,
        side=side,
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
        "raw_probability": side_raw_probability,
        "calibrated_probability": _to_float(getattr(decision, f"p_{side}_calibrated", None)),
        "gross_edge_cents": gross_edge_cents,
        "entry_fee_cents": entry_fee_cents,
        "exit_or_settlement_fee_cents": exit_fee_cents,
        "adverse_selection_haircut_cents": (
            _to_float(getattr(decision, "adverse_selection_reserve", None))
            or 0.0
        ) * 100.0,
        "model_uncertainty_haircut_cents": model_risk_cents,
        "expected_net_ev_cents": expected_net_ev_cents,
        "lower_confidence_bound_ev_cents": lcb,
        "required_edge_cents": required_edge_cents,
        "passed_edge_gate": passed_edge,
        "admission_owner": indicators.get(f"{side}_admission_owner"),
        "threshold_source": indicators.get(f"{side}_threshold_source"),
        "legacy_risk_label": indicators.get(f"{side}_legacy_risk_label"),
        **_exec,
        **_evidence_health_cols(indicators, side),
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
    """Estimate book age in milliseconds from market state's last update.

    ``last_book_update_wall_ts`` is wall-clock (comparable to ``decision_ts``);
    ``last_book_update_ts`` is monotonic and must only be compared to
    ``time.monotonic()``.  Prefer the wall sibling; fall back to the monotonic
    field so states without the wall marker still report an age.
    """
    if market_state is None:
        return None
    wall_update = getattr(market_state, "last_book_update_wall_ts", None)
    if wall_update:
        try:
            age_s = decision_ts - float(wall_update)
            if age_s < 0:
                return 0
            return int(age_s * 1000.0)
        except Exception:
            pass
    last_update = getattr(market_state, "last_book_update_ts", None)
    if last_update is None:
        return None
    try:
        age_s = time.monotonic() - float(last_update)
        if age_s < 0:
            return 0
        return int(age_s * 1000.0)
    except Exception:
        return None


def _rest_age_ms(market_state: Optional[Any], decision_ts: float) -> Optional[int]:
    """Estimate REST quote age in milliseconds from market state's last REST update.

    ``last_rest_quote_update_ts`` / ``last_rest_update_ts`` are monotonic
    clocks, so they are compared against ``time.monotonic()``, not
    ``decision_ts`` (wall-clock).
    """
    if market_state is None:
        return None
    last_update = getattr(market_state, "last_rest_quote_update_ts", None)
    if not last_update:
        last_update = getattr(market_state, "last_rest_update_ts", None)
    if not last_update:
        return None
    try:
        age_s = time.monotonic() - float(last_update)
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


def _candidate_id_from_decision_id(decision_id: Optional[str]) -> Optional[str]:
    """Recover the stable candidate identity from a decision id.

    Instrumented writers mint ``decision_id = "<candidate_id>:<route>"`` where
    route is the evaluation pass (``t``/``m``/``b``/``pre``).  Legacy ids have
    no route suffix and are their own candidate id.
    """
    if not decision_id:
        return None
    s = str(decision_id)
    if s.startswith("cand_") and ":" in s:
        head = s.rsplit(":", 1)[0]
        if head:
            return head
    return s


def _route_from_decision_id(decision_id: Optional[str]) -> Optional[str]:
    """Return the evaluation-route suffix of a decision id, if present."""
    if not decision_id:
        return None
    s = str(decision_id)
    if s.startswith("cand_") and ":" in s:
        return s.rsplit(":", 1)[1] or None
    return None


def _counterfactual_executability(
    *,
    entry_price_cents: Optional[int],
    depth_cc: float,
    requested_contracts: float,
    market_state: Optional[Any],
    side: str,
) -> Dict[str, Any]:
    """Classify whether the recorded decision-time quote could actually fill.

    Conservative rule: the counterfactual only earns P&L on the quantity that
    was visibly resting at the executable top-of-book price at decision time.
    ``depth_cc`` is in fixed-point units (100.0 == 1 contract).
    """
    available_contracts = max(0.0, float(depth_cc or 0.0) / 100.0)
    ask_attr = "best_ask_cents" if side == "yes" else "best_no_ask_cents"
    ask = (
        _to_int(getattr(market_state, ask_attr, None))
        if market_state is not None
        else None
    )
    if side == "yes":
        entry_source = "yes_ask" if ask else "no_bid_complement"
    else:
        entry_source = "no_ask" if ask else "yes_bid_complement"

    # Book-quality evidence only exists when a market_state snapshot was
    # attached at write time.  Absent snapshot != bad book: that is
    # UNKNOWN_EXECUTABILITY, and the fill assumption still respects the
    # recorded depth cap.  A *known-bad* book is the only stale-book marker.
    book_known_bad = (
        market_state is not None and not _book_is_executable(market_state)
    )

    if entry_price_cents is None:
        status = CF_NOT_EXECUTABLE_NO_PRICE
        assumed = 0.0
    elif book_known_bad:
        status = CF_NOT_EXECUTABLE_STALE_BOOK
        assumed = 0.0
    elif available_contracts <= 0.0:
        status = CF_NOT_EXECUTABLE_NO_DEPTH
        assumed = 0.0
    else:
        assumed = min(float(requested_contracts or 0.0), available_contracts)
        if assumed <= 0.0:
            status = CF_NOT_EXECUTABLE_NO_DEPTH
        elif assumed >= float(requested_contracts or 0.0) - 1e-9:
            # FULLY_EXECUTABLE requires a verified book; without a market-state
            # snapshot the quantity fits but book trust is unknown.
            status = (
                CF_FULLY_EXECUTABLE
                if market_state is not None
                else CF_UNKNOWN_EXECUTABILITY
            )
        else:
            status = CF_PARTIALLY_EXECUTABLE

    requested = float(requested_contracts or 0.0)
    fill_ratio = (assumed / requested) if requested > 0 else 0.0
    return {
        "requested_contracts": requested,
        "top_of_book_executable_contracts": available_contracts,
        "counterfactual_assumed_filled_contracts": assumed,
        "counterfactual_fill_ratio": fill_ratio,
        "counterfactual_full_fill_possible": 1 if assumed >= requested - 1e-9 and requested > 0 else 0,
        "counterfactual_execution_status": status,
        "counterfactual_entry_source": entry_source,
        "counterfactual_fee_model_version": COUNTERFACTUAL_FEE_MODEL_VERSION,
        "counterfactual_slippage_model_version": COUNTERFACTUAL_SLIPPAGE_MODEL_VERSION,
        "counterfactual_fill_model_version": COUNTERFACTUAL_FILL_MODEL_VERSION,
    }


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


def _policy_epoch() -> str:
    """Active policy epoch stamped on new decisions and settlements."""
    return os.environ.get("MERID_POLICY_EPOCH", "post_drawdown_2026-10-01")


def _evidence_health_cols(indicators: Mapping[str, Any], side: str) -> Dict[str, Any]:
    """Per-side evidence-health columns from the decision's indicators."""
    evh = indicators.get("evidence_health") or {}
    return {
        "evidence_state": indicators.get(f"{side}_evidence_state") or evh.get("evidence_state"),
        "evidence_age_s": _to_float(
            indicators.get(f"{side}_evidence_age_s", evh.get("evidence_age_seconds"))
        ),
        "evidence_action": indicators.get(f"{side}_evidence_action"),
        "evidence_binding_gate": indicators.get(f"{side}_evidence_binding_gate"),
        "evidence_artifact_mtime": _to_float(evh.get("artifact_mtime")),
        "evidence_last_refresh_success_at": _to_float(evh.get("last_refresh_success_at")),
    }


_UNTRUSTED_FILL_STATES = (
    "UNTRUSTED_LEGACY",
    "UNTRUSTED_RAW",
    "UNTRUSTED_SIDE_CONFLICT",
)


def _safety_pnl_source() -> str:
    """Which P&L feeds capital-protection counters: ``realized`` | ``thesis``.

    ``realized`` (default) is what the account actually booked — exit
    proceeds for exited quantity plus settlement for the residual.
    ``thesis`` is the legacy hold-to-settlement value (rollback switch).
    """
    v = os.environ.get("MERID_SAFETY_PNL_SOURCE", "realized").strip().lower()
    return v if v in ("realized", "thesis") else "realized"


def _fill_yes_delta_sign(side: Optional[str], action: Optional[str]) -> int:
    """+1 when a fill adds YES exposure (buy YES / sell NO), -1 when it adds
    NO exposure (buy NO / sell YES), 0 when undetermined."""
    s, a = (side or "").lower(), (action or "").lower()
    if s not in ("yes", "no") or a not in ("buy", "sell"):
        return 0
    return 1 if (s == "yes") == (a == "buy") else -1


def compute_capital_realized_pnl(
    *,
    fills: Any,
    target_fill_id: str,
    held_side: str,
    settle_value_yes_cents: Optional[float],
) -> Optional[Dict[str, Any]]:
    """Realized P&L of one entry lot, as the account actually booked it.

    ``fills`` are every trusted fill on the lot's ticker (dicts carrying
    ``execution_outcome_side``/``execution_action``/``execution_price_cents``
    in venue leg space, ``quantity_cc``, ``fee_cost`` dollars,
    ``created_time``).  Kalshi nets each ticker, so opposite-direction fills
    close held lots FIFO.  The target lot's realized P&L is

        exit proceeds (held-side price x allocated qty) - allocated exit fees
        + residual qty x held-side settlement value
        - entry price x qty - entry fee

    Returns None when the target lot is absent or its residual cannot be
    valued (no settlement yet).
    """
    held = (held_side or "").lower()
    if held not in ("yes", "no") or not target_fill_id:
        return None
    held_sign = 1 if held == "yes" else -1
    ordered = sorted(
        fills,
        key=lambda f: (str(f.get("created_time") or ""), str(f.get("fill_id") or "")),
    )
    lots: List[Dict[str, Any]] = []
    target: Optional[Dict[str, Any]] = None
    for f in ordered:
        side = (f.get("execution_outcome_side") or "").lower()
        sign = _fill_yes_delta_sign(side, f.get("execution_action"))
        px = f.get("execution_price_cents")
        if sign == 0 or px is None:
            continue
        qty = float(f.get("quantity_cc") or 100) / 100.0
        if qty <= 0:
            continue
        held_px = float(px) if side == held else 100.0 - float(px)
        fee_c = float(f.get("fee_cost") or 0.0) * 100.0
        if sign == held_sign:
            lot = {
                "qty": qty, "open": qty, "px": held_px, "fee": fee_c,
                "exit_qty": 0.0, "exit_value": 0.0, "exit_fee": 0.0,
            }
            lots.append(lot)
            if str(f.get("fill_id")) == str(target_fill_id):
                target = lot
            continue
        remaining = qty
        for lot in lots:
            if remaining <= 1e-9:
                break
            take = min(lot["open"], remaining)
            if take <= 1e-9:
                continue
            lot["open"] -= take
            remaining -= take
            lot["exit_qty"] += take
            lot["exit_value"] += take * held_px
            lot["exit_fee"] += fee_c * take / qty
    if target is None:
        return None
    residual = max(0.0, target["open"])
    settle_leg = 0.0
    if residual > 1e-9:
        if settle_value_yes_cents is None:
            return None
        sv = float(settle_value_yes_cents)
        settle_leg = sv if held == "yes" else 100.0 - sv
    pnl = (
        target["exit_value"]
        - target["exit_fee"]
        + residual * settle_leg
        - target["px"] * target["qty"]
        - target["fee"]
    )
    if target["exit_qty"] <= 1e-9:
        attribution = "held_to_settlement"
    elif residual <= 1e-9:
        attribution = "exited"
    else:
        attribution = "partial"
    return {
        "realized_pnl_cents": pnl,
        "exited_qty": target["exit_qty"],
        "held_qty": residual,
        "exit_vwap_cents": (
            target["exit_value"] / target["exit_qty"] if target["exit_qty"] > 1e-9 else None
        ),
        "attribution": attribution,
    }


def _add_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    """Add a column to a table if it does not already exist."""
    existing = {
        row[1]
        for row in conn.execute(f"PRAGMA table_info({table})")
    }
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

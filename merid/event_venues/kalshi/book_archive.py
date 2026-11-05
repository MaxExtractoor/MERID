"""Raw 15-minute orderbook archive — Phase A' execution-audit capture layer.

Persists every Kalshi ``orderbook_delta``-channel frame (snapshots AND deltas)
for the five crypto 15m series to a WAL SQLite archive, with explicit
coverage bookkeeping, so a later audit can answer:

    "Can we reconstruct the book we actually observed, in order, at a
    specified local receipt time — and explicitly identify intervals where
    we cannot?"

What this module deliberately records — and what it does not
------------------------------------------------------------
The archive captures the book **as locally observed**: raw wire payloads,
local receipt timestamps (utc + monotonic, captured before parsing), the
connection/subscription context that owns each sequence number, and every
discontinuity (seq gaps, buffer overflows, write failures, reconnects).

It does NOT claim to capture the exchange matching-engine state at order
arrival.  Downstream replay (Phase B') must therefore label its output
"estimated arrival-time execution": the observed book at receipt-time
``t`` bounds, but does not equal, the engine state the order actually
encountered.  Arrival-time inference needs the decision→submit→ack
latency distribution and clock-alignment uncertainty, documented
separately — never silently substitute observed-at-receipt for
arrival-at-engine.

Sequence semantics (per Kalshi docs): ``seq`` is scoped to the
subscription (``sid``), which lives inside a connection.  A sid can
multiplex several market tickers; a lost message on the sid cannot be
attributed to one ticker, so a seq gap degrades **every** ticker on that
sid.  Recovery requires a fresh snapshot — on a new subscription that
means a new seq stream; a mid-stream snapshot for the same ticker is
treated as an authoritative resync.

Tables
------
book_events       one row per received frame (and explicit ``__dropped__``
                  markers for buffered-but-unwritten events)
archive_sessions  one row per WS connection (session lifecycle)
archive_coverage  one row per (connection, sid, ticker) — the coverage
                  validity interval + gap ledger per book
archive_markets   discovered-market registry with contract fingerprints
archive_alerts    durable alert rows (gaps, overflows, write failures,
                  late discovery, missing snapshots)

The replay verifier (:class:`BookReplayVerifier`) reads only ``book_events``
+ ``archive_coverage``; everything else is observability metadata.
"""

from __future__ import annotations

import json
import os
import queue
import sqlite3
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.book_archive")

PARSER_VERSION = "book_archive_v1"

# Message types we archive verbatim.  Non-book frames on the socket
# (subscribed/unsubscribed/error/etc.) are stored too so the subscription
# lifecycle is durably reconstructible.
_BOOK_TYPES = frozenset({"orderbook_snapshot", "orderbook_delta"})

# Synthetic marker rows.  A ``__dropped__`` row carries the real envelope
# metadata (sid/seq/ticker/type) with an empty payload: it preserves the
# exact position where a captured event could not be persisted, so replay
# sees the discontinuity instead of silently reconstructing across it.
MSG_DROPPED = "__dropped__"
MSG_UNPARSED = "__unparsed__"

# Coverage states (per connection+sid+ticker row in archive_coverage).
COV_AWAITING_SNAPSHOT = "awaiting_snapshot"   # subscribed, no snapshot yet
COV_COVERING = "covering"                     # snapshot seen, seq contiguous
COV_GAPPED = "gapped"                         # seq gap / dropped event —
                                            # book untrusted until resync
COV_CLOSED = "closed"                         # window ended or session ended

# Alert codes persisted to archive_alerts (and echoed to stderr/heartbeat).
ALERT_SEQ_GAP = "seq_gap"
ALERT_BUFFER_OVERFLOW = "buffer_overflow"
ALERT_DB_WRITE_ERROR = "db_write_error"
ALERT_RECONNECT = "reconnect"
ALERT_COLLECTOR_START = "collector_start"
ALERT_LATE_DISCOVERY = "late_discovery"
ALERT_MISSING_SNAPSHOT = "missing_snapshot"
ALERT_UNPARSED_MESSAGE = "unparsed_message"
ALERT_SESSION_END = "session_end"

SCHEMA = """
CREATE TABLE IF NOT EXISTS book_events(
  archive_event_id        TEXT PRIMARY KEY,
  collector_instance_id   TEXT NOT NULL,
  connection_id           TEXT NOT NULL,
  subscription_id         INTEGER,
  market_ticker           TEXT,
  message_type            TEXT NOT NULL,
  sequence_number         INTEGER,
  exchange_timestamp_raw  TEXT,
  received_at_utc_ns      INTEGER NOT NULL,
  received_at_monotonic_ns INTEGER NOT NULL,
  raw_payload             TEXT NOT NULL,
  parser_version          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_book_events_sid_seq
  ON book_events(connection_id, subscription_id, sequence_number);
CREATE INDEX IF NOT EXISTS idx_book_events_ticker_recv
  ON book_events(market_ticker, received_at_utc_ns);
CREATE INDEX IF NOT EXISTS idx_book_events_recv
  ON book_events(received_at_utc_ns);

CREATE TABLE IF NOT EXISTS archive_sessions(
  connection_id          TEXT PRIMARY KEY,
  collector_instance_id  TEXT NOT NULL,
  ws_url                 TEXT,
  connect_utc_ns         INTEGER NOT NULL,
  disconnect_utc_ns      INTEGER,
  disconnect_reason      TEXT,
  subscription_map       TEXT NOT NULL DEFAULT '{}',  -- sid -> [tickers]
  msgs_received          INTEGER NOT NULL DEFAULT 0,
  parser_version         TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS archive_coverage(
  coverage_id             TEXT PRIMARY KEY,  -- {connection_id}:{sid}:{ticker}
  connection_id           TEXT NOT NULL,
  subscription_id         INTEGER NOT NULL,
  market_ticker           TEXT NOT NULL,
  market_open_ts          REAL,
  market_close_ts         REAL,
  discovered_at_utc_ns    INTEGER,
  discovery_late          INTEGER NOT NULL DEFAULT 0,
  subscribed_utc_ns       INTEGER,
  first_snapshot_seq      INTEGER,
  first_snapshot_recv_utc_ns INTEGER,
  last_seq                INTEGER,
  last_event_recv_utc_ns  INTEGER,
  event_count             INTEGER NOT NULL DEFAULT 0,
  delta_count             INTEGER NOT NULL DEFAULT 0,
  snapshot_count          INTEGER NOT NULL DEFAULT 0,
  pre_snapshot_deltas     INTEGER NOT NULL DEFAULT 0,
  gap_count               INTEGER NOT NULL DEFAULT 0,
  duplicate_seq_count     INTEGER NOT NULL DEFAULT 0,
  gaps                    TEXT NOT NULL DEFAULT '[]',
  valid_from_utc_ns       INTEGER,           -- first snapshot receipt
  valid_to_utc_ns         INTEGER,           -- last contiguous event receipt
  state                   TEXT NOT NULL,
  state_detail            TEXT,
  updated_utc_ns          INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_archive_coverage_ticker
  ON archive_coverage(market_ticker, state);

CREATE TABLE IF NOT EXISTS archive_markets(
  ticker                   TEXT PRIMARY KEY,
  series                   TEXT,
  asset                    TEXT,
  status                   TEXT,
  open_ts                  REAL,
  close_ts                 REAL,
  expiration_ts            REAL,
  contract_semantics_hash  TEXT,
  execution_metadata_version TEXT,
  discovered_at_utc_ns     INTEGER NOT NULL,
  last_seen_utc_ns         INTEGER NOT NULL,
  raw_market               TEXT
);

CREATE TABLE IF NOT EXISTS archive_alerts(
  alert_id       INTEGER PRIMARY KEY AUTOINCREMENT,
  ts_utc_ns      INTEGER NOT NULL,
  severity       TEXT NOT NULL,
  code           TEXT NOT NULL,
  connection_id  TEXT,
  subscription_id INTEGER,
  market_ticker  TEXT,
  detail         TEXT
);
CREATE INDEX IF NOT EXISTS idx_archive_alerts_ts ON archive_alerts(ts_utc_ns);
"""

# ─────────────────────────────────────────────────────────────────────────────
# Event envelope
# ─────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EventEnvelope:
    """One archived frame: raw payload + indexing fields + receipt stamps."""

    archive_event_id: str
    collector_instance_id: str
    connection_id: str
    subscription_id: Optional[int]
    market_ticker: Optional[str]
    message_type: str
    sequence_number: Optional[int]
    exchange_timestamp_raw: Optional[str]
    received_at_utc_ns: int
    received_at_monotonic_ns: int
    raw_payload: str
    parser_version: str = PARSER_VERSION

    def db_row(self) -> Tuple:
        return (
            self.archive_event_id,
            self.collector_instance_id,
            self.connection_id,
            self.subscription_id,
            self.market_ticker,
            self.message_type,
            self.sequence_number,
            self.exchange_timestamp_raw,
            self.received_at_utc_ns,
            self.received_at_monotonic_ns,
            self.raw_payload,
            self.parser_version,
        )

    @staticmethod
    def dropped(
        *,
        collector_instance_id: str,
        connection_id: str,
        subscription_id: Optional[int],
        market_ticker: Optional[str],
        dropped_type: str,
        sequence_number: Optional[int],
        received_at_utc_ns: int,
        received_at_monotonic_ns: int,
        drop_ordinal: int,
        reason: str,
    ) -> "EventEnvelope":
        """Marker preserving where a captured event failed to persist."""
        return EventEnvelope(
            archive_event_id=(
                f"{collector_instance_id}:{connection_id}:dropped:{drop_ordinal}"
            ),
            collector_instance_id=collector_instance_id,
            connection_id=connection_id,
            subscription_id=subscription_id,
            market_ticker=market_ticker,
            message_type=MSG_DROPPED,
            sequence_number=sequence_number,
            exchange_timestamp_raw=None,
            received_at_utc_ns=received_at_utc_ns,
            received_at_monotonic_ns=received_at_monotonic_ns,
            raw_payload=json.dumps(
                {"dropped_type": dropped_type, "reason": reason},
                separators=(",", ":"),
            ),
        )


def envelope_from_frame(
    raw_text: str,
    *,
    received_at_utc_ns: int,
    received_at_monotonic_ns: int,
    connection_id: str,
    collector_instance_id: str,
    recv_ordinal: int,
) -> EventEnvelope:
    """Index a raw wire frame without interpreting the payload.

    Only the fields needed for storage ordering and coverage bookkeeping are
    extracted; the payload is stored verbatim so future parsers are not
    constrained by today's understanding of the message shape.
    """
    subscription_id: Optional[int] = None
    market_ticker: Optional[str] = None
    message_type: Optional[str] = None
    sequence_number: Optional[int] = None
    exchange_timestamp_raw: Optional[str] = None

    try:
        data = json.loads(raw_text)
    except (json.JSONDecodeError, TypeError):
        data = None

    if isinstance(data, dict):
        message_type = data.get("type") or MSG_UNPARSED
        sid = data.get("sid")
        if isinstance(sid, int) and not isinstance(sid, bool):
            subscription_id = sid
        seq = data.get("seq")
        if isinstance(seq, int) and not isinstance(seq, bool):
            sequence_number = seq
        msg = data.get("msg")
        if isinstance(msg, dict):
            market_ticker = msg.get("market_ticker") or msg.get("ticker")
            # Exchange timestamps: retain only where the venue provides them.
            if msg.get("ts") is not None:
                exchange_timestamp_raw = str(msg["ts"])
            elif msg.get("timestamp") is not None:
                exchange_timestamp_raw = str(msg["timestamp"])
            # 'subscribed'/'unsubscribed' confirmations carry sid inside msg.
            if subscription_id is None:
                msid = msg.get("sid")
                if isinstance(msid, int) and not isinstance(msid, bool):
                    subscription_id = msid

    return EventEnvelope(
        archive_event_id=f"{collector_instance_id}:{connection_id}:{recv_ordinal}",
        collector_instance_id=collector_instance_id,
        connection_id=connection_id,
        subscription_id=subscription_id,
        market_ticker=market_ticker,
        message_type=message_type or MSG_UNPARSED,
        sequence_number=sequence_number,
        exchange_timestamp_raw=exchange_timestamp_raw,
        received_at_utc_ns=received_at_utc_ns,
        received_at_monotonic_ns=received_at_monotonic_ns,
        raw_payload=raw_text,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Coverage tracking (pure state machine — no I/O, fully testable)
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class CoverageRecord:
    """Mutable coverage state for one (connection, sid, ticker)."""

    coverage_id: str
    connection_id: str
    subscription_id: int
    market_ticker: str
    market_open_ts: Optional[float] = None
    market_close_ts: Optional[float] = None
    discovered_at_utc_ns: Optional[int] = None
    discovery_late: bool = False
    subscribed_utc_ns: Optional[int] = None
    first_snapshot_seq: Optional[int] = None
    first_snapshot_recv_utc_ns: Optional[int] = None
    last_seq: Optional[int] = None
    last_event_recv_utc_ns: Optional[int] = None
    event_count: int = 0
    delta_count: int = 0
    snapshot_count: int = 0
    pre_snapshot_deltas: int = 0
    gap_count: int = 0
    duplicate_seq_count: int = 0
    gaps: List[Dict[str, Any]] = field(default_factory=list)
    valid_from_utc_ns: Optional[int] = None
    valid_to_utc_ns: Optional[int] = None
    state: str = COV_AWAITING_SNAPSHOT
    state_detail: Optional[str] = None
    updated_utc_ns: int = 0

    def db_row(self) -> Dict[str, Any]:
        return {
            "coverage_id": self.coverage_id,
            "connection_id": self.connection_id,
            "subscription_id": self.subscription_id,
            "market_ticker": self.market_ticker,
            "market_open_ts": self.market_open_ts,
            "market_close_ts": self.market_close_ts,
            "discovered_at_utc_ns": self.discovered_at_utc_ns,
            "discovery_late": 1 if self.discovery_late else 0,
            "subscribed_utc_ns": self.subscribed_utc_ns,
            "first_snapshot_seq": self.first_snapshot_seq,
            "first_snapshot_recv_utc_ns": self.first_snapshot_recv_utc_ns,
            "last_seq": self.last_seq,
            "last_event_recv_utc_ns": self.last_event_recv_utc_ns,
            "event_count": self.event_count,
            "delta_count": self.delta_count,
            "snapshot_count": self.snapshot_count,
            "pre_snapshot_deltas": self.pre_snapshot_deltas,
            "gap_count": self.gap_count,
            "duplicate_seq_count": self.duplicate_seq_count,
            "gaps": json.dumps(self.gaps, separators=(",", ":")),
            "valid_from_utc_ns": self.valid_from_utc_ns,
            "valid_to_utc_ns": self.valid_to_utc_ns,
            "state": self.state,
            "state_detail": self.state_detail,
            "updated_utc_ns": self.updated_utc_ns,
        }


@dataclass(frozen=True)
class AlertRecord:
    severity: str
    code: str
    detail: str
    connection_id: Optional[str] = None
    subscription_id: Optional[int] = None
    market_ticker: Optional[str] = None
    ts_utc_ns: int = 0


class CoverageTracker:
    """Sequence-continuity + coverage state per (connection, sid, ticker).

    Pure bookkeeping: receives :class:`EventEnvelope`s in receive order and
    produces coverage mutations + alerts.  No I/O — the writer thread and the
    unit tests drive the same logic.
    """

    def __init__(self) -> None:
        # (connection_id, sid, ticker) -> CoverageRecord
        self.records: Dict[Tuple[str, int, str], CoverageRecord] = {}
        # (connection_id, sid) -> last contiguous seq observed
        self._last_seq: Dict[Tuple[str, int], int] = {}
        # (connection_id, sid) -> True once a gap broke this stream
        self._sid_gapped: Dict[Tuple[str, int], bool] = {}
        # (connection_id, sid) -> declared ticker set
        self._sid_tickers: Dict[Tuple[str, int], set] = {}
        self.alerts: List[AlertRecord] = []

    @staticmethod
    def _cid(connection_id: str, sid: int, ticker: str) -> str:
        return f"{connection_id}:{sid}:{ticker}"

    def _alert(
        self,
        code: str,
        *,
        severity: str = "error",
        detail: str = "",
        connection_id: Optional[str] = None,
        sid: Optional[int] = None,
        ticker: Optional[str] = None,
        ts_utc_ns: int = 0,
    ) -> AlertRecord:
        rec = AlertRecord(
            severity=severity,
            code=code,
            detail=detail,
            connection_id=connection_id,
            subscription_id=sid,
            market_ticker=ticker,
            ts_utc_ns=ts_utc_ns,
        )
        self.alerts.append(rec)
        return rec

    def note_subscription(
        self,
        connection_id: str,
        sid: int,
        tickers: Iterable[str],
        *,
        ts_utc_ns: int,
        market_meta: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> List[CoverageRecord]:
        """Register (sid -> tickers) and create AWAITING_SNAPSHOT rows.

        ``market_meta`` optionally supplies {ticker: {open_ts, close_ts,
        discovered_at_utc_ns, discovery_late}} from the discovery loop.
        """
        meta = market_meta or {}
        key = (connection_id, sid)
        declared = self._sid_tickers.setdefault(key, set())
        out: List[CoverageRecord] = []
        for ticker in tickers:
            declared.add(ticker)
            rkey = (connection_id, sid, ticker)
            if rkey in self.records:
                continue
            m = meta.get(ticker, {})
            rec = CoverageRecord(
                coverage_id=self._cid(connection_id, sid, ticker),
                connection_id=connection_id,
                subscription_id=sid,
                market_ticker=ticker,
                market_open_ts=m.get("open_ts"),
                market_close_ts=m.get("close_ts"),
                discovered_at_utc_ns=m.get("discovered_at_utc_ns"),
                discovery_late=bool(m.get("discovery_late")),
                subscribed_utc_ns=ts_utc_ns,
                updated_utc_ns=ts_utc_ns,
            )
            self.records[rkey] = rec
            out.append(rec)
            if rec.discovery_late:
                self._alert(
                    ALERT_LATE_DISCOVERY,
                    severity="warning",
                    detail=(
                        f"ticker={ticker} subscribed after market open "
                        f"(open_ts={m.get('open_ts')}); window cannot be "
                        "fully covered"
                    ),
                    connection_id=connection_id,
                    sid=sid,
                    ticker=ticker,
                    ts_utc_ns=ts_utc_ns,
                )
        return out

    def _note_seq(
        self,
        connection_id: str,
        sid: int,
        seq: int,
        ts_utc_ns: int,
        *,
        ticker: Optional[str] = None,
    ) -> Tuple[str, List[CoverageRecord]]:
        """Advance sid-level sequence continuity for any seq-bearing frame.

        The sequence space belongs to the (connection, sid) stream, not to a
        ticker — book deltas, snapshots, and control acknowledgments all
        consume it.  Returns (kind, touched_records) where kind is 'first' |
        'ok' | 'duplicate' | 'gapped'.  A forward jump degrades every ticker
        on the sid because the missing frame's owner is unknowable.
        """
        key = (connection_id, sid)
        last = self._last_seq.get(key)
        if last is None:
            self._last_seq[key] = seq
            return "first", []
        if seq == last + 1:
            self._last_seq[key] = seq
            return "ok", []
        if seq <= last:
            rec = (
                self.records.get((connection_id, sid, ticker))
                if ticker
                else None
            )
            if rec is not None:
                rec.duplicate_seq_count += 1
                rec.updated_utc_ns = ts_utc_ns
                return "duplicate", [rec]
            return "duplicate", []
        touched = self._gap_sid(
            connection_id,
            sid,
            expected_seq=last + 1,
            got_seq=seq,
            reason="seq_discontinuity",
            ts_utc_ns=ts_utc_ns,
            env_ticker=ticker,
        )
        self._last_seq[key] = seq
        return "gapped", touched

    def _gap_sid(
        self,
        connection_id: str,
        sid: int,
        *,
        expected_seq: Optional[int],
        got_seq: Optional[int],
        reason: str,
        ts_utc_ns: int,
        env_ticker: Optional[str] = None,
    ) -> List[CoverageRecord]:
        """Mark every ticker on (connection, sid) GAPPED.

        A lost message on a multiplexed sid cannot be attributed to a single
        ticker, so all coverage on the stream degrades together.
        """
        if self._sid_gapped.get((connection_id, sid)):
            return []
        self._sid_gapped[(connection_id, sid)] = True
        gap = {
            "expected_seq": expected_seq,
            "got_seq": got_seq,
            "reason": reason,
            "detected_utc_ns": ts_utc_ns,
            "detected_on_ticker": env_ticker,
        }
        touched: List[CoverageRecord] = []
        for (cid, s, ticker), rec in self.records.items():
            if cid != connection_id or s != sid:
                continue
            if rec.state in (COV_CLOSED,):
                continue
            rec.gap_count += 1
            rec.gaps.append(gap)
            rec.state = COV_GAPPED
            rec.state_detail = reason
            # The valid interval ends at the last contiguous event.
            rec.updated_utc_ns = ts_utc_ns
            touched.append(rec)
        self._alert(
            ALERT_SEQ_GAP,
            detail=(
                f"sid={sid} expected_seq={expected_seq} got_seq={got_seq} "
                f"reason={reason}; coverage degraded for "
                f"{len(touched)} ticker(s)"
            ),
            connection_id=connection_id,
            sid=sid,
            ticker=env_ticker,
            ts_utc_ns=ts_utc_ns,
        )
        return touched

    def note_event(self, env: EventEnvelope) -> List[CoverageRecord]:
        """Fold one received envelope into coverage state.

        Returns the coverage rows mutated (for the writer to persist).
        """
        touched: List[CoverageRecord] = []
        sid = env.subscription_id
        conn = env.connection_id
        ts = env.received_at_utc_ns

        if env.message_type == MSG_DROPPED:
            # An event we received but could not persist.  If it carried a
            # seq, the stored stream now jumps it at replay; mark sid gapped.
            if sid is not None:
                touched = self._gap_sid(
                    conn,
                    sid,
                    expected_seq=env.sequence_number,
                    got_seq=None,
                    reason=env.raw_payload[:200],
                    ts_utc_ns=ts,
                    env_ticker=env.market_ticker,
                )
            return touched

        if env.message_type == MSG_UNPARSED:
            self._alert(
                ALERT_UNPARSED_MESSAGE,
                severity="warning",
                detail=f"unparsed frame on {conn}",
                connection_id=conn,
                sid=sid,
                ts_utc_ns=ts,
            )
            return touched

        if env.message_type not in _BOOK_TYPES:
            # Lifecycle/control frames (subscribed, ok, error, unsubscribed)
            # are stored, not book-tracked — but a seq-bearing control frame
            # still occupies the sid's sequence space, so it must advance
            # continuity.  Otherwise every update_subscription ack surfaces
            # as a false seq gap on all of the sid's tickers.
            if sid is not None and env.sequence_number is not None:
                _, touched = self._note_seq(conn, sid, env.sequence_number, ts)
            return touched

        if sid is None:
            return touched

        key = (conn, sid)
        seq = env.sequence_number
        ticker = env.market_ticker

        # ── sid-level sequence continuity ────────────────────────────────
        if seq is not None:
            kind, seq_touched = self._note_seq(conn, sid, seq, ts,
                                               ticker=ticker)
            for r in seq_touched:
                if r not in touched:
                    touched.append(r)
            if kind == "duplicate":
                # Duplicate / out-of-order delivery: counted, not applied
                # (replay skips seq <= last applied too).
                return touched

        if ticker is None:
            return touched

        rkey = (conn, sid, ticker)
        rec = self.records.get(rkey)
        if rec is None:
            # Traffic for a ticker we never declared — a re-subscribe folded
            # this ticker into the sid, or discovery missed it.  Register it
            # so its coverage is still accounted for.
            rec = CoverageRecord(
                coverage_id=self._cid(conn, sid, ticker),
                connection_id=conn,
                subscription_id=sid,
                market_ticker=ticker,
                subscribed_utc_ns=ts,
                updated_utc_ns=ts,
            )
            self.records[rkey] = rec
            self._sid_tickers.setdefault(key, set()).add(ticker)

        if rec.state == COV_CLOSED:
            return touched

        rec.event_count += 1
        rec.last_seq = seq if seq is not None else rec.last_seq
        rec.last_event_recv_utc_ns = ts

        if env.message_type == "orderbook_snapshot":
            rec.snapshot_count += 1
            # A snapshot is authoritative: it establishes (or re-establishes)
            # a valid book from this point, even after a gap on the same sid.
            if rec.first_snapshot_seq is None:
                rec.first_snapshot_seq = seq
                rec.first_snapshot_recv_utc_ns = ts
                rec.valid_from_utc_ns = ts
            rec.state = COV_COVERING
            rec.state_detail = None
            rec.valid_to_utc_ns = ts
            # If this sid had gapped, the resync only heals THIS ticker if a
            # snapshot truly resets its book — it does; other tickers stay
            # gapped.  The sid-level flag clears only when every ticker has
            # resynced, which in practice means a new session.
            if self._sid_gapped.get(key) and all(
                r.snapshot_count > 0 or r.state == COV_CLOSED
                for (c, s, _), r in self.records.items()
                if c == conn and s == sid
            ):
                self._sid_gapped[key] = False
        else:  # orderbook_delta
            rec.delta_count += 1
            if rec.state == COV_AWAITING_SNAPSHOT:
                rec.pre_snapshot_deltas += 1
                self._alert(
                    ALERT_MISSING_SNAPSHOT,
                    severity="warning",
                    detail=(
                        f"delta before any snapshot ticker={ticker} "
                        f"seq={seq}"
                    ),
                    connection_id=conn,
                    sid=sid,
                    ticker=ticker,
                    ts_utc_ns=ts,
                )
            if rec.state == COV_COVERING:
                rec.valid_to_utc_ns = ts

        rec.updated_utc_ns = ts
        if rec not in touched:
            touched.append(rec)
        return touched

    def note_session_end(
        self, connection_id: str, *, reason: str, ts_utc_ns: int
    ) -> List[CoverageRecord]:
        """Close all coverage on a connection; valid intervals end here."""
        touched: List[CoverageRecord] = []
        for (cid, _, _), rec in self.records.items():
            if cid == connection_id and rec.state != COV_CLOSED:
                rec.state = COV_CLOSED
                rec.state_detail = reason
                rec.updated_utc_ns = ts_utc_ns
                touched.append(rec)
        self._alert(
            ALERT_SESSION_END,
            severity="info",
            detail=reason,
            connection_id=connection_id,
            ts_utc_ns=ts_utc_ns,
        )
        return touched

    def note_market_closed(
        self, ticker: str, *, reason: str, ts_utc_ns: int
    ) -> List[CoverageRecord]:
        """Close coverage for a ticker past its close+grace boundary."""
        touched = []
        for (_, _, t), rec in self.records.items():
            if t == ticker and rec.state != COV_CLOSED:
                rec.state = COV_CLOSED
                rec.state_detail = reason
                rec.updated_utc_ns = ts_utc_ns
                touched.append(rec)
        return touched


# ─────────────────────────────────────────────────────────────────────────────
# Archive DB (writer + reader)
# ─────────────────────────────────────────────────────────────────────────────

_EVENT_INSERT = (
    "INSERT INTO book_events(archive_event_id, collector_instance_id,"
    " connection_id, subscription_id, market_ticker, message_type,"
    " sequence_number, exchange_timestamp_raw, received_at_utc_ns,"
    " received_at_monotonic_ns, raw_payload, parser_version)"
    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)"
)

_COV_COLS = [
    "coverage_id", "connection_id", "subscription_id", "market_ticker",
    "market_open_ts", "market_close_ts", "discovered_at_utc_ns",
    "discovery_late", "subscribed_utc_ns", "first_snapshot_seq",
    "first_snapshot_recv_utc_ns", "last_seq", "last_event_recv_utc_ns",
    "event_count", "delta_count", "snapshot_count", "pre_snapshot_deltas",
    "gap_count", "duplicate_seq_count", "gaps", "valid_from_utc_ns",
    "valid_to_utc_ns", "state", "state_detail", "updated_utc_ns",
]
_COV_UPSERT = (
    f"INSERT INTO archive_coverage({','.join(_COV_COLS)})"
    f" VALUES({','.join('?' * len(_COV_COLS))})"
    " ON CONFLICT(coverage_id) DO UPDATE SET "
    + ", ".join(f"{c}=excluded.{c}" for c in _COV_COLS[4:])
)

_MARKET_COLS = [
    "ticker", "series", "asset", "status", "open_ts", "close_ts",
    "expiration_ts", "contract_semantics_hash",
    "execution_metadata_version", "discovered_at_utc_ns",
    "last_seen_utc_ns", "raw_market",
]
_MARKET_UPSERT = (
    f"INSERT INTO archive_markets({','.join(_MARKET_COLS)})"
    f" VALUES({','.join('?' * len(_MARKET_COLS))})"
    " ON CONFLICT(ticker) DO UPDATE SET "
    + ", ".join(
        f"{c}=excluded.{c}"
        for c in ("status", "last_seen_utc_ns", "raw_market")
    )
)
_ALERT_INSERT = (
    "INSERT INTO archive_alerts(ts_utc_ns, severity, code,"
    " connection_id, subscription_id, market_ticker, detail)"
    " VALUES(?,?,?,?,?,?,?)"
)


class BookArchiveDB:
    """SQLite store for the archive.  Single writer thread expected."""

    def __init__(self, path: str):
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA busy_timeout=5000")
        # Capture-tuned: keep index pages resident and checkpoint manually —
        # an 80MB auto-checkpoint mid-flood stalled the writer ~38s.
        self.conn.execute("PRAGMA cache_size=-1048576")
        self.conn.execute("PRAGMA temp_store=MEMORY")
        self.conn.execute("PRAGMA mmap_size=536870912")
        self.conn.execute("PRAGMA wal_autocheckpoint=0")
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self.write_errors: int = 0
        self.rows_written: int = 0

    # ── writers ────────────────────────────────────────────────────────
    def insert_events(self, envelopes: List[EventEnvelope]) -> None:
        """Atomically persist a batch; raises on failure (caller degrades)."""
        try:
            rows = [e.db_row() for e in envelopes]
            # Sort by (market_ticker, received_at_utc_ns): index inserts then
            # append at each ticker's right edge instead of descending cold
            # B-tree paths per interleaved row — dominant cost at flood
            # rates.  Ticker is NULL on control frames/markers — a bare
            # (None, str) key comparison raises TypeError, so untickered
            # rows sort first.
            rows.sort(key=lambda r: (r[4] or "", r[8]))
            self.conn.execute("BEGIN IMMEDIATE")
            self.conn.executemany(_EVENT_INSERT, rows)
            self.conn.execute("COMMIT")
            self.rows_written += len(rows)
        except Exception:
            try:
                self.conn.execute("ROLLBACK")
            except Exception:
                pass
            self.write_errors += 1
            raise

    def upsert_coverage(self, records: List[CoverageRecord]) -> None:
        if not records:
            return
        rows = [tuple(r.db_row()[c] for c in _COV_COLS) for r in records]
        self.conn.executemany(_COV_UPSERT, rows)
        self.conn.commit()

    def upsert_market(self, row: Dict[str, Any]) -> None:
        self.conn.execute(
            _MARKET_UPSERT, tuple(row.get(c) for c in _MARKET_COLS)
        )
        self.conn.commit()

    def upsert_markets(self, rows: List[Dict[str, Any]]) -> None:
        """Batch market registry writes in ONE commit — a discovery pass can
        carry ~500 markets, and per-row commits stall the writer loop."""
        if not rows:
            return
        self.conn.executemany(
            _MARKET_UPSERT,
            [tuple(r.get(c) for c in _MARKET_COLS) for r in rows],
        )
        self.conn.commit()

    def insert_alerts(self, alerts: List[AlertRecord]) -> None:
        """Batch alert writes in ONE commit — overflow storms can emit
        thousands of alerts per iteration."""
        if not alerts:
            return
        self.conn.executemany(
            _ALERT_INSERT,
            [
                (
                    a.ts_utc_ns or time.time_ns(),
                    a.severity,
                    a.code,
                    a.connection_id,
                    a.subscription_id,
                    a.market_ticker,
                    a.detail,
                )
                for a in alerts
            ],
        )
        self.conn.commit()

    def insert_session(
        self,
        *,
        connection_id: str,
        collector_instance_id: str,
        ws_url: str,
        connect_utc_ns: int,
    ) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO archive_sessions(connection_id,"
            " collector_instance_id, ws_url, connect_utc_ns, parser_version)"
            " VALUES(?,?,?,?,?)",
            (connection_id, collector_instance_id, ws_url, connect_utc_ns,
             PARSER_VERSION),
        )
        self.conn.commit()

    def close_session(
        self,
        connection_id: str,
        *,
        disconnect_utc_ns: int,
        reason: str,
        msgs_received: int,
        subscription_map: Dict[int, List[str]],
    ) -> None:
        self.conn.execute(
            "UPDATE archive_sessions SET disconnect_utc_ns=?,"
            " disconnect_reason=?, msgs_received=?, subscription_map=?"
            " WHERE connection_id=?",
            (
                disconnect_utc_ns,
                reason,
                msgs_received,
                json.dumps(
                    {str(k): sorted(v) for k, v in subscription_map.items()}
                ),
                connection_id,
            ),
        )
        self.conn.commit()

    def close_orphaned_sessions(self, live_connection_ids: Iterable[str]) -> int:
        """Mark sessions from dead collectors as ended at their last event."""
        live = set(live_connection_ids)
        rows = self.conn.execute(
            "SELECT connection_id FROM archive_sessions"
            " WHERE disconnect_utc_ns IS NULL"
        ).fetchall()
        n = 0
        for (cid,) in rows:
            if cid in live:
                continue
            # Cheap path: coverage.last_event_recv_utc_ns already tracks the
            # last tracked event per (conn,sid,ticker) — a book_events scan
            # per orphan connection takes minutes on a large archive.
            last = self.conn.execute(
                "SELECT MAX(last_event_recv_utc_ns) FROM archive_coverage"
                " WHERE connection_id=?",
                (cid,),
            ).fetchone()[0]
            if last is None:
                last = self.conn.execute(
                    "SELECT MAX(received_at_utc_ns) FROM book_events"
                    " WHERE connection_id=?",
                    (cid,),
                ).fetchone()[0]
            if last is None:
                last = self.conn.execute(
                    "SELECT connect_utc_ns FROM archive_sessions"
                    " WHERE connection_id=?",
                    (cid,),
                ).fetchone()[0]
            self.conn.execute(
                "UPDATE archive_sessions SET disconnect_utc_ns=?,"
                " disconnect_reason=? WHERE connection_id=?",
                (last, "collector_died_or_restarted", cid),
            )
            n += 1
        if n:
            self.conn.commit()
        return n

    def insert_alert(self, alert: AlertRecord) -> None:
        self.conn.execute(
            "INSERT INTO archive_alerts(ts_utc_ns, severity, code,"
            " connection_id, subscription_id, market_ticker, detail)"
            " VALUES(?,?,?,?,?,?,?)",
            (
                alert.ts_utc_ns or time.time_ns(),
                alert.severity,
                alert.code,
                alert.connection_id,
                alert.subscription_id,
                alert.market_ticker,
                alert.detail,
            ),
        )
        self.conn.commit()

    # ── readers ────────────────────────────────────────────────────────
    def coverage_for(self, ticker: str) -> List[sqlite3.Row]:
        self.conn.row_factory = sqlite3.Row
        try:
            return self.conn.execute(
                "SELECT * FROM archive_coverage WHERE market_ticker=?"
                " ORDER BY subscribed_utc_ns",
                (ticker,),
            ).fetchall()
        finally:
            self.conn.row_factory = None

    def events_for_sid(
        self, connection_id: str, sid: int
    ) -> List[sqlite3.Row]:
        self.conn.row_factory = sqlite3.Row
        try:
            return self.conn.execute(
                "SELECT * FROM book_events WHERE connection_id=?"
                " AND (subscription_id=? OR subscription_id IS NULL)"
                " ORDER BY rowid",
                (connection_id, sid),
            ).fetchall()
        finally:
            self.conn.row_factory = None

    def prune(self, older_than_utc_ns: int) -> int:
        cur = self.conn.execute(
            "DELETE FROM book_events WHERE received_at_utc_ns < ?",
            (older_than_utc_ns,),
        )
        n = cur.rowcount
        self.conn.commit()
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return n

    def stats(self, con=None) -> Dict[str, Any]:
        # NOTE: pass a dedicated read-only connection from the caller when
        # possible — queries on self.conn serialize behind in-flight writer
        # transactions.  Only rowid-ordered probes are O(1); received_at
        # MIN/MAX cannot use the (ticker, received) composite index, so
        # first/last receipt times come from the rows at MIN/MAX rowid.
        c = con or self.conn
        row = c.execute(
            "SELECT MAX(rowid) FROM book_events"
        ).fetchone()
        first_ts = c.execute(
            "SELECT received_at_utc_ns FROM book_events"
            " ORDER BY rowid ASC LIMIT 1"
        ).fetchone()
        last_ts = c.execute(
            "SELECT received_at_utc_ns FROM book_events"
            " ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        cov = c.execute(
            "SELECT state, COUNT(*) FROM archive_coverage GROUP BY state"
        ).fetchall()
        return {
            # MAX(rowid) approximates total rows; rows_written is exact for
            # this process.  No full-table COUNT(*) — it stalls the writer.
            "events": row[0],
            "first_event_utc_ns": first_ts[0] if first_ts else None,
            "last_event_utc_ns": last_ts[0] if last_ts else None,
            "coverage_by_state": {r[0]: r[1] for r in cov},
            "write_errors": self.write_errors,
            "rows_written": self.rows_written,
        }

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Replay verifier
# ─────────────────────────────────────────────────────────────────────────────

# Reconstruction statuses.
ST_OK = "ok"                       # snapshot + contiguous seq to cutoff
ST_OK_STALE = "ok_stale"           # contiguous but last event < cutoff window
ST_NO_DATA = "no_data"
ST_NO_SNAPSHOT = "no_snapshot"     # traffic but no snapshot before cutoff
ST_GAPPED = "gapped"               # discontinuity before cutoff — the book
                                   # returned is the last *trusted* state
ST_MALFORMED = "malformed"         # unparseable payload in the book path

_STALE_AFTER_S = 30.0


def _dec(v: Any) -> Optional[Decimal]:
    """Parse a wire numeric (string or number) into Decimal, loss-free."""
    if v is None:
        return None
    try:
        return Decimal(str(v))
    except Exception:
        return None


def _snapshot_levels(msg: Dict[str, Any], side: str) -> Optional[List[Any]]:
    """Bid levels for one side across the snapshot encodings we archive.

    Kalshi WS snapshots carry ``{side}_dollars_fp`` (fixed-point string
    pairs); REST/bootstrap or pre-normalized snapshots carry
    ``{side}_dollars`` or plain ``{side}``.  Returns the first list found,
    or ``None`` when the snapshot has no level key for the side at all.
    """
    for key in (f"{side}_dollars_fp", f"{side}_dollars", side):
        levels = msg.get(key)
        if isinstance(levels, list):
            return levels
    return None


@dataclass
class ReconstructedBook:
    """The book the collector observed, plus the coverage context."""

    ticker: str
    status: str
    # Decimal-precise bid ladders in DOLLARS (Kalshi wire space).
    yes_bids: Dict[Decimal, Decimal] = field(default_factory=dict)
    no_bids: Dict[Decimal, Decimal] = field(default_factory=dict)
    applied_through_seq: Optional[int] = None
    last_applied_recv_utc_ns: Optional[int] = None
    cutoff_utc_ns: Optional[int] = None
    connection_id: Optional[str] = None
    subscription_id: Optional[int] = None
    snapshot_count: int = 0
    delta_count: int = 0
    gaps: List[Dict[str, Any]] = field(default_factory=list)
    malformed_count: int = 0
    duplicate_seq_count: int = 0
    resynced_after_gap: bool = False
    stale_s: Optional[float] = None
    detail: str = ""

    @property
    def yes_best_bid(self) -> Optional[Decimal]:
        return max(self.yes_bids) if self.yes_bids else None

    @property
    def no_best_bid(self) -> Optional[Decimal]:
        return max(self.no_bids) if self.no_bids else None

    @property
    def yes_best_ask(self) -> Optional[Decimal]:
        # Kalshi binary inversion: YES ask = 1 - best NO bid.
        nb = self.no_best_bid
        return (Decimal("1") - nb) if nb is not None else None

    @property
    def no_best_ask(self) -> Optional[Decimal]:
        yb = self.yes_best_bid
        return (Decimal("1") - yb) if yb is not None else None

    def deterministic_digest(self) -> str:
        """Stable digest of the reconstructed book for repeat-replay checks."""
        import hashlib

        def _lv(d: Dict[Decimal, Decimal]) -> List[List[str]]:
            return [[str(k), str(d[k])] for k in sorted(d)]

        payload = {
            "ticker": self.ticker,
            "status": self.status,
            "yes": _lv(self.yes_bids),
            "no": _lv(self.no_bids),
            "seq": self.applied_through_seq,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ticker": self.ticker,
            "status": self.status,
            "yes_bids": {str(k): str(v) for k, v in sorted(self.yes_bids.items())},
            "no_bids": {str(k): str(v) for k, v in sorted(self.no_bids.items())},
            "yes_best_bid": str(self.yes_best_bid) if self.yes_best_bid else None,
            "no_best_bid": str(self.no_best_bid) if self.no_best_bid else None,
            "yes_best_ask": str(self.yes_best_ask) if self.yes_best_ask else None,
            "no_best_ask": str(self.no_best_ask) if self.no_best_ask else None,
            "applied_through_seq": self.applied_through_seq,
            "last_applied_recv_utc_ns": self.last_applied_recv_utc_ns,
            "cutoff_utc_ns": self.cutoff_utc_ns,
            "connection_id": self.connection_id,
            "subscription_id": self.subscription_id,
            "snapshot_count": self.snapshot_count,
            "delta_count": self.delta_count,
            "malformed_count": self.malformed_count,
            "duplicate_seq_count": self.duplicate_seq_count,
            "resynced_after_gap": self.resynced_after_gap,
            "stale_s": self.stale_s,
            "gaps": self.gaps,
            "digest": self.deterministic_digest(),
            "detail": self.detail,
        }


class BookReplayVerifier:
    """Minimal deterministic replay over the archive.

    Given a ticker and a local receipt-time cutoff:
      1. pick the newest (connection, sid) coverage for the ticker whose
         first snapshot precedes the cutoff;
      2. verify sid-level seq continuity (gaps, ``__dropped__`` markers and
         unparsed book payloads all break continuity);
      3. rebuild the book from the last snapshot before the cutoff, then
         apply that ticker's deltas in recorded order up to the cutoff or
         the first discontinuity — whichever comes first.

    The result is always "the book we observed" — coverage context included.
    """

    def __init__(self, db: BookArchiveDB):
        self.db = db

    def reconstruct(
        self,
        ticker: str,
        cutoff_utc_ns: Optional[int] = None,
        *,
        stale_after_s: float = _STALE_AFTER_S,
        connection_id: Optional[str] = None,
    ) -> ReconstructedBook:
        cutoff = cutoff_utc_ns if cutoff_utc_ns is not None else time.time_ns()

        cov_rows = [
            r for r in self.db.coverage_for(ticker)
            if connection_id is None or r["connection_id"] == connection_id
        ]
        if not cov_rows:
            return ReconstructedBook(
                ticker=ticker, status=ST_NO_DATA, cutoff_utc_ns=cutoff,
                detail="no coverage rows for ticker",
            )

        # Prefer the coverage row with the most recent snapshot that still
        # precedes the cutoff; fall back to the most recent row overall so
        # NO_SNAPSHOT/GAPPED states are still reported truthfully.
        def _sort_key(r: sqlite3.Row) -> int:
            return r["first_snapshot_recv_utc_ns"] or r["subscribed_utc_ns"] or 0

        chosen = None
        for r in sorted(cov_rows, key=_sort_key, reverse=True):
            snap = r["first_snapshot_recv_utc_ns"]
            if snap is not None and snap <= cutoff:
                chosen = r
                break
        if chosen is None:
            chosen = max(cov_rows, key=_sort_key)

        conn_id = chosen["connection_id"]
        sid = chosen["subscription_id"]

        events = self.db.events_for_sid(conn_id, sid)

        result = ReconstructedBook(
            ticker=ticker,
            status=ST_NO_SNAPSHOT,
            cutoff_utc_ns=cutoff,
            connection_id=conn_id,
            subscription_id=sid,
        )

        prev_seq: Optional[int] = None
        book_valid = False          # True between snapshot and next break
        continuity_broken = False   # gap/dropped/malformed since last snapshot
        saw_ticker_event = False
        saw_gap_after_last_apply = False
        for ev in events:
            recv = ev["received_at_utc_ns"]
            seq = ev["sequence_number"]
            mtype = ev["message_type"]

            # ── sid-level continuity: a gap poisons every ticker on it ──
            if mtype == MSG_DROPPED:
                continuity_broken = True
                book_valid = False
                result.gaps.append(
                    {
                        "reason": "archive_dropped_event",
                        "at_seq": seq,
                        "recv_utc_ns": recv,
                    }
                )
                if recv <= cutoff:
                    saw_gap_after_last_apply = True
                continue
            # Any seq-bearing stored frame advances stream continuity —
            # including control frames (ok/subscribed acks), which occupy the
            # same sid sequence space as book deltas.
            if seq is not None:
                if prev_seq is not None:
                    if seq == prev_seq + 1:
                        pass
                    elif seq <= prev_seq:
                        # Duplicate / out-of-order delivery: first-wins,
                        # skipped deterministically — not a gap.
                        result.duplicate_seq_count += 1
                        continue
                    else:
                        continuity_broken = True
                        book_valid = False
                        result.gaps.append(
                            {
                                "reason": "seq_discontinuity",
                                "expected_seq": prev_seq + 1,
                                "got_seq": seq,
                                "recv_utc_ns": recv,
                            }
                        )
                        if recv <= cutoff:
                            saw_gap_after_last_apply = True
                prev_seq = seq

            if recv > cutoff:
                continue  # beyond the requested receipt-time cutoff

            if mtype not in _BOOK_TYPES:
                continue

            try:
                data = json.loads(ev["raw_payload"])
            except (json.JSONDecodeError, TypeError):
                result.malformed_count += 1
                continuity_broken = True
                book_valid = False
                continue
            msg = data.get("msg") if isinstance(data.get("msg"), dict) else {}
            msg_ticker = msg.get("market_ticker") or msg.get("ticker")
            if msg_ticker != ticker:
                continue  # other multiplexed ticker — continuity only

            saw_ticker_event = True
            if mtype == "orderbook_snapshot":
                # Snapshots are authoritative: rebuild the book and heal
                # continuity from this point.
                if continuity_broken or result.gaps:
                    result.resynced_after_gap = True
                continuity_broken = False
                result.yes_bids.clear()
                result.no_bids.clear()
                book_valid = True
                result.snapshot_count += 1
                bad_level = False
                for side_key, book in (("yes", result.yes_bids),
                                       ("no", result.no_bids)):
                    levels = _snapshot_levels(msg, side_key)
                    if levels is None:
                        # A snapshot carrying no book for a side at all is
                        # not a trustworthy resync point.
                        result.malformed_count += 1
                        bad_level = True
                        continue
                    for level in levels:
                        if not (
                            isinstance(level, (list, tuple))
                            and len(level) >= 2
                        ):
                            result.malformed_count += 1
                            bad_level = True
                            continue
                        p = _dec(level[0])
                        s = _dec(level[1])
                        if p is None or s is None:
                            result.malformed_count += 1
                            bad_level = True
                            continue
                        if s > 0 and Decimal("0") < p < Decimal("1"):
                            book[p] = s
                if bad_level:
                    # A partially-parsed snapshot is not a trustworthy base.
                    book_valid = False
                    continuity_broken = True
                    result.yes_bids.clear()
                    result.no_bids.clear()
                    continue
            else:  # orderbook_delta
                if not book_valid or continuity_broken:
                    continue  # untrusted delta — snapshot required first
                side = msg.get("side")
                p = _dec(msg.get("price_dollars"))
                d = _dec(msg.get("delta_fp"))
                if side not in ("yes", "no") or p is None or d is None:
                    result.malformed_count += 1
                    continuity_broken = True
                    book_valid = False
                    continue
                result.delta_count += 1
                book = result.yes_bids if side == "yes" else result.no_bids
                if not (Decimal("0") < p < Decimal("1")):
                    result.malformed_count += 1
                    continue
                new_size = book.get(p, Decimal("0")) + d
                if new_size <= 0:
                    book.pop(p, None)
                else:
                    book[p] = new_size

            result.applied_through_seq = seq
            result.last_applied_recv_utc_ns = recv
            saw_gap_after_last_apply = False

        # ── status resolution ────────────────────────────────────────────
        if not book_valid:
            if saw_gap_after_last_apply or result.gaps:
                result.status = ST_GAPPED
            elif result.malformed_count:
                result.status = ST_MALFORMED
            elif saw_ticker_event:
                result.status = ST_NO_SNAPSHOT
            else:
                result.status = ST_NO_DATA
        elif continuity_broken:
            # Deltas were being applied when continuity broke after the last
            # trusted point — emit the last trusted state, flagged.
            result.status = ST_GAPPED
        else:
            age_s = (
                (cutoff - result.last_applied_recv_utc_ns) / 1e9
                if result.last_applied_recv_utc_ns
                else float("inf")
            )
            result.stale_s = age_s
            result.status = ST_OK_STALE if age_s > stale_after_s else ST_OK
        if result.malformed_count and result.status == ST_OK:
            result.status = ST_OK_STALE
        if not result.detail:
            result.detail = (
                f"applied_through_seq={result.applied_through_seq} "
                f"snaps={result.snapshot_count} deltas={result.delta_count} "
                f"gaps={len(result.gaps)} malformed={result.malformed_count}"
            )
        return result

    def reconstruct_into_local_orderbook(
        self,
        ticker: str,
        cutoff_utc_ns: Optional[int] = None,
        **kw: Any,
    ) -> Tuple[ReconstructedBook, Optional[Dict[str, Any]]]:
        """Replay the same events through the production LocalOrderbook.

        Proves the archive can drive the existing book model.  Returns the
        Decimal reconstruction plus a compatibility summary comparing tops
        of book (after LocalOrderbook's 0.01c/0.01-contract rounding).
        """
        from merid.event_venues.kalshi.orderbook import LocalOrderbook

        result = self.reconstruct(ticker, cutoff_utc_ns, **kw)
        cutoff = result.cutoff_utc_ns or time.time_ns()
        if result.connection_id is None or result.subscription_id is None:
            return result, None

        ob = LocalOrderbook(ticker)
        prev_seq: Optional[int] = None
        book_valid = False
        continuity_broken = False
        for ev in self.db.events_for_sid(
            result.connection_id, result.subscription_id
        ):
            if ev["received_at_utc_ns"] > cutoff:
                continue
            if ev["message_type"] == MSG_DROPPED:
                continuity_broken = True
                book_valid = False
                continue
            seq = ev["sequence_number"]
            # Any seq-bearing stored frame advances stream continuity —
            # control frames occupy the same sid sequence space as book
            # deltas (they are skipped for book application below).
            if seq is not None:
                if prev_seq is not None:
                    if seq == prev_seq + 1:
                        pass
                    elif seq <= prev_seq:
                        continue  # duplicate — skipped deterministically
                    else:
                        continuity_broken = True
                        book_valid = False
                prev_seq = seq
            if ev["message_type"] not in _BOOK_TYPES:
                continue
            try:
                data = json.loads(ev["raw_payload"])
            except (json.JSONDecodeError, TypeError):
                continuity_broken = True
                book_valid = False
                continue
            msg = data.get("msg") if isinstance(data.get("msg"), dict) else {}
            if (msg.get("market_ticker") or msg.get("ticker")) != ticker:
                continue
            is_snapshot = ev["message_type"] == "orderbook_snapshot"
            if not is_snapshot and (not book_valid or continuity_broken):
                continue
            payload = dict(msg)
            if seq is not None:
                payload["seq"] = seq
            payload.setdefault("market_ticker", ticker)
            payload.setdefault("ticker", ticker)
            try:
                if is_snapshot:
                    # Mirror the production normalization: wire snapshots
                    # carry {side}_dollars_fp string pairs; LocalOrderbook
                    # expects float [price, size] under yes/no.
                    for _side in ("yes", "no"):
                        levels = _snapshot_levels(msg, _side)
                        if levels is None:
                            raise ValueError(
                                f"snapshot missing {_side} levels"
                            )
                        payload[_side] = [
                            [float(level[0]), float(level[1])]
                            for level in levels
                            if isinstance(level, (list, tuple))
                            and len(level) >= 2
                            and float(level[1]) > 0
                        ]
                    ob.apply_snapshot(payload)
                    book_valid = True
                    continuity_broken = False
                else:
                    ob.apply_delta(payload)
            except Exception as exc:  # shape errors surface incompatibilities
                return result, {
                    "compatible": False,
                    "error": f"{type(exc).__name__}: {exc}",
                }

        def _cents(d: Decimal) -> float:
            return float(d * 100)

        ob_yes = max(ob.yes_levels.keys()) if ob.yes_levels else None
        ob_no = max(ob.no_levels.keys()) if ob.no_levels else None
        cmp_yes = _cents(result.yes_best_bid) if result.yes_best_bid else None
        cmp_no = _cents(result.no_best_bid) if result.no_best_bid else None
        compat = {
            "compatible": True,
            "archive_top": {"yes_bid_cents": cmp_yes, "no_bid_cents": cmp_no},
            "local_orderbook_top": {"yes_bid_cents": ob_yes, "no_bid_cents": ob_no},
            "tops_match": (ob_yes == cmp_yes) and (ob_no == cmp_no),
            "yes_levels": len(ob.yes_levels),
            "no_levels": len(ob.no_levels),
            "ob_initialized": ob.initialized,
        }
        return result, compat


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket collector transport
# ─────────────────────────────────────────────────────────────────────────────


class BookArchiveStream:
    """Authenticated orderbook_delta WebSocket for the archiver.

    Runs its own asyncio loop in a background thread (same pattern as
    ``KalshiCfRtiStream``).  For every received frame it invokes
    ``on_frame(raw_text, recv_utc_ns, recv_mono_ns, connection_id)`` BEFORE
    parsing — receipt timestamps bound the moment of local observation.

    ``on_session(connection_id, event, detail)`` reports connect /
    subscribed / disconnect lifecycle transitions.  The collector layer
    turns those into archive_sessions + coverage rows.
    """

    def __init__(
        self,
        on_frame: Callable[[str, int, int, str], None],
        on_session: Callable[[str, str, Dict[str, Any]], None],
        *,
        ws_url: Optional[str] = None,
        silence_reconnect_s: float = 45.0,
    ):
        from merid.event_venues.kalshi.kalshi_config import get_kalshi_config

        self.config = get_kalshi_config()
        self.ws_url = (
            ws_url
            or os.environ.get("MERID_KALSHI_WS_BASE")
            or self.config.ws_base_url
        )
        self.on_frame = on_frame
        self.on_session = on_session
        self.silence_reconnect_s = silence_reconnect_s
        self._ws = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._msg_id = 0
        self._lock = threading.Lock()
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0
        self.connection_id: Optional[str] = None
        # Pending ticker-set the collector wants subscribed on next connect.
        self._desired_tickers: List[str] = []
        # Subscription identity for the live connection — learned from
        # ``subscribed`` confirmations so rollover can mutate the existing
        # sid via update_subscription rather than starting new seq streams.
        self._sid: Optional[int] = None
        self._subscribed_tickers: set = set()
        self.update_interval_ms: int = int(
            os.environ.get("MERID_BOOK_UPDATE_INTERVAL_MS", "0")
        )

    # ── auth (mirrors KalshiCfRtiStream) ───────────────────────────────
    def _load_private_key(self):
        from cryptography.hazmat.primitives import serialization
        from pathlib import Path

        pem = getattr(self.config, "private_key_pem", None)
        path = getattr(self.config, "private_key_path", None)
        if pem:
            return serialization.load_pem_private_key(pem.encode(), password=None)
        if not path:
            raise ValueError("Kalshi private key (path or PEM) required")
        with open(Path(path), "rb") as f:
            return serialization.load_pem_private_key(f.read(), password=None)

    def _build_auth_headers(self) -> Dict[str, str]:
        import base64
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding

        key = self._load_private_key()
        ts = str(int(time.time() * 1000))
        msg = ts + "GET" + "/trade-api/ws/v2"
        sig = key.sign(
            msg.encode("utf-8"),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
        return {
            "Content-Type": "application/json",
            "KALSHI-ACCESS-KEY": self.config.api_key_id,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode("utf-8"),
            "KALSHI-ACCESS-TIMESTAMP": ts,
        }

    def set_tickers(self, tickers: List[str]) -> None:
        """Update the desired subscription set.

        On a live connection with a known sid this sends
        ``update_subscription`` add/delete_markets — keeping the existing
        sid (and its sequence stream) instead of opening a parallel one.
        Otherwise a fresh ``subscribe`` carries the full desired set.
        """
        self._desired_tickers = sorted(set(tickers))
        if self._ws is not None and self._loop is not None:
            import asyncio as _aio

            try:
                _aio.run_coroutine_threadsafe(
                    self._sync_subscription(), self._loop
                )
            except Exception as exc:
                logger.warning("[BOOK-ARCH-WS] live re-subscribe failed: %s", exc)

    def _next_msg_id(self) -> int:
        with self._lock:
            self._msg_id += 1
            return self._msg_id

    async def _subscribe_tickers(self, tickers: List[str]) -> None:
        if not self._ws or not tickers:
            return
        params: Dict[str, Any] = {
            "channels": ["orderbook_delta"],
            "market_tickers": tickers,
            "use_yes_price": False,
        }
        if self.update_interval_ms > 0:
            params["update_interval_ms"] = self.update_interval_ms
        await self._ws.send(
            json.dumps(
                {"id": self._next_msg_id(), "cmd": "subscribe", "params": params}
            )
        )
        self._subscribed_tickers = set(tickers)
        self._emit_session("subscribe_sent", {"tickers": tickers})

    async def _update_markets(self, action: str, tickers: List[str]) -> None:
        if not self._ws or not tickers or self._sid is None:
            return
        await self._ws.send(
            json.dumps(
                {
                    "id": self._next_msg_id(),
                    "cmd": "update_subscription",
                    "params": {
                        "sid": self._sid,
                        "market_tickers": tickers,
                        "action": action,
                    },
                }
            )
        )
        self._emit_session(
            "subscribe_sent", {"action": action, "tickers": tickers}
        )

    async def _sync_subscription(self) -> None:
        """Reconcile wire subscription state with ``_desired_tickers``."""
        if not self._ws:
            return
        desired = set(self._desired_tickers)
        if self._sid is None or not self._subscribed_tickers:
            await self._subscribe_tickers(sorted(desired))
            return
        adds = sorted(desired - self._subscribed_tickers)
        removes = sorted(self._subscribed_tickers - desired)
        try:
            if adds:
                await self._update_markets("add_markets", adds)
            if removes:
                await self._update_markets("delete_markets", removes)
        except Exception as exc:
            logger.warning("[BOOK-ARCH-WS] update_subscription failed: %s", exc)
            return
        self._subscribed_tickers = desired

    def _emit_session(self, event: str, detail: Dict[str, Any]) -> None:
        try:
            self.on_session(self.connection_id or "", event, detail)
        except Exception:
            logger.exception("[BOOK-ARCH-WS] on_session error")

    async def _connect(self) -> None:
        import websockets

        headers = self._build_auth_headers()
        try:
            self._ws = await websockets.connect(
                self.ws_url,
                additional_headers=headers,
                ping_interval=30,
                ping_timeout=60,
                close_timeout=5,
            )
        except TypeError:
            self._ws = await websockets.connect(
                self.ws_url,
                extra_headers=headers,
                ping_interval=30,
                ping_timeout=60,
                close_timeout=5,
            )

    async def _recv_loop(self) -> None:
        last_data = time.monotonic()
        while self._running and self._ws:
            try:
                import asyncio
                import websockets

                try:
                    raw = await asyncio.wait_for(self._ws.recv(), timeout=5.0)
                except asyncio.TimeoutError:
                    raw = None
                # Receipt stamps bind the moment of local observation:
                # captured when the frame arrives, before any parsing/DB work.
                recv_utc = time.time_ns()
                recv_mono = time.monotonic_ns()
                if raw is None:
                    silent = time.monotonic() - last_data
                    if silent > self.silence_reconnect_s:
                        self._emit_session(
                            "silence_timeout", {"silent_s": silent}
                        )
                        return
                    continue
                last_data = time.monotonic()
                # Text frames only; binary/control frames are not book data.
                if isinstance(raw, (bytes, bytearray)):
                    continue
                # Cheap sid learning: subscribed/error frames are rare, so a
                # substring pre-check avoids double-parsing every frame.
                if '"subscribed"' in raw or '"error"' in raw:
                    try:
                        _d = json.loads(raw)
                        _t = _d.get("type")
                        if _t == "subscribed":
                            _m = _d.get("msg") if isinstance(_d.get("msg"), dict) else {}
                            sid = _d.get("sid", _m.get("sid"))
                            if isinstance(sid, int) and not isinstance(sid, bool):
                                self._sid = sid
                        elif _t == "error":
                            self._emit_session(
                                "ws_error",
                                {"msg": _d.get("msg")},
                            )
                    except Exception:
                        pass
                self.on_frame(
                    raw, recv_utc, recv_mono, self.connection_id or ""
                )
            except websockets.ConnectionClosed as exc:
                self._emit_session("connection_closed", {"reason": str(exc)})
                return
            except Exception as exc:
                self._emit_session("recv_error", {"reason": str(exc)})
                return

    async def _run_once(self) -> None:
        import asyncio

        self.connection_id = uuid.uuid4().hex[:16]
        self._sid = None
        self._subscribed_tickers = set()
        self._emit_session(
            "connect",
            {"ws_url": self.ws_url, "desired_tickers": self._desired_tickers},
        )
        try:
            await self._connect()
            if self._desired_tickers:
                await self._subscribe_tickers(self._desired_tickers)
            await self._recv_loop()
        finally:
            # A session row without a disconnect marker reads as a live
            # connection — always close it, on every exit path.
            ws, self._ws = self._ws, None
            if ws:
                try:
                    await ws.close()
                except Exception:
                    pass
            self._emit_session("disconnect", {})

    def _run(self) -> None:
        self._loop = __import__("asyncio").new_event_loop()
        __import__("asyncio").set_event_loop(self._loop)
        self._running = True
        while self._running:
            try:
                started = time.monotonic()
                self._loop.run_until_complete(self._run_once())
                if time.monotonic() - started > 60.0:
                    self._reconnect_delay = 1.0
            except Exception as exc:
                logger.error("[BOOK-ARCH-WS] run error: %s", exc)
            if not self._running:
                break
            self._loop.run_until_complete(
                __import__("asyncio").sleep(self._reconnect_delay)
            )
            self._reconnect_delay = min(
                self._reconnect_delay * 2, self._max_reconnect_delay
            )
        try:
            self._loop.close()
        except Exception:
            pass

    _loop = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="book-archive-ws", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)


# ─────────────────────────────────────────────────────────────────────────────
# Bounded ingest queue with explicit overflow
# ─────────────────────────────────────────────────────────────────────────────


class IngestQueue:
    """Bounded FIFO between the WS thread and the writer thread.

    Two tiers: the fast ``queue.Queue`` plus an ``overflow`` deque that
    preserves envelopes whole when the fast tier fills.  Frames in overflow
    are delayed, not dropped — they persist once the writer catches up.
    Only envelopes beyond ``overflow_cap`` become ``__dropped__`` markers:
    the envelope's indexing metadata is kept in ``dropped_meta``
    (cap-bounded) and flushed to the archive as marker rows, while
    ``dropped_total`` counts everything including descriptors beyond the
    meta cap.
    """

    def __init__(self, maxsize: int = 50000, dropped_meta_cap: int = 10000,
                 overflow_cap: int = 1_500_000):
        self.q: "queue.Queue[EventEnvelope]" = queue.Queue(maxsize=maxsize)
        self.overflow: "deque[EventEnvelope]" = deque()
        self.overflow_cap = overflow_cap
        self.overflow_total = 0
        self.dropped_meta: "queue.Queue[EventEnvelope]" = queue.Queue(
            maxsize=dropped_meta_cap
        )
        self.dropped_total = 0
        self._drop_ord = 0
        self._lock = threading.Lock()

    def put(self, env: EventEnvelope) -> bool:
        # Strict FIFO: once overflow exists, new arrivals go straight to the
        # back so the writer never persists newer frames ahead of older ones.
        if not self.overflow:
            try:
                self.q.put_nowait(env)
                return True
            except queue.Full:
                pass
        if len(self.overflow) < self.overflow_cap:
            self.overflow.append(env)
            self.overflow_total += 1
            return True
        with self._lock:
            self._drop_ord += 1
            self.dropped_total += 1
            marker = EventEnvelope.dropped(
                collector_instance_id=env.collector_instance_id,
                connection_id=env.connection_id,
                subscription_id=env.subscription_id,
                market_ticker=env.market_ticker,
                dropped_type=env.message_type,
                sequence_number=env.sequence_number,
                received_at_utc_ns=env.received_at_utc_ns,
                received_at_monotonic_ns=env.received_at_monotonic_ns,
                drop_ordinal=self._drop_ord,
                reason="buffer_overflow",
            )
            try:
                self.dropped_meta.put_nowait(marker)
            except queue.Full:
                pass  # count already incremented; descriptors are capped
        return False

    def drain(self, max_items: int = 5000) -> List[EventEnvelope]:
        """Pop up to ``max_items`` real events (q then overflow, FIFO),
        then any dropped markers."""
        out: List[EventEnvelope] = []
        while len(out) < max_items:
            try:
                out.append(self.q.get_nowait())
            except queue.Empty:
                break
        while self.overflow and len(out) < max_items:
            out.append(self.overflow.popleft())
        while True:
            try:
                out.append(self.dropped_meta.get_nowait())
            except queue.Empty:
                break
        return out

    @property
    def depth(self) -> int:
        return self.q.qsize() + len(self.overflow)

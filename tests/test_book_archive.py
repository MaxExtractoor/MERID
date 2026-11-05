"""Acceptance tests for the Phase A' book archive.

Covers the contract's acceptance table:

    snapshot+deltas -> reconstructed levels match
    YES/NO executable-ladder -> LocalOrderbook behavior unchanged
    sub-cent prices + fractional quantities -> no precision loss
    missing sequence -> coverage invalid, no silent continuation
    reconnect/restart -> new session identity + explicit recovery boundary
    subscription changes / rollover -> no mixing of books or seq contexts
    duplicate / malformed input -> explicit deterministic handling
    DB failure / buffer overflow -> visible failure + degraded coverage
    repeat replay -> deterministic identical output
    sustained capture -> storage/write/coverage stats available
"""
from __future__ import annotations

import json
import sys
import time
import uuid
from decimal import Decimal
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from merid.event_venues.kalshi.book_archive import (  # noqa: E402
    ALERT_MISSING_SNAPSHOT,
    ALERT_SEQ_GAP,
    BookArchiveDB,
    COV_AWAITING_SNAPSHOT,
    COV_CLOSED,
    COV_COVERING,
    COV_GAPPED,
    CoverageTracker,
    EventEnvelope,
    IngestQueue,
    MSG_DROPPED,
    ST_GAPPED,
    ST_MALFORMED,
    ST_NO_DATA,
    ST_NO_SNAPSHOT,
    ST_OK,
    ST_OK_STALE,
    BookReplayVerifier,
    envelope_from_frame,
)

COLLECTOR = "col-test-1"
CONN_A = "conn-A"
CONN_B = "conn-B"
TICKER = "KXBTC15M-26NOV041415-15"
TICKER2 = "KXETH15M-26NOV041415-15"

_T0_NS = 1_800_000_000_000_000_000  # fixed epoch-ish base for determinism


def _frame(mtype, sid, seq, msg, ts_ns):
    """Build (raw_text, recv_utc_ns) for a wire-format frame."""
    raw = json.dumps({"type": mtype, "sid": sid, "seq": seq, "msg": msg},
                     separators=(",", ":"))
    return raw, ts_ns


def _env(raw, conn, sid_seq, ts_ns, ordinal):
    return envelope_from_frame(
        raw,
        received_at_utc_ns=ts_ns,
        received_at_monotonic_ns=ts_ns // 1000,
        connection_id=conn,
        collector_instance_id=COLLECTOR,
        recv_ordinal=ordinal,
    )


def _snap_msg(ticker, yes, no):
    """Wire-format snapshot: yes_dollars_fp/no_dollars_fp string pairs."""
    return {
        "market_ticker": ticker,
        "yes_dollars_fp": yes,
        "no_dollars_fp": no,
    }


def _delta_msg(ticker, side, price_dollars, delta_fp):
    return {
        "market_ticker": ticker,
        "side": side,
        "price_dollars": price_dollars,
        "delta_fp": delta_fp,
    }


class _Harness:
    """Push frames through envelope -> tracker -> DB, like the writer does."""

    def __init__(self, tmp_path):
        self.db = BookArchiveDB(str(tmp_path / "book_test.db"))
        self.tracker = CoverageTracker()
        self.ord = 0

    def feed(self, raw, conn, ts_ns):
        self.ord += 1
        env = _env(raw, conn, None, ts_ns, self.ord)
        touched = self.tracker.note_event(env)
        self.db.insert_events([env])
        self.db.upsert_coverage(touched)
        return env

    def feed_raw(self, conn, ts_ns, mtype, sid, seq, msg):
        raw, _ = _frame(mtype, sid, seq, msg, ts_ns)
        return self.feed(raw, conn, ts_ns)

    def verifier(self):
        return BookReplayVerifier(self.db)


@pytest.fixture
def h(tmp_path):
    harness = _Harness(tmp_path)
    yield harness
    harness.db.close()


# ─────────────────────────────────────────────────────────────────────────────
# 1. Snapshot followed by deltas
# ─────────────────────────────────────────────────────────────────────────────


def test_snapshot_then_deltas_reconstruct(h):
    conn, sid = CONN_A, 7
    h.feed_raw(conn, _T0_NS, "orderbook_snapshot", sid, 1,
               _snap_msg(TICKER, [["0.42", "10"], ["0.41", "5"]],
                         [["0.55", "3"]]))
    h.feed_raw(conn, _T0_NS + 1_000_000_000, "orderbook_delta", sid, 2,
               _delta_msg(TICKER, "yes", "0.42", "2"))
    h.feed_raw(conn, _T0_NS + 2_000_000_000, "orderbook_delta", sid, 3,
               _delta_msg(TICKER, "no", "0.55", "-3"))   # removes level
    h.feed_raw(conn, _T0_NS + 3_000_000_000, "orderbook_delta", sid, 4,
               _delta_msg(TICKER, "no", "0.50", "7"))

    rec = h.verifier().reconstruct(TICKER, cutoff_utc_ns=_T0_NS + 4e9)
    assert rec.status == ST_OK
    assert rec.yes_bids == {Decimal("0.42"): Decimal("12"),
                           Decimal("0.41"): Decimal("5")}
    assert rec.no_bids == {Decimal("0.50"): Decimal("7")}
    # Executable-ladder inversion: YES ask = 1 - best NO bid.
    assert rec.yes_best_ask == Decimal("0.50")
    assert rec.no_best_ask == Decimal("0.58")
    assert rec.applied_through_seq == 4
    assert rec.delta_count == 3  # all three deltas applied, incl. the removal


def test_delta_before_snapshot_is_awaiting(h):
    conn, sid = CONN_A, 7
    h.feed_raw(conn, _T0_NS, "orderbook_delta", sid, 1,
               _delta_msg(TICKER, "yes", "0.42", "5"))
    rec = h.verifier().reconstruct(TICKER, cutoff_utc_ns=_T0_NS + 1e9)
    assert rec.status == ST_NO_SNAPSHOT
    cov = h.db.coverage_for(TICKER)[0]
    assert cov["state"] == COV_AWAITING_SNAPSHOT
    assert cov["pre_snapshot_deltas"] == 1
    assert any(a.code == ALERT_MISSING_SNAPSHOT for a in h.tracker.alerts)


# ─────────────────────────────────────────────────────────────────────────────
# 2. YES/NO executable-ladder compatibility with LocalOrderbook
# ─────────────────────────────────────────────────────────────────────────────


def test_local_orderbook_compatibility(h):
    conn, sid = CONN_A, 7
    h.feed_raw(conn, _T0_NS, "orderbook_snapshot", sid, 1,
               _snap_msg(TICKER, [["0.42", "10"], ["0.415", "3"]],
                         [["0.50", "4"]]))
    h.feed_raw(conn, _T0_NS + 1e9, "orderbook_delta", sid, 2,
               _delta_msg(TICKER, "no", "0.50", "-1"))
    h.feed_raw(conn, _T0_NS + 2e9, "orderbook_delta", sid, 3,
               _delta_msg(TICKER, "yes", "0.43", "6"))

    rec, compat = h.verifier().reconstruct_into_local_orderbook(
        TICKER, cutoff_utc_ns=_T0_NS + 3e9
    )
    assert rec.status == ST_OK
    assert compat is not None and compat["compatible"] is True
    assert compat["tops_match"] is True
    # LocalOrderbook top-of-book in cents matches Decimal reconstruction.
    assert compat["local_orderbook_top"]["yes_bid_cents"] == pytest.approx(43.0)
    assert compat["local_orderbook_top"]["no_bid_cents"] == pytest.approx(50.0)


# ─────────────────────────────────────────────────────────────────────────────
# 3. Sub-cent prices + fractional quantities survive end-to-end
# ─────────────────────────────────────────────────────────────────────────────


def test_subcent_and_fractional_precision(h):
    conn, sid = CONN_A, 7
    h.feed_raw(conn, _T0_NS, "orderbook_snapshot", sid, 1,
               _snap_msg(TICKER, [["0.9150", "2.5"], ["0.9160", "1.25"]],
                         [["0.0825", "4.75"]]))
    h.feed_raw(conn, _T0_NS + 1e9, "orderbook_delta", sid, 2,
               _delta_msg(TICKER, "yes", "0.9150", "0.75"))
    h.feed_raw(conn, _T0_NS + 2e9, "orderbook_delta", sid, 3,
               _delta_msg(TICKER, "no", "0.0825", "-2.25"))

    rec = h.verifier().reconstruct(TICKER, cutoff_utc_ns=_T0_NS + 3e9)
    assert rec.status == ST_OK
    # Exact Decimal values — no float drift through archive->read->replay.
    assert rec.yes_bids[Decimal("0.915")] == Decimal("3.25")
    assert rec.yes_bids[Decimal("0.916")] == Decimal("1.25")
    assert rec.no_bids[Decimal("0.0825")] == Decimal("2.5")
    # And LocalOrderbook agrees (its 0.01c / 0.01-contract rounding).
    _, compat = h.verifier().reconstruct_into_local_orderbook(
        TICKER, cutoff_utc_ns=_T0_NS + 3e9
    )
    assert compat["compatible"] and compat["tops_match"]
    assert compat["local_orderbook_top"]["yes_bid_cents"] == pytest.approx(91.6)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Missing sequence -> invalid coverage, no silent continuation
# ─────────────────────────────────────────────────────────────────────────────


def test_missing_seq_gaps_coverage(h):
    conn, sid = CONN_A, 7
    h.feed_raw(conn, _T0_NS, "orderbook_snapshot", sid, 1,
               _snap_msg(TICKER, [["0.42", "10"]], [["0.50", "3"]]))
    h.feed_raw(conn, _T0_NS + 1e9, "orderbook_delta", sid, 2,
               _delta_msg(TICKER, "yes", "0.42", "2"))
    # seq 3 is lost; seq 4 arrives.
    h.feed_raw(conn, _T0_NS + 3e9, "orderbook_delta", sid, 4,
               _delta_msg(TICKER, "yes", "0.43", "9"))

    cov = h.db.coverage_for(TICKER)[0]
    assert cov["state"] == COV_GAPPED
    assert cov["gap_count"] == 1
    gaps = json.loads(cov["gaps"])
    assert gaps[0]["expected_seq"] == 3 and gaps[0]["got_seq"] == 4
    assert cov["valid_to_utc_ns"] == _T0_NS + 1e9  # last contiguous event
    assert any(a.code == ALERT_SEQ_GAP for a in h.tracker.alerts)

    rec = h.verifier().reconstruct(TICKER, cutoff_utc_ns=_T0_NS + 4e9)
    assert rec.status == ST_GAPPED
    # Book stops at the last trusted event — seq 4 was never applied.
    assert rec.yes_bids == {Decimal("0.42"): Decimal("12")}
    assert rec.applied_through_seq == 2


def test_resync_snapshot_heals_coverage(h):
    conn, sid = CONN_A, 7
    h.feed_raw(conn, _T0_NS, "orderbook_snapshot", sid, 1,
               _snap_msg(TICKER, [["0.42", "10"]], [["0.50", "3"]]))
    h.feed_raw(conn, _T0_NS + 1e9, "orderbook_delta", sid, 2,
               _delta_msg(TICKER, "yes", "0.42", "2"))
    h.feed_raw(conn, _T0_NS + 2e9, "orderbook_delta", sid, 4,
               _delta_msg(TICKER, "yes", "0.43", "9"))  # gap at 3
    # Kalshi resends a snapshot after resubscribe -> authoritative resync.
    h.feed_raw(conn, _T0_NS + 3e9, "orderbook_snapshot", sid, 5,
               _snap_msg(TICKER, [["0.44", "20"]], [["0.51", "8"]]))
    h.feed_raw(conn, _T0_NS + 4e9, "orderbook_delta", sid, 6,
               _delta_msg(TICKER, "yes", "0.44", "1"))

    rec = h.verifier().reconstruct(TICKER, cutoff_utc_ns=_T0_NS + 5e9)
    assert rec.status == ST_OK
    assert rec.resynced_after_gap is True
    assert rec.yes_bids == {Decimal("0.44"): Decimal("21")}
    assert len(rec.gaps) == 1  # the gap is still reported, not hidden


# ─────────────────────────────────────────────────────────────────────────────
# 5. Reconnect -> new session identity, explicit recovery boundary
# ─────────────────────────────────────────────────────────────────────────────


def test_reconnect_new_session(h):
    # Connection A: snapshot + delta.
    h.feed_raw(CONN_A, _T0_NS, "orderbook_snapshot", 7, 1,
               _snap_msg(TICKER, [["0.42", "10"]], [["0.50", "3"]]))
    h.feed_raw(CONN_A, _T0_NS + 1e9, "orderbook_delta", 7, 2,
               _delta_msg(TICKER, "yes", "0.42", "2"))
    touched = h.tracker.note_session_end(
        CONN_A, reason="connection_closed", ts_utc_ns=_T0_NS + 2e9
    )
    h.db.upsert_coverage(touched)

    # Connection B: same sid NUMBER is fine — different connection context.
    h.feed_raw(CONN_B, _T0_NS + 10e9, "orderbook_snapshot", 7, 1,
               _snap_msg(TICKER, [["0.45", "8"]], [["0.49", "2"]]))
    h.feed_raw(CONN_B, _T0_NS + 11e9, "orderbook_delta", 7, 2,
               _delta_msg(TICKER, "yes", "0.45", "1"))

    rec = h.verifier().reconstruct(TICKER, cutoff_utc_ns=_T0_NS + 12e9)
    assert rec.status == ST_OK
    assert rec.connection_id == CONN_B
    assert rec.yes_bids == {Decimal("0.45"): Decimal("9")}

    # Both coverage rows exist; A is closed, B is live.
    covs = h.db.coverage_for(TICKER)
    by_conn = {c["connection_id"]: c for c in covs}
    assert by_conn[CONN_A]["state"] == COV_CLOSED
    assert by_conn[CONN_B]["state"] == COV_COVERING

    # A cutoff inside connection A still reconstructs A's book.
    rec_a = h.verifier().reconstruct(TICKER, cutoff_utc_ns=_T0_NS + 1.5e9)
    assert rec_a.connection_id == CONN_A
    assert rec_a.yes_bids == {Decimal("0.42"): Decimal("12")}


def test_orphaned_session_marked_ended(h, tmp_path):
    db = h.db
    db.insert_session(connection_id="dead-conn",
                      collector_instance_id="col-old",
                      ws_url="wss://x", connect_utc_ns=_T0_NS)
    n = db.close_orphaned_sessions(live_connection_ids=[])
    assert n == 1
    row = db.conn.execute(
        "SELECT disconnect_reason FROM archive_sessions"
        " WHERE connection_id='dead-conn'"
    ).fetchone()
    assert row[0] == "collector_died_or_restarted"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Subscription changes / rollover: no mixing of books or seq contexts
# ─────────────────────────────────────────────────────────────────────────────


def test_rollover_multiplexed_sid(h):
    conn, sid = CONN_A, 7
    # Two tickers share one sid (Kalshi multiplexes).  Snapshots per ticker.
    h.feed_raw(conn, _T0_NS, "orderbook_snapshot", sid, 1,
               _snap_msg(TICKER, [["0.42", "10"]], [["0.50", "3"]]))
    h.feed_raw(conn, _T0_NS + 0.5e9, "orderbook_snapshot", sid, 2,
               _snap_msg(TICKER2, [["0.30", "6"]], [["0.65", "4"]]))
    h.feed_raw(conn, _T0_NS + 1e9, "orderbook_delta", sid, 3,
               _delta_msg(TICKER, "yes", "0.42", "5"))
    h.feed_raw(conn, _T0_NS + 2e9, "orderbook_delta", sid, 4,
               _delta_msg(TICKER2, "no", "0.65", "-2"))

    r1 = h.verifier().reconstruct(TICKER, cutoff_utc_ns=_T0_NS + 3e9)
    r2 = h.verifier().reconstruct(TICKER2, cutoff_utc_ns=_T0_NS + 3e9)
    assert r1.status == ST_OK and r2.status == ST_OK
    assert r1.yes_bids == {Decimal("0.42"): Decimal("15")}
    assert r2.no_bids == {Decimal("0.65"): Decimal("2")}


def test_gap_on_shared_sid_degrades_all_tickers(h):
    conn, sid = CONN_A, 7
    h.feed_raw(conn, _T0_NS, "orderbook_snapshot", sid, 1,
               _snap_msg(TICKER, [["0.42", "10"]], [["0.50", "3"]]))
    h.feed_raw(conn, _T0_NS + 0.5e9, "orderbook_snapshot", sid, 2,
               _snap_msg(TICKER2, [["0.30", "6"]], [["0.65", "4"]]))
    # seq 3 lost on the shared sid — BOTH tickers degrade (the lost message
    # cannot be attributed to one ticker).
    h.feed_raw(conn, _T0_NS + 1e9, "orderbook_delta", sid, 5,
               _delta_msg(TICKER, "yes", "0.42", "5"))

    covs = {c["market_ticker"]: c for c in
            [r for r in h.db.coverage_for(TICKER)]
            + [r for r in h.db.coverage_for(TICKER2)]}
    assert covs[TICKER]["state"] == COV_GAPPED
    assert covs[TICKER2]["state"] == COV_GAPPED
    r2 = h.verifier().reconstruct(TICKER2, cutoff_utc_ns=_T0_NS + 2e9)
    assert r2.status == ST_GAPPED


def test_market_close_marks_coverage_closed(h):
    conn, sid = CONN_A, 7
    h.feed_raw(conn, _T0_NS, "orderbook_snapshot", sid, 1,
               _snap_msg(TICKER, [["0.42", "10"]], [["0.50", "3"]]))
    touched = h.tracker.note_market_closed(
        TICKER, reason="past_close_grace", ts_utc_ns=_T0_NS + 900e9
    )
    h.db.upsert_coverage(touched)
    cov = h.db.coverage_for(TICKER)[0]
    assert cov["state"] == COV_CLOSED
    assert cov["state_detail"] == "past_close_grace"


# ─────────────────────────────────────────────────────────────────────────────
# 7. Duplicate / malformed input -> explicit deterministic handling
# ─────────────────────────────────────────────────────────────────────────────


def test_duplicate_seq_skipped_not_applied(h):
    conn, sid = CONN_A, 7
    h.feed_raw(conn, _T0_NS, "orderbook_snapshot", sid, 1,
               _snap_msg(TICKER, [["0.42", "10"]], [["0.50", "3"]]))
    h.feed_raw(conn, _T0_NS + 1e9, "orderbook_delta", sid, 2,
               _delta_msg(TICKER, "yes", "0.42", "2"))
    # Same seq redelivered with different size — first-wins determinism.
    h.feed_raw(conn, _T0_NS + 2e9, "orderbook_delta", sid, 2,
               _delta_msg(TICKER, "yes", "0.42", "99"))

    rec = h.verifier().reconstruct(TICKER, cutoff_utc_ns=_T0_NS + 3e9)
    assert rec.status == ST_OK
    assert rec.yes_bids[Decimal("0.42")] == Decimal("12")  # not 111
    assert rec.duplicate_seq_count == 1


def test_malformed_payload_breaks_book(h):
    conn, sid = CONN_A, 7
    h.feed_raw(conn, _T0_NS, "orderbook_snapshot", sid, 1,
               _snap_msg(TICKER, [["0.42", "10"]], [["0.50", "3"]]))
    # A structurally-valid frame whose delta lacks required fields.
    h.feed_raw(conn, _T0_NS + 1e9, "orderbook_delta", sid, 2,
               {"market_ticker": TICKER, "side": "yes"})  # no price/delta
    rec = h.verifier().reconstruct(TICKER, cutoff_utc_ns=_T0_NS + 2e9)
    assert rec.status == ST_MALFORMED
    assert rec.malformed_count == 1


def test_unparseable_frame_indexed_and_flagged(h):
    conn = CONN_A
    h.feed("this is not json {{{", conn, _T0_NS)
    row = h.db.conn.execute(
        "SELECT message_type FROM book_events LIMIT 1"
    ).fetchone()
    assert row[0] == "__unparsed__"


# ─────────────────────────────────────────────────────────────────────────────
# 8. Buffer overflow / DB failure -> visible, degraded, not silent
# ─────────────────────────────────────────────────────────────────────────────


def test_buffer_overflow_drops_with_marker(h):
    q = IngestQueue(maxsize=2, overflow_cap=1)
    envs = []
    for i, seq in enumerate((1, 2, 3, 4)):
        raw, _ = _frame(
            "orderbook_delta", 7, seq,
            _delta_msg(TICKER, "yes", "0.42", "1"), _T0_NS + i
        )
        envs.append(_env(raw, CONN_A, None, _T0_NS + i, i + 1))
    assert q.put(envs[0]) is True   # fast tier
    assert q.put(envs[1]) is True   # fast tier
    assert q.put(envs[2]) is True   # overflow tier: delayed, not dropped
    assert q.put(envs[3]) is False  # past overflow cap -> dropped marker
    assert q.overflow_total == 1
    assert q.dropped_total == 1

    drained = q.drain()
    assert len(drained) == 4                # 3 real + 1 dropped marker
    marker = [e for e in drained if e.message_type == MSG_DROPPED]
    assert len(marker) == 1
    assert marker[0].sequence_number == 4   # lost seq is preserved
    seqs = [e.sequence_number for e in drained
            if e.message_type != MSG_DROPPED]
    assert seqs == [1, 2, 3]                # strict FIFO across tiers


def test_dropped_marker_gaps_coverage_and_replay(h):
    conn, sid = CONN_A, 7
    h.feed_raw(conn, _T0_NS, "orderbook_snapshot", sid, 1,
               _snap_msg(TICKER, [["0.42", "10"]], [["0.50", "3"]]))
    h.feed_raw(conn, _T0_NS + 1e9, "orderbook_delta", sid, 2,
               _delta_msg(TICKER, "yes", "0.42", "1"))
    # Writer could not persist seq=3 (queue overflow); marker row instead.
    marker = EventEnvelope.dropped(
        collector_instance_id=COLLECTOR,
        connection_id=conn,
        subscription_id=sid,
        market_ticker=TICKER,
        dropped_type="orderbook_delta",
        sequence_number=3,
        received_at_utc_ns=_T0_NS + 2e9,
        received_at_monotonic_ns=_T0_NS + 2e9,
        drop_ordinal=1,
        reason="buffer_overflow",
    )
    touched = h.tracker.note_event(marker)
    h.db.insert_events([marker])
    h.db.upsert_coverage(touched)
    h.feed_raw(conn, _T0_NS + 3e9, "orderbook_delta", sid, 4,
               _delta_msg(TICKER, "yes", "0.43", "5"))

    cov = h.db.coverage_for(TICKER)[0]
    assert cov["state"] == COV_GAPPED
    rec = h.verifier().reconstruct(TICKER, cutoff_utc_ns=_T0_NS + 4e9)
    assert rec.status == ST_GAPPED
    assert rec.yes_bids == {Decimal("0.42"): Decimal("11")}  # seq 4 unapplied


def test_db_write_failure_surfaces(h):
    h.db.conn.close()
    env = _env(
        _frame("orderbook_delta", 7, 1,
               _delta_msg(TICKER, "yes", "0.42", "1"), _T0_NS)[0],
        CONN_A, None, _T0_NS, 1,
    )
    with pytest.raises(Exception):
        h.db.insert_events([env])
    assert h.db.write_errors == 1


def test_insert_events_mixed_null_ticker_batch(h):
    """A batch mixing tickered deltas with NULL-ticker frames (markers,
    control frames) must persist — the batch sort key is None-safe."""
    conn, sid = CONN_A, 7
    envs = []
    envs.append(_env(
        _frame("orderbook_delta", sid, 1,
               _delta_msg(TICKER, "yes", "0.42", "1"), _T0_NS)[0],
        conn, sid, _T0_NS, 1,
    ))
    envs.append(EventEnvelope.dropped(
        collector_instance_id=COLLECTOR, connection_id=conn,
        subscription_id=sid, market_ticker=None,
        dropped_type="orderbook_delta", sequence_number=None,
        received_at_utc_ns=_T0_NS + 1, received_at_monotonic_ns=_T0_NS + 1,
        drop_ordinal=1, reason="buffer_overflow",
    ))
    envs.append(_env(
        _frame("orderbook_delta", sid, 2,
               _delta_msg(TICKER, "yes", "0.43", "1"), _T0_NS + 2)[0],
        conn, sid, _T0_NS + 2, 3,
    ))
    h.db.insert_events(envs)   # must not raise on the mixed None/str keys
    assert h.db.write_errors == 0
    n = h.db.conn.execute(
        "SELECT COUNT(*) FROM book_events").fetchone()[0]
    assert n == 3


# ─────────────────────────────────────────────────────────────────────────────
# 9. Repeat replay -> deterministic output
# ─────────────────────────────────────────────────────────────────────────────


def test_repeat_replay_deterministic(h):
    conn, sid = CONN_A, 7
    h.feed_raw(conn, _T0_NS, "orderbook_snapshot", sid, 1,
               _snap_msg(TICKER, [["0.42", "10"], ["0.41", "5"]],
                         [["0.50", "3"], ["0.51", "2"]]))
    for i in range(2, 8):
        h.feed_raw(conn, _T0_NS + i * 1e9, "orderbook_delta", sid, i,
                   _delta_msg(TICKER, "yes" if i % 2 else "no",
                              "0.42" if i % 2 else "0.50",
                              "1" if i % 3 else "-1"))
    v = h.verifier()
    a = v.reconstruct(TICKER, cutoff_utc_ns=_T0_NS + 10e9)
    b = v.reconstruct(TICKER, cutoff_utc_ns=_T0_NS + 10e9)
    assert a.status == b.status == ST_OK
    assert a.deterministic_digest() == b.deterministic_digest()
    assert a.to_dict() == b.to_dict()


# ─────────────────────────────────────────────────────────────────────────────
# 10. Sustained capture -> stats + coverage accounting available
# ─────────────────────────────────────────────────────────────────────────────


def test_stats_and_coverage_report(h):
    conn, sid = CONN_A, 7
    h.feed_raw(conn, _T0_NS, "orderbook_snapshot", sid, 1,
               _snap_msg(TICKER, [["0.42", "10"]], [["0.50", "3"]]))
    h.feed_raw(conn, _T0_NS + 1e9, "orderbook_delta", sid, 2,
               _delta_msg(TICKER, "yes", "0.42", "1"))
    st = h.db.stats()
    assert st["events"] == 2
    assert st["rows_written"] == 2
    assert st["coverage_by_state"][COV_COVERING] == 1


def test_no_data_status(h):
    rec = h.verifier().reconstruct("KXNOPE-1", cutoff_utc_ns=_T0_NS)
    assert rec.status == ST_NO_DATA


def test_cutoff_excludes_future_events(h):
    conn, sid = CONN_A, 7
    h.feed_raw(conn, _T0_NS, "orderbook_snapshot", sid, 1,
               _snap_msg(TICKER, [["0.42", "10"]], [["0.50", "3"]]))
    h.feed_raw(conn, _T0_NS + 5e9, "orderbook_delta", sid, 2,
               _delta_msg(TICKER, "yes", "0.42", "7"))
    # Cut off before the delta arrived.
    rec = h.verifier().reconstruct(TICKER, cutoff_utc_ns=_T0_NS + 1e9)
    assert rec.yes_bids == {Decimal("0.42"): Decimal("10")}
    assert rec.applied_through_seq == 1


def test_stale_book_flagged(h):
    conn, sid = CONN_A, 7
    h.feed_raw(conn, _T0_NS, "orderbook_snapshot", sid, 1,
               _snap_msg(TICKER, [["0.42", "10"]], [["0.50", "3"]]))
    rec = h.verifier().reconstruct(
        TICKER, cutoff_utc_ns=_T0_NS + 600e9, stale_after_s=30.0
    )
    assert rec.status == ST_OK_STALE
    assert rec.stale_s > 30


# ─────────────────────────────────────────────────────────────────────────────
# Envelope semantics
# ─────────────────────────────────────────────────────────────────────────────


def test_envelope_preserves_exchange_ts_and_context():
    msg = {"market_ticker": TICKER, "yes": [["0.42", "1"]], "no": [],
           "ts": "2026-11-04T14:15:01.123Z"}
    raw = json.dumps({"type": "orderbook_snapshot", "sid": 42, "seq": 9,
                      "msg": msg})
    env = envelope_from_frame(
        raw,
        received_at_utc_ns=_T0_NS,
        received_at_monotonic_ns=999,
        connection_id="c1",
        collector_instance_id="k1",
        recv_ordinal=1,
    )
    assert env.subscription_id == 42
    assert env.sequence_number == 9
    assert env.market_ticker == TICKER
    assert env.exchange_timestamp_raw == "2026-11-04T14:15:01.123Z"
    assert env.archive_event_id == "k1:c1:1"
    # No manufactured exchange ts when absent:
    raw2 = json.dumps({"type": "orderbook_delta", "sid": 42, "seq": 10,
                       "msg": _delta_msg(TICKER, "yes", "0.42", "1")})
    env2 = envelope_from_frame(
        raw2, received_at_utc_ns=_T0_NS, received_at_monotonic_ns=1000,
        connection_id="c1", collector_instance_id="k1", recv_ordinal=2,
    )
    assert env2.exchange_timestamp_raw is None
    assert env2.market_ticker == TICKER


def test_coverage_tracker_late_discovery_alert():
    tr = CoverageTracker()
    recs = tr.note_subscription(
        "c1", 7, [TICKER],
        ts_utc_ns=_T0_NS,
        market_meta={TICKER: {"open_ts": 100.0, "close_ts": 1000.0,
                              "discovered_at_utc_ns": _T0_NS,
                              "discovery_late": True}},
    )
    assert recs[0].discovery_late is True
    assert any(a.code == "late_discovery" for a in tr.alerts)


# ─────────────────────────────────────────────────────────────────────────────
# Control frames occupy the sid sequence space; retention honesty
# ─────────────────────────────────────────────────────────────────────────────


def _ok_msg(*tickers):
    return {"market_tickers": list(tickers)}


def test_seq_bearing_control_frame_advances_continuity(h):
    """An 'ok' ack stored between deltas must not register as a gap."""
    conn, sid = CONN_A, 7
    h.feed_raw(conn, _T0_NS, "orderbook_snapshot", sid, 1,
               _snap_msg(TICKER, [["0.42", "10"]], [["0.50", "3"]]))
    h.feed_raw(conn, _T0_NS + 1e9, "orderbook_delta", sid, 2,
               _delta_msg(TICKER, "yes", "0.42", "2"))
    # update_subscription acknowledgment consumes seq 3 on the same sid.
    h.feed_raw(conn, _T0_NS + 2e9, "ok", sid, 3,
               _ok_msg(TICKER, TICKER2))
    h.feed_raw(conn, _T0_NS + 3e9, "orderbook_delta", sid, 4,
               _delta_msg(TICKER, "yes", "0.41", "5"))

    rec = h.verifier().reconstruct(TICKER, cutoff_utc_ns=_T0_NS + 4e9)
    assert rec.status == ST_OK
    assert rec.yes_bids == {Decimal("0.42"): Decimal("12"),
                           Decimal("0.41"): Decimal("5")}
    cov = h.db.coverage_for(TICKER)[0]
    assert cov["state"] == COV_COVERING
    assert cov["gap_count"] == 0
    assert not any(a.code == ALERT_SEQ_GAP for a in h.tracker.alerts)


def test_pruned_snapshot_window_is_not_reconstructible(h):
    """Retention deleting a snapshot must not leave retained deltas that
    replay as 'ok' — the verifier reports them honestly."""
    conn, sid = CONN_A, 7
    h.feed_raw(conn, _T0_NS, "orderbook_snapshot", sid, 1,
               _snap_msg(TICKER, [["0.42", "10"]], [["0.50", "3"]]))
    h.feed_raw(conn, _T0_NS + 1e9, "orderbook_delta", sid, 2,
               _delta_msg(TICKER, "yes", "0.42", "2"))
    h.feed_raw(conn, _T0_NS + 2e9, "orderbook_delta", sid, 3,
               _delta_msg(TICKER, "yes", "0.41", "5"))
    assert h.verifier().reconstruct(
        TICKER, cutoff_utc_ns=_T0_NS + 3e9
    ).status == ST_OK

    # Retention horizon removes the snapshot; the deltas stay.
    h.db.prune(_T0_NS + 1_500_000_000)
    rec = h.verifier().reconstruct(TICKER, cutoff_utc_ns=_T0_NS + 3e9)
    assert rec.status != ST_OK
    assert rec.status in (ST_NO_SNAPSHOT, ST_GAPPED)
    assert rec.yes_bids == {}

"""P0 must not forget old uncertain submissions on restart."""

import time
import sqlite3
from types import SimpleNamespace

import pytest

from merid.event_venues.kalshi import order_attempt_store as attempts
from merid.preflight.p0 import _check_uncertain_submissions, run_p0_preflight_checks


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(attempts, "DEFAULT_DB_PATH", str(tmp_path / "attempts.db"))
    monkeypatch.setattr(attempts.OrderAttemptStore, "_instances", {})
    return attempts.OrderAttemptStore()


def test_empty_store_passes(store):
    assert _check_uncertain_submissions()[0]


@pytest.mark.parametrize("status", ["SUBMITTING", "SUBMISSION_UNKNOWN"])
def test_old_uncertain_attempt_fails_and_is_not_modified(store, status):
    old = time.time() - 400 * 86400
    store.persist_attempt(attempts.OrderAttemptRecord(
        order_attempt_id="oa-1", client_order_id="co-1", decision_id="dec-1",
        replaces_order_attempt_id=None, intent_id="intent-1", client_tag=None,
        run_id=None, process_id=None, fingerprint="fp-1", status=status,
        created_at=old, updated_at=old, payload_json="{}",
    ))
    assert not _check_uncertain_submissions()[0]
    assert store.get_by_order_attempt_id("oa-1").status == status
    assert store.get_unresolved() == []


def test_missing_store_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(attempts, "DEFAULT_DB_PATH", str(tmp_path / "missing.db"))
    assert not _check_uncertain_submissions()[0]
    assert not (tmp_path / "missing.db").exists()


def test_missing_exit_table_fails_closed(tmp_path, monkeypatch):
    path = tmp_path / "incomplete.db"
    monkeypatch.setattr(attempts, "DEFAULT_DB_PATH", str(path))
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE order_attempts (status TEXT)")
    assert not _check_uncertain_submissions()[0]


def test_uncertain_exit_attempt_fails(store):
    rec = store.create_exit_attempt(
        exit_intent_id="exit-1", position_key="pos-1",
        ticker="KXBTC15M-TEST", reason="test",
        client_order_id="exit-co-1", requested_quantity=100,
    )
    store.transition_exit_attempt(rec.attempt_id, "SUBMITTING", actor="test", reason="test")
    assert not _check_uncertain_submissions()[0]


@pytest.mark.asyncio
async def test_p0_stops_before_balance_or_funding(monkeypatch):
    monkeypatch.setattr(
        "merid.preflight.p0._check_uncertain_submissions",
        lambda: (False, "uncertain submissions"),
    )
    result = await run_p0_preflight_checks(
        client=SimpleNamespace(), bankroll=None, catalog=None,
    )
    assert result[-1] == (False, "uncertain submissions")

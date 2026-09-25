"""Orphaned decision-outcome sweep: markets evaluated-but-never-entered must
still get settled outcomes joined (portfolio/settlements is position-scoped)."""
import time
from unittest.mock import AsyncMock

import pytest

from merid.execution.decision_audit_ledger import DecisionAuditLedger


def _mk_ledger(tmp_path):
    led = DecisionAuditLedger(db_path=tmp_path / "audit.db")
    led._ensure_db()
    return led


def _insert_pending(ledger, decision_id, ticker, close_ts):
    conn = ledger._conn()
    with conn:
        conn.execute(
            "INSERT INTO strategy_decisions (decision_id, decision_ts, observed_at_ts, "
            "decision_ts_iso, strategy_name, strategy_version, model_version, "
            "config_version, ticker, asset, close_ts, close_ts_iso, seconds_to_close, "
            "settlement_reference, settlement_rule_version, decision, "
            "primary_reason_code, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                decision_id, close_ts - 300, close_ts - 300, "2026-09-25T00:00:00Z",
                "test", "v1", "m1", "cfg",
                ticker, "XRP", close_ts, "2026-09-25T00:15:00Z", 300.0,
                "rti", "v1", "NO_TRADE", "NO_EDGE", close_ts - 300,
            ),
        )
        conn.execute(
            "INSERT INTO strategy_decision_outcomes (decision_id, outcome_status) "
            "VALUES (?, 'PENDING')",
            (decision_id,),
        )


def test_pending_unsettled_tickers_finds_past_close_pending(tmp_path, monkeypatch):
    monkeypatch.setenv("MERID_DECISION_AUDIT_LEDGER_ENABLED", "1")
    led = _mk_ledger(tmp_path)
    now = time.time()
    _insert_pending(led, "d-old", "KXXRP15M-A", now - 3600)      # past close, pending -> hit
    _insert_pending(led, "d-fresh", "KXXRP15M-B", now - 60)    # inside grace -> skip
    _insert_pending(led, "d-future", "KXXRP15M-C", now + 600)  # not closed -> skip
    conn = led._conn()
    with conn:
        _d = dict(
            decision_id="d-settled", decision_ts=now - 4000, observed_at_ts=now - 4000,
            decision_ts_iso="2026-09-25T00:00:00Z", strategy_name="test",
            strategy_version="v1", model_version="m1", config_version="cfg",
            ticker="KXXRP15M-D", asset="XRP", close_ts=now - 3600,
            close_ts_iso="2026-09-25T01:00:00Z", seconds_to_close=300.0,
            settlement_reference="rti", settlement_rule_version="v1",
            decision="NO_TRADE", primary_reason_code="NO_EDGE", created_at=now - 4000,
        )
        conn.execute(
            "INSERT INTO strategy_decisions (decision_id, decision_ts, observed_at_ts, "
            "decision_ts_iso, strategy_name, strategy_version, model_version, "
            "config_version, ticker, asset, close_ts, close_ts_iso, seconds_to_close, "
            "settlement_reference, settlement_rule_version, decision, "
            "primary_reason_code, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            tuple(_d.values()),
        )
        conn.execute(
            "INSERT INTO strategy_decision_outcomes (decision_id, outcome_status) "
            "VALUES (?, 'SETTLED')",
            ("d-settled",),
        )
    out = led.pending_unsettled_tickers(now=now, grace_s=120.0)
    tickers = [t for t, _ in out]
    assert "KXXRP15M-A" in tickers
    assert "KXXRP15M-B" not in tickers
    assert "KXXRP15M-C" not in tickers
    assert "KXXRP15M-D" not in tickers


@pytest.mark.asyncio
async def test_sweep_joins_exchange_result_and_writes_outcome(tmp_path, monkeypatch):
    from merid.event_venues.kalshi.settlement_poller import KalshiSettlementPoller
    import merid.execution.decision_audit_ledger as dal

    led = dal.reset_decision_audit_ledger(db_path=tmp_path / "audit.db")
    led._ensure_db()
    now = time.time()
    _insert_pending(led, "d1", "KXXRP15M-26SEP251300-15", now - 1800)
    monkeypatch.setenv("MERID_DECISION_AUDIT_ENABLED", "1")
    monkeypatch.setenv("MERID_SETTLEMENT_SWEEP_ENABLED", "1")

    poller = KalshiSettlementPoller.__new__(KalshiSettlementPoller)
    poller.client = None

    async def fake_api(method, endpoint, params=None, **_):
        return {
            "market": {
                "ticker": "KXXRP15M-26SEP251300-15",
                "series_ticker": "KXXRP15M",
                "status": "settled",
                "result": "no",
                "settlement_time": "2026-09-25T17:00:30Z",
            }
        }

    poller._api_call_with_retry = fake_api  # type: ignore[attr-defined]
    monkeypatch.setattr(
        "merid.analysis.settlement_outcome_exporter.DEFAULT_OUT_PATH",
        str(tmp_path / "outcomes.jsonl"),
    )
    await poller._sweep_orphaned_decision_outcomes()

    rows = led._conn().execute(
        "SELECT outcome_status, settled_yes FROM strategy_decision_outcomes WHERE decision_id='d1'"
    ).fetchall()
    assert rows and rows[0][0] == "SETTLED" and rows[0][1] == 0


@pytest.mark.asyncio
async def test_sweep_skips_unsettled_markets(tmp_path, monkeypatch):
    from merid.event_venues.kalshi.settlement_poller import KalshiSettlementPoller
    import merid.execution.decision_audit_ledger as dal

    led = dal.reset_decision_audit_ledger(db_path=tmp_path / "audit.db")
    led._ensure_db()
    now = time.time()
    _insert_pending(led, "d1", "KXBTC15M-X", now - 1800)
    monkeypatch.setenv("MERID_SETTLEMENT_SWEEP_ENABLED", "1")

    poller = KalshiSettlementPoller.__new__(KalshiSettlementPoller)
    poller.client = None

    async def fake_api(method, endpoint, params=None, **_):
        return {"market": {"ticker": "KXBTC15M-X", "status": "active"}}

    poller._api_call_with_retry = fake_api  # type: ignore[attr-defined]
    await poller._sweep_orphaned_decision_outcomes()
    rows = led._conn().execute(
        "SELECT outcome_status FROM strategy_decision_outcomes WHERE decision_id='d1'"
    ).fetchall()
    assert rows[0][0] == "PENDING"

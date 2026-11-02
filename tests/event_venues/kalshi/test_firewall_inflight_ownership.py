"""The exit firewall must not forget unresolved submissions by age."""

import json
import time
from types import SimpleNamespace

import pytest

from merid.event_venues.kalshi import order_attempt_store as attempts
from merid.event_venues.kalshi.execution_risk_firewall import ExecutionRiskFirewall
from tests.test_exit_price_path_firewall import (
    BTC_TICKER, _btc_book, _firewall, _loss_cap_canonical, _pos, _run,
)


def _record(coid, intent_id, payload):
    return attempts.OrderAttemptRecord(
        order_attempt_id="attempt-" + coid, client_order_id=coid,
        decision_id=None, replaces_order_attempt_id=None, intent_id=intent_id,
        client_tag=coid, run_id=None, process_id=None, fingerprint=coid,
        status="SUBMISSION_UNKNOWN", created_at=time.time() - 3600,
        updated_at=time.time() - 3600, payload_json=json.dumps(payload),
    )


@pytest.mark.parametrize("direction", ["exit", None])
def test_old_unresolved_nested_order_blocks_exit(tmp_path, monkeypatch, direction):
    store = attempts.OrderAttemptStore(tmp_path / "attempts.db")
    record = _record("old", "old-intent", {
        "order": {"ticker": BTC_TICKER}, "entry_or_exit": direction,
    })
    store.persist_attempt(record)
    monkeypatch.setattr(attempts, "OrderAttemptStore", lambda: store)
    canonical = SimpleNamespace(
        market_ticker=BTC_TICKER, client_order_id="new", intent_id="new-intent"
    )
    assert store.get_unresolved() == []
    assert ExecutionRiskFirewall()._has_in_flight_exit(canonical) == record


def test_own_claim_and_confirmed_entry_do_not_block_exit(tmp_path, monkeypatch):
    store = attempts.OrderAttemptStore(tmp_path / "attempts.db")
    store.persist_attempt(_record("own", "own-intent", {
        "order": {"ticker": BTC_TICKER}, "entry_or_exit": "exit",
    }))
    store.persist_attempt(_record("entry", "entry-intent", {
        "order": {"ticker": BTC_TICKER}, "entry_or_exit": "entry",
    }))
    monkeypatch.setattr(attempts, "OrderAttemptStore", lambda: store)
    canonical = SimpleNamespace(
        market_ticker=BTC_TICKER, client_order_id="own", intent_id="own-intent"
    )
    assert ExecutionRiskFirewall()._has_in_flight_exit(canonical) is None


def test_unavailable_attempt_store_denies_even_in_observe_mode(monkeypatch):
    fw, _ = _firewall(monkeypatch, pos=_pos(), book=_btc_book())
    def unavailable(_canonical):
        raise RuntimeError("store unavailable")
    monkeypatch.setattr(fw, "_has_in_flight_exit", unavailable)
    monkeypatch.setattr(fw, "_is_enforced", lambda: False)
    decision = _run(fw, _loss_cap_canonical())
    assert decision.status == "rejected"
    assert "in_flight_exit_check_unavailable" in decision.reason

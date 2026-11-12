"""Unit tests for the explicit entry-approval state machine.

Every risk-increasing entry must resolve to APPROVED with a positive
centi-contract ceiling; zero is a rejection, missing state is UNAVAILABLE,
and stale decisions are EXPIRED.
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from merid.prediction.entry_approval import (
    ApprovalState,
    approval_enforced,
    resolve_entry_approval,
)


def _td(*, selected="yes", size_cc=Decimal("600"), age_s=5.0, decision_id="dec-1", with_ts=True):
    ts = datetime.now(timezone.utc) - timedelta(seconds=age_s) if with_ts else None
    return SimpleNamespace(
        selected_outcome=selected,
        approved_size_cc=size_cc,
        decision_id=decision_id,
        timestamp_utc=ts,
        policy_version="trade_decision_v2",
        config_hash="abc",
        no_trade_reason=None,
    )


def test_missing_trade_decision_is_unavailable():
    a = resolve_entry_approval({"ticker": "KXBTC15M-X"})
    assert a.state is ApprovalState.UNAVAILABLE
    assert a.reason == "missing_trade_decision"
    assert a.ceiling_cc is None


def test_no_selected_outcome_is_rejected():
    td = _td(selected=None, size_cc=Decimal("0"))
    td.no_trade_reason = "ev_gate_rejected"
    a = resolve_entry_approval({"trade_decision": td})
    assert a.state is ApprovalState.REJECTED
    assert a.reason == "no_selected_outcome"


def test_zero_approval_is_rejected_not_unbounded():
    a = resolve_entry_approval({"trade_decision": _td(size_cc=Decimal("0"))})
    assert a.state is ApprovalState.REJECTED
    assert a.reason == "approved_size_zero"
    assert a.ceiling_cc == 0


def test_negative_approval_is_rejected():
    a = resolve_entry_approval({"trade_decision": _td(size_cc=Decimal("-50"))})
    assert a.state is ApprovalState.REJECTED


def test_missing_approved_size_is_unavailable():
    td = _td()
    td.approved_size_cc = None
    a = resolve_entry_approval({"trade_decision": td})
    assert a.state is ApprovalState.UNAVAILABLE
    assert a.reason == "approved_size_missing"


def test_unparseable_approved_size_is_unavailable():
    td = _td()
    td.approved_size_cc = "not-a-number"
    a = resolve_entry_approval({"trade_decision": td})
    assert a.state is ApprovalState.UNAVAILABLE
    assert a.reason == "approved_size_unparseable"


def test_missing_timestamp_is_unavailable():
    a = resolve_entry_approval({"trade_decision": _td(with_ts=False)})
    assert a.state is ApprovalState.UNAVAILABLE
    assert a.reason == "decision_timestamp_missing"


def test_future_timestamp_is_unavailable():
    td = _td(age_s=-30.0)
    a = resolve_entry_approval({"trade_decision": td})
    assert a.state is ApprovalState.UNAVAILABLE
    assert a.reason == "decision_timestamp_future"


def test_expired_decision():
    a = resolve_entry_approval({"trade_decision": _td(age_s=500.0)})
    assert a.state is ApprovalState.EXPIRED
    assert a.reason == "decision_expired"
    assert a.ceiling_cc == 600


def test_expiry_respects_env_max_age(monkeypatch):
    monkeypatch.setenv("MERID_ENTRY_APPROVAL_MAX_AGE_S", "10")
    a = resolve_entry_approval({"trade_decision": _td(age_s=30.0)})
    assert a.state is ApprovalState.EXPIRED
    monkeypatch.setenv("MERID_ENTRY_APPROVAL_MAX_AGE_S", "120")
    a = resolve_entry_approval({"trade_decision": _td(age_s=30.0)})
    assert a.state is ApprovalState.APPROVED


def test_positive_approval_carries_ceiling():
    a = resolve_entry_approval({"trade_decision": _td(size_cc=Decimal("150"), age_s=2.0)})
    assert a.state is ApprovalState.APPROVED
    assert a.ceiling_cc == 150
    assert a.decision_id == "dec-1"
    assert a.detail["policy_version"] == "trade_decision_v2"


def test_fractional_centi_contracts_floor():
    a = resolve_entry_approval({"trade_decision": _td(size_cc=Decimal("150.9"))})
    assert a.state is ApprovalState.APPROVED
    assert a.ceiling_cc == 150


def test_isoformat_timestamp_accepted():
    td = _td()
    td.timestamp_utc = (datetime.now(timezone.utc) - timedelta(seconds=3)).isoformat()
    a = resolve_entry_approval({"trade_decision": td})
    assert a.state is ApprovalState.APPROVED


def test_naive_datetime_treated_as_utc():
    td = _td()
    td.timestamp_utc = datetime.utcnow() - timedelta(seconds=3)
    a = resolve_entry_approval({"trade_decision": td})
    assert a.state is ApprovalState.APPROVED


def test_candidate_decision_id_fallback():
    td = _td(decision_id=None)
    a = resolve_entry_approval({"trade_decision": td, "decision_id": "cand-did"})
    assert a.state is ApprovalState.APPROVED
    assert a.decision_id == "cand-did"


def test_enforcement_flag(monkeypatch):
    monkeypatch.setenv("MERID_ENTRY_APPROVAL_ENFORCED", "1")
    assert approval_enforced() is True
    monkeypatch.setenv("MERID_ENTRY_APPROVAL_ENFORCED", "0")
    assert approval_enforced() is False

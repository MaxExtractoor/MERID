"""Tiered evidence-artifact health (FRESH / DEGRADED / STALE / UNUSABLE)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import merid.prediction.trade_decision as _td
from merid.prediction import evidence_health as eh
from merid.prediction import evidence_policy
from merid.prediction.threshold_cells import SOFT_EVIDENCE_CODES
from merid.prediction.trade_decision import _clear_live_evidence_cache

NOW = 1_800_000_000.0


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    for k in (
        "MERID_EVIDENCE_OPERATOR_OVERRIDE_UNTIL",
        "MERID_EVIDENCE_DEGRADED_AFTER_S",
        "MERID_EVIDENCE_STALE_AFTER_S",
        "MERID_EVIDENCE_UNUSABLE_AFTER_S",
    ):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("MERID_LIVE_EVIDENCE_EXPORT", "1")
    eh._reset_for_tests()
    yield
    eh._reset_for_tests()


def _art(age_s: float) -> dict:
    return {"generated_at": NOW - age_s, "cells": {"7": {}}}


@pytest.mark.parametrize(
    "age_s,state,action",
    [
        (60, eh.FRESH, "allow"),
        (900, eh.FRESH, "allow"),
        (1800, eh.DEGRADED, "downsize"),
        (7200, eh.STALE, "fallback"),
        (8 * 3600, eh.UNUSABLE, "block"),
    ],
)
def test_age_tiers(age_s, state, action):
    h = eh.assess(_art(age_s), now=NOW)
    assert h.state == state
    assert h.decision_action == action
    assert h.age_s == pytest.approx(age_s)


def test_missing_or_corrupt_artifact_is_unusable():
    h = eh.assess({"artifact_missing": True, "generated_at": 0.0}, now=NOW)
    assert h.state == eh.UNUSABLE
    assert h.artifact_parse_ok is False
    assert h.age_s is None


def test_age_falls_back_to_mtime_without_generated_at():
    h = eh.assess({"cells": {}}, artifact_mtime=NOW - 1800, now=NOW)
    assert h.state == eh.DEGRADED


def test_degraded_controls():
    fresh = eh.assess(_art(60), now=NOW)
    deg = eh.assess(_art(1800), now=NOW)
    stale = eh.assess(_art(7200), now=NOW)
    assert fresh.max_contracts is None and fresh.margin_uplift_frac == 0.0
    assert deg.max_contracts == 1
    assert deg.margin_uplift_frac == pytest.approx(0.01)
    assert deg.score_cells and fresh.score_cells
    assert not stale.score_cells and stale.max_contracts == 1


def test_operator_override_holds_unusable_at_stale_until_expiry(monkeypatch):
    monkeypatch.setenv("MERID_LIVE_EVIDENCE_EXPORT", "0")
    monkeypatch.setenv("MERID_EVIDENCE_OPERATOR_OVERRIDE_UNTIL", str(NOW + 3600))
    h = eh.assess(_art(8 * 3600), now=NOW)
    assert h.state == eh.STALE
    assert h.age_state == eh.UNUSABLE
    assert h.mode == "DISABLED_OPERATOR_OVERRIDE"
    expired = eh.assess(_art(8 * 3600), now=NOW + 7200)
    assert expired.state == eh.UNUSABLE
    assert expired.mode == "EXPORT_DISABLED"


def test_override_never_upgrades_a_better_state(monkeypatch):
    monkeypatch.setenv("MERID_EVIDENCE_OPERATOR_OVERRIDE_UNTIL", str(NOW + 3600))
    assert eh.assess(_art(60), now=NOW).state == eh.FRESH


def test_override_iso_requires_timezone(monkeypatch):
    monkeypatch.setenv("MERID_EVIDENCE_OPERATOR_OVERRIDE_UNTIL", "2030-01-01T00:00:00")
    assert eh.override_until() is None
    monkeypatch.setenv("MERID_EVIDENCE_OPERATOR_OVERRIDE_UNTIL", "2030-01-01T00:00:00+00:00")
    assert eh.override_until() == pytest.approx(1893456000.0)


def test_transition_logged_once_per_state(monkeypatch):
    calls = []

    class _Stub:
        def __getattr__(self, level):
            return lambda msg, *a: calls.append((level, msg % a))

    monkeypatch.setattr(eh, "logger", _Stub())
    monkeypatch.setenv("MERID_EVIDENCE_HEALTH_ALERT_EVERY_S", "600")
    eh.assess(_art(60), now=NOW)
    eh.assess(_art(61), now=NOW + 1)
    assert [c[0] for c in calls] == ["info"]
    eh.assess(_art(1800), now=NOW + 2)
    assert calls[-1][0] == "warning" and "[EVIDENCE_DEGRADED] transition" in calls[-1][1]
    eh.assess(_art(1801), now=NOW + 3)
    assert len(calls) == 2
    # recurring reminder while non-FRESH
    eh.assess(_art(2500), now=NOW + 700)
    assert "[EVIDENCE_DEGRADED] still" in calls[-1][1]


def test_refresh_status_feeds_health():
    eh.record_refresh_attempt(NOW - 30)
    eh.record_refresh_result(False, "query: timeout")
    eh.record_refresh_result(False, "query: timeout")
    h = eh.assess(_art(60), now=NOW)
    assert h.refresh_failure_streak == 2
    assert h.last_refresh_attempt_at == NOW - 30
    assert h.last_refresh_success_at == pytest.approx(NOW - 60)
    eh.record_refresh_result(True, ts=NOW - 5)
    h = eh.assess(_art(60), now=NOW)
    assert h.refresh_failure_streak == 0
    assert h.last_refresh_success_at == NOW - 5


def test_unusable_verdict_is_hard_and_unescapable():
    d = evidence_policy.evaluate_unusable(
        "BTC", "no", 55.0, 400.0, age_s=99999.0, reason="test"
    )
    assert d.allowed is False
    assert d.code == "EVIDENCE_UNUSABLE"
    assert d.code not in SOFT_EVIDENCE_CODES
    assert d.escape_required is False


def test_stale_fallback_is_coded_distinctly():
    d = evidence_policy.evaluate_missing_artifact(
        "BTC", "no", 55.0, 400.0, 0.01, 0.015, 10.0, artifact_state="stale"
    )
    assert d.code.startswith("EVIDENCE_ARTIFACT_STALE")
    assert d.escape_required is True


# ── compute_trade_decision integration ───────────────────────────────


@pytest.fixture
def _evidence_path(monkeypatch, tmp_path):
    path = tmp_path / "live_entry_evidence.json"
    monkeypatch.setenv("MERID_LIVE_EVIDENCE_PATH", str(path))
    monkeypatch.setattr(_td, "MERID_LIVE_EVIDENCE_GATE", True)
    monkeypatch.setattr(_td, "MERID_CALIBRATION_CAP_FULL_RANGE", False)
    monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MIN_W", 0.0)
    monkeypatch.setattr(_td, "MERID_MARKET_ANCHOR_MAX_W", 0.0)
    _clear_live_evidence_cache()
    yield path
    _clear_live_evidence_cache()


def _write(path: Path, age_s: float) -> None:
    path.write_text(json.dumps({
        "version": 2, "generated_at": time.time() - age_s, "window_hours": 48,
        "assets": {}, "cells": {"7": {}},
    }))
    _clear_live_evidence_cache()


def _decide(**kw):
    args = dict(
        run_id="r", decision_id="d", ticker="KXBTC15M-26SEP282100-00",
        asset="BTC", spot_price=99.5, strike_price=100.0, seconds_to_expiry=900.0,
        yes_bid_cents=40.0, yes_ask_cents=42.0, no_bid_cents=56.0, no_ask_cents=58.0,
        yes_depth_cc=200.0, no_depth_cc=200.0, fee_per_contract_cents=1.0,
        data_quality="live", regime="normal", settlement_reference="cfb_rti_live",
    )
    args.update(kw)
    return _td.compute_trade_decision(**args)


@pytest.mark.parametrize(
    "age_s,state", [(60, "FRESH"), (1800, "DEGRADED"), (7200, "STALE"), (8 * 3600, "UNUSABLE")]
)
def test_decision_records_evidence_state_per_side(_evidence_path, age_s, state):
    _write(_evidence_path, age_s)
    d = _decide()
    ind = d.indicators
    assert ind["evidence_health"]["evidence_state"] == state
    for side in ("yes", "no"):
        assert ind[f"{side}_evidence_state"] == state
        assert ind[f"{side}_evidence_binding_gate"]
        assert ind[f"{side}_evidence_action"] in ("allow", "downsize", "fallback", "block")
    if state == "UNUSABLE":
        assert ind["yes_evidence_binding_gate"] == "EVIDENCE_UNUSABLE"
        assert ind["no_evidence_action"] == "block"
    if state == "STALE":
        assert ind["no_evidence_binding_gate"].startswith("EVIDENCE_ARTIFACT_STALE")


def test_unusable_evidence_blocks_evidence_dependent_entry(_evidence_path):
    """Outside the provisional/settlement lanes (TTE 900s), an 8h-old
    artifact must not admit: the side is blocked by EVIDENCE_UNUSABLE."""
    _write(_evidence_path, 8 * 3600)
    d = _decide()
    assert d.selected_outcome is None
    assert "evidence_unusable" in (d.no_trade_reason or "")


def test_degraded_caps_size_to_one_contract(_evidence_path, monkeypatch):
    monkeypatch.setenv("MERID_MAX_CONTRACTS_PER_ORDER", "3")
    _write(_evidence_path, 1800)
    d = _decide()
    if d.selected_outcome is None:
        pytest.skip("fixture candidate not admitted under DEGRADED margin")
    assert int(d.approved_size_cc) == 100
    assert d.indicators["evidence_size_cap"]["capped_contracts"] == 1

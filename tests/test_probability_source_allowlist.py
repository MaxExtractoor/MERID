"""Probability-source allowlist + contract-spec containment tests (2026-11-18).

The live decision must be physically unable to consume a probability produced
by the hybrid/indicator delta stack unless the resolved live config explicitly
allowlists it AND the delta stack is enabled.  These tests cover:

- Resolution semantics: allowlist parsing, unknown-source rejection, delta-
  stack containment, and the ALLOW_HYBRID_P request vs. grant distinction.
- Decision-level containment: ``p_yes_model`` cannot move any decision field
  when the source is denied — including when the legacy module flag is
  permissive but the resolved allowlist is not (the resolved config is
  authoritative).
- Contract-spec validation: arithmetic-mean RTI rules are compatible;
  trimmed/filtered aggregations, absent rules, and foreign fee schedules are
  rejected rather than silently priced on the assumed model.
"""
from __future__ import annotations

import pytest

import merid.prediction.trade_decision as _td
from merid.config.live_config import (
    LiveConfigInvariantError,
    resolve_live_config,
    reset_resolved_live_config,
)
from merid.event_venues.kalshi.contract_spec import (
    IMPLEMENTED_AGGREGATION,
    evaluate_market_contract,
    extract_market_contract_fields,
)
from merid.prediction.trade_decision import compute_trade_decision


def _decision(p_yes_model=None):
    return compute_trade_decision(
        run_id="test_run",
        decision_id="test_decision",
        ticker="KXBTC15M-26SEP282100-00",
        asset="BTC",
        spot_price=99.5,
        strike_price=100.0,
        seconds_to_expiry=900.0,
        yes_bid_cents=40.0,
        yes_ask_cents=42.0,
        no_bid_cents=56.0,
        no_ask_cents=58.0,
        yes_depth_cc=200.0,
        no_depth_cc=200.0,
        fee_per_contract_cents=1.0,
        data_quality="live",
        regime="normal",
        settlement_reference="cfb_rti_live",
        p_yes_model=p_yes_model,
    )


def _decision_fields(d):
    return (
        d.p_yes_raw,
        d.p_yes_calibrated,
        d.p_no_calibrated,
        d.yes_net_edge,
        d.no_net_edge,
        d.selected_outcome,
        d.selected_action,
        d.no_trade_reason,
    )


# ── Resolution semantics ─────────────────────────────────────────────────────


def test_default_allowlist_is_settlement_only():
    resolved = resolve_live_config()
    try:
        assert resolved.resolved
        assert "settlement_rti_bachelier_v2" in resolved.allowed_probability_sources
        # .env keeps the hybrid delta stack disabled; it must never appear.
        assert "hybrid_bachelier_deltas" not in resolved.allowed_probability_sources
    finally:
        reset_resolved_live_config()


def test_allowlist_strips_hybrid_when_deltas_disabled(monkeypatch):
    monkeypatch.setenv(
        "MERID_ALLOWED_PROBABILITY_SOURCES",
        "settlement_rti_bachelier_v2,hybrid_bachelier_deltas",
    )
    # Delta stack stays disabled (BACHELIER_ONLY=1 / DISABLE_ALL_DELTAS=1 in .env).
    resolved = resolve_live_config()
    try:
        assert resolved.allowed_probability_sources == ("settlement_rti_bachelier_v2",)
        assert any(
            "hybrid_bachelier_deltas" in c for c in resolved.conflicts_caught
        )
    finally:
        reset_resolved_live_config()


def test_allowlist_unknown_source_dropped_empty_fails_closed(monkeypatch):
    monkeypatch.setenv("MERID_ALLOWED_PROBABILITY_SOURCES", "fvg_momentum_v9")
    with pytest.raises(LiveConfigInvariantError):
        resolve_live_config()
    reset_resolved_live_config()


def test_allow_hybrid_p_request_denied_when_not_allowlisted(monkeypatch):
    monkeypatch.setenv("MERID_TRADE_DECISION_ALLOW_HYBRID_P", "1")
    resolved = resolve_live_config()
    try:
        assert "hybrid_bachelier_deltas" not in resolved.allowed_probability_sources
        assert any("ALLOW_HYBRID_P" in c for c in resolved.conflicts_caught)
    finally:
        reset_resolved_live_config()


# ── Decision-level containment ───────────────────────────────────────────────


def test_p_yes_model_inert_when_flag_denied(monkeypatch):
    """Unresolved fallback + flag False -> the external probability is ignored."""
    monkeypatch.setattr(_td, "MERID_TRADE_DECISION_ALLOW_HYBRID_P", False)
    denied = _decision(p_yes_model=0.99)
    baseline = _decision(p_yes_model=None)
    assert _decision_fields(denied) == _decision_fields(baseline)


def test_p_yes_model_inert_under_resolved_allowlist(monkeypatch):
    """The resolved allowlist is authoritative: even a permissive legacy flag
    cannot admit the hybrid source once the config resolves settlement-only."""
    monkeypatch.setattr(_td, "MERID_TRADE_DECISION_ALLOW_HYBRID_P", True)
    resolved = resolve_live_config()
    try:
        assert "hybrid_bachelier_deltas" not in resolved.allowed_probability_sources
        denied = _decision(p_yes_model=0.99)
        baseline = _decision(p_yes_model=None)
        assert _decision_fields(denied) == _decision_fields(baseline)
    finally:
        reset_resolved_live_config()


def test_p_yes_model_admitted_only_when_flag_permits(monkeypatch):
    """Sanity: on the unresolved fallback path, flag True admits the model —
    this documents the gate location, not a live-approved source."""
    monkeypatch.setattr(_td, "MERID_TRADE_DECISION_ALLOW_HYBRID_P", True)
    admitted = _decision(p_yes_model=0.99)
    baseline = _decision(p_yes_model=None)
    # p_yes_raw always records the Bachelier output; the admitted model value
    # propagates through p_yes_for_yes -> p_yes_calibrated and the edges.
    assert admitted.p_yes_calibrated != baseline.p_yes_calibrated


# ── Contract-spec validation ─────────────────────────────────────────────────

_RTI_MEAN_RULES = {
    "rules_primary": (
        "The expiration value is the arithmetic mean of the CF Benchmarks "
        "Bitcoin Real-Time Index (BRTI) values published at one-second "
        "intervals during the final 60 seconds preceding expiration."
    ),
    "rules_secondary": None,
    "resolution_source": "CF Benchmarks",
    "fee_type": "quadratic_with_maker_fees",
    "fee_multiplier": "1.0",
    "fee_waiver_expiration_time_ms": None,
}


def test_contract_spec_accepts_rti_mean_60s():
    spec = evaluate_market_contract(dict(_RTI_MEAN_RULES), ticker="KXBTC15M-T1")
    assert spec.recognized is True
    assert spec.compatible is True
    assert spec.aggregation == IMPLEMENTED_AGGREGATION
    assert spec.reference == "cf_benchmarks_rti"
    assert spec.expected_sample_count == 60
    assert spec.window_seconds == 60
    assert spec.sample_interval_seconds == 1
    assert spec.rules_sha256 is not None


def test_contract_spec_rejects_trimmed_mean():
    fields = dict(_RTI_MEAN_RULES)
    fields["rules_primary"] = (
        "The expiration value is the trimmed mean of the CF Benchmarks BRTI "
        "values over the final 60 seconds, excluding the highest 20% and "
        "lowest 20% of observations."
    )
    spec = evaluate_market_contract(fields, ticker="KXBTC15M-T2")
    assert spec.aggregation == "filtered_mean"
    assert spec.compatible is False
    assert any("trimmed" in r or "unsupported" in r for r in spec.reasons)


def test_contract_spec_rejects_absent_rules():
    spec = evaluate_market_contract(
        {"fee_type": "quadratic", "fee_multiplier": 1.0}, ticker="KXBTC15M-T3"
    )
    assert spec.compatible is False
    assert "rules_text_absent" in spec.reasons
    assert spec.rules_sha256 is None


def test_contract_spec_rejects_unrecognized_aggregation():
    fields = dict(_RTI_MEAN_RULES)
    fields["rules_primary"] = "Resolves per the published settlement procedure."
    fields["resolution_source"] = None
    spec = evaluate_market_contract(fields, ticker="KXBTC15M-T4")
    assert spec.compatible is False
    assert "aggregation_unrecognized" in spec.reasons


def test_contract_spec_rejects_foreign_fee_multiplier():
    fields = dict(_RTI_MEAN_RULES)
    fields["fee_multiplier"] = 0.5
    spec = evaluate_market_contract(fields, ticker="KXBTC15M-T5")
    assert spec.compatible is False
    assert any(r.startswith("fee_multiplier_mismatch") for r in spec.reasons)


def test_contract_spec_rejects_unsupported_fee_type():
    fields = dict(_RTI_MEAN_RULES)
    fields["fee_type"] = "flat_per_contract"
    spec = evaluate_market_contract(fields, ticker="KXBTC15M-T6")
    assert spec.compatible is False
    assert any(r.startswith("fee_type_unsupported") for r in spec.reasons)


def test_contract_spec_absent_fee_metadata_unverified_not_rejected():
    """Kalshi does not publish fee_type/fee_multiplier on every market record.

    Absent fee metadata is *unverified*, not a declared mismatch: the
    configured schedule stays active and the per-fill fee audit remains the
    drift detector.  Declared-but-wrong metadata stays fatal (covered by the
    multiplier/type rejection tests above).
    """
    fields = dict(_RTI_MEAN_RULES)
    del fields["fee_type"]
    del fields["fee_multiplier"]
    spec = evaluate_market_contract(fields, ticker="KXBTC15M-T7")
    assert spec.compatible is True
    assert spec.fee_verified is False
    assert "fee_metadata_unverified" in spec.reasons


def test_contract_spec_maker_unverified_demotes_not_rejects():
    fields = dict(_RTI_MEAN_RULES)
    fields["fee_type"] = "quadratic"  # no maker-fees clause
    spec = evaluate_market_contract(
        fields, ticker="KXBTC15M-T8", maker_entries_enabled=True
    )
    assert spec.compatible is True          # taker lane still valid
    assert spec.maker_fee_verified is False  # maker lane must be disabled


def test_contract_spec_hash_is_stable_and_sensitive():
    a = evaluate_market_contract(dict(_RTI_MEAN_RULES), ticker="KXBTC15M-T9")
    b = evaluate_market_contract(dict(_RTI_MEAN_RULES), ticker="KXBTC15M-T9")
    assert a.rules_sha256 == b.rules_sha256
    fields = dict(_RTI_MEAN_RULES)
    fields["rules_primary"] += " "
    c = evaluate_market_contract(fields, ticker="KXBTC15M-T9")
    assert c.rules_sha256 != a.rules_sha256


def test_contract_spec_accepts_live_kalshi_rule_wording():
    """The verbatim live Kalshi 15m rule text must validate.

    Regression: the live payload spells the window out ("sixty seconds" /
    "the last minute") and declares "60 RTI prices are collected" rather
    than a literal "60 seconds" / "per second" — a parser that only accepts
    digits rejects every real contract.
    """
    fields = {
        "rules_primary": (
            "If the simple average of the sixty seconds of CF Benchmarks' "
            "BRTI before 8:45 PM EDT on Sep 28, 2026 is at least the simple "
            "average of the sixty seconds of CF Benchmarks' BRTI before "
            "8:30 PM EDT on September 28, 2026, then the market resolves "
            "to Yes."
        ),
        "rules_secondary": (
            "Not all cryptocurrency price data is the same. While checking "
            "a source like Google or Coinbase may help guide your decision, "
            "the price used to determine this market is based on CF "
            "Benchmarks' corresponding Real Time Index (RTI). At the last "
            "minute before expiration, 60 RTI prices are collected. The "
            "official and final value is the average of these prices, "
            "rounded to the nearest 2 decimal places."
        ),
        # fee_type / fee_multiplier / resolution_source deliberately absent:
        # the live market payload does not carry them.
    }
    spec = evaluate_market_contract(fields, ticker="KXBTC15M-26SEP282045-45")
    assert spec.recognized is True
    assert spec.aggregation == IMPLEMENTED_AGGREGATION
    assert spec.reference == "cf_benchmarks_rti"
    assert spec.window_seconds == 60
    assert spec.sample_interval_seconds == 1
    assert spec.expected_sample_count == 60
    assert spec.compatible is True
    assert spec.fee_verified is False
    assert "fee_metadata_unverified" in spec.reasons


def test_extract_fields_from_event_market_raw_data():
    class FakeEventMarket:
        raw_data = dict(_RTI_MEAN_RULES)

    class FakeCatalogMarket:
        market = FakeEventMarket()

    out = extract_market_contract_fields(FakeEventMarket(), FakeCatalogMarket())
    assert out["fee_type"] == "quadratic_with_maker_fees"
    assert "final 60 seconds" in out["rules_primary"]

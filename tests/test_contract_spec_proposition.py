"""YES-proposition validation tests for contract_spec (2026-11-19).

The settlement-aggregation check verifies *how* the official value is
computed; the proposition check verifies *which side of the reference wins
YES*.  The decision model prices ``P(settlement_measure > reference)`` —
YES must pay on the upward claim.  These tests cover:

- The verbatim live Kalshi 15m up/down rule wording ("is at least" the
  opening-window average) validates as ``reference_ge``.
- Strict upward comparisons ("above", "greater than") validate as
  ``reference_gt``.
- Inverted claims ("below", "at most"), two-sided ranges, directional
  language, contradictory wording, absent clauses, and non-price operands
  all fail closed.
- Structured strike metadata (``cap_strike``, ``custom_strike.cap_strike``,
  ``strike_type`` range/bracket) rejects range markets even when the rules
  text looks like a threshold comparison.
"""
from __future__ import annotations

from merid.event_venues.kalshi.contract_spec import (
    evaluate_market_contract,
    extract_market_contract_fields,
)

_BASE = {
    "rules_secondary": (
        "Not all cryptocurrency price data is the same. While checking "
        "a source like Google or Coinbase may help guide your decision, "
        "the price used to determine this market is based on CF "
        "Benchmarks' corresponding Real Time Index (RTI). At the last "
        "minute before expiration, 60 RTI prices are collected. The "
        "official and final value is the average of these prices, "
        "rounded to the nearest 2 decimal places."
    ),
    "fee_type": "quadratic",
    "fee_multiplier": 1.0,
}

_LIVE_UPDOWN = {
    "rules_primary": (
        "If the simple average of the sixty seconds of CF Benchmarks' BRTI "
        "before 8:45 PM EDT on Sep 28, 2026 is at least the simple average "
        "of the sixty seconds of CF Benchmarks' BRTI before 8:30 PM EDT on "
        "September 28, 2026, then the market resolves to Yes."
    ),
}


def _eval(primary: str, **extra):
    fields = dict(_BASE)
    fields["rules_primary"] = primary
    fields.update(extra)
    return evaluate_market_contract(fields, ticker="KXBTC15M-26SEP282045-45")


# ── Compatible propositions ────────────────────────────────────────────────


def test_live_updown_wording_is_reference_ge():
    fields = dict(_BASE)
    fields.update(_LIVE_UPDOWN)
    spec = evaluate_market_contract(fields, ticker="KXBTC15M-26SEP282045-45")
    assert spec.compatible is True
    assert spec.proposition == "reference_ge"
    assert spec.proposition_comparison == "ge"


def test_strict_above_is_reference_gt():
    spec = _eval(
        "If the CF Benchmarks RTI value is above the opening reference "
        "value, then the market resolves to Yes."
    )
    assert spec.compatible is True
    assert spec.proposition == "reference_gt"
    assert spec.proposition_comparison == "gt"


def test_reversed_anchor_phrasing():
    spec = _eval(
        "The market resolves to Yes if the settlement index is greater "
        "than the reference level."
    )
    assert spec.compatible is True
    assert spec.proposition == "reference_gt"


def test_negated_below_is_ge():
    spec = _eval(
        "If the index value is not below the reference price, the market "
        "resolves to Yes."
    )
    assert spec.compatible is True
    assert spec.proposition == "reference_ge"


def test_equal_to_or_above_is_ge_not_contradictory():
    """Compound ge phrasing must not double-count the bare 'above' as gt."""
    spec = _eval(
        "If the price is equal to or above the strike, the market "
        "resolves to Yes."
    )
    assert spec.compatible is True
    assert spec.proposition == "reference_ge"


# ── Rejected propositions ──────────────────────────────────────────────────


def test_below_is_inverted_reject():
    spec = _eval(
        "If the settlement value is below the opening reference, then "
        "the market resolves to Yes."
    )
    assert spec.compatible is False
    assert spec.proposition == "reference_lt"
    assert any(r.startswith("proposition_inverted") for r in spec.reasons)


def test_at_most_is_inverted_reject():
    spec = _eval(
        "If the index is at most the reference value, the market "
        "resolves to Yes."
    )
    assert spec.compatible is False
    assert spec.proposition == "reference_le"


def test_between_is_range_reject():
    spec = _eval(
        "If the settlement value is between 100 and 200, then the "
        "market resolves to Yes."
    )
    assert spec.compatible is False
    assert spec.proposition == "range_or_bracket"
    assert "proposition_range_or_bracket" in spec.reasons


def test_directional_language_rejected():
    spec = _eval(
        "If the price decreases during the window, the market resolves "
        "to Yes."
    )
    assert spec.compatible is False
    assert spec.proposition == "directional_inverted"


def test_contradictory_comparisons_rejected():
    spec = _eval(
        "If the price is above the reference and below the cap, the "
        "market resolves to Yes."
    )
    assert spec.compatible is False
    assert spec.proposition == "unrecognized"
    assert any(r.startswith("proposition_contradictory") for r in spec.reasons)


def test_absent_yes_clause_rejected():
    spec = _eval("Resolves per the published settlement procedure.")
    assert spec.compatible is False
    assert spec.proposition == "unrecognized"
    assert "proposition_clause_absent" in spec.reasons


def test_nonprice_operands_rejected():
    spec = _eval(
        "If the committee has at least a quorum of members, the market "
        "resolves to Yes."
    )
    assert spec.compatible is False
    assert spec.proposition == "unrecognized"
    assert "proposition_operands_unverified" in spec.reasons


# ── Structured strike-metadata cross-checks ────────────────────────────────


def test_cap_strike_rejects_despite_ge_text():
    """A declared cap strike means a range market — the rules text cannot
    override contradictory structured metadata."""
    spec = _eval(
        "If the settlement value is at least the reference value, the "
        "market resolves to Yes.",
        cap_strike=200.0,
        floor_strike=100.0,
    )
    assert spec.compatible is False
    assert spec.proposition == "range_or_bracket"
    assert "proposition_metadata_contradiction" in spec.reasons


def test_custom_strike_cap_rejects():
    spec = _eval(
        "If the settlement value is at least the reference value, the "
        "market resolves to Yes.",
        custom_strike={"floor_strike": 100.0, "cap_strike": 200.0},
    )
    assert spec.compatible is False
    assert spec.proposition == "range_or_bracket"


def test_strike_type_bracket_rejects():
    spec = _eval(
        "If the settlement value is at least the reference value, the "
        "market resolves to Yes.",
        strike_type="bracket",
    )
    assert spec.compatible is False
    assert spec.proposition == "range_or_bracket"


def test_floor_strike_alone_is_fine():
    """floor_strike/strike_price are the expected single-reference fields
    for up/down and threshold markets — they must not trigger rejection."""
    spec = _eval(
        "If the settlement value is at least the reference value, the "
        "market resolves to Yes.",
        floor_strike=100.0,
        strike_price=100.0,
    )
    assert spec.compatible is True
    assert spec.proposition == "reference_ge"


# ── Field extraction ───────────────────────────────────────────────────────


def test_extract_fields_picks_up_strike_metadata():
    class FakeMarket:
        raw_data = {
            "rules_primary": "x",
            "floor_strike": 100.0,
            "cap_strike": 200.0,
            "custom_strike": {"floor_strike": 1.0},
            "strike_type": "bracket",
        }

    out = extract_market_contract_fields(FakeMarket())
    assert out["cap_strike"] == 200.0
    assert out["strike_type"] == "bracket"
    assert out["custom_strike"] == {"floor_strike": 1.0}
    assert out["floor_strike"] == 100.0
    assert "strike_price" not in out


def test_extract_fields_from_attributes():
    class FakeState:
        floor_strike = 42.5
        cap_strike = None
        strike_type = "threshold"

    out = extract_market_contract_fields(FakeState())
    assert out["floor_strike"] == 42.5
    assert out["strike_type"] == "threshold"
    assert "cap_strike" not in out  # None attributes are skipped


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
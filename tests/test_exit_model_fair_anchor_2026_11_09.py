"""Exit-side model fair-value anchor alignment (2026-11-09).

The entry decision under ``MERID_SETTLEMENT_DISTRIBUTION_V2`` prices the
contract against the *final 60-second CF RTI average* via
``settlement_fair_prob``.  Exit-side fair anchors previously consumed only
``model_fair_prob`` — the point-expiry Bachelier probability — so a
position's hold-vs-sell valuation ignored banked settlement samples and
could disagree with the model that authorized the entry
(KXXRP15M-26NOV082330-30 incident: model fair read 19c while the
settlement distribution still favoured YES).

These tests pin:

  1. ``settlement_fair_prob`` outranks ``model_fair_prob`` when both are
     fresh — the contract-true anchor wins.
  2. Stale or absent ``settlement_fair_prob`` falls back to a fresh
     ``model_fair_prob``.
  3. Model-derived anchors require resolved-vol provenance
     (``_model_vol_source_trusted``): a probability built on a
     default/requested/fallback vol is a prior, not a valuation, and must
     not anchor a sell-vs-hold decision.
  4. NO-side mirroring stays exact (``100 - yes_fair``).
  5. ``_get_fair_value_provenance`` reports the winning source and the
     untrusted-vol fallback reason for audit.
"""

import time
from types import SimpleNamespace

import pytest

from merid.event_venues.kalshi.stop_candidate import (
    _get_fair_value_provenance,
    _get_model_fair_value_cents,
    _model_vol_source_trusted,
)


class TestUnifiedStateModelMirror:
    """``get_unified`` must surface the kalshi state's model provenance —
    exit consumers prefer the unified view, so without the mirror the model
    fair value that authorized the entry is invisible to them."""

    def test_unified_mirrors_model_provenance(self):
        from merid.event_venues.kalshi.market_state import KalshiMarketStateStore

        store = KalshiMarketStateStore()
        store._main_event_loop = None
        ticker = "KXXRP15M-TESTMIRROR"

        kalshi_state = store._get_or_create(ticker)
        kalshi_state.model_fair_prob = 0.19
        kalshi_state.model_fair_prob_ts = time.time()
        kalshi_state.settlement_fair_prob = 0.55
        kalshi_state.settlement_fair_prob_ts = time.time()
        kalshi_state.annualized_vol = 0.82
        kalshi_state.annualized_vol_source = "realized"
        kalshi_state.seconds_to_expiry = 300.0
        # A kalshi state with no expiry metadata keeps recompute-on-read
        # from touching the ticker; give it real expiry fields anyway.
        kalshi_state.expiration_time = time.time() + 300

        unified = store._get_or_create_unified(ticker)
        assert unified is not None
        out = store.get_unified(ticker)
        assert out is not None
        assert out.model_fair_prob == 0.19
        assert out.settlement_fair_prob == 0.55
        assert out.settlement_fair_prob_ts == kalshi_state.settlement_fair_prob_ts
        assert out.annualized_vol == 0.82
        assert out.annualized_vol_source == "realized"
        # The mirrored fields drive the same helpers consumers call.
        assert _get_model_fair_value_cents(out, "yes") == 55
        prov = _get_fair_value_provenance(out, "yes")
        assert prov["source"] == "settlement_fair_prob"

    def test_unified_without_kalshi_state_keeps_none(self):
        from merid.event_venues.kalshi.market_state import KalshiMarketStateStore

        store = KalshiMarketStateStore()
        store._main_event_loop = None
        ticker = "KXXRP15M-TESTMIRROR2"
        store._get_or_create_unified(ticker)
        out = store.get_unified(ticker)
        assert out is not None
        assert out.model_fair_prob is None
        assert out.settlement_fair_prob is None


def _state(**kwargs):
    defaults = dict(
        annualized_vol_source="realized",
        model_fair_prob=None,
        model_fair_prob_ts=None,
        settlement_fair_prob=None,
        settlement_fair_prob_ts=None,
        external_fair_value=None,
        implied_prob=None,
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestVolSourceTrust:
    @pytest.mark.parametrize("source", ["realized", "market_implied", "env_override", "realized_clamped"])
    def test_trusted_sources(self, source):
        assert _model_vol_source_trusted(_state(annualized_vol_source=source)) is True

    @pytest.mark.parametrize("source", ["", "default", "requested", "fallback", "unknown", "n/a", "none", "default_clamped"])
    def test_untrusted_sources(self, source):
        assert _model_vol_source_trusted(_state(annualized_vol_source=source)) is False

    def test_missing_source_is_untrusted(self):
        assert _model_vol_source_trusted(SimpleNamespace()) is False


class TestModelFairValueAnchor:
    def test_settlement_prob_preferred_over_point_bachelier(self):
        """The contract-true anchor wins when both publications are fresh."""
        state = _state(
            settlement_fair_prob=0.55,
            settlement_fair_prob_ts=time.time(),
            model_fair_prob=0.19,
            model_fair_prob_ts=time.time(),
        )
        assert _get_model_fair_value_cents(state, "yes") == 55
        assert _get_model_fair_value_cents(state, "no") == 45

    def test_stale_settlement_prob_falls_back_to_model_fair(self):
        state = _state(
            settlement_fair_prob=0.55,
            settlement_fair_prob_ts=time.time() - 9999,
            model_fair_prob=0.19,
            model_fair_prob_ts=time.time(),
        )
        assert _get_model_fair_value_cents(state, "yes") == 19

    def test_absent_settlement_prob_uses_model_fair(self):
        """Flag-off / non-V2 states keep the legacy behaviour."""
        state = _state(
            model_fair_prob=0.63,
            model_fair_prob_ts=time.time(),
        )
        assert _get_model_fair_value_cents(state, "yes") == 63
        assert _get_model_fair_value_cents(state, "no") == 37

    def test_untrusted_vol_rejects_model_anchors(self):
        """Both model probabilities are skipped on a default-vol state —
        falls through to the independent external fair value."""
        state = _state(
            annualized_vol_source="default",
            settlement_fair_prob=0.55,
            settlement_fair_prob_ts=time.time(),
            model_fair_prob=0.19,
            model_fair_prob_ts=time.time(),
            external_fair_value=0.42,
        )
        assert _get_model_fair_value_cents(state, "yes") == 42

    def test_untrusted_vol_no_model_no_anchor(self):
        state = _state(
            annualized_vol_source="",
            settlement_fair_prob=0.55,
            settlement_fair_prob_ts=time.time(),
            model_fair_prob=0.19,
            model_fair_prob_ts=time.time(),
        )
        assert _get_model_fair_value_cents(state, "yes") is None

    def test_never_falls_back_to_implied_prob(self):
        """implied_prob is book-derived — anchoring sell-vs-hold to it is
        tautological and must stay excluded from this helper."""
        state = _state(implied_prob=0.50)
        assert _get_model_fair_value_cents(state, "yes") is None


class TestFairValueProvenance:
    def test_settlement_source_reported(self):
        state = _state(
            settlement_fair_prob=0.55,
            settlement_fair_prob_ts=time.time(),
            model_fair_prob=0.19,
            model_fair_prob_ts=time.time(),
        )
        prov = _get_fair_value_provenance(state, "yes")
        assert prov["value_cents"] == 55
        assert prov["source"] == "settlement_fair_prob"
        assert prov["model_fresh"] is True
        assert prov["fallback_reason"] is None

    def test_untrusted_vol_fallback_reason(self):
        state = _state(
            annualized_vol_source="default",
            model_fair_prob=0.50,
            model_fair_prob_ts=time.time(),
            implied_prob=0.48,
        )
        prov = _get_fair_value_provenance(state, "yes")
        assert prov["source"] == "implied_prob"
        assert prov["value_cents"] == 48
        assert prov["fallback_reason"] == "model_vol_source_untrusted"
        assert prov["model_available"] is True
        assert prov["model_fresh"] is False

    def test_stale_settlement_then_fresh_model_reason(self):
        state = _state(
            settlement_fair_prob=0.55,
            settlement_fair_prob_ts=time.time() - 9999,
            model_fair_prob=0.19,
            model_fair_prob_ts=time.time(),
        )
        prov = _get_fair_value_provenance(state, "yes")
        assert prov["value_cents"] == 19
        assert prov["source"] == "model_fair_prob"

    def test_no_model_publication_reports_absent(self):
        state = _state(implied_prob=0.30)
        prov = _get_fair_value_provenance(state, "yes")
        assert prov["source"] == "implied_prob"
        assert prov["model_available"] is False
        assert prov["fallback_reason"] == "model_fair_prob_absent"

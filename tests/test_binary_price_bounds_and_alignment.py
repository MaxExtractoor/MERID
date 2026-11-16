"""Unit tests for binary price bounds, duality, and quote alignment.

Validates:
1. Canonical price space: prices must remain within valid Kalshi contract space [1, 99] cents.
2. An empty bid (bid <= 0) must NEVER derive an ask of 100 cents.
3. Quote misalignment and phantom price rejection: held_price_cents and rejection counterfactuals
   never log or score unexecutable prices (< 1c or > 99c).
4. Order router duality derivation: no_ask derivation respects book presence.
"""

import pytest
from merid.event_venues.kalshi.binary_price_space import (
    CanonicalBinaryMarketState,
    derive_no_ask_from_yes_bid,
    derive_yes_ask_from_no_bid,
    yes_to_no_price,
    no_to_yes_price,
)
from merid.prediction.rejection_counterfactual import (
    _price_bucket,
    log_rejected_candidate,
)


class TestBinaryPriceBoundsAndDuality:
    """Ensure prices stay strictly in Kalshi DCM contract space [1, 99] cents."""

    def test_derive_missing_prices_empty_book_does_not_derive_100c(self):
        """When yes_bid is 0 (empty book), no_ask must NOT be derived as 100 cents."""
        state = CanonicalBinaryMarketState(
            ticker="KXBTC15M-TEST",
            yes_bid_cents=0,
            yes_ask_cents=None,
            no_bid_cents=None,
            no_ask_cents=None,
        )
        state.derive_missing_prices()
        # no_ask must NOT become 100c
        assert state.no_ask_cents is None

    def test_derive_missing_prices_valid_bid_derives_correct_ask(self):
        """When yes_bid is in [1, 99], no_ask is correctly derived as 100 - yes_bid."""
        state = CanonicalBinaryMarketState(
            ticker="KXBTC15M-TEST",
            yes_bid_cents=25,
            yes_ask_cents=None,
            no_bid_cents=None,
            no_ask_cents=None,
        )
        state.derive_missing_prices()
        assert state.no_ask_cents == 75

    def test_price_bucket_rejects_phantom_prices(self):
        """Prices <= 0 or >= 100 must not produce valid trading price buckets."""
        assert _price_bucket(0) is None
        assert _price_bucket(100) is None
        assert _price_bucket(105) is None
        assert _price_bucket(-5) is None
        assert _price_bucket(0.09999) is None
        # Valid prices in [1, 99]
        assert _price_bucket(1) == "1-9c"
        assert _price_bucket(50) == "40-59c"
        assert _price_bucket(99) == "90-99c"


class TestTradeDecisionPriceBounds:
    """Ensure trade_decision does not create tradeable orders with prices >= 100c or <= 0c."""

    def test_trade_decision_empty_bid_no_ask_unexecutable(self, monkeypatch):
        """When yes_bid is 0 and no_ask is 0, no_entry does not derive to 1.0 (100c)."""
        from merid.prediction.trade_decision import compute_trade_decision

        decision = compute_trade_decision(
            run_id="r_test",
            decision_id="d_test",
            ticker="KXBTC15M-TEST",
            asset="BTC",
            spot_price=100.0,
            strike_price=100.0,
            seconds_to_expiry=300.0,
            yes_bid_cents=0.0,
            yes_ask_cents=50.0,
            no_bid_cents=0.0,
            no_ask_cents=0.0,
            annualized_vol=0.60,
            model_uncertainty=0.05,
            min_required_edge=0.03,
            data_quality="live",
            data_state="healthy",
            regime="normal",
            regime_label="normal",
            regime_probability=1.0,
            settlement_reference="cfb_rti_live",
        )
        # Decision must not enter on NO with a phantom 100c price
        assert decision.selected_outcome != "no"

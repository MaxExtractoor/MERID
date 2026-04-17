"""Tests for O-C1: seconds_to_expiry=0 must not invert expiry dampening."""
import pytest
from unittest.mock import MagicMock, patch


def _make_expired_state(seconds_to_expiry: float):
    """Create a minimal mock UnifiedMarketState for opinion strategy tests."""
    state = MagicMock()
    state.book_initialized = True
    state.mid_cents = 50
    state.spread_cents = 2
    state.yes_bids = [(55, 100)]
    state.no_bids = [(45, 100)]
    state.volume_24h = 1000
    state.open_interest = 500
    state.seconds_to_expiry = seconds_to_expiry
    return state


def test_kalshi_live_market_strategy_zero_expiry_uses_low_scale():
    """O-C1: seconds_to_expiry=0 must produce expiry_scale=0.25 (dampened),
    NOT 1.0 (full bias). The `or 7*86400` coercion must be removed."""
    from merid.prediction.opinion_strategy import KalshiLiveMarketStrategy

    strategy = KalshiLiveMarketStrategy(min_edge=0.0, imbalance_weight=0.10)

    # Patch market state store to return a state with seconds_to_expiry=0
    mock_state = _make_expired_state(seconds_to_expiry=0)
    mock_store = MagicMock()
    mock_store.get.return_value = mock_state

    with patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
        return_value=mock_store,
    ):
        # Use yes_bids/no_bids imbalanced to create a detectable imbalance_bias
        mock_state.yes_bids = [(55, 200)]
        mock_state.no_bids = [(45, 100)]

        # Call with slightly unbalanced book — expect near-zero imbalance_bias
        # because expiry_scale should be 0.25 for seconds_to_expiry=0
        result_expired = strategy.estimate(
            agent_id="test", ticker="BTC-TEST", market_prob=0.50,
            context={}
        )

    # If expiry_scale=1.0 (bug), edge = 0.10 * (1/3) * 1.0 * 1.0 = ~0.033
    # If expiry_scale=0.25 (fix), edge = 0.10 * (1/3) * 1.0 * 0.25 = ~0.008
    # With min_edge=0.0 both would return a result; check the edge magnitude
    # The bug produces a larger edge than the fix
    if result_expired is not None:
        # With 0.25 scale, imbalance_bias should be < 0.02
        assert abs(result_expired.edge) < 0.02, (
            f"Expired market produced edge={result_expired.edge:.4f} — "
            f"expiry dampening not applied (expected < 0.02)"
        )


def test_kalshi_live_market_strategy_nonzero_expiry_not_affected():
    """O-C1: seconds_to_expiry > 3600 must still produce expiry_scale=1.0.

    Also verifies that a nonzero-expiry market produces a LARGER edge than
    the same market with seconds_to_expiry=0 (the fix ensures dampening works).
    """
    from merid.prediction.opinion_strategy import KalshiLiveMarketStrategy

    strategy = KalshiLiveMarketStrategy(min_edge=0.0, imbalance_weight=0.10)

    # Test with non-expired market (1 day away)
    mock_state = _make_expired_state(seconds_to_expiry=86400)
    mock_store = MagicMock()
    mock_store.get.return_value = mock_state
    mock_state.yes_bids = [(55, 200)]
    mock_state.no_bids = [(45, 100)]

    with patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
        return_value=mock_store,
    ):
        result_nonexpired = strategy.estimate(
            agent_id="test", ticker="BTC-TEST", market_prob=0.50, context={}
        )

    # Test with expired market (seconds_to_expiry=0)
    mock_state.seconds_to_expiry = 0
    with patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store",
        return_value=mock_store,
    ):
        result_expired = strategy.estimate(
            agent_id="test", ticker="BTC-TEST", market_prob=0.50, context={}
        )

    # Both should produce results, but nonexpired must have larger edge magnitude
    assert result_nonexpired is not None, "Non-expired market should produce estimate"
    assert result_expired is not None, "Expired market should produce estimate"

    assert abs(result_nonexpired.edge) > abs(result_expired.edge), (
        f"Non-expired edge {abs(result_nonexpired.edge):.4f} must be > "
        f"expired edge {abs(result_expired.edge):.4f} (expiry dampening not working)"
    )

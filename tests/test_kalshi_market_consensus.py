"""Tests for Kalshi-market-driven consensus pipeline.

Covers:
- KalshiLiveMarketStrategy: opinion estimation from live orderbook data
- AgentProposal.market_data field
- News/sentiment is capped at 3% contribution
- Fallback to market_prob when book is absent
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from unittest.mock import MagicMock, patch

import pytest

from merid.prediction.opinion_strategy import (
    KalshiLiveMarketStrategy,
    OpinionEstimate,
    get_strategy,
    list_strategies,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_state(
    *,
    book_initialized: bool = True,
    mid_cents: Optional[int] = 55,
    spread_cents: Optional[int] = 2,
    best_bid_cents: Optional[int] = 54,
    best_ask_cents: Optional[int] = 56,
    yes_bids: Optional[List[Tuple[int, int]]] = None,
    no_bids: Optional[List[Tuple[int, int]]] = None,
    top_of_book_size: int = 10,
    depth_10c: int = 40,
    volume_24h: Optional[int] = 5000,
    open_interest: Optional[int] = 2000,
    seconds_to_expiry: Optional[int] = 7 * 86400,
) -> MagicMock:
    state = MagicMock()
    state.book_initialized = book_initialized
    state.mid_cents = mid_cents
    state.spread_cents = spread_cents
    state.best_bid_cents = best_bid_cents
    state.best_ask_cents = best_ask_cents
    state.yes_bids = yes_bids if yes_bids is not None else [(54, 10), (53, 5)]
    state.no_bids = no_bids if no_bids is not None else [(45, 6), (44, 4)]
    state.top_of_book_size = top_of_book_size
    state.depth_10c = depth_10c
    state.volume_24h = volume_24h
    state.open_interest = open_interest
    state.seconds_to_expiry = seconds_to_expiry
    return state


def _strategy_with_state(state) -> KalshiLiveMarketStrategy:
    """Return a strategy whose KalshiMarketStateStore is mocked."""
    return KalshiLiveMarketStrategy()


# ── Registry ─────────────────────────────────────────────────────────────────

def test_kalshi_live_market_in_registry():
    assert "kalshi_live_market" in list_strategies()


def test_get_strategy_returns_instance():
    s = get_strategy("kalshi_live_market")
    assert isinstance(s, KalshiLiveMarketStrategy)


# ── Basic estimation ──────────────────────────────────────────────────────────

def test_estimate_returns_opinion_when_book_live():
    strategy = KalshiLiveMarketStrategy()
    state = _make_state()
    with patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store"
    ) as mock_store:
        mock_store.return_value.get.return_value = state
        est = strategy.estimate(
            agent_id="agent-1",
            ticker="KXBTCD-25JUN-T100000",
            market_prob=0.50,
        )
    assert est is not None
    assert isinstance(est, OpinionEstimate)
    assert 0.02 <= est.agent_prob <= 0.98
    assert 0.0 <= est.confidence <= 1.0
    assert est.reasoning_tag == "kalshi_live_market"


def test_estimate_uses_mid_cents_as_base():
    """mid_cents=60 → base_prob=0.60, not market_prob=0.50."""
    strategy = KalshiLiveMarketStrategy()
    state = _make_state(mid_cents=60, spread_cents=0, yes_bids=[], no_bids=[])
    with patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store"
    ) as mock_store:
        mock_store.return_value.get.return_value = state
        est = strategy.estimate(
            agent_id="agent-1",
            ticker="KXBTCD-25JUN-T100000",
            market_prob=0.50,
        )
    assert est is not None
    # With mid=60, no imbalance, should be near 0.60
    assert abs(est.agent_prob - 0.60) < 0.05


def test_estimate_falls_back_to_market_prob_when_no_state():
    """When KalshiMarketStateStore returns None, strategy uses market_prob anchor."""
    strategy = KalshiLiveMarketStrategy()
    with patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store"
    ) as mock_store:
        mock_store.return_value.get.return_value = None
        est = strategy.estimate(
            agent_id="agent-1",
            ticker="KXBTCD-MISSING",
            market_prob=0.55,
        )
    # With no state, base_prob = market_prob, imbalance = 0, so edge = 0 → None
    assert est is None or (est is not None and abs(est.agent_prob - 0.55) < 0.10)


def test_estimate_falls_back_when_book_not_initialized():
    """Uninitialized book → base_prob = market_prob, no imbalance."""
    strategy = KalshiLiveMarketStrategy()
    state = _make_state(book_initialized=False, mid_cents=None)
    with patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store"
    ) as mock_store:
        mock_store.return_value.get.return_value = state
        est = strategy.estimate(
            agent_id="agent-1",
            ticker="KXBTCD-25JUN-T100000",
            market_prob=0.50,
        )
    # No imbalance, no spread, base = 0.50 → edge near 0 → likely None
    assert est is None or abs(est.agent_prob - 0.50) < 0.05


# ── Book imbalance ────────────────────────────────────────────────────────────

def test_yes_heavy_book_raises_prob():
    """Strong YES depth → positive imbalance → agent_prob > market_prob (mid)."""
    strategy = KalshiLiveMarketStrategy()
    state = _make_state(
        mid_cents=50,
        spread_cents=1,
        yes_bids=[(49, 40)],   # big YES stack
        no_bids=[(50, 5)],     # thin NO stack
    )
    with patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store"
    ) as mock_store:
        mock_store.return_value.get.return_value = state
        est = strategy.estimate(
            agent_id="agent-1",
            ticker="KXBTCD-25JUN-T100000",
            market_prob=0.50,
        )
    assert est is not None
    assert est.agent_prob > 0.50


def test_no_heavy_book_lowers_prob():
    """Strong NO depth → negative imbalance → agent_prob < market_prob (mid)."""
    strategy = KalshiLiveMarketStrategy()
    state = _make_state(
        mid_cents=50,
        spread_cents=1,
        yes_bids=[(49, 5)],
        no_bids=[(50, 40)],
    )
    with patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store"
    ) as mock_store:
        mock_store.return_value.get.return_value = state
        est = strategy.estimate(
            agent_id="agent-1",
            ticker="KXBTCD-25JUN-T100000",
            market_prob=0.50,
        )
    assert est is not None
    assert est.agent_prob < 0.50


def test_balanced_book_no_imbalance_bias():
    """Equal YES/NO depth → imbalance_bias = 0 → agent_prob ≈ mid."""
    strategy = KalshiLiveMarketStrategy()
    state = _make_state(
        mid_cents=55,
        spread_cents=0,
        yes_bids=[(54, 20)],
        no_bids=[(45, 20)],
    )
    with patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store"
    ) as mock_store:
        mock_store.return_value.get.return_value = state
        est = strategy.estimate(
            agent_id="agent-1",
            ticker="KXBTCD-25JUN-T100000",
            market_prob=0.50,
        )
    if est is not None:
        # With 0 spread, spread_factor=1.0, imbalance=0 → pure mid
        assert abs(est.agent_prob - 0.55) < 0.02


# ── Spread signal ─────────────────────────────────────────────────────────────

def test_wide_spread_reduces_imbalance_bias():
    """Wide spread (10c) → spread_factor=0 → imbalance bias zeroed."""
    strategy = KalshiLiveMarketStrategy()
    state = _make_state(
        mid_cents=50,
        spread_cents=10,              # very wide
        yes_bids=[(49, 40)],          # heavy YES
        no_bids=[(50, 5)],
    )
    with patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store"
    ) as mock_store:
        mock_store.return_value.get.return_value = state
        est_wide = strategy.estimate(
            agent_id="agent-1",
            ticker="KXBTCD-WIDE",
            market_prob=0.45,
        )

    state2 = _make_state(
        mid_cents=50,
        spread_cents=1,               # tight
        yes_bids=[(49, 40)],
        no_bids=[(50, 5)],
    )
    with patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store"
    ) as mock_store:
        mock_store.return_value.get.return_value = state2
        est_tight = strategy.estimate(
            agent_id="agent-1",
            ticker="KXBTCD-TIGHT",
            market_prob=0.45,
        )

    # Wide spread must produce a smaller or equal bias than tight spread
    if est_wide and est_tight:
        assert abs(est_wide.agent_prob - 0.50) <= abs(est_tight.agent_prob - 0.50)


# ── Time-to-expiry decay ──────────────────────────────────────────────────────

def test_near_expiry_reduces_bias():
    """< 1h to expiry → expiry_scale=0.25 → bias heavily reduced."""
    strategy = KalshiLiveMarketStrategy()
    kwargs = dict(
        mid_cents=50,
        spread_cents=1,
        yes_bids=[(49, 40)],
        no_bids=[(50, 5)],
    )
    state_far = _make_state(**kwargs, seconds_to_expiry=7 * 86400)
    state_near = _make_state(**kwargs, seconds_to_expiry=1800)  # 30 min

    def _run(state):
        with patch(
            "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store"
        ) as mock_store:
            mock_store.return_value.get.return_value = state
            return strategy.estimate(
                agent_id="agent-1",
                ticker="KXBTCD-25JUN-T100000",
                market_prob=0.45,
            )

    est_far = _run(state_far)
    est_near = _run(state_near)

    if est_far and est_near:
        # Far-expiry should show more deviation from 0.50 than near-expiry
        assert abs(est_far.agent_prob - 0.50) >= abs(est_near.agent_prob - 0.50)


# ── Signal sources ────────────────────────────────────────────────────────────

def test_signal_sources_include_kalshi_fields():
    """Signal sources must reference Kalshi data, not news."""
    strategy = KalshiLiveMarketStrategy()
    state = _make_state()
    with patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store"
    ) as mock_store:
        mock_store.return_value.get.return_value = state
        est = strategy.estimate(
            agent_id="agent-1",
            ticker="KXBTCD-25JUN-T100000",
            market_prob=0.50,
            context={"sentiment_score": 0.8},  # news present
        )
    assert est is not None
    assert "kalshi_orderbook" in est.signal_sources
    assert "kalshi_spread" in est.signal_sources
    # News present but should not dominate — kalshi sources must outnumber it
    kalshi_count = sum(1 for s in est.signal_sources if s.startswith("kalshi_"))
    assert kalshi_count >= 3


def test_news_sentiment_in_signal_sources_when_provided():
    """When sentiment_score is in context it should be tagged but not dominate."""
    strategy = KalshiLiveMarketStrategy()
    state = _make_state()
    with patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store"
    ) as mock_store:
        mock_store.return_value.get.return_value = state
        est = strategy.estimate(
            agent_id="agent-1",
            ticker="KXBTCD-25JUN-T100000",
            market_prob=0.50,
            context={"sentiment_score": 1.0},
        )
    if est:
        assert "news_sentiment" in est.signal_sources
        # Sentiment contribution must be ≤ SENTIMENT_WEIGHT (3%)
        if est.explanation:
            assert abs(est.explanation.contributions.get("sentiment", 0)) <= 0.04


# ── News sentiment is capped ──────────────────────────────────────────────────

def test_sentiment_contribution_capped_at_3pct():
    """Even with extreme sentiment (±1.0), contribution stays ≤ 3%."""
    strategy = KalshiLiveMarketStrategy()
    # Use balanced book so imbalance_bias ≈ 0; mid=50 → base=0.50
    state = _make_state(
        mid_cents=50,
        spread_cents=0,
        yes_bids=[(49, 20)],
        no_bids=[(50, 20)],
    )

    def _run(sent):
        with patch(
            "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store"
        ) as mock_store:
            mock_store.return_value.get.return_value = state
            return strategy.estimate(
                agent_id="agent-1",
                ticker="KXBTCD-25JUN-T100000",
                market_prob=0.47,
                context={"sentiment_score": sent},
            )

    est_bull = _run(1.0)
    est_bear = _run(-1.0)

    if est_bull and est_bear:
        # The gap attributable to sentiment alone must be ≤ 2 * SENTIMENT_WEIGHT
        delta = est_bull.agent_prob - est_bear.agent_prob
        assert delta <= 2 * KalshiLiveMarketStrategy.SENTIMENT_WEIGHT + 0.01


# ── Explanation ───────────────────────────────────────────────────────────────

def test_explanation_populated_with_market_data():
    strategy = KalshiLiveMarketStrategy()
    state = _make_state()
    with patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store"
    ) as mock_store:
        mock_store.return_value.get.return_value = state
        est = strategy.estimate(
            agent_id="agent-1",
            ticker="KXBTCD-25JUN-T100000",
            market_prob=0.50,
        )
    assert est is not None
    assert est.explanation is not None
    assert "spread_cents" in est.explanation.inputs_used
    assert "imbalance_raw" in est.explanation.inputs_used
    assert "seconds_to_expiry" in est.explanation.inputs_used
    assert "book_imbalance" in est.explanation.contributions
    assert est.explanation.rationale == "kalshi_live_market_primary"


def test_explanation_rationale_fallback_when_no_book():
    strategy = KalshiLiveMarketStrategy()
    state = _make_state(book_initialized=False, mid_cents=None)
    state.yes_bids = []
    state.no_bids = []
    with patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store"
    ) as mock_store:
        mock_store.return_value.get.return_value = state
        est = strategy.estimate(
            agent_id="agent-1",
            ticker="KXBTCD-25JUN-T100000",
            market_prob=0.55,
            context={"sentiment_score": 0.5},
        )
    if est and est.explanation:
        assert est.explanation.rationale == "kalshi_market_prob_fallback"


# ── Min-edge filter ───────────────────────────────────────────────────────────

def test_returns_none_when_edge_below_threshold():
    """When mid ≈ market_prob and no imbalance, edge < min_edge → None."""
    strategy = KalshiLiveMarketStrategy(min_edge=0.10)  # very high threshold
    state = _make_state(mid_cents=50, spread_cents=0, yes_bids=[], no_bids=[])
    with patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store"
    ) as mock_store:
        mock_store.return_value.get.return_value = state
        est = strategy.estimate(
            agent_id="agent-1",
            ticker="KXBTCD-25JUN-T100000",
            market_prob=0.50,
        )
    assert est is None


def test_skips_extreme_market_probs():
    """market_prob ≤ 0.01 or ≥ 0.99 must return None (should_skip)."""
    strategy = KalshiLiveMarketStrategy()
    state = _make_state()
    with patch(
        "merid.event_venues.kalshi.market_state.get_kalshi_market_state_store"
    ) as mock_store:
        mock_store.return_value.get.return_value = state
        assert strategy.estimate("a", "T", market_prob=0.005) is None
        assert strategy.estimate("a", "T", market_prob=0.995) is None


# ── AgentProposal.market_data ─────────────────────────────────────────────────

def test_agent_proposal_accepts_market_data():
    """AgentProposal.market_data field exists and stores Kalshi context."""
    from datetime import datetime, timezone
    from merid.swarm.consensus_aggregator import AgentProposal

    proposal = AgentProposal(
        agent_id="agent-1",
        asset="BTC",
        timeframe="15m",
        direction="yes",
        probability=0.62,
        confidence=0.70,
        size_preference="base",
        rationale="kalshi_live_market",
        edge_estimate=12.0,
        timestamp=datetime.now(timezone.utc),
        agent_archetype="trend",
        market_data={
            "mid_cents": 62,
            "spread_cents": 2,
            "depth_10c": 45,
            "volume_24h": 4500,
            "open_interest": 1800,
            "seconds_to_expiry": 86400,
        },
    )
    assert proposal.market_data is not None
    assert proposal.market_data["spread_cents"] == 2
    assert proposal.market_data["seconds_to_expiry"] == 86400


def test_agent_proposal_market_data_defaults_none():
    """market_data is optional — existing callers don't break."""
    from datetime import datetime, timezone
    from merid.swarm.consensus_aggregator import AgentProposal

    proposal = AgentProposal(
        agent_id="agent-2",
        asset="ETH",
        timeframe="1h",
        direction="no",
        probability=0.38,
        confidence=0.55,
        size_preference="small",
        rationale="hash_bias",
        edge_estimate=5.0,
        timestamp=datetime.now(timezone.utc),
        agent_archetype="mean_reversion",
    )
    assert proposal.market_data is None

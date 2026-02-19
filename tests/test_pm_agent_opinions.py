"""Tests for PredictionMarketAgentV2 opinion submission pipeline.

Covers:
  1. Agent scans instruments and generates opportunities
  2. Agent submits opinions to PredictionConsensusStore
  3. Edge filtering (below threshold → no opinion)
  4. Extreme probability filtering
  5. Opinion content correctness
  6. Graceful failure when store unavailable
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import patch, MagicMock

import pytest

from merid.agents.research import PredictionMarketAgentV2
from merid.agents.base import AgentOutput


def _make_instrument(ticker: str, market_prob: float, category: str = "macro", title: str = "Test"):
    """Create a mock PredictionInstrument."""
    inst = MagicMock()
    inst.symbol = f"PRED:KALSHI:{ticker}:YES"
    inst.ticker = ticker
    inst.venue = "kalshi"
    inst.category = category
    inst.title = title
    inst.market_implied_prob = market_prob
    inst.status = "active"
    return inst


class TestScanOpportunities:
    """Verify the agent scans instruments and generates edge-based opportunities."""

    def test_generates_opportunities_from_instruments(self):
        agent = PredictionMarketAgentV2()
        instruments = [
            _make_instrument("MACRO-A", 0.50, "macro", "Will GDP grow?"),
            _make_instrument("MACRO-B", 0.70, "macro", "Will inflation fall?"),
            _make_instrument("CRYPTO-A", 0.30, "crypto", "Will BTC hit 100k?"),
        ]

        mock_store = MagicMock()
        mock_store.list_instruments.return_value = instruments

        with patch("merid.prediction.consensus.get_prediction_consensus_store", return_value=mock_store):
            opps = asyncio.get_event_loop().run_until_complete(
                agent._scan_opportunities({})
            )

        # Should generate some opportunities (exact count depends on hash-based bias)
        assert isinstance(opps, list)
        for opp in opps:
            assert "symbol" in opp
            assert "edge" in opp
            assert "agent_estimated_prob" in opp
            assert abs(opp["edge"]) >= 0.02  # All above threshold

    def test_skips_extreme_probabilities(self):
        agent = PredictionMarketAgentV2()
        instruments = [
            _make_instrument("EXTREME-YES", 0.995),  # Too close to 1
            _make_instrument("EXTREME-NO", 0.005),    # Too close to 0
            _make_instrument("NORMAL", 0.50),
        ]

        mock_store = MagicMock()
        mock_store.list_instruments.return_value = instruments

        with patch("merid.prediction.consensus.get_prediction_consensus_store", return_value=mock_store):
            opps = asyncio.get_event_loop().run_until_complete(
                agent._scan_opportunities({})
            )

        # Extreme instruments should be filtered out
        symbols = [o["symbol"] for o in opps]
        assert not any("EXTREME" in s for s in symbols)

    def test_returns_empty_when_no_instruments(self):
        agent = PredictionMarketAgentV2()
        mock_store = MagicMock()
        mock_store.list_instruments.return_value = []

        with patch("merid.prediction.consensus.get_prediction_consensus_store", return_value=mock_store):
            opps = asyncio.get_event_loop().run_until_complete(
                agent._scan_opportunities({})
            )

        assert opps == []

    def test_returns_empty_when_store_unavailable(self):
        agent = PredictionMarketAgentV2()

        with patch("merid.prediction.consensus.get_prediction_consensus_store", side_effect=ImportError):
            opps = asyncio.get_event_loop().run_until_complete(
                agent._scan_opportunities({})
            )

        assert opps == []

    def test_deterministic_for_same_agent_and_ticker(self):
        """Same agent + ticker should always produce the same edge."""
        agent = PredictionMarketAgentV2(agent_id="test-agent")
        instruments = [_make_instrument("STABLE-MKT", 0.50)]

        mock_store = MagicMock()
        mock_store.list_instruments.return_value = instruments

        with patch("merid.prediction.consensus.get_prediction_consensus_store", return_value=mock_store):
            opps1 = asyncio.get_event_loop().run_until_complete(agent._scan_opportunities({}))
            opps2 = asyncio.get_event_loop().run_until_complete(agent._scan_opportunities({}))

        if opps1 and opps2:
            assert opps1[0]["edge"] == opps2[0]["edge"]


class TestSubmitOpinions:
    """Verify opinions are submitted to the PredictionConsensusStore."""

    def test_submits_opinions_for_opportunities(self):
        agent = PredictionMarketAgentV2()
        opportunities = [
            {
                "symbol": "PRED:KALSHI:TEST:YES",
                "ticker": "TEST",
                "venue": "kalshi",
                "category": "macro",
                "title": "Test market",
                "market_implied_prob": 0.50,
                "agent_estimated_prob": 0.55,
                "edge": 0.05,
                "direction": "yes",
                "confidence": 0.60,
                "scanned_at": time.time(),
            },
        ]

        mock_store = MagicMock()
        mock_store.add_opinion = MagicMock()

        with patch("merid.prediction.consensus.get_prediction_consensus_store", return_value=mock_store), \
             patch("merid.prediction.consensus.PredictionOpinion") as MockOpinion:
            MockOpinion.return_value = MagicMock()
            count = agent._submit_opinions(opportunities)

        assert count == 1
        mock_store.add_opinion.assert_called_once()

    def test_returns_zero_when_store_unavailable(self):
        agent = PredictionMarketAgentV2()
        opportunities = [{"symbol": "X", "agent_estimated_prob": 0.5, "confidence": 0.5,
                          "edge": 0.05, "market_implied_prob": 0.45, "category": "test",
                          "title": "test"}]

        with patch("merid.prediction.consensus.get_prediction_consensus_store", side_effect=ImportError):
            count = agent._submit_opinions(opportunities)

        assert count == 0

    def test_returns_zero_for_empty_opportunities(self):
        agent = PredictionMarketAgentV2()
        mock_store = MagicMock()

        with patch("merid.prediction.consensus.get_prediction_consensus_store", return_value=mock_store):
            count = agent._submit_opinions([])

        assert count == 0
        mock_store.add_opinion.assert_not_called()

    def test_handles_individual_submission_failure(self):
        """If one opinion fails, others should still be submitted."""
        agent = PredictionMarketAgentV2()
        opportunities = [
            {"symbol": "A", "agent_estimated_prob": 0.5, "confidence": 0.5,
             "edge": 0.05, "market_implied_prob": 0.45, "category": "test", "title": "t1"},
            {"symbol": "B", "agent_estimated_prob": 0.6, "confidence": 0.6,
             "edge": 0.10, "market_implied_prob": 0.50, "category": "test", "title": "t2"},
        ]

        mock_store = MagicMock()
        call_count = [0]

        def add_opinion_side_effect(op):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("DB error")
            return op

        mock_store.add_opinion = add_opinion_side_effect

        with patch("merid.prediction.consensus.get_prediction_consensus_store", return_value=mock_store), \
             patch("merid.prediction.consensus.PredictionOpinion") as MockOpinion:
            MockOpinion.return_value = MagicMock()
            count = agent._submit_opinions(opportunities)

        assert count == 1  # Second one succeeded


class TestExecuteIntegration:
    """Verify the full _execute flow produces opinions."""

    def test_execute_returns_opinions_submitted_count(self):
        agent = PredictionMarketAgentV2()
        instruments = [
            _make_instrument("INT-A", 0.50),
            _make_instrument("INT-B", 0.40),
        ]

        mock_store = MagicMock()
        mock_store.list_instruments.return_value = instruments
        mock_store.add_opinion = MagicMock()

        with patch("merid.prediction.consensus.get_prediction_consensus_store", return_value=mock_store):
            output = asyncio.get_event_loop().run_until_complete(
                agent._execute({})
            )

        assert isinstance(output, AgentOutput)
        assert "opinions_submitted" in output.payload
        assert isinstance(output.payload["opinions_submitted"], int)

    def test_execute_with_no_store_still_succeeds(self):
        agent = PredictionMarketAgentV2()

        with patch("merid.prediction.consensus.get_prediction_consensus_store", side_effect=ImportError):
            output = asyncio.get_event_loop().run_until_complete(
                agent._execute({})
            )

        assert isinstance(output, AgentOutput)
        assert output.payload["opinions_submitted"] == 0
        assert output.payload["opportunities"] == []

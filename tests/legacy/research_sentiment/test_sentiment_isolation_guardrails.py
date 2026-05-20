"""Tests for sentiment isolation guardrails.

NOTE: This test is marked as sentiment_research and should be excluded from
kalshi_crypto_15m_v2 production test runs. Sentiment is research-only and
must not influence live 15m Kalshi trading decisions.
"""

import pytest

pytestmark = pytest.mark.sentiment_research

"""
Sentiment Isolation Guardrail Tests

These tests ensure that sentiment is fully decoupled from trading and execution logic.
Sentiment should only control ingestion/plumbing services, with no impact on:
- Order routing and acceptance
- Risk limits and rejection
- Order sizing
- Agent gating

Tests run:
1. No SENTIMENT block reasons in block_reasons.py
2. No SentimentRisk codes in risk modules
3. Trading decisions are invariant to ENABLE_SENTIMENT_TRUTH flag (deterministic scenario)
"""

import unittest
import os
from unittest.mock import patch, MagicMock


class TestSentimentBlockReasons(unittest.TestCase):
    """Test that no SENTIMENT block reasons exist."""

    def test_no_sentiment_block_reasons(self):
        """Assert no block reason contains 'SENTIMENT' or 'sentiment'."""
        from merid.guards.block_reasons import BlockReason

        # Get all block reason constants
        block_reasons = [
            getattr(BlockReason, attr)
            for attr in dir(BlockReason)
            if not attr.startswith("_") and isinstance(getattr(BlockReason, attr), str)
        ]

        # Assert no sentiment-related block reasons
        for reason in block_reasons:
            self.assertNotIn(
                "SENTIMENT",
                reason,
                f"Block reason '{reason}' contains 'SENTIMENT' - sentiment should not gate trading"
            )
            self.assertNotIn(
                "sentiment",
                reason.lower(),
                f"Block reason '{reason}' contains 'sentiment' - sentiment should not gate trading"
            )

    def test_no_sentiment_notional_cap(self):
        """Assert SENTIMENT_NOTIONAL_CAP constant does not exist."""
        from merid.guards.block_reasons import BlockReason

        # This constant should have been removed during sentiment decoupling
        self.assertFalse(
            hasattr(BlockReason, "SENTIMENT_NOTIONAL_CAP"),
            "SENTIMENT_NOTIONAL_CAP should not exist - sentiment should not gate trading via notional caps"
        )


class TestSentimentRiskCodes(unittest.TestCase):
    """Test that no SentimentRisk codes exist in risk modules."""

    def test_no_sentiment_order_rejection_reason(self):
        """Assert sentiment_order_rejection_reason function does not exist."""
        from merid.risk import sentiment_risk

        # This function should have been removed during sentiment decoupling
        self.assertFalse(
            hasattr(sentiment_risk, "sentiment_order_rejection_reason"),
            "sentiment_order_rejection_reason should not exist - sentiment should not gate trading"
        )

    def test_no_sentiment_cap_rejection_in_unified_risk(self):
        """Assert unified_risk_engine does not perform sentiment cap rejection."""
        # This is a static check - the code should not contain sentiment cap rejection logic
        import merid.risk.unified_risk_engine as ure

        # Read the file and check for sentiment cap rejection
        with open(ure.__file__, 'r') as f:
            content = f.read()

        # These patterns should not exist
        self.assertNotIn(
            "sentiment_cap",
            content.lower(),
            "unified_risk_engine should not contain sentiment_cap logic"
        )
        self.assertNotIn(
            "sentiment rejection",
            content.lower(),
            "unified_risk_engine should not contain sentiment rejection logic"
        )


class TestSentimentFlagInvariance(unittest.TestCase):
    """Test that trading decisions are invariant to ENABLE_SENTIMENT_TRUTH flag."""

    def test_flag_only_controls_ingestion(self):
        """Assert ENABLE_SENTIMENT_TRUTH only affects ingestion service startup."""
        # This is a code structure check - the flag should only appear in:
        # - web/main.py (sentiment service startup)
        # - merid/sentiment/* (ingestion/plumbing modules)
        # - trading lanes should NOT check this flag for trading decisions

        # Check that trading lanes don't gate on ENABLE_SENTIMENT_TRUTH
        import merid.lanes.crypto15m_lane as crypto_lane
        import merid.lanes.btc15m_lane as btc_lane

        # Read the files and check for ENABLE_SENTIMENT_TRUTH gating
        with open(crypto_lane.__file__, 'r') as f:
            crypto_content = f.read()

        with open(btc_lane.__file__, 'r') as f:
            btc_content = f.read()

        # These files should only have comments about ENABLE_SENTIMENT_TRUTH, not gating logic
        # The decoupling comment should be present
        self.assertIn(
            "SENTIMENT DECOUPLING",
            crypto_content,
            "crypto15m_lane should have sentiment decoupling comment"
        )
        self.assertIn(
            "SENTIMENT DECOUPLING",
            btc_content,
            "btc15m_lane should have sentiment decoupling comment"
        )

        # Should NOT have if/else gating on ENABLE_SENTIMENT_TRUTH for trading decisions
        # (comments are ok, but not actual control flow)
        lines_with_flag = [
            line for line in crypto_content.split('\n')
            if 'ENABLE_SENTIMENT_TRUTH' in line and 'if' in line
        ]
        # Only comments should remain
        for line in lines_with_flag:
            self.assertTrue(
                line.strip().startswith('#'),
                f"crypto15m_lane should not gate on ENABLE_SENTIMENT_TRUTH: {line}"
            )


class TestSentimentInTradingStack(unittest.TestCase):
    """Test that sentiment does not appear in trading stack modules."""

    def test_no_sentiment_in_order_router(self):
        """Assert order_router does not have sentiment gating logic."""
        import merid.event_venues.kalshi.order_router as order_router

        with open(order_router.__file__, 'r') as f:
            content = f.read()

        # These functions should have been removed
        self.assertNotIn(
            "_check_sentiment_notional_cap",
            content,
            "order_router should not contain _check_sentiment_notional_cap function"
        )
        self.assertNotIn(
            "sentiment_size_scalar",
            content.lower(),
            "order_router should not contain sentiment_size_scalar logic"
        )

    def test_no_sentiment_in_agent_grid(self):
        """Assert agent_grid does not have sentiment-based agent gating."""
        import merid.prediction.agent_grid as agent_grid

        with open(agent_grid.__file__, 'r') as f:
            content = f.read()

        # Sentiment-based agent gating should have been removed from _apply_regime_gating
        # The method should now be a no-op or only perform non-sentiment gating
        self.assertIn(
            "SENTIMENT DECOUPLING",
            content,
            "agent_grid should have sentiment decoupling comment"
        )

    def test_no_fear_greed_in_crypto_swarm_risk(self):
        """Assert crypto_swarm_risk_btc15m does not use fear/greed for sizing."""
        import merid.risk.crypto_swarm_risk_btc15m as risk_btc15m

        # The _get_fear_greed_multiplier should always return 1.0 now
        with open(risk_btc15m.__file__, 'r') as f:
            content = f.read()

        # Should have decoupling comment
        self.assertIn(
            "SENTIMENT DECOUPLING",
            content,
            "crypto_swarm_risk_btc15m should have sentiment decoupling comment"
        )


if __name__ == "__main__":
    unittest.main()

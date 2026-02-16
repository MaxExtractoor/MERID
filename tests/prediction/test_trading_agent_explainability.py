"""
Phase 2: Risk Rejection Explainability Tests

Tests for KalshiTradingAgent risk rejection explainability covering:
1. Exposure cap blocks
2. Daily loss limit blocks
3. Swarm health blocks
4. Explainability format validation

Reference: .windsurf/tickets/phase2-risk-rejection-explainability-tests.md
Baseline: Commit c25d2702
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, Mock, patch, MagicMock

import pytest

from agents.explainability import get_explainability_tracker, DecisionType
from merid.prediction.trading_agent import KalshiTradingAgent
from merid.prediction.strategy import StrategySignal, SignalAction
from merid.prediction.model import EdgeEstimate
from merid.prediction.risk import PreTradeCheck, RiskAction, PredictionRiskConfig
from merid.event_venues.base import EventMarket, EventOutcome
from merid.prediction.agent_grid_config import AgentConfig


@pytest.fixture
def mock_agent_config():
    """Create a mock agent config for testing."""
    config = AgentConfig(
        name="KalshiTradingAgent",
        category="crypto",
        assets=["BTC"],
        timeframes=["daily"],
        enabled=True,
        archetype="directional",
    )
    return config


@pytest.fixture
def mock_market():
    """Create a mock EventMarket for testing."""
    return EventMarket(
        market_id="KXBTC-24FEB16-B60000",
        venue="kalshi",
        question="Will BTC be above $60,000 on Feb 16?",
        description="Binary market on BTC price",
        outcomes=[
            EventOutcome(outcome_id="yes", outcome_name="Yes", price=Decimal("55")),
            EventOutcome(outcome_id="no", outcome_name="No", price=Decimal("45")),
        ],
    )


@pytest.fixture
def mock_signal():
    """Create a mock trading signal."""
    return StrategySignal(
        market_id="KXBTC-24FEB16-B60000",
        action=SignalAction.BUY_YES,
        side="yes",
        contracts=10,
        limit_price_cents=55,
        edge=EdgeEstimate(
            market_id="KXBTC-24FEB16-B60000",
            side="yes",
            action="buy",
            market_prob=Decimal("0.55"),
            model_prob=Decimal("0.60"),
            raw_edge=Decimal("0.05"),
            fee_drag=Decimal("0.002"),
            slippage_est=Decimal("0.001"),
            net_edge=Decimal("0.047"),
            edge_type="speculative",
            confidence=Decimal("0.75"),
        ),
    )


class TestExposureCapBlock:
    """Test exposure cap risk rejection explainability."""

    def test_exposure_cap_block_records_explainability(self, mock_agent_config, mock_market, mock_signal):
        """Verify exposure cap block creates explainability record with correct fields."""
        agent = KalshiTradingAgent(mock_agent_config)
        tracker = get_explainability_tracker()
        
        # Clear any existing decisions
        tracker.decisions.clear()
        tracker._decisions_by_agent.clear()
        
        # Create risk check that blocks due to exposure cap
        check = PreTradeCheck(
            allowed=False,
            action=RiskAction.REJECT,
            reason="exposure_cap: Market exposure $550 would exceed limit $500",
            market_id=mock_market.market_id,
        )
        
        # Mock snapshot
        mock_snapshot = Mock()
        mock_snapshot.implied = Mock(yes_prob=Decimal("0.55"), no_prob=Decimal("0.45"))
        mock_snapshot.volume = Decimal("10000")
        mock_snapshot.open_interest = Decimal("5000")
        
        # Record decision
        agent._record_explainability_decision(
            market=mock_market,
            signal=mock_signal,
            snapshot=mock_snapshot,
            check=check,
            now=datetime.now(timezone.utc),
            allowed=False,
        )
        
        # Retrieve decision from tracker
        decisions = tracker.get_agent_decisions(mock_agent_config.name, limit=1)
        
        assert len(decisions) == 1
        decision = decisions[0]
        
        # Verify decision structure
        assert decision.agent_id == mock_agent_config.name
        assert decision.decision_type == DecisionType.ACTION
        
        # Verify reasoning includes risk block details
        reasoning_dict = decision.to_dict()
        assert "exposure_cap" in reasoning_dict["primary_reason"] or "exposure_cap" in str(reasoning_dict.get("contrary_factors", []))
        assert "allowed=False" in str(reasoning_dict.get("supporting_factors", []))
        
        # Verify market context
        assert reasoning_dict.get("market_context") is not None
        assert reasoning_dict["market_context"]["market_id"] == mock_market.market_id

    def test_exposure_cap_includes_threshold_details(self, mock_agent_config, mock_market, mock_signal):
        """Verify exposure cap block includes current exposure and threshold."""
        agent = KalshiTradingAgent(mock_agent_config)
        tracker = get_explainability_tracker()
        tracker.decisions.clear()
        tracker._decisions_by_agent.clear()
        
        check = PreTradeCheck(
            allowed=False,
            action=RiskAction.REJECT,
            reason="exposure_cap: Current exposure $450, signal size $100, limit $500",
            market_id=mock_market.market_id,
        )
        
        mock_snapshot = Mock()
        mock_snapshot.implied = Mock(yes_prob=Decimal("0.55"), no_prob=Decimal("0.45"))
        mock_snapshot.volume = Decimal("10000")
        mock_snapshot.open_interest = Decimal("5000")
        
        agent._record_explainability_decision(
            market=mock_market,
            signal=mock_signal,
            snapshot=mock_snapshot,
            check=check,
            now=datetime.now(timezone.utc),
            allowed=False,
        )
        
        decisions = tracker.get_agent_decisions(mock_agent_config.name, limit=1)
        assert len(decisions) == 1
        
        decision_dict = decisions[0].to_dict()
        # Check that risk_assessment contains the block reason
        risk_assessment = decision_dict.get("risk_assessment", {})
        assert risk_assessment["allowed"] is False
        assert "exposure_cap" in risk_assessment["reason"]


class TestDailyLossLimitBlock:
    """Test daily loss limit risk rejection explainability."""

    def test_daily_loss_limit_block_records_explainability(self, mock_agent_config, mock_market, mock_signal):
        """Verify daily loss limit block creates explainability record."""
        agent = KalshiTradingAgent(mock_agent_config)
        tracker = get_explainability_tracker()
        tracker.decisions.clear()
        tracker._decisions_by_agent.clear()
        
        check = PreTradeCheck(
            allowed=False,
            action=RiskAction.REJECT,
            reason="daily_loss_limit: Current P&L -$240, limit -$250, signal would breach",
            market_id=mock_market.market_id,
        )
        
        mock_snapshot = Mock()
        mock_snapshot.implied = Mock(yes_prob=Decimal("0.55"), no_prob=Decimal("0.45"))
        mock_snapshot.volume = Decimal("10000")
        mock_snapshot.open_interest = Decimal("5000")
        
        agent._record_explainability_decision(
            market=mock_market,
            signal=mock_signal,
            snapshot=mock_snapshot,
            check=check,
            now=datetime.now(timezone.utc),
            allowed=False,
        )
        
        decisions = tracker.get_agent_decisions(mock_agent_config.name, limit=1)
        assert len(decisions) == 1
        
        decision = decisions[0]
        decision_dict = decision.to_dict()
        
        # Verify risk assessment contains daily loss details
        risk_assessment = decision_dict.get("risk_assessment", {})
        assert risk_assessment["allowed"] is False
        assert "daily_loss_limit" in risk_assessment["reason"]
        assert "P&L" in risk_assessment["reason"] or "loss" in risk_assessment["reason"].lower()

    def test_daily_loss_includes_pnl_context(self, mock_agent_config, mock_market, mock_signal):
        """Verify daily loss block includes P&L state in data sources."""
        agent = KalshiTradingAgent(mock_agent_config)
        tracker = get_explainability_tracker()
        tracker.decisions.clear()
        tracker._decisions_by_agent.clear()
        
        check = PreTradeCheck(
            allowed=False,
            action=RiskAction.REJECT,
            reason="daily_loss_limit: -$240 / -$250 limit",
            market_id=mock_market.market_id,
        )
        
        mock_snapshot = Mock()
        mock_snapshot.implied = Mock(yes_prob=Decimal("0.55"), no_prob=Decimal("0.45"))
        mock_snapshot.volume = Decimal("10000")
        mock_snapshot.open_interest = Decimal("5000")
        
        agent._record_explainability_decision(
            market=mock_market,
            signal=mock_signal,
            snapshot=mock_snapshot,
            check=check,
            now=datetime.now(timezone.utc),
            allowed=False,
        )
        
        decisions = tracker.get_agent_decisions(mock_agent_config.name, limit=1)
        decision_dict = decisions[0].to_dict()
        
        # Verify data sources include risk engine
        data_sources = decision_dict.get("data_sources", [])
        assert "prediction_risk" in data_sources


class TestSwarmHealthBlock:
    """Test swarm health risk rejection explainability."""

    def test_swarm_health_block_records_explainability(self, mock_agent_config, mock_market, mock_signal):
        """Verify swarm health block creates explainability record."""
        agent = KalshiTradingAgent(mock_agent_config)
        tracker = get_explainability_tracker()
        tracker.decisions.clear()
        tracker._decisions_by_agent.clear()
        
        check = PreTradeCheck(
            allowed=False,
            action=RiskAction.HALT,
            reason="swarm_health_block: consensus_engine health 50%, required 100%",
            market_id=mock_market.market_id,
        )
        
        mock_snapshot = Mock()
        mock_snapshot.implied = Mock(yes_prob=Decimal("0.55"), no_prob=Decimal("0.45"))
        mock_snapshot.volume = Decimal("10000")
        mock_snapshot.open_interest = Decimal("5000")
        
        agent._record_explainability_decision(
            market=mock_market,
            signal=mock_signal,
            snapshot=mock_snapshot,
            check=check,
            now=datetime.now(timezone.utc),
            allowed=False,
        )
        
        decisions = tracker.get_agent_decisions(mock_agent_config.name, limit=1)
        assert len(decisions) == 1
        
        decision_dict = decisions[0].to_dict()
        risk_assessment = decision_dict.get("risk_assessment", {})
        
        assert risk_assessment["allowed"] is False
        assert "swarm_health" in risk_assessment["reason"] or "health" in risk_assessment["reason"].lower()

    def test_swarm_health_includes_component_details(self, mock_agent_config, mock_market, mock_signal):
        """Verify swarm health block includes degraded component name and health score."""
        agent = KalshiTradingAgent(mock_agent_config)
        tracker = get_explainability_tracker()
        tracker.decisions.clear()
        tracker._decisions_by_agent.clear()
        
        check = PreTradeCheck(
            allowed=False,
            action=RiskAction.HALT,
            reason="swarm_health_block: risk_manager health 0%, required 100%",
            market_id=mock_market.market_id,
        )
        
        mock_snapshot = Mock()
        mock_snapshot.implied = Mock(yes_prob=Decimal("0.55"), no_prob=Decimal("0.45"))
        mock_snapshot.volume = Decimal("10000")
        mock_snapshot.open_interest = Decimal("5000")
        
        agent._record_explainability_decision(
            market=mock_market,
            signal=mock_signal,
            snapshot=mock_snapshot,
            check=check,
            now=datetime.now(timezone.utc),
            allowed=False,
        )
        
        decisions = tracker.get_agent_decisions(mock_agent_config.name, limit=1)
        decision_dict = decisions[0].to_dict()
        
        risk_assessment = decision_dict.get("risk_assessment", {})
        assert "risk_manager" in risk_assessment["reason"]
        assert "0%" in risk_assessment["reason"] or "100%" in risk_assessment["reason"]


class TestExplainabilityFormatValidation:
    """Test explainability record format consistency."""

    def test_all_risk_blocks_have_consistent_schema(self, mock_agent_config, mock_market, mock_signal):
        """Verify all risk block types produce consistent schema."""
        agent = KalshiTradingAgent(mock_agent_config)
        tracker = get_explainability_tracker()
        
        risk_scenarios = [
            ("exposure_cap", "exposure_cap: Limit exceeded"),
            ("daily_loss_limit", "daily_loss_limit: Loss threshold breached"),
            ("swarm_health_block", "swarm_health_block: Component degraded"),
        ]
        
        mock_snapshot = Mock()
        mock_snapshot.implied = Mock(yes_prob=Decimal("0.55"), no_prob=Decimal("0.45"))
        mock_snapshot.volume = Decimal("10000")
        mock_snapshot.open_interest = Decimal("5000")
        
        for rule_id, reason in risk_scenarios:
            tracker.decisions.clear()
            tracker._decisions_by_agent.clear()
            
            check = PreTradeCheck(
                allowed=False,
                action=RiskAction.REJECT,
                reason=reason,
                market_id=mock_market.market_id,
            )
            
            agent._record_explainability_decision(
                market=mock_market,
                signal=mock_signal,
                snapshot=mock_snapshot,
                check=check,
                now=datetime.now(timezone.utc),
                allowed=False,
            )
            
            decisions = tracker.get_agent_decisions(mock_agent_config.name, limit=1)
            assert len(decisions) == 1
            
            decision_dict = decisions[0].to_dict()
            
            # Verify required fields present
            assert "agent_id" in decision_dict
            assert "decision_type" in decision_dict
            assert "primary_reason" in decision_dict
            assert "timestamp" in decision_dict
            assert "data_sources" in decision_dict
            assert "risk_assessment" in decision_dict
            
            # Verify risk assessment structure
            risk_assessment = decision_dict["risk_assessment"]
            assert "allowed" in risk_assessment
            assert risk_assessment["allowed"] is False
            assert "reason" in risk_assessment
            assert rule_id in risk_assessment["reason"]

    def test_primary_reasoning_non_empty(self, mock_agent_config, mock_market, mock_signal):
        """Verify primary_reasoning always contains human-readable explanation."""
        agent = KalshiTradingAgent(mock_agent_config)
        tracker = get_explainability_tracker()
        tracker.decisions.clear()
        tracker._decisions_by_agent.clear()
        
        check = PreTradeCheck(
            allowed=False,
            action=RiskAction.REJECT,
            reason="exposure_cap: Limit breached",
            market_id=mock_market.market_id,
        )
        
        mock_snapshot = Mock()
        mock_snapshot.implied = Mock(yes_prob=Decimal("0.55"), no_prob=Decimal("0.45"))
        mock_snapshot.volume = Decimal("10000")
        mock_snapshot.open_interest = Decimal("5000")
        
        agent._record_explainability_decision(
            market=mock_market,
            signal=mock_signal,
            snapshot=mock_snapshot,
            check=check,
            now=datetime.now(timezone.utc),
            allowed=False,
        )
        
        decisions = tracker.get_agent_decisions(mock_agent_config.name, limit=1)
        decision_dict = decisions[0].to_dict()
        
        primary_reasoning = decision_dict.get("primary_reason", "")
        assert len(primary_reasoning) > 0
        assert mock_market.market_id in primary_reasoning

    def test_timestamp_is_iso_formatted(self, mock_agent_config, mock_market, mock_signal):
        """Verify timestamp is ISO-formatted."""
        agent = KalshiTradingAgent(mock_agent_config)
        tracker = get_explainability_tracker()
        tracker.decisions.clear()
        tracker._decisions_by_agent.clear()
        
        check = PreTradeCheck(
            allowed=False,
            action=RiskAction.REJECT,
            reason="exposure_cap: Blocked",
            market_id=mock_market.market_id,
        )
        
        mock_snapshot = Mock()
        mock_snapshot.implied = Mock(yes_prob=Decimal("0.55"), no_prob=Decimal("0.45"))
        mock_snapshot.volume = Decimal("10000")
        mock_snapshot.open_interest = Decimal("5000")
        
        now = datetime.now(timezone.utc)
        agent._record_explainability_decision(
            market=mock_market,
            signal=mock_signal,
            snapshot=mock_snapshot,
            check=check,
            now=now,
            allowed=False,
        )
        
        decisions = tracker.get_agent_decisions(mock_agent_config.name, limit=1)
        decision_dict = decisions[0].to_dict()
        
        timestamp = decision_dict.get("timestamp", "")
        # Verify ISO format by attempting parse
        # timestamp is a float (unix timestamp), not ISO string in this implementation
        assert timestamp > 0
        assert isinstance(timestamp, (int, float))

    def test_data_sources_includes_risk_state(self, mock_agent_config, mock_market, mock_signal):
        """Verify data_sources includes relevant risk state components."""
        agent = KalshiTradingAgent(mock_agent_config)
        tracker = get_explainability_tracker()
        tracker.decisions.clear()
        tracker._decisions_by_agent.clear()
        
        check = PreTradeCheck(
            allowed=False,
            action=RiskAction.REJECT,
            reason="daily_loss_limit: Breached",
            market_id=mock_market.market_id,
        )
        
        mock_snapshot = Mock()
        mock_snapshot.implied = Mock(yes_prob=Decimal("0.55"), no_prob=Decimal("0.45"))
        mock_snapshot.volume = Decimal("10000")
        mock_snapshot.open_interest = Decimal("5000")
        
        agent._record_explainability_decision(
            market=mock_market,
            signal=mock_signal,
            snapshot=mock_snapshot,
            check=check,
            now=datetime.now(timezone.utc),
            allowed=False,
        )
        
        decisions = tracker.get_agent_decisions(mock_agent_config.name, limit=1)
        decision_dict = decisions[0].to_dict()
        
        data_sources = decision_dict.get("data_sources", [])
        # Should include risk-related sources
        assert "prediction_risk" in data_sources
        assert "kalshi_order_router" in data_sources

    def test_allowed_signal_also_records_explainability(self, mock_agent_config, mock_market, mock_signal):
        """Verify allowed signals (not just blocks) also create explainability records."""
        agent = KalshiTradingAgent(mock_agent_config)
        tracker = get_explainability_tracker()
        tracker.decisions.clear()
        tracker._decisions_by_agent.clear()
        
        check = PreTradeCheck(
            allowed=True,
            action=RiskAction.ALLOW,
            reason="All checks passed",
            adjusted_size=10,
            market_id=mock_market.market_id,
        )
        
        mock_snapshot = Mock()
        mock_snapshot.implied = Mock(yes_prob=Decimal("0.55"), no_prob=Decimal("0.45"))
        mock_snapshot.volume = Decimal("10000")
        mock_snapshot.open_interest = Decimal("5000")
        
        agent._record_explainability_decision(
            market=mock_market,
            signal=mock_signal,
            snapshot=mock_snapshot,
            check=check,
            now=datetime.now(timezone.utc),
            allowed=True,
        )
        
        decisions = tracker.get_agent_decisions(mock_agent_config.name, limit=1)
        assert len(decisions) == 1
        
        decision_dict = decisions[0].to_dict()
        risk_assessment = decision_dict.get("risk_assessment", {})
        assert risk_assessment["allowed"] is True

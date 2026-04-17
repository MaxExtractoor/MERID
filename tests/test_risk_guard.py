"""
Comprehensive tests for RiskGuard module.

Tests cover:
- Kill switch functionality
- Risk limit enforcement
- Tradable universe management
- Portfolio state tracking
- Trade plan review logic
- Pause/resume functionality
- Limit updates
"""

import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch

from risk.risk_guard import (
    RiskGuard,
    RiskLimits,
    TradableUniverse,
    PortfolioState,
    TradePlanInput,
    RiskReviewResult,
    RiskDecision,
    LimitType,
    get_risk_guard,
    review_trade_plan,
)


@pytest.fixture
def risk_guard():
    """Create a fresh RiskGuard instance for each test."""
    # Reset singleton
    RiskGuard._instance = None
    guard = RiskGuard()
    
    # Set up basic tradable universe
    guard.add_symbol("BTC", max_position_usd=5000.0)
    guard.add_symbol("ETH", max_position_usd=3000.0)
    guard.add_venue("binance")
    guard.add_venue("coinbase")
    
    return guard


@pytest.fixture
def sample_trade_plan():
    """Create a sample trade plan for testing."""
    return TradePlanInput(
        plan_id="test_plan_001",
        symbol="BTC",
        venue="binance",
        direction="long",
        target_size_usd=1000.0,
        confidence=0.75,
        agent_id="test_agent",
        consensus_score=0.8
    )


class TestKillSwitch:
    """Test kill switch functionality."""
    
    @pytest.mark.asyncio
    async def test_trigger_kill_switch(self, risk_guard):
        """Test triggering the kill switch."""
        assert not risk_guard.is_kill_switch_active()
        
        await risk_guard.trigger_kill_switch("Emergency stop", "admin")
        
        assert risk_guard.is_kill_switch_active()
        assert risk_guard._kill_switch_reason == "Emergency stop"
    
    @pytest.mark.asyncio
    async def test_kill_switch_blocks_trades(self, risk_guard, sample_trade_plan):
        """Test that kill switch blocks all trades."""
        await risk_guard.trigger_kill_switch("Testing", "admin")
        
        result = await risk_guard.review_plan(sample_trade_plan)
        
        assert result.decision == RiskDecision.VETO
        assert "Kill switch active" in result.reason
        assert "KILL_SWITCH_ACTIVE" in result.limit_breaches
    
    @pytest.mark.asyncio
    async def test_reset_kill_switch_requires_confirmation(self, risk_guard):
        """Test that resetting kill switch requires confirmation code."""
        await risk_guard.trigger_kill_switch("Testing", "admin")
        
        # Wrong confirmation code
        success = await risk_guard.reset_kill_switch("admin", "WRONG_CODE")
        assert not success
        assert risk_guard.is_kill_switch_active()
        
        # Correct confirmation code
        success = await risk_guard.reset_kill_switch("admin", "CONFIRM_RESET_TRADING")
        assert success
        assert not risk_guard.is_kill_switch_active()
    
    @pytest.mark.asyncio
    async def test_kill_switch_emits_events(self, risk_guard):
        """Test that kill switch emits governance events."""
        events = []
        
        def event_handler(event_type, data):
            events.append((event_type, data))
        
        risk_guard.subscribe_events(event_handler)
        
        await risk_guard.trigger_kill_switch("Testing", "admin")
        
        assert len(events) == 1
        assert events[0][0] == "governance.kill_switch"
        assert events[0][1]["active"] is True


class TestPauseResume:
    """Test pause/resume functionality."""
    
    @pytest.mark.asyncio
    async def test_pause_trading(self, risk_guard):
        """Test pausing trading."""
        await risk_guard.pause_trading("Maintenance", "admin")
        
        assert risk_guard._paused
        assert risk_guard._pause_reason == "Maintenance"
    
    @pytest.mark.asyncio
    async def test_pause_blocks_trades(self, risk_guard, sample_trade_plan):
        """Test that pause blocks trades."""
        await risk_guard.pause_trading("Testing", "admin")
        
        result = await risk_guard.review_plan(sample_trade_plan)
        
        assert result.decision == RiskDecision.REJECT
        assert "Trading paused" in result.reason
        assert "TRADING_PAUSED" in result.limit_breaches
    
    @pytest.mark.asyncio
    async def test_resume_trading(self, risk_guard, sample_trade_plan):
        """Test resuming trading."""
        await risk_guard.pause_trading("Testing", "admin")
        await risk_guard.resume_trading("admin")
        
        assert not risk_guard._paused
        
        # Trade should now be allowed
        result = await risk_guard.review_plan(sample_trade_plan)
        assert result.decision in [RiskDecision.APPROVE, RiskDecision.APPROVE_REDUCED]


class TestTradableUniverse:
    """Test tradable universe management."""
    
    def test_add_symbol(self, risk_guard):
        """Test adding a symbol to tradable universe."""
        risk_guard.add_symbol("SOL", max_position_usd=2000.0)
        
        assert "SOL" in risk_guard.universe.allowed_symbols
        assert risk_guard.universe.is_symbol_allowed("SOL")
        assert risk_guard.universe.get_symbol_limit("SOL", 0) == 2000.0
    
    def test_remove_symbol(self, risk_guard):
        """Test removing a symbol from tradable universe."""
        risk_guard.remove_symbol("BTC")
        
        assert "BTC" in risk_guard.universe.blocked_symbols
        assert not risk_guard.universe.is_symbol_allowed("BTC")
    
    @pytest.mark.asyncio
    async def test_blocked_symbol_rejects_trade(self, risk_guard, sample_trade_plan):
        """Test that blocked symbols are rejected."""
        risk_guard.remove_symbol("BTC")
        
        result = await risk_guard.review_plan(sample_trade_plan)
        
        assert result.decision == RiskDecision.REJECT
        assert "not in tradable universe" in result.reason
        assert "SYMBOL_NOT_ALLOWED" in result.limit_breaches
    
    def test_add_venue(self, risk_guard):
        """Test adding a venue."""
        risk_guard.add_venue("kraken")
        
        assert "kraken" in risk_guard.universe.allowed_venues
        assert risk_guard.universe.is_venue_allowed("kraken")
    
    def test_remove_venue(self, risk_guard):
        """Test removing a venue."""
        risk_guard.remove_venue("binance")
        
        assert "binance" in risk_guard.universe.blocked_venues
        assert not risk_guard.universe.is_venue_allowed("binance")
    
    @pytest.mark.asyncio
    async def test_blocked_venue_rejects_trade(self, risk_guard, sample_trade_plan):
        """Test that blocked venues are rejected."""
        risk_guard.remove_venue("binance")
        
        result = await risk_guard.review_plan(sample_trade_plan)
        
        assert result.decision == RiskDecision.REJECT
        assert "not in allowed venues" in result.reason
        assert "VENUE_NOT_ALLOWED" in result.limit_breaches


class TestRiskLimits:
    """Test risk limit enforcement."""
    
    @pytest.mark.asyncio
    async def test_confidence_limit(self, risk_guard, sample_trade_plan):
        """Test minimum confidence requirement."""
        sample_trade_plan.confidence = 0.3  # Below default 0.5
        
        result = await risk_guard.review_plan(sample_trade_plan)
        
        assert result.decision == RiskDecision.REJECT
        assert "Confidence" in result.reason
        assert "LOW_CONFIDENCE" in result.limit_breaches
    
    @pytest.mark.asyncio
    async def test_single_trade_limit(self, risk_guard, sample_trade_plan):
        """Test single trade size limit."""
        sample_trade_plan.target_size_usd = 10000.0  # Above default 5000
        
        result = await risk_guard.review_plan(sample_trade_plan)
        
        assert result.decision == RiskDecision.APPROVE_REDUCED
        assert result.approved_size_usd == 5000.0
        assert "max single trade limit" in result.warnings[0]
    
    @pytest.mark.asyncio
    async def test_position_limit(self, risk_guard, sample_trade_plan):
        """Test position size limit per symbol."""
        # Set existing position
        risk_guard.portfolio.positions["BTC"] = 4500.0
        
        # Try to add 1000 more (would exceed 5000 limit)
        sample_trade_plan.target_size_usd = 1000.0
        
        result = await risk_guard.review_plan(sample_trade_plan)
        
        assert result.decision == RiskDecision.APPROVE_REDUCED
        assert result.approved_size_usd == 500.0  # Only 500 available
    
    @pytest.mark.asyncio
    async def test_position_limit_exceeded(self, risk_guard, sample_trade_plan):
        """Test rejection when position limit already exceeded."""
        # Set position at limit
        risk_guard.portfolio.positions["BTC"] = 5000.0
        
        result = await risk_guard.review_plan(sample_trade_plan)
        
        assert result.decision == RiskDecision.REJECT
        assert "Position limit reached" in result.reason
        assert "POSITION_LIMIT" in result.limit_breaches
    
    @pytest.mark.asyncio
    async def test_total_exposure_limit(self, risk_guard, sample_trade_plan):
        """Test total exposure limit."""
        # Set high total exposure
        risk_guard.portfolio.total_exposure_usd = 99000.0
        risk_guard.limits.max_total_exposure_usd = 100000.0
        
        sample_trade_plan.target_size_usd = 2000.0
        
        result = await risk_guard.review_plan(sample_trade_plan)
        
        assert result.decision == RiskDecision.APPROVE_REDUCED
        assert result.approved_size_usd == 1000.0  # Only 1000 available
    
    @pytest.mark.asyncio
    async def test_daily_loss_limit(self, risk_guard, sample_trade_plan):
        """Test daily loss limit triggers veto."""
        risk_guard.portfolio.daily_pnl_usd = -5000.0  # At limit
        
        result = await risk_guard.review_plan(sample_trade_plan)
        
        assert result.decision == RiskDecision.VETO
        assert "Daily loss limit reached" in result.reason
        assert "DAILY_LOSS_LIMIT" in result.limit_breaches
    
    @pytest.mark.asyncio
    async def test_drawdown_limit(self, risk_guard, sample_trade_plan):
        """Test max drawdown limit triggers veto."""
        risk_guard.portfolio.current_drawdown_pct = 10.0  # At limit
        
        result = await risk_guard.review_plan(sample_trade_plan)
        
        assert result.decision == RiskDecision.VETO
        assert "Max drawdown reached" in result.reason
        assert "MAX_DRAWDOWN" in result.limit_breaches
    
    @pytest.mark.asyncio
    async def test_concentration_warning(self, risk_guard, sample_trade_plan):
        """Test concentration warning."""
        risk_guard.portfolio.total_exposure_usd = 10000.0
        risk_guard.portfolio.positions["BTC"] = 2000.0
        
        sample_trade_plan.target_size_usd = 1000.0
        
        result = await risk_guard.review_plan(sample_trade_plan)
        
        # Should approve but warn about concentration
        assert result.decision in [RiskDecision.APPROVE, RiskDecision.APPROVE_REDUCED]
        assert any("concentration" in w.lower() for w in result.warnings)


class TestRateLimits:
    """Test rate limiting functionality."""
    
    @pytest.mark.asyncio
    async def test_time_between_trades(self, risk_guard, sample_trade_plan):
        """Test minimum time between trades."""
        risk_guard.portfolio.last_trade_time = time.time() - 30  # 30 seconds ago
        risk_guard.limits.min_time_between_trades_seconds = 60.0
        
        result = await risk_guard.review_plan(sample_trade_plan)
        
        assert result.decision == RiskDecision.REJECT
        assert "Too soon since last trade" in result.reason
        assert "TRADE_RATE_LIMIT" in result.limit_breaches
    
    @pytest.mark.asyncio
    async def test_hourly_trade_limit(self, risk_guard, sample_trade_plan):
        """Test hourly trade count limit."""
        # Fill up hourly trades
        now = time.time()
        risk_guard._hourly_trades = [now - i for i in range(20)]
        risk_guard.limits.max_trades_per_hour = 20
        
        result = await risk_guard.review_plan(sample_trade_plan)
        
        assert result.decision == RiskDecision.REJECT
        assert "Hourly trade limit reached" in result.reason
        assert "HOURLY_TRADE_LIMIT" in result.limit_breaches


class TestPortfolioTracking:
    """Test portfolio state tracking."""
    
    def test_record_trade(self, risk_guard):
        """Test recording a trade."""
        risk_guard.record_trade("BTC", 1000.0, pnl_usd=50.0)
        
        assert risk_guard.portfolio.daily_trades == 1
        assert risk_guard.portfolio.daily_pnl_usd == 50.0
        assert risk_guard.portfolio.positions["BTC"] == 1000.0
        assert len(risk_guard._hourly_trades) == 1
    
    def test_update_portfolio(self, risk_guard):
        """Test updating portfolio state."""
        new_state = PortfolioState(
            total_exposure_usd=50000.0,
            net_exposure_usd=30000.0,
            positions={"BTC": 20000.0, "ETH": 30000.0},
            daily_pnl_usd=500.0,
            daily_trades=10,
            current_drawdown_pct=5.0
        )
        
        risk_guard.update_portfolio(new_state)
        
        assert risk_guard.portfolio.total_exposure_usd == 50000.0
        assert risk_guard.portfolio.positions["BTC"] == 20000.0
        assert risk_guard.portfolio.daily_trades == 10
    
    def test_get_position_size(self, risk_guard):
        """Test getting position size."""
        risk_guard.portfolio.positions["BTC"] = 5000.0
        
        assert risk_guard.portfolio.get_position_size("BTC") == 5000.0
        assert risk_guard.portfolio.get_position_size("ETH") == 0.0
    
    def test_get_concentration(self, risk_guard):
        """Test calculating concentration."""
        risk_guard.portfolio.total_exposure_usd = 10000.0
        risk_guard.portfolio.positions["BTC"] = 2500.0
        
        concentration = risk_guard.portfolio.get_concentration("BTC")
        assert concentration == 25.0


class TestLimitUpdates:
    """Test updating risk limits."""
    
    @pytest.mark.asyncio
    async def test_update_limits(self, risk_guard):
        """Test updating risk limits."""
        old_version = risk_guard.limits.version
        
        new_limits = {
            "max_single_trade_usd": 10000.0,
            "max_daily_loss_usd": 10000.0
        }
        
        success = await risk_guard.update_limits(new_limits, "admin")
        
        assert success
        assert risk_guard.limits.max_single_trade_usd == 10000.0
        assert risk_guard.limits.max_daily_loss_usd == 10000.0
        assert risk_guard.limits.version != old_version
        assert risk_guard.limits.updated_by == "admin"
    
    @pytest.mark.asyncio
    async def test_limit_update_emits_event(self, risk_guard):
        """Test that limit updates emit governance events."""
        events = []
        
        def event_handler(event_type, data):
            events.append((event_type, data))
        
        risk_guard.subscribe_events(event_handler)
        
        await risk_guard.update_limits({"max_leverage": 5.0}, "admin")
        
        assert len(events) == 1
        assert events[0][0] == "governance.limit_change"


class TestReviewHistory:
    """Test review history tracking."""
    
    @pytest.mark.asyncio
    async def test_review_history_recorded(self, risk_guard, sample_trade_plan):
        """Test that reviews are recorded in history."""
        initial_count = len(risk_guard._review_history)
        
        await risk_guard.review_plan(sample_trade_plan)
        
        assert len(risk_guard._review_history) == initial_count + 1
    
    def test_get_recent_reviews(self, risk_guard):
        """Test getting recent reviews."""
        # Add some mock reviews
        for i in range(10):
            result = RiskReviewResult(
                plan_id=f"plan_{i}",
                decision=RiskDecision.APPROVE,
                approved_size_usd=1000.0
            )
            risk_guard._review_history.append(result)
        
        recent = risk_guard.get_recent_reviews(limit=5)
        
        assert len(recent) == 5
        assert recent[-1]["plan_id"] == "plan_9"


class TestStatusReporting:
    """Test status and metrics reporting."""
    
    def test_get_status(self, risk_guard):
        """Test getting risk guard status."""
        status = risk_guard.get_status()
        
        assert "kill_switch_active" in status
        assert "paused" in status
        assert "limits" in status
        assert "portfolio" in status
        assert "hourly_trades" in status
        assert "review_count" in status
    
    def test_status_reflects_kill_switch(self, risk_guard):
        """Test that status reflects kill switch state."""
        status_before = risk_guard.get_status()
        assert not status_before["kill_switch_active"]
        
        asyncio.run(risk_guard.trigger_kill_switch("Testing", "admin"))
        
        status_after = risk_guard.get_status()
        assert status_after["kill_switch_active"]
        assert status_after["kill_switch_reason"] == "Testing"


class TestSingleton:
    """Test singleton pattern."""
    
    def test_get_risk_guard_returns_singleton(self):
        """Test that get_risk_guard returns the same instance."""
        RiskGuard._instance = None
        
        guard1 = get_risk_guard()
        guard2 = get_risk_guard()
        
        assert guard1 is guard2
    
    def test_get_instance_returns_singleton(self):
        """Test that get_instance returns the same instance."""
        RiskGuard._instance = None
        
        guard1 = RiskGuard.get_instance()
        guard2 = RiskGuard.get_instance()
        
        assert guard1 is guard2


class TestConvenienceFunctions:
    """Test convenience functions."""
    
    @pytest.mark.asyncio
    async def test_review_trade_plan_function(self, risk_guard):
        """Test the review_trade_plan convenience function."""
        risk_guard.add_symbol("BTC")
        risk_guard.add_venue("binance")
        
        is_approved, approved_size, reason = await review_trade_plan(
            plan_id="test_001",
            symbol="BTC",
            venue="binance",
            direction="long",
            target_size_usd=1000.0,
            confidence=0.75,
            agent_id="test_agent"
        )
        
        assert isinstance(is_approved, bool)
        assert isinstance(approved_size, float)
        assert isinstance(reason, str)


class TestComplexScenarios:
    """Test complex multi-constraint scenarios."""
    
    @pytest.mark.asyncio
    async def test_multiple_constraints_applied(self, risk_guard, sample_trade_plan):
        """Test that multiple constraints are properly applied."""
        # Set up a scenario where multiple limits apply
        risk_guard.portfolio.total_exposure_usd = 95000.0
        risk_guard.limits.max_total_exposure_usd = 100000.0
        
        sample_trade_plan.target_size_usd = 10000.0  # Would exceed both single trade and exposure
        
        result = await risk_guard.review_plan(sample_trade_plan)
        
        assert result.decision == RiskDecision.APPROVE_REDUCED
        assert result.approved_size_usd < sample_trade_plan.target_size_usd
        assert len(result.warnings) > 0
    
    @pytest.mark.asyncio
    async def test_approved_trade_within_all_limits(self, risk_guard, sample_trade_plan):
        """Test that a trade within all limits is approved."""
        result = await risk_guard.review_plan(sample_trade_plan)
        
        assert result.decision == RiskDecision.APPROVE
        assert result.approved_size_usd == sample_trade_plan.target_size_usd
        assert "Approved within all limits" in result.reason
        assert len(result.limit_breaches) == 0

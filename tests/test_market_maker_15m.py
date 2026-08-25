"""Tests for 15m market making agent."""

import pytest
from unittest.mock import Mock, patch
import time
from datetime import datetime, timezone, timedelta


class TestMarketMakingConfig:
    """Test market making configuration."""
    
    def test_default_config(self):
        """Test default configuration values."""
        from merid.event_venues.kalshi.market_maker_15m import MarketMakingConfig
        
        config = MarketMakingConfig()
        assert config.enabled is False
        assert config.quoting_mode == "two_phase"
        assert config.spread_cents == 2
        assert config.inventory_limit_contracts == 50
        assert config.skew_adjustment is True
        assert config.phase1_duration_seconds == 720
        assert config.phase1_price_center_cents == 50
        assert config.phase1_spread_cents == 3
        assert config.phase1_refresh_interval_seconds == 15
        assert config.phase1_contracts_per_side == 15
        assert config.phase2_price_cents == 52
        assert config.phase2_contracts == 15
    
    def test_custom_config(self):
        """Test custom configuration values."""
        from merid.event_venues.kalshi.market_maker_15m import MarketMakingConfig
        
        config = MarketMakingConfig(
            enabled=True,
            quoting_mode="one_sided",
            spread_cents=3,
            inventory_limit_contracts=100,
            skew_adjustment=False,
            phase1_duration_seconds=600,
            phase1_contracts_per_side=20
        )
        
        assert config.enabled is True
        assert config.quoting_mode == "one_sided"
        assert config.spread_cents == 3
        assert config.inventory_limit_contracts == 100
        assert config.skew_adjustment is False
        assert config.phase1_duration_seconds == 600
        assert config.phase1_contracts_per_side == 20


class TestMarketMaker15m:
    """Test MarketMaker15m class."""
    
    @pytest.fixture
    def enabled_config(self):
        """Create enabled market making configuration."""
        from merid.event_venues.kalshi.market_maker_15m import MarketMakingConfig
        return MarketMakingConfig(enabled=True)
    
    @pytest.fixture
    def disabled_config(self):
        """Create disabled market making configuration."""
        from merid.event_venues.kalshi.market_maker_15m import MarketMakingConfig
        return MarketMakingConfig(enabled=False)
    
    def test_initialization_disabled(self, disabled_config):
        """Test initialization with disabled config."""
        from merid.event_venues.kalshi.market_maker_15m import MarketMaker15m
        
        mm = MarketMaker15m(disabled_config)
        assert mm._running is False
        assert mm.get_phase().value == "disabled"
    
    def test_initialization_enabled(self, enabled_config):
        """Test initialization with enabled config."""
        from merid.event_venues.kalshi.market_maker_15m import MarketMaker15m
        
        mm = MarketMaker15m(enabled_config)
        assert mm._running is False  # Not running until start() is called
        assert mm.config.enabled is True
    
    def test_start_stop(self, enabled_config):
        """Test start and stop lifecycle."""
        from merid.event_venues.kalshi.market_maker_15m import MarketMaker15m, MarketMakingPhase
        
        mm = MarketMaker15m(enabled_config)
        
        # Start
        window_start = datetime.now(timezone.utc)
        mm.start(window_start)
        
        assert mm._running is True
        assert mm.get_phase() == MarketMakingPhase.PHASE1_TWO_SIDED
        
        # Stop
        mm.stop()
        
        assert mm._running is False
        assert mm.get_phase() == MarketMakingPhase.DISABLED
    
    def test_phase_transition(self, enabled_config):
        """Test phase transition from Phase 1 to Phase 2."""
        from merid.event_venues.kalshi.market_maker_15m import MarketMaker15m, MarketMakingPhase
        
        mm = MarketMaker15m(enabled_config)
        mm.start(datetime.now(timezone.utc))
        
        # Initially in Phase 1
        assert mm.get_phase() == MarketMakingPhase.PHASE1_TWO_SIDED
        
        # Simulate time passing beyond phase1_duration
        mm._phase_start_time = time.time() - 800  # 800s ago (beyond 720s)
        
        # Should be in Phase 2
        assert mm.get_phase() == MarketMakingPhase.PHASE2_DIRECTIONAL
    
    def test_should_refresh_quotes_phase1(self, enabled_config):
        """Test quote refresh logic in Phase 1."""
        from merid.event_venues.kalshi.market_maker_15m import MarketMaker15m
        
        mm = MarketMaker15m(enabled_config)
        mm.start(datetime.now(timezone.utc))
        
        # Initially should refresh (last refresh was at start)
        assert mm.should_refresh_quotes() is True
        
        # After refresh, should not refresh immediately
        mm._last_quote_refresh = time.time()
        assert mm.should_refresh_quotes() is False
        
        # After refresh interval, should refresh again
        mm._last_quote_refresh = time.time() - 20  # 20s ago (beyond 15s)
        assert mm.should_refresh_quotes() is True
    
    def test_should_refresh_quotes_phase2(self, enabled_config):
        """Test quote refresh logic in Phase 2 (no refresh)."""
        from merid.event_venues.kalshi.market_maker_15m import MarketMaker15m
        
        mm = MarketMaker15m(enabled_config)
        mm.start(datetime.now(timezone.utc))
        
        # Move to Phase 2
        mm._phase_start_time = time.time() - 800
        
        # Phase 2 should not refresh (single directional quote)
        assert mm.should_refresh_quotes() is False
    
    def test_generate_phase1_quotes(self, enabled_config):
        """Test Phase 1 quote generation (BUY-only entries per exit policy)."""
        from merid.event_venues.kalshi.market_maker_15m import MarketMaker15m
        
        mm = MarketMaker15m(enabled_config)
        mm.start(datetime.now(timezone.utc))
        
        quotes = mm.generate_quotes(
            ticker="KXBTCD-TEST",
            yes_bid=48,
            yes_ask=52,
            no_bid=48,
            no_ask=52,
            seconds_to_expiry=600
        )
        
        # CRITICAL FIX (2026-08-08): Should generate 2 quotes (YES bid, NO bid) only
        # SELL actions are reserved for exit trades only per exit policy
        assert len(quotes) == 2
        
        # Check quote properties - all should be BUY actions
        for quote in quotes:
            assert quote.action == "buy", f"Market maker must only generate BUY entries, got {quote.action}"
        
        # Check YES bid quote
        yes_bid_quote = [q for q in quotes if q.side == "yes"][0]
        assert yes_bid_quote.price_cents == 47  # 50 - 3 spread
        assert yes_bid_quote.size_contracts == 15
        assert yes_bid_quote.action == "buy"
        
        # Check NO bid quote
        no_bid_quote = [q for q in quotes if q.side == "no"][0]
        assert no_bid_quote.price_cents == 47  # (100 - 50) - 3 spread = 47
        assert no_bid_quote.size_contracts == 15
        assert no_bid_quote.action == "buy"
    
    def test_phase1_quotes_no_sell_actions(self, enabled_config):
        """Test Phase 1 quotes never include SELL actions (entry/exit invariant)."""
        from merid.event_venues.kalshi.market_maker_15m import MarketMaker15m
        
        mm = MarketMaker15m(enabled_config)
        mm.start(datetime.now(timezone.utc))
        
        quotes = mm.generate_quotes(
            ticker="KXBTCD-TEST",
            yes_bid=48,
            yes_ask=52,
            no_bid=48,
            no_ask=52,
            seconds_to_expiry=600
        )
        
        # CRITICAL INVARIANT: Market maker must never generate SELL entries
        # SELL actions are reserved for exit trades only per exit policy
        for quote in quotes:
            assert quote.action == "buy", (
                f"Market maker entry invariant violation: quote has action={quote.action}, "
                f"only 'buy' allowed for entries. SELL actions are for exits only."
            )
    
    def test_generate_phase2_quotes(self, enabled_config):
        """Test Phase 2 directional quote generation (BUY-only entry)."""
        from merid.event_venues.kalshi.market_maker_15m import MarketMaker15m
        
        mm = MarketMaker15m(enabled_config)
        mm.start(datetime.now(timezone.utc))
        
        # Move to Phase 2
        mm._phase_start_time = time.time() - 800
        
        # YES ask < 50c -> market favors YES
        quotes = mm.generate_quotes(
            ticker="KXBTCD-TEST",
            yes_bid=45,
            yes_ask=47,  # Below 50c
            no_bid=53,
            no_ask=55,
            seconds_to_expiry=300
        )
        
        # Should generate 1 directional quote
        assert len(quotes) == 1
        assert quotes[0].side == "yes"
        assert quotes[0].price_cents == 52  # Phase 2 price
        assert quotes[0].size_contracts == 15
        assert quotes[0].action == "buy"  # CRITICAL: Must be BUY action
    
    def test_inventory_limit(self, enabled_config):
        """Test inventory limit enforcement."""
        from merid.event_venues.kalshi.market_maker_15m import MarketMaker15m
        
        mm = MarketMaker15m(enabled_config)
        mm.start(datetime.now(timezone.utc))
        
        # Update inventory to near limit
        mm.update_inventory("KXBTCD-TEST", "yes", 50, 50)
        
        # Should not generate quotes when at limit
        quotes = mm.generate_quotes(
            ticker="KXBTCD-TEST",
            yes_bid=48,
            yes_ask=52,
            no_bid=48,
            no_ask=52,
            seconds_to_expiry=600
        )
        
        assert len(quotes) == 0
    
    def test_skew_adjustment(self, enabled_config):
        """Test inventory skew adjustment."""
        from merid.event_venues.kalshi.market_maker_15m import MarketMaker15m
        
        mm = MarketMaker15m(enabled_config)
        mm.start(datetime.now(timezone.utc))
        
        # Build up YES position
        mm.update_inventory("KXBTCD-TEST", "yes", 30, 50)
        
        quotes = mm.generate_quotes(
            ticker="KXBTCD-TEST",
            yes_bid=48,
            yes_ask=52,
            no_bid=48,
            no_ask=52,
            seconds_to_expiry=600
        )
        
        # With skew adjustment, quotes should be skewed away from YES
        # (i.e., center price should be higher when long YES)
        # Skew = min(5, 30 // 5) = 6, but capped at 5
        # Center moves from 50 to 55 (50 + 5)
        # YES bid = 55 - 3 = 52 (BUY only - no ask)
        # NO bid = (100 - 55) - 3 = 42 (BUY only - no ask)
        
        yes_quotes = [q for q in quotes if q.side == "yes"]
        no_quotes = [q for q in quotes if q.side == "no"]
        
        # CRITICAL FIX (2026-08-08): Only 1 quote per side (BUY only)
        assert len(yes_quotes) == 1
        assert len(no_quotes) == 1
        
        # When skewed up (long YES), YES quote should be higher than base (50)
        # and NO quote should be lower than base (50)
        yes_quote = yes_quotes[0]
        no_quote = no_quotes[0]
        
        # YES quote should be > 50 (skewed up)
        assert yes_quote.price_cents > 50
        # NO quote should be < 50 (skewed down)
        assert no_quote.price_cents < 50
        
        # Both should be BUY actions
        assert yes_quote.action == "buy"
        assert no_quote.action == "buy"
    
    def test_price_clamping(self, enabled_config):
        """Test price clamping to 10-75c range."""
        from merid.event_venues.kalshi.market_maker_15m import MarketMaker15m
        
        mm = MarketMaker15m(enabled_config)
        mm.start(datetime.now(timezone.utc))
        
        # Use extreme market prices
        quotes = mm.generate_quotes(
            ticker="KXBTCD-TEST",
            yes_bid=5,   # Below 10c
            yes_ask=95,  # Above 75c
            no_bid=5,
            no_ask=95,
            seconds_to_expiry=600
        )
        
        # All quotes should be clamped to 10-75c range
        for quote in quotes:
            assert 10 <= quote.price_cents <= 75
    
    def test_inventory_tracking(self, enabled_config):
        """Test inventory state tracking."""
        from merid.event_venues.kalshi.market_maker_15m import MarketMaker15m
        
        mm = MarketMaker15m(enabled_config)
        mm.start(datetime.now(timezone.utc))
        
        # Add YES position
        mm.update_inventory("KXBTCD-TEST", "yes", 10, 50)
        
        inventory = mm.get_inventory_state("KXBTCD-TEST")
        assert inventory is not None
        assert inventory.yes_contracts == 10
        assert inventory.no_contracts == 0
        assert inventory.net_position == 10
        
        # Add NO position
        mm.update_inventory("KXBTCD-TEST", "no", 5, 50)
        
        inventory = mm.get_inventory_state("KXBTCD-TEST")
        assert inventory.yes_contracts == 10
        assert inventory.no_contracts == 5
        assert inventory.net_position == 5  # 10 - 5


class TestMarketMakerSingleton:
    """Test market maker singleton pattern."""
    
    def test_singleton_initialization(self):
        """Test singleton initialization."""
        from merid.event_venues.kalshi.market_maker_15m import (
            init_market_maker_15m,
            get_market_maker_15m,
            MarketMakingConfig
        )
        
        config = MarketMakingConfig(enabled=True)
        mm = init_market_maker_15m(config)
        
        # Should return same instance
        mm2 = get_market_maker_15m()
        assert mm is mm2
    
    def test_singleton_reset(self):
        """Test singleton reset."""
        from merid.event_venues.kalshi.market_maker_15m import (
            init_market_maker_15m,
            get_market_maker_15m,
            reset_market_maker_15m,
            MarketMakingConfig
        )
        
        config = MarketMakingConfig(enabled=True)
        mm1 = init_market_maker_15m(config)
        
        # Reset
        reset_market_maker_15m()
        
        # Should return None after reset
        mm2 = get_market_maker_15m()
        assert mm2 is None
        
        # Can reinitialize
        mm3 = init_market_maker_15m(config)
        assert mm3 is not None

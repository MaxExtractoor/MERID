"""Tests for per-coin fill rate tracking in KalshiFillsLedger."""

import pytest
from datetime import datetime, timedelta, timezone
from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger, KalshiFill, OrderIntent


class TestFillRateTracking:
    """Tests for get_fill_rate_stats method."""
    
    @pytest.fixture
    def ledger(self):
        """Create a fresh ledger for each test."""
        # Reset singleton to avoid test pollution
        from merid.event_venues.kalshi import fills_ledger
        fills_ledger._ledger = None
        fills_ledger.KalshiFillsLedger._instance = None
        fills_ledger.KalshiFillsLedger._initialized = False
        
        ledger = fills_ledger.KalshiFillsLedger()
        return ledger
    
    def test_fill_rate_basic(self, ledger):
        """Test basic fill rate calculation."""
        # Add intents for BTC
        intent1 = OrderIntent(
            intent_id="intent1",
            ticker="KXBTC-15M-ABOVE-75000",
            side="yes",
            action="buy",
            count=10,
            price_cents=50,
            agent_id="agent1"
        )
        ledger.record_intent(intent1)
        
        intent2 = OrderIntent(
            intent_id="intent2",
            ticker="KXBTC-15M-ABOVE-75000",
            side="yes",
            action="buy",
            count=10,
            price_cents=50,
            agent_id="agent1"
        )
        ledger.record_intent(intent2)
        
        # Add fills for BTC (1 fill, 1 intent filled)
        fill1 = KalshiFill(
            fill_id="fill1",
            market_ticker="KXBTC-15M-ABOVE-75000",
            side="yes",
            action="buy",
            count_fp=10,
            yes_price_dollars=0.50,
            fee_cost=0.01,
            proceeds_dollars=-5.01,
            asset="BTC",
            intent_id="intent1",
            created_time=datetime.now(timezone.utc)
        )
        ledger._fills["fill1"] = fill1
        
        stats = ledger.get_fill_rate_stats()
        
        assert "BTC" in stats
        assert stats["BTC"]["intents"] == 2.0
        assert stats["BTC"]["fills"] == 1.0
        assert stats["BTC"]["fill_rate"] == 0.5
        assert stats["BTC"]["partial_fills"] == 0.0
    
    def test_fill_rate_per_asset(self, ledger):
        """Test fill rate tracking for BTC."""
        btc_intent = OrderIntent(
            intent_id="btc_intent",
            ticker="KXBTC-15M-ABOVE-75000",
            side="yes",
            action="buy",
            count=10,
            price_cents=50,
            agent_id="agent1"
        )
        ledger.record_intent(btc_intent)
        
        fill_btc = KalshiFill(
            fill_id="fill_btc",
            market_ticker="KXBTC-15M-ABOVE-75000",
            side="yes",
            action="buy",
            count_fp=10,
            yes_price_dollars=0.50,
            fee_cost=0.01,
            proceeds_dollars=-5.01,
            asset="BTC",
            intent_id="btc_intent",
            created_time=datetime.now(timezone.utc)
        )
        ledger._fills["fill_btc"] = fill_btc
        
        stats = ledger.get_fill_rate_stats()
        assert "BTC" in stats
        assert stats["BTC"]["fill_rate"] == 1.0
    
    def test_fill_rate_eth(self, ledger):
        """Test fill rate tracking for ETH."""
        eth_intent = OrderIntent(
            intent_id="eth_intent",
            ticker="KXETH-15M-ABOVE-3500",
            side="yes",
            action="buy",
            count=10,
            price_cents=50,
            agent_id="agent1"
        )
        ledger.record_intent(eth_intent)
        
        fill_eth = KalshiFill(
            fill_id="fill_eth",
            market_ticker="KXETH-15M-ABOVE-3500",
            side="yes",
            action="buy",
            count_fp=10,
            yes_price_dollars=0.50,
            fee_cost=0.01,
            proceeds_dollars=-5.01,
            asset="ETH",
            intent_id="eth_intent",
            created_time=datetime.now(timezone.utc)
        )
        ledger._fills["fill_eth"] = fill_eth
        
        stats = ledger.get_fill_rate_stats()
        assert "ETH" in stats
        assert stats["ETH"]["fill_rate"] == 1.0
    
    def test_fill_rate_with_partial_fills(self, ledger):
        """Test fill rate with partial fills."""
        # Add intent for 10 contracts
        intent1 = OrderIntent(
            intent_id="intent1",
            ticker="KXBTC-15M-ABOVE-75000",
            side="yes",
            action="buy",
            count=10,
            price_cents=50,
            agent_id="agent1"
        )
        ledger.record_intent(intent1)
        
        # Add partial fill (5 contracts)
        fill1 = KalshiFill(
            fill_id="fill1",
            market_ticker="KXBTC-15M-ABOVE-75000",
            side="yes",
            action="buy",
            count_fp=5,
            yes_price_dollars=0.50,
            fee_cost=0.01,
            proceeds_dollars=-2.51,
            asset="BTC",
            intent_id="intent1",
            created_time=datetime.now(timezone.utc)
        )
        ledger._fills["fill1"] = fill1
        
        stats = ledger.get_fill_rate_stats()
        
        assert stats["BTC"]["partial_fills"] == 1.0
        assert stats["BTC"]["fill_rate"] == 1.0  # Still counts as a fill
    
    def test_fill_rate_time_filter(self, ledger):
        """Test fill rate with time filter."""
        now = datetime.now(timezone.utc)
        old_time = now - timedelta(hours=2)
        
        # Add old intent and fill
        old_intent = OrderIntent(
            intent_id="old_intent",
            ticker="KXBTC-15M-ABOVE-75000",
            side="yes",
            action="buy",
            count=10,
            price_cents=50,
            agent_id="agent1"
        )
        old_intent.created_at = old_time
        ledger.record_intent(old_intent)
        
        old_fill = KalshiFill(
            fill_id="old_fill",
            market_ticker="KXBTC-15M-ABOVE-75000",
            side="yes",
            action="buy",
            count_fp=10,
            yes_price_dollars=0.50,
            fee_cost=0.01,
            proceeds_dollars=-5.01,
            asset="BTC",
            intent_id="old_intent",
            created_time=old_time
        )
        ledger._fills["old_fill"] = old_fill
        
        # Add new intent and fill
        new_intent = OrderIntent(
            intent_id="new_intent",
            ticker="KXBTC-15M-ABOVE-75000",
            side="yes",
            action="buy",
            count=10,
            price_cents=50,
            agent_id="agent1"
        )
        ledger.record_intent(new_intent)
        
        new_fill = KalshiFill(
            fill_id="new_fill",
            market_ticker="KXBTC-15M-ABOVE-75000",
            side="yes",
            action="buy",
            count_fp=10,
            yes_price_dollars=0.50,
            fee_cost=0.01,
            proceeds_dollars=-5.01,
            asset="BTC",
            intent_id="new_intent",
            created_time=now
        )
        ledger._fills["new_fill"] = new_fill
        
        # Stats without time filter
        stats_all = ledger.get_fill_rate_stats()
        assert stats_all["BTC"]["intents"] == 2.0
        assert stats_all["BTC"]["fills"] == 2.0
        
        # Stats with time filter (last hour)
        stats_recent = ledger.get_fill_rate_stats(since=now - timedelta(hours=1))
        assert stats_recent["BTC"]["intents"] == 1.0
        assert stats_recent["BTC"]["fills"] == 1.0
    
    def test_fill_rate_asset_filter(self, ledger):
        """Test fill rate with asset filter."""
        # Add BTC data
        btc_intent = OrderIntent(
            intent_id="btc_intent",
            ticker="KXBTC-15M-ABOVE-75000",
            side="yes",
            action="buy",
            count=10,
            price_cents=50,
            agent_id="agent1"
        )
        ledger.record_intent(btc_intent)
        
        fill_btc = KalshiFill(
            fill_id="fill_btc",
            market_ticker="KXBTC-15M-ABOVE-75000",
            side="yes",
            action="buy",
            count_fp=10,
            yes_price_dollars=0.50,
            fee_cost=0.01,
            proceeds_dollars=-5.01,
            asset="BTC",
            intent_id="btc_intent",
            created_time=datetime.now(timezone.utc)
        )
        ledger._fills["fill_btc"] = fill_btc
        
        # Filter by BTC only
        stats_btc = ledger.get_fill_rate_stats(asset="BTC")
        
        assert "BTC" in stats_btc
        assert stats_btc["BTC"]["fill_rate"] == 1.0


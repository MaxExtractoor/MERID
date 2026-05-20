"""Unit tests for spot composite calculation."""
import pytest
from datetime import datetime, timezone
from data.spot_models import Asset, ExchangeName, CompositeHealth, ExchangeTick
from data.spot_composite import SpotComposite, ExchangeTickBuffer


class TestExchangeTickBuffer:
    """Test ExchangeTickBuffer."""
    
    def test_add_tick_and_get_latest(self):
        """Adding ticks and retrieving latest."""
        buffer = ExchangeTickBuffer(exchange=ExchangeName.COINBASE, asset=Asset.BTC)
        tick1 = ExchangeTick(
            exchange=ExchangeName.COINBASE,
            asset=Asset.BTC,
            bid=50000.0,
            ask=50010.0,
            last=50005.0,
            volume_24h=1000000.0,
            ts_exchange=datetime.now(timezone.utc),
        )
        tick2 = ExchangeTick(
            exchange=ExchangeName.COINBASE,
            asset=Asset.BTC,
            bid=50010.0,
            ask=50020.0,
            last=50015.0,
            volume_24h=1100000.0,
            ts_exchange=datetime.now(timezone.utc),
        )
        
        buffer.add_tick(tick1)
        buffer.add_tick(tick2)
        
        latest = buffer.get_latest_tick()
        assert latest == tick2
    
    def test_get_fresh_ticks(self):
        """Filter fresh ticks by age."""
        buffer = ExchangeTickBuffer(exchange=ExchangeName.COINBASE, asset=Asset.BTC)
        
        # Add fresh tick
        fresh_tick = ExchangeTick(
            exchange=ExchangeName.COINBASE,
            asset=Asset.BTC,
            bid=50000.0,
            ask=50010.0,
            last=50005.0,
            volume_24h=1000000.0,
            ts_exchange=datetime.now(timezone.utc),
        )
        buffer.add_tick(fresh_tick)
        
        fresh_ticks = buffer.get_fresh_ticks(max_age_seconds=10.0)
        assert len(fresh_ticks) == 1
        assert fresh_ticks[0] == fresh_tick
    
    def test_get_average_volume(self):
        """Calculate average 24h volume."""
        buffer = ExchangeTickBuffer(exchange=ExchangeName.COINBASE, asset=Asset.BTC)
        
        tick1 = ExchangeTick(
            exchange=ExchangeName.COINBASE,
            asset=Asset.BTC,
            bid=50000.0,
            ask=50010.0,
            last=50005.0,
            volume_24h=1000000.0,
            ts_exchange=datetime.now(timezone.utc),
        )
        tick2 = ExchangeTick(
            exchange=ExchangeName.COINBASE,
            asset=Asset.BTC,
            bid=50010.0,
            ask=50020.0,
            last=50015.0,
            volume_24h=2000000.0,
            ts_exchange=datetime.now(timezone.utc),
        )
        
        buffer.add_tick(tick1)
        buffer.add_tick(tick2)
        
        avg_vol = buffer.get_average_volume()
        assert avg_vol == 1500000.0


class TestSpotComposite:
    """Test SpotComposite aggregation."""
    
    def test_add_single_exchange_healthy(self):
        """Single exchange with healthy tick."""
        composite = SpotComposite()
        
        tick = ExchangeTick(
            exchange=ExchangeName.COINBASE,
            asset=Asset.BTC,
            bid=50000.0,
            ask=50010.0,
            last=50005.0,
            volume_24h=1000000.0,
            ts_exchange=datetime.now(timezone.utc),
        )
        composite.add_tick(tick)
        
        spot = composite.get_composite_spot(Asset.BTC)
        assert spot.asset == Asset.BTC
        assert spot.price is not None
        assert spot.health == CompositeHealth.DEGRADED  # Only 1 exchange
        assert len(spot.contributing_exchanges) == 1
    
    def test_add_multiple_exchanges_healthy(self):
        """Multiple exchanges with healthy ticks."""
        composite = SpotComposite()
        
        # Add Coinbase tick
        tick1 = ExchangeTick(
            exchange=ExchangeName.COINBASE,
            asset=Asset.BTC,
            bid=50000.0,
            ask=50010.0,
            last=50005.0,
            volume_24h=1000000.0,
            ts_exchange=datetime.now(timezone.utc),
        )
        composite.add_tick(tick1)
        
        # Add Kraken tick
        tick2 = ExchangeTick(
            exchange=ExchangeName.KRAKEN,
            asset=Asset.BTC,
            bid=49995.0,
            ask=50005.0,
            last=50000.0,
            volume_24h=800000.0,
            ts_exchange=datetime.now(timezone.utc),
        )
        composite.add_tick(tick2)
        
        spot = composite.get_composite_spot(Asset.BTC)
        assert spot.asset == Asset.BTC
        assert spot.price is not None
        assert spot.health == CompositeHealth.HEALTHY
        assert len(spot.contributing_exchanges) == 2
        assert "coinbase" in spot.contributing_exchanges
        assert "kraken" in spot.contributing_exchanges
    
    def test_vwap_calculation(self):
        """VWAP calculation with volume weighting."""
        composite = SpotComposite()
        
        # High volume exchange
        tick1 = ExchangeTick(
            exchange=ExchangeName.BINANCE,
            asset=Asset.BTC,
            bid=50000.0,
            ask=50010.0,
            last=50005.0,
            volume_24h=10000000.0,  # 10x volume
            ts_exchange=datetime.now(timezone.utc),
        )
        composite.add_tick(tick1)
        
        # Low volume exchange
        tick2 = ExchangeTick(
            exchange=ExchangeName.KRAKEN,
            asset=Asset.BTC,
            bid=49000.0,
            ask=49100.0,
            last=49050.0,
            volume_24h=1000000.0,
            ts_exchange=datetime.now(timezone.utc),
        )
        composite.add_tick(tick2)
        
        spot = composite.get_composite_spot(Asset.BTC)
        assert spot.method == "vwap"
        # VWAP should be closer to high-volume exchange price
        assert spot.price > 49500.0  # Should be weighted toward 50005
    
    def test_median_calculation(self):
        """Median calculation when VWAP fails."""
        composite = SpotComposite()
        
        # Add ticks without volume data (VWAP will fail, fall back to median)
        tick1 = ExchangeTick(
            exchange=ExchangeName.COINBASE,
            asset=Asset.BTC,
            bid=50000.0,
            ask=50010.0,
            last=50005.0,
            volume_24h=None,  # No volume
            ts_exchange=datetime.now(timezone.utc),
        )
        composite.add_tick(tick1)
        
        tick2 = ExchangeTick(
            exchange=ExchangeName.KRAKEN,
            asset=Asset.BTC,
            bid=49995.0,
            ask=50005.0,
            last=50000.0,
            volume_24h=None,
            ts_exchange=datetime.now(timezone.utc),
        )
        composite.add_tick(tick2)
        
        spot = composite.get_composite_spot(Asset.BTC)
        assert spot.method == "median"
        # Median of [50005, 50000] should be ~50002.5
        assert 50000.0 <= spot.price <= 50005.0
    
    def test_insufficient_data(self):
        """No fresh ticks available."""
        composite = SpotComposite()
        
        spot = composite.get_composite_spot(Asset.BTC)
        assert spot.asset == Asset.BTC
        assert spot.price is None
        assert spot.health == CompositeHealth.INSUFFICIENT_DATA
        assert len(spot.contributing_exchanges) == 0
    
    def test_get_all_composite_spots(self):
        """Get composite spots for all assets."""
        composite = SpotComposite()
        
        # Add BTC tick
        tick_btc = ExchangeTick(
            exchange=ExchangeName.COINBASE,
            asset=Asset.BTC,
            bid=50000.0,
            ask=50010.0,
            last=50005.0,
            volume_24h=1000000.0,
            ts_exchange=datetime.now(timezone.utc),
        )
        composite.add_tick(tick_btc)
        
        # Add ETH tick
        tick_eth = ExchangeTick(
            exchange=ExchangeName.COINBASE,
            asset=Asset.ETH,
            bid=3000.0,
            ask=3010.0,
            last=3005.0,
            volume_24h=500000.0,
            ts_exchange=datetime.now(timezone.utc),
        )
        composite.add_tick(tick_eth)
        
        all_spots = composite.get_all_composite_spots()
        assert Asset.BTC.value in all_spots
        assert Asset.ETH.value in all_spots
        assert len(all_spots) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""Unit tests for spot price models."""
import pytest
from datetime import datetime, timezone
from data.spot_models import Asset, CompositeHealth, AlignmentHealth, ExchangeName, ExchangeTick, CompositeSpot, CfbRtiObservation, SpotAlignment


class TestExchangeTick:
    """Test ExchangeTick model."""
    
    def test_mid_price_with_bid_ask(self):
        """Mid price calculation when bid and ask available."""
        tick = ExchangeTick(
            exchange=ExchangeName.COINBASE,
            asset=Asset.BTC,
            bid=50000.0,
            ask=50010.0,
            last=50005.0,
            volume_24h=1000000.0,
            ts_exchange=datetime.now(timezone.utc),
        )
        assert tick.mid == 50005.0
    
    def test_mid_price_fallback_to_last(self):
        """Mid price falls back to last when bid/ask missing."""
        tick = ExchangeTick(
            exchange=ExchangeName.KRAKEN,
            asset=Asset.BTC,
            bid=None,
            ask=None,
            last=50005.0,
            volume_24h=1000000.0,
            ts_exchange=datetime.now(timezone.utc),
        )
        assert tick.mid == 50005.0
    
    def test_mid_price_none_when_all_missing(self):
        """Mid price is None when all fields missing."""
        tick = ExchangeTick(
            exchange=ExchangeName.KRAKEN,
            asset=Asset.BTC,
            bid=None,
            ask=None,
            last=None,
            volume_24h=1000000.0,
            ts_exchange=datetime.now(timezone.utc),
        )
        assert tick.mid is None
    
    def test_is_fresh_true(self):
        """Tick is fresh when within max age."""
        tick = ExchangeTick(
            exchange=ExchangeName.COINBASE,
            asset=Asset.BTC,
            bid=50000.0,
            ask=50010.0,
            last=50005.0,
            volume_24h=1000000.0,
            ts_exchange=datetime.now(timezone.utc),
        )
        assert tick.is_fresh(max_age_seconds=10.0) is True
    
    def test_is_fresh_false(self):
        """Tick is not fresh when older than max age."""
        old_ts = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        tick = ExchangeTick(
            exchange=ExchangeName.COINBASE,
            asset=Asset.BTC,
            bid=50000.0,
            ask=50010.0,
            last=50005.0,
            volume_24h=1000000.0,
            ts_exchange=old_ts,
            ts_received=old_ts,
        )
        assert tick.is_fresh(max_age_seconds=1.0) is False


class TestCompositeSpot:
    """Test CompositeSpot model."""
    
    def test_is_healthy_true(self):
        """Composite is healthy when price exists and health is HEALTHY."""
        composite = CompositeSpot(
            asset=Asset.BTC,
            price=50000.0,
            method="vwap",
            contributing_exchanges=["coinbase", "kraken"],
            health=CompositeHealth.HEALTHY,
        )
        assert composite.is_healthy is True
    
    def test_is_healthy_false_no_price(self):
        """Composite is not healthy when price is None."""
        composite = CompositeSpot(
            asset=Asset.BTC,
            price=None,
            method="vwap",
            contributing_exchanges=["coinbase"],
            health=CompositeHealth.DEGRADED,
        )
        assert composite.is_healthy is False
    
    def test_is_healthy_false_degraded(self):
        """Composite is not healthy when health is DEGRADED."""
        composite = CompositeSpot(
            asset=Asset.BTC,
            price=50000.0,
            method="median",
            contributing_exchanges=["coinbase"],
            health=CompositeHealth.DEGRADED,
        )
        assert composite.is_healthy is False


class TestCfbRtiObservation:
    """Test CfbRtiObservation model."""
    
    def test_is_fresh_true(self):
        """RTI is fresh when within max age."""
        rti = CfbRtiObservation(
            asset=Asset.BTC,
            price=50000.0,
            ts=datetime.now(timezone.utc),
        )
        assert rti.is_fresh(max_age_seconds=5.0) is True
    
    def test_is_fresh_false(self):
        """RTI is not fresh when older than max age."""
        old_ts = datetime.now(timezone.utc).replace(second=0, microsecond=0)
        rti = CfbRtiObservation(
            asset=Asset.BTC,
            price=50000.0,
            ts=old_ts,
            ts_received=old_ts,
        )
        assert rti.is_fresh(max_age_seconds=1.0) is False


class TestSpotAlignment:
    """Test SpotAlignment model."""
    
    def test_from_composite_and_rti_aligned(self):
        """Alignment is ALIGNED when basis within threshold."""
        composite = CompositeSpot(
            asset=Asset.BTC,
            price=50000.0,
            method="vwap",
            health=CompositeHealth.HEALTHY,
        )
        rti = CfbRtiObservation(
            asset=Asset.BTC,
            price=50002.5,  # 2.5 USD diff = 0.5 bps
            ts=datetime.now(timezone.utc),
        )
        alignment = SpotAlignment.from_composite_and_rti(
            asset=Asset.BTC,
            composite=composite,
            rti=rti,
            threshold1_bps=5.0,
            threshold2_bps=20.0,
        )
        assert alignment.health == AlignmentHealth.ALIGNED
        assert alignment.basis_abs == -2.5
        assert alignment.basis_bps == pytest.approx(-0.5, rel=0.1)
    
    def test_from_composite_and_rti_mild_drift(self):
        """Alignment is MILD_DRIFT when basis exceeds threshold1 but not threshold2."""
        composite = CompositeSpot(
            asset=Asset.BTC,
            price=50000.0,
            method="vwap",
            health=CompositeHealth.HEALTHY,
        )
        rti = CfbRtiObservation(
            asset=Asset.BTC,
            price=49925.0,  # 75 USD diff = 15 bps (between 5 and 20 bps)
            ts=datetime.now(timezone.utc),
        )
        alignment = SpotAlignment.from_composite_and_rti(
            asset=Asset.BTC,
            composite=composite,
            rti=rti,
            threshold1_bps=5.0,
            threshold2_bps=20.0,
        )
        assert alignment.health == AlignmentHealth.MILD_DRIFT
        assert alignment.basis_abs == 75.0
        assert alignment.basis_bps == pytest.approx(15.0, rel=0.1)
    
    def test_from_composite_and_rti_severe_drift(self):
        """Alignment is SEVERE_DRIFT when basis exceeds threshold2."""
        composite = CompositeSpot(
            asset=Asset.BTC,
            price=50000.0,
            method="vwap",
            health=CompositeHealth.HEALTHY,
        )
        rti = CfbRtiObservation(
            asset=Asset.BTC,
            price=49000.0,  # 1000 USD diff = 200 bps
            ts=datetime.now(timezone.utc),
        )
        alignment = SpotAlignment.from_composite_and_rti(
            asset=Asset.BTC,
            composite=composite,
            rti=rti,
            threshold1_bps=5.0,
            threshold2_bps=20.0,
        )
        assert alignment.health == AlignmentHealth.SEVERE_DRIFT
        assert alignment.basis_abs == 1000.0
        assert alignment.basis_bps == pytest.approx(200.0, rel=0.1)
    
    def test_from_composite_no_spot(self):
        """Alignment is NO_SPOT when composite price is None."""
        composite = CompositeSpot(
            asset=Asset.BTC,
            price=None,
            method="vwap",
            health=CompositeHealth.INSUFFICIENT_DATA,
        )
        rti = CfbRtiObservation(
            asset=Asset.BTC,
            price=50000.0,
            ts=datetime.now(timezone.utc),
        )
        alignment = SpotAlignment.from_composite_and_rti(
            asset=Asset.BTC,
            composite=composite,
            rti=rti,
        )
        assert alignment.health == AlignmentHealth.NO_SPOT
        assert alignment.merid_spot is None
    
    def test_from_composite_no_rti(self):
        """Alignment is NO_RTI when RTI is None."""
        composite = CompositeSpot(
            asset=Asset.BTC,
            price=50000.0,
            method="vwap",
            health=CompositeHealth.HEALTHY,
        )
        alignment = SpotAlignment.from_composite_and_rti(
            asset=Asset.BTC,
            composite=composite,
            rti=None,
        )
        assert alignment.health == AlignmentHealth.NO_RTI
        assert alignment.cfb_rti is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

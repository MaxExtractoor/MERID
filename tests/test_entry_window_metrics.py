"""Tests for entry window metrics tracking.

Tests that metrics are properly tracked for verifying edge vs config drift.
"""

import pytest

from merid.prediction.dynamic_entry_window import (
    resolve_entry_window,
    reset_entry_window_metrics,
    get_entry_window_metrics,
    log_entry_window_metrics_summary,
    get_scope_metrics,
    check_scope_violation_threshold,
    log_scope_metrics_summary,
    check_liquidity_guard,
    EntryWindowDecision,
)


class TestEntryWindowMetrics:
    """Test entry window metrics tracking functionality."""

    def setup_method(self):
        """Reset metrics before each test."""
        reset_entry_window_metrics()

    def test_metrics_track_allowed_base_window(self):
        """Test that allowed base window decisions are tracked."""
        # BTC with 10m to expiry should be in base window
        resolution = resolve_entry_window(
            asset="BTC",
            minutes_to_expiry=10,
            edge_pct=15.0,
        )
        
        assert resolution.allowed is True
        assert resolution.reason == EntryWindowDecision.ALLOWED_BASE
        
        metrics = get_entry_window_metrics()
        assert "BTC" in metrics
        # Bucket depends on canonical config availability
        btc_buckets = list(metrics["BTC"].keys())
        assert len(btc_buckets) == 1
        bucket = btc_buckets[0]
        assert metrics["BTC"][bucket]["total"] == 1
        assert metrics["BTC"][bucket]["allowed"] == 1

    def test_metrics_track_terminal_edge_too_low(self):
        """Test that terminal edge too low decisions are tracked."""
        # BTC with 1m to expiry and low edge should be rejected
        resolution = resolve_entry_window(
            asset="BTC",
            minutes_to_expiry=1,
            edge_pct=5.0,  # Below threshold
        )
        
        # This may fail if terminal phase is disabled in config
        if resolution.reason == EntryWindowDecision.TERMINAL_DISABLED:
            # Skip this test if terminal is disabled
            pytest.skip("Terminal phase disabled in config")
        
        assert resolution.allowed is False
        assert resolution.reason == EntryWindowDecision.TERMINAL_EDGE_TOO_LOW
        
        metrics = get_entry_window_metrics()
        assert "BTC" in metrics
        # Bucket depends on canonical config availability
        btc_buckets = list(metrics["BTC"].keys())
        bucket = btc_buckets[0]
        assert metrics["BTC"][bucket]["total"] == 1
        assert metrics["BTC"][bucket]["allowed"] == 0
        assert "terminal_edge_too_low" in metrics["BTC"][bucket]

    def test_metrics_track_outside_window(self):
        """Test that outside window decisions are tracked."""
        # BTC with 20m to expiry should be outside window
        resolution = resolve_entry_window(
            asset="BTC",
            minutes_to_expiry=20,
            edge_pct=15.0,
        )
        
        assert resolution.allowed is False
        assert resolution.reason == EntryWindowDecision.OUTSIDE_WINDOW
        
        metrics = get_entry_window_metrics()
        assert "BTC" in metrics
        # Bucket depends on canonical config availability
        btc_buckets = list(metrics["BTC"].keys())
        bucket = btc_buckets[0]
        assert metrics["BTC"][bucket]["total"] == 1
        assert metrics["BTC"][bucket]["allowed"] == 0
        assert "outside_window" in metrics["BTC"][bucket]

    def test_metrics_track_multiple_assets(self):
        """Test that metrics are tracked separately for each asset."""
        # Test BTC
        resolve_entry_window(asset="BTC", minutes_to_expiry=10, edge_pct=15.0)
        # Test ETH
        resolve_entry_window(asset="ETH", minutes_to_expiry=10, edge_pct=15.0)
        # Test SOL
        resolve_entry_window(asset="SOL", minutes_to_expiry=5, edge_pct=15.0)
        
        metrics = get_entry_window_metrics()
        
        # All three assets should have metrics
        assert "BTC" in metrics
        assert "ETH" in metrics
        assert "SOL" in metrics
        
        # Each asset should have its own counts
        assert sum(metrics["BTC"][bucket]["total"] for bucket in metrics["BTC"]) == 1
        assert sum(metrics["ETH"][bucket]["total"] for bucket in metrics["ETH"]) == 1
        assert sum(metrics["SOL"][bucket]["total"] for bucket in metrics["SOL"]) == 1

    def test_metrics_track_rejection_reasons(self):
        """Test that different rejection reasons are tracked separately."""
        # Outside window
        resolve_entry_window(asset="BTC", minutes_to_expiry=20, edge_pct=15.0)
        # Terminal edge too low (may be disabled)
        resolve_entry_window(asset="BTC", minutes_to_expiry=1, edge_pct=5.0)
        
        metrics = get_entry_window_metrics()
        btc_metrics = metrics["BTC"]
        
        # Count total rejections across all buckets
        total_rejections = 0
        for bucket, counts in btc_metrics.items():
            total_rejections += counts.get("total", 0) - counts.get("allowed", 0)
        
        # At least 2 rejections (outside window + terminal)
        assert total_rejections >= 2

    def test_reset_metrics(self):
        """Test that metrics can be reset."""
        # Add some metrics
        resolve_entry_window(asset="BTC", minutes_to_expiry=10, edge_pct=15.0)
        resolve_entry_window(asset="ETH", minutes_to_expiry=10, edge_pct=15.0)
        
        metrics_before = get_entry_window_metrics()
        assert len(metrics_before) == 2
        
        # Reset
        reset_entry_window_metrics()
        
        metrics_after = get_entry_window_metrics()
        assert len(metrics_after) == 0

    def test_metrics_thread_safety(self):
        """Test that metrics tracking is thread-safe (basic smoke test)."""
        import threading
        
        def add_metrics(asset):
            for _ in range(10):
                resolve_entry_window(asset=asset, minutes_to_expiry=10, edge_pct=15.0)
        
        threads = [
            threading.Thread(target=add_metrics, args=("BTC",)),
            threading.Thread(target=add_metrics, args=("ETH",)),
            threading.Thread(target=add_metrics, args=("SOL",)),
        ]
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        metrics = get_entry_window_metrics()
        
        # Each asset should have 10 evaluations
        assert sum(metrics["BTC"][bucket]["total"] for bucket in metrics["BTC"]) == 10
        assert sum(metrics["ETH"][bucket]["total"] for bucket in metrics["ETH"]) == 10
        assert sum(metrics["SOL"][bucket]["total"] for bucket in metrics["SOL"]) == 10

    def test_migration_guard_canonical_asset(self):
        """Test that migration guard allows canonical assets."""
        from merid.prediction.dynamic_entry_window import assert_15m_canonical_asset
        
        # Should not raise for canonical assets
        assert_15m_canonical_asset("BTC")
        assert_15m_canonical_asset("ETH")
        assert_15m_canonical_asset("SOL")
        assert_15m_canonical_asset("XRP")
        assert_15m_canonical_asset("DOGE")

    def test_migration_guard_non_canonical_asset(self):
        """Test that migration guard rejects non-canonical assets."""
        from merid.prediction.dynamic_entry_window import assert_15m_canonical_asset
        
        # Should raise for non-canonical assets
        with pytest.raises(AssertionError, match="not in canonical 15m config"):
            assert_15m_canonical_asset("PEPE")
        
        with pytest.raises(AssertionError, match="not in canonical 15m config"):
            assert_15m_canonical_asset("WIF")

    def test_migration_guard_wrong_timeframe(self):
        """Test that migration guard rejects wrong timeframe."""
        from merid.prediction.dynamic_entry_window import assert_15m_canonical_asset
        
        # Should raise for wrong timeframe
        with pytest.raises(AssertionError, match="not canonical 15m timeframe"):
            assert_15m_canonical_asset("BTC", timeframe="1h")
        
        with pytest.raises(AssertionError, match="not canonical 15m timeframe"):
            assert_15m_canonical_asset("BTC", timeframe="5m")


class TestScopeMetrics:
    """Test scope violation metrics tracking."""
    
    def setup_method(self):
        """Reset metrics before each test."""
        reset_entry_window_metrics()
    
    def test_get_scope_metrics_empty(self):
        """Test that get_scope_metrics returns empty structure when no data."""
        metrics = get_scope_metrics()
        assert metrics["scope_violations"] == {}
        assert metrics["books_seen"] == {}
        assert metrics["violation_ratios"] == {}
    
    def test_scope_metrics_tracking(self):
        """Test that scope metrics are tracked correctly."""
        from merid.prediction.dynamic_entry_window import _increment_scope_metric
        
        # Add some scope metrics
        _increment_scope_metric("BTC", is_violation=False)
        _increment_scope_metric("BTC", is_violation=False)
        _increment_scope_metric("BTC", is_violation=True)  # 1 violation
        _increment_scope_metric("ETH", is_violation=False)
        _increment_scope_metric("ETH", is_violation=True)  # 1 violation
        
        metrics = get_scope_metrics()
        
        assert metrics["scope_violations"]["BTC"] == 1
        assert metrics["books_seen"]["BTC"] == 3
        assert metrics["violation_ratios"]["BTC"] == 1/3
        
        assert metrics["scope_violations"]["ETH"] == 1
        assert metrics["books_seen"]["ETH"] == 2
        assert metrics["violation_ratios"]["ETH"] == 0.5
    
    def test_check_scope_violation_threshold(self):
        """Test that threshold checking works correctly."""
        from merid.prediction.dynamic_entry_window import _increment_scope_metric
        
        # Add metrics with high violation rate for DOGE
        for _ in range(10):
            _increment_scope_metric("DOGE", is_violation=True)  # 100% violation rate
        
        # Add metrics with low violation rate for BTC
        for _ in range(100):
            _increment_scope_metric("BTC", is_violation=False)
        for _ in range(2):
            _increment_scope_metric("BTC", is_violation=True)  # 2% violation rate
        
        # Check with 5% threshold
        violations = check_scope_violation_threshold(threshold_pct=0.05)
        
        assert "DOGE" in violations  # 100% > 5%
        assert "BTC" not in violations  # 2% < 5%


class TestLiquidityGuard:
    """Test liquidity/spread guard functionality."""
    
    def test_liquidity_guard_pass(self):
        """Test that liquidity guard passes when conditions are met."""
        passes, reason = check_liquidity_guard(
            asset="BTC",
            bucket="10+",
            bid=0.48,
            ask=0.50,
            bid_size=50,
            ask_size=50,
        )
        
        assert passes is True
        assert reason is None
    
    def test_liquidity_guard_spread_too_wide(self):
        """Test that liquidity guard rejects when spread is too wide."""
        passes, reason = check_liquidity_guard(
            asset="BTC",
            bucket="10+",
            bid=0.45,
            ask=0.55,  # 10% spread, exceeds 3% threshold
            bid_size=50,
            ask_size=50,
        )
        
        assert passes is False
        assert reason == EntryWindowDecision.SPREAD_TOO_WIDE.value
    
    def test_liquidity_guard_depth_too_low(self):
        """Test that liquidity guard rejects when depth is too low."""
        passes, reason = check_liquidity_guard(
            asset="BTC",
            bucket="10+",
            bid=0.48,
            ask=0.50,
            bid_size=5,  # Below 10 threshold
            ask_size=50,
        )
        
        assert passes is False
        assert reason == EntryWindowDecision.DEPTH_TOO_LOW.value
    
    def test_liquidity_guard_no_price_data(self):
        """Test that liquidity guard passes when price data is missing."""
        passes, reason = check_liquidity_guard(
            asset="BTC",
            bucket="10+",
            bid=None,
            ask=None,
            bid_size=None,
            ask_size=None,
        )
        
        # Should pass when no data available (fail-open)
        assert passes is True
        assert reason is None
    
    def test_liquidity_guard_different_assets(self):
        """Test that different assets have different thresholds."""
        # DOGE has higher spread tolerance (6% for 10+ bucket)
        passes_doge, _ = check_liquidity_guard(
            asset="DOGE",
            bucket="10+",
            bid=0.47,
            ask=0.52,  # 5% spread, within 6% threshold
            bid_size=50,
            ask_size=50,
        )
        
        # BTC has lower spread tolerance (3% for 10+ bucket)
        passes_btc, _ = check_liquidity_guard(
            asset="BTC",
            bucket="10+",
            bid=0.47,
            ask=0.52,  # 5% spread, exceeds 3% threshold
            bid_size=50,
            ask_size=50,
        )
        
        # DOGE should pass (5% < 6% threshold), BTC should fail (5% > 3% threshold)
        assert passes_doge is True
        assert passes_btc is False

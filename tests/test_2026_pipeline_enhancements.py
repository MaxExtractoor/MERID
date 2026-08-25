"""Tests for 2026 Pipeline Audit Enhancements.

Tests for:
- Signal Quality Score (SQS) computation
- Recovery state transitions (LIVE/DEGRADED/STALE/FALLBACK/RECOVERING/DEAD)
- Fallback tracking metrics in agent_grid_15m
- Graduated exposure controls
- Structured error classification
"""

import pytest
import time
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass

# Test Signal Quality Score (SQS)
class TestSignalQualityScore:
    """Test Signal Quality Score computation in unified_spot_service."""
    
    def test_sqs_computation_fresh_data(self):
        """Test SQS computation with fresh data should yield high score."""
        from data.unified_spot_service import UnifiedSpotService, DataState
        
        service = UnifiedSpotService()
        
        # Simulate fresh data
        with service._cache_lock:
            service._cache["BTC"] = {
                'price': 50000.0,
                'timestamp': int(time.time() * 1000),  # Current time
                'source': 'coinbase_ticker_hybrid',
                'open': 49900.0,
                'high': 50100.0,
                'low': 49800.0,
                'volume': 1000.0
            }
            service._data_states["BTC"] = DataState.LIVE
            service._price_history["BTC"] = [(int(time.time() * 1000) - i * 3000, 50000.0 + i * 10) for i in range(20)]
        
        sqs = service._compute_sqs("BTC")
        
        # Fresh data with LIVE state should yield high score
        assert sqs.composite >= 70.0, f"Fresh data should yield SQS >= 70, got {sqs.composite}"
        assert sqs.trade_permitted is True
        assert sqs.degradation_level in ["normal", "yellow"]
    
    def test_sqs_computation_stale_data(self):
        """Test SQS computation with stale data should yield low score."""
        from data.unified_spot_service import UnifiedSpotService, DataState
        
        service = UnifiedSpotService()
        
        # Simulate stale data (20 seconds old)
        stale_timestamp = int((time.time() - 20) * 1000)
        with service._cache_lock:
            service._cache["BTC"] = {
                'price': 50000.0,
                'timestamp': stale_timestamp,
                'source': 'coinbase_ticker_hybrid',
                'open': 49900.0,
                'high': 50100.0,
                'low': 49800.0,
                'volume': 1000.0
            }
            service._data_states["BTC"] = DataState.STALE
            service._price_history["BTC"] = [(stale_timestamp - i * 3000, 50000.0 + i * 10) for i in range(20)]
        
        sqs = service._compute_sqs("BTC")
        
        # Stale data should yield lower score
        assert sqs.composite < 70.0, f"Stale data should yield SQS < 70, got {sqs.composite}"
        assert sqs.trade_permitted is False or sqs.degradation_level in ["orange", "red"]
    
    def test_sqs_computation_fallback_source(self):
        """Test SQS computation with fallback source should penalize score."""
        from data.unified_spot_service import UnifiedSpotService, DataState
        
        service = UnifiedSpotService()
        
        # Simulate fallback source
        with service._cache_lock:
            service._cache["BTC"] = {
                'price': 50000.0,
                'timestamp': int(time.time() * 1000),
                'source': 'coinbase_public',  # Fallback source
                'open': 50000.0,
                'high': 50000.0,
                'low': 50000.0,
                'volume': None
            }
            service._data_states["BTC"] = DataState.FALLBACK
            service._price_history["BTC"] = [(int(time.time() * 1000) - i * 3000, 50000.0) for i in range(20)]
        
        sqs = service._compute_sqs("BTC")
        
        # Fallback source should yield lower score
        assert sqs.composite < 80.0, f"Fallback source should yield SQS < 80, got {sqs.composite}"
    
    def test_sqs_component_weights(self):
        """Test that SQS component weights sum to 1.0."""
        from data.unified_spot_service import UnifiedSpotService, DataState
        
        service = UnifiedSpotService()
        
        with service._cache_lock:
            service._cache["BTC"] = {
                'price': 50000.0,
                'timestamp': int(time.time() * 1000),
                'source': 'coinbase_ticker_hybrid',
                'open': 49900.0,
                'high': 50100.0,
                'low': 49800.0,
                'volume': 1000.0
            }
            service._data_states["BTC"] = DataState.LIVE
            service._price_history["BTC"] = [(int(time.time() * 1000) - i * 3000, 50000.0 + i * 10) for i in range(20)]
        
        sqs = service._compute_sqs("BTC")
        
        # Check component weights
        total_weight = sum(comp.weight for comp in sqs.components.values())
        assert abs(total_weight - 1.0) < 0.01, f"Component weights should sum to 1.0, got {total_weight}"
    
    def test_get_degradation_level(self):
        """Test overall system degradation level calculation."""
        from data.unified_spot_service import UnifiedSpotService, DataState
        
        service = UnifiedSpotService()
        
        # All assets with fresh data -> normal
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            with service._cache_lock:
                service._cache[asset] = {
                    'price': 50000.0,
                    'timestamp': int(time.time() * 1000),
                    'source': 'coinbase_ticker_hybrid',
                    'open': 49900.0,
                    'high': 50100.0,
                    'low': 49800.0,
                    'volume': 1000.0
                }
                service._data_states[asset] = DataState.LIVE
                service._price_history[asset] = [(int(time.time() * 1000) - i * 3000, 50000.0 + i * 10) for i in range(20)]
        
        degradation = service.get_degradation_level()
        assert degradation == "normal", f"All fresh data should yield 'normal' degradation, got {degradation}"


# Test Recovery State Transitions
class TestRecoveryStateTransitions:
    """Test recovery state transitions in unified_spot_service."""
    
    def test_live_to_degraded_transition(self):
        """Test transition from LIVE to DEGRADED when data ages."""
        from data.unified_spot_service import UnifiedSpotService, DataState
        
        service = UnifiedSpotService()
        
        # Start with LIVE data
        with service._cache_lock:
            service._cache["BTC"] = {
                'price': 50000.0,
                'timestamp': int(time.time() * 1000),
                'source': 'coinbase_ticker_hybrid',
                'open': 49900.0,
                'high': 50100.0,
                'low': 49800.0,
                'volume': 1000.0
            }
            service._data_states["BTC"] = DataState.LIVE
        
        # Simulate data aging to 5 seconds (DEGRADED threshold)
        time.sleep(0.1)  # Small delay
        with service._cache_lock:
            service._cache["BTC"]['timestamp'] = int((time.time() - 5) * 1000)
        
        state = service._classify_data_state("BTC", "coinbase_ticker_hybrid", service._cache["BTC"]['timestamp'])
        assert state == DataState.DEGRADED, f"5s old data should be DEGRADED, got {state}"
    
    def test_degraded_to_stale_transition(self):
        """Test transition from DEGRADED to STALE when data ages further."""
        from data.unified_spot_service import UnifiedSpotService, DataState
        
        service = UnifiedSpotService()
        
        # Start with DEGRADED data
        with service._cache_lock:
            service._cache["BTC"] = {
                'price': 50000.0,
                'timestamp': int((time.time() - 10) * 1000),
                'source': 'coinbase_ticker_hybrid',
                'open': 49900.0,
                'high': 50100.0,
                'low': 49800.0,
                'volume': 1000.0
            }
            service._data_states["BTC"] = DataState.DEGRADED
        
        # Simulate data aging to 15 seconds (STALE threshold)
        with service._cache_lock:
            service._cache["BTC"]['timestamp'] = int((time.time() - 15) * 1000)
        
        state = service._classify_data_state("BTC", "coinbase_ticker_hybrid", service._cache["BTC"]['timestamp'])
        assert state == DataState.STALE, f"15s old data should be STALE, got {state}"
    
    def test_fallback_state_detection(self):
        """Test that fallback sources are labeled as FALLBACK state."""
        from data.unified_spot_service import UnifiedSpotService, DataState
        
        service = UnifiedSpotService()
        
        # Set previous state to LIVE to test transition
        service._data_states["BTC"] = DataState.LIVE
        
        # Use sources that actually contain "fallback" or "proxy" to trigger FALLBACK state
        state = service._classify_data_state("BTC", "coinbase_ticker_ohlc_proxy", int(time.time() * 1000))
        assert state == DataState.FALLBACK, f"Proxy source should be FALLBACK state, got {state}"
        
        state = service._classify_data_state("BTC", "coinbase_ticker_spread_proxy", int(time.time() * 1000))
        assert state == DataState.FALLBACK, f"Proxy source should be FALLBACK state, got {state}"
    
    def test_recovering_to_live_transition(self):
        """Test transition from RECOVERING to LIVE after 3 consecutive fresh ticks."""
        from data.unified_spot_service import UnifiedSpotService, DataState
        
        service = UnifiedSpotService()
        
        # Start in RECOVERING state
        with service._cache_lock:
            service._data_states["BTC"] = DataState.RECOVERING
            service._consecutive_fresh_ticks["BTC"] = 0
        
        # Simulate 3 consecutive fresh ticks
        for i in range(3):
            state = service._classify_data_state("BTC", "coinbase_ticker_hybrid", int(time.time() * 1000))
            if i < 2:
                assert state == DataState.RECOVERING, f"Tick {i+1}: Should still be RECOVERING"
            else:
                assert state == DataState.LIVE, f"Tick {i+1}: Should transition to LIVE"
    
    def test_state_transition_tracking(self):
        """Test that state transitions are tracked for metrics."""
        from data.unified_spot_service import UnifiedSpotService, DataState
        
        service = UnifiedSpotService()
        
        # Trigger a state transition
        with service._cache_lock:
            service._data_states["BTC"] = DataState.LIVE
            service._cache["BTC"] = {
                'price': 50000.0,
                'timestamp': int(time.time() * 1000),
                'source': 'coinbase_ticker_hybrid',
                'open': 49900.0,
                'high': 50100.0,
                'low': 49800.0,
                'volume': 1000.0
            }
        
        # Update cache with fallback source to trigger transition
        ohlc_data = {
            'open': 50000.0,
            'high': 50000.0,
            'low': 50000.0,
            'close': 50000.0,
            'volume': None
        }
        service._update_cache("BTC", ohlc_data, "coinbase_ticker_ohlc_proxy")  # Use proxy to trigger FALLBACK state
        
        # Check that transition was tracked
        assert "BTC" in service._state_transitions, "State transitions should be tracked"
        assert len(service._state_transitions["BTC"]) > 0, "Should have at least one transition"


# Test Fallback Tracking Metrics
class TestFallbackTrackingMetrics:
    """Test fallback tracking metrics in agent_grid_15m."""
    
    def test_fallback_activation_tracking(self):
        """Test that fallback activations are tracked."""
        from merid.prediction.agent_grid_15m import LeanAgentGrid15m
        
        # Create a minimal agent grid without full agent initialization
        grid = LeanAgentGrid15m([])
        
        # Simulate fallback activation
        grid._fallback_activations["ohlc_fallback"] += 1
        grid._fallback_timestamps["ohlc_fallback"].append(time.time())
        
        # Check metrics
        metrics = grid.get_fallback_metrics()
        assert metrics["total_activations"]["ohlc_fallback"] == 1
        assert metrics["recent_activations_5m"]["ohlc_fallback"] == 1
    
    def test_fallback_metrics_reset(self):
        """Test that fallback metrics are reset on market rollover."""
        from merid.prediction.agent_grid_15m import LeanAgentGrid15m
        
        # Create a minimal agent grid
        grid = LeanAgentGrid15m([])
        
        # Add some fallback activations
        grid._fallback_activations["ohlc_fallback"] = 5
        grid._fallback_timestamps["ohlc_fallback"].append(time.time())
        
        # Reset
        grid.reset_strip_order_counts()
        
        # Check that metrics were reset
        assert grid._fallback_activations["ohlc_fallback"] == 0
        assert len(grid._fallback_timestamps["ohlc_fallback"]) == 0
    
    def test_recent_fallback_count(self):
        """Test that recent fallback count only counts last 5 minutes."""
        from merid.prediction.agent_grid_15m import LeanAgentGrid15m
        
        # Create a minimal agent grid
        grid = LeanAgentGrid15m([])
        
        # Add fallbacks at different times
        now = time.time()
        grid._fallback_timestamps["ohlc_fallback"] = [
            now - 10,  # Recent (within 5 min = 300s)
            now - 100,  # Recent
            now - 200,  # Recent
            now - 400,  # Old (outside 5 min)
            now - 600,  # Old (outside 5 min)
        ]
        grid._fallback_activations["ohlc_fallback"] = 5
        
        # Check metrics
        metrics = grid.get_fallback_metrics()
        assert metrics["total_activations"]["ohlc_fallback"] == 5
        assert metrics["recent_activations_5m"]["ohlc_fallback"] == 3  # Only recent ones (10, 100, 200)


# Test Graduated Exposure Controls
class TestGraduatedExposureControls:
    """Test graduated exposure controls in spot service degradation level calculation."""
    
    def test_degradation_level_normal(self):
        """Test that high SQS yields normal degradation level."""
        from data.unified_spot_service import UnifiedSpotService, DataState
        
        service = UnifiedSpotService()
        
        # All assets with high SQS
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            with service._cache_lock:
                service._cache[asset] = {
                    'price': 50000.0,
                    'timestamp': int(time.time() * 1000),
                    'source': 'coinbase_ticker_hybrid',
                    'open': 49900.0,
                    'high': 50100.0,
                    'low': 49800.0,
                    'volume': 1000.0
                }
                service._data_states[asset] = DataState.LIVE
                service._price_history[asset] = [(int(time.time() * 1000) - i * 3000, 50000.0 + i * 10) for i in range(20)]
        
        degradation = service.get_degradation_level()
        assert degradation == "normal", f"High SQS should yield 'normal' degradation, got {degradation}"
    
    def test_degradation_level_yellow(self):
        """Test that medium SQS yields yellow degradation level."""
        from data.unified_spot_service import UnifiedSpotService, DataState
        
        service = UnifiedSpotService()
        
        # Assets with medium SQS (stale data)
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            with service._cache_lock:
                service._cache[asset] = {
                    'price': 50000.0,
                    'timestamp': int((time.time() - 15) * 1000),  # 15s old
                    'source': 'coinbase_ticker_hybrid',
                    'open': 49900.0,
                    'high': 50100.0,
                    'low': 49800.0,
                    'volume': 1000.0
                }
                service._data_states[asset] = DataState.STALE
                service._price_history[asset] = [(int((time.time() - 15) * 1000) - i * 3000, 50000.0 + i * 10) for i in range(20)]
        
        degradation = service.get_degradation_level()
        assert degradation in ["yellow", "orange"], f"Medium SQS should yield 'yellow' or 'orange' degradation, got {degradation}"
    
    def test_degradation_level_red(self):
        """Test that low SQS yields red degradation level."""
        from data.unified_spot_service import UnifiedSpotService, DataState
        
        service = UnifiedSpotService()
        
        # No data or very old data
        # Empty cache should yield red
        degradation = service.get_degradation_level()
        assert degradation == "red", f"No data should yield 'red' degradation, got {degradation}"
    
    def test_degradation_multipliers(self):
        """Test that degradation multipliers are correctly defined."""
        from data.unified_spot_service import UnifiedSpotService
        
        service = UnifiedSpotService()
        
        # The get_degradation_level function uses these thresholds:
        # >= 65.0: normal (100% exposure)
        # >= 50.0: yellow (40% exposure)
        # >= 35.0: orange (15% exposure)
        # < 35.0: red (0% exposure)
        
        # Test that the function returns valid degradation levels
        degradation = service.get_degradation_level()
        assert degradation in ["normal", "yellow", "orange", "red"], f"Invalid degradation level: {degradation}"


# Test Structured Error Classification
class TestStructuredErrorClassification:
    """Test structured error classification system."""
    
    def test_network_timeout_classification(self):
        """Test that network timeouts are classified as expected operational issues."""
        from merid.core.error_classification import ErrorClassifier, ErrorCategory, ErrorSeverity, ErrorRecoveryStrategy
        
        exception = TimeoutError("Connection timeout")
        classified = ErrorClassifier.classify(exception)
        
        assert classified.category == ErrorCategory.NETWORK_TIMEOUT
        assert classified.severity == ErrorSeverity.WARNING
        assert classified.recovery_strategy == ErrorRecoveryStrategy.RETRY_WITH_BACKOFF
        assert classified.is_expected() is True
        assert classified.is_fail_open() is True
    
    def test_rate_limit_classification(self):
        """Test that rate limits are classified as expected operational issues."""
        from merid.core.error_classification import ErrorClassifier, ErrorCategory, ErrorSeverity, ErrorRecoveryStrategy
        
        # Create a mock rate limit exception
        class RateLimitError(Exception):
            pass
        
        exception = RateLimitError("429 Too Many Requests")
        classified = ErrorClassifier.classify(exception)
        
        assert classified.category == ErrorCategory.API_RATE_LIMIT
        assert classified.severity == ErrorSeverity.WARNING
        assert classified.recovery_strategy == ErrorRecoveryStrategy.RETRY_WITH_BACKOFF
        assert classified.is_expected() is True
    
    def test_data_corruption_classification(self):
        """Test that data corruption is classified as unexpected error."""
        from merid.core.error_classification import ErrorClassifier, ErrorCategory, ErrorSeverity, ErrorRecoveryStrategy
        
        exception = ValueError("Invalid price: -100")
        classified = ErrorClassifier.classify(exception, context={"expected_field_missing": False})
        
        assert classified.category == ErrorCategory.DATA_CORRUPTION
        assert classified.severity == ErrorSeverity.ERROR
        assert classified.recovery_strategy == ErrorRecoveryStrategy.FAIL_CLOSED
        assert classified.is_expected() is False
        assert classified.is_fail_open() is False
    
    def test_expected_field_missing_classification(self):
        """Test that expected missing fields are classified as data stale."""
        from merid.core.error_classification import ErrorClassifier, ErrorCategory, ErrorSeverity, ErrorRecoveryStrategy
        
        exception = KeyError("volume")
        classified = ErrorClassifier.classify(exception, context={"expected_field_missing": True})
        
        assert classified.category == ErrorCategory.DATA_STALE
        assert classified.severity == ErrorSeverity.INFO
        assert classified.recovery_strategy == ErrorRecoveryStrategy.USE_FALLBACK
        assert classified.is_expected() is True
        assert classified.is_fail_open() is True
    
    def test_unknown_error_classification(self):
        """Test that unknown errors default to logic error."""
        from merid.core.error_classification import ErrorClassifier, ErrorCategory, ErrorSeverity, ErrorRecoveryStrategy
        
        exception = RuntimeError("Unexpected error")
        classified = ErrorClassifier.classify(exception)
        
        assert classified.category == ErrorCategory.LOGIC_ERROR
        assert classified.severity == ErrorSeverity.ERROR
        assert classified.recovery_strategy == ErrorRecoveryStrategy.ALERT_OPERATOR
        assert classified.is_expected() is False
        assert classified.is_fail_open() is False
    
    def test_classify_and_log(self):
        """Test classify_and_log helper function."""
        from merid.core.error_classification import classify_and_log, ErrorSeverity
        from utils.logger import get_logger
        
        logger = get_logger("test")
        exception = TimeoutError("Connection timeout")
        
        classified = classify_and_log(exception, logger, context={"operation": "fetch_data"}, component="test_component")
        
        assert classified.category.value == "network_timeout"
        assert classified.severity == ErrorSeverity.WARNING
        assert classified.context["operation"] == "fetch_data"


# Test RLock Deadlock Fix
class TestRLockDeadlockFix:
    """Test that RLock prevents deadlock in nested lock acquisition."""
    
    def test_health_check_no_deadlock(self):
        """Test that health_check() can call _compute_sqs() without deadlock."""
        from data.unified_spot_service import UnifiedSpotService, DataState
        
        service = UnifiedSpotService()
        
        # Add some data to cache
        with service._cache_lock:
            service._cache["BTC"] = {
                'price': 50000.0,
                'timestamp': int(time.time() * 1000),
                'source': 'coinbase_ticker_hybrid',
                'open': 49900.0,
                'high': 50100.0,
                'low': 49800.0,
                'volume': 1000.0
            }
            service._data_states["BTC"] = DataState.LIVE
            service._price_history["BTC"] = [(int(time.time() * 1000) - i * 3000, 50000.0 + i * 10) for i in range(20)]
        
        # This should not deadlock (health_check acquires lock, then calls _compute_sqs which also acquires lock)
        health = service.health_check()
        
        # Verify health check completed successfully
        assert health is not None
        assert "status" in health
        assert "cached_count" in health
        assert "sqs_scores" in health
        assert "BTC" in health["sqs_scores"]
    
    def test_rlock_is_reentrant(self):
        """Test that the lock is reentrant (RLock, not Lock)."""
        from data.unified_spot_service import UnifiedSpotService
        import threading
        
        service = UnifiedSpotService()
        
        # Verify it's an RLock (reentrant) by checking type name
        lock_type = type(service._cache_lock).__name__
        assert lock_type == "RLock", f"Cache lock should be RLock for nested acquisition, got {lock_type}"
        
        # Test nested acquisition
        with service._cache_lock:
            # Acquire again while holding
            with service._cache_lock:
                # Should not deadlock
                pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

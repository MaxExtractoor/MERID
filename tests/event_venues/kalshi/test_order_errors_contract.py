"""Integration test for order errors API contract.

This test validates the contract between the KalshiOrderErrorCode taxonomy
and the API endpoint without requiring a full FastAPI test setup.
"""

import pytest
import asyncio
from unittest.mock import patch, MagicMock
from merid.event_venues.kalshi.order_errors import (
    KalshiOrderErrorCode,
    get_error_breakdown,
)
from web.api.kalshi_api import get_order_error_breakdown


class TestOrderErrorsContractIntegration:
    """Integration test for order errors API contract validation."""

    @patch('monitoring.kalshi_metrics.get_kalshi_metrics_collector')
    def test_api_contract_matches_taxonomy(self, mock_collector):
        """API endpoint returns data consistent with KalshiOrderErrorCode taxonomy."""
        # Mock metrics collector to return sample data
        mock_instance = MagicMock()
        mock_collector.return_value = mock_instance
        
        # Create mock metrics with error codes
        mock_metrics = []
        error_codes = [
            "kill_switch",
            "rate_limit", 
            "invalid_price",
            "insufficient_funds",
            "market_closed",
            "daily_loss_limit",
            "unknown"
        ]
        counts = [5, 3, 2, 4, 1, 2, 1]
        
        for code, count in zip(error_codes, counts):
            metric = MagicMock()
            metric.name = "kalshi_orders_rejected_total"
            metric.value = count
            metric.labels = {"error_code": code}
            mock_metrics.append(metric)
        
        mock_instance.collect.return_value = mock_metrics
        
        # Call the endpoint function directly (async)
        result = asyncio.run(get_order_error_breakdown(window_hours=24))
        
        # Verify top-level structure
        assert "window_hours" in result
        assert "total_rejections" in result
        assert "breakdown" in result
        assert "by_category" in result
        assert "by_severity" in result
        assert "top_errors" in result
        assert "last_updated" in result
        
        # Verify totals
        assert result["total_rejections"] == sum(counts)
        assert result["window_hours"] == 24
        
        # Verify breakdown items have all expected fields matching taxonomy
        breakdown = result["breakdown"]
        assert len(breakdown) == len(error_codes)
        
        for item in breakdown:
            code_str = item["code"]
            error_code = KalshiOrderErrorCode.from_string(code_str)
            
            # Verify taxonomy metadata is preserved
            assert item["severity"] == error_code.severity
            assert item["category"] == error_code.category
            assert item["is_retryable"] == error_code.is_retryable
            assert item["description"] == error_code.description
            
            # Verify percentage calculation
            expected_count = counts[error_codes.index(code_str)]
            assert item["count"] == expected_count
            expected_percentage = round((expected_count / sum(counts)) * 100, 2)
            assert item["percentage"] == expected_percentage
        
        # Verify by_category aggregation matches utility function
        utility_by_code, utility_by_severity, utility_by_category = get_error_breakdown(error_codes)
        
        endpoint_by_category = result["by_category"]
        for cat, codes in utility_by_category.items():
            if cat in endpoint_by_category:
                expected_count = sum(counts[error_codes.index(c)] for c in codes if c in error_codes)
                assert endpoint_by_category[cat]["count"] == expected_count
                assert set(endpoint_by_category[cat]["codes"]) == set(codes)
        
        # Verify by_severity aggregation
        endpoint_by_severity = result["by_severity"]
        for severity, count in utility_by_severity.items():
            expected_count = sum(
                counts[error_codes.index(c)] 
                for c in error_codes 
                if KalshiOrderErrorCode.from_string(c).severity == severity
            )
            assert endpoint_by_severity[severity] == expected_count
        
        # Verify top_errors ordering (should be sorted by count descending)
        top_errors = result["top_errors"]
        sorted_counts = sorted(counts, reverse=True)
        for i, item in enumerate(top_errors):
            assert item["count"] == sorted_counts[i]

    @patch('monitoring.kalshi_metrics.get_kalshi_metrics_collector')
    def test_api_handles_unknown_error_codes(self, mock_collector):
        """API gracefully handles unknown error codes using UNKNOWN taxonomy."""
        mock_instance = MagicMock()
        mock_collector.return_value = mock_instance
        
        # Create mock metric with unknown error code
        mock_metric = MagicMock()
        mock_metric.name = "kalshi_orders_rejected_total"
        mock_metric.value = 5
        mock_metric.labels = {"error_code": "not_a_real_code"}
        
        mock_instance.collect.return_value = [mock_metric]
        
        result = asyncio.run(get_order_error_breakdown(window_hours=24))
        
        assert result["total_rejections"] == 5
        assert len(result["breakdown"]) == 1
        
        unknown_item = result["breakdown"][0]
        assert unknown_item["code"] == "not_a_real_code"
        
        # Should use UNKNOWN taxonomy values
        unknown_code = KalshiOrderErrorCode.UNKNOWN
        assert unknown_item["severity"] == unknown_code.severity
        assert unknown_item["category"] == unknown_code.category
        assert unknown_item["is_retryable"] == unknown_code.is_retryable
        assert unknown_item["description"] == "Unknown error occurred"  # fallback description

    @patch('monitoring.kalshi_metrics.get_kalshi_metrics_collector')
    def test_api_empty_metrics(self, mock_collector):
        """API handles empty metrics gracefully."""
        mock_instance = MagicMock()
        mock_collector.return_value = mock_instance
        mock_instance.collect.return_value = []
        
        result = asyncio.run(get_order_error_breakdown(window_hours=48))
        
        assert result["total_rejections"] == 0
        assert result["breakdown"] == []
        assert result["by_category"] == {}
        assert result["by_severity"] == {"critical": 0, "warning": 0, "info": 0}
        assert result["top_errors"] == []
        assert result["window_hours"] == 48

    @patch('monitoring.kalshi_metrics.get_kalshi_metrics_collector')
    def test_api_error_propagation(self, mock_collector):
        """API properly propagates collector errors."""
        mock_collector.side_effect = Exception("Metrics collector failed")
        
        with pytest.raises(Exception) as exc_info:
            asyncio.run(get_order_error_breakdown(window_hours=24))
        
        assert "Metrics collector failed" in str(exc_info.value)

    def test_taxonomy_contract_stability(self):
        """Taxonomy contract remains stable and predictable."""
        # Test critical error codes have expected properties
        critical_codes = [
            KalshiOrderErrorCode.KILL_SWITCH,
            KalshiOrderErrorCode.CIRCUIT_BREAKER,
            KalshiOrderErrorCode.DAILY_LOSS_LIMIT,
        ]
        
        for code in critical_codes:
            assert code.severity == "critical"
            assert code.is_retryable is False
            assert len(code.description) > 10  # Meaningful description
        
        # Test retryable codes have expected properties
        retryable_codes = [
            KalshiOrderErrorCode.EXCHANGE_ERROR,
            KalshiOrderErrorCode.RATE_LIMIT,
            KalshiOrderErrorCode.WEBSOCKET_UNAVAILABLE,
        ]
        
        for code in retryable_codes:
            assert code.is_retryable is True
            assert code.severity in ("critical", "warning")
        
        # Test validation codes have expected properties
        validation_codes = [
            KalshiOrderErrorCode.INVALID_ORDER,
            KalshiOrderErrorCode.INVALID_PRICE,
            KalshiOrderErrorCode.INVALID_TICKER,
        ]
        
        for code in validation_codes:
            assert code.category == "validation"
            assert code.is_retryable is False
            assert code.severity in ("info", "warning")

    def test_error_breakdown_utility_contract(self):
        """get_error_breakdown utility maintains stable contract."""
        # Test with mixed string and enum inputs
        mixed_codes = [
            "kill_switch",
            KalshiOrderErrorCode.RATE_LIMIT,
            "invalid_price",
            KalshiOrderErrorCode.EXCHANGE_ERROR,
        ]
        
        by_code, by_severity, by_category = get_error_breakdown(mixed_codes)
        
        # Verify structure
        assert isinstance(by_code, dict)
        assert isinstance(by_severity, dict)
        assert isinstance(by_category, dict)
        
        # Verify expected keys
        assert "kill_switch" in by_code
        assert "rate_limit" in by_code
        assert "invalid_price" in by_code
        assert "exchange_error" in by_code
        
        # Verify severity aggregation
        assert by_severity["critical"] >= 1  # kill_switch + exchange_error
        assert by_severity["warning"] >= 1    # rate_limit + invalid_price
        
        # Verify category aggregation
        assert "risk" in by_category
        assert "system" in by_category
        assert "validation" in by_category
        
        # Verify all counts are 1 (no duplicates in mixed input)
        for count in by_code.values():
            assert count == 1

    def test_from_string_contract_stability(self):
        """from_string factory maintains stable contract."""
        # Valid codes
        assert KalshiOrderErrorCode.from_string("kill_switch") == KalshiOrderErrorCode.KILL_SWITCH
        assert KalshiOrderErrorCode.from_string("rate_limit") == KalshiOrderErrorCode.RATE_LIMIT
        assert KalshiOrderErrorCode.from_string("unknown") == KalshiOrderErrorCode.UNKNOWN
        
        # Invalid codes default to UNKNOWN
        assert KalshiOrderErrorCode.from_string("invalid_code") == KalshiOrderErrorCode.UNKNOWN
        assert KalshiOrderErrorCode.from_string("") == KalshiOrderErrorCode.UNKNOWN
        assert KalshiOrderErrorCode.from_string(None) == KalshiOrderErrorCode.UNKNOWN  # type: ignore
        
        # Properties are preserved for converted codes
        code = KalshiOrderErrorCode.from_string("kill_switch")
        assert code.severity == "critical"
        assert code.category == "risk"
        assert code.is_retryable is False

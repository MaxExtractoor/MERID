"""Integration test for /order-errors endpoint.

This test ensures the API endpoint returns data consistent with the
KalshiOrderErrorCode taxonomy and utility functions.
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from merid.event_venues.kalshi.order_errors import (
    KalshiOrderErrorCode,
    get_error_breakdown,
)
from web.api.kalshi_api import router


class TestOrderErrorsEndpointIntegration:
    """Integration test for /order-errors API endpoint."""

    def setup_method(self):
        """Set up test client."""
        from fastapi import FastAPI
        from web.api.auth import get_current_session
        app = FastAPI()
        app.include_router(router)
        # Bypass auth in tests
        app.dependency_overrides[get_current_session] = lambda: {"user": None, "session_id": "__test__"}
        self.client = TestClient(app)

    @patch('monitoring.kalshi_metrics.get_kalshi_metrics_collector')
    def test_order_errors_endpoint_shape_consistency(self, mock_collector):
        """Endpoint returns JSON shape consistent with KalshiOrderError.to_dict()."""
        # Mock metrics collector to return sample data
        mock_instance = MagicMock()
        mock_collector.return_value = mock_instance
        
        # Create mock metrics with error codes
        mock_metric1 = MagicMock()
        mock_metric1.name = "kalshi_orders_rejected_total"
        mock_metric1.value = 5
        mock_metric1.labels = {"error_code": "kill_switch"}
        
        mock_metric2 = MagicMock()
        mock_metric2.name = "kalshi_orders_rejected_total"
        mock_metric2.value = 3
        mock_metric2.labels = {"error_code": "rate_limit"}
        
        mock_metric3 = MagicMock()
        mock_metric3.name = "kalshi_orders_rejected_total"
        mock_metric3.value = 2
        mock_metric3.labels = {"error_code": "invalid_price"}
        
        mock_metric4 = MagicMock()
        mock_metric4.name = "kalshi_orders_rejected_total"
        mock_metric4.value = 1
        mock_metric4.labels = {"error_code": "unknown"}
        
        mock_instance.collect.return_value = [
            mock_metric1, mock_metric2, mock_metric3, mock_metric4
        ]
        
        # Call the endpoint
        response = self.client.get("/api/v1/kalshi/order-errors")
        assert response.status_code == 200
        
        data = response.json()
        
        # Verify top-level structure
        assert "window_hours" in data
        assert "total_rejections" in data
        assert "breakdown" in data
        assert "by_category" in data
        assert "by_severity" in data
        assert "top_errors" in data
        assert "last_updated" in data
        
        # Verify totals
        assert data["total_rejections"] == 11  # 5 + 3 + 2 + 1
        assert data["window_hours"] == 24  # default
        
        # Verify breakdown items have all expected fields
        breakdown = data["breakdown"]
        assert len(breakdown) == 4
        
        # Check kill_switch entry
        kill_switch_item = next(item for item in breakdown if item["code"] == "kill_switch")
        assert kill_switch_item["count"] == 5
        assert kill_switch_item["severity"] == "critical"
        assert kill_switch_item["category"] == "risk"
        assert kill_switch_item["is_retryable"] is False
        assert kill_switch_item["description"] == "Kill switch active - trading halted"
        assert kill_switch_item["percentage"] == pytest.approx(45.45, rel=1e-2)  # 5/11
        
        # Check rate_limit entry
        rate_limit_item = next(item for item in breakdown if item["code"] == "rate_limit")
        assert rate_limit_item["count"] == 3
        assert rate_limit_item["severity"] == "warning"
        assert rate_limit_item["category"] == "system"
        assert rate_limit_item["is_retryable"] is True
        assert rate_limit_item["description"] == "Rate limit hit - throttling"
        assert rate_limit_item["percentage"] == pytest.approx(27.27, rel=1e-2)  # 3/11
        
        # Check invalid_price entry
        invalid_price_item = next(item for item in breakdown if item["code"] == "invalid_price")
        assert invalid_price_item["count"] == 2
        assert invalid_price_item["severity"] == "warning"
        assert invalid_price_item["category"] == "validation"
        assert invalid_price_item["is_retryable"] is False
        assert invalid_price_item["description"] == "Invalid price submitted"
        assert invalid_price_item["percentage"] == pytest.approx(18.18, rel=1e-2)  # 2/11
        
        # Check unknown entry
        unknown_item = next(item for item in breakdown if item["code"] == "unknown")
        assert unknown_item["count"] == 1
        assert unknown_item["severity"] == "info"
        assert unknown_item["category"] == "system"
        assert unknown_item["is_retryable"] is True
        assert unknown_item["description"] == "Unknown error occurred"
        assert unknown_item["percentage"] == pytest.approx(9.09, rel=1e-2)  # 1/11
        
        # Verify by_category aggregation
        by_category = data["by_category"]
        assert by_category["risk"]["count"] == 5  # kill_switch
        assert by_category["risk"]["codes"] == ["kill_switch"]
        assert by_category["system"]["count"] == 4  # rate_limit + unknown
        assert set(by_category["system"]["codes"]) == {"rate_limit", "unknown"}
        assert by_category["validation"]["count"] == 2  # invalid_price
        assert by_category["validation"]["codes"] == ["invalid_price"]
        
        # Verify by_severity aggregation
        by_severity = data["by_severity"]
        assert by_severity["critical"] == 5  # kill_switch
        assert by_severity["warning"] == 5   # rate_limit + invalid_price
        assert by_severity["info"] == 1      # unknown
        
        # Verify top_errors (should be sorted by count descending)
        top_errors = data["top_errors"]
        assert len(top_errors) == 4  # max 5, but we only have 4
        assert top_errors[0]["code"] == "kill_switch"  # highest count
        assert top_errors[1]["code"] == "rate_limit"
        assert top_errors[2]["code"] == "invalid_price"
        assert top_errors[3]["code"] == "unknown"
        
        # Verify last_updated is a valid ISO timestamp
        assert data["last_updated"]
        assert "T" in data["last_updated"]  # ISO format indicator

    @patch('monitoring.kalshi_metrics.get_kalshi_metrics_collector')
    def test_order_errors_endpoint_consistency_with_utility(self, mock_collector):
        """Endpoint data is consistent with get_error_breakdown utility."""
        # Mock metrics collector
        mock_instance = MagicMock()
        mock_collector.return_value = mock_instance
        
        # Create mock metrics
        mock_metrics = []
        error_codes = ["kill_switch", "rate_limit", "invalid_price", "daily_loss_limit"]
        counts = [3, 7, 2, 4]
        
        for code, count in zip(error_codes, counts):
            metric = MagicMock()
            metric.name = "kalshi_orders_rejected_total"
            metric.value = count
            metric.labels = {"error_code": code}
            mock_metrics.append(metric)
        
        mock_instance.collect.return_value = mock_metrics
        
        # Get endpoint data
        response = self.client.get("/api/v1/kalshi/order-errors")
        assert response.status_code == 200
        data = response.json()
        
        # Get utility breakdown for same codes
        utility_by_code, utility_by_severity, utility_by_category = get_error_breakdown(error_codes)
        
        # Verify by_severity matches utility
        endpoint_by_severity = data["by_severity"]
        
        # Calculate expected severity counts from utility
        expected_severity = {"critical": 0, "warning": 0, "info": 0}
        for code in error_codes:
            error_code = KalshiOrderErrorCode.from_string(code)
            expected_severity[error_code.severity] += counts[error_codes.index(code)]
        
        assert endpoint_by_severity["critical"] == expected_severity["critical"]
        assert endpoint_by_severity["warning"] == expected_severity["warning"]
        assert endpoint_by_severity["info"] == expected_severity["info"]
        
        # Verify by_category structure matches utility
        endpoint_by_category = data["by_category"]
        for cat, codes in utility_by_category.items():
            if cat in endpoint_by_category:
                expected_count = sum(counts[error_codes.index(c)] for c in codes if c in error_codes)
                assert endpoint_by_category[cat]["count"] == expected_count

    @patch('monitoring.kalshi_metrics.get_kalshi_metrics_collector')
    def test_order_errors_endpoint_empty_metrics(self, mock_collector):
        """Endpoint handles empty metrics gracefully."""
        mock_instance = MagicMock()
        mock_collector.return_value = mock_instance
        mock_instance.collect.return_value = []
        
        response = self.client.get("/api/v1/kalshi/order-errors")
        assert response.status_code == 200
        
        data = response.json()
        assert data["total_rejections"] == 0
        assert data["breakdown"] == []
        assert data["by_category"] == {}
        assert data["by_severity"] == {"critical": 0, "warning": 0, "info": 0}
        assert data["top_errors"] == []

    @patch('monitoring.kalshi_metrics.get_kalshi_metrics_collector')
    def test_order_errors_endpoint_with_window_hours(self, mock_collector):
        """Endpoint respects window_hours parameter."""
        mock_instance = MagicMock()
        mock_collector.return_value = mock_instance
        mock_instance.collect.return_value = []
        
        response = self.client.get("/api/v1/kalshi/order-errors?window_hours=48")
        assert response.status_code == 200
        
        data = response.json()
        assert data["window_hours"] == 48

    @patch('monitoring.kalshi_metrics.get_kalshi_metrics_collector')
    def test_order_errors_endpoint_error_handling(self, mock_collector):
        """Endpoint handles collector errors gracefully."""
        mock_collector.side_effect = Exception("Metrics collector failed")
        
        response = self.client.get("/api/v1/kalshi/order-errors")
        assert response.status_code == 500
        assert "detail" in response.json()

    @patch('monitoring.kalshi_metrics.get_kalshi_metrics_collector')
    def test_order_errors_endpoint_invalid_error_codes(self, mock_collector):
        """Endpoint handles unknown error codes gracefully."""
        mock_instance = MagicMock()
        mock_collector.return_value = mock_instance
        
        # Create mock metric with unknown error code
        mock_metric = MagicMock()
        mock_metric.name = "kalshi_orders_rejected_total"
        mock_metric.value = 5
        mock_metric.labels = {"error_code": "not_a_real_code"}
        
        mock_instance.collect.return_value = [mock_metric]
        
        response = self.client.get("/api/v1/kalshi/order-errors")
        assert response.status_code == 200
        
        data = response.json()
        assert data["total_rejections"] == 5
        
        # Unknown code should be treated as UNKNOWN
        unknown_item = data["breakdown"][0]
        assert unknown_item["code"] == "not_a_real_code"
        assert unknown_item["severity"] == "info"  # UNKNOWN severity
        assert unknown_item["category"] == "system"  # UNKNOWN category
        assert unknown_item["description"]  # fallback description exists

    @patch('monitoring.kalshi_metrics.get_kalshi_metrics_collector')
    def test_order_errors_endpoint_breakdown_ordering(self, mock_collector):
        """Breakdown is sorted by count descending."""
        mock_instance = MagicMock()
        mock_collector.return_value = mock_instance
        
        # Create mock metrics with different counts
        mock_metrics = []
        error_codes = ["invalid_price", "kill_switch", "rate_limit", "daily_loss_limit"]
        counts = [2, 8, 5, 3]  # Not in order
        
        for code, count in zip(error_codes, counts):
            metric = MagicMock()
            metric.name = "kalshi_orders_rejected_total"
            metric.value = count
            metric.labels = {"error_code": code}
            mock_metrics.append(metric)
        
        mock_instance.collect.return_value = mock_metrics
        
        response = self.client.get("/api/v1/kalshi/order-errors")
        assert response.status_code == 200
        
        data = response.json()
        breakdown = data["breakdown"]
        
        # Should be sorted by count descending
        assert breakdown[0]["code"] == "kill_switch"  # count=8
        assert breakdown[1]["code"] == "rate_limit"  # count=5
        assert breakdown[2]["code"] == "daily_loss_limit"  # count=3
        assert breakdown[3]["code"] == "invalid_price"  # count=2
        
        # Verify percentages are calculated correctly
        total = sum(counts)
        for item in breakdown:
            expected_percentage = round((item["count"] / total) * 100, 2)
            assert item["percentage"] == expected_percentage

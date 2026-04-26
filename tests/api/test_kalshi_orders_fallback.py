"""
Pass 8 Tests: REST Fallback Guard

Verifies that /api/v1/kalshi/orders:
- Fails closed (503) if order_router unavailable in LIVE/PAPER
- Does NOT fall back to KalshiRestClient.create_order()
- Triggers kill-switch alert
- Logs contract violation
"""

import pytest
from unittest.mock import patch, MagicMock, ANY
from fastapi.testclient import TestClient
import importlib


class TestOrdersFallbackGuard:
    """Test orders endpoint fails closed without router."""
    
    @pytest.fixture
    def mock_rest_client(self):
        """Mock that would be dangerous if called."""
        mock = MagicMock()
        mock.create_order.return_value = {
            "order_id": "DANGEROUS-FALLBACK-123",
            "status": "filled"
        }
        return mock
    
    def test_orders_fails_closed_in_live_when_router_missing(self, client: TestClient):
        """Must return 503, not use REST fallback in LIVE."""
        # Simulate order_router import failure
        with patch.dict("sys.modules", {"execution.order_router": None}):
            with patch("merid.trading.trade_mode.get_trade_mode", return_value="live"):
                # Also need to simulate the ImportError when trying to use router
                with patch("web.api.kalshi_api._get_order_router", side_effect=ImportError("No module named 'execution.order_router'")):
                    response = client.post(
                        "/api/v1/kalshi/orders",
                        json={
                            "ticker": "KXBTC-250425",
                            "side": "yes",
                            "action": "buy",
                            "count": 10,
                            "price": 50  # cents
                        }
                    )
                    
                    assert response.status_code == 503, \
                        f"Expected 503 (fail closed) in LIVE, got {response.status_code}"
                    
                    data = response.json()
                    assert "degraded" in data.get("detail", "").lower() or \
                           "halted" in data.get("detail", "").lower() or \
                           "unavailable" in data.get("detail", "").lower()
    
    def test_orders_fails_closed_in_paper_when_router_missing(self, client: TestClient):
        """Must return 503, not use REST fallback in PAPER."""
        with patch("merid.trading.trade_mode.get_trade_mode", return_value="paper"):
            with patch("web.api.kalshi_api._get_order_router", side_effect=ImportError("Router unavailable")):
                response = client.post(
                    "/api/v1/kalshi/orders",
                    json={
                        "ticker": "KXBTC-250425",
                        "side": "yes",
                        "action": "buy",
                        "count": 10,
                        "price": 50
                    }
                )
                
                assert response.status_code == 503, \
                    f"Expected 503 in PAPER, got {response.status_code}"
    
    def test_orders_no_rest_fallback_called_in_live(self, client: TestClient, mock_rest_client):
        """Verify KalshiRestClient.create_order is NEVER called in LIVE fallback."""
        with patch("merid.trading.trade_mode.get_trade_mode", return_value="live"):
            with patch("web.api.kalshi_api._get_order_router", side_effect=ImportError("Router down")):
                # This mock should NEVER be called
                with patch("web.api.kalshi_api._get_rest_client", return_value=mock_rest_client):
                    response = client.post(
                        "/api/v1/kalshi/orders",
                        json={"ticker": "KXBTC-250425", "side": "yes", "action": "buy", "count": 10, "price": 50}
                    )
                    
                    # REST client should NOT be called
                    mock_rest_client.create_order.assert_not_called()
                    assert response.status_code == 503
    
    def test_orders_triggers_kill_switch_in_live(self, client: TestClient):
        """Kill switch should be triggered on executor failure."""
        mock_ks = MagicMock()
        
        with patch("merid.trading.trade_mode.get_trade_mode", return_value="live"):
            with patch("web.api.kalshi_api._get_order_router", side_effect=ImportError("Router down")):
                with patch("merid.risk.kill_switches.get_kill_switch", return_value=mock_ks):
                    response = client.post(
                        "/api/v1/kalshi/orders",
                        json={"ticker": "KXBTC-250425", "side": "yes", "action": "buy", "count": 10, "price": 50}
                    )
                    
                    # Kill switch should have been triggered
                    mock_ks.trigger.assert_called_once()
                    call_args = mock_ks.trigger.call_args
                    assert "contract violation" in call_args.kwargs.get("reason", "").lower() or \
                           "executor" in call_args.kwargs.get("reason", "").lower() or \
                           "unavailable" in call_args.kwargs.get("reason", "").lower()
                    assert call_args.kwargs.get("severity") == "critical"
    
    def test_orders_allows_fallback_in_sim_mode(self, client: TestClient, mock_rest_client):
        """SIM mode can use fallback for development (different risk profile)."""
        with patch("merid.trading.trade_mode.get_trade_mode", return_value="sim"):
            with patch("web.api.kalshi_api._get_order_router", side_effect=ImportError("Router down")):
                with patch("web.api.kalshi_api._get_rest_client", return_value=mock_rest_client):
                    response = client.post(
                        "/api/v1/kalshi/orders",
                        json={"ticker": "KXBTC-250425", "side": "yes", "action": "buy", "count": 10, "price": 50}
                    )
                    
                    # SIM mode may allow fallback (for development)
                    # This test documents the behavior
                    # Note: Implementation may still choose to fail closed in SIM
                    pass  # Document behavior
    
    def test_orders_logs_contract_violation(self, client: TestClient, caplog):
        """Must log contract violation attempt."""
        import logging
        
        with caplog.at_level(logging.ERROR):
            with patch("merid.trading.trade_mode.get_trade_mode", return_value="live"):
                with patch("web.api.kalshi_api._get_order_router", side_effect=ImportError("Router down")):
                    client.post(
                        "/api/v1/kalshi/orders",
                        json={"ticker": "KXBTC-250425", "side": "yes", "action": "buy", "count": 10, "price": 50}
                    )
        
        # Should log the security event
        assert any("PASS8_GUARD" in record.message or
                   "contract violation" in record.message.lower() or
                   "REST fallback blocked" in record.message
                   for record in caplog.records), \
            "Contract violation must be logged"


class TestOrdersFallbackInvariants:
    """Invariant tests for fallback behavior."""
    
    @pytest.mark.parametrize("mode", ["live", "paper", "LIVE", "PAPER"])
    def test_all_live_variants_fail_closed(self, client: TestClient, mode: str):
        """All live/paper variants must fail closed."""
        with patch("merid.trading.trade_mode.get_trade_mode", return_value=mode):
            with patch("web.api.kalshi_api._get_order_router", side_effect=ImportError("Router down")):
                response = client.post(
                    "/api/v1/kalshi/orders",
                    json={"ticker": "KXBTC-250425", "side": "yes", "action": "buy", "count": 10, "price": 50}
                )
                assert response.status_code == 503, f"Mode '{mode}' should fail closed"

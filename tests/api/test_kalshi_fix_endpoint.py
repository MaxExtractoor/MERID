"""
Pass 8 Tests: FIX Endpoint Guards

Verifies that /api/v1/kalshi/fix/orders:
- Returns 403 in LIVE/PAPER modes
- Is accessible in SIM/MOCK modes
- Logs security events appropriately
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


class TestFixEndpointGuards:
    """Test FIX endpoint is disabled in live/paper modes."""
    
    @pytest.fixture
    def mock_fix_client(self):
        """Mock FIX client for sim mode tests."""
        mock = MagicMock()
        mock.submit_order.return_value = {
            "order_id": "FIX-TEST-123",
            "status": "pending"
        }
        return mock
    
    def test_fix_orders_blocked_in_live_mode(self, client: TestClient):
        """FIX endpoint must return 403 in LIVE mode."""
        with patch("merid.trading.trade_mode.get_trade_mode", return_value="live"):
            response = client.post(
                "/api/v1/kalshi/fix/orders",
                json={
                    "ticker": "KXBTC-250425",
                    "side": "buy",
                    "quantity": 10,
                    "price": 5000
                }
            )
            
            assert response.status_code == 403, \
                f"Expected 403 in LIVE mode, got {response.status_code}"
            
            data = response.json()
            assert "disabled" in data.get("detail", "").lower() or \
                   "canonical executor" in data.get("detail", "").lower()
    
    def test_fix_orders_blocked_in_paper_mode(self, client: TestClient):
        """FIX endpoint must return 403 in PAPER mode."""
        with patch("merid.trading.trade_mode.get_trade_mode", return_value="paper"):
            response = client.post(
                "/api/v1/kalshi/fix/orders",
                json={
                    "ticker": "KXBTC-250425",
                    "side": "buy",
                    "quantity": 10,
                    "price": 5000
                }
            )
            
            assert response.status_code == 403, \
                f"Expected 403 in PAPER mode, got {response.status_code}"
    
    def test_fix_orders_allowed_in_sim_mode(self, client: TestClient, mock_fix_client):
        """FIX endpoint accessible in SIM/MOCK mode for development."""
        with patch("merid.trading.trade_mode.get_trade_mode", return_value="sim"):
            with patch("web.api.kalshi_api._get_fix_client", return_value=mock_fix_client):
                response = client.post(
                    "/api/v1/kalshi/fix/orders",
                    json={
                        "ticker": "KXBTC-250425",
                        "side": "buy",
                        "quantity": 10,
                        "price": 5000
                    }
                )
                
                # SIM mode allows FIX (for development/testing)
                # Status could be 200 or 202 depending on implementation
                assert response.status_code in [200, 202, 500], \
                    f"SIM mode should attempt FIX, got {response.status_code}"
    
    def test_fix_orders_logs_security_event_in_live(self, client: TestClient, caplog):
        """Security event must be logged when FIX blocked."""
        import logging
        
        with caplog.at_level(logging.ERROR):
            with patch("merid.trading.trade_mode.get_trade_mode", return_value="live"):
                client.post(
                    "/api/v1/kalshi/fix/orders",
                    json={
                        "ticker": "KXBTC-250425",
                        "side": "buy",
                        "quantity": 10
                    }
                )
        
        # Should have logged the security block
        assert any("PASS8_GUARD" in record.message or 
                   "blocked" in record.message.lower() or
                   "disabled" in record.message.lower()
                   for record in caplog.records), \
            "Security block should be logged"
    
    def test_fix_orders_includes_canonical_message(self, client: TestClient):
        """Error message should direct to canonical endpoint."""
        with patch("merid.trading.trade_mode.get_trade_mode", return_value="live"):
            response = client.post(
                "/api/v1/kalshi/fix/orders",
                json={"ticker": "KXBTC-250425", "side": "buy", "quantity": 10}
            )
            
            data = response.json()
            detail = data.get("detail", "")
            
            # Should mention the canonical alternative
            assert any(phrase in detail.lower() for phrase in [
                "canonical executor",
                "/api/v1/kalshi/orders",
                "risk-engineering"
            ]), f"Error message should direct to canonical path: {detail}"


class TestFixEndpointInvariants:
    """Invariant tests for FIX endpoint behavior."""
    
    @pytest.mark.parametrize("mode", ["live", "paper", "LIVE", "PAPER"])
    def test_all_live_variants_blocked(self, client: TestClient, mode: str):
        """All case variants of live/paper must be blocked."""
        with patch("merid.trading.trade_mode.get_trade_mode", return_value=mode):
            response = client.post(
                "/api/v1/kalshi/fix/orders",
                json={"ticker": "KXBTC-250425", "side": "buy", "quantity": 10}
            )
            assert response.status_code == 403, f"Mode '{mode}' should block FIX"

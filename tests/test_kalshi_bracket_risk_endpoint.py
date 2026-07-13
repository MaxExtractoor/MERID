"""Tests for the Kalshi bracket risk endpoint."""
import pytest
from fastapi.testclient import TestClient


class TestKalshiBracketRiskEndpoint:
    """Test the /api/v1/kalshi/bracket-risk endpoint."""

    def test_bracket_risk_returns_valid_structure(self) -> None:
        """Bracket risk endpoint returns valid structure."""
        from web.main_15m_lean import app
        client = TestClient(app)
        response = client.get("/api/v1/kalshi/bracket-risk")
        assert response.status_code == 200

        data = response.json()
        # Check all required fields are present
        assert "halted" in data
        assert isinstance(data["halted"], bool)
        assert "halt_reason" in data
        assert "open_brackets" in data
        assert isinstance(data["open_brackets"], int)
        assert "total_brackets" in data
        assert isinstance(data["total_brackets"], int)
        assert "winning_brackets" in data
        assert "losing_brackets" in data
        assert "win_rate_pct" in data
        assert isinstance(data["win_rate_pct"], (int, float))
        assert "total_pnl_cents" in data
        assert "total_pnl_usd" in data
        assert "consecutive_losers" in data
        assert "max_consecutive_losers_seen" in data
        assert "net_delta" in data
        assert "hours_with_exposure" in data
        assert "contracts_by_hour" in data
        assert isinstance(data["contracts_by_hour"], dict)
        assert "config" in data
        assert isinstance(data["config"], dict)

        # Config should have expected keys
        config = data["config"]
        assert "max_loss_per_contract_pct" in config
        assert "max_loss_per_bracket_cents" in config
        assert "max_contracts_per_hour" in config
        assert "max_notional_per_hour_cents" in config
        assert "max_consecutive_losers" in config
        assert "max_unhedged_delta" in config
        assert "max_open_brackets" in config

    def test_bracket_risk_config_values_are_reasonable(self) -> None:
        """Config values should be within reasonable ranges."""
        from web.main_15m_lean import app
        client = TestClient(app)
        response = client.get("/api/v1/kalshi/bracket-risk")
        assert response.status_code == 200

        data = response.json()
        config = data["config"]

        # Percentage-based configs should be positive
        assert config["max_loss_per_contract_pct"] > 0
        # Cent-based configs should be non-negative (0 means no limit configured)
        assert config["max_loss_per_bracket_cents"] >= 0
        assert config["max_contracts_per_hour"] >= 0
        assert config["max_notional_per_hour_cents"] >= 0
        assert config["max_consecutive_losers"] >= 0
        assert config["max_unhedged_delta"] >= 0
        assert config["max_open_brackets"] >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

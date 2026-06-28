"""Pytest configuration for Kalshi executor tests.

Ensures kill-switch state is cleared before each test so previous
'manual: Test kill' or drawdown kills don't bleed into other tests.
"""
import pytest
import respx
from httpx import Response


@pytest.fixture(autouse=True)
def reset_kill_switches():
    """
    Ensure kill-switch state is cleared before each test.

    This prevents test isolation leaks from the global RiskController singleton.
    """
    from merid.risk.kill_switches import risk_controller

    # Reset the kill switch to allow trading
    # This clears any previous manual kills, daily loss kills, etc.
    risk_controller.reset(operator="test_fixture")

    yield

    # Clean up after each test as well
    risk_controller.reset(operator="test_fixture")


@pytest.fixture(autouse=True)
def mock_kalshi_balance():
    """
    Mock the Kalshi balance endpoint for all tests.

    The KalshiExecutor checks balance before placing orders, so we need to mock this.
    """
    with respx.mock:
        # Mock the balance endpoint used by KalshiExecutor
        respx.get("https://external-api.kalshi.com/trade-api/v2/portfolio/balance").mock(
            return_value=Response(200, json={
                "balance": 1000000,  # $10,000 in cents
                "available_balance": 1000000,
                "portfolio_balance": 0
            })
        )
        yield

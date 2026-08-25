"""Acceptance tests for explicit production vs testing environment policy."""

from __future__ import annotations

import os
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from merid.startup_validations import StartupValidationError, validate_production_startup


# ---------------------------------------------------------------------------
# Startup hard-fail checks
# ---------------------------------------------------------------------------

def test_production_startup_rejects_pytest_current_test(monkeypatch):
    monkeypatch.setenv("MERID_ENV", "prod")
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/x.py::test")
    with pytest.raises(StartupValidationError, match="PYTEST_CURRENT_TEST"):
        validate_production_startup()


def test_production_startup_rejects_debug_manual_orders(monkeypatch):
    monkeypatch.setenv("MERID_ENV", "prod")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("DEBUG_ALLOW_MANUAL_ORDERS", "true")
    with pytest.raises(StartupValidationError, match="DEBUG_ALLOW_MANUAL_ORDERS"):
        validate_production_startup()


def test_production_startup_rejects_allow_direct_execution(monkeypatch):
    monkeypatch.setenv("MERID_ENV", "prod")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("ALLOW_DIRECT_EXECUTION", "true")
    with pytest.raises(StartupValidationError, match="ALLOW_DIRECT_EXECUTION"):
        validate_production_startup()


def test_production_startup_rejects_ct_script_bypass(monkeypatch):
    monkeypatch.setenv("MERID_ENV", "prod")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("MERID_ALLOW_CT_SCRIPT_BYPASS", "1")
    with pytest.raises(StartupValidationError, match="MERID_ALLOW_CT_SCRIPT_BYPASS"):
        validate_production_startup()


def test_production_startup_rejects_firewall_observe_only(monkeypatch):
    monkeypatch.setenv("MERID_ENV", "prod")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("MERID_EXIT_FIREWALL_OBSERVE_ONLY", "true")
    with pytest.raises(StartupValidationError, match="MERID_EXIT_FIREWALL_OBSERVE_ONLY"):
        validate_production_startup()


def test_production_startup_rejects_missing_exit_parentage(monkeypatch):
    monkeypatch.setenv("MERID_ENV", "prod")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setenv("MERID_EXIT_FIREWALL_OBSERVE_ONLY", "false")
    monkeypatch.delenv("MERID_REQUIRE_EXIT_PARENTAGE", raising=False)
    with pytest.raises(StartupValidationError, match="MERID_REQUIRE_EXIT_PARENTAGE"):
        validate_production_startup()


def test_production_startup_passes_when_clean(monkeypatch):
    _clean_prod(monkeypatch)
    validate_production_startup()


def test_testing_env_not_inherited_from_dotenv():
    """conftest must set MERID_ENV=testing and .env must not override it."""
    assert os.environ.get("MERID_ENV") == "testing"


def _clean_prod(monkeypatch):
    """Set a fully clean 15m production environment."""
    monkeypatch.setenv("MERID_ENV", "prod")
    monkeypatch.setenv("MERID_PROFILE", "kalshi_crypto_15m_v2")
    monkeypatch.setenv("MERID_KALSHI_ENV", "prod")
    monkeypatch.delenv("KALSHI_ENV", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("DEBUG_ALLOW_MANUAL_ORDERS", raising=False)
    monkeypatch.delenv("ALLOW_DIRECT_EXECUTION", raising=False)
    monkeypatch.delenv("MERID_ALLOW_CT_SCRIPT_BYPASS", raising=False)
    monkeypatch.setenv("MERID_EXIT_FIREWALL_OBSERVE_ONLY", "false")
    monkeypatch.setenv("MERID_REQUIRE_EXIT_PARENTAGE", "1")
    monkeypatch.setenv("MERID_CIRCUIT_BREAKER_DISABLED", "0")
    for var in ["BINANCE_API_KEY", "COINBASE_API_KEY", "KRAKEN_API_KEY", "ALPACA_API_KEY", "POLYMARKET_API_KEY"]:
        monkeypatch.delenv(var, raising=False)


def test_production_startup_rejects_missing_kalshi_env(monkeypatch):
    _clean_prod(monkeypatch)
    monkeypatch.delenv("MERID_KALSHI_ENV", raising=False)
    monkeypatch.setenv("KALSHI_ENV", "live")
    with pytest.raises(StartupValidationError, match="KALSHI_ENV"):
        validate_production_startup()


def test_production_startup_rejects_kalshi_env_conflict(monkeypatch):
    _clean_prod(monkeypatch)
    monkeypatch.setenv("KALSHI_ENV", "demo")
    with pytest.raises(StartupValidationError, match="KALSHI_ENV"):
        validate_production_startup()


def test_production_startup_rejects_legacy_exchange_credentials(monkeypatch):
    _clean_prod(monkeypatch)
    monkeypatch.setenv("BINANCE_API_KEY", "leaked")
    with pytest.raises(StartupValidationError, match="BINANCE_API_KEY"):
        validate_production_startup()


def test_production_startup_rejects_circuit_breaker_disabled(monkeypatch):
    _clean_prod(monkeypatch)
    monkeypatch.setenv("MERID_CIRCUIT_BREAKER_DISABLED", "1")
    with pytest.raises(StartupValidationError, match="MERID_CIRCUIT_BREAKER_DISABLED"):
        validate_production_startup()


def test_production_startup_rejects_invalid_exit_parentage(monkeypatch):
    _clean_prod(monkeypatch)
    monkeypatch.setenv("MERID_REQUIRE_EXIT_PARENTAGE", "0")
    with pytest.raises(StartupValidationError, match="MERID_REQUIRE_EXIT_PARENTAGE"):
        validate_production_startup()


def test_production_startup_passes_with_canonical_env(monkeypatch):
    _clean_prod(monkeypatch)
    monkeypatch.setenv("KALSHI_ENV", "live")
    validate_production_startup()


# ---------------------------------------------------------------------------
# Direct submission policy
# ---------------------------------------------------------------------------

@pytest.fixture
def _prod_client():
    from merid.event_venues.kalshi.client import KalshiVenueClient
    from merid.event_venues.kalshi.kalshi_config import KalshiConfig

    config = KalshiConfig(
        env="prod",
        rest_base_url="https://external-api.kalshi.com/trade-api/v2",
        ws_base_url="wss://external-api-ws.kalshi.com/trade-api/ws/v2",
        api_key_id="test_key_12345",
        private_key_path="/path/to/key.pem",
        public_rest_api_url="https://api.kalshi.com/public-api/v2",
        private_key_pem="-----BEGIN RSA PRIVATE KEY-----\nMIICXgIBAAJBAL8U2zCkGqM3mLwP+5F1z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9\nz9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z0CAwEAAQJBAKjM3mLw\nP+5F1z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F\n9z9F9z9F9z9F9z9F9z9F9z0CIQDP8U2zCkGqM3mLwP+5F1z9F9z9F9z9F9z9F9z9\nF9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z0IfwIX\nAAL8U2zCkGqM3mLwP+5F1z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9\nz9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z9F9z0=\n-----END RSA PRIVATE KEY-----",
    )
    client = KalshiVenueClient(config)
    client._http_client = AsyncMock()
    client._http_client.is_closed = False
    client._auth_mode = "rsa"
    client._private_key = MagicMock()
    client._private_key.sign.return_value = b"mock_signature"
    yield client


@pytest.mark.asyncio
async def test_direct_place_order_in_prod_rejected_even_with_pytest_current_test(
    _prod_client, monkeypatch
):
    """A direct client.place_order attempt in MERID_ENV=prod is rejected even if
    a PYTEST_CURRENT_TEST artifact is present."""
    from merid.settings import settings
    from merid.event_venues.base import VenueOrder

    monkeypatch.setattr(settings, "MERID_ENV", "prod", raising=False)
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "tests/x.py::test")
    monkeypatch.setenv("DEBUG_ALLOW_MANUAL_ORDERS", "false")
    monkeypatch.setenv("MERID_EXIT_FIREWALL_OBSERVE_ONLY", "false")

    order = VenueOrder(
        market_id="KXBTC15M-001",
        side="sell",
        outcome_id="yes",
        size=Decimal("1"),
        price=Decimal("0.55"),
        order_type="limit",
        client_order_id="unapproved_coid_prod_001",
        reduce_only=True,
    )

    result = await _prod_client.place_order_result(order)
    assert not result.success
    assert "Manual order placement blocked" in (result.error or "") or "firewall" in (result.error or "")
    assert not _prod_client._http_client.request.called


@pytest.mark.asyncio
async def test_direct_place_order_allowed_in_testing_with_explicit_capability(
    _prod_client, monkeypatch
):
    """In MERID_ENV=testing, direct submission is allowed only when the explicit
    test-only capability DEBUG_ALLOW_MANUAL_ORDERS=true is set."""
    from merid.settings import settings
    from merid.event_venues.base import VenueOrder

    monkeypatch.setattr(settings, "MERID_ENV", "testing", raising=False)
    monkeypatch.setenv("DEBUG_ALLOW_MANUAL_ORDERS", "true")
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)

    response = MagicMock(
        status_code=201,
        json=MagicMock(return_value={"order": {"order_id": "o1", "ticker": "KXBTC15M-001", "status": "resting"}}),
        headers={},
        text="",
    )
    _prod_client._http_client.request = AsyncMock(return_value=response)

    order = VenueOrder(
        market_id="KXBTC15M-001",
        side="buy",
        outcome_id="yes",
        size=Decimal("1"),
        price=Decimal("0.55"),
        order_type="limit",
        client_order_id="test_coid_001",
    )

    result = await _prod_client.place_order_result(order)
    assert result.success
    assert _prod_client._http_client.request.called

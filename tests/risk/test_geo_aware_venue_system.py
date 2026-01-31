"""Risk-core tests for GeoAwareVenueSystem allow/deny logic."""

from __future__ import annotations

import pytest

from data.geo_aware_venue_system import (
    AssetClass,
    GeoAwareVenueSystem,
    Jurisdiction,
    VenueType,
)


pytestmark = pytest.mark.risk_core


def _fresh_system() -> GeoAwareVenueSystem:
    system = GeoAwareVenueSystem()
    system._venues.clear()  # type: ignore[attr-defined]
    system._restrictions.clear()  # type: ignore[attr-defined]
    return system


def test_allowed_when_jurisdiction_and_asset_class_match() -> None:
    system = _fresh_system()
    system.register_venue(
        venue_id="alpha",
        name="Alpha",
        venue_type=VenueType.CEX,
        asset_classes={AssetClass.CRYPTO_SPOT},
        allowed_jurisdictions={Jurisdiction.US},
        blocked_jurisdictions=set(),
        supports_rest_api=True,
        supports_websocket=True,
        supports_fix=False,
        supports_historical=True,
        has_tick_data=True,
        has_order_book=True,
        has_ohlcv=True,
        is_free=True,
        requires_kyc=True,
        website="https://alpha",
        api_docs="https://alpha/docs",
    )

    allowed, reason = system.is_venue_allowed("alpha", Jurisdiction.US, AssetClass.CRYPTO_SPOT)
    assert allowed is True
    assert reason is None


def test_blocked_when_jurisdiction_denied() -> None:
    system = _fresh_system()
    system.register_venue(
        venue_id="beta",
        name="Beta",
        venue_type=VenueType.CEX,
        asset_classes={AssetClass.CRYPTO_SPOT},
        allowed_jurisdictions={Jurisdiction.EU},
        blocked_jurisdictions={Jurisdiction.US},
        supports_rest_api=True,
        supports_websocket=True,
        supports_fix=False,
        supports_historical=True,
        has_tick_data=True,
        has_order_book=True,
        has_ohlcv=True,
        is_free=True,
        requires_kyc=True,
        website="https://beta",
        api_docs="https://beta/docs",
    )

    allowed, reason = system.is_venue_allowed("beta", Jurisdiction.US, AssetClass.CRYPTO_SPOT)
    assert allowed is False
    assert "not available" in reason.lower() or "blocked" in reason.lower()


def test_blocked_when_asset_class_not_supported() -> None:
    system = _fresh_system()
    system.register_venue(
        venue_id="gamma",
        name="Gamma",
        venue_type=VenueType.CEX,
        asset_classes={AssetClass.CRYPTO_SPOT},
        allowed_jurisdictions={Jurisdiction.US},
        blocked_jurisdictions=set(),
        supports_rest_api=True,
        supports_websocket=True,
        supports_fix=False,
        supports_historical=True,
        has_tick_data=True,
        has_order_book=True,
        has_ohlcv=True,
        is_free=True,
        requires_kyc=True,
        website="https://gamma",
        api_docs="https://gamma/docs",
    )

    allowed, reason = system.is_venue_allowed("gamma", Jurisdiction.US, AssetClass.EQUITY_SPOT)
    assert allowed is False
    assert "support" in reason.lower()


def test_global_allow_but_specific_jurisdiction_block() -> None:
    system = _fresh_system()
    system.register_venue(
        venue_id="delta",
        name="Delta",
        venue_type=VenueType.CEX,
        asset_classes={AssetClass.CRYPTO_SPOT},
        allowed_jurisdictions={Jurisdiction.GLOBAL},
        blocked_jurisdictions={Jurisdiction.US},
        supports_rest_api=True,
        supports_websocket=True,
        supports_fix=False,
        supports_historical=True,
        has_tick_data=True,
        has_order_book=True,
        has_ohlcv=True,
        is_free=True,
        requires_kyc=True,
        website="https://delta",
        api_docs="https://delta/docs",
    )

    allowed, reason = system.is_venue_allowed("delta", Jurisdiction.US, AssetClass.CRYPTO_SPOT)
    assert allowed is False
    assert "blocked" in reason.lower()

    allowed_global, reason_global = system.is_venue_allowed("delta", Jurisdiction.EU, AssetClass.CRYPTO_SPOT)
    assert allowed_global is True
    assert reason_global is None

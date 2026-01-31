"""Risk-core tests for venue onboarding tripwires."""

from __future__ import annotations

import pytest

from onboarding.venue_registry import RouteGuard, VenueConfig, VenueOnboardingError, VenueRegistry


pytestmark = pytest.mark.risk_core


def test_venue_without_risk_or_surveillance_mappings_is_blocked():
    registry = VenueRegistry()
    guard = RouteGuard(registry)

    cfg = VenueConfig(venue_id="dark_pool", name="Dark Pool")
    registry.register_venue(cfg)

    with pytest.raises(VenueOnboardingError) as exc:
        registry.approve("dark_pool")
    assert "risk mapping" in str(exc.value)
    assert not registry.is_live("dark_pool")
    assert guard.can_route("dark_pool") is False

    registry.set_risk_mapping("dark_pool", {"position_limit": "10mm"})
    with pytest.raises(VenueOnboardingError) as exc:
        registry.approve("dark_pool")
    assert "surveillance" in str(exc.value)
    assert guard.can_route("dark_pool") is False

    registry.set_surveillance_mapping("dark_pool", {"alert_route": "tier1"})
    registry.approve("dark_pool")
    assert registry.is_live("dark_pool")
    assert guard.can_route("dark_pool") is True


def test_duplicate_approval_and_mapping_updates():
    registry = VenueRegistry()
    registry.register_venue(VenueConfig(venue_id="dup", name="Dup"))
    registry.set_risk_mapping("dup", {"risk": "1"})
    registry.set_surveillance_mapping("dup", {"surv": "a"})
    registry.approve("dup")

    with pytest.raises(VenueOnboardingError):
        registry.approve("dup")

    # Update mappings after approval should not break state
    registry.set_risk_mapping("dup", {"risk": "2"})
    registry.set_surveillance_mapping("dup", {"surv": "b"})
    assert registry.is_live("dup") is True


def test_deactivation_blocks_routing():
    registry = VenueRegistry()
    guard = RouteGuard(registry)

    registry.register_venue(VenueConfig(venue_id="temp", name="Temp"))
    registry.set_risk_mapping("temp", {"risk": "safe"})
    registry.set_surveillance_mapping("temp", {"surv": "tier1"})
    registry.approve("temp")
    assert guard.can_route("temp") is True

    registry.deactivate("temp")
    assert registry.is_live("temp") is False
    assert guard.can_route("temp") is False

"""Venue onboarding registry with risk/surveillance gating."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional


class VenueOnboardingError(RuntimeError):
    """Raised when a venue cannot be promoted to live due to missing controls."""


@dataclass
class VenueConfig:
    venue_id: str
    name: str
    metadata: Dict[str, str] = field(default_factory=dict)


class VenueRegistry:
    """Minimal registry enforcing risk/surveillance mappings before go-live."""

    def __init__(self) -> None:
        self._pending: Dict[str, VenueConfig] = {}
        self._risk_mappings: Dict[str, Dict[str, str]] = {}
        self._surveillance_mappings: Dict[str, Dict[str, str]] = {}
        self._approved: Dict[str, VenueConfig] = {}

    def register_venue(self, cfg: VenueConfig) -> None:
        self._pending[cfg.venue_id] = cfg

    def set_risk_mapping(self, venue_id: str, mapping: Dict[str, str]) -> None:
        self._risk_mappings[venue_id] = mapping

    def set_surveillance_mapping(self, venue_id: str, mapping: Dict[str, str]) -> None:
        self._surveillance_mappings[venue_id] = mapping

    def approve(self, venue_id: str) -> None:
        if venue_id not in self._pending:
            raise VenueOnboardingError(f"Venue '{venue_id}' not registered")
        if venue_id in self._approved:
            raise VenueOnboardingError(f"Venue '{venue_id}' already approved")
        if venue_id not in self._risk_mappings:
            raise VenueOnboardingError(f"Venue '{venue_id}' missing risk mapping")
        if venue_id not in self._surveillance_mappings:
            raise VenueOnboardingError(f"Venue '{venue_id}' missing surveillance mapping")

        cfg = self._pending.pop(venue_id)
        self._approved[venue_id] = cfg

    def is_live(self, venue_id: str) -> bool:
        return venue_id in self._approved

    def get_config(self, venue_id: str) -> Optional[VenueConfig]:
        return self._approved.get(venue_id)

    def deactivate(self, venue_id: str) -> None:
        if venue_id in self._approved:
            self._approved.pop(venue_id)


class RouteGuard:
    """Guards routing decisions by checking venue approval state."""

    def __init__(self, registry: VenueRegistry) -> None:
        self._registry = registry

    def can_route(self, venue_id: str) -> bool:
        return self._registry.is_live(venue_id)

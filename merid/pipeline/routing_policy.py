"""RoutingPolicy + VenueSelector — health-aware venue routing for the TradeRouter.

Reads circuit breaker state from the resilience registry and filters
venues by health before order flow reaches them. This prevents routing
live orders to venues whose breakers are OPEN or that are disabled.

Configuration knobs:
    - allow_degraded: Whether to route to venues in HALF_OPEN / degraded state
    - max_degraded_venues: Max simultaneous degraded venues to allow routing to
    - preferred_venues: Per-domain ordered preference list
    - fallback_strategy: What to do when all candidates are unhealthy

Usage:
    policy = RoutingPolicy(allow_degraded=True, max_degraded_venues=2)
    selector = VenueSelector(policy=policy)

    # In TradeRouter, before submitting:
    venue = selector.select(proposal.venue, proposal.domain.value)
    if venue is None:
        proposal.reject("No healthy venue available")
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.pipeline.routing_policy")


class FallbackStrategy(str, Enum):
    """What to do when all candidate venues are unhealthy."""
    REJECT = "reject"          # Reject the proposal outright
    FORCE_SIM = "force_sim"    # Route to the venue but force SIM mode
    BEST_EFFORT = "best_effort"  # Route to the least-bad venue anyway


class VenueHealth(str, Enum):
    """Venue health levels, ordered from best to worst."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    DISABLED = "disabled"


@dataclass
class RoutingPolicy:
    """Configuration for health-aware venue routing.

    Attributes:
        allow_degraded: If True, venues in HALF_OPEN / degraded state are
            eligible for routing. If False, only fully healthy venues are used.
        max_degraded_venues: Maximum number of degraded venues to consider.
            If more than this many are degraded, only healthy ones are used.
        preferred_venues: Per-domain ordered preference list. When multiple
            healthy venues exist, the first match in this list wins.
            Example: {"crypto": ["binance", "coinbase", "kraken"]}
        fallback_strategy: What to do when no healthy (or degraded, if allowed)
            venue is available.
    """
    allow_degraded: bool = True
    max_degraded_venues: int = 2
    preferred_venues: Dict[str, List[str]] = field(default_factory=dict)
    fallback_strategy: FallbackStrategy = FallbackStrategy.REJECT

    def to_dict(self) -> dict:
        return {
            "allow_degraded": self.allow_degraded,
            "max_degraded_venues": self.max_degraded_venues,
            "preferred_venues": self.preferred_venues,
            "fallback_strategy": self.fallback_strategy.value,
        }


@dataclass
class RoutingDecision:
    """Result of a venue selection decision."""
    venue: Optional[str]
    health: Optional[str]
    reason: str
    fallback_used: bool = False
    original_venue: str = ""
    candidates_checked: int = 0

    def to_dict(self) -> dict:
        return {
            "venue": self.venue,
            "health": self.health,
            "reason": self.reason,
            "fallback_used": self.fallback_used,
            "original_venue": self.original_venue,
            "candidates_checked": self.candidates_checked,
        }


class VenueSelector:
    """Selects a healthy venue for order routing based on circuit breaker state.

    Reads breaker state from the resilience registry and mode/enabled state
    from the ModeManager to compute per-venue health, then applies the
    RoutingPolicy to pick the best candidate.
    """

    def __init__(self, policy: Optional[RoutingPolicy] = None):
        self._policy = policy or RoutingPolicy()

    @property
    def policy(self) -> RoutingPolicy:
        return self._policy

    def _get_venue_health(self, venue: str) -> VenueHealth:
        """Compute health for a single venue from breaker + mode state."""
        # Check if venue is enabled in ModeManager
        try:
            from merid.pipeline.mode_manager import get_mode_manager
            mm = get_mode_manager()
            cfg = mm.get_config(venue)
            if cfg and not cfg.enabled:
                return VenueHealth.DISABLED
        except Exception as exc:
            logger.debug(f"Mode manager check error (ignored): {exc}")

        # Check circuit breaker state
        try:
            from merid.resilience.circuit_breaker import get_all_breakers
            breakers = get_all_breakers()
            if venue in breakers:
                state = breakers[venue].state.value
                if state == "open":
                    return VenueHealth.UNHEALTHY
                if state == "half_open":
                    return VenueHealth.DEGRADED
                if breakers[venue].failure_count > 0:
                    return VenueHealth.DEGRADED
        except Exception as exc:
            logger.debug(f"Circuit breaker check error (ignored): {exc}")

        return VenueHealth.HEALTHY

    def _get_domain_candidates(self, domain: str) -> List[str]:
        """Get all venues for a domain, in preference order."""
        preferred = self._policy.preferred_venues.get(domain, [])

        # Get all venues for this domain from ModeManager
        try:
            from merid.pipeline.mode_manager import get_mode_manager
            mm = get_mode_manager()
            all_venues = [c.venue for c in mm.venues_by_domain(domain)]
        except Exception:
            all_venues = []

        # Preferred first, then any remaining
        ordered = list(preferred)
        for v in all_venues:
            if v not in ordered:
                ordered.append(v)
        return ordered

    def check_venue(self, venue: str) -> Tuple[bool, VenueHealth]:
        """Check if a specific venue is eligible for routing.

        Returns (eligible, health).
        """
        health = self._get_venue_health(venue)

        if health == VenueHealth.HEALTHY:
            return True, health
        if health == VenueHealth.DEGRADED and self._policy.allow_degraded:
            return True, health
        return False, health

    def select(self, requested_venue: str, domain: str) -> RoutingDecision:
        """Select the best venue for a proposal.

        1. If the requested venue is healthy, use it.
        2. If the requested venue is degraded and policy allows, use it.
        3. Otherwise, try alternative venues in the same domain.
        4. If no healthy venue found, apply fallback strategy.
        """
        # First: check the requested venue
        eligible, health = self.check_venue(requested_venue)
        if eligible:
            return RoutingDecision(
                venue=requested_venue,
                health=health.value,
                reason="requested_venue_healthy" if health == VenueHealth.HEALTHY
                    else "requested_venue_degraded",
                original_venue=requested_venue,
                candidates_checked=1,
            )

        # Requested venue is not eligible — try alternatives
        candidates = self._get_domain_candidates(domain)
        checked = 1  # already checked requested_venue
        degraded_count = 0

        for candidate in candidates:
            if candidate == requested_venue:
                continue
            checked += 1
            c_eligible, c_health = self.check_venue(candidate)
            if not c_eligible:
                continue
            if c_health == VenueHealth.DEGRADED:
                degraded_count += 1
                if degraded_count > self._policy.max_degraded_venues:
                    continue
            logger.info(
                f"Failover: {requested_venue} ({health.value}) -> "
                f"{candidate} ({c_health.value}) for domain={domain}"
            )
            return RoutingDecision(
                venue=candidate,
                health=c_health.value,
                reason="failover",
                fallback_used=True,
                original_venue=requested_venue,
                candidates_checked=checked,
            )

        # No healthy venue found — apply fallback strategy
        strategy = self._policy.fallback_strategy

        if strategy == FallbackStrategy.FORCE_SIM:
            logger.warning(
                f"All venues unhealthy for domain={domain}. "
                f"Forcing SIM on {requested_venue}."
            )
            return RoutingDecision(
                venue=requested_venue,
                health=health.value,
                reason="force_sim_fallback",
                fallback_used=True,
                original_venue=requested_venue,
                candidates_checked=checked,
            )

        if strategy == FallbackStrategy.BEST_EFFORT:
            logger.warning(
                f"All venues unhealthy for domain={domain}. "
                f"Best-effort routing to {requested_venue}."
            )
            return RoutingDecision(
                venue=requested_venue,
                health=health.value,
                reason="best_effort_fallback",
                fallback_used=True,
                original_venue=requested_venue,
                candidates_checked=checked,
            )

        # REJECT (default)
        logger.warning(
            f"All venues unhealthy for domain={domain}. Rejecting proposal."
        )
        return RoutingDecision(
            venue=None,
            health=None,
            reason="all_venues_unhealthy",
            fallback_used=False,
            original_venue=requested_venue,
            candidates_checked=checked,
        )

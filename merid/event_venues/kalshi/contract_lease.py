"""Contract Lease Registry — Single ownership per (venue, contract, side, strategy).

Enforces invariant: at most one owner agent per (venue, contract_id, side,
strategy_group) tuple at any instant.  All agents must acquire a lease through
this registry before building an order.

Design:
  - In-memory map with TTL-based expiry (no Redis dependency).
  - Thread-safe via threading.Lock (agents run on asyncio but grid startup
    and CT cycle are multi-threaded).
  - Coordinator-mediated hand-off: only ``release`` or ``transfer`` can change
    ownership — never direct agent-to-agent.
  - Structured logging on every acquire / conflict / release for audit trail.

Usage::

    from merid.event_venues.kalshi.contract_lease import (
        get_contract_lease_registry,
        LeaseKey,
    )

    reg = get_contract_lease_registry()
    key = LeaseKey(venue="kalshi", contract_id="KXBTC-25DEC-T100000",
                   side="yes", strategy_group="btc_15m")
    lease = reg.acquire(key, owner_agent_id="BTC_15M_MOMENTUM")
    if lease is None:
        # Another agent owns this contract — abort order
        ...
    # … build and submit order …
    reg.release(key, owner_agent_id="BTC_15M_MOMENTUM")
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.contract_lease")

# Default lease TTL in seconds.  Agents must renew before expiry or the lease
# lapses and another agent can claim the contract.
DEFAULT_LEASE_TTL_S: float = 300.0  # 5 minutes

# Maximum TTL to prevent infinite leases from configuration mistakes.
MAX_LEASE_TTL_S: float = 3600.0  # 1 hour


# ── Data models ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class LeaseKey:
    """Composite key for a contract lease.

    Attributes:
        venue:          Exchange / venue name (always "kalshi" for now).
        contract_id:    Market ticker, e.g. ``KXBTC-25DEC-T100000``.
        side:           ``"yes"`` or ``"no"``.
        strategy_group: Logical strategy group, e.g. ``"btc_15m"`` or ``"ct"``.
    """
    venue: str
    contract_id: str
    side: str
    strategy_group: str

    def __str__(self) -> str:
        return f"{self.venue}:{self.contract_id}:{self.side}:{self.strategy_group}"


@dataclass
class Lease:
    """Active lease metadata."""
    key: LeaseKey
    owner_agent_id: str
    acquired_at: float = field(default_factory=time.monotonic)
    expires_at: float = 0.0
    renewals: int = 0

    @property
    def is_expired(self) -> bool:
        return time.monotonic() > self.expires_at

    def remaining_seconds(self) -> float:
        return max(0.0, self.expires_at - time.monotonic())


# ── Metrics counters ─────────────────────────────────────────────────────────

@dataclass
class LeaseMetrics:
    """Observable counters for the lease registry."""
    acquired: int = 0
    released: int = 0
    conflicts: int = 0
    expired: int = 0
    renewed: int = 0
    transferred: int = 0


# ── Registry ─────────────────────────────────────────────────────────────────

class ContractLeaseRegistry:
    """Thread-safe in-memory contract lease registry.

    Invariant: ``_leases[key]`` always contains the single current owner.
    """

    def __init__(self, default_ttl_s: float = DEFAULT_LEASE_TTL_S) -> None:
        self._lock = threading.Lock()
        self._leases: Dict[LeaseKey, Lease] = {}
        self._default_ttl = min(max(default_ttl_s, 1.0), MAX_LEASE_TTL_S)
        self._metrics = LeaseMetrics()

    # ── Core API ─────────────────────────────────────────────────────────

    def acquire(
        self,
        key: LeaseKey,
        owner_agent_id: str,
        ttl_s: Optional[float] = None,
    ) -> Optional[Lease]:
        """Attempt to acquire an exclusive lease.

        Returns:
            The :class:`Lease` if acquired, or ``None`` if another agent
            already owns this key (conflict).
        """
        ttl = min(ttl_s or self._default_ttl, MAX_LEASE_TTL_S)
        now = time.monotonic()

        with self._lock:
            existing = self._leases.get(key)

            # Lease exists and is still valid — conflict
            if existing is not None and not existing.is_expired:
                if existing.owner_agent_id == owner_agent_id:
                    # Same owner re-acquiring → treat as renewal
                    existing.expires_at = now + ttl
                    existing.renewals += 1
                    self._metrics.renewed += 1
                    logger.debug(
                        "[LEASE] renewed key=%s owner=%s renewals=%d remaining=%.1fs",
                        key, owner_agent_id, existing.renewals, existing.remaining_seconds(),
                    )
                    return existing

                # Different owner — hard conflict
                self._metrics.conflicts += 1
                logger.warning(
                    "[LEASE-CONFLICT] key=%s requested_by=%s current_owner=%s "
                    "remaining=%.1fs",
                    key, owner_agent_id, existing.owner_agent_id,
                    existing.remaining_seconds(),
                )
                return None

            # Expired lease — clean up metrics
            if existing is not None and existing.is_expired:
                self._metrics.expired += 1
                logger.debug(
                    "[LEASE] expired key=%s previous_owner=%s",
                    key, existing.owner_agent_id,
                )

            # Grant new lease
            lease = Lease(
                key=key,
                owner_agent_id=owner_agent_id,
                acquired_at=now,
                expires_at=now + ttl,
            )
            self._leases[key] = lease
            self._metrics.acquired += 1
            logger.info(
                "[LEASE] acquired key=%s owner=%s ttl=%.0fs",
                key, owner_agent_id, ttl,
            )
            return lease

    def release(self, key: LeaseKey, owner_agent_id: str) -> bool:
        """Release a lease.  Only the current owner may release.

        Returns True if released, False if not owned by this agent.
        """
        with self._lock:
            existing = self._leases.get(key)
            if existing is None:
                logger.debug("[LEASE] release no-op: key=%s not in registry", key)
                return False
            if existing.owner_agent_id != owner_agent_id:
                logger.warning(
                    "[LEASE] release denied: key=%s requested_by=%s actual_owner=%s",
                    key, owner_agent_id, existing.owner_agent_id,
                )
                return False
            del self._leases[key]
            self._metrics.released += 1
            logger.info(
                "[LEASE] released key=%s owner=%s held_for=%.1fs",
                key, owner_agent_id, time.monotonic() - existing.acquired_at,
            )
            return True

    def renew(self, key: LeaseKey, owner_agent_id: str, ttl_s: Optional[float] = None) -> bool:
        """Extend the TTL on an existing lease.  Only the current owner may renew.

        Returns True if renewed, False otherwise.
        """
        ttl = min(ttl_s or self._default_ttl, MAX_LEASE_TTL_S)
        with self._lock:
            existing = self._leases.get(key)
            if existing is None or existing.owner_agent_id != owner_agent_id:
                return False
            existing.expires_at = time.monotonic() + ttl
            existing.renewals += 1
            self._metrics.renewed += 1
            logger.debug(
                "[LEASE] renewed key=%s owner=%s renewals=%d",
                key, owner_agent_id, existing.renewals,
            )
            return True

    def transfer(
        self,
        key: LeaseKey,
        from_agent_id: str,
        to_agent_id: str,
        ttl_s: Optional[float] = None,
    ) -> bool:
        """Coordinator-mediated ownership transfer.

        Only succeeds if ``from_agent_id`` is the current owner.
        The new owner gets a fresh TTL.
        """
        ttl = min(ttl_s or self._default_ttl, MAX_LEASE_TTL_S)
        now = time.monotonic()
        with self._lock:
            existing = self._leases.get(key)
            if existing is None or existing.owner_agent_id != from_agent_id:
                logger.warning(
                    "[LEASE] transfer denied: key=%s from=%s — not current owner",
                    key, from_agent_id,
                )
                return False
            existing.owner_agent_id = to_agent_id
            existing.expires_at = now + ttl
            existing.renewals = 0
            self._metrics.transferred += 1
            logger.info(
                "[LEASE] transferred key=%s from=%s to=%s ttl=%.0fs",
                key, from_agent_id, to_agent_id, ttl,
            )
            return True

    # ── Query API ────────────────────────────────────────────────────────

    def owner_of(self, key: LeaseKey) -> Optional[str]:
        """Return the current owner agent_id, or None if unleased/expired."""
        with self._lock:
            existing = self._leases.get(key)
            if existing is None or existing.is_expired:
                return None
            return existing.owner_agent_id

    def is_owned_by(self, key: LeaseKey, agent_id: str) -> bool:
        """Check if a specific agent owns this key."""
        return self.owner_of(key) == agent_id

    def active_leases(self) -> List[Lease]:
        """Return snapshot of all non-expired leases."""
        now = time.monotonic()
        with self._lock:
            return [l for l in self._leases.values() if l.expires_at > now]

    def active_count(self) -> int:
        """Number of currently active (non-expired) leases."""
        now = time.monotonic()
        with self._lock:
            return sum(1 for l in self._leases.values() if l.expires_at > now)

    def leases_for_agent(self, agent_id: str) -> List[Lease]:
        """Return all active leases held by a specific agent."""
        now = time.monotonic()
        with self._lock:
            return [
                l for l in self._leases.values()
                if l.owner_agent_id == agent_id and l.expires_at > now
            ]

    # ── Maintenance ──────────────────────────────────────────────────────

    def prune_expired(self) -> int:
        """Remove all expired leases.  Returns count removed."""
        now = time.monotonic()
        with self._lock:
            expired_keys = [k for k, v in self._leases.items() if v.expires_at <= now]
            for k in expired_keys:
                del self._leases[k]
            if expired_keys:
                self._metrics.expired += len(expired_keys)
        return len(expired_keys)

    def force_release_all(self, reason: str = "admin") -> int:
        """Emergency: release ALL leases.  Returns count released."""
        with self._lock:
            count = len(self._leases)
            self._leases.clear()
            logger.warning("[LEASE] force_release_all: cleared %d leases reason=%s", count, reason)
            return count

    # ── Metrics ──────────────────────────────────────────────────────────

    def get_metrics(self) -> Dict[str, int]:
        """Return copy of observable counters."""
        m = self._metrics
        return {
            "acquired": m.acquired,
            "released": m.released,
            "conflicts": m.conflicts,
            "expired": m.expired,
            "renewed": m.renewed,
            "transferred": m.transferred,
            "active": self.active_count(),
        }


# ── Global singleton ─────────────────────────────────────────────────────────

_registry: Optional[ContractLeaseRegistry] = None
_registry_lock = threading.Lock()


def get_contract_lease_registry() -> ContractLeaseRegistry:
    """Get the process-wide contract lease registry singleton."""
    global _registry
    if _registry is not None:
        return _registry
    with _registry_lock:
        if _registry is None:
            _registry = ContractLeaseRegistry()
        return _registry


def reset_contract_lease_registry_for_testing() -> None:
    """Reset the global singleton (tests only)."""
    global _registry
    with _registry_lock:
        _registry = None

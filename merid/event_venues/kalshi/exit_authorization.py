"""Shared exit-authorization policy — single source for emergency authority.

Versioned (``AUTHORIZATION_POLICY_VERSION``) so audit records can pin the
policy an authorization was evaluated under.

Three consumers, three distinct questions:

- ``ExitArbiter``: may this *proposal* claim a floor exception at all?
  (``authorize_emergency`` — issuer/type/generation binding)
- ``ExecutionRiskFirewall``: does the *approved decision* still match the
  current exposure at submit time?  (revalidates the same tables)
- Router/client: does the *transmitted payload* equal the approved
  decision?  (approval binding — not this module's job)

Producer provenance
-------------------

``authorization_source`` is a label; ``ProducerToken`` is the provenance.
A named producer registers once at module-init time and receives a token
object; a proposal asserting emergency authority must carry the token
whose ``issuer`` equals its declared ``authorization_source``.  An
ordinary producer can write any label into ``authorization_source`` — but
without the registered token for that issuer the claim fails.  Within a
process this is the practical boundary: registering as "position_monitor"
is identifying as that component, and the issuer table still scopes what
that component may request.

In-process trust limit: a compromised producer module could import the
registry and mint a token for an already-registered name (``register``
returns the existing token).  The binding this module *does* guarantee is
that an unregistered/arbitrary producer cannot mint privileged proposals
and that a token issued to one producer cannot speak for another.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Dict, Optional

AUTHORIZATION_POLICY_VERSION = "exit-auth-v1"


# Emergency types permitted to submit below the fee-adjusted floor
# (deliberate loss-taking).  Declaring a type is necessary, never
# sufficient — the issuer/generation binding below must also pass.
LOSS_AUTHORIZED_EMERGENCY_TYPES = frozenset({
    "POSITION_LOSS_BUDGET",
    "ACCOUNT_LOSS_BUDGET",
    "MARKET_OBLIGATION",
    "STATE_REPAIR",
    "OPERATIONAL_RISK",
    "EXTERNAL_AUTHORITY",
    "GENERIC_EMERGENCY",
})


# Authorization (independent of classification): which issuing component
# may request which emergency type.  ``normalize_order`` classifies a
# proposal — it never grants privilege.  A producer not listed for a type
# cannot acquire below-floor authority even with a valid-looking tuple.
EMERGENCY_TYPE_ISSUERS: Dict[str, frozenset] = {
    "POSITION_LOSS_BUDGET": frozenset({
        "position_monitor", "position_monitor_exit",
        "position_monitor_exit_retry",
        "stop_candidate", "stop_candidate_reducer",
    }),
    # No account-wide loss-budget exit controller exists today.  A future
    # one must identify as one of these; everything else is denied.
    "ACCOUNT_LOSS_BUDGET": frozenset({
        "unified_risk_manager", "global_allocator",
    }),
    "MARKET_OBLIGATION": frozenset({
        "position_monitor", "position_monitor_exit",
        "position_monitor_exit_retry", "settlement_aligned_exit",
        "stop_candidate",
    }),
    "STATE_REPAIR": frozenset({
        "position_monitor", "position_monitor_exit",
        "position_monitor_exit_retry", "reconciliation",
        "canonical_reconciler",
    }),
    "OPERATIONAL_RISK": frozenset({
        "position_monitor", "position_monitor_exit",
        "position_monitor_exit_retry",
        "stop_candidate", "stop_candidate_reducer",
        "hedge_engine",
    }),
    "EXTERNAL_AUTHORITY": frozenset({
        "manual", "operator", "manual_close", "external_exit",
    }),
    "GENERIC_EMERGENCY": frozenset({
        "position_monitor", "position_monitor_exit",
        "position_monitor_exit_retry",
        "stop_candidate", "stop_candidate_reducer",
    }),
}


# Issuers permitted to run reduce-only exits with weak/unknown parentage
# (identity tolerance — grants no loss-taking authority).
OPERATIONAL_EXIT_ISSUERS = frozenset({
    "position_monitor", "position_monitor_exit",
    "position_monitor_exit_retry",
    "stop_candidate", "stop_candidate_reducer", "stop_candidate_degraded",
    "settlement_aligned_exit", "reconciliation", "canonical_reconciler",
    "manual", "operator", "manual_close", "external_exit",
    "resting_bracket_stop_loss", "resting_bracket_take_profit",
    "market_maker_15m", "hedge_engine",
})


MANUAL_CLOSE_ISSUERS = frozenset({
    "manual", "operator", "manual_close", "external_exit",
})


# ---------------------------------------------------------------------------
# Producer provenance
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProducerToken:
    """Issued once per registered producer name.  A proposal carrying a
    token asserts it was built by the component that owns the name; the
    arbiter requires ``token.issuer == proposal.authorization_source``."""

    issuer: str
    policy_version: str = AUTHORIZATION_POLICY_VERSION


class ProducerRegistry:
    """Process-wide table of registered producer tokens."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tokens: Dict[str, ProducerToken] = {}

    def register(self, issuer: str) -> ProducerToken:
        """Register a producer name; returns the canonical token.

        First registrant wins the name — subsequent calls for the same
        name return the same token (the token IS the name's identity, so
        duplicate registration is idempotent, not a second identity).
        """
        issuer = (issuer or "").strip()
        if not issuer:
            raise ValueError("producer issuer must be non-empty")
        with self._lock:
            tok = self._tokens.get(issuer)
            if tok is None:
                tok = ProducerToken(issuer=issuer)
                self._tokens[issuer] = tok
            return tok

    def token_for(self, issuer: str) -> Optional[ProducerToken]:
        with self._lock:
            return self._tokens.get((issuer or "").strip())


_REGISTRY = ProducerRegistry()


def register_producer(issuer: str) -> ProducerToken:
    return _REGISTRY.register(issuer)


def registered_token(issuer: str) -> Optional[ProducerToken]:
    return _REGISTRY.token_for(issuer)


# ---------------------------------------------------------------------------
# Authorization checks
# ---------------------------------------------------------------------------

def authorize_emergency(
    *,
    emergency_type: Optional[str],
    authorization_source: Optional[str],
    position_generation_id: Optional[str],
    expected_generation_id: Optional[str],
    producer_issuer: Optional[str] = None,
    producer_token: Optional[ProducerToken] = None,
    require_token: bool = True,
) -> Optional[str]:
    """Loss-taking authorization check.

    Returns ``None`` when the emergency tuple authorizes a below-floor /
    loss-taking submission for ``expected_generation_id``; else a stable
    denial reason string.

    Fail-closed rules:
      - missing declared generation can never satisfy a live generation
        (empty-vs-empty is NOT consistency)
      - the type must be in ``LOSS_AUTHORIZED_EMERGENCY_TYPES``
      - the issuer must be allowlisted for that type
      - provenance: a valid ``producer_token`` issued to the declared
        ``producer_issuer`` must be supplied (the token proves the
        proposal was built through the controlled path; the
        ``authorization_source`` is the *authority* claim and may differ
        from the producing module, e.g. a monitor relaying an operator's
        manual close)
    """
    if not expected_generation_id:
        return "generation_unbound"
    if not position_generation_id or \
            position_generation_id != expected_generation_id:
        return "generation_unbound"
    etype = (emergency_type or "").strip().upper()
    if etype not in LOSS_AUTHORIZED_EMERGENCY_TYPES:
        return "emergency_type_not_loss_authorized"
    src = (authorization_source or "").strip()
    issuers = EMERGENCY_TYPE_ISSUERS.get(etype, frozenset())
    if not src or src not in issuers:
        return "issuer_not_authorized"
    if producer_token is None:
        return "producer_token_missing" if require_token else None
    if producer_issuer is not None and \
            producer_token.issuer != producer_issuer:
        return "token_issuer_mismatch"
    return None


def operational_issuer_ok(
    *,
    exit_class: Optional[str],
    authorization_source: Optional[str],
    producer_token: Optional[ProducerToken] = None,
) -> bool:
    """Identity-tolerance check (parentage-exempt reduce-only exits).

    Operational issuers may run reduce-only exits when parentage is weak;
    this never grants loss-taking authority.
    """
    if (exit_class or "").strip().lower() not in ("emergency", "operational"):
        return False
    src = (authorization_source or "").strip()
    if src not in OPERATIONAL_EXIT_ISSUERS:
        return False
    if producer_token is not None and producer_token.issuer != src:
        return False
    return True

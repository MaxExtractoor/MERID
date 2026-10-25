"""Position risk contract: explicit no-edge salvage classification.

2026-10-26 alignment patch (SOL-2215): a bounded research probe admitted
under a negative-net-EV exception was classified "model-edge" because
``entry_edge_pct`` was fabricated to +0.03 when the intent's ``edge_pct``
was absent, and the union discriminator then saw only positive claims.
The authorized net claim lived on the intent (``ev_net_cents``) but was
never persisted into the position.

Contract (versioned):

* ``entry_authorized_net_edge_c`` is the authoritative no-edge claim -- the
  exact net-of-cost EV the submitted route's gate compared against the
  effective admission threshold (``decision.{side}_net_edge * 100`` ->
  ``intent.ev_net_cents``).  NOT ``raw_edge_cents`` (gross model-vs-market).
* ``entry_gross_edge_c`` preserves the legacy gross stamp separately so
  edge-decay consumers are untouched.
* Classification states are explicit: KNOWN_POSITIVE, KNOWN_NONPOSITIVE,
  UNKNOWN (missing provenance), CONFLICT (conflicting persisted claims).
  Missing provenance is never manufactured into a positive claim.
* Salvage eligibility (existing policy, thresholds unchanged):
      KNOWN_NONPOSITIVE -> eligible under the existing no-edge policy
      KNOWN_POSITIVE    -> not eligible via the no-edge carve-out
      UNKNOWN/CONFLICT  -> not eligible; flagged for reconciliation; the
                           legacy union discriminator is preserved so
                           existing controls are unchanged.

Pure module: no heavy imports; safe to import from monitors and tests.
"""
from __future__ import annotations

from typing import Any, Optional, Tuple

RISK_POLICY_ID = "no_edge_salvage_contract"
RISK_POLICY_VERSION = "2026-10-26.1"

NET_CLAIM_KNOWN_POSITIVE = "KNOWN_POSITIVE"
NET_CLAIM_KNOWN_NONPOSITIVE = "KNOWN_NONPOSITIVE"
NET_CLAIM_UNKNOWN = "UNKNOWN"
NET_CLAIM_CONFLICT = "CONFLICT"

# entry_edge_pct_claim_source values that mark a fabricated compat default
# rather than a persisted claim.  Compat values never produce a CONFLICT
# and never count as evidence — they exist only for numeric edge-decay
# consumers that still read the legacy field.
_COMPAT_CLAIM_SOURCES = frozenset({
    "post_init_compat_default",
    "deserialize_compat_default",
    "missing",
    "rest_reconstruct_missing",
    "snapshot_gross_alias",
})


def classify_net_claim(value: Optional[float]) -> str:
    """Explicit classification of a persisted authorized net claim (cents)."""
    if value is None:
        return NET_CLAIM_UNKNOWN
    try:
        v = float(value)
    except (TypeError, ValueError):
        return NET_CLAIM_UNKNOWN
    return NET_CLAIM_KNOWN_NONPOSITIVE if v <= 0.0 else NET_CLAIM_KNOWN_POSITIVE


def _as_float(v: Any) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def resolve_net_claim_state(position: Any) -> Tuple[str, Optional[float], str]:
    """Resolve the persisted net-claim state for a position.

    Returns (state, value_c, source).  Reads the contract fields first;
    reports CONFLICT when two persisted claim fields disagree in sign
    classification (never silently picks one).
    """
    net = getattr(position, "entry_authorized_net_edge_c", None)
    net_v = _as_float(net) if net is not None else None
    net_state = classify_net_claim(net_v)

    # Legacy claim fields are evidence, not authority: they can conflict
    # with the contract stamp — but only when they are real persisted
    # claims, not compat-fabricated defaults.
    pct_source = getattr(position, "entry_edge_pct_claim_source", None)
    legacy_pct = _as_float(getattr(position, "entry_edge_pct", None))
    if pct_source in _COMPAT_CLAIM_SOURCES:
        legacy_pct = None  # compat-fabricated: not a claim
    gross = _as_float(getattr(position, "entry_edge", None))

    if net_state == NET_CLAIM_UNKNOWN:
        if legacy_pct is None and gross is None:
            return NET_CLAIM_UNKNOWN, None, "no_persisted_claim"
        # Contract field absent but legacy stamps exist: legacy union
        # semantics govern (preserves existing controls for pre-contract
        # positions); source is reported honestly.
        vals = [v for v in (legacy_pct, gross) if v is not None]
        if any(v <= 0.0 for v in vals):
            return NET_CLAIM_KNOWN_NONPOSITIVE, min(vals), "legacy_union"
        return NET_CLAIM_UNKNOWN, None, "missing_net_claim_provenance"

    conflicts = []
    for name, v in (("entry_edge_pct", legacy_pct),):
        if v is not None and classify_net_claim(v) != net_state:
            conflicts.append(name)
    if conflicts:
        return (
            NET_CLAIM_CONFLICT,
            net_v,
            "contract_vs_%s" % ",".join(conflicts),
        )
    return net_state, net_v, "contract"


def no_edge_salvage_eligible(position: Any) -> Tuple[bool, str]:
    """Return (eligible, reason) under the existing no-edge salvage policy.

    Eligible only on an explicit KNOWN_NONPOSITIVE authorized net claim or
    the preserved legacy union for pre-contract positions.  UNKNOWN and
    CONFLICT are never eligible and are flagged, not fabricated.

    Persisted verdict handling: a stamped ``no_edge_salvage_eligible`` is
    the authorized control — it is honored when stamped under this policy
    version (with a recompute consistency check), and preserved with an
    explicit flag when stamped under a different version.  A persisted
    verdict is never silently recomputed under a different policy version.
    """
    persisted = getattr(position, "no_edge_salvage_eligible", None)
    if persisted is not None:
        ver = getattr(position, "risk_policy_version", None)
        if ver is not None and ver != RISK_POLICY_VERSION:
            return bool(persisted), "persisted_prior_policy:%s" % ver
        state, _v, src = resolve_net_claim_state(position)
        if state == NET_CLAIM_CONFLICT:
            return False, "claim_conflict:%s" % src
        computed = state == NET_CLAIM_KNOWN_NONPOSITIVE
        if computed != bool(persisted):
            # Restore-time disagreement between claim fields, claim state,
            # and the persisted verdict: preserve the stamped control and
            # keep the divergence observable.
            return bool(persisted), "restore_disagreement:persisted=%s computed=%s:%s" % (
                persisted, state, src,
            )
        return bool(persisted), "persisted_contract:%s" % src

    state, _value, source = resolve_net_claim_state(position)
    if state == NET_CLAIM_KNOWN_NONPOSITIVE:
        return True, "net_claim_nonpositive:%s" % source
    if state == NET_CLAIM_KNOWN_POSITIVE:
        return False, "net_claim_positive:%s" % source
    if state == NET_CLAIM_CONFLICT:
        return False, "claim_conflict:%s" % source
    # UNKNOWN: preserve current controls (legacy union) for pre-contract
    # positions whose stamps exist; positions with no stamps at all keep
    # the historical model-edge treatment but are flagged by source.
    if source == "missing_net_claim_provenance":
        return False, "unknown_claim_flagged:%s" % source
    return False, "unknown_claim:%s" % source


def legacy_union_no_edge_claim(position: Any) -> bool:
    """Pre-contract discriminator, kept verbatim for fallback and audit."""
    for attr in ("entry_edge_pct", "entry_edge"):
        v = getattr(position, attr, None)
        if v is not None and float(v) <= 0.0:
            return True
    return False


def risk_contract_fields(
    *,
    gross_edge_c: Optional[float],
    authorized_net_edge_c: Optional[float],
    net_edge_source: Optional[str],
    admission_type: Optional[str],
    admission_lane: Optional[str],
    effective_threshold_c: Optional[float],
    decision_id: Optional[str] = None,
    selected_route: Optional[str] = None,
) -> dict:
    """Build the persisted position risk contract for a new fill.

    ``eligible`` is computed at stamp time; ``reason`` records provenance
    (state:source) so a later audit can see exactly which claim governed.
    """
    class _P:  # lightweight view over the contract values themselves
        pass

    p = _P()
    p.entry_authorized_net_edge_c = authorized_net_edge_c
    p.entry_edge_pct = None
    p.entry_edge = None
    state, value, source = resolve_net_claim_state(p)
    eligible, reason = no_edge_salvage_eligible(p)
    return {
        "entry_gross_edge_c": gross_edge_c,
        "entry_authorized_net_edge_c": authorized_net_edge_c,
        "entry_authorized_net_edge_source": net_edge_source,
        "entry_admission_type": admission_type,
        "entry_admission_lane": admission_lane,
        "entry_effective_threshold_c": effective_threshold_c,
        "risk_decision_id": decision_id,
        "risk_selected_route": selected_route,
        "risk_policy_id": RISK_POLICY_ID,
        "risk_policy_version": RISK_POLICY_VERSION,
        "net_claim_state": state,
        "net_claim_state_source": source,
        "no_edge_salvage_eligible": eligible,
        "no_edge_salvage_eligibility_reason": reason,
    }

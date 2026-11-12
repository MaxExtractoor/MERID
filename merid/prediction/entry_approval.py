"""Explicit entry-approval state for risk-increasing orders.

Every new-risk entry must carry an authoritative approval from the decision
layer (``TradeDecision``).  ``None``, zero, and positive quantities must never
share one ambiguous field: this module resolves the approval into an explicit
state so admission can enforce "approved ceiling or no entry" without
guessing.

States
------
APPROVED    — a selected outcome with a positive centi-contract ceiling and a
              valid decision identity, still within the freshness window.
REJECTED    — the decision engine actively denied the entry (no selected
              outcome, or an approved size of zero).  Zero is a rejection,
              never "no ceiling".
UNAVAILABLE — approval could not be established (missing decision object,
              missing/unparseable ceiling, missing decision identity, or the
              resolver itself failed).
EXPIRED     — the decision was approved but is older than
              ``MERID_ENTRY_APPROVAL_MAX_AGE_S``.

Only APPROVED carries ``ceiling_cc`` (centi-contracts).  Downstream stages
(window-plan admission, sizing, router) may reduce the ceiling but must never
increase it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


class ApprovalState(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"
    EXPIRED = "expired"


@dataclass(frozen=True)
class EntryApproval:
    state: ApprovalState
    ceiling_cc: Optional[int] = None
    decision_id: Optional[str] = None
    reason: str = ""
    age_s: Optional[float] = None
    detail: Dict[str, Any] = field(default_factory=dict)

    @property
    def approved(self) -> bool:
        return self.state is ApprovalState.APPROVED


def approval_enforced() -> bool:
    """Kill switch: MERID_ENTRY_APPROVAL_ENFORCED=0 logs would-be rejections
    without blocking (emergency shadow mode only)."""
    return os.environ.get("MERID_ENTRY_APPROVAL_ENFORCED", "1").strip().lower() not in (
        "0", "false", "no", "off",
    )


def _max_age_s() -> float:
    try:
        return float(os.environ.get("MERID_ENTRY_APPROVAL_MAX_AGE_S", "120.0"))
    except (TypeError, ValueError):
        return 120.0


def _coerce_timestamp_utc(value: Any) -> Optional[datetime]:
    """Best-effort parse of TradeDecision.timestamp_utc (datetime, ISO str,
    or epoch seconds).  Naive datetimes are treated as UTC."""
    if value is None:
        return None
    if isinstance(value, datetime):
        ts = value
    elif isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    else:
        try:
            ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def resolve_entry_approval(
    candidate: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> EntryApproval:
    """Resolve the entry-approval state for one candidate dict.

    ``candidate`` is the loop's candidate mapping; the authoritative approval
    lives on ``candidate["trade_decision"]`` (a ``TradeDecision``).  Pure and
    side-effect free — safe to call in tests and shadow paths.
    """
    now = now or datetime.now(timezone.utc)
    td = candidate.get("trade_decision") if isinstance(candidate, dict) else None
    fallback_did = candidate.get("decision_id") if isinstance(candidate, dict) else None

    if td is None:
        return EntryApproval(
            state=ApprovalState.UNAVAILABLE,
            decision_id=fallback_did,
            reason="missing_trade_decision",
        )

    decision_id = getattr(td, "decision_id", None) or fallback_did

    selected = getattr(td, "selected_outcome", None)
    if not selected:
        no_trade = getattr(td, "no_trade_reason", None)
        return EntryApproval(
            state=ApprovalState.REJECTED,
            decision_id=decision_id,
            reason="no_selected_outcome",
            detail={"no_trade_reason": no_trade},
        )

    asc = getattr(td, "approved_size_cc", None)
    if asc is None:
        return EntryApproval(
            state=ApprovalState.UNAVAILABLE,
            decision_id=decision_id,
            reason="approved_size_missing",
        )
    try:
        ceiling_cc = int(asc)  # centi-contracts; int() floors fractional cc
    except (TypeError, ValueError):
        return EntryApproval(
            state=ApprovalState.UNAVAILABLE,
            decision_id=decision_id,
            reason="approved_size_unparseable",
            detail={"approved_size_cc": str(asc)},
        )

    if ceiling_cc <= 0:
        # Zero is an explicit rejection — never "no ceiling".
        return EntryApproval(
            state=ApprovalState.REJECTED,
            ceiling_cc=ceiling_cc,
            decision_id=decision_id,
            reason="approved_size_zero",
            detail={"approved_size_cc": ceiling_cc},
        )

    ts = _coerce_timestamp_utc(getattr(td, "timestamp_utc", None))
    age_s: Optional[float] = None
    if ts is not None:
        age_s = (now - ts).total_seconds()
        if age_s < 0:
            # Clock skew: a future-dated decision is not yet valid.
            return EntryApproval(
                state=ApprovalState.UNAVAILABLE,
                ceiling_cc=ceiling_cc,
                decision_id=decision_id,
                reason="decision_timestamp_future",
                age_s=age_s,
            )
        if age_s > _max_age_s():
            return EntryApproval(
                state=ApprovalState.EXPIRED,
                ceiling_cc=ceiling_cc,
                decision_id=decision_id,
                reason="decision_expired",
                age_s=age_s,
                detail={"max_age_s": _max_age_s()},
            )
    else:
        # No usable timestamp: cannot bound approval freshness → unavailable.
        return EntryApproval(
            state=ApprovalState.UNAVAILABLE,
            ceiling_cc=ceiling_cc,
            decision_id=decision_id,
            reason="decision_timestamp_missing",
        )

    return EntryApproval(
        state=ApprovalState.APPROVED,
        ceiling_cc=ceiling_cc,
        decision_id=decision_id,
        reason="approved",
        age_s=age_s,
        detail={
            "selected_outcome": str(selected),
            "policy_version": getattr(td, "policy_version", None),
            "config_hash": getattr(td, "config_hash", None),
        },
    )

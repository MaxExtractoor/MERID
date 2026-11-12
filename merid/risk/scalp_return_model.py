"""Scalp net-return model interface — the ``f*`` input for Kelly sizing.

Destination model (Release 2+): a validated *conditional* distribution of net
scalp returns per dollar allocated, estimated from realized trade outcomes
including fees, partial fills, failed exits, and forced holds — conditional on
a manageable feature set (asset, side, entry price, time remaining, route,
signal strength, exit policy, quantity).

Until that model is validated, ``get_active_return_model()`` returns ``None``
and callers must treat Kelly magnitude as unavailable — sizing stays
cap/gate-driven and shadow targets are labeled provisional.  A two-outcome
approximation is permitted for unit tests and shadow comparisons only; it is
not the production allocation model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol, Tuple


@dataclass(frozen=True)
class ReturnOutcome:
    """One branch of the net-return distribution.

    ``probability`` — branch probability (branches need not sum to 1 exactly;
    the estimator is responsible for normalization/shrinkage).
    ``net_return`` — net profit/loss per dollar of acquisition cost allocated,
    inclusive of fees, exit costs, and realized execution frictions.
    """
    probability: float
    net_return: float
    label: str = ""


@dataclass(frozen=True)
class ReturnDistribution:
    """Conditional net-return distribution for one candidate."""
    model_version: str
    outcomes: Tuple[ReturnOutcome, ...]
    features: Dict[str, Any] = field(default_factory=dict)
    sample_size: int = 0
    shrinkage_applied: bool = False


class ScalpReturnModel(Protocol):
    """Validated conditional scalp-return estimator."""

    model_version: str

    def estimate(
        self,
        *,
        asset: str,
        side: str,
        entry_price_cents: float,
        quantity_cc: Optional[int] = None,
        features: Optional[Dict[str, Any]] = None,
    ) -> Optional[ReturnDistribution]:
        """Return the net-return distribution for this candidate, or None when
        the model has insufficient support (caller must not size on it)."""
        ...


_ACTIVE_MODEL: Optional[ScalpReturnModel] = None


def register_return_model(model: ScalpReturnModel) -> None:
    """Install the active return model (Release 2 validation gate decides when
    a real model may be registered)."""
    global _ACTIVE_MODEL
    _ACTIVE_MODEL = model


def get_active_return_model() -> Optional[ScalpReturnModel]:
    """The validated return model, or None while unvalidated."""
    return _ACTIVE_MODEL


def reset_for_tests() -> None:
    global _ACTIVE_MODEL
    _ACTIVE_MODEL = None

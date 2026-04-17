"""
Versioned Kalshi fee schedule (quadratic / parabolic maker-taker).

Compare against Kalshi Series API fee metadata in CI when credentials exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True)
class KalshiFeeSchedule:
    """Active fee model for prediction contracts."""

    version: str
    fee_type: Literal["quadratic"] = "quadratic"
    taker_rate: Decimal = Decimal("0.07")
    maker_rate: Decimal = Decimal("0.0175")


DEFAULT_KALSHI_FEE_SCHEDULE = KalshiFeeSchedule(version="parabolic-default-2024")


def get_active_fee_schedule() -> KalshiFeeSchedule:
    """Return the in-repo schedule; override via env in future if needed."""
    return DEFAULT_KALSHI_FEE_SCHEDULE

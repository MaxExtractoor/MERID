"""
RWA integration adapters for Ondo, Maple, Goldfinch.

Provides unified portfolio view, yield stats, and compliance metadata so vaults
can allocate capital into tokenized T-bills, credit pools, and RWA loans.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Dict, List


@dataclass
class RWAInstrument:
    platform: str
    asset: str
    apy: Decimal
    lockup_days: int
    outstanding_principal: Decimal
    risk_rating: str
    last_update: datetime


class RWAIntegrationHub:
    def __init__(self) -> None:
        self._positions: Dict[str, RWAInstrument] = {}

    def register_instrument(self, platform: str, asset: str, apy: Decimal, lockup_days: int, principal: Decimal, risk_rating: str) -> None:
        instrument = RWAInstrument(
            platform=platform,
            asset=asset,
            apy=apy,
            lockup_days=lockup_days,
            outstanding_principal=principal,
            risk_rating=risk_rating,
            last_update=datetime.utcnow(),
        )
        self._positions[f"{platform}:{asset}"] = instrument

    def list_instruments(self) -> List[RWAInstrument]:
        return list(self._positions.values())

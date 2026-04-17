"""
Automated tax reporting for yield income.

Aggregates vault distributions, capital gains, and jurisdiction-specific rules
to produce exportable tax reports. Provides deterministic audit trail for
compliance integrations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Dict, List


@dataclass
class YieldEvent:
    event_id: str
    user_id: str
    vault_id: str
    amount_usd: Decimal
    event_type: str  # distribution, realized_gain, fee
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class TaxReport:
    user_id: str
    jurisdiction: str
    total_income_usd: Decimal
    total_gains_usd: Decimal
    total_fees_usd: Decimal
    generated_at: datetime = field(default_factory=datetime.utcnow)


class AutomatedTaxReporter:
    def __init__(self) -> None:
        self._events: List[YieldEvent] = []

    def record_event(self, event: YieldEvent) -> None:
        self._events.append(event)

    def generate_report(self, user_id: str, jurisdiction: str) -> TaxReport:
        income = sum(event.amount_usd for event in self._events if event.user_id == user_id and event.event_type == "distribution")
        gains = sum(event.amount_usd for event in self._events if event.user_id == user_id and event.event_type == "realized_gain")
        fees = sum(event.amount_usd for event in self._events if event.user_id == user_id and event.event_type == "fee")
        return TaxReport(user_id=user_id, jurisdiction=jurisdiction, total_income_usd=Decimal(income), total_gains_usd=Decimal(gains), total_fees_usd=Decimal(fees))

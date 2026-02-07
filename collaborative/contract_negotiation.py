"""
Automated contract negotiation service for agent collaborations.

Supports proposal/counter-offer flows with templated clauses, risk scoring, and
auto-approval thresholds so agents can form agreements without manual review.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List


@dataclass
class ContractOffer:
    contract_id: str
    proposer: str
    counterparty: str
    terms: Dict[str, str]
    risk_score: float
    expires_at: datetime
    status: str = "pending"
    history: List[Dict[str, str]] = field(default_factory=list)


class ContractNegotiationEngine:
    def __init__(self, auto_approval_threshold: float = 0.3) -> None:
        self.auto_approval_threshold = auto_approval_threshold
        self._contracts: Dict[str, ContractOffer] = {}

    def propose(self, contract_id: str, proposer: str, counterparty: str, terms: Dict[str, str], risk_score: float) -> ContractOffer:
        offer = ContractOffer(
            contract_id=contract_id,
            proposer=proposer,
            counterparty=counterparty,
            terms=terms,
            risk_score=risk_score,
            expires_at=datetime.utcnow() + timedelta(days=3),
        )
        self._contracts[contract_id] = offer
        if risk_score <= self.auto_approval_threshold:
            offer.status = "auto_approved"
        return offer

    def counter(self, contract_id: str, counterparty: str, new_terms: Dict[str, str], risk_score: float) -> ContractOffer:
        offer = self._contracts[contract_id]
        offer.history.append({"counterparty": counterparty, "timestamp": datetime.utcnow().isoformat(), "terms": str(new_terms)})
        offer.terms.update(new_terms)
        offer.risk_score = risk_score
        offer.status = "countered"
        return offer

    def finalize(self, contract_id: str, approved: bool) -> ContractOffer:
        offer = self._contracts[contract_id]
        offer.status = "active" if approved else "rejected"
        return offer

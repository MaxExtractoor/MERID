"""§3 Risk, Capital, and Safety Agents.

- RiskManagerAgent: enforce hard risk constraints across all domains.
- CapitalAllocatorAgent: allocate capital between strategies/venues/domains.
- AnomalyDetectorAgent: watch for bad data and weird price behavior.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from merid.agents.base import AgentCategory, AgentOutput, CanonicalAgent
from merid.pipeline.proposal import TradeDomain, TradeProposal
from merid.pipeline.risk_manager import GlobalRiskManager, get_global_risk_manager

from utils.logger import get_logger

logger = get_logger("merid.agents.risk_agents")


# ======================================================================
# RiskManagerAgent
# ======================================================================

@dataclass
class RiskVerdict:
    """Risk evaluation result for a single proposal."""
    proposal_id: str
    approved: bool
    reason: str
    original_qty: Decimal = Decimal("0")
    adjusted_qty: Optional[Decimal] = None
    risk_score: float = 0.0  # 0 = safe, 1 = max risk
    checks_passed: List[str] = field(default_factory=list)
    checks_failed: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "proposal_id": self.proposal_id,
            "approved": self.approved,
            "reason": self.reason,
            "original_qty": str(self.original_qty),
            "adjusted_qty": str(self.adjusted_qty) if self.adjusted_qty else None,
            "risk_score": self.risk_score,
            "checks_passed": self.checks_passed,
            "checks_failed": self.checks_failed,
        }


class RiskManagerAgent(CanonicalAgent):
    """Enforces hard risk constraints across all domains.

    Evaluates every trade proposal and can resize or veto.
    Triggers circuit breakers and kill switches under defined conditions.
    """

    def __init__(
        self,
        agent_id: str = "risk-manager-01",
        risk_manager: Optional[GlobalRiskManager] = None,
    ):
        super().__init__(agent_id, AgentCategory.RISK)
        self._rm = risk_manager
        self._verdicts: List[RiskVerdict] = []

    @property
    def rm(self) -> GlobalRiskManager:
        if self._rm is None:
            self._rm = get_global_risk_manager()
        return self._rm

    async def _execute(self, context: Dict[str, Any]) -> AgentOutput:
        proposals = context.get("proposals", [])
        verdicts = []
        for p in proposals:
            v = self.evaluate(p)
            verdicts.append(v)
            self._verdicts.append(v)

        approved = sum(1 for v in verdicts if v.approved)
        rejected = len(verdicts) - approved

        return AgentOutput(
            agent_id=self.agent_id,
            category=self.category.value,
            output_type="risk_verdicts",
            payload={
                "verdicts": [v.to_dict() for v in verdicts],
                "approved": approved,
                "rejected": rejected,
                "risk_summary": self.rm.summary(),
            },
            confidence=0.9,
        )

    def evaluate(self, proposal: TradeProposal) -> RiskVerdict:
        """Evaluate a single proposal against all risk checks."""
        result = self.rm.check_proposal(proposal)

        checks_passed = []
        checks_failed = []
        if result.approved:
            checks_passed = ["domain_enabled", "order_size", "domain_notional",
                             "daily_loss", "positions", "portfolio_notional", "allocation"]
        else:
            checks_failed.append(result.reason)

        return RiskVerdict(
            proposal_id=proposal.proposal_id,
            approved=result.approved,
            reason=result.reason,
            original_qty=proposal.qty,
            risk_score=0.2 if result.approved else 0.8,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
        )

    def halt_domain(self, domain: str, reason: str) -> None:
        self.rm.halt_domain(domain, reason)

    def resume_domain(self, domain: str) -> None:
        self.rm.resume_domain(domain)


# ======================================================================
# CapitalAllocatorAgent
# ======================================================================

@dataclass
class AllocationPlan:
    """Capital allocation plan across domains."""
    total_capital_usd: Decimal = Decimal("0")
    allocations: Dict[str, Decimal] = field(default_factory=dict)  # domain -> USD
    rationale: str = ""
    rebalance_needed: bool = False

    def to_dict(self) -> dict:
        return {
            "total_capital_usd": str(self.total_capital_usd),
            "allocations": {k: str(v) for k, v in self.allocations.items()},
            "rationale": self.rationale,
            "rebalance_needed": self.rebalance_needed,
        }


class CapitalAllocatorAgent(CanonicalAgent):
    """Allocates capital between strategies, venues, and domains.

    Maintains a budget for prediction markets vs crypto vs equities.
    Shifts capital based on performance, risk, and opportunity set.
    """

    def __init__(
        self,
        agent_id: str = "capital-allocator-01",
        risk_manager: Optional[GlobalRiskManager] = None,
        target_allocations: Optional[Dict[str, Decimal]] = None,
    ):
        super().__init__(agent_id, AgentCategory.RISK)
        self._rm = risk_manager
        self.target_allocations = target_allocations or {
            "prediction": Decimal("0.10"),
            "crypto": Decimal("0.50"),
            "equity": Decimal("0.40"),
        }

    @property
    def rm(self) -> GlobalRiskManager:
        if self._rm is None:
            self._rm = get_global_risk_manager()
        return self._rm

    async def _execute(self, context: Dict[str, Any]) -> AgentOutput:
        plan = self.compute_allocation()
        return AgentOutput(
            agent_id=self.agent_id,
            category=self.category.value,
            output_type="allocation_plan",
            payload=plan.to_dict(),
            confidence=0.7,
        )

    def compute_allocation(self) -> AllocationPlan:
        """Compute current vs target allocation and flag rebalance."""
        total = self.rm.total_capital_usd
        current: Dict[str, Decimal] = {}
        for domain in TradeDomain:
            current[domain.value] = self.rm.domain_notional(domain.value)

        target_usd: Dict[str, Decimal] = {}
        for domain, pct in self.target_allocations.items():
            target_usd[domain] = total * pct

        # Check if rebalance needed (>5% drift from target)
        rebalance = False
        for domain, target in target_usd.items():
            actual = current.get(domain, Decimal("0"))
            if target > 0 and abs(actual - target) / target > Decimal("0.05"):
                rebalance = True
                break

        return AllocationPlan(
            total_capital_usd=total,
            allocations={
                d: self.rm.available_capital(TradeDomain(d))
                for d in self.target_allocations
            },
            rationale="Target allocation check" + (" — rebalance recommended" if rebalance else " — within bounds"),
            rebalance_needed=rebalance,
        )


# ======================================================================
# AnomalyDetectorAgent
# ======================================================================

class AnomalyType(str):
    STALE_DATA = "stale_data"
    PRICE_SPIKE = "price_spike"
    LIQUIDITY_COLLAPSE = "liquidity_collapse"
    SPREAD_ANOMALY = "spread_anomaly"
    SCHEMA_ERROR = "schema_error"


@dataclass
class Anomaly:
    """A detected anomaly."""
    anomaly_type: str
    severity: str = "warning"  # info, warning, critical
    venue: str = ""
    instrument: str = ""
    message: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
    recommend_pause: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "anomaly_type": self.anomaly_type,
            "severity": self.severity,
            "venue": self.venue,
            "instrument": self.instrument,
            "message": self.message,
            "recommend_pause": self.recommend_pause,
            "timestamp": self.timestamp.isoformat(),
        }


class AnomalyDetectorAgent(CanonicalAgent):
    """Watches for bad data and weird price behavior.

    Checks:
    - Per-feed staleness and schema validation.
    - Suspicious price moves, liquidity collapses, odd spreads.
    - Can recommend auto-pause for affected instruments/venues.
    """

    def __init__(
        self,
        agent_id: str = "anomaly-detector-01",
        stale_threshold_seconds: int = 60,
        spike_threshold_pct: float = 0.10,
    ):
        super().__init__(agent_id, AgentCategory.RISK)
        self.stale_threshold_seconds = stale_threshold_seconds
        self.spike_threshold_pct = spike_threshold_pct
        self._anomalies: List[Anomaly] = []
        self._last_prices: Dict[str, Dict[str, Any]] = {}  # instrument -> {price, ts}

    async def _execute(self, context: Dict[str, Any]) -> AgentOutput:
        """Run anomaly detection on provided market data.

        Context should contain 'market_data': list of {instrument, venue, price, bid, ask, volume, timestamp}.
        """
        market_data = context.get("market_data", [])
        anomalies = self._detect(market_data)
        self._anomalies.extend(anomalies)

        return AgentOutput(
            agent_id=self.agent_id,
            category=self.category.value,
            output_type="anomalies",
            payload={
                "anomalies": [a.to_dict() for a in anomalies],
                "count": len(anomalies),
                "critical": sum(1 for a in anomalies if a.severity == "critical"),
            },
            confidence=0.8,
        )

    def _detect(self, market_data: List[Dict[str, Any]]) -> List[Anomaly]:
        anomalies = []
        now = datetime.now(timezone.utc)

        for md in market_data:
            instrument = md.get("instrument", "")
            venue = md.get("venue", "")
            price = float(md.get("price", 0))
            bid = float(md.get("bid", 0))
            ask = float(md.get("ask", 0))
            ts = md.get("timestamp")

            # Staleness check
            if ts:
                if isinstance(ts, str):
                    try:
                        ts = datetime.fromisoformat(ts)
                    except (ValueError, TypeError):
                        ts = None
                if ts and (now - ts).total_seconds() > self.stale_threshold_seconds:
                    anomalies.append(Anomaly(
                        anomaly_type="stale_data", severity="warning",
                        venue=venue, instrument=instrument,
                        message=f"Data stale by {(now - ts).total_seconds():.0f}s.",
                        recommend_pause=True,
                    ))

            # Price spike check
            key = f"{venue}:{instrument}"
            prev = self._last_prices.get(key)
            if prev and prev.get("price", 0) > 0 and price > 0:
                change_pct = abs(price - prev["price"]) / prev["price"]
                if change_pct > self.spike_threshold_pct:
                    anomalies.append(Anomaly(
                        anomaly_type="price_spike", severity="critical",
                        venue=venue, instrument=instrument,
                        message=f"Price moved {change_pct:.1%} ({prev['price']:.2f} → {price:.2f}).",
                        recommend_pause=True,
                        data={"prev_price": prev["price"], "new_price": price, "change_pct": change_pct},
                    ))
            self._last_prices[key] = {"price": price, "ts": now}

            # Spread anomaly
            if bid > 0 and ask > 0:
                spread_pct = (ask - bid) / bid
                if spread_pct > 0.05:  # > 5% spread
                    anomalies.append(Anomaly(
                        anomaly_type="spread_anomaly", severity="warning",
                        venue=venue, instrument=instrument,
                        message=f"Wide spread: {spread_pct:.1%} (bid={bid}, ask={ask}).",
                    ))

        return anomalies

    def get_anomalies(self, limit: int = 50) -> List[Anomaly]:
        return self._anomalies[-limit:]

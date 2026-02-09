"""Flow domain risk management — budgets, safety gates, auto-throttle.

Enforces:
  - Max % NAV in memecoin domain
  - Max per-token exposure
  - Max per-whale/KOL dependence
  - Safety gates: environment, MEV routing health, swarm quality
  - Auto-throttle on degraded Brier scores / PnL
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from merid.flow.models import PlanStatus, _now


# ── Configuration ─────────────────────────────────────────────────────

@dataclass
class FlowRiskConfig:
    """Risk budget configuration for the flow domain."""
    # Portfolio-level
    max_nav_pct: float = 0.05  # max 5% of NAV in flow domain
    max_domain_notional_usd: float = 2500.0
    max_daily_loss_usd: float = 500.0

    # Per-token
    max_per_token_usd: float = 200.0
    max_per_token_pct: float = 0.02  # 2% of NAV

    # Per-entity dependence
    max_per_whale_exposure_pct: float = 0.30  # no single whale drives > 30% of flow positions
    max_per_kol_exposure_pct: float = 0.20

    # Plan limits
    max_concurrent_plans: int = 10
    max_meme_plans_active: int = 5
    max_whale_plans_active: int = 3
    max_kol_plans_active: int = 3

    # Quality gates
    min_swarm_confidence: float = 0.40  # minimum avg confidence to allow new plans
    min_domain_hit_rate: float = 0.35  # minimum hit rate before throttle kicks in
    min_flow_score: float = 30.0  # minimum flow score for a token to allow plans

    # Auto-throttle
    throttle_loss_trigger_usd: float = 300.0  # start throttling after this much daily loss
    throttle_size_reduction: float = 0.50  # reduce sizes by 50% when throttled
    halt_loss_trigger_usd: float = 500.0  # halt domain at this daily loss


@dataclass
class FlowRiskState:
    """Mutable runtime state for risk tracking."""
    domain_exposure_usd: float = 0.0
    daily_pnl_usd: float = 0.0
    daily_loss_usd: float = 0.0  # absolute loss today (positive number)
    is_throttled: bool = False
    is_halted: bool = False
    halt_reason: str = ""
    active_plan_count: int = 0
    per_token_exposure: Dict[str, float] = field(default_factory=dict)
    per_entity_exposure: Dict[str, float] = field(default_factory=dict)
    last_check_at: float = field(default_factory=_now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain_exposure_usd": round(self.domain_exposure_usd, 2),
            "daily_pnl_usd": round(self.daily_pnl_usd, 2),
            "daily_loss_usd": round(self.daily_loss_usd, 2),
            "is_throttled": self.is_throttled,
            "is_halted": self.is_halted,
            "halt_reason": self.halt_reason,
            "active_plan_count": self.active_plan_count,
            "per_token_count": len(self.per_token_exposure),
            "per_entity_count": len(self.per_entity_exposure),
        }


# ── Risk check result ─────────────────────────────────────────────────

@dataclass
class RiskCheckResult:
    """Result of a risk check for a proposed plan."""
    allowed: bool = True
    reason: str = ""
    adjusted_size_usd: float = 0.0  # may be reduced from requested size
    warnings: List[str] = field(default_factory=list)


# ── FlowDomainRisk ────────────────────────────────────────────────────

class FlowDomainRisk:
    """Risk manager for the flow domain.

    Checks:
      1. Domain halted?
      2. Environment check (live requires MERID_FLOW_LIVE)
      3. MEV routing health
      4. Domain notional limit
      5. Daily loss limit
      6. Per-token exposure limit
      7. Per-entity dependence limit
      8. Concurrent plan limit
      9. Swarm quality gates (confidence, hit rate)
      10. Flow score minimum
    """

    def __init__(self, config: Optional[FlowRiskConfig] = None):
        self.config = config or FlowRiskConfig()
        self.state = FlowRiskState()
        self._nav_usd = float(os.environ.get("MERID_TOTAL_CAPITAL_USD", "50000"))

    @property
    def max_domain_usd(self) -> float:
        return min(self.config.max_domain_notional_usd, self._nav_usd * self.config.max_nav_pct)

    def check_plan(
        self,
        plan_type: str,
        token_id: str,
        entity_id: str,
        size_usd: float,
        flow_score: float = 50.0,
        avg_confidence: float = 0.5,
        domain_hit_rate: float = 0.5,
        mev_routes_healthy: bool = True,
    ) -> RiskCheckResult:
        """Run all risk checks for a proposed plan.

        Returns RiskCheckResult with allowed/denied + adjusted size.
        """
        warnings: List[str] = []

        # 1. Domain halted
        if self.state.is_halted:
            return RiskCheckResult(
                allowed=False,
                reason=f"Flow domain halted: {self.state.halt_reason}",
            )

        # 2. Environment
        is_live = os.environ.get("MERID_FLOW_LIVE", "").lower() in ("1", "true", "yes")
        env = os.environ.get("MERID_ENV", "dev")
        if is_live and env == "dev":
            return RiskCheckResult(
                allowed=False,
                reason="Live trading not allowed in dev environment",
            )

        # 3. MEV routing health
        if not mev_routes_healthy:
            warnings.append("MEV-protected routing is unhealthy")
            # Only block if low MEV tolerance plans
            if plan_type == "meme":
                return RiskCheckResult(
                    allowed=False,
                    reason="MEV routing unhealthy — meme plans blocked",
                )

        # 4. Domain notional
        if self.state.domain_exposure_usd + size_usd > self.max_domain_usd:
            return RiskCheckResult(
                allowed=False,
                reason=f"Domain exposure ${self.state.domain_exposure_usd + size_usd:,.0f} exceeds limit ${self.max_domain_usd:,.0f}",
            )

        # 5. Daily loss
        if self.state.daily_loss_usd >= self.config.halt_loss_trigger_usd:
            self.state.is_halted = True
            self.state.halt_reason = f"Daily loss ${self.state.daily_loss_usd:,.0f} hit halt trigger"
            return RiskCheckResult(
                allowed=False,
                reason=self.state.halt_reason,
            )

        # 6. Per-token exposure
        token_exposure = self.state.per_token_exposure.get(token_id, 0.0)
        if token_exposure + size_usd > self.config.max_per_token_usd:
            return RiskCheckResult(
                allowed=False,
                reason=f"Per-token exposure ${token_exposure + size_usd:,.0f} exceeds ${self.config.max_per_token_usd:,.0f}",
            )

        # 7. Per-entity dependence
        if entity_id:
            entity_exposure = self.state.per_entity_exposure.get(entity_id, 0.0)
            entity_pct = (entity_exposure + size_usd) / max(self.state.domain_exposure_usd + size_usd, 1)
            max_pct = (
                self.config.max_per_whale_exposure_pct if plan_type == "whale"
                else self.config.max_per_kol_exposure_pct
            )
            if entity_pct > max_pct:
                return RiskCheckResult(
                    allowed=False,
                    reason=f"Entity dependence {entity_pct:.0%} exceeds {max_pct:.0%}",
                )

        # 8. Concurrent plans
        plan_limits = {
            "meme": self.config.max_meme_plans_active,
            "whale": self.config.max_whale_plans_active,
            "kol": self.config.max_kol_plans_active,
        }
        if self.state.active_plan_count >= self.config.max_concurrent_plans:
            return RiskCheckResult(
                allowed=False,
                reason=f"Max concurrent plans ({self.config.max_concurrent_plans}) reached",
            )

        # 9. Swarm quality gates
        if avg_confidence < self.config.min_swarm_confidence:
            warnings.append(f"Low swarm confidence: {avg_confidence:.2f}")

        if domain_hit_rate < self.config.min_domain_hit_rate:
            return RiskCheckResult(
                allowed=False,
                reason=f"Domain hit rate {domain_hit_rate:.0%} below minimum {self.config.min_domain_hit_rate:.0%}",
            )

        # 10. Flow score minimum
        if flow_score < self.config.min_flow_score:
            return RiskCheckResult(
                allowed=False,
                reason=f"Flow score {flow_score:.0f} below minimum {self.config.min_flow_score:.0f}",
            )

        # Auto-throttle: reduce size if approaching loss trigger
        adjusted_size = size_usd
        if self.state.daily_loss_usd >= self.config.throttle_loss_trigger_usd:
            self.state.is_throttled = True
            adjusted_size = size_usd * self.config.throttle_size_reduction
            warnings.append(
                f"Throttled: daily loss ${self.state.daily_loss_usd:,.0f} "
                f"≥ trigger ${self.config.throttle_loss_trigger_usd:,.0f}, "
                f"size reduced to ${adjusted_size:,.0f}"
            )

        self.state.last_check_at = _now()
        return RiskCheckResult(
            allowed=True,
            adjusted_size_usd=adjusted_size,
            warnings=warnings,
        )

    def record_fill(self, token_id: str, entity_id: str, size_usd: float, pnl_usd: float = 0.0):
        """Record a fill for risk tracking."""
        self.state.domain_exposure_usd += size_usd
        self.state.per_token_exposure[token_id] = (
            self.state.per_token_exposure.get(token_id, 0.0) + size_usd
        )
        if entity_id:
            self.state.per_entity_exposure[entity_id] = (
                self.state.per_entity_exposure.get(entity_id, 0.0) + size_usd
            )
        self.state.active_plan_count += 1

    def record_exit(self, token_id: str, entity_id: str, size_usd: float, pnl_usd: float):
        """Record a position exit."""
        self.state.domain_exposure_usd = max(0, self.state.domain_exposure_usd - size_usd)
        self.state.per_token_exposure[token_id] = max(
            0, self.state.per_token_exposure.get(token_id, 0) - size_usd
        )
        if entity_id:
            self.state.per_entity_exposure[entity_id] = max(
                0, self.state.per_entity_exposure.get(entity_id, 0) - size_usd
            )
        self.state.active_plan_count = max(0, self.state.active_plan_count - 1)
        self.state.daily_pnl_usd += pnl_usd
        if pnl_usd < 0:
            self.state.daily_loss_usd += abs(pnl_usd)

        # Check auto-halt
        if self.state.daily_loss_usd >= self.config.halt_loss_trigger_usd:
            self.state.is_halted = True
            self.state.halt_reason = f"Daily loss ${self.state.daily_loss_usd:,.0f} hit halt trigger"

        # Check throttle
        if self.state.daily_loss_usd >= self.config.throttle_loss_trigger_usd:
            self.state.is_throttled = True

    def reset_daily(self):
        """Reset daily counters (call at start of trading day)."""
        self.state.daily_pnl_usd = 0.0
        self.state.daily_loss_usd = 0.0
        self.state.is_throttled = False
        if self.state.is_halted and "daily loss" in self.state.halt_reason.lower():
            self.state.is_halted = False
            self.state.halt_reason = ""

    def resume(self):
        """Manually resume a halted domain."""
        self.state.is_halted = False
        self.state.halt_reason = ""
        self.state.is_throttled = False

    def get_status(self) -> Dict[str, Any]:
        """Return current risk status."""
        return {
            "config": {
                "max_nav_pct": self.config.max_nav_pct,
                "max_domain_notional_usd": self.config.max_domain_notional_usd,
                "max_daily_loss_usd": self.config.max_daily_loss_usd,
                "max_per_token_usd": self.config.max_per_token_usd,
                "max_concurrent_plans": self.config.max_concurrent_plans,
            },
            "state": self.state.to_dict(),
            "nav_usd": self._nav_usd,
            "effective_max_domain_usd": self.max_domain_usd,
            "utilization_pct": round(
                self.state.domain_exposure_usd / max(self.max_domain_usd, 1) * 100, 1
            ),
        }


# ── Singleton ─────────────────────────────────────────────────────────

_flow_risk: Optional[FlowDomainRisk] = None


def get_flow_risk() -> FlowDomainRisk:
    global _flow_risk
    if _flow_risk is None:
        _flow_risk = FlowDomainRisk()
    return _flow_risk

"""
Analytics dashboard for agent performance, drift, governance, and cost metrics.

Provides regime-segmented analytics, drift detection summaries, governance
audit trails, and cost tracking across the trading swarm.
"""

import logging
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict
import numpy as np

from core.info_theory_metrics import get_info_theory_metrics
from core.telemetry_manager import get_telemetry_manager
from observability.observability_stack import get_observability_stack

logger = logging.getLogger(__name__)


@dataclass
class RegimeSegmentedMetrics:
    """Performance metrics segmented by market regime."""
    regime: str
    sample_count: int
    avg_pnl: float
    avg_sharpe: float
    avg_drawdown: float
    win_rate: float
    avg_entropy: float
    avg_kl_divergence: float
    time_in_regime_hours: float


@dataclass
class DriftSummary:
    """Drift detection summary."""
    component: str
    total_checks: int
    breach_count: int
    breach_rate: float
    avg_kl_divergence: float
    max_kl_divergence: float
    last_breach: Optional[datetime]
    status: str


@dataclass
class GovernanceAuditEntry:
    """Governance action audit entry."""
    timestamp: datetime
    action_type: str
    target: str
    parameters: Dict[str, Any]
    approver: str
    reason: str
    impact: str


@dataclass
class CostMetrics:
    """Cost tracking metrics."""
    period_start: datetime
    period_end: datetime
    llm_api_calls: int
    llm_cost_usd: float
    data_feed_cost_usd: float
    exchange_fees_usd: float
    infrastructure_cost_usd: float
    total_cost_usd: float
    pnl_usd: float
    cost_to_pnl_ratio: float


class AnalyticsDashboard:
    """
    Analytics dashboard for MERID trading swarm.
    
    Provides:
    - Regime-segmented performance analytics
    - Drift detection summaries
    - Governance audit trails
    - Cost tracking and efficiency metrics
    - Agent performance comparisons
    """
    
    def __init__(self):
        self.info_metrics = get_info_theory_metrics()
        self.telemetry = get_telemetry_manager()
        self.observability = get_observability_stack()
        
        self._regime_metrics: Dict[str, List[RegimeSegmentedMetrics]] = defaultdict(list)
        self._governance_audit: List[GovernanceAuditEntry] = []
        self._cost_history: List[CostMetrics] = []
    
    def compute_regime_segmented_performance(
        self,
        strategy_id: str,
        since: Optional[datetime] = None,
    ) -> List[RegimeSegmentedMetrics]:
        """
        Compute performance metrics segmented by market regime.
        
        Args:
            strategy_id: Strategy to analyze
            since: Optional start time
            
        Returns:
            List of RegimeSegmentedMetrics per regime
        """
        if since is None:
            since = datetime.utcnow() - timedelta(days=30)
        
        trading_metrics = self.observability.get_trading_metrics(
            strategy_id=strategy_id,
            since=since,
        )
        
        drift_metrics = self.observability.get_drift_metrics(
            component=strategy_id,
            since=since,
        )
        
        logs = self.telemetry.get_logs(
            agent_id=strategy_id,
            since=since,
            limit=10000,
        )
        
        regime_data = defaultdict(lambda: {
            "pnls": [],
            "sharpes": [],
            "drawdowns": [],
            "wins": 0,
            "total": 0,
            "entropies": [],
            "kl_divergences": [],
            "timestamps": [],
        })
        
        for log in logs:
            if log.regime_tags:
                regime = log.regime_tags[0]
                regime_data[regime]["timestamps"].append(log.timestamp)
                
                if "entropy" in log.fields:
                    regime_data[regime]["entropies"].append(log.fields["entropy"])
                
                if "kl_divergence" in log.fields and log.fields["kl_divergence"] is not None:
                    regime_data[regime]["kl_divergences"].append(log.fields["kl_divergence"])
        
        for metric in trading_metrics:
            regime = "unknown"
            for log in logs:
                if abs((log.timestamp - metric.timestamp).total_seconds()) < 60:
                    if log.regime_tags:
                        regime = log.regime_tags[0]
                        break
            
            regime_data[regime]["pnls"].append(metric.pnl)
            regime_data[regime]["sharpes"].append(metric.sharpe_ratio)
            regime_data[regime]["drawdowns"].append(metric.max_drawdown)
            regime_data[regime]["total"] += 1
            if metric.pnl > 0:
                regime_data[regime]["wins"] += 1
        
        results = []
        for regime, data in regime_data.items():
            if data["total"] == 0:
                continue
            
            time_in_regime = 0.0
            if data["timestamps"]:
                time_in_regime = (
                    max(data["timestamps"]) - min(data["timestamps"])
                ).total_seconds() / 3600.0
            
            results.append(RegimeSegmentedMetrics(
                regime=regime,
                sample_count=data["total"],
                avg_pnl=float(np.mean(data["pnls"])) if data["pnls"] else 0.0,
                avg_sharpe=float(np.mean(data["sharpes"])) if data["sharpes"] else 0.0,
                avg_drawdown=float(np.mean(data["drawdowns"])) if data["drawdowns"] else 0.0,
                win_rate=data["wins"] / data["total"] if data["total"] > 0 else 0.0,
                avg_entropy=float(np.mean(data["entropies"])) if data["entropies"] else 0.0,
                avg_kl_divergence=float(np.mean(data["kl_divergences"])) if data["kl_divergences"] else 0.0,
                time_in_regime_hours=time_in_regime,
            ))
        
        results.sort(key=lambda x: x.sample_count, reverse=True)
        
        return results
    
    def get_drift_summary(
        self,
        component: Optional[str] = None,
    ) -> List[DriftSummary]:
        """
        Get drift detection summary across components.
        
        Args:
            component: Optional component filter
            
        Returns:
            List of DriftSummary
        """
        drift_info = self.info_metrics.get_drift_summary()
        
        summaries = []
        for baseline_name, stats in drift_info.get("baselines", {}).items():
            if component and not baseline_name.startswith(component):
                continue
            
            checks = stats.get("checks_performed", 0)
            breaches = stats.get("recent_breaches", 0)
            
            status = "healthy"
            if breaches > 5:
                status = "critical"
            elif breaches > 2:
                status = "warning"
            
            last_breach = None
            if stats.get("last_check"):
                try:
                    last_breach = datetime.fromisoformat(stats["last_check"])
                except:
                    pass
            
            summaries.append(DriftSummary(
                component=baseline_name,
                total_checks=checks,
                breach_count=breaches,
                breach_rate=breaches / checks if checks > 0 else 0.0,
                avg_kl_divergence=stats.get("recent_avg_kl", 0.0),
                max_kl_divergence=stats.get("recent_max_kl", 0.0),
                last_breach=last_breach,
                status=status,
            ))
        
        summaries.sort(key=lambda x: x.breach_rate, reverse=True)
        
        return summaries
    
    def record_governance_action(
        self,
        action_type: str,
        target: str,
        parameters: Dict[str, Any],
        approver: str,
        reason: str,
        impact: str,
    ) -> GovernanceAuditEntry:
        """Record a governance action for audit trail."""
        entry = GovernanceAuditEntry(
            timestamp=datetime.utcnow(),
            action_type=action_type,
            target=target,
            parameters=parameters,
            approver=approver,
            reason=reason,
            impact=impact,
        )
        
        self._governance_audit.append(entry)
        
        self.observability.log_governance_action(
            action_type=action_type,
            target=target,
            parameters=parameters,
            approver=approver,
        )
        
        logger.info(f"Governance action recorded: {action_type} on {target} by {approver}")
        
        return entry
    
    def get_governance_audit_trail(
        self,
        action_type: Optional[str] = None,
        target: Optional[str] = None,
        since: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[GovernanceAuditEntry]:
        """Query governance audit trail."""
        entries = self._governance_audit
        
        if action_type:
            entries = [e for e in entries if e.action_type == action_type]
        
        if target:
            entries = [e for e in entries if e.target == target]
        
        if since:
            entries = [e for e in entries if e.timestamp >= since]
        
        return entries[-limit:]
    
    def record_cost_metrics(
        self,
        period_start: datetime,
        period_end: datetime,
        llm_api_calls: int,
        llm_cost_usd: float,
        data_feed_cost_usd: float,
        exchange_fees_usd: float,
        infrastructure_cost_usd: float,
        pnl_usd: float,
    ) -> CostMetrics:
        """Record cost metrics for a period."""
        total_cost = (
            llm_cost_usd +
            data_feed_cost_usd +
            exchange_fees_usd +
            infrastructure_cost_usd
        )
        
        cost_to_pnl = total_cost / pnl_usd if pnl_usd != 0 else float('inf')
        
        metrics = CostMetrics(
            period_start=period_start,
            period_end=period_end,
            llm_api_calls=llm_api_calls,
            llm_cost_usd=llm_cost_usd,
            data_feed_cost_usd=data_feed_cost_usd,
            exchange_fees_usd=exchange_fees_usd,
            infrastructure_cost_usd=infrastructure_cost_usd,
            total_cost_usd=total_cost,
            pnl_usd=pnl_usd,
            cost_to_pnl_ratio=cost_to_pnl,
        )
        
        self._cost_history.append(metrics)
        
        logger.info(
            f"Cost metrics recorded: ${total_cost:.2f} total, "
            f"${pnl_usd:.2f} PnL, ratio={cost_to_pnl:.4f}"
        )
        
        return metrics
    
    def get_cost_summary(
        self,
        since: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Get cost summary."""
        if since is None:
            since = datetime.utcnow() - timedelta(days=30)
        
        recent_costs = [
            c for c in self._cost_history
            if c.period_end >= since
        ]
        
        if not recent_costs:
            return {
                "total_cost_usd": 0.0,
                "total_pnl_usd": 0.0,
                "avg_cost_to_pnl_ratio": 0.0,
                "breakdown": {},
            }
        
        total_llm = sum(c.llm_cost_usd for c in recent_costs)
        total_data = sum(c.data_feed_cost_usd for c in recent_costs)
        total_exchange = sum(c.exchange_fees_usd for c in recent_costs)
        total_infra = sum(c.infrastructure_cost_usd for c in recent_costs)
        total_cost = sum(c.total_cost_usd for c in recent_costs)
        total_pnl = sum(c.pnl_usd for c in recent_costs)
        
        avg_ratio = np.mean([c.cost_to_pnl_ratio for c in recent_costs if c.cost_to_pnl_ratio != float('inf')])
        
        return {
            "total_cost_usd": float(total_cost),
            "total_pnl_usd": float(total_pnl),
            "avg_cost_to_pnl_ratio": float(avg_ratio) if not np.isnan(avg_ratio) else 0.0,
            "breakdown": {
                "llm_cost_usd": float(total_llm),
                "data_feed_cost_usd": float(total_data),
                "exchange_fees_usd": float(total_exchange),
                "infrastructure_cost_usd": float(total_infra),
            },
            "period_count": len(recent_costs),
        }
    
    def compare_agent_performance(
        self,
        agent_ids: List[str],
        since: Optional[datetime] = None,
    ) -> Dict[str, Dict[str, Any]]:
        """Compare performance across multiple agents."""
        if since is None:
            since = datetime.utcnow() - timedelta(days=7)
        
        comparison = {}
        
        for agent_id in agent_ids:
            metrics = self.observability.get_trading_metrics(
                strategy_id=agent_id,
                since=since,
            )
            
            if not metrics:
                comparison[agent_id] = {
                    "status": "no_data",
                }
                continue
            
            pnls = [m.pnl for m in metrics]
            sharpes = [m.sharpe_ratio for m in metrics]
            drawdowns = [m.max_drawdown for m in metrics]
            
            comparison[agent_id] = {
                "status": "active",
                "sample_count": len(metrics),
                "total_pnl": float(sum(pnls)),
                "avg_sharpe": float(np.mean(sharpes)),
                "max_drawdown": float(max(drawdowns)),
                "win_rate": float(sum(1 for p in pnls if p > 0) / len(pnls)),
            }
        
        return comparison
    
    def get_dashboard_summary(self) -> Dict[str, Any]:
        """Get comprehensive dashboard summary."""
        return {
            "drift_summary": [
                {
                    "component": s.component,
                    "status": s.status,
                    "breach_rate": s.breach_rate,
                    "avg_kl": s.avg_kl_divergence,
                }
                for s in self.get_drift_summary()[:10]
            ],
            "governance_actions": len(self._governance_audit),
            "recent_governance": [
                {
                    "timestamp": e.timestamp.isoformat(),
                    "action": e.action_type,
                    "target": e.target,
                    "approver": e.approver,
                }
                for e in self._governance_audit[-10:]
            ],
            "cost_summary": self.get_cost_summary(),
            "observability": self.observability.get_observability_summary(),
        }


_analytics_dashboard: Optional[AnalyticsDashboard] = None


def get_analytics_dashboard() -> AnalyticsDashboard:
    """Get global AnalyticsDashboard instance."""
    global _analytics_dashboard
    if _analytics_dashboard is None:
        _analytics_dashboard = AnalyticsDashboard()
    return _analytics_dashboard

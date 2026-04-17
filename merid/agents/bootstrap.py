"""Bootstrap canonical agents into the registry.

Registers all wired agents (research, strategy, risk, coordination, ops)
into the CanonicalAgentRegistry for orchestrator use.
"""

from merid.agents.base import get_canonical_registry
from merid.agents.wiring import WiredPredictionMarketAgent
from merid.agents.strategy import StrategyDesignerAgent
from merid.agents.risk_agents import (
    RiskManagerAgent,
    CapitalAllocatorAgent,
    AnomalyDetectorAgent,
)
from merid.agents.coordination import (
    ConsensusCoordinatorAgent,
    ExplainabilityAgent,
    DebateCoordinatorAgent,
    GovernanceAgent,
)
from merid.agents.ops import OpsRunbookAgent, BacktestAgent

from utils.logger import get_logger

logger = get_logger("merid.agents.bootstrap")


def bootstrap_canonical_agents() -> int:
    """Register all canonical agents into the global registry."""
    registry = get_canonical_registry()

    _specs = [
        # (label, factory)
        ("PredictionMarketAgent",    lambda: WiredPredictionMarketAgent(agent_id="pm-research-live")),
        ("StrategyDesignerAgent",    lambda: StrategyDesignerAgent(agent_id="strategy-designer")),
        ("RiskManagerAgent",         lambda: RiskManagerAgent(agent_id="risk-manager")),
        ("CapitalAllocatorAgent",    lambda: CapitalAllocatorAgent(agent_id="capital-allocator")),
        ("AnomalyDetectorAgent",     lambda: AnomalyDetectorAgent(agent_id="anomaly-detector")),
        ("ConsensusCoordinatorAgent",lambda: ConsensusCoordinatorAgent(agent_id="consensus-coordinator")),
        ("ExplainabilityAgent",      lambda: ExplainabilityAgent(agent_id="explainability")),
        ("DebateCoordinatorAgent",   lambda: DebateCoordinatorAgent(agent_id="debate-coordinator")),
        ("GovernanceAgent",          lambda: GovernanceAgent(agent_id="governance")),
        ("OpsRunbookAgent",          lambda: OpsRunbookAgent(agent_id="ops-runbook")),
        ("BacktestAgent",            lambda: BacktestAgent(agent_id="backtest")),
    ]

    failed: list[str] = []
    for label, factory in _specs:
        try:
            agent = factory()
            # BUG-m4 fix: newly registered agents start inactive.
            # An explicit enable() call or operator action is required
            # before the agent participates in any trading loop.
            if hasattr(agent, "is_active"):
                agent.is_active = False
            registry.register(agent)
        except Exception as e:
            logger.warning("Failed to register %s: %s", label, e)
            failed.append(label)

    agent_count = registry.count()
    if failed:
        logger.warning(
            "bootstrap_canonical_agents: %d/%d agents failed to register: %s",
            len(failed), len(_specs), ", ".join(failed),
        )
    logger.info("✅ Bootstrapped %d canonical agents into registry", agent_count)
    return agent_count


_bootstrapped = False


def ensure_bootstrapped() -> int:
    """Ensure agents are bootstrapped (idempotent).

    Must be called **explicitly** by application startup code.  This function
    is intentionally NOT called at module import time (BUG-m4 fix) so that
    importing from this module does not silently register agents and trigger
    paper trading before any operator action.
    """
    global _bootstrapped
    if not _bootstrapped:
        count = bootstrap_canonical_agents()
        _bootstrapped = True
        return count
    return get_canonical_registry().count()

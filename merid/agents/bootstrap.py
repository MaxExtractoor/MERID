"""Bootstrap canonical agents into the registry.

LEAN 15m KALSHI STACK (2026-05-13): Pruned for BTC/ETH/SOL/XRP/DOGE trading.
Only core agents: PredictionMarketAgent, StrategyDesignerAgent, RiskManagerAgent, CapitalAllocatorAgent, AnomalyDetectorAgent.
Deleted agents (moved to legacy/): ConsensusCoordinatorAgent, ExplainabilityAgent, DebateCoordinatorAgent, GovernanceAgent, OpsRunbookAgent.
"""

from merid.agents.base import get_canonical_registry
from merid.agents.wiring import WiredPredictionMarketAgent

# Optional imports - make them try/except to handle missing modules
try:
    from merid.agents.strategy import StrategyDesignerAgent
except ImportError:
    StrategyDesignerAgent = None

try:
    from merid.agents.risk_agents import (
        RiskManagerAgent,
        CapitalAllocatorAgent,
        AnomalyDetectorAgent,
    )
except ImportError:
    RiskManagerAgent = None
    CapitalAllocatorAgent = None
    AnomalyDetectorAgent = None

# BacktestAgent kept as CLI/offline tool - optional import
try:
    from merid.agents.ops import BacktestAgent
except ImportError:
    BacktestAgent = None

from utils.logger import get_logger

logger = get_logger("merid.agents.bootstrap")


def bootstrap_canonical_agents() -> int:
    """Register all canonical agents into the global registry."""
    registry = get_canonical_registry()
    
    # PRODUCTION DATA GUARDS (2026-05-14): Type assertions for catalog and execution backend
    from merid.settings import settings as _settings
    env = _settings.MERID_ENV if hasattr(_settings, 'MERID_ENV') else "development"
    pm_profile = _settings.MERID_PM_PROFILE if hasattr(_settings, 'MERID_PM_PROFILE') else "baseline"
    is_production = env == "production" or pm_profile == "production"
    
    if is_production:
        # Assert registry is the real CanonicalAgentRegistry, not a mock
        from merid.agents.base import CanonicalAgentRegistry
        if not isinstance(registry, CanonicalAgentRegistry):
            raise RuntimeError(
                f"PRODUCTION_WIRING_VIOLATION: Registry is not a CanonicalAgentRegistry "
                f"(got {type(registry).__name__}). Mock/fake registries not allowed in production."
            )
        logger.info("[PRODUCTION_WIRING] Registry type validated: CanonicalAgentRegistry")
    
    # Check if research agents are enabled
    _enable_research = _settings.MERID_ENABLE_RESEARCH_AGENTS
    
    if not _enable_research:
        logger.info(
            "[BOOTSTRAP] MERID_ENABLE_RESEARCH_AGENTS=False - skipping WiredPredictionMarketAgent (legacy research agent). "
            "Set MERID_ENABLE_RESEARCH_AGENTS=True in .env to enable."
        )

    _specs = [
        # LEAN 15m KALSHI STACK (2026-05-13): Core agents only
        # WiredPredictionMarketAgent is legacy research - gated behind MERID_ENABLE_RESEARCH_AGENTS
        ("PredictionMarketAgent",    lambda: WiredPredictionMarketAgent(agent_id="pm-research-live"), _enable_research),
    ]
    
    # Add optional agents if they exist
    if StrategyDesignerAgent is not None:
        _specs.append(("StrategyDesignerAgent", lambda: StrategyDesignerAgent(agent_id="strategy-designer"), True))
    if RiskManagerAgent is not None:
        _specs.append(("RiskManagerAgent", lambda: RiskManagerAgent(agent_id="risk-manager"), True))
    if CapitalAllocatorAgent is not None:
        _specs.append(("CapitalAllocatorAgent", lambda: CapitalAllocatorAgent(agent_id="capital-allocator"), True))
    if AnomalyDetectorAgent is not None:
        _specs.append(("AnomalyDetectorAgent", lambda: AnomalyDetectorAgent(agent_id="anomaly-detector"), True))
    if BacktestAgent is not None:
        _specs.append(("BacktestAgent", lambda: BacktestAgent(agent_id="backtest"), True))

    failed: list[str] = []
    skipped: list[str] = []
    for label, factory, enabled in _specs:
        if not enabled:
            logger.info("[BOOTSTRAP] Skipping %s (disabled by feature flag)", label)
            skipped.append(label)
            continue
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
    if skipped:
        logger.info(
            "bootstrap_canonical_agents: %d/%d agents skipped (feature flags): %s",
            len(skipped), len(_specs), ", ".join(skipped),
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

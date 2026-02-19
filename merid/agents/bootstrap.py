"""Bootstrap canonical agents into the registry.

Registers all wired agents (research, strategy, risk, coordination, ops)
into the CanonicalAgentRegistry for orchestrator use.
"""

from merid.agents.base import get_canonical_registry
from merid.agents.wiring import (
    WiredPredictionMarketAgent,
    WiredCryptoSignalsAgent,
    WiredMarketResearchAgent,
)
from merid.agents.strategy import (
    StrategyDesignerAgent,
    ArbitrageAgent,
    ExecutionOptimizerAgent,
)
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
    
    # Research agents
    try:
        pm_agent = WiredPredictionMarketAgent(agent_id="pm-research-live")
        registry.register(pm_agent)
    except Exception as e:
        logger.warning(f"Failed to register PredictionMarketAgent: {e}")
    
    try:
        crypto_agent = WiredCryptoSignalsAgent(agent_id="crypto-signals-live")
        registry.register(crypto_agent)
    except Exception as e:
        logger.warning(f"Failed to register CryptoSignalsAgent: {e}")
    
    try:
        equity_agent = WiredMarketResearchAgent(agent_id="market-research-live")
        registry.register(equity_agent)
    except Exception as e:
        logger.warning(f"Failed to register MarketResearchAgent: {e}")
    
    # Strategy agents
    try:
        strategy_designer = StrategyDesignerAgent(agent_id="strategy-designer")
        registry.register(strategy_designer)
    except Exception as e:
        logger.warning(f"Failed to register StrategyDesignerAgent: {e}")
    
    try:
        arb_agent = ArbitrageAgent(agent_id="arbitrage-scanner")
        registry.register(arb_agent)
    except Exception as e:
        logger.warning(f"Failed to register ArbitrageAgent: {e}")
    
    try:
        exec_optimizer = ExecutionOptimizerAgent(agent_id="execution-optimizer")
        registry.register(exec_optimizer)
    except Exception as e:
        logger.warning(f"Failed to register ExecutionOptimizerAgent: {e}")
    
    # Risk agents
    try:
        risk_agent = RiskManagerAgent(agent_id="risk-manager")
        registry.register(risk_agent)
    except Exception as e:
        logger.warning(f"Failed to register RiskManagerAgent: {e}")
    
    try:
        capital_allocator = CapitalAllocatorAgent(agent_id="capital-allocator")
        registry.register(capital_allocator)
    except Exception as e:
        logger.warning(f"Failed to register CapitalAllocatorAgent: {e}")
    
    try:
        anomaly_detector = AnomalyDetectorAgent(agent_id="anomaly-detector")
        registry.register(anomaly_detector)
    except Exception as e:
        logger.warning(f"Failed to register AnomalyDetectorAgent: {e}")
    
    # Coordination agents
    try:
        consensus_coord = ConsensusCoordinatorAgent(agent_id="consensus-coordinator")
        registry.register(consensus_coord)
    except Exception as e:
        logger.warning(f"Failed to register ConsensusCoordinatorAgent: {e}")
    
    try:
        explainability = ExplainabilityAgent(agent_id="explainability")
        registry.register(explainability)
    except Exception as e:
        logger.warning(f"Failed to register ExplainabilityAgent: {e}")
    
    try:
        debate_coord = DebateCoordinatorAgent(agent_id="debate-coordinator")
        registry.register(debate_coord)
    except Exception as e:
        logger.warning(f"Failed to register DebateCoordinatorAgent: {e}")
    
    try:
        governance = GovernanceAgent(agent_id="governance")
        registry.register(governance)
    except Exception as e:
        logger.warning(f"Failed to register GovernanceAgent: {e}")
    
    # Ops agents
    try:
        ops_runbook = OpsRunbookAgent(agent_id="ops-runbook")
        registry.register(ops_runbook)
    except Exception as e:
        logger.warning(f"Failed to register OpsRunbookAgent: {e}")
    
    try:
        backtest = BacktestAgent(agent_id="backtest")
        registry.register(backtest)
    except Exception as e:
        logger.warning(f"Failed to register BacktestAgent: {e}")
    
    agent_count = registry.count()
    logger.info(f"✅ Bootstrapped {agent_count} canonical agents into registry")
    return agent_count


# Auto-bootstrap on import
_bootstrapped = False

def ensure_bootstrapped() -> int:
    """Ensure agents are bootstrapped (idempotent)."""
    global _bootstrapped
    if not _bootstrapped:
        count = bootstrap_canonical_agents()
        _bootstrapped = True
        return count
    return get_canonical_registry().count()

"""
Kalshi Market Wiring Layer

Complete market coverage, explicit mapping, and strong safety constraints
for Kalshi prediction markets integration with MERID unified signal system.

Components:
- Models: Data structures for markets, mappings, and safety checks
- Store: Database persistence and querying
- Sync: Universe synchronization with Kalshi API
- Mapping: Automatic and manual market mapping rules
- Safety: Data freshness and risk limit enforcement
- Coverage: Completeness checking and gap detection
- Orchestrator: Main coordination and integration layer
"""

from .models import (
    KalshiMarketRecord,
    MarketMapping,
    RiskProfile,
    MarketStatus,
    CoverageReport,
    MarketContextConfig,
)

from .safety import (
    SafetyCheckResult,
    ContextCheckResult,
    RiskCheckResult,
    ContextStatus,
)

from merid.signals.cqi_gating import QualityBand

from .store import (
    KalshiMarketStore,
    get_kalshi_market_store,
)

from .sync import (
    KalshiUniverseSync,
    SyncConfig,
    get_kalshi_universe_sync,
)

from .mapping import (
    MarketMappingBuilder,
    MappingRule,
    get_market_mapping_builder,
)

from .safety import (
    KalshiSafetyLayer,
    ContextCheckResult,
    RiskCheckResult,
    get_kalshi_safety_layer,
)

from .coverage import (
    KalshiCoverageChecker,
    CoverageConfig,
    get_kalshi_coverage_checker,
)

from .orchestrator import (
    KalshiWiringOrchestrator,
    get_kalshi_wiring_orchestrator,
)

__all__ = [
    # Models
    "KalshiMarketRecord",
    "MarketMapping", 
    "RiskProfile",
    "MarketStatus",
    "CoverageReport",
    "MarketContextConfig",
    "SafetyCheckResult",
    "ContextStatus",
    "QualityBand",
    
    # Store
    "KalshiMarketStore",
    "get_kalshi_market_store",
    
    # Sync
    "KalshiUniverseSync",
    "SyncConfig",
    "get_kalshi_universe_sync",
    
    # Mapping
    "MarketMappingBuilder",
    "MappingRule",
    "get_market_mapping_builder",
    
    # Safety
    "KalshiSafetyLayer",
    "ContextCheckResult",
    "RiskCheckResult",
    "get_kalshi_safety_layer",
    
    # Coverage
    "KalshiCoverageChecker",
    "CoverageConfig",
    "get_kalshi_coverage_checker",
    
    # Orchestrator
    "KalshiWiringOrchestrator",
    "get_kalshi_wiring_orchestrator",
]

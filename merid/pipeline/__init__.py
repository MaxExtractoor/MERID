"""MERID Unified Trade Pipeline — One pipeline, many adapters, strict risk.

Provides:
- TradeProposal: normalized object all agents produce
- UnifiedVenueAdapter: ABC for venue-specific implementations
- InstrumentRegistry: merid_symbol ↔ venue:native_symbol mapping
- VenueConfig + ModeManager: per-venue SIM/PAPER/LIVE gating
- GlobalRiskManager: cross-domain limits, capital routing, domain PnL
- Domain agents: PredictionMarketAgent, CryptoArbAgent, EquityAgent
"""

from merid.pipeline.proposal import (
    TradeDomain,
    TradeProposal,
    ProposalStatus,
    ExecutionResult,
)
from merid.pipeline.adapter import UnifiedVenueAdapter, AdapterRegistry
from merid.pipeline.instruments import InstrumentRegistry, Instrument
from merid.pipeline.mode_manager import ModeManager, VenueConfig, TradingMode
from merid.pipeline.risk_manager import GlobalRiskManager, DomainRiskConfig
from merid.pipeline.risk_context import RiskContext, build_risk_context, get_risk_context
from merid.pipeline.router import TradeRouter

__all__ = [
    "AdapterRegistry",
    "DomainRiskConfig",
    "ExecutionResult",
    "GlobalRiskManager",
    "Instrument",
    "InstrumentRegistry",
    "ModeManager",
    "ProposalStatus",
    "RiskContext",
    "TradeDomain",
    "TradeProposal",
    "TradeRouter",
    "TradingMode",
    "UnifiedVenueAdapter",
    "VenueConfig",
    "build_risk_context",
    "get_risk_context",
]

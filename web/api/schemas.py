"""
Schema API Endpoints.

Provides API access to canonical data schemas for validation and documentation.
"""

from __future__ import annotations

from typing import Dict, Any, List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from schemas import SCHEMA_VERSION
from schemas.intent import IntentEnvelope, IntentType, IntentStatus, IntentPriority
from schemas.consensus import ConsensusBlock, ConsensusVote, ConsensusOutcome, VoteType
from schemas.arbitrage import ArbitrageOpportunity, ArbitrageType, ArbitrageStatus, ArbitrageLeg
from schemas.execution import ExecutionResult, ExecutionStatus, ExecutionVenue, FailureReason
from schemas.simulation import SimulationReport, SimulationType, SimulationStatus, SimulationOutcome
from schemas.risk import RiskPreview, RiskLevel, RiskCategory, RiskFactor
from utils.logger import get_logger

router = APIRouter(prefix="/api/v1/schemas", tags=["schemas"])
logger = get_logger("web.api.schemas")


@router.get("/version")
async def get_schema_version() -> Dict[str, Any]:
    """Get current schema version."""
    return {
        "version": SCHEMA_VERSION,
        "schemas": [
            "IntentEnvelope",
            "ConsensusBlock",
            "ArbitrageOpportunity",
            "ExecutionResult",
            "SimulationReport",
            "RiskPreview",
        ]
    }


@router.get("/intent/types")
async def get_intent_types() -> Dict[str, Any]:
    """Get all intent types."""
    return {
        "types": [t.value for t in IntentType],
        "statuses": [s.value for s in IntentStatus],
        "priorities": [p.value for p in IntentPriority],
    }


@router.get("/intent/example")
async def get_intent_example() -> Dict[str, Any]:
    """Get example IntentEnvelope."""
    example = IntentEnvelope(
        intent_type=IntentType.SPOT_BUY,
        symbol="BTC/USDT",
        side="buy",
        quantity=0.1,
        order_type="market",
        stop_loss_pct=0.02,
        take_profit_pct=0.04,
    )
    return example.to_dict()


@router.post("/intent/validate")
async def validate_intent(data: Dict[str, Any]) -> Dict[str, Any]:
    """Validate an IntentEnvelope structure."""
    try:
        intent = IntentEnvelope.from_dict(data)
        return {
            "valid": True,
            "hash": intent.compute_hash(),
            "can_execute": intent.can_execute(),
            "is_expired": intent.is_expired(),
        }
    except Exception as e:
        return {
            "valid": False,
            "error": str(e),
        }


@router.get("/consensus/types")
async def get_consensus_types() -> Dict[str, Any]:
    """Get all consensus types."""
    return {
        "outcomes": [o.value for o in ConsensusOutcome],
        "vote_types": [v.value for v in VoteType],
    }


@router.get("/consensus/example")
async def get_consensus_example() -> Dict[str, Any]:
    """Get example ConsensusBlock."""
    block = ConsensusBlock(
        block_number=1,
        intent_id="intent_abc123",
        intent_hash="hash123",
        intent_summary="Buy 0.1 BTC at market",
    )
    
    # Add sample votes
    block.add_vote(ConsensusVote(
        agent_id="market-analyst-01",
        vote=VoteType.APPROVE,
        confidence=0.85,
        trust_weight=1.0,
        reasoning="Strong bullish signal",
        signal="bullish",
    ))
    block.add_vote(ConsensusVote(
        agent_id="risk-agent-01",
        vote=VoteType.APPROVE,
        confidence=0.75,
        trust_weight=1.0,
        reasoning="Risk within limits",
    ))
    block.add_vote(ConsensusVote(
        agent_id="skeptic-agent-01",
        vote=VoteType.APPROVE,
        confidence=0.70,
        trust_weight=1.0,
        reasoning="No contradictions detected",
    ))
    
    block.finalize()
    return block.to_dict()


@router.get("/arbitrage/types")
async def get_arbitrage_types() -> Dict[str, Any]:
    """Get all arbitrage types."""
    return {
        "types": [t.value for t in ArbitrageType],
        "statuses": [s.value for s in ArbitrageStatus],
    }


@router.get("/arbitrage/example")
async def get_arbitrage_example() -> Dict[str, Any]:
    """Get example ArbitrageOpportunity."""
    opp = ArbitrageOpportunity(
        arb_type=ArbitrageType.CROSS_CEX,
        source_scanner="cross_cex_scanner",
    )
    
    # Add legs
    opp.legs.append(ArbitrageLeg(
        sequence=1,
        venue="binance",
        symbol="BTC/USDT",
        side="buy",
        quantity=0.1,
        price=94000.0,
        estimated_fee=9.4,
    ))
    opp.legs.append(ArbitrageLeg(
        sequence=2,
        venue="coinbase",
        symbol="BTC/USDT",
        side="sell",
        quantity=0.1,
        price=94150.0,
        estimated_fee=14.1,
    ))
    
    opp.calculate_profit()
    return opp.to_dict()


@router.get("/execution/types")
async def get_execution_types() -> Dict[str, Any]:
    """Get all execution types."""
    return {
        "statuses": [s.value for s in ExecutionStatus],
        "venues": [v.value for v in ExecutionVenue],
        "failure_reasons": [f.value for f in FailureReason],
    }


@router.get("/execution/example")
async def get_execution_example() -> Dict[str, Any]:
    """Get example ExecutionResult."""
    result = ExecutionResult(
        intent_id="intent_abc123",
        symbol="BTC/USDT",
        side="buy",
        order_type="market",
        requested_quantity=0.1,
        venue=ExecutionVenue.CEX_SPOT,
        venue_name="binance",
    )
    return result.to_dict()


@router.get("/simulation/types")
async def get_simulation_types() -> Dict[str, Any]:
    """Get all simulation types."""
    return {
        "types": [t.value for t in SimulationType],
        "statuses": [s.value for s in SimulationStatus],
        "outcomes": [o.value for o in SimulationOutcome],
    }


@router.get("/simulation/example")
async def get_simulation_example() -> Dict[str, Any]:
    """Get example SimulationReport."""
    report = SimulationReport(
        sim_type=SimulationType.INTENT_PREVIEW,
        symbol="BTC/USDT",
        initial_capital=100000.0,
        position_size=10000.0,
    )
    return report.to_dict()


@router.get("/risk/types")
async def get_risk_types() -> Dict[str, Any]:
    """Get all risk types."""
    return {
        "levels": [l.value for l in RiskLevel],
        "categories": [c.value for c in RiskCategory],
    }


@router.get("/risk/example")
async def get_risk_example() -> Dict[str, Any]:
    """Get example RiskPreview."""
    preview = RiskPreview(
        symbol="BTC/USDT",
        side="buy",
        quantity=0.1,
    )
    
    # Add sample risk factors
    preview.add_factor(RiskFactor(
        category=RiskCategory.MARKET,
        name="Volatility Risk",
        description="Current volatility above average",
        severity=0.3,
        probability=0.6,
    ))
    preview.add_factor(RiskFactor(
        category=RiskCategory.LIQUIDITY,
        name="Slippage Risk",
        description="Order size may cause slippage",
        severity=0.2,
        probability=0.4,
    ))
    
    preview.evaluate_approval()
    return preview.to_dict()


@router.get("/all")
async def get_all_schemas() -> Dict[str, Any]:
    """Get documentation for all schemas."""
    return {
        "version": SCHEMA_VERSION,
        "schemas": {
            "IntentEnvelope": {
                "description": "Canonical trading intent structure",
                "types": [t.value for t in IntentType],
                "statuses": [s.value for s in IntentStatus],
            },
            "ConsensusBlock": {
                "description": "Hashable, replayable consensus record",
                "outcomes": [o.value for o in ConsensusOutcome],
                "vote_types": [v.value for v in VoteType],
            },
            "ArbitrageOpportunity": {
                "description": "Arbitrage opportunity with legs and cost model",
                "types": [t.value for t in ArbitrageType],
                "statuses": [s.value for s in ArbitrageStatus],
            },
            "ExecutionResult": {
                "description": "Complete execution result with fills",
                "statuses": [s.value for s in ExecutionStatus],
                "venues": [v.value for v in ExecutionVenue],
            },
            "SimulationReport": {
                "description": "Simulation results with scenarios",
                "types": [t.value for t in SimulationType],
                "outcomes": [o.value for o in SimulationOutcome],
            },
            "RiskPreview": {
                "description": "Risk assessment for trading actions",
                "levels": [l.value for l in RiskLevel],
                "categories": [c.value for c in RiskCategory],
            },
        }
    }

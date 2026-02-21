"""
Institutional API - Endpoints for Four-System Architecture UI

Exposes:
- System status and health
- Intent management and approval workflows
- Vault governance operations
- Shadow MERID comparison
- Risk and compliance metrics
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Depends, Request
from pydantic import BaseModel, Field

from contracts.system_contracts import (
    SystemID,
    SYSTEM_CONTRACTS,
    get_contract_enforcer,
)
from contracts.capital_firewall import (
    TransferType,
    get_capital_firewall,
)
from contracts.intents import (
    IntentType,
    IntentPriority,
    IntentPayload,
    get_intent_processor,
)
from contracts.vault_governance import (
    VaultOperation,
    KeyRole,
    get_vault_governance,
)
from hardening.lockdown import get_lockdown_manager, LockdownLevel, LockdownReason
from hardening.circuit_breaker import get_circuit_registry
from monitoring.metrics import get_metrics_registry
from simulation.divergence_engine import (
    get_divergence_engine,
    DivergenceLevel,
    LiveState,
    ShadowState,
)
from simulation.shadow_guardian import get_shadow_guardian, ThreatLevel
from simulation.attack_simulator import get_attack_simulator, AttackType, AttackSeverity, AttackConfig
from defi.aave import get_aave_client, stash_profits
from utils.logger import get_logger

logger = get_logger("web.api.institutional")

router = APIRouter(prefix="/api/v1/institutional", tags=["institutional"])


class SystemStatusResponse(BaseModel):
    """System status response."""
    system_id: str
    status: str
    health_score: float
    active_intents: int
    violations_24h: int
    last_activity: Optional[float]


class IntentCreateRequest(BaseModel):
    """Request to create an intent."""
    intent_type: str
    source_system: str
    action: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    amount_usd: Optional[float] = None
    symbol: Optional[str] = None
    target_system: Optional[str] = None
    priority: str = "normal"


class IntentApprovalRequest(BaseModel):
    """Request to approve/reject an intent."""
    intent_id: str
    approver_id: str
    action: str  # "approve", "reject", "veto"
    reason: Optional[str] = None


class VaultOperationRequest(BaseModel):
    """Request for vault operation."""
    operation: str
    proposer_key_id: str
    amount_usd: Optional[float] = None
    destination: Optional[str] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)


class VaultSignatureRequest(BaseModel):
    """Request to sign vault operation."""
    request_id: str
    key_id: str
    signature: str


class LockdownRequest(BaseModel):
    """Request to trigger/release lockdown."""
    action: str  # "trigger" or "release"
    level: Optional[str] = None
    reason: Optional[str] = None
    triggered_by: str


@router.get("/systems/status")
async def get_all_systems_status() -> Dict[str, Any]:
    """Get status of all four systems."""
    enforcer = get_contract_enforcer()
    lockdown = get_lockdown_manager()
    
    systems = []
    for system_id, contract in SYSTEM_CONTRACTS.items():
        violations = [
            v for v in enforcer.get_violations(100)
            if v.system == system_id
        ]
        recent_violations = [
            v for v in violations
            if time.time() - v.timestamp < 86400
        ]
        
        health_score = 1.0 - (len(recent_violations) * 0.1)
        health_score = max(0.0, min(1.0, health_score))
        
        systems.append({
            "system_id": system_id.value,
            "name": system_id.value.title(),
            "status": "locked" if lockdown.is_locked else "operational",
            "health_score": health_score,
            "allowed_actions": len(contract.allowed_actions),
            "forbidden_actions": len(contract.forbidden_actions),
            "max_capital_authority": contract.max_capital_authority_usd,
            "can_initiate_lockdown": contract.can_initiate_lockdown,
            "violations_24h": len(recent_violations),
        })
    
    return {
        "systems": systems,
        "global_status": "locked" if lockdown.is_locked else "operational",
        "lockdown_level": lockdown.level.value if lockdown.is_locked else None,
        "total_violations": enforcer.get_violation_count(),
    }


@router.get("/systems/{system_id}/contract")
async def get_system_contract(system_id: str) -> Dict[str, Any]:
    """Get detailed contract for a system."""
    try:
        sys_id = SystemID(system_id)
    except ValueError:
        raise HTTPException(status_code=404, detail=f"Unknown system: {system_id}")
    
    contract = SYSTEM_CONTRACTS.get(sys_id)
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    
    return {
        "system_id": sys_id.value,
        "allowed_actions": list(contract.allowed_actions),
        "forbidden_actions": list(contract.forbidden_actions),
        "can_request_from": {
            k.value: list(v) for k, v in contract.can_request_from.items()
        },
        "max_capital_authority_usd": contract.max_capital_authority_usd,
        "can_initiate_lockdown": contract.can_initiate_lockdown,
        "can_modify_other_systems": contract.can_modify_other_systems,
        "rate_limits": {
            k: {"max_count": v[0], "window_seconds": v[1]}
            for k, v in contract.rate_limits.items()
        },
    }


@router.get("/intents")
async def list_intents(
    system: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """List pending intents."""
    processor = get_intent_processor()
    
    sys_filter = SystemID(system) if system else None
    intents = processor.get_pending_intents(system=sys_filter)
    
    if status:
        intents = [i for i in intents if i.status.value == status]
    
    return {
        "intents": [i.to_dict() for i in intents[:limit]],
        "total": len(intents),
    }


@router.post("/intents")
async def create_intent(request: IntentCreateRequest) -> Dict[str, Any]:
    """Create a new intent."""
    processor = get_intent_processor()
    
    try:
        intent_type = IntentType(request.intent_type)
        source_system = SystemID(request.source_system)
        priority = IntentPriority[request.priority.upper()]
    except (ValueError, KeyError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    target = SystemID(request.target_system) if request.target_system else None
    
    payload = IntentPayload(
        action=request.action,
        parameters=request.parameters,
        target_system=target,
        amount_usd=request.amount_usd,
        symbol=request.symbol,
    )
    
    intent = processor.create_intent(
        intent_type=intent_type,
        source_system=source_system,
        payload=payload,
        priority=priority,
    )
    
    return {
        "status": "created",
        "intent": intent.to_dict(),
    }


@router.post("/intents/action")
async def intent_action(request: IntentApprovalRequest) -> Dict[str, Any]:
    """Approve, reject, or veto an intent."""
    processor = get_intent_processor()
    
    if request.action == "approve":
        success = processor.approve_intent(request.intent_id, request.approver_id)
    elif request.action == "reject":
        success = processor.reject_intent(
            request.intent_id, request.approver_id, request.reason or ""
        )
    elif request.action == "veto":
        success = processor.veto_intent(
            request.intent_id, request.approver_id, request.reason or ""
        )
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {request.action}")
    
    intent = processor.get_intent(request.intent_id)
    
    return {
        "success": success,
        "intent": intent.to_dict() if intent else None,
    }


@router.get("/vault/status")
async def get_vault_status() -> Dict[str, Any]:
    """Get vault governance status."""
    vault = get_vault_governance()
    firewall = get_capital_firewall()
    
    return {
        "vault": vault.get_status(),
        "firewall": firewall.get_status(),
        "key_holders": [
            {
                "key_id": h.key_id,
                "role": h.role.value,
                "weight": h.weight,
                "is_active": h.is_active,
                "last_used": h.last_used_at,
            }
            for h in vault.get_key_holders()
        ],
    }


@router.get("/vault/operations")
async def list_vault_operations() -> Dict[str, Any]:
    """List pending vault operations."""
    vault = get_vault_governance()
    
    operations = vault.get_pending_operations()
    
    return {
        "operations": [
            {
                "request_id": op.request_id,
                "operation": op.operation.value,
                "proposer": op.proposer_key_id,
                "amount_usd": op.amount_usd,
                "status": op.status.value,
                "signatures": len(op.signatures),
                "required_signatures": op.required_signatures,
                "total_weight": op.total_weight(),
                "required_weight": op.required_weight,
                "timelock_until": op.timelock_until,
                "created_at": op.created_at,
            }
            for op in operations
        ],
        "total": len(operations),
    }


@router.post("/vault/operations")
async def create_vault_operation(request: VaultOperationRequest) -> Dict[str, Any]:
    """Create a new vault operation."""
    vault = get_vault_governance()
    
    try:
        operation = VaultOperation(request.operation)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Unknown operation: {request.operation}")
    
    try:
        op_request = vault.propose_operation(
            operation=operation,
            proposer_key_id=request.proposer_key_id,
            amount_usd=request.amount_usd,
            destination=request.destination,
            parameters=request.parameters,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return {
        "status": "proposed",
        "request_id": op_request.request_id,
        "operation": op_request.operation.value,
        "required_signatures": op_request.required_signatures,
        "required_weight": op_request.required_weight,
    }


@router.post("/vault/sign")
async def sign_vault_operation(request: VaultSignatureRequest) -> Dict[str, Any]:
    """Sign a vault operation."""
    vault = get_vault_governance()
    
    success = vault.sign_operation(
        request_id=request.request_id,
        key_id=request.key_id,
        signature=request.signature,
    )
    
    op = vault.get_operation(request.request_id)
    
    return {
        "success": success,
        "operation": {
            "request_id": op.request_id,
            "status": op.status.value,
            "signatures": len(op.signatures),
            "required_signatures": op.required_signatures,
            "total_weight": op.total_weight(),
            "required_weight": op.required_weight,
        } if op else None,
    }


@router.post("/vault/execute/{request_id}")
async def execute_vault_operation(request_id: str) -> Dict[str, Any]:
    """Execute an approved vault operation."""
    vault = get_vault_governance()
    
    success = vault.execute_operation(request_id)
    
    return {
        "success": success,
        "request_id": request_id,
    }


@router.get("/firewall/transfers")
async def list_pending_transfers() -> Dict[str, Any]:
    """List pending capital transfers."""
    firewall = get_capital_firewall()
    
    requests = firewall.get_pending_requests()
    
    return {
        "transfers": [
            {
                "request_id": r.request_id,
                "transfer_type": r.transfer_type.value,
                "source_system": r.source_system.value,
                "destination_system": r.destination_system.value if r.destination_system else None,
                "amount_usd": r.amount_usd,
                "status": r.status.value,
                "approvals": len(r.approvals),
                "required_approvals": firewall.config.quorum_thresholds.get(r.transfer_type, 2),
                "cooldown_ends_at": r.cooldown_ends_at,
                "created_at": r.created_at,
            }
            for r in requests
        ],
        "status": firewall.get_status(),
    }


@router.get("/lockdown/status")
async def get_lockdown_status() -> Dict[str, Any]:
    """Get lockdown status."""
    lockdown = get_lockdown_manager()
    circuits = get_circuit_registry()
    
    return {
        "lockdown": lockdown.get_status(),
        "circuits": circuits.get_all_stats(),
        "recent_events": [
            {
                "event_id": e.event_id,
                "level": e.level.value,
                "reason": e.reason.value,
                "triggered_by": e.triggered_by,
                "message": e.message,
                "timestamp": e.timestamp,
                "resolved_at": e.resolved_at,
            }
            for e in lockdown.get_event_history(10)
        ],
    }


@router.post("/lockdown")
async def lockdown_action(request: LockdownRequest) -> Dict[str, Any]:
    """Trigger or release lockdown."""
    lockdown = get_lockdown_manager()
    
    if request.action == "trigger":
        try:
            level = LockdownLevel(request.level) if request.level else LockdownLevel.FULL
            reason = LockdownReason(request.reason) if request.reason else LockdownReason.MANUAL
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        
        event = lockdown.trigger_lockdown(
            level=level,
            reason=reason,
            triggered_by=request.triggered_by,
            message=request.reason or "Manual lockdown",
        )
        
        return {
            "status": "locked",
            "event_id": event.event_id,
            "level": event.level.value,
        }
    
    elif request.action == "release":
        success = lockdown.release_lockdown(
            released_by=request.triggered_by,
            message=request.reason or "Manual release",
        )
        
        return {
            "status": "released" if success else "failed",
            "success": success,
        }
    
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {request.action}")


@router.get("/shadow/status")
async def get_shadow_status() -> Dict[str, Any]:
    """Get shadow MERID status."""
    try:
        from simulation.shadow_merid import get_shadow_merid
        shadow = get_shadow_merid()
        
        return {
            "portfolio": {
                "balance": shadow._portfolio.balance,
                "equity": shadow._portfolio.equity,
                "total_pnl": shadow._portfolio.total_pnl,
                "positions": len(shadow._portfolio.positions),
                "max_drawdown": shadow._portfolio.max_drawdown,
            },
            "performance": shadow.get_performance_metrics(),
            "divergence": shadow.get_divergence_report(),
        }
    except Exception as e:
        return {
            "status": "unavailable",
            "error": str(e),
        }


@router.get("/metrics/prometheus")
async def get_prometheus_metrics() -> str:
    """Get Prometheus-format metrics."""
    registry = get_metrics_registry()
    return registry.export_prometheus()


@router.get("/risk/summary")
async def get_risk_summary() -> Dict[str, Any]:
    """Get risk and compliance summary."""
    lockdown = get_lockdown_manager()
    enforcer = get_contract_enforcer()
    firewall = get_capital_firewall()
    
    violations = enforcer.get_violations(100)
    recent_violations = [v for v in violations if time.time() - v.timestamp < 86400]
    
    violation_by_type = {}
    for v in recent_violations:
        vtype = v.violation_type.value
        violation_by_type[vtype] = violation_by_type.get(vtype, 0) + 1
    
    risk_score = 0.0
    if lockdown.is_locked:
        risk_score += 0.5
    risk_score += len(recent_violations) * 0.05
    daily_outflow = firewall.get_daily_outflow()
    max_outflow = firewall.config.max_daily_outflow_usd
    risk_score += (daily_outflow / max_outflow) * 0.2
    risk_score = min(1.0, risk_score)
    
    if risk_score < 0.3:
        risk_level = "low"
    elif risk_score < 0.6:
        risk_level = "medium"
    elif risk_score < 0.8:
        risk_level = "high"
    else:
        risk_level = "critical"
    
    return {
        "risk_score": risk_score,
        "risk_level": risk_level,
        "lockdown_active": lockdown.is_locked,
        "violations_24h": len(recent_violations),
        "violations_by_type": violation_by_type,
        "capital_utilization": {
            "daily_outflow": daily_outflow,
            "daily_limit": max_outflow,
            "utilization_pct": (daily_outflow / max_outflow) * 100,
        },
        "compliance_status": "compliant" if len(recent_violations) == 0 else "violations_detected",
    }


@router.get("/shadow/divergence")
async def get_shadow_divergence() -> Dict[str, Any]:
    """Get real-time divergence score and metrics."""
    engine = get_divergence_engine()
    guardian = get_shadow_guardian()
    
    status = engine.get_status()
    guardian_status = guardian.get_status()
    
    history = engine.get_history(20)
    
    return {
        "current_score": status["current_score"],
        "current_score_pct": f"{status['current_score'] * 100:.2f}%",
        "current_level": status["current_level"],
        "thresholds": status["thresholds"],
        "weights": status["weights"],
        "guardian": {
            "state": guardian_status["state"],
            "consecutive_alerts": guardian_status["consecutive_alerts"],
            "recent_threats": guardian_status["recent_threats"],
        },
        "history": [
            {
                "timestamp": r.timestamp,
                "score": r.total_score,
                "level": r.level.value,
            }
            for r in history
        ],
        "events": [
            {
                "event_id": e.event_id,
                "timestamp": e.timestamp,
                "level": e.level.value,
                "score": e.score,
            }
            for e in engine.get_events(10)
        ],
    }


@router.post("/shadow/update-state")
async def update_shadow_state(
    live_consensus: float = 0.0,
    live_balance: float = 100000.0,
    live_pnl: float = 0.0,
    shadow_consensus: float = 0.0,
    shadow_balance: float = 100000.0,
    shadow_pnl: float = 0.0,
) -> Dict[str, Any]:
    """Update live and shadow states for divergence calculation."""
    engine = get_divergence_engine()
    
    live = LiveState(
        consensus_probability=live_consensus,
        balance=live_balance,
        total_pnl=live_pnl,
    )
    
    shadow = ShadowState(
        consensus_probability=shadow_consensus,
        balance=shadow_balance,
        total_pnl=shadow_pnl,
    )
    
    engine.update_live_state(live)
    engine.update_shadow_state(shadow)
    
    result = engine.calculate_divergence()
    
    return {
        "divergence_calculated": True,
        "result": result.to_dict(),
    }


@router.post("/shadow/stress-test")
async def run_stress_test(
    attack_types: Optional[List[str]] = None,
    severity: str = "medium",
    duration: float = 5.0,
) -> Dict[str, Any]:
    """Run stress test with attack simulation."""
    simulator = get_attack_simulator()
    
    types = None
    if attack_types:
        types = [AttackType(t) for t in attack_types]
    
    sev = AttackSeverity(severity)
    
    results = await simulator.run_stress_test(
        attack_types=types,
        severity=sev,
        duration_per_attack=duration,
    )
    
    return {
        "stress_test_completed": True,
        "attacks_run": len(results),
        "results": [r.to_dict() for r in results],
        "detection_stats": simulator.get_detection_stats(),
    }


@router.get("/shadow/guardian")
async def get_guardian_status() -> Dict[str, Any]:
    """Get ShadowGuardian status."""
    guardian = get_shadow_guardian()
    return guardian.get_status()


@router.post("/shadow/replay")
async def trigger_replay(
    blocks: int = 5,
    noise_pct: float = 0.05,
    runs: int = 3,
) -> Dict[str, Any]:
    """Trigger replay with perturbations."""
    from simulation.shadow_guardian import ReplayConfig
    
    guardian = get_shadow_guardian()
    
    config = ReplayConfig(
        blocks_to_replay=blocks,
        oracle_noise_pct=noise_pct,
        run_count=runs,
    )
    
    result = await guardian.run_replay_with_perturbations(config)
    
    return {
        "replay_id": result.replay_id,
        "blocks_replayed": result.blocks_replayed,
        "resilience_score": result.resilience_score,
        "passed": result.passed,
        "anomalies": result.anomalies_detected,
        "divergence_scores": result.divergence_scores,
    }


@router.get("/treasury/aave/status")
async def get_aave_status() -> Dict[str, Any]:
    """Get Aave integration status."""
    client = get_aave_client()
    
    account = await client.get_account_data()
    positions = await client.get_positions()
    
    return {
        "status": client.get_status(),
        "account": account.to_dict(),
        "positions": {
            asset: {
                "supplied": pos.supplied_amount,
                "borrowed": pos.borrowed_amount,
                "apy_supply": pos.apy_supply,
                "apy_borrow": pos.apy_borrow,
            }
            for asset, pos in positions.items()
        },
        "transactions": [
            {
                "tx_id": tx.tx_id,
                "operation": tx.operation.value,
                "asset": tx.asset,
                "amount": tx.amount,
                "status": tx.status,
                "timestamp": tx.timestamp,
            }
            for tx in client.get_transaction_history(10)
        ],
    }


@router.post("/treasury/aave/supply")
async def aave_supply(
    asset: str = "USDC",
    amount: float = 100.0,
) -> Dict[str, Any]:
    """Supply asset to Aave."""
    client = get_aave_client()
    
    try:
        tx = await client.supply(asset, amount)
        health = await client.get_health_factor()
        
        return {
            "success": tx.status != "failed",
            "tx_id": tx.tx_id,
            "tx_hash": tx.tx_hash,
            "status": tx.status,
            "health_factor": health,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/treasury/aave/withdraw")
async def aave_withdraw(
    asset: str = "USDC",
    amount: float = -1,
) -> Dict[str, Any]:
    """Withdraw asset from Aave."""
    client = get_aave_client()
    
    try:
        tx = await client.withdraw(asset, amount)
        health = await client.get_health_factor()
        
        return {
            "success": tx.status != "failed",
            "tx_id": tx.tx_id,
            "tx_hash": tx.tx_hash,
            "status": tx.status,
            "health_factor": health,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/treasury/stash-profits")
async def stash_treasury_profits(
    profit_usd: float = 1000.0,
    allocation_ratio: float = 0.3,
) -> Dict[str, Any]:
    """Stash profits to Aave for yield."""
    tx = await stash_profits(profit_usd, allocation_ratio)
    
    if tx:
        client = get_aave_client()
        health = await client.get_health_factor()
        
        return {
            "success": True,
            "amount_stashed": profit_usd * allocation_ratio,
            "tx_id": tx.tx_id,
            "health_factor": health,
        }
    
    return {
        "success": False,
        "reason": "Amount too small or stash failed",
    }


@router.get("/news/feed")
async def get_news_feed() -> Dict[str, Any]:
    """Get latest news articles."""
    try:
        from monitoring.news_feeds import get_news_aggregator
        aggregator = get_news_aggregator()
        articles = aggregator.get_recent_articles(limit=10)
        
        return {
            "articles": [
                {
                    "title": a.headline,
                    "summary": a.summary,
                    "source": a.source,
                    "url": a.url,
                    "published_at": a.published_at,
                    "importance": a.importance,
                    "categories": a.categories,
                }
                for a in articles
            ],
            "count": len(articles),
        }
    except Exception as e:
        logger.warning(f"News feed error: {e}")
        return {"articles": [], "count": 0, "error": str(e)}


@router.get("/intelligence/feed")
async def get_intelligence_feed() -> Dict[str, Any]:
    """Get comprehensive intelligence feed with all signal types."""
    try:
        from monitoring.intelligence_layer import get_intelligence_layer
        layer = get_intelligence_layer()
        
        signals = layer.get_all_signals(limit=30)
        alerts = layer.get_alerts(limit=10)
        sentiment = layer.get_market_sentiment()
        
        return {
            "signals": [s.to_dict() for s in signals],
            "alerts": [a.to_dict() for a in alerts],
            "sentiment": sentiment,
            "status": layer.get_status(),
        }
    except Exception as e:
        logger.warning(f"Intelligence feed error: {e}")
        return {"signals": [], "alerts": [], "error": str(e)}


@router.get("/intelligence/signals")
async def get_intelligence_signals(
    signal_type: Optional[str] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """Get intelligence signals, optionally filtered by type."""
    try:
        from monitoring.intelligence_layer import get_intelligence_layer, IntelligenceType
        layer = get_intelligence_layer()
        
        if signal_type:
            try:
                sig_type = IntelligenceType(signal_type)
                signals = layer.get_signals_by_type(sig_type, limit=limit)
            except ValueError:
                return {"error": f"Invalid signal type: {signal_type}"}
        else:
            signals = layer.get_all_signals(limit=limit)
        
        return {
            "signals": [s.to_dict() for s in signals],
            "count": len(signals),
        }
    except Exception as e:
        logger.warning(f"Intelligence signals error: {e}")
        return {"signals": [], "error": str(e)}


@router.get("/intelligence/sentiment")
async def get_market_sentiment() -> Dict[str, Any]:
    """Get aggregated market sentiment analysis."""
    try:
        layer = get_intelligence_layer()
        
        return layer.get_market_sentiment()
    except Exception as e:
        logger.warning(f"Sentiment error: {e}")
        return {"overall": 0.0, "label": "unknown", "error": str(e)}


@router.get("/intelligence/alerts")
async def get_intelligence_alerts(limit: int = 20) -> Dict[str, Any]:
    """Get high-priority market alerts."""
    try:
        layer = get_intelligence_layer()
        
        alerts = layer.get_alerts(limit=limit)
        
        return {
            "alerts": [a.to_dict() for a in alerts],
            "count": len(alerts),
        }
    except Exception as e:
        logger.warning(f"Alerts error: {e}")
        return {"alerts": [], "error": str(e)}


@router.post("/intelligence/start")
async def start_intelligence() -> Dict[str, Any]:
    """Start the intelligence processing layer."""
    try:
        from monitoring.intelligence_layer import start_intelligence_layer
        layer = await start_intelligence_layer()
        
        return {
            "status": "started",
            "message": "Intelligence layer started successfully",
        }
    except Exception as e:
        logger.error(f"Failed to start intelligence: {e}")
        return {"status": "error", "error": str(e)}


@router.get("/realtime/stream")
async def get_realtime_stream() -> Dict[str, Any]:
    """Get real-time data stream snapshot."""
    from data.live_price_feed import get_live_price_feed
    
    price_feed = get_live_price_feed()
    shadow = get_shadow_merid()
    engine = get_divergence_engine()
    guardian = get_shadow_guardian()
    lockdown = get_lockdown_manager()
    
    prices = price_feed.get_all_prices()
    
    return {
        "timestamp": time.time(),
        "prices": {
            symbol: {
                "price": p.price,
                "change_24h": p.change_24h_pct,
                "exchange": p.exchange,
            }
            for symbol, p in prices.items()
        },
        "shadow": {
            "equity": shadow._portfolio.equity,
            "pnl": shadow._portfolio.total_pnl,
            "positions": len(shadow._portfolio.positions),
        },
        "divergence": {
            "score": engine.get_current_score(),
            "level": engine.get_status()["current_level"],
            "percentage": engine.get_current_score() * 100,
        },
        "guardian": {
            "state": guardian.state.value,
            "alerts": guardian._consecutive_alerts,
            "threat_level": guardian._threat_level.value if hasattr(guardian, '_threat_level') else "none",
        },
        "system": {
            "locked": lockdown.is_locked,
            "level": lockdown.level.value if lockdown.is_locked else None,
        },
    }


# ============================================
# PREDICTION MARKET ENDPOINTS
# ============================================

@router.get("/predictions/markets")
async def get_prediction_markets(
    request: Request,
    category: Optional[str] = None,
    limit: int = 50
) -> Dict[str, Any]:
    """Get prediction markets from all platforms."""
    try:
        from monitoring.prediction_markets import MarketCategory
        
        # Get aggregator from app state (persists across module reloads)
        aggregator = getattr(request.app.state, 'prediction_aggregator', None)
        
        if not aggregator:
            logger.warning("Prediction aggregator not found in app.state, falling back to singleton")
            from monitoring.prediction_markets import get_prediction_aggregator
            aggregator = get_prediction_aggregator()
        
        logger.info(f"API using aggregator id={id(aggregator)}, markets={len(aggregator._all_markets)}")
        
        if category:
            try:
                cat = MarketCategory(category.lower())
                markets = aggregator.get_markets_by_category(cat, limit)
            except ValueError:
                markets = aggregator.get_all_markets(limit)
        else:
            markets = aggregator.get_all_markets(limit)
        
        return {
            "markets": [m.to_dict() for m in markets],
            "count": len(markets),
            "status": aggregator.get_status(),
        }
    except Exception as e:
        import traceback
        logger.error(f"Prediction markets error: {type(e).__name__}: {e}")
        logger.error(traceback.format_exc())
        return {"markets": [], "error": str(e)}


@router.get("/predictions/drift")
async def get_odds_drift_signals(request: Request, limit: int = 20) -> Dict[str, Any]:
    """Get recent odds drift signals."""
    try:
        # Get aggregator from app state
        aggregator = getattr(request.app.state, 'prediction_aggregator', None)
        
        if not aggregator:
            aggregator = get_prediction_aggregator()
        signals = aggregator.get_drift_signals(limit)
        
        # Return mock data if aggregator is still warming up
        if not signals:
            return {
                "signals": [],
                "count": 0,
                "status": "warming_up",
                "message": "Prediction market aggregator is fetching data"
            }
        
        return {
            "signals": [s.to_dict() for s in signals],
            "count": len(signals),
            "status": "active"
        }
    except Exception as e:
        logger.error(f"Drift signals error: {e}")
        return {
            "signals": [],
            "count": 0,
            "status": "error",
            "error": str(e)
        }


@router.get("/predictions/arbitrage")
async def get_arbitrage_opportunities(request: Request, limit: int = 10) -> Dict[str, Any]:
    """Get cross-platform arbitrage opportunities."""
    try:
        # Get aggregator from app state
        aggregator = getattr(request.app.state, 'prediction_aggregator', None)
        
        if not aggregator:
            aggregator = get_prediction_aggregator()
        opportunities = aggregator.get_arbitrage_opportunities(limit)
        
        # Return mock data if aggregator is still warming up
        if not opportunities:
            return {
                "opportunities": [],
                "count": 0,
                "status": "warming_up",
                "message": "Prediction market aggregator is fetching data"
            }
        
        return {
            "opportunities": [o.to_dict() for o in opportunities],
            "count": len(opportunities),
            "status": "active"
        }
    except Exception as e:
        logger.error(f"Arbitrage error: {e}")
        return {
            "opportunities": [],
            "count": 0,
            "status": "error",
            "error": str(e)
        }


@router.get("/predictions/decay/{market_id}")
async def get_market_decay_metrics(market_id: str) -> Dict[str, Any]:
    """Get resolution decay metrics for a market."""
    try:
        
        aggregator = get_prediction_aggregator()
        metrics = aggregator.get_decay_metrics(market_id)
        
        if not metrics:
            return {"error": "Market not found or no decay metrics available"}
        
        return {"metrics": metrics.to_dict()}
    except Exception as e:
        logger.error(f"Decay metrics error: {e}")
        return {"error": str(e)}


@router.get("/predictions/urgent")
async def get_urgent_markets() -> Dict[str, Any]:
    """Get markets with high exit urgency (approaching resolution)."""
    try:
        
        aggregator = get_prediction_aggregator()
        urgent = aggregator.get_high_urgency_markets()
        
        # Return mock data if aggregator is still warming up
        if not urgent:
            return {
                "markets": [],
                "count": 0,
                "status": "warming_up",
                "message": "Prediction market aggregator is fetching data"
            }
        
        return {
            "markets": [
                {
                    "market": m.to_dict(),
                    "decay": d.to_dict(),
                }
                for m, d in urgent
            ],
            "count": len(urgent),
            "status": "active"
        }
    except Exception as e:
        logger.error(f"Urgent markets error: {e}")
        return {
            "markets": [],
            "count": 0,
            "status": "error",
            "error": str(e)
        }


@router.post("/predictions/start")
async def start_prediction_markets() -> Dict[str, Any]:
    """Start prediction market aggregation."""
    try:
        from monitoring.prediction_markets import start_prediction_markets as start_pm
        
        aggregator = await start_pm()
        
        return {
            "status": "started",
            "message": "Prediction market aggregation started",
        }
    except Exception as e:
        logger.error(f"Failed to start prediction markets: {e}")
        return {"status": "error", "error": str(e)}


@router.get("/predictions/status")
async def get_prediction_status() -> Dict[str, Any]:
    """Get prediction market aggregator status."""
    try:
        
        aggregator = get_prediction_aggregator()
        return aggregator.get_status()
    except Exception as e:
        logger.error(f"Prediction status error: {e}")
        return {"error": str(e)}


# ============================================
# CONSENSUS ENGINE ENDPOINTS
# ============================================

@router.get("/consensus/status")
async def get_consensus_status() -> Dict[str, Any]:
    """Get consensus engine status."""
    try:
        from core.consensus_engine import get_consensus_engine
        
        engine = get_consensus_engine()
        
        return {
            "running": engine.running,
            "pending_votes": len(engine.pending_votes),
            "quorum_threshold": engine.quorum_threshold,
            "min_votes": engine.min_votes,
            "consensus_interval": engine.consensus_interval,
            "last_consensus_time": engine.last_consensus_time,
            "trust_scores": dict(engine.trust_scores),
        }
    except Exception as e:
        logger.error(f"Consensus status error: {e}")
        return {"error": str(e)}


@router.get("/consensus/votes")
async def get_pending_votes() -> Dict[str, Any]:
    """Get current pending votes."""
    try:
        
        engine = get_consensus_engine()
        
        votes = [
            {
                "agent_id": v.agent_id,
                "proposal": v.proposal,
                "signal": v.signal,
                "confidence": v.confidence,
                "weight": v.weight,
                "timestamp": v.timestamp,
            }
            for v in engine.pending_votes.values()
        ]
        
        return {
            "votes": votes,
            "count": len(votes),
        }
    except Exception as e:
        logger.error(f"Pending votes error: {e}")
        return {"votes": [], "error": str(e)}


@router.post("/consensus/start")
async def start_consensus_engine() -> Dict[str, Any]:
    """Start the consensus engine."""
    try:
        
        engine = get_consensus_engine()
        await engine.start()
        
        return {
            "status": "started",
            "message": "Consensus engine started",
        }
    except Exception as e:
        logger.error(f"Failed to start consensus: {e}")
        return {"status": "error", "error": str(e)}


@router.post("/consensus/stop")
async def stop_consensus_engine() -> Dict[str, Any]:
    """Stop the consensus engine."""
    try:
        
        engine = get_consensus_engine()
        await engine.stop()
        
        return {
            "status": "stopped",
            "message": "Consensus engine stopped",
        }
    except Exception as e:
        logger.error(f"Failed to stop consensus: {e}")
        return {"status": "error", "error": str(e)}


# ============================================
# SIMULATION MINING ENDPOINTS
# ============================================

@router.get("/simulation/status")
async def get_simulation_status() -> Dict[str, Any]:
    """Get simulation miner status."""
    try:
        from simulation.continuous_miner import get_continuous_miner
        
        miner = get_continuous_miner()
        
        return {
            "running": miner.running,
            "current_block": miner.current_block,
            "chain_length": len(miner.chain),
            "last_hash": miner.last_hash,
            "block_interval": miner.block_interval,
            "base_reward": miner.base_reward,
            "pending_decisions": len(miner.pending_decisions),
            "strategies": {k: v for k, v in miner.strategies.items()},
        }
    except Exception as e:
        logger.error(f"Simulation status error: {e}")
        return {"error": str(e)}


@router.get("/simulation/chain")
async def get_simulation_chain(limit: int = 20) -> Dict[str, Any]:
    """Get recent simulation blocks."""
    try:
        
        miner = get_continuous_miner()
        
        # Get most recent blocks
        blocks = miner.chain[-limit:] if miner.chain else []
        
        return {
            "blocks": [b.to_dict() for b in reversed(blocks)],
            "count": len(blocks),
            "total_blocks": len(miner.chain),
        }
    except Exception as e:
        logger.error(f"Simulation chain error: {e}")
        return {"blocks": [], "error": str(e)}


@router.get("/simulation/block/{block_number}")
async def get_simulation_block(block_number: int) -> Dict[str, Any]:
    """Get a specific simulation block."""
    try:
        
        miner = get_continuous_miner()
        
        if block_number < 1 or block_number > len(miner.chain):
            return {"error": f"Block {block_number} not found"}
        
        block = miner.chain[block_number - 1]
        return {"block": block.to_dict()}
    except Exception as e:
        logger.error(f"Block fetch error: {e}")
        return {"error": str(e)}


@router.get("/simulation/strategies")
async def get_simulation_strategies() -> Dict[str, Any]:
    """Get strategy performance metrics."""
    try:
        
        miner = get_continuous_miner()
        
        strategies = []
        for name, data in miner.strategies.items():
            avg_confidence = data["total_confidence"] / max(data["decisions"], 1)
            strategies.append({
                "name": name,
                "decisions": data["decisions"],
                "total_confidence": data["total_confidence"],
                "avg_confidence": avg_confidence,
                "useful_work": data["useful_work"],
            })
        
        # Sort by useful work
        strategies.sort(key=lambda x: x["useful_work"], reverse=True)
        
        return {
            "strategies": strategies,
            "count": len(strategies),
        }
    except Exception as e:
        logger.error(f"Strategies error: {e}")
        return {"strategies": [], "error": str(e)}


@router.post("/simulation/start")
async def start_simulation_miner() -> Dict[str, Any]:
    """Start the simulation miner."""
    try:
        
        miner = get_continuous_miner()
        await miner.start()
        
        return {
            "status": "started",
            "message": "Simulation miner started",
        }
    except Exception as e:
        logger.error(f"Failed to start simulation: {e}")
        return {"status": "error", "error": str(e)}


@router.post("/simulation/stop")
async def stop_simulation_miner() -> Dict[str, Any]:
    """Stop the simulation miner."""
    try:
        
        miner = get_continuous_miner()
        await miner.stop()
        
        return {
            "status": "stopped",
            "message": "Simulation miner stopped",
        }
    except Exception as e:
        logger.error(f"Failed to stop simulation: {e}")
        return {"status": "error", "error": str(e)}


# ============================================
# AUDIT TRAIL ENDPOINTS
# ============================================

@router.get("/audit/status")
async def get_audit_status() -> Dict[str, Any]:
    """Get audit trail status."""
    try:
        from core.audit_trail import get_audit_trail
        
        audit = get_audit_trail()
        
        return {
            "running": audit.running,
            "total_entries": len(audit.entries),
            "sequence": audit.sequence,
            "last_hash": audit.last_hash[:16] + "..." if audit.last_hash != "genesis" else "genesis",
            "storage_path": str(audit.storage_path),
        }
    except Exception as e:
        logger.error(f"Audit status error: {e}")
        return {"error": str(e)}


@router.get("/audit/entries")
async def get_audit_entries(limit: int = 50, offset: int = 0) -> Dict[str, Any]:
    """Get audit trail entries."""
    try:
        
        audit = get_audit_trail()
        entries = audit.get_entries(limit=limit, offset=offset)
        
        return {
            "entries": entries,
            "count": len(entries),
            "total": len(audit.entries),
            "offset": offset,
        }
    except Exception as e:
        logger.error(f"Audit entries error: {e}")
        return {"entries": [], "error": str(e)}


@router.get("/audit/recent")
async def get_recent_audit_entries(limit: int = 20) -> Dict[str, Any]:
    """Get most recent audit entries."""
    try:
        
        audit = get_audit_trail()
        
        # Get last N entries
        start = max(0, len(audit.entries) - limit)
        entries = [e.to_dict() for e in audit.entries[start:]]
        entries.reverse()  # Most recent first
        
        return {
            "entries": entries,
            "count": len(entries),
        }
    except Exception as e:
        logger.error(f"Recent audit error: {e}")
        return {"entries": [], "error": str(e)}


@router.get("/audit/by-source/{source}")
async def get_audit_by_source(source: str, limit: int = 50) -> Dict[str, Any]:
    """Get audit entries by source."""
    try:
        
        audit = get_audit_trail()
        entries = audit.get_by_source(source, limit=limit)
        
        return {
            "entries": entries,
            "count": len(entries),
            "source": source,
        }
    except Exception as e:
        logger.error(f"Audit by source error: {e}")
        return {"entries": [], "error": str(e)}


@router.get("/audit/verify")
async def verify_audit_chain() -> Dict[str, Any]:
    """Verify the integrity of the audit chain."""
    try:
        
        audit = get_audit_trail()
        is_valid = audit.verify_chain()
        
        return {
            "valid": is_valid,
            "entries_verified": len(audit.entries),
            "message": "Chain integrity verified" if is_valid else "Chain integrity compromised",
        }
    except Exception as e:
        logger.error(f"Audit verify error: {e}")
        return {"valid": False, "error": str(e)}


@router.get("/audit/entry/{sequence}")
async def get_audit_entry(sequence: int) -> Dict[str, Any]:
    """Get a specific audit entry by sequence number."""
    try:
        
        audit = get_audit_trail()
        
        if sequence < 1 or sequence > len(audit.entries):
            return {"error": f"Entry {sequence} not found"}
        
        entry = audit.entries[sequence - 1]
        return {"entry": entry.to_dict()}
    except Exception as e:
        logger.error(f"Audit entry error: {e}")
        return {"error": str(e)}


@router.post("/audit/start")
async def start_audit_trail() -> Dict[str, Any]:
    """Start the audit trail."""
    try:
        
        audit = get_audit_trail()
        await audit.start()
        
        return {
            "status": "started",
            "message": "Audit trail started",
        }
    except Exception as e:
        logger.error(f"Failed to start audit: {e}")
        return {"status": "error", "error": str(e)}


# ============================================
# EXECUTION ENGINE ENDPOINTS
# ============================================

@router.get("/execution/status")
async def get_execution_status() -> Dict[str, Any]:
    """Get execution engine status and account summary."""
    try:
        from trading.execution import get_execution_engine
        
        engine = get_execution_engine()
        summary = engine.get_account_summary()
        
        return {
            "running": engine._running,
            **summary,
        }
    except Exception as e:
        logger.error(f"Execution status error: {e}")
        return {"error": str(e)}


@router.get("/execution/positions")
async def get_execution_positions() -> Dict[str, Any]:
    """Get all open positions."""
    try:
        
        engine = get_execution_engine()
        positions = engine.get_all_positions()
        
        return {
            "positions": [
                {
                    "position_id": p.position_id,
                    "symbol": p.symbol,
                    "side": p.side.value,
                    "quantity": p.quantity,
                    "entry_price": p.entry_price,
                    "current_price": p.current_price,
                    "unrealized_pnl": p.unrealized_pnl,
                    "realized_pnl": p.realized_pnl,
                    "stop_loss": p.stop_loss,
                    "take_profit": p.take_profit,
                    "opened_at": p.opened_at,
                }
                for p in positions
            ],
            "count": len(positions),
        }
    except Exception as e:
        logger.error(f"Positions error: {e}")
        return {"positions": [], "error": str(e)}


@router.get("/execution/orders")
async def get_execution_orders() -> Dict[str, Any]:
    """Get open orders."""
    try:
        
        engine = get_execution_engine()
        orders = engine.get_open_orders()
        
        return {
            "orders": [
                {
                    "order_id": o.order_id,
                    "symbol": o.symbol,
                    "side": o.side.value,
                    "order_type": o.order_type.value,
                    "quantity": o.quantity,
                    "price": o.price,
                    "status": o.status.value,
                    "filled_quantity": o.filled_quantity,
                    "filled_price": o.filled_price,
                    "created_at": o.created_at,
                }
                for o in orders
            ],
            "count": len(orders),
        }
    except Exception as e:
        logger.error(f"Orders error: {e}")
        return {"orders": [], "error": str(e)}


@router.get("/execution/history")
async def get_execution_history(limit: int = 50) -> Dict[str, Any]:
    """Get order history."""
    try:
        
        engine = get_execution_engine()
        history = engine._order_history[-limit:]
        
        return {
            "orders": [
                {
                    "order_id": o.order_id,
                    "symbol": o.symbol,
                    "side": o.side.value,
                    "order_type": o.order_type.value,
                    "quantity": o.quantity,
                    "filled_price": o.filled_price,
                    "status": o.status.value,
                    "filled_at": o.filled_at,
                }
                for o in reversed(history)
            ],
            "count": len(history),
        }
    except Exception as e:
        logger.error(f"History error: {e}")
        return {"orders": [], "error": str(e)}


@router.post("/execution/order")
async def submit_execution_order(
    symbol: str,
    side: str,
    quantity: float,
    order_type: str = "market",
    price: float = None,
    stop_loss: float = None,
    take_profit: float = None,
) -> Dict[str, Any]:
    """Submit a new order."""
    try:
        from trading.execution import get_execution_engine, OrderSide, OrderType
        
        engine = get_execution_engine()
        
        order_side = OrderSide.BUY if side.lower() == "buy" else OrderSide.SELL
        o_type = OrderType.MARKET if order_type.lower() == "market" else OrderType.LIMIT
        
        order = await engine.submit_order(
            symbol=symbol,
            side=order_side,
            quantity=quantity,
            order_type=o_type,
            price=price,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )
        
        return {
            "status": "submitted",
            "order_id": order.order_id,
            "filled": order.status.value == "filled",
            "filled_price": order.filled_price,
        }
    except Exception as e:
        logger.error(f"Order submission error: {e}")
        return {"status": "error", "error": str(e)}


@router.post("/execution/close/{symbol}")
async def close_execution_position(symbol: str, reason: str = "manual") -> Dict[str, Any]:
    """Close a position."""
    try:
        
        engine = get_execution_engine()
        order = await engine.close_position(symbol, reason=reason)
        
        if order:
            return {
                "status": "closed",
                "order_id": order.order_id,
                "symbol": symbol,
            }
        else:
            return {"status": "not_found", "message": f"No position for {symbol}"}
    except Exception as e:
        logger.error(f"Close position error: {e}")
        return {"status": "error", "error": str(e)}


@router.post("/execution/start")
async def start_execution_engine() -> Dict[str, Any]:
    """Start the execution engine."""
    try:
        
        engine = get_execution_engine()
        await engine.start()
        
        return {
            "status": "started",
            "message": "Execution engine started",
            "mode": engine.config.mode.value,
        }
    except Exception as e:
        logger.error(f"Failed to start execution: {e}")
        return {"status": "error", "error": str(e)}


@router.post("/execution/mode/{mode}")
async def set_execution_mode(mode: str) -> Dict[str, Any]:
    """Set execution mode (paper/live/disabled)."""
    try:
        from trading.execution import get_execution_engine, ExecutionMode
        
        engine = get_execution_engine()
        
        mode_map = {
            "paper": ExecutionMode.PAPER,
            "live": ExecutionMode.LIVE,
            "disabled": ExecutionMode.DISABLED,
        }
        
        if mode.lower() not in mode_map:
            return {"status": "error", "error": f"Invalid mode: {mode}"}
        
        engine.config.mode = mode_map[mode.lower()]
        
        return {
            "status": "updated",
            "mode": engine.config.mode.value,
            "message": f"Execution mode set to {mode}",
        }
    except Exception as e:
        logger.error(f"Failed to set mode: {e}")
        return {"status": "error", "error": str(e)}


@router.post("/execution/configure")
async def configure_execution(
    exchange: str = None,
    api_key: str = None,
    api_secret: str = None,
    sandbox: bool = True,
    max_position_usd: float = None,
    max_exposure_usd: float = None,
) -> Dict[str, Any]:
    """Configure execution engine settings."""
    try:
        
        engine = get_execution_engine()
        
        if exchange:
            engine.config.exchange = exchange
        if api_key:
            engine.config.api_key = api_key
        if api_secret:
            engine.config.api_secret = api_secret
        if sandbox is not None:
            engine.config.sandbox = sandbox
        if max_position_usd:
            engine.config.max_position_size_usd = max_position_usd
        if max_exposure_usd:
            engine.config.max_total_exposure_usd = max_exposure_usd
        
        return {
            "status": "configured",
            "exchange": engine.config.exchange,
            "sandbox": engine.config.sandbox,
            "max_position_usd": engine.config.max_position_size_usd,
            "max_exposure_usd": engine.config.max_total_exposure_usd,
            "api_key_set": bool(engine.config.api_key),
        }
    except Exception as e:
        logger.error(f"Failed to configure execution: {e}")
        return {"status": "error", "error": str(e)}


@router.get("/execution/config")
async def get_execution_config() -> Dict[str, Any]:
    """Get current execution configuration."""
    try:
        
        engine = get_execution_engine()
        
        return {
            "mode": engine.config.mode.value,
            "exchange": engine.config.exchange,
            "sandbox": engine.config.sandbox,
            "max_position_usd": engine.config.max_position_size_usd,
            "max_exposure_usd": engine.config.max_total_exposure_usd,
            "max_leverage": engine.config.max_leverage,
            "default_stop_loss_pct": engine.config.default_stop_loss_pct,
            "default_take_profit_pct": engine.config.default_take_profit_pct,
            "api_key_set": bool(engine.config.api_key),
            "require_consensus": engine.config.require_consensus,
        }
    except Exception as e:
        logger.error(f"Failed to get config: {e}")
        return {"error": str(e)}


@router.post("/execution/sync")
async def sync_with_exchange() -> Dict[str, Any]:
    """Synchronize positions and balance with exchange."""
    try:
        
        engine = get_execution_engine()
        result = await engine.sync_with_exchange()
        
        return result
    except Exception as e:
        logger.error(f"Sync failed: {e}")
        return {"status": "error", "error": str(e)}


# ============================================
# PERFORMANCE ANALYTICS ENDPOINTS
# ============================================

@router.get("/analytics/summary")
async def get_analytics_summary() -> Dict[str, Any]:
    """Get performance analytics summary."""
    try:
        from analytics.performance import get_performance_tracker
        
        tracker = get_performance_tracker()
        return tracker.get_summary()
    except Exception as e:
        logger.error(f"Analytics summary error: {e}")
        return {"error": str(e)}


@router.get("/analytics/trades")
async def get_analytics_trades(limit: int = 20) -> Dict[str, Any]:
    """Get recent trades."""
    try:
        
        tracker = get_performance_tracker()
        return {
            "trades": tracker.get_recent_trades(limit),
            "count": len(tracker._trades),
        }
    except Exception as e:
        logger.error(f"Analytics trades error: {e}")
        return {"trades": [], "error": str(e)}


@router.get("/analytics/equity-curve")
async def get_equity_curve(points: int = 100) -> Dict[str, Any]:
    """Get equity curve data."""
    try:
        
        tracker = get_performance_tracker()
        return {
            "curve": tracker.get_equity_curve(points),
        }
    except Exception as e:
        logger.error(f"Equity curve error: {e}")
        return {"curve": [], "error": str(e)}


@router.get("/portfolio/positions")
async def get_portfolio_positions() -> Dict[str, Any]:
    """Get current open positions."""
    try:
        from trading.execution import get_optimal_executor
        
        executor = get_optimal_executor()
        positions = []
        
        # Get positions from executor if available
        if hasattr(executor, 'get_positions'):
            positions = executor.get_positions()
        
        return {
            "positions": positions,
            "count": len(positions),
            "status": "success"
        }
    except Exception as e:
        logger.error(f"Portfolio positions error: {e}")
        return {
            "positions": [],
            "count": 0,
            "status": "error",
            "error": str(e)
        }


@router.get("/audit/trail")
async def get_audit_trail(limit: int = 100) -> Dict[str, Any]:
    """Get audit trail events."""
    try:
        
        audit = get_audit_trail()
        events = []
        
        # Get recent events from audit trail
        if hasattr(audit, 'get_recent_events'):
            events = audit.get_recent_events(limit)
        elif hasattr(audit, '_events'):
            events = list(audit._events)[-limit:]
        
        # Format events for dashboard
        formatted_events = []
        for event in events:
            if isinstance(event, dict):
                formatted_events.append(event)
            elif hasattr(event, 'to_dict'):
                formatted_events.append(event.to_dict())
            else:
                formatted_events.append({
                    "type": getattr(event, 'type', 'UNKNOWN'),
                    "message": str(event),
                    "timestamp": getattr(event, 'timestamp', None),
                    "payload": {}
                })
        
        return {
            "events": formatted_events,
            "count": len(formatted_events),
            "status": "success"
        }
    except Exception as e:
        logger.error(f"Audit trail error: {e}")
        return {
            "events": [],
            "count": 0,
            "status": "error",
            "error": str(e)
        }


@router.get("/analytics/agents")
async def get_agent_analytics() -> Dict[str, Any]:
    """Get performance breakdown by agent."""
    try:
        
        tracker = get_performance_tracker()
        return {
            "agents": tracker.get_agent_performance(),
        }
    except Exception as e:
        logger.error(f"Agent analytics error: {e}")
        return {"agents": {}, "error": str(e)}


@router.get("/analytics/daily-pnl")
async def get_daily_pnl(days: int = 7) -> Dict[str, Any]:
    """Get daily P&L for the last N days."""
    try:
        
        tracker = get_performance_tracker()
        return {
            "daily": tracker.get_daily_pnl(days),
        }
    except Exception as e:
        logger.error(f"Daily PnL error: {e}")
        return {"daily": [], "error": str(e)}


# ============================================
# ALERT SYSTEM ENDPOINTS
# ============================================

@router.get("/alerts/summary")
async def get_alerts_summary() -> Dict[str, Any]:
    """Get alert system summary."""
    try:
        from core.alerts import get_alert_manager
        
        manager = get_alert_manager()
        return manager.get_summary()
    except Exception as e:
        logger.error(f"Alerts summary error: {e}")
        return {"error": str(e)}


@router.get("/alerts")
async def get_alerts(status: str = None) -> Dict[str, Any]:
    """Get all alerts."""
    try:
        from core.alerts import get_alert_manager, AlertStatus
        
        manager = get_alert_manager()
        
        status_filter = None
        if status:
            status_filter = AlertStatus(status)
        
        alerts = manager.get_alerts(status_filter)
        return {
            "alerts": [a.to_dict() for a in alerts],
            "count": len(alerts),
        }
    except Exception as e:
        logger.error(f"Get alerts error: {e}")
        return {"alerts": [], "error": str(e)}


@router.post("/alerts/price")
async def create_price_alert(
    symbol: str,
    target_price: float,
    direction: str = "above",
    priority: str = "medium",
) -> Dict[str, Any]:
    """Create a price alert."""
    try:
        from core.alerts import get_alert_manager, AlertType, AlertPriority
        
        manager = get_alert_manager()
        
        alert_type = AlertType.PRICE_ABOVE if direction == "above" else AlertType.PRICE_BELOW
        alert_priority = AlertPriority(priority)
        
        alert = manager.create_price_alert(
            symbol=symbol,
            alert_type=alert_type,
            target_price=target_price,
            priority=alert_priority,
        )
        
        return {
            "status": "created",
            "alert": alert.to_dict(),
        }
    except Exception as e:
        logger.error(f"Create alert error: {e}")
        return {"status": "error", "error": str(e)}


@router.delete("/alerts/{alert_id}")
async def delete_alert(alert_id: str) -> Dict[str, Any]:
    """Delete an alert."""
    try:
        
        manager = get_alert_manager()
        success = manager.delete_alert(alert_id)
        
        return {
            "status": "deleted" if success else "not_found",
            "alert_id": alert_id,
        }
    except Exception as e:
        logger.error(f"Delete alert error: {e}")
        return {"status": "error", "error": str(e)}


@router.get("/notifications")
async def get_notifications(unread_only: bool = False) -> Dict[str, Any]:
    """Get notifications."""
    try:
        
        manager = get_alert_manager()
        notifications = manager.get_notifications(unread_only)
        
        return {
            "notifications": [n.to_dict() for n in notifications],
            "count": len(notifications),
        }
    except Exception as e:
        logger.error(f"Get notifications error: {e}")
        return {"notifications": [], "error": str(e)}


@router.post("/notifications/{notification_id}/read")
async def mark_notification_read(notification_id: str) -> Dict[str, Any]:
    """Mark a notification as read."""
    try:
        
        manager = get_alert_manager()
        success = manager.mark_notification_read(notification_id)
        
        return {
            "status": "marked_read" if success else "not_found",
        }
    except Exception as e:
        logger.error(f"Mark read error: {e}")
        return {"status": "error", "error": str(e)}


@router.post("/notifications/read-all")
async def mark_all_notifications_read() -> Dict[str, Any]:
    """Mark all notifications as read."""
    try:
        
        manager = get_alert_manager()
        count = manager.mark_all_read()
        
        return {
            "status": "success",
            "marked_read": count,
        }
    except Exception as e:
        logger.error(f"Mark all read error: {e}")
        return {"status": "error", "error": str(e)}


# ============================================
# HEALTH MONITORING ENDPOINTS
# ============================================

@router.get("/health")
async def get_health() -> Dict[str, Any]:
    """Get system health status."""
    try:
        from core.health import get_health_monitor
        
        monitor = get_health_monitor()
        await monitor.check_all()
        
        return monitor.get_summary()
    except Exception as e:
        logger.error(f"Health check error: {e}")
        return {
            "status": "unhealthy",
            "error": str(e),
        }


@router.get("/health/component/{component}")
async def get_component_health(component: str) -> Dict[str, Any]:
    """Get health of a specific component."""
    try:
        
        monitor = get_health_monitor()
        await monitor.check_all()
        
        if component in monitor._components:
            return monitor._components[component].to_dict()
        else:
            return {
                "error": f"Component '{component}' not found",
                "available": list(monitor._components.keys()),
            }
    except Exception as e:
        logger.error(f"Component health error: {e}")
        return {"error": str(e)}


@router.get("/health/ping")
async def health_ping() -> Dict[str, Any]:
    """Simple health ping endpoint."""
    return {
        "status": "ok",
        "timestamp": time.time(),
    }


# ============================================
# CONFIGURATION ENDPOINTS
# ============================================

@router.get("/config")
async def get_config() -> Dict[str, Any]:
    """Get current configuration (excluding secrets)."""
    try:
        from config.settings import get_settings
        
        settings = get_settings()
        return settings.to_dict()
    except Exception as e:
        logger.error(f"Config error: {e}")
        return {"error": str(e)}


@router.get("/config/validate")
async def validate_config() -> Dict[str, Any]:
    """Validate current configuration."""
    try:
        
        settings = get_settings()
        warnings = settings.validate()
        
        return {
            "valid": len(warnings) == 0,
            "warnings": warnings,
            "environment": settings.environment.value,
        }
    except Exception as e:
        logger.error(f"Config validation error: {e}")
        return {"valid": False, "error": str(e)}


# ============================================
# BACKTESTING ENDPOINTS
# ============================================

@router.get("/backtest/strategies")
async def get_backtest_strategies() -> Dict[str, Any]:
    """Get available backtesting strategies."""
    try:
        from backtesting.engine import get_backtest_engine
        
        engine = get_backtest_engine()
        return {
            "strategies": engine.get_available_strategies(),
            "summary": engine.get_summary(),
        }
    except Exception as e:
        logger.error(f"Backtest strategies error: {e}")
        return {"strategies": [], "error": str(e)}


@router.post("/backtest/run")
async def run_backtest(
    strategy: str,
    symbol: str = "BTC/USDT",
    days: int = 30,
    initial_capital: float = 100000.0,
) -> Dict[str, Any]:
    """Run a backtest."""
    try:
        from backtesting.engine import get_backtest_engine, BacktestConfig
        from datetime import datetime, timedelta, timezone
        import uuid
        
        engine = get_backtest_engine()
        
        config = BacktestConfig(
            backtest_id=f"bt_{uuid.uuid4().hex[:8]}",
            strategy_name=strategy,
            symbols=[symbol],
            start_date=datetime.now(timezone.utc) - timedelta(days=days),
            end_date=datetime.now(timezone.utc),
            initial_capital=initial_capital,
        )
        
        result = await engine.run_backtest(config)
        
        return {
            "status": "completed",
            "result": result.to_dict(),
        }
    except Exception as e:
        logger.error(f"Backtest run error: {e}")
        return {"status": "error", "error": str(e)}


@router.get("/backtest/results")
async def get_backtest_results() -> Dict[str, Any]:
    """Get all backtest results."""
    try:
        
        engine = get_backtest_engine()
        results = engine.get_all_results()
        
        return {
            "results": [r.to_dict() for r in results],
            "count": len(results),
        }
    except Exception as e:
        logger.error(f"Backtest results error: {e}")
        return {"results": [], "error": str(e)}


@router.get("/backtest/result/{backtest_id}")
async def get_backtest_result(backtest_id: str) -> Dict[str, Any]:
    """Get a specific backtest result."""
    try:
        
        engine = get_backtest_engine()
        result = engine.get_result(backtest_id)
        
        if result:
            return {"result": result.to_dict()}
        else:
            return {"error": f"Backtest {backtest_id} not found"}
    except Exception as e:
        logger.error(f"Backtest result error: {e}")
        return {"error": str(e)}


# ============================================
# PORTFOLIO MANAGEMENT ENDPOINTS
# ============================================

@router.get("/portfolio/summary")
async def get_portfolio_summary() -> Dict[str, Any]:
    """Get portfolio summary."""
    try:
        from portfolio.manager import get_portfolio_manager
        
        manager = get_portfolio_manager()
        return manager.get_summary()
    except Exception as e:
        logger.error(f"Portfolio summary error: {e}")
        return {"error": str(e)}


@router.get("/portfolio/holdings")
async def get_portfolio_holdings() -> Dict[str, Any]:
    """Get portfolio holdings."""
    try:
        
        manager = get_portfolio_manager()
        return {
            "holdings": manager.get_holdings(),
            "total_value": manager.total_value,
        }
    except Exception as e:
        logger.error(f"Portfolio holdings error: {e}")
        return {"holdings": [], "error": str(e)}


@router.get("/portfolio/history")
async def get_portfolio_history(limit: int = 30) -> Dict[str, Any]:
    """Get portfolio value history for charting."""
    try:
        
        manager = get_portfolio_manager()
        history = manager.get_value_history(limit=limit)
        
        return {
            "history": history,
            "count": len(history),
        }
    except Exception as e:
        logger.error(f"Portfolio history error: {e}")
        # Return empty history on error
        return {"history": [], "error": str(e)}


@router.get("/portfolio/allocation")
async def get_portfolio_allocation() -> Dict[str, Any]:
    """Get current vs target allocation."""
    try:
        
        manager = get_portfolio_manager()
        return {
            "allocation": manager.get_allocation(),
            "summary": manager.get_summary(),
        }
    except Exception as e:
        logger.error(f"Portfolio allocation error: {e}")
        return {"error": str(e)}


@router.post("/portfolio/target-weights")
async def set_target_weights(weights: Dict[str, float]) -> Dict[str, Any]:
    """Set target portfolio weights."""
    try:
        
        manager = get_portfolio_manager()
        manager.set_target_weights(weights)
        
        return {
            "status": "success",
            "weights": weights,
        }
    except Exception as e:
        logger.error(f"Set weights error: {e}")
        return {"status": "error", "error": str(e)}


@router.get("/portfolio/rebalance")
async def get_rebalance_orders() -> Dict[str, Any]:
    """Get orders needed to rebalance portfolio."""
    try:
        
        manager = get_portfolio_manager()
        orders = manager.calculate_rebalance_orders()
        
        return {
            "orders": [
                {
                    "symbol": o.symbol,
                    "action": o.action,
                    "quantity": o.quantity,
                    "current_weight": o.current_weight,
                    "target_weight": o.target_weight,
                    "estimated_value": o.estimated_value,
                }
                for o in orders
            ],
            "count": len(orders),
        }
    except Exception as e:
        logger.error(f"Rebalance orders error: {e}")
        return {"orders": [], "error": str(e)}


@router.post("/portfolio/position-size")
async def calculate_position_size(
    symbol: str,
    entry_price: float,
    stop_loss: float,
    risk_per_trade: float = 0.02,
) -> Dict[str, Any]:
    """Calculate position size based on risk management."""
    try:
        
        manager = get_portfolio_manager()
        size = manager.calculate_position_size(
            symbol=symbol,
            entry_price=entry_price,
            stop_loss=stop_loss,
            risk_per_trade=risk_per_trade,
        )
        
        return {
            "symbol": symbol,
            "position_size": size,
            "position_value": size * entry_price,
            "risk_amount": manager.total_value * risk_per_trade,
        }
    except Exception as e:
        logger.error(f"Position size error: {e}")
        return {"error": str(e)}


# ============================================
# STREAMING AGENT MESH ENDPOINTS
# ============================================

@router.get("/mesh/status")
async def get_mesh_status() -> Dict[str, Any]:
    """Get streaming agent mesh status."""
    try:
        from agents.agent_mesh import agent_mesh
        
        return {
            "running": agent_mesh.running,
            "total_agents": len(agent_mesh.agents),
            "agents": [
                {
                    "agent_id": a.agent_id,
                    "running": a.running,
                    "model": a.model,
                }
                for a in agent_mesh.agents
            ],
        }
    except Exception as e:
        logger.error(f"Mesh status error: {e}")
        return {"error": str(e)}


@router.get("/mesh/metrics")
async def get_mesh_metrics() -> Dict[str, Any]:
    """Get streaming agent mesh metrics."""
    try:
        
        return agent_mesh.get_metrics()
    except Exception as e:
        logger.error(f"Mesh metrics error: {e}")
        return {"error": str(e)}


@router.get("/mesh/agent/{agent_id}")
async def get_mesh_agent(agent_id: str) -> Dict[str, Any]:
    """Get specific agent details."""
    try:
        
        for agent in agent_mesh.agents:
            if agent.agent_id == agent_id:
                return {
                    "agent_id": agent.agent_id,
                    "running": agent.running,
                    "model": agent.model,
                    "metrics": agent.get_metrics(),
                }
        
        return {"error": f"Agent {agent_id} not found"}
    except Exception as e:
        logger.error(f"Agent details error: {e}")
        return {"error": str(e)}


@router.post("/mesh/start")
async def start_mesh() -> Dict[str, Any]:
    """Start the streaming agent mesh."""
    try:
        
        if not agent_mesh.agents:
            await agent_mesh.initialize()
        await agent_mesh.start()
        
        return {
            "status": "started",
            "message": "Agent mesh started",
            "agents": len(agent_mesh.agents),
        }
    except Exception as e:
        logger.error(f"Failed to start mesh: {e}")
        return {"status": "error", "error": str(e)}


@router.post("/mesh/stop")
async def stop_mesh() -> Dict[str, Any]:
    """Stop the streaming agent mesh."""
    try:
        
        await agent_mesh.stop()
        
        return {
            "status": "stopped",
            "message": "Agent mesh stopped",
        }
    except Exception as e:
        logger.error(f"Failed to stop mesh: {e}")
        return {"status": "error", "error": str(e)}

"""
MERID System Orchestrator

Production orchestration layer that connects all MERID systems:
- OPS (Regime Intelligence)
- GOV (Governance & Defense)
- FIN (Execution Dominance)
- TREASURY (Capital Preservation)
- ARCHIVE (Memory & Forensics)

This is the central nervous system of MERID, enforcing authority boundaries
and coordinating inter-system communication according to the Master Build Directive.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Callable

from core.intersystem_api import (
    get_intersystem_api,
    InterSystemAPI,
    Intent,
    IntentStatus,
    ExecutionConstraints,
    ExecutionReport,
    ProfitDeposit,
    RiskPreview,
    ShadowSimulation,
    PositionRequest,
    EmergencyFreeze,
    FreezeReason,
    FreezeSeverity,
    MeridSystem,
    ExecutionMode,
)
from core.streaming_bus import get_event_bus, EventChannel, StreamEvent
from core.consensus_engine import get_consensus_engine
from utils.logger import get_logger

logger = get_logger("core.system_orchestrator")


class OrchestratorState(Enum):
    """Orchestrator operational states."""
    INITIALIZING = "initializing"
    RUNNING = "running"
    PAUSED = "paused"
    FROZEN = "frozen"
    SHUTDOWN = "shutdown"


@dataclass
class SystemHealth:
    """Health status of a MERID system."""
    system: MeridSystem
    healthy: bool
    last_heartbeat: float
    error_count: int = 0
    latency_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "system": self.system.value,
            "healthy": self.healthy,
            "last_heartbeat": self.last_heartbeat,
            "error_count": self.error_count,
            "latency_ms": round(self.latency_ms, 2),
        }


@dataclass
class OrchestratorMetrics:
    """Orchestrator performance metrics."""
    intents_processed: int = 0
    intents_approved: int = 0
    intents_rejected: int = 0
    executions_completed: int = 0
    executions_failed: int = 0
    profits_deposited: float = 0.0
    freezes_triggered: int = 0
    
    # Timing
    avg_intent_latency_ms: float = 0.0
    avg_execution_latency_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "intents_processed": self.intents_processed,
            "intents_approved": self.intents_approved,
            "intents_rejected": self.intents_rejected,
            "executions_completed": self.executions_completed,
            "executions_failed": self.executions_failed,
            "profits_deposited": round(self.profits_deposited, 2),
            "freezes_triggered": self.freezes_triggered,
            "avg_intent_latency_ms": round(self.avg_intent_latency_ms, 2),
            "avg_execution_latency_ms": round(self.avg_execution_latency_ms, 2),
        }


class SystemOrchestrator:
    """
    Central orchestrator for all MERID systems.
    
    Responsibilities:
    - Initialize and connect all systems
    - Route messages between systems
    - Enforce authority boundaries
    - Monitor system health
    - Handle emergency situations
    """
    
    # Health check interval
    HEALTH_CHECK_INTERVAL = 30.0
    
    # Heartbeat timeout
    HEARTBEAT_TIMEOUT = 60.0
    
    def __init__(self):
        self._state = OrchestratorState.INITIALIZING
        self._api = get_intersystem_api()
        self._bus = get_event_bus()
        self._consensus = get_consensus_engine()
        
        # System health tracking
        self._system_health: Dict[MeridSystem, SystemHealth] = {}
        for system in MeridSystem:
            self._system_health[system] = SystemHealth(
                system=system,
                healthy=False,
                last_heartbeat=0.0,
            )
        
        # Metrics
        self._metrics = OrchestratorMetrics()
        
        # Background tasks
        self._tasks: List[asyncio.Task] = []
        
        # System references (set during initialization)
        self._ops_engine = None
        self._gov_engine = None
        self._fin_engine = None
        self._treasury_engine = None
        self._archive_engine = None
        
        # Register API callbacks
        self._api.on_execution_authorized(self._on_execution_authorized)
        self._api.on_freeze(self._on_freeze)
        self._api.on_unfreeze(self._on_unfreeze)
        self._api.set_archive_callback(self._archive_record)
        
        logger.info("System orchestrator initialized")
    
    async def start(self) -> None:
        """Start the orchestrator and all systems."""
        logger.info("Starting MERID system orchestrator...")
        
        # Initialize systems
        await self._initialize_systems()
        
        # Subscribe to event channels
        await self._subscribe_to_channels()
        
        # Start background tasks
        self._tasks.append(asyncio.create_task(self._health_check_loop()))
        self._tasks.append(asyncio.create_task(self._event_processing_loop()))
        self._tasks.append(asyncio.create_task(self._intent_expiry_loop()))
        
        # Start consensus engine
        await self._consensus.start()
        
        self._state = OrchestratorState.RUNNING
        logger.info("MERID system orchestrator started")
    
    async def stop(self) -> None:
        """Stop the orchestrator and all systems."""
        logger.info("Stopping MERID system orchestrator...")
        
        self._state = OrchestratorState.SHUTDOWN
        
        # Cancel background tasks
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        
        # Stop consensus engine
        await self._consensus.stop()
        
        # Unsubscribe from channels
        await self._bus.unsubscribe("orchestrator")
        
        logger.info("MERID system orchestrator stopped")
    
    async def _initialize_systems(self) -> None:
        """Initialize all MERID systems."""
        # Import and initialize OPS
        try:
            from ops import get_regime_detector, get_anomaly_detection, get_epistemic_engine
            self._ops_engine = {
                "regime": get_regime_detector(),
                "anomaly": get_anomaly_detection(),
                "epistemic": get_epistemic_engine(),
            }
            self._system_health[MeridSystem.OPS].healthy = True
            self._system_health[MeridSystem.OPS].last_heartbeat = time.time()
            logger.info("OPS system initialized")
        except Exception as e:
            logger.error("Failed to initialize OPS: %s", e)
        
        # Import and initialize GOV
        try:
            from governance import get_constitutional, get_authority_enforcer, get_adversarial_engine
            self._gov_engine = {
                "constitutional": get_constitutional(),
                "authority": get_authority_enforcer(),
                "adversarial": get_adversarial_engine(),
            }
            self._system_health[MeridSystem.GOV].healthy = True
            self._system_health[MeridSystem.GOV].last_heartbeat = time.time()
            logger.info("GOV system initialized")
        except Exception as e:
            logger.error("Failed to initialize GOV: %s", e)
        
        # Import and initialize TREASURY
        try:
            from treasury import get_portfolio_geometry, get_capital_thermodynamics, get_vault_manager
            self._treasury_engine = {
                "geometry": get_portfolio_geometry(),
                "thermodynamics": get_capital_thermodynamics(),
                "vaults": get_vault_manager(),
            }
            self._system_health[MeridSystem.TREASURY].healthy = True
            self._system_health[MeridSystem.TREASURY].last_heartbeat = time.time()
            logger.info("TREASURY system initialized")
        except Exception as e:
            logger.error("Failed to initialize TREASURY: %s", e)
        
        # Import and initialize ARCHIVE (optional for Kalshi-only mode)
        try:
            from archive import get_audit_ledger, get_decision_logger, get_replay_engine
            self._archive_engine = {
                "ledger": get_audit_ledger(),
                "decisions": get_decision_logger(),
                "replay": get_replay_engine(),
            }
            self._system_health[MeridSystem.ARCHIVE].healthy = True
            self._system_health[MeridSystem.ARCHIVE].last_heartbeat = time.time()
            logger.info("ARCHIVE system initialized")
        except ImportError:
            # Archive module not available - optional for Kalshi-only mode
            logger.warning("ARCHIVE module not available - skipping (optional for Kalshi-only mode)")
            self._archive_engine = None
        except Exception as e:
            logger.error("Failed to initialize ARCHIVE: %s", e)
            self._archive_engine = None
        
        # FIN is initialized on-demand for execution
        self._system_health[MeridSystem.FIN].healthy = True
        self._system_health[MeridSystem.FIN].last_heartbeat = time.time()
        logger.info("FIN system ready")
    
    async def _subscribe_to_channels(self) -> None:
        """Subscribe to event bus channels."""
        await self._bus.subscribe_named(
            subscriber_id="orchestrator",
            channels=[
                EventChannel.CONSENSUS,
                EventChannel.AGENT_OUTPUT,
                EventChannel.SYSTEM,
            ],
            queue_size=500,
        )
    
    async def _health_check_loop(self) -> None:
        """Periodic health check of all systems."""
        while self._state != OrchestratorState.SHUTDOWN:
            try:
                await asyncio.sleep(self.HEALTH_CHECK_INTERVAL)
                
                now = time.time()
                unhealthy_systems = []
                
                for system, health in self._system_health.items():
                    if now - health.last_heartbeat > self.HEARTBEAT_TIMEOUT:
                        health.healthy = False
                        unhealthy_systems.append(system)
                
                if unhealthy_systems:
                    logger.debug(
                        "Systems without heartbeat: %s",
                        [s.value for s in unhealthy_systems]
                    )
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Health check error: %s", e)
    
    async def _event_processing_loop(self) -> None:
        """Process events from the event bus."""
        while self._state != OrchestratorState.SHUTDOWN:
            try:
                event = await asyncio.wait_for(
                    self._bus.get_event("orchestrator"),
                    timeout=1.0
                )
                
                if event:
                    await self._process_event(event)
                
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Event processing error: %s", e)
    
    async def _intent_expiry_loop(self) -> None:
        """Check for and expire old intents."""
        while self._state != OrchestratorState.SHUTDOWN:
            try:
                await asyncio.sleep(60.0)  # Check every minute
                
                pending = self._api.get_pending_intents()
                for intent in pending:
                    if intent.is_expired():
                        intent.status = IntentStatus.EXPIRED
                        logger.info("Intent expired: %s", intent.intent_id[:8])
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Intent expiry check error: %s", e)
    
    async def _process_event(self, event: StreamEvent) -> None:
        """Process an event from the bus."""
        event_type = event.event_type
        
        # Handle consensus decisions
        if event_type == "consensus_decision":
            await self._handle_consensus_decision(event)
        
        # Handle system heartbeats
        elif event_type == "system_heartbeat":
            self._handle_heartbeat(event)
        
        # Handle anomaly alerts
        elif event_type == "anomaly_alert":
            await self._handle_anomaly(event)
    
    async def _handle_consensus_decision(self, event: StreamEvent) -> None:
        """Handle a consensus decision from the consensus engine."""
        data = event.data
        decision = data.get("decision")
        confidence = data.get("confidence", 0)
        
        if decision in ["EXECUTE_LONG", "EXECUTE_SHORT"] and confidence > 0.6:
            # Create intent from consensus
            await self._create_intent_from_consensus(data)
    
    async def _create_intent_from_consensus(self, consensus_data: Dict[str, Any]) -> None:
        """Create a trading intent from consensus decision."""
        try:
            # Get regime from OPS
            regime = "UNKNOWN"
            if self._ops_engine and self._ops_engine.get("regime"):
                regime_state = self._ops_engine["regime"].get_current_state()
                if regime_state:
                    regime = regime_state.regime.value
            
            # Get epistemic confidence
            epistemic_confidence = 0.5
            if self._ops_engine and self._ops_engine.get("epistemic"):
                snapshot = self._ops_engine["epistemic"].get_snapshot()
                if snapshot:
                    epistemic_confidence = snapshot.overall_confidence
            
            # Create risk preview
            risk_preview = RiskPreview(
                max_drawdown_pct=0.05,  # 5% max drawdown
                corr_exposure=0.3,
                var_95=0.02,
                cvar_95=0.03,
            )
            
            # Create shadow simulation
            shadow_sim = ShadowSimulation(
                expected_return=consensus_data.get("confidence", 0) * 0.01,
                p_loss=1 - consensus_data.get("confidence", 0.5),
                sharpe_ratio=1.5,
                max_adverse_excursion=0.03,
            )
            
            # Determine position
            signal = consensus_data.get("signal", "neutral")
            side = "LONG" if signal == "bullish" else "SHORT"
            
            _asset_sym = consensus_data.get("symbol")
            if not _asset_sym:
                try:
                    from data.asset_universe import get_swarm_eligible
                    _eligible = get_swarm_eligible()
                    _asset_sym = _eligible[0].symbol if _eligible else "BTC/USD"
                except Exception:
                    _asset_sym = "BTC/USD"
            position = PositionRequest(
                asset=_asset_sym,
                side=side,
                notional_usd=10000.0,  # Conservative default
                leverage=1.0,
            )
            
            # Propose intent
            result = await self._api.propose_intent(
                strategy_id="consensus_signal",
                regime=regime,
                confidence=consensus_data.get("confidence", 0.5),
                risk_preview=risk_preview,
                shadow_simulation=shadow_sim,
                position_request=position,
                expiry_ts=time.time() + 3600,  # 1 hour expiry
                epistemic_confidence=epistemic_confidence,
                regime_confidence=0.8,
            )
            
            self._metrics.intents_processed += 1
            
            logger.info(
                "Intent created from consensus: %s signal=%s",
                result["intent_id"][:8], signal
            )
            
        except Exception as e:
            logger.error("Failed to create intent from consensus: %s", e)
    
    def _handle_heartbeat(self, event: StreamEvent) -> None:
        """Handle system heartbeat."""
        source = event.source
        
        try:
            system = MeridSystem(source.upper())
            health = self._system_health.get(system)
            if health:
                health.healthy = True
                health.last_heartbeat = time.time()
                health.latency_ms = event.data.get("latency_ms", 0)
        except ValueError:
            logger.debug("Unknown system source in heartbeat: %s", source)
    
    async def _handle_anomaly(self, event: StreamEvent) -> None:
        """Handle anomaly alert from OPS."""
        severity = event.data.get("severity", "LOW")
        
        if severity in ["HIGH", "CRITICAL"]:
            logger.warning("High severity anomaly detected: %s", event.data)
            
            # Consider triggering freeze for critical anomalies
            if severity == "CRITICAL":
                await self._trigger_emergency_freeze(
                    f"Critical anomaly: {event.data.get('description', 'Unknown')}",
                    FreezeSeverity.CRITICAL
                )
    
    async def _trigger_emergency_freeze(
        self,
        reason: str,
        severity: FreezeSeverity,
    ) -> None:
        """Trigger an emergency freeze."""
        try:
            await self._api.emergency_freeze(
                scope="ALL",
                reason=FreezeReason.ANOMALY_DETECTED,
                severity=severity,
                duration_sec=3600,  # 1 hour default
                authorized_by=["orchestrator", "auto_freeze"],
                halt_new_intents=True,
                cancel_pending_executions=severity == FreezeSeverity.EMERGENCY,
            )
            
            self._metrics.freezes_triggered += 1
            self._state = OrchestratorState.FROZEN
            
        except Exception as e:
            logger.error("Failed to trigger emergency freeze: %s", e)
    
    def _on_execution_authorized(
        self,
        intent: Intent,
        constraints: ExecutionConstraints,
    ) -> None:
        """Callback when execution is authorized."""
        self._metrics.intents_approved += 1
        logger.info(
            "Execution authorized: %s constraints=%s",
            intent.intent_id[:8], constraints.to_dict()
        )
    
    def _on_freeze(self, freeze: EmergencyFreeze) -> None:
        """Callback when freeze is triggered."""
        self._state = OrchestratorState.FROZEN
        logger.warning("System frozen: %s", freeze.freeze_id[:8])
    
    def _on_unfreeze(self, freeze_id: str) -> None:
        """Callback when unfreeze occurs."""
        self._state = OrchestratorState.RUNNING
        logger.info("System unfrozen: %s", freeze_id[:8])
    
    def _archive_record(self, record: Dict[str, Any]) -> None:
        """Archive a record."""
        if self._archive_engine and self._archive_engine.get("ledger"):
            try:
                from archive import EventType
                event_type = EventType(record.get("event_type", "GOVERNANCE_DECISION").lower())
                self._archive_engine["ledger"].record(
                    event_type=event_type,
                    origin_system="ORCHESTRATOR",
                    intent_id=record.get("intent_id"),
                    data=record.get("data", {}),
                )
            except Exception as e:
                logger.error("Failed to archive record: %s", e)
    
    # =========================================================================
    # Public API
    # =========================================================================
    
    async def submit_intent(
        self,
        strategy_id: str,
        regime: str,
        confidence: float,
        risk_preview: RiskPreview,
        shadow_simulation: ShadowSimulation,
        position_request: PositionRequest,
        expiry_ts: float,
    ) -> Dict[str, Any]:
        """Submit a trading intent for approval."""
        if self._state == OrchestratorState.FROZEN:
            return {"error": "System is frozen"}
        
        result = await self._api.propose_intent(
            strategy_id=strategy_id,
            regime=regime,
            confidence=confidence,
            risk_preview=risk_preview,
            shadow_simulation=shadow_simulation,
            position_request=position_request,
            expiry_ts=expiry_ts,
        )
        
        self._metrics.intents_processed += 1
        return result
    
    async def approve_intent(
        self,
        intent_id: str,
        approved_by: List[str],
        constraints: ExecutionConstraints,
        mode: ExecutionMode = ExecutionMode.MANUAL_REQUIRED,
    ) -> Dict[str, Any]:
        """Approve an intent for execution."""
        result = await self._api.authorize_execution(
            intent_id=intent_id,
            approved_by=approved_by,
            constraints=constraints,
            mode=mode,
        )
        
        self._metrics.intents_approved += 1
        return result
    
    async def reject_intent(
        self,
        intent_id: str,
        rejected_by: List[str],
        reason: str,
    ) -> Dict[str, Any]:
        """Reject an intent."""
        result = await self._api.reject_intent(
            intent_id=intent_id,
            rejected_by=rejected_by,
            reason=reason,
        )
        
        self._metrics.intents_rejected += 1
        return result
    
    async def report_execution(self, report: ExecutionReport) -> Dict[str, Any]:
        """Report execution outcome."""
        result = await self._api.report_execution(report)
        
        if report.status == "COMPLETED":
            self._metrics.executions_completed += 1
        else:
            self._metrics.executions_failed += 1
        
        return result
    
    async def deposit_profit(self, deposit: ProfitDeposit) -> Dict[str, Any]:
        """Deposit profit to treasury."""
        result = await self._api.deposit_profit(deposit)
        
        if result.get("status") == "ACCEPTED":
            self._metrics.profits_deposited += deposit.amount
        
        return result
    
    def get_state(self) -> OrchestratorState:
        """Get orchestrator state."""
        return self._state
    
    def get_system_health(self) -> Dict[str, Any]:
        """Get health status of all systems."""
        return {
            system.value: health.to_dict()
            for system, health in self._system_health.items()
        }
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get orchestrator metrics."""
        return self._metrics.to_dict()
    
    def get_status(self) -> Dict[str, Any]:
        """Get full orchestrator status."""
        return {
            "state": self._state.value,
            "systems": self.get_system_health(),
            "metrics": self.get_metrics(),
            "api_stats": self._api.get_stats(),
            "active_freeze": self._api.get_active_freeze() is not None,
        }


# Singleton instance
_orchestrator: Optional[SystemOrchestrator] = None
_orchestrator_lock = threading.Lock()


def get_system_orchestrator() -> SystemOrchestrator:
    """Get the singleton system orchestrator."""
    global _orchestrator
    if _orchestrator is None:
        with _orchestrator_lock:
            if _orchestrator is None:
                _orchestrator = SystemOrchestrator()
    return _orchestrator


async def start_merid() -> SystemOrchestrator:
    """Start the MERID system."""
    orchestrator = get_system_orchestrator()
    await orchestrator.start()
    return orchestrator


async def stop_merid() -> None:
    """Stop the MERID system."""
    orchestrator = get_system_orchestrator()
    await orchestrator.stop()

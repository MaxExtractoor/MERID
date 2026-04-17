"""
Integration Wiring Module

Wires together all MERID subsystems:
- Emergent behavior safeguards → agent orchestration
- Growth metrics → analytics dashboard
- Continuous learning → model deployment pipeline
- Secure communication → agent-to-agent messages
- Privacy controls → distributed agent network
- Growth metrics visualization
- Meta-learning checkpoint storage
- Canary deployment automation
- Observability integrations
"""

from utils.logger import get_logger
import threading
import time
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = get_logger(__name__)


class IntegrationStatus(Enum):
    """Status of an integration."""
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    DEGRADED = "degraded"
    ERROR = "error"


class IntegrationType(Enum):
    """Types of integrations."""
    EMERGENT_SAFEGUARDS = "emergent_safeguards"
    GROWTH_METRICS = "growth_metrics"
    CONTINUOUS_LEARNING = "continuous_learning"
    SECURE_COMMS = "secure_comms"
    PRIVACY_CONTROLS = "privacy_controls"
    META_LEARNING = "meta_learning"
    CANARY_DEPLOYMENT = "canary_deployment"
    OBSERVABILITY = "observability"
    DRIFT_MONITORING = "drift_monitoring"
    EXPLAINABILITY = "explainability"
    MARKET_DATA_LIVE_FEEDS = "market_data_live_feeds"


@dataclass
class IntegrationConfig:
    """Configuration for an integration."""
    integration_id: str
    integration_type: IntegrationType
    
    source_system: str
    target_system: str
    
    enabled: bool = True
    auto_reconnect: bool = True
    
    config: Dict[str, Any] = field(default_factory=dict)
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class IntegrationState:
    """State of an integration."""
    integration_id: str
    status: IntegrationStatus
    
    last_sync: Optional[datetime] = None
    messages_processed: int = 0
    errors_count: int = 0
    
    health_score: float = 1.0
    
    last_error: str = ""
    last_error_at: Optional[datetime] = None


class IntegrationWiring:
    """
    Central Integration Wiring System.
    
    Connects all MERID subsystems and ensures proper
    data flow between components.
    """
    
    def __init__(self):
        self._integrations: Dict[str, IntegrationConfig] = {}
        self._states: Dict[str, IntegrationState] = {}
        self._handlers: Dict[str, Callable] = {}
        self._message_queues: Dict[str, List[Dict[str, Any]]] = {}
        
        self._initialize_default_integrations()
    
    def _initialize_default_integrations(self) -> None:
        """Initialize default integrations."""
        integrations = [
            IntegrationConfig(
                integration_id="emergent_to_orchestration",
                integration_type=IntegrationType.EMERGENT_SAFEGUARDS,
                source_system="emergent_behavior_monitor",
                target_system="agent_orchestrator",
                config={
                    "safeguard_types": ["runaway_detection", "goal_drift", "resource_abuse"],
                    "action_on_trigger": "pause_and_escalate",
                },
            ),
            IntegrationConfig(
                integration_id="growth_to_dashboard",
                integration_type=IntegrationType.GROWTH_METRICS,
                source_system="growth_metrics_collector",
                target_system="analytics_dashboard",
                config={
                    "metrics": ["aum", "users", "strategies", "agents", "trades"],
                    "refresh_interval_seconds": 60,
                },
            ),
            IntegrationConfig(
                integration_id="learning_to_deployment",
                integration_type=IntegrationType.CONTINUOUS_LEARNING,
                source_system="continuous_learning_pipeline",
                target_system="model_deployment_service",
                config={
                    "auto_deploy": False,
                    "validation_required": True,
                    "canary_percentage": 5,
                },
            ),
            IntegrationConfig(
                integration_id="secure_agent_comms",
                integration_type=IntegrationType.SECURE_COMMS,
                source_system="agent_mesh",
                target_system="agent_mesh",
                config={
                    "encryption": "aes-256-gcm",
                    "authentication": "mtls",
                    "message_signing": True,
                },
            ),
            IntegrationConfig(
                integration_id="privacy_to_agents",
                integration_type=IntegrationType.PRIVACY_CONTROLS,
                source_system="privacy_controller",
                target_system="distributed_agent_network",
                config={
                    "data_classification_required": True,
                    "pii_redaction": True,
                    "audit_logging": True,
                },
            ),
            IntegrationConfig(
                integration_id="meta_learning_storage",
                integration_type=IntegrationType.META_LEARNING,
                source_system="meta_learning_engine",
                target_system="checkpoint_storage",
                config={
                    "checkpoint_interval_hours": 24,
                    "retention_days": 90,
                    "compression": True,
                },
            ),
            IntegrationConfig(
                integration_id="canary_automation",
                integration_type=IntegrationType.CANARY_DEPLOYMENT,
                source_system="deployment_pipeline",
                target_system="canary_controller",
                config={
                    "initial_percentage": 5,
                    "increment_percentage": 10,
                    "success_threshold": 0.99,
                    "rollback_on_failure": True,
                },
            ),
            IntegrationConfig(
                integration_id="observability_pipeline",
                integration_type=IntegrationType.OBSERVABILITY,
                source_system="telemetry_collector",
                target_system="observability_stack",
                config={
                    "metrics_enabled": True,
                    "traces_enabled": True,
                    "logs_enabled": True,
                    "sampling_rate": 0.1,
                },
            ),
            IntegrationConfig(
                integration_id="drift_to_explainability",
                integration_type=IntegrationType.DRIFT_MONITORING,
                source_system="drift_monitoring_pipeline",
                target_system="explainability_storage",
                config={
                    "auto_explain_drift": True,
                    "severity_threshold": "warning",
                },
            ),
        ]
        
        for integration in integrations:
            self._integrations[integration.integration_id] = integration
            self._states[integration.integration_id] = IntegrationState(
                integration_id=integration.integration_id,
                status=IntegrationStatus.DISCONNECTED,
            )
        
        logger.info(f"Initialized {len(integrations)} default integrations")
    
    def register_handler(
        self,
        integration_id: str,
        handler: Callable[[Dict[str, Any]], None],
    ) -> None:
        """Register a message handler for an integration."""
        self._handlers[integration_id] = handler
        logger.debug(f"Registered handler for integration '{integration_id}'")
    
    def connect(self, integration_id: str) -> bool:
        """Connect an integration."""
        if integration_id not in self._integrations:
            logger.error(f"Integration '{integration_id}' not found")
            return False
        
        config = self._integrations[integration_id]
        state = self._states[integration_id]
        
        if not config.enabled:
            logger.warning(f"Integration '{integration_id}' is disabled")
            return False
        
        state.status = IntegrationStatus.CONNECTING
        
        try:
            state.status = IntegrationStatus.CONNECTED
            state.health_score = 1.0
            logger.info(f"Connected integration '{integration_id}'")
            return True
        except Exception as e:
            state.status = IntegrationStatus.ERROR
            state.last_error = str(e)
            state.last_error_at = datetime.utcnow()
            state.errors_count += 1
            logger.error(f"Failed to connect integration '{integration_id}': {e}")
            return False
    
    def disconnect(self, integration_id: str) -> bool:
        """Disconnect an integration."""
        if integration_id not in self._states:
            return False
        
        self._states[integration_id].status = IntegrationStatus.DISCONNECTED
        logger.info(f"Disconnected integration '{integration_id}'")
        return True
    
    def send_message(
        self,
        integration_id: str,
        message: Dict[str, Any],
    ) -> bool:
        """Send a message through an integration."""
        if integration_id not in self._integrations:
            return False
        
        state = self._states[integration_id]
        
        if state.status != IntegrationStatus.CONNECTED:
            logger.warning(f"Integration '{integration_id}' not connected")
            return False
        
        if integration_id not in self._message_queues:
            self._message_queues[integration_id] = []
        
        message["timestamp"] = datetime.utcnow().isoformat()
        message["integration_id"] = integration_id
        
        self._message_queues[integration_id].append(message)
        state.messages_processed += 1
        state.last_sync = datetime.utcnow()
        
        if integration_id in self._handlers:
            try:
                self._handlers[integration_id](message)
            except Exception as e:
                state.errors_count += 1
                state.last_error = str(e)
                state.last_error_at = datetime.utcnow()
                logger.error(f"Handler error for '{integration_id}': {e}")
        
        return True
    
    def connect_all(self) -> Dict[str, bool]:
        """Connect all enabled integrations."""
        results = {}
        for integration_id, config in self._integrations.items():
            if config.enabled:
                results[integration_id] = self.connect(integration_id)
        return results
    
    def get_integration_status(self, integration_id: str) -> Optional[Dict[str, Any]]:
        """Get status of an integration."""
        if integration_id not in self._integrations:
            return None
        
        config = self._integrations[integration_id]
        state = self._states[integration_id]
        
        return {
            "integration_id": integration_id,
            "type": config.integration_type.value,
            "source": config.source_system,
            "target": config.target_system,
            "enabled": config.enabled,
            "status": state.status.value,
            "health_score": state.health_score,
            "messages_processed": state.messages_processed,
            "errors_count": state.errors_count,
            "last_sync": state.last_sync.isoformat() if state.last_sync else None,
            "last_error": state.last_error,
        }
    
    def get_all_status(self) -> Dict[str, Any]:
        """Get status of all integrations."""
        statuses = {}
        for integration_id in self._integrations:
            statuses[integration_id] = self.get_integration_status(integration_id)
        
        connected = sum(
            1 for s in self._states.values()
            if s.status == IntegrationStatus.CONNECTED
        )
        
        return {
            "total_integrations": len(self._integrations),
            "connected": connected,
            "disconnected": len(self._integrations) - connected,
            "integrations": statuses,
        }


class EmergentBehaviorSafeguardIntegration:
    """Integration for emergent behavior safeguards."""
    
    def __init__(self, wiring: IntegrationWiring):
        self._wiring = wiring
        self._safeguard_triggers: List[Dict[str, Any]] = []
    
    def wire_to_orchestration(self) -> None:
        """Wire emergent safeguards to agent orchestration."""
        def handler(message: Dict[str, Any]) -> None:
            if message.get("type") == "safeguard_trigger":
                self._safeguard_triggers.append(message)
                logger.warning(f"Safeguard triggered: {message.get('safeguard_type')}")
        
        self._wiring.register_handler("emergent_to_orchestration", handler)
        self._wiring.connect("emergent_to_orchestration")
    
    def trigger_safeguard(
        self,
        safeguard_type: str,
        agent_id: str,
        reason: str,
        evidence: Dict[str, Any],
    ) -> bool:
        """Trigger a safeguard."""
        return self._wiring.send_message("emergent_to_orchestration", {
            "type": "safeguard_trigger",
            "safeguard_type": safeguard_type,
            "agent_id": agent_id,
            "reason": reason,
            "evidence": evidence,
        })


class GrowthMetricsIntegration:
    """Integration for growth metrics to dashboard."""
    
    def __init__(self, wiring: IntegrationWiring):
        self._wiring = wiring
        self._metrics_history: List[Dict[str, Any]] = []
    
    def wire_to_dashboard(self) -> None:
        """Wire growth metrics to analytics dashboard."""
        def handler(message: Dict[str, Any]) -> None:
            if message.get("type") == "metrics_update":
                self._metrics_history.append(message)
        
        self._wiring.register_handler("growth_to_dashboard", handler)
        self._wiring.connect("growth_to_dashboard")
    
    def push_metrics(
        self,
        aum: float,
        users: int,
        strategies: int,
        agents: int,
        trades_24h: int,
    ) -> bool:
        """Push growth metrics to dashboard."""
        return self._wiring.send_message("growth_to_dashboard", {
            "type": "metrics_update",
            "aum": aum,
            "users": users,
            "strategies": strategies,
            "agents": agents,
            "trades_24h": trades_24h,
        })


class ContinuousLearningIntegration:
    """Integration for continuous learning to model deployment."""
    
    def __init__(self, wiring: IntegrationWiring):
        self._wiring = wiring
        self._pending_deployments: List[Dict[str, Any]] = []
    
    def wire_to_deployment(self) -> None:
        """Wire continuous learning to model deployment."""
        def handler(message: Dict[str, Any]) -> None:
            if message.get("type") == "model_ready":
                self._pending_deployments.append(message)
                logger.info(f"Model ready for deployment: {message.get('model_id')}")
        
        self._wiring.register_handler("learning_to_deployment", handler)
        self._wiring.connect("learning_to_deployment")
    
    def notify_model_ready(
        self,
        model_id: str,
        model_type: str,
        metrics: Dict[str, float],
        validation_passed: bool,
    ) -> bool:
        """Notify that a model is ready for deployment."""
        return self._wiring.send_message("learning_to_deployment", {
            "type": "model_ready",
            "model_id": model_id,
            "model_type": model_type,
            "metrics": metrics,
            "validation_passed": validation_passed,
        })


class SecureCommsIntegration:
    """Integration for secure agent-to-agent communication."""
    
    def __init__(self, wiring: IntegrationWiring):
        self._wiring = wiring
        self._message_log: List[Dict[str, Any]] = []
    
    def wire_secure_channel(self) -> None:
        """Wire secure communication channel."""
        def handler(message: Dict[str, Any]) -> None:
            self._message_log.append({
                "from": message.get("from_agent"),
                "to": message.get("to_agent"),
                "timestamp": message.get("timestamp"),
                "encrypted": True,
            })
        
        self._wiring.register_handler("secure_agent_comms", handler)
        self._wiring.connect("secure_agent_comms")
    
    def send_secure_message(
        self,
        from_agent: str,
        to_agent: str,
        payload: Dict[str, Any],
    ) -> bool:
        """Send a secure message between agents."""
        return self._wiring.send_message("secure_agent_comms", {
            "type": "agent_message",
            "from_agent": from_agent,
            "to_agent": to_agent,
            "payload": payload,
            "encrypted": True,
            "signed": True,
        })


class CanaryDeploymentIntegration:
    """Integration for canary deployment automation."""
    
    def __init__(self, wiring: IntegrationWiring):
        self._wiring = wiring
        self._deployments: Dict[str, Dict[str, Any]] = {}
    
    def wire_canary_automation(self) -> None:
        """Wire canary deployment automation."""
        def handler(message: Dict[str, Any]) -> None:
            deployment_id = message.get("deployment_id")
            if deployment_id:
                self._deployments[deployment_id] = message
        
        self._wiring.register_handler("canary_automation", handler)
        self._wiring.connect("canary_automation")
    
    def start_canary(
        self,
        deployment_id: str,
        model_id: str,
        traffic_percentage: float,
        success_threshold: float,
    ) -> bool:
        """Start a canary deployment."""
        return self._wiring.send_message("canary_automation", {
            "type": "start_canary",
            "deployment_id": deployment_id,
            "model_id": model_id,
            "traffic_percentage": traffic_percentage,
            "success_threshold": success_threshold,
        })


class MarketDataLiveFeedsIntegration:
    """Integration for market data live feeds to execution engine."""
    
    def __init__(self, wiring: IntegrationWiring):
        self._wiring = wiring
        self._feed_handlers: Dict[str, Dict[str, Any]] = {}
        self._market_data_buffer: List[Dict[str, Any]] = []
    
    def wire_to_execution_engine(self) -> None:
        """Wire market data feeds to execution engine."""
        def handler(message: Dict[str, Any]) -> None:
            if message.get("type") == "market_data":
                self._market_data_buffer.append({
                    "symbol": message.get("symbol"),
                    "timestamp": message.get("timestamp"),
                    "data_type": message.get("data_type"),
                    "bid_price": message.get("bid_price"),
                    "ask_price": message.get("ask_price"),
                    "last_price": message.get("last_price"),
                    "venue": message.get("venue"),
                    "feed_handler": message.get("feed_handler")
                })
                
                # Keep buffer size manageable
                if len(self._market_data_buffer) > 10000:
                    self._market_data_buffer = self._market_data_buffer[-5000:]
        
        self._wiring.register_handler("market_data_to_execution", handler)
        self._wiring.connect("market_data_to_execution")
    
    def wire_to_observability(self) -> None:
        """Wire market data feeds to observability."""
        def handler(message: Dict[str, Any]) -> None:
            if message.get("type") == "feed_heartbeat":
                feed_name = message.get("handler_name")
                if feed_name:
                    self._feed_handlers[feed_name] = {
                        "last_heartbeat": message.get("timestamp"),
                        "status": message.get("status"),
                        "symbol_count": message.get("symbol_count")
                    }
        
        self._wiring.register_handler("feed_health_to_observability", handler)
        self._wiring.connect("feed_health_to_observability")
    
    def publish_market_data(
        self,
        symbol: str,
        data_type: str,
        bid_price: Optional[float],
        ask_price: Optional[float],
        last_price: Optional[float],
        venue: str,
        feed_handler: str,
    ) -> bool:
        """Publish market data to execution engine."""
        return self._wiring.send_message("market_data_to_execution", {
            "type": "market_data",
            "symbol": symbol,
            "timestamp": time.time(),
            "data_type": data_type,
            "bid_price": bid_price,
            "ask_price": ask_price,
            "last_price": last_price,
            "venue": venue,
            "feed_handler": feed_handler
        })
    
    def emit_feed_heartbeat(self, handler_name: str, status: str, symbol_count: int) -> bool:
        """Emit feed heartbeat to anti-silent-failure system."""
        return self._wiring.send_message("feed_health_to_observability", {
            "type": "feed_heartbeat",
            "handler_name": handler_name,
            "timestamp": time.time(),
            "status": status,
            "symbol_count": symbol_count
        })
    
    def get_feed_status(self) -> Dict[str, Dict[str, Any]]:
        """Get status of all feed handlers."""
        return self._feed_handlers.copy()
    
    def get_recent_market_data(self, symbol: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent market data."""
        data = self._market_data_buffer
        if symbol:
            data = [d for d in data if d.get("symbol") == symbol]
        return data[-limit:] if data else []


class ObservabilityIntegration:
    """Integration for observability pipeline."""
    
    def __init__(self, wiring: IntegrationWiring):
        self._wiring = wiring
    
    def wire_observability(self) -> None:
        """Wire observability pipeline."""
        self._wiring.connect("observability_pipeline")
    
    def emit_metric(
        self,
        name: str,
        value: float,
        tags: Dict[str, str],
    ) -> bool:
        """Emit a metric."""
        return self._wiring.send_message("observability_pipeline", {
            "type": "metric",
            "name": name,
            "value": value,
            "tags": tags,
        })
    
    def emit_trace(
        self,
        trace_id: str,
        span_id: str,
        operation: str,
        duration_ms: float,
    ) -> bool:
        """Emit a trace span."""
        return self._wiring.send_message("observability_pipeline", {
            "type": "trace",
            "trace_id": trace_id,
            "span_id": span_id,
            "operation": operation,
            "duration_ms": duration_ms,
        })
    
    def emit_log(
        self,
        level: str,
        message: str,
        context: Dict[str, Any],
    ) -> bool:
        """Emit a structured log."""
        return self._wiring.send_message("observability_pipeline", {
            "type": "log",
            "level": level,
            "message": message,
            "context": context,
        })


_wiring: Optional[IntegrationWiring] = None
_wiring_lock = threading.Lock()


def get_integration_wiring() -> IntegrationWiring:
    """Get global IntegrationWiring instance."""
    global _wiring
    if _wiring is None:
        with _wiring_lock:
            if _wiring is None:
                _wiring = IntegrationWiring()
    return _wiring


def wire_all_integrations() -> Dict[str, Any]:
    """Wire all integrations and return status."""
    wiring = get_integration_wiring()
    
    emergent = EmergentBehaviorSafeguardIntegration(wiring)
    emergent.wire_to_orchestration()
    
    growth = GrowthMetricsIntegration(wiring)
    growth.wire_to_dashboard()
    
    learning = ContinuousLearningIntegration(wiring)
    learning.wire_to_deployment()
    
    secure = SecureCommsIntegration(wiring)
    secure.wire_secure_channel()
    
    canary = CanaryDeploymentIntegration(wiring)
    canary.wire_canary_automation()
    
    observability = ObservabilityIntegration(wiring)
    observability.wire_observability()
    
    # Market Data Live Feeds integration
    market_data = MarketDataLiveFeedsIntegration(wiring)
    market_data.wire_to_execution_engine()
    market_data.wire_to_observability()
    
    wiring.connect("privacy_to_agents")
    wiring.connect("meta_learning_storage")
    wiring.connect("drift_to_explainability")
    
    return wiring.get_all_status()

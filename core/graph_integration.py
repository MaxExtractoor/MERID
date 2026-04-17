"""
Graph Integration Adapters for MERID Core Modules

Provides integration adapters that wire GraphService into:
- ExecutionController
- RiskEnvelopeManager
- EnhancedThreatMonitor
- CircuitBreakerManager

These adapters handle the translation between MERID's internal
data structures and Neo4j graph operations.
"""

from typing import Dict, List, Optional, Any
from utils.logger import get_logger
import uuid
import time

logger = get_logger(__name__)


class ExecutionControllerGraphAdapter:
    """
    Adapter for ExecutionController to record all execution lifecycle events in Neo4j.
    
    Integrates with:
    - submit_proposal() → record_proposal()
    - update_status() → record_proposal_state_change()
    - _execute_proposal() → record_execution()
    """
    
    def __init__(self, graph_service):
        """
        Initialize adapter with GraphService instance.
        
        Args:
            graph_service: GraphService instance
        """
        self.graph = graph_service
    
    def record_proposal_submission(
        self,
        proposal,
        agent_id: str
    ) -> None:
        """
        Record proposal submission to graph.
        
        Extracts assertions from proposal and records complete lineage.
        
        Args:
            proposal: TradeProposal instance
            agent_id: ID of agent that created proposal
        """
        try:
            # Extract proposal data
            proposal_data = {
                "proposal_id": proposal.proposal_id,
                "state": proposal.status.value,
                "side": proposal.side,
                "asset_id": proposal.instrument,
                "venue_id": proposal.venue,
                "size_usd": proposal.size * (proposal.price_limit or 0),
                "leverage": 1.0,  # Add if available
                "stop_loss_pct": None,
                "take_profit_pct": None,
                "strategy": proposal.strategy,
                "confidence": proposal.confidence,
            }
            
            # Extract assertions (if available from reasoning link)
            assertions = []
            if hasattr(proposal, 'supporting_features') and proposal.supporting_features:
                # Convert supporting features to assertions
                for key, value in proposal.supporting_features.items():
                    assertions.append({
                        "assertion_id": f"assert_{proposal.proposal_id}_{key}",
                        "domain": key,
                        "status": "VERIFIED",
                        "confidence": value if isinstance(value, float) else 0.8,
                        "decay_factor": 0.1,
                        "expires_at": time.time() + 3600  # 1 hour
                    })
            
            # Record to graph
            self.graph.record_proposal(
                proposal=proposal_data,
                assertions=assertions,
                agent_id=agent_id
            )
            
            logger.debug(f"Recorded proposal {proposal.proposal_id} to graph")
            
        except Exception as e:
            logger.error(f"Failed to record proposal to graph: {e}")
            # Don't fail execution on graph errors
    
    def record_state_transition(
        self,
        proposal,
        from_status,
        to_status,
        reason: str,
        updated_by: str
    ) -> None:
        """
        Record proposal state transition to graph.
        
        Args:
            proposal: TradeProposal instance
            from_status: Previous status
            to_status: New status
            reason: Reason for transition
            updated_by: Who/what triggered transition
        """
        try:
            event_id = f"event_{proposal.proposal_id}_{int(time.time() * 1000)}"
            
            self.graph.record_proposal_state_change(
                proposal_id=proposal.proposal_id,
                from_state=from_status.value if hasattr(from_status, 'value') else str(from_status),
                to_state=to_status.value if hasattr(to_status, 'value') else str(to_status),
                event_id=event_id,
                reason=reason,
                updated_by=updated_by
            )
            
            logger.debug(f"Recorded state transition for {proposal.proposal_id}: {from_status} → {to_status}")
            
        except Exception as e:
            logger.error(f"Failed to record state transition to graph: {e}")
    
    def record_execution_result(
        self,
        proposal,
        wallet_id: str,
        execution_result: Dict[str, Any]
    ) -> None:
        """
        Record execution result to graph.
        
        Args:
            proposal: TradeProposal instance
            wallet_id: Wallet that executed trade
            execution_result: Execution result from venue
        """
        try:
            # Create order data
            order_data = {
                "order_id": execution_result.get("order_id", f"order_{proposal.proposal_id}"),
                "side": proposal.side,
                "size_usd": proposal.size * execution_result.get("avg_price", 0),
                "status": "FILLED"
            }
            
            # Create execution data
            execution_data = {
                "execution_id": execution_result.get("execution_id", f"exec_{proposal.proposal_id}"),
                "size_usd": execution_result.get("filled_size", 0) * execution_result.get("avg_price", 0),
                "price": execution_result.get("avg_price", 0),
                "fees_usd": execution_result.get("fees", 0),
                "slippage_bps": execution_result.get("slippage", 0) * 10000
            }
            
            # Position ID (create or use existing)
            position_id = f"pos_{wallet_id}_{proposal.instrument}_{proposal.venue}"
            
            # Record to graph
            self.graph.record_execution(
                proposal_id=proposal.proposal_id,
                wallet_id=wallet_id,
                venue_id=proposal.venue,
                asset_id=proposal.instrument,
                order=order_data,
                execution=execution_data,
                position_id=position_id
            )
            
            logger.debug(f"Recorded execution for {proposal.proposal_id}")
            
        except Exception as e:
            logger.error(f"Failed to record execution to graph: {e}")


class RiskEnvelopeGraphAdapter:
    """
    Adapter for RiskEnvelopeManager to query exposure and record violations.
    
    Integrates with:
    - check_proposal() → get_wallet_exposure() + record_risk_violation()
    """
    
    def __init__(self, graph_service):
        """
        Initialize adapter with GraphService instance.
        
        Args:
            graph_service: GraphService instance
        """
        self.graph = graph_service
    
    def get_current_exposure(
        self,
        wallet_id: str
    ) -> Dict[str, float]:
        """
        Get current exposure from graph for risk checks.
        
        Args:
            wallet_id: Wallet ID
        
        Returns:
            Dictionary of asset → exposure_usd
        """
        try:
            exposures = self.graph.get_wallet_exposure(wallet_id)
            
            # Convert to simple dict
            exposure_dict = {}
            for exp in exposures:
                asset = exp.get("asset")
                exposure_usd = exp.get("exposure_usd", 0.0)
                if asset:
                    exposure_dict[asset] = exposure_usd
            
            return exposure_dict
            
        except Exception as e:
            logger.error(f"Failed to get exposure from graph: {e}")
            return {}
    
    def record_violation(
        self,
        proposal,
        violation: Dict[str, Any]
    ) -> None:
        """
        Record risk violation to graph.
        
        Args:
            proposal: TradeProposal instance
            violation: Violation details
        """
        try:
            violation_id = f"violation_{proposal.proposal_id}_{int(time.time() * 1000)}"
            
            self.graph.record_risk_violation(
                proposal_id=proposal.proposal_id,
                violation_id=violation_id,
                violation_type=violation.get("type", "UNKNOWN"),
                severity=violation.get("severity", "high"),
                limit=violation.get("limit", 0.0),
                actual=violation.get("value", 0.0),
                message=violation.get("message", "Risk limit exceeded")
            )
            
            logger.debug(f"Recorded risk violation for {proposal.proposal_id}")
            
        except Exception as e:
            logger.error(f"Failed to record violation to graph: {e}")
    
    def check_venue_incidents(
        self,
        venue_id: str
    ) -> bool:
        """
        Check if venue has active incidents.
        
        Args:
            venue_id: Venue ID
        
        Returns:
            True if venue has active incidents, False otherwise
        """
        try:
            incidents = self.graph.get_active_incidents_for_venue(venue_id)
            return len(incidents) > 0
            
        except Exception as e:
            logger.error(f"Failed to check venue incidents: {e}")
            return False


class ThreatMonitorGraphAdapter:
    """
    Adapter for EnhancedThreatMonitor to record incidents and circuit breakers.
    
    Integrates with:
    - _create_incident() → record_incident()
    - _execute_mitigations() → record_circuit_breaker()
    """
    
    def __init__(self, graph_service):
        """
        Initialize adapter with GraphService instance.
        
        Args:
            graph_service: GraphService instance
        """
        self.graph = graph_service
    
    def record_threat_incident(
        self,
        threat_id: str,
        incident_data: Dict[str, Any]
    ) -> None:
        """
        Record threat incident to graph.
        
        Args:
            threat_id: Threat ID
            incident_data: Incident details
        """
        try:
            incident_id = f"incident_{threat_id}_{int(time.time() * 1000)}"
            
            self.graph.record_incident(
                incident_id=incident_id,
                incident_type=incident_data.get("threat_description", "Unknown"),
                severity=incident_data.get("impact", "MEDIUM"),
                description=incident_data.get("triggered_signal", ""),
                wallet_id=incident_data.get("wallet_id"),
                venue_id=incident_data.get("venue_id"),
                threat_id=threat_id
            )
            
            logger.info(f"Recorded threat incident {incident_id} for threat {threat_id}")
            
        except Exception as e:
            logger.error(f"Failed to record incident to graph: {e}")
    
    def record_circuit_breaker_trigger(
        self,
        breaker_id: str,
        breaker_type: str,
        threshold: float,
        actual_value: float,
        action: str,
        incident_id: Optional[str] = None
    ) -> None:
        """
        Record circuit breaker trigger to graph.
        
        Args:
            breaker_id: Breaker ID
            breaker_type: Type of breaker
            threshold: Threshold exceeded
            actual_value: Actual value
            action: Action taken
            incident_id: Optional related incident
        """
        try:
            self.graph.record_circuit_breaker(
                breaker_id=breaker_id,
                breaker_type=breaker_type,
                threshold=threshold,
                actual_value=actual_value,
                action=action,
                incident_id=incident_id
            )
            
            logger.info(f"Recorded circuit breaker {breaker_id}: {breaker_type}")
            
        except Exception as e:
            logger.error(f"Failed to record circuit breaker to graph: {e}")
    
    def get_recent_incidents(
        self,
        wallet_id: Optional[str] = None,
        venue_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get recent incidents from graph.
        
        Args:
            wallet_id: Optional wallet filter
            venue_id: Optional venue filter
        
        Returns:
            List of incidents
        """
        try:
            if wallet_id:
                return self.graph.get_active_incidents_for_wallet(wallet_id)
            elif venue_id:
                return self.graph.get_active_incidents_for_venue(venue_id)
            else:
                return []
                
        except Exception as e:
            logger.error(f"Failed to get incidents from graph: {e}")
            return []


class OperatorQueryAdapter:
    """
    Adapter for operator queries and UX.
    
    Provides high-level query methods for operator console.
    """
    
    def __init__(self, graph_service):
        """
        Initialize adapter with GraphService instance.
        
        Args:
            graph_service: GraphService instance
        """
        self.graph = graph_service
    
    def explain_trade(
        self,
        execution_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get complete explanation for a trade.
        
        Returns full lineage from proposal to execution.
        
        Args:
            execution_id: Execution ID
        
        Returns:
            Complete lineage or None
        """
        try:
            return self.graph.get_execution_lineage(execution_id)
        except Exception as e:
            logger.error(f"Failed to get trade explanation: {e}")
            return None
    
    def explain_proposal(
        self,
        proposal_id: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get complete explanation for a proposal.
        
        Returns full lineage including rejections.
        
        Args:
            proposal_id: Proposal ID
        
        Returns:
            Complete lineage or None
        """
        try:
            return self.graph.get_proposal_lineage(proposal_id)
        except Exception as e:
            logger.error(f"Failed to get proposal explanation: {e}")
            return None
    
    def get_wallet_summary(
        self,
        wallet_id: str
    ) -> Dict[str, Any]:
        """
        Get wallet summary with exposure and incidents.
        
        Args:
            wallet_id: Wallet ID
        
        Returns:
            Wallet summary
        """
        try:
            exposure = self.graph.get_wallet_exposure(wallet_id)
            incidents = self.graph.get_active_incidents_for_wallet(wallet_id)
            
            return {
                "wallet_id": wallet_id,
                "exposure": exposure,
                "active_incidents": len(incidents),
                "incidents": incidents
            }
        except Exception as e:
            logger.error(f"Failed to get wallet summary: {e}")
            return {"wallet_id": wallet_id, "error": str(e)}
    
    def get_system_dashboard(self) -> Dict[str, Any]:
        """
        Get system-wide dashboard data.
        
        Returns:
            Dashboard summary
        """
        try:
            health = self.graph.get_system_health_summary()
            circuit_breakers = self.graph.get_recent_circuit_breakers(hours=24)
            
            return {
                "health": health,
                "circuit_breakers_24h": len(circuit_breakers),
                "recent_breakers": circuit_breakers[:10]  # Last 10
            }
        except Exception as e:
            logger.error(f"Failed to get system dashboard: {e}")
            return {"error": str(e)}
    
    def get_agent_report(
        self,
        agent_id: str,
        days: int = 30
    ) -> Dict[str, Any]:
        """
        Get agent performance report.
        
        Args:
            agent_id: Agent ID
            days: Number of days to analyze
        
        Returns:
            Performance metrics
        """
        try:
            return self.graph.get_agent_performance(agent_id, days)
        except Exception as e:
            logger.error(f"Failed to get agent report: {e}")
            return {"agent_id": agent_id, "error": str(e)}


# Convenience functions for creating adapters

def create_execution_adapter():
    """Create ExecutionControllerGraphAdapter with global GraphService."""
    from core.graph_service import get_graph_service
    return ExecutionControllerGraphAdapter(get_graph_service())


def create_risk_adapter():
    """Create RiskEnvelopeGraphAdapter with global GraphService."""
    from core.graph_service import get_graph_service
    return RiskEnvelopeGraphAdapter(get_graph_service())


def create_threat_adapter():
    """Create ThreatMonitorGraphAdapter with global GraphService."""
    from core.graph_service import get_graph_service
    return ThreatMonitorGraphAdapter(get_graph_service())


def create_operator_adapter():
    """Create OperatorQueryAdapter with global GraphService."""
    from core.graph_service import get_graph_service
    return OperatorQueryAdapter(get_graph_service())

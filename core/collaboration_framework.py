"""
MERID Collaboration Framework
Enhances inter-component collaboration, reduces coupling, and improves integration patterns
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable, Set
from enum import Enum
import logging
import json

logger = logging.getLogger(__name__)


class IntegrationPattern(Enum):
    """Integration patterns between components"""
    EVENT_DRIVEN = "event_driven"
    API_GATEWAY = "api_gateway"
    MESSAGE_QUEUE = "message_queue"
    SHARED_STATE = "shared_state"
    DIRECT_CALL = "direct_call"
    PUBLISH_SUBSCRIBE = "publish_subscribe"


class CouplingLevel(Enum):
    """Coupling levels between components"""
    LOOSE = "loose"
    MODERATE = "moderate"
    TIGHT = "tight"
    VERY_TIGHT = "very_tight"


@dataclass
class ComponentInterface:
    """Interface definition for a component"""
    component_name: str
    provides: List[str] = field(default_factory=list)  # Services provided
    requires: List[str] = field(default_factory=list)  # Services required
    events_published: List[str] = field(default_factory=list)
    events_subscribed: List[str] = field(default_factory=list)
    api_endpoints: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'component_name': self.component_name,
            'provides': self.provides,
            'requires': self.requires,
            'events_published': self.events_published,
            'events_subscribed': self.events_subscribed,
            'api_endpoints': self.api_endpoints
        }


@dataclass
class IntegrationPoint:
    """Integration point between two components"""
    source_component: str
    target_component: str
    integration_pattern: IntegrationPattern
    coupling_level: CouplingLevel
    data_flow: str  # unidirectional, bidirectional
    
    # Metrics
    call_count: int = 0
    error_count: int = 0
    avg_latency_ms: float = 0.0
    last_interaction: Optional[float] = None
    
    def calculate_health_score(self) -> float:
        """Calculate integration health score (0-100)"""
        if self.call_count == 0:
            return 100.0
        
        error_rate = self.error_count / self.call_count
        error_score = max(0, 100 - (error_rate * 100))
        
        latency_score = max(0, 100 - (self.avg_latency_ms / 10))
        
        return (error_score * 0.7 + latency_score * 0.3)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'source_component': self.source_component,
            'target_component': self.target_component,
            'integration_pattern': self.integration_pattern.value,
            'coupling_level': self.coupling_level.value,
            'data_flow': self.data_flow,
            'call_count': self.call_count,
            'error_count': self.error_count,
            'avg_latency_ms': self.avg_latency_ms,
            'health_score': self.calculate_health_score()
        }


class EventBus:
    """Centralized event bus for loose coupling"""
    
    def __init__(self):
        self.subscribers: Dict[str, List[Callable]] = {}
        self.event_history: List[Dict[str, Any]] = []
        self.max_history = 1000
        
        logger.info("Event bus initialized")
    
    def subscribe(self, event_type: str, handler: Callable):
        """Subscribe to event type"""
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        
        self.subscribers[event_type].append(handler)
        logger.debug(f"Subscribed to event: {event_type}")
    
    def unsubscribe(self, event_type: str, handler: Callable):
        """Unsubscribe from event type"""
        if event_type in self.subscribers:
            self.subscribers[event_type].remove(handler)
            logger.debug(f"Unsubscribed from event: {event_type}")
    
    async def publish(self, event_type: str, data: Dict[str, Any]):
        """Publish event to all subscribers"""
        event = {
            'event_type': event_type,
            'data': data,
            'timestamp': time.time()
        }
        
        # Store in history
        self.event_history.append(event)
        if len(self.event_history) > self.max_history:
            self.event_history.pop(0)
        
        # Notify subscribers
        if event_type in self.subscribers:
            tasks = []
            for handler in self.subscribers[event_type]:
                if asyncio.iscoroutinefunction(handler):
                    tasks.append(handler(data))
                else:
                    handler(data)
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
        
        logger.debug(f"Published event: {event_type}")
    
    def get_event_stats(self) -> Dict[str, Any]:
        """Get event bus statistics"""
        event_counts = {}
        for event in self.event_history:
            event_type = event['event_type']
            event_counts[event_type] = event_counts.get(event_type, 0) + 1
        
        return {
            'total_events': len(self.event_history),
            'event_types': len(self.subscribers),
            'total_subscribers': sum(len(subs) for subs in self.subscribers.values()),
            'event_counts': event_counts
        }


class ServiceRegistry:
    """Service registry for service discovery"""
    
    def __init__(self):
        self.services: Dict[str, ComponentInterface] = {}
        self.service_health: Dict[str, Dict[str, Any]] = {}
        
        logger.info("Service registry initialized")
    
    def register_service(self, interface: ComponentInterface):
        """Register a service"""
        self.services[interface.component_name] = interface
        self.service_health[interface.component_name] = {
            'status': 'healthy',
            'last_heartbeat': time.time(),
            'uptime_start': time.time()
        }
        
        logger.info(f"Service registered: {interface.component_name}")
    
    def unregister_service(self, component_name: str):
        """Unregister a service"""
        if component_name in self.services:
            del self.services[component_name]
            del self.service_health[component_name]
            logger.info(f"Service unregistered: {component_name}")
    
    def discover_service(self, service_name: str) -> Optional[ComponentInterface]:
        """Discover a service by name"""
        return self.services.get(service_name)
    
    def find_providers(self, service_type: str) -> List[ComponentInterface]:
        """Find all providers of a service type"""
        providers = []
        for interface in self.services.values():
            if service_type in interface.provides:
                providers.append(interface)
        return providers
    
    def update_health(self, component_name: str, status: str):
        """Update service health status"""
        if component_name in self.service_health:
            self.service_health[component_name]['status'] = status
            self.service_health[component_name]['last_heartbeat'] = time.time()
    
    def get_registry_status(self) -> Dict[str, Any]:
        """Get registry status"""
        healthy = sum(
            1 for health in self.service_health.values()
            if health['status'] == 'healthy'
        )
        
        return {
            'total_services': len(self.services),
            'healthy_services': healthy,
            'unhealthy_services': len(self.services) - healthy,
            'services': [
                {
                    'name': name,
                    'status': self.service_health[name]['status'],
                    'provides': interface.provides,
                    'requires': interface.requires
                }
                for name, interface in self.services.items()
            ]
        }


class IntegrationAnalyzer:
    """Analyzes and optimizes component integrations"""
    
    def __init__(self):
        self.integration_points: List[IntegrationPoint] = []
        self.component_interfaces: Dict[str, ComponentInterface] = {}
        
        logger.info("Integration analyzer initialized")
    
    def register_integration(self, integration: IntegrationPoint):
        """Register an integration point"""
        self.integration_points.append(integration)
        logger.debug(
            f"Integration registered: {integration.source_component} -> "
            f"{integration.target_component}"
        )
    
    def analyze_coupling(self) -> Dict[str, Any]:
        """Analyze coupling between components"""
        coupling_matrix = {}
        
        for integration in self.integration_points:
            source = integration.source_component
            target = integration.target_component
            
            if source not in coupling_matrix:
                coupling_matrix[source] = {}
            
            coupling_matrix[source][target] = {
                'pattern': integration.integration_pattern.value,
                'coupling': integration.coupling_level.value,
                'health': integration.calculate_health_score()
            }
        
        # Identify tightly coupled components
        tight_couplings = [
            integration for integration in self.integration_points
            if integration.coupling_level in [CouplingLevel.TIGHT, CouplingLevel.VERY_TIGHT]
        ]
        
        return {
            'coupling_matrix': coupling_matrix,
            'total_integrations': len(self.integration_points),
            'tight_couplings': len(tight_couplings),
            'recommendations': self._generate_coupling_recommendations(tight_couplings)
        }
    
    def _generate_coupling_recommendations(
        self,
        tight_couplings: List[IntegrationPoint]
    ) -> List[Dict[str, str]]:
        """Generate recommendations to reduce coupling"""
        recommendations = []
        
        for integration in tight_couplings:
            if integration.integration_pattern == IntegrationPattern.DIRECT_CALL:
                recommendations.append({
                    'source': integration.source_component,
                    'target': integration.target_component,
                    'current_pattern': 'direct_call',
                    'suggested_pattern': 'event_driven',
                    'reason': 'Reduce tight coupling through event-driven architecture'
                })
            
            elif integration.integration_pattern == IntegrationPattern.SHARED_STATE:
                recommendations.append({
                    'source': integration.source_component,
                    'target': integration.target_component,
                    'current_pattern': 'shared_state',
                    'suggested_pattern': 'message_queue',
                    'reason': 'Eliminate shared state through message passing'
                })
        
        return recommendations
    
    def get_component_dependencies(self, component_name: str) -> Dict[str, Any]:
        """Get all dependencies for a component"""
        depends_on = []
        depended_by = []
        
        for integration in self.integration_points:
            if integration.source_component == component_name:
                depends_on.append({
                    'component': integration.target_component,
                    'pattern': integration.integration_pattern.value,
                    'coupling': integration.coupling_level.value
                })
            
            if integration.target_component == component_name:
                depended_by.append({
                    'component': integration.source_component,
                    'pattern': integration.integration_pattern.value,
                    'coupling': integration.coupling_level.value
                })
        
        return {
            'component': component_name,
            'depends_on': depends_on,
            'depended_by': depended_by,
            'total_dependencies': len(depends_on) + len(depended_by)
        }


class CollaborationCoordinator:
    """Coordinates collaboration between all components"""
    
    def __init__(self):
        self.event_bus = EventBus()
        self.service_registry = ServiceRegistry()
        self.integration_analyzer = IntegrationAnalyzer()
        
        self._monitoring = False
        self._monitor_task: Optional[asyncio.Task] = None
        
        logger.info("Collaboration coordinator initialized")
    
    async def start_monitoring(self, interval: float = 30.0):
        """Start collaboration monitoring"""
        self._monitoring = True
        
        async def monitor_loop():
            while self._monitoring:
                try:
                    await self._analyze_collaboration_health()
                    await asyncio.sleep(interval)
                except Exception as e:
                    logger.error(f"Collaboration monitoring error: {e}")
                    await asyncio.sleep(interval)
        
        self._monitor_task = asyncio.create_task(monitor_loop())
        logger.info("Collaboration monitoring started")
    
    async def stop_monitoring(self):
        """Stop collaboration monitoring"""
        self._monitoring = False
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        logger.info("Collaboration monitoring stopped")
    
    async def _analyze_collaboration_health(self):
        """Analyze overall collaboration health"""
        coupling_analysis = self.integration_analyzer.analyze_coupling()
        
        if coupling_analysis['tight_couplings'] > 0:
            logger.warning(
                f"Found {coupling_analysis['tight_couplings']} tight couplings. "
                "Consider refactoring for loose coupling."
            )
    
    def get_collaboration_status(self) -> Dict[str, Any]:
        """Get comprehensive collaboration status"""
        return {
            'event_bus': self.event_bus.get_event_stats(),
            'service_registry': self.service_registry.get_registry_status(),
            'coupling_analysis': self.integration_analyzer.analyze_coupling(),
            'monitoring_active': self._monitoring
        }
    
    def optimize_integration(
        self,
        source: str,
        target: str,
        current_pattern: IntegrationPattern
    ) -> Dict[str, Any]:
        """Suggest optimization for an integration"""
        # Analyze current integration
        current_integration = None
        for integration in self.integration_analyzer.integration_points:
            if (integration.source_component == source and
                integration.target_component == target):
                current_integration = integration
                break
        
        if not current_integration:
            return {
                'status': 'not_found',
                'message': f"No integration found between {source} and {target}"
            }
        
        # Generate optimization suggestion
        suggestions = []
        
        if current_integration.coupling_level in [CouplingLevel.TIGHT, CouplingLevel.VERY_TIGHT]:
            suggestions.append({
                'priority': 'high',
                'type': 'reduce_coupling',
                'current_pattern': current_pattern.value,
                'suggested_pattern': IntegrationPattern.EVENT_DRIVEN.value,
                'reason': 'Reduce tight coupling through event-driven architecture',
                'expected_improvement': '40-60% coupling reduction'
            })
        
        if current_integration.error_count > current_integration.call_count * 0.05:
            suggestions.append({
                'priority': 'high',
                'type': 'improve_reliability',
                'suggestion': 'Add retry logic and circuit breakers',
                'reason': f'High error rate: {current_integration.error_count / current_integration.call_count:.1%}',
                'expected_improvement': '80% error reduction'
            })
        
        if current_integration.avg_latency_ms > 100:
            suggestions.append({
                'priority': 'medium',
                'type': 'improve_performance',
                'suggestion': 'Add caching or async processing',
                'reason': f'High latency: {current_integration.avg_latency_ms:.1f}ms',
                'expected_improvement': '50% latency reduction'
            })
        
        return {
            'status': 'analyzed',
            'current_health': current_integration.calculate_health_score(),
            'suggestions': suggestions
        }


# Global collaboration coordinator
_collaboration_coordinator: Optional[CollaborationCoordinator] = None


def get_collaboration_coordinator() -> CollaborationCoordinator:
    """Get global collaboration coordinator"""
    global _collaboration_coordinator
    if _collaboration_coordinator is None:
        _collaboration_coordinator = CollaborationCoordinator()
    return _collaboration_coordinator

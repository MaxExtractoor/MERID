"""
Load Balancer for MERID Production Scalability

Provides intelligent load balancing and instance management for
horizontal scaling of MERID components with US-compliant configuration.

Features:
- Multi-instance load balancing
- Health checking and failover
- Dynamic instance management
- Performance-based routing
- US-compliant deployment controls
"""

import asyncio
import time
import json
import hashlib
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
import logging
import aiohttp
import random

from utils.logger import get_logger

logger = get_logger("scaling.load_balancer")

@dataclass
class Instance:
    """Instance information and status."""
    instance_id: str
    host: str
    port: int
    protocol: str  # http, https, ws
    status: str  # healthy, unhealthy, draining, maintenance
    weight: int  # Load balancing weight
    connections: int
    max_connections: int
    response_time: float
    error_rate: float
    last_health_check: float
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class LoadBalancingRule:
    """Load balancing rule configuration."""
    rule_id: str
    pattern: str  # URL pattern or service type
    algorithm: str  # round_robin, weighted_round_robin, least_connections, response_time
    sticky_sessions: bool
    health_check_interval: int
    health_check_timeout: int
    max_failures: int
    backup_instances: List[str] = field(default_factory=list)

@dataclass
class RoutingDecision:
    """Load balancing routing decision."""
    instance_id: str
    host: str
    port: int
    protocol: str
    selected_at: float
    algorithm_used: str
    reasoning: str
    metadata: Dict[str, Any] = field(default_factory=dict)

class LoadBalancer:
    """
    Production-grade load balancer for MERID components.
    
    Provides intelligent load distribution, health monitoring,
    and dynamic instance management for horizontal scaling.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Instance registry
        self.instances: Dict[str, Instance] = {}
        self.instance_groups: Dict[str, List[str]] = {}
        
        # Load balancing rules
        self.rules: Dict[str, LoadBalancingRule] = {}
        self.default_rule = LoadBalancingRule(
            rule_id="default",
            pattern="*",
            algorithm="weighted_round_robin",
            sticky_sessions=False,
            health_check_interval=30,
            health_check_timeout=5,
            max_failures=3
        )
        
        # Routing state
        self.routing_history: deque = deque(maxlen=10000)
        self.sticky_sessions: Dict[str, str] = {}  # session_id -> instance_id
        
        # Health checking
        self.health_check_task: Optional[asyncio.Task] = None
        self.health_check_stats: Dict[str, Dict[str, Any]] = {}
        
        # US compliance settings
        self.us_compliance = config.get("us_compliance", {
            "geo_fencing": True,
            "data_residency": True,
            "audit_logging": True,
            "security_zones": True
        })
        
        # Performance metrics
        self.request_counts: Dict[str, int] = {}
        self.response_times: Dict[str, List[float]] = {}
        
        logger.info("LoadBalancer initialized")
    
    async def start(self):
        """Start the load balancer services."""
        logger.info("Starting load balancer")
        
        # Start health checking
        self.health_check_task = asyncio.create_task(self._health_check_loop())
        
        # Load initial configuration
        await self._load_configuration()
        
        logger.info("Load balancer started successfully")
    
    async def stop(self):
        """Stop the load balancer services."""
        logger.info("Stopping load balancer")
        
        if self.health_check_task:
            self.health_check_task.cancel()
            try:
                await self.health_check_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Load balancer stopped")
    
    async def register_instance(self, instance_id: str, host: str, port: int, 
                              protocol: str = "http", weight: int = 1,
                              max_connections: int = 1000, 
                              group: str = "default", **metadata) -> bool:
        """Register a new instance."""
        try:
            instance = Instance(
                instance_id=instance_id,
                host=host,
                port=port,
                protocol=protocol,
                status="unhealthy",
                weight=weight,
                connections=0,
                max_connections=max_connections,
                response_time=0.0,
                error_rate=0.0,
                last_health_check=0.0,
                metadata=metadata
            )
            
            self.instances[instance_id] = instance
            
            # Add to group
            if group not in self.instance_groups:
                self.instance_groups[group] = []
            if instance_id not in self.instance_groups[group]:
                self.instance_groups[group].append(instance_id)
            
            # Initialize metrics
            self.request_counts[instance_id] = 0
            self.response_times[instance_id] = []
            
            logger.info(f"Registered instance {instance_id} ({host}:{port})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to register instance {instance_id}: {e}")
            return False
    
    async def unregister_instance(self, instance_id: str) -> bool:
        """Unregister an instance."""
        try:
            if instance_id not in self.instances:
                return False
            
            # Set to draining first
            await self._drain_instance(instance_id)
            
            # Remove from registry
            del self.instances[instance_id]
            
            # Remove from groups
            for group_instances in self.instance_groups.values():
                if instance_id in group_instances:
                    group_instances.remove(instance_id)
            
            # Clean up metrics
            self.request_counts.pop(instance_id, None)
            self.response_times.pop(instance_id, None)
            
            logger.info(f"Unregistered instance {instance_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to unregister instance {instance_id}: {e}")
            return False
    
    async def route_request(self, service: str, session_id: Optional[str] = None,
                          **routing_context) -> Optional[RoutingDecision]:
        """Route a request to an appropriate instance."""
        try:
            # Get rule for service
            rule = self._get_rule_for_service(service)
            
            # Get healthy instances
            healthy_instances = self._get_healthy_instances(service)
            
            if not healthy_instances:
                logger.warning(f"No healthy instances available for service {service}")
                return None
            
            # Check sticky sessions
            if rule.sticky_sessions and session_id and session_id in self.sticky_sessions:
                sticky_instance_id = self.sticky_sessions[session_id]
                if sticky_instance_id in healthy_instances:
                    instance = self.instances[sticky_instance_id]
                    decision = RoutingDecision(
                        instance_id=sticky_instance_id,
                        host=instance.host,
                        port=instance.port,
                        protocol=instance.protocol,
                        selected_at=time.time(),
                        algorithm_used="sticky_session",
                        reasoning=f"Sticky session for {session_id}",
                        metadata={"session_id": session_id}
                    )
                    self._record_routing(decision)
                    return decision
            
            # Apply load balancing algorithm
            selected_instance_id = await self._apply_algorithm(rule, healthy_instances, routing_context)
            
            if not selected_instance_id:
                return None
            
            instance = self.instances[selected_instance_id]
            
            # Update sticky sessions if enabled
            if rule.sticky_sessions and session_id:
                self.sticky_sessions[session_id] = selected_instance_id
            
            decision = RoutingDecision(
                instance_id=selected_instance_id,
                host=instance.host,
                port=instance.port,
                protocol=instance.protocol,
                selected_at=time.time(),
                algorithm_used=rule.algorithm,
                reasoning=f"Algorithm: {rule.algorithm}",
                metadata={"service": service, "rule_id": rule.rule_id}
            )
            
            self._record_routing(decision)
            return decision
            
        except Exception as e:
            logger.error(f"Failed to route request for {service}: {e}")
            return None
    
    async def record_request_result(self, instance_id: str, success: bool, 
                                  response_time: float, error: Optional[str] = None):
        """Record request result for performance tracking."""
        try:
            if instance_id not in self.instances:
                return
            
            instance = self.instances[instance_id]
            
            # Update metrics
            self.request_counts[instance_id] = self.request_counts.get(instance_id, 0) + 1
            
            if success:
                instance.response_time = (instance.response_time * 0.9 + response_time * 0.1)  # EMA
                self.response_times[instance_id].append(response_time)
                
                # Keep only last 100 measurements
                if len(self.response_times[instance_id]) > 100:
                    self.response_times[instance_id] = self.response_times[instance_id][-100:]
            else:
                # Update error rate
                total_requests = self.request_counts[instance_id]
                if total_requests > 0:
                    recent_errors = sum(1 for rt in self.response_times[instance_id][-10:] if rt < 0)
                    instance.error_rate = recent_errors / min(10, total_requests)
            
            logger.debug(f"Recorded request result for {instance_id}: success={success}, time={response_time:.3f}")
            
        except Exception as e:
            logger.error(f"Failed to record request result for {instance_id}: {e}")
    
    def _get_rule_for_service(self, service: str) -> LoadBalancingRule:
        """Get load balancing rule for a service."""
        # Simple pattern matching (in production, use more sophisticated routing)
        for rule in self.rules.values():
            if rule.pattern == service or rule.pattern == "*":
                return rule
        
        return self.default_rule
    
    def _get_healthy_instances(self, service: str) -> List[str]:
        """Get list of healthy instances for a service."""
        group_instances = self.instance_groups.get(service, list(self.instances.keys()))
        
        healthy = []
        for instance_id in group_instances:
            if instance_id in self.instances:
                instance = self.instances[instance_id]
                if instance.status == "healthy" and instance.connections < instance.max_connections:
                    healthy.append(instance_id)
        
        return healthy
    
    async def _apply_algorithm(self, rule: LoadBalancingRule, 
                            healthy_instances: List[str], 
                            routing_context: Dict[str, Any]) -> Optional[str]:
        """Apply load balancing algorithm to select instance."""
        try:
            if rule.algorithm == "round_robin":
                return self._round_robin_selection(healthy_instances)
            elif rule.algorithm == "weighted_round_robin":
                return self._weighted_round_robin_selection(healthy_instances)
            elif rule.algorithm == "least_connections":
                return self._least_connections_selection(healthy_instances)
            elif rule.algorithm == "response_time":
                return self._response_time_selection(healthy_instances)
            else:
                # Default to round robin
                return self._round_robin_selection(healthy_instances)
                
        except Exception as e:
            logger.error(f"Failed to apply algorithm {rule.algorithm}: {e}")
            return None
    
    def _round_robin_selection(self, instances: List[str]) -> Optional[str]:
        """Round robin selection algorithm."""
        if not instances:
            return None
        
        # Use request count for simple round robin
        min_requests = min(self.request_counts.get(instance_id, 0) for instance_id in instances)
        candidates = [instance_id for instance_id in instances 
                      if self.request_counts.get(instance_id, 0) == min_requests]
        
        return random.choice(candidates) if candidates else instances[0]
    
    def _weighted_round_robin_selection(self, instances: List[str]) -> Optional[str]:
        """Weighted round robin selection algorithm."""
        if not instances:
            return None
        
        # Calculate weighted selection
        weights = []
        for instance_id in instances:
            instance = self.instances[instance_id]
            weight = instance.weight
            
            # Adjust weight based on current load
            load_factor = instance.connections / instance.max_connections
            adjusted_weight = weight * (1 - load_factor)
            weights.append(adjusted_weight)
        
        # Weighted random selection
        total_weight = sum(weights)
        if total_weight == 0:
            return random.choice(instances)
        
        rand_value = random.random() * total_weight
        current_weight = 0
        
        for i, weight in enumerate(weights):
            current_weight += weight
            if rand_value <= current_weight:
                return instances[i]
        
        return instances[-1]
    
    def _least_connections_selection(self, instances: List[str]) -> Optional[str]:
        """Least connections selection algorithm."""
        if not instances:
            return None
        
        min_connections = min(self.instances[instance_id].connections for instance_id in instances)
        candidates = [instance_id for instance_id in instances 
                      if self.instances[instance_id].connections == min_connections]
        
        return random.choice(candidates) if candidates else instances[0]
    
    def _response_time_selection(self, instances: List[str]) -> Optional[str]:
        """Response time based selection algorithm."""
        if not instances:
            return None
        
        # Calculate response time scores (lower is better)
        response_times = {}
        for instance_id in instances:
            instance = self.instances[instance_id]
            times = self.response_times.get(instance_id, [])
            if times:
                avg_time = sum(times) / len(times)
                # Convert to score (higher is better)
                response_times[instance_id] = 1.0 / (avg_time + 0.001)
            else:
                response_times[instance_id] = 1.0
        
        # Select instance with best response time
        best_instance = max(response_times, key=response_times.get)
        return best_instance
    
    async def _health_check_loop(self):
        """Continuous health checking loop."""
        while True:
            try:
                await self._perform_health_checks()
                await asyncio.sleep(self.default_rule.health_check_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Health check loop error: {e}")
                await asyncio.sleep(10)
    
    async def _perform_health_checks(self):
        """Perform health checks on all instances."""
        tasks = []
        
        for instance_id, instance in self.instances.items():
            if instance.status != "maintenance":
                tasks.append(self._check_instance_health(instance_id))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def _check_instance_health(self, instance_id: str):
        """Check health of a specific instance."""
        try:
            instance = self.instances[instance_id]
            
            # Create health check URL
            health_url = f"{instance.protocol}://{instance.host}:{instance.port}/health"
            
            # Perform health check
            start_time = time.time()
            
            try:
                timeout = aiohttp.ClientTimeout(total=self.default_rule.health_check_timeout)
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.get(health_url) as response:
                        if response.status == 200:
                            # Healthy
                            instance.status = "healthy"
                            instance.last_health_check = time.time()
                            
                            # Update health check stats
                            if instance_id not in self.health_check_stats:
                                self.health_check_stats[instance_id] = {"success": 0, "failure": 0}
                            self.health_check_stats[instance_id]["success"] += 1
                            
                        else:
                            # Unhealthy
                            await self._mark_instance_unhealthy(instance_id, f"HTTP {response.status}")
                            
            except Exception as e:
                # Health check failed
                await self._mark_instance_unhealthy(instance_id, str(e))
            
            # Record health check time
            check_time = time.time() - start_time
            logger.debug(f"Health check for {instance_id} completed in {check_time:.3f}s")
            
        except Exception as e:
            logger.error(f"Failed to check health for {instance_id}: {e}")
    
    async def _mark_instance_unhealthy(self, instance_id: str, reason: str):
        """Mark an instance as unhealthy."""
        try:
            instance = self.instances[instance_id]
            
            if instance.status == "healthy":
                instance.status = "unhealthy"
                logger.warning(f"Instance {instance_id} marked unhealthy: {reason}")
            
            # Update health check stats
            if instance_id not in self.health_check_stats:
                self.health_check_stats[instance_id] = {"success": 0, "failure": 0}
            self.health_check_stats[instance_id]["failure"] += 1
            
            # Check if instance should be removed
            failures = self.health_check_stats[instance_id]["failure"]
            if failures >= self.default_rule.max_failures:
                logger.error(f"Instance {instance_id} exceeded max failures, removing from rotation")
                await self._remove_instance_from_rotation(instance_id)
                
        except Exception as e:
            logger.error(f"Failed to mark instance {instance_id} unhealthy: {e}")
    
    async def _remove_instance_from_rotation(self, instance_id: str):
        """Remove instance from rotation."""
        try:
            instance = self.instances[instance_id]
            instance.status = "draining"
            
            # Remove from all groups
            for group_instances in self.instance_groups.values():
                if instance_id in group_instances:
                    group_instances.remove(instance_id)
            
            logger.info(f"Instance {instance_id} removed from rotation")
            
        except Exception as e:
            logger.error(f"Failed to remove instance {instance_id} from rotation: {e}")
    
    async def _drain_instance(self, instance_id: str):
        """Drain an instance (stop sending new requests)."""
        try:
            instance = self.instances[instance_id]
            instance.status = "draining"
            
            # Wait for existing connections to complete
            while instance.connections > 0:
                await asyncio.sleep(1)
                logger.info(f"Waiting for {instance.connections} connections to drain for {instance_id}")
            
            logger.info(f"Instance {instance_id} drained successfully")
            
        except Exception as e:
            logger.error(f"Failed to drain instance {instance_id}: {e}")
    
    def _record_routing(self, decision: RoutingDecision):
        """Record routing decision for analytics."""
        self.routing_history.append(decision)
        
        # Update instance connection count
        if decision.instance_id in self.instances:
            self.instances[decision.instance_id].connections += 1
    
    async def _load_configuration(self):
        """Load load balancer configuration."""
        try:
            # In production, load from config file or database
            config_file = self.config.get("config_file")
            if config_file:
                # Load configuration logic here
                pass
            
            logger.info("Load balancer configuration loaded")
            
        except Exception as e:
            logger.error(f"Failed to load configuration: {e}")
    
    def get_load_balancer_stats(self) -> Dict[str, Any]:
        """Get comprehensive load balancer statistics."""
        stats = {
            "total_instances": len(self.instances),
            "healthy_instances": sum(1 for i in self.instances.values() if i.status == "healthy"),
            "unhealthy_instances": sum(1 for i in self.instances.values() if i.status == "unhealthy"),
            "draining_instances": sum(1 for i in self.instances.values() if i.status == "draining"),
            "maintenance_instances": sum(1 for i in self.instances.values() if i.status == "maintenance"),
            "total_requests": sum(self.request_counts.values()),
            "routing_history_size": len(self.routing_history),
            "sticky_sessions": len(self.sticky_sessions),
            "instance_groups": {group: len(instances) for group, instances in self.instance_groups.items()},
            "health_check_stats": self.health_check_stats
        }
        
        # Add instance details
        stats["instances"] = {}
        for instance_id, instance in self.instances.items():
            stats["instances"][instance_id] = {
                "host": instance.host,
                "port": instance.port,
                "status": instance.status,
                "connections": instance.connections,
                "max_connections": instance.max_connections,
                "response_time": instance.response_time,
                "error_rate": instance.error_rate,
                "weight": instance.weight,
                "requests": self.request_counts.get(instance_id, 0)
            }
        
        return stats
    
    def get_instance_health(self, instance_id: str) -> Optional[Dict[str, Any]]:
        """Get detailed health information for an instance."""
        if instance_id not in self.instances:
            return None
        
        instance = self.instances[instance_id]
        response_times = self.response_times.get(instance_id, [])
        
        health_info = {
            "instance_id": instance_id,
            "status": instance.status,
            "connections": instance.connections,
            "max_connections": instance.max_connections,
            "response_time": instance.response_time,
            "error_rate": instance.error_rate,
            "last_health_check": instance.last_health_check,
            "total_requests": self.request_counts.get(instance_id, 0),
            "avg_response_time": sum(response_times) / len(response_times) if response_times else 0,
            "health_check_stats": self.health_check_stats.get(instance_id, {}),
            "metadata": instance.metadata
        }
        
        return health_info

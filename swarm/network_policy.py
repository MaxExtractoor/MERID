"""
Network policy and proxy management for MERID AI swarm.

Implements proxy/relay registry, network policies, geo-compliance enforcement,
and comprehensive logging for all network operations.
"""

import threading

from utils.logger import get_logger
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from decimal import Decimal

logger = get_logger(__name__)


class ProxyType(Enum):
    """Proxy type."""
    HTTP = "http"
    HTTPS = "https"
    SOCKS5 = "socks5"
    VPN = "vpn"
    RELAY = "relay"
    DIRECT = "direct"


class NetworkSensitivity(Enum):
    """Network sensitivity level."""
    PUBLIC = "public"  # Public data, any network path OK
    SENSITIVE = "sensitive"  # User data, approved proxies only
    CRITICAL = "critical"  # Signing/keys, minimal path only
    INTERNAL = "internal"  # Internal only, no external proxies


class ComplianceStatus(Enum):
    """Compliance status."""
    COMPLIANT = "compliant"
    NON_COMPLIANT = "non_compliant"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"


@dataclass
class ProxyEndpoint:
    """Proxy or relay endpoint."""
    endpoint_id: str
    endpoint_type: ProxyType
    
    # Connection
    host: str
    port: int
    protocol: str  # "http", "https", "socks5", "vpn"
    
    # Metadata
    provider: str
    region: str
    latency_ms: float
    cost_per_request: Decimal = Decimal("0")
    
    # Compliance
    compliance_flags: List[str] = field(default_factory=list)
    allowed_regions: Set[str] = field(default_factory=set)
    blocked_regions: Set[str] = field(default_factory=set)
    
    # Capabilities
    supports_https: bool = True
    supports_websocket: bool = True
    max_concurrent_connections: int = 100
    
    # Status
    active: bool = True
    health_score: float = 1.0  # 0.0 (unhealthy) to 1.0 (healthy)
    last_health_check: Optional[datetime] = None
    
    # Usage
    total_requests: int = 0
    failed_requests: int = 0
    avg_latency_ms: float = 0.0
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class NetworkPolicy:
    """Network policy for agent or operation."""
    policy_id: str
    policy_name: str
    
    # Sensitivity
    sensitivity_level: NetworkSensitivity

    # Allowed endpoints
    allowed_proxy_types: Set[ProxyType] = field(default_factory=set)
    allowed_proxy_ids: Set[str] = field(default_factory=set)
    allowed_rpc_endpoints: Set[str] = field(default_factory=set)
    allowed_api_endpoints: Set[str] = field(default_factory=set)

    # Restrictions
    require_encryption: bool = True
    require_authentication: bool = True
    max_latency_ms: float = 1000.0

    # Geo-compliance
    allowed_regions: Set[str] = field(default_factory=set)
    blocked_regions: Set[str] = field(default_factory=set)

    # Fallback
    fallback_to_direct: bool = False
    fallback_proxy_ids: List[str] = field(default_factory=list)

    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class NetworkRequest:
    """Network request with policy enforcement."""
    request_id: str
    agent_id: str
    
    # Request details
    target_url: str
    method: str  # "GET", "POST", etc.
    policy_id: str
    sensitivity_level: NetworkSensitivity

    headers: Dict[str, str] = field(default_factory=dict)
    
    # Network path
    proxy_id: Optional[str] = None
    proxy_type: ProxyType = ProxyType.DIRECT
    actual_endpoint: Optional[str] = None
    
    # Compliance
    user_region: Optional[str] = None
    compliance_status: ComplianceStatus = ComplianceStatus.UNKNOWN
    compliance_checks: List[str] = field(default_factory=list)
    
    # Result
    success: bool = False
    status_code: Optional[int] = None
    latency_ms: Optional[float] = None
    error_message: Optional[str] = None
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


@dataclass
class GeoComplianceRule:
    """Geo-compliance rule."""
    rule_id: str
    rule_name: str
    
    # Scope
    applies_to_regions: Set[str] = field(default_factory=set)
    
    # Restrictions
    blocked_venues: Set[str] = field(default_factory=set)
    blocked_assets: Set[str] = field(default_factory=set)
    blocked_protocols: Set[str] = field(default_factory=set)
    
    # Allowed alternatives
    allowed_venues: Set[str] = field(default_factory=set)
    
    # Enforcement
    enforce_strict: bool = True
    log_violations: bool = True
    
    created_at: datetime = field(default_factory=datetime.utcnow)


@dataclass
class NetworkAlert:
    """Network anomaly alert."""
    alert_id: str
    alert_type: str  # "unusual_region", "spike_traffic", "proxy_failure", "compliance_violation"
    severity: str  # "low", "medium", "high", "critical"
    
    # Details
    agent_id: Optional[str] = None
    proxy_id: Optional[str] = None
    description: str = ""
    
    # Metrics
    metric_name: Optional[str] = None
    metric_value: Optional[float] = None
    threshold: Optional[float] = None
    
    # Response
    action_taken: Optional[str] = None
    resolved: bool = False
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None


class NetworkPolicyManager:
    """
    Network policy and proxy management for MERID AI swarm.
    
    Implements:
    - Proxy/relay endpoint registry
    - Network policies per agent/operation
    - Geo-compliance enforcement
    - Proxy selection and fallback
    - Comprehensive network logging
    - Anomaly detection and alerting
    """
    
    def __init__(self):
        self._proxies: Dict[str, ProxyEndpoint] = {}
        self._policies: Dict[str, NetworkPolicy] = {}
        self._geo_rules: Dict[str, GeoComplianceRule] = {}
        self._requests: List[NetworkRequest] = []
        self._alerts: List[NetworkAlert] = []
        
        self._initialize_default_config()
    
    def _initialize_default_config(self) -> None:
        """Initialize default network configuration."""
        
        # Direct connection (no proxy)
        self.register_proxy(
            endpoint_id="direct",
            endpoint_type=ProxyType.DIRECT,
            host="",
            port=0,
            protocol="direct",
            provider="direct",
            region="global",
            latency_ms=0.0,
            allowed_regions={"*"},
        )
        
        # Example RPC proxy (Infura)
        self.register_proxy(
            endpoint_id="infura_mainnet",
            endpoint_type=ProxyType.HTTPS,
            host="mainnet.infura.io",
            port=443,
            protocol="https",
            provider="infura",
            region="us-east-1",
            latency_ms=50.0,
            cost_per_request=Decimal("0.0001"),
            allowed_regions={"US", "EU", "GLOBAL"},
        )
        
        # Example RPC proxy (Alchemy)
        self.register_proxy(
            endpoint_id="alchemy_mainnet",
            endpoint_type=ProxyType.HTTPS,
            host="eth-mainnet.g.alchemy.com",
            port=443,
            protocol="https",
            provider="alchemy",
            region="us-west-2",
            latency_ms=45.0,
            cost_per_request=Decimal("0.0001"),
            allowed_regions={"US", "EU", "GLOBAL"},
        )
        
        # Public network policy (low sensitivity)
        self.create_policy(
            policy_id="public_data",
            policy_name="Public Data Access",
            sensitivity_level=NetworkSensitivity.PUBLIC,
            allowed_proxy_types={ProxyType.DIRECT, ProxyType.HTTP, ProxyType.HTTPS},
            allowed_proxy_ids={"direct", "infura_mainnet", "alchemy_mainnet"},
            fallback_to_direct=True,
        )
        
        # Sensitive network policy (user data)
        self.create_policy(
            policy_id="sensitive_data",
            policy_name="Sensitive Data Access",
            sensitivity_level=NetworkSensitivity.SENSITIVE,
            allowed_proxy_types={ProxyType.HTTPS, ProxyType.VPN},
            allowed_proxy_ids={"infura_mainnet", "alchemy_mainnet"},
            require_encryption=True,
            require_authentication=True,
            fallback_to_direct=False,
        )
        
        # Critical network policy (signing/keys)
        self.create_policy(
            policy_id="critical_ops",
            policy_name="Critical Operations",
            sensitivity_level=NetworkSensitivity.CRITICAL,
            allowed_proxy_types={ProxyType.DIRECT},
            allowed_proxy_ids={"direct"},
            require_encryption=True,
            require_authentication=True,
            fallback_to_direct=False,
            max_latency_ms=100.0,
        )
        
        # US geo-compliance rule
        self.add_geo_rule(
            rule_id="us_compliance",
            rule_name="US Regulatory Compliance",
            applies_to_regions={"US"},
            blocked_venues={"binance", "bybit"},  # Example blocked venues
            allowed_venues={"coinbase", "kraken", "uniswap"},
        )
        
        logger.info("Initialized default network configuration")
    
    def register_proxy(
        self,
        endpoint_id: str,
        endpoint_type: ProxyType,
        host: str,
        port: int,
        protocol: str,
        provider: str,
        region: str,
        latency_ms: float,
        cost_per_request: Decimal = Decimal("0"),
        allowed_regions: Optional[Set[str]] = None,
        blocked_regions: Optional[Set[str]] = None,
    ) -> ProxyEndpoint:
        """Register proxy endpoint."""
        proxy = ProxyEndpoint(
            endpoint_id=endpoint_id,
            endpoint_type=endpoint_type,
            host=host,
            port=port,
            protocol=protocol,
            provider=provider,
            region=region,
            latency_ms=latency_ms,
            cost_per_request=cost_per_request,
            allowed_regions=allowed_regions or set(),
            blocked_regions=blocked_regions or set(),
        )
        
        self._proxies[endpoint_id] = proxy
        
        logger.info(
            f"Registered proxy '{endpoint_id}': {provider} ({region}, {latency_ms}ms)"
        )
        
        return proxy
    
    def create_policy(
        self,
        policy_id: str,
        policy_name: str,
        sensitivity_level: NetworkSensitivity,
        allowed_proxy_types: Optional[Set[ProxyType]] = None,
        allowed_proxy_ids: Optional[Set[str]] = None,
        allowed_rpc_endpoints: Optional[Set[str]] = None,
        require_encryption: bool = True,
        require_authentication: bool = True,
        fallback_to_direct: bool = False,
        max_latency_ms: float = 1000.0,
    ) -> NetworkPolicy:
        """Create network policy."""
        policy = NetworkPolicy(
            policy_id=policy_id,
            policy_name=policy_name,
            sensitivity_level=sensitivity_level,
            allowed_proxy_types=allowed_proxy_types or set(),
            allowed_proxy_ids=allowed_proxy_ids or set(),
            allowed_rpc_endpoints=allowed_rpc_endpoints or set(),
            require_encryption=require_encryption,
            require_authentication=require_authentication,
            fallback_to_direct=fallback_to_direct,
            max_latency_ms=max_latency_ms,
        )
        
        self._policies[policy_id] = policy
        
        logger.info(
            f"Created network policy '{policy_id}': {sensitivity_level.value}"
        )
        
        return policy
    
    def add_geo_rule(
        self,
        rule_id: str,
        rule_name: str,
        applies_to_regions: Set[str],
        blocked_venues: Optional[Set[str]] = None,
        blocked_assets: Optional[Set[str]] = None,
        allowed_venues: Optional[Set[str]] = None,
    ) -> GeoComplianceRule:
        """Add geo-compliance rule."""
        rule = GeoComplianceRule(
            rule_id=rule_id,
            rule_name=rule_name,
            applies_to_regions=applies_to_regions,
            blocked_venues=blocked_venues or set(),
            blocked_assets=blocked_assets or set(),
            allowed_venues=allowed_venues or set(),
        )
        
        self._geo_rules[rule_id] = rule
        
        logger.info(
            f"Added geo-compliance rule '{rule_id}' for regions: {applies_to_regions}"
        )
        
        return rule
    
    def select_proxy(
        self,
        policy_id: str,
        user_region: Optional[str] = None,
        prefer_low_latency: bool = True,
    ) -> Optional[ProxyEndpoint]:
        """Select best proxy based on policy and preferences."""
        policy = self._policies.get(policy_id)
        if not policy:
            logger.error(f"Policy '{policy_id}' not found")
            return None
        
        # Get allowed proxies
        candidates = [
            proxy for proxy in self._proxies.values()
            if proxy.endpoint_id in policy.allowed_proxy_ids
            and proxy.endpoint_type in policy.allowed_proxy_types
            and proxy.active
            and proxy.health_score > 0.5
        ]
        
        # Filter by region
        if user_region:
            candidates = [
                proxy for proxy in candidates
                if not proxy.allowed_regions or user_region in proxy.allowed_regions or "*" in proxy.allowed_regions
            ]
            candidates = [
                proxy for proxy in candidates
                if user_region not in proxy.blocked_regions
            ]
        
        # Filter by latency
        candidates = [
            proxy for proxy in candidates
            if proxy.latency_ms <= policy.max_latency_ms
        ]
        
        if not candidates:
            if policy.fallback_to_direct:
                return self._proxies.get("direct")
            return None
        
        # Select best proxy
        if prefer_low_latency:
            # Sort by latency, then health score
            candidates.sort(key=lambda p: (p.latency_ms, -p.health_score))
        else:
            # Sort by health score, then latency
            candidates.sort(key=lambda p: (-p.health_score, p.latency_ms))
        
        return candidates[0]
    
    def check_compliance(
        self,
        user_region: str,
        target_venue: str,
        target_asset: Optional[str] = None,
    ) -> tuple[ComplianceStatus, List[str]]:
        """Check geo-compliance for operation."""
        checks = []
        
        # Find applicable rules
        applicable_rules = [
            rule for rule in self._geo_rules.values()
            if user_region in rule.applies_to_regions
        ]
        
        if not applicable_rules:
            checks.append(f"No compliance rules for region '{user_region}'")
            return ComplianceStatus.UNKNOWN, checks
        
        # Check each rule
        for rule in applicable_rules:
            # Check blocked venues
            if target_venue in rule.blocked_venues:
                checks.append(f"Venue '{target_venue}' blocked in '{user_region}' by rule '{rule.rule_id}'")
                return ComplianceStatus.NON_COMPLIANT, checks
            
            # Check allowed venues (if whitelist exists)
            if rule.allowed_venues and target_venue not in rule.allowed_venues:
                checks.append(f"Venue '{target_venue}' not in allowed list for '{user_region}'")
                return ComplianceStatus.RESTRICTED, checks
            
            # Check blocked assets
            if target_asset and target_asset in rule.blocked_assets:
                checks.append(f"Asset '{target_asset}' blocked in '{user_region}' by rule '{rule.rule_id}'")
                return ComplianceStatus.NON_COMPLIANT, checks
        
        checks.append(f"Compliant: '{target_venue}' allowed in '{user_region}'")
        return ComplianceStatus.COMPLIANT, checks
    
    def create_request(
        self,
        agent_id: str,
        target_url: str,
        method: str,
        policy_id: str,
        user_region: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> NetworkRequest:
        """Create network request with policy enforcement."""
        policy = self._policies.get(policy_id)
        if not policy:
            raise ValueError(f"Policy '{policy_id}' not found")
        
        request_id = f"req_{agent_id}_{int(datetime.utcnow().timestamp())}"
        
        # Select proxy
        proxy = self.select_proxy(policy_id, user_region)
        
        request = NetworkRequest(
            request_id=request_id,
            agent_id=agent_id,
            target_url=target_url,
            method=method,
            headers=headers or {},
            proxy_id=proxy.endpoint_id if proxy else None,
            proxy_type=proxy.endpoint_type if proxy else ProxyType.DIRECT,
            policy_id=policy_id,
            sensitivity_level=policy.sensitivity_level,
            user_region=user_region,
        )
        
        self._requests.append(request)
        
        logger.info(
            f"Created network request '{request_id}': {method} {target_url} "
            f"via {proxy.endpoint_id if proxy else 'direct'}"
        )
        
        return request
    
    def complete_request(
        self,
        request_id: str,
        success: bool,
        status_code: Optional[int] = None,
        latency_ms: Optional[float] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Complete network request and update metrics."""
        request = next((r for r in self._requests if r.request_id == request_id), None)
        if not request:
            logger.error(f"Request '{request_id}' not found")
            return
        
        request.success = success
        request.status_code = status_code
        request.latency_ms = latency_ms
        request.error_message = error_message
        request.completed_at = datetime.utcnow()
        
        # Update proxy metrics
        if request.proxy_id:
            proxy = self._proxies.get(request.proxy_id)
            if proxy:
                proxy.total_requests += 1
                if not success:
                    proxy.failed_requests += 1
                if latency_ms:
                    # Update rolling average latency
                    proxy.avg_latency_ms = (
                        proxy.avg_latency_ms * 0.9 + latency_ms * 0.1
                    )
        
        # Check for anomalies
        self._check_anomalies(request)
        
        logger.info(
            f"Completed request '{request_id}': "
            f"{'success' if success else 'failed'} ({latency_ms}ms)"
        )
    
    def _check_anomalies(self, request: NetworkRequest) -> None:
        """Check for network anomalies."""
        # Check unusual region
        if request.user_region and request.user_region not in {"US", "EU", "GLOBAL"}:
            self._create_alert(
                alert_type="unusual_region",
                severity="medium",
                agent_id=request.agent_id,
                description=f"Request from unusual region: {request.user_region}",
            )
        
        # Check high latency
        if request.latency_ms and request.latency_ms > 5000:
            self._create_alert(
                alert_type="high_latency",
                severity="medium",
                agent_id=request.agent_id,
                proxy_id=request.proxy_id,
                description=f"High latency: {request.latency_ms}ms",
                metric_name="latency_ms",
                metric_value=request.latency_ms,
                threshold=5000.0,
            )
        
        # Check compliance violation
        if request.compliance_status == ComplianceStatus.NON_COMPLIANT:
            self._create_alert(
                alert_type="compliance_violation",
                severity="critical",
                agent_id=request.agent_id,
                description=f"Compliance violation: {request.compliance_checks}",
            )
    
    def _create_alert(
        self,
        alert_type: str,
        severity: str,
        agent_id: Optional[str] = None,
        proxy_id: Optional[str] = None,
        description: str = "",
        metric_name: Optional[str] = None,
        metric_value: Optional[float] = None,
        threshold: Optional[float] = None,
    ) -> NetworkAlert:
        """Create network alert."""
        alert_id = f"alert_{int(datetime.utcnow().timestamp())}"
        
        alert = NetworkAlert(
            alert_id=alert_id,
            alert_type=alert_type,
            severity=severity,
            agent_id=agent_id,
            proxy_id=proxy_id,
            description=description,
            metric_name=metric_name,
            metric_value=metric_value,
            threshold=threshold,
        )
        
        self._alerts.append(alert)
        
        logger.warning(
            f"Network alert [{severity}]: {alert_type} - {description}"
        )
        
        return alert
    
    def get_proxy(self, endpoint_id: str) -> Optional[ProxyEndpoint]:
        """Get proxy endpoint by ID."""
        return self._proxies.get(endpoint_id)
    
    def get_policy(self, policy_id: str) -> Optional[NetworkPolicy]:
        """Get network policy by ID."""
        return self._policies.get(policy_id)
    
    def get_active_proxies(self) -> List[ProxyEndpoint]:
        """Get all active proxies."""
        return [p for p in self._proxies.values() if p.active]
    
    def get_requests(
        self,
        agent_id: Optional[str] = None,
        proxy_id: Optional[str] = None,
        since: Optional[datetime] = None,
    ) -> List[NetworkRequest]:
        """Get network requests."""
        requests = self._requests
        
        if agent_id:
            requests = [r for r in requests if r.agent_id == agent_id]
        
        if proxy_id:
            requests = [r for r in requests if r.proxy_id == proxy_id]
        
        if since:
            requests = [r for r in requests if r.created_at >= since]
        
        return requests
    
    def get_active_alerts(
        self,
        severity: Optional[str] = None,
        alert_type: Optional[str] = None,
    ) -> List[NetworkAlert]:
        """Get active alerts."""
        alerts = [a for a in self._alerts if not a.resolved]
        
        if severity:
            alerts = [a for a in alerts if a.severity == severity]
        
        if alert_type:
            alerts = [a for a in alerts if a.alert_type == alert_type]
        
        return alerts


_network_policy_manager: Optional[NetworkPolicyManager] = None
_network_policy_manager_lock = threading.Lock()


def get_network_policy_manager() -> NetworkPolicyManager:
    """Get global NetworkPolicyManager instance."""
    global _network_policy_manager
    if _network_policy_manager is None:
        with _network_policy_manager_lock:
            if _network_policy_manager is None:
                _network_policy_manager = NetworkPolicyManager()
    return _network_policy_manager

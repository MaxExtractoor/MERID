from dataclasses import dataclass, field
from enum import Enum
from typing import Set, List
from datetime import datetime

class NetworkSensitivity(Enum):
    PUBLIC = "public"

class ProxyType(Enum):
    HTTPS = "https"

@dataclass
class NetworkPolicy:
    policy_id: str
    policy_name: str
    sensitivity_level: NetworkSensitivity
    allowed_proxy_types: Set[ProxyType] = field(default_factory=set)
    allowed_proxy_ids: Set[str] = field(default_factory=set)
    allowed_rpc_endpoints: Set[str] = field(default_factory=set)
    allowed_api_endpoints: Set[str] = field(default_factory=set)
    require_encryption: bool = True
    require_authentication: bool = True
    max_latency_ms: float = 1000.0
    allowed_regions: Set[str] = field(default_factory=set)
    blocked_regions: Set[str] = field(default_factory=set)
    fallback_to_direct: bool = False
    fallback_proxy_ids: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.utcnow)

print(NetworkPolicy("a","b",NetworkSensitivity.PUBLIC))

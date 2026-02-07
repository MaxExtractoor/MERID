from dataclasses import dataclass, field
from enum import Enum
from typing import Set

class NetworkSensitivity(Enum):
    PUBLIC = "public"

@dataclass
class NetworkPolicy:
    policy_id: str
    policy_name: str
    sensitivity_level: NetworkSensitivity
    allowed_proxy_types: Set[str] = field(default_factory=set)
    fallback_to_direct: bool = False

print(NetworkPolicy("id","name",NetworkSensitivity.PUBLIC))

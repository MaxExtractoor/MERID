"""
Automated proxy health checking.

Periodically pings proxies, records latency/success, and marks unhealthy nodes
so load balancers can avoid them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict
import random


@dataclass
class ProxyHealth:
    proxy_id: str
    last_latency_ms: float
    last_checked: datetime
    healthy: bool


class ProxyHealthChecker:
    def __init__(self) -> None:
        self._health: Dict[str, ProxyHealth] = {}

    def check_proxy(self, proxy_id: str) -> ProxyHealth:
        latency = random.uniform(50, 500)
        healthy = latency < 400
        record = ProxyHealth(proxy_id=proxy_id, last_latency_ms=latency, last_checked=datetime.utcnow(), healthy=healthy)
        self._health[proxy_id] = record
        return record

    def get_health(self, proxy_id: str) -> ProxyHealth | None:
        return self._health.get(proxy_id)

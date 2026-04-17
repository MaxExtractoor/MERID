"""
Cross-region proxy load balancing utilities.

Distributes requests across proxy pools per geography, tracking latency and
success metrics to ensure optimal routing for agents operating in different
regions.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
from datetime import datetime
import random


@dataclass
class ProxyEndpoint:
    endpoint_id: str
    region: str
    url: str
    latency_ms: float
    success_rate: float
    last_checked: datetime


class CrossRegionProxyLoadBalancer:
    def __init__(self) -> None:
        self._proxies: Dict[str, List[ProxyEndpoint]] = {}

    def register_proxy(self, proxy: ProxyEndpoint) -> None:
        self._proxies.setdefault(proxy.region, []).append(proxy)

    def choose_proxy(self, region: str) -> ProxyEndpoint:
        candidates = self._proxies.get(region) or sum(self._proxies.values(), [])
        scored = sorted(candidates, key=lambda proxy: (proxy.latency_ms * (1 - proxy.success_rate)))
        if not scored:
            raise ValueError("No proxies available")
        top = scored[: max(1, len(scored) // 3)]
        return random.choice(top)

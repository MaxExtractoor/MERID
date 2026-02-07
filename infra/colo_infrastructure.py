"""
Co-location infrastructure configuration for MERID.

Defines rack layouts, connectivity policies, and service deployment plans to
simulate colo provisioning in the roadmap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
from datetime import datetime


@dataclass
class RackAllocation:
    rack_id: str
    role: str
    power_kw: float
    network_segment: str
    occupancy_pct: float
    cooling_zone: str


@dataclass
class ConnectivityPolicy:
    segment: str
    providers: List[str]
    redundancy_level: str
    firewall_profile: str


class ColoInfrastructure:
    def __init__(self) -> None:
        self._racks: Dict[str, RackAllocation] = {}
        self._connectivity: Dict[str, ConnectivityPolicy] = {}
        self._deployments: Dict[str, str] = {}
        self._last_updated = datetime.utcnow()

    def register_rack(self, rack: RackAllocation) -> None:
        self._racks[rack.rack_id] = rack
        self._last_updated = datetime.utcnow()

    def set_connectivity(self, policy: ConnectivityPolicy) -> None:
        self._connectivity[policy.segment] = policy
        self._last_updated = datetime.utcnow()

    def deploy_service(self, service: str, rack_id: str) -> None:
        self._deployments[service] = rack_id
        self._last_updated = datetime.utcnow()

    def status(self) -> Dict[str, str]:
        return {
            "racks": str(len(self._racks)),
            "segments": str(len(self._connectivity)),
            "services": str(len(self._deployments)),
            "last_updated": self._last_updated.isoformat(),
        }

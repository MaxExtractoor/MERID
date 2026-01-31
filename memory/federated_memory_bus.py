"""
Federated memory across swarm instances.

Synchronizes summarized memory entries between regional clusters using conflict
resolution and provenance tracking.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List


@dataclass
class FederatedMemoryPacket:
    packet_id: str
    origin_cluster: str
    entry_id: str
    summary: str
    embedding_checksum: str
    timestamp: datetime


@dataclass
class MemorySyncState:
    entry_id: str
    latest_packet_id: str
    clusters: List[str]
    last_synced: datetime


class FederatedMemoryBus:
    def __init__(self) -> None:
        self._packets: Dict[str, FederatedMemoryPacket] = {}
        self._state: Dict[str, MemorySyncState] = {}

    def publish(self, packet: FederatedMemoryPacket) -> None:
        self._packets[packet.packet_id] = packet
        state = self._state.get(packet.entry_id)
        if state:
            if packet.timestamp > state.last_synced:
                state.latest_packet_id = packet.packet_id
                if packet.origin_cluster not in state.clusters:
                    state.clusters.append(packet.origin_cluster)
                state.last_synced = packet.timestamp
        else:
            self._state[packet.entry_id] = MemorySyncState(
                entry_id=packet.entry_id,
                latest_packet_id=packet.packet_id,
                clusters=[packet.origin_cluster],
                last_synced=packet.timestamp,
            )

    def sync_status(self, entry_id: str) -> MemorySyncState | None:
        return self._state.get(entry_id)

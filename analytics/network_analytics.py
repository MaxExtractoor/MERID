"""
Advanced analytics and reporting for network/model orchestration.

Aggregates per-agent latency/cost/compliance stats and produces narratives
usable in governance dashboards.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List
from datetime import datetime


@dataclass
class AgentAnalyticsRecord:
    agent_id: str
    avg_latency_ms: float
    success_rate: float
    compliance_incidents: int
    cost_usd: float
    window_start: datetime
    window_end: datetime


class NetworkAnalyticsReporter:
    def __init__(self) -> None:
        self._records: Dict[str, AgentAnalyticsRecord] = {}

    def upsert_record(self, record: AgentAnalyticsRecord) -> None:
        self._records[record.agent_id] = record

    def summary(self) -> Dict[str, float]:
        if not self._records:
            return {}
        total_cost = sum(record.cost_usd for record in self._records.values())
        avg_latency = sum(record.avg_latency_ms for record in self._records.values()) / len(self._records)
        incident_rate = sum(record.compliance_incidents for record in self._records.values()) / max(len(self._records), 1)
        return {"total_cost_usd": total_cost, "avg_latency_ms": avg_latency, "avg_compliance_incidents": incident_rate}

    def top_outliers(self, limit: int = 3) -> List[AgentAnalyticsRecord]:
        return sorted(self._records.values(), key=lambda record: (record.compliance_incidents, record.avg_latency_ms), reverse=True)[:limit]

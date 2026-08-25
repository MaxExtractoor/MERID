"""Position Drift Detector

Compares three sources of position truth:
1. REST position (Kalshi API snapshot)
2. Derived position (ledger replay)
3. Live cache (in-memory state)

Triggers alerts if mismatch persists > N seconds.
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional, Set
import logging

logger = logging.getLogger(__name__)


class DriftSeverity(Enum):
    """Severity levels for position drift."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class PositionSnapshot:
    """Snapshot of position from a specific source."""
    source: str  # "rest", "ledger", "cache"
    market_id: str
    agent_id: str
    contracts: int
    side: str
    avg_price_cents: Optional[int]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class DriftEvent:
    """Record of a position drift event."""
    market_id: str
    agent_id: str
    severity: DriftSeverity
    description: str
    rest_contracts: int
    ledger_contracts: int
    cache_contracts: int
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    resolved: bool = False
    resolution_timestamp: Optional[datetime] = None


class PositionDriftDetector:
    """Detects position drift across REST, ledger, and cache sources."""
    
    _instance: Optional["PositionDriftDetector"] = None
    _initialized: bool = False
    
    def __new__(cls) -> "PositionDriftDetector":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    def get_instance(cls) -> "PositionDriftDetector":
        """Get singleton instance."""
        if not cls._initialized:
            cls._instance = cls()
            cls._initialized = True
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        self._initialized = True
        
        # Track active drift events
        self._active_drifts: Dict[str, DriftEvent] = {}  # (market_id, agent_id) -> DriftEvent
        self._drift_history: List[DriftEvent] = []
        self._max_drift_history = 1000
        
        # Drift threshold: alert if mismatch persists > N seconds
        self._drift_threshold_seconds = 30.0
        
        # Critical threshold: halt trading if mismatch persists > N seconds
        self._critical_threshold_seconds = 120.0
        
        # Last snapshots from each source
        self._rest_snapshots: Dict[str, PositionSnapshot] = {}  # market_id -> snapshot
        self._ledger_snapshots: Dict[str, PositionSnapshot] = {}
        self._cache_snapshots: Dict[str, PositionSnapshot] = {}
        
        # Metrics
        self._checks_run: int = 0
        self._drifts_detected: int = 0
        self._drifts_resolved: int = 0
        
        logger.info("[POSITION-DRIFT-DETECTOR] Initialized")
    
    async def check_drift(
        self,
        market_id: str,
        agent_id: str,
        rest_position: Optional[Dict[str, Any]],
        ledger_position: Optional[Dict[str, Any]],
        cache_position: Optional[Dict[str, Any]]
    ) -> Optional[DriftEvent]:
        """
        Check for position drift across three sources.
        
        Args:
            market_id: Market identifier
            agent_id: Agent identifier
            rest_position: Position from REST API (or None)
            ledger_position: Position derived from ledger (or None)
            cache_position: Position from live cache (or None)
            
        Returns:
            DriftEvent if drift detected, None if all sources agree
        """
        self._checks_run += 1
        
        # Extract contract counts
        rest_contracts = rest_position.get("contracts", 0) if rest_position else 0
        ledger_contracts = ledger_position.get("contracts", 0) if ledger_position else 0
        cache_contracts = cache_position.get("contracts", 0) if cache_position else 0
        
        # Check if all sources agree
        if rest_contracts == ledger_contracts == cache_contracts:
            # No drift - check if we have an active drift to resolve
            drift_key = f"{market_id}:{agent_id}"
            if drift_key in self._active_drifts:
                drift = self._active_drifts[drift_key]
                drift.resolved = True
                drift.resolution_timestamp = datetime.now(timezone.utc)
                self._drifts_resolved += 1
                del self._active_drifts[drift_key]
                logger.info(
                    "[DRIFT-RESOLVED] Position drift resolved for %s: all sources agree on %d contracts",
                    market_id, rest_contracts
                )
            return None
        
        # Drift detected
        self._drifts_detected += 1
        
        # Determine severity based on delta and duration
        max_delta = max(
            abs(rest_contracts - ledger_contracts),
            abs(rest_contracts - cache_contracts),
            abs(ledger_contracts - cache_contracts)
        )
        
        drift_key = f"{market_id}:{agent_id}"
        existing_drift = self._active_drifts.get(drift_key)
        
        if existing_drift:
            # Update existing drift
            existing_drift.rest_contracts = rest_contracts
            existing_drift.ledger_contracts = ledger_contracts
            existing_drift.cache_contracts = cache_contracts
            existing_drift.timestamp = datetime.now(timezone.utc)
            
            # Check if drift has persisted long enough to escalate
            duration = (datetime.now(timezone.utc) - existing_drift.timestamp).total_seconds()
            if duration > self._critical_threshold_seconds:
                existing_drift.severity = DriftSeverity.CRITICAL
            elif duration > self._drift_threshold_seconds:
                existing_drift.severity = DriftSeverity.ERROR
            elif max_delta > 1:
                existing_drift.severity = DriftSeverity.ERROR
            else:
                existing_drift.severity = DriftSeverity.WARNING
            
            drift = existing_drift
        else:
            # New drift event
            severity = DriftSeverity.WARNING
            if max_delta > 1:
                severity = DriftSeverity.ERROR
            
            drift = DriftEvent(
                market_id=market_id,
                agent_id=agent_id,
                severity=severity,
                description=f"Position drift detected: REST={rest_contracts}, Ledger={ledger_contracts}, Cache={cache_contracts}",
                rest_contracts=rest_contracts,
                ledger_contracts=ledger_contracts,
                cache_contracts=cache_contracts
            )
            self._active_drifts[drift_key] = drift
            self._drift_history.append(drift)
            if len(self._drift_history) > self._max_drift_history:
                self._drift_history.pop(0)
        
        # Log based on severity
        if drift.severity == DriftSeverity.CRITICAL:
            logger.critical(
                "[DRIFT-CRITICAL] Position drift CRITICAL for %s: REST=%d, Ledger=%d, Cache=%d - "
                "persisted > %d seconds - consider trading halt",
                market_id, rest_contracts, ledger_contracts, cache_contracts,
                self._critical_threshold_seconds
            )
        elif drift.severity == DriftSeverity.ERROR:
            logger.error(
                "[DRIFT-ERROR] Position drift ERROR for %s: REST=%d, Ledger=%d, Cache=%d",
                market_id, rest_contracts, ledger_contracts, cache_contracts
            )
        else:
            logger.warning(
                "[DRIFT-WARNING] Position drift WARNING for %s: REST=%d, Ledger=%d, Cache=%d",
                market_id, rest_contracts, ledger_contracts, cache_contracts
            )
        
        return drift
    
    def get_active_drifts(self) -> List[DriftEvent]:
        """Get all currently active drift events."""
        return list(self._active_drifts.values())
    
    def get_critical_drifts(self) -> List[DriftEvent]:
        """Get only critical drift events (should trigger trading halt)."""
        return [d for d in self._active_drifts.values() if d.severity == DriftSeverity.CRITICAL]
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get drift detector metrics."""
        return {
            "checks_run": self._checks_run,
            "drifts_detected": self._drifts_detected,
            "drifts_resolved": self._drifts_resolved,
            "active_drifts": len(self._active_drifts),
            "critical_drifts": len(self.get_critical_drifts()),
            "drift_threshold_seconds": self._drift_threshold_seconds,
            "critical_threshold_seconds": self._critical_threshold_seconds
        }
    
    def clear_drift(self, market_id: str, agent_id: str) -> None:
        """Manually clear a drift event (for testing or manual resolution)."""
        drift_key = f"{market_id}:{agent_id}"
        if drift_key in self._active_drifts:
            drift = self._active_drifts[drift_key]
            drift.resolved = True
            drift.resolution_timestamp = datetime.now(timezone.utc)
            self._drifts_resolved += 1
            del self._active_drifts[drift_key]
            logger.info("[DRIFT-CLEARED] Manually cleared drift for %s", market_id)


def get_position_drift_detector() -> PositionDriftDetector:
    """Get singleton instance of PositionDriftDetector."""
    return PositionDriftDetector.get_instance()

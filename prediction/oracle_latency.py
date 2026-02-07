"""
Oracle Latency Detector.

Detects latency between real-world events and oracle price updates
on prediction markets. This latency creates exploitable windows.

Version: 1.0.0
"""

from __future__ import annotations

import asyncio
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum

from utils.logger import get_logger

logger = get_logger("prediction.oracle_latency")


class OracleType(Enum):
    """Types of oracles."""
    CHAINLINK = "chainlink"
    PYTH = "pyth"
    UMA = "uma"
    API3 = "api3"
    CUSTOM = "custom"


class EventType(Enum):
    """Types of events that oracles track."""
    PRICE = "price"
    SPORTS = "sports"
    ELECTION = "election"
    WEATHER = "weather"
    ECONOMIC = "economic"
    CUSTOM = "custom"


@dataclass
class OracleReading:
    """A single oracle reading."""
    oracle_id: str
    oracle_type: OracleType
    event_type: EventType
    value: Any
    timestamp: float
    block_number: Optional[int] = None
    tx_hash: Optional[str] = None


@dataclass
class LatencyMeasurement:
    """Measurement of oracle latency."""
    oracle_id: str
    event_id: str
    real_world_time: float  # When event actually occurred
    oracle_update_time: float  # When oracle reflected it
    latency_seconds: float
    latency_blocks: int = 0
    confidence: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "oracle_id": self.oracle_id,
            "event_id": self.event_id,
            "real_world_time": self.real_world_time,
            "oracle_update_time": self.oracle_update_time,
            "latency_seconds": self.latency_seconds,
            "latency_blocks": self.latency_blocks,
            "confidence": self.confidence,
        }


@dataclass
class LatencyProfile:
    """Statistical profile of oracle latency."""
    oracle_id: str
    oracle_type: OracleType
    event_type: EventType
    
    # Statistics
    avg_latency_seconds: float = 0.0
    min_latency_seconds: float = 0.0
    max_latency_seconds: float = 0.0
    std_dev_seconds: float = 0.0
    
    # Percentiles
    p50_latency: float = 0.0
    p90_latency: float = 0.0
    p99_latency: float = 0.0
    
    # Sample info
    sample_count: int = 0
    last_updated: float = field(default_factory=time.time)
    
    def exploitable_window_seconds(self) -> float:
        """Estimated exploitable window based on latency."""
        # Use p50 as conservative estimate
        return max(0, self.p50_latency - 2.0)  # Subtract 2s safety margin
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "oracle_id": self.oracle_id,
            "oracle_type": self.oracle_type.value,
            "event_type": self.event_type.value,
            "avg_latency_seconds": self.avg_latency_seconds,
            "min_latency_seconds": self.min_latency_seconds,
            "max_latency_seconds": self.max_latency_seconds,
            "std_dev_seconds": self.std_dev_seconds,
            "p50_latency": self.p50_latency,
            "p90_latency": self.p90_latency,
            "p99_latency": self.p99_latency,
            "sample_count": self.sample_count,
            "exploitable_window_seconds": self.exploitable_window_seconds(),
            "last_updated": self.last_updated,
        }


class OracleLatencyDetector:
    """
    Detects and profiles oracle latency for prediction markets.
    
    Monitors the delay between real-world events and their
    reflection in on-chain oracles. This latency creates
    windows where prediction market prices are stale.
    """
    
    def __init__(self):
        self.logger = get_logger("prediction.oracle_latency")
        
        # Latency measurements
        self._measurements: Dict[str, List[LatencyMeasurement]] = {}
        self._max_measurements: int = 1000
        
        # Latency profiles
        self._profiles: Dict[str, LatencyProfile] = {}
        
        # Known oracles
        self._oracles: Dict[str, Dict[str, Any]] = {
            "chainlink_btc_usd": {
                "type": OracleType.CHAINLINK,
                "event_type": EventType.PRICE,
                "address": "0x...",
                "heartbeat_seconds": 3600,
            },
            "pyth_btc_usd": {
                "type": OracleType.PYTH,
                "event_type": EventType.PRICE,
                "feed_id": "...",
                "heartbeat_seconds": 1,
            },
            "uma_election": {
                "type": OracleType.UMA,
                "event_type": EventType.ELECTION,
                "identifier": "...",
            },
        }
        
        # Real-time event feeds (for comparison)
        self._event_feeds: Dict[str, Any] = {}
        
        # Running state
        self._running: bool = False
        self._task: Optional[asyncio.Task] = None
    
    async def start(self) -> None:
        """Start latency monitoring."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        self.logger.info("Oracle latency detector started")
    
    async def stop(self) -> None:
        """Stop latency monitoring."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.logger.info("Oracle latency detector stopped")
    
    async def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        while self._running:
            try:
                # Check each oracle
                for oracle_id, config in self._oracles.items():
                    await self._check_oracle_latency(oracle_id, config)
                
                # Update profiles
                self._update_profiles()
                
                await asyncio.sleep(10)  # Check every 10 seconds
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Monitor error: {e}")
                await asyncio.sleep(30)
    
    async def _check_oracle_latency(self, oracle_id: str, config: Dict[str, Any]) -> None:
        """Check latency for a specific oracle."""
        # In production, this would:
        # 1. Get real-time event data (e.g., from exchange APIs)
        # 2. Get oracle on-chain data
        # 3. Compare timestamps
        
        # Simulated for now
        import random
        
        oracle_type = config.get("type", OracleType.CUSTOM)
        event_type = config.get("event_type", EventType.PRICE)
        
        # Use expected latency based on oracle type (no random variance)
        # Real latency measurements come from actual oracle observations
        expected_latency = {
            OracleType.CHAINLINK: 60.0,  # ~1 minute
            OracleType.PYTH: 1.0,        # ~1 second
            OracleType.UMA: 7200.0,      # ~2 hours (dispute period)
            OracleType.API3: 30.0,
            OracleType.CUSTOM: 300.0,
        }.get(oracle_type, 60.0)
        
        measurement = LatencyMeasurement(
            oracle_id=oracle_id,
            event_id=f"event_{int(time.time())}",
            real_world_time=time.time() - expected_latency,
            oracle_update_time=time.time(),
            latency_seconds=expected_latency,
            confidence=0.5,  # Lower confidence for estimated values
        )
        
        self._record_measurement(oracle_id, measurement)
    
    def _record_measurement(self, oracle_id: str, measurement: LatencyMeasurement) -> None:
        """Record a latency measurement."""
        if oracle_id not in self._measurements:
            self._measurements[oracle_id] = []
        
        self._measurements[oracle_id].append(measurement)
        
        # Trim old measurements
        if len(self._measurements[oracle_id]) > self._max_measurements:
            self._measurements[oracle_id] = self._measurements[oracle_id][-self._max_measurements:]
    
    def _update_profiles(self) -> None:
        """Update latency profiles from measurements."""
        for oracle_id, measurements in self._measurements.items():
            if not measurements:
                continue
            
            latencies = [m.latency_seconds for m in measurements]
            latencies.sort()
            
            config = self._oracles.get(oracle_id, {})
            
            profile = LatencyProfile(
                oracle_id=oracle_id,
                oracle_type=config.get("type", OracleType.CUSTOM),
                event_type=config.get("event_type", EventType.CUSTOM),
                avg_latency_seconds=sum(latencies) / len(latencies),
                min_latency_seconds=min(latencies),
                max_latency_seconds=max(latencies),
                std_dev_seconds=self._std_dev(latencies),
                p50_latency=self._percentile(latencies, 50),
                p90_latency=self._percentile(latencies, 90),
                p99_latency=self._percentile(latencies, 99),
                sample_count=len(latencies),
            )
            
            self._profiles[oracle_id] = profile
    
    def _std_dev(self, values: List[float]) -> float:
        """Calculate standard deviation."""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return variance ** 0.5
    
    def _percentile(self, sorted_values: List[float], p: int) -> float:
        """Get percentile from sorted values."""
        if not sorted_values:
            return 0.0
        idx = int(len(sorted_values) * p / 100)
        return sorted_values[min(idx, len(sorted_values) - 1)]
    
    def get_profile(self, oracle_id: str) -> Optional[LatencyProfile]:
        """Get latency profile for an oracle."""
        return self._profiles.get(oracle_id)
    
    def get_all_profiles(self) -> Dict[str, LatencyProfile]:
        """Get all latency profiles."""
        return self._profiles.copy()
    
    def get_exploitable_oracles(self, min_window_seconds: float = 5.0) -> List[LatencyProfile]:
        """Get oracles with exploitable latency windows."""
        return [
            p for p in self._profiles.values()
            if p.exploitable_window_seconds() >= min_window_seconds
        ]
    
    def register_oracle(
        self,
        oracle_id: str,
        oracle_type: OracleType,
        event_type: EventType,
        config: Dict[str, Any]
    ) -> None:
        """Register a new oracle to monitor."""
        self._oracles[oracle_id] = {
            "type": oracle_type,
            "event_type": event_type,
            **config,
        }
        self.logger.info(f"Registered oracle: {oracle_id}")
    
    def get_status(self) -> Dict[str, Any]:
        """Get detector status."""
        return {
            "running": self._running,
            "oracles_monitored": len(self._oracles),
            "total_measurements": sum(len(m) for m in self._measurements.values()),
            "profiles": {k: v.to_dict() for k, v in self._profiles.items()},
            "exploitable_count": len(self.get_exploitable_oracles()),
        }


# Singleton
_oracle_latency_detector: Optional[OracleLatencyDetector] = None


def get_oracle_latency_detector() -> OracleLatencyDetector:
    """Get or create the Oracle Latency Detector singleton."""
    global _oracle_latency_detector
    if _oracle_latency_detector is None:
        _oracle_latency_detector = OracleLatencyDetector()
    return _oracle_latency_detector

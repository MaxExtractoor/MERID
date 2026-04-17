"""
Throttle Manager.

Provides adaptive throttling based on system load and error rates.

Version: 1.0.0
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from enum import Enum
from collections import deque

from utils.logger import get_logger

logger = get_logger("ratelimit.throttle")


class ThrottleLevel(Enum):
    """Throttle levels."""
    NONE = 0
    LIGHT = 1
    MODERATE = 2
    HEAVY = 3
    CRITICAL = 4


@dataclass
class ThrottleConfig:
    """Configuration for throttling."""
    # Error rate thresholds (percentage)
    light_threshold: float = 5.0
    moderate_threshold: float = 10.0
    heavy_threshold: float = 20.0
    critical_threshold: float = 50.0
    
    # Latency thresholds (ms)
    latency_light: float = 500.0
    latency_moderate: float = 1000.0
    latency_heavy: float = 2000.0
    latency_critical: float = 5000.0
    
    # Throttle multipliers (how much to reduce rate)
    light_multiplier: float = 0.8
    moderate_multiplier: float = 0.5
    heavy_multiplier: float = 0.25
    critical_multiplier: float = 0.1
    
    # Recovery
    recovery_time_seconds: float = 60.0
    sample_window_seconds: float = 60.0


@dataclass
class ThrottleState:
    """Current throttle state."""
    level: ThrottleLevel = ThrottleLevel.NONE
    multiplier: float = 1.0
    reason: str = ""
    since: float = field(default_factory=time.time)
    
    # Metrics
    current_error_rate: float = 0.0
    current_latency_ms: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level.name,
            "level_value": self.level.value,
            "multiplier": self.multiplier,
            "reason": self.reason,
            "since": self.since,
            "duration_seconds": time.time() - self.since,
            "current_error_rate": self.current_error_rate,
            "current_latency_ms": self.current_latency_ms,
        }


class ThrottleManager:
    """
    Manages adaptive throttling based on system conditions.
    
    Features:
    - Error rate based throttling
    - Latency based throttling
    - Automatic recovery
    - Per-endpoint throttling
    """
    
    def __init__(self):
        self.logger = get_logger("ratelimit.throttle")
        
        # Configuration
        self._config = ThrottleConfig()
        
        # Global state
        self._global_state = ThrottleState()
        
        # Per-endpoint states
        self._endpoint_states: Dict[str, ThrottleState] = {}
        
        # Request tracking
        self._requests: deque = deque(maxlen=10000)
        self._errors: deque = deque(maxlen=10000)
        self._latencies: deque = deque(maxlen=10000)
        
        # Manual overrides
        self._manual_throttle: Optional[ThrottleLevel] = None
    
    def record_request(
        self,
        endpoint: str = "",
        success: bool = True,
        latency_ms: float = 0.0,
    ) -> None:
        """Record a request for throttle calculation."""
        now = time.time()
        
        self._requests.append({"timestamp": now, "endpoint": endpoint})
        
        if not success:
            self._errors.append({"timestamp": now, "endpoint": endpoint})
        
        if latency_ms > 0:
            self._latencies.append({
                "timestamp": now,
                "endpoint": endpoint,
                "latency_ms": latency_ms,
            })
        
        # Update throttle state periodically
        if len(self._requests) % 100 == 0:
            self._update_throttle_state()
    
    def _update_throttle_state(self) -> None:
        """Update throttle state based on recent metrics."""
        now = time.time()
        cutoff = now - self._config.sample_window_seconds
        
        # Calculate error rate
        recent_requests = [r for r in self._requests if r["timestamp"] >= cutoff]
        recent_errors = [e for e in self._errors if e["timestamp"] >= cutoff]
        
        if recent_requests:
            error_rate = len(recent_errors) / len(recent_requests) * 100
        else:
            error_rate = 0.0
        
        # Calculate average latency
        recent_latencies = [l for l in self._latencies if l["timestamp"] >= cutoff]
        if recent_latencies:
            avg_latency = sum(l["latency_ms"] for l in recent_latencies) / len(recent_latencies)
        else:
            avg_latency = 0.0
        
        # Determine throttle level
        new_level, new_multiplier, reason = self._determine_level(error_rate, avg_latency)
        
        # Check for manual override
        if self._manual_throttle is not None:
            new_level = self._manual_throttle
            new_multiplier = self._get_multiplier(new_level)
            reason = "manual_override"
        
        # Update state if changed
        if new_level != self._global_state.level:
            self.logger.warning(
                f"Throttle level changed: {self._global_state.level.name} -> {new_level.name} ({reason})"
            )
            self._global_state = ThrottleState(
                level=new_level,
                multiplier=new_multiplier,
                reason=reason,
            )
        
        self._global_state.current_error_rate = error_rate
        self._global_state.current_latency_ms = avg_latency
    
    def _determine_level(
        self,
        error_rate: float,
        latency_ms: float,
    ) -> tuple[ThrottleLevel, float, str]:
        """Determine throttle level based on metrics."""
        # Check error rate
        if error_rate >= self._config.critical_threshold:
            return ThrottleLevel.CRITICAL, self._config.critical_multiplier, f"error_rate:{error_rate:.1f}%"
        elif error_rate >= self._config.heavy_threshold:
            return ThrottleLevel.HEAVY, self._config.heavy_multiplier, f"error_rate:{error_rate:.1f}%"
        elif error_rate >= self._config.moderate_threshold:
            return ThrottleLevel.MODERATE, self._config.moderate_multiplier, f"error_rate:{error_rate:.1f}%"
        elif error_rate >= self._config.light_threshold:
            return ThrottleLevel.LIGHT, self._config.light_multiplier, f"error_rate:{error_rate:.1f}%"
        
        # Check latency
        if latency_ms >= self._config.latency_critical:
            return ThrottleLevel.CRITICAL, self._config.critical_multiplier, f"latency:{latency_ms:.0f}ms"
        elif latency_ms >= self._config.latency_heavy:
            return ThrottleLevel.HEAVY, self._config.heavy_multiplier, f"latency:{latency_ms:.0f}ms"
        elif latency_ms >= self._config.latency_moderate:
            return ThrottleLevel.MODERATE, self._config.moderate_multiplier, f"latency:{latency_ms:.0f}ms"
        elif latency_ms >= self._config.latency_light:
            return ThrottleLevel.LIGHT, self._config.light_multiplier, f"latency:{latency_ms:.0f}ms"
        
        return ThrottleLevel.NONE, 1.0, "normal"
    
    def _get_multiplier(self, level: ThrottleLevel) -> float:
        """Get multiplier for a throttle level."""
        if level == ThrottleLevel.NONE:
            return 1.0
        elif level == ThrottleLevel.LIGHT:
            return self._config.light_multiplier
        elif level == ThrottleLevel.MODERATE:
            return self._config.moderate_multiplier
        elif level == ThrottleLevel.HEAVY:
            return self._config.heavy_multiplier
        elif level == ThrottleLevel.CRITICAL:
            return self._config.critical_multiplier
        return 1.0
    
    def get_multiplier(self, endpoint: str = "") -> float:
        """Get current rate multiplier."""
        # Check endpoint-specific throttle
        if endpoint and endpoint in self._endpoint_states:
            return self._endpoint_states[endpoint].multiplier
        
        return self._global_state.multiplier
    
    def should_throttle(self, endpoint: str = "") -> bool:
        """Check if requests should be throttled."""
        return self.get_multiplier(endpoint) < 1.0
    
    def set_manual_throttle(self, level: Optional[ThrottleLevel]) -> None:
        """Set manual throttle override."""
        self._manual_throttle = level
        if level is not None:
            self.logger.warning(f"Manual throttle set: {level.name}")
        else:
            self.logger.info("Manual throttle cleared")
        self._update_throttle_state()
    
    def clear_manual_throttle(self) -> None:
        """Clear manual throttle override."""
        self.set_manual_throttle(None)
    
    def set_endpoint_throttle(self, endpoint: str, level: ThrottleLevel) -> None:
        """Set throttle for a specific endpoint."""
        self._endpoint_states[endpoint] = ThrottleState(
            level=level,
            multiplier=self._get_multiplier(level),
            reason="manual_endpoint",
        )
    
    def clear_endpoint_throttle(self, endpoint: str) -> bool:
        """Clear endpoint-specific throttle."""
        if endpoint in self._endpoint_states:
            del self._endpoint_states[endpoint]
            return True
        return False
    
    def get_state(self) -> Dict[str, Any]:
        """Get current throttle state."""
        return self._global_state.to_dict()
    
    def get_endpoint_states(self) -> Dict[str, Dict[str, Any]]:
        """Get endpoint-specific states."""
        return {k: v.to_dict() for k, v in self._endpoint_states.items()}
    
    def get_stats(self) -> Dict[str, Any]:
        """Get throttle statistics."""
        now = time.time()
        cutoff = now - self._config.sample_window_seconds
        
        recent_requests = len([r for r in self._requests if r["timestamp"] >= cutoff])
        recent_errors = len([e for e in self._errors if e["timestamp"] >= cutoff])
        
        return {
            "global_state": self._global_state.to_dict(),
            "endpoint_states": self.get_endpoint_states(),
            "recent_requests": recent_requests,
            "recent_errors": recent_errors,
            "manual_override": self._manual_throttle.name if self._manual_throttle else None,
            "config": {
                "sample_window_seconds": self._config.sample_window_seconds,
                "recovery_time_seconds": self._config.recovery_time_seconds,
            },
        }


# Singleton
_throttle_manager: Optional[ThrottleManager] = None


def get_throttle_manager() -> ThrottleManager:
    """Get or create the Throttle Manager singleton."""
    global _throttle_manager
    if _throttle_manager is None:
        _throttle_manager = ThrottleManager()
    return _throttle_manager

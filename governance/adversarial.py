"""
MERID-GOV Adversarial Intelligence Layer

Phase 2.2 of Master Build Directive

Implements:
- Behavioral randomization
- Honeytoken strategies
- Deception detection
- Adversary fingerprinting
- Adaptive red-team agents

This module answers: "Are we being exploited?"

Assume adversaries are intelligent, adaptive, and hostile.
"""

from __future__ import annotations

import threading
import time
import math
import random
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Callable, Set
import numpy as np
from collections import deque

from utils.logger import get_logger

logger = get_logger("governance.adversarial")


class AdversaryType(Enum):
    """Types of adversaries MERID may face."""
    MEV_BOT = "mev_bot"
    FRONT_RUNNER = "front_runner"
    SANDWICH_ATTACKER = "sandwich_attacker"
    ORACLE_MANIPULATOR = "oracle_manipulator"
    EXCHANGE_INSIDER = "exchange_insider"
    MARKET_MAKER = "market_maker"
    WHALE = "whale"
    GOVERNANCE_ATTACKER = "governance_attacker"
    DATA_POISONER = "data_poisoner"
    UNKNOWN = "unknown"


class ThreatLevel(Enum):
    """Threat level assessment."""
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DeceptionType(Enum):
    """Types of deception detected."""
    SPOOFING = "spoofing"              # Fake orders
    LAYERING = "layering"              # Multiple fake levels
    WASH_TRADING = "wash_trading"      # Self-trading
    PUMP_AND_DUMP = "pump_and_dump"    # Coordinated manipulation
    FAKE_NEWS = "fake_news"            # False information
    HONEYPOT = "honeypot"              # Trap contracts
    RUG_PULL = "rug_pull"              # Exit scam setup
    ORACLE_ATTACK = "oracle_attack"    # Price feed manipulation


@dataclass
class AdversaryFingerprint:
    """Fingerprint of a detected adversary."""
    fingerprint_id: str
    adversary_type: AdversaryType
    first_seen: float
    last_seen: float
    
    # Behavioral patterns
    typical_size_range: Tuple[float, float] = (0.0, 0.0)
    typical_timing_ms: float = 0.0
    preferred_venues: List[str] = field(default_factory=list)
    target_patterns: List[str] = field(default_factory=list)
    
    # Threat assessment
    threat_level: ThreatLevel = ThreatLevel.LOW
    estimated_capital: float = 0.0
    success_rate: float = 0.0
    
    # Tracking
    interactions: int = 0
    losses_caused: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "fingerprint_id": self.fingerprint_id,
            "adversary_type": self.adversary_type.value,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "typical_size_range": self.typical_size_range,
            "typical_timing_ms": round(self.typical_timing_ms, 2),
            "preferred_venues": self.preferred_venues,
            "threat_level": self.threat_level.value,
            "estimated_capital": round(self.estimated_capital, 2),
            "success_rate": round(self.success_rate, 4),
            "interactions": self.interactions,
            "losses_caused": round(self.losses_caused, 2),
        }


@dataclass
class Honeytoken:
    """A honeytoken for detecting adversary surveillance."""
    token_id: str
    token_type: str  # order, signal, position, etc.
    created_at: float
    expires_at: float
    
    # Honeytoken data
    fake_data: Dict[str, Any] = field(default_factory=dict)
    
    # Detection
    triggered: bool = False
    triggered_at: Optional[float] = None
    triggered_by: Optional[str] = None
    
    def is_expired(self) -> bool:
        return time.time() > self.expires_at
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "token_id": self.token_id,
            "token_type": self.token_type,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "triggered": self.triggered,
            "triggered_at": self.triggered_at,
            "triggered_by": self.triggered_by,
            "is_expired": self.is_expired(),
        }


@dataclass
class DeceptionEvent:
    """A detected deception event."""
    event_id: str
    deception_type: DeceptionType
    detected_at: float
    confidence: float
    
    # Details
    description: str
    evidence: Dict[str, Any] = field(default_factory=dict)
    
    # Attribution
    suspected_adversary: Optional[str] = None
    
    # Response
    response_taken: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "deception_type": self.deception_type.value,
            "detected_at": self.detected_at,
            "confidence": round(self.confidence, 4),
            "description": self.description,
            "evidence": self.evidence,
            "suspected_adversary": self.suspected_adversary,
            "response_taken": self.response_taken,
        }


class BehavioralRandomizer:
    """
    Adds controlled randomness to MERID's behavior to prevent
    adversaries from predicting and exploiting patterns.
    """
    
    def __init__(self, seed: Optional[int] = None):
        self._rng = random.Random(seed)
        self._np_rng = np.random.RandomState(seed)
        
        # Randomization parameters
        self._timing_jitter_pct: float = 0.2  # 20% timing variation
        self._size_jitter_pct: float = 0.1    # 10% size variation
        self._route_randomization: bool = True
        
        # History for pattern detection
        self._action_history: deque = deque(maxlen=1000)
        
        logger.info("Behavioral randomizer initialized")
    
    def randomize_timing(self, base_delay_ms: float) -> float:
        """Add random jitter to timing."""
        jitter = self._rng.uniform(
            -self._timing_jitter_pct,
            self._timing_jitter_pct
        )
        randomized = base_delay_ms * (1 + jitter)
        return max(0, randomized)
    
    def randomize_size(self, base_size: float) -> float:
        """Add random variation to order size."""
        jitter = self._rng.uniform(
            -self._size_jitter_pct,
            self._size_jitter_pct
        )
        randomized = base_size * (1 + jitter)
        return max(0, randomized)
    
    def randomize_route(self, available_routes: List[str]) -> str:
        """Randomly select execution route."""
        if not available_routes:
            return "default"
        
        if not self._route_randomization:
            return available_routes[0]
        
        # Weighted random selection (can be customized)
        return self._rng.choice(available_routes)
    
    def should_delay_action(self) -> Tuple[bool, float]:
        """
        Decide if action should be delayed and by how much.
        
        Returns (should_delay, delay_ms).
        """
        # Random delay with probability
        if self._rng.random() < 0.3:  # 30% chance of delay
            delay = self._rng.uniform(100, 2000)  # 100ms to 2s
            return True, delay
        return False, 0
    
    def generate_decoy_parameters(
        self,
        real_size: float,
        real_price: float,
    ) -> List[Dict[str, float]]:
        """Generate decoy order parameters to confuse adversaries."""
        decoys = []
        
        # Generate 2-4 decoy parameter sets
        n_decoys = self._rng.randint(2, 4)
        
        for _ in range(n_decoys):
            decoy_size = real_size * self._rng.uniform(0.5, 2.0)
            decoy_price = real_price * self._rng.uniform(0.98, 1.02)
            
            decoys.append({
                "size": decoy_size,
                "price": decoy_price,
                "is_decoy": True,
            })
        
        return decoys
    
    def record_action(self, action_type: str, parameters: Dict[str, Any]) -> None:
        """Record action for pattern analysis."""
        self._action_history.append({
            "type": action_type,
            "parameters": parameters,
            "timestamp": time.time(),
        })
    
    def detect_own_patterns(self) -> List[str]:
        """Detect patterns in MERID's own behavior that could be exploited."""
        patterns = []
        
        if len(self._action_history) < 50:
            return patterns
        
        actions = list(self._action_history)
        
        # Check timing patterns
        timestamps = [a["timestamp"] for a in actions]
        intervals = np.diff(timestamps)
        
        if len(intervals) > 10:
            interval_std = np.std(intervals)
            interval_mean = np.mean(intervals)
            
            # Low variance = predictable timing
            if interval_std < interval_mean * 0.1:
                patterns.append("PREDICTABLE_TIMING: Action intervals too regular")
        
        # Check size patterns
        sizes = [
            a["parameters"].get("size", 0)
            for a in actions
            if "size" in a.get("parameters", {})
        ]
        
        if len(sizes) > 10:
            unique_sizes = len(set(round(s, 2) for s in sizes))
            if unique_sizes < len(sizes) * 0.3:
                patterns.append("PREDICTABLE_SIZES: Too many repeated order sizes")
        
        return patterns
    
    def get_stats(self) -> Dict[str, Any]:
        """Get randomizer statistics."""
        patterns = self.detect_own_patterns()
        
        return {
            "timing_jitter_pct": self._timing_jitter_pct,
            "size_jitter_pct": self._size_jitter_pct,
            "route_randomization": self._route_randomization,
            "actions_recorded": len(self._action_history),
            "detected_patterns": patterns,
            "pattern_count": len(patterns),
        }


class HoneytokenManager:
    """
    Manages honeytokens for detecting adversary surveillance.
    
    Honeytokens are fake signals/orders that should never be acted upon.
    If an adversary reacts to them, we know they're watching.
    """
    
    def __init__(self):
        self._active_tokens: Dict[str, Honeytoken] = {}
        self._triggered_tokens: List[Honeytoken] = []
        self._token_count = 0
        
        # Token types and their configurations
        self._token_configs = {
            "fake_order": {"ttl_seconds": 300, "detection_window_ms": 5000},
            "fake_signal": {"ttl_seconds": 600, "detection_window_ms": 10000},
            "fake_position": {"ttl_seconds": 3600, "detection_window_ms": 60000},
            "fake_intent": {"ttl_seconds": 1800, "detection_window_ms": 30000},
        }
        
        logger.info("Honeytoken manager initialized")
    
    def create_token(
        self,
        token_type: str,
        fake_data: Dict[str, Any],
    ) -> Honeytoken:
        """Create a new honeytoken."""
        self._token_count += 1
        
        config = self._token_configs.get(token_type, {"ttl_seconds": 300})
        now = time.time()
        
        token = Honeytoken(
            token_id=f"honey_{token_type}_{self._token_count}_{int(now)}",
            token_type=token_type,
            created_at=now,
            expires_at=now + config["ttl_seconds"],
            fake_data=fake_data,
        )
        
        self._active_tokens[token.token_id] = token
        
        logger.debug("Created honeytoken: %s", token.token_id)
        return token
    
    def check_trigger(
        self,
        token_id: str,
        trigger_source: str,
    ) -> bool:
        """
        Check if a honeytoken was triggered.
        
        Returns True if this is a valid trigger (adversary detected).
        """
        token = self._active_tokens.get(token_id)
        if not token:
            return False
        
        if token.triggered or token.is_expired():
            return False
        
        # Mark as triggered
        token.triggered = True
        token.triggered_at = time.time()
        token.triggered_by = trigger_source
        
        self._triggered_tokens.append(token)
        del self._active_tokens[token_id]
        
        logger.warning(
            "HONEYTOKEN TRIGGERED: %s by %s - Adversary surveillance detected!",
            token_id, trigger_source
        )
        
        return True
    
    def cleanup_expired(self) -> int:
        """Remove expired tokens."""
        expired = [
            tid for tid, token in self._active_tokens.items()
            if token.is_expired()
        ]
        
        for tid in expired:
            del self._active_tokens[tid]
        
        return len(expired)
    
    def get_active_tokens(self) -> List[Honeytoken]:
        """Get all active honeytokens."""
        self.cleanup_expired()
        return list(self._active_tokens.values())
    
    def get_triggered_tokens(self, limit: int = 50) -> List[Honeytoken]:
        """Get recently triggered tokens."""
        return self._triggered_tokens[-limit:]
    
    def get_trigger_rate(self) -> float:
        """Get rate of honeytoken triggers."""
        total = self._token_count
        triggered = len(self._triggered_tokens)
        
        if total == 0:
            return 0.0
        return triggered / total
    
    def get_stats(self) -> Dict[str, Any]:
        """Get manager statistics."""
        return {
            "total_created": self._token_count,
            "active_count": len(self._active_tokens),
            "triggered_count": len(self._triggered_tokens),
            "trigger_rate": round(self.get_trigger_rate(), 4),
        }


class DeceptionDetector:
    """
    Detects deceptive market behavior and manipulation.
    """
    
    def __init__(self):
        # Detection thresholds
        self._spoofing_threshold = 0.7
        self._wash_trading_threshold = 0.8
        
        # Event tracking
        self._events: List[DeceptionEvent] = []
        self._event_count = 0
        
        # Pattern buffers
        self._order_flow: deque = deque(maxlen=10000)
        self._price_history: deque = deque(maxlen=10000)
        
        logger.info("Deception detector initialized")
    
    def analyze_order_flow(
        self,
        orders: List[Dict[str, Any]],
    ) -> List[DeceptionEvent]:
        """Analyze order flow for deceptive patterns."""
        events = []
        
        # Add to buffer
        for order in orders:
            self._order_flow.append(order)
        
        # Check for spoofing (large orders that get cancelled)
        spoofing_score = self._detect_spoofing(orders)
        if spoofing_score > self._spoofing_threshold:
            events.append(self._create_event(
                DeceptionType.SPOOFING,
                spoofing_score,
                "Large orders placed and cancelled rapidly",
                {"score": spoofing_score},
            ))
        
        # Check for layering
        layering_score = self._detect_layering(orders)
        if layering_score > 0.6:
            events.append(self._create_event(
                DeceptionType.LAYERING,
                layering_score,
                "Multiple price levels with suspicious order patterns",
                {"score": layering_score},
            ))
        
        return events
    
    def _detect_spoofing(self, orders: List[Dict[str, Any]]) -> float:
        """Detect spoofing patterns."""
        if len(orders) < 10:
            return 0.0
        
        # Look for large orders with short lifetimes
        large_cancelled = 0
        total_large = 0
        
        for order in orders:
            size = order.get("size", 0)
            lifetime_ms = order.get("lifetime_ms", float('inf'))
            status = order.get("status", "")
            
            # Consider "large" as > 2x average
            avg_size = np.mean([o.get("size", 0) for o in orders])
            
            if size > avg_size * 2:
                total_large += 1
                if status == "cancelled" and lifetime_ms < 1000:
                    large_cancelled += 1
        
        if total_large == 0:
            return 0.0
        
        return large_cancelled / total_large
    
    def _detect_layering(self, orders: List[Dict[str, Any]]) -> float:
        """Detect layering patterns."""
        if len(orders) < 20:
            return 0.0
        
        # Group orders by price level
        price_levels: Dict[float, List[Dict]] = {}
        for order in orders:
            price = round(order.get("price", 0), 2)
            if price not in price_levels:
                price_levels[price] = []
            price_levels[price].append(order)
        
        # Check for suspicious patterns across levels
        suspicious_levels = 0
        for price, level_orders in price_levels.items():
            if len(level_orders) >= 3:
                # Multiple orders at same level
                cancelled = sum(1 for o in level_orders if o.get("status") == "cancelled")
                if cancelled / len(level_orders) > 0.7:
                    suspicious_levels += 1
        
        if len(price_levels) == 0:
            return 0.0
        
        return suspicious_levels / len(price_levels)
    
    def analyze_price_action(
        self,
        prices: List[Dict[str, Any]],
    ) -> List[DeceptionEvent]:
        """Analyze price action for manipulation."""
        events = []
        
        for price_data in prices:
            self._price_history.append(price_data)
        
        # Check for pump and dump patterns
        if len(self._price_history) >= 100:
            pump_dump_score = self._detect_pump_dump()
            if pump_dump_score > 0.7:
                events.append(self._create_event(
                    DeceptionType.PUMP_AND_DUMP,
                    pump_dump_score,
                    "Rapid price increase followed by sharp decline",
                    {"score": pump_dump_score},
                ))
        
        return events
    
    def _detect_pump_dump(self) -> float:
        """Detect pump and dump patterns."""
        prices = [p.get("price", 0) for p in list(self._price_history)[-100:]]
        
        if len(prices) < 50:
            return 0.0
        
        # Look for sharp rise followed by sharp fall
        max_idx = np.argmax(prices)
        
        if max_idx < 10 or max_idx > len(prices) - 10:
            return 0.0
        
        pre_pump = np.mean(prices[:max_idx//2])
        peak = prices[max_idx]
        post_dump = np.mean(prices[max_idx + (len(prices) - max_idx)//2:])
        
        if pre_pump == 0:
            return 0.0
        
        pump_pct = (peak - pre_pump) / pre_pump
        dump_pct = (peak - post_dump) / peak if peak > 0 else 0
        
        # High pump followed by high dump = suspicious
        if pump_pct > 0.2 and dump_pct > 0.15:
            return min(1.0, (pump_pct + dump_pct) / 0.5)
        
        return 0.0
    
    def _create_event(
        self,
        deception_type: DeceptionType,
        confidence: float,
        description: str,
        evidence: Dict[str, Any],
    ) -> DeceptionEvent:
        """Create a deception event."""
        self._event_count += 1
        
        event = DeceptionEvent(
            event_id=f"deception_{self._event_count}_{int(time.time())}",
            deception_type=deception_type,
            detected_at=time.time(),
            confidence=confidence,
            description=description,
            evidence=evidence,
        )
        
        self._events.append(event)
        
        logger.warning(
            "DECEPTION DETECTED: [%s] %s (confidence=%.2f)",
            deception_type.value, description, confidence
        )
        
        return event
    
    def get_recent_events(self, limit: int = 50) -> List[DeceptionEvent]:
        """Get recent deception events."""
        return self._events[-limit:]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get detector statistics."""
        return {
            "total_events": len(self._events),
            "order_flow_buffer": len(self._order_flow),
            "price_history_buffer": len(self._price_history),
            "events_by_type": {
                dt.value: sum(1 for e in self._events if e.deception_type == dt)
                for dt in DeceptionType
            },
        }


class AdversaryTracker:
    """
    Tracks and fingerprints adversaries.
    """
    
    def __init__(self):
        self._fingerprints: Dict[str, AdversaryFingerprint] = {}
        self._fingerprint_count = 0
        
        # Interaction history
        self._interactions: deque = deque(maxlen=10000)
        
        logger.info("Adversary tracker initialized")
    
    def record_interaction(
        self,
        adversary_type: AdversaryType,
        characteristics: Dict[str, Any],
        loss_caused: float = 0.0,
    ) -> AdversaryFingerprint:
        """Record an interaction with a potential adversary."""
        # Generate fingerprint ID from characteristics
        char_str = str(sorted(characteristics.items()))
        fingerprint_id = hashlib.sha256(char_str.encode()).hexdigest()[:16]
        
        now = time.time()
        
        if fingerprint_id in self._fingerprints:
            # Update existing fingerprint
            fp = self._fingerprints[fingerprint_id]
            fp.last_seen = now
            fp.interactions += 1
            fp.losses_caused += loss_caused
            
            # Update success rate
            if "was_successful" in characteristics:
                old_rate = fp.success_rate
                new_success = 1.0 if characteristics["was_successful"] else 0.0
                fp.success_rate = 0.9 * old_rate + 0.1 * new_success
        else:
            # Create new fingerprint
            self._fingerprint_count += 1
            
            fp = AdversaryFingerprint(
                fingerprint_id=fingerprint_id,
                adversary_type=adversary_type,
                first_seen=now,
                last_seen=now,
                typical_size_range=characteristics.get("size_range", (0, 0)),
                typical_timing_ms=characteristics.get("timing_ms", 0),
                preferred_venues=characteristics.get("venues", []),
                interactions=1,
                losses_caused=loss_caused,
            )
            
            self._fingerprints[fingerprint_id] = fp
        
        # Update threat level
        self._update_threat_level(fp)
        
        # Record interaction
        self._interactions.append({
            "fingerprint_id": fingerprint_id,
            "timestamp": now,
            "characteristics": characteristics,
            "loss_caused": loss_caused,
        })
        
        return fp
    
    def _update_threat_level(self, fp: AdversaryFingerprint) -> None:
        """Update threat level based on fingerprint data."""
        # Factors: interactions, losses, success rate, recency
        
        threat_score = 0.0
        
        # More interactions = higher threat
        threat_score += min(1.0, fp.interactions / 100) * 0.2
        
        # Higher losses = higher threat
        threat_score += min(1.0, fp.losses_caused / 10000) * 0.3
        
        # Higher success rate = higher threat
        threat_score += fp.success_rate * 0.3
        
        # Recent activity = higher threat
        recency = time.time() - fp.last_seen
        if recency < 3600:  # Last hour
            threat_score += 0.2
        elif recency < 86400:  # Last day
            threat_score += 0.1
        
        # Classify
        if threat_score >= 0.8:
            fp.threat_level = ThreatLevel.CRITICAL
        elif threat_score >= 0.6:
            fp.threat_level = ThreatLevel.HIGH
        elif threat_score >= 0.4:
            fp.threat_level = ThreatLevel.MEDIUM
        elif threat_score >= 0.2:
            fp.threat_level = ThreatLevel.LOW
        else:
            fp.threat_level = ThreatLevel.NONE
    
    def get_fingerprint(self, fingerprint_id: str) -> Optional[AdversaryFingerprint]:
        """Get a specific fingerprint."""
        return self._fingerprints.get(fingerprint_id)
    
    def get_high_threat_adversaries(self) -> List[AdversaryFingerprint]:
        """Get adversaries with HIGH or CRITICAL threat level."""
        return [
            fp for fp in self._fingerprints.values()
            if fp.threat_level in (ThreatLevel.HIGH, ThreatLevel.CRITICAL)
        ]
    
    def get_all_fingerprints(self) -> List[AdversaryFingerprint]:
        """Get all fingerprints."""
        return list(self._fingerprints.values())
    
    def get_stats(self) -> Dict[str, Any]:
        """Get tracker statistics."""
        fps = list(self._fingerprints.values())
        
        return {
            "total_fingerprints": len(fps),
            "by_type": {
                at.value: sum(1 for fp in fps if fp.adversary_type == at)
                for at in AdversaryType
            },
            "by_threat_level": {
                tl.value: sum(1 for fp in fps if fp.threat_level == tl)
                for tl in ThreatLevel
            },
            "total_losses_caused": sum(fp.losses_caused for fp in fps),
            "total_interactions": len(self._interactions),
        }


class AdversarialIntelligenceEngine:
    """
    Main adversarial intelligence engine.
    
    Coordinates all adversarial defense mechanisms.
    """
    
    def __init__(self):
        self.randomizer = BehavioralRandomizer()
        self.honeytoken_manager = HoneytokenManager()
        self.deception_detector = DeceptionDetector()
        self.adversary_tracker = AdversaryTracker()
        
        # Threat state
        self._current_threat_level: ThreatLevel = ThreatLevel.NONE
        self._threat_history: deque = deque(maxlen=1000)
        
        # Callbacks
        self._threat_callbacks: List[Callable[[ThreatLevel], None]] = []
        
        logger.info("Adversarial intelligence engine initialized")
    
    def register_threat_callback(
        self,
        callback: Callable[[ThreatLevel], None]
    ) -> None:
        """Register callback for threat level changes."""
        self._threat_callbacks.append(callback)
    
    def assess_threat_level(self) -> ThreatLevel:
        """Assess current overall threat level."""
        factors = []
        
        # Honeytoken triggers
        trigger_rate = self.honeytoken_manager.get_trigger_rate()
        if trigger_rate > 0.1:
            factors.append(ThreatLevel.HIGH)
        elif trigger_rate > 0.05:
            factors.append(ThreatLevel.MEDIUM)
        
        # High-threat adversaries
        high_threat = self.adversary_tracker.get_high_threat_adversaries()
        if len(high_threat) >= 3:
            factors.append(ThreatLevel.CRITICAL)
        elif len(high_threat) >= 1:
            factors.append(ThreatLevel.HIGH)
        
        # Recent deception events
        recent_deception = [
            e for e in self.deception_detector.get_recent_events(100)
            if time.time() - e.detected_at < 3600
        ]
        if len(recent_deception) >= 5:
            factors.append(ThreatLevel.HIGH)
        elif len(recent_deception) >= 2:
            factors.append(ThreatLevel.MEDIUM)
        
        # Own pattern detection
        own_patterns = self.randomizer.detect_own_patterns()
        if len(own_patterns) >= 2:
            factors.append(ThreatLevel.MEDIUM)
        
        # Determine overall level
        if ThreatLevel.CRITICAL in factors:
            new_level = ThreatLevel.CRITICAL
        elif ThreatLevel.HIGH in factors:
            new_level = ThreatLevel.HIGH
        elif ThreatLevel.MEDIUM in factors:
            new_level = ThreatLevel.MEDIUM
        elif factors:
            new_level = ThreatLevel.LOW
        else:
            new_level = ThreatLevel.NONE
        
        # Check for level change
        if new_level != self._current_threat_level:
            logger.warning(
                "THREAT LEVEL CHANGE: %s -> %s",
                self._current_threat_level.value, new_level.value
            )
            for callback in self._threat_callbacks:
                try:
                    callback(new_level)
                except Exception as e:
                    logger.error("Threat callback failed: %s", e)
        
        self._current_threat_level = new_level
        self._threat_history.append({
            "level": new_level,
            "timestamp": time.time(),
            "factors": [f.value for f in factors],
        })
        
        return new_level
    
    def should_proceed_with_action(
        self,
        action_type: str,
        parameters: Dict[str, Any],
    ) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Check if an action should proceed given adversarial conditions.
        
        Returns (should_proceed, reason, modified_parameters).
        """
        threat_level = self.assess_threat_level()
        
        # Critical threat = halt most actions
        if threat_level == ThreatLevel.CRITICAL:
            if action_type not in ("exit", "hedge", "defensive"):
                return False, "CRITICAL threat level - only defensive actions allowed", {}
        
        # High threat = reduce exposure
        if threat_level == ThreatLevel.HIGH:
            if action_type in ("new_position", "increase_position"):
                return False, "HIGH threat level - no new exposure", {}
        
        # Apply randomization
        modified = parameters.copy()
        
        if "size" in modified:
            modified["size"] = self.randomizer.randomize_size(modified["size"])
        
        if "delay_ms" in modified:
            modified["delay_ms"] = self.randomizer.randomize_timing(modified["delay_ms"])
        
        # Check for additional delay
        should_delay, delay_ms = self.randomizer.should_delay_action()
        if should_delay:
            modified["additional_delay_ms"] = delay_ms
        
        # Record action
        self.randomizer.record_action(action_type, parameters)
        
        return True, "Action approved with modifications", modified
    
    def get_defensive_recommendations(self) -> List[str]:
        """Get defensive recommendations based on current threat state."""
        recommendations = []
        
        threat_level = self._current_threat_level
        
        if threat_level == ThreatLevel.CRITICAL:
            recommendations.extend([
                "HALT all new positions",
                "Reduce existing exposure by 50%",
                "Enable maximum behavioral randomization",
                "Deploy additional honeytokens",
                "Alert human operators",
            ])
        elif threat_level == ThreatLevel.HIGH:
            recommendations.extend([
                "Reduce position sizes by 30%",
                "Increase execution delays",
                "Avoid predictable timing",
                "Monitor for specific adversary patterns",
            ])
        elif threat_level == ThreatLevel.MEDIUM:
            recommendations.extend([
                "Increase behavioral randomization",
                "Deploy honeytokens in active markets",
                "Review recent deception events",
            ])
        
        # Check own patterns
        own_patterns = self.randomizer.detect_own_patterns()
        for pattern in own_patterns:
            recommendations.append(f"FIX PATTERN: {pattern}")
        
        return recommendations
    
    def get_status(self) -> Dict[str, Any]:
        """Get engine status."""
        return {
            "current_threat_level": self._current_threat_level.value,
            "recommendations": self.get_defensive_recommendations(),
            "randomizer": self.randomizer.get_stats(),
            "honeytokens": self.honeytoken_manager.get_stats(),
            "deception": self.deception_detector.get_stats(),
            "adversaries": self.adversary_tracker.get_stats(),
        }


# Singleton instance
_adversarial_engine: Optional[AdversarialIntelligenceEngine] = None
_adversarial_engine_lock = threading.Lock()


def get_adversarial_engine() -> AdversarialIntelligenceEngine:
    """Get the singleton adversarial intelligence engine."""
    global _adversarial_engine
    if _adversarial_engine is None:
        with _adversarial_engine_lock:
            if _adversarial_engine is None:
                _adversarial_engine = AdversarialIntelligenceEngine()
    return _adversarial_engine

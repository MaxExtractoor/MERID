"""
MERID-FIN MEV & Manipulation Defense

Phase 4.2 of Master Build Directive

Implements:
- Order slicing
- Randomized timing
- Hidden liquidity inference
- MEV intensity heatmaps
- Front-running detection
- Sandwich attack detection

This module answers: "How do we avoid being exploited?"

Assume adversaries are intelligent, adaptive, and hostile.
"""

from __future__ import annotations

import time
import math
import random
import hashlib
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Set
import numpy as np
from collections import deque

from utils.logger import get_logger

logger = get_logger("trading.execution.defense")


class MEVType(Enum):
    """Types of MEV attacks."""
    FRONT_RUNNING = "front_running"
    BACK_RUNNING = "back_running"
    SANDWICH = "sandwich"
    LIQUIDATION = "liquidation"
    ARBITRAGE = "arbitrage"
    JIT_LIQUIDITY = "jit_liquidity"


class ThreatLevel(Enum):
    """MEV threat level."""
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class DefenseAction(Enum):
    """Defensive actions."""
    PROCEED = "proceed"
    DELAY = "delay"
    SLICE = "slice"
    RANDOMIZE = "randomize"
    ABORT = "abort"
    USE_PRIVATE_MEMPOOL = "use_private_mempool"


@dataclass
class MEVEvent:
    """A detected MEV event."""
    event_id: str
    mev_type: MEVType
    detected_at: float
    
    # Details
    confidence: float
    estimated_loss: float
    attacker_address: Optional[str] = None
    
    # Transaction details
    victim_tx: Optional[str] = None
    attacker_tx: Optional[str] = None
    
    # Context
    symbol: str = ""
    block_number: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "mev_type": self.mev_type.value,
            "detected_at": self.detected_at,
            "confidence": round(self.confidence, 4),
            "estimated_loss": round(self.estimated_loss, 4),
            "attacker_address": self.attacker_address[:10] + "..." if self.attacker_address else None,
            "symbol": self.symbol,
        }


@dataclass
class MEVHeatmapEntry:
    """Entry in MEV intensity heatmap."""
    symbol: str
    venue: str
    time_bucket: int  # Hour of day
    
    # Intensity metrics
    mev_intensity: float  # 0-1 scale
    attack_count_24h: int
    avg_loss_per_attack: float
    
    # Risk factors
    liquidity_depth: float
    volatility: float
    
    last_updated: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "venue": self.venue,
            "time_bucket": self.time_bucket,
            "mev_intensity": round(self.mev_intensity, 4),
            "attack_count_24h": self.attack_count_24h,
            "avg_loss_per_attack": round(self.avg_loss_per_attack, 4),
        }


@dataclass
class DefenseRecommendation:
    """Recommendation from defense system."""
    action: DefenseAction
    reason: str
    
    # Modifications
    suggested_delay_ms: int = 0
    suggested_slice_count: int = 1
    suggested_size_reduction: float = 1.0
    
    # Risk assessment
    threat_level: ThreatLevel = ThreatLevel.NONE
    estimated_mev_risk: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action.value,
            "reason": self.reason,
            "suggested_delay_ms": self.suggested_delay_ms,
            "suggested_slice_count": self.suggested_slice_count,
            "suggested_size_reduction": round(self.suggested_size_reduction, 4),
            "threat_level": self.threat_level.value,
            "estimated_mev_risk": round(self.estimated_mev_risk, 6),
        }


class OrderSlicer:
    """
    Slices large orders to reduce market impact and MEV exposure.
    """
    
    def __init__(
        self,
        min_slice_size: float = 100.0,
        max_slices: int = 20,
    ):
        self.min_slice_size = min_slice_size
        self.max_slices = max_slices
        
        logger.info("Order slicer initialized")
    
    def compute_optimal_slices(
        self,
        total_size: float,
        daily_volume: float,
        volatility: float,
        mev_intensity: float,
    ) -> List[float]:
        """
        Compute optimal slice sizes.
        
        Factors:
        - Larger orders need more slices
        - Higher MEV intensity needs smaller slices
        - Higher volatility needs faster execution (fewer slices)
        """
        # Base number of slices from size
        participation_rate = total_size / daily_volume if daily_volume > 0 else 1.0
        base_slices = max(1, int(participation_rate * 100))
        
        # Adjust for MEV intensity (more slices if high MEV)
        mev_multiplier = 1 + mev_intensity * 2
        
        # Adjust for volatility (fewer slices if high vol)
        vol_multiplier = max(0.5, 1 - volatility * 2)
        
        n_slices = int(base_slices * mev_multiplier * vol_multiplier)
        n_slices = max(1, min(self.max_slices, n_slices))
        
        # Ensure minimum slice size
        if total_size / n_slices < self.min_slice_size:
            n_slices = max(1, int(total_size / self.min_slice_size))
        
        # Generate slice sizes with randomization
        slices = []
        remaining = total_size
        
        for i in range(n_slices):
            if i == n_slices - 1:
                slices.append(remaining)
            else:
                # Random variation around equal split
                base_size = remaining / (n_slices - i)
                variation = random.uniform(0.7, 1.3)
                slice_size = min(remaining, base_size * variation)
                slice_size = max(self.min_slice_size, slice_size)
                slices.append(slice_size)
                remaining -= slice_size
        
        return slices
    
    def compute_iceberg_schedule(
        self,
        total_size: float,
        visible_pct: float = 0.1,
    ) -> Tuple[float, float]:
        """
        Compute iceberg order parameters.
        
        Returns (visible_size, hidden_size).
        """
        visible = total_size * visible_pct
        hidden = total_size - visible
        
        return visible, hidden


class TimingRandomizer:
    """
    Randomizes execution timing to avoid detection.
    """
    
    def __init__(self):
        self._rng = random.Random()
        
        logger.info("Timing randomizer initialized")
    
    def randomize_delay(
        self,
        base_delay_ms: int,
        jitter_pct: float = 0.3,
    ) -> int:
        """Add random jitter to delay."""
        jitter = self._rng.uniform(-jitter_pct, jitter_pct)
        randomized = int(base_delay_ms * (1 + jitter))
        return max(0, randomized)
    
    def compute_random_schedule(
        self,
        n_orders: int,
        total_duration_ms: int,
    ) -> List[int]:
        """
        Compute randomized execution times.
        
        Returns list of delays in ms.
        """
        if n_orders <= 1:
            return [0]
        
        # Generate random points
        points = sorted([self._rng.random() for _ in range(n_orders - 1)])
        points = [0] + points + [1]
        
        # Convert to delays
        delays = []
        for i in range(n_orders):
            delay = int(points[i] * total_duration_ms)
            delays.append(delay)
        
        return delays
    
    def should_add_decoy_delay(self) -> Tuple[bool, int]:
        """
        Decide if a decoy delay should be added.
        
        Returns (should_delay, delay_ms).
        """
        if self._rng.random() < 0.2:  # 20% chance
            delay = self._rng.randint(500, 5000)
            return True, delay
        return False, 0


class HiddenLiquidityInference:
    """
    Infers hidden liquidity from market data.
    """
    
    def __init__(self):
        self._observations: Dict[str, deque] = {}
        
        logger.info("Hidden liquidity inference initialized")
    
    def record_observation(
        self,
        symbol: str,
        visible_depth: float,
        executed_volume: float,
        price_impact: float,
    ) -> None:
        """Record an observation for inference."""
        if symbol not in self._observations:
            self._observations[symbol] = deque(maxlen=1000)
        
        self._observations[symbol].append({
            "visible_depth": visible_depth,
            "executed_volume": executed_volume,
            "price_impact": price_impact,
            "timestamp": time.time(),
        })
    
    def estimate_hidden_liquidity(
        self,
        symbol: str,
        visible_depth: float,
    ) -> float:
        """
        Estimate hidden liquidity based on historical observations.
        
        Returns estimated total liquidity (visible + hidden).
        """
        obs = self._observations.get(symbol, [])
        if len(obs) < 10:
            # Default: assume 2x visible
            return visible_depth * 2
        
        # Analyze ratio of executed volume to visible depth
        ratios = []
        for o in obs:
            if o["visible_depth"] > 0:
                ratio = o["executed_volume"] / o["visible_depth"]
                ratios.append(ratio)
        
        if not ratios:
            return visible_depth * 2
        
        # Hidden liquidity ratio
        avg_ratio = np.mean(ratios)
        hidden_multiplier = max(1.0, avg_ratio)
        
        return visible_depth * hidden_multiplier
    
    def estimate_price_impact(
        self,
        symbol: str,
        order_size: float,
        visible_depth: float,
    ) -> float:
        """
        Estimate price impact considering hidden liquidity.
        
        Returns estimated impact in bps.
        """
        total_liquidity = self.estimate_hidden_liquidity(symbol, visible_depth)
        
        if total_liquidity <= 0:
            return 100.0  # Max impact
        
        # Linear impact model
        impact_pct = order_size / total_liquidity
        impact_bps = impact_pct * 10000
        
        return min(100.0, impact_bps)


class FrontRunningDetector:
    """
    Detects front-running attacks.
    """
    
    def __init__(self, detection_window_ms: int = 5000):
        self.detection_window_ms = detection_window_ms
        self._pending_orders: Dict[str, Dict] = {}
        self._detected_events: List[MEVEvent] = []
        self._event_count = 0
        
        logger.info("Front-running detector initialized")
    
    def register_pending_order(
        self,
        order_id: str,
        symbol: str,
        side: str,
        size: float,
        price: float,
    ) -> None:
        """Register a pending order for monitoring."""
        self._pending_orders[order_id] = {
            "symbol": symbol,
            "side": side,
            "size": size,
            "price": price,
            "submitted_at": time.time(),
        }
    
    def check_for_front_running(
        self,
        order_id: str,
        executed_price: float,
        market_trades: List[Dict[str, Any]],
    ) -> Optional[MEVEvent]:
        """
        Check if order was front-run.
        
        market_trades: Recent trades with {price, size, timestamp, tx_hash}
        """
        pending = self._pending_orders.get(order_id)
        if not pending:
            return None
        
        submitted_at = pending["submitted_at"]
        expected_price = pending["price"]
        
        # Look for suspicious trades before our execution
        suspicious_trades = []
        
        for trade in market_trades:
            trade_time = trade.get("timestamp", 0)
            
            # Trade happened after we submitted but before we executed
            if submitted_at < trade_time < time.time():
                # Same direction, moved price against us
                if pending["side"] == "buy" and trade.get("price", 0) > expected_price:
                    suspicious_trades.append(trade)
                elif pending["side"] == "sell" and trade.get("price", 0) < expected_price:
                    suspicious_trades.append(trade)
        
        if not suspicious_trades:
            return None
        
        # Calculate estimated loss
        price_diff = abs(executed_price - expected_price)
        estimated_loss = price_diff * pending["size"]
        
        # Confidence based on timing and pattern
        confidence = min(0.9, len(suspicious_trades) * 0.3)
        
        self._event_count += 1
        event = MEVEvent(
            event_id=f"fr_{self._event_count}_{int(time.time())}",
            mev_type=MEVType.FRONT_RUNNING,
            detected_at=time.time(),
            confidence=confidence,
            estimated_loss=estimated_loss,
            victim_tx=order_id,
            attacker_tx=suspicious_trades[0].get("tx_hash"),
            symbol=pending["symbol"],
        )
        
        self._detected_events.append(event)
        
        logger.warning(
            "FRONT-RUNNING DETECTED: %s - Loss: %.4f, Confidence: %.2f",
            order_id, estimated_loss, confidence
        )
        
        # Clean up
        del self._pending_orders[order_id]
        
        return event
    
    def get_recent_events(self, limit: int = 50) -> List[MEVEvent]:
        """Get recent front-running events."""
        return self._detected_events[-limit:]


class SandwichDetector:
    """
    Detects sandwich attacks.
    """
    
    def __init__(self):
        self._detected_events: List[MEVEvent] = []
        self._event_count = 0
        
        logger.info("Sandwich detector initialized")
    
    def detect_sandwich(
        self,
        our_trade: Dict[str, Any],
        surrounding_trades: List[Dict[str, Any]],
    ) -> Optional[MEVEvent]:
        """
        Detect if our trade was sandwiched.
        
        Sandwich pattern:
        1. Attacker buys before us (front-run)
        2. We buy at worse price
        3. Attacker sells after us (back-run)
        """
        our_time = our_trade.get("timestamp", time.time())
        our_side = our_trade.get("side", "buy")
        our_price = our_trade.get("price", 0)
        our_size = our_trade.get("size", 0)
        
        # Find potential front-run and back-run
        front_run = None
        back_run = None
        
        for trade in surrounding_trades:
            trade_time = trade.get("timestamp", 0)
            trade_side = trade.get("side", "")
            
            # Front-run: same direction, just before us
            if trade_time < our_time and trade_side == our_side:
                time_diff = our_time - trade_time
                if time_diff < 2.0:  # Within 2 seconds
                    front_run = trade
            
            # Back-run: opposite direction, just after us
            if trade_time > our_time and trade_side != our_side:
                time_diff = trade_time - our_time
                if time_diff < 2.0:
                    back_run = trade
        
        if not (front_run and back_run):
            return None
        
        # Check if same attacker (same address or similar size)
        front_addr = front_run.get("address", "")
        back_addr = back_run.get("address", "")
        
        if front_addr and back_addr and front_addr == back_addr:
            confidence = 0.9
        else:
            # Check size similarity
            front_size = front_run.get("size", 0)
            back_size = back_run.get("size", 0)
            size_ratio = min(front_size, back_size) / max(front_size, back_size) if max(front_size, back_size) > 0 else 0
            
            if size_ratio > 0.8:
                confidence = 0.7
            else:
                confidence = 0.4
        
        # Estimate loss
        if our_side == "buy":
            price_impact = our_price - front_run.get("price", our_price)
        else:
            price_impact = front_run.get("price", our_price) - our_price
        
        estimated_loss = max(0, price_impact * our_size)
        
        self._event_count += 1
        event = MEVEvent(
            event_id=f"sw_{self._event_count}_{int(time.time())}",
            mev_type=MEVType.SANDWICH,
            detected_at=time.time(),
            confidence=confidence,
            estimated_loss=estimated_loss,
            attacker_address=front_addr or back_addr,
            victim_tx=our_trade.get("tx_hash"),
            symbol=our_trade.get("symbol", ""),
        )
        
        self._detected_events.append(event)
        
        logger.warning(
            "SANDWICH ATTACK DETECTED: Loss: %.4f, Confidence: %.2f",
            estimated_loss, confidence
        )
        
        return event
    
    def get_recent_events(self, limit: int = 50) -> List[MEVEvent]:
        """Get recent sandwich events."""
        return self._detected_events[-limit:]


class MEVHeatmap:
    """
    Tracks MEV intensity across symbols, venues, and time.
    """
    
    def __init__(self):
        self._entries: Dict[Tuple[str, str, int], MEVHeatmapEntry] = {}
        self._attack_history: deque = deque(maxlen=10000)
        
        logger.info("MEV heatmap initialized")
    
    def record_attack(
        self,
        symbol: str,
        venue: str,
        mev_type: MEVType,
        loss: float,
    ) -> None:
        """Record an MEV attack."""
        now = time.time()
        hour = int((now % 86400) / 3600)
        
        self._attack_history.append({
            "symbol": symbol,
            "venue": venue,
            "hour": hour,
            "mev_type": mev_type.value,
            "loss": loss,
            "timestamp": now,
        })
        
        # Update heatmap entry
        self._update_entry(symbol, venue, hour)
    
    def _update_entry(self, symbol: str, venue: str, hour: int) -> None:
        """Update heatmap entry."""
        key = (symbol, venue, hour)
        
        # Get attacks in last 24h for this key
        cutoff = time.time() - 86400
        attacks = [
            a for a in self._attack_history
            if a["symbol"] == symbol
            and a["venue"] == venue
            and a["hour"] == hour
            and a["timestamp"] > cutoff
        ]
        
        attack_count = len(attacks)
        avg_loss = np.mean([a["loss"] for a in attacks]) if attacks else 0.0
        
        # Calculate intensity (0-1)
        intensity = min(1.0, attack_count / 10)  # 10+ attacks = max intensity
        
        self._entries[key] = MEVHeatmapEntry(
            symbol=symbol,
            venue=venue,
            time_bucket=hour,
            mev_intensity=intensity,
            attack_count_24h=attack_count,
            avg_loss_per_attack=avg_loss,
            liquidity_depth=0.0,  # To be updated externally
            volatility=0.0,
        )
    
    def get_intensity(
        self,
        symbol: str,
        venue: str,
        hour: Optional[int] = None,
    ) -> float:
        """Get MEV intensity for symbol/venue/time."""
        if hour is None:
            hour = int((time.time() % 86400) / 3600)
        
        key = (symbol, venue, hour)
        entry = self._entries.get(key)
        
        if entry:
            return entry.mev_intensity
        
        # Check if any attacks for this symbol/venue
        for k, e in self._entries.items():
            if k[0] == symbol and k[1] == venue:
                return e.mev_intensity * 0.5  # Reduced intensity for different hour
        
        return 0.0
    
    def get_safest_time(self, symbol: str, venue: str) -> int:
        """Get hour with lowest MEV intensity."""
        intensities = {}
        
        for hour in range(24):
            key = (symbol, venue, hour)
            entry = self._entries.get(key)
            intensities[hour] = entry.mev_intensity if entry else 0.0
        
        return min(intensities, key=intensities.get)
    
    def get_heatmap(self, symbol: str) -> Dict[str, Any]:
        """Get heatmap data for a symbol."""
        entries = [
            e.to_dict()
            for k, e in self._entries.items()
            if k[0] == symbol
        ]
        
        return {
            "symbol": symbol,
            "entries": entries,
            "safest_hour": self.get_safest_time(symbol, "default"),
        }


class MEVDefenseEngine:
    """
    Main MEV defense engine.
    
    Coordinates all defense mechanisms.
    """
    
    def __init__(self):
        self.slicer = OrderSlicer()
        self.timing = TimingRandomizer()
        self.liquidity = HiddenLiquidityInference()
        self.front_running_detector = FrontRunningDetector()
        self.sandwich_detector = SandwichDetector()
        self.heatmap = MEVHeatmap()
        
        # Defense statistics
        self._defense_actions: deque = deque(maxlen=1000)
        self._total_mev_avoided: float = 0.0
        self._total_mev_suffered: float = 0.0
        
        logger.info("MEV defense engine initialized")
    
    def assess_mev_risk(
        self,
        symbol: str,
        venue: str,
        order_size: float,
        daily_volume: float,
    ) -> Tuple[ThreatLevel, float]:
        """
        Assess MEV risk for an order.
        
        Returns (threat_level, estimated_risk_usd).
        """
        # Get MEV intensity from heatmap
        intensity = self.heatmap.get_intensity(symbol, venue)
        
        # Participation rate risk
        participation = order_size / daily_volume if daily_volume > 0 else 1.0
        
        # Combined risk score
        risk_score = intensity * 0.5 + min(1.0, participation * 10) * 0.5
        
        # Estimate risk in USD (simplified)
        estimated_risk = order_size * risk_score * 0.001  # 0.1% at max risk
        
        # Determine threat level
        if risk_score >= 0.8:
            level = ThreatLevel.CRITICAL
        elif risk_score >= 0.6:
            level = ThreatLevel.HIGH
        elif risk_score >= 0.4:
            level = ThreatLevel.MEDIUM
        elif risk_score >= 0.2:
            level = ThreatLevel.LOW
        else:
            level = ThreatLevel.NONE
        
        return level, estimated_risk
    
    def get_defense_recommendation(
        self,
        symbol: str,
        venue: str,
        side: str,
        order_size: float,
        daily_volume: float,
        volatility: float,
    ) -> DefenseRecommendation:
        """
        Get defense recommendation for an order.
        """
        threat_level, estimated_risk = self.assess_mev_risk(
            symbol, venue, order_size, daily_volume
        )
        
        mev_intensity = self.heatmap.get_intensity(symbol, venue)
        
        # Determine action
        if threat_level == ThreatLevel.CRITICAL:
            action = DefenseAction.ABORT
            reason = "MEV risk too high - consider private mempool or delay"
            delay = 0
            slices = 1
            size_reduction = 0.0
        
        elif threat_level == ThreatLevel.HIGH:
            action = DefenseAction.SLICE
            reason = "High MEV risk - slicing and randomizing"
            delay = self.timing.randomize_delay(2000, 0.5)
            slices = max(5, int(order_size / daily_volume * 50))
            size_reduction = 0.7
        
        elif threat_level == ThreatLevel.MEDIUM:
            action = DefenseAction.RANDOMIZE
            reason = "Medium MEV risk - adding randomization"
            delay = self.timing.randomize_delay(1000, 0.3)
            slices = max(3, int(order_size / daily_volume * 30))
            size_reduction = 0.9
        
        elif threat_level == ThreatLevel.LOW:
            action = DefenseAction.DELAY
            reason = "Low MEV risk - minor delay recommended"
            delay = self.timing.randomize_delay(500, 0.2)
            slices = max(2, int(order_size / daily_volume * 20))
            size_reduction = 1.0
        
        else:
            action = DefenseAction.PROCEED
            reason = "Minimal MEV risk"
            delay = 0
            slices = 1
            size_reduction = 1.0
        
        recommendation = DefenseRecommendation(
            action=action,
            reason=reason,
            suggested_delay_ms=delay,
            suggested_slice_count=min(20, slices),
            suggested_size_reduction=size_reduction,
            threat_level=threat_level,
            estimated_mev_risk=estimated_risk,
        )
        
        # Record action
        self._defense_actions.append({
            "symbol": symbol,
            "action": action.value,
            "threat_level": threat_level.value,
            "timestamp": time.time(),
        })
        
        return recommendation
    
    def apply_defense(
        self,
        order_size: float,
        recommendation: DefenseRecommendation,
        daily_volume: float,
        volatility: float,
    ) -> Dict[str, Any]:
        """
        Apply defense measures to an order.
        
        Returns execution parameters.
        """
        mev_intensity = recommendation.estimated_mev_risk / order_size if order_size > 0 else 0
        
        # Compute slices
        slices = self.slicer.compute_optimal_slices(
            order_size * recommendation.suggested_size_reduction,
            daily_volume,
            volatility,
            mev_intensity,
        )
        
        # Compute timing
        total_duration = len(slices) * 1000 + recommendation.suggested_delay_ms
        timing_schedule = self.timing.compute_random_schedule(
            len(slices), total_duration
        )
        
        # Add decoy delays
        final_schedule = []
        for i, (slice_size, delay) in enumerate(zip(slices, timing_schedule)):
            should_decoy, decoy_delay = self.timing.should_add_decoy_delay()
            if should_decoy:
                delay += decoy_delay
            final_schedule.append({
                "slice_index": i,
                "size": slice_size,
                "delay_ms": delay,
            })
        
        return {
            "original_size": order_size,
            "adjusted_size": order_size * recommendation.suggested_size_reduction,
            "slices": final_schedule,
            "total_duration_ms": total_duration,
            "defense_action": recommendation.action.value,
        }
    
    def record_mev_event(self, event: MEVEvent) -> None:
        """Record an MEV event."""
        self._total_mev_suffered += event.estimated_loss
        
        # Update heatmap
        self.heatmap.record_attack(
            event.symbol,
            "default",
            event.mev_type,
            event.estimated_loss,
        )
    
    def record_mev_avoided(self, estimated_savings: float) -> None:
        """Record MEV that was avoided."""
        self._total_mev_avoided += estimated_savings
    
    def get_status(self) -> Dict[str, Any]:
        """Get defense engine status."""
        recent_actions = list(self._defense_actions)[-100:]
        
        action_counts = {}
        for a in recent_actions:
            action = a["action"]
            action_counts[action] = action_counts.get(action, 0) + 1
        
        return {
            "total_mev_suffered": round(self._total_mev_suffered, 4),
            "total_mev_avoided": round(self._total_mev_avoided, 4),
            "net_mev_impact": round(self._total_mev_suffered - self._total_mev_avoided, 4),
            "recent_action_counts": action_counts,
            "front_running_events": len(self.front_running_detector.get_recent_events()),
            "sandwich_events": len(self.sandwich_detector.get_recent_events()),
        }
    
    def get_mev_summary(self, symbol: str) -> Dict[str, Any]:
        """Get MEV summary for a symbol."""
        return {
            "heatmap": self.heatmap.get_heatmap(symbol),
            "safest_hour": self.heatmap.get_safest_time(symbol, "default"),
            "current_intensity": self.heatmap.get_intensity(symbol, "default"),
        }


class ManipulationDetector:
    """
    Detects market manipulation patterns.
    """
    
    def __init__(self):
        self._price_history: Dict[str, deque] = {}
        self._volume_history: Dict[str, deque] = {}
        self._alerts: List[Dict[str, Any]] = []
        
        logger.info("Manipulation detector initialized")
    
    def record_tick(
        self,
        symbol: str,
        price: float,
        volume: float,
    ) -> None:
        """Record a price/volume tick."""
        if symbol not in self._price_history:
            self._price_history[symbol] = deque(maxlen=1000)
            self._volume_history[symbol] = deque(maxlen=1000)
        
        self._price_history[symbol].append({
            "price": price,
            "timestamp": time.time(),
        })
        self._volume_history[symbol].append({
            "volume": volume,
            "timestamp": time.time(),
        })
    
    def detect_pump_and_dump(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Detect pump and dump patterns."""
        prices = self._price_history.get(symbol, [])
        if len(prices) < 50:
            return None
        
        price_values = [p["price"] for p in list(prices)[-50:]]
        
        # Look for sharp rise followed by sharp fall
        max_idx = np.argmax(price_values)
        
        if max_idx < 10 or max_idx > len(price_values) - 10:
            return None
        
        pre_pump = np.mean(price_values[:max_idx//2])
        peak = price_values[max_idx]
        post_dump = np.mean(price_values[max_idx + (len(price_values) - max_idx)//2:])
        
        if pre_pump == 0:
            return None
        
        pump_pct = (peak - pre_pump) / pre_pump
        dump_pct = (peak - post_dump) / peak if peak > 0 else 0
        
        if pump_pct > 0.15 and dump_pct > 0.10:
            alert = {
                "type": "pump_and_dump",
                "symbol": symbol,
                "pump_pct": round(pump_pct * 100, 2),
                "dump_pct": round(dump_pct * 100, 2),
                "detected_at": time.time(),
            }
            self._alerts.append(alert)
            
            logger.warning(
                "PUMP AND DUMP DETECTED: %s - Pump: %.1f%%, Dump: %.1f%%",
                symbol, pump_pct * 100, dump_pct * 100
            )
            
            return alert
        
        return None
    
    def detect_wash_trading(
        self,
        symbol: str,
        trades: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Detect wash trading patterns."""
        if len(trades) < 20:
            return None
        
        # Group by address
        address_volumes: Dict[str, float] = {}
        for trade in trades:
            addr = trade.get("address", "unknown")
            address_volumes[addr] = address_volumes.get(addr, 0) + trade.get("size", 0)
        
        total_volume = sum(address_volumes.values())
        if total_volume == 0:
            return None
        
        # Check for concentrated volume
        max_addr_volume = max(address_volumes.values())
        concentration = max_addr_volume / total_volume
        
        if concentration > 0.5:  # Single address > 50% of volume
            alert = {
                "type": "wash_trading",
                "symbol": symbol,
                "concentration": round(concentration * 100, 2),
                "detected_at": time.time(),
            }
            self._alerts.append(alert)
            
            logger.warning(
                "WASH TRADING SUSPECTED: %s - Concentration: %.1f%%",
                symbol, concentration * 100
            )
            
            return alert
        
        return None
    
    def get_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent alerts."""
        return self._alerts[-limit:]


# Singleton instance
_mev_defense: Optional[MEVDefenseEngine] = None


def get_mev_defense() -> MEVDefenseEngine:
    """Get the singleton MEV defense engine."""
    global _mev_defense
    if _mev_defense is None:
        _mev_defense = MEVDefenseEngine()
    return _mev_defense

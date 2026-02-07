"""
MERID-TREASURY Capital Thermodynamics

Phase 3.2 of Master Build Directive

Implements:
- Capital temperature (activity/risk level)
- Turnover heat (trading intensity)
- Correlation stress
- Cooling mechanisms

This module answers: "Is our capital overheating?"

Capital that moves too fast burns. Capital that sits too long freezes.
Optimal capital temperature is the balance between opportunity and survival.
"""

from __future__ import annotations

import time
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple
import numpy as np
from collections import deque

from utils.logger import get_logger

logger = get_logger("treasury.capital_thermodynamics")


class TemperatureState(Enum):
    """Capital temperature states."""
    FROZEN = "frozen"           # < 0.1 - No activity, may miss opportunities
    COLD = "cold"               # 0.1 - 0.3 - Low activity, conservative
    OPTIMAL = "optimal"         # 0.3 - 0.6 - Balanced activity
    WARM = "warm"               # 0.6 - 0.8 - Elevated activity
    HOT = "hot"                 # 0.8 - 0.95 - High risk, needs cooling
    OVERHEATING = "overheating" # > 0.95 - Critical, immediate cooling required


class CoolingMechanism(Enum):
    """Types of cooling mechanisms."""
    POSITION_REDUCTION = "position_reduction"
    TRADING_PAUSE = "trading_pause"
    LEVERAGE_REDUCTION = "leverage_reduction"
    CORRELATION_HEDGE = "correlation_hedge"
    TIME_DECAY = "time_decay"
    FORCED_LIQUIDATION = "forced_liquidation"


@dataclass
class HeatSource:
    """A source of capital heat."""
    source_id: str
    source_type: str  # trade, position, correlation, leverage
    heat_contribution: float
    timestamp: float
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_type": self.source_type,
            "heat_contribution": round(self.heat_contribution, 4),
            "timestamp": self.timestamp,
            "details": self.details,
        }


@dataclass
class CoolingAction:
    """A cooling action taken."""
    action_id: str
    mechanism: CoolingMechanism
    heat_removed: float
    timestamp: float
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "mechanism": self.mechanism.value,
            "heat_removed": round(self.heat_removed, 4),
            "timestamp": self.timestamp,
            "details": self.details,
        }


@dataclass
class ThermodynamicState:
    """Complete thermodynamic state of capital."""
    timestamp: float
    
    # Temperature metrics
    capital_temperature: float  # 0.0 to 1.0+
    temperature_state: TemperatureState
    
    # Heat components
    turnover_heat: float
    correlation_heat: float
    leverage_heat: float
    concentration_heat: float
    volatility_heat: float
    
    # Cooling capacity
    available_cooling: float
    cooling_rate: float
    
    # Stress indicators
    is_stressed: bool
    stress_level: float
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "capital_temperature": round(self.capital_temperature, 4),
            "temperature_state": self.temperature_state.value,
            "turnover_heat": round(self.turnover_heat, 4),
            "correlation_heat": round(self.correlation_heat, 4),
            "leverage_heat": round(self.leverage_heat, 4),
            "concentration_heat": round(self.concentration_heat, 4),
            "volatility_heat": round(self.volatility_heat, 4),
            "available_cooling": round(self.available_cooling, 4),
            "cooling_rate": round(self.cooling_rate, 6),
            "is_stressed": self.is_stressed,
            "stress_level": round(self.stress_level, 4),
        }


class TurnoverHeatCalculator:
    """
    Calculates heat from trading turnover.
    
    High turnover = high heat
    Rapid position changes = friction heat
    """
    
    def __init__(self, lookback_hours: float = 24.0):
        self.lookback_hours = lookback_hours
        self._trades: deque = deque(maxlen=10000)
        
        logger.info("Turnover heat calculator initialized")
    
    def record_trade(
        self,
        trade_id: str,
        volume: float,
        is_round_trip: bool = False,
    ) -> float:
        """Record a trade and return heat contribution."""
        now = time.time()
        
        # Base heat from volume
        heat = volume / 10000  # Normalize
        
        # Round trips generate more heat (friction)
        if is_round_trip:
            heat *= 1.5
        
        self._trades.append({
            "trade_id": trade_id,
            "volume": volume,
            "heat": heat,
            "timestamp": now,
        })
        
        return heat
    
    def calculate_turnover_heat(self) -> float:
        """Calculate current turnover heat."""
        now = time.time()
        cutoff = now - (self.lookback_hours * 3600)
        
        # Filter recent trades
        recent = [t for t in self._trades if t["timestamp"] > cutoff]
        
        if not recent:
            return 0.0
        
        # Sum heat with time decay
        total_heat = 0.0
        for trade in recent:
            age_hours = (now - trade["timestamp"]) / 3600
            decay = math.exp(-age_hours / self.lookback_hours)
            total_heat += trade["heat"] * decay
        
        # Normalize to 0-1 range
        normalized = min(1.0, total_heat / 10)
        
        return normalized
    
    def get_turnover_rate(self) -> float:
        """Get trades per hour."""
        now = time.time()
        cutoff = now - 3600  # Last hour
        
        recent = [t for t in self._trades if t["timestamp"] > cutoff]
        return len(recent)


class CorrelationHeatCalculator:
    """
    Calculates heat from correlation stress.
    
    High correlation = positions move together = concentrated risk
    Correlation spikes = heat spikes
    """
    
    def __init__(self):
        self._correlation_history: deque = deque(maxlen=1000)
        self._baseline_correlation: float = 0.3
        
        logger.info("Correlation heat calculator initialized")
    
    def update_correlation(
        self,
        avg_correlation: float,
        max_correlation: float,
    ) -> float:
        """Update correlation and return heat contribution."""
        now = time.time()
        
        # Heat from deviation above baseline
        excess_correlation = max(0, avg_correlation - self._baseline_correlation)
        
        # Extra heat from extreme correlations
        extreme_heat = max(0, max_correlation - 0.8) * 2
        
        heat = excess_correlation + extreme_heat
        
        self._correlation_history.append({
            "avg": avg_correlation,
            "max": max_correlation,
            "heat": heat,
            "timestamp": now,
        })
        
        return min(1.0, heat)
    
    def calculate_correlation_heat(self) -> float:
        """Calculate current correlation heat."""
        if not self._correlation_history:
            return 0.0
        
        # Use recent correlations
        recent = list(self._correlation_history)[-20:]
        
        avg_heat = np.mean([c["heat"] for c in recent])
        
        # Check for correlation spike
        if len(recent) >= 5:
            recent_avg = np.mean([c["avg"] for c in recent[-5:]])
            older_avg = np.mean([c["avg"] for c in recent[:-5]])
            
            if recent_avg > older_avg + 0.2:
                # Correlation spike - add extra heat
                avg_heat += 0.2
        
        return min(1.0, avg_heat)
    
    def update_baseline(self, new_baseline: float) -> None:
        """Update baseline correlation."""
        self._baseline_correlation = new_baseline


class LeverageHeatCalculator:
    """
    Calculates heat from leverage.
    
    Higher leverage = higher heat
    Leverage amplifies all other heat sources.
    """
    
    # Leverage thresholds
    SAFE_LEVERAGE = 1.0
    WARNING_LEVERAGE = 2.0
    DANGER_LEVERAGE = 3.0
    CRITICAL_LEVERAGE = 5.0
    
    def __init__(self):
        self._current_leverage: float = 1.0
        self._leverage_history: deque = deque(maxlen=1000)
        
        logger.info("Leverage heat calculator initialized")
    
    def update_leverage(self, leverage: float) -> float:
        """Update leverage and return heat contribution."""
        self._current_leverage = leverage
        
        # Heat calculation
        if leverage <= self.SAFE_LEVERAGE:
            heat = 0.0
        elif leverage <= self.WARNING_LEVERAGE:
            heat = (leverage - self.SAFE_LEVERAGE) / (self.WARNING_LEVERAGE - self.SAFE_LEVERAGE) * 0.3
        elif leverage <= self.DANGER_LEVERAGE:
            heat = 0.3 + (leverage - self.WARNING_LEVERAGE) / (self.DANGER_LEVERAGE - self.WARNING_LEVERAGE) * 0.4
        elif leverage <= self.CRITICAL_LEVERAGE:
            heat = 0.7 + (leverage - self.DANGER_LEVERAGE) / (self.CRITICAL_LEVERAGE - self.DANGER_LEVERAGE) * 0.25
        else:
            heat = 0.95 + min(0.05, (leverage - self.CRITICAL_LEVERAGE) * 0.01)
        
        self._leverage_history.append({
            "leverage": leverage,
            "heat": heat,
            "timestamp": time.time(),
        })
        
        return heat
    
    def calculate_leverage_heat(self) -> float:
        """Calculate current leverage heat."""
        return self.update_leverage(self._current_leverage)
    
    def get_leverage_multiplier(self) -> float:
        """Get multiplier for other heat sources based on leverage."""
        if self._current_leverage <= 1.0:
            return 1.0
        return 1.0 + (self._current_leverage - 1.0) * 0.5


class CoolingSystem:
    """
    Manages cooling mechanisms to reduce capital heat.
    """
    
    # Cooling effectiveness by mechanism
    COOLING_EFFECTIVENESS = {
        CoolingMechanism.POSITION_REDUCTION: 0.3,
        CoolingMechanism.TRADING_PAUSE: 0.2,
        CoolingMechanism.LEVERAGE_REDUCTION: 0.4,
        CoolingMechanism.CORRELATION_HEDGE: 0.25,
        CoolingMechanism.TIME_DECAY: 0.1,
        CoolingMechanism.FORCED_LIQUIDATION: 0.8,
    }
    
    def __init__(self):
        self._cooling_actions: List[CoolingAction] = []
        self._action_count = 0
        self._passive_cooling_rate: float = 0.01  # Per hour
        
        logger.info("Cooling system initialized")
    
    def apply_cooling(
        self,
        mechanism: CoolingMechanism,
        intensity: float = 1.0,
        details: Optional[Dict[str, Any]] = None,
    ) -> CoolingAction:
        """Apply a cooling mechanism."""
        self._action_count += 1
        
        effectiveness = self.COOLING_EFFECTIVENESS[mechanism]
        heat_removed = effectiveness * intensity
        
        action = CoolingAction(
            action_id=f"cool_{self._action_count}_{int(time.time())}",
            mechanism=mechanism,
            heat_removed=heat_removed,
            timestamp=time.time(),
            details=details or {},
        )
        
        self._cooling_actions.append(action)
        
        logger.info(
            "Cooling applied: %s - Heat removed: %.3f",
            mechanism.value, heat_removed
        )
        
        return action
    
    def calculate_passive_cooling(self, hours_elapsed: float) -> float:
        """Calculate passive cooling from time decay."""
        return self._passive_cooling_rate * hours_elapsed
    
    def get_recommended_cooling(
        self,
        current_temperature: float,
        target_temperature: float = 0.5,
    ) -> List[Tuple[CoolingMechanism, float]]:
        """Get recommended cooling actions."""
        recommendations = []
        
        heat_to_remove = current_temperature - target_temperature
        
        if heat_to_remove <= 0:
            return recommendations
        
        # Prioritize by effectiveness
        sorted_mechanisms = sorted(
            self.COOLING_EFFECTIVENESS.items(),
            key=lambda x: x[1],
            reverse=True
        )
        
        remaining_heat = heat_to_remove
        
        for mechanism, effectiveness in sorted_mechanisms:
            if remaining_heat <= 0:
                break
            
            # Calculate required intensity
            intensity = min(1.0, remaining_heat / effectiveness)
            
            if intensity >= 0.1:  # Only recommend if meaningful
                recommendations.append((mechanism, intensity))
                remaining_heat -= effectiveness * intensity
        
        return recommendations
    
    def get_recent_actions(self, limit: int = 20) -> List[CoolingAction]:
        """Get recent cooling actions."""
        return self._cooling_actions[-limit:]


class CapitalThermodynamicsEngine:
    """
    Main capital thermodynamics engine.
    
    Monitors and manages capital temperature to ensure survival.
    """
    
    # Temperature thresholds
    TEMPERATURE_THRESHOLDS = {
        TemperatureState.FROZEN: 0.1,
        TemperatureState.COLD: 0.3,
        TemperatureState.OPTIMAL: 0.6,
        TemperatureState.WARM: 0.8,
        TemperatureState.HOT: 0.95,
        TemperatureState.OVERHEATING: float('inf'),
    }
    
    # Heat component weights
    HEAT_WEIGHTS = {
        "turnover": 0.25,
        "correlation": 0.25,
        "leverage": 0.30,
        "concentration": 0.10,
        "volatility": 0.10,
    }
    
    def __init__(self):
        self.turnover_calc = TurnoverHeatCalculator()
        self.correlation_calc = CorrelationHeatCalculator()
        self.leverage_calc = LeverageHeatCalculator()
        self.cooling_system = CoolingSystem()
        
        # State tracking
        self._current_state: Optional[ThermodynamicState] = None
        self._state_history: List[ThermodynamicState] = []
        
        # Additional heat sources
        self._concentration_heat: float = 0.0
        self._volatility_heat: float = 0.0
        
        # Stress tracking
        self._stress_events: deque = deque(maxlen=100)
        
        logger.info("Capital thermodynamics engine initialized")
    
    def record_trade(
        self,
        trade_id: str,
        volume: float,
        is_round_trip: bool = False,
    ) -> None:
        """Record a trade."""
        self.turnover_calc.record_trade(trade_id, volume, is_round_trip)
    
    def update_correlation(
        self,
        avg_correlation: float,
        max_correlation: float,
    ) -> None:
        """Update correlation metrics."""
        self.correlation_calc.update_correlation(avg_correlation, max_correlation)
    
    def update_leverage(self, leverage: float) -> None:
        """Update leverage."""
        self.leverage_calc.update_leverage(leverage)
    
    def update_concentration(self, concentration_ratio: float) -> None:
        """Update concentration heat."""
        # Heat increases with concentration
        self._concentration_heat = min(1.0, concentration_ratio * 1.5)
    
    def update_volatility(self, portfolio_volatility: float) -> None:
        """Update volatility heat."""
        # Normalize volatility (assume 20% annual is baseline)
        normalized = portfolio_volatility / 0.20
        self._volatility_heat = min(1.0, max(0, normalized - 1.0))
    
    def compute_temperature(self) -> ThermodynamicState:
        """Compute current capital temperature."""
        now = time.time()
        
        # Get component heats
        turnover_heat = self.turnover_calc.calculate_turnover_heat()
        correlation_heat = self.correlation_calc.calculate_correlation_heat()
        leverage_heat = self.leverage_calc.calculate_leverage_heat()
        concentration_heat = self._concentration_heat
        volatility_heat = self._volatility_heat
        
        # Weighted sum
        base_temperature = (
            turnover_heat * self.HEAT_WEIGHTS["turnover"] +
            correlation_heat * self.HEAT_WEIGHTS["correlation"] +
            leverage_heat * self.HEAT_WEIGHTS["leverage"] +
            concentration_heat * self.HEAT_WEIGHTS["concentration"] +
            volatility_heat * self.HEAT_WEIGHTS["volatility"]
        )
        
        # Apply leverage multiplier
        leverage_multiplier = self.leverage_calc.get_leverage_multiplier()
        temperature = base_temperature * leverage_multiplier
        
        # Determine state
        state = self._classify_temperature(temperature)
        
        # Calculate stress
        is_stressed = state in (TemperatureState.HOT, TemperatureState.OVERHEATING)
        stress_level = max(0, (temperature - 0.6) / 0.4) if temperature > 0.6 else 0.0
        
        # Calculate cooling capacity
        available_cooling = self._calculate_available_cooling()
        cooling_rate = self.cooling_system._passive_cooling_rate
        
        thermo_state = ThermodynamicState(
            timestamp=now,
            capital_temperature=temperature,
            temperature_state=state,
            turnover_heat=turnover_heat,
            correlation_heat=correlation_heat,
            leverage_heat=leverage_heat,
            concentration_heat=concentration_heat,
            volatility_heat=volatility_heat,
            available_cooling=available_cooling,
            cooling_rate=cooling_rate,
            is_stressed=is_stressed,
            stress_level=stress_level,
        )
        
        # Track state change
        if self._current_state and self._current_state.temperature_state != state:
            logger.warning(
                "TEMPERATURE STATE CHANGE: %s -> %s (temp=%.3f)",
                self._current_state.temperature_state.value,
                state.value,
                temperature
            )
            
            if is_stressed:
                self._stress_events.append({
                    "timestamp": now,
                    "temperature": temperature,
                    "state": state.value,
                })
        
        self._current_state = thermo_state
        self._state_history.append(thermo_state)
        
        return thermo_state
    
    def _classify_temperature(self, temperature: float) -> TemperatureState:
        """Classify temperature into state."""
        if temperature < self.TEMPERATURE_THRESHOLDS[TemperatureState.FROZEN]:
            return TemperatureState.FROZEN
        elif temperature < self.TEMPERATURE_THRESHOLDS[TemperatureState.COLD]:
            return TemperatureState.COLD
        elif temperature < self.TEMPERATURE_THRESHOLDS[TemperatureState.OPTIMAL]:
            return TemperatureState.OPTIMAL
        elif temperature < self.TEMPERATURE_THRESHOLDS[TemperatureState.WARM]:
            return TemperatureState.WARM
        elif temperature < self.TEMPERATURE_THRESHOLDS[TemperatureState.HOT]:
            return TemperatureState.HOT
        else:
            return TemperatureState.OVERHEATING
    
    def _calculate_available_cooling(self) -> float:
        """Calculate available cooling capacity."""
        # Based on current state
        if self._current_state is None:
            return 1.0
        
        # Less cooling available if already stressed
        if self._current_state.is_stressed:
            return 0.5
        
        return 1.0
    
    def should_cool(self) -> Tuple[bool, List[Tuple[CoolingMechanism, float]]]:
        """
        Check if cooling is needed.
        
        Returns (should_cool, recommended_actions).
        """
        if self._current_state is None:
            return False, []
        
        temp = self._current_state.capital_temperature
        state = self._current_state.temperature_state
        
        if state in (TemperatureState.HOT, TemperatureState.OVERHEATING):
            recommendations = self.cooling_system.get_recommended_cooling(
                temp, target_temperature=0.5
            )
            return True, recommendations
        
        if state == TemperatureState.WARM:
            # Mild cooling recommended
            recommendations = self.cooling_system.get_recommended_cooling(
                temp, target_temperature=0.5
            )
            return True, recommendations[:2]  # Only top 2 recommendations
        
        return False, []
    
    def apply_cooling(
        self,
        mechanism: CoolingMechanism,
        intensity: float = 1.0,
    ) -> CoolingAction:
        """Apply cooling mechanism."""
        action = self.cooling_system.apply_cooling(mechanism, intensity)
        
        # Reduce temperature
        if self._current_state:
            # Cooling effect is applied on next compute_temperature call
            pass
        
        return action
    
    def get_trading_permission(self) -> Tuple[bool, str, float]:
        """
        Check if trading is permitted based on temperature.
        
        Returns (permitted, reason, size_multiplier).
        """
        if self._current_state is None:
            return True, "No temperature data", 1.0
        
        state = self._current_state.temperature_state
        temp = self._current_state.capital_temperature
        
        if state == TemperatureState.OVERHEATING:
            return False, "OVERHEATING - Trading halted", 0.0
        
        if state == TemperatureState.HOT:
            return True, "HOT - Reduced trading only", 0.25
        
        if state == TemperatureState.WARM:
            return True, "WARM - Moderate trading", 0.5
        
        if state == TemperatureState.FROZEN:
            return True, "FROZEN - Consider increasing activity", 1.0
        
        if state == TemperatureState.COLD:
            return True, "COLD - Normal trading", 1.0
        
        return True, "OPTIMAL - Full trading permitted", 1.0
    
    def get_heat_breakdown(self) -> Dict[str, float]:
        """Get breakdown of heat sources."""
        if self._current_state is None:
            return {}
        
        state = self._current_state
        total = state.capital_temperature
        
        if total == 0:
            return {}
        
        return {
            "turnover": round(state.turnover_heat * self.HEAT_WEIGHTS["turnover"] / total, 4),
            "correlation": round(state.correlation_heat * self.HEAT_WEIGHTS["correlation"] / total, 4),
            "leverage": round(state.leverage_heat * self.HEAT_WEIGHTS["leverage"] / total, 4),
            "concentration": round(state.concentration_heat * self.HEAT_WEIGHTS["concentration"] / total, 4),
            "volatility": round(state.volatility_heat * self.HEAT_WEIGHTS["volatility"] / total, 4),
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get engine status."""
        state = self._current_state
        should_cool, recommendations = self.should_cool()
        permitted, reason, multiplier = self.get_trading_permission()
        
        return {
            "current_state": state.to_dict() if state else None,
            "heat_breakdown": self.get_heat_breakdown(),
            "should_cool": should_cool,
            "cooling_recommendations": [
                {"mechanism": m.value, "intensity": round(i, 2)}
                for m, i in recommendations
            ],
            "trading_permitted": permitted,
            "trading_reason": reason,
            "size_multiplier": multiplier,
            "stress_events_24h": len([
                e for e in self._stress_events
                if time.time() - e["timestamp"] < 86400
            ]),
        }
    
    def get_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get temperature history."""
        return [s.to_dict() for s in self._state_history[-limit:]]


# Singleton instance
_thermo_engine: Optional[CapitalThermodynamicsEngine] = None


def get_capital_thermodynamics() -> CapitalThermodynamicsEngine:
    """Get the singleton capital thermodynamics engine."""
    global _thermo_engine
    if _thermo_engine is None:
        _thermo_engine = CapitalThermodynamicsEngine()
    return _thermo_engine

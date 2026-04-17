"""
Simulation Handler for MERID Pipeline

Provides simulation execution for LLM proposals routed through
the SimulationPipeline. Integrates with the event-driven simulator
for realistic market microstructure simulation.
"""
from __future__ import annotations

import threading
import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("simulation.sim_handler")


@dataclass
class SimulatedFill:
    """Simulated order fill."""
    fill_id: str
    order_id: str
    price: float
    size: float
    slippage: float
    latency_ms: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class SimulationState:
    """State for a simulation run."""
    sim_id: str
    start_time: float
    positions: Dict[str, float] = field(default_factory=dict)
    cash: float = 10000.0
    pnl: float = 0.0
    fills: List[SimulatedFill] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)


class SimulationExecutor:
    """
    Executes simulated trades for the pipeline.
    
    Features:
    - Realistic slippage modeling
    - Latency simulation
    - Market impact estimation
    - Position tracking
    - PnL calculation
    """
    
    def __init__(self):
        self._states: Dict[str, SimulationState] = {}
        self._sim_counter = 0
        
        # Market parameters
        self._base_prices = {
            "BTC": 43250.0,
            "ETH": 2280.0,
            "SOL": 98.0,
            "AVAX": 35.0,
        }
        
        # Simulation parameters
        self._base_slippage = 0.001  # 0.1%
        self._base_latency_ms = 50.0
        self._impact_factor = 0.0001  # Per $1000
        
        logger.info("SimulationExecutor initialized")
    
    def _get_or_create_state(self, agent_id: str) -> SimulationState:
        """Get or create simulation state for agent."""
        if agent_id not in self._states:
            self._sim_counter += 1
            self._states[agent_id] = SimulationState(
                sim_id=f"sim_{self._sim_counter:06d}",
                start_time=time.time(),
            )
        return self._states[agent_id]
    
    def _get_simulated_price(self, asset: str, side: str, size: float) -> tuple:
        """Get simulated fill price with slippage and impact."""
        base_price = self._base_prices.get(asset, 100.0)
        
        # Add random noise
        noise = random.gauss(0, 0.001) * base_price
        
        # Calculate slippage
        slippage_pct = self._base_slippage * (1 + random.random())
        
        # Calculate market impact
        impact_pct = self._impact_factor * (size / 1000.0)
        
        # Apply direction
        if side in ["long", "buy", "yes"]:
            fill_price = base_price * (1 + slippage_pct + impact_pct) + noise
        else:
            fill_price = base_price * (1 - slippage_pct - impact_pct) + noise
        
        total_slippage = abs(fill_price - base_price) / base_price
        
        return fill_price, total_slippage
    
    def execute_order(
        self,
        action_type: str,
        parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute simulated order."""
        agent_id = parameters.get("agent_id", "default")
        state = self._get_or_create_state(agent_id)
        
        asset = parameters.get("asset", "BTC")
        side = parameters.get("side", "long")
        size = parameters.get("size", 100.0)
        
        # Simulate latency
        latency = self._base_latency_ms * (1 + random.random() * 0.5)
        
        # Get fill price
        fill_price, slippage = self._get_simulated_price(asset, side, size)
        
        # Create fill
        fill = SimulatedFill(
            fill_id=f"fill_{len(state.fills):06d}",
            order_id=f"order_{int(time.time() * 1000)}",
            price=fill_price,
            size=size,
            slippage=slippage,
            latency_ms=latency,
        )
        state.fills.append(fill)
        
        # Update position
        position_key = f"{asset}_{side}"
        current_pos = state.positions.get(position_key, 0.0)
        state.positions[position_key] = current_pos + size
        
        # Deduct from cash
        state.cash -= size
        
        # Calculate mock PnL (random for simulation)
        mock_pnl = random.gauss(0, size * 0.02)  # 2% std dev
        state.pnl += mock_pnl
        
        # Record event
        state.events.append({
            "type": "order_fill",
            "fill_id": fill.fill_id,
            "asset": asset,
            "side": side,
            "size": size,
            "price": fill_price,
            "slippage": slippage,
            "latency_ms": latency,
            "timestamp": time.time(),
        })
        
        logger.debug(
            "Simulated fill: %s %s %.2f @ %.2f (slippage: %.4f%%)",
            asset, side, size, fill_price, slippage * 100,
        )
        
        return {
            "simulated": True,
            "fill_id": fill.fill_id,
            "fill_price": fill_price,
            "slippage": slippage,
            "latency_ms": latency,
            "mock_pnl": mock_pnl,
            "position_size": state.positions.get(position_key, 0.0),
            "cash_remaining": state.cash,
        }
    
    def close_position(
        self,
        parameters: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Close simulated position."""
        agent_id = parameters.get("agent_id", "default")
        state = self._get_or_create_state(agent_id)
        
        position_key = parameters.get("position_key", "")
        
        if position_key not in state.positions:
            return {
                "simulated": True,
                "closed": False,
                "error": "Position not found",
            }
        
        size = state.positions[position_key]
        
        # Parse asset and side from key
        parts = position_key.split("_")
        asset = parts[0] if parts else "BTC"
        side = parts[1] if len(parts) > 1 else "long"
        
        # Get exit price (opposite side)
        exit_side = "short" if side == "long" else "long"
        exit_price, slippage = self._get_simulated_price(asset, exit_side, size)
        
        # Calculate PnL
        entry_fills = [f for f in state.fills if f.order_id.startswith(asset)]
        avg_entry = sum(f.price * f.size for f in entry_fills) / max(sum(f.size for f in entry_fills), 1)
        
        if side == "long":
            pnl = (exit_price - avg_entry) / avg_entry * size
        else:
            pnl = (avg_entry - exit_price) / avg_entry * size
        
        # Update state
        del state.positions[position_key]
        state.cash += size + pnl
        state.pnl += pnl
        
        # Record event
        state.events.append({
            "type": "position_close",
            "position_key": position_key,
            "exit_price": exit_price,
            "pnl": pnl,
            "timestamp": time.time(),
        })
        
        return {
            "simulated": True,
            "closed": True,
            "exit_price": exit_price,
            "mock_pnl": pnl,
            "total_pnl": state.pnl,
        }
    
    def get_state(self, agent_id: str) -> Dict[str, Any]:
        """Get simulation state for agent."""
        state = self._states.get(agent_id)
        if not state:
            return {"exists": False}
        
        return {
            "exists": True,
            "sim_id": state.sim_id,
            "positions": state.positions,
            "cash": state.cash,
            "pnl": state.pnl,
            "fill_count": len(state.fills),
            "event_count": len(state.events),
        }
    
    def reset_state(self, agent_id: str) -> None:
        """Reset simulation state for agent."""
        if agent_id in self._states:
            del self._states[agent_id]
            logger.info("Reset simulation state for %s", agent_id)


# Global executor
_sim_executor: Optional[SimulationExecutor] = None
_sim_executor_lock = threading.Lock()


def get_sim_executor() -> SimulationExecutor:
    """Get simulation executor singleton."""
    global _sim_executor
    if _sim_executor is None:
        with _sim_executor_lock:
            if _sim_executor is None:
                _sim_executor = SimulationExecutor()
    return _sim_executor


def simulation_handler(action_type: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handler for simulation pipeline.
    
    Routes LLM proposals to appropriate simulation logic.
    """
    executor = get_sim_executor()
    
    if action_type == "propose_order":
        return executor.execute_order(action_type, parameters)
    
    elif action_type == "close_position":
        return executor.close_position(parameters)
    
    elif action_type == "get_state":
        agent_id = parameters.get("agent_id", "default")
        return executor.get_state(agent_id)
    
    elif action_type == "reset":
        agent_id = parameters.get("agent_id", "default")
        executor.reset_state(agent_id)
        return {"simulated": True, "reset": True}
    
    else:
        # Generic simulation response
        return {
            "simulated": True,
            "action_type": action_type,
            "mock_pnl": random.gauss(0, 10),
        }


def register_with_pipeline() -> None:
    """Register simulation handler with pipeline."""
    try:
        from core.simulation_pipeline import get_simulation_pipeline
        pipeline = get_simulation_pipeline()
        pipeline.register_sim_handler(simulation_handler)
        logger.info("Simulation handler registered with pipeline")
    except ImportError:
        logger.warning("Could not register with simulation pipeline")

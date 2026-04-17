"""
Simulation Assertion Source

Provides simulation domain assertions to reduce blind spots in the reality system.
"""

import threading
import time
import uuid
from typing import Dict, List, Optional
from dataclasses import dataclass

from core.reality_registry import (
    get_reality_registry,
    AssertionDomain,
    AssertionProvenance,
    RealityAssertion,
    AssertionStatus
)
from utils.logger import get_logger

logger = get_logger("simulation.assertion_source")


@dataclass
class SimulationAssertion:
    """Simulation data assertion for reality system."""
    scenario_name: str
    status: str
    parity_score: float
    latency_ms: float
    timestamp: float
    source: str
    confidence: float = 0.85


class SimulationAssertionSource:
    """
    Simulation data assertion source for reality system.
    
    Periodically registers simulation state assertions to reduce blind spots
    in the simulation domain.
    """
    
    def __init__(self):
        self.registry = get_reality_registry()
        self.last_assertion_time = 0.0
        self.assertion_interval = 180.0  # 3 minutes
        self.simulation_state_cache: Dict[str, SimulationAssertion] = {}
    
    def update_simulation_state(self, scenario_name: str, status: str, parity_score: float, 
                              latency_ms: float, source: str = "sim_engine"):
        """Update simulation state and register assertion if needed."""
        current_time = time.time()
        
        # Cache the simulation state
        self.simulation_state_cache[scenario_name] = SimulationAssertion(
            scenario_name=scenario_name,
            status=status,
            parity_score=parity_score,
            latency_ms=latency_ms,
            timestamp=current_time,
            source=source,
            confidence=0.85
        )
        
        # Register assertion if interval has passed
        if current_time - self.last_assertion_time >= self.assertion_interval:
            self._register_simulation_assertion(scenario_name)
            self.last_assertion_time = current_time
    
    def _register_simulation_assertion(self, scenario_name: str):
        """Register a simulation state assertion."""
        try:
            sim_data = self.simulation_state_cache.get(scenario_name)
            if not sim_data:
                logger.warning(f"No simulation data available for {scenario_name}")
                return
            
            # Create assertion
            assertion_id = self.registry.register_assertion(
                domain=AssertionDomain.SIMULATION,
                description=f"Simulation {scenario_name}: {sim_data.status}, parity {sim_data.parity_score:.2f}, latency {sim_data.latency_ms}ms",
                confidence=sim_data.confidence,
                provenance_score=0.75,
                regime_compatibility=1.0,
                decay_rate=0.04,  # Simulation data decays moderately
                validity_window=900.0,  # 15 minutes
                sources=[
                    AssertionProvenance(
                        source_id="simulation_feed",
                        module_id="simulation_assertion_source",
                        evidence_hash=f"sim_{scenario_name}_{sim_data.timestamp}",
                        weight=1.0,
                        timestamp=sim_data.timestamp
                    )
                ]
            )
            
            logger.info(f"Registered simulation assertion: {scenario_name} - {assertion_id}")
            
        except Exception as e:
            logger.error(f"Error registering simulation assertion for {scenario_name}: {e}")
    
    def register_batch_simulation_data(self, simulation_data_list: List[Dict]):
        """Register multiple simulation data assertions at once."""
        for sim_data in simulation_data_list:
            scenario_name = sim_data.get("scenario_name")
            status = sim_data.get("status")
            parity_score = sim_data.get("parity_score")
            latency_ms = sim_data.get("latency_ms")
            source = sim_data.get("source", "batch")
            
            if scenario_name and status and parity_score is not None and latency_ms is not None:
                # Cache the simulation data
                current_time = time.time()
                self.simulation_state_cache[scenario_name] = SimulationAssertion(
                    scenario_name=scenario_name,
                    status=status,
                    parity_score=parity_score,
                    latency_ms=latency_ms,
                    timestamp=current_time,
                    source=source,
                    confidence=0.85
                )
                
                # Register assertion immediately for demo data (bypass interval check)
                if source == "demo":
                    self._register_simulation_assertion(scenario_name)
                else:
                    self.update_simulation_state(scenario_name, status, parity_score, latency_ms, source)
    
    def get_simulation_assertions(self) -> List[Dict]:
        """Get all simulation assertions from the registry."""
        try:
            assertions = self.registry.get_assertions_by_domain(AssertionDomain.SIMULATION)
            return [
                {
                    "assertion_id": a.assertion_id,
                    "scenario_name": a.description.split(":")[0].replace("Simulation ", ""),
                    "description": a.description,
                    "confidence_score": a.confidence_score,
                    "provenance_score": a.provenance_score,
                    "status": a.status.value,
                    "created_at": a.created_at,
                    "effective_confidence": a.effective_confidence(time.time(), self.registry.regime_entropy),
                    "is_usable": a.is_usable(time.time(), self.registry.regime_entropy)
                }
                for a in assertions
            ]
        except Exception as e:
            logger.error(f"Error getting simulation assertions: {e}")
            return []


# Singleton instance
_simulation_source: Optional[SimulationAssertionSource] = None
_simulation_source_lock = threading.Lock()


def get_simulation_assertion_source() -> SimulationAssertionSource:
    """Get the global simulation assertion source."""
    global _simulation_source
    if _simulation_source is None:
        with _simulation_source_lock:
            if _simulation_source is None:
                _simulation_source = SimulationAssertionSource()
    return _simulation_source


# Example usage
if __name__ == "__main__":
    # Create simulation assertion source
    source = get_simulation_assertion_source()
    
    # Update some simulation data
    source.update_simulation_state("core_scenario", "PASSED", 0.98, 45.2, "sim_engine")
    source.update_simulation_state("risk_scenario", "PASSED", 0.95, 52.1, "sim_engine")
    source.update_simulation_state("market_scenario", "PASSED", 0.92, 38.7, "bootstrap")
    
    # Get simulation assertions
    assertions = source.get_simulation_assertions()
    print(f"Simulation assertions: {len(assertions)}")
    for assertion in assertions[:3]:  # Show first 3
        print(f"  - {assertion['scenario_name']}: {assertion['status']} (confidence: {assertion['confidence_score']:.2f})")
    
    print("Simulation assertion source is ready!")

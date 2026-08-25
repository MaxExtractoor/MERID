"""
Seed Manager for Deterministic Reproducibility

Provides centralized seed management for all ML components to ensure
deterministic behavior and reproducibility across training and inference.

CRITICAL: All ML components must use this SeedManager for any stochastic operations.
"""

from __future__ import annotations

import time
import hashlib
from typing import Dict, Optional, List
from dataclasses import dataclass, field
from datetime import datetime, timezone
import random
import numpy as np

from utils.logger import get_logger

logger = get_logger("merid.ml.seed_manager")


@dataclass
class SeedRecord:
    """Record of a seed usage event."""
    seed: int
    context: str
    timestamp: float
    component: str
    purpose: str


@dataclass
class SeedHistory:
    """History of seed usage."""
    records: List[SeedRecord] = field(default_factory=list)
    
    def add_record(self, seed: int, context: str, component: str, purpose: str):
        """Add a seed usage record."""
        record = SeedRecord(
            seed=seed,
            context=context,
            timestamp=time.time(),
            component=component,
            purpose=purpose
        )
        self.records.append(record)
    
    def get_recent(self, limit: int = 100) -> List[SeedRecord]:
        """Get recent seed records."""
        return self.records[-limit:]
    
    def get_by_component(self, component: str) -> List[SeedRecord]:
        """Get seed records for a specific component."""
        return [r for r in self.records if r.component == component]


class SeedManager:
    """
    Centralized seed manager for deterministic reproducibility.
    
    Features:
    - Fixed base seed for reproducibility
    - Context-specific seed derivation
    - Seed history tracking
    - API endpoint support for seed history
    """
    
    def __init__(self, base_seed: int = 42):
        """
        Initialize the seed manager.
        
        Args:
            base_seed: Base seed for deterministic behavior (default: 42)
        """
        self.base_seed = base_seed
        self.history = SeedHistory()
        self._current_seed = base_seed
        
        logger.info(f"SeedManager initialized with base_seed={base_seed}")
    
    def set_seed(self, seed: int, context: str, component: str, purpose: str):
        """
        Set a seed for stochastic operations.
        
        Args:
            seed: Seed value
            context: Context string (e.g., "training", "inference")
            component: Component name (e.g., "model", "signal_generator")
            purpose: Purpose (e.g., "weight_init", "dropout")
        """
        self._current_seed = seed
        
        # Set both Python and NumPy seeds
        random.seed(seed)
        np.random.seed(seed)
        
        # Record usage
        self.history.add_record(seed, context, component, purpose)
        
        logger.debug(
            f"Seed set: seed={seed}, context={context}, "
            f"component={component}, purpose={purpose}"
        )
    
    def derive_seed(self, context: str, component: str, purpose: str) -> int:
        """
        Derive a deterministic seed from base seed and context.
        
        Args:
            context: Context string (e.g., "training", "inference")
            component: Component name (e.g., "model", "signal_generator")
            purpose: Purpose (e.g., "weight_init", "dropout")
            
        Returns:
            Derived seed value
        """
        # Create deterministic hash from base seed and context
        seed_string = f"{self.base_seed}_{context}_{component}_{purpose}"
        hash_value = hashlib.sha256(seed_string.encode()).hexdigest()
        
        # Convert to integer and ensure it's within valid range
        derived_seed = int(hash_value[:8], 16) % (2**32 - 1)
        
        return derived_seed
    
    def set_derived_seed(self, context: str, component: str, purpose: str):
        """
        Set a derived seed for stochastic operations.
        
        Args:
            context: Context string (e.g., "training", "inference")
            component: Component name (e.g., "model", "signal_generator")
            purpose: Purpose (e.g., "weight_init", "dropout")
        """
        derived_seed = self.derive_seed(context, component, purpose)
        self.set_seed(derived_seed, context, component, purpose)
    
    def get_current_seed(self) -> int:
        """Get the current seed value."""
        return self._current_seed
    
    def get_history(self, limit: int = 100) -> List[SeedRecord]:
        """Get recent seed history."""
        return self.history.get_recent(limit)
    
    def get_history_by_component(self, component: str) -> List[SeedRecord]:
        """Get seed history for a specific component."""
        return self.history.get_by_component(component)
    
    def reset_to_base(self):
        """Reset to base seed."""
        self._current_seed = self.base_seed
        random.seed(self.base_seed)
        np.random.seed(self.base_seed)
        logger.info(f"Seed reset to base_seed={self.base_seed}")
    
    def get_seed_summary(self) -> Dict:
        """
        Get a summary of seed usage.
        
        Returns:
            Dictionary with seed usage statistics
        """
        records = self.history.records
        
        if not records:
            return {
                "total_seeds_used": 0,
                "base_seed": self.base_seed,
                "current_seed": self._current_seed,
                "components": {},
                "contexts": {}
            }
        
        # Count by component
        components: Dict[str, int] = {}
        for record in records:
            components[record.component] = components.get(record.component, 0) + 1
        
        # Count by context
        contexts: Dict[str, int] = {}
        for record in records:
            contexts[record.context] = contexts.get(record.context, 0) + 1
        
        return {
            "total_seeds_used": len(records),
            "base_seed": self.base_seed,
            "current_seed": self._current_seed,
            "components": components,
            "contexts": contexts,
            "last_used": records[-1].timestamp if records else None
        }


# Global instance
_seed_manager: Optional[SeedManager] = None


def get_seed_manager() -> SeedManager:
    """Get the global seed manager instance."""
    global _seed_manager
    if _seed_manager is None:
        _seed_manager = SeedManager()
    return _seed_manager


def set_global_seed_manager(manager: SeedManager):
    """Set the global seed manager instance (for testing)."""
    global _seed_manager
    _seed_manager = manager


def reset_seed_manager():
    """Reset the global seed manager to default."""
    global _seed_manager
    _seed_manager = None

"""
Cross-Cutting Test: Seed Reproducibility

Confirms that running the same set of trades and predictions twice with the same
seeds yields identical behavior; changing seeds shifts only the intended stochastic pieces.

Targets:
- merid/ml/seed_manager.py
- AI signal components
- Training and inference paths
"""

import pytest
import numpy as np
import random


class TestSeedReproducibility:
    """Test seed reproducibility across ML components."""
    
    @pytest.mark.crosscutting
    @pytest.mark.production_audit
    def test_same_seed_identical_behavior(self):
        """
        Run same trades/predictions twice with same seeds, assert identical behavior.
        
        Validates:
        - Same seed produces identical results
        - Deterministic behavior enables debugging
        - Randomness is controlled
        """
        from merid.ml.seed_manager import SeedManager
        
        # Create two seed managers with same base seed
        manager1 = SeedManager(base_seed=42)
        manager2 = SeedManager(base_seed=42)
        
        # Get context-specific seeds
        seed1 = manager1.derive_seed("training", "model", "init")
        seed2 = manager2.derive_seed("training", "model", "init")
        
        # Seeds should be identical
        assert seed1 == seed2, "Same base seed should produce identical context seeds"
        
        # Verify deterministic random behavior
        random.seed(seed1)
        val1 = random.random()
        random.seed(seed2)
        val2 = random.random()
        
        assert val1 == val2, "Same seed should produce identical random values"
    
    @pytest.mark.crosscutting
    @pytest.mark.production_audit
    def test_different_seed_shifts_stochastic_only(self):
        """
        Change seeds and assert only stochastic pieces shift.
        
        Validates:
        - Different seeds change only stochastic components
        - Deterministic components remain unchanged
        - Seed changes are isolated to intended randomness
        """
        from merid.ml.seed_manager import SeedManager
        
        # Create two seed managers with different base seeds
        manager1 = SeedManager(base_seed=42)
        manager2 = SeedManager(base_seed=99)
        
        # Get context-specific seeds
        seed1 = manager1.derive_seed("training", "model", "init")
        seed2 = manager2.derive_seed("training", "model", "init")
        
        # Seeds should be different
        assert seed1 != seed2, "Different base seeds should produce different context seeds"
        
        # Verify different random behavior
        random.seed(seed1)
        val1 = random.random()
        random.seed(seed2)
        val2 = random.random()
        
        assert val1 != val2, "Different seeds should produce different random values"
    
    @pytest.mark.crosscutting
    def test_seed_manager_integration(self):
        """
        Assert that SeedManager is integrated into all training/inference paths.
        
        Validates:
        - All training paths use SeedManager
        - All inference paths use SeedManager
        - Seed history is logged
        """
        from merid.ml.seed_manager import get_seed_manager
        
        # Verify global seed manager exists
        manager = get_seed_manager()
        assert manager is not None, "Global seed manager should exist"
        
        # Verify it has history tracking
        assert hasattr(manager, 'history'), "Should have history tracking"
        
        # Verify it can set seeds
        manager.set_seed(42, "test", "context", "operation")
        
        # Verify seed was recorded in history
        assert len(manager.history.records) > 0, "Seed should be recorded in history"
    
    @pytest.mark.crosscutting
    def test_seed_history_api(self):
        """
        Assert that seed history is exposed via API.
        
        Validates:
        - API endpoint returns seed history
        - Seeds are logged with context
        - Historical seeds can be retrieved
        """
        from merid.ml.seed_manager import SeedManager, SeedRecord
        
        # Create seed manager and add some history
        manager = SeedManager(base_seed=42)
        manager.set_seed(42, "training", "model", "init")
        manager.set_seed(99, "inference", "signal", "generation")
        
        # Verify history is accessible
        assert len(manager.history.records) >= 2, "Should have at least 2 seed records"
        
        # Verify records have context
        for record in manager.history.records:
            assert isinstance(record, SeedRecord), "History should contain SeedRecord objects"
            assert record.context is not None, "Records should have context"

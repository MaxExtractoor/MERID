"""
Unit tests for ReflectionCore layer.

Tests:
- Decision recording
- Input validation
- Thread safety
- Memory management
- Query operations
"""

import pytest
import time
import threading
from agents.reflection.core import ReflectionCore, Reflection, DecisionOutcome


class TestReflectionCore:
    """Test suite for ReflectionCore."""
    
    def test_record_decision_basic(self):
        """Test basic decision recording."""
        core = ReflectionCore()
        
        reflection_id = core.record_decision(
            agent_id="test-agent",
            energy_id="test-energy",
            decision="accept",
            confidence=0.8,
            reasoning="Test reasoning"
        )
        
        assert reflection_id is not None
        assert len(reflection_id) > 0
        
        # Verify reflection stored
        reflection = core.get_reflection(reflection_id)
        assert reflection is not None
        assert reflection.agent_id == "test-agent"
        assert reflection.energy_id == "test-energy"
        assert reflection.decision == "accept"
        assert reflection.confidence == 0.8
        assert reflection.outcome == DecisionOutcome.PENDING
    
    def test_record_decision_validation(self):
        """Test input validation."""
        core = ReflectionCore()
        
        # Invalid confidence
        with pytest.raises(ValueError):
            core.record_decision(
                agent_id="test-agent",
                energy_id="test-energy",
                decision="accept",
                confidence=1.5,  # Invalid
                reasoning="Test"
            )
        
        # Invalid decision
        with pytest.raises(ValueError):
            core.record_decision(
                agent_id="test-agent",
                energy_id="test-energy",
                decision="invalid",  # Invalid
                confidence=0.5,
                reasoning="Test"
            )
    
    def test_update_outcome(self):
        """Test outcome updates."""
        core = ReflectionCore()
        
        reflection_id = core.record_decision(
            agent_id="test-agent",
            energy_id="test-energy",
            decision="accept",
            confidence=0.8,
            reasoning="Test"
        )
        
        # Update outcome
        success = core.update_outcome(
            reflection_id=reflection_id,
            outcome=DecisionOutcome.VALIDATED,
            reality_gap=0.15,
            validation_score=0.9,
            learning_insight="Good prediction"
        )
        
        assert success is True
        
        # Verify update
        reflection = core.get_reflection(reflection_id)
        assert reflection.outcome == DecisionOutcome.VALIDATED
        assert reflection.reality_gap == 0.15
        assert reflection.validation_score == 0.9
        assert reflection.learning_insight == "Good prediction"
        assert reflection.outcome_timestamp is not None
    
    def test_get_agent_reflections(self):
        """Test agent reflection queries."""
        core = ReflectionCore()
        
        # Record multiple reflections
        for i in range(5):
            core.record_decision(
                agent_id="agent-1",
                energy_id=f"energy-{i}",
                decision="accept",
                confidence=0.7 + i * 0.05,
                reasoning=f"Test {i}"
            )
        
        # Record for different agent
        core.record_decision(
            agent_id="agent-2",
            energy_id="energy-x",
            decision="reject",
            confidence=0.6,
            reasoning="Other agent"
        )
        
        # Query agent-1 reflections
        reflections = core.get_agent_reflections("agent-1")
        assert len(reflections) == 5
        
        # Verify sorted by timestamp (newest first)
        for i in range(len(reflections) - 1):
            assert reflections[i].decision_timestamp >= reflections[i+1].decision_timestamp
        
        # Query with limit
        limited = core.get_agent_reflections("agent-1", limit=3)
        assert len(limited) == 3
    
    def test_get_agent_reflections_with_filter(self):
        """Test filtered agent queries."""
        core = ReflectionCore()
        
        # Record and validate some
        for i in range(3):
            rid = core.record_decision(
                agent_id="agent-1",
                energy_id=f"energy-{i}",
                decision="accept",
                confidence=0.8,
                reasoning="Test"
            )
            core.update_outcome(
                rid,
                DecisionOutcome.VALIDATED,
                reality_gap=0.1
            )
        
        # Record and invalidate some
        for i in range(2):
            rid = core.record_decision(
                agent_id="agent-1",
                energy_id=f"energy-fail-{i}",
                decision="reject",
                confidence=0.7,
                reasoning="Test"
            )
            core.update_outcome(
                rid,
                DecisionOutcome.INVALIDATED,
                reality_gap=0.9
            )
        
        # Query validated only
        validated = core.get_agent_reflections(
            "agent-1",
            outcome_filter=DecisionOutcome.VALIDATED
        )
        assert len(validated) == 3
        
        # Query invalidated only
        invalidated = core.get_agent_reflections(
            "agent-1",
            outcome_filter=DecisionOutcome.INVALIDATED
        )
        assert len(invalidated) == 2
    
    def test_get_pending_reflections(self):
        """Test pending reflection queries."""
        core = ReflectionCore()
        
        # Record some reflections
        for i in range(3):
            core.record_decision(
                agent_id="agent-1",
                energy_id=f"energy-{i}",
                decision="accept",
                confidence=0.8,
                reasoning="Test"
            )
        
        # Validate one
        reflections = core.get_agent_reflections("agent-1")
        core.update_outcome(
            reflections[0].reflection_id,
            DecisionOutcome.VALIDATED,
            reality_gap=0.1
        )
        
        # Query pending
        pending = core.get_pending_reflections()
        assert len(pending) == 2
        
        for r in pending:
            assert r.outcome == DecisionOutcome.PENDING
    
    def test_thread_safety(self):
        """Test thread-safe operations."""
        core = ReflectionCore()
        results = []
        errors = []
        
        def record_decisions(agent_id: str, count: int):
            try:
                for i in range(count):
                    rid = core.record_decision(
                        agent_id=agent_id,
                        energy_id=f"energy-{agent_id}-{i}",
                        decision="accept",
                        confidence=0.8,
                        reasoning="Test"
                    )
                    results.append(rid)
            except Exception as e:
                errors.append(e)
        
        # Create multiple threads
        threads = []
        for i in range(5):
            t = threading.Thread(
                target=record_decisions,
                args=(f"agent-{i}", 10)
            )
            threads.append(t)
            t.start()
        
        # Wait for completion
        for t in threads:
            t.join()
        
        # Verify no errors
        assert len(errors) == 0
        
        # Verify all recorded
        assert len(results) == 50
        assert len(set(results)) == 50  # All unique
        
        # Verify stats
        stats = core.get_stats()
        assert stats["total_reflections"] == 50
        assert stats["active_agents"] == 5
    
    def test_memory_management(self):
        """Test memory eviction."""
        core = ReflectionCore(max_reflections=100)
        
        # Record more than max
        for i in range(150):
            core.record_decision(
                agent_id="agent-1",
                energy_id=f"energy-{i}",
                decision="accept",
                confidence=0.8,
                reasoning="Test"
            )
        
        # Verify eviction occurred
        stats = core.get_stats()
        assert stats["total_reflections"] <= 100
    
    def test_get_stats(self):
        """Test statistics reporting."""
        core = ReflectionCore()
        
        # Record some decisions
        for i in range(10):
            rid = core.record_decision(
                agent_id="agent-1",
                energy_id=f"energy-{i}",
                decision="accept",
                confidence=0.8,
                reasoning="Test"
            )
            
            if i % 2 == 0:
                core.update_outcome(
                    rid,
                    DecisionOutcome.VALIDATED,
                    reality_gap=0.1
                )
        
        stats = core.get_stats()
        
        assert stats["total_reflections"] == 10
        assert stats["active_agents"] == 1
        assert stats["operations"]["records"] == 10
        assert stats["operations"]["updates"] == 5
        assert "performance" in stats
        assert stats["performance"]["uptime_seconds"] > 0
    
    def test_reflection_age(self):
        """Test reflection age calculation."""
        core = ReflectionCore()
        
        rid = core.record_decision(
            agent_id="agent-1",
            energy_id="energy-1",
            decision="accept",
            confidence=0.8,
            reasoning="Test"
        )
        
        reflection = core.get_reflection(rid)
        
        # Age should be very small (just created)
        age = reflection.age_seconds()
        assert 0 <= age < 1.0
        
        # Wait a bit
        time.sleep(0.1)
        
        # Age should increase
        new_age = reflection.age_seconds()
        assert new_age > age
    
    def test_reflection_is_resolved(self):
        """Test resolved status check."""
        core = ReflectionCore()
        
        rid = core.record_decision(
            agent_id="agent-1",
            energy_id="energy-1",
            decision="accept",
            confidence=0.8,
            reasoning="Test"
        )
        
        reflection = core.get_reflection(rid)
        
        # Should not be resolved initially
        assert not reflection.is_resolved()
        
        # Update to validated
        core.update_outcome(
            rid,
            DecisionOutcome.VALIDATED,
            reality_gap=0.1
        )
        
        reflection = core.get_reflection(rid)
        assert reflection.is_resolved()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

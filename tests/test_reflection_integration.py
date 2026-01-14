"""
Integration tests for ReflectionSystem.

Tests:
- End-to-end decision recording and validation
- Multi-layer coordination
- System statistics
- Error handling
"""

import pytest
import time
from pathlib import Path
import tempfile
from agents.reflection.integration import ReflectionSystem


class TestReflectionIntegration:
    """Integration test suite for ReflectionSystem."""
    
    def test_end_to_end_consensus_validation(self):
        """Test complete workflow: record -> validate -> analyze."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "test_reflections.json"
            system = ReflectionSystem(storage_path=storage_path, auto_persist=False)
            
            # Record decision
            reflection_id = system.record_decision(
                agent_id="test-agent",
                energy_id="test-energy",
                decision="accept",
                confidence=0.8,
                reasoning="Test reasoning for acceptance",
                market_context={"symbol": "BTC", "price": 50000}
            )
            
            assert reflection_id is not None
            
            # Validate against consensus
            success = system.validate_consensus_outcome(
                reflection_id=reflection_id,
                actual_consensus="accept",
                consensus_confidence=0.9,
                vote_distribution={"accept": 8, "reject": 1, "abstain": 1}
            )
            
            assert success is True
            
            # Get metrics
            metrics = system.get_agent_metrics("test-agent")
            assert metrics is not None
            assert metrics.total_decisions == 1
            assert metrics.validated_count == 1
            assert metrics.accuracy == 1.0
            
            # Get context
            context = system.get_agent_context("test-agent")
            assert "test-agent" in context
            assert "Performance Metrics" in context
    
    def test_end_to_end_market_validation(self):
        """Test market outcome validation workflow."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "test_reflections.json"
            system = ReflectionSystem(storage_path=storage_path, auto_persist=False)
            
            # Record bullish decision
            reflection_id = system.record_decision(
                agent_id="market-agent",
                energy_id="market-energy",
                decision="accept",  # Bullish
                confidence=0.75,
                reasoning="Strong bullish signals",
                market_context={"symbol": "ETH", "price": 3000}
            )
            
            # Validate with positive price movement
            success = system.validate_market_outcome(
                reflection_id=reflection_id,
                actual_price_change=5.2,  # +5.2%
                timeframe_hours=24.0
            )
            
            assert success is True
            
            # Check metrics
            metrics = system.get_agent_metrics("market-agent")
            assert metrics.validated_count == 1
            assert metrics.avg_reality_gap < 1.0
    
    def test_multiple_agents_comparison(self):
        """Test comparing multiple agents."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "test_reflections.json"
            system = ReflectionSystem(storage_path=storage_path, auto_persist=False)
            
            # Create decisions for multiple agents with different accuracy
            agents = [
                ("agent-high", 0.9),
                ("agent-medium", 0.7),
                ("agent-low", 0.5)
            ]
            
            for agent_id, accuracy in agents:
                for i in range(10):
                    rid = system.record_decision(
                        agent_id=agent_id,
                        energy_id=f"energy-{agent_id}-{i}",
                        decision="accept",
                        confidence=0.8,
                        reasoning="Test"
                    )
                    
                    # Validate based on desired accuracy
                    if i < int(10 * accuracy):
                        actual = "accept"
                    else:
                        actual = "reject"
                    
                    system.validate_consensus_outcome(
                        rid, actual, 0.9, {"accept": 7, "reject": 3}
                    )
            
            # Get all metrics
            all_metrics = system.get_all_agent_metrics()
            assert len(all_metrics) == 3
            
            # Verify accuracy ordering
            assert all_metrics["agent-high"].accuracy > all_metrics["agent-medium"].accuracy
            assert all_metrics["agent-medium"].accuracy > all_metrics["agent-low"].accuracy
    
    def test_learning_insights_generation(self):
        """Test learning insights are generated correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "test_reflections.json"
            system = ReflectionSystem(storage_path=storage_path, auto_persist=False)
            
            # Create pattern of overconfident failures
            for i in range(10):
                rid = system.record_decision(
                    agent_id="overconfident-agent",
                    energy_id=f"energy-{i}",
                    decision="accept",
                    confidence=0.9,  # High confidence
                    reasoning="Very confident"
                )
                
                # All fail
                system.validate_consensus_outcome(
                    rid, "reject", 0.85, {"accept": 2, "reject": 8}
                )
            
            # Get insights
            insights = system.get_agent_insights("overconfident-agent")
            
            assert len(insights) > 0
            
            # Should detect overconfidence
            overconfidence_insights = [
                i for i in insights
                if "overconfidence" in i.title.lower() or "overconfidence" in str(i.pattern_tags)
            ]
            assert len(overconfidence_insights) > 0
    
    def test_persistence_save_and_load(self):
        """Test persistence layer saves and loads correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "test_reflections.json"
            
            # Create system and record decisions
            system1 = ReflectionSystem(storage_path=storage_path, auto_persist=True)
            
            for i in range(5):
                system1.record_decision(
                    agent_id="persist-agent",
                    energy_id=f"energy-{i}",
                    decision="accept",
                    confidence=0.8,
                    reasoning="Test"
                )
            
            # Force flush
            system1.persistence.flush()
            
            # Create new system instance (should load from storage)
            system2 = ReflectionSystem(storage_path=storage_path, auto_persist=False)
            
            # Verify loaded
            metrics = system2.get_agent_metrics("persist-agent")
            assert metrics is not None
            assert metrics.total_decisions == 5
    
    def test_context_with_no_history(self):
        """Test context generation with no history."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "test_reflections.json"
            system = ReflectionSystem(storage_path=storage_path, auto_persist=False)
            
            context = system.get_agent_context("new-agent")
            
            assert "No reflection history" in context
    
    def test_system_stats(self):
        """Test comprehensive system statistics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "test_reflections.json"
            system = ReflectionSystem(storage_path=storage_path, auto_persist=False)
            
            # Record some decisions
            for i in range(5):
                rid = system.record_decision(
                    agent_id="stats-agent",
                    energy_id=f"energy-{i}",
                    decision="accept",
                    confidence=0.8,
                    reasoning="Test"
                )
                
                system.validate_consensus_outcome(
                    rid, "accept", 0.9, {"accept": 8, "reject": 2}
                )
            
            # Get system stats
            stats = system.get_system_stats()
            
            assert "core" in stats
            assert "validator" in stats
            assert "analytics" in stats
            assert "learning" in stats
            assert "context" in stats
            assert "persistence" in stats
            
            # Verify core stats
            assert stats["core"]["total_reflections"] == 5
            assert stats["validator"]["total_validations"] == 5
    
    def test_invalid_reflection_id(self):
        """Test handling of invalid reflection ID."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "test_reflections.json"
            system = ReflectionSystem(storage_path=storage_path, auto_persist=False)
            
            # Try to validate non-existent reflection
            success = system.validate_consensus_outcome(
                reflection_id="invalid-id",
                actual_consensus="accept",
                consensus_confidence=0.9,
                vote_distribution={"accept": 8, "reject": 2}
            )
            
            assert success is False
    
    def test_concurrent_operations(self):
        """Test thread-safe concurrent operations."""
        import threading
        
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "test_reflections.json"
            system = ReflectionSystem(storage_path=storage_path, auto_persist=False)
            
            results = []
            errors = []
            
            def record_and_validate(agent_id: str, count: int):
                try:
                    for i in range(count):
                        rid = system.record_decision(
                            agent_id=agent_id,
                            energy_id=f"energy-{agent_id}-{i}",
                            decision="accept",
                            confidence=0.8,
                            reasoning="Test"
                        )
                        
                        system.validate_consensus_outcome(
                            rid, "accept", 0.9, {"accept": 8, "reject": 2}
                        )
                        
                        results.append(rid)
                except Exception as e:
                    errors.append(e)
            
            # Create multiple threads
            threads = []
            for i in range(3):
                t = threading.Thread(
                    target=record_and_validate,
                    args=(f"agent-{i}", 5)
                )
                threads.append(t)
                t.start()
            
            # Wait for completion
            for t in threads:
                t.join()
            
            # Verify no errors
            assert len(errors) == 0
            assert len(results) == 15
            
            # Verify all agents have correct metrics
            for i in range(3):
                metrics = system.get_agent_metrics(f"agent-{i}")
                assert metrics.total_decisions == 5
                assert metrics.validated_count == 5


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

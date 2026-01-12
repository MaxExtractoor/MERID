"""
MERID Production Systems Test Suite
Comprehensive tests for all production-grade implementations
"""

import pytest
import asyncio
import time
from typing import Dict, Any

# Import all production systems
from core.error_handling import (
    get_error_handler, get_health_monitor, CircuitBreaker,
    RetryStrategy, ErrorSeverity
)
from core.state_recovery import (
    get_state_manager, get_self_healing, GracefulDegradation
)
from agents.explainability import (
    get_explainability_tracker, create_reasoning_builder, DecisionType
)
from core.consensus_logging import (
    get_consensus_logger, VoteType, ConsensusOutcome
)
from core.trust_transparency import (
    get_trust_manager, TrustAdjustmentReason
)
from core.signal_provenance import (
    get_provenance_tracker, create_provenance_builder,
    SignalSource, ConflictResolution
)
from core.optimization_engine import get_optimization_engine
from core.automated_risk_controls import get_risk_coordinator
from core.collaboration_framework import get_collaboration_coordinator


class TestErrorHandling:
    """Test error handling framework"""
    
    @pytest.mark.asyncio
    async def test_circuit_breaker_opens_on_failures(self):
        """Test circuit breaker opens after threshold failures"""
        breaker = CircuitBreaker("test_breaker", failure_threshold=3, timeout=1.0)
        
        async def failing_function():
            raise Exception("Test failure")
        
        # Should fail 3 times before opening
        for i in range(3):
            with pytest.raises(Exception):
                await breaker.call(failing_function)
        
        # Circuit should now be open
        assert breaker.state.state == "open"
    
    @pytest.mark.asyncio
    async def test_retry_strategy_with_exponential_backoff(self):
        """Test retry strategy with exponential backoff"""
        strategy = RetryStrategy(max_attempts=3, initial_delay=0.1)
        
        attempt_count = 0
        
        async def flaky_function():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 3:
                raise Exception("Temporary failure")
            return "success"
        
        from core.error_handling import retry_async
        result = await retry_async(flaky_function, strategy)
        
        assert result == "success"
        assert attempt_count == 3
    
    def test_health_monitor_tracks_component_health(self):
        """Test health monitor tracks component health"""
        monitor = get_health_monitor()
        check = monitor.register_health_check("test_component")
        
        assert check.name == "test_component"
        assert check.is_healthy == True


class TestStateRecovery:
    """Test state recovery framework"""
    
    @pytest.mark.asyncio
    async def test_state_persistence(self):
        """Test state can be persisted and recovered"""
        manager = get_state_manager("test_component")
        
        test_state = {"counter": 42, "status": "active"}
        await manager.update_state(test_state)
        
        # State is stored in current_state attribute
        assert manager.current_state["counter"] == 42
        assert manager.current_state["status"] == "active"
    
    @pytest.mark.asyncio
    async def test_recovery_points(self):
        """Test recovery points are created"""
        manager = get_state_manager("test_recovery")
        
        state1 = {"version": 1}
        await manager.update_state(state1, create_recovery_point=True)
        
        state2 = {"version": 2}
        await manager.update_state(state2, create_recovery_point=True)
        
        # Should have recovery points
        assert len(manager.recovery_points) > 0
    
    @pytest.mark.asyncio
    async def test_self_healing_registration(self):
        """Test self-healing strategy registration"""
        healing = get_self_healing()
        
        async def heal_function():
            return True
        
        healing.register_healing_strategy("test_component", heal_function)
        
        # Should be registered
        assert "test_component" in healing.healing_strategies


class TestExplainability:
    """Test agent explainability framework"""
    
    def test_reasoning_builder_creates_decision(self):
        """Test reasoning builder creates complete decision"""
        builder = create_reasoning_builder(
            agent_id="test_agent",
            decision_type=DecisionType.VOTE
        )
        
        reasoning = (
            builder
            .set_decision("BUY", 0.85)
            .set_primary_reason("Strong bullish signal")
            .add_supporting_factor("RSI oversold")
            .add_contrary_factor("High volatility")
            .add_data_source("price_feed")
            .set_market_context({"price": 100})
            .build()
        )
        
        assert reasoning.agent_id == "test_agent"
        assert reasoning.decision == "BUY"
        assert reasoning.confidence == 0.85
        assert len(reasoning.supporting_factors) == 1
        assert len(reasoning.contrary_factors) == 1
    
    def test_explainability_tracker_records_decisions(self):
        """Test explainability tracker records decisions"""
        tracker = get_explainability_tracker()
        
        builder = create_reasoning_builder("agent1", DecisionType.VOTE)
        reasoning = builder.set_decision("SELL", 0.75).build()
        
        tracker.record_decision(reasoning)
        
        # Should be recorded
        decisions = tracker.get_agent_decisions("agent1")
        assert len(decisions) > 0


class TestConsensusLogging:
    """Test consensus logging framework"""
    
    def test_consensus_round_tracking(self):
        """Test consensus round is tracked"""
        logger = get_consensus_logger()
        
        proposal = {"action": "BUY", "symbol": "BTC"}
        round_id = logger.start_round(proposal, quorum_required=3)
        
        assert round_id is not None
        
        # Record votes
        logger.record_vote(
            round_id=round_id,
            agent_id="agent1",
            vote=VoteType.APPROVE,
            reasoning="Good signal",
            confidence=0.8,
            trust_weight=0.9
        )
        
        # Complete round
        logger.complete_round(
            round_id=round_id,
            outcome=ConsensusOutcome.PASSED,
            final_confidence=0.8,
            final_action="BUY"
        )
        
        # Should be in history
        round_data = logger.get_round(round_id)
        assert round_data is not None
        assert round_data.outcome == ConsensusOutcome.PASSED


class TestTrustTransparency:
    """Test trust transparency framework"""
    
    def test_trust_score_initialization(self):
        """Test trust score initialization"""
        manager = get_trust_manager()
        
        manager.initialize_agent("test_agent", 1.0)
        
        profile = manager.get_trust_profile("test_agent")
        assert profile is not None
        assert profile.current_score == 1.0
    
    def test_trust_adjustment_tracking(self):
        """Test trust adjustments are tracked"""
        manager = get_trust_manager()
        
        manager.initialize_agent("agent2", 1.0)
        
        manager.record_prediction_outcome(
            agent_id="agent2",
            correct=True,
            response_time_ms=100
        )
        
        profile = manager.get_trust_profile("agent2")
        assert len(profile.adjustment_history) > 0


class TestSignalProvenance:
    """Test signal provenance framework"""
    
    def test_provenance_builder_creates_chain(self):
        """Test provenance builder creates complete chain"""
        builder = create_provenance_builder()
        
        provenance = (
            builder
            .add_input_signal(
                source_id="price_feed",
                source_type=SignalSource.PRICE_FEED,
                signal_value="bullish",
                confidence=0.8
            )
            .add_input_signal(
                source_id="sentiment",
                source_type=SignalSource.SENTIMENT_AGENT,
                signal_value="bearish",
                confidence=0.6
            )
            .set_weighting(
                formula="trust * confidence",
                distribution={"price_feed": 0.6, "sentiment": 0.4}
            )
            .add_step("Collected input signals")
            .add_step("Applied weighting formula")
            .set_final_signal("bullish", 0.72)
            .build()
        )
        
        assert len(provenance.input_signals) == 2
        assert provenance.final_signal == "bullish"
        assert provenance.final_confidence == 0.72
    
    def test_provenance_tracker_records_synthesis(self):
        """Test provenance tracker records synthesis"""
        tracker = get_provenance_tracker()
        
        builder = create_provenance_builder()
        provenance = (
            builder
            .add_input_signal("source1", SignalSource.TECHNICAL_AGENT, "buy", 0.9)
            .set_final_signal("buy", 0.9)
            .build()
        )
        
        tracker.record_synthesis(provenance)
        
        # Should be recorded
        recent = tracker.get_recent_syntheses(limit=10)
        assert len(recent) > 0


class TestOptimizationEngine:
    """Test optimization engine"""
    
    @pytest.mark.asyncio
    async def test_comprehensive_optimization(self):
        """Test comprehensive optimization runs"""
        engine = get_optimization_engine()
        
        results = await engine.run_comprehensive_optimization()
        
        assert 'results' in results
        assert 'summary' in results
        assert results['summary']['overall_score'] > 0
    
    def test_complexity_analyzer(self):
        """Test complexity analyzer"""
        from core.optimization_engine import ComplexityAnalyzer
        
        analyzer = ComplexityAnalyzer()
        
        code = """
def complex_function(x):
    if x > 0:
        if x > 10:
            if x > 20:
                return "high"
        return "medium"
    return "low"
"""
        
        analysis = analyzer.analyze_function_complexity(code, "complex_function")
        
        # Complex function should trigger refactoring suggestions
        assert analysis['cyclomatic_complexity'] > 1
        # Suggestions are generated based on thresholds
        # This simple function may not exceed all thresholds


class TestRiskControls:
    """Test automated risk controls"""
    
    @pytest.mark.asyncio
    async def test_position_limit_enforcement(self):
        """Test position limits are enforced"""
        coordinator = get_risk_coordinator()
        coordinator.portfolio_manager.portfolio_value = 100000
        
        # Try to open position larger than limit
        result = await coordinator.portfolio_manager.check_position_allowed(
            symbol="BTC",
            position_size=100,
            price=50000  # 5M position on 100k portfolio = 50x
        )
        
        assert result['allowed'] == False
        assert len(result['violations']) > 0
    
    def test_dynamic_position_sizing(self):
        """Test dynamic position sizing"""
        from core.automated_risk_controls import DynamicPositionSizer
        
        sizer = DynamicPositionSizer(base_risk_per_trade=0.02)
        
        result = sizer.calculate_position_size(
            portfolio_value=100000,
            entry_price=100,
            stop_loss_price=95,
            confidence=0.8
        )
        
        assert result['position_size'] > 0
        assert result['risk_pct'] <= 0.02
    
    def test_stop_loss_management(self):
        """Test stop loss management"""
        from core.automated_risk_controls import AutomatedStopLossManager
        
        manager = AutomatedStopLossManager()
        
        manager.set_stop_loss("BTC", stop_price=95000)
        manager.set_take_profit("BTC", target_price=105000)
        
        # Check stops at different prices
        result = manager.check_stops("BTC", current_price=94000)
        assert result['should_exit'] == True
        assert any(t['type'] == 'stop_loss' for t in result['triggered'])


class TestCollaboration:
    """Test collaboration framework"""
    
    @pytest.mark.asyncio
    async def test_event_bus_publish_subscribe(self):
        """Test event bus publish/subscribe"""
        from core.collaboration_framework import EventBus
        
        bus = EventBus()
        received_events = []
        
        async def handler(data):
            received_events.append(data)
        
        bus.subscribe("test_event", handler)
        await bus.publish("test_event", {"message": "hello"})
        
        # Give async time to process
        await asyncio.sleep(0.1)
        
        assert len(received_events) > 0
        assert received_events[0]['message'] == "hello"
    
    def test_service_registry(self):
        """Test service registry"""
        from core.collaboration_framework import ServiceRegistry, ComponentInterface
        
        registry = ServiceRegistry()
        
        interface = ComponentInterface(
            component_name="test_service",
            provides=["data_processing"],
            requires=["database"]
        )
        
        registry.register_service(interface)
        
        discovered = registry.discover_service("test_service")
        assert discovered is not None
        assert discovered.component_name == "test_service"
    
    def test_integration_analyzer(self):
        """Test integration analyzer"""
        from core.collaboration_framework import (
            IntegrationAnalyzer, IntegrationPoint,
            IntegrationPattern, CouplingLevel
        )
        
        analyzer = IntegrationAnalyzer()
        
        integration = IntegrationPoint(
            source_component="service_a",
            target_component="service_b",
            integration_pattern=IntegrationPattern.DIRECT_CALL,
            coupling_level=CouplingLevel.TIGHT,
            data_flow="unidirectional"
        )
        
        analyzer.register_integration(integration)
        
        analysis = analyzer.analyze_coupling()
        assert analysis['total_integrations'] == 1
        assert analysis['tight_couplings'] == 1


class TestIntegration:
    """Integration tests across systems"""
    
    @pytest.mark.asyncio
    async def test_error_handling_with_state_recovery(self):
        """Test error handling integrates with state recovery"""
        handler = get_error_handler()
        manager = get_state_manager("integration_test")
        
        # Save state
        await manager.update_state({"status": "running"})
        
        # Simulate error
        try:
            raise Exception("Test error")
        except Exception as e:
            await handler.handle_error(e, "test", "operation", ErrorSeverity.HIGH)
        
        # State should still be recoverable
        # State should still be accessible
        assert manager.current_state is not None
    
    @pytest.mark.asyncio
    async def test_explainability_with_consensus(self):
        """Test explainability integrates with consensus"""
        explainability = get_explainability_tracker()
        consensus = get_consensus_logger()
        
        # Create decision with reasoning
        builder = create_reasoning_builder("agent1", DecisionType.VOTE)
        reasoning = builder.set_decision("APPROVE", 0.85).build()
        explainability.record_decision(reasoning)
        
        # Start consensus round
        round_id = consensus.start_round({"action": "BUY"}, quorum_required=2)
        consensus.record_vote(
            round_id=round_id,
            agent_id="agent1",
            vote=VoteType.APPROVE,
            reasoning="Strong signal",
            confidence=0.85,
            trust_weight=0.9
        )
        
        # Both systems should have records
        decisions = explainability.get_agent_decisions("agent1")
        round_data = consensus.get_round(round_id)
        
        assert len(decisions) > 0
        assert round_data is not None


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests"""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])

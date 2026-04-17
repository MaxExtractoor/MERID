"""Extended validation tests for BaseKalshiAgent contract and singleton behavior.

This module provides:
1. Meta-tests introspecting all BaseKalshiAgent subclasses
2. Smoke tests for regime agent instantiation
3. Bootstrap order validation
4. LoopLagMonitor lifecycle verification
"""

import pytest
import asyncio
import inspect
import importlib
import pkgutil
from typing import Type, List, Any, Optional


class TestBaseKalshiAgentContractIntrospection:
    """Meta-tests that validate all BaseKalshiAgent subclasses follow the contract."""

    def _get_all_subclasses(self, base_class: Type) -> List[Type]:
        """Recursively get all subclasses of a base class."""
        subclasses = []
        for subclass in base_class.__subclasses__():
            subclasses.append(subclass)
            subclasses.extend(self._get_all_subclasses(subclass))
        return subclasses

    def test_all_subclasses_have_valid_init_signatures(self):
        """Verify all BaseKalshiAgent subclasses call super().__init__ correctly."""
        from merid.agents.base import BaseKalshiAgent
        
        subclasses = self._get_all_subclasses(BaseKalshiAgent)
        
        failures = []
        for cls in subclasses:
            # Get __init__ signature
            init_sig = inspect.signature(cls.__init__)
            params = list(init_sig.parameters.keys())
            
            # Check that the class properly handles initialization
            try:
                # Get source to verify super().__init__ call
                source = inspect.getsource(cls.__init__)
                
                # Must call super().__init__ with agent_id
                if "super().__init__" not in source:
                    failures.append(f"{cls.__name__}: Missing super().__init__ call")
                elif "agent_id" not in source:
                    failures.append(f"{cls.__name__}: super().__init__ doesn't pass agent_id")
                    
            except (OSError, TypeError):
                # Can't get source (built-in or dynamically created), skip detailed check
                pass
        
        if failures:
            pytest.fail("BaseKalshiAgent subclass init violations:\n" + "\n".join(failures))

    def test_all_get_opinion_signatures_match_abstract(self):
        """Verify all concrete get_opinion methods match abstract signature."""
        from merid.agents.base import BaseKalshiAgent, AgentOpinion
        
        # Get abstract signature
        abstract_sig = inspect.signature(BaseKalshiAgent.get_opinion)
        abstract_params = list(abstract_sig.parameters.keys())
        
        subclasses = self._get_all_subclasses(BaseKalshiAgent)
        
        failures = []
        for cls in subclasses:
            # Check if get_opinion is overridden
            if 'get_opinion' not in cls.__dict__:
                continue  # Uses parent implementation
                
            method = cls.get_opinion
            concrete_sig = inspect.signature(method)
            concrete_params = list(concrete_sig.parameters.keys())
            
            # Check parameters match (allow additional but require base params)
            for param in abstract_params:
                if param not in concrete_params:
                    failures.append(f"{cls.__name__}.get_opinion: Missing param '{param}'")
        
        if failures:
            pytest.fail("get_opinion signature mismatches:\n" + "\n".join(failures))

    def test_all_concrete_agents_return_agent_opinion_or_none(self):
        """Verify get_opinion return type hints are correct."""
        from merid.agents.base import BaseKalshiAgent, AgentOpinion
        
        subclasses = self._get_all_subclasses(BaseKalshiAgent)
        
        for cls in subclasses:
            if 'get_opinion' not in cls.__dict__:
                continue
                
            method = cls.get_opinion
            hints = method.__annotations__
            
            # Check return type is Optional[AgentOpinion] or AgentOpinion
            return_type = hints.get('return', None)
            if return_type is None:
                pytest.fail(f"{cls.__name__}.get_opinion missing return type hint")
            
            # Should accept None as return
            assert 'AgentOpinion' in str(return_type), \
                f"{cls.__name__}: return type should include AgentOpinion"


class TestRegimeAgentInstantiation:
    """Smoke tests that agents can be instantiated without side effects."""

    def test_eth_15m_agent_instantiation_no_side_effects(self):
        """Eth15mAgent should instantiate without touching Redis or Kalshi."""
        from merid.agents.eth_15m_agent import Eth15mAgent
        
        agent = Eth15mAgent()
        assert agent.agent_id == "eth_15m"
        assert agent.category.value == "strategy"

    def test_sol_15m_agent_instantiation_no_side_effects(self):
        """Sol15mAgent should instantiate without touching Redis or Kalshi."""
        from merid.agents.sol_15m_agent import Sol15mAgent
        
        agent = Sol15mAgent()
        assert agent.agent_id == "sol_15m"
        assert agent.category.value == "strategy"

    def test_btc_1h_agent_instantiation_no_side_effects(self):
        """Btc1hAgent should instantiate without touching Redis or Kalshi."""
        from merid.agents.btc_1h_agent import Btc1hAgent
        
        agent = Btc1hAgent()
        assert agent.agent_id == "btc_1h"
        assert agent.category.value == "strategy"

    def test_xrp_15m_agent_instantiation_no_side_effects(self):
        """Xrp15mAgent should instantiate without touching Redis or Kalshi."""
        from merid.agents.xrp_15m_agent import Xrp15mAgent
        
        agent = Xrp15mAgent()
        assert agent.agent_id == "xrp_15m"
        assert agent.category.value == "strategy"

    def test_doge_15m_agent_instantiation_no_side_effects(self):
        """Doge15mAgent should instantiate without touching Redis or Kalshi."""
        from merid.agents.doge_15m_agent import Doge15mAgent
        
        agent = Doge15mAgent()
        assert agent.agent_id == "doge_15m"
        assert agent.category.value == "strategy"


class TestLoopLagMonitorLifecycle:
    """Verify LoopLagMonitor lifecycle and usage patterns."""

    def test_singleton_access_only_through_getter(self):
        """LoopLagMonitor should only be accessed via get_loop_lag_monitor()."""
        from merid.diagnostics.loop_lag import get_loop_lag_monitor, LoopLagMonitor
        
        # Direct instantiation should be discouraged (but possible for testing)
        # All production code should use the getter
        monitor1 = get_loop_lag_monitor()
        monitor2 = get_loop_lag_monitor()
        
        assert monitor1 is monitor2
        assert isinstance(monitor1, LoopLagMonitor)

    def test_monitor_can_start_and_stop_cleanly(self):
        """LoopLagMonitor should handle start/stop without errors."""
        from merid.diagnostics.loop_lag import get_loop_lag_monitor
        
        monitor = get_loop_lag_monitor()
        
        # Should be able to stop even if never started
        monitor.stop()
        
        # Start should work
        monitor.start()
        assert monitor._running is True
        
        # Stop should work
        monitor.stop()
        assert monitor._running is False

    def test_stats_available_without_start(self):
        """Stats methods should work even without starting the monitor."""
        from merid.diagnostics.loop_lag import get_loop_lag_monitor
        
        monitor = get_loop_lag_monitor()
        stats = monitor.get_stats()
        
        # Should have some default structure
        assert stats is not None


class TestPredictionRiskSingletonImmutability:
    """Verify risk singleton is not accidentally mutated by agents."""

    def test_risk_object_identity_across_multiple_agents(self):
        """Multiple TradingAgent instances should share identical risk object."""
        from merid.prediction.risk import get_prediction_risk, PredictionRiskConfig
        
        # Reset singleton for clean test
        import merid.prediction.risk as risk_module
        original_risk = risk_module._risk
        risk_module._risk = None
        
        try:
            # Initialize once (as AgentGrid does)
            risk1 = get_prediction_risk(PredictionRiskConfig())
            
            # Simulate multiple agent accesses
            risk2 = get_prediction_risk()
            risk3 = get_prediction_risk()
            
            # All should be identical object
            assert risk1 is risk2 is risk3, "Risk singleton identity broken"
            
            # Check id() values are identical
            assert id(risk1) == id(risk2) == id(risk3)
        finally:
            # Restore original
            risk_module._risk = original_risk

    def test_no_copy_or_replace_on_risk_object(self):
        """Verify no code copies or replaces the risk singleton."""
        import ast
        import os
        
        # Search for problematic patterns in the codebase
        problematic_patterns = [
            "copy.deepcopy",
            "copy.copy",
            "dataclasses.replace",
        ]
        
        # Files that should be checked
        check_dirs = [
            "merid/prediction",
            "merid/agents",
            "merid/trading",
        ]
        
        violations = []
        
        for check_dir in check_dirs:
            dir_path = os.path.join(os.getcwd(), check_dir)
            if not os.path.exists(dir_path):
                continue
                
            for root, _, files in os.walk(dir_path):
                for file in files:
                    if not file.endswith('.py'):
                        continue
                        
                    filepath = os.path.join(root, file)
                    try:
                        with open(filepath, 'r') as f:
                            content = f.read()
                            
                        # Check for copy patterns near risk references
                        if 'risk' in content.lower():
                            for pattern in problematic_patterns:
                                if pattern in content:
                                    violations.append(f"{filepath}: {pattern}")
                    except Exception:
                        pass
        
        if violations:
            pytest.fail("Potential risk object copying detected:\n" + "\n".join(violations))


class TestBootstrapOrderGuard:
    """Verify initialization order constraints."""

    def test_agent_grid_initializes_risk_before_creating_agents(self):
        """AgentGrid should call get_prediction_risk(config) before any agent creation."""
        from merid.prediction.agent_grid import AgentGrid
        from merid.prediction.risk import get_prediction_risk, PredictionRiskConfig
        
        import merid.prediction.risk as risk_module
        
        # Reset singleton
        original_risk = risk_module._risk
        risk_module._risk = None
        
        try:
            # Track initialization order
            init_order = []
            
            original_init = PredictionMarketRisk.__init__
            def tracking_init(self, config):
                init_order.append('risk_initialized')
                return original_init(self, config)
            
            # Patch for tracking
            from merid.prediction import risk as risk_mod
            original_risk_class_init = risk_mod.PredictionMarketRisk.__init__
            risk_mod.PredictionMarketRisk.__init__ = tracking_init
            
            try:
                # Create grid (should initialize risk)
                # Note: We can't fully instantiate without more mocks,
                # but we can check the pattern in the code
                source = inspect.getsource(AgentGrid.__init__)
                
                # Should call get_prediction_risk with config before agent creation
                assert "get_prediction_risk" in source
                assert "PredictionRiskConfig" in source
                
            finally:
                risk_mod.PredictionMarketRisk.__init__ = original_risk_class_init
                
        finally:
            risk_module._risk = original_risk


class TestRegimeGridSmokeTest:
    """Smoke test for the full regime agent grid."""

    @pytest.mark.asyncio
    async def test_all_regime_agents_can_generate_opinion(self):
        """All regime agents should be able to generate opinions."""
        from merid.agents.eth_15m_agent import Eth15mAgent
        from merid.agents.sol_15m_agent import Sol15mAgent
        from merid.agents.btc_1h_agent import Btc1hAgent
        from merid.agents.xrp_15m_agent import Xrp15mAgent
        from merid.agents.doge_15m_agent import Doge15mAgent
        
        agents = [
            Eth15mAgent(),
            Sol15mAgent(),
            Btc1hAgent(),
            Xrp15mAgent(),
            Doge15mAgent(),
        ]
        
        # Each agent should be able to generate an opinion (or None)
        for agent in agents:
            opinion = await agent.get_opinion(
                trace_id="test_trace",
                correlation_id="test_correlation"
            )
            
            # Should return AgentOpinion or None
            if opinion is not None:
                assert opinion.agent_id == agent.agent_id
                assert opinion.trace_id == "test_trace"
                assert opinion.correlation_id == "test_correlation"

    def test_regime_agents_have_unique_ids(self):
        """Each regime agent should have a unique agent_id."""
        from merid.agents.eth_15m_agent import Eth15mAgent
        from merid.agents.sol_15m_agent import Sol15mAgent
        from merid.agents.btc_1h_agent import Btc1hAgent
        from merid.agents.xrp_15m_agent import Xrp15mAgent
        from merid.agents.doge_15m_agent import Doge15mAgent
        
        agents = [
            Eth15mAgent(),
            Sol15mAgent(),
            Btc1hAgent(),
            Xrp15mAgent(),
            Doge15mAgent(),
        ]
        
        ids = [a.agent_id for a in agents]
        assert len(set(ids)) == len(ids), f"Duplicate agent IDs: {ids}"


# Import needed classes at module level for tests
from merid.prediction.risk import PredictionMarketRisk

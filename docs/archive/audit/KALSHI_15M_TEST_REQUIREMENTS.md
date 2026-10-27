# Kalshi 15m Agent Pruning - Startup Invariants and Test Requirements

## Startup Invariants

For `MERID_PROFILE=kalshi_crypto_15m_v2`, the following invariants must hold at startup:

### Invariant 1: Agent Registry Size
**Statement**: `AGENT_REGISTRY_SUMMARY: total <= MAX_15M_AGENTS`  
**Value**: `MAX_15M_AGENTS = 10`  
**Rationale**: Production 15m stack should only have 5 signal agents + 1 portfolio risk + optional monitoring (max 3)  
**Implementation**: `merid/prediction/agent_grid.py::__init__()` after agent creation  
**Violation Handling**: Log warning, continue (non-blocking)  
**Test**: `test_agent_registry_size_within_limit()`

### Invariant 2: No Research Agents in Registry
**Statement**: No agents classified as `research_only` or `remove` in active registry  
**Rationale**: Production should not load experimental or obsolete agents  
**Implementation**: `merid/prediction/agent_grid.py::__init__()` during agent filtering  
**Violation Handling**: Log warning and skip agent, continue  
**Test**: `test_no_research_agents_in_registry()`

### Invariant 3: Reflection System Disabled
**Statement**: Reflection system must report "disabled" or return None  
**Rationale**: Reflection system is designed for LLM agents, not deterministic 15m Kalshi agents  
**Implementation**: `agents/reflection/integration.py::get_reflection_system()`  
**Violation Handling**: Log error, continue (non-blocking for safety)  
**Test**: `test_reflection_system_disabled()`

### Invariant 4: AgentMesh Disabled
**Statement**: AgentMesh must not start for kalshi_crypto_15m_v2 profile  
**Rationale**: AgentMesh runs LLM-based streaming agents, not used in Kalshi 15m  
**Implementation**: `web/startup_agents.py::start_all()`  
**Violation Handling**: Log warning, continue  
**Test**: `test_agent_mesh_disabled()`

### Invariant 5: No LLM Agents in Logs
**Statement**: No LLM-based agent initialization logs (MarketAnalystAgent, BullAnalyst, etc.)  
**Rationale**: 15m Kalshi uses deterministic signal generators, not LLM agents  
**Implementation**: Log inspection in tests  
**Violation Handling**: Test failure  
**Test**: `test_no_llm_agents_in_logs()`

### Invariant 6: Profile Validation Passed
**Statement**: Profile config must pass all validation checks  
**Rationale**: Ensure profile configuration is valid and safe  
**Implementation**: `merid/startup_validations.py::validate_all()`  
**Violation Handling**: Raise ValueError, fail startup  
**Test**: `test_profile_validation_passed()`

### Invariant 7: Only Allowed Assets
**Statement**: Only BTC, ETH, SOL, XRP, DOGE assets in agent configurations  
**Rationale**: Production restricted to 5 crypto assets  
**Implementation**: `merid/prediction/agent_grid_config.py::_parse_agent()`  
**Violation Handling**: Log warning, skip agent  
**Test**: `test_only_allowed_assets_in_config()`

### Invariant 8: Only 15m Timeframe
**Statement**: Only 15m timeframe in agent configurations  
**Rationale**: Production restricted to 15-minute contracts  
**Implementation**: `merid/prediction/agent_grid_config.py::_parse_agent()`  
**Violation Handling**: Log warning, skip agent  
**Test**: `test_only_15m_timeframe_in_config()`

---

## Test Requirements

### Unit Tests

#### Test Suite: TestReflectionProfileGuard
**File**: `tests/test_kalshi_15m_agent_pruning.py`

```python
class TestReflectionProfileGuard:
    """Test reflection system profile guard."""
    
    def test_reflection_disabled_for_kalshi_crypto_15m_v2(self):
        """Reflection system should be disabled for kalshi_crypto_15m_v2 profile."""
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}):
            from agents.reflection.integration import get_reflection_system
            rs = get_reflection_system()
            assert rs is None, "Reflection system should be None for kalshi_crypto_15m_v2"
    
    def test_reflection_disabled_for_kalshi_crypto_15m(self):
        """Reflection system should be disabled for kalshi_crypto_15m profile."""
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m'}):
            from agents.reflection.integration import get_reflection_system
            rs = get_reflection_system()
            assert rs is None, "Reflection system should be None for kalshi_crypto_15m"
    
    def test_reflection_enabled_for_other_profiles(self):
        """Reflection system should be enabled for non-15m profiles."""
        with patch.dict(os.environ, {'MERID_PROFILE': 'full'}):
            from agents.reflection.integration import get_reflection_system
            rs = get_reflection_system()
            assert rs is not None, "Reflection system should be enabled for full profile"
    
    def test_reflection_enabled_when_profile_not_set(self):
        """Reflection system should be enabled when profile is not set."""
        with patch.dict(os.environ, {}, clear=True):
            from agents.reflection.integration import get_reflection_system
            rs = get_reflection_system()
            assert rs is not None, "Reflection system should be enabled when profile not set"
```

#### Test Suite: TestAgentMeshProfileGuard
**File**: `tests/test_kalshi_15m_agent_pruning.py`

```python
class TestAgentMeshProfileGuard:
    """Test AgentMesh profile guard."""
    
    @pytest.mark.asyncio
    async def test_agent_mesh_skipped_for_kalshi_crypto_15m_v2(self, caplog):
        """AgentMesh should be skipped for kalshi_crypto_15m_v2 profile."""
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}):
            from web.startup_agents import OrchestratorAgentManager
            manager = OrchestratorAgentManager()
            await manager.start_all()
            
            # Check that AgentMesh was skipped
            assert any("AgentMesh skipped" in record.message for record in caplog.records)
    
    @pytest.mark.asyncio
    async def test_agent_mesh_starts_for_other_profiles(self, caplog):
        """AgentMesh should start for non-15m profiles."""
        with patch.dict(os.environ, {'MERID_PROFILE': 'full'}):
            # This test requires mocking the agent mesh dependencies
            # For now, this is a placeholder
            pass
```

#### Test Suite: TestAgentRegistryValidation
**File**: `tests/test_kalshi_15m_agent_pruning.py`

```python
class TestAgentRegistryValidation:
    """Test agent registry validation."""
    
    def test_validate_agent_registry_for_profile_exists(self):
        """validate_agent_registry_for_profile function should exist."""
        from merid.startup_validations import validate_agent_registry_for_profile
        assert callable(validate_agent_registry_for_profile)
    
    def test_validate_agent_registry_for_profile_calls_validate_all(self):
        """validate_agent_registry_for_profile should be called in validate_all."""
        from merid.startup_validations import validate_all
        import inspect
        source = inspect.getsource(validate_all)
        assert 'validate_agent_registry_for_profile' in source
    
    def test_validate_agent_registry_for_profile_skips_non_15m_profiles(self, caplog):
        """Validation should skip non-15m profiles."""
        with patch.dict(os.environ, {'MERID_PROFILE': 'full'}):
            from merid.startup_validations import validate_agent_registry_for_profile
            validate_agent_registry_for_profile()
            
            assert any("not a 15m crypto profile" in record.message for record in caplog.records)
```

#### Test Suite: TestAgentClassificationFiltering
**File**: `tests/test_kalshi_15m_agent_pruning.py`

```python
class TestAgentClassificationFiltering:
    """Test agent classification filtering."""
    
    def test_agent_config_has_classification_field(self):
        """AgentConfig should have classification field."""
        from merid.prediction.agent_grid_config import AgentConfig
        config = AgentConfig(name="TEST", classification="prod_15m_core")
        assert config.classification == "prod_15m_core"
    
    def test_agent_config_default_classification(self):
        """AgentConfig should default to research_only classification."""
        from merid.prediction.agent_grid_config import AgentConfig
        config = AgentConfig(name="TEST")
        assert config.classification == "research_only"
    
    def test_research_only_agents_filtered_for_15m_profile(self, caplog):
        """Research-only agents should be filtered out for 15m profile."""
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}):
            # This test requires mocking the agent grid initialization
            # For now, this is a placeholder
            pass
```

#### Test Suite: TestAgentInventoryCompleteness
**File**: `tests/test_kalshi_15m_agent_pruning.py`

```python
class TestAgentInventoryCompleteness:
    """Test agent inventory completeness."""
    
    def test_kalshi_15m_agent_inventory_exists(self):
        """Kalshi 15m agent inventory document should exist."""
        from pathlib import Path
        inventory_path = Path("docs/audit/KALSHI_15M_AGENT_INVENTORY.md")
        assert inventory_path.exists(), "Agent inventory document should exist"
    
    def test_reflection_audit_exists(self):
        """Reflection audit document should exist."""
        from pathlib import Path
        audit_path = Path("docs/audit/KALSHI_15M_REFLECTION_AUDIT.md")
        assert audit_path.exists(), "Reflection audit document should exist"
    
    def test_diff_plan_exists(self):
        """Diff plan document should exist."""
        from pathlib import Path
        plan_path = Path("docs/audit/KALSHI_15M_DIFF_PLAN.md")
        assert plan_path.exists(), "Diff plan document should exist"
    
    def test_test_requirements_exists(self):
        """Test requirements document should exist."""
        from pathlib import Path
        req_path = Path("docs/audit/KALSHI_15M_TEST_REQUIREMENTS.md")
        assert req_path.exists(), "Test requirements document should exist"
```

### Integration Tests

#### Test Suite: TestKalshi15mProfileStartup
**File**: `tests/test_kalshi_15m_profile_startup.py`

```python
class TestKalshi15mProfileStartup:
    """Integration tests for Kalshi 15m profile startup."""
    
    @pytest.mark.asyncio
    async def test_startup_with_kalshi_crypto_15m_v2_profile(self, caplog):
        """Test full startup sequence with kalshi_crypto_15m_v2 profile."""
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}):
            from merid.prediction.agent_grid import get_agent_grid
            grid = get_agent_grid()
            
            # Check agent count
            assert len(grid._agents) == 5, "Should have 5 signal agents"
            
            # Check log sequence
            log_messages = [record.message for record in caplog.records]
            assert any("AGENT-REGISTRY-SUMMARY" in msg for msg in log_messages)
            assert any("Reflection disabled" in msg for msg in log_messages)
    
    @pytest.mark.asyncio
    async def test_no_llm_agents_loaded(self, caplog):
        """Test that no LLM agents are loaded for 15m profile."""
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi_crypto_15m_v2'}):
            from merid.prediction.agent_grid import get_agent_grid
            grid = get_agent_grid()
            
            # Check that only KalshiTradingAgent instances are loaded
            from merid.prediction.trading_agent import KalshiTradingAgent
            for agent in grid._agents:
                assert isinstance(agent, KalshiTradingAgent), f"Agent {agent} should be KalshiTradingAgent"
    
    def test_agent_grid_yaml_has_15m_agents_only(self):
        """Test that agent grid YAML only has 15m agents enabled."""
        import yaml
        from pathlib import Path
        
        yaml_path = Path("config/kalshi_agent_grid.yaml")
        with open(yaml_path) as f:
            config = yaml.safe_load(f)
        
        enabled_agents = [a for a in config['agents'] if a.get('enabled', True)]
        assert len(enabled_agents) == 5, "Should have 5 enabled agents"
        
        agent_names = [a['name'] for a in enabled_agents]
        expected_names = ['BTC_15M', 'ETH_15M', 'SOL_15M', 'XRP_15M', 'DOGE_15M']
        assert set(agent_names) == set(expected_names), f"Agent names should be {expected_names}"
```

### Regression Tests

#### Test Suite: TestOtherProfilesUnaffected
**File**: `tests/test_kalshi_15m_agent_pruning.py`

```python
class TestOtherProfilesUnaffected:
    """Test that other profiles are unaffected by profile guards."""
    
    def test_full_profile_reflection_enabled(self):
        """Reflection should be enabled for full profile."""
        with patch.dict(os.environ, {'MERID_PROFILE': 'full'}):
            from agents.reflection.integration import get_reflection_system
            rs = get_reflection_system()
            assert rs is not None, "Reflection should be enabled for full profile"
    
    def test_kalshi_only_profile_reflection_enabled(self):
        """Reflection should be enabled for kalshi-only profile."""
        with patch.dict(os.environ, {'MERID_PROFILE': 'kalshi-only'}):
            from agents.reflection.integration import get_reflection_system
            rs = get_reflection_system()
            assert rs is not None, "Reflection should be enabled for kalshi-only profile"
```

---

## Test Execution

### Running Tests

```bash
# Run all Kalshi 15m agent pruning tests
pytest tests/test_kalshi_15m_agent_pruning.py -v

# Run with specific profile
MERID_PROFILE=kalshi_crypto_15m_v2 pytest tests/test_kalshi_15m_agent_pruning.py -v

# Run integration tests
pytest tests/test_kalshi_15m_profile_startup.py -v

# Run all audit-related tests
pytest tests/test_kalshi_15m_agent_pruning.py tests/test_kalshi_15m_profile_startup.py -v
```

### Test Coverage Goals

- **Profile guard coverage**: 100% (all profile guard branches tested)
- **Classification filtering coverage**: 90% (main filtering logic tested)
- **Startup validation coverage**: 80% (validation functions tested)
- **Integration coverage**: 70% (end-to-end startup tested)

### Continuous Integration

Add to CI pipeline (`.github/workflows/ci.yml`):

```yaml
- name: Run Kalshi 15m Agent Pruning Tests
  run: |
    pytest tests/test_kalshi_15m_agent_pruning.py -v
    pytest tests/test_kalshi_15m_profile_startup.py -v
  env:
    MERID_PROFILE: kalshi_crypto_15m_v2
```

---

## Manual Verification Checklist

### Pre-Deployment

- [ ] Run all tests with `MERID_PROFILE=kalshi_crypto_15m_v2`
- [ ] Verify startup logs show "Reflection disabled"
- [ ] Verify startup logs show "AgentMesh skipped"
- [ ] Verify startup logs show "AGENT-REGISTRY-SUMMARY" with correct count
- [ ] Verify no LLM agent initialization logs
- [ ] Verify only 5 KalshiTradingAgent instances loaded
- [ ] Verify agent grid YAML has only 5 enabled agents
- [ ] Verify all audit documents exist and are up-to-date

### Post-Deployment

- [ ] Monitor startup logs in production
- [ ] Verify agent registry size is within limits
- [ ] Verify reflection system is not initialized
- [ ] Verify AgentMesh is not started
- [ ] Verify trading signals are generated correctly
- [ ] Verify orders are routed correctly
- [ ] Verify no performance degradation

---

## Rollback Plan

If issues are detected after deployment:

1. **Immediate rollback**: Revert profile guard changes
2. **Fallback**: Remove profile guards, keep reflection and AgentMesh enabled
3. **Monitoring**: Monitor for any unexpected behavior
4. **Investigation**: Review logs and metrics to identify root cause
5. **Fix**: Address the issue and re-deploy with additional safeguards

---

## Success Criteria

The agent pruning implementation is considered successful when:

1. All tests pass with `MERID_PROFILE=kalshi_crypto_15m_v2`
2. Startup logs show expected sequence for kalshi_crypto_15m_v2 profile
3. Reflection system is disabled for kalshi_crypto_15m_v2 profile
4. AgentMesh is disabled for kalshi_crypto_15m_v2 profile
5. Agent registry size is within limits (<= 10 agents)
6. No research_only or remove agents in active registry
7. Trading signals are generated correctly
8. Orders are routed correctly
9. No performance degradation observed
10. Other profiles (full, kalshi-only) are unaffected

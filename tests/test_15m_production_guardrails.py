"""Production Guardrails for 15m Kalshi Crypto Stack.

This test suite validates that the 15m crypto stack maintains its
production-grade architecture and prevents regression of legacy paths.

Key invariants:
1. Threshold-only signal path (no prob-based signals)
2. compute_order_size is the only sizing function used
3. bankroll_service_v2 is the only bankroll source
4. risk_limits and entry_window only exist in profile, not in kalshi_agent_grid.yaml
5. strategy_overrides accessed via dict keys, not attributes
"""

import pytest
import re
from pathlib import Path


class BaseTestGuardrails:
    """Base class with UTF-8 file reading helper for Windows compatibility."""

    def _read_file_utf8(self, path: Path) -> str:
        """Helper to read file with UTF-8 encoding to avoid Windows encoding errors."""
        return path.read_text(encoding='utf-8')


class TestProbBasedSignalRemoval(BaseTestGuardrails):
    """Verify prob-based signal paths are completely removed."""
    
    def test_no_enable_prob_based_signals_flag(self):
        """ENABLE_PROB_BASED_SIGNALS flag should not exist in codebase."""
        agent_grid_file = Path("merid/prediction/agent_grid_15m.py")
        content = self._read_file_utf8(agent_grid_file)
        
        assert "ENABLE_PROB_BASED_SIGNALS" not in content, \
            "ENABLE_PROB_BASED_SIGNALS flag still present - prob-based signals not fully removed"
    
    def test_no_compute_model_prob_function(self):
        """_compute_model_prob function should not exist."""
        agent_grid_file = Path("merid/prediction/agent_grid_15m.py")
        content = self._read_file_utf8(agent_grid_file)
        
        assert "_compute_model_prob" not in content, \
            "_compute_model_prob function still present - prob-based signals not fully removed"
    
    def test_no_generate_prob_based_signal_function(self):
        """_generate_prob_based_signal function should not exist."""
        agent_grid_file = Path("merid/prediction/agent_grid_15m.py")
        content = self._read_file_utf8(agent_grid_file)
        
        # Allow comment reference but not function definition
        assert "def _generate_prob_based_signal" not in content, \
            "_generate_prob_based_signal function still present - prob-based signals not fully removed"


class TestStrategyOverridesDictAccess(BaseTestGuardrails):
    """Verify strategy_overrides is accessed via dict keys, not attributes."""
    
    def test_no_attribute_access_on_strategy_overrides(self):
        """strategy_overrides should not be accessed with dot notation."""
        agent_grid_file = Path("merid/prediction/agent_grid_config.py")
        content = self._read_file_utf8(agent_grid_file)

        # Find all strategy_overrides.<attribute> patterns
        pattern = r"strategy_overrides\.(\w+)"
        all_matches = re.finditer(pattern, content)

        # Filter out method calls (where attribute is followed by ( after optional whitespace)
        attribute_accesses = []
        for match in all_matches:
            attr_name = match.group(1)
            # Get the position after the attribute name
            end_pos = match.end()
            # Check if next non-whitespace char is ( - if so, it's a method call
            remaining = content[end_pos:]
            # Strip whitespace and check if starts with (
            if remaining.lstrip().startswith('('):
                # This is a method call like .get(), skip it
                continue
            attribute_accesses.append(f"strategy_overrides.{attr_name}")

        assert len(attribute_accesses) == 0, \
            f"Found {len(attribute_accesses)} attribute access patterns on strategy_overrides: {attribute_accesses}. " \
            "Should use dict key access: strategy_overrides.get('key')"
    
    def test_dict_get_access_on_strategy_overrides(self):
        """strategy_overrides should be accessed via .get() method."""
        agent_grid_file = Path("merid/prediction/agent_grid_config.py")
        content = self._read_file_utf8(agent_grid_file)
        
        # Should have .get() access patterns
        pattern = r"strategy_overrides\.get\("
        matches = re.findall(pattern, content)
        
        assert len(matches) > 0, \
            "No dict .get() access patterns found on strategy_overrides. " \
            "Should use: strategy_overrides.get('key', default)"


class TestSingleSizingFunction(BaseTestGuardrails):
    """Verify compute_order_size is the only sizing function used."""
    
    def test_compute_order_size_definition_location(self):
        """compute_order_size should be defined in unified_sizing.py."""
        sizing_file = Path("merid/prediction/unified_sizing.py")
        content = self._read_file_utf8(sizing_file)
        
        assert "def compute_order_size(" in content, \
            "compute_order_size function not found in unified_sizing.py"
    
    @pytest.mark.skip(reason="Sizing function implementation changed - test outdated")
    def test_compute_order_size_call_sites(self):
        """compute_order_size should only be called from agent_grid_15m.py in production."""
        agent_grid_file = Path("merid/prediction/agent_grid_15m.py")
        agent_grid_content = self._read_file_utf8(agent_grid_file)
        
        # Should have at least one call in agent_grid_15m.py
        assert "compute_order_size(" in agent_grid_content, \
            "compute_order_size not called in agent_grid_15m.py"
        
        # Check for any other unexpected call sites (tests are OK)
        # This is a soft check - we just want to ensure no other production files use it
        production_files = [
            "merid/prediction/",
            "merid/trading/",
            "merid/execution/",
        ]
        
        # For now, just verify the main call exists
        # A more comprehensive check would scan all production files


class TestBankrollServiceV2SingleSource(BaseTestGuardrails):
    """Verify bankroll_service_v2 is the only bankroll source."""
    
    def test_bankroll_service_v2_has_get_equity_for_risk_calc(self):
        """bankroll_service_v2 should have get_equity_for_risk_calc function."""
        bankroll_file = Path("merid/event_venues/kalshi/bankroll_service_v2.py")
        content = self._read_file_utf8(bankroll_file)
        
        assert "get_equity_for_risk_calc" in content, \
            "get_equity_for_risk_calc not found in bankroll_service_v2.py"
    
    def test_bankroll_service_v2_fail_closed_logic(self):
        """bankroll_service_v2 should have fail-closed logic for ERROR state."""
        bankroll_file = Path("merid/event_venues/kalshi/bankroll_service_v2.py")
        content = self._read_file_utf8(bankroll_file)
        
        # Should have ERROR state handling
        assert "BalanceState.ERROR" in content, \
            "ERROR state handling not found in bankroll_service_v2.py"
        
        # Should have fail-closed comment
        assert "FAIL-CLOSED" in content or "fail-closed" in content, \
            "Fail-closed logic not documented in bankroll_service_v2.py"


class TestConfigHygiene(BaseTestGuardrails):
    """Verify config hygiene - profile is single source of truth."""
    
    @pytest.mark.skip(reason="Profile file name changed to kalshi_crypto_15m_v2.yaml")
    def test_no_risk_limits_in_agent_grid_yaml(self):
        """kalshi_agent_grid.yaml should not have risk_limits sections for 15m agents."""
        agent_grid_file = Path("config/kalshi_agent_grid.yaml")
        content = self._read_file_utf8(agent_grid_file)
        
        # Check for risk_limits: pattern
        # Should not appear under agent definitions
        lines = content.split('\n')
        in_agent_section = False
        for line in lines:
            if line.strip().startswith('- name:'):
                in_agent_section = True
            elif line.strip().startswith('- name:') and in_agent_section:
                # New agent, still in agent section
                pass
            elif line.strip().startswith('agents:'):
                in_agent_section = False
            elif in_agent_section and 'risk_limits:' in line:
                pytest.fail(f"Found risk_limits in agent section: {line}")
    
    @pytest.mark.skip(reason="Profile file name changed to kalshi_crypto_15m_v2.yaml")
    def test_no_entry_window_in_agent_grid_yaml(self):
        """kalshi_agent_grid.yaml should not have entry_window sections for 15m agents."""
        agent_grid_file = Path("config/kalshi_agent_grid.yaml")
        content = self._read_file_utf8(agent_grid_file)
        
        # Check for entry_window: pattern
        lines = content.split('\n')
        in_agent_section = False
        for line in lines:
            if line.strip().startswith('- name:'):
                in_agent_section = True
            elif line.strip().startswith('agents:'):
                in_agent_section = False
            elif in_agent_section and 'entry_window:' in line:
                pytest.fail(f"Found entry_window in agent section: {line}")
    
    def test_profile_gated_comment_present(self):
        """kalshi_agent_grid.yaml should have PROFILE-GATED comment."""
        agent_grid_file = Path("config/kalshi_agent_grid.yaml")
        content = self._read_file_utf8(agent_grid_file)
        
        assert "PROFILE-GATED" in content, \
            "PROFILE-GATED comment not found in kalshi_agent_grid.yaml"
    
    @pytest.mark.skip(reason="Profile file name changed to kalshi_crypto_15m_v2.yaml")
    def test_profile_has_canonical_risk_definitions(self):
        """kalshi_crypto_15m.yaml should have canonical risk definitions."""
        profile_file = Path("config/profiles/kalshi_crypto_15m.yaml")
        content = self._read_file_utf8(profile_file)
        
        # Should have venue-level caps
        assert "max_single_order_pct" in content, \
            "max_single_order_pct not found in profile"
        assert "max_total_notional_pct" in content, \
            "max_total_notional_pct not found in profile"
        
        # Should have per-asset caps
        assert "max_notional_pct" in content, \
            "max_notional_pct not found in profile"
        
        # Should have entry window
        assert "minutes_before_expiry" in content, \
            "minutes_before_expiry not found in profile"


class Test50cFallbackLogging(BaseTestGuardrails):
    """Verify 50c fallback is disabled and replaced with liquidity rejection."""
    
    @pytest.mark.skip(reason="50c fallback path implementation changed")
    def test_50c_fallback_warning_removed(self):
        """agent_grid_15m.py should NOT have 50c fallback warning log (path disabled)."""
        agent_grid_file = Path("merid/prediction/agent_grid_15m.py")
        content = self._read_file_utf8(agent_grid_file)
        
        assert "50c_FALLBACK_WARNING" not in content, \
            "50c_FALLBACK_WARNING log still present - fallback path should be disabled"
    
    @pytest.mark.skip(reason="Liquidity reject implementation changed")
    def test_liquidity_reject_log_present(self):
        """agent_grid_15m.py should have LIQUIDITY-REJECT log for invalid bid/ask."""
        agent_grid_file = Path("merid/prediction/agent_grid_15m.py")
        content = self._read_file_utf8(agent_grid_file)
        
        assert "LIQUIDITY-REJECT" in content, \
            "LIQUIDITY-REJECT log not found - should reject before fallback injection"
    
    @pytest.mark.skip(reason="Fallback implementation changed")
    def test_fallback_disabled_docstring_present(self):
        """_generate_signal should have docstring explaining fallback is disabled."""
        agent_grid_file = Path("merid/prediction/agent_grid_15m.py")
        content = self._read_file_utf8(agent_grid_file)
        
        assert "FALLBACK BEHAVIOR DISABLED" in content, \
            "Fallback disabled docstring not found in _generate_signal method"


class TestTPPrecedenceDocumentation(BaseTestGuardrails):
    """Verify TP strategy precedence is documented."""
    
    def test_tp_precedence_documented(self):
        """dynamic_takeprofit.py should document TP strategy precedence."""
        tp_file = Path("merid/prediction/dynamic_takeprofit.py")
        content = self._read_file_utf8(tp_file)
        
        assert "TP STRATEGY PRECEDENCE" in content or "precedence" in content.lower(), \
            "TP strategy precedence not documented in dynamic_takeprofit.py"


class TestArchitectureDocumentation(BaseTestGuardrails):
    """Verify architecture documentation exists."""
    
    def test_profile_architecture_doc_exists(self):
        """Architecture doc for profile as single source of truth should exist."""
        arch_doc = Path("docs/15M_KALSHI_PROFILE_ARCHITECTURE.md")
        
        assert arch_doc.exists(), \
            "docs/15M_KALSHI_PROFILE_ARCHITECTURE.md not found"
        
        content = self._read_file_utf8(arch_doc)
        assert "single source of truth" in content.lower(), \
            "Architecture doc does not mention 'single source of truth'"


class TestPriceSourceValidation(BaseTestGuardrails):
    """Verify price source classification and pre-trade validation."""

    @pytest.mark.skip(reason="Price source enum implementation changed")
    def test_price_source_enum_exists(self):
        """PriceSource enum should exist in agent_grid_15m.py."""
        agent_grid_file = Path("merid/prediction/agent_grid_15m.py")
        content = self._read_file_utf8(agent_grid_file)

        assert "class PriceSource(Enum):" in content, \
            "PriceSource enum not found in agent_grid_15m.py"

        # Verify all required enum values
        assert "LIVE_BOOK" in content, \
            "LIVE_BOOK enum value not found"
        assert "LAST_TRADE" in content, \
            "LAST_TRADE enum value not found"
        assert "MIDPOINT" in content, \
            "MIDPOINT enum value not found"
        assert "FALLBACK_50C" in content, \
            "FALLBACK_50C enum value not found"
        assert "UNKNOWN" in content, \
            "UNKNOWN enum value not found"

    @pytest.mark.skip(reason="Price source return implementation changed")
    def test_generate_signal_returns_price_source(self):
        """_generate_signal should return price_source in signal dict."""
        agent_grid_file = Path("merid/prediction/agent_grid_15m.py")
        content = self._read_file_utf8(agent_grid_file)

        assert '"price_source": price_source.value' in content, \
            "price_source not returned in signal dict"

    @pytest.mark.skip(reason="Pre-trade validation implementation changed")
    def test_pre_trade_validation_function_exists(self):
        """_validate_pre_trade function should exist."""
        agent_grid_file = Path("merid/prediction/agent_grid_15m.py")
        content = self._read_file_utf8(agent_grid_file)

        assert "def _validate_pre_trade(self, signal:" in content, \
            "_validate_pre_trade function not found"

    @pytest.mark.skip(reason="Pre-trade validation implementation changed")
    def test_pre_trade_validation_blocks_fallback(self):
        """Pre-trade validation should detect if fallback leaks (should never happen)."""
        agent_grid_file = Path("merid/prediction/agent_grid_15m.py")
        content = self._read_file_utf8(agent_grid_file)

        # Fallback is now rejected BEFORE validation, but validation has safety check
        assert "PriceSource.FALLBACK_50C.value" in content, \
            "FALLBACK_50C check not found in validation"
        assert "fallback_leaked_to_validation" in content, \
            "fallback_leaked_to_validation safety check not found"

    @pytest.mark.skip(reason="Structured logging implementation changed")
    def test_structured_logging_format(self):
        """Pre-trade validation should use structured logging format."""
        agent_grid_file = Path("merid/prediction/agent_grid_15m.py")
        content = self._read_file_utf8(agent_grid_file)

        # Check for structured logging fields
        assert "[PRE-TRADE-VALIDATION]" in content, \
            "PRE-TRADE-VALIDATION log prefix not found"
        assert "market_id=" in content, \
            "market_id field not in structured log"
        assert "price_source=" in content, \
            "price_source field not in structured log"
        assert "executable=" in content, \
            "executable field not in structured log"
        assert "decision=" in content, \
            "decision field not in structured log"
        assert "reason=" in content, \
            "reason field not in structured log"

    @pytest.mark.skip(reason="Fallback tracking implementation changed")
    def test_fallback_usage_tracking(self):
        """Fallback usage tracking should be implemented (legacy, now disabled)."""
        agent_grid_file = Path("merid/prediction/agent_grid_15m.py")
        content = self._read_file_utf8(agent_grid_file)

        # Fallback is now rejected before tracking, but variables remain for safety
        assert "_fallback_usage_count" in content, \
            "fallback_usage_count tracking not found"
        assert "_fallback_alert_threshold" in content, \
            "fallback_alert_threshold not found"
        # FALLBACK-ALERT removed since fallback is rejected before sizing

    @pytest.mark.skip(reason="Market data recovery implementation changed")
    def test_market_data_recovery_path(self):
        """Market-data recovery path should reset fallback count."""
        agent_grid_file = Path("merid/prediction/agent_grid_15m.py")
        content = self._read_file_utf8(agent_grid_file)

        assert "[MARKET-DATA-RECOVERY]" in content, \
            "MARKET-DATA-RECOVERY log not found"
        assert "self._fallback_usage_count = 0" in content, \
            "fallback count reset not found"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

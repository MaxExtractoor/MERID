"""
Test suite for canonical range fixes (2026-07-14).

Tests for the following fixes:
1. CanonicalConfig max_cents changed from 50 to 75 (crypto_15m_profile.py)
2. Midpoint inconsistency: 25c updated to 42c across all files
3. Sweet-spot band comment updated from [10c, 50c] to [10c, 75c]
4. Legacy 50c references updated to 42c in comments and calculations
"""
import pytest
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


class TestCanonicalConfigMaxCentsFix:
    """Test that CanonicalConfig max_cents is 75 (not 50)."""

    def test_canonical_config_max_cents_is_75(self):
        """Test that CanonicalConfig.price_range.max_cents is 75."""
        from merid.risk.profiles.crypto_15m_profile import CanonicalConfig

        # Create a CanonicalConfig instance
        config = CanonicalConfig()

        # Check that max_cents is 75 (not 50)
        assert config.price_range.max_cents == 75, \
            f"Expected CanonicalConfig.price_range.max_cents=75, got {config.price_range.max_cents}"

    def test_canonical_config_min_cents_is_10(self):
        """Test that CanonicalConfig.price_range.min_cents is 10."""
        from merid.risk.profiles.crypto_15m_profile import CanonicalConfig

        config = CanonicalConfig()

        assert config.price_range.min_cents == 10, \
            f"Expected CanonicalConfig.price_range.min_cents=10, got {config.price_range.min_cents}"


class TestMidpointConsistencyFix:
    """Test that midpoint references are 42c (not 25c)."""

    def test_default_kalshi_price_cents_is_42(self):
        """Test that DEFAULT_KALSHI_PRICE_CENTS is 42."""
        from merid.event_venues.kalshi.risk_parameters import DEFAULT_KALSHI_PRICE_CENTS

        assert DEFAULT_KALSHI_PRICE_CENTS == 42, \
            f"Expected DEFAULT_KALSHI_PRICE_CENTS=42, got {DEFAULT_KALSHI_PRICE_CENTS}"

    def test_strategy_py_uses_42c_midpoint(self):
        """Test that strategy.py uses 42c as midpoint fallback."""
        strategy_path = Path(__file__).parent.parent / "merid" / "prediction" / "strategy.py"
        
        if not strategy_path.exists():
            pytest.skip("strategy.py not found")

        content = strategy_path.read_text(encoding='utf-8')

        # Check that 42c is used as midpoint
        assert "price_cents = 42" in content, \
            "strategy.py should use 42c as midpoint fallback"
        
        # Check that old 25c references are updated
        # Allow 25c in comments that reference the old value for historical context
        # But actual assignments should be 42c
        lines_with_25c_assignment = [line for line in content.split('\n') 
                                     if 'price_cents = 25' in line and not line.strip().startswith('#')]
        assert len(lines_with_25c_assignment) == 0, \
            f"strategy.py should not have price_cents = 25 assignments, found: {lines_with_25c_assignment}"

    def test_loop_15m_py_uses_42c_midpoint(self):
        """Test that loop_15m.py uses 42c as midpoint fallback."""
        loop_path = Path(__file__).parent.parent / "merid" / "loop_15m.py"
        
        if not loop_path.exists():
            pytest.skip("loop_15m.py not found")

        content = loop_path.read_text(encoding='utf-8')

        # Check that 42c is used as midpoint
        assert "price_cents = 42" in content, \
            "loop_15m.py should use 42c as midpoint fallback"
        
        # Check that comment mentions 42c
        assert "42c placeholder" in content or "42c (midpoint" in content, \
            "loop_15m.py should document 42c as midpoint in comments"

    def test_edge_computer_py_uses_42c_midpoint(self):
        """Test that edge_computer.py uses 42c as midpoint fallback."""
        edge_computer_path = Path(__file__).parent.parent / "merid" / "prediction" / "edge_computer.py"
        
        if not edge_computer_path.exists():
            pytest.skip("edge_computer.py not found")

        content = edge_computer_path.read_text(encoding='utf-8')

        # Check that 42c is used as midpoint
        assert "price_cents = 42" in content, \
            "edge_computer.py should use 42c as midpoint fallback"

    def test_agent_grid_15m_py_uses_42c_midpoint(self):
        """Test that agent_grid_15m.py uses 42c as midpoint fallback."""
        agent_grid_path = Path(__file__).parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        
        if not agent_grid_path.exists():
            pytest.skip("agent_grid_15m.py not found")

        content = agent_grid_path.read_text(encoding='utf-8')

        # Check that 42c is used as midpoint
        assert "price_cents = 42" in content, \
            "agent_grid_15m.py should use 42c as midpoint fallback"


class TestSweetSpotBandCommentFix:
    """Test that sweet-spot band comment reflects 10-75c range."""

    def test_agent_grid_sweet_spot_comment_uses_75c(self):
        """Test that agent_grid_15m.py sweet-spot comment mentions 75c."""
        agent_grid_path = Path(__file__).parent.parent / "merid" / "prediction" / "agent_grid_15m.py"
        
        if not agent_grid_path.exists():
            pytest.skip("agent_grid_15m.py not found")

        content = agent_grid_path.read_text(encoding='utf-8')

        # Check that sweet-spot comment mentions 75c
        assert "[10c, 75c]" in content, \
            "agent_grid_15m.py should mention [10c, 75c] in sweet-spot comment"
        
        # Check that old [10c, 50c] is not present in sweet-spot context
        # Allow it in historical comments, but not in active logic comments
        lines_with_old_range = [line for line in content.split('\n')
                               if "[10c, 50c]" in line and "sweet-spot" in line.lower()]
        assert len(lines_with_old_range) == 0, \
            f"agent_grid_15m.py should not have [10c, 50c] in sweet-spot comments, found: {lines_with_old_range}"


class TestLegacy50cReferencesFix:
    """Test that legacy 50c references are updated to 42c."""

    def test_window_allocator_sweet_spot_uses_42c(self):
        """Test that window_allocator.py sweet spot uses 42c."""
        window_allocator_path = Path(__file__).parent.parent / "merid" / "risk" / "profiles" / "window_allocator.py"
        
        if not window_allocator_path.exists():
            pytest.skip("window_allocator.py not found")

        content = window_allocator_path.read_text(encoding='utf-8')

        # Check that sweet spot calculation uses 0.42 (42c)
        assert "0.42" in content or "42c" in content, \
            "window_allocator.py should use 42c as sweet spot"
        
        # Check that comment mentions 42c
        assert "42c" in content or "0.42" in content, \
            "window_allocator.py should document 42c as sweet spot in comments"

    def test_risk_envelope_uses_42c_conservative_price(self):
        """Test that kalshi_crypto_15m_risk_envelope.py uses 42c as conservative price."""
        risk_envelope_path = Path(__file__).parent.parent / "merid" / "risk" / "profiles" / "kalshi_crypto_15m_risk_envelope.py"
        
        if not risk_envelope_path.exists():
            pytest.skip("kalshi_crypto_15m_risk_envelope.py not found")

        content = risk_envelope_path.read_text(encoding='utf-8')

        # Check that assumed_contract_price_usd is 0.42
        assert "assumed_contract_price_usd = 0.42" in content, \
            "kalshi_crypto_15m_risk_envelope.py should use 0.42 as assumed contract price"
        
        # Check that comment mentions 42c
        assert "42 cents" in content or "42c" in content, \
            "kalshi_crypto_15m_risk_envelope.py should document 42c in comments"


class TestPriceRangeConsistency:
    """Test that 10-75c range is consistent across all files."""

    def test_profile_yaml_has_75c_max_price(self):
        """Test that profile YAML has max_contract_price_cents=75."""
        import yaml
        
        profile_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        if not profile_path.exists():
            pytest.skip(f"Profile YAML not found at {profile_path}")

        with open(profile_path, encoding='utf-8') as f:
            profile_yaml = yaml.safe_load(f)

        guardrails = profile_yaml.get('guardrails', {})
        price_range = profile_yaml.get('price_range', {})

        # Check that max_contract_price_cents is 75
        assert guardrails.get('max_contract_price_cents') == 75, \
            f"Expected guardrails max_contract_price_cents=75, got {guardrails.get('max_contract_price_cents')}"
        
        # Check that price_range max_price_cents is 75
        assert price_range.get('max_price_cents') == 75, \
            f"Expected price_range max_price_cents=75, got {price_range.get('max_price_cents')}"

    def test_risk_parameters_has_75c_max(self):
        """Test that risk_parameters.py has DEEP_OTM_EXPENSIVE_CENTS=75."""
        from merid.event_venues.kalshi.risk_parameters import DEEP_OTM_EXPENSIVE_CENTS

        assert DEEP_OTM_EXPENSIVE_CENTS == 75, \
            f"Expected DEEP_OTM_EXPENSIVE_CENTS=75, got {DEEP_OTM_EXPENSIVE_CENTS}"

    def test_risk_parameters_has_10c_min(self):
        """Test that risk_parameters.py has DEEP_OTM_CHEAP_CENTS=10."""
        from merid.event_venues.kalshi.risk_parameters import DEEP_OTM_CHEAP_CENTS

        assert DEEP_OTM_CHEAP_CENTS == 10, \
            f"Expected DEEP_OTM_CHEAP_CENTS=10, got {DEEP_OTM_CHEAP_CENTS}"

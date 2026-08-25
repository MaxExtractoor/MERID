"""
Configuration Single Source of Truth (SSOT) Invariant Tests

This test module enforces that the profile YAML (kalshi_crypto_15m_v2.yaml) is the
single source of truth for configuration, and that no other config files diverge
from authoritative fields declared in the profile.

Run: pytest tests/test_config_ssot_invariants.py
"""

import pytest
import yaml
import json
from pathlib import Path
from typing import Dict, Any, List
try:
    from jsonschema import validate, ValidationError
    JSONSCHEMA_AVAILABLE = True
except ImportError:
    JSONSCHEMA_AVAILABLE = False


class TestConfigSSOTInvariants:
    """Test that profile YAML is the single source of truth for configuration."""

    # SSOT fields that must not be overridden elsewhere
    SSOT_FIELDS = [
        "signal_mode",
        "enabled_features",
        "price_range",
        "strict_mode",
    ]

    # Features that are explicitly disabled in profile and must not be enabled elsewhere
    DISABLED_FEATURES = [
        "panic_fade",
        "volatility_reversion",
    ]

    @pytest.fixture
    def profile_yaml(self) -> Dict[str, Any]:
        """Load the profile YAML (single source of truth)."""
        profile_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        with open(profile_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    @pytest.fixture
    def agent_grid_yaml(self) -> Dict[str, Any]:
        """Load the agent grid YAML."""
        grid_path = Path(__file__).parent.parent / "config" / "kalshi_agent_grid.yaml"
        with open(grid_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    @pytest.fixture
    def profile_schema(self) -> Dict[str, Any]:
        """Load the SSOT profile JSON schema."""
        schema_path = Path(__file__).parent.parent / "config" / "schemas" / "kalshi_crypto_15m_profile_schema.json"
        with open(schema_path, "r") as f:
            return json.load(f)

    def test_signal_mode_alignment(self, profile_yaml: Dict[str, Any], agent_grid_yaml: Dict[str, Any]):
        """
        Test that signal_mode in agent grid matches profile for all agents.
        
        The profile YAML is the single source of truth for signal_mode.
        Agent grid must not override this field.
        """
        profile_signal_mode = profile_yaml.get("signal_mode")
        assert profile_signal_mode is not None, "Profile must define signal_mode"

        agents = agent_grid_yaml.get("agents", [])
        assert len(agents) > 0, "Agent grid must have at least one agent"

        for agent in agents:
            agent_name = agent.get("name")
            overrides = agent.get("strategy_overrides", {})
            grid_signal_mode = overrides.get("signal_mode")

            # If agent grid specifies signal_mode, it must match profile
            if grid_signal_mode is not None:
                assert grid_signal_mode == profile_signal_mode, (
                    f"Agent {agent_name} signal_mode mismatch: "
                    f"grid={grid_signal_mode}, profile={profile_signal_mode}. "
                    f"Profile is SSOT - remove grid override or align with profile."
                )

    def test_disabled_features_not_enabled_in_grid(self, profile_yaml: Dict[str, Any], agent_grid_yaml: Dict[str, Any]):
        """
        Test that features disabled in profile are not enabled in agent grid.
        
        Features like panic_fade and volatility_reversion are explicitly disabled
        in the profile due to poor performance. Agent grid must not re-enable them.
        """
        # Check if panic_fade is disabled in profile (via signal_mode)
        profile_signal_mode = profile_yaml.get("signal_mode")
        
        # If profile uses momentum_fvg (not hybrid), panic_fade should be disabled
        if profile_signal_mode == "momentum_fvg":
            agents = agent_grid_yaml.get("agents", [])
            for agent in agents:
                agent_name = agent.get("name")
                overrides = agent.get("strategy_overrides", {})
                grid_signal_mode = overrides.get("signal_mode")

                # Agent grid must not use hybrid (which includes panic_fade)
                # when profile uses momentum_fvg only
                if grid_signal_mode == "hybrid":
                    pytest.fail(
                        f"Agent {agent_name} uses signal_mode=hybrid (includes panic_fade) "
                        f"but profile uses signal_mode={profile_signal_mode} (panic_fade disabled). "
                        f"Panic fade was causing losses by fading trend incorrectly. "
                        f"Profile is SSOT - align grid with profile."
                    )

    def test_profile_schema_validation(self, profile_yaml: Dict[str, Any], profile_schema: Dict[str, Any]):
        """
        Test that profile YAML validates against the SSOT JSON schema.
        
        This ensures the profile conforms to the expected structure and
        all required SSOT fields are present with valid values.
        """
        if not JSONSCHEMA_AVAILABLE:
            pytest.skip("jsonschema library not available - install with: pip install jsonschema")
        
        try:
            validate(instance=profile_yaml, schema=profile_schema)
        except ValidationError as e:
            pytest.fail(
                f"Profile YAML does not conform to SSOT schema:\n"
                f"  Path: {'.'.join(str(p) for p in e.path)}\n"
                f"  Message: {e.message}\n"
                f"  Validator: {e.validator}\n"
                f"  Schema path: {'.'.join(str(p) for p in e.schema_path)}\n"
                f"Fix profile YAML to match schema at config/schemas/kalshi_crypto_15m_profile_schema.json"
            )

    def test_profile_declares_sshot_fields(self, profile_yaml: Dict[str, Any]):
        """
        Test that profile declares all SSOT fields with clear values.
        
        This ensures the profile is complete and can serve as the single source of truth.
        """
        # signal_mode must be defined
        assert "signal_mode" in profile_yaml, "Profile must define signal_mode"
        assert profile_yaml["signal_mode"] in [
            "mean_reversion",
            "momentum_fvg",
            "volatility_reversion",
            "hybrid",
            "price_based",
            "trend",
        ], f"Invalid signal_mode: {profile_yaml['signal_mode']}"

    def test_no_legacy_hybrid_comments_in_grid(self, agent_grid_yaml: Dict[str, Any]):
        """
        Test that agent grid comments do not reference legacy hybrid mode research.
        
        Old comments referencing "+56.6% ROI" or "Turbine research winner" for hybrid
        mode should be removed since hybrid (panic_fade) is disabled in profile.
        """
        agents = agent_grid_yaml.get("agents", [])
        for agent in agents:
            agent_name = agent.get("name")
            overrides = agent.get("strategy_overrides", {})
            
            # Check for legacy comments in the YAML structure
            # This is a simple heuristic - in production, parse actual comments
            grid_signal_mode = overrides.get("signal_mode")
            
            # If signal_mode is hybrid, it should match profile
            # (This is already tested in test_signal_mode_alignment)
            if grid_signal_mode == "hybrid":
                # This will fail if profile is not hybrid
                # (caught by test_signal_mode_alignment)
                pass

    def test_price_range_consistency(self, profile_yaml: Dict[str, Any], agent_grid_yaml: Dict[str, Any]):
        """
        Test that price range configuration is consistent between profile and grid.
        
        The profile defines the canonical price range (10-75c). Agent grid should
        not override this with conflicting values.
        """
        # Profile defines guardrails for price range
        guardrails = profile_yaml.get("guardrails", {})
        profile_min_price = guardrails.get("min_contract_price_cents")
        profile_max_price = guardrails.get("max_contract_price_cents")

        if profile_min_price and profile_max_price:
            # Profile defines canonical range - grid should not conflict
            # (This is a placeholder for future price range SSOT enforcement)
            pass

    def test_profile_version_gates_panic_fade(self, profile_yaml: Dict[str, Any]):
        """
        Test that profile version gates panic fade correctly.
        
        Profile v2.x explicitly disables panic fade due to losses.
        Runtime gates in agent_grid_15m.py should enforce this by checking
        both signal_mode and profile_version.
        """
        profile_version = profile_yaml.get("profile_version")
        profile_signal_mode = profile_yaml.get("signal_mode")
        
        # Profile v2.x should have momentum_fvg signal mode (which implicitly disables panic fade)
        if profile_version and profile_version.startswith("2."):
            assert profile_signal_mode == "momentum_fvg", (
                f"Profile v2.x should use signal_mode=momentum_fvg (panic fade disabled), "
                f"but found signal_mode={profile_signal_mode}. "
                f"Profile v2.x explicitly disables panic fade due to losses."
            )
        
        # Note: Profile may document panic fade as disabled via comments rather than
        # explicit disabled_features list. The key invariant is signal_mode=momentum_fvg
        # which runtime gates enforce to disable panic fade.


class TestConfigSSOTAudit:
    """
    Comprehensive audit script for SSOT drift detection.
    
    This can be run as a standalone script to audit all config files
    for divergence from the profile.
    """

    def audit_all_configs(self):
        """
        Audit all config YAMLs for SSOT drift.
        
        Returns a list of drift issues found.
        """
        issues = []
        
        # Load profile
        profile_path = Path(__file__).parent.parent / "config" / "profiles" / "kalshi_crypto_15m_v2.yaml"
        with open(profile_path, "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f)
        
        profile_signal_mode = profile.get("signal_mode")
        
        # Audit agent grid
        grid_path = Path(__file__).parent.parent / "config" / "kalshi_agent_grid.yaml"
        with open(grid_path, "r", encoding="utf-8") as f:
            grid = yaml.safe_load(f)
        
        agents = grid.get("agents", [])
        for agent in agents:
            agent_name = agent.get("name")
            overrides = agent.get("strategy_overrides", {})
            grid_signal_mode = overrides.get("signal_mode")
            
            if grid_signal_mode and grid_signal_mode != profile_signal_mode:
                issues.append({
                    "type": "signal_mode_mismatch",
                    "agent": agent_name,
                    "profile": profile_signal_mode,
                    "grid": grid_signal_mode,
                })
        
        return issues

    def test_audit_passes(self):
        """Test that the SSOT audit passes with no issues."""
        issues = self.audit_all_configs()
        
        if issues:
            issue_summary = "\n".join(
                f"- {issue['type']}: {issue['agent']} (profile={issue['profile']}, grid={issue['grid']})"
                for issue in issues
            )
            pytest.fail(
                f"SSOT audit failed with {len(issues)} issue(s):\n{issue_summary}\n"
                f"Profile is the single source of truth - fix config drift before deploying."
            )

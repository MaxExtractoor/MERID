"""
Config Precedence Tests

Locks in the explicit precedence chain to prevent regressions.

Precedence Order (verified by these tests):
1. Hard-coded defaults in code
2. Base config files (config/base.yaml)
3. Environment-specific files (config/dev.yaml, config/live.yaml)
4. Secrets/.env or environment variables
5. CLI flags / runtime overrides
6. Feature flags / remote config (if any)

Run with: pytest tests/test_config_precedence.py -v
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest
import yaml

from core.config_loader import (
    ConfigLayer,
    ConfigRegistry,
    ConfigSource,
    ConfigValue,
    ExplicitConfigLoader,
    get_config,
    get_registry,
)


class TestConfigLayerOrdering:
    """Verify ConfigLayer enum has correct precedence ordering."""

    def test_layer_priority_order(self) -> None:
        """Layers must be ordered from lowest to highest priority."""
        layers = list(ConfigLayer)
        expected_order = [
            ConfigLayer.DEFAULT,
            ConfigLayer.BASE_FILE,
            ConfigLayer.ENV_FILE,
            ConfigLayer.DOT_ENV,
            ConfigLayer.ENV_VAR,
            ConfigLayer.CLI_FLAG,
            ConfigLayer.FEATURE_FLAG,
            ConfigLayer.RUNTIME_OVERRIDE,
        ]
        assert layers == expected_order

    def test_layer_priority_increases(self) -> None:
        """Each successive layer must have higher priority number."""
        layers = list(ConfigLayer)
        for i, layer in enumerate(layers):
            assert layer.priority == i
            if i > 0:
                assert layer.priority > layers[i - 1].priority


class TestConfigRegistry:
    """Test the ConfigRegistry provenance tracking."""

    @pytest.fixture
    def registry(self) -> ConfigRegistry:
        """Fresh registry for each test."""
        return ConfigRegistry()

    def test_register_single_source(self, registry: ConfigRegistry) -> None:
        """Registering a value tracks its source."""
        source = ConfigSource(
            layer=ConfigLayer.DEFAULT,
            source_name="python_defaults",
            line=None,
            raw_value=100,
        )
        registry.register("test.key", 100, source)

        cv = registry.get_with_meta("test.key")
        assert cv is not None
        assert cv.value == 100
        assert cv.effective_source.layer == ConfigLayer.DEFAULT
        assert cv.effective_source.source_name == "python_defaults"

    def test_register_multiple_sources_tracks_provenance(self, registry: ConfigRegistry) -> None:
        """Multiple registrations build provenance chain."""
        # First: default
        default_src = ConfigSource(ConfigLayer.DEFAULT, "defaults", None, 100)
        registry.register("risk.max", 100, default_src)

        # Second: file (higher priority)
        file_src = ConfigSource(ConfigLayer.ENV_FILE, "config/live.yaml", 42, 200)
        registry.register("risk.max", 200, file_src)

        cv = registry.get_with_meta("risk.max")
        assert cv.value == 200  # File wins
        assert cv.effective_source.layer == ConfigLayer.ENV_FILE
        assert len(cv.all_sources) == 2
        assert cv.all_sources[0].layer == ConfigLayer.DEFAULT
        assert cv.all_sources[1].layer == ConfigLayer.ENV_FILE

    def test_lower_priority_does_not_override(self, registry: ConfigRegistry) -> None:
        """Registering from lower priority layer doesn't override higher."""
        # First: env var (high priority)
        env_src = ConfigSource(ConfigLayer.ENV_VAR, "MERID_RISK", None, 300)
        registry.register("risk.max", 300, env_src)

        # Second: default (lower priority)
        default_src = ConfigSource(ConfigLayer.DEFAULT, "defaults", None, 100)
        registry.register("risk.max", 100, default_src)

        cv = registry.get_with_meta("risk.max")
        assert cv.value == 300  # Env var still wins
        assert cv.effective_source.layer == ConfigLayer.ENV_VAR

    def test_higher_priority_overrides(self, registry: ConfigRegistry) -> None:
        """Higher priority layer correctly overrides lower."""
        layers_and_values = [
            (ConfigLayer.DEFAULT, 100, "defaults"),
            (ConfigLayer.BASE_FILE, 150, "base.yaml"),
            (ConfigLayer.ENV_FILE, 200, "live.yaml"),
            (ConfigLayer.DOT_ENV, 250, ".env"),
            (ConfigLayer.ENV_VAR, 300, "ENV"),
            (ConfigLayer.CLI_FLAG, 350, "--set"),
        ]

        for layer, value, source in layers_and_values:
            src = ConfigSource(layer, source, None, value)
            registry.register("test.key", value, src)

        cv = registry.get_with_meta("test.key")
        assert cv.value == 350  # CLI flag wins (highest priority)
        assert cv.effective_source.layer == ConfigLayer.CLI_FLAG
        assert len(cv.all_sources) == 6  # All tracked

    def test_compute_fingerprint_changes_with_values(self, registry: ConfigRegistry) -> None:
        """Fingerprint changes when values change."""
        # Register initial values
        for i in range(3):
            src = ConfigSource(ConfigLayer.DEFAULT, "defaults", None, i)
            registry.register(f"key.{i}", i, src)

        fp1 = registry.compute_fingerprint()

        # Change one value
        src = ConfigSource(ConfigLayer.ENV_VAR, "ENV", None, 999)
        registry.register("key.1", 999, src)

        fp2 = registry.compute_fingerprint()

        assert fp1 != fp2
        assert len(fp1) == 16  # Short hash
        assert len(fp2) == 16

    def test_compute_fingerprint_stable_for_same_values(self, registry: ConfigRegistry) -> None:
        """Fingerprint is stable for same config."""
        for i in range(3):
            src = ConfigSource(ConfigLayer.DEFAULT, "defaults", None, i)
            registry.register(f"key.{i}", i, src)

        fp1 = registry.compute_fingerprint()
        fp2 = registry.compute_fingerprint()

        assert fp1 == fp2

    def test_subsystem_fingerprint_isolation(self, registry: ConfigRegistry) -> None:
        """Subsystem fingerprints isolate different key sets."""
        # Portfolio keys
        for i in range(3):
            src = ConfigSource(ConfigLayer.DEFAULT, "defaults", None, i)
            registry.register(f"portfolio.key.{i}", i, src)

        # Risk keys
        for i in range(3):
            src = ConfigSource(ConfigLayer.DEFAULT, "defaults", None, i * 10)
            registry.register(f"risk.key.{i}", i * 10, src)

        portfolio_fp = registry.compute_fingerprint("portfolio")
        risk_fp = registry.compute_fingerprint("risk")

        assert portfolio_fp != risk_fp


class TestExplicitConfigLoader:
    """Test the full loader with real files."""

    @pytest.fixture
    def temp_configs(self) -> Path:
        """Create temporary config directory structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "config"
            config_dir.mkdir()

            # Create base.yaml
            base_config = {
                "portfolio": {"max_risk_usd": 1000, "global_budget": 5000},
                "feature_flags": {"enable_x": False},
            }
            with open(config_dir / "base.yaml", "w") as f:
                yaml.dump(base_config, f)

            # Create live.yaml
            live_config = {
                "portfolio": {"max_risk_usd": 2000},  # Overrides base
                "feature_flags": {"enable_x": True, "enable_y": True},
            }
            with open(config_dir / "live.yaml", "w") as f:
                yaml.dump(live_config, f)

            yield Path(tmpdir)

    def test_base_file_loading(self, temp_configs: Path) -> None:
        """Base config file loads correctly."""
        loader = ExplicitConfigLoader(project_root=temp_configs)
        loader.load_base_configs()

        registry = loader.registry
        assert registry.get("portfolio.max_risk_usd") == 1000
        assert registry.get("portfolio.global_budget") == 5000

    def test_env_file_overrides_base(self, temp_configs: Path) -> None:
        """Environment file correctly overrides base."""
        loader = ExplicitConfigLoader(project_root=temp_configs)
        loader.load_base_configs()
        loader.load_env_config("live")

        registry = loader.registry

        # Overridden value
        cv = registry.get_with_meta("portfolio.max_risk_usd")
        assert cv.value == 2000
        assert cv.effective_source.layer == ConfigLayer.ENV_FILE

        # Preserved from base
        assert registry.get("portfolio.global_budget") == 5000

    def test_env_var_overrides_file(self, temp_configs: Path) -> None:
        """Environment variable overrides file config."""
        loader = ExplicitConfigLoader(project_root=temp_configs)

        # Note: MERID_PORTFOLIO_MAX_RISK_USD becomes portfolio.max.risk.usd
        # because all underscores convert to dots after stripping MERID_
        with patch.dict(os.environ, {"MERID_PORTFOLIO__MAX_RISK_USD": "5000"}):
            loader.load_all(env="live")

        registry = loader.registry
        # MERID_PORTFOLIO__MAX_RISK_USD becomes portfolio.max_risk_usd
        cv = registry.get_with_meta("portfolio.max_risk_usd")
        assert cv.value == 5000
        assert cv.effective_source.layer == ConfigLayer.ENV_VAR

    def test_dotenv_parsing(self, temp_configs: Path) -> None:
        """.env file is parsed correctly."""
        # Clear registry for isolation
        import core.config_loader as cl
        cl._registry = None

        # Create .env file
        # Note: double underscore in env var = single dot/nested level in config key
        env_file = temp_configs / ".env"
        env_file.write_text("""
# Test env file
MERID_PORTFOLIO__MAX_RISK_USD=3000
MERID_FEATURE_FLAGS__ENABLE_X=true
MERID_STRING_VALUE=hello_world
MERID_FLOAT_VALUE=3.14
""")

        loader = ExplicitConfigLoader(project_root=temp_configs)
        loader.load_dot_env(env_file)

        registry = loader.registry
        # MERID_PORTFOLIO__MAX_RISK_USD becomes portfolio.max_risk_usd
        # __ (double underscore) becomes . (dot) for nesting
        assert registry.get("portfolio.max_risk_usd") == 3000
        assert registry.get("feature_flags.enable_x") is True
        assert registry.get("string_value") == "hello_world"
        assert registry.get("float_value") == 3.14

    def test_value_coercion(self, temp_configs: Path) -> None:
        """String values from env are coerced to proper types."""
        loader = ExplicitConfigLoader(project_root=temp_configs)

        coercion_tests = [
            ("true", True),
            ("TRUE", True),
            ("yes", True),
            ("1", True),
            ("false", False),
            ("FALSE", False),
            ("no", False),
            ("0", False),
            ("null", None),
            ("None", None),
            ("", None),
            ("123", 123),
            ("3.14", 3.14),
            ("hello", "hello"),
        ]

        for input_val, expected in coercion_tests:
            result = loader._coerce_value(input_val)
            assert result == expected, f"Failed for {input_val}: got {result}, expected {expected}"


class TestPrecedenceChainIntegration:
    """
    Integration tests that verify the complete precedence chain.

    These tests create temporary files and env vars to simulate
    real-world config loading scenarios.
    """

    @pytest.fixture
    def setup_full_config(self):
        """Setup a full config environment with all layers."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            config_dir = tmp_path / "config"
            config_dir.mkdir()

            # Layer 2: Base config
            base = {
                "risk": {"max_position": 100, "daily_loss": 500},
                "portfolio": {"budget": 10000},
            }
            with open(config_dir / "base.yaml", "w") as f:
                yaml.dump(base, f)

            # Layer 3: Environment config (overrides base)
            live = {
                "risk": {"max_position": 200},  # Override
                "portfolio": {"budget": 20000},  # Override
            }
            with open(config_dir / "live.yaml", "w") as f:
                yaml.dump(live, f)

            # Layer 4: .env file
            # Note: single underscore becomes dot, so use double underscore for nesting
            env_file = tmp_path / ".env"
            env_file.write_text("MERID_RISK__DAILY_LOSS=750\n")  # Override

            yield tmp_path

    def test_complete_precedence_chain(self, setup_full_config: Path) -> None:
        """
        Verify complete precedence chain:
        base.yaml (100) -> live.yaml (200) -> .env (750)
        """
        # Clear any existing registry
        import core.config_loader as cl

        cl._registry = None

        loader = ExplicitConfigLoader(project_root=setup_full_config)

        # Layer 2: Base
        loader.load_base_configs()
        assert loader.registry.get("risk.max_position") == 100

        # Layer 3: Environment file
        loader.load_env_config("live")
        assert loader.registry.get("risk.max_position") == 200

        # Layer 4: .env
        # Note: MERID_RISK__DAILY_LOSS becomes risk.daily_loss (double underscore becomes dot)
        loader.load_dot_env()
        assert loader.registry.get("risk.daily_loss") == 750

        # Verify provenance tracking
        cv = loader.registry.get_with_meta("risk.max_position")
        assert len(cv.all_sources) == 2  # Base + live
        assert cv.all_sources[0].layer == ConfigLayer.BASE_FILE
        assert cv.all_sources[1].layer == ConfigLayer.ENV_FILE

    def test_env_var_beats_all_files(self, setup_full_config: Path) -> None:
        """Environment variable (layer 5) beats all file-based configs."""
        import core.config_loader as cl

        cl._registry = None

        # Note: MERID_RISK__MAX_POSITION becomes risk.max_position
        # We need to match the YAML key structure from the fixture
        with patch.dict(os.environ, {"MERID_RISK__MAX_POSITION": "999"}):
            loader = ExplicitConfigLoader(project_root=setup_full_config)
            loader.load_all(env="live")

        cv = loader.registry.get_with_meta("risk.max_position")
        assert cv.value == 999
        assert cv.effective_source.layer == ConfigLayer.ENV_VAR


class TestEnvVarKeyConversion:
    """Test env var to config key conversion (__ -> . mapping)."""

    def test_double_underscore_becomes_dot(self) -> None:
        """MERID_FOO__BAR becomes foo.bar"""
        import core.config_loader as cl
        cl._registry = None

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            with patch.dict(os.environ, {"MERID_FOO__BAR": "value1"}):
                loader = ExplicitConfigLoader(project_root=tmp_path)
                loader.load_env_vars()

            assert loader.registry.get("foo.bar") == "value1"

    def test_triple_underscore_round_trip(self) -> None:
        """MERID_A__B__C becomes a.b.c (2 levels deep)"""
        import core.config_loader as cl
        cl._registry = None

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            with patch.dict(os.environ, {"MERID_A__B__C": "nested"}):
                loader = ExplicitConfigLoader(project_root=tmp_path)
                loader.load_env_vars()

            assert loader.registry.get("a.b.c") == "nested"

    def test_single_underscore_stays_underscore(self) -> None:
        """MERID_FOO_BAR becomes foo_bar (only __ becomes dot, _ stays _)"""
        import core.config_loader as cl
        cl._registry = None

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            with patch.dict(os.environ, {"MERID_FOO_BAR": "value2"}):
                loader = ExplicitConfigLoader(project_root=tmp_path)
                loader.load_env_vars()

            # Single underscore stays as underscore (use __ for nesting)
            assert loader.registry.get("foo_bar") == "value2"

    def test_realistic_kalshi_key(self) -> None:
        """MERID_KALSHI__SPOT_STRIKE_WARN_PCT becomes kalshi.spot_strike_warn_pct"""
        import core.config_loader as cl
        cl._registry = None

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            with patch.dict(os.environ, {"MERID_KALSHI__SPOT_STRIKE_WARN_PCT": "0.15"}):
                loader = ExplicitConfigLoader(project_root=tmp_path)
                loader.load_env_vars()

            # Value is coerced to float
            assert loader.registry.get("kalshi.spot_strike_warn_pct") == 0.15

    def test_wrong_delimiter_creates_flat_key(self) -> None:
        """Using _ instead of __ creates flat key - demonstrates the mistake"""
        import core.config_loader as cl
        cl._registry = None

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # WRONG: using single _ instead of __
            with patch.dict(os.environ, {"MERID_KALSHI_SPOT_STRIKE_WARN_PCT": "0.20"}):
                loader = ExplicitConfigLoader(project_root=tmp_path)
                loader.load_env_vars()

            # This creates a flat key, NOT nested (value coerced to float)
            assert loader.registry.get("kalshi_spot_strike_warn_pct") == 0.2
            # The intended nested key doesn't exist
            assert loader.registry.get("kalshi.spot_strike_warn_pct") is None


class TestDangerKeyInstrumentation:
    """Verify danger keys are properly tracked and logged."""

    def test_danger_keys_list_is_comprehensive(self) -> None:
        """Danger keys cover critical trading parameters."""
        loader = ExplicitConfigLoader()
        danger_keys = loader.DANGER_KEYS

        assert "portfolio.max_risk_usd" in danger_keys
        assert "portfolio.max_position_usd" in danger_keys
        assert "portfolio.global_risk_budget" in danger_keys
        assert "kalshi.spot_strike_warn_pct" in danger_keys
        assert "kalshi.spot_strike_max_pct" in danger_keys


class TestExplainOutput:
    """Test the human-readable explain output."""

    def test_explain_format(self) -> None:
        """Explain output is human-readable."""
        registry = ConfigRegistry()

        # Build chain
        sources = [
            ConfigSource(ConfigLayer.DEFAULT, "defaults.py", 42, 5),
            ConfigSource(ConfigLayer.BASE_FILE, "config/base.yaml", 18, 3),
            ConfigSource(ConfigLayer.ENV_FILE, "config/live.yaml", 27, 9),
        ]

        for src in sources:
            registry.register("portfolio.global_risk_budget", src.raw_value, src)

        cv = registry.get_with_meta("portfolio.global_risk_budget")
        explanation = cv.explain()

        assert "portfolio.global_risk_budget" in explanation
        assert "DEFAULT" in explanation
        assert "BASE_FILE" in explanation
        assert "ENV_FILE" in explanation
        assert "EFFECTIVE" in explanation
        assert "config/live.yaml:27" in explanation


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

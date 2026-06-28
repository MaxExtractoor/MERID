"""
Tests for environment mode enforcement.

These tests verify that:
1. PROD mode requires all required configuration
2. DEV/STAGING modes allow missing config
3. Fallbacks are disabled in PROD mode
4. Environment is logged at startup
"""

import os
import pytest
from unittest.mock import patch, MagicMock
from merid.config.environment import Env, current_env, require_prod_ready_config, enable_composite_spot_fallback, enable_legacy_fallbacks, enable_synthetic_data


class TestEnvironmentDetection:
    """Test environment detection from environment variables."""
    
    def test_current_env_default(self):
        """Test default environment is DEV."""
        with patch.dict(os.environ, {}, clear=True):
            env = current_env()
            assert env == Env.DEV
    
    def test_current_env_explicit_dev(self):
        """Test explicit DEV environment."""
        with patch.dict(os.environ, {"MERID_ENV": "dev"}):
            env = current_env()
            assert env == Env.DEV
    
    def test_current_env_staging(self):
        """Test STAGING environment."""
        with patch.dict(os.environ, {"MERID_ENV": "staging"}):
            env = current_env()
            assert env == Env.DEV
    
    def test_current_env_prod(self):
        """Test PROD environment."""
        with patch.dict(os.environ, {"MERID_ENV": "prod"}):
            env = current_env()
            assert env == Env.PROD
    
    def test_current_env_production_alias(self):
        """Test 'production' alias maps to PROD."""
        with patch.dict(os.environ, {"MERID_ENV": "production"}):
            env = current_env()
            assert env == Env.PROD
    
    def test_current_env_live_alias(self):
        """Test 'live' alias maps to PROD."""
        with patch.dict(os.environ, {"MERID_ENV": "live"}):
            env = current_env()
            assert env == Env.PROD
    
    def test_current_env_invalid(self):
        """Test invalid environment raises ValueError."""
        with patch.dict(os.environ, {"MERID_ENV": "invalid"}):
            with pytest.raises(ValueError, match="Invalid MERID_ENV"):
                current_env()


class TestProdConfigEnforcement:
    """Test production configuration enforcement."""
    
    def test_require_prod_ready_config_skips_dev(self):
        """Test DEV mode skips prod config checks."""
        with patch.dict(os.environ, {"MERID_ENV": "dev", "KALSHI_API_KEY_ID": "", "KALSHI_ENV": "demo"}):
            # Should not raise in DEV mode
            require_prod_ready_config()
    
    def test_require_prod_ready_config_skips_staging(self):
        """Test STAGING mode skips prod config checks."""
        with patch.dict(os.environ, {"MERID_ENV": "staging", "KALSHI_API_KEY_ID": "", "KALSHI_ENV": "demo"}):
            # Should not raise in STAGING mode
            require_prod_ready_config()
    
    def test_require_prod_ready_config_missing_key_id(self):
        """Test PROD mode fails without KALSHI_API_KEY_ID."""
        with patch.dict(os.environ, {"MERID_ENV": "prod", "KALSHI_API_KEY_ID": "", "KALSHI_ENV": "prod"}):
            with pytest.raises(RuntimeError, match="Missing KALSHI_API_KEY_ID"):
                require_prod_ready_config()
    
    def test_require_prod_ready_config_missing_key_path(self):
        """Test PROD mode fails without private key path."""
        with patch.dict(os.environ, {"MERID_ENV": "prod", "KALSHI_API_KEY_ID": "test", "KALSHI_PRIVATE_KEY_PATH": "", "KALSHI_PRIVATE_KEY_PEM": "", "KALSHI_ENV": "prod"}):
            with pytest.raises(RuntimeError, match="Missing KALSHI_PRIVATE_KEY_PATH"):
                require_prod_ready_config()
    
    def test_require_prod_ready_config_wrong_kalshi_env(self):
        """Test PROD mode fails if KALSHI_ENV is not prod/live."""
        with patch.dict(os.environ, {"MERID_ENV": "prod", "KALSHI_API_KEY_ID": "test", "KALSHI_PRIVATE_KEY_PATH": "/tmp/key.pem", "KALSHI_ENV": "demo"}):
            with pytest.raises(RuntimeError, match="KALSHI_ENV must be 'prod' or 'live'"):
                require_prod_ready_config()
    
    def test_require_prod_ready_config_success(self):
        """Test PROD mode succeeds with valid config."""
        with patch.dict(os.environ, {
            "MERID_ENV": "prod",
            "KALSHI_API_KEY_ID": "test_key",
            "KALSHI_PRIVATE_KEY_PATH": "/tmp/key.pem",
            "KALSHI_ENV": "prod"
        }):
            # Should not raise with valid config
            require_prod_ready_config()


class TestFallbackFlags:
    """Test fallback feature flags."""
    
    def test_composite_spot_fallback_disabled_in_prod(self):
        """Test composite spot fallback is disabled in PROD."""
        with patch.dict(os.environ, {"MERID_ENV": "prod"}):
            assert enable_composite_spot_fallback() is False
    
    def test_composite_spot_fallback_enabled_in_dev(self):
        """Test composite spot fallback is enabled in DEV."""
        with patch.dict(os.environ, {"MERID_ENV": "dev"}):
            assert enable_composite_spot_fallback() is True
    
    def test_composite_spot_fallback_enabled_in_staging(self):
        """Test composite spot fallback is enabled in STAGING."""
        with patch.dict(os.environ, {"MERID_ENV": "staging"}):
            assert enable_composite_spot_fallback() is True
    
    def test_legacy_fallbacks_disabled_in_prod(self):
        """Test legacy fallbacks are disabled in PROD."""
        with patch.dict(os.environ, {"MERID_ENV": "prod"}):
            assert enable_legacy_fallbacks() is False
    
    def test_legacy_fallbacks_enabled_in_dev(self):
        """Test legacy fallbacks are enabled in DEV."""
        with patch.dict(os.environ, {"MERID_ENV": "dev"}):
            assert enable_legacy_fallbacks() is True
    
    def test_synthetic_data_disabled_in_prod(self):
        """Test synthetic data is disabled in PROD."""
        with patch.dict(os.environ, {"MERID_ENV": "prod"}):
            assert enable_synthetic_data() is False
    
    def test_synthetic_data_enabled_in_dev(self):
        """Test synthetic data is enabled in DEV."""
        with patch.dict(os.environ, {"MERID_ENV": "dev"}):
            assert enable_synthetic_data() is True


class TestEnvironmentLogging:
    """Test environment logging at startup."""
    
    def test_log_environment_startup(self, caplog):
        """Test environment logging function."""
        with patch.dict(os.environ, {"MERID_ENV": "dev", "KALSHI_ENV": "demo", "MERID_RUNTIME_MODE": "15m_live"}):
            from merid.config.environment import log_environment_startup
            log_environment_startup()
            # Should log environment info
            assert any("STARTUP" in record.message for record in caplog.records)
            assert any("MERID_ENV" in record.message for record in caplog.records)

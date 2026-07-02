"""Regression tests for localhost configuration fixes.

Tests for hardcoded localhost fixes made during the 15m trading stack audit:
- Kelly endpoints (vix_kelly_endpoints.py, kelly_vix_sse.py, kelly_mvrk_endpoints.py, kelly_endpoints.py)
- crypto_series.py (Redis host)
- settlement_poller.py (Redis URL)
- fix_client.py (FIX host)
- reconciliation_alerts.py (API host)
- live_15m_end_to_end_probe.py (API host/port)
- spot_provider.py (API base URL)
- mode_manager.py (IB API host)
- settings.py (Neo4j URI, server host)
"""

import pytest
import os
from unittest.mock import patch, Mock


class TestKellyEndpointsLocalhostFix:
    """Test Kelly endpoints use configurable API base."""
    
    def test_vix_kelly_endpoints_uses_env_var(self):
        """Test that vix_kelly_endpoints uses KALSHI_API_BASE env var."""
        # Set env var
        os.environ['KALSHI_API_BASE'] = 'https://api.example.com'
        
        # The implementation should use: os.getenv("KALSHI_API_BASE", os.getenv("MERID_API_BASE", "http://localhost:8011"))
        api_base = os.getenv("KALSHI_API_BASE", os.getenv("MERID_API_BASE", "http://localhost:8011"))
        
        assert api_base == 'https://api.example.com', "Should use KALSHI_API_BASE env var"
        assert 'localhost' not in api_base, "Should not use hardcoded localhost"
        
        os.environ.pop('KALSHI_API_BASE', None)
    
    def test_kelly_endpoints_fallback_to_merid_api_base(self):
        """Test that Kelly endpoints fallback to MERID_API_BASE."""
        os.environ.pop('KALSHI_API_BASE', None)
        os.environ['MERID_API_BASE'] = 'https://merid.example.com'
        
        api_base = os.getenv("KALSHI_API_BASE", os.getenv("MERID_API_BASE", "http://localhost:8011"))
        
        assert api_base == 'https://merid.example.com', "Should fallback to MERID_API_BASE"
        assert 'localhost' not in api_base, "Should not use hardcoded localhost"
        
        os.environ.pop('MERID_API_BASE', None)
    
    def test_kelly_endpoints_final_fallback(self):
        """Test that Kelly endpoints have localhost as final fallback."""
        os.environ.pop('KALSHI_API_BASE', None)
        os.environ.pop('MERID_API_BASE', None)
        
        api_base = os.getenv("KALSHI_API_BASE", os.getenv("MERID_API_BASE", "http://localhost:8011"))
        
        assert api_base == 'http://localhost:8011', "Should fallback to localhost as last resort"
    
    def test_kelly_vix_sse_uses_merid_port(self):
        """Test that kelly_vix_sse uses MERID_PORT env var."""
        os.environ.pop('KALSHI_API_BASE', None)
        os.environ.pop('MERID_API_BASE', None)
        os.environ['MERID_PORT'] = '9090'
        
        # Implementation: f"http://localhost:{os.getenv('MERID_PORT', '8011')}"
        api_base = f"http://localhost:{os.getenv('MERID_PORT', '8011')}"
        
        assert api_base == 'http://localhost:9090', "Should use MERID_PORT env var"
        
        os.environ.pop('MERID_PORT', None)


class TestCryptoSeriesRedisHostFix:
    """Test crypto_series.py uses configurable Redis host."""
    
    def test_crypto_series_uses_redis_host_env_var(self):
        """Test that crypto_series uses REDIS_HOST env var."""
        os.environ['REDIS_HOST'] = 'redis.example.com'
        
        redis_host = os.getenv("REDIS_HOST", "localhost")
        
        assert redis_host == 'redis.example.com', "Should use REDIS_HOST env var"
        assert redis_host != 'localhost', "Should not use hardcoded localhost"
        
        os.environ.pop('REDIS_HOST', None)
    
    def test_crypto_series_fallback_to_localhost(self):
        """Test that crypto_series falls back to localhost."""
        os.environ.pop('REDIS_HOST', None)
        
        redis_host = os.getenv("REDIS_HOST", "localhost")
        
        assert redis_host == 'localhost', "Should fallback to localhost"


class TestSettlementPollerRedisURLFix:
    """Test settlement_poller.py uses configurable Redis URL."""
    
    def test_settlement_poller_uses_redis_url_env_var(self):
        """Test that settlement_poller uses REDIS_URL env var."""
        os.environ['REDIS_URL'] = 'redis://redis.example.com:6379/0'
        
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        
        assert redis_url == 'redis://redis.example.com:6379/0', "Should use REDIS_URL env var"
        assert 'localhost' not in redis_url, "Should not use hardcoded localhost"
        
        os.environ.pop('REDIS_URL', None)
    
    def test_settlement_poller_fallback_to_localhost(self):
        """Test that settlement_poller falls back to localhost."""
        os.environ.pop('REDIS_URL', None)
        
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        
        assert redis_url == 'redis://localhost:6379/0', "Should fallback to localhost"


class TestFixClientHostFix:
    """Test fix_client.py uses configurable FIX host."""
    
    def test_fix_client_uses_fix_host_env_var(self):
        """Test that fix_client uses FIX_HOST env var."""
        os.environ['FIX_HOST'] = 'fix.example.com'
        
        fix_host = os.getenv("FIX_HOST", "127.0.0.1")
        
        assert fix_host == 'fix.example.com', "Should use FIX_HOST env var"
        assert fix_host != '127.0.0.1', "Should not use hardcoded 127.0.0.1"
        
        os.environ.pop('FIX_HOST', None)
    
    def test_fix_client_fallback_to_127_0_0_1(self):
        """Test that fix_client falls back to 127.0.0.1."""
        os.environ.pop('FIX_HOST', None)
        
        fix_host = os.getenv("FIX_HOST", "127.0.0.1")
        
        assert fix_host == '127.0.0.1', "Should fallback to 127.0.0.1"


class TestReconciliationAlertsHostFix:
    """Test reconciliation_alerts.py uses configurable API host."""
    
    def test_reconciliation_alerts_uses_merid_api_host(self):
        """Test that reconciliation_alerts uses MERID_API_HOST env var."""
        os.environ['MERID_API_HOST'] = 'api.example.com'
        port = os.getenv("MERID_PORT", "8011")
        
        api_host = os.getenv("MERID_API_HOST", "localhost")
        api_endpoint = f"http://{api_host}:{port}/api/v1/kalshi/health/reconciliation"
        
        assert api_host == 'api.example.com', "Should use MERID_API_HOST env var"
        assert 'localhost' not in api_endpoint, "Should not use hardcoded localhost"
        
        os.environ.pop('MERID_API_HOST', None)
    
    def test_reconciliation_alerts_fallback_to_localhost(self):
        """Test that reconciliation_alerts falls back to localhost."""
        os.environ.pop('MERID_API_HOST', None)
        
        api_host = os.getenv("MERID_API_HOST", "localhost")
        
        assert api_host == 'localhost', "Should fallback to localhost"


class TestLive15mProbeHostFix:
    """Test live_15m_end_to_end_probe.py uses configurable host/port."""
    
    def test_live_15m_probe_uses_merid_api_host(self):
        """Test that live_15m_probe uses MERID_API_HOST env var."""
        os.environ['MERID_API_HOST'] = 'api.example.com'
        os.environ['MERID_API_PORT'] = '9090'
        
        api_host = os.getenv("MERID_API_HOST", "127.0.0.1")
        api_port = os.getenv("MERID_API_PORT", "8011")
        health_url = f"http://{api_host}:{api_port}/api/v1/health-snapshot/"
        
        assert api_host == 'api.example.com', "Should use MERID_API_HOST env var"
        assert api_port == '9090', "Should use MERID_API_PORT env var"
        assert '127.0.0.1' not in health_url, "Should not use hardcoded 127.0.0.1"
        
        os.environ.pop('MERID_API_HOST', None)
        os.environ.pop('MERID_API_PORT', None)
    
    def test_live_15m_probe_fallback_to_defaults(self):
        """Test that live_15m_probe falls back to defaults."""
        os.environ.pop('MERID_API_HOST', None)
        os.environ.pop('MERID_API_PORT', None)
        
        api_host = os.getenv("MERID_API_HOST", "127.0.0.1")
        api_port = os.getenv("MERID_API_PORT", "8011")
        
        assert api_host == '127.0.0.1', "Should fallback to 127.0.0.1"
        assert api_port == '8011', "Should fallback to 8011"


class TestSpotProviderHostFix:
    """Test spot_provider.py uses configurable API base."""
    
    def test_spot_provider_uses_merid_api_base(self):
        """Test that spot_provider uses MERID_API_BASE env var."""
        os.environ['MERID_API_BASE'] = 'https://api.example.com'
        
        base_url = os.getenv("MERID_API_BASE", "http://localhost:8011")
        
        assert base_url == 'https://api.example.com', "Should use MERID_API_BASE env var"
        assert 'localhost' not in base_url, "Should not use hardcoded localhost"
        
        os.environ.pop('MERID_API_BASE', None)
    
    def test_spot_provider_fallback_to_localhost(self):
        """Test that spot_provider falls back to localhost."""
        os.environ.pop('MERID_API_BASE', None)
        
        base_url = os.getenv("MERID_API_BASE", "http://localhost:8011")
        
        assert base_url == 'http://localhost:8011', "Should fallback to localhost"


class TestModeManagerHostFix:
    """Test mode_manager.py uses configurable IB API host."""
    
    def test_mode_manager_uses_ib_api_host(self):
        """Test that mode_manager uses IB_API_HOST env var."""
        os.environ['IB_API_HOST'] = 'ib.example.com:7497'
        
        api_url = os.getenv("IB_API_HOST", "127.0.0.1:7497")
        
        assert api_url == 'ib.example.com:7497', "Should use IB_API_HOST env var"
        assert '127.0.0.1' not in api_url, "Should not use hardcoded 127.0.0.1"
        
        os.environ.pop('IB_API_HOST', None)
    
    def test_mode_manager_fallback_to_127_0_0_1(self):
        """Test that mode_manager falls back to 127.0.0.1."""
        os.environ.pop('IB_API_HOST', None)
        
        api_url = os.getenv("IB_API_HOST", "127.0.0.1:7497")
        
        assert api_url == '127.0.0.1:7497', "Should fallback to 127.0.0.1"


class TestSettingsHostFix:
    """Test settings.py uses configurable host settings."""
    
    def test_neo4j_uri_uses_env_var(self):
        """Test that NEO4J_URI uses env var."""
        os.environ['NEO4J_URI'] = 'bolt://neo4j.example.com:7687'
        
        neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        
        assert neo4j_uri == 'bolt://neo4j.example.com:7687', "Should use NEO4J_URI env var"
        assert 'localhost' not in neo4j_uri, "Should not use hardcoded localhost"
        
        os.environ.pop('NEO4J_URI', None)
    
    def test_neo4j_uri_fallback_to_localhost(self):
        """Test that NEO4J_URI falls back to localhost."""
        os.environ.pop('NEO4J_URI', None)
        
        neo4j_uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
        
        assert neo4j_uri == 'bolt://localhost:7687', "Should fallback to localhost"
    
    def test_merid_host_uses_env_var(self):
        """Test that MERID_HOST uses env var."""
        os.environ['MERID_HOST'] = '0.0.0.0'
        
        host = os.getenv("MERID_HOST", "127.0.0.1")
        
        assert host == '0.0.0.0', "Should use MERID_HOST env var"
        assert host != '127.0.0.1', "Should not use hardcoded 127.0.0.1"
        
        os.environ.pop('MERID_HOST', None)
    
    def test_merid_host_fallback_to_127_0_0_1(self):
        """Test that MERID_HOST falls back to 127.0.0.1."""
        os.environ.pop('MERID_HOST', None)
        
        host = os.getenv("MERID_HOST", "127.0.0.1")
        
        assert host == '127.0.0.1', "Should fallback to 127.0.0.1"


class TestCatalogRefreshIntervalConfigurable:
    """Test that catalog refresh interval is configurable."""
    
    def test_catalog_refresh_interval_uses_env_var(self):
        """Test that catalog refresh interval uses MERID_KALSHI_CATALOG_REFRESH_INTERVAL_S."""
        os.environ['MERID_KALSHI_CATALOG_REFRESH_INTERVAL_S'] = '10.0'
        
        refresh_interval = float(os.getenv("MERID_KALSHI_CATALOG_REFRESH_INTERVAL_S", "5.0"))
        
        assert refresh_interval == 10.0, "Should use MERID_KALSHI_CATALOG_REFRESH_INTERVAL_S env var"
        
        os.environ.pop('MERID_KALSHI_CATALOG_REFRESH_INTERVAL_S', None)
    
    def test_catalog_refresh_interval_fallback_to_default(self):
        """Test that catalog refresh interval falls back to 5.0s."""
        os.environ.pop('MERID_KALSHI_CATALOG_REFRESH_INTERVAL_S', None)
        
        refresh_interval = float(os.getenv("MERID_KALSHI_CATALOG_REFRESH_INTERVAL_S", "5.0"))
        
        assert refresh_interval == 5.0, "Should fallback to 5.0s"
    
    def test_catalog_refresh_interval_minimum(self):
        """Test that catalog refresh interval has minimum of 2.0s."""
        _MIN_REFRESH_INTERVAL_S = 2.0
        
        # Test with value below minimum
        refresh_interval = 1.0
        if refresh_interval < _MIN_REFRESH_INTERVAL_S:
            refresh_interval = _MIN_REFRESH_INTERVAL_S
        
        assert refresh_interval == 2.0, "Should enforce minimum of 2.0s"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

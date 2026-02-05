"""Tests for merid/execution/executors/webull.py - Batch 60 (3-5 tests)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from merid.execution.executors.webull import WebullExecutor


class TestWebullExecutor:
    """Tests for WebullExecutor (small batch)."""

    def test_venue_attribute(self):
        """Test venue class attribute."""
        assert WebullExecutor.venue == "webull"

    def test_init_default(self):
        """Test initialization with default values."""
        with patch.dict('os.environ', {}, clear=True):
            executor = WebullExecutor()
            assert executor.venue == "webull"
            assert executor.username is None
            assert executor.password is None
            assert executor.did is None
            assert executor._access_token is None

    def test_init_with_env_vars(self):
        """Test initialization with environment variables."""
        env = {
            'WEBULL_USERNAME': 'test_user',
            'WEBULL_PASSWORD': 'test_pass',
            'WEBULL_DID': 'test_did'
        }
        with patch.dict('os.environ', env, clear=True):
            executor = WebullExecutor()
            assert executor.username == 'test_user'
            assert executor.password == 'test_pass'
            assert executor.did == 'test_did'

    @pytest.mark.asyncio
    async def test_ensure_auth_existing_token(self):
        """Test _ensure_auth when token already exists."""
        executor = WebullExecutor()
        executor._access_token = "existing_token"
        
        # Should return immediately without calling env
        await executor._ensure_auth()
        assert executor._access_token == "existing_token"

    @pytest.mark.asyncio
    async def test_ensure_auth_from_env(self):
        """Test _ensure_auth getting token from env."""
        with patch.dict('os.environ', {'WEBULL_ACCESS_TOKEN': 'env_token'}, clear=True):
            executor = WebullExecutor()
            await executor._ensure_auth()
            assert executor._access_token == "env_token"

    def test_get_auth_headers(self):
        """Test auth headers generation."""
        executor = WebullExecutor()
        executor._access_token = "test_token"
        headers = executor._get_auth_headers()
        assert headers == {"Authorization": "Bearer test_token"}

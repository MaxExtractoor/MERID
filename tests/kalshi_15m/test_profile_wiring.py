import os
import pytest
import asyncio
from web.main import _init_kalshi_crypto_15m_app
from fastapi import FastAPI


@pytest.mark.kalshi_15m

@pytest.fixture
def app():
    return FastAPI()

@pytest.fixture
def startup_state():
    return {"services": {}, "background_tasks": []}

@pytest.mark.kalshi_15m
@pytest.mark.asyncio
async def test_profile_assertion_wrong_profile(app, startup_state):
    """Verify that _init_kalshi_crypto_15m_app fails with wrong profile."""
    # Wrong profile should raise
    os.environ["MERID_PROFILE"] = "full"
    
    with pytest.raises(RuntimeError) as exc_info:
        await _init_kalshi_crypto_15m_app(app, startup_state, "kalshi_crypto_15m_v2")
    
    assert "PROFILE VIOLATION" in str(exc_info.value)
    assert "full" in str(exc_info.value)
    assert "kalshi_crypto_15m_v2" in str(exc_info.value)

@pytest.mark.kalshi_15m
@pytest.mark.asyncio
async def test_profile_assertion_correct_profile(app, startup_state):
    """Verify that _init_kalshi_crypto_15m_app succeeds with correct profile."""
    # Correct profile should not raise assertion
    os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"
    
    # Add started_at to startup_state with a valid timestamp to avoid TypeError
    import time
    startup_state["started_at"] = time.time()
        
    # Note: This will fail at later phases due to missing services, but the profile assertion should pass
    try:
        await _init_kalshi_crypto_15m_app(app, startup_state, "kalshi_crypto_15m_v2")
    except RuntimeError as e:
        # Should fail due to missing services, NOT profile assertion
        assert "PROFILE VIOLATION" not in str(e)
    except KeyError as e:
        # Expected - missing services during startup
        pass

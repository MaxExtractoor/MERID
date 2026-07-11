import pytest
from fastapi import FastAPI
from merid.startup_validations import check_router_isolation, StartupValidationError


def test_router_isolation_skip_for_other_profiles():
    """Verify that check_router_isolation() skips validation for non-15m profiles."""
    import os
    
    # Set profile to full
    os.environ["MERID_PROFILE"] = "full"
    
    # Check router isolation - should skip (not raise)
    try:
        check_router_isolation(None)  # No app needed for skip check
        skipped = True
    except StartupValidationError:
        skipped = False
    
    assert skipped, "Router isolation check should skip for non-kalshi_crypto_15m_v2 profiles"


def test_router_isolation_violation():
    """Verify that check_router_isolation() detects forbidden routers."""
    import os
    
    # Set profile to kalshi_crypto_15m_v2
    os.environ["MERID_PROFILE"] = "kalshi_crypto_15m_v2"
    
    # Create a test FastAPI app with a forbidden router
    app = FastAPI()
    
    # Manually add a forbidden router (simulate a violation)
    from fastapi import APIRouter
    forbidden_router = APIRouter()
    forbidden_router.add_api_route("/api/v1/swarm/status", lambda: {"status": "ok"})
    app.include_router(forbidden_router)
    
    # Check router isolation - should fail
    try:
        check_router_isolation(app)
        isolation_failed = False
    except StartupValidationError as e:
        isolation_failed = True
        assert "swarm" in str(e).lower(), "Error should mention the forbidden router"
    
    assert isolation_failed, "Router isolation check should fail with forbidden routers registered"

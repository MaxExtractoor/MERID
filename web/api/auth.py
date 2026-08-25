"""
Authentication API Endpoints.

Provides user registration, login, and session management.
"""

from __future__ import annotations

from typing import Optional

import os

from fastapi import APIRouter, Depends, HTTPException, Header, Response
from pydantic import BaseModel, EmailStr, Field

from auth.user_manager import user_manager
from utils.logger import get_logger
from utils.deps import require_dependency

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
logger = get_logger("web.api.auth")

# Ensure email validation stack is available early so API fails fast if missing.
require_dependency("email_validator", feature="Email authentication")


class WalletAuthRequest(BaseModel):
    """Wallet authentication request."""
    wallet_address: str = Field(..., min_length=42, max_length=42)
    signature: str
    message: str


class EmailAuthRequest(BaseModel):
    """Email/password authentication request."""
    email: EmailStr
    password: str = Field(..., min_length=8)


class RegisterRequest(BaseModel):
    """User registration request."""
    username: str = Field(..., min_length=3, max_length=32)
    email: Optional[EmailStr] = None
    wallet_address: Optional[str] = Field(None, min_length=42, max_length=42)
    twitter_handle: Optional[str] = None
    referral_code: Optional[str] = None


# ──────────────────────────────────────────────────────────────────────────────
# Reusable auth dependency — import and use as: Depends(get_current_session)
# ──────────────────────────────────────────────────────────────────────────────

async def get_current_session(
    session_id: Optional[str] = Header(None, alias="X-Session-ID"),
    authorization: Optional[str] = Header(None),
) -> dict:
    """FastAPI dependency: validates session from X-Session-ID or Authorization header.

    Accepts either:
      - ``X-Session-ID: <session_id>``
      - ``Authorization: Bearer <session_id>``

    ZT4-02: Centralises session validation so any endpoint can do:
        ``user = Depends(get_current_session)``

    SECURITY: Auth bypass mechanisms are fail-safe by default.
    - Test bypass requires explicit MERID_SKIP_AUTH_FOR_TESTS=1
    - Single-user mode requires explicit MERID_SINGLE_USER_OPERATOR=1
    - Dev bypass requires explicit MERID_DEV_AUTH_BYPASS=1 AND MERID_ENV=development
    - All bypasses are blocked when live trading is detected
    - All bypass events are logged for security auditing
    """
    # SECURITY: Fail-safe defaults - no bypass unless explicitly enabled
    # Test bypass (explicit env var)
    test_bypass = os.getenv("MERID_SKIP_AUTH_FOR_TESTS") == "1"
    if test_bypass:
        # SECURITY: Log test bypass for audit trail
        logger.warning(
            "AUTH BYPASS: Test mode bypass activated via MERID_SKIP_AUTH_FOR_TESTS=1. "
            "This should NEVER be used in production."
        )
        return {"user": None, "session_id": "__test_bypass__"}

    # SECURITY: Single-user operator mode requires explicit opt-in
    single_user_mode = os.getenv("MERID_SINGLE_USER_OPERATOR") == "1"
    if single_user_mode:
        # SECURITY: Fail-closed: single-user operator bypass is prohibited when live
        # trading is enabled.  It is only permitted in dev/test with 127.0.0.1 and
        # trading_mode != live.
        live_trading_indicators = [
            os.getenv("MERID_PM_LIVE_ENABLED", "false").lower() in ("1", "true", "yes"),
            os.getenv("MERID_TRADE_MODE", "").lower() == "live",
            os.getenv("MERID_PM_TRADING_MODE", "").lower() == "live",
            os.getenv("TRADING_ENABLED", "false").lower() in ("1", "true", "yes"),
        ]
        env = os.getenv("MERID_ENV", "production").lower()
        bind_host = os.getenv("MERID_SERVER_HOST", "127.0.0.1")

        if any(live_trading_indicators) or env not in ("development", "dev", "test", "testing") or bind_host != "127.0.0.1":
            logger.critical(
                "SECURITY ALERT: SINGLE-USER OPERATOR BYPASS BLOCKED. "
                "MERID_SINGLE_USER_OPERATOR=1 is prohibited in production or live trading. "
                "live=%s env=%s bind=%s",
                live_trading_indicators, env, bind_host,
            )
            raise HTTPException(
                status_code=403,
                detail="Single-user operator bypass is prohibited in production or live trading.",
            )

        # SECURITY: Log single-user bypass for audit trail
        logger.warning(
            "AUTH BYPASS: Single-user operator mode activated via MERID_SINGLE_USER_OPERATOR=1. "
            "Authentication disabled for local operator access."
        )
        return {"user": {"user_id": "operator", "username": "operator", "role": "admin"}, "session_id": "__single_user__"}

    # SECURITY: Development bypass requires explicit opt-in AND development environment
    # SECURITY FIX: Changed from auto-enabled to explicit opt-in for security
    dev_bypass_enabled = os.getenv("MERID_DEV_AUTH_BYPASS", "0") == "1"
    dev_env = os.getenv("MERID_ENV", "production").lower() in ("development", "dev", "local")
    
    if dev_bypass_enabled and dev_env:
        # SECURITY: Fail-closed: never allow bypass when live trading is enabled.
        # Check multiple indicators of live trading to be absolutely sure
        live_trading_indicators = [
            os.getenv("MERID_PM_LIVE_ENABLED", "false").lower() in ("1", "true", "yes"),
            os.getenv("MERID_TRADE_MODE", "").lower() == "live",
            os.getenv("MERID_PM_TRADING_MODE", "").lower() == "live",
            os.getenv("TRADING_ENABLED", "false").lower() in ("1", "true", "yes"),
        ]
        
        if any(live_trading_indicators):
            # SECURITY: Log attempted bypass in live trading mode (CRITICAL security event)
            logger.critical(
                "SECURITY ALERT: DEV AUTH BYPASS BLOCKED - Live trading detected. "
                "MERID_ENV=%s, live_trading_indicators=%s. "
                "Authentication bypass explicitly blocked to prevent unauthorized access.",
                os.getenv("MERID_ENV", "<unset>"),
                live_trading_indicators
            )
            raise HTTPException(
                status_code=403,
                detail="Dev auth bypass is disabled in live trading mode. Set MERID_ENV=production and MERID_DEV_AUTH_BYPASS=0.",
            )
        
        # SECURITY: Log dev bypass for audit trail
        logger.warning(
            "AUTH BYPASS: Development mode bypass activated via MERID_DEV_AUTH_BYPASS=1. "
            "MERID_ENV=%s. Authentication disabled for local development.",
            os.getenv("MERID_ENV", "<unset>")
        )
        return {"user": {"user_id": "dev_user", "username": "developer"}, "session_id": "__dev_bypass__"}

    # SECURITY: If dev bypass is not explicitly enabled, require authentication
    # This prevents accidental bypass due to unset environment variables
    if dev_env and not dev_bypass_enabled:
        logger.info(
            "AUTH: Development environment detected but MERID_DEV_AUTH_BYPASS not set to 1. "
            "Requiring authentication as fail-safe default."
        )

    # Resolve token: prefer X-Session-ID, fall back to Authorization: Bearer
    token = session_id
    if not token and authorization:
        if authorization.startswith("Bearer "):
            token = authorization[7:]
        else:
            token = authorization

    if not token:
        raise HTTPException(status_code=401, detail="X-Session-ID or Authorization header required")
    user = user_manager.validate_session(token)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    return {"user": user, "session_id": token}


@router.post("/register")
async def register_user(request: RegisterRequest):
    """
    Register a new user account.
    
    Supports multiple registration methods:
    - Email
    - Wallet address
    - Twitter handle
    
    Optional referral code for referral program.
    """
    try:
        user = user_manager.create_user(
            username=request.username,
            email=request.email,
            wallet_address=request.wallet_address,
            twitter_handle=request.twitter_handle,
            referred_by_code=request.referral_code
        )
        
        # Create session
        session = user_manager.create_session(user.user_id)
        
        return {
            "status": "success",
            "user": user.to_dict(),
            "session_id": session.session_id,
            "message": "Account created successfully"
        }
        
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Registration failed: %s", exc)
        raise HTTPException(status_code=500, detail="Registration failed")


@router.post("/login/wallet")
async def login_wallet(request: WalletAuthRequest):
    """
    Authenticate user via wallet signature.
    
    Verifies wallet ownership through cryptographic signature.
    """
    try:
        user = user_manager.authenticate_wallet(
            wallet_address=request.wallet_address,
            signature=request.signature,
            message=request.message
        )
        
        if not user:
            raise HTTPException(status_code=401, detail="Authentication failed")
        
        # Create session
        session = user_manager.create_session(user.user_id)
        
        return {
            "status": "success",
            "user": user.to_dict(),
            "session_id": session.session_id
        }
        
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Wallet authentication failed: %s", exc)
        raise HTTPException(status_code=500, detail="Authentication failed")


@router.post("/login/email")
async def login_email(request: EmailAuthRequest):
    """
    Authenticate user via email/password.
    
    Traditional email/password authentication.
    """
    try:
        user = user_manager.authenticate_email(
            email=request.email,
            password=request.password
        )
        
        if not user:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        # Create session
        session = user_manager.create_session(user.user_id)
        
        return {
            "status": "success",
            "user": user.to_dict(),
            "session_id": session.session_id
        }
        
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Email authentication failed: %s", exc)
        raise HTTPException(status_code=500, detail="Authentication failed")


@router.get("/session")
async def validate_session(session_id: Optional[str] = Header(None, alias="X-Session-ID")):
    """
    Validate current session.
    
    Returns user information if session is valid.
    """
    if not session_id:
        raise HTTPException(status_code=401, detail="No session ID provided")
    
    user = user_manager.validate_session(session_id)
    
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    
    return {
        "status": "valid",
        "user": user.to_dict()
    }


@router.post("/logout")
async def logout(session_id: Optional[str] = Header(None, alias="X-Session-ID")):
    """
    Logout and invalidate session.
    """
    if session_id:
        user_manager.invalidate_session(session_id)
    return {
        "status": "success",
        "message": "Logged out successfully"
    }


@router.get("/user/{user_id}")
async def get_user_profile(user_id: str):
    """Get public user profile."""
    user = user_manager.get_user(user_id)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Return public profile (exclude sensitive data)
    return {
        "user_id": user.user_id,
        "username": user.username,
        "created_at": user.created_at,
        "total_referrals": user.total_referrals,
        "is_verified": user.is_verified
    }


@router.get("/referral/{user_id}")
async def get_referral_info(user_id: str):
    """Get referral information for a user."""
    stats = user_manager.get_referral_stats(user_id)
    
    if not stats:
        raise HTTPException(status_code=404, detail="User not found")
    
    return stats

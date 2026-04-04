"""
Authentication API Endpoints.

Provides user registration, login, and session management.

AUDIT-19: 401 responses include an ``expired`` boolean so the frontend
can distinguish an expired session (→ "Session expired, please log in
again") from a missing / malformed token (→ generic auth error).
A ``POST /api/v1/auth/session/refresh`` endpoint allows the frontend to
extend a valid session near its expiry without forcing a full re-login.
"""

from __future__ import annotations

import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Header, Response
from pydantic import BaseModel, EmailStr, Field

from auth.user_manager import user_manager
from utils.logger import get_logger
from utils.deps import require_dependency

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
logger = get_logger("web.api.auth")

# Ensure email validation stack is available early so API fails fast if missing.
require_dependency("email_validator", feature="Email authentication")

# AUDIT-19: Window in which a session is considered "near expiry" and the
# client is advised to refresh (default: 1 hour before expiry).
_SESSION_REFRESH_WINDOW_SECONDS = 3600


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

    AUDIT-19: When the session exists but has expired the response includes
    ``"expired": true`` so the frontend can show a targeted "Session expired,
    please log in again" message instead of a generic error.  The ``near_expiry``
    flag hints that the client should call ``POST /session/refresh`` soon.
    """
    if not session_id:
        raise HTTPException(
            status_code=401,
            detail={"message": "No session ID provided", "expired": False},
        )

    # Check expiry explicitly so we can set the `expired` flag.
    raw_session = user_manager._sessions.get(session_id)  # noqa: SLF001
    if raw_session is not None and not raw_session.is_valid():
        raise HTTPException(
            status_code=401,
            detail={"message": "Session expired. Please log in again.", "expired": True},
        )

    user = user_manager.validate_session(session_id)

    if not user:
        raise HTTPException(
            status_code=401,
            detail={"message": "Invalid or expired session", "expired": False},
        )

    near_expiry = user_manager.is_session_near_expiry(
        session_id, window_seconds=_SESSION_REFRESH_WINDOW_SECONDS
    )

    return {
        "status": "valid",
        "user": user.to_dict(),
        "near_expiry": near_expiry,
    }


@router.post("/session/refresh")
async def refresh_session(session_id: Optional[str] = Header(None, alias="X-Session-ID")):
    """Extend the lifetime of an existing valid session.

    AUDIT-19: Prevents silent 401 loops by allowing a short-lived token
    extension near expiry.  The same ``session_id`` token is reused — no
    re-login is required.

    Returns ``{"status": "refreshed", "expires_at": <unix timestamp>}``.
    Returns 401 with ``"expired": true`` if the session has already lapsed.
    """
    if not session_id:
        raise HTTPException(
            status_code=401,
            detail={"message": "No session ID provided", "expired": False},
        )

    session = user_manager.refresh_session(session_id)
    if session is None:
        raise HTTPException(
            status_code=401,
            detail={"message": "Session expired. Please log in again.", "expired": True},
        )

    return {
        "status": "refreshed",
        "expires_at": session.expires_at,
    }


@router.post("/logout")
async def logout(session_id: Optional[str] = Header(None, alias="X-Session-ID")):
    """
    Logout and invalidate session.
    """
    # In production, would remove session from storage
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

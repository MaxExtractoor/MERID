"""
User Authentication and Management System.

Supports multiple authentication methods:
- Wallet connection (MetaMask, WalletConnect)
- Email/password
- Social OAuth (Twitter, Google)
"""

from __future__ import annotations

import hashlib
import re
import secrets
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

from fastapi import Request as _FastAPIRequest

from utils.logger import get_logger

logger = get_logger("auth.user_manager")


@dataclass
class User:
    """User account model."""
    user_id: str
    username: str
    email: Optional[str] = None
    wallet_address: Optional[str] = None
    twitter_handle: Optional[str] = None
    password_hash: Optional[str] = None  # T-015: bcrypt hash
    role: str = "viewer"  # viewer | operator | admin
    created_at: float = field(default_factory=time.time)
    last_login: float = field(default_factory=time.time)
    referral_code: Optional[str] = None
    referred_by: Optional[str] = None
    total_referrals: int = 0
    is_active: bool = True
    is_verified: bool = False
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class Session:
    """User session model."""
    session_id: str
    user_id: str
    created_at: float
    expires_at: float
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    
    def is_valid(self) -> bool:
        return time.time() < self.expires_at
    
    def to_dict(self) -> Dict:
        return asdict(self)


class UserManager:
    """
    Production-grade user management system.
    
    In production, this would use a proper database (PostgreSQL, MongoDB).
    For now, using in-memory storage with persistence to JSON.
    """
    
    def __init__(self):
        self._users: Dict[str, User] = {}
        self._sessions: Dict[str, Session] = {}
        self._email_to_user: Dict[str, str] = {}
        self._wallet_to_user: Dict[str, str] = {}
        self._referral_to_user: Dict[str, str] = {}
        
        logger.info("UserManager initialized")
    
    def create_user(
        self,
        username: str,
        email: Optional[str] = None,
        wallet_address: Optional[str] = None,
        twitter_handle: Optional[str] = None,
        referred_by_code: Optional[str] = None
    ) -> User:
        """Create a new user account."""
        
        # Validate uniqueness
        if email and email in self._email_to_user:
            raise ValueError(f"Email {email} already registered")
        
        if wallet_address and wallet_address in self._wallet_to_user:
            raise ValueError(f"Wallet {wallet_address} already registered")
        
        # Generate user ID
        user_id = self._generate_user_id()
        
        # Generate unique referral code
        referral_code = self._generate_referral_code(username)
        
        # Handle referral
        referred_by_user_id = None
        if referred_by_code and referred_by_code in self._referral_to_user:
            referred_by_user_id = self._referral_to_user[referred_by_code]
            # Increment referrer's count
            referrer = self._users[referred_by_user_id]
            referrer.total_referrals += 1
        
        # Create user
        user = User(
            user_id=user_id,
            username=username,
            email=email,
            wallet_address=wallet_address,
            twitter_handle=twitter_handle,
            referral_code=referral_code,
            referred_by=referred_by_user_id
        )
        
        # Store user
        self._users[user_id] = user
        
        if email:
            self._email_to_user[email] = user_id
        
        if wallet_address:
            self._wallet_to_user[wallet_address.lower()] = user_id
        
        self._referral_to_user[referral_code] = user_id
        
        logger.info(
            "User created: %s (email=%s, wallet=%s, referred_by=%s)",
            user_id, email, wallet_address, referred_by_code
        )
        
        return user
    
    def authenticate_wallet(self, wallet_address: str, signature: str, message: str) -> Optional[User]:
        """
        Authenticate user via wallet signature (T-016).
        Cryptographically verifies the signature using eth_account.
        """
        wallet_lower = wallet_address.lower()

        # T-016: Cryptographic wallet signature verification
        try:
            from eth_account.messages import encode_defunct
            from eth_account import Account
            msg = encode_defunct(text=message)
            recovered = Account.recover_message(msg, signature=signature).lower()
            if recovered != wallet_lower:
                logger.warning(
                    "Wallet signature mismatch: expected %s, recovered %s",
                    wallet_lower, recovered,
                )
                return None
        except ImportError:
            logger.error(
                "eth_account not installed — wallet auth BLOCKED (fail-closed). "
                "Install: pip install eth-account"
            )
            return None
        except Exception as exc:
            logger.warning("Wallet signature verification failed: %s", exc)
            return None

        user_id = self._wallet_to_user.get(wallet_lower)
        if not user_id:
            logger.warning(
                "Wallet %s not registered. Use explicit registration flow.",
                wallet_address,
            )
            return None

        user = self._users[user_id]
        user.last_login = time.time()

        logger.info("Wallet authentication successful (signature verified): %s", wallet_address)
        return user
    
    @staticmethod
    def _validate_password_complexity(password: str) -> Optional[str]:
        """T-015: Enforce password complexity (min 12 chars, mixed case, number, special)."""
        if len(password) < 12:
            return "Password must be at least 12 characters"
        if not re.search(r'[A-Z]', password):
            return "Password must contain an uppercase letter"
        if not re.search(r'[a-z]', password):
            return "Password must contain a lowercase letter"
        if not re.search(r'[0-9]', password):
            return "Password must contain a digit"
        if not re.search(r'[^A-Za-z0-9]', password):
            return "Password must contain a special character"
        return None

    def set_password(self, user_id: str, password: str) -> bool:
        """T-015: Hash and store password using bcrypt."""
        user = self._users.get(user_id)
        if not user:
            return False
        complexity_err = self._validate_password_complexity(password)
        if complexity_err:
            raise ValueError(complexity_err)
        try:
            from passlib.hash import bcrypt
            user.password_hash = bcrypt.hash(password)
            return True
        except ImportError:
            logger.error("passlib not installed — cannot hash password. Install: pip install passlib[bcrypt]")
            return False

    def authenticate_email(self, email: str, password: str) -> Optional[User]:
        """
        Authenticate user via email/password (T-015).
        Uses bcrypt for secure password verification.
        """
        user_id = self._email_to_user.get(email)
        if not user_id:
            return None

        user = self._users[user_id]

        if not user.password_hash:
            logger.warning("User %s has no password hash set — auth denied", email)
            return None

        try:
            from passlib.hash import bcrypt
            if not bcrypt.verify(password, user.password_hash):
                logger.warning("Password verification failed for %s", email)
                return None
        except ImportError:
            logger.error("passlib not installed — email auth BLOCKED. Install: pip install passlib[bcrypt]")
            return None
        except Exception as exc:
            logger.warning("Password verification error for %s: %s", email, exc)
            return None

        user.last_login = time.time()
        logger.info("Email authentication successful (bcrypt verified): %s", email)
        return user
    
    def create_session(
        self,
        user_id: str,
        duration_seconds: int = 86400,  # 24 hours
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Session:
        """Create a new user session."""
        session_id = secrets.token_urlsafe(32)
        
        session = Session(
            session_id=session_id,
            user_id=user_id,
            created_at=time.time(),
            expires_at=time.time() + duration_seconds,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        self._sessions[session_id] = session
        
        logger.info("Session created for user %s: %s", user_id, session_id)
        return session
    
    def validate_session(self, session_id: str) -> Optional[User]:
        """Validate session and return user if valid."""
        session = self._sessions.get(session_id)
        
        if not session or not session.is_valid():
            return None
        
        user = self._users.get(session.user_id)
        return user

    def invalidate_session(self, session_id: str) -> bool:
        """Remove session from storage, preventing further use (logout)."""
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info("Session invalidated: %s", session_id)
            return True
        return False
    
    def get_user(self, user_id: str) -> Optional[User]:
        """Get user by ID."""
        return self._users.get(user_id)
    
    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email."""
        user_id = self._email_to_user.get(email)
        return self._users.get(user_id) if user_id else None
    
    def get_user_by_wallet(self, wallet_address: str) -> Optional[User]:
        """Get user by wallet address."""
        user_id = self._wallet_to_user.get(wallet_address.lower())
        return self._users.get(user_id) if user_id else None
    
    def get_referral_stats(self, user_id: str) -> Dict:
        """Get referral statistics for a user."""
        user = self._users.get(user_id)
        if not user:
            return {}
        
        return {
            "referral_code": user.referral_code,
            "total_referrals": user.total_referrals,
            "referred_by": user.referred_by
        }
    
    def _generate_user_id(self) -> str:
        """Generate unique user ID."""
        return f"user_{secrets.token_hex(8)}"
    
    def _generate_referral_code(self, username: str) -> str:
        """Generate unique referral code."""
        # Create code from username + random suffix
        base = username.upper().replace(" ", "")[:6]
        suffix = secrets.token_hex(2).upper()
        code = f"{base}{suffix}"
        
        # Ensure uniqueness
        while code in self._referral_to_user:
            suffix = secrets.token_hex(2).upper()
            code = f"{base}{suffix}"
        
        return code


# Global singleton
user_manager = UserManager()


# ── T-018 / T-019: FastAPI auth dependencies ────────────────────────────

def _is_dev_bypass() -> bool:
    """Check if dev auth bypass is active (mirrors web.api.auth.get_current_session logic)."""
    import os
    dev_mode = os.getenv("MERID_ENV", "development").lower() in ("development", "dev", "local")
    if not dev_mode or os.getenv("MERID_DEV_AUTH_BYPASS") == "0":
        return False
    live_trading = (
        os.getenv("MERID_PM_LIVE_ENABLED", "false").lower() in ("1", "true", "yes")
        or os.getenv("MERID_TRADE_MODE", "").lower() == "live"
        or os.getenv("MERID_PM_TRADING_MODE", "").lower() == "live"
    )
    return not live_trading


def _get_session_id(request: _FastAPIRequest) -> Optional[str]:
    """Extract session ID from Authorization header or X-Session-ID."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:]
    return request.headers.get("X-Session-ID")


def get_current_user(request: _FastAPIRequest):
    """T-018: FastAPI dependency — validates session and returns User.
    Usage: `user = Depends(get_current_user)`
    """
    import os
    from fastapi import HTTPException

    # Test bypass
    if os.getenv("MERID_SKIP_AUTH_FOR_TESTS") == "1":
        return User(user_id="test_user", username="test", role="admin")

    # Single-user operator mode: sole local owner, no auth required
    if os.getenv("MERID_SINGLE_USER_OPERATOR") == "1":
        return User(user_id="operator", username="operator", role="admin")

    # Dev bypass — return a synthetic operator user so require_role works
    if _is_dev_bypass():
        return User(user_id="dev_user", username="developer", role="operator")

    sid = _get_session_id(request)
    if not sid:
        raise HTTPException(status_code=401, detail="Missing session token")
    user = user_manager.validate_session(sid)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account deactivated")
    return user


def require_role(*roles: str):
    """T-019: FastAPI dependency factory — enforces RBAC.
    Usage: `user = Depends(require_role("operator", "admin"))`
    """
    def _dependency(request: _FastAPIRequest):
        from fastapi import HTTPException
        user = get_current_user(request)
        if user.role not in roles:
            raise HTTPException(
                status_code=403,
                detail=f"Requires role {roles}, have {user.role}",
            )
        return user
    return _dependency

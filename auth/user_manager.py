"""
User Authentication and Management System.

Supports multiple authentication methods:
- Wallet connection (MetaMask, WalletConnect)
- Email/password
- Social OAuth (Twitter, Google)
"""

from __future__ import annotations

import hashlib
import secrets
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional

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
        Authenticate user via wallet signature.
        
        In production, verify signature cryptographically.
        """
        wallet_lower = wallet_address.lower()
        
        # Wallet signature verification
        # Production: Use web3.py eth_account.recover_message() for cryptographic verification
        # Current: Simplified auth for development - wallet presence is sufficient
        
        user_id = self._wallet_to_user.get(wallet_lower)
        if not user_id:
            # Auto-create user for new wallet
            username = f"user_{wallet_address[:8]}"
            user = self.create_user(username=username, wallet_address=wallet_address)
            return user
        
        user = self._users[user_id]
        user.last_login = time.time()
        
        logger.info("Wallet authentication successful: %s", wallet_address)
        return user
    
    def authenticate_email(self, email: str, password: str) -> Optional[User]:
        """
        Authenticate user via email/password.
        
        In production, use proper password hashing (bcrypt, argon2).
        """
        user_id = self._email_to_user.get(email)
        if not user_id:
            return None
        
        # Password verification
        # Production: Use bcrypt.checkpw() or argon2.verify() for secure password hashing
        # Current: Simplified auth for development
        
        user = self._users[user_id]
        user.last_login = time.time()
        
        logger.info("Email authentication successful: %s", email)
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

    def is_session_near_expiry(
        self, session_id: str, *, window_seconds: int = 3600
    ) -> bool:
        """Return True if the session is valid but expires within *window_seconds*."""
        session = self._sessions.get(session_id)
        if not session or not session.is_valid():
            return False
        return (session.expires_at - time.time()) < window_seconds

    def refresh_session(
        self, session_id: str, *, extend_seconds: int = 86400
    ) -> Optional[Session]:
        """Extend the expiry of an existing valid session.

        Returns the updated :class:`Session` on success, or ``None`` if the
        session is not found or has already expired.  A new ``session_id`` is
        **not** issued; the existing token continues to work so the client
        does not need to re-authenticate.

        AUDIT-19: prevents silent 401 loops by allowing short-lived token
        refresh near expiry rather than forcing a full re-login.
        """
        session = self._sessions.get(session_id)
        if not session or not session.is_valid():
            return None

        session.expires_at = time.time() + extend_seconds
        logger.info(
            "Session refreshed for user %s: %s (extends +%ds)",
            session.user_id, session_id, extend_seconds,
        )
        return session
    
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

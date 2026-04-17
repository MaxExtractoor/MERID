"""
WalletConnect Integration.

Provides WalletConnect v2 support for connecting external wallets
via QR code scanning.

Version: 1.0.0
"""

from __future__ import annotations

import threading
import time
import secrets
import json
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum

from utils.logger import get_logger

logger = get_logger("wallet.wallet_connect")


class SessionStatus(Enum):
    """Status of a WalletConnect session."""
    PENDING = "pending"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    EXPIRED = "expired"
    REJECTED = "rejected"


class ChainNamespace(Enum):
    """Supported chain namespaces."""
    EIP155 = "eip155"  # Ethereum and EVM chains
    SOLANA = "solana"
    COSMOS = "cosmos"


@dataclass
class WalletConnectSession:
    """A WalletConnect session."""
    session_id: str
    status: SessionStatus = SessionStatus.PENDING
    
    # Connection info
    topic: str = ""
    relay_url: str = "wss://relay.walletconnect.com"
    
    # Wallet info
    wallet_name: str = ""
    wallet_address: str = ""
    chain_id: int = 1  # Ethereum mainnet
    namespace: ChainNamespace = ChainNamespace.EIP155
    
    # Permissions
    allowed_methods: List[str] = field(default_factory=lambda: [
        "eth_sendTransaction",
        "eth_signTransaction",
        "eth_sign",
        "personal_sign",
        "eth_signTypedData",
    ])
    allowed_events: List[str] = field(default_factory=lambda: [
        "chainChanged",
        "accountsChanged",
    ])
    
    # QR code
    uri: str = ""
    qr_data: str = ""
    
    # Timing
    created_at: float = field(default_factory=time.time)
    connected_at: Optional[float] = None
    expires_at: float = field(default_factory=lambda: time.time() + 300)  # 5 min
    last_activity: float = field(default_factory=time.time)
    
    # Metadata
    app_name: str = "MERID"
    app_description: str = "Autonomous Trading System"
    app_url: str = "https://merid.local"
    app_icons: List[str] = field(default_factory=list)
    
    def is_expired(self) -> bool:
        return time.time() > self.expires_at
    
    def is_connected(self) -> bool:
        return self.status == SessionStatus.CONNECTED and not self.is_expired()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "status": self.status.value,
            "topic": self.topic,
            "wallet_name": self.wallet_name,
            "wallet_address": self.wallet_address,
            "chain_id": self.chain_id,
            "namespace": self.namespace.value,
            "uri": self.uri,
            "created_at": self.created_at,
            "connected_at": self.connected_at,
            "expires_at": self.expires_at,
            "is_connected": self.is_connected(),
            "allowed_methods": self.allowed_methods,
        }


@dataclass
class SignRequest:
    """A signing request."""
    request_id: str
    session_id: str
    method: str
    params: Dict[str, Any]
    status: str = "pending"
    result: Optional[str] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "session_id": self.session_id,
            "method": self.method,
            "params": self.params,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


class WalletConnectManager:
    """
    Manages WalletConnect v2 sessions.
    
    Features:
    - QR code generation for pairing
    - Session management
    - Transaction signing requests
    - Multi-chain support
    """
    
    def __init__(self):
        self.logger = get_logger("wallet.wallet_connect")
        
        # Sessions
        self._sessions: Dict[str, WalletConnectSession] = {}
        
        # Pending sign requests
        self._sign_requests: Dict[str, SignRequest] = {}
        
        # Callbacks
        self._on_connect_callbacks: List[Callable[[WalletConnectSession], None]] = []
        self._on_disconnect_callbacks: List[Callable[[str], None]] = []
        self._on_sign_request_callbacks: List[Callable[[SignRequest], None]] = []
        
        # Configuration
        self._project_id: str = ""  # WalletConnect Cloud project ID
        self._supported_chains: List[int] = [1, 137, 42161, 10, 8453]  # ETH, Polygon, Arb, OP, Base
    
    def set_project_id(self, project_id: str) -> None:
        """Set WalletConnect Cloud project ID."""
        self._project_id = project_id
        self.logger.info("WalletConnect project ID configured")
    
    def create_session(
        self,
        chain_id: int = 1,
        namespace: ChainNamespace = ChainNamespace.EIP155,
    ) -> WalletConnectSession:
        """Create a new WalletConnect session with QR code."""
        session_id = f"wc_{secrets.token_hex(16)}"
        topic = secrets.token_hex(32)
        sym_key = secrets.token_hex(32)
        
        # Generate WalletConnect URI
        # Format: wc:{topic}@2?relay-protocol=irn&symKey={symKey}
        uri = f"wc:{topic}@2?relay-protocol=irn&symKey={sym_key}"
        
        if self._project_id:
            uri += f"&projectId={self._project_id}"
        
        session = WalletConnectSession(
            session_id=session_id,
            topic=topic,
            chain_id=chain_id,
            namespace=namespace,
            uri=uri,
            qr_data=uri,
        )
        
        self._sessions[session_id] = session
        self.logger.info(f"Created WalletConnect session: {session_id}")
        
        return session
    
    def get_session(self, session_id: str) -> Optional[WalletConnectSession]:
        """Get a session by ID."""
        return self._sessions.get(session_id)
    
    def get_active_sessions(self) -> List[WalletConnectSession]:
        """Get all active sessions."""
        return [s for s in self._sessions.values() if s.is_connected()]
    
    def connect_session(
        self,
        session_id: str,
        wallet_address: str,
        wallet_name: str = "",
        chain_id: Optional[int] = None,
    ) -> bool:
        """Mark a session as connected (called when wallet responds)."""
        session = self._sessions.get(session_id)
        if not session:
            return False
        
        session.status = SessionStatus.CONNECTED
        session.wallet_address = wallet_address
        session.wallet_name = wallet_name
        session.connected_at = time.time()
        session.expires_at = time.time() + 86400  # 24 hours
        
        if chain_id:
            session.chain_id = chain_id
        
        # Notify callbacks
        for callback in self._on_connect_callbacks:
            try:
                callback(session)
            except Exception as e:
                self.logger.error(f"Connect callback error: {e}")
        
        self.logger.info(f"Session connected: {session_id} - {wallet_address}")
        return True
    
    def disconnect_session(self, session_id: str) -> bool:
        """Disconnect a session."""
        session = self._sessions.get(session_id)
        if not session:
            return False
        
        session.status = SessionStatus.DISCONNECTED
        
        # Notify callbacks
        for callback in self._on_disconnect_callbacks:
            try:
                callback(session_id)
            except Exception as e:
                self.logger.error(f"Disconnect callback error: {e}")
        
        self.logger.info(f"Session disconnected: {session_id}")
        return True
    
    def request_sign(
        self,
        session_id: str,
        method: str,
        params: Dict[str, Any],
    ) -> Optional[str]:
        """Request a signature from the connected wallet."""
        session = self._sessions.get(session_id)
        if not session or not session.is_connected():
            self.logger.error("Session not connected")
            return None
        
        if method not in session.allowed_methods:
            self.logger.error(f"Method not allowed: {method}")
            return None
        
        request_id = f"req_{secrets.token_hex(8)}"
        
        request = SignRequest(
            request_id=request_id,
            session_id=session_id,
            method=method,
            params=params,
        )
        
        self._sign_requests[request_id] = request
        
        # Notify callbacks
        for callback in self._on_sign_request_callbacks:
            try:
                callback(request)
            except Exception as e:
                self.logger.error(f"Sign request callback error: {e}")
        
        self.logger.info(f"Sign request created: {request_id} - {method}")
        return request_id
    
    def complete_sign_request(
        self,
        request_id: str,
        result: Optional[str] = None,
        error: Optional[str] = None,
    ) -> bool:
        """Complete a sign request with result or error."""
        request = self._sign_requests.get(request_id)
        if not request:
            return False
        
        if result:
            request.status = "completed"
            request.result = result
        elif error:
            request.status = "failed"
            request.error = error
        else:
            request.status = "rejected"
        
        request.completed_at = time.time()
        
        self.logger.info(f"Sign request completed: {request_id} - {request.status}")
        return True
    
    def get_sign_request(self, request_id: str) -> Optional[SignRequest]:
        """Get a sign request."""
        return self._sign_requests.get(request_id)
    
    def get_pending_requests(self, session_id: Optional[str] = None) -> List[SignRequest]:
        """Get pending sign requests."""
        requests = [r for r in self._sign_requests.values() if r.status == "pending"]
        if session_id:
            requests = [r for r in requests if r.session_id == session_id]
        return requests
    
    def on_connect(self, callback: Callable[[WalletConnectSession], None]) -> None:
        """Register callback for session connection."""
        self._on_connect_callbacks.append(callback)
    
    def on_disconnect(self, callback: Callable[[str], None]) -> None:
        """Register callback for session disconnection."""
        self._on_disconnect_callbacks.append(callback)
    
    def on_sign_request(self, callback: Callable[[SignRequest], None]) -> None:
        """Register callback for sign requests."""
        self._on_sign_request_callbacks.append(callback)
    
    def cleanup_expired(self) -> int:
        """Clean up expired sessions."""
        expired = [
            sid for sid, s in self._sessions.items()
            if s.is_expired() and s.status != SessionStatus.CONNECTED
        ]
        
        for sid in expired:
            self._sessions[sid].status = SessionStatus.EXPIRED
        
        return len(expired)
    
    def get_status(self) -> Dict[str, Any]:
        """Get WalletConnect manager status."""
        return {
            "project_id_configured": bool(self._project_id),
            "total_sessions": len(self._sessions),
            "active_sessions": len(self.get_active_sessions()),
            "pending_requests": len(self.get_pending_requests()),
            "supported_chains": self._supported_chains,
            "sessions": [s.to_dict() for s in self._sessions.values()],
        }


# Singleton
_wallet_connect_manager: Optional[WalletConnectManager] = None
_wallet_connect_manager_lock = threading.Lock()


def get_wallet_connect_manager() -> WalletConnectManager:
    """Get or create the WalletConnect Manager singleton."""
    global _wallet_connect_manager
    if _wallet_connect_manager is None:
        with _wallet_connect_manager_lock:
            if _wallet_connect_manager is None:
                _wallet_connect_manager = WalletConnectManager()
    return _wallet_connect_manager

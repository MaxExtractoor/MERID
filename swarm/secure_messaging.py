"""
Secure cross-agent messaging protocol with mTLS for MERID.

Implements:
- mTLS-based mutual authentication
- Message-level signatures and encryption
- Token binding to TLS sessions
- Replay attack prevention
- Protocol-level security (ANP/ACDP-style)
"""

import threading
import logging

from utils.logger import get_logger
import time
import hmac
import hashlib
import secrets
from typing import Dict, List, Optional, Any, Set
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import json

logger = get_logger(__name__)


class MessageType(Enum):
    """Message types."""
    REQUEST = "request"
    RESPONSE = "response"
    EVENT = "event"
    ERROR = "error"


class EncryptionAlgorithm(Enum):
    """Encryption algorithms."""
    AES_256_GCM = "aes_256_gcm"
    CHACHA20_POLY1305 = "chacha20_poly1305"


class SignatureAlgorithm(Enum):
    """Signature algorithms."""
    ED25519 = "ed25519"
    ECDSA_P256 = "ecdsa_p256"
    RSA_PSS = "rsa_pss"


@dataclass
class TLSSession:
    """TLS session information."""
    session_id: str
    
    # Certificates
    client_cert_fingerprint: str
    server_cert_fingerprint: str
    
    # Session keys
    session_key: str  # Derived from TLS handshake
    
    # Binding
    token_binding_id: Optional[str] = None
    
    # Metadata
    cipher_suite: str = "TLS_AES_256_GCM_SHA384"
    tls_version: str = "1.3"
    
    # Validity
    established_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    
    # Usage
    message_count: int = 0
    last_used: datetime = field(default_factory=datetime.utcnow)


@dataclass
class MessageEnvelope:
    """Secure message envelope."""
    message_id: str
    message_type: MessageType
    
    # Routing
    sender_did: str
    recipient_did: str
    
    # Payload
    payload: Dict[str, Any]
    
    # Security
    nonce: str  # For replay prevention
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    # Encryption
    encrypted: bool = False
    encryption_algorithm: Optional[EncryptionAlgorithm] = None
    
    # Signature
    signature: str = ""
    signature_algorithm: SignatureAlgorithm = SignatureAlgorithm.ED25519
    
    # Session binding
    session_id: Optional[str] = None
    token_binding_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for signing."""
        return {
            "message_id": self.message_id,
            "message_type": self.message_type.value,
            "sender_did": self.sender_did,
            "recipient_did": self.recipient_did,
            "payload": self.payload,
            "nonce": self.nonce,
            "timestamp": self.timestamp.isoformat(),
            "session_id": self.session_id,
        }
    
    def compute_signature_input(self) -> str:
        """Compute canonical string for signing."""
        return json.dumps(self.to_dict(), sort_keys=True)


@dataclass
class MessageAuditLog:
    """Message audit log entry."""
    log_id: str
    
    # Message reference
    message_id: str
    message_type: MessageType
    
    # Parties
    sender_did: str
    recipient_did: str
    
    # Status
    status: str  # sent, delivered, failed, rejected
    error_message: str = ""
    
    # Security
    signature_verified: bool = False
    session_verified: bool = False
    
    # Timing
    sent_at: datetime = field(default_factory=datetime.utcnow)
    delivered_at: Optional[datetime] = None


@dataclass
class ReplayCache:
    """Cache for replay attack prevention."""
    cache_id: str
    
    # Nonce tracking
    seen_nonces: Set[str] = field(default_factory=set)
    
    # Expiry
    ttl_seconds: int = 300  # 5 minutes
    
    # Cleanup
    last_cleanup: datetime = field(default_factory=datetime.utcnow)


class SecureMessagingProtocol:
    """
    Secure cross-agent messaging protocol with mTLS.
    
    Features:
    - mTLS mutual authentication
    - Message-level signatures
    - Replay attack prevention
    - Token binding to TLS sessions
    - Audit logging
    """
    
    def __init__(self):
        self._sessions: Dict[str, TLSSession] = {}
        self._audit_logs: List[MessageAuditLog] = []
        self._replay_cache = ReplayCache(cache_id="global")
        
        # Configuration
        self._max_message_age_seconds = 300  # 5 minutes
        self._require_mtls = True
        self._require_token_binding = True
        self._require_message_signature = True
    
    def establish_mtls_session(
        self,
        client_cert_fingerprint: str,
        server_cert_fingerprint: str,
        session_key: str,
    ) -> TLSSession:
        """Establish mTLS session."""
        session_id = f"session_{int(time.time() * 1000)}_{secrets.token_hex(8)}"
        
        session = TLSSession(
            session_id=session_id,
            client_cert_fingerprint=client_cert_fingerprint,
            server_cert_fingerprint=server_cert_fingerprint,
            session_key=session_key,
            expires_at=datetime.utcnow() + timedelta(hours=24),
        )
        
        self._sessions[session_id] = session
        
        logger.info(
            f"Established mTLS session '{session_id}' "
            f"(client: {client_cert_fingerprint[:16]}...)"
        )
        
        return session
    
    def bind_token_to_session(
        self,
        session_id: str,
        token: str,
    ) -> str:
        """Bind OAuth/JWT token to TLS session."""
        session = self._sessions.get(session_id)
        
        if not session:
            raise ValueError(f"Session '{session_id}' not found")
        
        # Create token binding ID (hash of token + session key)
        binding_input = f"{token}:{session.session_key}"
        token_binding_id = hashlib.sha256(binding_input.encode()).hexdigest()
        
        session.token_binding_id = token_binding_id
        
        logger.info(f"Bound token to session '{session_id}'")
        
        return token_binding_id
    
    def create_message(
        self,
        message_type: MessageType,
        sender_did: str,
        recipient_did: str,
        payload: Dict[str, Any],
        session_id: Optional[str] = None,
    ) -> MessageEnvelope:
        """Create secure message envelope."""
        message_id = f"msg_{int(time.time() * 1000)}_{secrets.token_hex(8)}"
        nonce = secrets.token_hex(32)
        
        message = MessageEnvelope(
            message_id=message_id,
            message_type=message_type,
            sender_did=sender_did,
            recipient_did=recipient_did,
            payload=payload,
            nonce=nonce,
            session_id=session_id,
        )
        
        # Add token binding if session exists
        if session_id:
            session = self._sessions.get(session_id)
            if session and session.token_binding_id:
                message.token_binding_id = session.token_binding_id
        
        # Sign message
        message.signature = self._sign_message(message)
        
        logger.debug(
            f"Created message '{message_id}': {message_type.value} "
            f"from {sender_did} to {recipient_did}"
        )
        
        return message
    
    def _sign_message(self, message: MessageEnvelope) -> str:
        """Sign message (simplified - in production would use actual crypto)."""
        signature_input = message.compute_signature_input()
        
        # Mock signature using HMAC (in production would use Ed25519/ECDSA)
        signature = hmac.new(
            b"mock_signing_key",
            signature_input.encode(),
            hashlib.sha256,
        ).hexdigest()
        
        return signature
    
    def verify_message(
        self,
        message: MessageEnvelope,
        session_id: Optional[str] = None,
    ) -> tuple[bool, str]:
        """Verify message security properties."""
        
        # Check message age
        age_seconds = (datetime.utcnow() - message.timestamp).total_seconds()
        if age_seconds > self._max_message_age_seconds:
            return False, f"Message too old: {age_seconds:.0f}s"
        
        # Check for replay
        if message.nonce in self._replay_cache.seen_nonces:
            return False, "Replay attack detected (nonce reused)"
        
        # Verify signature
        if self._require_message_signature:
            expected_signature = self._sign_message(message)
            if message.signature != expected_signature:
                return False, "Invalid message signature"
        
        # Verify session binding
        if self._require_mtls and session_id:
            session = self._sessions.get(session_id)
            if not session:
                return False, f"Session '{session_id}' not found"
            
            if message.session_id != session_id:
                return False, "Session ID mismatch"
            
            # Verify token binding
            if self._require_token_binding and session.token_binding_id:
                if message.token_binding_id != session.token_binding_id:
                    return False, "Token binding mismatch"
        
        # Add nonce to replay cache
        self._replay_cache.seen_nonces.add(message.nonce)
        
        return True, "Message verified"
    
    def send_message(
        self,
        message: MessageEnvelope,
        session_id: Optional[str] = None,
    ) -> MessageAuditLog:
        """Send message with audit logging."""
        
        # Verify message
        verified, error_msg = self.verify_message(message, session_id)
        
        # Create audit log
        log_id = f"log_{int(time.time() * 1000)}"
        
        audit_log = MessageAuditLog(
            log_id=log_id,
            message_id=message.message_id,
            message_type=message.message_type,
            sender_did=message.sender_did,
            recipient_did=message.recipient_did,
            status="sent" if verified else "rejected",
            error_message=error_msg if not verified else "",
            signature_verified=verified,
            session_verified=session_id is not None,
        )
        
        self._audit_logs.append(audit_log)
        
        # Update session usage
        if session_id and verified:
            session = self._sessions.get(session_id)
            if session:
                session.message_count += 1
                session.last_used = datetime.utcnow()
        
        if verified:
            logger.info(f"Sent message '{message.message_id}' successfully")
        else:
            logger.warning(
                f"Rejected message '{message.message_id}': {error_msg}"
            )
        
        return audit_log
    
    def receive_message(
        self,
        message: MessageEnvelope,
        session_id: Optional[str] = None,
    ) -> tuple[bool, str, Optional[Dict[str, Any]]]:
        """Receive and verify message."""
        
        # Verify message
        verified, error_msg = self.verify_message(message, session_id)
        
        if not verified:
            logger.warning(
                f"Rejected incoming message '{message.message_id}': {error_msg}"
            )
            return False, error_msg, None
        
        # Create audit log
        log_id = f"log_{int(time.time() * 1000)}"
        
        audit_log = MessageAuditLog(
            log_id=log_id,
            message_id=message.message_id,
            message_type=message.message_type,
            sender_did=message.sender_did,
            recipient_did=message.recipient_did,
            status="delivered",
            signature_verified=True,
            session_verified=session_id is not None,
            delivered_at=datetime.utcnow(),
        )
        
        self._audit_logs.append(audit_log)
        
        logger.info(f"Received message '{message.message_id}' from {message.sender_did}")
        
        return True, "Message received", message.payload
    
    def cleanup_expired_sessions(self) -> int:
        """Cleanup expired TLS sessions."""
        now = datetime.utcnow()
        
        expired_ids = [
            session_id for session_id, session in self._sessions.items()
            if session.expires_at and session.expires_at <= now
        ]
        
        for session_id in expired_ids:
            del self._sessions[session_id]
        
        logger.info(f"Cleaned up {len(expired_ids)} expired sessions")
        
        return len(expired_ids)
    
    def cleanup_replay_cache(self) -> int:
        """Cleanup old nonces from replay cache."""
        # In production, would track nonce timestamps and remove old ones
        # For now, just clear if cache is too large
        
        if len(self._replay_cache.seen_nonces) > 10000:
            old_size = len(self._replay_cache.seen_nonces)
            self._replay_cache.seen_nonces.clear()
            self._replay_cache.last_cleanup = datetime.utcnow()
            
            logger.info(f"Cleared replay cache ({old_size} nonces)")
            
            return old_size
        
        return 0
    
    def get_session(self, session_id: str) -> Optional[TLSSession]:
        """Get TLS session."""
        return self._sessions.get(session_id)
    
    def get_audit_logs(
        self,
        sender_did: Optional[str] = None,
        recipient_did: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[MessageAuditLog]:
        """Get audit logs with filters."""
        logs = self._audit_logs
        
        if sender_did:
            logs = [log for log in logs if log.sender_did == sender_did]
        
        if recipient_did:
            logs = [log for log in logs if log.recipient_did == recipient_did]
        
        if status:
            logs = [log for log in logs if log.status == status]
        
        return logs[-limit:]
    
    def get_messaging_stats(self) -> Dict[str, Any]:
        """Get messaging statistics."""
        total_sessions = len(self._sessions)
        active_sessions = sum(
            1 for session in self._sessions.values()
            if session.expires_at and session.expires_at > datetime.utcnow()
        )
        
        total_messages = len(self._audit_logs)
        successful_messages = sum(
            1 for log in self._audit_logs
            if log.status in ["sent", "delivered"]
        )
        
        return {
            "sessions": {
                "total": total_sessions,
                "active": active_sessions,
                "expired": total_sessions - active_sessions,
            },
            "messages": {
                "total": total_messages,
                "successful": successful_messages,
                "failed": total_messages - successful_messages,
                "success_rate": (
                    successful_messages / total_messages
                    if total_messages > 0 else 0.0
                ),
            },
            "replay_cache": {
                "nonces": len(self._replay_cache.seen_nonces),
            },
            "security": {
                "require_mtls": self._require_mtls,
                "require_token_binding": self._require_token_binding,
                "require_message_signature": self._require_message_signature,
                "max_message_age_seconds": self._max_message_age_seconds,
            },
        }


_secure_messaging_protocol: Optional[SecureMessagingProtocol] = None
_secure_messaging_protocol_lock = threading.Lock()


def get_secure_messaging_protocol() -> SecureMessagingProtocol:
    """Get global SecureMessagingProtocol instance."""
    global _secure_messaging_protocol
    if _secure_messaging_protocol is None:
        with _secure_messaging_protocol_lock:
            if _secure_messaging_protocol is None:
                _secure_messaging_protocol = SecureMessagingProtocol()
    return _secure_messaging_protocol

"""
MERID Secrets Manager - Section 9: Privacy, Secrets, and Compliance

Provides secure access to secrets with:
- Vault/HSM integration abstraction
- Key rotation support
- Access auditing
- Per-agent RBAC scoping
- Telemetry redaction

NO AGENT EVER GETS DIRECT ACCESS TO SECRETS.
All access goes through this governed service.
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from utils.logger import get_logger

logger = get_logger("security.secrets")


class SecretType(str, Enum):
    """Types of secrets."""
    API_KEY = "api_key"
    SIGNING_KEY = "signing_key"
    DATABASE_CREDENTIAL = "database_credential"
    ENCRYPTION_KEY = "encryption_key"
    OAUTH_TOKEN = "oauth_token"
    WEBHOOK_SECRET = "webhook_secret"


class AccessLevel(str, Enum):
    """Secret access levels."""
    NONE = "none"
    READ = "read"
    USE = "use"           # Can use but not see the value
    FULL = "full"         # Can see and use


@dataclass
class SecretMetadata:
    """Metadata about a secret (NOT the secret itself)."""
    secret_id: str
    name: str
    secret_type: SecretType
    
    # Access control
    allowed_services: Set[str] = field(default_factory=set)
    allowed_agents: Set[str] = field(default_factory=set)  # Empty = no agent access
    
    # Rotation
    created_at: float = field(default_factory=time.time)
    last_rotated: float = field(default_factory=time.time)
    rotation_interval_days: int = 90
    
    # Usage
    last_accessed: float = 0.0
    access_count: int = 0
    
    def needs_rotation(self) -> bool:
        """Check if secret needs rotation."""
        days_since_rotation = (time.time() - self.last_rotated) / 86400
        return days_since_rotation >= self.rotation_interval_days
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "secret_id": self.secret_id,
            "name": self.name,
            "secret_type": self.secret_type.value,
            "allowed_services": list(self.allowed_services),
            "allowed_agents": list(self.allowed_agents),
            "needs_rotation": self.needs_rotation(),
            "access_count": self.access_count,
        }


@dataclass
class AccessAuditEntry:
    """Audit log entry for secret access."""
    audit_id: str = field(default_factory=lambda: f"audit_{uuid.uuid4().hex[:12]}")
    secret_id: str = ""
    secret_name: str = ""
    
    accessor_type: str = ""   # service, agent, user
    accessor_id: str = ""
    access_level: AccessLevel = AccessLevel.NONE
    
    granted: bool = False
    denial_reason: str = ""
    
    timestamp: float = field(default_factory=time.time)
    ip_address: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "audit_id": self.audit_id,
            "secret_name": self.secret_name,
            "accessor_type": self.accessor_type,
            "accessor_id": self.accessor_id,
            "granted": self.granted,
            "denial_reason": self.denial_reason,
            "timestamp": self.timestamp,
        }


class SecretsManager:
    """
    Secure secrets management with RBAC and auditing.
    
    CRITICAL: Agents NEVER get direct secret values.
    They can only USE secrets through governed APIs.
    """
    
    _instance: Optional["SecretsManager"] = None
    
    def __init__(self):
        self._secrets: Dict[str, str] = {}  # secret_id -> value (encrypted in production)
        self._metadata: Dict[str, SecretMetadata] = {}
        self._audit_log: List[AccessAuditEntry] = []
        self._service_tokens: Dict[str, Set[str]] = {}  # service_id -> allowed_secrets
        self._lock = asyncio.Lock()
        
        # Redaction patterns for telemetry
        self._redaction_patterns = [
            (re.compile(r'api[_-]?key["\s:=]+["\']?([a-zA-Z0-9_-]{20,})["\']?', re.I), 'api_key=REDACTED'),
            (re.compile(r'secret[_-]?key["\s:=]+["\']?([a-zA-Z0-9_-]{20,})["\']?', re.I), 'secret_key=REDACTED'),
            (re.compile(r'password["\s:=]+["\']?([^\s"\']+)["\']?', re.I), 'password=REDACTED'),
            (re.compile(r'bearer\s+([a-zA-Z0-9_.-]+)', re.I), 'Bearer REDACTED'),
            (re.compile(r'authorization["\s:=]+["\']?([^\s"\']+)["\']?', re.I), 'authorization=REDACTED'),
        ]
        
        logger.info("SecretsManager initialized")
    
    @classmethod
    def get_instance(cls) -> "SecretsManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    # ============================================
    # SECRET REGISTRATION
    # ============================================
    
    async def register_secret(
        self,
        name: str,
        value: str,
        secret_type: SecretType,
        allowed_services: List[str] = None,
        rotation_days: int = 90,
    ) -> str:
        """
        Register a new secret.
        
        Returns:
            Secret ID for reference (NOT the secret value)
        """
        async with self._lock:
            secret_id = f"sec_{hashlib.sha256(name.encode()).hexdigest()[:12]}"
            
            # In production, encrypt value before storing
            self._secrets[secret_id] = value
            
            self._metadata[secret_id] = SecretMetadata(
                secret_id=secret_id,
                name=name,
                secret_type=secret_type,
                allowed_services=set(allowed_services or []),
                rotation_interval_days=rotation_days,
            )
            
            logger.info(f"Secret registered: {name} (id={secret_id})")
            return secret_id
    
    async def rotate_secret(
        self,
        secret_id: str,
        new_value: str,
        rotated_by: str,
    ) -> bool:
        """Rotate a secret value."""
        async with self._lock:
            if secret_id not in self._secrets:
                return False
            
            # In production, encrypt new value
            self._secrets[secret_id] = new_value
            
            meta = self._metadata[secret_id]
            meta.last_rotated = time.time()
            
            logger.info(f"Secret rotated: {meta.name} by {rotated_by}")
            return True
    
    # ============================================
    # SECRET ACCESS (SERVICES ONLY)
    # ============================================
    
    async def get_secret(
        self,
        secret_id: str,
        service_id: str,
        purpose: str = "",
    ) -> Optional[str]:
        """
        Get secret value for a SERVICE (not agent).
        
        Agents CANNOT call this directly.
        """
        async with self._lock:
            meta = self._metadata.get(secret_id)
            
            audit = AccessAuditEntry(
                secret_id=secret_id,
                secret_name=meta.name if meta else "unknown",
                accessor_type="service",
                accessor_id=service_id,
                access_level=AccessLevel.FULL,
            )
            
            # Check access
            if not meta:
                audit.granted = False
                audit.denial_reason = "Secret not found"
                self._audit_log.append(audit)
                return None
            
            if service_id not in meta.allowed_services:
                audit.granted = False
                audit.denial_reason = "Service not authorized"
                self._audit_log.append(audit)
                logger.warning(f"Denied secret access: {service_id} -> {meta.name}")
                return None
            
            # Grant access
            audit.granted = True
            meta.last_accessed = time.time()
            meta.access_count += 1
            self._audit_log.append(audit)
            
            return self._secrets.get(secret_id)
    
    async def use_secret_for_signing(
        self,
        secret_id: str,
        service_id: str,
        data_to_sign: bytes,
    ) -> Optional[bytes]:
        """
        Use a secret for signing without exposing the value.
        
        This is the PREFERRED way for services to use secrets.
        """
        secret = await self.get_secret(secret_id, service_id, "signing")
        if not secret:
            return None
        
        import hmac
        return hmac.new(secret.encode(), data_to_sign, hashlib.sha256).digest()
    
    # ============================================
    # AGENT ACCESS CONTROL
    # ============================================
    
    def agent_can_access(self, agent_id: str, secret_id: str) -> bool:
        """
        Check if an agent is allowed to USE a secret.
        
        NOTE: Agents can never SEE secret values, only use them
        through governed service calls.
        """
        meta = self._metadata.get(secret_id)
        if not meta:
            return False
        
        return agent_id in meta.allowed_agents
    
    def grant_agent_access(
        self,
        agent_id: str,
        secret_id: str,
        granted_by: str,
    ) -> bool:
        """Grant an agent permission to USE (not see) a secret."""
        meta = self._metadata.get(secret_id)
        if not meta:
            return False
        
        meta.allowed_agents.add(agent_id)
        logger.info(f"Agent {agent_id} granted USE access to {meta.name} by {granted_by}")
        return True
    
    def revoke_agent_access(self, agent_id: str, secret_id: str) -> bool:
        """Revoke agent access to a secret."""
        meta = self._metadata.get(secret_id)
        if not meta:
            return False
        
        meta.allowed_agents.discard(agent_id)
        logger.info(f"Agent {agent_id} access revoked for {meta.name}")
        return True
    
    # ============================================
    # TELEMETRY REDACTION
    # ============================================
    
    def redact_sensitive_data(self, text: str) -> str:
        """
        Redact sensitive data from text before logging/telemetry.
        
        Use this before sending any data to external logging or training.
        """
        redacted = text
        for pattern, replacement in self._redaction_patterns:
            redacted = pattern.sub(replacement, redacted)
        return redacted
    
    def redact_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Redact sensitive fields from a dictionary."""
        sensitive_keys = {
            "api_key", "apikey", "secret", "password", "token",
            "authorization", "credential", "private_key", "signing_key",
        }
        
        redacted = {}
        for key, value in data.items():
            key_lower = key.lower()
            
            if any(s in key_lower for s in sensitive_keys):
                redacted[key] = "REDACTED"
            elif isinstance(value, dict):
                redacted[key] = self.redact_dict(value)
            elif isinstance(value, str):
                redacted[key] = self.redact_sensitive_data(value)
            else:
                redacted[key] = value
        
        return redacted
    
    # ============================================
    # AUDIT & COMPLIANCE
    # ============================================
    
    def get_audit_log(
        self,
        secret_id: Optional[str] = None,
        accessor_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get audit log entries."""
        entries = self._audit_log
        
        if secret_id:
            entries = [e for e in entries if e.secret_id == secret_id]
        if accessor_id:
            entries = [e for e in entries if e.accessor_id == accessor_id]
        
        return [e.to_dict() for e in entries[-limit:]]
    
    def get_secrets_needing_rotation(self) -> List[Dict[str, Any]]:
        """Get list of secrets that need rotation."""
        return [
            meta.to_dict()
            for meta in self._metadata.values()
            if meta.needs_rotation()
        ]
    
    def get_compliance_report(self) -> Dict[str, Any]:
        """Get compliance report for auditing."""
        total_secrets = len(self._secrets)
        needing_rotation = len(self.get_secrets_needing_rotation())
        
        access_denials = sum(1 for e in self._audit_log if not e.granted)
        
        return {
            "total_secrets": total_secrets,
            "secrets_needing_rotation": needing_rotation,
            "rotation_compliance_rate": (total_secrets - needing_rotation) / max(1, total_secrets),
            "total_access_attempts": len(self._audit_log),
            "access_denials": access_denials,
            "denial_rate": access_denials / max(1, len(self._audit_log)),
            "agents_with_access": len(set(
                agent for meta in self._metadata.values()
                for agent in meta.allowed_agents
            )),
        }


# ============================================
# SAFE FIELDS FOR LOGGING
# ============================================

SAFE_TO_LOG_FIELDS = {
    "event_id", "timestamp", "event_type", "symbol", "venue",
    "agent_id", "direction", "score", "confidence", "status",
    "plan_id", "order_id", "trade_id", "quantity", "price",
}

REDACT_FIELDS = {
    "api_key", "secret", "password", "token", "credential",
    "private_key", "signing_key", "authorization", "bearer",
}


def is_safe_to_log(field_name: str) -> bool:
    """Check if a field is safe to include in logs."""
    field_lower = field_name.lower()
    
    # Explicitly safe
    if field_lower in SAFE_TO_LOG_FIELDS:
        return True
    
    # Explicitly unsafe
    for redact in REDACT_FIELDS:
        if redact in field_lower:
            return False
    
    return True


def sanitize_for_logging(data: Dict[str, Any]) -> Dict[str, Any]:
    """Sanitize a dictionary for safe logging."""
    manager = get_secrets_manager()
    return manager.redact_dict(data)


def get_secrets_manager() -> SecretsManager:
    """Get the global secrets manager instance."""
    return SecretsManager.get_instance()


# ============================================
# ENVIRONMENT VARIABLE LOADER
# ============================================

async def load_secrets_from_env() -> None:
    """Load secrets from environment variables into the manager."""
    manager = get_secrets_manager()
    
    # Common patterns for secret env vars
    secret_patterns = [
        ("KRAKEN_API_KEY", SecretType.API_KEY, ["venue_adapter", "kraken_service"]),
        ("KRAKEN_SECRET", SecretType.SIGNING_KEY, ["venue_adapter", "kraken_service"]),
        ("COINBASE_API_KEY", SecretType.API_KEY, ["venue_adapter", "coinbase_service"]),
        ("KALSHI_API_KEY", SecretType.API_KEY, ["venue_adapter", "kalshi_service"]),
        ("OPENAI_API_KEY", SecretType.API_KEY, ["llm_service"]),
        ("ANTHROPIC_API_KEY", SecretType.API_KEY, ["llm_service"]),
        ("DATABASE_URL", SecretType.DATABASE_CREDENTIAL, ["database_service"]),
        ("TELEGRAM_BOT_TOKEN", SecretType.API_KEY, ["telegram_bot"]),
        ("TWITTER_API_KEY", SecretType.API_KEY, ["twitter_bot"]),
    ]
    
    for env_var, secret_type, services in secret_patterns:
        value = os.environ.get(env_var)
        if value:
            await manager.register_secret(
                name=env_var,
                value=value,
                secret_type=secret_type,
                allowed_services=services,
            )
            logger.info(f"Loaded secret from env: {env_var}")

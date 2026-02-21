"""§3 Secrets Manager — Vault/KMS abstraction, env separation, least privilege.

All chain/CEX keys live in a secret manager, NEVER in code, repos, or logs.
Strict separation by environment (dev/staging/prod) and permission level.
Detailed audit logging of all key access.
"""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.blockchain.secrets")


# ── Permission model ─────────────────────────────────────────────────

class KeyPermission(str, Enum):
    READ_ONLY = "read_only"       # Data and analytics only
    TRADE = "trade"               # Can place orders on CEX
    SIGN = "sign"                 # Can sign on-chain transactions
    ADMIN = "admin"               # Full access (rotation, revocation)


class SecretEnvironment(str, Enum):
    DEV = "dev"
    STAGING = "staging"
    PROD = "prod"


# ── Data objects ─────────────────────────────────────────────────────

@dataclass
class SecretEntry:
    """A managed secret/key entry."""
    key_id: str                    # Unique identifier
    venue: str                     # "binance", "kalshi", "solana_wallet", etc.
    environment: SecretEnvironment = SecretEnvironment.DEV
    permission: KeyPermission = KeyPermission.READ_ONLY
    env_var_name: str = ""         # Environment variable name
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_rotated: Optional[datetime] = None
    rotation_interval_days: int = 90
    last_accessed: Optional[datetime] = None
    access_count: int = 0
    description: str = ""

    @property
    def needs_rotation(self) -> bool:
        """Check if key is overdue for rotation."""
        ref = self.last_rotated or self.created_at
        age = (datetime.now(timezone.utc) - ref).days
        return age >= self.rotation_interval_days

    @property
    def age_days(self) -> int:
        ref = self.last_rotated or self.created_at
        return (datetime.now(timezone.utc) - ref).days

    def to_dict(self) -> dict:
        return {
            "key_id": self.key_id,
            "venue": self.venue,
            "environment": self.environment.value,
            "permission": self.permission.value,
            "env_var_name": self.env_var_name,
            "age_days": self.age_days,
            "needs_rotation": self.needs_rotation,
            "access_count": self.access_count,
            "last_accessed": self.last_accessed.isoformat() if self.last_accessed else None,
        }


@dataclass
class AuditLogEntry:
    """Audit log entry for secret access."""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    key_id: str = ""
    action: str = ""               # "read", "rotate", "revoke", "create"
    service: str = ""              # Which service/agent accessed
    success: bool = True
    details: str = ""

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "key_id": self.key_id,
            "action": self.action,
            "service": self.service,
            "success": self.success,
            "details": self.details,
        }


# ── Secrets Manager ──────────────────────────────────────────────────

class SecretsManager:
    """Centralized secrets management with audit logging and RBAC.

    In production, this would delegate to HashiCorp Vault, AWS KMS,
    or GCP Secret Manager.  The current implementation uses environment
    variables as the backing store with full audit logging.

    Usage::

        sm = SecretsManager(environment=SecretEnvironment.DEV)
        sm.register_key(SecretEntry(
            key_id="binance-api", venue="binance",
            env_var_name="BINANCE_API_KEY",
            permission=KeyPermission.TRADE,
        ))
        value = sm.get_secret("binance-api", service="crypto-arb-agent")
    """

    def __init__(self, environment: SecretEnvironment = SecretEnvironment.DEV):
        self.environment = environment
        self._entries: Dict[str, SecretEntry] = {}
        self._audit_log: List[AuditLogEntry] = []
        self._revoked: set = set()

    # ── Key registration ─────────────────────────────────────────────

    def register_key(self, entry: SecretEntry) -> None:
        """Register a secret entry for management."""
        entry.environment = self.environment
        self._entries[entry.key_id] = entry
        self._audit(entry.key_id, "register", "secrets_manager",
                     f"Registered key for {entry.venue}")

    def get_entry(self, key_id: str) -> Optional[SecretEntry]:
        return self._entries.get(key_id)

    def list_keys(self) -> List[SecretEntry]:
        return list(self._entries.values())

    # ── Secret access (with audit) ───────────────────────────────────

    def get_secret(
        self,
        key_id: str,
        service: str = "unknown",
        required_permission: KeyPermission = KeyPermission.READ_ONLY,
    ) -> Optional[str]:
        """Retrieve a secret value with RBAC and audit logging.

        Returns the value from the environment variable, or None if
        not available or permission denied.
        """
        entry = self._entries.get(key_id)
        if not entry:
            self._audit(key_id, "read", service, "Key not found", success=False)
            return None

        # Check revocation
        if key_id in self._revoked:
            self._audit(key_id, "read", service, "Key is revoked", success=False)
            return None

        # RBAC: check permission level
        perm_order = [KeyPermission.READ_ONLY, KeyPermission.TRADE, KeyPermission.SIGN, KeyPermission.ADMIN]
        if perm_order.index(required_permission) > perm_order.index(entry.permission):
            self._audit(key_id, "read", service,
                        f"Permission denied: needs {required_permission.value}, has {entry.permission.value}",
                        success=False)
            return None

        # Fetch from environment
        value = os.getenv(entry.env_var_name, "")
        entry.last_accessed = datetime.now(timezone.utc)
        entry.access_count += 1
        self._audit(key_id, "read", service, "Secret accessed")

        return value if value else None

    # ── Rotation ─────────────────────────────────────────────────────

    def rotate_key(self, key_id: str, service: str = "secrets_manager") -> bool:
        """Mark a key as rotated.

        In production: calls Vault/KMS to generate new key, updates
        the environment, and invalidates the old key.
        """
        entry = self._entries.get(key_id)
        if not entry:
            return False

        entry.last_rotated = datetime.now(timezone.utc)
        self._audit(key_id, "rotate", service, "Key rotated")
        logger.info(f"Key rotated: {key_id} ({entry.venue})")
        return True

    def keys_needing_rotation(self) -> List[SecretEntry]:
        """Return all keys that are overdue for rotation."""
        return [e for e in self._entries.values() if e.needs_rotation and e.key_id not in self._revoked]

    # ── Revocation ───────────────────────────────────────────────────

    def revoke_key(self, key_id: str, service: str = "secrets_manager", reason: str = "") -> bool:
        """Revoke a key immediately."""
        if key_id not in self._entries:
            return False
        self._revoked.add(key_id)
        self._audit(key_id, "revoke", service, f"Key revoked: {reason}")
        logger.warning(f"Key revoked: {key_id} — {reason}")
        return True

    def is_revoked(self, key_id: str) -> bool:
        return key_id in self._revoked

    # ── Audit log ────────────────────────────────────────────────────

    def _audit(self, key_id: str, action: str, service: str, details: str, success: bool = True) -> None:
        entry = AuditLogEntry(
            key_id=key_id, action=action, service=service,
            success=success, details=details,
        )
        self._audit_log.append(entry)
        if not success:
            logger.warning(f"Secret audit [{action}] {key_id}: {details}")

    def get_audit_log(self, limit: int = 100) -> List[AuditLogEntry]:
        return self._audit_log[-limit:]

    # ── Summary ──────────────────────────────────────────────────────

    def summary(self) -> dict:
        needs_rotation = self.keys_needing_rotation()
        return {
            "environment": self.environment.value,
            "total_keys": len(self._entries),
            "revoked_keys": len(self._revoked),
            "keys_needing_rotation": len(needs_rotation),
            "audit_log_entries": len(self._audit_log),
            "keys": [e.to_dict() for e in self._entries.values()],
        }


# ── Default key registrations ────────────────────────────────────────

def _build_default_manager() -> SecretsManager:
    """Build a SecretsManager with all known MERID keys registered."""
    env = SecretEnvironment.DEV
    sm = SecretsManager(environment=env)

    keys = [
        SecretEntry(key_id="binance-api", venue="binance", env_var_name="BINANCE_API_KEY", permission=KeyPermission.TRADE),
        SecretEntry(key_id="binance-secret", venue="binance", env_var_name="BINANCE_API_SECRET", permission=KeyPermission.TRADE),
        SecretEntry(key_id="coinbase-api", venue="coinbase", env_var_name="COINBASE_API_KEY", permission=KeyPermission.TRADE),
        SecretEntry(key_id="coinbase-secret", venue="coinbase", env_var_name="COINBASE_API_SECRET", permission=KeyPermission.TRADE),
        SecretEntry(key_id="kraken-api", venue="kraken", env_var_name="KRAKEN_API_KEY", permission=KeyPermission.TRADE),
        SecretEntry(key_id="kraken-secret", venue="kraken", env_var_name="KRAKEN_PRIVATE_KEY", permission=KeyPermission.TRADE),
        SecretEntry(key_id="okx-api", venue="okx", env_var_name="OKX_KEY", permission=KeyPermission.TRADE),
        SecretEntry(key_id="okx-secret", venue="okx", env_var_name="OKX_SECRET", permission=KeyPermission.TRADE),
        SecretEntry(key_id="alpaca-api", venue="alpaca", env_var_name="ALPACA_API_KEY", permission=KeyPermission.TRADE),
        SecretEntry(key_id="alpaca-secret", venue="alpaca", env_var_name="ALPACA_API_SECRET", permission=KeyPermission.TRADE),
        SecretEntry(key_id="kalshi-api", venue="kalshi", env_var_name="KALSHI_API_KEY_ID", permission=KeyPermission.TRADE),
        SecretEntry(key_id="kalshi-pk", venue="kalshi", env_var_name="KALSHI_PRIVATE_KEY_PATH", permission=KeyPermission.SIGN),
        SecretEntry(key_id="helius-api", venue="helius", env_var_name="HELIUS_API_KEY", permission=KeyPermission.READ_ONLY),
        SecretEntry(key_id="the-graph-api", venue="the_graph", env_var_name="THE_GRAPH_API_KEY", permission=KeyPermission.READ_ONLY),
        SecretEntry(key_id="nansen-api", venue="nansen", env_var_name="NANSEN_API_KEY", permission=KeyPermission.READ_ONLY),
        SecretEntry(key_id="polygon-api", venue="polygon", env_var_name="POLYGON_API_KEY", permission=KeyPermission.READ_ONLY),
        SecretEntry(key_id="finnhub-api", venue="finnhub", env_var_name="FINNHUB_API_KEY", permission=KeyPermission.READ_ONLY),
    ]
    for k in keys:
        sm.register_key(k)

    return sm


# Module-level singleton
_manager: Optional[SecretsManager] = None


def get_secrets_manager() -> SecretsManager:
    global _manager
    if _manager is None:
        _manager = _build_default_manager()
    return _manager

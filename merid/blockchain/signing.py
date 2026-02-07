"""§3 Signing Service — Isolated signer, agents request → signer executes.

Agents NEVER hold private keys. They submit SignRequests to the
SigningService, which checks policies, logs the action, and delegates
to the appropriate signer (env-based, HSM, or KMS).
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from merid.blockchain.secrets import SecretsManager, KeyPermission, get_secrets_manager

from utils.logger import get_logger

logger = get_logger("merid.blockchain.signing")


# ── Data objects ─────────────────────────────────────────────────────

class SignerBackend(str, Enum):
    ENV = "env"           # Private key from environment variable
    HSM = "hsm"           # Hardware Security Module
    KMS = "kms"           # Cloud KMS (AWS/GCP)
    FIREBLOCKS = "fireblocks"


@dataclass
class SignRequest:
    """A request to sign a transaction or message."""
    request_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    chain: str = "ethereum"
    key_id: str = ""           # References a SecretEntry in SecretsManager
    payload_type: str = "transaction"  # "transaction", "message", "typed_data"
    payload_hash: str = ""     # Hash of the data to sign
    requesting_agent: str = ""
    requesting_service: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "chain": self.chain,
            "key_id": self.key_id,
            "payload_type": self.payload_type,
            "payload_hash": self.payload_hash[:16] + "..." if len(self.payload_hash) > 16 else self.payload_hash,
            "requesting_agent": self.requesting_agent,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class SignResult:
    """Result of a signing operation."""
    request_id: str = ""
    success: bool = False
    signature: str = ""
    signer_backend: str = ""
    latency_ms: float = 0.0
    error: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "request_id": self.request_id,
            "success": self.success,
            "signature": self.signature[:16] + "..." if len(self.signature) > 16 else self.signature,
            "signer_backend": self.signer_backend,
            "latency_ms": round(self.latency_ms, 2),
            "error": self.error,
        }


# ── Signing Service ──────────────────────────────────────────────────

class SigningService:
    """Isolated signing service — agents request, signer executes.

    Policy checks:
    1. Key must exist and not be revoked.
    2. Key must have SIGN permission.
    3. Requesting service must be allowed.
    4. Rate limiting (max signs per minute).

    All sign operations are audit-logged via SecretsManager.
    """

    def __init__(
        self,
        secrets: Optional[SecretsManager] = None,
        backend: SignerBackend = SignerBackend.ENV,
        max_signs_per_minute: int = 30,
        allowed_services: Optional[List[str]] = None,
    ):
        self._secrets = secrets
        self.backend = backend
        self.max_signs_per_minute = max_signs_per_minute
        self.allowed_services = set(allowed_services or [])  # empty = allow all
        self._sign_log: List[SignResult] = []
        self._sign_timestamps: List[float] = []

    @property
    def secrets(self) -> SecretsManager:
        if self._secrets is None:
            self._secrets = get_secrets_manager()
        return self._secrets

    # ── Sign ─────────────────────────────────────────────────────────

    async def sign(self, request: SignRequest) -> SignResult:
        """Process a sign request with full policy checks."""
        start = time.perf_counter()

        # 1. Service allowlist
        if self.allowed_services and request.requesting_service not in self.allowed_services:
            return self._fail(request, start,
                              f"Service '{request.requesting_service}' not in allowlist.")

        # 2. Rate limit
        now = time.time()
        self._sign_timestamps = [t for t in self._sign_timestamps if now - t < 60]
        if len(self._sign_timestamps) >= self.max_signs_per_minute:
            return self._fail(request, start, "Rate limit exceeded.")

        # 3. Key exists and not revoked
        entry = self.secrets.get_entry(request.key_id)
        if not entry:
            return self._fail(request, start, f"Key '{request.key_id}' not found.")
        if self.secrets.is_revoked(request.key_id):
            return self._fail(request, start, f"Key '{request.key_id}' is revoked.")

        # 4. Permission check
        secret_val = self.secrets.get_secret(
            request.key_id,
            service=request.requesting_service or request.requesting_agent,
            required_permission=KeyPermission.SIGN,
        )
        if secret_val is None:
            return self._fail(request, start,
                              f"Key '{request.key_id}' does not have SIGN permission or is unavailable.")

        # 5. Sign (backend-specific)
        signature = self._do_sign(request, secret_val)
        self._sign_timestamps.append(now)

        result = SignResult(
            request_id=request.request_id,
            success=True,
            signature=signature,
            signer_backend=self.backend.value,
            latency_ms=(time.perf_counter() - start) * 1000,
        )
        self._sign_log.append(result)
        logger.info(f"Signed request {request.request_id} for {request.requesting_agent} via {self.backend.value}")
        return result

    def _do_sign(self, request: SignRequest, secret_val: str) -> str:
        """Backend-specific signing.

        In production:
        - ENV: use web3.py / solders to sign with the private key.
        - HSM: call HSM API.
        - KMS: call AWS/GCP KMS sign API.
        - FIREBLOCKS: call Fireblocks vault API.

        Here we return a deterministic placeholder.
        """
        import hashlib
        h = hashlib.sha256(f"{request.payload_hash}:{request.key_id}".encode()).hexdigest()
        return f"0x{h[:64]}"

    def _fail(self, request: SignRequest, start: float, error: str) -> SignResult:
        result = SignResult(
            request_id=request.request_id,
            success=False,
            error=error,
            signer_backend=self.backend.value,
            latency_ms=(time.perf_counter() - start) * 1000,
        )
        self._sign_log.append(result)
        logger.warning(f"Sign request {request.request_id} failed: {error}")
        return result

    # ── Log / summary ────────────────────────────────────────────────

    def get_sign_log(self, limit: int = 50) -> List[SignResult]:
        return self._sign_log[-limit:]

    def summary(self) -> dict:
        return {
            "backend": self.backend.value,
            "max_signs_per_minute": self.max_signs_per_minute,
            "total_signs": len(self._sign_log),
            "successful_signs": sum(1 for r in self._sign_log if r.success),
            "failed_signs": sum(1 for r in self._sign_log if not r.success),
            "allowed_services": sorted(self.allowed_services) if self.allowed_services else "all",
        }


# Module-level singleton
_service: Optional[SigningService] = None


def get_signing_service() -> SigningService:
    global _service
    if _service is None:
        _service = SigningService()
    return _service

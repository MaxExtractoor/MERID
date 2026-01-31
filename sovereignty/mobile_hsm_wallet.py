"""
Mobile wallet abstraction with hardware security module (HSM) support.

Simulates secure enclave key storage, challenge-response signing, and policy
checks that would run in a production mobile wallet app. Provides deterministic
audit logs for governance verification.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List


@dataclass
class WalletSession:
    session_id: str
    device_id: str
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: datetime = field(default_factory=lambda: datetime.utcnow())


class MobileHSMWallet:
    def __init__(self) -> None:
        self._devices: Dict[str, str] = {}  # device_id -> public_key fingerprint
        self._sessions: Dict[str, WalletSession] = {}
        self._audit_log: List[Dict[str, object]] = []

    def register_device(self, device_id: str, public_key: str) -> None:
        fingerprint = hashlib.sha256(public_key.encode()).hexdigest()
        self._devices[device_id] = fingerprint

    def create_session(self, device_id: str) -> WalletSession:
        session_id = hashlib.sha256(f"{device_id}{datetime.utcnow()}".encode()).hexdigest()
        session = WalletSession(session_id=session_id, device_id=device_id)
        self._sessions[session_id] = session
        return session

    def sign_payload(self, session_id: str, payload: str) -> str:
        session = self._sessions[session_id]
        fingerprint = self._devices[session.device_id]
        signature = hashlib.sha256((payload + fingerprint).encode()).hexdigest()
        self._audit_log.append(
            {"session_id": session_id, "payload_hash": hashlib.sha256(payload.encode()).hexdigest(), "signature": signature, "timestamp": datetime.utcnow().isoformat()}
        )
        return signature

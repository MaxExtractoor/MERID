"""
Quantum-resistant key management scaffolding.

Generates Dilithium-style keypairs (mocked), stores key history, and enforces
rotation policies so sensitive agents can migrate away from classical schemes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List
import secrets
import hashlib


@dataclass
class PQKeyPair:
    key_id: str
    public_key: str
    private_seed: str
    created_at: datetime
    expires_at: datetime


class QuantumResistantKeyManager:
    def __init__(self, rotation_days: int = 30) -> None:
        self.rotation_days = rotation_days
        self._keys: Dict[str, PQKeyPair] = {}

    def generate_keypair(self, subject: str) -> PQKeyPair:
        seed = secrets.token_hex(64)
        public = hashlib.sha3_512(seed.encode()).hexdigest()
        keypair = PQKeyPair(
            key_id=f"{subject}_{int(datetime.utcnow().timestamp())}",
            public_key=public,
            private_seed=seed,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=self.rotation_days),
        )
        self._keys[subject] = keypair
        return keypair

    def get_active_key(self, subject: str) -> PQKeyPair | None:
        key = self._keys.get(subject)
        if key and key.expires_at > datetime.utcnow():
            return key
        return None

    def ensure_fresh_key(self, subject: str) -> PQKeyPair:
        key = self.get_active_key(subject)
        if key:
            return key
        return self.generate_keypair(subject)

    def rotation_schedule(self) -> List[PQKeyPair]:
        return list(self._keys.values())

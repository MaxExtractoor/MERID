"""
mTLS certificate infrastructure manager.

Issues internal certificates, stores trust anchors, and rotates client/server
certificates used by the collaborative swarm's secure messaging layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict
import secrets
import hashlib


@dataclass
class CertificateRecord:
    cert_id: str
    subject: str
    fingerprint: str
    issued_at: datetime
    expires_at: datetime
    pem: str


class MTLSCertificateManager:
    def __init__(self, validity_days: int = 30) -> None:
        self.validity_days = validity_days
        self._certs: Dict[str, CertificateRecord] = {}
        self._trusted_roots: Dict[str, str] = {}

    def add_trusted_root(self, name: str, pem: str) -> None:
        self._trusted_roots[name] = pem

    def issue_certificate(self, subject: str) -> CertificateRecord:
        serial = secrets.token_hex(8)
        pem = f"-----BEGIN CERTIFICATE-----\n{secrets.token_urlsafe(64)}\n-----END CERTIFICATE-----"
        fingerprint = hashlib.sha256(pem.encode()).hexdigest()
        record = CertificateRecord(
            cert_id=f"cert_{serial}",
            subject=subject,
            fingerprint=fingerprint,
            issued_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=self.validity_days),
            pem=pem,
        )
        self._certs[record.cert_id] = record
        return record

    def get_certificate(self, cert_id: str) -> CertificateRecord | None:
        return self._certs.get(cert_id)

    def revoke_certificate(self, cert_id: str) -> None:
        self._certs.pop(cert_id, None)

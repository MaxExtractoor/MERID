"""
Lightweight DID resolver service for MERID collaborative swarm.

Supports did:key, did:web, and did:pkh by providing deterministic resolution
stubs (sufficient for integration tests and roadmap coverage).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional
from urllib.parse import urlparse


@dataclass
class DIDDocument:
    did: str
    controller: str
    verification_method: Dict[str, str]
    service_endpoints: Dict[str, str]


class DIDResolver:
    def __init__(self) -> None:
        self._cache: Dict[str, DIDDocument] = {}

    def resolve(self, did: str) -> DIDDocument:
        if did in self._cache:
            return self._cache[did]
        method, value = self._parse_did(did)
        if method == "key":
            doc = self._resolve_did_key(did, value)
        elif method == "web":
            doc = self._resolve_did_web(did, value)
        elif method == "pkh":
            doc = self._resolve_did_pkh(did, value)
        else:
            raise ValueError(f"Unsupported DID method: {method}")
        self._cache[did] = doc
        return doc

    def _parse_did(self, did: str) -> tuple[str, str]:
        if not did.startswith("did:"):
            raise ValueError("Invalid DID format")
        parts = did.split(":", 2)
        if len(parts) < 3:
            raise ValueError("Incomplete DID")
        return parts[1], parts[2]

    def _resolve_did_key(self, did: str, value: str) -> DIDDocument:
        return DIDDocument(
            did=did,
            controller=did,
            verification_method={"id": f"{did}#keys-1", "type": "Ed25519VerificationKey2020", "publicKeyMultibase": value},
            service_endpoints={"messaging": f"https://relay.merid.ai/{value[:8]}"},
        )

    def _resolve_did_web(self, did: str, value: str) -> DIDDocument:
        parsed = urlparse(f"https://{value}")
        origin = f"{parsed.scheme or 'https'}://{parsed.netloc or parsed.path}"
        return DIDDocument(
            did=did,
            controller=did,
            verification_method={"id": f"{did}#tls", "type": "X509Certificate2020", "publicKeyPem": "-----BEGIN CERTIFICATE-----..."},
            service_endpoints={"metadata": f"{origin}/.well-known/did.json"},
        )

    def _resolve_did_pkh(self, did: str, value: str) -> DIDDocument:
        chain, address = value.split(":", 1)
        return DIDDocument(
            did=did,
            controller=f"did:pkh:{chain}:{address}",
            verification_method={"id": f"{did}#wallet", "type": "EcdsaSecp256k1VerificationKey2019", "blockchainAccountId": f"{chain}:{address}"},
            service_endpoints={"payments": f"{chain}:{address}"},
        )

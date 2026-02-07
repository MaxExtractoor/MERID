"""
Audit Anchor — periodic hash anchoring of audit trail state.

Provides tamper-evident anchoring by computing a Merkle-like root hash
of audit trail entries and recording it to a pluggable backend.

Backends:
- InMemoryAnchorStore (default, for testing)
- FileAnchorStore (JSON file on disk)
- Future: on-chain (Ethereum/Solana calldata)

Usage:
    anchor = AuditAnchor(store=FileAnchorStore("data/anchors.json"))
    receipt = anchor.anchor(entries)
    verified = anchor.verify(receipt.anchor_id)
"""

from __future__ import annotations

import hashlib
import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("core.audit_anchor")


# ── Data classes ───────────────────────────────────────────────────


@dataclass
class AnchorReceipt:
    """Proof that an audit state was anchored."""
    anchor_id: str
    merkle_root: str
    entry_count: int
    first_sequence: int
    last_sequence: int
    timestamp: str
    store_type: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "anchor_id": self.anchor_id,
            "merkle_root": self.merkle_root,
            "entry_count": self.entry_count,
            "first_sequence": self.first_sequence,
            "last_sequence": self.last_sequence,
            "timestamp": self.timestamp,
            "store_type": self.store_type,
        }


@dataclass
class AuditEntry:
    """Minimal audit entry for anchoring (mirrors core.audit_trail.AuditEntry)."""
    sequence: int
    entry_hash: str
    event_type: str = ""
    timestamp: float = 0.0


# ── Merkle helpers ─────────────────────────────────────────────────


def _sha256(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def compute_merkle_root(hashes: List[str]) -> str:
    """Compute Merkle root from a list of hashes.

    If the list is empty, returns the hash of an empty string.
    If odd number of leaves, the last leaf is duplicated.
    """
    if not hashes:
        return _sha256("")

    if len(hashes) == 1:
        return _sha256(hashes[0])

    level = list(hashes)
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])  # duplicate last
        next_level = []
        for i in range(0, len(level), 2):
            combined = level[i] + level[i + 1]
            next_level.append(_sha256(combined))
        level = next_level
    return level[0]


# ── Anchor stores ──────────────────────────────────────────────────


class AnchorStore(ABC):
    """Abstract backend for persisting anchor receipts."""

    @property
    @abstractmethod
    def store_type(self) -> str:
        ...

    @abstractmethod
    def save(self, receipt: AnchorReceipt) -> None:
        ...

    @abstractmethod
    def load(self, anchor_id: str) -> Optional[AnchorReceipt]:
        ...

    @abstractmethod
    def list_all(self) -> List[AnchorReceipt]:
        ...


class InMemoryAnchorStore(AnchorStore):
    """In-memory store for testing."""

    def __init__(self) -> None:
        self._receipts: Dict[str, AnchorReceipt] = {}

    @property
    def store_type(self) -> str:
        return "in_memory"

    def save(self, receipt: AnchorReceipt) -> None:
        self._receipts[receipt.anchor_id] = receipt

    def load(self, anchor_id: str) -> Optional[AnchorReceipt]:
        return self._receipts.get(anchor_id)

    def list_all(self) -> List[AnchorReceipt]:
        return list(self._receipts.values())


class FileAnchorStore(AnchorStore):
    """JSON file store for production."""

    def __init__(self, path: str = "data/anchors.json") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def store_type(self) -> str:
        return "file"

    def save(self, receipt: AnchorReceipt) -> None:
        existing = self._load_all()
        existing[receipt.anchor_id] = receipt.to_dict()
        with open(self._path, "w") as f:
            json.dump(existing, f, indent=2)

    def load(self, anchor_id: str) -> Optional[AnchorReceipt]:
        existing = self._load_all()
        data = existing.get(anchor_id)
        if data:
            return AnchorReceipt(**data)
        return None

    def list_all(self) -> List[AnchorReceipt]:
        return [AnchorReceipt(**v) for v in self._load_all().values()]

    def _load_all(self) -> Dict[str, Any]:
        if not self._path.exists():
            return {}
        try:
            with open(self._path) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}


# ── Main anchor class ──────────────────────────────────────────────


class AuditAnchor:
    """Anchors audit trail state by computing and storing Merkle roots."""

    def __init__(self, store: Optional[AnchorStore] = None) -> None:
        self._store = store or InMemoryAnchorStore()
        self._anchor_count = 0

    def anchor(self, entries: List[AuditEntry]) -> AnchorReceipt:
        """Compute Merkle root of entries and store an anchor receipt.

        Args:
            entries: List of audit entries to anchor.

        Returns:
            AnchorReceipt with the Merkle root and metadata.
        """
        hashes = [e.entry_hash for e in entries]
        merkle_root = compute_merkle_root(hashes)

        self._anchor_count += 1
        anchor_id = f"anchor-{int(time.time() * 1000)}-{self._anchor_count}"

        first_seq = entries[0].sequence if entries else 0
        last_seq = entries[-1].sequence if entries else 0

        receipt = AnchorReceipt(
            anchor_id=anchor_id,
            merkle_root=merkle_root,
            entry_count=len(entries),
            first_sequence=first_seq,
            last_sequence=last_seq,
            timestamp=datetime.now(timezone.utc).isoformat(),
            store_type=self._store.store_type,
        )

        self._store.save(receipt)
        logger.info(
            f"Anchored {len(entries)} entries: {anchor_id} "
            f"(root={merkle_root[:16]}…)"
        )
        return receipt

    def verify(self, anchor_id: str, entries: List[AuditEntry]) -> bool:
        """Verify that entries match a previously anchored Merkle root.

        Args:
            anchor_id: ID of the anchor receipt to verify against.
            entries: Current entries to recompute the root from.

        Returns:
            True if the recomputed root matches the stored root.
        """
        receipt = self._store.load(anchor_id)
        if not receipt:
            logger.warning(f"Anchor {anchor_id} not found")
            return False

        hashes = [e.entry_hash for e in entries]
        recomputed = compute_merkle_root(hashes)
        match = recomputed == receipt.merkle_root

        if not match:
            logger.warning(
                f"Anchor verification FAILED for {anchor_id}: "
                f"expected {receipt.merkle_root[:16]}…, got {recomputed[:16]}…"
            )
        return match

    def list_anchors(self) -> List[AnchorReceipt]:
        """List all stored anchor receipts."""
        return self._store.list_all()

    @property
    def anchor_count(self) -> int:
        return self._anchor_count

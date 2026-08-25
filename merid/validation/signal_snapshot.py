"""Signal Snapshot Ledger - Immutable signal records for audit chain.

This module provides the upstream foundation for intent verification:
- SignalSnapshot: Immutable record of signals before intent transformation
- SignalSnapshotLedger: Append-only storage for signal snapshots
- Hash computation for deterministic signal identification

This ensures every executable signal has a source-of-truth snapshot that
documents exactly what the system believed at decision time.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid


def compute_signal_hash(
    market_id: str,
    side: str,
    action: str,
    intent: str,
    edge: float,
    confidence: float,
    origin_agent: str,
    origin_strategy: str,
    timeframe_label: str,
    raw_features: Dict[str, Any],
) -> str:
    """Compute deterministic hash over core signal fields.
    
    This hash is used to verify signal-to-intent consistency and detect
    any drift between the original signal and downstream transformations.
    
    Args:
        market_id: Market identifier
        side: "yes" or "no"
        action: "buy", "sell", "hold", "no_action"
        intent: "open", "close", "scale_in", "scale_out"
        edge: Edge estimate
        confidence: Model confidence (0-1)
        origin_agent: Agent name (e.g., "BTC_15M")
        origin_strategy: Strategy class name
        timeframe_label: Timeframe (e.g., "15m")
        raw_features: Raw model features (ADX, ATR, velocity, etc.)
    
    Returns:
        SHA256 hash string (hex digest)
    """
    # Normalize raw features for consistent hashing
    # Sort keys and convert values to strings
    normalized_features = {
        k: str(v) if not isinstance(v, (list, dict)) else json.dumps(v, sort_keys=True)
        for k, v in sorted(raw_features.items())
    }
    
    # Build hash preimage with core fields
    hash_preimage = {
        "market_id": market_id,
        "side": side,
        "action": action,
        "intent": intent,
        "edge": f"{edge:.6f}",  # Normalize float precision
        "confidence": f"{confidence:.6f}",
        "origin_agent": origin_agent,
        "origin_strategy": origin_strategy,
        "timeframe_label": timeframe_label,
        "features": normalized_features,
    }
    
    # Convert to JSON string with sorted keys
    hash_string = json.dumps(hash_preimage, sort_keys=True)
    
    # Compute SHA256 hash
    return hashlib.sha256(hash_string.encode()).hexdigest()


@dataclass(frozen=True)
class SignalSnapshot:
    """Immutable snapshot of a signal at decision time.
    
    This is the source-of-truth for intent verification. Once created,
    a snapshot is never modified. Corrections create new snapshots with
    a link to the previous one.
    
    Attributes:
        snapshot_id: Unique snapshot identifier
        signal_id: From AgentSignal
        signal_hash: Deterministic hash over core fields
        market_id: Market identifier
        side: "yes" or "no"
        action: "buy", "sell", "hold", "no_action"
        intent: "open", "close", "scale_in", "scale_out"
        edge: Edge estimate
        confidence: Model confidence (0-1)
        origin_agent: Agent name (e.g., "BTC_15M")
        origin_strategy: Strategy class name
        timeframe_label: Timeframe (e.g., "15m")
        created_ts: Unix timestamp
        raw_features: Raw model features (ADX, ATR, velocity, etc.)
        previous_snapshot_id: For corrections, link to previous snapshot
        validation_errors: Any validation errors at snapshot time
    """
    snapshot_id: str
    signal_id: str
    signal_hash: str
    market_id: str
    side: str
    action: str
    intent: str
    edge: float
    confidence: float
    origin_agent: str
    origin_strategy: str
    timeframe_label: str
    created_ts: float
    raw_features: Dict[str, Any]
    previous_snapshot_id: Optional[str] = None
    validation_errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "snapshot_id": self.snapshot_id,
            "signal_id": self.signal_id,
            "signal_hash": self.signal_hash,
            "market_id": self.market_id,
            "side": self.side,
            "action": self.action,
            "intent": self.intent,
            "edge": self.edge,
            "confidence": self.confidence,
            "origin_agent": self.origin_agent,
            "origin_strategy": self.origin_strategy,
            "timeframe_label": self.timeframe_label,
            "created_ts": self.created_ts,
            "raw_features": self.raw_features,
            "previous_snapshot_id": self.previous_snapshot_id,
            "validation_errors": self.validation_errors,
        }


class SignalSnapshotLedger:
    """Append-only ledger for signal snapshots.
    
    This ledger stores all signal snapshots and provides lookup by
    signal_id and signal_hash for verification.
    """
    
    def __init__(self):
        self._snapshots_by_id: Dict[str, SignalSnapshot] = {}
        self._snapshots_by_hash: Dict[str, List[SignalSnapshot]] = {}
        self._snapshots_by_signal: Dict[str, List[SignalSnapshot]] = {}
    
    def record_snapshot(self, snapshot: SignalSnapshot) -> None:
        """Record a signal snapshot in the ledger.
        
        Args:
            snapshot: The snapshot to record
        """
        # Index by snapshot_id
        self._snapshots_by_id[snapshot.snapshot_id] = snapshot
        
        # Index by signal_hash (multiple snapshots can have same hash)
        if snapshot.signal_hash not in self._snapshots_by_hash:
            self._snapshots_by_hash[snapshot.signal_hash] = []
        self._snapshots_by_hash[snapshot.signal_hash].append(snapshot)
        
        # Index by signal_id (multiple snapshots per signal for corrections)
        if snapshot.signal_id not in self._snapshots_by_signal:
            self._snapshots_by_signal[snapshot.signal_id] = []
        self._snapshots_by_signal[snapshot.signal_id].append(snapshot)
    
    def get_by_snapshot_id(self, snapshot_id: str) -> Optional[SignalSnapshot]:
        """Get snapshot by snapshot_id."""
        return self._snapshots_by_id.get(snapshot_id)
    
    def get_by_signal_hash(self, signal_hash: str) -> List[SignalSnapshot]:
        """Get all snapshots with matching signal_hash."""
        return self._snapshots_by_hash.get(signal_hash, [])
    
    def get_by_signal_id(self, signal_id: str) -> List[SignalSnapshot]:
        """Get all snapshots for a given signal_id."""
        return self._snapshots_by_signal.get(signal_id, [])
    
    def verify_hash(self, signal_id: str, expected_hash: str) -> bool:
        """Verify that a signal's hash matches expected value.
        
        Args:
            signal_id: The signal ID to verify
            expected_hash: The expected signal hash
        
        Returns:
            True if any snapshot for this signal_id has the expected hash
        """
        snapshots = self.get_by_signal_id(signal_id)
        return any(snap.signal_hash == expected_hash for snap in snapshots)
    
    def get_latest_snapshot(self, signal_id: str) -> Optional[SignalSnapshot]:
        """Get the latest snapshot for a signal (by created_ts, then by record order)."""
        snapshots = self.get_by_signal_id(signal_id)
        if not snapshots:
            return None
        # Use index as a tie-breaker so a more recently recorded snapshot wins
        # when two are created within the same microsecond.
        return max(enumerate(snapshots), key=lambda x: (x[1].created_ts, x[0]))[1]


# Global singleton instance
_ledger: Optional[SignalSnapshotLedger] = None


def get_signal_snapshot_ledger() -> SignalSnapshotLedger:
    """Get the global signal snapshot ledger singleton."""
    global _ledger
    if _ledger is None:
        _ledger = SignalSnapshotLedger()
    return _ledger


def create_signal_snapshot(
    signal_id: str,
    market_id: str,
    side: str,
    action: str,
    intent: str,
    edge: float,
    confidence: float,
    origin_agent: str,
    origin_strategy: str,
    timeframe_label: str,
    raw_features: Dict[str, Any],
    previous_snapshot_id: Optional[str] = None,
    validation_errors: Optional[List[str]] = None,
) -> SignalSnapshot:
    """Create and record a new signal snapshot.
    
    This is the factory function for creating signal snapshots. It
    computes the hash, generates IDs, and records the snapshot in the
    global ledger.
    
    Args:
        signal_id: From AgentSignal
        market_id: Market identifier
        side: "yes" or "no"
        action: "buy", "sell", "hold", "no_action"
        intent: "open", "close", "scale_in", "scale_out"
        edge: Edge estimate
        confidence: Model confidence (0-1)
        origin_agent: Agent name (e.g., "BTC_15M")
        origin_strategy: Strategy class name
        timeframe_label: Timeframe (e.g., "15m")
        raw_features: Raw model features (ADX, ATR, velocity, etc.)
        previous_snapshot_id: For corrections, link to previous snapshot
        validation_errors: Any validation errors at snapshot time
    
    Returns:
        The created SignalSnapshot
    """
    # Compute deterministic hash
    signal_hash = compute_signal_hash(
        market_id=market_id,
        side=side,
        action=action,
        intent=intent,
        edge=edge,
        confidence=confidence,
        origin_agent=origin_agent,
        origin_strategy=origin_strategy,
        timeframe_label=timeframe_label,
        raw_features=raw_features,
    )
    
    # Generate snapshot ID
    snapshot_id = f"snap-{int(datetime.now(timezone.utc).timestamp())}-{uuid.uuid4().hex[:8]}"
    
    # Create snapshot
    snapshot = SignalSnapshot(
        snapshot_id=snapshot_id,
        signal_id=signal_id,
        signal_hash=signal_hash,
        market_id=market_id,
        side=side,
        action=action,
        intent=intent,
        edge=edge,
        confidence=confidence,
        origin_agent=origin_agent,
        origin_strategy=origin_strategy,
        timeframe_label=timeframe_label,
        created_ts=datetime.now(timezone.utc).timestamp(),
        raw_features=raw_features,
        previous_snapshot_id=previous_snapshot_id,
        validation_errors=validation_errors or [],
    )
    
    # Record in ledger
    ledger = get_signal_snapshot_ledger()
    ledger.record_snapshot(snapshot)
    
    return snapshot

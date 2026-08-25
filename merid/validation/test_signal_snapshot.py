"""Unit tests for SignalSnapshot module.

Tests the immutable signal snapshot ledger and hash computation.
Follows testing best practices: valid construction, invariant violations,
edge cases, and contract tests.
"""

import pytest
from datetime import datetime, timezone, timedelta
from dataclasses import FrozenInstanceError
import hashlib
import json

from merid.validation.signal_snapshot import (
    SignalSnapshot,
    SignalSnapshotLedger,
    compute_signal_hash,
    create_signal_snapshot,
    get_signal_snapshot_ledger,
)


class TestComputeSignalHash:
    """Test signal hash computation."""
    
    def test_hash_deterministic_for_same_inputs(self):
        """Hash should be deterministic - same inputs produce same hash."""
        hash1 = compute_signal_hash(
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            raw_features={"velocity": 0.01, "rsi": 50.0},
        )
        
        hash2 = compute_signal_hash(
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            raw_features={"velocity": 0.01, "rsi": 50.0},
        )
        
        assert hash1 == hash2
    
    def test_hash_different_for_different_inputs(self):
        """Hash should differ for different inputs."""
        hash1 = compute_signal_hash(
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            raw_features={"velocity": 0.01},
        )
        
        hash2 = compute_signal_hash(
            market_id="KXBTC15M-2026-07-20T14:00",
            side="no",  # Different side
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            raw_features={"velocity": 0.01},
        )
        
        assert hash1 != hash2
    
    def test_hash_includes_raw_features(self):
        """Hash should include raw features in computation."""
        hash1 = compute_signal_hash(
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            raw_features={"velocity": 0.01, "rsi": 50.0},
        )
        
        hash2 = compute_signal_hash(
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            raw_features={"velocity": 0.02, "rsi": 50.0},  # Different velocity
        )
        
        assert hash1 != hash2
    
    def test_hash_is_sha256_hex(self):
        """Hash should be a 64-character hex string (SHA256)."""
        hash_val = compute_signal_hash(
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            raw_features={},
        )
        
        assert len(hash_val) == 64
        assert all(c in "0123456789abcdef" for c in hash_val)


class TestSignalSnapshot:
    """Test SignalSnapshot dataclass."""
    
    def test_valid_construction(self):
        """Test valid snapshot construction."""
        snapshot = SignalSnapshot(
            snapshot_id="snap-1721476800-abc123",
            signal_id="sig-1721476800-BTC",
            signal_hash="abc123def456",
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            created_ts=1721476800.0,
            raw_features={"velocity": 0.01},
        )
        
        assert snapshot.snapshot_id == "snap-1721476800-abc123"
        assert snapshot.signal_id == "sig-1721476800-BTC"
        assert snapshot.signal_hash == "abc123def456"
        assert snapshot.market_id == "KXBTC15M-2026-07-20T14:00"
        assert snapshot.side == "yes"
        assert snapshot.action == "buy"
        assert snapshot.intent == "open"
        assert snapshot.edge == 0.05
        assert snapshot.confidence == 0.75
        assert snapshot.origin_agent == "agent_grid_15m"
        assert snapshot.origin_strategy == "momentum_fvg"
        assert snapshot.timeframe_label == "15m"
        assert snapshot.raw_features == {"velocity": 0.01}
    
    def test_hash_computed_on_construction(self):
        """Hash is provided as required field."""
        snapshot = SignalSnapshot(
            snapshot_id="snap-1721476800-abc123",
            signal_id="sig-1721476800-BTC",
            signal_hash="abc123def4567890" * 4,  # 64 char hash
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            created_ts=1721476800.0,
            raw_features={},
        )
        
        assert snapshot.signal_hash is not None
        assert len(snapshot.signal_hash) == 64
    
    def test_frozen_immutable(self):
        """Snapshot should be frozen (immutable)."""
        snapshot = SignalSnapshot(
            snapshot_id="snap-1721476800-abc123",
            signal_id="sig-1721476800-BTC",
            signal_hash="abc123def4567890" * 4,
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            created_ts=1721476800.0,
            raw_features={},
        )
        
        with pytest.raises(FrozenInstanceError):
            snapshot.side = "no"
    
    def test_to_dict_serialization(self):
        """Test to_dict serialization."""
        snapshot = SignalSnapshot(
            snapshot_id="snap-1721476800-abc123",
            signal_id="sig-1721476800-BTC",
            signal_hash="abc123def4567890" * 4,
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            created_ts=1721476800.0,
            raw_features={"velocity": 0.01},
        )
        
        d = snapshot.to_dict()
        
        assert d["snapshot_id"] == "snap-1721476800-abc123"
        assert d["signal_id"] == "sig-1721476800-BTC"
        assert d["signal_hash"] == "abc123def4567890" * 4
        assert d["market_id"] == "KXBTC15M-2026-07-20T14:00"
        assert d["side"] == "yes"
        assert d["action"] == "buy"
        assert d["intent"] == "open"
        assert d["edge"] == 0.05
        assert d["confidence"] == 0.75
        assert d["origin_agent"] == "agent_grid_15m"
        assert d["origin_strategy"] == "momentum_fvg"
        assert d["timeframe_label"] == "15m"
        assert d["raw_features"] == {"velocity": 0.01}
        assert "created_ts" in d


class TestSignalSnapshotLedger:
    """Test SignalSnapshotLedger append-only storage."""
    
    def test_singleton_instance(self):
        """Ledger should be a singleton."""
        ledger1 = get_signal_snapshot_ledger()
        ledger2 = get_signal_snapshot_ledger()
        
        assert ledger1 is ledger2
    
    def test_append_snapshot(self):
        """Test recording a snapshot to the ledger."""
        ledger = SignalSnapshotLedger()
        
        snapshot = SignalSnapshot(
            snapshot_id="snap-1721476800-abc123",
            signal_id="sig-1721476800-BTC",
            signal_hash="abc123def4567890" * 4,
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            created_ts=1721476800.0,
            raw_features={},
        )
        
        ledger.record_snapshot(snapshot)
        
        assert len(ledger._snapshots_by_id) == 1
        assert ledger._snapshots_by_id[snapshot.snapshot_id] == snapshot
    
    def test_get_by_signal_id(self):
        """Test retrieving snapshots by signal ID."""
        ledger = SignalSnapshotLedger()
        
        snapshot1 = SignalSnapshot(
            snapshot_id="snap-1721476800-abc123",
            signal_id="sig-1721476800-BTC",
            signal_hash="abc123def4567890" * 4,
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            created_ts=1721476800.0,
            raw_features={},
        )
        
        snapshot2 = SignalSnapshot(
            snapshot_id="snap-1721476801-def456",
            signal_id="sig-1721476800-BTC",  # Same signal ID
            signal_hash="def4567890abc123" * 4,
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.06,  # Different edge
            confidence=0.80,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            created_ts=1721476801.0,
            raw_features={},
        )
        
        ledger.record_snapshot(snapshot1)
        ledger.record_snapshot(snapshot2)
        
        snapshots = ledger.get_by_signal_id("sig-1721476800-BTC")
        
        assert len(snapshots) == 2
        assert snapshot1 in snapshots
        assert snapshot2 in snapshots
    
    def test_get_latest_snapshot(self):
        """Test retrieving the latest snapshot for a signal ID."""
        ledger = SignalSnapshotLedger()
        
        snapshot1 = SignalSnapshot(
            snapshot_id="snap-1721476800-abc123",
            signal_id="sig-1721476800-BTC",
            signal_hash="abc123def4567890" * 4,
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            created_ts=1721476800.0,
            raw_features={},
        )
        
        snapshot2 = SignalSnapshot(
            snapshot_id="snap-1721476801-def456",
            signal_id="sig-1721476800-BTC",
            signal_hash="def4567890abc123" * 4,
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.06,
            confidence=0.80,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            created_ts=1721476801.0,  # 1 second later
            raw_features={},
        )
        
        ledger.record_snapshot(snapshot1)
        ledger.record_snapshot(snapshot2)
        
        latest = ledger.get_latest_snapshot("sig-1721476800-BTC")
        
        assert latest == snapshot2
    
    def test_get_latest_snapshot_returns_none_for_unknown_signal(self):
        """Test that get_latest_snapshot returns None for unknown signal ID."""
        ledger = SignalSnapshotLedger()
        
        latest = ledger.get_latest_snapshot("sig-unknown")
        
        assert latest is None
    
    def test_get_by_signal_id_returns_empty_for_unknown_signal(self):
        """Test that get_by_signal_id returns empty list for unknown signal ID."""
        ledger = SignalSnapshotLedger()
        
        snapshots = ledger.get_by_signal_id("sig-unknown")
        
        assert snapshots == []


class TestCreateSignalSnapshot:
    """Test create_signal_snapshot factory function."""
    
    def test_creates_snapshot_with_auto_id(self):
        """Test that create_signal_snapshot generates auto IDs."""
        snapshot = create_signal_snapshot(
            signal_id="sig-1721476800-BTC",
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            raw_features={},
        )
        
        assert snapshot.snapshot_id.startswith("snap-")
        assert snapshot.signal_id == "sig-1721476800-BTC"
        assert snapshot.signal_hash is not None
    
    def test_appends_to_ledger(self):
        """Test that create_signal_snapshot records to the ledger."""
        ledger = get_signal_snapshot_ledger()
        initial_count = len(ledger._snapshots_by_id)
        
        create_signal_snapshot(
            signal_id="sig-1721476800-BTC",
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            raw_features={},
        )
        
        assert len(ledger._snapshots_by_id) == initial_count + 1
    
    def test_creates_correction_snapshot(self):
        """Test creating a correction snapshot with previous_snapshot_id."""
        original = create_signal_snapshot(
            signal_id="sig-1721476800-BTC",
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.05,
            confidence=0.75,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            raw_features={},
        )
        
        correction = create_signal_snapshot(
            signal_id="sig-1721476800-BTC",
            market_id="KXBTC15M-2026-07-20T14:00",
            side="yes",
            action="buy",
            intent="open",
            edge=0.06,  # Corrected edge
            confidence=0.80,
            origin_agent="agent_grid_15m",
            origin_strategy="momentum_fvg",
            timeframe_label="15m",
            raw_features={},
            previous_snapshot_id=original.snapshot_id,
        )
        
        assert correction.previous_snapshot_id == original.snapshot_id
        assert correction.signal_hash != original.signal_hash

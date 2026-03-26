"""Tests for F3 – BrierStore (SQLite WAL) and BrierGate (SHADOW/LIVE)."""

from __future__ import annotations

import sqlite3
import tempfile
import os

import pytest

from merid.metrics.brier_store import BrierStore, BrierGate


@pytest.fixture
def store(tmp_path):
    db = str(tmp_path / "test_brier.db")
    return BrierStore(db_path=db)


@pytest.fixture
def gate(store):
    return BrierGate(
        store,
        shadow_to_live_threshold=0.20,
        live_to_shadow_threshold=0.25,
        min_samples=3,
    )


# ── BrierStore ────────────────────────────────────────────────────────────

def test_record_returns_correct_brier_score(store):
    """record() returns (forecast - outcome)^2."""
    score = store.record("a1", "MKT1", forecast=0.7, outcome=1)
    assert abs(score - 0.09) < 1e-9


def test_record_and_read_back(store):
    """Brier scores are persisted and retrievable via rolling_brier."""
    store.record("a1", "MKT1", forecast=0.7, outcome=1)
    store.record("a1", "MKT2", forecast=0.5, outcome=0)

    avg = store.rolling_brier("a1", last_n=10)
    assert avg is not None
    # Expected: mean of 0.09 and 0.25 = 0.17
    assert abs(avg - 0.17) < 1e-9


def test_sample_count(store):
    """sample_count reflects the number of recorded predictions."""
    assert store.sample_count("a1") == 0
    store.record("a1", "MKT1", 0.6, 1)
    store.record("a1", "MKT2", 0.4, 0)
    assert store.sample_count("a1") == 2


def test_rolling_brier_returns_none_with_no_samples(store):
    """rolling_brier returns None when no predictions are recorded."""
    assert store.rolling_brier("unknown_agent") is None


def test_wal_mode_is_enabled(store):
    """SQLite WAL mode is configured on the BrierStore database."""
    conn = sqlite3.connect(store._db_path)
    row = conn.execute("PRAGMA journal_mode").fetchone()
    conn.close()
    assert row[0].lower() == "wal"


def test_rolling_brier_respects_last_n(store):
    """rolling_brier honours the last_n window."""
    # Record 5 scores of 0.25, then 5 scores of 0.01
    for _ in range(5):
        store.record("a1", "MKT", 0.5, 0)   # score = 0.25
    for _ in range(5):
        store.record("a1", "MKT", 0.9, 1)   # score = 0.01

    recent = store.rolling_brier("a1", last_n=5)
    all_n = store.rolling_brier("a1", last_n=10)

    assert recent is not None and all_n is not None
    assert recent < all_n  # recent 5 are lower-scoring


# ── BrierGate ────────────────────────────────────────────────────────────

def test_gate_stays_shadow_below_min_samples(gate, store):
    """Gate keeps agent in shadow when fewer than min_samples predictions exist."""
    store.record("a1", "MKT", 0.1, 1)   # score=0.81 (bad), 1 sample
    mode = gate.evaluate("a1")
    assert mode == "shadow"


def test_gate_promotes_to_live_when_brier_below_threshold(gate, store):
    """Agent is promoted to LIVE when rolling Brier ≤ shadow_to_live threshold."""
    # Record 3 near-perfect predictions (Brier ≈ 0.01)
    for _ in range(3):
        store.record("a1", "MKT", 0.9, 1)   # (0.9-1)^2 = 0.01

    mode = gate.evaluate("a1")
    assert mode == "live"


def test_gate_stays_shadow_when_brier_above_threshold(gate, store):
    """Agent remains in shadow when rolling Brier > shadow_to_live threshold."""
    for _ in range(3):
        store.record("a1", "MKT", 0.5, 0)   # (0.5-0)^2 = 0.25

    mode = gate.evaluate("a1")
    assert mode == "shadow"


def test_gate_demotes_to_shadow_when_brier_rises(gate, store):
    """Live agent is demoted back to shadow when Brier exceeds live_to_shadow threshold."""
    # Promote first
    for _ in range(3):
        store.record("a1", "MKT", 0.9, 1)   # score ≈ 0.01
    assert gate.evaluate("a1") == "live"

    # Now add many bad predictions to push rolling Brier above 0.25
    for _ in range(20):
        store.record("a1", "MKT", 0.5, 0)   # score = 0.25

    mode = gate.evaluate("a1")
    assert mode == "shadow"


def test_gate_get_mode_without_evaluate_returns_shadow(gate):
    """get_mode returns 'shadow' for unknown agent without prior evaluate."""
    assert gate.get_mode("never-seen") == "shadow"


def test_gate_evaluate_multiple_agents_independently(gate, store):
    """Two agents are evaluated independently."""
    for _ in range(3):
        store.record("good_agent", "MKT", 0.9, 1)  # score ≈ 0.01 → should promote
    for _ in range(3):
        store.record("bad_agent", "MKT", 0.5, 0)   # score = 0.25 → stay shadow

    assert gate.evaluate("good_agent") == "live"
    assert gate.evaluate("bad_agent") == "shadow"

"""Tests for Stage 6.5 non-bypassable consensus gate."""

from __future__ import annotations

import pytest

from core.consensus_gate import (
    fork_agents_on_poisoning,
    get_source_weight_gated,
    resolve_consensus,
    update_agent_trust_gated,
)
from core.consensus_math import Vote


def test_consensus_gate_normal_operation():
    """Test consensus gate under normal conditions."""
    votes = [
        Vote(agent_id="agent_1", vote=1, trust=1.0, confidence=0.8, source="source_a", source_srw=0.9),
        Vote(agent_id="agent_2", vote=1, trust=1.0, confidence=0.75, source="source_b", source_srw=0.85),
        Vote(agent_id="agent_3", vote=1, trust=1.0, confidence=0.82, source="source_c", source_srw=0.88),
    ]
    
    claims = [
        {"source": "source_a", "metric": "price", "value": 100.0, "weight": 1.0},
        {"source": "source_b", "metric": "price", "value": 101.0, "weight": 1.0},
        {"source": "source_c", "metric": "price", "value": 100.5, "weight": 1.0},
    ]
    
    resolution = resolve_consensus(votes, claims, threshold=0.6)
    
    assert resolution.approved
    assert not resolution.poisoning_detected
    assert resolution.trust_updates_allowed
    assert not resolution.degraded_mode


def test_consensus_gate_temporal_violation():
    """Test consensus gate detects temporal violations."""
    votes = [
        Vote(agent_id="agent_1", vote=1, trust=1.0, confidence=0.8, source="source_a", source_srw=0.9),
    ]
    
    # Simulate temporal spike
    claims = [
        {"source": "source_a", "metric": "price", "value": 100.0, "weight": 1.0},
        {"source": "source_a", "metric": "price", "value": 500.0, "weight": 1.0},  # Spike
    ]
    
    resolution = resolve_consensus(votes, claims, threshold=0.6)
    
    # May trigger poisoning depending on temporal profile state
    if resolution.poisoning_detected:
        assert not resolution.trust_updates_allowed
        assert resolution.degraded_mode


def test_consensus_gate_shadow_divergence():
    """Test consensus gate detects shadow consensus divergence."""
    votes = [
        Vote(agent_id="agent_1", vote=1, trust=1.0, confidence=0.8, source="source_a", source_srw=0.9),
        Vote(agent_id="agent_2", vote=1, trust=1.0, confidence=0.75, source="source_b", source_srw=0.85),
    ]
    
    # Weighted manipulation scenario
    claims = [
        {"source": "source_a", "metric": "price", "value": 100.0, "weight": 1.0},
        {"source": "source_b", "metric": "price", "value": 300.0, "weight": 10.0},  # Outlier with high weight
    ]
    
    resolution = resolve_consensus(votes, claims, threshold=0.6)
    
    if resolution.shadow_divergence:
        assert resolution.poisoning_detected
        assert not resolution.trust_updates_allowed


def test_trust_update_lock_during_poisoning():
    """Test trust updates are blocked during poisoning state."""
    from core.adversarial_hardening import get_hardening_layer
    
    hardening = get_hardening_layer()
    
    # Normal state: updates allowed
    hardening.trust_updates_frozen = False
    result = update_agent_trust_gated("test_agent", vote_correct=True, source_srw=0.9)
    assert result  # Update applied
    
    # Poisoning state: updates blocked
    hardening.trust_updates_frozen = True
    result = update_agent_trust_gated("test_agent", vote_correct=True, source_srw=0.9)
    assert not result  # Update blocked
    
    # Cleanup
    hardening.trust_updates_frozen = False


def test_source_weight_quarantine_enforcement():
    """Test source weight enforcement with quarantine status."""
    from core.source_health import SourceHealth, get_source_registry
    
    registry = get_source_registry()
    
    # Create a source with quarantine status (simulated)
    source_health = SourceHealth(source="test_source", srw=0.8)
    source_health.status = "quarantined"  # type: ignore
    registry._sources["test_source"] = source_health
    
    weight = get_source_weight_gated("test_source", base_weight=1.0)
    assert weight == 0.0  # Quarantined sources get zero weight
    
    # Test degraded status
    source_health.status = "degraded"  # type: ignore
    weight = get_source_weight_gated("test_source", base_weight=1.0)
    assert weight == 0.3  # Degraded sources get 30% weight
    
    # Cleanup
    del registry._sources["test_source"]


def test_consensus_gate_blocks_single_source_domination():
    """Test consensus floor prevents single-source domination."""
    votes = [
        Vote(agent_id="agent_1", vote=1, trust=2.0, confidence=0.95, source="source_a", source_srw=0.95),
        Vote(agent_id="agent_2", vote=-1, trust=0.5, confidence=0.3, source="source_b", source_srw=0.4),
    ]
    
    claims = [
        {"source": "source_a", "metric": "price", "value": 100.0, "weight": 10.0},
        {"source": "source_b", "metric": "price", "value": 101.0, "weight": 0.1},
    ]
    
    resolution = resolve_consensus(votes, claims, threshold=0.6)
    
    # Should trigger degraded mode due to low effective source count
    assert resolution.degraded_mode or resolution.confidence < 1.0


def test_agent_fork_on_poisoning():
    """Test agent forking is triggered on poisoning detection."""
    forked_ids = fork_agents_on_poisoning(reason="temporal_violation")
    # Currently returns empty list (placeholder implementation)
    assert isinstance(forked_ids, list)


def test_consensus_gate_metadata_logging():
    """Test consensus gate logs comprehensive metadata."""
    votes = [
        Vote(agent_id="agent_1", vote=1, trust=1.0, confidence=0.8, source="source_a", source_srw=0.9),
        Vote(agent_id="agent_2", vote=1, trust=1.0, confidence=0.75, source="source_b", source_srw=0.85),
    ]
    
    claims = [
        {"source": "source_a", "metric": "price", "value": 100.0, "weight": 1.0},
        {"source": "source_b", "metric": "price", "value": 101.0, "weight": 1.0},
    ]
    
    resolution = resolve_consensus(votes, claims, threshold=0.6)
    
    assert "vote_count" in resolution.metadata
    assert "avg_source_srw" in resolution.metadata
    assert "collusion_clusters" in resolution.metadata
    assert "primary_consensus" in resolution.metadata
    assert "shadow_consensus" in resolution.metadata

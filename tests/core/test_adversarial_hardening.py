"""Tests for Stage 6.5 adversarial hardening layer."""

from __future__ import annotations

import pytest

from core.adversarial_hardening import (
    AdversarialHardeningLayer,
    ShadowConsensus,
    SourceAgreementGraph,
    TemporalProfile,
)


pytestmark = pytest.mark.safety_critical


def test_temporal_profile_normal_updates():
    """Test temporal profile accepts normal gradual changes."""
    profile = TemporalProfile(source="test_source", metric="price", max_slope=0.01)
    
    # Gradual updates should not trigger violations
    assert not profile.update(100.0)
    assert not profile.update(100.5)
    assert not profile.update(101.0)
    assert profile.suspicion_counter == 0


def test_temporal_profile_detects_spike():
    """Test temporal profile detects sudden spikes."""
    profile = TemporalProfile(source="test_source", metric="price", max_slope=0.01)
    
    # Build baseline
    profile.update(100.0)
    profile.update(100.5)
    profile.update(101.0)
    
    # Sudden spike should trigger violation
    violation = profile.update(150.0)  # 50% jump
    assert violation
    assert profile.suspicion_counter > 0


def test_shadow_consensus_normal_agreement():
    """Test shadow consensus when primary and shadow agree."""
    shadow = ShadowConsensus(divergence_threshold=0.15)
    
    claims = [
        {"value": 100.0, "weight": 1.0},
        {"value": 102.0, "weight": 1.0},
        {"value": 101.0, "weight": 1.0},
    ]
    
    primary, shadow_val, alert = shadow.compute(claims)
    assert not alert
    assert abs(primary - shadow_val) < 15.0  # Within threshold


def test_shadow_consensus_detects_divergence():
    """Test shadow consensus detects weighted manipulation."""
    shadow = ShadowConsensus(divergence_threshold=0.15)
    
    # One source with extreme value and high weight
    claims = [
        {"value": 100.0, "weight": 1.0},
        {"value": 102.0, "weight": 1.0},
        {"value": 200.0, "weight": 10.0},  # Weighted outlier
    ]
    
    primary, shadow_val, alert = shadow.compute(claims)
    assert alert  # Should detect divergence
    assert shadow.poisoning_suspected


def test_confidence_inversion_penalty():
    """Test confidence inversion penalty for overconfident unreliable sources."""
    layer = AdversarialHardeningLayer(confidence_inversion_threshold=0.6)
    
    # High confidence + low reliability = penalty
    penalty = layer.apply_confidence_inversion_penalty(
        claim_confidence=0.95,
        source_reliability=0.4,
    )
    assert penalty == 0.5
    
    # Normal case = no penalty
    penalty = layer.apply_confidence_inversion_penalty(
        claim_confidence=0.8,
        source_reliability=0.7,
    )
    assert penalty == 1.0


def test_consensus_floor_enforcement():
    """Test consensus floor enforces minimum effective sources."""
    layer = AdversarialHardeningLayer(min_effective_sources=3)
    
    # Too few effective sources
    weights = [0.8, 0.05, 0.05]  # Only 1 effective
    multiplier = layer.check_consensus_floor(weights)
    assert multiplier == 0.5
    
    # Sufficient effective sources
    weights = [0.8, 0.6, 0.4]  # 3 effective
    multiplier = layer.check_consensus_floor(weights)
    assert multiplier == 1.0


def test_collusion_detection():
    """Test collusion detection identifies suspect clusters."""
    graph = SourceAgreementGraph()
    
    # Simulate two sources moving together, against the rest
    for _ in range(15):
        graph.record_delta("source_a", 0.5)
        graph.record_delta("source_b", 0.52)
        graph.record_delta("source_c", -0.3)
        graph.record_delta("source_d", -0.28)
    
    clusters = graph.detect_collusion(threshold_internal=0.9, threshold_external=-0.5)
    # Should detect at least one cluster
    assert len(clusters) > 0


def test_collusion_detection_is_deterministic_and_sign_aware():
    """Repeated agreement should yield deterministic clusters even for constant signals."""
    graph = SourceAgreementGraph(window_size=12, min_samples=6)

    for _ in range(12):
        graph.record_delta("sybil_a", 0.5)
        graph.record_delta("sybil_b", 0.5)
        graph.record_delta("honest", -0.2)

    clusters = graph.detect_collusion(threshold_internal=0.7, threshold_external=-0.1)
    assert clusters == [["sybil_a", "sybil_b"]]


def test_collusion_detection_respects_thresholds_and_limits_false_positive():
    """Low agreement pairs should not be clustered."""
    graph = SourceAgreementGraph(window_size=15, min_samples=8)

    for idx in range(15):
        graph.record_delta("noisy_a", (-1) ** idx * 0.3)
        graph.record_delta("noisy_b", (-1) ** (idx + 1) * 0.25)
        graph.record_delta("honest", 0.1)

    clusters = graph.detect_collusion(threshold_internal=0.85, threshold_external=0.2)
    assert clusters == []


def test_hardening_layer_integration():
    """Test full hardening layer workflow."""
    layer = AdversarialHardeningLayer()
    
    # Normal operation
    assert not layer.trust_updates_frozen
    
    # Temporal check
    violation = layer.check_temporal_consistency("test_src", "metric", 100.0)
    assert not violation
    
    # Shadow consensus with divergence
    claims = [
        {"value": 100.0, "weight": 1.0},
        {"value": 300.0, "weight": 5.0},
    ]
    primary, shadow, alert = layer.run_shadow_consensus_check(claims)
    
    if alert:
        assert layer.trust_updates_frozen
        assert layer.poisoning_alert_count > 0
    
    # Status check
    status = layer.hardening_status()
    assert "trust_updates_frozen" in status
    assert "poisoning_alert_count" in status


def test_hardening_layer_recovery():
    """Test hardening layer can recover after poisoning alert."""
    layer = AdversarialHardeningLayer()
    
    # Trigger alert
    layer.trust_updates_frozen = True
    layer.poisoning_alert_count = 3
    
    # Reset
    layer.reset_poisoning_state()
    
    assert not layer.trust_updates_frozen
    assert layer.poisoning_alert_count == 0

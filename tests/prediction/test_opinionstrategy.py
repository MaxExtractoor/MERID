"""Tests for C2: confidence clamp in opinion strategies."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import pytest
from merid.prediction.opinion_strategy import (
    HashBiasStrategy, MeanReversionStrategy, CalibrationAwareStrategy,
    OpinionEstimate, OpinionExplanation,
)

def test_hash_bias_no_phantom_fallback():
    s = HashBiasStrategy(bias_range=0.10)
    est = s.estimate("agent1", "BTC-2024", 0.40)
    if est:
        assert "fallback" not in est.explanation.rationale
        assert "clamped" not in est.explanation.rationale or "confidence_clamped_at" in est.explanation.rationale

def test_confidence_clamped_when_high():
    s = HashBiasStrategy(bias_range=0.50, max_confidence=0.50)
    est = s.estimate("agent1", "BTC-2024", 0.30)
    if est:
        assert est.confidence <= 0.50
        if "confidence_clamped_at" in est.explanation.rationale:
            assert "0.5" in est.explanation.rationale

def test_no_clamp_tag_when_below_max():
    s = HashBiasStrategy(bias_range=0.05, max_confidence=0.95)
    est = s.estimate("agent1", "BTC-2024", 0.55)
    if est:
        assert est.confidence <= 0.95
        if est.confidence < 0.95:
            assert "confidence_clamped_at" not in est.explanation.rationale

def test_mean_reversion_clamp():
    s = MeanReversionStrategy(reversion_strength=0.5, max_confidence=0.40)
    est = s.estimate("agent1", "BTC", 0.90)
    if est:
        assert est.confidence <= 0.40

def test_calibration_aware_clamp():
    s = CalibrationAwareStrategy(blend_weight=0.9, max_confidence=0.45)
    est = s.estimate("agent1", "BTC", 0.10, category="crypto")
    if est:
        assert est.confidence <= 0.45

def test_default_max_confidence_is_095():
    s = HashBiasStrategy()
    assert s.max_confidence == 0.95

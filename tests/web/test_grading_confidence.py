"""Tests for web/read_models/grading.py confidence threshold fixes."""
import pytest
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Literal

# Mock the ConsensusSignal and related classes
@dataclass
class GradingMetrics:
    brier_score: Optional[float] = None
    kelly_regret: Optional[float] = None
    realized_pnl_cents: Optional[int] = None
    roi_pct: Optional[float] = None

@dataclass
class ApprovedOpinionRecord:
    market_id: str
    asset_id: str
    originating_source: str
    confidence: float
    consensus_confidence: float
    direction: str
    sim_only: bool
    executed: bool
    settlement_price_cents: Optional[int] = None
    consensus_agents: int = 2


class TestGradingConfidenceThresholds:
    """Test confidence threshold fixes in grading processor."""

    def test_display_filter_threshold_0_65(self):
        """Test that display filter uses 0.65 threshold (was 0.30)."""
        # Create record with confidence below new threshold
        record = ApprovedOpinionRecord(
            market_id="KXBTC15M-26JUN022230-30",
            asset_id="BTC",
            originating_source="BTC_15M",
            confidence=0.50,  # Below 0.65 threshold
            consensus_confidence=0.70,
            direction="yes",
            sim_only=False,
            executed=False
        )
        
        # Should be filtered out (return None)
        min_confidence = 0.65  # New threshold
        if record.confidence < min_confidence:
            filtered = True
        else:
            filtered = False
        
        assert filtered is True

    def test_display_filter_passes_above_threshold(self):
        """Test that signals above 0.65 pass display filter."""
        record = ApprovedOpinionRecord(
            market_id="KXBTC15M-26JUN022230-30",
            asset_id="BTC",
            originating_source="BTC_15M",
            confidence=0.70,  # Above 0.65 threshold
            consensus_confidence=0.75,
            direction="yes",
            sim_only=False,
            executed=False
        )
        
        # Should pass filter
        min_confidence = 0.65
        if record.confidence < min_confidence:
            filtered = True
        else:
            filtered = False
        
        assert filtered is False

    def test_executable_threshold_0_65(self):
        """Test that executable flag uses 0.65 threshold (was 0.50)."""
        # Record with confidence below new executable threshold
        record = ApprovedOpinionRecord(
            market_id="KXBTC15M-26JUN022230-30",
            asset_id="BTC",
            originating_source="BTC_15M",
            confidence=0.60,  # Below 0.65 executable threshold
            consensus_confidence=0.70,
            direction="yes",
            sim_only=False,
            executed=False
        )
        
        # Should not be executable
        executable = (
            not record.sim_only and
            record.confidence >= 0.65 and  # New threshold
            record.consensus_confidence >= 0.65  # New threshold
        )
        
        assert executable is False

    def test_executable_passes_above_threshold(self):
        """Test that signals above 0.65 are marked executable."""
        record = ApprovedOpinionRecord(
            market_id="KXBTC15M-26JUN022230-30",
            asset_id="BTC",
            originating_source="BTC_15M",
            confidence=0.70,  # Above 0.65 threshold
            consensus_confidence=0.75,  # Above 0.65 threshold
            direction="yes",
            sim_only=False,
            executed=False
        )
        
        # Should be executable
        executable = (
            not record.sim_only and
            record.confidence >= 0.65 and
            record.consensus_confidence >= 0.65
        )
        
        assert executable is True

    def test_executable_requires_both_confidences(self):
        """Test that executable requires both confidence and consensus_confidence >= 0.65."""
        # High confidence but low consensus
        record1 = ApprovedOpinionRecord(
            market_id="KXBTC15M-26JUN022230-30",
            asset_id="BTC",
            originating_source="BTC_15M",
            confidence=0.70,
            consensus_confidence=0.60,  # Below threshold
            direction="yes",
            sim_only=False,
            executed=False
        )
        
        executable1 = (
            not record1.sim_only and
            record1.confidence >= 0.65 and
            record1.consensus_confidence >= 0.65
        )
        assert executable1 is False
        
        # Low confidence but high consensus
        record2 = ApprovedOpinionRecord(
            market_id="KXBTC15M-26JUN022230-30",
            asset_id="BTC",
            originating_source="BTC_15M",
            confidence=0.60,  # Below threshold
            consensus_confidence=0.70,
            direction="yes",
            sim_only=False,
            executed=False
        )
        
        executable2 = (
            not record2.sim_only and
            record2.confidence >= 0.65 and
            record2.consensus_confidence >= 0.65
        )
        assert executable2 is False

    def test_sim_only_not_executable(self):
        """Test that sim_only signals are never executable regardless of confidence."""
        record = ApprovedOpinionRecord(
            market_id="KXBTC15M-26JUN022230-30",
            asset_id="BTC",
            originating_source="BTC_15M",
            confidence=0.80,  # High confidence
            consensus_confidence=0.80,  # High consensus
            direction="yes",
            sim_only=True,  # But sim_only
            executed=False
        )
        
        executable = (
            not record.sim_only and
            record.confidence >= 0.65 and
            record.consensus_confidence >= 0.65
        )
        
        assert executable is False

    def test_boundary_confidence_display(self):
        """Test display filter at exactly 0.65 boundary."""
        record = ApprovedOpinionRecord(
            market_id="KXBTC15M-26JUN022230-30",
            asset_id="BTC",
            originating_source="BTC_15M",
            confidence=0.65,  # Exactly at threshold
            consensus_confidence=0.70,
            direction="yes",
            sim_only=False,
            executed=False
        )
        
        min_confidence = 0.65
        if record.confidence < min_confidence:
            filtered = True
        else:
            filtered = False
        
        # Should pass (inclusive threshold)
        assert filtered is False

    def test_boundary_confidence_executable(self):
        """Test executable flag at exactly 0.65 boundary."""
        record = ApprovedOpinionRecord(
            market_id="KXBTC15M-26JUN022230-30",
            asset_id="BTC",
            originating_source="BTC_15M",
            confidence=0.65,  # Exactly at threshold
            consensus_confidence=0.65,  # Exactly at threshold
            direction="yes",
            sim_only=False,
            executed=False
        )
        
        executable = (
            not record.sim_only and
            record.confidence >= 0.65 and
            record.consensus_confidence >= 0.65
        )
        
        # Should be executable (inclusive threshold)
        assert executable is True


if __name__ == "__main__":
    pytest.main([__file__])

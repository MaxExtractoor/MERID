"""Tests for core/consensus_math.py."""
import pytest
from core.consensus_math import Vote, ConsensusResult, compute_consensus


class TestVote:
    """Test Vote dataclass."""

    def test_creation(self):
        """Test Vote creation."""
        vote = Vote(
            agent_id="agent1",
            vote=1,
            trust=1.5,
            confidence=0.8,
            source="twitter",
            source_srw=0.9
        )
        assert vote.agent_id == "agent1"
        assert vote.vote == 1
        assert vote.trust == 1.5
        assert vote.confidence == 0.8
        assert vote.source == "twitter"
        assert vote.source_srw == 0.9


class TestConsensusResult:
    """Test ConsensusResult dataclass."""

    def test_creation(self):
        """Test ConsensusResult creation."""
        result = ConsensusResult(
            consensus_score=0.75,
            approved=True,
            vote_count=5,
            avg_source_srw=0.85,
            fallback_ratio=0.2,
            total_weight=10.0
        )
        assert result.consensus_score == 0.75
        assert result.approved is True
        assert result.vote_count == 5

    def test_to_dict(self):
        """Test ConsensusResult to_dict method."""
        result = ConsensusResult(
            consensus_score=0.756789,
            approved=True,
            vote_count=5,
            avg_source_srw=0.852345,
            fallback_ratio=0.234567,
            total_weight=10.123456
        )
        d = result.to_dict()
        assert d["consensus_score"] == 0.7568  # Rounded to 4 decimals
        assert d["approved"] is True
        assert d["vote_count"] == 5
        assert d["avg_source_srw"] == 0.8523


class TestComputeConsensus:
    """Test compute_consensus function."""

    def test_empty_votes(self):
        """Test consensus with no votes."""
        result = compute_consensus([])
        assert result.consensus_score == 0.0
        assert result.approved is False
        assert result.vote_count == 0

    def test_unanimous_positive(self):
        """Test unanimous positive votes."""
        votes = [
            Vote("a1", 1, 1.0, 1.0, "s1", 0.9),
            Vote("a2", 1, 1.0, 1.0, "s1", 0.9),
            Vote("a3", 1, 1.0, 1.0, "s1", 0.9)
        ]
        result = compute_consensus(votes, threshold=0.6)
        assert result.consensus_score == 1.0
        assert result.approved is True
        assert result.vote_count == 3

    def test_unanimous_negative(self):
        """Test unanimous negative votes."""
        votes = [
            Vote("a1", -1, 1.0, 1.0, "s1", 0.9),
            Vote("a2", -1, 1.0, 1.0, "s1", 0.9),
            Vote("a3", -1, 1.0, 1.0, "s1", 0.9)
        ]
        result = compute_consensus(votes, threshold=0.6)
        assert result.consensus_score == -1.0
        assert result.approved is False

    def test_mixed_votes(self):
        """Test mixed positive and negative votes."""
        votes = [
            Vote("a1", 1, 1.0, 1.0, "s1", 0.9),
            Vote("a2", 1, 1.0, 1.0, "s1", 0.9),
            Vote("a3", -1, 1.0, 1.0, "s1", 0.9)
        ]
        result = compute_consensus(votes, threshold=0.6)
        # 2 positive, 1 negative -> score should be positive but less than 1
        assert 0 < result.consensus_score < 1
        assert result.vote_count == 3

    def test_weighted_votes(self):
        """Test votes with different weights."""
        votes = [
            Vote("a1", 1, 2.0, 1.0, "s1", 0.9),  # High trust
            Vote("a2", -1, 0.5, 1.0, "s1", 0.9),  # Low trust
        ]
        result = compute_consensus(votes)
        # High trust positive should outweigh low trust negative
        assert result.consensus_score > 0

    def test_confidence_weighting(self):
        """Test confidence affects weighting."""
        votes = [
            Vote("a1", 1, 1.0, 0.9, "s1", 0.9),  # High confidence
            Vote("a2", -1, 1.0, 0.1, "s1", 0.9),  # Low confidence
        ]
        result = compute_consensus(votes)
        # High confidence positive should outweigh low confidence negative
        assert result.consensus_score > 0

    def test_threshold_boundary(self):
        """Test threshold boundary."""
        votes = [
            Vote("a1", 1, 1.0, 0.6, "s1", 0.9),
            Vote("a2", 1, 1.0, 0.6, "s1", 0.9),
            Vote("a3", -1, 1.0, 0.6, "s1", 0.9)
        ]
        result = compute_consensus(votes, threshold=0.5)
        # Should be approved at 0.5 threshold
        assert result.approved == (result.consensus_score >= 0.5)

    def test_fallback_ratio(self):
        """Test fallback ratio calculation."""
        votes = [
            Vote("a1", 1, 1.0, 1.0, "s1", 0.9),   # Normal SRW
            Vote("a2", 1, 1.0, 1.0, "s1", 0.5),   # Low SRW (fallback)
        ]
        result = compute_consensus(votes)
        assert result.fallback_ratio == 0.5  # 1 out of 2 is fallback

    def test_avg_source_srw(self):
        """Test average source SRW calculation."""
        votes = [
            Vote("a1", 1, 1.0, 1.0, "s1", 0.9),
            Vote("a2", 1, 1.0, 1.0, "s1", 0.7),
        ]
        result = compute_consensus(votes)
        assert result.avg_source_srw == 0.8  # Average of 0.9 and 0.7

    def test_total_weight(self):
        """Test total weight calculation."""
        votes = [
            Vote("a1", 1, 2.0, 0.5, "s1", 0.9),  # weight = 1.0
            Vote("a2", 1, 2.0, 0.5, "s1", 0.9),  # weight = 1.0
        ]
        result = compute_consensus(votes)
        assert result.total_weight == 2.0  # 1.0 + 1.0

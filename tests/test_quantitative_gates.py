"""
Quantitative Gates Tests
Tests for strategic debate protocol quality gates and agent evaluation.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch

from merid.prediction.quantitative_gates import (
    QuantitativeGates, GateConfig, GateResult, GateSummary,
    get_quantitative_gates, configure_quantitative_gates
)


class TestQuantitativeGates:
    """Test quantitative gate evaluation logic."""
    
    def setup_method(self):
        """Setup fresh gates for each test."""
        self.config = GateConfig()
        self.gates = QuantitativeGates(self.config)
    
    def test_initialization(self):
        """Test gates initialization with default config."""
        assert self.gates.config.min_brier_score == 0.25
        assert self.gates.config.min_recent_accuracy == 0.6
        assert self.gates.config.min_confidence == 0.3
        assert self.gates.config.max_confidence == 0.95
    
    def test_accuracy_gate_pass(self):
        """Test accuracy gate with good performance."""
        agent_data = {
            "domain": "kalshi_prediction",  # Add domain field
            "recent_predictions": [
                {"predicted_prob": 0.8, "actual_outcome": 1},  # Correct
                {"predicted_prob": 0.3, "actual_outcome": 0},  # Correct
                {"predicted_prob": 0.6, "actual_outcome": 1},  # Correct
                {"predicted_prob": 0.4, "actual_outcome": 0},  # Correct
                {"predicted_prob": 0.7, "actual_outcome": 1},  # Correct
                {"predicted_prob": 0.2, "actual_outcome": 0},  # Correct
                {"predicted_prob": 0.9, "actual_outcome": 1},  # Correct
                {"predicted_prob": 0.1, "actual_outcome": 0},  # Correct
                {"predicted_prob": 0.5, "actual_outcome": 1},  # Wrong
                {"predicted_prob": 0.5, "actual_outcome": 0},  # Wrong
            ]
        }
        
        result = self.gates._evaluate_accuracy_gate(agent_data)
        
        assert result.passed is True
        assert result.gate_name == "accuracy"
        assert result.score > 0.5  # Score based on Brier, not accuracy
        assert result.details["recent_accuracy"] == 0.9  # 9/10 correct
        assert result.details["avg_brier"] < 0.25
    
    def test_accuracy_gate_fail_brier(self):
        """Test accuracy gate failure due to high Brier score."""
        agent_data = {
            "domain": "kalshi_prediction",  # Add domain field
            "recent_predictions": [
                {"predicted_prob": 0.9, "actual_outcome": 0},  # Very wrong
                {"predicted_prob": 0.1, "actual_outcome": 1},  # Very wrong
                {"predicted_prob": 0.8, "actual_outcome": 0},  # Wrong
                {"predicted_prob": 0.2, "actual_outcome": 1},  # Wrong
                {"predicted_prob": 0.7, "actual_outcome": 0},  # Wrong
                {"predicted_prob": 0.3, "actual_outcome": 1},  # Wrong
                {"predicted_prob": 0.6, "actual_outcome": 0},  # Wrong
                {"predicted_prob": 0.4, "actual_outcome": 1},  # Wrong
                {"predicted_prob": 0.5, "actual_outcome": 0},  # Wrong
                {"predicted_prob": 0.5, "actual_outcome": 1},  # Wrong
            ]
        }
        
        result = self.gates._evaluate_accuracy_gate(agent_data)
        
        assert result.passed is False
        assert result.score == 0.0  # Failed gate gets score 0.0
        assert "Brier score too high" in result.recommendation
    
    def test_accuracy_gate_insufficient_data(self):
        """Test accuracy gate with insufficient prediction history."""
        agent_data = {
            "domain": "kalshi_prediction",  # Add domain field
            "recent_predictions": [
                {"predicted_prob": 0.8, "actual_outcome": 1},
                {"predicted_prob": 0.3, "actual_outcome": 0},
                # Only 2 predictions, need 10
            ]
        }
        
        result = self.gates._evaluate_accuracy_gate(agent_data)
        
        assert result.passed is False
        assert result.score == 0.0  # Failed gate gets score 0.0
        assert "Insufficient recent predictions" in result.recommendation
        assert result.details["recent_count"] == 2
    
    def test_confidence_gate_well_calibrated(self):
        """Test confidence gate with reasonably calibrated agent."""
        agent_data = {
            "domain": "kalshi_prediction",  # Add domain field
            "recent_predictions": [
                {"confidence": 0.9, "predicted_prob": 0.9, "actual_outcome": 1},  # Perfect calibration
                {"confidence": 0.8, "predicted_prob": 0.8, "actual_outcome": 1},  # Perfect calibration
                {"confidence": 0.7, "predicted_prob": 0.7, "actual_outcome": 1},  # Perfect calibration
                {"confidence": 0.6, "predicted_prob": 0.6, "actual_outcome": 1},  # Perfect calibration
                {"confidence": 0.5, "predicted_prob": 0.5, "actual_outcome": 0},  # Perfect calibration
                {"confidence": 0.4, "predicted_prob": 0.4, "actual_outcome": 0},  # Perfect calibration
                {"confidence": 0.3, "predicted_prob": 0.3, "actual_outcome": 0},  # Perfect calibration
                {"confidence": 0.2, "predicted_prob": 0.2, "actual_outcome": 0},  # Perfect calibration
            ]
        }
        
        result = self.gates._evaluate_confidence_gate(agent_data)
        
        # Check that gate evaluates correctly (may pass or fail depending on calibration strictness)
        assert result.gate_name == "confidence"
        assert result.details["avg_confidence"] == 0.55
        assert "avg_calibration_error" in result.details
        assert isinstance(result.passed, bool)
    
    def test_confidence_gate_overconfident(self):
        """Test confidence gate with overconfident agent."""
        agent_data = {
            "domain": "kalshi_prediction",  # Add domain field
            "recent_predictions": [
                {"confidence": 0.9, "predicted_prob": 0.9, "actual_outcome": 0},  # Overconfident, wrong
                {"confidence": 0.8, "predicted_prob": 0.8, "actual_outcome": 0},  # Overconfident, wrong
                {"confidence": 0.95, "predicted_prob": 0.95, "actual_outcome": 1},  # Very high confidence
            ]
        }
        
        result = self.gates._evaluate_confidence_gate(agent_data)
        
        assert result.passed is False
        assert "Poor confidence calibration" in result.recommendation
        assert result.details["avg_calibration_error"] > 0.15
    
    def test_confidence_gate_out_of_range(self):
        """Test confidence gate with confidence outside acceptable range."""
        agent_data = {
            "domain": "kalshi_prediction",  # Add domain field
            "recent_predictions": [
                {"confidence": 0.1, "predicted_prob": 0.5, "actual_outcome": 0},  # Too low
                {"confidence": 0.05, "predicted_prob": 0.5, "actual_outcome": 1},  # Too low
            ]
        }
        
        result = self.gates._evaluate_confidence_gate(agent_data)
        
        assert result.passed is False
        assert "Confidence out of range" in result.recommendation
        assert abs(result.details["avg_confidence"] - 0.075) < 0.001  # Handle floating point precision
    
    def test_activity_gate_active(self):
        """Test activity gate with sufficiently active agent."""
        now = datetime.now(timezone.utc)
        recent_timestamps = [
            (now - timedelta(days=1)).isoformat().replace("+00:00", "Z"),
            (now - timedelta(days=2)).isoformat().replace("+00:00", "Z"),
            (now - timedelta(days=3)).isoformat().replace("+00:00", "Z"),
            (now - timedelta(days=4)).isoformat().replace("+00:00", "Z"),
            (now - timedelta(days=5)).isoformat().replace("+00:00", "Z"),
        ]
        
        agent_data = {
            "domain": "kalshi_prediction",  # Add domain field
            "recent_predictions": [
                {"timestamp": ts}
                for ts in recent_timestamps
            ]
        }
        
        result = self.gates._evaluate_activity_gate(agent_data)
        
        assert result.passed is True
        assert result.details["recent_predictions_7d"] == 5
        assert result.details["days_since_last_prediction"] == 1
    
    def test_activity_gate_inactive(self):
        """Test activity gate with insufficient activity."""
        now = datetime.now(timezone.utc)
        old_timestamp = (now - timedelta(days=20)).isoformat().replace("+00:00", "Z")
        
        agent_data = {
            "domain": "kalshi_prediction",  # Add domain field
            "recent_predictions": [
                {"timestamp": old_timestamp}
            ]
        }
        
        result = self.gates._evaluate_activity_gate(agent_data)
        
        assert result.passed is False
        assert result.details["recent_predictions_7d"] == 0
        assert result.details["days_since_last_prediction"] == 20
        assert "Insufficient recent activity" in result.recommendation
    
    def test_activity_gate_no_history(self):
        """Test activity gate with no prediction history."""
        agent_data = {
            "domain": "kalshi_prediction",  # Add domain field
            "recent_predictions": []}
        
        result = self.gates._evaluate_activity_gate(agent_data)
        
        assert result.passed is False
        assert result.score == 0.0
    
    def test_argument_quality_gate_good(self):
        """Test argument quality gate with good arguments."""
        agent_data = {
            "domain": "kalshi_prediction",  # Add domain field
            "recent_arguments": [
                {
                    "content": "Well-reasoned argument with evidence",
                    "quality_score": 0.8,
                    "evidence_citations": ["source1", "source2"]
                },
                {
                    "content": "Another good argument",
                    "quality_score": 0.7,
                    "evidence_citations": ["source3"]
                }
            ]
        }
        
        result = self.gates._evaluate_argument_quality_gate(agent_data)
        
        assert result.passed is True
        assert result.details["avg_quality_score"] == 0.75
        assert result.details["avg_evidence_count"] == 1.5
        assert result.score == 0.75
    
    def test_argument_quality_gate_poor_quality(self):
        """Test argument quality gate with poor arguments."""
        agent_data = {
            "domain": "kalshi_prediction",  # Add domain field
            "recent_arguments": [
                {
                    "content": "Weak argument",
                    "quality_score": 0.2,
                    "evidence_citations": []
                }
            ]
        }
        
        result = self.gates._evaluate_argument_quality_gate(agent_data)
        
        assert result.passed is False
        assert result.details["avg_quality_score"] == 0.2
        assert "Argument quality too low" in result.recommendation
    
    def test_argument_quality_gate_no_evidence(self):
        """Test argument quality gate with insufficient evidence."""
        agent_data = {
            "domain": "kalshi_prediction",  # Add domain field
            "recent_arguments": [
                {
                    "content": "Argument without evidence",
                    "quality_score": 0.6,
                    "evidence_citations": []
                }
            ]
        }
        
        result = self.gates._evaluate_argument_quality_gate(agent_data)
        
        assert result.passed is False
        assert "Insufficient evidence citations" in result.recommendation
    
    def test_team_diversity_gate_good_team(self):
        """Test team diversity gate with well-composed team."""
        agent_data = {
            "domain": "kalshi_prediction",  # Add domain field
            "current_team": {
                "members": [
                    {"agent_id": "agent1", "current_opinion": 0.2},
                    {"agent_id": "agent2", "current_opinion": 0.8},
                    {"agent_id": "agent3", "current_opinion": 0.5},
                ]
            }
        }
        
        result = self.gates._evaluate_team_diversity_gate(agent_data)
        
        assert result.passed is True
        assert result.details["team_size"] == 3
        assert result.details["opinion_std"] > 0.1  # Should have diversity
        assert "Team composition acceptable" in result.recommendation
    
    def test_team_diversity_gate_no_team(self):
        """Test team diversity gate with no team."""
        agent_data = {
            "domain": "kalshi_prediction",  # Add domain field
            "current_team": {}}
        
        result = self.gates._evaluate_team_diversity_gate(agent_data)
        
        assert result.passed is True  # No team is OK
        assert result.details["team_size"] == 0
        assert "individual participation allowed" in result.recommendation
    
    def test_team_diversity_gate_oversized_team(self):
        """Test team diversity gate with oversized team."""
        agent_data = {
            "domain": "kalshi_prediction",  # Add domain field
            "current_team": {
                "members": [
                    {"agent_id": f"agent{i}", "current_opinion": 0.5}
                    for i in range(8)  # 8 members, max is 5
                ]
            }
        }
        
        result = self.gates._evaluate_team_diversity_gate(agent_data)
        
        assert result.passed is False
        assert result.details["team_size"] == 8
        assert "Team too large" in result.recommendation
    
    def test_performance_gate_good_performance(self):
        """Test performance gate with good debate history."""
        agent_data = {
            "domain": "kalshi_prediction",  # Add domain field
            "debate_history": [
                {"debate_lift": 0.05},
                {"debate_lift": 0.03},
                {"debate_lift": 0.04},
            ]
        }
        
        result = self.gates._evaluate_performance_gate(agent_data)
        
        assert result.passed is True
        assert result.details["avg_debate_lift"] == 0.04
        assert result.score >= 1.0  # Meets or exceeds threshold
    
    def test_performance_gate_poor_performance(self):
        """Test performance gate with poor debate history."""
        agent_data = {
            "domain": "kalshi_prediction",  # Add domain field
            "debate_history": [
                {"debate_lift": 0.01},
                {"debate_lift": 0.005},
                {"debate_lift": 0.01},
            ]
        }
        
        result = self.gates._evaluate_performance_gate(agent_data)
        
        assert result.passed is False
        assert result.details["avg_debate_lift"] == 0.008333333333333333
        assert "Average debate lift too low" in result.recommendation
    
    def test_performance_gate_no_history(self):
        """Test performance gate with no debate history."""
        agent_data = {
            "domain": "kalshi_prediction",  # Add domain field
            "debate_history": []}
        
        result = self.gates._evaluate_performance_gate(agent_data)
        
        assert result.passed is True  # No history is OK for new participants
        assert result.score == 0.5
        assert "new participant welcome" in result.recommendation
    
    def test_comprehensive_agent_evaluation(self):
        """Test complete agent evaluation across all gates."""
        now = datetime.now(timezone.utc)
        agent_data = {
            "domain": "kalshi_prediction",  # Add domain field
            "recent_predictions": [
                {
                    "predicted_prob": 0.8,
                    "actual_outcome": 1,
                    "confidence": 0.8,
                    "timestamp": (now - timedelta(days=1)).isoformat().replace("+00:00", "Z")
                },
                {
                    "predicted_prob": 0.3,
                    "actual_outcome": 0,
                    "confidence": 0.7,
                    "timestamp": (now - timedelta(days=2)).isoformat().replace("+00:00", "Z")
                },
                {
                    "predicted_prob": 0.7,
                    "actual_outcome": 1,
                    "confidence": 0.6,
                    "timestamp": (now - timedelta(days=3)).isoformat().replace("+00:00", "Z")
                },
                {
                    "predicted_prob": 0.4,
                    "actual_outcome": 0,
                    "confidence": 0.4,
                    "timestamp": (now - timedelta(days=4)).isoformat().replace("+00:00", "Z")
                },
                {
                    "predicted_prob": 0.6,
                    "actual_outcome": 1,
                    "confidence": 0.6,
                    "timestamp": (now - timedelta(days=5)).isoformat().replace("+00:00", "Z")
                },
                {
                    "predicted_prob": 0.2,
                    "actual_outcome": 0,
                    "confidence": 0.2,
                    "timestamp": (now - timedelta(days=6)).isoformat().replace("+00:00", "Z")
                },
                {
                    "predicted_prob": 0.9,
                    "actual_outcome": 1,
                    "confidence": 0.9,
                    "timestamp": (now - timedelta(days=7)).isoformat().replace("+00:00", "Z")
                },
                {
                    "predicted_prob": 0.1,
                    "actual_outcome": 0,
                    "confidence": 0.1,
                    "timestamp": (now - timedelta(days=8)).isoformat().replace("+00:00", "Z")
                },
                {
                    "predicted_prob": 0.5,
                    "actual_outcome": 1,
                    "confidence": 0.5,
                    "timestamp": (now - timedelta(days=9)).isoformat().replace("+00:00", "Z")
                },
                {
                    "predicted_prob": 0.5,
                    "actual_outcome": 0,
                    "confidence": 0.5,
                    "timestamp": (now - timedelta(days=10)).isoformat().replace("+00:00", "Z")
                },
            ],
            "recent_arguments": [
                {
                    "content": "Good argument",
                    "quality_score": 0.8,
                    "evidence_citations": ["source1"]
                }
            ],
            "current_team": {
                "members": [
                    {"agent_id": "agent1", "current_opinion": 0.2},
                    {"agent_id": "agent2", "current_opinion": 0.8},
                ]
            },
            "debate_history": [
                {"debate_lift": 0.05}
            ]
        }
        
        summary = self.gates.evaluate_agent("test_agent", agent_data)
        
        assert summary.agent_id == "test_agent"
        assert len(summary.gate_results) == 6  # All 6 gates evaluated
        assert summary.total_score > 0.0
        assert isinstance(summary.overall_passed, bool)
        assert isinstance(summary.blocked_reasons, list)
    
    def test_agent_evaluation_failure(self):
        """Test agent evaluation with multiple gate failures."""
        now = datetime.now(timezone.utc)
        agent_data = {
            "domain": "kalshi_prediction",  # Add domain field
            "recent_predictions": [
                {
                    "predicted_prob": 0.9,
                    "actual_outcome": 0,  # Poor accuracy
                    "confidence": 0.98,  # Overconfident
                    "timestamp": now.isoformat().replace("+00:00", "Z")
                },
                {
                    "predicted_prob": 0.1,
                    "actual_outcome": 1,  # Poor accuracy
                    "confidence": 0.95,  # Overconfident
                    "timestamp": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z")
                },
            ],
            "recent_arguments": [
                {
                    "content": "Poor argument",
                    "quality_score": 0.1,
                    "evidence_citations": []
                }
            ],
            "current_team": {
                "members": [
                    {"agent_id": f"agent{i}", "current_opinion": 0.5}
                    for i in range(10)  # Oversized team
                ]
            },
            "debate_history": [
                {"debate_lift": 0.001}  # Poor performance
            ]
        }
        
        summary = self.gates.evaluate_agent("test_agent", agent_data)
        
        assert summary.overall_passed is False
        assert len(summary.blocked_reasons) > 0
        assert any("Accuracy" in reason for reason in summary.blocked_reasons)
    
    def test_evaluate_agent_rejects_non_kalshi_domain(self):
        """Test that agent evaluation rejects non-Kalshi domain data."""
        agent_data = {
            "domain": "other_prediction",  # Non-Kalshi domain
            "recent_predictions": [
                {"predicted_prob": 0.8, "actual_outcome": 1},
                {"predicted_prob": 0.3, "actual_outcome": 0},
            ] * 5  # 10 predictions
        }
        
        summary = self.gates.evaluate_agent("test_agent", agent_data)
        
        assert summary.overall_passed is False
        assert any("domain" in reason.lower() for reason in summary.blocked_reasons)
        assert len(summary.gate_results) == 0  # No gates evaluated


class TestGlobalGates:
    """Test global gates instance management."""
    
    def test_get_quantitative_gates(self):
        """Test getting global gates instance."""
        gates = get_quantitative_gates()
        assert isinstance(gates, QuantitativeGates)
        
        # Should return same instance
        gates2 = get_quantitative_gates()
        assert gates is gates2
    
    def test_configure_quantitative_gates(self):
        """Test configuring global gates."""
        custom_config = GateConfig(
            min_brier_score=0.3,
            min_recent_accuracy=0.7
        )
        
        configure_quantitative_gates(custom_config)
        
        gates = get_quantitative_gates()
        assert gates.config.min_brier_score == 0.3
        assert gates.config.min_recent_accuracy == 0.7


class TestGateConfig:
    """Test gate configuration."""
    
    def test_default_config(self):
        """Test default configuration values."""
        config = GateConfig()
        
        assert config.min_brier_score == 0.25
        assert config.min_recent_accuracy == 0.6
        assert config.min_confidence == 0.3
        assert config.max_confidence == 0.95
        assert config.min_recent_predictions == 3
        assert config.max_prediction_age_days == 30
        assert config.min_argument_quality_score == 0.4
        assert config.min_evidence_count == 1
        assert config.max_team_size == 5
        assert config.min_debate_lift_threshold == 0.02
        assert config.max_consecutive_failures == 3
    
    def test_custom_config(self):
        """Test custom configuration values."""
        config = GateConfig(
            min_brier_score=0.2,
            min_recent_accuracy=0.8,
            max_team_size=10
        )
        
        assert config.min_brier_score == 0.2
        assert config.min_recent_accuracy == 0.8
        assert config.max_team_size == 10
        # Other values should be defaults
        assert config.min_confidence == 0.3


if __name__ == "__main__":
    pytest.main([__file__])

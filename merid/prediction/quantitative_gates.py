"""
Quantitative Gates for Strategic Debate Protocol
Implements data-driven quality controls and decision thresholds for debate participation.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.prediction.quantitative_gates")


# ── Gate Configuration ─────────────────────────────────────────────────────

@dataclass
class GateConfig:
    """Configuration for quantitative gates."""
    
    # Accuracy gates
    min_brier_score: float = 0.25          # Max Brier score to participate
    min_recent_accuracy: float = 0.6       # Min accuracy in last 10 predictions
    accuracy_window_size: int = 10         # Window for recent accuracy check
    
    # Confidence gates
    min_confidence: float = 0.65           # Min confidence to participate (FIX: Aligned with production config, was 0.30)
    max_confidence: float = 0.95           # Max confidence (prevents overconfidence)
    confidence_calibration_threshold: float = 0.15  # Max confidence-accuracy gap
    
    # Activity gates
    min_recent_predictions: int = 3        # Min predictions in last 7 days
    max_prediction_age_days: int = 30      # Max age of predictions to consider
    
    # Debate quality gates
    min_argument_quality_score: float = 0.4 # Min quality for arguments
    min_evidence_count: int = 1             # Min evidence citations required
    max_argument_length: int = 2000         # Max characters for arguments
    
    # Team diversity gates
    min_team_disagreement: float = 0.1     # Min disagreement within team
    max_team_size: int = 5                  # Max agents per debate team
    
    # Performance gates
    min_debate_lift_threshold: float = 0.02 # Min positive lift to continue debating
    max_consecutive_failures: int = 3       # Max consecutive failed debates


@dataclass
class GateResult:
    """Result of a gate evaluation."""
    gate_name: str
    passed: bool
    score: float
    threshold: float
    details: Dict[str, Any] = field(default_factory=dict)
    recommendation: str = ""


@dataclass
class GateSummary:
    """Summary of all gate evaluations for an agent."""
    agent_id: str
    timestamp: datetime
    overall_passed: bool
    gate_results: List[GateResult] = field(default_factory=list)
    total_score: float = 0.0
    blocked_reasons: List[str] = field(default_factory=list)


class QuantitativeGates:
    """
    Implements quantitative quality gates for debate participation.
    
    Gates evaluate agents on multiple dimensions:
    - Historical accuracy and calibration
    - Confidence quality and reasonableness
    - Recent activity and engagement
    - Argument quality and evidence
    - Team composition and diversity
    - Debate performance and lift
    """
    
    def __init__(self, config: Optional[GateConfig] = None):
        self.config = config or GateConfig()
        
    def evaluate_agent(self, agent_id: str, agent_data: Dict[str, Any]) -> GateSummary:
        """
        Evaluate an agent against all quantitative gates (Kalshi prediction domain validation).
        
        Args:
            agent_id: Unique identifier for the agent
            agent_data: Agent performance and activity data
            
        Returns:
            GateSummary with detailed results and overall pass/fail
        """
        # Validate domain is Kalshi prediction
        if agent_data.get("domain") != "kalshi_prediction":
            return GateSummary(
                agent_id=agent_id,
                timestamp=datetime.now(timezone.utc),
                overall_passed=False,
                gate_results=[],
                total_score=0.0,
                blocked_reasons=["Agent data not from Kalshi prediction domain"]
            )
        
        timestamp = datetime.now(timezone.utc)
        gate_results = []
        total_score = 0.0
        blocked_reasons = []
        
        # 1. Accuracy Gate
        accuracy_result = self._evaluate_accuracy_gate(agent_data)
        gate_results.append(accuracy_result)
        total_score += accuracy_result.score
        
        if not accuracy_result.passed:
            blocked_reasons.append(f"Accuracy: {accuracy_result.recommendation}")
        
        # 2. Confidence Gate
        confidence_result = self._evaluate_confidence_gate(agent_data)
        gate_results.append(confidence_result)
        total_score += confidence_result.score
        
        if not confidence_result.passed:
            blocked_reasons.append(f"Confidence: {confidence_result.recommendation}")
        
        # 3. Activity Gate
        activity_result = self._evaluate_activity_gate(agent_data)
        gate_results.append(activity_result)
        total_score += activity_result.score
        
        if not activity_result.passed:
            blocked_reasons.append(f"Activity: {activity_result.recommendation}")
        
        # 4. Argument Quality Gate
        arg_quality_result = self._evaluate_argument_quality_gate(agent_data)
        gate_results.append(arg_quality_result)
        total_score += arg_quality_result.score
        
        if not arg_quality_result.passed:
            blocked_reasons.append(f"Argument Quality: {arg_quality_result.recommendation}")
        
        # 5. Team Diversity Gate
        diversity_result = self._evaluate_team_diversity_gate(agent_data)
        gate_results.append(diversity_result)
        total_score += diversity_result.score
        
        if not diversity_result.passed:
            blocked_reasons.append(f"Team Diversity: {diversity_result.recommendation}")
        
        # 6. Performance Gate
        performance_result = self._evaluate_performance_gate(agent_data)
        gate_results.append(performance_result)
        total_score += performance_result.score
        
        if not performance_result.passed:
            blocked_reasons.append(f"Performance: {performance_result.recommendation}")
        
        # Overall decision
        overall_passed = all(result.passed for result in gate_results)
        
        return GateSummary(
            agent_id=agent_id,
            timestamp=timestamp,
            overall_passed=overall_passed,
            gate_results=gate_results,
            total_score=total_score,
            blocked_reasons=blocked_reasons
        )
    
    def _evaluate_accuracy_gate(self, agent_data: Dict[str, Any]) -> GateResult:
        """Evaluate agent's historical accuracy and calibration."""
        
        # Get recent predictions
        recent_predictions = agent_data.get("recent_predictions", [])
        if len(recent_predictions) < self.config.accuracy_window_size:
            return GateResult(
                gate_name="accuracy",
                passed=False,
                score=0.0,
                threshold=self.config.accuracy_window_size,
                details={"recent_count": len(recent_predictions)},
                recommendation=f"Insufficient recent predictions ({len(recent_predictions)} < {self.config.accuracy_window_size})"
            )
        
        # Calculate Brier score
        brier_scores = []
        correct_predictions = 0
        
        for pred in recent_predictions[:self.config.accuracy_window_size]:
            predicted_prob = pred.get("predicted_prob", 0.5)
            actual_outcome = pred.get("actual_outcome", 0)
            
            # Brier score: (predicted - actual)^2
            brier = (predicted_prob - actual_outcome) ** 2
            brier_scores.append(brier)
            
            # Binary accuracy
            if (predicted_prob > 0.5) == actual_outcome:
                correct_predictions += 1
        
        avg_brier = statistics.mean(brier_scores)
        accuracy = correct_predictions / len(recent_predictions)
        
        # Check thresholds
        brier_passed = avg_brier <= self.config.min_brier_score
        accuracy_passed = accuracy >= self.config.min_recent_accuracy
        
        score = max(0.0, 1.0 - (avg_brier / self.config.min_brier_score))
        
        details = {
            "avg_brier": avg_brier,
            "recent_accuracy": accuracy,
            "brier_threshold": self.config.min_brier_score,
            "accuracy_threshold": self.config.min_recent_accuracy,
            "predictions_analyzed": len(recent_predictions)
        }
        
        passed = brier_passed and accuracy_passed
        recommendation = ""
        
        if not brier_passed:
            recommendation += f"Brier score too high ({avg_brier:.3f} > {self.config.min_brier_score})"
        elif not accuracy_passed:
            recommendation += f"Recent accuracy too low ({accuracy:.3f} < {self.config.min_recent_accuracy})"
        else:
            recommendation = "Accuracy metrics within acceptable range"
        
        return GateResult(
            gate_name="accuracy",
            passed=passed,
            score=score,
            threshold=self.config.min_brier_score,
            details=details,
            recommendation=recommendation
        )
    
    def _evaluate_confidence_gate(self, agent_data: Dict[str, Any]) -> GateResult:
        """Evaluate agent's confidence quality and calibration."""
        
        recent_predictions = agent_data.get("recent_predictions", [])
        if not recent_predictions:
            return GateResult(
                gate_name="confidence",
                passed=False,
                score=0.0,
                threshold=self.config.min_confidence,
                details={},
                recommendation="No prediction history to evaluate confidence"
            )
        
        # Analyze confidence distribution
        confidences = [pred.get("confidence", 0.5) for pred in recent_predictions[:20]]
        avg_confidence = statistics.mean(confidences)
        
        # Check confidence range
        in_range = (self.config.min_confidence <= avg_confidence <= self.config.max_confidence)
        
        # Calculate confidence-accuracy calibration
        calibration_errors = []
        for pred in recent_predictions[:20]:
            confidence = pred.get("confidence", 0.5)
            actual_outcome = pred.get("actual_outcome", 0)
            predicted_correct = pred.get("predicted_prob", 0.5) > 0.5
            
            # Calibration error: difference between confidence and actual correctness
            error = abs(confidence - (1.0 if predicted_correct == actual_outcome else 0.0))
            calibration_errors.append(error)
        
        avg_calibration_error = statistics.mean(calibration_errors) if calibration_errors else 0.0
        well_calibrated = avg_calibration_error <= self.config.confidence_calibration_threshold
        
        # Score based on confidence quality
        score = max(0.0, 1.0 - (avg_calibration_error / self.config.confidence_calibration_threshold))
        
        details = {
            "avg_confidence": avg_confidence,
            "confidence_range": [self.config.min_confidence, self.config.max_confidence],
            "avg_calibration_error": avg_calibration_error,
            "calibration_threshold": self.config.confidence_calibration_threshold,
            "predictions_analyzed": len(confidences)
        }
        
        passed = in_range and well_calibrated
        
        if not in_range:
            recommendation = f"Confidence out of range ({avg_confidence:.3f} not in [{self.config.min_confidence}, {self.config.max_confidence}])"
        elif not well_calibrated:
            recommendation = f"Poor confidence calibration (error {avg_calibration_error:.3f} > {self.config.confidence_calibration_threshold})"
        else:
            recommendation = "Confidence well-calibrated and within range"
        
        return GateResult(
            gate_name="confidence",
            passed=passed,
            score=score,
            threshold=self.config.confidence_calibration_threshold,
            details=details,
            recommendation=recommendation
        )
    
    def _evaluate_activity_gate(self, agent_data: Dict[str, Any]) -> GateResult:
        """Evaluate agent's recent activity and engagement."""
        
        recent_predictions = agent_data.get("recent_predictions", [])
        now = datetime.now(timezone.utc)
        
        # Count recent predictions (last 7 days)
        # BUG-N fix: guard against missing/empty timestamp strings that
        # cause datetime.fromisoformat("") to raise ValueError.
        seven_days_ago = now - timedelta(days=7)
        recent_count = 0
        for pred in recent_predictions:
            ts = pred.get("timestamp", "")
            if ts:
                try:
                    if datetime.fromisoformat(ts.replace("Z", "+00:00")) >= seven_days_ago:
                        recent_count += 1
                except (ValueError, TypeError):
                    pass

        # Check prediction age
        if recent_predictions:
            latest_pred = max(
                (p for p in recent_predictions if p.get("timestamp", "")),
                key=lambda p: p.get("timestamp", ""),
                default=None,
            )
            if latest_pred:
                try:
                    latest_time = datetime.fromisoformat(latest_pred["timestamp"].replace("Z", "+00:00"))
                    age_days = (now - latest_time).days
                except (ValueError, TypeError):
                    age_days = float('inf')
            else:
                age_days = float('inf')
        else:
            age_days = float('inf')
        
        # Check thresholds
        activity_passed = recent_count >= self.config.min_recent_predictions
        freshness_passed = age_days <= self.config.max_prediction_age_days
        
        # Score based on activity level
        score = min(1.0, recent_count / self.config.min_recent_predictions)
        
        details = {
            "recent_predictions_7d": recent_count,
            "activity_threshold": self.config.min_recent_predictions,
            "days_since_last_prediction": age_days,
            "freshness_threshold": self.config.max_prediction_age_days,
            "total_predictions": len(recent_predictions)
        }
        
        passed = activity_passed and freshness_passed
        
        if not activity_passed:
            recommendation = f"Insufficient recent activity ({recent_count} < {self.config.min_recent_predictions} in last 7 days)"
        elif not freshness_passed:
            recommendation = f"Predictions too stale ({age_days} days > {self.config.max_prediction_age_days})"
        else:
            recommendation = "Activity level acceptable"
        
        return GateResult(
            gate_name="activity",
            passed=passed,
            score=score,
            threshold=self.config.min_recent_predictions,
            details=details,
            recommendation=recommendation
        )
    
    def _evaluate_argument_quality_gate(self, agent_data: Dict[str, Any]) -> GateResult:
        """Evaluate agent's argument quality and evidence usage."""
        
        recent_arguments = agent_data.get("recent_arguments", [])
        if not recent_arguments:
            return GateResult(
                gate_name="argument_quality",
                passed=False,
                score=0.0,
                threshold=self.config.min_argument_quality_score,
                details={},
                recommendation="No argument history to evaluate quality"
            )
        
        # Analyze argument quality
        quality_scores = []
        evidence_counts = []
        length_violations = 0
        
        for arg in recent_arguments[:10]:
            # Quality score (could be based on human ratings, automated metrics, etc.)
            quality = arg.get("quality_score", 0.5)
            quality_scores.append(quality)
            
            # Evidence count
            evidence = len(arg.get("evidence_citations", []))
            evidence_counts.append(evidence)
            
            # Length check
            if len(arg.get("content", "")) > self.config.max_argument_length:
                length_violations += 1
        
        avg_quality = statistics.mean(quality_scores) if quality_scores else 0.0
        avg_evidence = statistics.mean(evidence_counts) if evidence_counts else 0.0
        
        # Check thresholds
        quality_passed = avg_quality >= self.config.min_argument_quality_score
        evidence_passed = avg_evidence >= self.config.min_evidence_count
        length_passed = length_violations == 0
        
        # Score based on quality
        score = avg_quality
        
        details = {
            "avg_quality_score": avg_quality,
            "quality_threshold": self.config.min_argument_quality_score,
            "avg_evidence_count": avg_evidence,
            "evidence_threshold": self.config.min_evidence_count,
            "length_violations": length_violations,
            "arguments_analyzed": len(recent_arguments)
        }
        
        passed = quality_passed and evidence_passed and length_passed
        
        if not quality_passed:
            recommendation = f"Argument quality too low ({avg_quality:.3f} < {self.config.min_argument_quality_score})"
        elif not evidence_passed:
            recommendation = f"Insufficient evidence citations ({avg_evidence:.1f} < {self.config.min_evidence_count})"
        elif not length_passed:
            recommendation = f"Argument length violations ({length_violations} arguments too long)"
        else:
            recommendation = "Argument quality acceptable"
        
        return GateResult(
            gate_name="argument_quality",
            passed=passed,
            score=score,
            threshold=self.config.min_argument_quality_score,
            details=details,
            recommendation=recommendation
        )
    
    def _evaluate_team_diversity_gate(self, agent_data: Dict[str, Any]) -> GateResult:
        """Evaluate team composition and diversity for debate participation."""
        
        current_team = agent_data.get("current_team", {})
        team_members = current_team.get("members", [])
        
        if not team_members:
            return GateResult(
                gate_name="team_diversity",
                passed=True,  # No team is OK for individual participation
                score=1.0,
                threshold=self.config.min_team_disagreement,
                details={"team_size": 0},
                recommendation="No current team - individual participation allowed"
            )
        
        # Check team size
        size_passed = len(team_members) <= self.config.max_team_size
        
        # Calculate opinion diversity within team
        team_opinions = [member.get("current_opinion", 0.5) for member in team_members]
        if len(team_opinions) > 1:
            opinion_std = statistics.stdev(team_opinions)
            diversity_passed = opinion_std >= self.config.min_team_disagreement
        else:
            opinion_std = 0.0
            diversity_passed = False  # Single person team has no diversity
        
        # Score based on optimal team size and diversity
        size_score = 1.0 if size_passed else max(0.0, 1.0 - (len(team_members) - self.config.max_team_size) / self.config.max_team_size)
        diversity_score = min(1.0, opinion_std / self.config.min_team_disagreement) if self.config.min_team_disagreement > 0 else 1.0
        score = (size_score + diversity_score) / 2.0
        
        details = {
            "team_size": len(team_members),
            "size_threshold": self.config.max_team_size,
            "opinion_std": opinion_std,
            "diversity_threshold": self.config.min_team_disagreement,
            "team_members": [m.get("agent_id", "unknown") for m in team_members]
        }
        
        passed = size_passed and diversity_passed
        
        if not size_passed:
            recommendation = f"Team too large ({len(team_members)} > {self.config.max_team_size})"
        elif not diversity_passed:
            recommendation = f"Insufficient team diversity (std {opinion_std:.3f} < {self.config.min_team_disagreement})"
        else:
            recommendation = "Team composition acceptable"
        
        return GateResult(
            gate_name="team_diversity",
            passed=passed,
            score=score,
            threshold=self.config.min_team_disagreement,
            details=details,
            recommendation=recommendation
        )
    
    def _evaluate_performance_gate(self, agent_data: Dict[str, Any]) -> GateResult:
        """Evaluate agent's debate performance and lift contribution."""
        
        debate_history = agent_data.get("debate_history", [])
        if not debate_history:
            return GateResult(
                gate_name="performance",
                passed=True,  # No debate history is OK for new participants
                score=0.5,
                threshold=self.config.min_debate_lift_threshold,
                details={},
                recommendation="No debate history - new participant welcome"
            )
        
        # Analyze recent debate performance
        recent_debates = debate_history[:10]  # Last 10 debates
        lift_values = [debate.get("debate_lift", 0.0) for debate in recent_debates]
        
        # Calculate average lift
        avg_lift = statistics.mean(lift_values) if lift_values else 0.0
        
        # Count consecutive failures
        consecutive_failures = 0
        for debate in reversed(recent_debates):
            if debate.get("debate_lift", 0.0) < self.config.min_debate_lift_threshold:
                consecutive_failures += 1
            else:
                break
        
        # Check thresholds
        lift_passed = avg_lift >= self.config.min_debate_lift_threshold
        failure_passed = consecutive_failures <= self.config.max_consecutive_failures
        
        # Score based on lift performance
        score = max(0.0, avg_lift / self.config.min_debate_lift_threshold) if self.config.min_debate_lift_threshold > 0 else 1.0
        
        details = {
            "avg_debate_lift": avg_lift,
            "lift_threshold": self.config.min_debate_lift_threshold,
            "consecutive_failures": consecutive_failures,
            "failure_threshold": self.config.max_consecutive_failures,
            "debates_analyzed": len(recent_debates)
        }
        
        passed = lift_passed and failure_passed
        
        if not lift_passed:
            recommendation = f"Average debate lift too low ({avg_lift:.3f} < {self.config.min_debate_lift_threshold})"
        elif not failure_passed:
            recommendation = f"Too many consecutive failures ({consecutive_failures} > {self.config.max_consecutive_failures})"
        else:
            recommendation = "Debate performance acceptable"
        
        return GateResult(
            gate_name="performance",
            passed=passed,
            score=score,
            threshold=self.config.min_debate_lift_threshold,
            details=details,
            recommendation=recommendation
        )


# Global instance for easy access
_quantitative_gates = QuantitativeGates()


def get_quantitative_gates() -> QuantitativeGates:
    """Get the global quantitative gates instance."""
    return _quantitative_gates


def configure_quantitative_gates(config: GateConfig) -> None:
    """Configure the global quantitative gates instance."""
    global _quantitative_gates
    _quantitative_gates = QuantitativeGates(config)

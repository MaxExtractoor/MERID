"""
LearningEngine - Layer 4: Pattern Recognition and Insight Generation

Responsibilities:
- Identify patterns in agent decisions and outcomes
- Generate actionable learning insights
- Detect failure modes and success patterns
- Provide recommendations for improvement
- Track learning evolution over time
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from collections import defaultdict, Counter

from agents.reflection.core import Reflection, DecisionOutcome
from utils.logger import get_logger

logger = get_logger("reflection.learning")


@dataclass
class LearningInsight:
    """A learning insight derived from reflection patterns."""
    insight_id: str
    agent_id: str
    insight_type: str  # pattern/failure_mode/success_factor/recommendation
    title: str
    description: str
    evidence_count: int
    confidence: float
    actionable: bool
    recommendations: List[str]
    pattern_tags: Set[str]
    timestamp: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "insight_id": self.insight_id,
            "agent_id": self.agent_id,
            "insight_type": self.insight_type,
            "title": self.title,
            "description": self.description,
            "evidence_count": self.evidence_count,
            "confidence": round(self.confidence, 4),
            "actionable": self.actionable,
            "recommendations": self.recommendations,
            "pattern_tags": list(self.pattern_tags),
            "timestamp": self.timestamp
        }


class LearningEngine:
    """
    Generates learning insights from reflection patterns.
    
    Features:
    - Pattern detection (success/failure modes)
    - Confidence calibration analysis
    - Decision bias detection
    - Actionable recommendations
    - Learning evolution tracking
    """
    
    def __init__(self, min_evidence: int = 5):
        self.min_evidence = min_evidence
        self._insights_cache: Dict[str, List[LearningInsight]] = {}
        self._pattern_counts: Dict[str, Counter] = defaultdict(Counter)
        self._insight_count = 0
        self._start_time = time.time()
        
        logger.info("LearningEngine initialized (min_evidence=%d)", min_evidence)
    
    def generate_insights(
        self,
        agent_id: str,
        reflections: List[Reflection],
        force_refresh: bool = False
    ) -> List[LearningInsight]:
        """
        Generate learning insights for an agent.
        
        Args:
            agent_id: Agent identifier
            reflections: Agent's reflections
            force_refresh: Force regeneration (ignore cache)
        
        Returns:
            List of learning insights
        """
        start = time.time()
        
        # Check cache
        if not force_refresh and agent_id in self._insights_cache:
            logger.debug("Returning cached insights for %s", agent_id)
            return self._insights_cache[agent_id]
        
        insights = []
        
        if len(reflections) < self.min_evidence:
            logger.debug("Insufficient reflections for %s (%d < %d)", 
                        agent_id, len(reflections), self.min_evidence)
            return insights
        
        # Generate different types of insights
        insights.extend(self._detect_failure_patterns(agent_id, reflections))
        insights.extend(self._detect_success_patterns(agent_id, reflections))
        insights.extend(self._detect_confidence_issues(agent_id, reflections))
        insights.extend(self._detect_decision_biases(agent_id, reflections))
        insights.extend(self._generate_recommendations(agent_id, reflections))
        
        # Cache insights
        self._insights_cache[agent_id] = insights
        
        duration_ms = (time.time() - start) * 1000
        logger.info(
            "Generated %d insights for %s from %d reflections (%.2fms)",
            len(insights), agent_id, len(reflections), duration_ms
        )
        
        return insights
    
    def _detect_failure_patterns(
        self,
        agent_id: str,
        reflections: List[Reflection]
    ) -> List[LearningInsight]:
        """Detect patterns in failed predictions."""
        insights = []
        
        failed = [
            r for r in reflections
            if r.outcome == DecisionOutcome.INVALIDATED
        ]
        
        if len(failed) < self.min_evidence:
            return insights
        
        # Pattern 1: High confidence failures
        high_conf_failures = [r for r in failed if r.confidence > 0.7]
        if len(high_conf_failures) >= self.min_evidence:
            insights.append(LearningInsight(
                insight_id=f"{agent_id}_failure_overconfidence_{int(time.time())}",
                agent_id=agent_id,
                insight_type="failure_mode",
                title="Overconfidence in Failed Predictions",
                description=f"Agent shows high confidence (>0.7) in {len(high_conf_failures)} failed predictions. "
                           f"This suggests overconfidence bias or insufficient uncertainty modeling.",
                evidence_count=len(high_conf_failures),
                confidence=min(len(high_conf_failures) / len(failed), 1.0),
                actionable=True,
                recommendations=[
                    "Reduce confidence scores by 10-20% for similar contexts",
                    "Add more uncertainty factors to reasoning",
                    "Implement confidence calibration layer"
                ],
                pattern_tags={"overconfidence", "high_confidence_failure"},
                timestamp=time.time()
            ))
        
        # Pattern 2: Consistent decision type failures
        decision_failures = Counter(r.decision for r in failed)
        for decision, count in decision_failures.items():
            if count >= self.min_evidence and count / len(failed) > 0.6:
                insights.append(LearningInsight(
                    insight_id=f"{agent_id}_failure_{decision}_{int(time.time())}",
                    agent_id=agent_id,
                    insight_type="failure_mode",
                    title=f"High Failure Rate on '{decision.upper()}' Decisions",
                    description=f"Agent fails {count}/{len(failed)} times ({count/len(failed)*100:.1f}%) "
                               f"when deciding to '{decision}'. This suggests systematic bias or poor "
                               f"reasoning for this decision type.",
                    evidence_count=count,
                    confidence=count / len(failed),
                    actionable=True,
                    recommendations=[
                        f"Review reasoning patterns for '{decision}' decisions",
                        f"Add additional validation checks before '{decision}' decisions",
                        f"Consider abstaining more often instead of '{decision}'"
                    ],
                    pattern_tags={f"{decision}_failure", "decision_bias"},
                    timestamp=time.time()
                ))
        
        # Pattern 3: High reality gap failures
        high_gap_failures = [r for r in failed if r.reality_gap and r.reality_gap > 0.7]
        if len(high_gap_failures) >= self.min_evidence:
            insights.append(LearningInsight(
                insight_id=f"{agent_id}_failure_high_gap_{int(time.time())}",
                agent_id=agent_id,
                insight_type="failure_mode",
                title="Severe Reality Gap in Predictions",
                description=f"Agent has {len(high_gap_failures)} predictions with reality gap >0.7, "
                           f"indicating predictions are far from actual outcomes. This suggests "
                           f"fundamental misunderstanding of market dynamics or data quality issues.",
                evidence_count=len(high_gap_failures),
                confidence=min(len(high_gap_failures) / len(failed), 1.0),
                actionable=True,
                recommendations=[
                    "Review data sources for accuracy and timeliness",
                    "Add market regime detection to adjust predictions",
                    "Implement reality feedback loop for continuous learning"
                ],
                pattern_tags={"high_reality_gap", "prediction_error"},
                timestamp=time.time()
            ))
        
        return insights
    
    def _detect_success_patterns(
        self,
        agent_id: str,
        reflections: List[Reflection]
    ) -> List[LearningInsight]:
        """Detect patterns in successful predictions."""
        insights = []
        
        successful = [
            r for r in reflections
            if r.outcome == DecisionOutcome.VALIDATED
        ]
        
        if len(successful) < self.min_evidence:
            return insights
        
        # Pattern 1: Low reality gap successes
        low_gap_successes = [r for r in successful if r.reality_gap and r.reality_gap < 0.2]
        if len(low_gap_successes) >= self.min_evidence:
            insights.append(LearningInsight(
                insight_id=f"{agent_id}_success_accurate_{int(time.time())}",
                agent_id=agent_id,
                insight_type="success_factor",
                title="High Accuracy Predictions",
                description=f"Agent has {len(low_gap_successes)} predictions with reality gap <0.2, "
                           f"showing excellent prediction accuracy. These represent the agent's "
                           f"strongest performance areas.",
                evidence_count=len(low_gap_successes),
                confidence=min(len(low_gap_successes) / len(successful), 1.0),
                actionable=True,
                recommendations=[
                    "Identify common factors in these accurate predictions",
                    "Apply similar reasoning patterns to other decisions",
                    "Increase confidence in similar contexts"
                ],
                pattern_tags={"high_accuracy", "low_reality_gap"},
                timestamp=time.time()
            ))
        
        # Pattern 2: Well-calibrated confidence
        well_calibrated = [
            r for r in successful
            if r.reality_gap and abs(r.confidence - (1.0 - r.reality_gap)) < 0.2
        ]
        if len(well_calibrated) >= self.min_evidence:
            insights.append(LearningInsight(
                insight_id=f"{agent_id}_success_calibrated_{int(time.time())}",
                agent_id=agent_id,
                insight_type="success_factor",
                title="Well-Calibrated Confidence",
                description=f"Agent shows good confidence calibration in {len(well_calibrated)} predictions, "
                           f"where confidence matches actual accuracy. This indicates strong "
                           f"uncertainty modeling.",
                evidence_count=len(well_calibrated),
                confidence=min(len(well_calibrated) / len(successful), 1.0),
                actionable=True,
                recommendations=[
                    "Maintain current confidence calibration approach",
                    "Apply calibration method to other decision types",
                    "Use as baseline for confidence scoring"
                ],
                pattern_tags={"calibrated_confidence", "uncertainty_modeling"},
                timestamp=time.time()
            ))
        
        return insights
    
    def _detect_confidence_issues(
        self,
        agent_id: str,
        reflections: List[Reflection]
    ) -> List[LearningInsight]:
        """Detect confidence-related issues."""
        insights = []
        
        resolved = [r for r in reflections if r.is_resolved()]
        if len(resolved) < self.min_evidence:
            return insights
        
        # Calculate overall confidence vs accuracy
        avg_confidence = sum(r.confidence for r in resolved) / len(resolved)
        accuracy = sum(
            1 for r in resolved if r.outcome == DecisionOutcome.VALIDATED
        ) / len(resolved)
        
        confidence_gap = avg_confidence - accuracy
        
        # Overconfidence detection
        if confidence_gap > 0.2:
            insights.append(LearningInsight(
                insight_id=f"{agent_id}_overconfidence_{int(time.time())}",
                agent_id=agent_id,
                insight_type="pattern",
                title="Systematic Overconfidence",
                description=f"Agent's average confidence ({avg_confidence:.2f}) significantly exceeds "
                           f"actual accuracy ({accuracy:.2f}). Gap of {confidence_gap:.2f} indicates "
                           f"systematic overconfidence across all decisions.",
                evidence_count=len(resolved),
                confidence=min(abs(confidence_gap), 1.0),
                actionable=True,
                recommendations=[
                    f"Reduce all confidence scores by {confidence_gap:.2f}",
                    "Add confidence penalty for uncertain contexts",
                    "Implement Bayesian confidence calibration"
                ],
                pattern_tags={"overconfidence", "calibration_issue"},
                timestamp=time.time()
            ))
        
        # Underconfidence detection
        elif confidence_gap < -0.2:
            insights.append(LearningInsight(
                insight_id=f"{agent_id}_underconfidence_{int(time.time())}",
                agent_id=agent_id,
                insight_type="pattern",
                title="Systematic Underconfidence",
                description=f"Agent's average confidence ({avg_confidence:.2f}) is significantly lower than "
                           f"actual accuracy ({accuracy:.2f}). Gap of {abs(confidence_gap):.2f} indicates "
                           f"systematic underconfidence, potentially missing opportunities.",
                evidence_count=len(resolved),
                confidence=min(abs(confidence_gap), 1.0),
                actionable=True,
                recommendations=[
                    f"Increase confidence scores by {abs(confidence_gap):.2f}",
                    "Trust successful reasoning patterns more",
                    "Reduce uncertainty penalties in proven contexts"
                ],
                pattern_tags={"underconfidence", "calibration_issue"},
                timestamp=time.time()
            ))
        
        return insights
    
    def _detect_decision_biases(
        self,
        agent_id: str,
        reflections: List[Reflection]
    ) -> List[LearningInsight]:
        """Detect biases in decision-making."""
        insights = []
        
        if len(reflections) < self.min_evidence:
            return insights
        
        # Decision distribution
        decision_counts = Counter(r.decision for r in reflections)
        total = len(reflections)
        
        # Detect abstain bias
        abstain_rate = decision_counts.get("abstain", 0) / total
        if abstain_rate > 0.5:
            insights.append(LearningInsight(
                insight_id=f"{agent_id}_abstain_bias_{int(time.time())}",
                agent_id=agent_id,
                insight_type="pattern",
                title="High Abstention Rate",
                description=f"Agent abstains {abstain_rate*100:.1f}% of the time. While caution is good, "
                           f"excessive abstention reduces agent utility and may indicate lack of "
                           f"confidence or insufficient data.",
                evidence_count=decision_counts.get("abstain", 0),
                confidence=abstain_rate,
                actionable=True,
                recommendations=[
                    "Review abstention criteria - may be too conservative",
                    "Improve data quality to enable more decisive voting",
                    "Consider 'lean accept/reject' for borderline cases"
                ],
                pattern_tags={"abstain_bias", "decision_bias"},
                timestamp=time.time()
            ))
        
        # Detect accept/reject imbalance
        accept_rate = decision_counts.get("accept", 0) / total
        reject_rate = decision_counts.get("reject", 0) / total
        
        if accept_rate > 0.7:
            insights.append(LearningInsight(
                insight_id=f"{agent_id}_accept_bias_{int(time.time())}",
                agent_id=agent_id,
                insight_type="pattern",
                title="Strong Accept Bias",
                description=f"Agent accepts {accept_rate*100:.1f}% of proposals. This may indicate "
                           f"optimism bias or insufficient skepticism in evaluation.",
                evidence_count=decision_counts.get("accept", 0),
                confidence=accept_rate,
                actionable=True,
                recommendations=[
                    "Add more critical evaluation criteria",
                    "Increase weight of risk factors",
                    "Review false positive rate in accepted proposals"
                ],
                pattern_tags={"accept_bias", "optimism_bias"},
                timestamp=time.time()
            ))
        
        elif reject_rate > 0.7:
            insights.append(LearningInsight(
                insight_id=f"{agent_id}_reject_bias_{int(time.time())}",
                agent_id=agent_id,
                insight_type="pattern",
                title="Strong Reject Bias",
                description=f"Agent rejects {reject_rate*100:.1f}% of proposals. This may indicate "
                           f"pessimism bias or overly conservative evaluation.",
                evidence_count=decision_counts.get("reject", 0),
                confidence=reject_rate,
                actionable=True,
                recommendations=[
                    "Review rejection criteria - may be too strict",
                    "Balance risk assessment with opportunity cost",
                    "Check false negative rate in rejected proposals"
                ],
                pattern_tags={"reject_bias", "pessimism_bias"},
                timestamp=time.time()
            ))
        
        return insights
    
    def _generate_recommendations(
        self,
        agent_id: str,
        reflections: List[Reflection]
    ) -> List[LearningInsight]:
        """Generate actionable recommendations."""
        insights = []
        
        resolved = [r for r in reflections if r.is_resolved()]
        if len(resolved) < self.min_evidence:
            return insights
        
        # Calculate key metrics
        accuracy = sum(
            1 for r in resolved if r.outcome == DecisionOutcome.VALIDATED
        ) / len(resolved)
        
        avg_reality_gap = sum(
            r.reality_gap for r in resolved if r.reality_gap is not None
        ) / len([r for r in resolved if r.reality_gap is not None]) if any(r.reality_gap is not None for r in resolved) else 0.5
        
        # Low accuracy recommendation
        if accuracy < 0.4:
            insights.append(LearningInsight(
                insight_id=f"{agent_id}_rec_low_accuracy_{int(time.time())}",
                agent_id=agent_id,
                insight_type="recommendation",
                title="Critical: Low Prediction Accuracy",
                description=f"Agent accuracy is only {accuracy*100:.1f}%, significantly below acceptable "
                           f"threshold. Immediate intervention required.",
                evidence_count=len(resolved),
                confidence=1.0 - accuracy,
                actionable=True,
                recommendations=[
                    "URGENT: Review and update agent reasoning model",
                    "Validate data sources for accuracy and timeliness",
                    "Consider retraining or replacing agent",
                    "Reduce agent weight in consensus until improved"
                ],
                pattern_tags={"critical", "low_accuracy", "urgent"},
                timestamp=time.time()
            ))
        
        # High reality gap recommendation
        if avg_reality_gap > 0.6:
            insights.append(LearningInsight(
                insight_id=f"{agent_id}_rec_high_gap_{int(time.time())}",
                agent_id=agent_id,
                insight_type="recommendation",
                title="High Reality Gap - Prediction Quality Issue",
                description=f"Average reality gap of {avg_reality_gap:.2f} indicates predictions are "
                           f"far from actual outcomes. This suggests fundamental issues with "
                           f"prediction methodology.",
                evidence_count=len(resolved),
                confidence=avg_reality_gap,
                actionable=True,
                recommendations=[
                    "Implement reality feedback loop for continuous learning",
                    "Add market regime detection to adjust predictions",
                    "Review and update prediction algorithms",
                    "Increase data quality checks"
                ],
                pattern_tags={"high_reality_gap", "prediction_quality"},
                timestamp=time.time()
            ))
        
        return insights
    
    def get_learning_summary(
        self,
        agent_id: str,
        insights: List[LearningInsight]
    ) -> str:
        """
        Generate human-readable learning summary.
        
        Args:
            agent_id: Agent identifier
            insights: List of insights
        
        Returns:
            Formatted summary string
        """
        if not insights:
            return f"No learning insights available for {agent_id}"
        
        lines = [
            f"Learning Summary for {agent_id}",
            f"=" * 50,
            f"Total Insights: {len(insights)}",
            ""
        ]
        
        # Group by type
        by_type = defaultdict(list)
        for insight in insights:
            by_type[insight.insight_type].append(insight)
        
        for insight_type, type_insights in by_type.items():
            lines.append(f"{insight_type.upper()}: {len(type_insights)} insights")
            for insight in type_insights[:3]:  # Top 3 per type
                lines.append(f"  - {insight.title}")
                lines.append(f"    {insight.description[:100]}...")
            lines.append("")
        
        # Top recommendations
        recommendations = [i for i in insights if i.insight_type == "recommendation"]
        if recommendations:
            lines.append("TOP RECOMMENDATIONS:")
            for rec in recommendations[:3]:
                lines.append(f"  {rec.title}")
                for r in rec.recommendations[:2]:
                    lines.append(f"    • {r}")
            lines.append("")
        
        return "\n".join(lines)
    
    def get_stats(self) -> Dict[str, Any]:
        """Get learning engine statistics."""
        uptime = time.time() - self._start_time
        
        total_insights = sum(len(insights) for insights in self._insights_cache.values())
        
        return {
            "cached_agents": len(self._insights_cache),
            "total_insights": total_insights,
            "min_evidence": self.min_evidence,
            "performance": {
                "uptime_seconds": round(uptime, 2),
                "insights_generated": self._insight_count
            }
        }

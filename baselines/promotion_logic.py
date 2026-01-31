"""
Baseline v1 Promotion Logic

Hard gate enforcement for Multi-Category Baseline v1: 0.004316 Brier score
"""

from typing import Dict, List, Optional
from dataclasses import dataclass
from enum import Enum

class PromotionDecision(Enum):
    PROMOTE = "PROMOTE"
    REJECT = "REJECT"
    INVESTIGATE = "INVESTIGATE"

@dataclass
class BaselineCheck:
    baseline_brier: float = 0.004316
    improvement_threshold: float = 0.01  # 1% improvement required
    min_runs: int = 3
    max_latency_regression: int = 10  # ms
    min_success_rate: float = 99.5  # %

@dataclass
class ExperimentResult:
    brier_scores: List[float]
    latency_ms: List[int]
    success_rates: List[float]
    run_count: int

class BaselinePromotionLogic:
    def __init__(self, baseline: BaselineCheck):
        self.baseline = baseline
    
    def evaluate_promotion(self, results: ExperimentResult) -> PromotionDecision:
        """
        Evaluate if experiment results meet promotion criteria against Baseline v1
        """
        # Check minimum runs
        if results.run_count < self.baseline.min_runs:
            return PromotionDecision.REJECT
        
        # Calculate metrics
        avg_brier = sum(results.brier_scores) / len(results.brier_scores)
        avg_latency = sum(results.latency_ms) / len(results.latency_ms)
        avg_success_rate = sum(results.success_rates) / len(results.success_rates)
        
        # Brier score improvement check
        brier_improvement = (self.baseline.baseline_brier - avg_brier) / self.baseline.baseline_brier
        if brier_improvement < self.baseline.improvement_threshold:
            return PromotionDecision.REJECT
        
        # Latency regression check
        baseline_latency = 850  # From baseline v1
        if avg_latency > baseline_latency + self.baseline.max_latency_regression:
            return PromotionDecision.INVESTIGATE
        
        # Success rate check
        if avg_success_rate < self.baseline.min_success_rate:
            return PromotionDecision.REJECT
        
        # Variance check for consistency
        brier_variance = self._calculate_variance(results.brier_scores)
        if brier_variance > 0.0001:  # Variance tolerance
            return PromotionDecision.INVESTIGATE
        
        return PromotionDecision.PROMOTE
    
    def _calculate_variance(self, values: List[float]) -> float:
        """Calculate variance of values"""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        return sum((x - mean) ** 2 for x in values) / len(values)
    
    def generate_promotion_report(self, results: ExperimentResult) -> Dict:
        """Generate detailed promotion evaluation report"""
        avg_brier = sum(results.brier_scores) / len(results.brier_scores)
        brier_improvement = (self.baseline.baseline_brier - avg_brier) / self.baseline.baseline_brier
        
        return {
            "baseline_v1": self.baseline.baseline_brier,
            "experiment_brier": avg_brier,
            "improvement_percent": brier_improvement * 100,
            "meets_threshold": brier_improvement >= self.baseline.improvement_threshold,
            "run_count": results.run_count,
            "meets_min_runs": results.run_count >= self.baseline.min_runs,
            "variance": self._calculate_variance(results.brier_scores),
            "within_variance_tolerance": self._calculate_variance(results.brier_scores) <= 0.0001
        }

# Usage Example
def evaluate_against_baseline_v1(experiment_results: ExperimentResult) -> PromotionDecision:
    """
    Main function to evaluate experiments against Baseline v1
    """
    baseline_check = BaselineCheck()
    promotion_logic = BaselinePromotionLogic(baseline_check)
    
    decision = promotion_logic.evaluate_promotion(experiment_results)
    report = promotion_logic.generate_promotion_report(experiment_results)
    
    print(f"Baseline v1 Evaluation: {decision.value}")
    print(f"Report: {report}")
    
    return decision

# Hard Gate Enforcement
def hard_gate_check(brier_score: float, run_count: int = 1) -> bool:
    """
    Quick hard gate check against Baseline v1
    Returns True if passes basic criteria
    """
    baseline = BaselineCheck()
    
    # Basic Brier check
    if brier_score >= baseline.baseline_brier:
        return False
    
    # Improvement check
    improvement = (baseline.baseline_brier - brier_score) / baseline.baseline_brier
    if improvement < baseline.improvement_threshold:
        return False
    
    # Minimum runs check
    if run_count < baseline.min_runs:
        return False
    
    return True

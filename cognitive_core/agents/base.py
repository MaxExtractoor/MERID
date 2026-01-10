"""
Base agent interface and abstract class.
All agents must inherit from Agent and implement analyze().
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any
from datetime import datetime

from ..utils.types import BeliefVector, AgentType, Datum
from ..memory.snapshot import DataSnapshot


class Agent(ABC):
    """
    Abstract base class for all MERID agents.
    
    Principles:
    - Each agent is an independent observer
    - Agents receive data snapshots (read-only)
    - Agents output belief vectors (probability, confidence, risk, dissent)
    - Agents NEVER execute actions
    - Agents NEVER communicate directly (only via Spine Bus)
    """
    
    def __init__(self, agent_type: AgentType):
        self.agent_type = agent_type
        self.track_record: List[Dict[str, Any]] = []
        self.weight = 1.0  # Adjusted based on historical performance
    
    @abstractmethod
    def analyze(
        self,
        hypothesis: str,
        data_snapshot: DataSnapshot,
    ) -> BeliefVector:
        """
        Analyze hypothesis given current data snapshot.
        
        Args:
            hypothesis: The hypothesis to evaluate
            data_snapshot: Current view of all available data
        
        Returns:
            BeliefVector with probability, confidence, risk, dissent
        """
        pass
    
    def record_outcome(
        self,
        prediction: BeliefVector,
        actual_outcome: bool,
        timestamp: datetime,
    ) -> None:
        """
        Record prediction outcome for learning.
        
        Args:
            prediction: Original belief vector
            actual_outcome: What actually happened
            timestamp: When outcome was determined
        """
        self.track_record.append({
            "prediction": prediction,
            "actual_outcome": actual_outcome,
            "timestamp": timestamp,
        })
        
        # Update agent weight based on accuracy
        self._update_weight()
    
    def _update_weight(self) -> None:
        """
        Update agent weight based on track record.
        Agents with good calibration get higher weight.
        """
        if len(self.track_record) < 10:
            return
        
        recent = self.track_record[-50:]
        
        # Calculate Brier score (lower is better)
        brier_score = sum(
            (record["prediction"].probability - float(record["actual_outcome"]))**2
            for record in recent
        ) / len(recent)
        
        # Convert to weight (0.5 = random, 0 = perfect)
        # Weight in [0.5, 2.0]
        self.weight = max(0.5, min(2.0, 1 / (1 + brier_score)))
    
    def get_calibration_metrics(self) -> Dict[str, float]:
        """
        Get agent calibration metrics.
        
        Returns:
            Dictionary with Brier score, log score, calibration error
        """
        if not self.track_record:
            return {
                "brier_score": 0.5,
                "log_score": 0.0,
                "calibration_error": 0.0,
                "sample_size": 0,
            }
        
        recent = self.track_record[-100:]
        
        # Brier score
        brier = sum(
            (r["prediction"].probability - float(r["actual_outcome"]))**2
            for r in recent
        ) / len(recent)
        
        # Log score
        log_score = sum(
            (r["actual_outcome"] * r["prediction"].probability +
             (not r["actual_outcome"]) * (1 - r["prediction"].probability))
            for r in recent
        ) / len(recent)
        
        # Calibration error (simplified)
        predicted_probs = [r["prediction"].probability for r in recent]
        actual_outcomes = [float(r["actual_outcome"]) for r in recent]
        calibration_error = abs(sum(predicted_probs) / len(predicted_probs) - 
                                sum(actual_outcomes) / len(actual_outcomes))
        
        return {
            "brier_score": brier,
            "log_score": log_score,
            "calibration_error": calibration_error,
            "sample_size": len(recent),
        }

"""
Logic Agent - Formal reasoning and Bayesian updating.
"""

from datetime import datetime, timedelta
from typing import Dict, Any

from .base import Agent
from ..utils.types import BeliefVector, AgentType, DataType, DataSource
from ..utils.bayesian import BayesianCore
from ..memory.snapshot import DataSnapshot


class LogicAgent(Agent):
    """
    Logic Agent: Formal reasoning, constraint satisfaction, Bayesian updating.
    
    Responsibilities:
    - Bayesian belief updating from evidence
    - Internal consistency checking
    - Sensitivity analysis
    - Constraint satisfaction
    """
    
    def __init__(self):
        super().__init__(AgentType.LOGIC)
        self.bayesian = BayesianCore()
    
    def analyze(
        self,
        hypothesis: str,
        data_snapshot: DataSnapshot,
    ) -> BeliefVector:
        """
        Analyze hypothesis using formal logic and Bayesian reasoning.
        
        Example hypothesis: "BTC breaks $105K within 48h"
        """
        
        # Start with base rate (prior)
        prior = self._estimate_prior(hypothesis, data_snapshot)
        
        # Collect evidence and compute likelihoods
        evidence = self._collect_evidence(hypothesis, data_snapshot)
        
        # Sequential Bayesian update
        posterior = self.bayesian.sequential_update(prior, evidence)
        
        # Estimate confidence based on data quality and quantity
        confidence = self._estimate_confidence(data_snapshot, evidence)
        
        # Estimate risk
        risk = self._estimate_risk(hypothesis, posterior, data_snapshot)
        
        # Generate dissent/assumptions
        dissent = self._generate_dissent(hypothesis, evidence, data_snapshot)
        
        # Detailed reasoning
        reasoning = self._generate_reasoning(
            hypothesis, prior, evidence, posterior, confidence, risk
        )
        
        return BeliefVector(
            agent_type=self.agent_type,
            hypothesis=hypothesis,
            probability=posterior,
            confidence=confidence,
            risk=risk,
            dissent_notes=dissent,
            reasoning=reasoning,
        )
    
    def _estimate_prior(self, hypothesis: str, snapshot: DataSnapshot) -> float:
        """
        Estimate prior probability (base rate).
        
        For price movements: use historical frequency of similar moves.
        """
        # Simple heuristic: 30% base rate for significant price movements
        # In production: analyze historical data
        return 0.30
    
    def _collect_evidence(
        self,
        hypothesis: str,
        snapshot: DataSnapshot,
    ) -> list:
        """
        Collect evidence and compute likelihoods.
        
        Returns list of (P(E|H), P(E|¬H)) tuples.
        """
        evidence = []
        
        # Evidence 1: Price trend
        price_data = snapshot.get_by_type(DataType.PRICE, max_age=timedelta(hours=24))
        if len(price_data) >= 2:
            recent = price_data[-1].value
            older = price_data[0].value
            trend = (recent - older) / older
            
            if trend > 0:
                # Positive trend increases likelihood
                evidence.append((0.70, 0.30))  # P(uptrend|bullish), P(uptrend|¬bullish)
        
        # Evidence 2: Volume
        volume_data = snapshot.get_by_type(DataType.VOLUME, max_age=timedelta(hours=6))
        if volume_data:
            recent_volume = sum(d.value for d in volume_data[-3:]) / 3
            older_volume = sum(d.value for d in volume_data[:3]) / 3 if len(volume_data) >= 6 else recent_volume
            
            if recent_volume > older_volume * 1.5:
                # High volume confirms move
                evidence.append((0.65, 0.35))
        
        # Evidence 3: Sentiment
        sentiment = snapshot.get_sentiment(max_age=timedelta(hours=6))
        if sentiment is not None:
            if sentiment > 0.3:
                evidence.append((0.60, 0.40))
            elif sentiment < -0.3:
                # Contrarian indicator
                evidence.append((0.55, 0.45))
        
        return evidence
    
    def _estimate_confidence(
        self,
        snapshot: DataSnapshot,
        evidence: list,
    ) -> float:
        """
        Estimate confidence in probability estimate.
        
        Based on:
        - Data quality (freshness, confidence)
        - Data quantity (more evidence = higher confidence)
        - Consistency (agreement between sources)
        """
        if not evidence:
            return 0.20  # Low confidence with no evidence
        
        # Data freshness
        data_ages = [
            (snapshot.timestamp - d.timestamp).total_seconds()
            for d in snapshot._data
        ]
        avg_age_hours = (sum(data_ages) / len(data_ages)) / 3600 if data_ages else 24
        
        freshness_score = max(0, 1.0 - avg_age_hours / 24)
        
        # Evidence quantity
        quantity_score = min(1.0, len(evidence) / 5)
        
        # Combine
        confidence = 0.3 * freshness_score + 0.7 * quantity_score
        
        return max(0.3, min(0.9, confidence))
    
    def _estimate_risk(
        self,
        hypothesis: str,
        probability: float,
        snapshot: DataSnapshot,
    ) -> float:
        """
        Estimate tail risk if hypothesis is wrong.
        
        Risk increases with:
        - Extreme probabilities (overconfidence)
        - High leverage environments
        - Volatility
        """
        # Base risk
        risk = 0.4
        
        # Overconfidence penalty
        if probability > 0.85 or probability < 0.15:
            risk += 0.2
        
        # Check for high volatility indicators
        price_data = snapshot.get_by_type(DataType.PRICE, max_age=timedelta(hours=24))
        if len(price_data) >= 10:
            prices = [float(d.value) for d in price_data]
            volatility = (max(prices) - min(prices)) / min(prices)
            if volatility > 0.05:  # >5% swing
                risk += 0.15
        
        return max(0.1, min(0.95, risk))
    
    def _generate_dissent(
        self,
        hypothesis: str,
        evidence: list,
        snapshot: DataSnapshot,
    ) -> str:
        """
        Generate dissent notes and assumptions.
        """
        notes = []
        
        # Check for missing data
        if snapshot.data_count < 10:
            notes.append("WARNING: Limited data points - estimate unreliable")
        
        # Check for stale data
        data_ages = [
            (snapshot.timestamp - d.timestamp).total_seconds() / 3600
            for d in snapshot._data
        ]
        if data_ages and max(data_ages) > 24:
            notes.append("CAUTION: Some data >24h old - may not reflect current regime")
        
        # Assumptions
        notes.append("ASSUMES: No black swan regulatory/macro events")
        notes.append("ASSUMES: Historical patterns remain valid")
        
        if not evidence:
            notes.append("CRITICAL: No evidence collected - estimate is pure prior")
        
        return " | ".join(notes)
    
    def _generate_reasoning(
        self,
        hypothesis: str,
        prior: float,
        evidence: list,
        posterior: float,
        confidence: float,
        risk: float,
    ) -> str:
        """
        Generate detailed reasoning for audit trail.
        """
        reasoning_parts = [
            f"HYPOTHESIS: {hypothesis}",
            f"PRIOR: {prior:.2%} (base rate)",
            f"EVIDENCE: {len(evidence)} pieces collected",
        ]
        
        for i, (p_e_h, p_e_not_h) in enumerate(evidence, 1):
            likelihood_ratio = p_e_h / p_e_not_h if p_e_not_h > 0 else float('inf')
            reasoning_parts.append(
                f"  Evidence {i}: P(E|H)={p_e_h:.2%}, P(E|¬H)={p_e_not_h:.2%}, "
                f"LR={likelihood_ratio:.2f}"
            )
        
        reasoning_parts.extend([
            f"POSTERIOR: {posterior:.2%} (after Bayesian update)",
            f"CONFIDENCE: {confidence:.2%} (data quality × quantity)",
            f"RISK: {risk:.2%} (tail risk if wrong)",
        ])
        
        return "\n".join(reasoning_parts)

"""
Intuition Agent - Pattern recognition and regime detection.
"""

from datetime import timedelta
from typing import List, Tuple

from .base import Agent
from ..utils.types import BeliefVector, AgentType, DataType
from ..memory.snapshot import DataSnapshot


class IntuitionAgent(Agent):
    """
    Intuition Agent: Pattern recognition, regime detection, nonlinear correlations.
    
    Responsibilities:
    - Detect patterns before formal confirmation
    - Identify regime shifts
    - Spot crowd vs price vs time divergences
    - Signal emergence from noise
    """
    
    def __init__(self):
        super().__init__(AgentType.INTUITION)
        self.patterns_db = []  # In production: trained pattern database
    
    def analyze(
        self,
        hypothesis: str,
        data_snapshot: DataSnapshot,
    ) -> BeliefVector:
        """
        Analyze hypothesis using pattern recognition and intuition.
        """
        
        # Detect regime (accumulation, distribution, trend, range)
        regime = self._detect_regime(data_snapshot)
        
        # Detect divergences
        divergences = self._detect_divergences(data_snapshot)
        
        # Pattern matching
        pattern_score = self._match_patterns(data_snapshot)
        
        # Compute gut feel probability
        probability = self._compute_gut_feel(
            regime, divergences, pattern_score, hypothesis
        )
        
        # Intuition is less confident than logic
        confidence = 0.40 + 0.30 * pattern_score
        
        # Higher risk when divergences detected
        risk = 0.50 + 0.20 * len(divergences)
        
        # Generate dissent
        dissent = self._generate_dissent(regime, divergences)
        
        # Reasoning
        reasoning = self._generate_reasoning(
            regime, divergences, pattern_score, probability
        )
        
        return BeliefVector(
            agent_type=self.agent_type,
            hypothesis=hypothesis,
            probability=probability,
            confidence=min(0.7, confidence),
            risk=min(0.85, risk),
            dissent_notes=dissent,
            reasoning=reasoning,
        )
    
    def _detect_regime(self, snapshot: DataSnapshot) -> str:
        """
        Detect current market regime.
        
        Returns: "accumulation", "distribution", "uptrend", "downtrend", "range"
        """
        price_data = snapshot.get_by_type(DataType.PRICE, max_age=timedelta(hours=48))
        volume_data = snapshot.get_by_type(DataType.VOLUME, max_age=timedelta(hours=48))
        
        if not price_data or len(price_data) < 10:
            return "unknown"
        
        prices = [float(d.value) for d in price_data]
        
        # Simple heuristic: check trend + volatility
        recent_avg = sum(prices[-10:]) / 10
        older_avg = sum(prices[:10]) / 10
        
        trend = (recent_avg - older_avg) / older_avg
        volatility = (max(prices) - min(prices)) / min(prices)
        
        if abs(trend) < 0.02 and volatility < 0.05:
            return "range"
        elif trend > 0.03:
            # Check volume for confirmation
            if volume_data:
                volumes = [float(d.value) for d in volume_data]
                recent_vol = sum(volumes[-5:]) / 5
                older_vol = sum(volumes[:5]) / 5
                if recent_vol > older_vol:
                    return "accumulation"
            return "uptrend"
        elif trend < -0.03:
            return "downtrend"
        else:
            return "uncertain"
    
    def _detect_divergences(self, snapshot: DataSnapshot) -> List[Tuple[str, float]]:
        """
        Detect divergences between price, sentiment, and other indicators.
        
        Returns list of (divergence_type, magnitude) tuples.
        """
        divergences = []
        
        # Price vs Sentiment divergence
        price_data = snapshot.get_by_type(DataType.PRICE, max_age=timedelta(hours=12))
        sentiment = snapshot.get_sentiment(max_age=timedelta(hours=6))
        
        if price_data and sentiment is not None:
            recent_price = float(price_data[-1].value)
            older_price = float(price_data[0].value) if len(price_data) > 1 else recent_price
            price_trend = (recent_price - older_price) / older_price
            
            # Sentiment range: [-1, 1], price_trend range: [-inf, inf]
            # Normalize price_trend to [-1, 1] for comparison
            normalized_trend = max(-1, min(1, price_trend * 10))
            
            divergence_magnitude = abs(normalized_trend - sentiment)
            
            if divergence_magnitude > 0.5:
                div_type = "bullish_divergence" if sentiment < normalized_trend else "bearish_divergence"
                divergences.append((div_type, divergence_magnitude))
        
        # Price vs Volume divergence
        volume_data = snapshot.get_by_type(DataType.VOLUME, max_age=timedelta(hours=12))
        if price_data and volume_data and len(volume_data) >= 5:
            volumes = [float(d.value) for d in volume_data]
            recent_vol = sum(volumes[-3:]) / 3
            older_vol = sum(volumes[:3]) / 3
            vol_trend = (recent_vol - older_vol) / older_vol if older_vol > 0 else 0
            
            if price_data:
                prices = [float(d.value) for d in price_data]
                price_trend = (prices[-1] - prices[0]) / prices[0] if prices[0] > 0 else 0
                
                # Price rising but volume falling = distribution
                if price_trend > 0.02 and vol_trend < -0.1:
                    divergences.append(("distribution_signal", 0.6))
                # Price falling but volume rising = capitulation
                elif price_trend < -0.02 and vol_trend > 0.1:
                    divergences.append(("capitulation_signal", 0.6))
        
        return divergences
    
    def _match_patterns(self, snapshot: DataSnapshot) -> float:
        """
        Match current data against known patterns.
        
        Returns confidence score [0, 1].
        """
        # Simplified: check for basic patterns
        price_data = snapshot.get_by_type(DataType.PRICE, max_age=timedelta(hours=24))
        
        if not price_data or len(price_data) < 10:
            return 0.2
        
        prices = [float(d.value) for d in price_data]
        
        # Check for consolidation before breakout pattern
        recent_range = max(prices[-5:]) - min(prices[-5:])
        older_range = max(prices[:5]) - min(prices[:5])
        
        if recent_range < older_range * 0.5:
            # Consolidation detected
            return 0.7
        
        # Check for ascending triangle
        highs = [prices[i] for i in range(len(prices)) if i % 3 == 0]
        if len(highs) >= 3:
            high_trend = (highs[-1] - highs[0]) / highs[0] if highs[0] > 0 else 0
            if -0.02 < high_trend < 0.02:  # Flat resistance
                return 0.65
        
        return 0.4
    
    def _compute_gut_feel(
        self,
        regime: str,
        divergences: List[Tuple[str, float]],
        pattern_score: float,
        hypothesis: str,
    ) -> float:
        """
        Compute gut feel probability.
        """
        # Base probability from pattern matching
        base = 0.3 + 0.3 * pattern_score
        
        # Regime adjustment
        if "bullish" in hypothesis.lower() or "breaks" in hypothesis.lower():
            if regime == "accumulation":
                base += 0.15
            elif regime == "distribution":
                base -= 0.15
            elif regime == "uptrend":
                base += 0.10
        
        # Divergence adjustment
        for div_type, magnitude in divergences:
            if "bearish" in div_type:
                base -= 0.10 * magnitude
            elif div_type == "distribution_signal":
                base -= 0.15
        
        return max(0.1, min(0.9, base))
    
    def _generate_dissent(
        self,
        regime: str,
        divergences: List[Tuple[str, float]],
    ) -> str:
        """
        Generate dissent notes.
        """
        notes = []
        
        notes.append(f"REGIME: {regime.upper()}")
        
        if divergences:
            div_desc = ", ".join(f"{dt}({mag:.2f})" for dt, mag in divergences)
            notes.append(f"DIVERGENCES DETECTED: {div_desc}")
            notes.append("WARNING: Price-sentiment misalignment suggests regime shift risk")
        
        notes.append("INTUITION: Pattern-based, not formal proof")
        notes.append("ASSUMES: Patterns remain statistically valid")
        
        return " | ".join(notes)
    
    def _generate_reasoning(
        self,
        regime: str,
        divergences: List[Tuple[str, float]],
        pattern_score: float,
        probability: float,
    ) -> str:
        """
        Generate reasoning trail.
        """
        parts = [
            f"REGIME: {regime}",
            f"PATTERN MATCH: {pattern_score:.2%} confidence",
        ]
        
        if divergences:
            parts.append(f"DIVERGENCES: {len(divergences)} detected")
            for div_type, mag in divergences:
                parts.append(f"  {div_type}: magnitude {mag:.2f}")
        else:
            parts.append("DIVERGENCES: None detected")
        
        parts.append(f"GUT FEEL: {probability:.2%}")
        parts.append("NOTE: Intuition signals emerge before formal confirmation")
        
        return "\n".join(parts)

"""
Adversarial Agent - Game theory, MEV, manipulation detection.
"""

from datetime import timedelta
from typing import Dict, List, Any

from .base import Agent
from ..utils.types import BeliefVector, AgentType, DataType, DataSource
from ..memory.snapshot import DataSnapshot


class AdversarialAgent(Agent):
    """
    Adversarial Agent: Game theory, MEV modeling, assumption attack.
    
    Responsibilities:
    - Detect manipulation/wash trading
    - Model MEV (front-run, sandwich, back-run)
    - Attack assumptions
    - Identify who profits if we act on this belief
    """
    
    def __init__(self):
        super().__init__(AgentType.ADVERSARIAL)
    
    def analyze(
        self,
        hypothesis: str,
        data_snapshot: DataSnapshot,
    ) -> BeliefVector:
        """
        Analyze hypothesis from adversarial perspective.
        """
        
        # Who profits if this hypothesis is believed?
        beneficiaries = self._identify_beneficiaries(hypothesis, data_snapshot)
        
        # Check for manipulation signals
        manipulation_score = self._detect_manipulation(data_snapshot)
        
        # Model MEV risk
        mev_risk = self._estimate_mev_risk(hypothesis, data_snapshot)
        
        # Attack assumptions
        assumption_vulnerabilities = self._attack_assumptions(hypothesis)
        
        # Compute adversarial probability (skeptical view)
        probability = self._compute_adversarial_view(
            manipulation_score,
            mev_risk,
            beneficiaries,
        )
        
        # High confidence when manipulation detected
        confidence = 0.50 + 0.30 * manipulation_score
        
        # Very high risk if manipulation suspected
        risk = 0.60 + 0.25 * manipulation_score
        
        # Generate warnings
        dissent = self._generate_warnings(
            manipulation_score,
            mev_risk,
            beneficiaries,
            assumption_vulnerabilities,
        )
        
        # Reasoning
        reasoning = self._generate_reasoning(
            manipulation_score,
            mev_risk,
            beneficiaries,
            probability,
        )
        
        return BeliefVector(
            agent_type=self.agent_type,
            hypothesis=hypothesis,
            probability=probability,
            confidence=min(0.85, confidence),
            risk=min(0.95, risk),
            dissent_notes=dissent,
            reasoning=reasoning,
        )
    
    def _identify_beneficiaries(
        self,
        hypothesis: str,
        snapshot: DataSnapshot,
    ) -> List[str]:
        """
        Identify who profits if hypothesis is believed and acted upon.
        """
        beneficiaries = []
        
        # Check for sudden odds shifts in prediction markets
        polymarket_data = snapshot.get_by_source(
            DataSource.POLYMARKET,
            max_age=timedelta(hours=6)
        )
        
        if polymarket_data and len(polymarket_data) >= 2:
            recent_odds = float(polymarket_data[-1].value)
            older_odds = float(polymarket_data[0].value)
            shift = abs(recent_odds - older_odds)
            
            if shift > 0.15:  # >15% shift
                beneficiaries.append("Market makers who shifted odds")
                beneficiaries.append("Insiders who positioned before shift")
        
        # Check volume patterns
        volume_data = snapshot.get_by_type(DataType.VOLUME, max_age=timedelta(hours=12))
        if volume_data and len(volume_data) >= 5:
            volumes = [float(d.value) for d in volume_data]
            recent_vol = sum(volumes[-3:]) / 3
            older_vol = sum(volumes[:3]) / 3
            
            if recent_vol > older_vol * 3:  # 3x volume spike
                beneficiaries.append("Large position holders (pump signal)")
        
        return beneficiaries if beneficiaries else ["No clear beneficiaries identified"]
    
    def _detect_manipulation(self, snapshot: DataSnapshot) -> float:
        """
        Detect manipulation signals.
        
        Returns manipulation score [0, 1].
        """
        score = 0.0
        
        # Check for wash trading (high volume, low price movement)
        price_data = snapshot.get_by_type(DataType.PRICE, max_age=timedelta(hours=6))
        volume_data = snapshot.get_by_type(DataType.VOLUME, max_age=timedelta(hours=6))
        
        if price_data and volume_data and len(price_data) >= 5 and len(volume_data) >= 5:
            prices = [float(d.value) for d in price_data]
            volumes = [float(d.value) for d in volume_data]
            
            price_range = (max(prices) - min(prices)) / min(prices)
            avg_volume = sum(volumes) / len(volumes)
            
            # High volume but low price movement = potential wash trading
            if avg_volume > 1e6 and price_range < 0.01:  # <1% move despite volume
                score += 0.4
        
        # Check for coordinated social sentiment
        sentiment = snapshot.get_sentiment(max_age=timedelta(hours=3))
        if sentiment is not None and abs(sentiment) > 0.7:
            # Extreme sentiment can indicate coordination
            score += 0.2
        
        # Check for prediction market odds manipulation
        polymarket_data = snapshot.get_by_source(
            DataSource.POLYMARKET,
            max_age=timedelta(hours=6)
        )
        
        if polymarket_data and len(polymarket_data) >= 3:
            odds = [float(d.value) for d in polymarket_data]
            # Check for suspicious patterns (sudden jumps then reversion)
            for i in range(len(odds) - 2):
                jump = abs(odds[i+1] - odds[i])
                reversion = abs(odds[i+2] - odds[i])
                if jump > 0.1 and reversion < 0.03:  # Jump then revert
                    score += 0.3
                    break
        
        return min(1.0, score)
    
    def _estimate_mev_risk(
        self,
        hypothesis: str,
        snapshot: DataSnapshot,
    ) -> float:
        """
        Estimate MEV (front-run, sandwich, back-run) risk.
        """
        # Base MEV risk
        risk = 0.2
        
        # Higher risk for onchain actions
        if any(word in hypothesis.lower() for word in ["swap", "trade", "buy", "sell"]):
            risk += 0.3
        
        # Check for high gas/congestion (MEV opportunity indicator)
        # In production: query onchain gas prices
        # For now: assume moderate risk
        risk += 0.1
        
        # Check liquidity depth
        # Thin liquidity = higher slippage = more MEV opportunity
        # In production: query DEX liquidity
        risk += 0.15
        
        return min(0.9, risk)
    
    def _attack_assumptions(self, hypothesis: str) -> List[str]:
        """
        Attack key assumptions in hypothesis.
        """
        vulnerabilities = []
        
        # Time-based assumptions
        if "within" in hypothesis.lower() or "48h" in hypothesis.lower():
            vulnerabilities.append("Time window assumption may be arbitrary")
        
        # Price-based assumptions
        if "$" in hypothesis or "price" in hypothesis.lower():
            vulnerabilities.append("Assumes price discovery is honest (ignores manipulation)")
        
        # Market efficiency assumptions
        vulnerabilities.append("Assumes market is rational (often false in crypto)")
        
        # Liquidity assumptions
        vulnerabilities.append("Assumes liquidity remains constant (can vanish instantly)")
        
        # External event assumptions
        vulnerabilities.append("Assumes no black swan regulatory/technical events")
        
        return vulnerabilities
    
    def _compute_adversarial_view(
        self,
        manipulation_score: float,
        mev_risk: float,
        beneficiaries: List[str],
    ) -> float:
        """
        Compute adversarial (skeptical) probability.
        """
        # Start skeptical
        base = 0.35
        
        # Heavy penalty for manipulation
        base -= 0.30 * manipulation_score
        
        # Penalty for clear beneficiaries
        if len(beneficiaries) > 2:
            base -= 0.10
        
        # Penalty for high MEV risk
        base -= 0.15 * mev_risk
        
        return max(0.05, min(0.7, base))
    
    def _generate_warnings(
        self,
        manipulation_score: float,
        mev_risk: float,
        beneficiaries: List[str],
        vulnerabilities: List[str],
    ) -> str:
        """
        Generate warnings and dissent.
        """
        warnings = []
        
        if manipulation_score > 0.5:
            warnings.append(f"🚨 HIGH MANIPULATION RISK ({manipulation_score:.0%})")
            warnings.append("Possible wash trading or coordinated pump detected")
        
        if mev_risk > 0.5:
            warnings.append(f"⚠️ MEV RISK: {mev_risk:.0%} (front-run/sandwich exposure)")
        
        if len(beneficiaries) > 1:
            warnings.append(f"BENEFICIARIES: {', '.join(beneficiaries)}")
        
        warnings.append(f"ASSUMPTION VULNERABILITIES: {len(vulnerabilities)}")
        for vuln in vulnerabilities[:2]:  # Show top 2
            warnings.append(f"  - {vuln}")
        
        warnings.append("ADVERSARIAL STANCE: Treat all signals as potentially adversarial")
        
        return " | ".join(warnings)
    
    def _generate_reasoning(
        self,
        manipulation_score: float,
        mev_risk: float,
        beneficiaries: List[str],
        probability: float,
    ) -> str:
        """
        Generate adversarial reasoning.
        """
        parts = [
            "ADVERSARIAL ANALYSIS:",
            f"Manipulation Score: {manipulation_score:.2%}",
            f"MEV Risk: {mev_risk:.2%}",
            f"Identified Beneficiaries: {len(beneficiaries)}",
        ]
        
        for beneficiary in beneficiaries[:3]:
            parts.append(f"  - {beneficiary}")
        
        parts.extend([
            f"Adversarial Probability: {probability:.2%}",
            "STANCE: Skeptical - assume adversarial until proven otherwise",
            "RECOMMENDATION: Verify all signals independently, expect manipulation",
        ])
        
        return "\n".join(parts)

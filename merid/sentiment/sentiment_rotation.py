"""
Portfolio Rotation Based on Sentiment Sectors (Kalshi)

Treats clusters of Kalshi markets as "sectors" (BTC/crypto, macro, politics)
and rotates exposure as sentiment regimes change.

Mirrors sentiment-based sector rotation: shift capital toward sectors with
constructive sentiment, away from deteriorating sentiment.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class SectorSentiment:
    """Sentiment state for a sector."""
    name: str                      # Sector name (crypto, macro, politics)
    combined: float = 0.0          # Combined sentiment -1..1
    fg_index: int = 50           # Fear/greed for sector
    confidence: float = 0.5        # Confidence in sentiment
    score: float = 0.0             # Computed rotation score
    markets: List[str] = field(default_factory=list)  # Markets in sector
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    def is_extreme(self) -> bool:
        """Check if sector in extreme sentiment state."""
        return self.fg_index >= 80 or self.fg_index <= 20


@dataclass
class RotationPlan:
    """Target allocation per sector."""
    sector: str
    current_exposure: float
    target_exposure: float
    delta: float
    reason: str


class SentimentSectorRotator:
    """
    Rotate Kalshi portfolio exposure based on sector sentiment.
    
    Usage:
        rotator = SentimentSectorRotator()
        
        # Get sector sentiments
        sectors = [
            SectorSentiment("crypto", 0.4, 75, 0.8, ["KXBTC-DAILY", "KXBTC-HOURLY"]),
            SectorSentiment("macro", 0.1, 45, 0.6, ["KXGDP-Q4", "KXINF-JAN"]),
        ]
        
        # Compute rotation
        targets = rotator.compute_rotation(sectors, total_exposure=1.0)
        
        # Apply to portfolio
        for sector, target in targets.items():
            >>> print(f"{sector}: ${target:.2f}")
    """
    
    def __init__(
        self,
        min_score_threshold: float = 0.1,
        extreme_penalty: float = 0.3,
        max_sector_concentration: float = 0.6,
    ):
        self.min_score_threshold = min_score_threshold
        self.extreme_penalty = extreme_penalty
        self.max_sector_concentration = max_sector_concentration
    
    def compute_sector_score(
        self,
        sent: SectorSentiment,
    ) -> float:
        """
        Compute rotation score for a sector.
        
        Formula: sentiment - penalty if FG extreme
        
        Args:
            sent: Sector sentiment state
        
        Returns:
            Score (-1 to 1, higher = more attractive)
        """
        score = sent.combined
        
        # Penalty for extreme FG (riskier)
        if sent.is_extreme():
            score -= self.extreme_penalty
        
        # Penalty for low confidence
        if sent.confidence < 0.4:
            score *= 0.7
        
        return max(-1.0, min(1.0, score))
    
    def compute_rotation(
        self,
        sector_sents: List[SectorSentiment],
        total_exposure: float = 1.0,
        current_allocations: Optional[Dict[str, float]] = None,
    ) -> Dict[str, float]:
        """
        Compute target exposure per sector.
        
        Args:
            sector_sents: List of sector sentiment states
            total_exposure: Total portfolio exposure to allocate
            current_allocations: Current sector exposures (optional)
        
        Returns:
            Dict mapping sector name to target exposure
        """
        # Compute scores
        scored_sectors = []
        for sent in sector_sents:
            score = self.compute_sector_score(sent)
            sent.score = score
            scored_sectors.append(sent)
        
        # Keep only positive scores for allocation
        positive_sectors = [s for s in scored_sectors if s.score > self.min_score_threshold]
        
        if not positive_sectors:
            # No attractive sectors - reduce exposure
            logger.warning("No sectors with positive score - returning zero allocation")
            return {s.name: 0.0 for s in sector_sents}
        
        # Compute total score
        total_score = sum(s.score for s in positive_sectors)
        
        # Allocate proportionally to scores
        targets = {}
        for sector in positive_sectors:
            share = sector.score / total_score
            target = total_exposure * share
            
            # Apply max concentration limit
            target = min(target, total_exposure * self.max_sector_concentration)
            
            targets[sector.name] = target
        
        # Zero allocation for negative score sectors
        for sector in sector_sents:
            if sector.name not in targets:
                targets[sector.name] = 0.0
        
        # Normalize to ensure sum equals total_exposure
        total_allocated = sum(targets.values())
        if total_allocated > 0 and total_allocated != total_exposure:
            scale = total_exposure / total_allocated
            targets = {k: v * scale for k, v in targets.items()}
        
        return targets
    
    def generate_rotation_plan(
        self,
        sector_sents: List[SectorSentiment],
        current_allocations: Dict[str, float],
        total_exposure: float = 1.0,
    ) -> List[RotationPlan]:
        """
        Generate detailed rotation plan with deltas.
        
        Args:
            sector_sents: Sector sentiment states
            current_allocations: Current exposure per sector
            total_exposure: Total target exposure
        
        Returns:
            List of RotationPlan
        """
        targets = self.compute_rotation(sector_sents, total_exposure, current_allocations)
        
        plans = []
        for sector in sector_sents:
            current = current_allocations.get(sector.name, 0.0)
            target = targets.get(sector.name, 0.0)
            delta = target - current
            
            # Generate reason
            if delta > 0:
                reason = f"Increase: score={sector.score:+.2f}, sentiment={sector.combined:+.2f}"
            elif delta < 0:
                reason = f"Decrease: score={sector.score:+.2f}"
            else:
                reason = "Hold: no change"
            
            plans.append(RotationPlan(
                sector=sector.name,
                current_exposure=current,
                target_exposure=target,
                delta=delta,
                reason=reason,
            ))
        
        # Sort by absolute delta (largest changes first)
        plans.sort(key=lambda p: -abs(p.delta))
        
        return plans
    
    def should_rebalance(
        self,
        plan: List[RotationPlan],
        threshold_pct: float = 0.05,
    ) -> bool:
        """
        Check if rebalancing is needed.
        
        Args:
            plan: Rotation plan
            threshold_pct: Minimum change threshold (5% default)
        
        Returns:
            True if any sector change exceeds threshold
        """
        for p in plan:
            if abs(p.delta) > threshold_pct:
                return True
        return False
    
    def get_sector_summary(
        self,
        sector_sents: List[SectorSentiment],
    ) -> Dict[str, Any]:
        """
        Get summary of sector sentiments.
        
        Returns:
            Dict with ranked sectors
        """
        # Compute scores
        for sent in sector_sents:
            sent.score = self.compute_sector_score(sent)
        
        # Sort by score
        ranked = sorted(sector_sents, key=lambda s: -s.score)
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sectors_ranked": [
                {
                    "name": s.name,
                    "score": round(s.score, 3),
                    "sentiment": round(s.combined, 3),
                    "fg_index": s.fg_index,
                    "confidence": round(s.confidence, 3),
                    "markets": s.markets,
                    "is_extreme": s.is_extreme(),
                }
                for s in ranked
            ],
            "recommendation": f"Top sector: {ranked[0].name} (score={ranked[0].score:+.2f})" if ranked else "None",
        }


# ── Convenience functions ──────────────────────────────────────────

def quick_sector_rotation(
    sectors: List[Tuple[str, float, int]],  # (name, sentiment, fg)
    total_exposure: float = 1.0,
) -> Dict[str, float]:
    """
    Quick one-liner for sector rotation.
    
    Args:
        sectors: List of (name, combined_sentiment, fg_index)
        total_exposure: Total exposure to allocate
    
    Returns:
        Dict of sector -> target exposure
    """
    rotator = SentimentSectorRotator()
    
    sector_sents = [
        SectorSentiment(
            name=name,
            combined=sent,
            fg_index=fg,
            confidence=0.5,
        )
        for name, sent, fg in sectors
    ]
    
    return rotator.compute_rotation(sector_sents, total_exposure)


def rank_sectors_by_sentiment(
    sectors: List[SectorSentiment],
) -> List[str]:
    """
    Rank sectors by sentiment score.
    
    Returns:
        List of sector names (best first)
    """
    rotator = SentimentSectorRotator()
    
    for s in sectors:
        s.score = rotator.compute_sector_score(s)
    
    ranked = sorted(sectors, key=lambda s: -s.score)
    return [s.name for s in ranked]

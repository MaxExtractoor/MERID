"""
Multi-Timeframe Fusion Engine
=============================
Fuses signals from higher, primary, and lower timeframes into a
cluster signal that drives Kalshi contract selection.
"""

from __future__ import annotations

from typing import Optional, List
from dataclasses import dataclass

from .ta_models import SignalScore, FusedClusterSignal, MarketStructure


@dataclass
class FusionConfig:
    """Configuration for timeframe fusion logic."""
    # Confidence thresholds
    min_higher_tf_alignment: float = 0.3
    min_lower_tf_confirmation: float = 0.3

    # Quality weights
    trend_alignment_weight: float = 0.4
    divergence_weight: float = 0.3
    fib_confluence_weight: float = 0.2
    volume_confirm_weight: float = 0.1

    # Rejection rules
    reject_if_higher_tf_contra_div: bool = True
    range_market_min_confluence_tags: int = 3

    # Contra-trend penalties
    contra_trend_confidence_cap: float = 0.6
    contra_trend_quality_penalty: float = 0.3

    # Size multipliers by quality
    high_quality_size_mult: float = 1.2
    medium_quality_size_mult: float = 1.0
    low_quality_size_mult: float = 0.6


class TimeframeFusionEngine:
    """
    Engine for fusing multi-timeframe signals.
    Pure functions - no state, thread-safe.
    """

    def __init__(self, config: Optional[FusionConfig] = None):
        self.config = config or FusionConfig()

    def fuse(
        self,
        asset: str,
        primary_tf: str,
        higher_tf_signal: Optional[SignalScore],
        primary_tf_signal: SignalScore,
        lower_tf_signal: Optional[SignalScore],
        market_structure: MarketStructure,
    ) -> FusedClusterSignal:
        """
        Fuse three timeframe signals into a cluster signal.

        Fusion rules:
        1. Only allow aggressive longs if:
           - Primary TF is long
           - Higher TF trend is up (or neutral)
           - No bearish divergence on higher TF
           - Lower TF confirms (or is neutral)

        2. Only allow aggressive shorts if:
           - Primary TF is short
           - Higher TF trend is down (or neutral)
           - No bullish divergence on higher TF
           - Lower TF confirms (or is neutral)

        3. In ranges, require stronger confluence:
           - Multiple aligned signals
           - RSI divergence + fib level proximity
           - Liquidity sweep confirmation

        4. Reject if:
           - Primary signal is flat
           - Higher TF has contra-trend divergence
           - Not enough confirmation in range markets
        """

        # Start with primary signal
        direction = primary_tf_signal.direction
        confidence = primary_tf_signal.confidence
        quality = primary_tf_signal.quality_score
        tags = list(primary_tf_signal.rationale_tags)
        rejection = None

        # Calculate alignment with higher TF
        higher_alignment = self._calc_higher_tf_alignment(
            primary_tf_signal, higher_tf_signal
        )

        # Calculate confirmation from lower TF
        lower_confirmation = self._calc_lower_tf_confirmation(
            primary_tf_signal, lower_tf_signal
        )

        # Check multi-TF agreement
        all_directions = [primary_tf_signal.direction]
        if higher_tf_signal:
            all_directions.append(higher_tf_signal.direction)
        if lower_tf_signal:
            all_directions.append(lower_tf_signal.direction)

        multi_tf_agreement = len(set(all_directions)) == 1 and "flat" not in all_directions

        # Apply rejection rules
        if direction == "flat":
            rejection = "PRIMARY_SIGNAL_FLAT"
        elif higher_tf_signal and self._has_contra_divergence(primary_tf_signal, higher_tf_signal):
            if self.config.reject_if_higher_tf_contra_div:
                rejection = "HIGHER_TF_CONTRA_DIVERGENCE"
                confidence *= 0.5

        # Apply regime-specific rules
        if market_structure.trend_regime == "range":
            # In ranges, require more confluence
            if len(tags) < self.config.range_market_min_confluence_tags:
                if not primary_tf_signal.has_bullish_divergence and not primary_tf_signal.has_bearish_divergence:
                    rejection = "INSUFFICIENT_CONFLUENCE_IN_RANGE"

        # Apply contra-trend penalties
        if primary_tf_signal.contra_trend:
            confidence = min(confidence, self.config.contra_trend_confidence_cap)
            quality = max(0.0, quality - self.config.contra_trend_quality_penalty)
            tags.append("contra_trend")

        # Final confidence is capped by alignment and confirmation
        confidence = min(confidence, 0.5 + higher_alignment * 0.3 + lower_confirmation * 0.2)

        # Calculate size multiplier based on quality and alignment
        size_mult = self._calc_size_multiplier(
            quality, higher_alignment, lower_confirmation, multi_tf_agreement
        )

        return FusedClusterSignal(
            asset=asset,
            primary_tf=primary_tf,
            timestamp=primary_tf_signal.timestamp,
            direction=direction if not rejection else "flat",
            confidence=round(confidence, 3),
            quality_score=round(quality, 3),
            higher_tf_alignment=round(higher_alignment, 3),
            lower_tf_confirmation=round(lower_confirmation, 3),
            multi_tf_agreement=multi_tf_agreement,
            higher_tf_signal=higher_tf_signal,
            primary_tf_signal=primary_tf_signal,
            lower_tf_signal=lower_tf_signal,
            rationale_tags=tags,
            rejection_reason=rejection,
            size_multiplier=round(size_mult, 3),
        )

    def _calc_higher_tf_alignment(
        self,
        primary: SignalScore,
        higher: Optional[SignalScore],
    ) -> float:
        """
        Calculate how well higher TF aligns with primary signal.
        1.0 = perfect alignment, 0.0 = neutral, -1.0 = contra
        """
        if not higher or higher.direction == "flat":
            return 0.5  # Neutral is okay

        if higher.direction == primary.direction:
            return 0.7 + higher.confidence * 0.3
        else:
            return -0.5 - higher.confidence * 0.5

    def _calc_lower_tf_confirmation(
        self,
        primary: SignalScore,
        lower: Optional[SignalScore],
    ) -> float:
        """
        Calculate how well lower TF confirms primary signal.
        """
        if not lower or lower.direction == "flat":
            return 0.3  # Neutral is weak confirmation

        if lower.direction == primary.direction:
            return 0.6 + lower.confidence * 0.4
        else:
            return -0.4  # Disagreement reduces confidence

    def _has_contra_divergence(
        self,
        primary: SignalScore,
        higher: SignalScore,
    ) -> bool:
        """
        Check if higher TF has divergence contra to primary direction.
        Example: Primary is long, higher TF has bearish divergence
        """
        if primary.direction == "long":
            return higher.divergence_score < -0.3
        elif primary.direction == "short":
            return higher.divergence_score > 0.3
        return False

    def _calc_size_multiplier(
        self,
        quality: float,
        higher_alignment: float,
        lower_confirmation: float,
        multi_tf_agreement: bool,
    ) -> float:
        """Calculate position size multiplier based on signal quality."""
        base_mult = self.config.medium_quality_size_mult

        if quality > 0.7 and higher_alignment > 0.5:
            base_mult = self.config.high_quality_size_mult
        elif quality < 0.4 or higher_alignment < 0:
            base_mult = self.config.low_quality_size_mult

        # Boost for multi-TF agreement
        if multi_tf_agreement:
            base_mult *= 1.1

        # Penalty for poor lower TF confirmation
        if lower_confirmation < 0:
            base_mult *= 0.7

        return min(1.5, max(0.3, base_mult))

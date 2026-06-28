"""
Fear/Greed, Volatility & Sizing — Canonical Types and Config

This module defines the single source of truth for:
- SentimentScalar: 0-100 fear/greed index with regime classification
- VolatilityScalar: Normalized volatility measure with uncertainty tracking
- SizingMultiplier: Deterministic sizing multiplier [0,1] from sentiment/vol

All execution-critical sizing decisions MUST use these types.
No magic numbers allowed outside this config layer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any, Callable, List
import os


# ═══════════════════════════════════════════════════════════════════════════
# Regime Classifications
# ═══════════════════════════════════════════════════════════════════════════

class FearGreedRegime(str, Enum):
    """Canonical fear/greed regime classification."""
    EXTREME_FEAR = "extreme_fear"
    FEAR = "fear"
    NEUTRAL = "neutral"
    GREED = "greed"
    EXTREME_GREED = "extreme_greed"


class VolatilityRegime(str, Enum):
    """Canonical volatility regime classification."""
    DEAD = "dead"           # Below minimum tradeable threshold
    LOW = "low"             # Below target - can increase size
    TARGET = "target"       # Optimal trading zone
    HIGH = "high"           # Above target - reduce size
    EXTREME = "extreme"     # Chaos - halt or minimal size


class UncertaintyRegime(str, Enum):
    """Volatility-of-volatility uncertainty classification."""
    STABLE = "stable"       # Vol is predictable
    ELEVATED = "elevated"   # Vol is shifting
    UNSTABLE = "unstable"   # Vol is unpredictable - additional penalty


# ═══════════════════════════════════════════════════════════════════════════
# Config (All thresholds centralized here)
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class SentimentVolConfig:
    """
    Centralized configuration for sentiment/volatility thresholds.
    
    All thresholds are configurable via environment variables with
    sensible defaults based on academic research and market conventions.
    
    Environment variable pattern: KALSHI_{SETTING_NAME}
    """
    
    # ── Fear/Greed Index Thresholds ─────────────────────────────────────────
    # Standard 0-100 FGI scale from alternative.me/cfgi.io conventions
    EXTREME_FEAR_MAX: int = field(
        default_factory=lambda: int(os.getenv("KALSHI_SENTIMENT_EXTREME_FEAR_MAX", "25"))
    )
    FEAR_MAX: int = field(
        default_factory=lambda: int(os.getenv("KALSHI_SENTIMENT_FEAR_MAX", "45"))
    )
    GREED_MIN: int = field(
        default_factory=lambda: int(os.getenv("KALSHI_SENTIMENT_GREED_MIN", "55"))
    )
    EXTREME_GREED_MIN: int = field(
        default_factory=lambda: int(os.getenv("KALSHI_SENTIMENT_EXTREME_GREED_MIN", "75"))
    )
    
    # ── Volatility Thresholds ────────────────────────────────────────────────
    # Annualized volatility bounds (fraction, e.g., 0.15 = 15%)
    VOL_DEAD_MAX: float = field(
        default_factory=lambda: float(os.getenv("KALSHI_VOL_DEAD_MAX", "0.15"))
    )
    VOL_LOW_MAX: float = field(
        default_factory=lambda: float(os.getenv("KALSHI_VOL_LOW_MAX", "0.30"))
    )
    VOL_TARGET: float = field(
        default_factory=lambda: float(os.getenv("KALSHI_VOL_TARGET", "0.50"))
    )
    VOL_HIGH_MIN: float = field(
        default_factory=lambda: float(os.getenv("KALSHI_VOL_HIGH_MIN", "0.70"))
    )
    VOL_EXTREME_MIN: float = field(
        default_factory=lambda: float(os.getenv("KALSHI_VOL_EXTREME_MIN", "1.20"))
    )
    
    # Update __post_init__ to also validate volatility thresholds
    def __post_init__(self):
        # CRITICAL FIX: Validate sentiment thresholds are in valid range [0, 100]
        for field_name in ["EXTREME_FEAR_MAX", "FEAR_MAX", "GREED_MIN", "EXTREME_GREED_MIN"]:
            value = getattr(self, field_name)
            if value < 0 or value > 100:
                logger.warning(
                    "[SENTIMENT-VOL] Invalid %s=%s - clamping to [0, 100]",
                    field_name, value
                )
                setattr(self, field_name, max(0, min(100, value)))
        # CRITICAL FIX: Validate volatility thresholds are reasonable positive values
        for field_name in ["VOL_DEAD_MAX", "VOL_LOW_MAX", "VOL_TARGET", "VOL_HIGH_MIN", "VOL_EXTREME_MIN"]:
            value = getattr(self, field_name)
            if value < 0 or value > 5.0:
                logger.warning(
                    "[SENTIMENT-VOL] Invalid %s=%s - clamping to [0, 5.0]",
                    field_name, value
                )
                setattr(self, field_name, max(0.0, min(5.0, value)))
    
    # ── Uncertainty (Vol-of-Vol) Thresholds ─────────────────────────────────
    # When vol-of-vol is high, we penalize sizing further
    UNCERTAINTY_STABLE_MAX: float = field(
        default_factory=lambda: float(os.getenv("KALSHI_UNCERTAINTY_STABLE_MAX", "0.20"))
    )
    UNCERTAINTY_ELEVATED_MAX: float = field(
        default_factory=lambda: float(os.getenv("KALSHI_UNCERTAINTY_ELEVATED_MAX", "0.40"))
    )
    
    # ── Sizing Multiplier Parameters ──────────────────────────────────────
    # Extreme sentiment regime multiplier
    SIZING_MULT_EXTREME_SENTIMENT: float = field(
        default_factory=lambda: float(os.getenv("KALSHI_SIZING_MULT_EXTREME_SENTIMENT", "0.60"))
    )
    # Fear/greed (non-extreme) sentiment multiplier
    SIZING_MULT_FEAR_GREED: float = field(
        default_factory=lambda: float(os.getenv("KALSHI_SIZING_MULT_FEAR_GREED", "0.80"))
    )
    # Neutral sentiment multiplier
    SIZING_MULT_NEUTRAL: float = field(
        default_factory=lambda: float(os.getenv("KALSHI_SIZING_MULT_NEUTRAL", "1.00"))
    )
    
    # Volatility regime multipliers (applied on top of sentiment)
    SIZING_MULT_DEAD_VOL: float = field(
        default_factory=lambda: float(os.getenv("KALSHI_SIZING_MULT_DEAD_VOL", "0.50"))
    )
    SIZING_MULT_LOW_VOL: float = field(
        default_factory=lambda: float(os.getenv("KALSHI_SIZING_MULT_LOW_VOL", "1.10"))
    )
    SIZING_MULT_TARGET_VOL: float = field(
        default_factory=lambda: float(os.getenv("KALSHI_SIZING_MULT_TARGET_VOL", "1.00"))
    )
    SIZING_MULT_HIGH_VOL: float = field(
        default_factory=lambda: float(os.getenv("KALSHI_SIZING_MULT_HIGH_VOL", "0.70"))
    )
    SIZING_MULT_EXTREME_VOL: float = field(
        default_factory=lambda: float(os.getenv("KALSHI_SIZING_MULT_EXTREME_VOL", "0.30"))
    )
    
    # Uncertainty penalty (additional multiplier on top of vol multiplier)
    UNCERTAINTY_ELEVATED_PENALTY: float = field(
        default_factory=lambda: float(os.getenv("KALSHI_UNCERTAINTY_ELEVATED_PENALTY", "0.85"))
    )
    UNCERTAINTY_UNSTABLE_PENALTY: float = field(
        default_factory=lambda: float(os.getenv("KALSHI_UNCERTAINTY_UNSTABLE_PENALTY", "0.65"))
    )
    
    # ── Confidence Scaling ───────────────────────────────────────────────
    # Low confidence sentiment signals get scaled down
    CONFIDENCE_SCALE_BASE: float = field(
        default_factory=lambda: float(os.getenv("KALSHI_CONFIDENCE_SCALE_BASE", "0.50"))
    )
    CONFIDENCE_SCALE_MAX: float = field(
        default_factory=lambda: float(os.getenv("KALSHI_CONFIDENCE_SCALE_MAX", "0.50"))
    )
    
    # ── Absolute Limits ────────────────────────────────────────────────────
    # Hard floor and ceiling for final sizing multiplier
    SIZING_MULT_FLOOR: float = field(
        default_factory=lambda: float(os.getenv("KALSHI_SIZING_MULT_FLOOR", "0.20"))
    )
    SIZING_MULT_CEILING: float = field(
        default_factory=lambda: float(os.getenv("KALSHI_SIZING_MULT_CEILING", "1.20"))
    )
    
    # ── News Health Factor ───────────────────────────────────────────────────
    # News feed health affects sizing but never blocks execution (per D6/D7)
    NEWS_HEALTH_HEALTHY: float = field(
        default_factory=lambda: float(os.getenv("KALSHI_NEWS_HEALTH_HEALTHY", "1.0"))
    )
    NEWS_HEALTH_DEGRADED: float = field(
        default_factory=lambda: float(os.getenv("KALSHI_NEWS_HEALTH_DEGRADED", "0.5"))
    )
    NEWS_HEALTH_ERROR: float = field(
        default_factory=lambda: float(os.getenv("KALSHI_NEWS_HEALTH_ERROR", "0.5"))
    )
    NEWS_HEALTH_FLOOR: float = field(
        default_factory=lambda: float(os.getenv("KALSHI_NEWS_HEALTH_FLOOR", "0.3"))
    )
    
    # ── Contrarian Logic ──────────────────────────────────────────────────
    # When going against extreme crowd sentiment, we can be less cautious
    CONTRARIAN_BOOST: float = field(
        default_factory=lambda: float(os.getenv("KALSHI_CONTRARIAN_BOOST", "1.15"))
    )
    EXTREME_SENTIMENT_THRESHOLD: int = field(
        default_factory=lambda: int(os.getenv("KALSHI_EXTREME_SENTIMENT_THRESHOLD", "20"))
    )
    
    def validate(self) -> List[str]:
        """Validate config consistency. Returns list of error messages."""
        errors = []
        
        # Check ordering of sentiment thresholds
        if not (0 <= self.EXTREME_FEAR_MAX <= self.FEAR_MAX <= 50 <= self.GREED_MIN <= self.EXTREME_GREED_MIN <= 100):
            errors.append(f"Invalid sentiment threshold ordering: {self.EXTREME_FEAR_MAX}/{self.FEAR_MAX}/{self.GREED_MIN}/{self.EXTREME_GREED_MIN}")
        
        # Check ordering of volatility thresholds
        if not (0 < self.VOL_DEAD_MAX < self.VOL_LOW_MAX < self.VOL_TARGET < self.VOL_HIGH_MIN < self.VOL_EXTREME_MIN):
            errors.append(f"Invalid volatility threshold ordering")
        
        # Check multiplier ranges
        for name, val in [
            ("SIZING_MULT_EXTREME_SENTIMENT", self.SIZING_MULT_EXTREME_SENTIMENT),
            ("SIZING_MULT_FEAR_GREED", self.SIZING_MULT_FEAR_GREED),
            ("SIZING_MULT_DEAD_VOL", self.SIZING_MULT_DEAD_VOL),
            ("SIZING_MULT_HIGH_VOL", self.SIZING_MULT_HIGH_VOL),
            ("SIZING_MULT_EXTREME_VOL", self.SIZING_MULT_EXTREME_VOL),
        ]:
            if not (0.1 <= val <= 1.0):
                errors.append(f"{name} should be in [0.1, 1.0], got {val}")
        
        if not (1.0 <= self.SIZING_MULT_LOW_VOL <= self.SIZING_MULT_CEILING):
            errors.append(f"SIZING_MULT_LOW_VOL should be >= 1.0")
        
        if not (0.1 <= self.SIZING_MULT_FLOOR < self.SIZING_MULT_CEILING <= 2.0):
            errors.append(f"Invalid floor/ceiling: {self.SIZING_MULT_FLOOR}/{self.SIZING_MULT_CEILING}")
        
        return errors


# Singleton config instance
_config_instance: Optional[SentimentVolConfig] = None


def get_sentiment_vol_config() -> SentimentVolConfig:
    """Get the singleton SentimentVolConfig instance."""
    global _config_instance
    if _config_instance is None:
        _config_instance = SentimentVolConfig()
        errors = _config_instance.validate()
        if errors:
            from utils.logger import get_logger
            logger = get_logger(__name__)
            for err in errors:
                logger.error(f"SentimentVolConfig validation: {err}")
    return _config_instance


def reset_config() -> None:
    """Reset config singleton (useful for testing)."""
    global _config_instance
    _config_instance = None


# ═══════════════════════════════════════════════════════════════════════════
# Canonical Data Types
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class SentimentScalar:
    """
    Canonical 0-100 sentiment index with regime classification.
    
    This is the ONLY type that should be used for fear/greed decisions
    throughout the codebase. Raw data sources must convert to this format.
    
    Attributes:
        value: 0-100 fear/greed index (0=extreme fear, 100=extreme greed)
        regime: Canonical regime classification
        confidence: 0-1 confidence in the sentiment reading
        source: Identifier of the data source (e.g., "cfgi", "kalshi_ob")
        is_synthetic: True if data is estimated/fallback
        timestamp: UTC timestamp of the reading
        raw_data: Optional dict with source-specific raw values
    """
    value: float  # 0-100
    regime: FearGreedRegime
    confidence: float = 1.0  # 0-1
    source: str = "unknown"
    is_synthetic: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    raw_data: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        # Clamp value to valid range
        object.__setattr__(self, 'value', max(0.0, min(100.0, float(self.value))))
        object.__setattr__(self, 'confidence', max(0.0, min(1.0, float(self.confidence))))
    
    def is_extreme(self) -> bool:
        """Check if sentiment is in extreme zone."""
        return self.regime in (FearGreedRegime.EXTREME_FEAR, FearGreedRegime.EXTREME_GREED)
    
    def get_contrarian_signal(self) -> str:
        """Get contrarian trading signal."""
        if self.regime == FearGreedRegime.EXTREME_FEAR:
            return "bullish_contrarian"
        elif self.regime == FearGreedRegime.EXTREME_GREED:
            return "bearish_contrarian"
        return "neutral"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": round(self.value, 2),
            "regime": self.regime.value,
            "confidence": round(self.confidence, 3),
            "source": self.source,
            "is_synthetic": self.is_synthetic,
            "timestamp": self.timestamp.isoformat(),
            "is_extreme": self.is_extreme(),
            "contrarian_signal": self.get_contrarian_signal(),
        }


@dataclass(frozen=True)
class VolatilityScalar:
    """
    Canonical volatility measure with regime classification and uncertainty.
    
    This is the ONLY type that should be used for volatility-based sizing.
    All vol calculations must normalize to this format.
    
    Attributes:
        value: Annualized volatility (e.g., 0.50 = 50% annualized)
        regime: Canonical vol regime classification
        uncertainty: Volatility-of-volatility measure (0-1 scale)
        uncertainty_regime: Classification of vol stability
        source: Identifier of calculation method (e.g., "realized", "atr", "vix")
        confidence: Confidence in the vol estimate (0-1)
        timestamp: UTC timestamp
        lookback_hours: Hours of data used for calculation
        raw_data: Optional dict with source-specific values
    """
    value: float  # Annualized vol as fraction
    regime: VolatilityRegime
    uncertainty: float = 0.0  # 0-1 vol-of-vol proxy
    uncertainty_regime: UncertaintyRegime = UncertaintyRegime.STABLE
    source: str = "unknown"
    confidence: float = 1.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    lookback_hours: float = 24.0
    raw_data: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        object.__setattr__(self, 'value', max(0.0, float(self.value)))
        object.__setattr__(self, 'uncertainty', max(0.0, min(1.0, float(self.uncertainty))))
        object.__setattr__(self, 'confidence', max(0.0, min(1.0, float(self.confidence))))
    
    def is_tradeable(self) -> bool:
        """Check if vol regime permits trading."""
        return self.regime not in (VolatilityRegime.DEAD, VolatilityRegime.EXTREME)
    
    def requires_size_reduction(self) -> bool:
        """Check if sizing should be reduced due to high vol."""
        return self.regime in (VolatilityRegime.HIGH, VolatilityRegime.EXTREME)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": round(self.value, 4),
            "regime": self.regime.value,
            "uncertainty": round(self.uncertainty, 3),
            "uncertainty_regime": self.uncertainty_regime.value,
            "source": self.source,
            "confidence": round(self.confidence, 3),
            "timestamp": self.timestamp.isoformat(),
            "lookback_hours": self.lookback_hours,
            "is_tradeable": self.is_tradeable(),
            "requires_size_reduction": self.requires_size_reduction(),
        }


@dataclass(frozen=True)
class SizingMultiplier:
    """
    Canonical sizing multiplier combining sentiment, volatility, and news health effects.
    
    This is the final multiplier applied to base position size (Kelly/fixed%).
    It encapsulates all fear/greed, volatility, and news feed adjustments in one value.
    
    The multiplier is deterministic given the inputs and config.
    
    Attributes:
        value: Final multiplier in [0, 1+] (typically 0.2 to 1.2)
        sentiment_contribution: Portion from sentiment adjustment
        volatility_contribution: Portion from volatility adjustment
        uncertainty_contribution: Portion from uncertainty penalty
        confidence_contribution: Portion from confidence scaling
        news_health_contribution: Portion from news feed health (per D6/D7)
        base_multiplier: Before any adjustments
        reasoning: Human-readable explanation of the calculation
        timestamp: UTC timestamp
        inputs: Snapshot of inputs used for reproducibility
    """
    value: float
    sentiment_contribution: float
    volatility_contribution: float
    uncertainty_contribution: float
    confidence_contribution: float
    news_health_contribution: float = 1.0
    base_multiplier: float = 1.0
    reasoning: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    inputs: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        cfg = get_sentiment_vol_config()
        # Clamp to configured bounds
        clamped = max(cfg.SIZING_MULT_FLOOR, min(cfg.SIZING_MULT_CEILING, float(self.value)))
        object.__setattr__(self, 'value', clamped)
    
    @property
    def is_fallback(self) -> bool:
        """True when multiplier was computed from synthetic/fallback inputs."""
        if self.inputs:
            sent = self.inputs.get("sentiment") or {}
            vol = self.inputs.get("volatility") or {}
            if sent.get("is_synthetic") or sent.get("source", "").startswith("fallback"):
                return True
            if vol.get("source", "").startswith("fallback"):
                return True
        return False

    def apply_to_size(self, base_size: float) -> float:
        """Apply multiplier to a base position size."""
        return base_size * self.value
    
    def get_regime_label(self) -> str:
        """Get human-readable regime label for UI display."""
        v = self.value
        cfg = get_sentiment_vol_config()
        
        if v <= cfg.SIZING_MULT_EXTREME_VOL:
            return "HALTED"
        elif v <= cfg.SIZING_MULT_HIGH_VOL:
            return "DOWNSIZED"
        elif v >= cfg.SIZING_MULT_LOW_VOL:
            return "BOOSTED"
        elif v >= 0.95:
            return "NORMAL"
        else:
            return "CAUTION"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": round(self.value, 4),
            "regime_label": self.get_regime_label(),
            "sentiment_contribution": round(self.sentiment_contribution, 4),
            "volatility_contribution": round(self.volatility_contribution, 4),
            "uncertainty_contribution": round(self.uncertainty_contribution, 4),
            "confidence_contribution": round(self.confidence_contribution, 4),
            "news_health_contribution": round(self.news_health_contribution, 4),
            "base_multiplier": round(self.base_multiplier, 4),
            "reasoning": self.reasoning,
            "timestamp": self.timestamp.isoformat(),
            "inputs": self.inputs,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Transform Functions (Pure, Testable)
# ═══════════════════════════════════════════════════════════════════════════

def compute_sentiment_regime(value: float, config: Optional[SentimentVolConfig] = None) -> FearGreedRegime:
    """
    Pure function to classify a 0-100 sentiment value into regime.
    
    Args:
        value: 0-100 fear/greed index
        config: Optional config override (uses singleton if None)
    
    Returns:
        FearGreedRegime classification
    """
    cfg = config or get_sentiment_vol_config()
    
    if value <= cfg.EXTREME_FEAR_MAX:
        return FearGreedRegime.EXTREME_FEAR
    elif value <= cfg.FEAR_MAX:
        return FearGreedRegime.FEAR
    elif value >= cfg.EXTREME_GREED_MIN:
        return FearGreedRegime.EXTREME_GREED
    elif value >= cfg.GREED_MIN:
        return FearGreedRegime.GREED
    else:
        return FearGreedRegime.NEUTRAL


def compute_volatility_regime(value: float, config: Optional[SentimentVolConfig] = None) -> VolatilityRegime:
    """
    Pure function to classify annualized volatility into regime.
    
    Args:
        value: Annualized volatility as fraction (e.g., 0.50 = 50%)
        config: Optional config override
    
    Returns:
        VolatilityRegime classification
    """
    cfg = config or get_sentiment_vol_config()
    
    if value <= cfg.VOL_DEAD_MAX:
        return VolatilityRegime.DEAD
    elif value <= cfg.VOL_LOW_MAX:
        return VolatilityRegime.LOW
    elif value >= cfg.VOL_EXTREME_MIN:
        return VolatilityRegime.EXTREME
    elif value >= cfg.VOL_HIGH_MIN:
        return VolatilityRegime.HIGH
    else:
        return VolatilityRegime.TARGET


def compute_uncertainty_regime(uncertainty: float, config: Optional[SentimentVolConfig] = None) -> UncertaintyRegime:
    """
    Pure function to classify vol-of-vol uncertainty.
    
    Args:
        uncertainty: 0-1 uncertainty measure
        config: Optional config override
    
    Returns:
        UncertaintyRegime classification
    """
    cfg = config or get_sentiment_vol_config()
    
    if uncertainty <= cfg.UNCERTAINTY_STABLE_MAX:
        return UncertaintyRegime.STABLE
    elif uncertainty <= cfg.UNCERTAINTY_ELEVATED_MAX:
        return UncertaintyRegime.ELEVATED
    else:
        return UncertaintyRegime.UNSTABLE


def compute_news_health_factor(
    status: str = "unknown",
    config: Optional[SentimentVolConfig] = None,
) -> float:
    """
    Pure function to compute news feed health sizing factor.
    
    Per D6/D7: News feed failures only inform conviction, never block execution.
    The factor reduces sizing but never to zero (floor ensures non-zero).
    
    Args:
        status: News health status from get_feed_health()["news"]["status"]
            - "healthy" → 1.0 (full sizing)
            - "stale", "zero_data", "no_matches" → 0.5 (degraded)
            - "error", "not_configured" → 0.5 (degraded, but not zero)
            - "unknown" or any other → 1.0 (assume healthy)
        config: Optional config override
    
    Returns:
        Multiplier in [NEWS_HEALTH_FLOOR, 1.0] (never zero)
    """
    cfg = config or get_sentiment_vol_config()
    
    factor_map = {
        "healthy": cfg.NEWS_HEALTH_HEALTHY,
        "stale": cfg.NEWS_HEALTH_DEGRADED,
        "zero_data": cfg.NEWS_HEALTH_DEGRADED,
        "no_matches": cfg.NEWS_HEALTH_DEGRADED,
        "error": cfg.NEWS_HEALTH_ERROR,
        "not_configured": cfg.NEWS_HEALTH_ERROR,
    }
    
    base_factor = factor_map.get(status, 1.0)
    
    # Enforce floor: news degradation never reduces to zero (per D6/D7)
    return max(cfg.NEWS_HEALTH_FLOOR, base_factor)


def compute_sentiment_multiplier(
    sentiment: SentimentScalar,
    is_contrarian: bool = False,
    config: Optional[SentimentVolConfig] = None,
) -> float:
    """
    Pure function to compute sentiment sizing multiplier.
    
    Args:
        sentiment: SentimentScalar with regime and confidence
        is_contrarian: True if position is against crowd sentiment
        config: Optional config override
    
    Returns:
        Multiplier in [0.2, 1.0+] based on config
    """
    cfg = config or get_sentiment_vol_config()
    
    # Base multiplier from regime
    if sentiment.regime in (FearGreedRegime.EXTREME_FEAR, FearGreedRegime.EXTREME_GREED):
        base = cfg.SIZING_MULT_EXTREME_SENTIMENT
    elif sentiment.regime in (FearGreedRegime.FEAR, FearGreedRegime.GREED):
        base = cfg.SIZING_MULT_FEAR_GREED
    else:
        base = cfg.SIZING_MULT_NEUTRAL
    
    # Contrarian boost in extremes
    if is_contrarian and sentiment.is_extreme():
        base *= cfg.CONTRARIAN_BOOST
    
    # Confidence scaling
    conf_scale = cfg.CONFIDENCE_SCALE_BASE + cfg.CONFIDENCE_SCALE_MAX * sentiment.confidence
    
    return base * conf_scale


def compute_volatility_multiplier(
    volatility: VolatilityScalar,
    config: Optional[SentimentVolConfig] = None,
) -> float:
    """
    Pure function to compute volatility sizing multiplier.
    
    Args:
        volatility: VolatilityScalar with regime and uncertainty
        config: Optional config override
    
    Returns:
        Multiplier based on vol regime and uncertainty
    """
    cfg = config or get_sentiment_vol_config()
    
    # Base multiplier from vol regime
    mult_map = {
        VolatilityRegime.DEAD: cfg.SIZING_MULT_DEAD_VOL,
        VolatilityRegime.LOW: cfg.SIZING_MULT_LOW_VOL,
        VolatilityRegime.TARGET: cfg.SIZING_MULT_TARGET_VOL,
        VolatilityRegime.HIGH: cfg.SIZING_MULT_HIGH_VOL,
        VolatilityRegime.EXTREME: cfg.SIZING_MULT_EXTREME_VOL,
    }
    base = mult_map.get(volatility.regime, cfg.SIZING_MULT_TARGET_VOL)
    
    # Uncertainty penalty
    if volatility.uncertainty_regime == UncertaintyRegime.ELEVATED:
        base *= cfg.UNCERTAINTY_ELEVATED_PENALTY
    elif volatility.uncertainty_regime == UncertaintyRegime.UNSTABLE:
        base *= cfg.UNCERTAINTY_UNSTABLE_PENALTY
    
    return base


def compute_sizing_multiplier(
    sentiment: SentimentScalar,
    volatility: VolatilityScalar,
    is_contrarian: bool = False,
    news_health_status: str = "healthy",
    config: Optional[SentimentVolConfig] = None,
) -> SizingMultiplier:
    """
    Pure function to compute complete sizing multiplier.
    
    This is the canonical entry point for sizing decisions.
    Given sentiment, volatility, and news health, returns deterministic multiplier.
    
    Per D6/D7: News feed health affects sizing but never blocks execution.
    The news_health_factor has a floor (NEWS_HEALTH_FLOOR) ensuring non-zero sizing.
    
    Args:
        sentiment: SentimentScalar with regime and confidence
        volatility: VolatilityScalar with regime and uncertainty
        is_contrarian: True if position is against crowd sentiment
        news_health_status: News feed status from get_feed_health()["news"]["status"]
        config: Optional config override
    
    Returns:
        SizingMultiplier with full decomposition including news_health_contribution
    """
    cfg = config or get_sentiment_vol_config()
    
    # Compute component multipliers
    sentiment_mult = compute_sentiment_multiplier(sentiment, is_contrarian, cfg)
    volatility_mult = compute_volatility_multiplier(volatility, cfg)
    news_health_mult = compute_news_health_factor(news_health_status, cfg)
    
    # Confidence contribution (already in sentiment_mult, but track separately)
    conf_scale = cfg.CONFIDENCE_SCALE_BASE + cfg.CONFIDENCE_SCALE_MAX * sentiment.confidence
    
    # Combined multiplier (sentiment * volatility * news_health)
    final_mult = sentiment_mult * volatility_mult * news_health_mult
    
    # Uncertainty contribution (extracted from volatility_mult)
    unc_penalty = 1.0
    if volatility.uncertainty_regime == UncertaintyRegime.ELEVATED:
        unc_penalty = cfg.UNCERTAINTY_ELEVATED_PENALTY
    elif volatility.uncertainty_regime == UncertaintyRegime.UNSTABLE:
        unc_penalty = cfg.UNCERTAINTY_UNSTABLE_PENALTY
    
    # Build reasoning string
    reasons = []
    if sentiment.is_extreme():
        reasons.append(f"extreme_{sentiment.regime.value}({sentiment.value:.0f})")
    else:
        reasons.append(f"sentiment_{sentiment.regime.value}({sentiment.value:.0f})")
    
    if is_contrarian and sentiment.is_extreme():
        reasons.append("contrarian_boost")
    
    reasons.append(f"vol_{volatility.regime.value}({volatility.value:.2%})")
    
    if volatility.uncertainty_regime != UncertaintyRegime.STABLE:
        reasons.append(f"uncertainty_{volatility.uncertainty_regime.value}")
    
    if sentiment.confidence < 0.8:
        reasons.append(f"low_confidence({sentiment.confidence:.2f})")
    
    # Add news health to reasoning if degraded
    if news_health_status not in ("healthy", "unknown"):
        reasons.append(f"news_{news_health_status}({news_health_mult:.2f})")
    
    return SizingMultiplier(
        value=final_mult,
        sentiment_contribution=sentiment_mult,
        volatility_contribution=volatility_mult,
        uncertainty_contribution=unc_penalty,
        confidence_contribution=conf_scale,
        news_health_contribution=news_health_mult,
        base_multiplier=1.0,
        reasoning="; ".join(reasons),
        inputs={
            "sentiment": sentiment.to_dict(),
            "volatility": volatility.to_dict(),
            "is_contrarian": is_contrarian,
            "news_health_status": news_health_status,
            "config_hash": hash(str(cfg)),
        },
    )


# ═══════════════════════════════════════════════════════════════════════════
# Convenience Functions
# ═══════════════════════════════════════════════════════════════════════════

def create_sentiment_scalar(
    value: float,
    confidence: float = 1.0,
    source: str = "manual",
    is_synthetic: bool = False,
    raw_data: Optional[Dict[str, Any]] = None,
) -> SentimentScalar:
    """Factory to create SentimentScalar with auto-classified regime."""
    regime = compute_sentiment_regime(value)
    return SentimentScalar(
        value=value,
        regime=regime,
        confidence=confidence,
        source=source,
        is_synthetic=is_synthetic,
        raw_data=raw_data,
    )


def create_volatility_scalar(
    value: float,
    uncertainty: float = 0.0,
    source: str = "manual",
    confidence: float = 1.0,
    lookback_hours: float = 24.0,
    raw_data: Optional[Dict[str, Any]] = None,
) -> VolatilityScalar:
    """Factory to create VolatilityScalar with auto-classified regime."""
    regime = compute_volatility_regime(value)
    unc_regime = compute_uncertainty_regime(uncertainty)
    return VolatilityScalar(
        value=value,
        regime=regime,
        uncertainty=uncertainty,
        uncertainty_regime=unc_regime,
        source=source,
        confidence=confidence,
        lookback_hours=lookback_hours,
        raw_data=raw_data,
    )
    unc_regime = compute_uncertainty_regime(uncertainty)
    return VolatilityScalar(
        value=value,
        regime=regime,
        uncertainty=uncertainty,
        uncertainty_regime=unc_regime,
        source=source,
        confidence=confidence,
        lookback_hours=lookback_hours,
        raw_data=raw_data,
    )

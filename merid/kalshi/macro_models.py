"""Kalshi Macro Overlay Data Models

Defines data structures for macro/event market state and conviction scoring.
Part of the MERID single-signal hierarchy (Level 3: Kalshi macro overlay).

Categories ingested:
- Financials: Fed decisions, rate cuts, inflation (CPI/PCE)
- Elections: major election outcomes, policy shifts
- Commodities: energy, metals, agricultural shocks
- Economics: GDP, unemployment, recession indicators
- Tech/Science: breakthrough events, regulatory decisions
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Set


class MacroCategory(str, Enum):
    """Kalshi macro market categories."""
    FINANCIALS = "financials"
    ELECTIONS = "elections"
    COMMODITIES = "commodities"
    ECONOMICS = "economics"
    TECH_SCIENCE = "tech_science"
    OTHER = "other"


class MacroRegime(str, Enum):
    """Macro regime classification."""
    RISK_ON = "risk_on"           # Favorable for risk assets
    RISK_OFF = "risk_off"         # Unfavorable for risk assets
    NEUTRAL = "neutral"           # No strong directional bias
    EVENT_RISK_HIGH = "event_risk_high"  # Elevated uncertainty


class VolatilityRegime(str, Enum):
    """Volatility regime inferred from macro markets."""
    EXPANDING = "expanding"       # Volatility rising
    CONTRACTING = "contracting"   # Volatility falling
    STABLE = "stable"             # Range-bound
    ELEVATED = "elevated"         # High but stable


@dataclass(frozen=True)
class MacroMarketState:
    """State for a single Kalshi macro/event market.
    
    Captures the probability-implied market view on macro outcomes.
    """
    ticker: str
    category: MacroCategory
    title: str
    
    # Core probability metrics
    yes_prob: float               # Current YES probability (0.0-1.0)
    yes_prob_24h_ago: float      # 24h change context
    yes_prob_7d_ago: float       # 7d trend context
    
    # Market microstructure
    spread_cents: int
    volume_24h: int
    open_interest: int
    
    # Timeliness
    last_update_ts: float
    seconds_to_expiry: Optional[int] = None
    
    # Derived sentiment
    @property
    def prob_change_24h(self) -> float:
        """24-hour probability change."""
        return self.yes_prob - self.yes_prob_24h_ago
    
    @property
    def is_liquid(self) -> bool:
        """Market has adequate liquidity."""
        return self.volume_24h > 100 and self.spread_cents <= 5


@dataclass
class MacroState:
    """Aggregated macro state across all tracked Kalshi markets.
    
    This is the output of the macro overlay layer, consumed by
    UnifiedSignalState.merge() in the single-signal hierarchy.
    """
    timestamp: float
    
    # Per-category states
    financials: Dict[str, MacroMarketState] = field(default_factory=dict)
    elections: Dict[str, MacroMarketState] = field(default_factory=dict)
    commodities: Dict[str, MacroMarketState] = field(default_factory=dict)
    economics: Dict[str, MacroMarketState] = field(default_factory=dict)
    tech_science: Dict[str, MacroMarketState] = field(default_factory=dict)
    
    # Aggregated regime classification
    macro_regime: MacroRegime = MacroRegime.NEUTRAL
    vol_regime: VolatilityRegime = VolatilityRegime.STABLE
    event_risk_score: float = 0.0  # 0.0-1.0, higher = more event risk
    
    # Key indicators
    fed_hike_prob: Optional[float] = None       # Next meeting hike probability
    cpi_surprise_prob: Optional[float] = None   # CPI surprise expectation
    recession_prob: Optional[float] = None       # Recession probability
    
    @property
    def is_risk_on(self) -> bool:
        """Check if regime is risk-on."""
        return self.macro_regime == MacroRegime.RISK_ON
    
    @property
    def is_risk_off(self) -> bool:
        """Check if regime is risk-off."""
        return self.macro_regime == MacroRegime.RISK_OFF


@dataclass
class AssetMacroSensitivity:
    """Defines how a crypto asset responds to macro factors.
    
    Sensitivity scores range from -1.0 (strong negative) to 
    +1.0 (strong positive), with 0.0 = neutral.
    """
    asset: str  # "BTC", "ETH", "SOL", "XRP", "DOGE"
    
    # Factor sensitivities
    risk_on_sensitivity: float = 0.0      # How much asset rises in risk-on
    rate_cut_sensitivity: float = 0.0     # Response to Fed rate cuts
    cpi_surprise_sensitivity: float = 0.0  # Response to inflation surprises
    recession_sensitivity: float = 0.0    # Response to recession fears
    tech_sentiment_sensitivity: float = 0.0  # Response to tech sector sentiment
    
    def validate(self) -> bool:
        """Ensure all sensitivities in valid range."""
        for val in [
            self.risk_on_sensitivity,
            self.rate_cut_sensitivity,
            self.cpi_surprise_sensitivity,
            self.recession_sensitivity,
            self.tech_sentiment_sensitivity,
        ]:
            if not -1.0 <= val <= 1.0:
                return False
        return True


@dataclass
class MacroConvictionScore:
    """Conviction score for a specific asset based on macro overlay.
    
    Output of MacroConvictionScorer.compute_score().
    Consumed by UnifiedSignalState to adjust crypto signal weights.
    """
    asset: str
    timestamp: float
    
    # Core score (0.0-1.0, higher = more favorable macro backdrop)
    score: float
    
    # Breakdown by factor
    risk_on_contribution: float = 0.0
    monetary_policy_contribution: float = 0.0
    inflation_contribution: float = 0.0
    recession_contribution: float = 0.0
    tech_sentiment_contribution: float = 0.0
    
    # Confidence in the score (based on data quality, liquidity)
    confidence: float = 0.5
    
    # Recommended action modifier
    recommended_modifier: float = 1.0  # Multiply base signal by this
    
    @property
    def is_bullish(self) -> bool:
        """Score indicates bullish macro backdrop."""
        return self.score > 0.6 and self.confidence > 0.5
    
    @property
    def is_bearish(self) -> bool:
        """Score indicates bearish macro backdrop."""
        return self.score < 0.4 and self.confidence > 0.5


# Default asset sensitivities based on empirical crypto-macro relationships
DEFAULT_ASSET_SENSITIVITIES: Dict[str, AssetMacroSensitivity] = {
    "BTC": AssetMacroSensitivity(
        asset="BTC",
        risk_on_sensitivity=0.7,           # BTC benefits from risk-on
        rate_cut_sensitivity=0.6,          # Rate cuts typically bullish
        cpi_surprise_sensitivity=-0.4,     # High CPI surprise often bearish
        recession_sensitivity=-0.5,        # Recession fears hurt BTC
        tech_sentiment_sensitivity=0.3,    # Some tech correlation
    ),
    "ETH": AssetMacroSensitivity(
        asset="ETH",
        risk_on_sensitivity=0.8,           # ETH more risk-sensitive than BTC
        rate_cut_sensitivity=0.7,
        cpi_surprise_sensitivity=-0.5,
        recession_sensitivity=-0.6,
        tech_sentiment_sensitivity=0.5,    # Higher tech correlation
    ),
    "SOL": AssetMacroSensitivity(
        asset="SOL",
        risk_on_sensitivity=0.9,           # Alts most risk-sensitive
        rate_cut_sensitivity=0.8,
        cpi_surprise_sensitivity=-0.6,
        recession_sensitivity=-0.7,
        tech_sentiment_sensitivity=0.6,
    ),
    "XRP": AssetMacroSensitivity(
        asset="XRP",
        risk_on_sensitivity=0.6,
        rate_cut_sensitivity=0.5,
        cpi_surprise_sensitivity=-0.3,
        recession_sensitivity=-0.4,
        tech_sentiment_sensitivity=0.2,    # Lower tech correlation
    ),
    "DOGE": AssetMacroSensitivity(
        asset="DOGE",
        risk_on_sensitivity=0.85,          # Meme coins very risk-sensitive
        rate_cut_sensitivity=0.75,
        cpi_surprise_sensitivity=-0.5,
        recession_sensitivity=-0.6,
        tech_sentiment_sensitivity=0.4,
    ),
}

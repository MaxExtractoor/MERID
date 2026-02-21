"""
Sentiment Regime Engine for Kalshi Swarm Risk Management.

Detects market regimes based on Fear/Greed, social sentiment, and volatility
to dynamically adjust risk caps and trading rules for all agents.
"""

from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


class SentimentRegime(Enum):
    """
    Sentiment-based market regimes for swarm coordination.
    
    Regimes drive different risk rules across all BTC 15m agents.
    """
    CALM_NEUTRAL = "calm_neutral"      # FG 30-70, low vol, neutral sentiment
    HOT_GREED = "hot_greed"            # FG >= 80, positive sentiment, high vol
    HOT_FEAR = "hot_fear"              # FG <= 20, negative sentiment, high vol
    NOISY = "noisy"                    # Sentiment flipping, no clear direction
    CONTRARIAN_OPPORTUNITY = "contrarian_opportunity"  # Extreme FG vs sentiment divergence


@dataclass
class RiskCaps:
    """Dynamic risk caps for a regime."""
    max_per_trade: float      # Max per-trade size (0.25 base)
    max_live_positions: int   # Max concurrent positions
    max_exposure: float       # Max total exposure (% of equity)
    sentiment_bias_max: float  # Max probability bias from sentiment (+/-)
    allow_new_entries: bool   # Can agents enter new positions?
    late_entry_cutoff: Optional[int]  # Block entries after X bars (None = no cutoff)


@dataclass
class RegimeState:
    """Current regime state with all inputs."""
    regime: SentimentRegime
    fg_index: int
    sent_combined: float
    volatility: float         # Realized vol (0-1 scale)
    timestamp: datetime
    reasoning: str
    
    def is_extreme(self) -> bool:
        """Check if in extreme regime."""
        return self.regime in [SentimentRegime.HOT_GREED, SentimentRegime.HOT_FEAR]
    
    def should_reduce_size(self) -> bool:
        """Check if position sizes should be reduced."""
        return self.regime in [SentimentRegime.HOT_GREED, SentimentRegime.HOT_FEAR, SentimentRegime.NOISY]


class SentimentRegimeEngine:
    """
    Central governor for swarm sentiment regimes.
    
    Detects regime from FG + sentiment + vol and returns risk caps
    for all BTC 15m agents to follow.
    
    Usage:
        engine = SentimentRegimeEngine()
        regime = engine.detect_regime(fg=75, sent=0.35, vol=0.25)
        caps = engine.get_risk_caps(regime)
        # Apply caps to all agents
    """
    
    # Default risk caps per regime
    REGIME_CAPS: Dict[SentimentRegime, RiskCaps] = {
        SentimentRegime.CALM_NEUTRAL: RiskCaps(
            max_per_trade=0.25,
            max_live_positions=2,
            max_exposure=0.50,
            sentiment_bias_max=0.02,
            allow_new_entries=True,
            late_entry_cutoff=None,
        ),
        SentimentRegime.HOT_GREED: RiskCaps(
            max_per_trade=0.15,
            max_live_positions=1,
            max_exposure=0.30,
            sentiment_bias_max=0.01,
            allow_new_entries=True,
            late_entry_cutoff=8,  # Block entries after 8 bars (2h in 15m)
        ),
        SentimentRegime.HOT_FEAR: RiskCaps(
            max_per_trade=0.15,
            max_live_positions=1,
            max_exposure=0.30,
            sentiment_bias_max=0.01,
            allow_new_entries=True,
            late_entry_cutoff=8,
        ),
        SentimentRegime.NOISY: RiskCaps(
            max_per_trade=0.20,
            max_live_positions=1,
            max_exposure=0.35,
            sentiment_bias_max=0.00,  # No sentiment bias in noisy regime
            allow_new_entries=True,
            late_entry_cutoff=6,
        ),
        SentimentRegime.CONTRARIAN_OPPORTUNITY: RiskCaps(
            max_per_trade=0.25,  # Keep base size for contrarian
            max_live_positions=2,
            max_exposure=0.50,
            sentiment_bias_max=0.02,
            allow_new_entries=True,
            late_entry_cutoff=None,
        ),
    }
    
    def __init__(self):
        self._current_regime: Optional[RegimeState] = None
        self._history: list = []
    
    def detect_regime(
        self,
        fg_index: int,
        sent_combined: float,
        volatility: float,
        sent_history: Optional[list] = None,
    ) -> RegimeState:
        """
        Detect current sentiment regime from inputs.
        
        Args:
            fg_index: Fear/Greed index (0-100)
            sent_combined: Combined social sentiment (-1 to 1)
            volatility: Realized volatility (0-1 scale)
            sent_history: Recent sentiment values to detect noisy regime
        
        Returns:
            RegimeState with detected regime and reasoning
        """
        now = datetime.now(timezone.utc)
        
        # Check for contrarian opportunity first
        is_extreme_fg = fg_index >= 80 or fg_index <= 20
        sent_against_crowd = (fg_index >= 80 and sent_combined < -0.2) or (fg_index <= 20 and sent_combined > 0.2)
        
        if is_extreme_fg and sent_against_crowd:
            regime = SentimentRegime.CONTRARIAN_OPPORTUNITY
            reasoning = f"Contrarian: FG={fg_index} extreme, but sentiment {sent_combined:+.2f} diverges"
        
        # Check for hot greed
        elif fg_index >= 80 and sent_combined > 0.2:
            regime = SentimentRegime.HOT_GREED
            reasoning = f"Euphoria: FG={fg_index} (greed), sentiment {sent_combined:+.2f} bullish"
        
        # Check for hot fear
        elif fg_index <= 20 and sent_combined < -0.2:
            regime = SentimentRegime.HOT_FEAR
            reasoning = f"Panic: FG={fg_index} (fear), sentiment {sent_combined:+.2f} bearish"
        
        # Check for noisy regime (sentiment flipping)
        elif sent_history and len(sent_history) >= 5:
            recent_signs = [1 if s > 0 else -1 for s in sent_history[-5:]]
            sign_changes = sum(1 for i in range(1, len(recent_signs)) if recent_signs[i] != recent_signs[i-1])
            
            if sign_changes >= 2 and abs(sent_combined) < 0.3:
                regime = SentimentRegime.NOISY
                reasoning = f"Noisy: {sign_changes} sign changes in last 5, weak magnitude {abs(sent_combined):.2f}"
            else:
                regime = SentimentRegime.CALM_NEUTRAL
                reasoning = f"Calm: FG={fg_index} neutral, sentiment stable"
        
        # Default to calm neutral
        else:
            regime = SentimentRegime.CALM_NEUTRAL
            reasoning = f"Calm: FG={fg_index} neutral, sentiment {sent_combined:+.2f}"
        
        state = RegimeState(
            regime=regime,
            fg_index=fg_index,
            sent_combined=sent_combined,
            volatility=volatility,
            timestamp=now,
            reasoning=reasoning,
        )
        
        self._current_regime = state
        self._history.append(state)
        
        # Keep last 100 states
        if len(self._history) > 100:
            self._history = self._history[-100:]
        
        logger.info(f"Regime detected: {regime.value} - {reasoning}")
        return state
    
    def get_risk_caps(self, regime: Optional[SentimentRegime] = None) -> RiskCaps:
        """
        Get risk caps for a regime.
        
        Args:
            regime: Regime to get caps for (default: current)
        
        Returns:
            RiskCaps for the regime
        """
        if regime is None:
            regime = self._current_regime.regime if self._current_regime else SentimentRegime.CALM_NEUTRAL
        
        return self.REGIME_CAPS.get(regime, self.REGIME_CAPS[SentimentRegime.CALM_NEUTRAL])
    
    def get_current_caps(self) -> RiskCaps:
        """Get risk caps for current regime."""
        return self.get_risk_caps()
    
    def can_enter_position(self, bar_count: int = 0) -> Tuple[bool, str]:
        """
        Check if new entries are allowed.
        
        Args:
            bar_count: Current bar count in 15m cycle
        
        Returns:
            (allowed, reason) tuple
        """
        if self._current_regime is None:
            return True, "no regime data"
        
        caps = self.get_risk_caps()
        
        if not caps.allow_new_entries:
            return False, "new entries blocked by regime"
        
        if caps.late_entry_cutoff and bar_count >= caps.late_entry_cutoff:
            return False, f"late entry cutoff (bar {bar_count} >= {caps.late_entry_cutoff})"
        
        return True, "entry allowed"
    
    def get_sentiment_bias_limit(self) -> float:
        """Get max sentiment bias allowed in current regime."""
        caps = self.get_risk_caps()
        return caps.sentiment_bias_max
    
    def get_status(self) -> Dict[str, Any]:
        """Get current engine status."""
        if self._current_regime is None:
            return {"error": "No regime detected yet"}
        
        caps = self.get_risk_caps()
        
        return {
            "regime": self._current_regime.regime.value,
            "fg_index": self._current_regime.fg_index,
            "sent_combined": self._current_regime.sent_combined,
            "volatility": self._current_regime.volatility,
            "reasoning": self._current_regime.reasoning,
            "timestamp": self._current_regime.timestamp.isoformat(),
            "risk_caps": {
                "max_per_trade": caps.max_per_trade,
                "max_live_positions": caps.max_live_positions,
                "max_exposure": caps.max_exposure,
                "sentiment_bias_max": caps.sentiment_bias_max,
                "allow_new_entries": caps.allow_new_entries,
                "late_entry_cutoff": caps.late_entry_cutoff,
            },
        }


# Singleton accessor
_engine: Optional[SentimentRegimeEngine] = None

def get_sentiment_regime_engine() -> SentimentRegimeEngine:
    """Get the singleton SentimentRegimeEngine instance."""
    global _engine
    if _engine is None:
        _engine = SentimentRegimeEngine()
    return _engine


# ── Convenience functions ──────────────────────────────────────────

def quick_regime_check(fg: int, sent: float, vol: float = 0.2) -> str:
    """Quick one-liner to get regime name."""
    engine = get_sentiment_regime_engine()
    state = engine.detect_regime(fg, sent, vol)
    return state.regime.value


def get_current_risk_caps() -> Dict[str, Any]:
    """Get current risk caps as dict."""
    engine = get_sentiment_regime_engine()
    caps = engine.get_current_caps()
    return {
        "max_per_trade": caps.max_per_trade,
        "max_live_positions": caps.max_live_positions,
        "max_exposure": caps.max_exposure,
        "sentiment_bias_max": caps.sentiment_bias_max,
    }

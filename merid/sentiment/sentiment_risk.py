"""
Sentiment-aware risk rules for Kalshi trading.

Enhanced risk management for sentiment-based trading strategies,
including position sizing, gating, and cooldown rules.
"""

from dataclasses import dataclass
from typing import Optional, Tuple, Dict, Any
from datetime import datetime, timedelta, timezone
import logging

logger = logging.getLogger(__name__)


@dataclass
class SentimentRiskConfig:
    """Configuration for sentiment risk rules."""
    # Per-trade caps
    max_trade_pct: float = 0.03  # Max 3% of equity per trade
    
    # Daily loss caps
    hard_stop_pct: float = 0.10  # Hard stop at -10%
    soft_stop_pct: float = 0.05  # Soft stop at -5% (halve size)
    
    # Sentiment gating
    min_sentiment_confidence: float = 0.5
    require_tech_agreement: bool = True
    
    # FG/extreme adjustments
    extreme_fg_reduce_mult: float = 0.5  # Reduce 50% in extreme FG
    
    # Cooldown
    min_sentiment_change: float = 0.2  # Min change to act again
    cooldown_bars: int = 3  # Bars to wait after spike
    
    # Volatility spike detection
    vol_spike_std_mult: float = 2.0  # X standard deviations
    vol_spike_window: int = 20  # Lookback window


class SentimentRiskManager:
    """
    Risk manager for sentiment-based Kalshi trading.
    
    Implements:
    - Position sizing with FG/sentiment adjustments
    - Daily loss caps with soft/hard stops
    - Sentiment gating (confidence + tech agreement)
    - Cooldown after volatility spikes
    - Turnover limits
    """
    
    def __init__(self, config: Optional[SentimentRiskConfig] = None):
        self.config = config or SentimentRiskConfig()
        self.daily_pnl: float = 0.0
        self.last_sentiment: float = 0.0
        self.last_trade_time: Optional[datetime] = None
        self.cooldown_until: Optional[datetime] = None
        self.equity: float = 10000.0  # Starting equity
        
    def calculate_position_size(
        self,
        base_size: float,
        fg_index: int,
        sentiment: float,
        confidence: float,
        sentiment_agrees_with_crowd: bool = False,
    ) -> Tuple[float, str]:
        """
        Calculate position size with risk adjustments.
        
        Returns:
            (adjusted_size, reasoning) tuple
        """
        size = base_size
        reasons = []
        
        # 1. Apply max trade cap
        max_dollar = self.equity * self.config.max_trade_pct
        if size > max_dollar:
            size = max_dollar
            reasons.append(f"capped at {self.config.max_trade_pct:.0%}")
        
        # 2. Reduce in extreme FG when going with crowd
        if fg_index >= 80 or fg_index <= 20:
            if sentiment_agrees_with_crowd:
                size *= self.config.extreme_fg_reduce_mult
                reasons.append(f"extreme_fg_reduce ({self.config.extreme_fg_reduce_mult:.0%})")
        
        # 3. Scale by confidence
        if confidence < self.config.min_sentiment_confidence:
            size *= confidence
            reasons.append(f"low_conf_scale ({confidence:.0%})")
        
        # 4. Check daily loss limits
        if self.daily_pnl <= -self.equity * self.config.hard_stop_pct:
            size = 0
            reasons.append("HARD_STOP")
        elif self.daily_pnl <= -self.equity * self.config.soft_stop_pct:
            size *= 0.5
            reasons.append("soft_stop (50%)")
        
        reasoning = ", ".join(reasons) if reasons else "base_size"
        return size, reasoning
    
    def check_sentiment_gating(
        self,
        sentiment_confidence: float,
        tech_signal: str,
        sent_signal: str,
    ) -> Tuple[bool, str]:
        """
        Check if sentiment passes gating criteria.
        
        Returns:
            (allowed, reason) tuple
        """
        # Confidence check
        if sentiment_confidence < self.config.min_sentiment_confidence:
            return False, f"confidence {sentiment_confidence:.2f} < {self.config.min_sentiment_confidence}"
        
        # Tech agreement check
        if self.config.require_tech_agreement:
            tech_bullish = tech_signal in ["bullish", "strong_bullish"]
            tech_bearish = tech_signal in ["bearish", "strong_bearish"]
            sent_bullish = sent_signal in ["bullish", "strong_bullish"]
            sent_bearish = sent_signal in ["bearish", "strong_bearish"]
            
            # Require alignment
            if (tech_bullish and sent_bearish) or (tech_bearish and sent_bullish):
                return False, "tech/sentiment disagreement"
        
        return True, "passed"
    
    def check_cooldown(
        self,
        current_sentiment: float,
        current_time: datetime,
        vol_spike_detected: bool = False,
    ) -> Tuple[bool, str]:
        """
        Check if trading is in cooldown.
        
        Returns:
            (allowed, reason) tuple
        """
        # Global cooldown (after vol spike)
        if self.cooldown_until and current_time < self.cooldown_until:
            remaining = (self.cooldown_until - current_time).seconds
            return False, f"cooldown {remaining}s remaining"
        
        # Sentiment change check
        if self.last_trade_time:
            sentiment_change = abs(current_sentiment - self.last_sentiment)
            if sentiment_change < self.config.min_sentiment_change:
                return False, f"sentiment_change {sentiment_change:.2f} < {self.config.min_sentiment_change}"
        
        # Vol spike detected
        if vol_spike_detected:
            self.cooldown_until = current_time + timedelta(minutes=5)
            return False, "vol_spike_detected - cooldown 5min"
        
        return True, "passed"
    
    def detect_volatility_spike(
        self,
        recent_returns: list,
        current_return: float,
    ) -> bool:
        """
        Detect if current return represents a volatility spike.
        
        Args:
            recent_returns: List of recent returns
            current_return: Current period return
        
        Returns:
            True if spike detected
        """
        if len(recent_returns) < self.config.vol_spike_window:
            return False
        
        import numpy as np
        mean = np.mean(recent_returns)
        std = np.std(recent_returns)
        
        if std == 0:
            return False
        
        z_score = abs(current_return - mean) / std
        return z_score > self.config.vol_spike_std_mult
    
    def record_trade(
        self,
        pnl: float,
        sentiment: float,
        timestamp: datetime,
    ):
        """Record trade result for tracking."""
        self.daily_pnl += pnl
        self.last_sentiment = sentiment
        self.last_trade_time = timestamp
        self.equity += pnl
    
    def reset_daily(self):
        """Reset daily tracking (call at start of trading day)."""
        self.daily_pnl = 0.0
        self.cooldown_until = None
    
    def get_status(self) -> Dict[str, Any]:
        """Get current risk manager status."""
        return {
            "equity": self.equity,
            "daily_pnl": self.daily_pnl,
            "daily_pnl_pct": self.daily_pnl / self.equity if self.equity > 0 else 0,
            "hard_stop_triggered": self.daily_pnl <= -self.equity * self.config.hard_stop_pct,
            "soft_stop_triggered": self.daily_pnl <= -self.equity * self.config.soft_stop_pct,
            "in_cooldown": self.cooldown_until is not None and datetime.now(timezone.utc) < self.cooldown_until,
            "last_sentiment": self.last_sentiment,
        }


# ── Convenience functions ──────────────────────────────────────────

def check_sentiment_trade_allowed(
    equity: float,
    daily_pnl: float,
    sentiment_confidence: float,
    tech_signal: str,
    sent_signal: str,
    fg_index: int,
    sentiment: float,
) -> Tuple[bool, float, str]:
    """
    Quick check if sentiment trade is allowed.
    
    Returns:
        (allowed, size, reason) tuple
    """
    config = SentimentRiskConfig()
    manager = SentimentRiskManager(config)
    manager.equity = equity
    manager.daily_pnl = daily_pnl
    
    # Check gating
    allowed, reason = manager.check_sentiment_gating(
        sentiment_confidence, tech_signal, sent_signal
    )
    if not allowed:
        return False, 0.0, reason
    
    # Check daily stops
    if daily_pnl <= -equity * config.hard_stop_pct:
        return False, 0.0, "hard_stop"
    
    # Calculate size
    base_size = equity * config.max_trade_pct
    sentiment_agrees = (fg_index >= 80 and sentiment > 0) or (fg_index <= 20 and sentiment < 0)
    
    size, reasoning = manager.calculate_position_size(
        base_size, fg_index, sentiment, sentiment_confidence, sentiment_agrees
    )
    
    return True, size, reasoning

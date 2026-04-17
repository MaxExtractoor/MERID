"""
Tech + Sentiment Combined Signal Generator

Combines technical indicators (RSI, SMA) with sentiment signals
for Kalshi trading decisions.
"""

import numpy as np
import pandas as pd
from typing import List, Optional, Tuple, Dict, Any
from dataclasses import dataclass
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class TechSentSignal:
    """Combined technical and sentiment signal."""
    # Technical
    rsi: float
    above_sma: bool
    tech_signal: str  # bullish, bearish, neutral
    
    # Sentiment
    sentiment: float
    sentiment_signal: str
    sentiment_confidence: float
    
    # Combined
    combined_signal: str  # bullish, bearish, neutral, strong_bullish, strong_bearish
    confidence: float
    reasoning: str


def generate_tech_sent_signal(
    price: float,
    rsi_val: float,
    sma_val: float,
    sentiment: float,
    sentiment_confidence: float = 0.5,
    pos_th: float = 0.2,
    neg_th: float = -0.2,
    rsi_low: float = 30,
    rsi_high: float = 70,
) -> TechSentSignal:
    """
    Generate combined technical + sentiment signal.
    
    Signal logic:
    - Long when sentiment positive AND price above SMA AND RSI in mid-range
    - Short when sentiment negative AND price below SMA AND RSI in mid-range
    - Require agreement between tech and sentiment
    
    Args:
        price: Current price
        rsi_val: RSI value (0-100)
        sma_val: SMA value
        sentiment: Sentiment score (-1 to 1)
        sentiment_confidence: Confidence in sentiment (0-1)
        pos_th: Positive sentiment threshold
        neg_th: Negative sentiment threshold
        rsi_low: RSI oversold threshold
        rsi_high: RSI overbought threshold
    
    Returns:
        TechSentSignal with combined analysis
    """
    # Technical signal
    above_sma = price > sma_val
    
    if above_sma and rsi_low < rsi_val < rsi_high:
        tech_signal = "bullish"
    elif not above_sma and rsi_low < rsi_val < rsi_high:
        tech_signal = "bearish"
    else:
        tech_signal = "neutral"
    
    # Sentiment signal
    if sentiment >= pos_th:
        sent_signal = "bullish"
    elif sentiment <= neg_th:
        sent_signal = "bearish"
    else:
        sent_signal = "neutral"
    
    # Combined signal - require agreement
    if tech_signal == "bullish" and sent_signal == "bullish":
        combined = "strong_bullish"
        confidence = 0.7 + 0.3 * sentiment_confidence
        reason = f"Tech&Sent aligned bullish (RSI={rsi_val:.1f}, Above SMA, Sent={sentiment:+.2f})"
    elif tech_signal == "bearish" and sent_signal == "bearish":
        combined = "strong_bearish"
        confidence = 0.7 + 0.3 * sentiment_confidence
        reason = f"Tech&Sent aligned bearish (RSI={rsi_val:.1f}, Below SMA, Sent={sentiment:+.2f})"
    elif sent_signal == "bullish" and tech_signal != "bearish":
        combined = "bullish"
        confidence = 0.5 + 0.3 * sentiment_confidence
        reason = f"Sentiment bullish (RSI={rsi_val:.1f}, Sent={sentiment:+.2f})"
    elif sent_signal == "bearish" and tech_signal != "bullish":
        combined = "bearish"
        confidence = 0.5 + 0.3 * sentiment_confidence
        reason = f"Sentiment bearish (RSI={rsi_val:.1f}, Sent={sentiment:+.2f})"
    else:
        combined = "neutral"
        confidence = 0.3
        reason = f"Mixed signals (RSI={rsi_val:.1f}, Tech={tech_signal}, Sent={sentiment:+.2f})"
    
    return TechSentSignal(
        rsi=rsi_val,
        above_sma=above_sma,
        tech_signal=tech_signal,
        sentiment=sentiment,
        sentiment_signal=sent_signal,
        sentiment_confidence=sentiment_confidence,
        combined_signal=combined,
        confidence=confidence,
        reasoning=reason,
    )


def tech_sent_signal_series(
    prices: pd.Series,
    rsi_series: pd.Series,
    sma_series: pd.Series,
    sentiment_series: pd.Series,
    sentiment_confidence: pd.Series,
    pos_th: float = 0.2,
    neg_th: float = -0.2,
    rsi_low: float = 30,
    rsi_high: float = 70,
) -> pd.DataFrame:
    """
    Generate combined signals for a full series.
    
    Returns DataFrame with all signal columns.
    """
    signals = []
    
    for i in range(len(prices)):
        signal = generate_tech_sent_signal(
            price=prices.iloc[i],
            rsi_val=rsi_series.iloc[i],
            sma_val=sma_series.iloc[i],
            sentiment=sentiment_series.iloc[i],
            sentiment_confidence=sentiment_confidence.iloc[i] if i < len(sentiment_confidence) else 0.5,
            pos_th=pos_th,
            neg_th=neg_th,
            rsi_low=rsi_low,
            rsi_high=rsi_high,
        )
        
        signals.append({
            "rsi": signal.rsi,
            "above_sma": signal.above_sma,
            "tech_signal": signal.tech_signal,
            "sentiment": signal.sentiment,
            "sentiment_signal": signal.sentiment_signal,
            "combined_signal": signal.combined_signal,
            "confidence": signal.confidence,
        })
    
    return pd.DataFrame(signals, index=prices.index)


def signal_to_position(signal: str) -> int:
    """Convert signal to position (-1, 0, 1)."""
    return {
        "strong_bullish": 1,
        "bullish": 1,
        "neutral": 0,
        "bearish": -1,
        "strong_bearish": -1,
    }.get(signal, 0)


# ── Convenience functions ──────────────────────────────────────────

def quick_tech_sent_check(
    price: float,
    prices_history: List[float],
    sentiment: float,
) -> Tuple[str, float]:
    """
    Quick combined signal check.
    
    Returns (signal, confidence) tuple.
    """
    from merid.sentiment.technical_indicators import quick_rsi, quick_sma
    
    rsi_val = quick_rsi(prices_history)
    sma_val = quick_sma(prices_history)
    
    result = generate_tech_sent_signal(
        price=price,
        rsi_val=rsi_val,
        sma_val=sma_val,
        sentiment=sentiment,
    )
    
    return result.combined_signal, result.confidence

"""
MERID Signals Module
====================

Technical analysis indicators and signal generation for trading strategies.

This module provides:
- Crypto15mIndicatorStack: Comprehensive indicator stack for 15-minute Kalshi crypto binaries
- TAEngine: Core engine for computing RSI, MACD, EMAs, ATR, and divergence detection
- TA Models: Data models for OHLCV snapshots, indicator bundles, and market structure

Usage:
    from merid.signals.crypto_15m_indicators import Crypto15mIndicatorStack, IndicatorConfig
    
    # Initialize with asset-specific config
    stack = Crypto15mIndicatorStack(config=IndicatorConfig(asset="BTC"))
    
    # Feed 1-minute close prices
    stack.update(price=87450.0)
    
    # Get indicator snapshot
    snap = stack.snapshot()
    if snap.trade_allowed:
        # Use indicators for edge computation
        pass
"""

from merid.signals.crypto_15m_indicators import (
    Crypto15mIndicatorStack,
    IndicatorConfig,
    IndicatorSnapshot,
    FVGZone,
    FVGContext,
    DEFAULT_15M_CONFIG,
)

from merid.signals.ta_engine import (
    TAEngine,
    IndicatorConfig as TAIndicatorConfig,
)

from merid.signals.ta_models import (
    OHLCVSnapshot,
    PricePivot,
    Divergence,
    FibPivots,
    IndicatorBundle,
    MarketStructure,
    SignalScore,
    FusedClusterSignal,
    GlobalRegime,
)

__all__ = [
    # Crypto 15m indicators
    "Crypto15mIndicatorStack",
    "IndicatorConfig",
    "IndicatorSnapshot",
    "FVGZone",
    "FVGContext",
    "DEFAULT_15M_CONFIG",
    # TA Engine
    "TAEngine",
    "TAIndicatorConfig",
    # TA Models
    "OHLCVSnapshot",
    "PricePivot",
    "Divergence",
    "FibPivots",
    "IndicatorBundle",
    "MarketStructure",
    "SignalScore",
    "FusedClusterSignal",
    "GlobalRegime",
]

"""
Crypto Asset Registry — Centralized configuration for BTC, ETH, SOL, XRP, DOGE
================================================================================

Single source of truth for:
- Asset metadata (symbol, name, CoinGecko ID)
- Kalshi market mappings (ticker prefixes, supported timeframes)
- Indicator configurations (per-asset overrides for FVG, vol thresholds, etc.)
- Risk parameters (exposure caps, Kelly fractions, term structure buckets)
- Spot price fallback mappings (Coinbase, Binance)

Usage:
    from merid.sentiment.crypto_registry import get_asset_config, FVGConfig
    
    btc_cfg = get_asset_config("BTC")
    print(btc_cfg.fvg_config.min_gap_size_atr)  # 1.5
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from enum import Enum


class Timeframe(str, Enum):
    """Supported timeframes for technical analysis."""
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    H4 = "4h"
    D1 = "1d"
    W1 = "1w"


@dataclass
class FVGConfig:
    """Fair Value Gap detection parameters per asset/timeframe."""
    
    # Enable/disable FVG for this asset
    enabled: bool = True
    
    # Minimum gap size in ATR units to qualify as FVG
    min_gap_size_atr: float = 1.5
    
    # Minimum gap size as % of price (alternative to ATR)
    min_gap_size_pct: float = 0.002  # 0.2%
    
    # Maximum age (in bars) before an unfilled FVG is considered stale
    max_age_bars: int = 50
    
    # Maximum number of active zones to track per asset
    max_zones_tracked: int = 10
    
    # Timeframes where FVG is active for this asset
    active_timeframes: List[str] = field(default_factory=lambda: ["15m", "1h", "4h"])
    
    # Weight for fvg_pressure calculation (higher = more influence on signals)
    pressure_weight: float = 0.3
    
    # Minimum distance from current price to consider zone "relevant" (in ATR)
    relevance_distance_atr: float = 3.0
    
    # Whether to ignore gaps immediately filled by next candle
    ignore_immediate_fill: bool = True
    
    def __post_init__(self):
        # Validate timeframe strings
        valid_tfs = {tf.value for tf in Timeframe}
        for tf in self.active_timeframes:
            if tf not in valid_tfs:
                raise ValueError(f"Invalid timeframe: {tf}. Must be one of {valid_tfs}")


@dataclass
class IndicatorOverrides:
    """Per-asset indicator stack overrides."""
    
    # Volatility thresholds (annualized)
    vol_low_threshold: Optional[float] = None
    vol_high_threshold: Optional[float] = None
    
    # ATR minimum move gate
    atr_min_move_pct: Optional[float] = None
    
    # RSI thresholds (can override default 30/70)
    rsi_oversold: Optional[float] = None
    rsi_overbought: Optional[float] = None
    
    # EMA periods (can override defaults)
    ema_trend_period: Optional[int] = None
    ema_fast_period: Optional[int] = None
    ema_slow_period: Optional[int] = None
    
    # MACD periods
    macd_fast: Optional[int] = None
    macd_slow: Optional[int] = None
    macd_signal: Optional[int] = None
    
    # Consecutive closes required for trend confirmation
    consecutive_closes_required: Optional[int] = None
    
    # Distance from EMA overextension threshold (ATR units)
    distance_overextended_atrs: Optional[float] = None


@dataclass
class RiskConfig:
    """Per-asset risk and sizing parameters."""
    
    # Maximum exposure as % of total bankroll
    max_exposure_pct: float = 0.15
    
    # Base Kelly fraction (0.25 = quarter-Kelly)
    kelly_fraction: float = 0.25
    
    # Maximum Kelly cap (absolute)
    max_kelly_cap: float = 0.35
    
    # Per-trade risk limit
    max_risk_per_trade_pct: float = 0.02
    
    # Drawdown thresholds
    drawdown_halt_pct: float = 0.20
    drawdown_reduce_pct: float = 0.10
    
    # Term structure bucket assignment
    term_structure_bucket: str = "major"  # major (BTC/ETH), mid (SOL), minor (XRP/DOGE)
    
    # Correlation grouping for exposure stacking
    correlation_group: str = "crypto"


@dataclass
class CalibrationConfig:
    """Per-asset calibration parameters for 80%+ decision hit-rate targeting."""
    
    # Probability edge thresholds (|p - 0.5| must exceed this)
    min_prob_edge_low_tf: float = 0.15  # For short-term markets (15m, 1h)
    min_prob_edge_high_tf: float = 0.12  # For longer-term (4h, daily)
    
    # Conviction floor thresholds
    conviction_veto_threshold: float = 0.4  # Below this: absolute NO_ACTION
    conviction_strict_threshold: float = 0.6  # Below this: requires higher prob edge
    
    # Probability edge boost required when conviction is borderline
    prob_edge_boost_for_low_conviction: float = 0.10  # Add to min_prob_edge
    
    # Hit-rate targets per conviction bucket
    target_hit_rate_low: float = 0.60  # For 0.4-0.6 bucket
    target_hit_rate_mid: float = 0.70  # For 0.6-0.8 bucket
    target_hit_rate_high: float = 0.80  # For 0.8-1.0 bucket
    
    # Auto-tightening parameters
    auto_tighten_enabled: bool = True
    min_trades_for_tightening: int = 20  # Min sample size before adjusting
    tighten_delta: float = 0.02  # How much to increase threshold on underperform
    max_prob_edge: float = 0.35  # Hard ceiling to prevent over-tightening


@dataclass
class AssetConfig:
    """Complete configuration for a single crypto asset."""
    
    # Identity
    symbol: str
    name: str
    coingecko_id: str
    
    # Kalshi market identification
    kalshi_ticker_prefix: str  # e.g., "KXBTC"
    kalshi_event_prefix: str   # e.g., "CRYPTO_BTC"
    
    # Supported Kalshi timeframes
    supported_timeframes: List[str] = field(default_factory=list)
    
    # Spot price fallbacks
    coinbase_symbol: str = ""
    binance_symbol: str = ""  # e.g., "BTCUSDT"
    
    # Config sections
    fvg_config: FVGConfig = field(default_factory=FVGConfig)
    indicator_overrides: IndicatorOverrides = field(default_factory=IndicatorOverrides)
    risk_config: RiskConfig = field(default_factory=RiskConfig)
    calibration_config: CalibrationConfig = field(default_factory=CalibrationConfig)
    
    def __post_init__(self):
        # Set defaults if empty
        if not self.coinbase_symbol:
            self.coinbase_symbol = self.symbol
        if not self.binance_symbol:
            self.binance_symbol = f"{self.symbol}USDT"


# =============================================================================
# Default Configurations for All 5 Assets
# =============================================================================

_DEFAULT_ASSET_CONFIGS: Dict[str, AssetConfig] = {
    "BTC": AssetConfig(
        symbol="BTC",
        name="Bitcoin",
        coingecko_id="bitcoin",
        kalshi_ticker_prefix="KXBTC",
        kalshi_event_prefix="CRYPTO_BTC",
        supported_timeframes=["15m", "1h", "daily", "weekly", "monthly"],
        coinbase_symbol="BTC",
        binance_symbol="BTCUSDT",
        fvg_config=FVGConfig(
            enabled=True,
            min_gap_size_atr=1.5,
            min_gap_size_pct=0.0015,  # 0.15% for BTC (tighter)
            max_age_bars=60,
            max_zones_tracked=12,
            active_timeframes=["15m", "1h", "4h", "1d"],
            pressure_weight=0.35,
            relevance_distance_atr=2.5,
            ignore_immediate_fill=True,
        ),
        indicator_overrides=IndicatorOverrides(
            vol_low_threshold=0.40,
            vol_high_threshold=0.80,
            atr_min_move_pct=0.0003,
        ),
        risk_config=RiskConfig(
            max_exposure_pct=0.20,
            kelly_fraction=0.25,
            term_structure_bucket="major",
        ),
        calibration_config=CalibrationConfig(
            min_prob_edge_low_tf=0.15,  # BTC: tighter edge for major asset
            min_prob_edge_high_tf=0.12,
            conviction_veto_threshold=0.4,
            conviction_strict_threshold=0.6,
            target_hit_rate_high=0.80,
        ),
    ),
    
    "ETH": AssetConfig(
        symbol="ETH",
        name="Ethereum",
        coingecko_id="ethereum",
        kalshi_ticker_prefix="KXETH",
        kalshi_event_prefix="CRYPTO_ETH",
        supported_timeframes=["15m", "1h", "daily", "weekly", "monthly", "annual"],
        coinbase_symbol="ETH",
        binance_symbol="ETHUSDT",
        fvg_config=FVGConfig(
            enabled=True,
            min_gap_size_atr=1.5,
            min_gap_size_pct=0.0018,
            max_age_bars=55,
            max_zones_tracked=10,
            active_timeframes=["15m", "1h", "4h", "1d"],
            pressure_weight=0.35,
            relevance_distance_atr=2.8,
            ignore_immediate_fill=True,
        ),
        indicator_overrides=IndicatorOverrides(
            vol_low_threshold=0.45,
            vol_high_threshold=0.90,
            atr_min_move_pct=0.0003,
        ),
        risk_config=RiskConfig(
            max_exposure_pct=0.15,
            kelly_fraction=0.25,
            term_structure_bucket="major",
        ),
        calibration_config=CalibrationConfig(
            min_prob_edge_low_tf=0.15,  # ETH: same as BTC
            min_prob_edge_high_tf=0.12,
            conviction_veto_threshold=0.4,
            conviction_strict_threshold=0.6,
            target_hit_rate_high=0.80,
        ),
    ),
    
    "SOL": AssetConfig(
        symbol="SOL",
        name="Solana",
        coingecko_id="solana",
        kalshi_ticker_prefix="KXSOL",
        kalshi_event_prefix="CRYPTO_SOL",
        supported_timeframes=["15m", "1h", "daily", "weekly", "monthly", "annual"],
        coinbase_symbol="SOL",
        binance_symbol="SOLUSDT",
        fvg_config=FVGConfig(
            enabled=True,
            min_gap_size_atr=1.8,  # Wider for SOL's higher vol
            min_gap_size_pct=0.0025,
            max_age_bars=45,
            max_zones_tracked=8,
            active_timeframes=["15m", "1h", "4h"],  # Skip daily (less liquid)
            pressure_weight=0.30,
            relevance_distance_atr=3.0,
            ignore_immediate_fill=True,
        ),
        indicator_overrides=IndicatorOverrides(
            vol_low_threshold=0.20,
            vol_high_threshold=1.50,
            atr_min_move_pct=0.0004,
            consecutive_closes_required=4,  # More confirmation for alt volatility
        ),
        risk_config=RiskConfig(
            max_exposure_pct=0.10,
            kelly_fraction=0.20,  # Lower Kelly for higher vol asset
            term_structure_bucket="mid",
        ),
        calibration_config=CalibrationConfig(
            min_prob_edge_low_tf=0.18,  # SOL: wider edge for higher vol
            min_prob_edge_high_tf=0.15,
            conviction_veto_threshold=0.45,  # Higher floor for alt
            conviction_strict_threshold=0.65,
            target_hit_rate_high=0.75,
        ),
    ),
    
    "XRP": AssetConfig(
        symbol="XRP",
        name="XRP",
        coingecko_id="ripple",
        kalshi_ticker_prefix="KXXRP",
        kalshi_event_prefix="CRYPTO_XRP",
        supported_timeframes=["15m", "1h", "daily", "weekly", "monthly", "annual"],
        coinbase_symbol="XRP",
        binance_symbol="XRPUSDT",
        fvg_config=FVGConfig(
            enabled=True,
            min_gap_size_atr=2.0,  # Even wider for XRP's noise
            min_gap_size_pct=0.0030,
            max_age_bars=40,
            max_zones_tracked=6,  # Fewer zones (more noise)
            active_timeframes=["15m", "1h"],  # Focus on short-term
            pressure_weight=0.25,  # Lower weight (less reliable)
            relevance_distance_atr=3.5,
            ignore_immediate_fill=True,
        ),
        indicator_overrides=IndicatorOverrides(
            vol_low_threshold=0.25,
            vol_high_threshold=1.80,
            atr_min_move_pct=0.0008,
            consecutive_closes_required=4,
            distance_overextended_atrs=2.5,  # Wider overextension threshold
        ),
        risk_config=RiskConfig(
            max_exposure_pct=0.10,
            kelly_fraction=0.15,  # Conservative Kelly
            term_structure_bucket="minor",
        ),
        calibration_config=CalibrationConfig(
            min_prob_edge_low_tf=0.20,  # XRP: widest edge for noisy asset
            min_prob_edge_high_tf=0.18,
            conviction_veto_threshold=0.50,  # Higher floor
            conviction_strict_threshold=0.70,
            target_hit_rate_high=0.70,
        ),
    ),
    
    "DOGE": AssetConfig(
        symbol="DOGE",
        name="Dogecoin",
        coingecko_id="dogecoin",
        kalshi_ticker_prefix="KXDOGE",
        kalshi_event_prefix="CRYPTO_DOGE",
        supported_timeframes=["15m", "1h", "daily", "weekly", "monthly", "annual"],
        coinbase_symbol="DOGE",
        binance_symbol="DOGEUSDT",
        fvg_config=FVGConfig(
            enabled=True,
            min_gap_size_atr=2.2,  # Widest for DOGE's meme volatility
            min_gap_size_pct=0.0035,
            max_age_bars=35,
            max_zones_tracked=5,  # Very few zones (high noise)
            active_timeframes=["15m", "1h"],  # Only short-term
            pressure_weight=0.20,  # Lowest weight
            relevance_distance_atr=4.0,
            ignore_immediate_fill=True,
        ),
        indicator_overrides=IndicatorOverrides(
            vol_low_threshold=0.30,
            vol_high_threshold=2.00,
            atr_min_move_pct=0.0010,
            consecutive_closes_required=5,  # High confirmation needed
            distance_overextended_atrs=3.0,
            rsi_oversold=25,  # Adjusted for DOGE's extreme moves
            rsi_overbought=75,
        ),
        risk_config=RiskConfig(
            max_exposure_pct=0.10,
            kelly_fraction=0.12,  # Most conservative
            term_structure_bucket="minor",
        ),
        calibration_config=CalibrationConfig(
            min_prob_edge_low_tf=0.20,  # DOGE: widest edge for meme vol
            min_prob_edge_high_tf=0.18,
            conviction_veto_threshold=0.50,  # Highest floor
            conviction_strict_threshold=0.70,
            target_hit_rate_high=0.70,
        ),
    ),
}


# =============================================================================
# Registry API
# =============================================================================

class CryptoAssetRegistry:
    """Central registry for all crypto asset configurations."""
    
    def __init__(self):
        self._configs: Dict[str, AssetConfig] = {}
        self._load_defaults()
    
    def _load_defaults(self) -> None:
        """Load default configurations."""
        for symbol, config in _DEFAULT_ASSET_CONFIGS.items():
            self._configs[symbol] = config
    
    def get_config(self, symbol: str) -> Optional[AssetConfig]:
        """Get configuration for a specific asset."""
        return self._configs.get(symbol.upper())
    
    def get_all_configs(self) -> Dict[str, AssetConfig]:
        """Get all asset configurations."""
        return self._configs.copy()
    
    def get_supported_assets(self) -> List[str]:
        """Get list of all supported asset symbols."""
        return list(self._configs.keys())
    
    def get_fvg_config(self, symbol: str) -> Optional[FVGConfig]:
        """Get FVG configuration for an asset."""
        config = self._configs.get(symbol.upper())
        return config.fvg_config if config else None
    
    def get_indicator_overrides(self, symbol: str) -> Optional[IndicatorOverrides]:
        """Get indicator overrides for an asset."""
        config = self._configs.get(symbol.upper())
        return config.indicator_overrides if config else None
    
    def get_risk_config(self, symbol: str) -> Optional[RiskConfig]:
        """Get risk configuration for an asset."""
        config = self._configs.get(symbol.upper())
        return config.risk_config if config else None
    
    def get_calibration_config(self, symbol: str) -> Optional[CalibrationConfig]:
        """Get calibration configuration for an asset."""
        config = self._configs.get(symbol.upper())
        return config.calibration_config if config else None
    
    def is_fvg_enabled(self, symbol: str, timeframe: str) -> bool:
        """Check if FVG is enabled for asset/timeframe combination."""
        config = self._configs.get(symbol.upper())
        if not config:
            return False
        return (
            config.fvg_config.enabled 
            and timeframe in config.fvg_config.active_timeframes
        )
    
    def update_config(self, symbol: str, config: AssetConfig) -> None:
        """Update configuration for an asset (runtime override)."""
        self._configs[symbol.upper()] = config
    
    def get_kalshi_series_tickers(self, symbol: str) -> List[str]:
        """Generate expected Kalshi series tickers for an asset."""
        config = self._configs.get(symbol.upper())
        if not config:
            return []
        
        series_tickers = []
        timeframe_suffixes = {
            "15m": "-15M",
            "1h": "",  # Hourly is default/no suffix
            "daily": "-D1",
            "weekly": "-W1",
            "monthly": "-1M",
            "annual": "-Y",
        }
        
        for tf in config.supported_timeframes:
            suffix = timeframe_suffixes.get(tf, f"-{tf.upper()}")
            series_tickers.append(f"{config.kalshi_ticker_prefix}{suffix}")
        
        return series_tickers
    
    def get_by_coingecko_id(self, coingecko_id: str) -> Optional[AssetConfig]:
        """Find asset config by CoinGecko ID."""
        for config in self._configs.values():
            if config.coingecko_id == coingecko_id:
                return config
        return None
    
    def get_by_kalshi_prefix(self, prefix: str) -> Optional[AssetConfig]:
        """Find asset config by Kalshi ticker prefix."""
        for config in self._configs.values():
            if config.kalshi_ticker_prefix == prefix.upper():
                return config
        return None
    
    def compute_structural_conviction(
        self,
        symbol: str,
        fvg_pressure: float,
        fvg_confluence: bool,
        trend_aligned: bool,
        sentiment_regime: str,
        nearest_fvg_distance_atr: float,
    ) -> Dict[str, any]:
        """Compute structural conviction score (0-1) for position sizing.
        
        Combines FVG, trend alignment, sentiment regime, and proximity into
        a single scalar for multiplicative position sizing.
        
        Returns dict with:
        - conviction: float (0.0-1.0)
        - fvg_component: float (contribution from FVG)
        - trend_component: float (contribution from trend)
        - sentiment_component: float (contribution from sentiment)
        - proximity_component: float (contribution from zone proximity)
        - raw_drivers: dict (all inputs for logging)
        """
        config = self._configs.get(symbol.upper())
        if not config:
            return {
                "conviction": 0.5,
                "fvg_component": 0.0,
                "trend_component": 0.0,
                "sentiment_component": 0.0,
                "proximity_component": 0.0,
                "raw_drivers": {},
            }
        
        # FVG component: pressure magnitude + confluence bonus
        fvg_mag = abs(fvg_pressure)
        fvg_component = min(1.0, fvg_mag * (1.5 if fvg_confluence else 1.0))
        
        # Trend component: aligned = full, neutral = half, misaligned = zero
        trend_component = 1.0 if trend_aligned else 0.3
        
        # Sentiment component: favorable regimes boost, hostile reduce
        hostile_regimes = ["hot_fear", "hot_greed", "turbulent"]
        if sentiment_regime in hostile_regimes:
            sentiment_component = 0.4  # Reduce in extreme regimes
        elif sentiment_regime in ["calm_neutral", "calm"]:
            sentiment_component = 1.0  # Full in calm
        else:
            sentiment_component = 0.7  # Moderate in other regimes
        
        # Proximity component: closer to zone = higher conviction
        # Inverse relationship: 0 ATR = 1.0, 5 ATR = 0.0
        proximity_component = max(0.0, 1.0 - abs(nearest_fvg_distance_atr) / 5.0)
        
        # Weighted combination (FVG and trend get highest weights)
        weights = {
            "fvg": 0.35,
            "trend": 0.30,
            "sentiment": 0.20,
            "proximity": 0.15,
        }
        
        conviction = (
            fvg_component * weights["fvg"] +
            trend_component * weights["trend"] +
            sentiment_component * weights["sentiment"] +
            proximity_component * weights["proximity"]
        )
        
        # Bound to [0.2, 1.0] - never go below 20% conviction
        conviction = max(0.2, min(1.0, conviction))
        
        return {
            "conviction": round(conviction, 3),
            "fvg_component": round(fvg_component, 3),
            "trend_component": round(trend_component, 3),
            "sentiment_component": round(sentiment_component, 3),
            "proximity_component": round(proximity_component, 3),
            "raw_drivers": {
                "fvg_pressure": fvg_pressure,
                "fvg_confluence": fvg_confluence,
                "trend_aligned": trend_aligned,
                "sentiment_regime": sentiment_regime,
                "nearest_fvg_distance_atr": nearest_fvg_distance_atr,
            },
        }


# =============================================================================
# Singleton Accessor
# =============================================================================

_registry: Optional[CryptoAssetRegistry] = None


def get_crypto_registry() -> CryptoAssetRegistry:
    """Get the singleton crypto asset registry."""
    global _registry
    if _registry is None:
        _registry = CryptoAssetRegistry()
    return _registry


def get_asset_config(symbol: str) -> Optional[AssetConfig]:
    """Convenience function to get asset config."""
    return get_crypto_registry().get_config(symbol)


def get_fvg_config(symbol: str) -> Optional[FVGConfig]:
    """Convenience function to get FVG config."""
    return get_crypto_registry().get_fvg_config(symbol)


def get_calibration_config(symbol: str) -> Optional[CalibrationConfig]:
    """Convenience function to get calibration config for 80%+ hit-rate targeting."""
    return get_crypto_registry().get_calibration_config(symbol)


def is_fvg_enabled(symbol: str, timeframe: str = "15m") -> bool:
    """Quick check if FVG is enabled for asset/timeframe."""
    return get_crypto_registry().is_fvg_enabled(symbol, timeframe)


def get_all_supported_assets() -> List[str]:
    """Get all supported asset symbols."""
    return get_crypto_registry().get_supported_assets()


# =============================================================================
# Validation
# =============================================================================

def validate_registry() -> Dict[str, List[str]]:
    """Validate registry configuration and report any issues."""
    registry = get_crypto_registry()
    issues: Dict[str, List[str]] = {}
    
    for symbol in registry.get_supported_assets():
        config = registry.get_config(symbol)
        asset_issues = []
        
        # Check FVG config
        if config.fvg_config.enabled:
            if config.fvg_config.min_gap_size_atr <= 0:
                asset_issues.append("FVG min_gap_size_atr must be positive")
            if config.fvg_config.pressure_weight < 0 or config.fvg_config.pressure_weight > 1:
                asset_issues.append("FVG pressure_weight must be in [0, 1]")
        
        # Check risk config
        if config.risk_config.max_exposure_pct <= 0:
            asset_issues.append("Risk max_exposure_pct must be positive")
        if config.risk_config.kelly_fraction <= 0 or config.risk_config.kelly_fraction > 1:
            asset_issues.append("Risk kelly_fraction must be in (0, 1]")
        
        # Check indicator overrides
        if config.indicator_overrides.vol_low_threshold and config.indicator_overrides.vol_high_threshold:
            if config.indicator_overrides.vol_low_threshold >= config.indicator_overrides.vol_high_threshold:
                asset_issues.append("vol_low_threshold must be < vol_high_threshold")
        
        if asset_issues:
            issues[symbol] = asset_issues
    
    return issues


if __name__ == "__main__":
    # Quick validation
    print("Crypto Asset Registry Validation")
    print("=" * 50)
    
    registry = get_crypto_registry()
    
    print(f"\nSupported assets: {registry.get_supported_assets()}")
    
    for symbol in registry.get_supported_assets():
        config = registry.get_config(symbol)
        print(f"\n{symbol}:")
        print(f"  Name: {config.name}")
        print(f"  CoinGecko: {config.coingecko_id}")
        print(f"  Kalshi prefix: {config.kalshi_ticker_prefix}")
        print(f"  FVG enabled: {config.fvg_config.enabled}")
        print(f"  FVG timeframes: {config.fvg_config.active_timeframes}")
        print(f"  FVG min gap (ATR): {config.fvg_config.min_gap_size_atr}")
        print(f"  Exposure cap: {config.risk_config.max_exposure_pct:.0%}")
        print(f"  Kelly fraction: {config.risk_config.kelly_fraction}")
    
    # Validate
    issues = validate_registry()
    if issues:
        print("\n\nValidation Issues Found:")
        for symbol, asset_issues in issues.items():
            print(f"  {symbol}: {asset_issues}")
    else:
        print("\n\nAll configurations valid!")

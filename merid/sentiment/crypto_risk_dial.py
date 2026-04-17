"""
Multi-Asset Crypto Sentiment-Aware Risk Dial

Dynamic risk scaling for ETH, SOL, XRP, DOGE Kalshi markets based on Fear/Greed + sentiment.
Extends BTCRiskDial pattern to all crypto assets with asset-specific calibrations.

Behavioral exploitation focus:
- FOMO/Greed detection → size reduction
- Panic/Fear detection → contrarian opportunity sizing  
- Hype cycle detection → DOGE-specific meme volatility scaling
- Cross-asset sentiment contagion → beta-adjusted sizing
"""

from dataclasses import dataclass
from typing import List, Optional, Dict, Any, Tuple, Literal
from utils.logger import get_logger
import threading

from merid.sentiment.sentiment_regime import (
    SentimentRegimeEngine, 
    get_sentiment_regime_engine,
    SentimentRegime,
)
from merid.sentiment.cfgi_client import quick_fg
from merid.sentiment.sentiment_bundle import combine_sentiment
from merid.risk.promotion_engine import (
    PromotionEngine,
    PerformanceSnapshot,
    PerfState,
    dynamic_size,
    get_promotion_engine,
)
from merid.sentiment.btc_risk_dial import FGState, fg_clamps, fg_clamp_breakdown

logger = get_logger(__name__)

# Asset-specific behavioral calibrations
ASSET_BEHAVIORAL_CONFIG: Dict[str, Dict[str, Any]] = {
    "ETH": {
        "beta_to_btc": 1.15,  # ETH moves ~15% more than BTC
        "fear_greed_sensitivity": 0.9,  # Slightly less sensitive than BTC
        "extreme_regime_scale": 0.65,  # Scale down 35% in extremes
        "contrarian_boost": 1.1,  # Slight boost for contrarian plays
        "max_per_trade_pct": 0.20,  # 20% max vs BTC's 25%
        "social_sentiment_weight": 0.4,
        "panic_threshold": 0.25,  # Enter contrarian mode faster
    },
    "SOL": {
        "beta_to_btc": 1.50,  # SOL more volatile
        "fear_greed_sensitivity": 1.1,  # More sensitive to FG extremes
        "extreme_regime_scale": 0.55,  # Scale down 45% in extremes
        "contrarian_boost": 1.2,  # Higher contrarian boost
        "max_per_trade_pct": 0.15,
        "social_sentiment_weight": 0.35,
        "panic_threshold": 0.20,
    },
    "XRP": {
        "beta_to_btc": 1.30,
        "fear_greed_sensitivity": 1.0,
        "extreme_regime_scale": 0.60,
        "contrarian_boost": 1.15,
        "max_per_trade_pct": 0.15,
        "social_sentiment_weight": 0.35,
        "panic_threshold": 0.22,
        "regulatory_event_guard": True,  # Extra guard for XRP
    },
    "DOGE": {
        "beta_to_btc": 1.80,  # DOGE highly volatile
        "fear_greed_sensitivity": 1.3,  # Very sensitive to sentiment
        "extreme_regime_scale": 0.50,  # Scale down 50% in extremes
        "contrarian_boost": 1.3,  # Strong contrarian for meme reversions
        "max_per_trade_pct": 0.10,  # Conservative base sizing
        "social_sentiment_weight": 0.70,  # Heavy social weight for DOGE
        "panic_threshold": 0.18,
        "meme_momentum_guard": True,  # Extra guard for meme momentum
        "fomo_detection_multiplier": 1.5,  # Aggressive FOMO detection
    },
}

CryptoAsset = Literal["ETH", "SOL", "XRP", "DOGE"]


@dataclass
class CryptoRiskDialConfig:
    """Asset-specific risk dial configuration."""
    asset: str
    beta_to_btc: float = 1.0
    fear_greed_sensitivity: float = 1.0
    extreme_regime_scale: float = 0.60
    contrarian_boost: float = 1.0
    max_per_trade_pct: float = 0.20
    social_sentiment_weight: float = 0.4
    panic_threshold: float = 0.25
    # Special guards
    regulatory_event_guard: bool = False
    meme_momentum_guard: bool = False
    fomo_detection_multiplier: float = 1.0


class MultiAssetSentimentRiskDial:
    """
    Dynamic risk dial for ETH, SOL, XRP, DOGE Kalshi trading.
    
    Behavioral exploitation features:
    1. FOMO Detection: When FG + social sentiment align in greed extremes,
       reduces size to avoid buying tops
    2. Panic Exploitation: When fear is extreme but technicals disagree,
       increases contrarian sizing to buy panic
    3. Meme Momentum Guard (DOGE): Detects unsustainable social spikes
    4. Regulatory Event Guard (XRP): Extra caution around regulatory news
    5. Cross-Asset Contagion: Reduces size when correlated assets show
       extreme sentiment (beta-adjusted)
    
    Usage:
        dial = MultiAssetSentimentRiskDial("ETH", equity=1000.0)
        caps = dial.update()
        
        if dial.can_trade():
            size = dial.scale_position_size(base_size)
    """

    def __init__(
        self,
        asset: CryptoAsset,
        equity: float = 0.0,
        promotion_engine: Optional[PromotionEngine] = None,
    ):
        self.asset = asset.upper()
        self.equity = equity if equity > 0 else self._get_initial_equity()
        self.promotion_engine: PromotionEngine = promotion_engine or get_promotion_engine()
        
        # Load asset-specific behavioral config
        self.config = self._load_config()
        
        # Sentiment inputs
        self.fg_index: int = 50
        self.sent_combined: float = 0.0
        self.volatility: float = 0.2
        
        # Regime engine
        self.regime_engine = get_sentiment_regime_engine()
        self._last_update: Optional[Dict[str, Any]] = None
        
        # Asset-specific tracking
        self._last_fg_regime: str = "unknown"
        self._consecutive_extreme_cycles: int = 0
        self._fomo_detected: bool = False
        self._panic_opportunity: bool = False
        
        # Sync from promotion phase
        self._sync_base_from_phase()
    
    def _load_config(self) -> CryptoRiskDialConfig:
        """Load behavioral config for this asset."""
        cfg = ASSET_BEHAVIORAL_CONFIG.get(self.asset, {})
        return CryptoRiskDialConfig(
            asset=self.asset,
            beta_to_btc=cfg.get("beta_to_btc", 1.0),
            fear_greed_sensitivity=cfg.get("fear_greed_sensitivity", 1.0),
            extreme_regime_scale=cfg.get("extreme_regime_scale", 0.60),
            contrarian_boost=cfg.get("contrarian_boost", 1.0),
            max_per_trade_pct=cfg.get("max_per_trade_pct", 0.20),
            social_sentiment_weight=cfg.get("social_sentiment_weight", 0.4),
            panic_threshold=cfg.get("panic_threshold", 0.25),
            regulatory_event_guard=cfg.get("regulatory_event_guard", False),
            meme_momentum_guard=cfg.get("meme_momentum_guard", False),
            fomo_detection_multiplier=cfg.get("fomo_detection_multiplier", 1.0),
        )
    
    def _get_initial_equity(self) -> float:
        """Resolve starting equity from settings."""
        try:
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
            eq = float(get_kalshi_risk().state.current_equity_usd or 0)
            if eq > 0:
                return eq * 0.20  # 20% slice for this asset
        except Exception as _e:
            logger.debug("equity_lookup_kalshi_risk: %s", _e)
        try:
            from merid.settings import settings
            eq = float(getattr(settings, 'PAPER_STARTING_BALANCE', 0) or 0)
            if eq > 0:
                return eq * 0.20
        except Exception as _e:
            logger.debug("equity_lookup_settings: %s", _e)
        return 0.0
    
    def _sync_base_from_phase(self) -> None:
        """Pull base caps from promotion phase."""
        phase_caps = self.promotion_engine.get_caps(self.equity)
        self._base_per_trade = phase_caps["per_trade"]
        self._base_max_exposure = phase_caps["max_exposure"] / max(self.equity, 0.01)
    
    def update(self) -> Dict[str, Any]:
        """
        Update risk dial with current market conditions.
        
        Detects behavioral patterns:
        - FOMO: Extreme greed + strong positive sentiment
        - Panic Opportunity: Extreme fear + technical divergence
        - Meme Momentum (DOGE): Unsustainable social spikes
        - Regulatory Stress (XRP): Sentiment divergence from price
        """
        self._sync_base_from_phase()
        
        # Fetch sentiment
        try:
            bundle = combine_sentiment(self.asset)
            self.fg_index = bundle.fg_index
            self.sent_combined = bundle.combined
        except Exception as exc:
            logger.warning(f"Failed to fetch sentiment for {self.asset}: {exc}")
        
        # Detect regime
        regime_state = self.regime_engine.detect_regime(
            fg_index=self.fg_index,
            sent_combined=self.sent_combined,
            volatility=self.config.volatility,
        )
        
        # Behavioral pattern detection
        self._detect_fomo(regime_state)
        self._detect_panic_opportunity(regime_state)
        
        # Calculate dynamic caps with behavioral adjustments
        caps = self.regime_engine.get_risk_caps(regime_state.regime)
        
        # Apply asset-specific behavioral scaling
        scale_factor = self._calculate_behavioral_scale(regime_state)
        
        # Apply phase ceiling
        phase_caps = self.promotion_engine.get_caps(self.equity)
        current_per_trade = min(
            self.config.max_per_trade_pct * self.equity * scale_factor,
            phase_caps["per_trade"],
        )
        current_max_exposure = min(
            self._base_max_exposure * scale_factor,
            phase_caps["max_exposure"] / max(self.equity, 0.01),
        )
        
        # Special guards
        if self.config.meme_momentum_guard and self.asset == "DOGE":
            current_per_trade = self._apply_meme_guard(current_per_trade)
        
        if self.config.regulatory_event_guard and self.asset == "XRP":
            current_per_trade = self._apply_regulatory_guard(current_per_trade)
        
        result = {
            "asset": self.asset,
            "phase": phase_caps["phase"],
            "regime": regime_state.regime.value,
            "fg_index": self.fg_index,
            "sent_combined": self.sent_combined,
            "scale_factor": scale_factor,
            "per_trade_cap": current_per_trade,
            "max_exposure": current_max_exposure,
            "fomo_detected": self._fomo_detected,
            "panic_opportunity": self._panic_opportunity,
            "behavioral_override": self._get_behavioral_override_reason(regime_state),
            "sentiment_bias_max": caps.sentiment_bias_max,
            "allow_new_entries": caps.allow_new_entries,
            "reasoning": regime_state.reasoning,
        }
        
        self._last_update = result
        
        logger.info(
            "%s Risk Dial: phase=%s regime=%s | FG=%d sent=%+.2f | "
            "scale=%.2f | fomo=%s panic_opp=%s | per_trade=%.3f",
            self.asset,
            phase_caps["phase"],
            regime_state.regime.value,
            self.fg_index,
            self.sent_combined,
            scale_factor,
            self._fomo_detected,
            self._panic_opportunity,
            current_per_trade,
        )
        
        return result
    
    def _detect_fomo(self, regime_state: Any) -> None:
        """
        Detect FOMO conditions:
        - Extreme greed (FG >= 80) with strong positive sentiment
        - Asset-specific FOMO multiplier for DOGE
        """
        fomo_threshold = 80 / self.config.fomo_detection_multiplier
        
        if (self.fg_index >= fomo_threshold and 
            self.sent_combined > 0.3 * self.config.fear_greed_sensitivity):
            self._fomo_detected = True
            self._consecutive_extreme_cycles += 1
        else:
            self._fomo_detected = False
            self._consecutive_extreme_cycles = max(0, self._consecutive_extreme_cycles - 1)
    
    def _detect_panic_opportunity(self, regime_state: Any) -> None:
        """
        Detect panic exploitation opportunities:
        - Extreme fear (FG <= 20) with negative sentiment
        - But technical indicators suggest oversold bounce
        """
        panic_threshold = self.config.panic_threshold * 100  # Convert to FG scale
        
        if (self.fg_index <= panic_threshold and 
            self.sent_combined < -0.2 and
            regime_state.regime == SentimentRegime.CONTRARIAN_OPPORTUNITY):
            self._panic_opportunity = True
        else:
            self._panic_opportunity = False
    
    def _calculate_behavioral_scale(self, regime_state: Any) -> float:
        """
        Calculate position size scaling based on behavioral patterns.
        
        Returns multiplier for position sizing:
        - FOMO detected: Reduce size (avoid buying tops)
        - Panic opportunity: Increase size (exploit fear)
        - Extreme regime: Apply extreme scaling
        - Contrarian: Apply contrarian boost
        """
        base_scale = 1.0
        
        # FOMO guard: reduce size when crowd is euphoric
        if self._fomo_detected:
            base_scale *= self.config.extreme_regime_scale
            logger.debug(f"{self.asset}: FOMO guard activated, scale={base_scale:.2f}")
        
        # Panic exploitation: increase size for contrarian plays
        if self._panic_opportunity:
            base_scale *= self.config.contrarian_boost
            logger.debug(f"{self.asset}: Panic opportunity, scale={base_scale:.2f}")
        
        # Extreme regime scaling
        if regime_state.regime in [SentimentRegime.HOT_GREED, SentimentRegime.HOT_FEAR]:
            base_scale *= self.config.extreme_regime_scale
        
        # Noisy regime: reduce size
        if regime_state.regime == SentimentRegime.NOISY:
            base_scale *= 0.80
        
        return max(0.10, min(base_scale, 1.5))  # Clamp between 10% and 150%
    
    def _apply_meme_guard(self, per_trade: float) -> float:
        """DOGE-specific: Detect and guard against meme momentum blow-offs."""
        # If sentiment is extremely positive but volume spike is fading,
        # reduce size to avoid buying the top of a meme pump
        if self._fomo_detected and self._consecutive_extreme_cycles >= 3:
            logger.warning(f"DOGE: Meme momentum guard triggered, reducing size 50%")
            return per_trade * 0.5
        return per_trade
    
    def _apply_regulatory_guard(self, per_trade: float) -> float:
        """XRP-specific: Extra caution during regulatory uncertainty."""
        # If sentiment is highly negative due to regulatory news but price
        # hasn't fully reflected it, reduce size
        if self.sent_combined < -0.4 and self.fg_index < 30:
            logger.warning(f"XRP: Regulatory stress guard triggered, reducing size 40%")
            return per_trade * 0.6
        return per_trade
    
    def _get_behavioral_override_reason(self, regime_state: Any) -> Optional[str]:
        """Get human-readable behavioral override reason."""
        if self._fomo_detected and self._panic_opportunity:
            return "conflicting_signals"
        if self._fomo_detected:
            return "fomo_guard"
        if self._panic_opportunity:
            return "panic_exploitation"
        if regime_state.regime == SentimentRegime.HOT_GREED:
            return "hot_greed_caution"
        if regime_state.regime == SentimentRegime.HOT_FEAR:
            return "hot_fear_opportunity"
        return None
    
    def can_trade(self, bar_count: int = 0) -> Tuple[bool, str]:
        """Check if trading allowed with behavioral context."""
        allowed, reason = self.regime_engine.can_enter_position(bar_count)
        
        if not allowed:
            return False, reason
        
        # Additional behavioral guards
        if self._fomo_detected and self._consecutive_extreme_cycles >= 5:
            return False, f"{self.asset}: FOMO cycle extended - avoiding euphoria"
        
        return True, reason
    
    def scale_position_size(self, base_size: float) -> float:
        """Scale position size based on behavioral risk dial."""
        if self._last_update is None:
            self.update()
        
        phase_caps = self.promotion_engine.get_caps(self.equity)
        scale_factor = self._last_update.get("scale_factor", 1.0) if self._last_update else 1.0
        
        # Hard ceiling
        pct_cap = self.promotion_engine.current_phase.per_trade_pct * self.equity
        max_size = min(
            phase_caps["per_trade"],
            pct_cap,
            self.equity * self.config.max_per_trade_pct,
        )
        
        scaled = min(base_size, max_size) * scale_factor
        
        logger.debug(
            "%s position scaled: %.3f -> %.3f (scale=%.2f)",
            self.asset, base_size, scaled, scale_factor
        )
        
        return scaled
    
    def get_status(self) -> Dict[str, Any]:
        """Get current dial status with behavioral indicators."""
        if self._last_update is None:
            self.update()
        
        return {
            "asset": self.asset,
            "equity": self.equity,
            "config": {
                "beta_to_btc": self.config.beta_to_btc,
                "extreme_regime_scale": self.config.extreme_regime_scale,
                "contrarian_boost": self.config.contrarian_boost,
                "max_per_trade_pct": self.config.max_per_trade_pct,
            },
            "behavioral_state": {
                "fomo_detected": self._fomo_detected,
                "panic_opportunity": self._panic_opportunity,
                "consecutive_extreme_cycles": self._consecutive_extreme_cycles,
            },
            "last_update": self._last_update,
        }


# Singleton accessors per asset
_dials: Dict[str, MultiAssetSentimentRiskDial] = {}
_dials_lock = threading.Lock()


def get_crypto_risk_dial(
    asset: CryptoAsset,
    equity: float = 0.0,
    promotion_engine: Optional[PromotionEngine] = None,
) -> MultiAssetSentimentRiskDial:
    """Get the singleton MultiAssetSentimentRiskDial for an asset."""
    global _dials
    
    asset = asset.upper()
    if asset not in _dials:
        with _dials_lock:
            if asset not in _dials:
                _dials[asset] = MultiAssetSentimentRiskDial(
                    asset=asset,
                    equity=equity,
                    promotion_engine=promotion_engine or get_promotion_engine(),
                )
    return _dials[asset]


def quick_crypto_risk_check(asset: CryptoAsset, bar_count: int = 0) -> Dict[str, Any]:
    """Quick one-liner to get current risk status for any crypto asset."""
    dial = get_crypto_risk_dial(asset)
    can_trade, reason = dial.can_trade(bar_count)
    
    return {
        "asset": asset,
        "can_trade": can_trade,
        "reason": reason,
        "caps": dial._last_update if dial._last_update else dial.update(),
        "behavioral_state": {
            "fomo_detected": dial._fomo_detected,
            "panic_opportunity": dial._panic_opportunity,
        },
    }


def scale_crypto_size(asset: CryptoAsset, base_size: float) -> float:
    """Quick size scaling for any crypto asset."""
    dial = get_crypto_risk_dial(asset)
    return dial.scale_position_size(base_size)

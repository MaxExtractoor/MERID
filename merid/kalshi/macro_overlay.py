"""Kalshi Macro Overlay Implementation

Implements Level 3 of the MERID single-signal hierarchy:
- Ingests Kalshi macro/event markets (financials, elections, commodities, etc.)
- Computes MacroState with regime classification
- Produces MacroConvictionScore per crypto asset

Uses existing infrastructure:
- kalshi/ws.py for WebSocket streaming
- kalshi/client.py for REST polling
- kalshi/market_state.py pattern for state management

Safety constraints:
- All macro signals tagged with timestamp and expiry
- Liquidity filters (volume, spread) before using any market
- Graceful degradation if macro data unavailable
"""

from __future__ import annotations

import os
import threading
import time
from typing import Dict, List, Optional, Set, Callable

from merid.kalshi.macro_models import (
    AssetMacroSensitivity,
    MacroCategory,
    MacroConvictionScore,
    MacroMarketState,
    MacroRegime,
    MacroState,
    VolatilityRegime,
    DEFAULT_ASSET_SENSITIVITIES,
)
from utils.logger import get_logger

logger = get_logger("merid.kalshi.macro_overlay")


# Kalshi macro market ticker patterns (category prefixes)
MACRO_CATEGORY_PATTERNS: Dict[str, MacroCategory] = {
    "KXFR": MacroCategory.FINANCIALS,      # Fed/rates
    "KXCPI": MacroCategory.FINANCIALS,     # Inflation
    "KXGEOP": MacroCategory.ELECTIONS,     # Geopolitical/elections
    "KXWTI": MacroCategory.COMMODITIES,    # Oil
    "KXGLD": MacroCategory.COMMODITIES,    # Gold
    "KXBTC": MacroCategory.COMMODITIES,    # Crypto (for correlation)
    "KXGDP": MacroCategory.ECONOMICS,      # GDP
    "KXUNEMP": MacroCategory.ECONOMICS,    # Unemployment
    "KXRECES": MacroCategory.ECONOMICS,    # Recession indicators
    "KXTECH": MacroCategory.TECH_SCIENCE,  # Tech/science events
}

# Minimum liquidity thresholds
MIN_VOLUME_24H = 50      # Minimum 24h contracts traded
MAX_SPREAD_CENTS = 10    # Maximum acceptable spread
MAX_AGE_SECONDS = 300    # Maximum age for macro data (5 minutes)


class MacroConvictionScorer:
    """Converts macro market states into per-asset conviction scores.
    
    Implements the mapping from Kalshi macro probabilities to crypto
    sensitivity adjustments in the single-signal hierarchy.
    """
    
    def __init__(
        self,
        sensitivities: Optional[Dict[str, AssetMacroSensitivity]] = None,
    ):
        self.sensitivities = sensitivities or DEFAULT_ASSET_SENSITIVITIES
        self._lock = threading.Lock()
        
    def compute_score(
        self,
        asset: str,
        macro_state: MacroState,
    ) -> MacroConvictionScore:
        """Compute conviction score for a crypto asset based on macro state.
        
        Args:
            asset: Asset symbol (BTC, ETH, SOL, XRP, DOGE)
            macro_state: Current aggregated macro state
            
        Returns:
            MacroConvictionScore with breakdown and modifier
        """
        if asset not in self.sensitivities:
            logger.warning(f"No sensitivity config for {asset}, using neutral")
            return MacroConvictionScore(
                asset=asset,
                timestamp=time.time(),
                score=0.5,
                confidence=0.3,
                recommended_modifier=1.0,
            )
        
        sens = self.sensitivities[asset]
        
        # Base score starts at neutral (0.5)
        base_score = 0.5
        contributions = {
            "risk_on": 0.0,
            "monetary_policy": 0.0,
            "inflation": 0.0,
            "recession": 0.0,
            "tech_sentiment": 0.0,
        }
        
        # Risk-on/off contribution
        if macro_state.macro_regime == MacroRegime.RISK_ON:
            contributions["risk_on"] = sens.risk_on_sensitivity * 0.15
        elif macro_state.macro_regime == MacroRegime.RISK_OFF:
            contributions["risk_on"] = -sens.risk_on_sensitivity * 0.15
        
        # Monetary policy contribution (from fed_hike_prob)
        if macro_state.fed_hike_prob is not None:
            # Lower hike prob = more dovish = bullish for crypto
            dovish_score = 1.0 - macro_state.fed_hike_prob
            contributions["monetary_policy"] = (
                (dovish_score - 0.5) * sens.rate_cut_sensitivity * 0.2
            )
        
        # Inflation contribution
        if macro_state.cpi_surprise_prob is not None:
            # Lower surprise prob = less inflation fear = bullish
            low_inflation_score = 1.0 - macro_state.cpi_surprise_prob
            contributions["inflation"] = (
                (low_inflation_score - 0.5) * sens.cpi_surprise_sensitivity * 0.2
            )
        
        # Recession contribution
        if macro_state.recession_prob is not None:
            # Lower recession prob = bullish
            growth_score = 1.0 - macro_state.recession_prob
            contributions["recession"] = (
                (growth_score - 0.5) * sens.recession_sensitivity * 0.2
            )
        
        # Tech sentiment (from tech_science category)
        if macro_state.tech_science:
            # Aggregate tech sentiment from available markets
            tech_bullish_count = sum(
                1 for m in macro_state.tech_science.values()
                if m.yes_prob > 0.6
            )
            tech_total = len(macro_state.tech_science)
            if tech_total > 0:
                tech_sentiment = tech_bullish_count / tech_total
                contributions["tech_sentiment"] = (
                    (tech_sentiment - 0.5) * sens.tech_sentiment_sensitivity * 0.15
                )
        
        # Calculate final score
        total_contribution = sum(contributions.values())
        score = max(0.0, min(1.0, base_score + total_contribution))
        
        # Calculate confidence based on data quality
        confidence = self._calculate_confidence(macro_state)
        
        # Calculate recommended modifier (0.5x to 1.5x range)
        # Score < 0.4: reduce exposure (modifier < 1.0)
        # Score > 0.6: increase exposure (modifier > 1.0)
        # Score 0.4-0.6: neutral (modifier = 1.0)
        if score < 0.4:
            modifier = 0.5 + (score / 0.4) * 0.5  # 0.5 to 1.0
        elif score > 0.6:
            modifier = 1.0 + ((score - 0.6) / 0.4) * 0.5  # 1.0 to 1.5
        else:
            modifier = 1.0
        
        return MacroConvictionScore(
            asset=asset,
            timestamp=time.time(),
            score=score,
            risk_on_contribution=contributions["risk_on"],
            monetary_policy_contribution=contributions["monetary_policy"],
            inflation_contribution=contributions["inflation"],
            recession_contribution=contributions["recession"],
            tech_sentiment_contribution=contributions["tech_sentiment"],
            confidence=confidence,
            recommended_modifier=round(modifier, 3),
        )
    
    def _calculate_confidence(self, macro_state: MacroState) -> float:
        """Calculate confidence score based on macro data quality."""
        factors = []
        
        # Financials data available
        if macro_state.financials:
            liquid_financials = sum(
                1 for m in macro_state.financials.values() if m.is_liquid
            )
            factors.append(min(1.0, liquid_financials / 3))
        
        # Economics data available
        if macro_state.economics:
            factors.append(0.8)
        
        # Regime clarity (not neutral = more confident)
        if macro_state.macro_regime != MacroRegime.NEUTRAL:
            factors.append(0.9)
        else:
            factors.append(0.5)
        
        # Data freshness
        age_seconds = time.time() - macro_state.timestamp
        if age_seconds < 60:
            factors.append(1.0)
        elif age_seconds < 300:
            factors.append(0.8)
        else:
            factors.append(0.5)
        
        return sum(factors) / len(factors) if factors else 0.3


class KalshiMacroOverlay:
    """Main macro overlay service for Kalshi prediction markets.
    
    Manages macro market state and produces conviction scores for crypto assets.
    Integrates with the single-signal hierarchy via get_macro_state() and
    get_conviction_scores().
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        tracked_assets: Optional[Set[str]] = None,
    ):
        self.api_key = api_key or os.getenv("KALSHI_API_KEY_ID", "")
        self.api_secret = api_secret or os.getenv("KALSHI_API_KEY_PRIVATE", "")
        self.tracked_assets = tracked_assets or {"BTC", "ETH", "SOL", "XRP", "DOGE"}
        
        # State
        self._macro_state: Optional[MacroState] = None
        self._market_cache: Dict[str, MacroMarketState] = {}
        self._last_update: float = 0.0
        
        # Components
        self._scorer = MacroConvictionScorer()
        
        # Thread safety
        self._lock = threading.Lock()
        self._running = False
        
        # Callbacks for state updates
        self._callbacks: List[Callable[[MacroState], None]] = []
    
    def register_callback(self, callback: Callable[[MacroState], None]) -> None:
        """Register callback for macro state updates."""
        self._callbacks.append(callback)
    
    def get_macro_state(self) -> Optional[MacroState]:
        """Get current macro state. Thread-safe."""
        with self._lock:
            return self._macro_state
    
    def get_conviction_scores(self) -> Dict[str, MacroConvictionScore]:
        """Get conviction scores for all tracked assets.
        
        Returns:
            Dict mapping asset symbol to MacroConvictionScore
        """
        with self._lock:
            state = self._macro_state
        
        if state is None:
            logger.warning("Macro state not available, returning neutral scores")
            return {
                asset: MacroConvictionScore(
                    asset=asset,
                    timestamp=time.time(),
                    score=0.5,
                    confidence=0.3,
                    recommended_modifier=1.0,
                )
                for asset in self.tracked_assets
            }
        
        return {
            asset: self._scorer.compute_score(asset, state)
            for asset in self.tracked_assets
        }
    
    def update_from_markets(self, markets: List[Dict]) -> None:
        """Update macro state from list of Kalshi market dicts.
        
        Called by REST polling or WebSocket handlers.
        
        Args:
            markets: List of market dicts from Kalshi API
        """
        try:
            macro_markets = self._parse_markets(markets)
            self._update_state(macro_markets)
        except Exception as e:
            logger.error(f"Failed to update macro state: {e}", exc_info=True)
    
    def _parse_markets(
        self,
        markets: List[Dict],
    ) -> Dict[MacroCategory, Dict[str, MacroMarketState]]:
        """Parse Kalshi market dicts into MacroMarketState by category."""
        result: Dict[MacroCategory, Dict[str, MacroMarketState]] = {
            cat: {} for cat in MacroCategory
        }
        
        for market in markets:
            ticker = market.get("ticker", "")
            category = self._categorize_ticker(ticker)
            
            # Skip if not a macro market
            if category is None:
                continue
            
            # Parse probability
            yes_prob = market.get("yes_ask", 0.5)  # Use ask as conservative estimate
            if isinstance(yes_prob, (int, float)):
                yes_prob = float(yes_prob)
            else:
                yes_prob = 0.5
            
            # Build state
            state = MacroMarketState(
                ticker=ticker,
                category=category,
                title=market.get("title", ""),
                yes_prob=yes_prob,
                yes_prob_24h_ago=market.get("yes_ask_24h_ago", yes_prob),
                yes_prob_7d_ago=market.get("yes_ask_7d_ago", yes_prob),
                spread_cents=market.get("spread_cents", 5),
                volume_24h=market.get("volume_24h", 0),
                open_interest=market.get("open_interest", 0),
                last_update_ts=time.time(),
                seconds_to_expiry=market.get("seconds_to_expiry"),
            )
            
            # Only include liquid markets
            if state.is_liquid:
                result[category][ticker] = state
        
        return result
    
    def _categorize_ticker(self, ticker: str) -> Optional[MacroCategory]:
        """Determine macro category from ticker prefix."""
        for prefix, category in MACRO_CATEGORY_PATTERNS.items():
            if ticker.startswith(prefix):
                return category
        return None
    
    def _update_state(
        self,
        markets_by_category: Dict[MacroCategory, Dict[str, MacroMarketState]],
    ) -> None:
        """Update aggregated macro state from parsed markets."""
        with self._lock:
            # Update market cache
            for category, markets in markets_by_category.items():
                self._market_cache.update(markets)
            
            # Prune stale entries
            cutoff = time.time() - MAX_AGE_SECONDS
            self._market_cache = {
                k: v for k, v in self._market_cache.items()
                if v.last_update_ts > cutoff
            }
            
            # Build new macro state
            state = MacroState(
                timestamp=time.time(),
                financials={k: v for k, v in self._market_cache.items()
                          if v.category == MacroCategory.FINANCIALS},
                elections={k: v for k, v in self._market_cache.items()
                          if v.category == MacroCategory.ELECTIONS},
                commodities={k: v for k, v in self._market_cache.items()
                           if v.category == MacroCategory.COMMODITIES},
                economics={k: v for k, v in self._market_cache.items()
                         if v.category == MacroCategory.ECONOMICS},
                tech_science={k: v for k, v in self._market_cache.items()
                            if v.category == MacroCategory.TECH_SCIENCE},
            )
            
            # Classify regime
            state.macro_regime = self._classify_regime(state)
            state.vol_regime = self._classify_volatility(state)
            state.event_risk_score = self._compute_event_risk(state)
            
            # Extract key indicators
            state.fed_hike_prob = self._extract_fed_prob(state.financials)
            state.cpi_surprise_prob = self._extract_cpi_prob(state.financials)
            state.recession_prob = self._extract_recession_prob(state.economics)
            
            self._macro_state = state
            self._last_update = time.time()
        
        # Notify callbacks
        for callback in self._callbacks:
            try:
                callback(state)
            except Exception as e:
                logger.warning(f"Macro state callback failed: {e}")
    
    def _classify_regime(self, state: MacroState) -> MacroRegime:
        """Classify overall macro regime from market states."""
        # Count bullish vs bearish signals
        risk_on_signals = 0
        risk_off_signals = 0
        
        # Financials: dovish Fed = risk-on
        for market in state.financials.values():
            if "hike" in market.title.lower() or "rate" in market.title.lower():
                if market.yes_prob < 0.3:  # Low hike probability
                    risk_on_signals += 1
                elif market.yes_prob > 0.7:
                    risk_off_signals += 1
        
        # Recession indicators
        for market in state.economics.values():
            if "recession" in market.title.lower():
                if market.yes_prob > 0.5:
                    risk_off_signals += 2  # Recession fear is strong signal
                else:
                    risk_on_signals += 1
        
        # Determine regime
        if risk_off_signals >= 2:
            return MacroRegime.RISK_OFF
        elif risk_on_signals >= 2:
            return MacroRegime.RISK_ON
        elif state.event_risk_score > 0.7:
            return MacroRegime.EVENT_RISK_HIGH
        else:
            return MacroRegime.NEUTRAL
    
    def _classify_volatility(self, state: MacroState) -> VolatilityRegime:
        """Classify volatility regime."""
        # Use event risk as proxy for vol regime
        if state.event_risk_score > 0.7:
            return VolatilityRegime.ELEVATED
        elif state.event_risk_score > 0.4:
            return VolatilityRegime.EXPANDING
        elif state.event_risk_score < 0.2:
            return VolatilityRegime.CONTRACTING
        else:
            return VolatilityRegime.STABLE
    
    def _compute_event_risk(self, state: MacroState) -> float:
        """Compute aggregate event risk score (0.0-1.0)."""
        factors = []
        
        # Elections
        for market in state.elections.values():
            if market.yes_prob > 0.3 and market.yes_prob < 0.7:
                factors.append(0.5)  # Uncertain outcome
        
        # Close macro events (low seconds_to_expiry)
        for market in list(state.financials.values()) + list(state.economics.values()):
            if market.seconds_to_expiry and market.seconds_to_expiry < 86400:
                factors.append(0.3)
        
        # Volatile macro markets (high spread = uncertainty)
        for market in self._market_cache.values():
            if market.spread_cents > 5:
                factors.append(0.2)
        
        return min(1.0, sum(factors)) if factors else 0.0
    
    def _extract_fed_prob(self, financials: Dict[str, MacroMarketState]) -> Optional[float]:
        """Extract Fed hike probability from financials markets."""
        for ticker, market in financials.items():
            if "hike" in market.title.lower() and "fed" in market.title.lower():
                return market.yes_prob
        return None
    
    def _extract_cpi_prob(self, financials: Dict[str, MacroMarketState]) -> Optional[float]:
        """Extract CPI surprise probability."""
        for ticker, market in financials.items():
            if "cpi" in market.title.lower():
                return market.yes_prob
        return None
    
    def _extract_recession_prob(self, economics: Dict[str, MacroMarketState]) -> Optional[float]:
        """Extract recession probability."""
        for ticker, market in economics.items():
            if "recession" in market.title.lower():
                return market.yes_prob
        return None


# ═══════════════════════════════════════════════════════════════════════════
# Singleton
# ═══════════════════════════════════════════════════════════════════════════

_overlay_instance: Optional[KalshiMacroOverlay] = None
_overlay_lock = threading.Lock()


def get_kalshi_macro_overlay() -> KalshiMacroOverlay:
    """Get or create the singleton KalshiMacroOverlay instance."""
    global _overlay_instance
    if _overlay_instance is None:
        with _overlay_lock:
            if _overlay_instance is None:
                _overlay_instance = KalshiMacroOverlay()
                logger.info("KalshiMacroOverlay singleton initialized")
    return _overlay_instance


def reset_kalshi_macro_overlay() -> None:
    """Reset the singleton (for testing)."""
    global _overlay_instance
    with _overlay_lock:
        _overlay_instance = None
        logger.info("KalshiMacroOverlay singleton reset")

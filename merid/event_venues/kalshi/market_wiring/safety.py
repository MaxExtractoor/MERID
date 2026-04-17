"""
Safety and Gating Layer

Enforces data freshness constraints, per-market risk caps, and segment-based CQI
for safe Kalshi market operations.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from enum import Enum

from merid.signals.cqi_gating import GatingDecision, QualityBand
from merid.signals.store import get_signal_store
from merid.event_venues.kalshi.market_wiring.models import (
    MarketMapping,
    KalshiMarketRecord,
    MarketContextConfig,
    RiskProfile,
)
from merid.event_venues.kalshi.market_wiring.store import get_kalshi_market_store
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.market_wiring.safety")


class ContextStatus(Enum):
    """Status of context data availability"""
    AVAILABLE = "available"
    STALE = "stale"
    MISSING = "missing"


@dataclass
class ContextCheckResult:
    """Result of context availability check"""
    crypto_status: ContextStatus
    sentiment_status: ContextStatus
    debate_status: ContextStatus
    
    crypto_age_seconds: Optional[float]
    sentiment_age_seconds: Optional[float]
    debate_age_seconds: Optional[float]
    
    @property
    def all_available(self) -> bool:
        """Check if all required contexts are available"""
        return all(status == ContextStatus.AVAILABLE for status in [
            self.crypto_status, self.sentiment_status, self.debate_status
        ])
    
    @property
    def any_stale(self) -> bool:
        """Check if any context is stale"""
        return any(status == ContextStatus.STALE for status in [
            self.crypto_status, self.sentiment_status, self.debate_status
        ])


@dataclass
class RiskCheckResult:
    """Result of risk limit check"""
    passes_risk_limits: bool
    current_exposure: float
    daily_pnl: float
    max_notional_per_trade: float
    max_daily_notional: float
    max_open_risk: float
    
    # Limit breaches
    breaches_per_trade_limit: bool
    breaches_daily_limit: bool
    breaches_open_risk_limit: bool
    
    def get_breach_reasons(self) -> List[str]:
        """Get list of breach reasons"""
        reasons = []
        if self.breaches_per_trade_limit:
            reasons.append("per_trade_notional_limit")
        if self.breaches_daily_limit:
            reasons.append("daily_notional_limit")
        if self.breaches_open_risk_limit:
            reasons.append("open_risk_limit")
        return reasons


@dataclass
class SafetyCheckResult:
    """Complete safety check result"""
    market_ticker: str
    safe_to_trade: bool
    
    # Context availability
    context_check: ContextCheckResult
    
    # Risk limits
    risk_check: RiskCheckResult
    
    # CQI gating
    cqi_decision: GatingDecision
    cqi_value: float
    cqi_band: QualityBand
    
    # Overall decision
    block_reasons: List[str]
    
    # Effective limits (may be reduced due to poor CQI)
    effective_max_notional: float
    effective_daily_notional: float
    effective_open_risk: float


class KalshiSafetyLayer:
    """Enforces safety constraints for Kalshi market operations"""
    
    def __init__(self):
        self._store = get_kalshi_market_store()
        self._signal_store = get_signal_store()
        
        # CQI segment multipliers for risk reduction
        self._cqi_multipliers = {
            QualityBand.EXCELLENT: 1.0,
            QualityBand.GOOD: 0.8,
            QualityBand.NEUTRAL: 0.6,
            QualityBand.POOR: 0.4,
            QualityBand.CRITICAL: 0.2,
        }
    
    def _check_crypto_context_freshness(self, underlying_symbol: str, max_staleness: float) -> Tuple[ContextStatus, Optional[float]]:
        """Check crypto feature freshness"""
        try:
            # Get latest crypto features for the symbol
            features = self._signal_store.get_latest_features(
                symbol=underlying_symbol,
                domain="crypto"
            )
            
            if not features:
                return ContextStatus.MISSING, None
            
            # Check age
            current_time = time.time()
            feature_time = features.get("timestamp", 0)
            age = current_time - feature_time
            
            if age <= max_staleness:
                return ContextStatus.AVAILABLE, age
            else:
                return ContextStatus.STALE, age
                
        except Exception as e:
            logger.error(f"Error checking crypto context for {underlying_symbol}: {e}")
            return ContextStatus.MISSING, None
    
    def _check_sentiment_context_freshness(self, sentiment_symbols: List[str], max_staleness: float) -> Tuple[ContextStatus, Optional[float]]:
        """Check sentiment context freshness"""
        try:
            current_time = time.time()
            youngest_age = None
            
            for symbol in sentiment_symbols:
                features = self._signal_store.get_latest_features(
                    symbol=symbol,
                    domain="sentiment"
                )
                
                if features:
                    age = current_time - features.get("timestamp", 0)
                    if youngest_age is None or age < youngest_age:
                        youngest_age = age
            
            if youngest_age is None:
                return ContextStatus.MISSING, None
            
            if youngest_age <= max_staleness:
                return ContextStatus.AVAILABLE, youngest_age
            else:
                return ContextStatus.STALE, youngest_age
                
        except Exception as e:
            logger.error(f"Error checking sentiment context: {e}")
            return ContextStatus.MISSING, None
    
    def _check_debate_context_freshness(self, debate_symbol: Optional[str], max_staleness: float) -> Tuple[ContextStatus, Optional[float]]:
        """Check debate context freshness"""
        if not debate_symbol:
            return ContextStatus.AVAILABLE, None  # Not required
        
        try:
            features = self._signal_store.get_latest_features(
                symbol=debate_symbol,
                domain="debate"
            )
            
            if not features:
                return ContextStatus.MISSING, None
            
            # Check age
            current_time = time.time()
            feature_time = features.get("timestamp", 0)
            age = current_time - feature_time
            
            if age <= max_staleness:
                return ContextStatus.AVAILABLE, age
            else:
                return ContextStatus.STALE, age
                
        except Exception as e:
            logger.error(f"Error checking debate context for {debate_symbol}: {e}")
            return ContextStatus.MISSING, None
    
    def check_context_freshness(self, mapping: MarketMapping) -> ContextCheckResult:
        """Check freshness of all required contexts"""
        # Crypto context
        if mapping.requires_crypto_context:
            crypto_status, crypto_age = self._check_crypto_context_freshness(
                mapping.underlying_symbol, mapping.max_crypto_staleness
            )
        else:
            crypto_status, crypto_age = ContextStatus.AVAILABLE, None
        
        # Sentiment context
        if mapping.requires_sentiment_context:
            sentiment_status, sentiment_age = self._check_sentiment_context_freshness(
                mapping.sentiment_symbols, mapping.max_sentiment_staleness
            )
        else:
            sentiment_status, sentiment_age = ContextStatus.AVAILABLE, None
        
        # Debate context
        if mapping.requires_debate_context:
            debate_status, debate_age = self._check_debate_context_freshness(
                mapping.debate_symbol, mapping.max_debate_staleness
            )
        else:
            debate_status, debate_age = ContextStatus.AVAILABLE, None
        
        return ContextCheckResult(
            crypto_status=crypto_status,
            sentiment_status=sentiment_status,
            debate_status=debate_status,
            crypto_age_seconds=crypto_age,
            sentiment_age_seconds=sentiment_age,
            debate_age_seconds=debate_age,
        )
    
    def check_risk_limits(self, market: KalshiMarketRecord, proposed_notional: float) -> RiskCheckResult:
        """Check if proposed notional exceeds raw market risk limits (hard caps)"""
        try:
            # Use raw market limits for blocking decisions (hard caps)
            max_notional = market.max_notional_per_trade
            max_daily = market.max_daily_notional
            max_open_risk = market.max_open_risk
            
            # Get current exposure (simplified - would integrate with position tracking)
            current_daily_exposure = self._get_current_daily_exposure(market.market_ticker)
            current_open_risk = self._get_current_open_risk(market.market_ticker)
            
            # Check per-trade limit
            notional_breach = proposed_notional > max_notional
            
            # Check daily limit
            daily_breach = (current_daily_exposure + proposed_notional) > max_daily
            
            # Check open risk limit
            open_risk_breach = (current_open_risk + proposed_notional) > max_open_risk
            
            passes_risk_limits = not (notional_breach or daily_breach or open_risk_breach)
            
            return RiskCheckResult(
                passes_risk_limits=passes_risk_limits,
                current_exposure=current_daily_exposure,
                daily_pnl=current_daily_exposure,  # Simplified
                max_notional_per_trade=max_notional,
                max_daily_notional=max_daily,
                max_open_risk=max_open_risk,
                breaches_per_trade_limit=notional_breach,
                breaches_daily_limit=daily_breach,
                breaches_open_risk_limit=open_risk_breach,
            )
            
        except Exception as e:
            logger.error(f"Error checking risk limits for {market.market_ticker}: {e}")
            return RiskCheckResult(
                passes_risk_limits=False,
                current_exposure=0.0,
                daily_pnl=0.0,
                max_notional_per_trade=0.0,
                max_daily_notional=0.0,
                max_open_risk=0.0,
                breaches_per_trade_limit=True,
                breaches_daily_limit=True,
                breaches_open_risk_limit=True,
            )
    
    def get_segment_cqi(self, risk_profile: RiskProfile) -> Tuple[float, QualityBand]:
        """Get CQI for a specific market segment"""
        # Map risk profile to CQI segment
        segment_map = {
            RiskProfile.CRYPTO_LINKED: "prediction_crypto_linked",
            RiskProfile.MACRO_ELECTION: "prediction_macro_election",
            RiskProfile.EQUITY_LINKED: "prediction_equity_linked",
            RiskProfile.IDIOSYNCRATIC: "prediction_other",
        }
        
        segment = segment_map.get(risk_profile, "prediction_other")
        
        try:
            # Get CQI for the segment
            cqi_data = self._signal_store.get_latest_cqi(domain="prediction", segment=segment)
            if cqi_data:
                cqi_value = cqi_data.get("quality_index", 0.5)
                
                # Determine quality band
                if cqi_value >= 0.8:
                    band = QualityBand.EXCELLENT
                elif cqi_value >= 0.6:
                    band = QualityBand.GOOD
                elif cqi_value >= 0.4:
                    band = QualityBand.NEUTRAL
                elif cqi_value >= 0.2:
                    band = QualityBand.POOR
                else:
                    band = QualityBand.CRITICAL
                
                return cqi_value, band
        except Exception as e:
            logger.error(f"Error getting segment CQI for {segment}: {e}")
        
        # Default values
        return 0.5, QualityBand.NEUTRAL
    
    def apply_cqi_gating(self, signal: Dict[str, Any], mapping: MarketMapping) -> Tuple[GatingDecision, float, QualityBand]:
        """Apply CQI gating to a signal"""
        # Get segment CQI
        cqi_value, cqi_band = self.get_segment_cqi(mapping.risk_profile)
        
        # Apply gating thresholds (could be made configurable per risk profile)
        min_cqi = 0.4  # Default minimum
        
        # Adjust thresholds based on risk profile
        if mapping.risk_profile == RiskProfile.CRYPTO_LINKED:
            min_cqi = 0.3  # More lenient for crypto (richer context)
        elif mapping.risk_profile == RiskProfile.MACRO_ELECTION:
            min_cqi = 0.5  # Stricter for elections
        elif mapping.risk_profile == RiskProfile.IDIOSYNCRATIC:
            min_cqi = 0.6  # Strictest for idiosyncratic
        
        # Make gating decision
        if cqi_value >= 0.7:
            decision = GatingDecision.ALLOW
        elif cqi_value >= min_cqi:
            decision = GatingDecision.THROTTLE
        else:
            decision = GatingDecision.SUPPRESS
        
        return decision, cqi_value, cqi_band
    
    def calculate_effective_limits(self, market: KalshiMarketRecord, cqi_band: QualityBand) -> Tuple[float, float, float]:
        """Calculate effective risk limits based on CQI"""
        multiplier = self._cqi_multipliers.get(cqi_band, 0.5)
        
        effective_notional = market.max_notional_per_trade * multiplier
        effective_daily = market.max_daily_notional * multiplier
        effective_open = market.max_open_risk * multiplier
        
        return effective_notional, effective_daily, effective_open
    
    def perform_safety_check(self, market_ticker: str, signal: Optional[Dict[str, Any]] = None, proposed_notional: float = 0.0) -> SafetyCheckResult:
        """Perform complete safety check for a market"""
        try:
            # Get market and mapping
            market = self._store.get_market(market_ticker)
            mapping = self._store.get_mapping(market_ticker)
            
            if not market or not mapping:
                return SafetyCheckResult(
                    market_ticker=market_ticker,
                    safe_to_trade=False,
                    context_check=ContextCheckResult(
                        crypto_status=ContextStatus.MISSING,
                        sentiment_status=ContextStatus.MISSING,
                        debate_status=ContextStatus.MISSING,
                        crypto_age_seconds=None,
                        sentiment_age_seconds=None,
                        debate_age_seconds=None,
                    ),
                    risk_check=RiskCheckResult(
                        passes_risk_limits=False,
                        current_exposure=0.0,
                        daily_pnl=0.0,
                        max_notional_per_trade=0.0,
                        max_daily_notional=0.0,
                        max_open_risk=0.0,
                        breaches_per_trade_limit=True,
                        breaches_daily_limit=True,
                        breaches_open_risk_limit=True,
                    ),
                    cqi_decision=GatingDecision.SUPPRESS,
                    cqi_value=0.0,
                    cqi_band=QualityBand.CRITICAL,
                    block_reasons=["missing_market_or_mapping"],
                    effective_max_notional=0.0,
                    effective_daily_notional=0.0,
                    effective_open_risk=0.0,
                )
            
            # Check if enabled
            if not mapping.enabled or not market.enabled_for_merid:
                return SafetyCheckResult(
                    market_ticker=market_ticker,
                    safe_to_trade=False,
                    context_check=ContextCheckResult(
                        crypto_status=ContextStatus.AVAILABLE,
                        sentiment_status=ContextStatus.AVAILABLE,
                        debate_status=ContextStatus.AVAILABLE,
                        crypto_age_seconds=None,
                        sentiment_age_seconds=None,
                        debate_age_seconds=None,
                    ),
                    risk_check=RiskCheckResult(
                        passes_risk_limits=True,
                        current_exposure=0.0,
                        daily_pnl=0.0,
                        max_notional_per_trade=market.max_notional_per_trade,
                        max_daily_notional=market.max_daily_notional,
                        max_open_risk=market.max_open_risk,
                        breaches_per_trade_limit=False,
                        breaches_daily_limit=False,
                        breaches_open_risk_limit=False,
                    ),
                    cqi_decision=GatingDecision.SUPPRESS,
                    cqi_value=0.5,
                    cqi_band=QualityBand.NEUTRAL,
                    block_reasons=["market_disabled"],
                    effective_max_notional=0.0,
                    effective_daily_notional=0.0,
                    effective_open_risk=0.0,
                )
            
            # Check context freshness
            context_check = self.check_context_freshness(mapping)
            
            # Check risk limits
            risk_check = self.check_risk_limits(market, proposed_notional)
            
            # Apply CQI gating
            if signal:
                cqi_decision, cqi_value, cqi_band = self.apply_cqi_gating(signal, mapping)
            else:
                cqi_value, cqi_band = self.get_segment_cqi(mapping.risk_profile)
                cqi_decision = GatingDecision.ALLOW if cqi_value >= 0.6 else GatingDecision.THROTTLE
            
            # Calculate effective limits
            effective_notional, effective_daily, effective_open = self.calculate_effective_limits(market, cqi_band)
            
            # Collect block reasons
            block_reasons = []
            
            if not context_check.all_available:
                block_reasons.append("missing_context")
            elif context_check.any_stale:
                block_reasons.append("stale_context")
            
            if not risk_check.passes_risk_limits:
                block_reasons.extend(risk_check.get_breach_reasons())
            
            if cqi_decision == GatingDecision.SUPPRESS:
                block_reasons.append("cqi_suppression")
            elif cqi_decision == GatingDecision.THROTTLE:
                block_reasons.append("cqi_throttling")
            
            # Final safety decision
            safe_to_trade = (
                mapping.enabled and
                market.enabled_for_merid and
                context_check.all_available and
                not context_check.any_stale and
                risk_check.passes_risk_limits and
                cqi_decision != GatingDecision.SUPPRESS
            )
            
            return SafetyCheckResult(
                market_ticker=market_ticker,
                safe_to_trade=safe_to_trade,
                context_check=context_check,
                risk_check=risk_check,
                cqi_decision=cqi_decision,
                cqi_value=cqi_value,
                cqi_band=cqi_band,
                block_reasons=block_reasons,
                effective_max_notional=effective_notional,
                effective_daily_notional=effective_daily,
                effective_open_risk=effective_open,
            )
            
        except Exception as e:
            logger.error(f"Error performing safety check for {market_ticker}: {e}")
            return SafetyCheckResult(
                market_ticker=market_ticker,
                safe_to_trade=False,
                context_check=ContextCheckResult(
                    crypto_status=ContextStatus.MISSING,
                    sentiment_status=ContextStatus.MISSING,
                    debate_status=ContextStatus.MISSING,
                    crypto_age_seconds=None,
                    sentiment_age_seconds=None,
                    debate_age_seconds=None,
                ),
                risk_check=RiskCheckResult(
                    passes_risk_limits=False,
                    current_exposure=0.0,
                    daily_pnl=0.0,
                    max_notional_per_trade=0.0,
                    max_daily_notional=0.0,
                    max_open_risk=0.0,
                    breaches_per_trade_limit=True,
                    breaches_daily_limit=True,
                    breaches_open_risk_limit=True,
                ),
                cqi_decision=GatingDecision.SUPPRESS,
                cqi_value=0.0,
                cqi_band=QualityBand.CRITICAL,
                block_reasons=["safety_check_error"],
                effective_max_notional=0.0,
                effective_daily_notional=0.0,
                effective_open_risk=0.0,
            )


# Singleton instance
_safety_layer: Optional[KalshiSafetyLayer] = None


def get_kalshi_safety_layer() -> KalshiSafetyLayer:
    """Get singleton safety layer instance"""
    global _safety_layer
    if _safety_layer is None:
        _safety_layer = KalshiSafetyLayer()
    return _safety_layer

"""
Debate Integration for Signal Generation

Integrates debate system context (health, risk multipliers, alerts) into
the unified signal pipeline for cross-domain signal generation.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from merid.trading.debate_risk_multiplier import DebateRiskMultiplier, DebateRiskAdjustment
from merid.prediction.debate import get_debate_store
from merid.signals.unified_manager import get_unified_signal_manager
from utils.logger import get_logger

logger = get_logger("signals.debate_integration")


@dataclass
class DebateContext:
    """Debate system context for a symbol/market"""
    symbol: str
    debate_status: str
    health_score: float  # 0-1, higher is healthier
    active_debates: int
    recent_alerts: Dict[str, int]  # alert types -> counts
    last_activity: float
    confidence_level: float  # Overall confidence in debate outcomes
    cache_timestamp: float  # When this context was computed (for freshness)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage"""
        return {
            "symbol": self.symbol,
            "debate_status": self.debate_status,
            "health_score": self.health_score,
            "active_debates": self.active_debates,
            "recent_alerts": self.recent_alerts,
            "last_activity": self.last_activity,
            "confidence_level": self.confidence_level,
            "cache_timestamp": self.cache_timestamp,
        }


class DebateSignalIntegrator:
    """Integrates debate system data into the unified signal pipeline"""
    
    def __init__(self):
        self._unified_manager = get_unified_signal_manager()
        self._debate_store = get_debate_store()
        self._risk_multiplier = DebateRiskMultiplier()
        self._context_cache: Dict[str, DebateContext] = {}
        self._cache_ttl = 300  # 5 minutes cache
    
    def process_all_debate_signals(self) -> int:
        """Process debate signals for all active markets"""
        processed_count = 0
        
        try:
            # Get all active debate sessions
            active_debates = self._debate_store.get_active_debates()
            
            # Group debates by symbol/market
            debates_by_symbol = self._group_debates_by_symbol(active_debates)
            
            for symbol, debates in debates_by_symbol.items():
                try:
                    context = self._build_debate_context(symbol, debates)
                    if context:
                        # Store as feature snapshot
                        success = self._unified_manager.store_feature_snapshot(
                            symbol=symbol,
                            domain="prediction",
                            features=context.to_dict(),
                            source="debate_system"
                        )
                        
                        # Create debate risk signal if significant
                        if context.health_score < 0.7 or context.active_debates > 0:
                            self._create_debate_risk_signal(context)
                        
                        if success:
                            processed_count += 1
                            
                except Exception as e:
                    logger.warning(f"Failed to process debate context for {symbol}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Failed to process debate signals: {e}")
            
        return processed_count
    
    def get_debate_context_for_symbol(self, symbol: str) -> Optional[DebateContext]:
        """Get cached debate context for a symbol"""
        cached = self._context_cache.get(symbol)
        if cached and (time.time() - cached.cache_timestamp) < self._cache_ttl:
            return cached
        
        # Build fresh context
        active_debates = self._debate_store.get_active_debates_for_symbol(symbol)
        if not active_debates:
            return None
            
        context = self._build_debate_context(symbol, active_debates)
        if context:
            self._context_cache[symbol] = context
            
        return context
    
    def calculate_risk_adjustment(self, symbol: str, base_size: int) -> Optional[DebateRiskAdjustment]:
        """Calculate risk adjustment based on debate context"""
        context = self.get_debate_context_for_symbol(symbol)
        if not context:
            return None
        
        try:
            # Use the existing risk multiplier logic
            adjustment = self._risk_multiplier.calculate_adjustment(
                symbol=symbol,
                base_size=base_size,
                debate_status=context.debate_status,
                alert_counts=context.recent_alerts
            )
            
            return adjustment
            
        except Exception as e:
            logger.warning(f"Failed to calculate risk adjustment for {symbol}: {e}")
            return None
    
    def _group_debates_by_symbol(self, debates: List[Any]) -> Dict[str, List[Any]]:
        """Group active debates by symbol"""
        debates_by_symbol = {}
        
        for debate in debates:
            try:
                symbol = getattr(debate, 'instrument', None) or getattr(debate, 'symbol', None)
                if symbol:
                    if symbol not in debates_by_symbol:
                        debates_by_symbol[symbol] = []
                    debates_by_symbol[symbol].append(debate)
            except Exception as e:
                logger.warning(f"Failed to process debate in grouping: {e}")
                continue
                
        return debates_by_symbol
    
    def _build_debate_context(self, symbol: str, debates: List[Any]) -> Optional[DebateContext]:
        """Build debate context from debate data"""
        try:
            if not debates:
                return None
            
            # Calculate basic metrics
            active_count = len(debates)
            last_activity = max(
                getattr(debate, 'last_activity', 0) or 0 
                for debate in debates
            )
            
            # Determine overall status
            statuses = [getattr(debate, 'status', 'unknown') for debate in debates]
            if 'critical' in statuses:
                overall_status = 'critical'
            elif 'warning' in statuses:
                overall_status = 'warning'
            elif 'active' in statuses:
                overall_status = 'active'
            else:
                overall_status = 'healthy'
            
            # Calculate health score (0-1)
            health_score = self._calculate_health_score(debates)
            
            # Get recent alerts
            recent_alerts = self._get_recent_alerts(symbol)
            
            # Calculate confidence level
            confidence = self._calculate_confidence_level(debates, health_score)
            
            return DebateContext(
                symbol=symbol,
                debate_status=overall_status,
                health_score=health_score,
                active_debates=active_count,
                recent_alerts=recent_alerts,
                last_activity=last_activity,
                confidence_level=confidence,
                cache_timestamp=time.time()  # Explicit cache timestamp
            )
            
        except Exception as e:
            logger.warning(f"Failed to build debate context for {symbol}: {e}")
            return None
    
    def _calculate_health_score(self, debates: List[Any]) -> float:
        """Calculate overall health score from debates"""
        try:
            if not debates:
                return 1.0  # No debates = healthy by default
            
            health_factors = []
            
            for debate in debates:
                # Status contribution
                status = getattr(debate, 'status', 'healthy')
                if status == 'healthy':
                    health_factors.append(1.0)
                elif status == 'active':
                    health_factors.append(0.8)
                elif status == 'warning':
                    health_factors.append(0.6)
                elif status == 'critical':
                    health_factors.append(0.3)
                else:
                    health_factors.append(0.5)
                
                # Activity level (recent activity is good)
                last_activity = getattr(debate, 'last_activity', 0) or 0
                activity_age = time.time() - last_activity
                if activity_age < 3600:  # Less than 1 hour
                    health_factors.append(1.0)
                elif activity_age < 86400:  # Less than 1 day
                    health_factors.append(0.8)
                else:
                    health_factors.append(0.5)
            
            # Average all factors
            return sum(health_factors) / len(health_factors) if health_factors else 0.5
            
        except Exception as e:
            logger.warning(f"Failed to calculate health score: {e}")
            return 0.5
    
    def _get_recent_alerts(self, symbol: str) -> Dict[str, int]:
        """Get recent alert counts for a symbol"""
        try:
            # This would query the debate alert system
            # For now, return placeholder data with guaranteed total key
            return {
                "accuracy_warnings": 0,
                "consensus_drift": 0,
                "agent_conflicts": 0,
                "total": 0  # Always present for downstream consumers
            }
        except Exception as e:
            logger.warning(f"Failed to get recent alerts for {symbol}: {e}")
            # Always return total key even on error
            return {"total": 0}
    
    def _calculate_confidence_level(self, debates: List[Any], health_score: float) -> float:
        """Calculate overall confidence in debate outcomes"""
        try:
            if not debates:
                return 0.5
            
            confidence_factors = [health_score]
            
            # Number of participants (more participants = higher confidence)
            for debate in debates:
                participants = getattr(debate, 'participant_count', 0) or 0
                if participants >= 5:
                    confidence_factors.append(0.9)
                elif participants >= 3:
                    confidence_factors.append(0.7)
                else:
                    confidence_factors.append(0.5)
            
            # Debate depth (more arguments = higher confidence)
            for debate in debates:
                argument_count = getattr(debate, 'argument_count', 0) or 0
                if argument_count >= 10:
                    confidence_factors.append(0.9)
                elif argument_count >= 5:
                    confidence_factors.append(0.7)
                else:
                    confidence_factors.append(0.5)
            
            return sum(confidence_factors) / len(confidence_factors) if confidence_factors else 0.5
            
        except Exception as e:
            logger.warning(f"Failed to calculate confidence level: {e}")
            return 0.5
    
    def _create_debate_risk_signal(self, context: DebateContext):
        """Create a debate risk signal"""
        try:
            # Calculate base multiplier from status
            if context.debate_status == 'critical':
                base_multiplier = 0.5
            elif context.debate_status == 'warning':
                base_multiplier = 0.7
            elif context.debate_status == 'active':
                base_multiplier = 0.85
            else:
                base_multiplier = 1.0
            
            # Get explicit risk adjustment from the risk multiplier engine
            adjustment = self.calculate_risk_adjustment(context.symbol, base_size=100)  # Standard base size
            effective_multiplier = adjustment.multiplier if adjustment else base_multiplier
            
            success = self._unified_manager.create_debate_risk_signal(
                symbol=context.symbol,
                multiplier=effective_multiplier,
                status=context.debate_status,
                features={
                    "base_status_multiplier": base_multiplier,
                    "effective_multiplier": effective_multiplier,
                    "health_score": context.health_score,
                    "active_debates": context.active_debates,
                    "confidence_level": context.confidence_level,
                    "recent_alerts_total": context.recent_alerts.get("total", 0),
                    "last_activity": context.last_activity,
                    "risk_adjustment_reason": adjustment.reason if adjustment else "No adjustment",
                    "should_warn": adjustment.should_warn if adjustment else False,
                    "adjusted_size": adjustment.adjusted_size if adjustment else 100,
                },
                source="debate_system"
            )
            
            if success:
                logger.info(f"Created debate risk signal for {context.symbol}: {context.debate_status} (multiplier: {effective_multiplier:.2f})")
                
        except Exception as e:
            logger.warning(f"Failed to create debate risk signal for {context.symbol}: {e}")


# Singleton instance
_integrator: Optional[DebateSignalIntegrator] = None


def get_debate_signal_integrator() -> DebateSignalIntegrator:
    """Get the singleton debate signal integrator"""
    global _integrator
    if _integrator is None:
        _integrator = DebateSignalIntegrator()
    return _integrator


def run_debate_signal_processing() -> int:
    """Run debate signal processing and return count of processed symbols"""
    integrator = get_debate_signal_integrator()
    return integrator.process_all_debate_signals()

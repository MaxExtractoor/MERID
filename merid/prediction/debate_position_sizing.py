"""
Debate-Aware Position Sizing
Integrates debate backtest results into Kalshi position sizing decisions.
"""

import asyncio
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
import statistics
import logging

from merid.prediction.debate_backtest import get_debate_backtester, BacktestResult
from merid.prediction.debate import get_debate_store
from merid.prediction.portfolio_risk_manager import get_portfolio_risk_manager, check_portfolio_risk_limits
from merid.prediction.agent_risk_quotas import get_agent_risk_quota_manager, check_agent_risk_quota
from merid.prediction.debate_deployment import get_debate_deployment_manager, is_debate_enabled, get_effective_multiplier, should_log_shadow_recommendation
from core.slo_monitor import SLOMonitor
from config.trading_constants import (
    DEBATE_BOOST_STRONG_THRESHOLD, DEBATE_BOOST_MEDIUM_THRESHOLD, DEBATE_BOOST_MILD_THRESHOLD,
    DEBATE_NORMAL_THRESHOLD, DEBATE_REDUCE_THRESHOLD, DEBATE_AVOID_THRESHOLD,
    DEBATE_BOOST_WIN_RATE, DEBATE_NORMAL_WIN_RATE, DEBATE_REDUCE_WIN_RATE,
    DEBATE_MIN_SAMPLES,
    DEBATE_MULT_BOOST_STRONG, DEBATE_MULT_BOOST_MEDIUM, DEBATE_MULT_BOOST_MILD,
    DEBATE_MULT_NORMAL, DEBATE_MULT_REDUCE, DEBATE_MULT_AVOID,
    DEBATE_PERFORMANCE_CACHE_TTL_S,
)

logger = logging.getLogger("merid.prediction.debate_position_sizing")


@dataclass
class DebatePerformanceProfile:
    """Performance profile for a Kalshi symbol based on debate history."""
    symbol: str
    avg_improvement_pct: float
    debate_count: int
    success_rate: float
    avg_debate_lift: float
    last_updated: float
    confidence_level: float
    recommendation: str  # "boost", "normal", "reduce", "avoid"


class DebateAwarePositionSizer:
    """Integrates debate performance into Kalshi position sizing decisions."""

    _MAX_CONCURRENT_BACKTESTS = 2  # prevent thundering-herd on the backtest engine

    def __init__(self):
        self.backtester = get_debate_backtester()
        self.debate_store = get_debate_store()
        self.slo_monitor = SLOMonitor.get_instance()
        self.deployment_manager = get_debate_deployment_manager()
        self.performance_cache: Dict[str, DebatePerformanceProfile] = {}
        self.cache_ttl = DEBATE_PERFORMANCE_CACHE_TTL_S
        self.last_cache_update = 0.0
        self._backtest_semaphore: Optional[asyncio.Semaphore] = None  # lazy-init on event loop
        self._inflight: Dict[str, asyncio.Future] = {}  # symbol -> in-progress backtest future
    
    async def get_position_multiplier(
        self,
        symbol: str,
        base_kelly_fraction: float,
        position_size_dollars: float = None,
        total_equity: float = None,
        portfolio_var: float = None,
        agent_id: str = None,
        asset: Optional[str] = None,
    ) -> float:
        """
        Get position size multiplier based on debate performance and risk checks.
        
        Args:
            symbol: Kalshi symbol (e.g., 'KXBTCD-25JUN-T100000')
            base_kelly_fraction: Base Kelly fraction from edge model
            position_size_dollars: Position size in dollars (for risk checks)
            total_equity: Total portfolio equity (for risk checks)
            portfolio_var: Portfolio VaR (for risk checks)
            agent_id: Agent requesting the position (for quota checks)
            
        Returns:
            Multiplier to apply to base position (0.5 to 2.0)
        """
        try:
            # Check if debate features are enabled for this symbol
            if not self.deployment_manager.is_debate_enabled(symbol):
                # Log shadow recommendation if needed
                if self.deployment_manager.should_log_shadow_recommendation(symbol):
                    # Calculate what the debate multiplier would be
                    profile = await self._get_performance_profile(symbol)
                    if profile:
                        debate_multiplier = self._calculate_multiplier(profile, base_kelly_fraction, asset=asset)
                        self.deployment_manager.log_shadow_recommendation(
                            symbol=symbol,
                            base_kelly=base_kelly_fraction,
                            debate_multiplier=debate_multiplier,
                            agent_id=agent_id,
                            reason="Debate system disabled - shadow recommendation"
                        )
                
                logger.debug(f"Debate features disabled for {symbol}, using base position")
                return 1.0
            
            # Get performance profile
            profile = await self._get_performance_profile(symbol)
            
            if not profile:
                # No debate history available
                logger.debug(f"No debate history for {symbol}, using base position")
                return 1.0
            
            # Calculate multiplier based on performance (with correlation adjustment)
            multiplier = self._calculate_multiplier(profile, base_kelly_fraction, asset=asset)
            
            # Apply deployment mode and kill switch
            effective_multiplier = self.deployment_manager.get_effective_multiplier(symbol, multiplier)
            
            # Log shadow recommendation if deployment mode requires it
            if self.deployment_manager.should_log_shadow_recommendation(symbol):
                self.deployment_manager.log_shadow_recommendation(
                    symbol=symbol,
                    base_kelly=base_kelly_fraction,
                    debate_multiplier=multiplier,
                    agent_id=agent_id,
                    reason="Canary mode - symbol not in canary set"
                )
            
            # Apply safety caps
            adjusted_kelly = base_kelly_fraction * effective_multiplier
            max_safe_kelly = min(base_kelly_fraction * 2.0, 0.5)  # Cap at 2x boost or 50% absolute
            final_kelly = min(adjusted_kelly, max_safe_kelly)
            final_multiplier = final_kelly / base_kelly_fraction if base_kelly_fraction > 0 else 1.0
            
            # Portfolio risk checks (if portfolio data provided)
            portfolio_adjusted_multiplier = final_multiplier
            portfolio_violations = []
            
            if all([position_size_dollars, total_equity, portfolio_var]):
                try:
                    base_risk = position_size_dollars
                    portfolio_adjusted_multiplier, risk_check = await check_portfolio_risk_limits(
                        symbol, base_risk, final_multiplier, total_equity, portfolio_var
                    )
                    portfolio_violations = risk_check.get("risk_violations", [])
                    
                    # Recalculate final Kelly based on portfolio adjustment
                    if portfolio_adjusted_multiplier != final_multiplier:
                        final_kelly = base_kelly_fraction * portfolio_adjusted_multiplier
                        final_multiplier = portfolio_adjusted_multiplier
                        
                except Exception as e:
                    logger.warning(f"Portfolio risk check failed for {symbol}: {e}")
                    # Continue with individual multiplier
            
            # Agent risk quota checks (if agent provided)
            agent_adjusted_multiplier = final_multiplier
            agent_violations = []
            
            if agent_id and all([position_size_dollars, total_equity]):
                try:
                    quota_check = await check_agent_risk_quota(
                        symbol, agent_id, position_size_dollars, total_equity
                    )
                    
                    if not quota_check.passed:
                        agent_adjusted_multiplier = quota_check.recommended_multiplier or 1.0
                        agent_violations = [quota_check.violation_type]
                        
                        # Recalculate final Kelly based on agent quota adjustment
                        final_kelly = base_kelly_fraction * agent_adjusted_multiplier
                        final_multiplier = agent_adjusted_multiplier
                        
                except Exception as e:
                    logger.warning(f"Agent quota check failed for {agent_id}: {e}")
                    # Continue with portfolio-adjusted multiplier
            
            # Track sizing decisions
            self.slo_monitor.track_slo(
                metric_name="debate.position_sizing.decision",
                success=True,
                total=1,
                metadata={
                    "symbol": symbol,
                    "agent_id": agent_id,
                    "base_kelly": base_kelly_fraction,
                    "performance_multiplier": multiplier,
                    "safety_cap_multiplier": final_kelly / base_kelly_fraction if base_kelly_fraction > 0 else 1.0,
                    "portfolio_adjusted_multiplier": portfolio_adjusted_multiplier,
                    "agent_adjusted_multiplier": agent_adjusted_multiplier,
                    "final_multiplier": final_multiplier,
                    "final_kelly": final_kelly,
                    "recommendation": profile.recommendation,
                    "avg_improvement": profile.avg_improvement_pct,
                    "debate_count": profile.debate_count,
                    "safety_cap_applied": final_multiplier < multiplier,
                    "portfolio_violations": len(portfolio_violations),
                    "agent_violations": len(agent_violations),
                    "portfolio_risk_check": all([position_size_dollars, total_equity, portfolio_var]),
                    "agent_quota_check": all([agent_id, position_size_dollars, total_equity])
                }
            )
            
            logger.info(
                f"Debate-aware sizing for {symbol} (agent: {agent_id}): {base_kelly_fraction:.3f} → {final_multiplier:.2f} "
                f"(portfolio_violations: {len(portfolio_violations)}, agent_violations: {len(agent_violations)})"
            )
            
            return final_multiplier
            
        except Exception as e:
            logger.warning(f"Error calculating debate-aware position for {symbol}: {e}")
            return 1.0  # Fail-safe to base position
    
    def _get_semaphore(self) -> asyncio.Semaphore:
        """Lazy-initialize the semaphore on the running event loop."""
        if self._backtest_semaphore is None:
            self._backtest_semaphore = asyncio.Semaphore(self._MAX_CONCURRENT_BACKTESTS)
        return self._backtest_semaphore

    async def _get_performance_profile(self, symbol: str) -> Optional[DebatePerformanceProfile]:
        """Get or calculate performance profile for a symbol.

        Concurrent callers for the *same* symbol coalesce on a single in-flight
        backtest rather than each launching an independent one.  A semaphore
        additionally caps the total number of simultaneous backtests across all
        symbols to ``_MAX_CONCURRENT_BACKTESTS``.
        """
        current_time = time.time()

        # Cache hit — no backtest needed
        if (symbol in self.performance_cache and
                current_time - self.performance_cache[symbol].last_updated < self.cache_ttl):
            return self.performance_cache[symbol]

        # If another coroutine is already computing this symbol, await its result
        if symbol in self._inflight:
            try:
                return await asyncio.shield(self._inflight[symbol])
            except Exception:
                pass  # fall through to recompute

        # Create a Future so subsequent callers can piggyback
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._inflight[symbol] = fut

        try:
            async with self._get_semaphore():
                profile = await self._calculate_performance_profile(symbol)
            if profile:
                self.performance_cache[symbol] = profile
            fut.set_result(profile)
            return profile
        except Exception as exc:
            if not fut.done():
                fut.set_exception(exc)
            return None
        finally:
            self._inflight.pop(symbol, None)
    
    async def _calculate_performance_profile(self, symbol: str) -> Optional[DebatePerformanceProfile]:
        """Calculate performance profile from debate backtest data."""
        try:
            # Get recent backtest data (last 30 days)
            end_date = datetime.now(timezone.utc)
            start_date = end_date - timedelta(days=30)
            
            summary, results = await self.backtester.run_backtest(start_date, end_date, min_debates_per_symbol=1)
            
            # Find results for this symbol
            symbol_results = [r for r in results if r.symbol == symbol]
            
            if not symbol_results:
                return None
            
            # Aggregate results for this symbol
            improvements = [r.improvement_pct for r in symbol_results]
            avg_improvement = statistics.mean(improvements)
            total_debates = sum([r.debate_count for r in symbol_results])
            positive_markets = sum(1 for r in symbol_results if r.improvement_pct > 0)
            success_rate = positive_markets / len(symbol_results)
            avg_lift = statistics.mean([r.debate_lift for r in symbol_results])
            confidence = sum(1 for r in symbol_results if r.statistically_significant) / len(symbol_results)
            
            # Generate recommendation
            recommendation = self._generate_recommendation(avg_improvement, success_rate, total_debates)
            
            return DebatePerformanceProfile(
                symbol=symbol,
                avg_improvement_pct=avg_improvement,
                debate_count=total_debates,
                success_rate=success_rate,
                avg_debate_lift=avg_lift,
                last_updated=time.time(),
                confidence_level=confidence,
                recommendation=recommendation
            )
            
        except Exception as e:
            logger.warning(f"Error calculating performance profile for {symbol}: {e}")
            return None
    
    def _generate_recommendation(self, avg_improvement: float, success_rate: float, debate_count: int) -> str:
        """Generate position sizing recommendation based on performance."""
        if debate_count < DEBATE_MIN_SAMPLES:
            return "normal"  # Insufficient data

        if avg_improvement > DEBATE_BOOST_MILD_THRESHOLD and success_rate > DEBATE_BOOST_WIN_RATE:
            return "boost"  # Strong positive performance
        elif avg_improvement > DEBATE_NORMAL_THRESHOLD and success_rate > DEBATE_NORMAL_WIN_RATE:
            return "normal"  # Moderate positive performance
        elif avg_improvement < DEBATE_AVOID_THRESHOLD or success_rate < DEBATE_REDUCE_WIN_RATE:
            return "avoid"  # Poor performance
        elif avg_improvement < DEBATE_REDUCE_THRESHOLD:
            return "reduce"  # Slightly negative performance
        else:
            return "normal"  # Neutral performance

    def _calculate_multiplier(
        self,
        profile: DebatePerformanceProfile,
        base_kelly: float,
        asset: Optional[str] = None,
    ) -> float:
        """Calculate position size multiplier, further reduced by inter-asset correlation.

        The debate-history multiplier is computed first, then scaled down by
        ``CorrelationTracker.get_cluster_factor(asset)`` so that correlated
        positions (e.g. BTC + ETH open simultaneously) don't over-concentrate.
        """
        if profile.recommendation == "boost":
            if profile.avg_improvement_pct > DEBATE_BOOST_STRONG_THRESHOLD:
                mult = DEBATE_MULT_BOOST_STRONG
            elif profile.avg_improvement_pct > DEBATE_BOOST_MEDIUM_THRESHOLD:
                mult = DEBATE_MULT_BOOST_MEDIUM
            else:
                mult = DEBATE_MULT_BOOST_MILD
        elif profile.recommendation == "normal":
            mult = DEBATE_MULT_NORMAL
        elif profile.recommendation == "reduce":
            mult = DEBATE_MULT_REDUCE
        elif profile.recommendation == "avoid":
            mult = DEBATE_MULT_AVOID
        else:
            mult = DEBATE_MULT_NORMAL

        # Apply correlation-adjusted factor (Sprint D integration)
        if asset:
            try:
                from merid.risk.correlation import get_correlation_tracker
                corr_factor = get_correlation_tracker().get_cluster_factor(asset)
                if corr_factor < 1.0:
                    logger.debug(
                        "Correlation factor %.2f applied to %s multiplier (%.2f → %.2f)",
                        corr_factor, asset, mult, mult * corr_factor,
                    )
                    mult = mult * corr_factor
            except Exception as _ce:
                logger.debug("Correlation factor unavailable for %s: %s", asset, _ce)

        return mult
    
    async def get_performance_summary(self) -> Dict[str, Any]:
        """Get summary of debate performance across all symbols."""
        if not self.performance_cache:
            return {"message": "No performance data available"}
        
        profiles = list(self.performance_cache.values())
        
        return {
            "total_symbols": len(profiles),
            "avg_improvement": statistics.mean([p.avg_improvement_pct for p in profiles]),
            "total_debates": sum([p.debate_count for p in profiles]),
            "recommendations": {
                "boost": len([p for p in profiles if p.recommendation == "boost"]),
                "normal": len([p for p in profiles if p.recommendation == "normal"]),
                "reduce": len([p for p in profiles if p.recommendation == "reduce"]),
                "avoid": len([p for p in profiles if p.recommendation == "avoid"])
            },
            "top_performers": sorted(
                [(p.symbol, p.avg_improvement_pct) for p in profiles],
                key=lambda x: x[1],
                reverse=True
            )[:5],
            "worst_performers": sorted(
                [(p.symbol, p.avg_improvement_pct) for p in profiles],
                key=lambda x: x[1]
            )[:5]
        }
    
    async def get_profile_for_symbol(self, symbol: str) -> Optional[DebatePerformanceProfile]:
        """
        Get performance profile for a symbol (public API wrapper).
        
        Args:
            symbol: Kalshi symbol
            
        Returns:
            Performance profile or None if no data available
        """
        return await self._get_performance_profile(symbol)
    
    def clear_cache(self):
        """Clear the performance cache."""
        self.performance_cache.clear()
        logger.info("Debate performance cache cleared")


# Global instance
_sizer_instance: Optional[DebateAwarePositionSizer] = None


def get_debate_position_sizer() -> DebateAwarePositionSizer:
    """Get the global debate-aware position sizer instance."""
    global _sizer_instance
    if _sizer_instance is None:
        _sizer_instance = DebateAwarePositionSizer()
    return _sizer_instance


async def get_debate_adjusted_position_size(
    symbol: str,
    base_kelly_fraction: float,
    position_size_dollars: float = None,
    total_equity: float = None,
    portfolio_var: float = None,
    agent_id: str = None,
    asset: Optional[str] = None,
) -> float:
    """
    Convenience function to get debate-adjusted position size with all risk checks.
    
    Args:
        symbol: Kalshi symbol
        base_kelly_fraction: Base Kelly fraction
        position_size_dollars: Position size in dollars (for risk checks)
        total_equity: Total portfolio equity (for risk checks)
        portfolio_var: Portfolio VaR (for risk checks)
        agent_id: Agent requesting the position (for quota checks)
        
    Returns:
        Adjusted Kelly fraction
    """
    sizer = get_debate_position_sizer()
    multiplier = await sizer.get_position_multiplier(
        symbol, base_kelly_fraction, position_size_dollars,
        total_equity, portfolio_var, agent_id, asset=asset,
    )
    return base_kelly_fraction * multiplier

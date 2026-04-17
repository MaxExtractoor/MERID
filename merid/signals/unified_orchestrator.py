"""
Unified Signal Orchestrator

Coordinates all signal processing components into a cohesive pipeline:
- Crypto fear & greed + volume features
- Debate risk integration  
- Sentiment analysis
- Enhanced Kalshi signal generation
- CQI-based gating
- UI dashboard data

This is the main entry point for the cross-domain signal system.
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime, timezone

from merid.signals.crypto_features import run_crypto_feature_processing
from merid.signals.debate_integration import run_debate_signal_processing
from merid.signals.sentiment_integration import run_sentiment_signal_processing
from merid.signals.enhanced_kalshi_generator import run_enhanced_kalshi_generation
from merid.signals.cqi_gating import update_all_domain_quality, gate_signal_with_cqi
from merid.signals.unified_manager import get_unified_signal_manager
from merid.signals.store import get_signal_store
from utils.logger import get_logger
from config.trading_constants import KALSHI_EDGE_THRESHOLD_PCT, KALSHI_MAX_SIGNALS_PER_RUN

logger = get_logger("signals.unified_orchestrator")


@dataclass
class OrchestratorConfig:
    """Configuration for the unified signal orchestrator"""
    enable_crypto_features: bool = True
    enable_debate_integration: bool = True
    enable_sentiment_integration: bool = True
    enable_kalshi_generation: bool = True
    enable_cqi_gating: bool = True
    
    # Processing intervals (seconds)
    crypto_interval: int = 300  # 5 minutes
    debate_interval: int = 600  # 10 minutes
    sentiment_interval: int = 300  # 5 minutes
    kalshi_interval: int = 180  # 3 minutes
    cqi_update_interval: int = 900  # 15 minutes
    
    # Kalshi signal generation
    kalshi_edge_threshold: float = KALSHI_EDGE_THRESHOLD_PCT
    max_signals_per_run: int = KALSHI_MAX_SIGNALS_PER_RUN

    # Forecaster ensemble sweep (runs after enhanced Kalshi generation)
    enable_forecaster_ensemble: bool = True
    ensemble_interval: int = 300  # 5 minutes


@dataclass
class ProcessingResults:
    """Results from a processing run"""
    timestamp: float
    duration: float
    
    crypto_processed: int
    debate_processed: int
    sentiment_processed: int
    
    kalshi_generated: int
    kalshi_suppressed: int
    kalshi_insufficient_data: int
    ensemble_forecasts: int
    
    cqi_gated_allowed: int
    cqi_gated_throttled: int
    cqi_gated_suppressed: int
    
    total_signals_stored: int
    errors: List[str]


class UnifiedSignalOrchestrator:
    """Orchestrates all signal processing components"""
    
    def __init__(self, config: Optional[OrchestratorConfig] = None):
        self._config = config or OrchestratorConfig()
        self._unified_manager = get_unified_signal_manager()
        self._signal_store = get_signal_store()
        
        # Last processing times
        self._last_crypto_time = 0.0
        self._last_debate_time = 0.0
        self._last_sentiment_time = 0.0
        self._last_kalshi_time = 0.0
        self._last_cqi_time = 0.0
        self._last_ensemble_time = 0.0
        
        # Performance tracking
        self._processing_history: List[ProcessingResults] = []
        self._max_history = 100  # Keep last 100 runs
        
        # Caching for expensive operations
        self._cqi_summary_cache: Optional[Dict[str, Any]] = None
        self._cqi_cache_ttl = 60  # Cache CQI summary for 1 minute
    
    def run_full_pipeline(self) -> ProcessingResults:
        """Run the complete signal processing pipeline"""
        start_time = time.time()
        results = ProcessingResults(
            timestamp=start_time,
            duration=0.0,
            crypto_processed=0,
            debate_processed=0,
            sentiment_processed=0,
            kalshi_generated=0,
            kalshi_suppressed=0,
            kalshi_insufficient_data=0,
            ensemble_forecasts=0,
            cqi_gated_allowed=0,
            cqi_gated_throttled=0,
            cqi_gated_suppressed=0,
            total_signals_stored=0,
            errors=[]
        )
        
        try:
            logger.info("Starting unified signal processing pipeline")
            
            # Step 1: Update CQI metrics (used for gating)
            if self._should_process("cqi"):
                try:
                    cqi_summary = update_all_domain_quality()
                    logger.info(f"CQI metrics updated for {len(cqi_summary.get('domains', {}))} domains")
                except Exception as e:
                    results.errors.append(f"CQI update failed: {e}")
                    logger.warning(f"CQI update failed: {e}")
            
            # Step 2: Process crypto features (fear & greed + volume)
            if self._should_process("crypto") and self._config.enable_crypto_features:
                try:
                    results.crypto_processed = run_crypto_feature_processing()
                    logger.info(f"Processed crypto features for {results.crypto_processed} symbols")
                except Exception as e:
                    results.errors.append(f"Crypto feature processing failed: {e}")
                    logger.warning(f"Crypto feature processing failed: {e}")
            
            # Step 3: Process debate signals
            if self._should_process("debate") and self._config.enable_debate_integration:
                try:
                    results.debate_processed = run_debate_signal_processing()
                    logger.info(f"Processed debate signals for {results.debate_processed} symbols")
                except Exception as e:
                    results.errors.append(f"Debate signal processing failed: {e}")
                    logger.warning(f"Debate signal processing failed: {e}")
            
            # Step 4: Process sentiment signals
            if self._should_process("sentiment") and self._config.enable_sentiment_integration:
                try:
                    results.sentiment_processed = run_sentiment_signal_processing()
                    logger.info(f"Processed sentiment signals for {results.sentiment_processed} symbols")
                except Exception as e:
                    results.errors.append(f"Sentiment signal processing failed: {e}")
                    logger.warning(f"Sentiment signal processing failed: {e}")
            
            # Step 5: Generate enhanced Kalshi signals
            if self._should_process("kalshi") and self._config.enable_kalshi_generation:
                try:
                    # Get Kalshi markets (placeholder - would integrate with actual Kalshi API)
                    kalshi_markets = self._get_kalshi_markets()
                    
                    kalshi_results = run_enhanced_kalshi_generation(kalshi_markets)
                    results.kalshi_generated = kalshi_results.get("generated", 0)
                    results.kalshi_suppressed = kalshi_results.get("suppressed", 0)
                    results.kalshi_insufficient_data = kalshi_results.get("insufficient_data", 0)
                    
                    logger.info(f"Kalshi generation: {results.kalshi_generated} generated, {results.kalshi_suppressed} suppressed")
                    
                except Exception as e:
                    results.errors.append(f"Kalshi signal generation failed: {e}")
                    logger.warning(f"Kalshi signal generation failed: {e}")
            
            # Step 5b: Run calibration-weighted forecaster ensemble across live markets
            if self._should_process("ensemble") and self._config.enable_forecaster_ensemble:
                try:
                    results.ensemble_forecasts = self._run_forecaster_ensemble()
                    logger.info(f"Forecaster ensemble: {results.ensemble_forecasts} markets scored")
                except Exception as e:
                    results.errors.append(f"Forecaster ensemble failed: {e}")
                    logger.warning(f"Forecaster ensemble failed: {e}")

            # Step 6: Apply CQI gating to generated signals
            if self._config.enable_cqi_gating:
                try:
                    gating_results = self._apply_cqi_gating()
                    results.cqi_gated_allowed = gating_results.get("allowed", 0)
                    results.cqi_gated_throttled = gating_results.get("throttled", 0)
                    results.cqi_gated_suppressed = gating_results.get("suppressed", 0)
                    
                    logger.info(f"CQI gating: {results.cqi_gated_allowed} allowed, {results.cqi_gated_throttled} throttled, {results.cqi_gated_suppressed} suppressed")
                    
                except Exception as e:
                    results.errors.append(f"CQI gating failed: {e}")
                    logger.warning(f"CQI gating failed: {e}")
            
            # Step 7: Get final signal count
            try:
                signal_metrics = self._signal_store.get_signal_metrics()
                results.total_signals_stored = signal_metrics.get("feature_snapshots", 0)
            except Exception as e:
                results.errors.append(f"Signal metrics retrieval failed: {e}")
            
            # NOTE: individual component timers are updated inside _should_process()
            # at the moment each component is cleared to run — do NOT call
            # _update_processing_times() here as it would reset timers for
            # components that were skipped this cycle, delaying their next run.
            logger.info("Unified signal processing pipeline completed successfully")
            
        except Exception as e:
            results.errors.append(f"Pipeline failed: {e}")
            logger.error(f"Pipeline failed: {e}")
        
        finally:
            results.duration = time.time() - start_time
            
            # Store results
            self._processing_history.append(results)
            if len(self._processing_history) > self._max_history:
                self._processing_history.pop(0)
        
        return results
    
    def get_dashboard_data(self) -> Dict[str, Any]:
        """Get data for UI dashboards"""
        try:
            # Get signal metrics
            signal_metrics = self._signal_store.get_signal_metrics()
            
            # Get CQI summary (use cache if recent)
            if (self._cqi_summary_cache is None or 
                time.time() - self._cqi_summary_cache.get("timestamp", 0) > self._cqi_cache_ttl):
                cqi_summary = update_all_domain_quality()
                cqi_summary["timestamp"] = time.time()
                self._cqi_summary_cache = cqi_summary
            else:
                cqi_summary = self._cqi_summary_cache
            
            # Get recent processing results
            recent_results = self._processing_history[-5:] if self._processing_history else []
            
            # Get feature snapshots for dashboard
            dashboard_data = {
                # Signal overview
                "signal_metrics": signal_metrics,
                
                # Quality metrics (cached)
                "cqi_summary": cqi_summary,
                "overall_health": cqi_summary.get("overall_health", 0.0),
                "suppressed_domains": cqi_summary.get("suppressed_domains", []),
                "throttled_domains": cqi_summary.get("throttled_domains", []),
                
                # Recent activity
                "recent_processing": [
                    {
                        "timestamp": r.timestamp,
                        "duration": r.duration,
                        "crypto_processed": r.crypto_processed,
                        "debate_processed": r.debate_processed,
                        "sentiment_processed": r.sentiment_processed,
                        "kalshi_generated": r.kalshi_generated,
                        "total_signals": r.total_signals_stored,
                        "errors": len(r.errors)
                    }
                    for r in recent_results
                ],
                
                # Feature highlights
                "featured_signals": self._get_featured_signals(),
                
                # System status
                "system_status": {
                    "last_run": recent_results[-1].timestamp if recent_results else None,  # Use most recent
                    "error_count": sum(len(r.errors) for r in recent_results),
                    "processing_enabled": {
                        "crypto": self._config.enable_crypto_features,
                        "debate": self._config.enable_debate_integration,
                        "sentiment": self._config.enable_sentiment_integration,
                        "kalshi": self._config.enable_kalshi_generation,
                        "cqi_gating": self._config.enable_cqi_gating,
                    }
                }
            }
            
            return dashboard_data
            
        except Exception as e:
            logger.warning(f"Failed to get dashboard data: {e}")
            return {"error": str(e)}
    
    def _should_process(self, component: str) -> bool:
        """Check if a component should be processed based on interval"""
        now = time.time()
        
        if component == "crypto":
            if now - self._last_crypto_time >= self._config.crypto_interval:
                self._last_crypto_time = now
                return True
        elif component == "debate":
            if now - self._last_debate_time >= self._config.debate_interval:
                self._last_debate_time = now
                return True
        elif component == "sentiment":
            if now - self._last_sentiment_time >= self._config.sentiment_interval:
                self._last_sentiment_time = now
                return True
        elif component == "kalshi":
            if now - self._last_kalshi_time >= self._config.kalshi_interval:
                self._last_kalshi_time = now
                return True
        elif component == "cqi":
            if now - self._last_cqi_time >= self._config.cqi_update_interval:
                self._last_cqi_time = now
                return True
        elif component == "ensemble":
            if now - self._last_ensemble_time >= self._config.ensemble_interval:
                self._last_ensemble_time = now
                return True

        return False
    
    def _run_forecaster_ensemble(self) -> int:
        """Run the calibration-weighted ForecasterRegistry across all live Kalshi markets.

        For each active market in the catalog, calls ``predict_all()`` which:
        1. Runs all 6 registered forecasters (momentum, mean_reversion, macro_regime,
           orderbook, time_series, sentiment)
        2. Weights each by its Brier-calibrated score from CalibrationStore
        3. Returns a single ``EnsembleForecast`` with ``p_ensemble`` and per-forecaster breakdown
        4. Logs the forecast to CalibrationStore for future weight updates

        The ensemble result is stored in SignalStore under domain "ensemble" so
        downstream consumers (trading agents, dashboard) can read it.
        """
        from merid.prediction.forecasters.registry import get_forecaster_registry
        from datetime import timezone

        registry = get_forecaster_registry()
        markets = self._get_kalshi_markets()
        scored = 0

        for market in markets[:self._config.max_signals_per_run]:
            try:
                ticker = market.get("ticker", "")
                if not ticker:
                    continue

                # Extract market data — present on catalog objects, optional on dict markets
                implied_yes = float(market.get("implied_yes", market.get("yes_bid", 0.5) or 0.5))
                implied_no = 1.0 - implied_yes
                volume = float(market.get("volume", 0) or 0)
                open_interest = float(market.get("open_interest", 0) or 0)
                bid = market.get("best_bid") or market.get("bid")
                ask = market.get("best_ask") or market.get("ask")
                bid_f = float(bid) / 100.0 if bid is not None else None
                ask_f = float(ask) / 100.0 if ask is not None else None
                expiry = market.get("expiry_seconds")  # seconds to expiry if available
                minutes_to_expiry = float(expiry) / 60.0 if expiry else None
                asset = market.get("symbol") or market.get("asset", "")
                category = market.get("domain", "prediction")

                ensemble = registry.predict_all(
                    market_id=ticker,
                    implied_yes=implied_yes,
                    implied_no=implied_no,
                    volume=volume,
                    open_interest=open_interest,
                    minutes_to_expiry=minutes_to_expiry,
                    asset=asset or None,
                    timeframe=market.get("timeframe"),
                    bid=bid_f,
                    ask=ask_f,
                    category=category,
                )

                if ensemble is None:
                    continue

                # Store ensemble result for downstream consumers
                try:
                    self._signal_store.store_feature_snapshot(
                        symbol=ticker,
                        domain="ensemble",
                        features={
                            "p_ensemble": ensemble.p_ensemble,
                            "confidence": ensemble.confidence,
                            "forecaster_count": len(ensemble.forecasts),
                            "weights": ensemble.weights_used,
                            "implied_yes": implied_yes,
                            "edge_pct": round((ensemble.p_ensemble - implied_yes) * 100, 2),
                            "bucket": ensemble.bucket,
                        },
                    )
                except Exception:
                    pass  # Signal store unavailable — ensemble still logged to CalibrationStore

                scored += 1

            except Exception as exc:
                logger.debug("Ensemble forecast failed for %s: %s", market.get("ticker", "?"), exc)

        return scored

    def _update_processing_times(self):
        """Update all processing times to current time"""
        now = time.time()
        self._last_crypto_time = now
        self._last_debate_time = now
        self._last_sentiment_time = now
        self._last_kalshi_time = now
        self._last_cqi_time = now
    
    # Static fallback for when the catalog is unavailable on first call
    _KALSHI_MARKET_FALLBACK: List[Dict[str, Any]] = []

    def _get_kalshi_markets(self) -> List[Dict[str, Any]]:
        """Return active Kalshi markets from the live catalog.

        Falls back to the last known snapshot (or an empty list on cold start)
        rather than hardcoded fake tickers, so signal generation uses real
        market data when the catalog has been populated.
        """
        try:
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            catalog = get_market_catalog()
            # get_all_markets() returns CatalogMarket objects; filter to tradeable
            all_cat = catalog.get_all_markets()
            # Prefer high-volume markets (volume_fp > 0) and known categories
            active = [
                m for m in all_cat
                if getattr(m, 'category', None) in (
                    'crypto', 'economics', 'financials', 'politics', 'climate', 'tech'
                ) or (getattr(m, 'volume', 0) or 0) > 0
            ] or all_cat  # fall back to everything if filters yield nothing
            if active:
                # Normalise to the domain schema expected by enhanced_kalshi_generator
                markets = [
                    {
                        "ticker": (
                            m.market.market_id if hasattr(m, 'market') and m.market
                            else getattr(m, 'ticker', '') or ''
                        ),
                        "symbol": getattr(m, 'asset', '') or '',
                        "domain": "prediction",
                        "category": getattr(m, 'category', '') or '',
                    }
                    for m in active
                ]
                UnifiedSignalOrchestrator._KALSHI_MARKET_FALLBACK = markets
                return markets
        except Exception as e:
            logger.warning("Kalshi catalog unavailable for signal generation: %s", e)

        if not UnifiedSignalOrchestrator._KALSHI_MARKET_FALLBACK:
            logger.warning(
                "Kalshi market catalog is empty on cold start — "
                "signal generation will produce 0 signals until catalog refreshes"
            )
        return UnifiedSignalOrchestrator._KALSHI_MARKET_FALLBACK
    
    def _apply_cqi_gating(self) -> Dict[str, int]:
        """Apply CQI gating domain-level quality check.

        NOTE: Signal-level gating is applied inline during generation via
        gate_signal_with_cqi().  This method reports the domain summary from
        the CQI gating manager's in-memory state — it does NOT call non-existent
        SignalStore methods (get_recent_signals / bulk_update_signals).
        """
        from merid.signals.cqi_gating import get_cqi_gating_manager
        stats = {"allowed": 0, "throttled": 0, "suppressed": 0}
        try:
            mgr = get_cqi_gating_manager()
            summary = mgr.get_domain_quality_summary()
            stats["suppressed"] = len(summary.get("suppressed_domains", []))
            stats["throttled"] = len(summary.get("throttled_domains", []))
            stats["allowed"] = max(
                0,
                len(summary.get("domains", {})) - stats["suppressed"] - stats["throttled"],
            )
        except Exception as e:
            logger.warning("Failed to summarise CQI gating state: %s", e)
        return stats
    
    def _get_featured_signals(self) -> List[Dict[str, Any]]:
        """Get featured signals for dashboard display"""
        try:
            # Get recent high-quality signals across domains
            featured = []
            
            # Get latest crypto features
            crypto_features = self._signal_store.get_latest_features("BTC", "crypto")
            for feature in crypto_features[:3]:
                featured.append({
                    "type": "crypto_feature",
                    "symbol": feature.get("symbol", ""),
                    "data": feature.get("features", {}),
                    "timestamp": feature.get("timestamp", 0),
                })

            # Get latest debate signals
            debate_features = self._signal_store.get_latest_features("BTC", "prediction")
            for feature in debate_features[:3]:
                if "debate_status" in feature.get("features", {}):
                    featured.append({
                        "type": "debate_signal",
                        "symbol": feature.get("symbol", ""),
                        "data": feature.get("features", {}),
                        "timestamp": feature.get("timestamp", 0),
                    })
            
            # Sort by timestamp and limit
            featured.sort(key=lambda x: x.get("timestamp", 0), reverse=True)
            return featured[:10]
            
        except Exception as e:
            logger.warning(f"Failed to get featured signals: {e}")
            return []


# Singleton instance
_orchestrator: Optional[UnifiedSignalOrchestrator] = None


def get_unified_orchestrator(config: Optional[OrchestratorConfig] = None) -> UnifiedSignalOrchestrator:
    """Get the singleton unified signal orchestrator"""
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = UnifiedSignalOrchestrator(config)
    return _orchestrator


def run_unified_signal_pipeline() -> ProcessingResults:
    """Run the complete unified signal pipeline"""
    orchestrator = get_unified_orchestrator()
    return orchestrator.run_full_pipeline()


def get_signal_dashboard_data() -> Dict[str, Any]:
    """Get data for signal dashboards"""
    orchestrator = get_unified_orchestrator()
    return orchestrator.get_dashboard_data()

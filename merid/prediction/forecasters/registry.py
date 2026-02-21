"""Forecaster Registry — Manages heterogeneous forecasters and produces ensemble output.

Runs all registered forecasters on each market snapshot, logs each forecast
to CalibrationStore, and returns a calibration-weighted ensemble probability.

Sprint B + C integration point: the ensemble uses Brier-calibrated weights
from Sprint A's CalibrationStore to weight each forecaster's contribution.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from merid.prediction.forecasters.base import Forecaster, ForecastResult
from utils.logger import get_logger

logger = get_logger("merid.prediction.forecasters.registry")


@dataclass
class EnsembleForecast:
    """Calibration-weighted ensemble of multiple forecasters."""
    market_id: str
    p_ensemble: float               # Weighted average probability
    confidence: float               # Ensemble confidence
    forecasts: List[ForecastResult] # Individual forecaster outputs
    weights_used: Dict[str, float]  # forecaster_id -> calibration weight
    bucket: str                     # Category bucket for calibration

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market_id": self.market_id,
            "p_ensemble": round(self.p_ensemble, 6),
            "confidence": round(self.confidence, 4),
            "forecasts": [f.to_dict() for f in self.forecasts],
            "weights_used": {k: round(v, 4) for k, v in self.weights_used.items()},
            "bucket": self.bucket,
            "forecaster_count": len(self.forecasts),
        }


class ForecasterRegistry:
    """Manages all forecasters and produces ensemble predictions.

    Usage::

        registry = get_forecaster_registry()
        ensemble = registry.predict_all(
            market_id="KXBTC-26FEB-T95000",
            implied_yes=0.55, implied_no=0.45,
            volume=1200, open_interest=500,
            minutes_to_expiry=30,
            asset="BTC", timeframe="15m", category="crypto",
        )
        # ensemble.p_ensemble is the calibration-weighted probability
    """

    def __init__(self):
        self._forecasters: List[Forecaster] = []
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register the default heterogeneous forecasters."""
        from merid.prediction.forecasters.momentum import MomentumForecaster
        from merid.prediction.forecasters.mean_reversion import MeanReversionForecaster

        self._forecasters.append(MomentumForecaster())
        self._forecasters.append(MeanReversionForecaster())
        logger.info(
            f"ForecasterRegistry: {len(self._forecasters)} forecasters registered "
            f"({', '.join(f.forecaster_id for f in self._forecasters)})"
        )

    def register(self, forecaster: Forecaster) -> None:
        """Register an additional forecaster."""
        self._forecasters.append(forecaster)
        logger.info(f"Registered forecaster: {forecaster.forecaster_id}")

    @property
    def forecasters(self) -> List[Forecaster]:
        return list(self._forecasters)

    def predict_all(
        self,
        market_id: str,
        implied_yes: float,
        implied_no: float,
        volume: float,
        open_interest: float,
        minutes_to_expiry: Optional[float],
        asset: Optional[str] = None,
        timeframe: Optional[str] = None,
        bid: Optional[float] = None,
        ask: Optional[float] = None,
        category: Optional[str] = None,
        **kwargs,
    ) -> Optional[EnsembleForecast]:
        """Run all forecasters and produce a calibration-weighted ensemble.

        Each forecaster's output is:
        1. Logged to CalibrationStore for Brier tracking
        2. Weighted by its calibration score (Sprint C feedback loop)
        3. Combined into an ensemble probability

        Returns None if no forecaster produces a prediction.
        """
        bucket = (category or "unknown").lower()
        ts = time.time()
        results: List[ForecastResult] = []
        weights: Dict[str, float] = {}

        for forecaster in self._forecasters:
            try:
                result = forecaster.predict(
                    market_id=market_id,
                    implied_yes=implied_yes,
                    implied_no=implied_no,
                    volume=volume,
                    open_interest=open_interest,
                    minutes_to_expiry=minutes_to_expiry,
                    asset=asset,
                    timeframe=timeframe,
                    bid=bid,
                    ask=ask,
                    category=category,
                    **kwargs,
                )
                if result is None:
                    continue

                results.append(result)

                # Log forecast to CalibrationStore (Sprint A)
                self._log_forecast(result, bucket, market_id, ts)

                # Sprint E: Publish typed Forecast message to streaming bus
                self._publish_forecast_message(result, market_id, asset, category, timeframe)

                # Get calibration weight (Sprint C feedback loop)
                w = self._get_calibration_weight(result.forecaster_id, bucket)
                weights[result.forecaster_id] = w

            except Exception as exc:
                logger.debug(
                    f"Forecaster {forecaster.forecaster_id} failed for {market_id}: {exc}"
                )

        if not results:
            return None

        # Compute calibration-weighted ensemble probability
        total_weight = 0.0
        weighted_prob = 0.0
        weighted_confidence = 0.0

        for r in results:
            w = weights.get(r.forecaster_id, 1.0) * r.confidence
            weighted_prob += r.p_model * w
            weighted_confidence += r.confidence * weights.get(r.forecaster_id, 1.0)
            total_weight += w

        if total_weight > 0:
            p_ensemble = weighted_prob / total_weight
            ensemble_confidence = weighted_confidence / (
                sum(weights.get(r.forecaster_id, 1.0) for r in results) or 1.0
            )
        else:
            p_ensemble = sum(r.p_model for r in results) / len(results)
            ensemble_confidence = sum(r.confidence for r in results) / len(results)

        p_ensemble = max(0.02, min(0.98, p_ensemble))

        return EnsembleForecast(
            market_id=market_id,
            p_ensemble=round(p_ensemble, 4),
            confidence=round(min(1.0, ensemble_confidence), 3),
            forecasts=results,
            weights_used=weights,
            bucket=bucket,
        )

    def _log_forecast(
        self, result: ForecastResult, bucket: str, market_id: str, ts: float,
    ) -> None:
        """Log an individual forecast to CalibrationStore."""
        try:
            from merid.metrics.calibration import get_calibration_store
            store = get_calibration_store()
            store.record_forecast(
                forecaster_id=result.forecaster_id,
                bucket=bucket,
                market_id=market_id,
                p_model=result.p_model,
                timestamp=ts,
            )
        except Exception as exc:
            logger.debug(f"CalibrationStore log failed: {exc}")

    def _publish_forecast_message(
        self,
        result: ForecastResult,
        market_id: str,
        asset: str,
        category: str,
        timeframe: str,
    ) -> None:
        """Sprint E: Publish typed Forecast message to the streaming bus."""
        try:
            import asyncio
            from merid.swarm.messages import Forecast, publish_forecast
            msg = Forecast(
                forecaster_id=result.forecaster_id,
                model_type=getattr(result, "model_type", "unknown"),
                market_id=market_id,
                asset=asset or "",
                category=category or "",
                timeframe=timeframe or "",
                p_model=result.p_model,
                confidence=result.confidence,
                edge_estimate=result.components.get("edge_estimate", 0.0),
                components=result.components,
            )
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(publish_forecast(msg))
            except RuntimeError:
                pass  # No running event loop — skip publish
        except Exception as exc:
            logger.debug(f"Forecast message publish failed: {exc}")

    def _get_calibration_weight(self, forecaster_id: str, bucket: str) -> float:
        """Get calibration-based weight for a forecaster (Sprint C)."""
        try:
            from merid.metrics.calibration import get_calibration_store
            store = get_calibration_store()
            return store.get_weight(forecaster_id, bucket)
        except Exception:
            return 1.0  # Default weight if calibration unavailable


# ── Singleton ────────────────────────────────────────────────────────────

_registry: Optional[ForecasterRegistry] = None


def get_forecaster_registry() -> ForecasterRegistry:
    """Get or create the singleton ForecasterRegistry."""
    global _registry
    if _registry is None:
        from merid.prediction.forecasters.macro_regime import MacroRegimeForecaster
        from merid.prediction.forecasters.orderbook import OrderbookForecaster
        from merid.prediction.forecasters.time_series import TimeSeriesForecaster
        from merid.prediction.forecasters.sentiment import ExternalSentimentForecaster
        _registry = ForecasterRegistry()  # __init__ auto-registers momentum + mean_reversion
        _registry.register(MacroRegimeForecaster())
        _registry.register(OrderbookForecaster())
        _registry.register(TimeSeriesForecaster())
        _registry.register(ExternalSentimentForecaster())
    return _registry

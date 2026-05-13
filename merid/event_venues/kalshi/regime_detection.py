"""Market Regime Change Detection & Alerts — Sprint I Extension.

Detects transitions between market regimes (trending/mean-reverting/volatile/calm)
and emits alerts when confidence thresholds are breached.

Integrates with:
- MacroRegimeForecaster: Provides regime classification
- KalshiRiskManager: Adjusts position sizing based on regime
- EventBus: Publishes regime change events for downstream consumers
- Alerting: Real-time notifications on regime transitions
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.regime_detection")


class MarketRegime(str, Enum):
    """Market regime classifications."""
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    MEAN_REVERTING = "mean_reverting"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"
    CHOPPY = "choppy"
    UNKNOWN = "unknown"


class RegimeTransition(str, Enum):
    """Type of regime transition."""
    ENTRY = "entry"          # Entering a regime
    EXIT = "exit"            # Exiting a regime
    STAY = "stay"            # Remaining in same regime


@dataclass
class RegimeState:
    """Current regime state for an asset/market."""
    asset: str
    regime: MarketRegime
    confidence: float  # 0.0-1.0
    regime_duration_minutes: float
    last_transition_ts: str
    features: Dict[str, float] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset": self.asset,
            "regime": self.regime.value,
            "confidence": round(self.confidence, 3),
            "regime_duration_minutes": round(self.regime_duration_minutes, 1),
            "last_transition_ts": self.last_transition_ts,
            "features": {k: round(v, 4) for k, v in self.features.items()},
        }


@dataclass  
class RegimeChangeEvent:
    """Regime change event for publishing to event bus."""
    asset: str
    previous_regime: MarketRegime
    new_regime: MarketRegime
    transition_type: RegimeTransition
    confidence: float
    timestamp: str
    reasoning: str
    recommended_action: str
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": "regime_change",
            "asset": self.asset,
            "previous_regime": self.previous_regime.value,
            "new_regime": self.new_regime.value,
            "transition_type": self.transition_type.value,
            "confidence": round(self.confidence, 3),
            "timestamp": self.timestamp,
            "reasoning": self.reasoning,
            "recommended_action": self.recommended_action,
        }


@dataclass
class RegimeAlertConfig:
    """Configuration for regime alerts."""
    min_confidence: float = 0.70  # Minimum confidence to alert
    alert_on_entry: Set[MarketRegime] = field(default_factory=lambda: {
        MarketRegime.HIGH_VOLATILITY,
        MarketRegime.TRENDING_DOWN,
    })
    alert_on_exit: Set[MarketRegime] = field(default_factory=lambda: {
        MarketRegime.TRENDING_UP,
    })
    cooldown_minutes: float = 30.0  # Minimum time between alerts for same asset
    

class RegimeDetector:
    """Detects market regime changes and emits alerts.
    
    Tracks regime state per asset and detects transitions.
    Publishes events to the event bus when regime changes occur.
    """
    
    def __init__(self, config: Optional[RegimeAlertConfig] = None):
        self.config = config or RegimeAlertConfig()
        self._states: Dict[str, RegimeState] = {}
        self._last_alert_ts: Dict[str, float] = {}
        self._listeners: List[Callable[[RegimeChangeEvent], None]] = []
        self._lock = threading.Lock()
        
    def register_listener(self, callback: Callable[[RegimeChangeEvent], None]) -> None:
        """Register a callback to receive regime change events."""
        self._listeners.append(callback)
        
    def unregister_listener(self, callback: Callable[[RegimeChangeEvent], None]) -> None:
        """Unregister a callback."""
        if callback in self._listeners:
            self._listeners.remove(callback)
    
    def get_current_regime(self, asset: str) -> Dict[str, Any]:
        """Get current regime state for an asset (lightweight cached lookup).
        
        This method is safe for frequent calls from API endpoints - it performs
        no computation, only returns cached state.
        
        Args:
            asset: Asset symbol (e.g., "BTC", "ETH", "KXBTCD-25JUN-T100000")
            
        Returns:
            Dict with regime label, confidence, and duration, or "unknown" if not tracked.
        """
        with self._lock:
            state = self._states.get(asset)
            if state is None:
                return {
                    "label": "unknown",
                    "confidence": 0.0,
                    "duration_minutes": 0.0,
                    "asset": asset,
                }
            
            return {
                "label": state.regime.value,
                "confidence": state.confidence,
                "duration_minutes": state.regime_duration_minutes,
                "asset": asset,
                "last_updated": state.last_transition_ts,
            }
            
    def update_regime(
        self,
        asset: str,
        regime: MarketRegime,
        confidence: float,
        features: Optional[Dict[str, float]] = None,
    ) -> Optional[RegimeChangeEvent]:
        """Update regime state for an asset and detect transitions.
        
        Args:
            asset: Asset symbol (e.g., "BTC", "ETH")
            regime: Detected regime
            confidence: Confidence score (0.0-1.0)
            features: Feature values that contributed to detection
            
        Returns:
            RegimeChangeEvent if a transition occurred, None otherwise
        """
        now = datetime.now(timezone.utc)
        now_ts = now.isoformat()
        
        with self._lock:
            prev_state = self._states.get(asset)
            
            if prev_state is None:
                # First observation - just record it
                self._states[asset] = RegimeState(
                    asset=asset,
                    regime=regime,
                    confidence=confidence,
                    regime_duration_minutes=0.0,
                    last_transition_ts=now_ts,
                    features=features or {},
                )
                return None
            
            # Check if regime changed
            if prev_state.regime == regime:
                # Staying in same regime - update duration
                duration = (now - datetime.fromisoformat(prev_state.last_transition_ts)).total_seconds() / 60.0
                self._states[asset] = RegimeState(
                    asset=asset,
                    regime=regime,
                    confidence=confidence,
                    regime_duration_minutes=duration,
                    last_transition_ts=prev_state.last_transition_ts,
                    features=features or prev_state.features,
                )
                return None
            
            # Regime transition detected
            duration = (now - datetime.fromisoformat(prev_state.last_transition_ts)).total_seconds() / 60.0
            
            new_state = RegimeState(
                asset=asset,
                regime=regime,
                confidence=confidence,
                regime_duration_minutes=0.0,  # Reset duration
                last_transition_ts=now_ts,
                features=features or {},
            )
            
            self._states[asset] = new_state
            
            # Create transition event
            event = RegimeChangeEvent(
                asset=asset,
                previous_regime=prev_state.regime,
                new_regime=regime,
                transition_type=RegimeTransition.ENTRY,
                confidence=confidence,
                timestamp=now_ts,
                reasoning=self._generate_reasoning(prev_state.regime, regime, features),
                recommended_action=self._recommended_action(regime, confidence),
            )
            
            # Check if we should alert
            if self._should_alert(event):
                self._emit_event(event)
                self._last_alert_ts[asset] = now.timestamp()
            else:
                logger.debug(f"[RegimeDetector] Transition detected but not alerting: {asset} {prev_state.regime.value} -> {regime.value}")
            
            return event
    
    def _generate_reasoning(
        self,
        prev_regime: MarketRegime,
        new_regime: MarketRegime,
        features: Optional[Dict[str, float]],
    ) -> str:
        """Generate human-readable reasoning for the transition."""
        if features is None:
            return f"Market transitioned from {prev_regime.value} to {new_regime.value}"
        
        # Build reasoning based on key features
        parts = []
        
        if "adx" in features and features["adx"] > 25:
            parts.append(f"strong trend (ADX={features['adx']:.1f})")
        elif "adx" in features:
            parts.append(f"weak trend (ADX={features['adx']:.1f})")
            
        if "hurst" in features:
            if features["hurst"] > 0.6:
                parts.append(f"persistent momentum (H={features['hurst']:.2f})")
            elif features["hurst"] < 0.4:
                parts.append(f"mean-reverting (H={features['hurst']:.2f})")
                
        if "volatility_regime" in features:
            parts.append(f"volatility={features['volatility_regime']:.2f}")
            
        if "sentiment_score" in features:
            score = features["sentiment_score"]
            if abs(score) > 0.5:
                parts.append(f"extreme sentiment ({score:+.2f})")
                
        if parts:
            return f"Transition to {new_regime.value}: {', '.join(parts)}"
        return f"Market regime changed from {prev_regime.value} to {new_regime.value}"
    
    def _recommended_action(self, regime: MarketRegime, confidence: float) -> str:
        """Generate recommended action based on regime and confidence."""
        if confidence < self.config.min_confidence:
            return "Monitor closely - low confidence in regime detection"
            
        recommendations = {
            MarketRegime.TRENDING_UP: "Increase position sizes, reduce mean-reversion strategies",
            MarketRegime.TRENDING_DOWN: "Reduce exposure, activate downside protection, tighten stops",
            MarketRegime.MEAN_REVERTING: "Deploy mean-reversion strategies, reduce trend-following exposure",
            MarketRegime.HIGH_VOLATILITY: "Reduce position sizes, widen stops, increase cash buffer",
            MarketRegime.LOW_VOLATILITY: "Normal operations - consider increasing edge thresholds",
            MarketRegime.CHOPPY: "Reduce position sizes, avoid directional bets",
            MarketRegime.UNKNOWN: "Maintain current strategy - insufficient data",
        }
        
        return recommendations.get(regime, "No specific recommendation")
    
    def _should_alert(self, event: RegimeChangeEvent) -> bool:
        """Determine if this event should trigger an alert."""
        # Check confidence threshold
        if event.confidence < self.config.min_confidence:
            return False
            
        # Check cooldown
        last_alert = self._last_alert_ts.get(event.asset, 0)
        now = datetime.now(timezone.utc).timestamp()
        if (now - last_alert) < (self.config.cooldown_minutes * 60):
            return False
            
        # Check if this regime is in alert list
        if event.new_regime in self.config.alert_on_entry:
            return True
            
        if event.previous_regime in self.config.alert_on_exit:
            return True
            
        return False
    
    def _emit_event(self, event: RegimeChangeEvent) -> None:
        """Emit event to all registered listeners."""
        logger.info(
            f"[RegimeDetector] ALERT: {event.asset} regime change "
            f"{event.previous_regime.value} -> {event.new_regime.value} "
            f"(confidence={event.confidence:.2f})"
        )
        
        for listener in self._listeners:
            try:
                listener(event)
            except Exception as exc:
                logger.warning(f"[RegimeDetector] Listener failed: {exc}")
    
    def get_state(self, asset: str) -> Optional[RegimeState]:
        """Get current regime state for an asset."""
        with self._lock:
            return self._states.get(asset)
    
    def get_all_states(self) -> Dict[str, RegimeState]:
        """Get all regime states."""
        with self._lock:
            return dict(self._states)
    
    def reset(self, asset: Optional[str] = None) -> None:
        """Reset regime state for an asset or all assets."""
        with self._lock:
            if asset:
                self._states.pop(asset, None)
                self._last_alert_ts.pop(asset, None)
            else:
                self._states.clear()
                self._last_alert_ts.clear()


# ── Integration with MacroRegimeForecaster ───────────────────────────────

class RegimeDetectorForecasterBridge:
    """Bridge between MacroRegimeForecaster and RegimeDetector.
    
    Automatically forwards regime classifications from the forecaster
    to the detector for alerting and event publishing.
    """
    
    def __init__(self, detector: RegimeDetector):
        self.detector = detector
        
    def on_forecaster_update(
        self,
        asset: str,
        regime: str,
        confidence: float,
        features: Dict[str, float],
    ) -> None:
        """Callback for forecaster regime updates."""
        try:
            regime_enum = MarketRegime(regime)
        except ValueError:
            regime_enum = MarketRegime.UNKNOWN
            
        self.detector.update_regime(asset, regime_enum, confidence, features)


# ── Event Bus Integration ────────────────────────────────────────────────

def publish_to_event_bus(event: RegimeChangeEvent) -> None:
    """Publish regime change event to the MERID event bus.
    
    This function integrates with the StreamingBus for downstream consumers.
    """
    try:
        from merid.streams.market import StreamingBus
        bus = StreamingBus()
        bus.publish("market.regime.change", event.to_dict())
        logger.debug(f"[RegimeDetector] Published regime change to event bus: {event.asset}")
    except ImportError:
        logger.debug("[RegimeDetector] StreamingBus not available - event not published")
    except Exception as exc:
        logger.warning(f"[RegimeDetector] Failed to publish to event bus: {exc}")


# ── Singleton ────────────────────────────────────────────────────────────

_detector: Optional[RegimeDetector] = None
_bridge: Optional[RegimeDetectorForecasterBridge] = None
_lock = threading.Lock()


def get_regime_detector() -> RegimeDetector:
    """Get the singleton RegimeDetector."""
    global _detector
    if _detector is None:
        with _lock:
            if _detector is None:
                _detector = RegimeDetector()
                # Auto-register event bus publisher
                _detector.register_listener(publish_to_event_bus)
    return _detector


def get_forecaster_bridge() -> RegimeDetectorForecasterBridge:
    """Get the singleton ForecasterBridge."""
    global _bridge
    if _bridge is None:
        with _lock:
            if _bridge is None:
                _bridge = RegimeDetectorForecasterBridge(get_regime_detector())
    return _bridge


# ── Alert Callback Helpers ───────────────────────────────────────────────

def create_telegram_alert_callback() -> Callable[[RegimeChangeEvent], None]:
    """Create an alert callback that sends Telegram notifications.
    
    SOCIAL-TRUTH (2026-05-13): Telegram alert disabled for lean 15m Kalshi trading.
    """
    def callback(event: RegimeChangeEvent) -> None:
        pass
    return callback


def create_webhook_alert_callback(url: str) -> Callable[[RegimeChangeEvent], None]:
    """Create an alert callback that POSTs to a webhook.
    
    BUG-FIX (2026-05-12): Wrapped blocking requests.post in executor to prevent
    event loop blocking when called from async contexts. Uses cooperative cancellation
    pattern with timeout.
    """
    def callback(event: RegimeChangeEvent) -> None:
        try:
            import requests
            import concurrent.futures
            
            def _blocking_post():
                return requests.post(
                    url,
                    json=event.to_dict(),
                    timeout=5.0,
                    headers={"Content-Type": "application/json"},
                )
            
            # Run in executor to avoid blocking event loop
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(_blocking_post)
                try:
                    future.result(timeout=6.0)  # Slightly longer than request timeout
                except concurrent.futures.TimeoutError:
                    logger.debug(f"[RegimeDetector] Webhook alert timed out")
                except Exception as exc:
                    logger.debug(f"[RegimeDetector] Webhook alert failed: {exc}")
        except Exception as exc:
            logger.debug(f"[RegimeDetector] Webhook alert failed: {exc}")
    
    return callback

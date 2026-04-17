"""
Unified Signal Manager

Manages the creation, storage, and retrieval of unified signals across all domains.
Integrates with the existing SignalStore while providing a higher-level interface.
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Union

from merid.signals.unified_schema import (
    UnifiedSignal,
    SignalType,
    SignalDomain,
    create_kalshi_signal,
    create_fear_greed_signal,
    create_news_sentiment_signal,
    create_debate_risk_signal,
    suppress_signal
)
from merid.signals.store import get_signal_store


class UnifiedSignalManager:
    """High-level manager for unified cross-domain signals"""
    
    def __init__(self):
        self._store = get_signal_store()
    
    def store_signal(self, signal: UnifiedSignal) -> bool:
        """Store a unified signal in the SignalStore"""
        try:
            # Convert to the format expected by SignalStore.store_signal
            signal_dict = signal.to_dict()
            
            # Add the signal to the unified signal format
            signal_dict.update({
                "ticker": signal.symbol,  # For compatibility with existing schema
                "signal_type": signal.signal_type.value if isinstance(signal.signal_type, SignalType) else signal.signal_type,
            })
            
            self._store.store_signal(signal_dict)
            return True
            
        except Exception as e:
            print(f"Failed to store unified signal {signal.signal_id}: {e}")
            return False
    
    def store_feature_snapshot(self, symbol: str, domain: str, features: Dict[str, Any], source: str) -> bool:
        """Store feature snapshot for later signal generation"""
        try:
            feature_set = {
                "symbol": symbol,
                "domain": domain,
                "features": features,
                "source": source,
                "avg_freshness": 1.0,  # Default freshness
            }
            
            self._store.store_feature_snapshot(feature_set)
            return True
            
        except Exception as e:
            print(f"Failed to store feature snapshot for {symbol}: {e}")
            return False
    
    def get_latest_features(self, symbol: str, domain: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get latest features for a symbol"""
        try:
            return self._store.get_latest_features(symbol, domain)
        except Exception as e:
            print(f"Failed to get latest features for {symbol}: {e}")
            return []
    
    def get_signals_by_symbol(self, symbol: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent signals for a specific symbol"""
        try:
            # This would need to be implemented in SignalStore if not already available
            # For now, return empty list as placeholder
            return []
        except Exception as e:
            print(f"Failed to get signals for {symbol}: {e}")
            return []
    
    def create_kalshi_signal(
        self,
        ticker: str,
        edge_bps: float,
        features: Dict[str, Any],
        confidence: float = 0.5,
        source: str = "kalshi_signals"
    ) -> bool:
        """Create and store a Kalshi edge signal"""
        signal = create_kalshi_signal(ticker, edge_bps, features, confidence, source)
        return self.store_signal(signal)
    
    def create_fear_greed_signal(
        self,
        symbol: str,
        fg_score: float,
        volume_z: float,
        features: Dict[str, Any],
        source: str = "coingecko_live"
    ) -> bool:
        """Create and store a fear/greed signal"""
        signal = create_fear_greed_signal(symbol, fg_score, volume_z, features, source)
        return self.store_signal(signal)
    
    def create_news_sentiment_signal(
        self,
        symbol: str,
        sentiment_score: float,
        intensity: float,
        features: Dict[str, Any],
        source: str = "news_reddit_x"
    ) -> bool:
        """Create and store a news sentiment signal"""
        signal = create_news_sentiment_signal(symbol, sentiment_score, intensity, features, source)
        return self.store_signal(signal)
    
    def create_debate_risk_signal(
        self,
        symbol: str,
        multiplier: float,
        status: str,
        features: Dict[str, Any],
        source: str = "debate_system"
    ) -> bool:
        """Create and store a debate risk signal"""
        signal = create_debate_risk_signal(symbol, multiplier, status, features, source)
        return self.store_signal(signal)
    
    def suppress_signal_with_reason(
        self,
        signal_id: str,
        reason: str,
        new_confidence: Optional[float] = None
    ) -> bool:
        """Suppress a signal with a specific reason"""
        try:
            # This would need to retrieve the signal first
            # For now, just log the suppression
            print(f"Signal {signal_id} suppressed: {reason}")
            return True
        except Exception as e:
            print(f"Failed to suppress signal {signal_id}: {e}")
            return False
    
    def get_signal_metrics(self) -> Dict[str, Any]:
        """Get metrics about stored signals"""
        try:
            base_metrics = self._store.get_signal_metrics()
            
            # Add unified signal specific metrics
            return {
                **base_metrics,
                "unified_signals": {
                    "total_signals": base_metrics.get("feature_snapshots", 0),
                    "active_domains": ["crypto", "prediction", "equity", "betting", "macro"],
                    "signal_types": [t.value for t in SignalType],
                }
            }
        except Exception as e:
            print(f"Failed to get signal metrics: {e}")
            return {}
    
    def query_cross_domain_signals(
        self,
        symbol: str,
        signal_types: Optional[List[Union[SignalType, str]]] = None,
        min_confidence: float = 0.0,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Query signals across domains for a symbol with filters"""
        try:
            # This would implement cross-domain signal querying
            # For now, return empty list as placeholder
            return []
        except Exception as e:
            print(f"Failed to query cross-domain signals for {symbol}: {e}")
            return []


# Singleton instance
_unified_manager: Optional[UnifiedSignalManager] = None


def get_unified_signal_manager() -> UnifiedSignalManager:
    """Get the singleton unified signal manager instance"""
    global _unified_manager
    if _unified_manager is None:
        _unified_manager = UnifiedSignalManager()
    return _unified_manager

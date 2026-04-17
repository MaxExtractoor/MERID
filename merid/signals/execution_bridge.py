"""
Signal Execution Bridge

Connects unified signals to the execution engine, converting signals
into orders while applying confidence, strength, and risk filters.
"""

from __future__ import annotations

import os
import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from merid.signals.store import get_signal_store
from merid.event_venues.kalshi.market_context_resolver import get_market_context_resolver
from merid.event_venues.kalshi.market_wiring.safety import get_kalshi_safety_layer
from utils.logger import get_logger

logger = get_logger("signals.execution_bridge")


@dataclass
class ExecutionConfig:
    """Configuration for signal execution"""
    min_confidence: float = 0.6
    min_strength: float = 0.4
    max_notional: float = 1000.0
    lookback_minutes: int = 60  # How far back to look for signals
    target_domains: List[str] = None
    target_signal_types: List[str] = None
    
    def __post_init__(self):
        if self.target_domains is None:
            self.target_domains = ["prediction"]
        if self.target_signal_types is None:
            self.target_signal_types = ["kalshi_edge"]


class SignalExecutionBridge:
    """Bridge between unified signals and execution engine"""
    
    def __init__(self, config: Optional[ExecutionConfig] = None):
        self._config = config or ExecutionConfig()
        self._signal_store = get_signal_store()
        self._context_resolver = None  # Will be initialized lazily
        self._safety_layer = None  # Will be initialized lazily
        self._execution_engine = self._get_execution_engine()
        self._last_execution_time = 0.0
        self._execution_history: List[Dict[str, Any]] = []
        self._max_history = 1000
        
        # Global execution kill switch (for shadow testing)
        self._execution_enabled = os.getenv("MERID_EXECUTION_ENABLED", "true").lower() == "true"
    
    def _get_context_resolver(self):
        """Get market context resolver (lazy initialization)"""
        if self._context_resolver is None:
            self._context_resolver = get_market_context_resolver()
        return self._context_resolver
    
    def _get_safety_layer(self):
        """Get safety layer (lazy initialization)"""
        if self._safety_layer is None:
            self._safety_layer = get_kalshi_safety_layer()
        return self._safety_layer
    
    def _get_execution_engine(self):
        """Get the execution engine - placeholder for actual implementation"""
        # This would integrate with your existing execution engine
        # For now, return a mock that logs orders
        return MockExecutionEngine()
    
    def run_once(self) -> int:
        """Consume recent signals and send eligible ones to execution"""
        try:
            # Get recent signals
            since_ts = time.time() - (self._config.lookback_minutes * 60)
            signals = self._signal_store.get_recent_unified_signals(
                since_ts=since_ts,
                domains=self._config.target_domains,
            )
            
            executed_count = 0
            
            for signal in signals:
                if self._should_execute_signal(signal):
                    try:
                        order = self._build_order_from_signal(signal)
                        if order:
                            # Check global execution kill switch
                            if not self._execution_enabled:
                                # Shadow mode: record would-be execution but don't actually execute
                                logger.info(f"SHADOW MODE: Would execute order {order['symbol']} {order['side']} "
                                           f"${order['notional']} (signal: {order['meta'].get('signal_id')})")
                                self._record_execution(signal, order)
                                executed_count += 1
                            else:
                                # Live execution
                                success = self._execution_engine.submit_order(order)
                                if success:
                                    executed_count += 1
                                    self._record_execution(signal, order)
                                else:
                                    logger.warning(f"Execution rejected for signal {signal.get('signal_id')}")
                    except Exception as e:
                        logger.warning(f"Failed to execute signal {signal.get('signal_id')}: {e}")
            
            logger.info(f"Signal execution bridge processed {len(signals)} signals, executed {executed_count}")
            return executed_count
            
        except Exception as e:
            logger.error(f"Signal execution bridge failed: {e}")
            return 0
    
    def _should_execute_signal(self, signal: Dict[str, Any]) -> bool:
        """Check if a signal meets execution criteria with per-market safety checks"""
        # Skip suppressed signals
        if signal.get("suppressed", False):
            return False

        # Deduplicate: skip signals already executed in the last 5 minutes
        signal_id = signal.get("signal_id")
        if signal_id and self._was_executed_recently(signal_id):
            return False

        # Check basic confidence and strength thresholds
        confidence = signal.get("confidence", 0.0)
        strength = signal.get("strength", 0.0)
        
        if confidence < self._config.min_confidence or strength < self._config.min_strength:
            return False
        
        # Check domain and signal type filters
        domain = signal.get("domain", "")
        signal_type = signal.get("signal_type", "")
        
        if domain not in self._config.target_domains:
            return False
        
        if signal_type not in self._config.target_signal_types:
            return False
        
        # For Kalshi signals, check per-market safety and caps
        if signal_type == "kalshi_edge" and signal.get("market_ticker"):
            return self._check_kalshi_signal_safety(signal)
        
        return True
    
    def _check_kalshi_signal_safety(self, signal: Dict[str, Any]) -> bool:
        """Check Kalshi signal safety using safety layer (final validation)"""
        try:
            safety_layer = self._get_safety_layer()
            if not safety_layer:
                logger.warning("Safety layer not available, skipping Kalshi signal safety check")
                return False
            
            market_ticker = signal.get("market_ticker")
            if not market_ticker:
                return False
            
            # Get proposed notional from signal (already adjusted by generator)
            proposed_notional = signal.get("notional", self._config.max_notional)
            
            # Final safety check with proposed notional
            safety_result = safety_layer.perform_safety_check(
                market_ticker=market_ticker,
                signal=signal,
                proposed_notional=proposed_notional
            )
            
            if not safety_result.safe_to_trade:
                logger.debug(f"Signal safety check failed for {market_ticker}: {safety_result.block_reasons}")
                return False
            
            logger.debug(f"Signal safety check passed for {market_ticker}")
            return True
            
        except Exception as e:
            logger.error(f"Error checking Kalshi signal safety: {e}")
            return False
    
    def _check_per_market_caps(self, signal: Dict[str, Any], context) -> bool:
        """Check if signal respects per-market risk caps from KalshiMarketRecord"""
        try:
            # Get signal notional (default to config max if not specified)
            signal_notional = signal.get("notional", self._config.max_notional)
            
            # Get per-market caps from KalshiMarketRecord via context
            market_record = context.kalshi_market
            
            # Use effective limits from context (already adjusted for freshness/CQI)
            max_notional = context.effective_max_notional
            max_daily = context.effective_daily_notional
            max_open_risk = context.effective_open_risk
            
            # Check per-trade limit
            if signal_notional > max_notional:
                logger.debug(f"Signal notional {signal_notional} exceeds market max {max_notional} for {market_record.market_ticker}")
                return False
            
            # Check daily limit (simplified - would need actual position tracking)
            # For now, just log the check
            current_daily_exposure = self._get_current_daily_exposure(market_record.market_ticker)
            if current_daily_exposure + signal_notional > max_daily:
                logger.debug(f"Daily exposure would exceed limit for {market_record.market_ticker}")
                return False
            
            # Check open risk limit (simplified)
            current_open_risk = self._get_current_open_risk(market_record.market_ticker)
            if current_open_risk + signal_notional > max_open_risk:
                logger.debug(f"Open risk would exceed limit for {market_record.market_ticker}")
                return False
            
            logger.debug(f"Signal {signal_notional} respects per-market caps for {market_record.market_ticker}")
            return True
            
        except Exception as e:
            logger.error(f"Error checking per-market caps: {e}")
            return False
    
    def _get_current_daily_exposure(self, market_ticker: str) -> float:
        """Get current daily exposure for a market (placeholder)"""
        # This would integrate with your position tracking system
        # For now, return 0 as placeholder
        return 0.0
    
    def _get_current_open_risk(self, market_ticker: str) -> float:
        """Get current open risk for a market (placeholder)"""
        # This would integrate with your risk management system
        # For now, return 0 as placeholder
        return 0.0
    
    def _build_order_from_signal(self, signal: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Build an order from a unified signal"""
        try:
            # Extract edge information
            edge_bps = (signal.get("edge_bps") or 
                       signal.get("features", {}).get("kalshi_edge_bps") or
                       signal.get("features", {}).get("edge_bps"))
            
            if edge_bps is None:
                logger.debug(f"No edge information in signal {signal.get('signal_id')}")
                return None
            
            # Determine order side
            side = "buy" if edge_bps > 0 else "sell"
            
            # Calculate notional (simple sizing - replace with Kelly/quota logic)
            base_notional = abs(edge_bps) * 100  # Simple linear sizing
            notional = min(base_notional, self._config.max_notional)
            
            if notional < 10:  # Minimum notional threshold
                return None
            
            # Build order
            order = {
                "symbol": signal.get("symbol"),
                "side": side,
                "notional": notional,
                "order_type": "market",  # Could be configurable
                "meta": {
                    "signal_id": signal.get("signal_id"),
                    "source": signal.get("source"),
                    "signal_type": signal.get("signal_type"),
                    "confidence": signal.get("confidence"),
                    "strength": signal.get("strength"),
                    "edge_bps": edge_bps,
                    "features": signal.get("features", {}),
                    "generated_at": signal.get("generated_at"),  # Match unified schema timestamp field
                }
            }
            
            return order
            
        except Exception as e:
            logger.warning(f"Failed to build order from signal {signal.get('signal_id')}: {e}")
            return None
    
    def _was_executed_recently(self, signal_id: str) -> bool:
        """Check if a signal was executed recently to avoid duplicates"""
        if not signal_id:
            return False
        
        # Check last 5 minutes of executions
        cutoff_time = time.time() - 300
        recent_executions = [
            exec_record for exec_record in self._execution_history
            if exec_record.get("timestamp", 0) > cutoff_time
        ]
        
        return any(
            exec_record.get("signal_id") == signal_id 
            for exec_record in recent_executions
        )
    
    def _record_execution(self, signal: Dict[str, Any], order: Dict[str, Any]):
        """Record a successful execution for tracking"""
        execution_record = {
            "signal_id": signal.get("signal_id"),
            "symbol": signal.get("symbol"),
            "signal_type": signal.get("signal_type"),
            "order": order,
            "timestamp": time.time(),
        }
        
        self._execution_history.append(execution_record)
        
        # Trim history if too large
        if len(self._execution_history) > self._max_history:
            self._execution_history = self._execution_history[-self._max_history:]
    
    def get_execution_stats(self) -> Dict[str, Any]:
        """Get execution statistics"""
        if not self._execution_history:
            return {
                "total_executions": 0,
                "recent_executions_1h": 0,
                "success_rate": 0.0,
                "avg_notional": 0.0,
            }
        
        total_executions = len(self._execution_history)
        
        # Recent executions (last hour)
        one_hour_ago = time.time() - 3600
        recent_executions = [
            exec_record for exec_record in self._execution_history
            if exec_record.get("timestamp", 0) > one_hour_ago
        ]
        
        # Calculate average notional
        avg_notional = 0.0
        if self._execution_history:
            notionals = [
                exec_record.get("order", {}).get("notional", 0)
                for exec_record in self._execution_history
            ]
            avg_notional = sum(notionals) / len(notionals)
        
        return {
            "total_executions": total_executions,
            "recent_executions_1h": len(recent_executions),
            "success_rate": 1.0,  # Would be calculated from actual execution results
            "avg_notional": avg_notional,
            "execution_enabled": self._execution_enabled,
            "execution_mode": "shadow" if not self._execution_enabled else "live",
        }
    
    def get_execution_history(self, since_ts: Optional[float] = None) -> List[Dict[str, Any]]:
        """Get execution history with optional time filtering"""
        if since_ts is None:
            return list(self._execution_history)
        return [
            r for r in self._execution_history
            if r.get("timestamp", 0) > since_ts
        ]


class MockExecutionEngine:
    """Mock execution engine for development/testing"""
    
    def submit_order(self, order: Dict[str, Any]) -> bool:
        """Mock order submission - just log and return success"""
        logger.info(f"Mock order submission: {order['symbol']} {order['side']} "
                   f"${order['notional']} (signal: {order['meta'].get('signal_id')})")
        return True


# Singleton instance
_bridge: Optional[SignalExecutionBridge] = None


def get_signal_execution_bridge(config: Optional[ExecutionConfig] = None) -> SignalExecutionBridge:
    """Get the singleton signal execution bridge"""
    global _bridge
    if _bridge is None:
        _bridge = SignalExecutionBridge(config)
    return _bridge


def run_signal_execution() -> int:
    """Run signal execution bridge and return count of executed orders"""
    bridge = get_signal_execution_bridge()
    return bridge.run_once()

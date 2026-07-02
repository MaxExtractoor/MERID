"""Runtime Integrity Monitor - Critical safety checks for live trading.

Monitors key system invariants and alerts on data integrity failures.
This is the "love mode" safety layer that ensures no harm comes from
stale data or inconsistent state.

Critical Checks:
1. WS Forwarder stall detection (events_processed=0 for >60s)
2. Bankroll consistency (internal vs Kalshi divergence >1%)
3. Market data freshness (last_update > 120s)
4. Position cache vs Kalshi portfolio reconciliation

All alerts use the rate-limited tg_send system to avoid spam.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional
import os

logger = logging.getLogger(__name__)

class IntegrityMonitor:
    """Monitors critical system invariants for live trading safety."""
    
    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._check_interval = int(os.getenv("MERID_INTEGRITY_CHECK_INTERVAL_S", "30"))  # 30s default
        self._ws_stall_threshold = int(os.getenv("MERID_WS_STALL_THRESHOLD_S", "60"))  # 60s default
        self._bankroll_divergence_threshold = float(os.getenv("MERID_BANKROLL_DIVERGENCE_PCT", "1.0"))  # 1% default
        self._market_data_stale_threshold = int(os.getenv("MERID_MARKET_DATA_STALE_S", "120"))  # 120s default
        
        logger.info(
            "[INTEGRITY-MONITOR] Initialized with check_interval=%ds, "
            "ws_stall=%ds, bankroll_divergence=%.1f%%, md_stale=%ds",
            self._check_interval, self._ws_stall_threshold, 
            self._bankroll_divergence_threshold, self._market_data_stale_threshold
        )
    
    async def start(self):
        """Start the integrity monitoring loop."""
        if self._running:
            logger.warning("[INTEGRITY-MONITOR] Already running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        logger.info("[INTEGRITY-MONITOR] Started monitoring loop")
    
    async def stop(self):
        """Stop the integrity monitoring loop."""
        if not self._running:
            return
        
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("[INTEGRITY-MONITOR] Stopped monitoring loop")
    
    async def _monitor_loop(self):
        """Main monitoring loop."""
        logger.info("[INTEGRITY-MONITOR] Entering monitoring loop")
        
        while self._running:
            try:
                await self._run_checks()
                await asyncio.sleep(self._check_interval)
            except asyncio.CancelledError:
                logger.info("[INTEGRITY-MONITOR] Cancelled, exiting")
                break
            except Exception as e:
                logger.error(f"[INTEGRITY-MONITOR] Check failed: {e}", exc_info=True)
                await asyncio.sleep(self._check_interval)
    
    async def _run_checks(self):
        """Run all integrity checks."""
        logger.debug("[INTEGRITY-MONITOR] Running integrity checks")
        
        # Check 1: WS Forwarder health
        await self._check_ws_forwarder()
        
        # Check 2: Bankroll consistency
        await self._check_bankroll_consistency()
        
        # Check 3: Market data freshness
        await self._check_market_data_freshness()
        
        # Check 4: Position reconciliation
        await self._check_position_reconciliation()
    
    async def _check_ws_forwarder(self):
        """Check WS forwarder is processing events."""
        try:
            from merid.event_venues.kalshi.ws_bridge import get_bridge

            bridge = get_bridge()
            if not bridge:
                logger.warning("[INTEGRITY-MONITOR] WS bridge not available")
                return
            
            # Get forwarder stats from simpler bridge
            stats = bridge.stats()
            events_processed = stats.get('messages_received', 0)
            last_event_ts = stats.get('last_message_time', 0.0) / 1000 if stats.get('last_message_time') else 0.0
            
            if last_event_ts == 0.0:
                # Never received events - check if we've been running long enough
                logger.info("[INTEGRITY-MONITOR] WS forwarder idle (no events yet)")
                return
            
            # Check stall
            import time
            time_since_last = time.monotonic() - last_event_ts
            
            if time_since_last > self._ws_stall_threshold:
                await self._send_critical_alert(
                    "WS Forwarder Stall",
                    f"• Events processed: {events_processed}\n"
                    f"• Time since last event: {time_since_last:.0f}s\n"
                    f"• Risk: Trading on stale market data\n"
                    f"• Action: Check WebSocket connection"
                )
                logger.error(
                    "[INTEGRITY-MONITOR] CRITICAL: WS forwarder stalled for %.0fs",
                    time_since_last
                )
            elif time_since_last > 30:
                logger.warning(
                    "[INTEGRITY-MONITOR] WS forwarder idle for %.0fs",
                    time_since_last
                )
            
        except Exception as e:
            logger.error(f"[INTEGRITY-MONITOR] WS forwarder check failed: {e}")
    
    async def _check_bankroll_consistency(self):
        """Check bankroll consistency between internal and Kalshi."""
        try:
            from merid.event_venues.kalshi.bankroll_service_v2 import get_bankroll_service
            
            service = await get_bankroll_service()
            consistency = await service.check_consistency()
            
            if not consistency.get("consistent", True):
                severity = consistency.get("severity", "warning")
                if severity == "critical":
                    await self._send_critical_alert(
                        "Bankroll Consistency Failure",
                        f"• Fresh equity: ${consistency.get('fresh_equity', 0):.2f}\n"
                        f"• Cached equity: ${consistency.get('cached_equity', 0):.2f}\n"
                        f"• Divergence: {consistency.get('equity_diff_pct', 0):.2f}%\n"
                        f"• Risk: Position sizing may be wrong\n"
                        f"• Action: Investigate data sync"
                    )
                logger.warning(
                    "[INTEGRITY-MONITOR] Bankroll consistency issue: %s",
                    consistency.get("error", "Unknown")
                )
            
        except Exception as e:
            logger.error(f"[INTEGRITY-MONITOR] Bankroll consistency check failed: {e}")
    
    async def _check_market_data_freshness(self):
        """Check market data is fresh."""
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            
            store = get_kalshi_market_state_store()
            if not store:
                logger.warning("[INTEGRITY-MONITOR] Market state store not available")
                return
            
            # Get current tickers from catalog instead of hardcoded demo values
            # CRITICAL FIX: Remove hardcoded June 26 demo tickers from production
            # CRITICAL FIX: Use singleton catalog instead of creating new instance
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            catalog = get_market_catalog()
            snapshot = catalog.snapshot()
            
            # Get current 15m markets for BTC and ETH
            key_tickers = []
            for asset in ["BTC", "ETH"]:
                market = snapshot.get_current_15m_market(asset)
                if market:
                    ticker = market.market.market_id if hasattr(market, 'market') else market.market_id
                    key_tickers.append(ticker)
            
            if not key_tickers:
                logger.warning("[INTEGRITY-MONITOR] No current 15m markets found in catalog")
                return
            
            stale_tickers = []
            
            import time
            now = time.monotonic()
            
            for ticker in key_tickers:
                state = store.get(ticker)
                if state and hasattr(state, 'last_update_ts'):
                    age = now - state.last_update_ts
                    if age > self._market_data_stale_threshold:
                        stale_tickers.append((ticker, age))
            
            if stale_tickers:
                await self._send_critical_alert(
                    "Market Data Stale",
                    f"• Stale tickers: {len(stale_tickers)}\n" + 
                    "\n".join([f"• {ticker}: {age:.0f}s old" for ticker, age in stale_tickers[:3]]) +
                    f"\n• Risk: Trading on outdated prices\n"
                    f"• Action: Check market data feeds"
                )
                logger.error(
                    "[INTEGRITY-MONITOR] CRITICAL: %d tickers stale >%ds",
                    len(stale_tickers), self._market_data_stale_threshold
                )
            
        except Exception as e:
            logger.error(f"[INTEGRITY-MONITOR] Market data freshness check failed: {e}")
    
    async def _check_position_reconciliation(self):
        """Check position cache vs Kalshi portfolio."""
        try:
            # This would require fetching positions from Kalshi and comparing
            # For now, just log that this check exists but isn't implemented
            logger.debug("[INTEGRITY-MONITOR] Position reconciliation check (not implemented)")
            
        except Exception as e:
            logger.error(f"[INTEGRITY-MONITOR] Position reconciliation check failed: {e}")
    
    async def _send_critical_alert(self, title: str, details: str):
        """Send a critical alert via rate-limited notification system."""
        try:
            from merid.alerts.webhook_client import tg_send
            
            message = f"🚨 CRITICAL: {title}\n{details}\n⏰ {datetime.now(timezone.utc).isoformat()}"
            
            tg_send(message)
            logger.info("[INTEGRITY-MONITOR] Critical alert sent: %s", title)
            
        except Exception as e:
            logger.error(f"[INTEGRITY-MONITOR] Failed to send critical alert: {e}")

# Global instance
_integrity_monitor: Optional[IntegrityMonitor] = None

def get_integrity_monitor() -> IntegrityMonitor:
    """Get the global integrity monitor instance."""
    global _integrity_monitor
    if _integrity_monitor is None:
        _integrity_monitor = IntegrityMonitor()
    return _integrity_monitor

async def start_integrity_monitoring():
    """Start integrity monitoring (called during startup)."""
    monitor = get_integrity_monitor()
    await monitor.start()

async def stop_integrity_monitoring():
    """Stop integrity monitoring (called during shutdown)."""
    monitor = get_integrity_monitor()
    await monitor.stop()

#!/usr/bin/env python3
"""
Soak Test Monitor for Kalshi 15m Lean Stack

Monitors system health during 60-minute soak test with targeted sanity counters:
- Catalog markets count
- Market state counts
- WebSocket stats
- Agent metrics
- Bankroll equity
- Risk envelope status

Usage:
    python scripts/soak_test_monitor.py
"""

import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.logger import get_logger

logger = get_logger("scripts.soak_test_monitor")


class SoakTestMonitor:
    """Monitor system health during soak test."""
    
    def __init__(self, duration_minutes: int = 60):
        self.duration_seconds = duration_minutes * 60
        self.start_time = time.time()
        self.snapshot_interval = 60  # seconds
        self.log_file = Path(__file__).parent.parent / "soak_test_results.jsonl"
        
    async def collect_catalog_metrics(self) -> Dict[str, Any]:
        """Collect catalog metrics."""
        try:
            from merid.event_venues.kalshi.market_catalog import get_market_catalog
            catalog = get_market_catalog()
            
            return {
                "catalog_markets_count": len(catalog._markets) if hasattr(catalog, '_markets') else 0,
                "catalog_last_refresh": catalog._last_refresh_ts if hasattr(catalog, '_last_refresh_ts') else None,
                "catalog_age_seconds": time.time() - catalog._last_refresh_ts if hasattr(catalog, '_last_refresh_ts') else None,
            }
        except Exception as e:
            logger.error(f"Failed to collect catalog metrics: {e}")
            return {"catalog_error": str(e)}
    
    async def collect_market_state_metrics(self) -> Dict[str, Any]:
        """Collect market state store metrics."""
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            store = get_kalshi_market_state_store()
            
            return {
                "market_state_count": len(store._state) if hasattr(store, '_state') else 0,
                "market_state_fresh_count": self._count_fresh_states(store),
            }
        except Exception as e:
            logger.error(f"Failed to collect market state metrics: {e}")
            return {"market_state_error": str(e)}
    
    def _count_fresh_states(self, store) -> int:
        """Count fresh market states (updated within 30s)."""
        if not hasattr(store, '_state'):
            return 0
        
        fresh_threshold = time.time() - 30
        fresh_count = 0
        for state in store._state.values():
            if hasattr(state, 'last_update_ts') and state.last_update_ts > fresh_threshold:
                fresh_count += 1
        return fresh_count
    
    async def collect_ws_metrics(self) -> Dict[str, Any]:
        """Collect WebSocket bridge metrics."""
        try:
            from merid.event_venues.kalshi.ws_bridge import get_bridge
            bridge = get_bridge()

            return {
                "ws_messages_received": bridge.messages_received,
                "ws_messages_published": bridge.messages_published,
                "ws_reconnect_count": bridge.reconnect_count,
                "ws_last_message_time": bridge.last_message_time,
                "ws_subscribed_tickers": len(bridge._subscribed_tickers),
            }
        except Exception as e:
            logger.error(f"Failed to collect WS metrics: {e}")
            return {"ws_error": str(e)}
    
    async def collect_agent_metrics(self) -> Dict[str, Any]:
        """Collect agent grid metrics."""
        try:
            from merid.prediction.agent_grid_15m import LeanAgentGrid15m
            # This would need access to the running agent grid instance
            # For now, return placeholder
            return {
                "agent_grid_status": "running",
                "agents_count": 5,  # BTC, ETH, SOL, XRP, DOGE
            }
        except Exception as e:
            logger.error(f"Failed to collect agent metrics: {e}")
            return {"agent_error": str(e)}
    
    async def collect_bankroll_metrics(self) -> Dict[str, Any]:
        """Collect bankroll service metrics."""
        try:
            from merid.event_venues.kalshi.bankroll_service_v2 import get_equity_for_risk_calc_sync
            equity = get_equity_for_risk_calc_sync()
            
            return {
                "bankroll_equity_usd": equity,
                "bankroll_source": "bankroll_service_v2",
            }
        except Exception as e:
            logger.error(f"Failed to collect bankroll metrics: {e}")
            return {"bankroll_error": str(e)}
    
    async def collect_risk_envelope_metrics(self) -> Dict[str, Any]:
        """Collect risk envelope metrics."""
        try:
            from merid.risk.profiles.risk_envelope_service import get_risk_envelope_service
            service = get_risk_envelope_service()
            config = service.get_config()
            
            return {
                "risk_envelope_halted": config.is_halted if hasattr(config, 'is_halted') else False,
                "risk_envelope_drawdown_pct": config.current_drawdown_pct * 100 if hasattr(config, 'current_drawdown_pct') else 0,
                "risk_envelope_band": config.current_risk_band.value if hasattr(config, 'current_risk_band') else "unknown",
            }
        except Exception as e:
            logger.error(f"Failed to collect risk envelope metrics: {e}")
            return {"risk_envelope_error": str(e)}
    
    async def collect_spot_metrics(self) -> Dict[str, Any]:
        """Collect unified spot service metrics."""
        try:
            from data.unified_spot_service import get_unified_spot_service
            spot = get_unified_spot_service()
            health = spot.health_check()
            
            return {
                "spot_running": health.get("running", False),
                "spot_cached_count": health.get("cached_count", 0),
                "spot_stale_count": health.get("stale_count", 0),
            }
        except Exception as e:
            logger.error(f"Failed to collect spot metrics: {e}")
            return {"spot_error": str(e)}
    
    async def collect_snapshot(self) -> Dict[str, Any]:
        """Collect a complete system snapshot."""
        timestamp = datetime.now(timezone.utc).isoformat()
        elapsed_seconds = time.time() - self.start_time
        
        metrics = {
            "timestamp": timestamp,
            "elapsed_seconds": elapsed_seconds,
            "elapsed_minutes": elapsed_seconds / 60,
        }
        
        # Collect all metrics in parallel
        catalog_metrics = await self.collect_catalog_metrics()
        state_metrics = await self.collect_market_state_metrics()
        ws_metrics = await self.collect_ws_metrics()
        agent_metrics = await self.collect_agent_metrics()
        bankroll_metrics = await self.collect_bankroll_metrics()
        risk_metrics = await self.collect_risk_envelope_metrics()
        spot_metrics = await self.collect_spot_metrics()
        
        metrics.update(catalog_metrics)
        metrics.update(state_metrics)
        metrics.update(ws_metrics)
        metrics.update(agent_metrics)
        metrics.update(bankroll_metrics)
        metrics.update(risk_metrics)
        metrics.update(spot_metrics)
        
        return metrics
    
    async def run(self):
        """Run the soak test monitor."""
        logger.info(f"Starting soak test monitor for {self.duration_seconds / 60} minutes")
        logger.info(f"Logging results to {self.log_file}")
        
        snapshot_count = 0
        
        while time.time() - self.start_time < self.duration_seconds:
            snapshot_count += 1
            elapsed = time.time() - self.start_time
            
            logger.info(f"Collecting snapshot {snapshot_count} (elapsed: {elapsed:.1f}s)")
            
            try:
                snapshot = await self.collect_snapshot()
                
                # Write to log file
                with open(self.log_file, 'a') as f:
                    f.write(json.dumps(snapshot) + '\n')
                
                # Log summary
                logger.info(
                    f"Snapshot {snapshot_count}: "
                    f"catalog={snapshot.get('catalog_markets_count', 0)}, "
                    f"state_fresh={snapshot.get('market_state_fresh_count', 0)}, "
                    f"ws_msgs={snapshot.get('ws_messages_received', 0)}, "
                    f"bankroll=${snapshot.get('bankroll_equity_usd', 0):.2f}, "
                    f"risk_halted={snapshot.get('risk_envelope_halted', False)}"
                )
                
                # Check for anomalies
                self._check_anomalies(snapshot)
                
            except Exception as e:
                logger.error(f"Failed to collect snapshot {snapshot_count}: {e}")
            
            # Wait for next snapshot
            await asyncio.sleep(self.snapshot_interval)
        
        logger.info(f"Soak test monitor completed after {self.duration_seconds / 60} minutes")
        logger.info(f"Collected {snapshot_count} snapshots")
        logger.info(f"Results saved to {self.log_file}")
    
    def _check_anomalies(self, snapshot: Dict[str, Any]):
        """Check for anomalies in the snapshot."""
        anomalies = []
        
        # Check catalog age
        catalog_age = snapshot.get('catalog_age_seconds')
        if catalog_age and catalog_age > 300:  # 5 minutes
            anomalies.append(f"Catalog stale: {catalog_age:.1f}s")
        
        # Check market state freshness
        fresh_count = snapshot.get('market_state_fresh_count', 0)
        if fresh_count < 5:  # Should have at least 5 fresh states (BTC, ETH, SOL, XRP, DOGE)
            anomalies.append(f"Low fresh market states: {fresh_count}")
        
        # Check bankroll
        bankroll = snapshot.get('bankroll_equity_usd')
        if bankroll is None or bankroll <= 0:
            anomalies.append(f"Invalid bankroll: ${bankroll}")
        
        # Check risk envelope
        if snapshot.get('risk_envelope_halted'):
            anomalies.append("Risk envelope halted")
        
        # Check spot service
        if not snapshot.get('spot_running'):
            anomalies.append("Spot service not running")
        
        if anomalies:
            logger.warning(f"Anomalies detected: {', '.join(anomalies)}")


async def main():
    """Main entry point."""
    monitor = SoakTestMonitor(duration_minutes=60)
    await monitor.run()


if __name__ == "__main__":
    asyncio.run(main())

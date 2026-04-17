"""Kalshi Pipeline Diagnostics Probe

Concurrent probe for diagnosing Kalshi timeout and lag issues.
Runs multiple probes in parallel to identify bottlenecks.

Usage:
    python -m merid.diagnostics.kalshi_probe [--duration 30] [--output json]

Reports:
    - WebSocket latency and message backlog
    - REST endpoint response times
    - Event-loop lag samples
    - Fill/position reconciliation gaps
"""

from __future__ import annotations

import asyncio
import argparse
import json
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from collections import defaultdict

from utils.logger import get_logger

logger = get_logger("merid.diagnostics.kalshi_probe")


@dataclass
class ProbeResult:
    """Result from a single probe measurement."""
    probe_name: str
    timestamp: float
    duration_ms: float
    success: bool
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProbeReport:
    """Aggregated diagnostic report."""
    start_time: str
    end_time: str
    duration_seconds: float
    probes: List[ProbeResult] = field(default_factory=list)
    
    def add(self, result: ProbeResult) -> None:
        self.probes.append(result)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_seconds": self.duration_seconds,
            "summary": self._summary(),
            "probes": [
                {
                    "probe_name": p.probe_name,
                    "timestamp": p.timestamp,
                    "duration_ms": round(p.duration_ms, 2),
                    "success": p.success,
                    "error": p.error,
                    "metadata": p.metadata,
                }
                for p in self.probes
            ],
        }
    
    def _summary(self) -> Dict[str, Any]:
        by_name = defaultdict(list)
        for p in self.probes:
            by_name[p.probe_name].append(p)
        
        summary = {}
        for name, probes in by_name.items():
            durations = [p.duration_ms for p in probes if p.success]
            success_count = sum(1 for p in probes if p.success)
            fail_count = len(probes) - success_count
            
            summary[name] = {
                "count": len(probes),
                "success": success_count,
                "failed": fail_count,
                "avg_ms": round(sum(durations) / len(durations), 2) if durations else None,
                "p95_ms": round(sorted(durations)[int(len(durations) * 0.95)], 2) if durations else None,
                "max_ms": round(max(durations), 2) if durations else None,
            }
        return summary


class KalshiPipelineProbe:
    """Concurrent diagnostic probe for Kalshi pipeline health."""
    
    def __init__(self, duration_seconds: int = 30):
        self.duration = duration_seconds
        self.report = ProbeReport(
            start_time=datetime.now(timezone.utc).isoformat(),
            end_time="",
            duration_seconds=0.0,
        )
        self._stop_event = asyncio.Event()
    
    async def run(self) -> ProbeReport:
        """Run all probes concurrently for the specified duration."""
        logger.info(f"Starting Kalshi pipeline probe for {self.duration}s")
        
        # Start all probe tasks concurrently
        probe_tasks = [
            asyncio.create_task(self._ws_latency_probe()),
            asyncio.create_task(self._rest_latency_probe()),
            asyncio.create_task(self._loop_lag_probe()),
            asyncio.create_task(self._fills_sync_probe()),
            asyncio.create_task(self._position_sync_probe()),
        ]
        
        # Stop after duration
        await asyncio.wait_for(self._stop_event.wait(), timeout=self.duration)
        self._stop_event.set()
        
        # Cancel remaining tasks
        for task in probe_tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        
        # Collect results from completed tasks
        for task in probe_tasks:
            if task.done() and not task.cancelled():
                try:
                    results = task.result()
                    if results:
                        for r in results:
                            self.report.add(r)
                except Exception as e:
                    logger.warning(f"Probe task failed: {e}")
        
        self.report.end_time = datetime.now(timezone.utc).isoformat()
        self.report.duration_seconds = self.duration
        
        return self.report
    
    def stop(self) -> None:
        """Signal probe to stop."""
        self._stop_event.set()
    
    async def _ws_latency_probe(self) -> List[ProbeResult]:
        """Probe WebSocket latency and message backlog."""
        results = []
        probe_interval = 5.0  # Check every 5 seconds
        
        while not self._stop_event.is_set():
            try:
                t0 = time.monotonic()
                
                # Check WS bridge health
                try:
                    from merid.event_venues.kalshi.ws_bridge import get_ws_bridge
                    bridge = get_ws_bridge()
                    
                    # Gather metrics
                    is_running = bridge.is_running()
                    queue_size = bridge._queue.qsize() if hasattr(bridge, '_queue') else 0
                    events_forwarded = getattr(bridge, '_events_forwarded', 0)
                    events_dropped = getattr(bridge, '_events_dropped', 0)
                    
                    # Calculate lag from message timestamps if available
                    last_msg_age = None
                    if hasattr(bridge, '_ws') and bridge._ws:
                        from merid.event_venues.kalshi.ws import KalshiWebSocket
                        if isinstance(bridge._ws, KalshiWebSocket):
                            last_msg_ts = getattr(bridge._ws, '_last_message_ts', 0)
                            if last_msg_ts:
                                last_msg_age = time.monotonic() - last_msg_ts
                    
                    t1 = time.monotonic()
                    duration_ms = (t1 - t0) * 1000
                    
                    results.append(ProbeResult(
                        probe_name="ws_bridge_health",
                        timestamp=t0,
                        duration_ms=duration_ms,
                        success=is_running,
                        metadata={
                            "is_running": is_running,
                            "queue_size": queue_size,
                            "queue_maxsize": getattr(bridge._queue, 'maxsize', 0) if hasattr(bridge, '_queue') else 0,
                            "events_forwarded": events_forwarded,
                            "events_dropped": events_dropped,
                            "last_msg_age_seconds": round(last_msg_age, 2) if last_msg_age else None,
                        }
                    ))
                except Exception as e:
                    t1 = time.monotonic()
                    results.append(ProbeResult(
                        probe_name="ws_bridge_health",
                        timestamp=t0,
                        duration_ms=(t1 - t0) * 1000,
                        success=False,
                        error=str(e),
                    ))
                
                # Wait before next probe
                await asyncio.wait_for(self._stop_event.wait(), timeout=probe_interval)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.warning(f"WS probe error: {e}")
        
        return results
    
    async def _rest_latency_probe(self) -> List[ProbeResult]:
        """Probe REST endpoint response times."""
        results = []
        endpoints = [
            ("kalshi_rest_markets", "/markets"),
            ("kalshi_rest_positions", "/portfolio/positions"),
            ("kalshi_rest_balance", "/portfolio/balance"),
        ]
        probe_interval = 10.0  # Check every 10 seconds
        
        while not self._stop_event.is_set():
            for name, path in endpoints:
                t0 = time.monotonic()
                
                try:
                    from merid.event_venues.kalshi.client import KalshiVenueClient
                    from merid.event_venues.kalshi.models import KalshiConfig
                    from merid.settings import settings
                    
                    config = KalshiConfig(
                        api_key=settings.KALSHI_API_KEY_ID,
                        private_key_path=settings.KALSHI_PRIVATE_KEY_PATH,
                    )
                    client = KalshiVenueClient(config)
                    
                    # Measure actual request
                    if path == "/markets":
                        result = await client.list_markets(limit=10)
                    elif path == "/portfolio/positions":
                        result = await client.get_positions_with_filters({})
                    else:
                        result = await client.get_balance()
                    
                    t1 = time.monotonic()
                    duration_ms = (t1 - t0) * 1000
                    
                    results.append(ProbeResult(
                        probe_name=name,
                        timestamp=t0,
                        duration_ms=duration_ms,
                        success=result.success if hasattr(result, 'success') else True,
                        metadata={
                            "path": path,
                            "status": "ok" if (hasattr(result, 'success') and result.success) else "error",
                        }
                    ))
                except Exception as e:
                    t1 = time.monotonic()
                    results.append(ProbeResult(
                        probe_name=name,
                        timestamp=t0,
                        duration_ms=(t1 - t0) * 1000,
                        success=False,
                        error=str(e),
                    ))
                
                # Small delay between endpoints
                await asyncio.sleep(0.5)
            
            # Wait before next round
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=probe_interval)
            except asyncio.TimeoutError:
                continue
        
        return results
    
    async def _loop_lag_probe(self) -> List[ProbeResult]:
        """Probe event-loop lag continuously."""
        results = []
        probe_interval = 1.0  # Sample every second
        
        while not self._stop_event.is_set():
            try:
                t0 = time.monotonic()
                expected_time = t0 + probe_interval
                
                # Try to sleep exactly probe_interval
                await asyncio.sleep(probe_interval)
                
                # Measure how late we are
                t1 = time.monotonic()
                lag_ms = max(0.0, (t1 - expected_time) * 1000)
                
                from merid.diagnostics.loop_lag import get_loop_lag_thresholds_ms

                _th = get_loop_lag_thresholds_ms()
                _h, _d, _halt = _th["healthy_ms"], _th["degrade_ms"], _th["halt_ms"]
                results.append(ProbeResult(
                    probe_name="event_loop_lag",
                    timestamp=t1,
                    duration_ms=lag_ms,  # This IS the lag measurement
                    success=lag_ms < _d,
                    metadata={
                        "lag_ms": round(lag_ms, 2),
                        "healthy": lag_ms < _h,
                        "degraded": _d <= lag_ms < _halt,
                        "critical": lag_ms >= _halt,
                    }
                ))
            except Exception as e:
                logger.warning(f"Loop lag probe error: {e}")
        
        return results
    
    async def _fills_sync_probe(self) -> List[ProbeResult]:
        """Probe fills synchronization status."""
        results = []
        probe_interval = 15.0  # Check every 15 seconds
        
        while not self._stop_event.is_set():
            try:
                t0 = time.monotonic()
                
                try:
                    from merid.event_venues.kalshi.fills_poller import get_fills_poller
                    poller = get_fills_poller()
                    health = poller.get_health()
                    
                    t1 = time.monotonic()
                    duration_ms = (t1 - t0) * 1000
                    
                    results.append(ProbeResult(
                        probe_name="fills_sync",
                        timestamp=t0,
                        duration_ms=duration_ms,
                        success=health.get("running", False),
                        metadata={
                            "running": health.get("running"),
                            "polls_completed": health.get("polls_completed"),
                            "polls_failed": health.get("polls_failed"),
                            "fills_ingested": health.get("fills_ingested"),
                            "last_poll_age_seconds": (
                                (datetime.now(timezone.utc) - datetime.fromisoformat(health["last_poll_time"])).total_seconds()
                                if health.get("last_poll_time") else None
                            ),
                            "reconciliation_status": health.get("reconciliation", {}).get("status"),
                        }
                    ))
                except Exception as e:
                    t1 = time.monotonic()
                    results.append(ProbeResult(
                        probe_name="fills_sync",
                        timestamp=t0,
                        duration_ms=(t1 - t0) * 1000,
                        success=False,
                        error=str(e),
                    ))
                
                await asyncio.wait_for(self._stop_event.wait(), timeout=probe_interval)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.warning(f"Fills probe error: {e}")
        
        return results
    
    async def _position_sync_probe(self) -> List[ProbeResult]:
        """Probe position cache synchronization."""
        results = []
        probe_interval = 20.0  # Check every 20 seconds
        
        while not self._stop_event.is_set():
            try:
                t0 = time.monotonic()
                
                try:
                    from merid.event_venues.kalshi.position_cache import get_position_cache
                    cache = get_position_cache()
                    positions = cache.get_all_positions()
                    
                    t1 = time.monotonic()
                    duration_ms = (t1 - t0) * 1000
                    
                    results.append(ProbeResult(
                        probe_name="position_cache",
                        timestamp=t0,
                        duration_ms=duration_ms,
                        success=True,
                        metadata={
                            "position_count": len(positions),
                            "last_sync_age_seconds": (
                                (datetime.now(timezone.utc) - cache._last_sync).total_seconds()
                                if cache._last_sync else None
                            ),
                        }
                    ))
                except Exception as e:
                    t1 = time.monotonic()
                    results.append(ProbeResult(
                        probe_name="position_cache",
                        timestamp=t0,
                        duration_ms=(t1 - t0) * 1000,
                        success=False,
                        error=str(e),
                    ))
                
                await asyncio.wait_for(self._stop_event.wait(), timeout=probe_interval)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.warning(f"Position probe error: {e}")
        
        return results


async def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Kalshi Pipeline Diagnostics Probe")
    parser.add_argument("--duration", type=int, default=30, help="Probe duration in seconds")
    parser.add_argument("--output", choices=["json", "text"], default="text", help="Output format")
    args = parser.parse_args()
    
    probe = KalshiPipelineProbe(duration_seconds=args.duration)
    
    # Handle Ctrl+C gracefully
    def signal_handler():
        probe.stop()
    
    try:
        report = await probe.run()
        
        if args.output == "json":
            print(json.dumps(report.to_dict(), indent=2))
        else:
            print("\n" + "="*60)
            print("KALSHI PIPELINE DIAGNOSTICS REPORT")
            print("="*60)
            print(f"Duration: {report.duration_seconds}s")
            print(f"From: {report.start_time}")
            print(f"To: {report.end_time}")
            print("\nSUMMARY:")
            for name, stats in report._summary().items():
                print(f"\n  {name}:")
                print(f"    Samples: {stats['count']}")
                print(f"    Success: {stats['success']}/{stats['count']}")
                if stats['avg_ms']:
                    print(f"    Avg/P95/Max: {stats['avg_ms']}ms / {stats['p95_ms']}ms / {stats['max_ms']}ms")
            print("\n" + "="*60)
    
    except KeyboardInterrupt:
        probe.stop()
        print("\nProbe interrupted")
    
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

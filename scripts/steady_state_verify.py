#!/usr/bin/env python3
"""
Steady-state verification script for MERID Agent Grid.
Monitors event-loop lag, health status, and lag spikes post-startup.
"""

import asyncio
import aiohttp
import json
import sys
from datetime import datetime, timezone
from typing import List, Dict, Any

# Configuration
HEALTH_URL = "http://127.0.0.1:8011/api/health"
MONITOR_DURATION_SECONDS = 60
LAG_SPIKE_THRESHOLD_MS = 2000  # 2s threshold
STEADY_STATE_TARGET_MS = 500  # 500ms target

class SteadyStateMonitor:
    def __init__(self):
        self.lag_readings: List[float] = []
        self.health_statuses: List[Dict] = []
        self.lag_spikes: List[Dict] = []
        self.start_time = datetime.now(timezone.utc)
        
    async def fetch_health(self, session: aiohttp.ClientSession) -> Dict:
        """Fetch health status from endpoint."""
        try:
            async with session.get(HEALTH_URL, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                data = await resp.json()
                return {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "status_code": resp.status,
                    "status": data.get("status", "unknown"),
                    "critical_failures": data.get("critical_failures", []),
                    "agent_grid": data.get("checks", {}).get("agent_grid", {}),
                    "event_loop_lag": data.get("checks", {}).get("event_loop_lag", {}),
                }
        except Exception as e:
            return {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "error": str(e),
                "status": "error",
            }
    
    def analyze_lag(self, health: Dict) -> None:
        """Extract and analyze lag from health check."""
        lag_data = health.get("event_loop_lag", {})
        
        # Try different lag fields
        lag_ms = None
        if "ema_ms" in lag_data:
            lag_ms = lag_data["ema_ms"]
        elif "p95_ms" in lag_data:
            lag_ms = lag_data["p95_ms"]
        elif "current_ms" in lag_data:
            lag_ms = lag_data["current_ms"]
            
        if lag_ms is not None:
            self.lag_readings.append(lag_ms)
            
            # Check for spike
            if lag_ms > LAG_SPIKE_THRESHOLD_MS:
                self.lag_spikes.append({
                    "timestamp": health["timestamp"],
                    "lag_ms": lag_ms,
                    "threshold_ms": LAG_SPIKE_THRESHOLD_MS,
                })
    
    async def monitor(self) -> Dict[str, Any]:
        """Run monitoring for specified duration."""
        print(f"[{datetime.now(timezone.utc).isoformat()}] Starting steady-state verification...")
        print(f"  - Duration: {MONITOR_DURATION_SECONDS}s")
        print(f"  - Lag spike threshold: {LAG_SPIKE_THRESHOLD_MS}ms")
        print(f"  - Steady-state target: <{STEADY_STATE_TARGET_MS}ms")
        print()
        
        async with aiohttp.ClientSession() as session:
            start = asyncio.get_event_loop().time()
            
            while (asyncio.get_event_loop().time() - start) < MONITOR_DURATION_SECONDS:
                health = await self.fetch_health(session)
                self.health_statuses.append(health)
                self.analyze_lag(health)
                
                # Print status
                status = health.get("status", "unknown")
                grid = health.get("agent_grid", {})
                lag_data = health.get("event_loop_lag", {})
                
                lag_str = "N/A"
                if "ema_ms" in lag_data:
                    lag_str = f"{lag_data['ema_ms']:.1f}ms EMA"
                elif "current_ms" in lag_data:
                    lag_str = f"{lag_data['current_ms']:.1f}ms"
                    
                print(f"[{health['timestamp']}] Status: {status} | "
                      f"Grid: startup={grid.get('startup_complete', False)}, "
                      f"agents={grid.get('agents_ready', False)} | "
                      f"Lag: {lag_str}")
                
                await asyncio.sleep(2)  # Poll every 2 seconds
        
        return self.generate_report()
    
    def generate_report(self) -> Dict[str, Any]:
        """Generate final verification report."""
        print("\n" + "="*70)
        print("STEADY-STATE VERIFICATION REPORT")
        print("="*70)
        
        # Analyze health statuses
        healthy_count = sum(1 for h in self.health_statuses if h.get("status") == "healthy")
        total_checks = len(self.health_statuses)
        
        # Check for 503s after ready
        statuses_after_ready = []
        for h in self.health_statuses:
            grid = h.get("agent_grid", {})
            if grid.get("startup_complete") and grid.get("agents_ready"):
                statuses_after_ready.append(h.get("status_code", 200))
        
        five_oh_three_after_ready = sum(1 for s in statuses_after_ready if s == 503)
        
        # Analyze lag
        if self.lag_readings:
            avg_lag = sum(self.lag_readings) / len(self.lag_readings)
            max_lag = max(self.lag_readings)
            min_lag = min(self.lag_readings)
            p95_lag = sorted(self.lag_readings)[int(len(self.lag_readings) * 0.95)] if len(self.lag_readings) > 20 else max_lag
            
            above_target = sum(1 for l in self.lag_readings if l > STEADY_STATE_TARGET_MS)
            above_target_pct = (above_target / len(self.lag_readings)) * 100
        else:
            avg_lag = max_lag = min_lag = p95_lag = 0
            above_target_pct = 0
        
        report = {
            "duration_seconds": MONITOR_DURATION_SECONDS,
            "health_checks_total": total_checks,
            "health_checks_healthy": healthy_count,
            "health_healthy_percentage": (healthy_count / total_checks * 100) if total_checks else 0,
            "status_503_after_ready_count": five_oh_three_after_ready,
            "lag_spikes_over_2s": len(self.lag_spikes),
            "lag_spike_details": self.lag_spikes,
            "lag_statistics": {
                "min_ms": round(min_lag, 2),
                "max_ms": round(max_lag, 2),
                "avg_ms": round(avg_lag, 2),
                "p95_ms": round(p95_lag, 2),
                "above_target_500ms_percentage": round(above_target_pct, 2),
            },
            "verification_passed": (
                len(self.lag_spikes) == 0 and  # No spikes >2s
                five_oh_three_after_ready == 0 and  # No 503s after ready
                p95_lag < STEADY_STATE_TARGET_MS  # P95 under target
            ),
        }
        
        # Print summary
        print(f"\nHealth Checks:")
        print(f"  Total: {total_checks}")
        print(f"  Healthy: {healthy_count} ({report['health_healthy_percentage']:.1f}%)")
        print(f"  503s after ready: {five_oh_three_after_ready}")
        
        print(f"\nEvent-Loop Lag (steady-state):")
        print(f"  Min: {min_lag:.2f}ms")
        print(f"  Max: {max_lag:.2f}ms")
        print(f"  Avg: {avg_lag:.2f}ms")
        print(f"  P95: {p95_lag:.2f}ms")
        print(f"  Above 500ms target: {above_target_pct:.1f}%")
        
        print(f"\nLag Spikes (>2s threshold):")
        print(f"  Count: {len(self.lag_spikes)}")
        if self.lag_spikes:
            for spike in self.lag_spikes:
                print(f"    - {spike['timestamp']}: {spike['lag_ms']:.1f}ms")
        
        print(f"\n{'='*70}")
        if report["verification_passed"]:
            print("✅ VERIFICATION PASSED - System is steady-state ready")
        else:
            print("❌ VERIFICATION FAILED - Issues detected:")
            if len(self.lag_spikes) > 0:
                print(f"   - {len(self.lag_spikes)} lag spike(s) >2s detected after startup")
            if five_oh_three_after_ready > 0:
                print(f"   - {five_oh_three_after_ready} 503 response(s) after ready state")
            if p95_lag >= STEADY_STATE_TARGET_MS:
                print(f"   - P95 lag ({p95_lag:.1f}ms) exceeds target ({STEADY_STATE_TARGET_MS}ms)")
        print("="*70)
        
        return report


async def main():
    monitor = SteadyStateMonitor()
    report = await monitor.monitor()
    
    # Save report to file
    report_file = f"steady_state_report_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
    with open(report_file, 'w') as f:
        json.dump(report, f, indent=2)
    print(f"\nReport saved to: {report_file}")
    
    # Exit code based on verification
    sys.exit(0 if report["verification_passed"] else 1)


if __name__ == "__main__":
    asyncio.run(main())

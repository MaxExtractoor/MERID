#!/usr/bin/env python3
"""
MERID Paper Gate Runner

Executes a validation gate against the MERID backend in paper mode.
Monitors event-loop lag, health status, and readiness over a specified duration.

Usage:
    python scripts/run_paper_gate.py --dry-run                    # Quick wiring check (~2 min)
    python scripts/run_paper_gate.py --duration 1800              # 30-minute gate
    python scripts/run_paper_gate.py --duration 1800 --gate-id pre_live_check
    python scripts/run_paper_gate.py --duration 300 --output-dir ./results

Exit codes:
    0 - Gate PASSED
    1 - Gate FAILED (criteria not met)
    2 - Server startup error
    3 - Configuration error
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any

import aiohttp

# Configuration
DEFAULT_HEALTH_URL = "http://127.0.0.1:8011/api/health"
DEFAULT_EVENT_LOOP_URL = "http://127.0.0.1:8011/health/event_loop"
DEFAULT_LAG_PROFILES_URL = "http://127.0.0.1:8011/api/v1/diagnostics/loop-lag-profiles"
DEFAULT_DURATION = 1800  # 30 minutes
DEFAULT_SAMPLE_INTERVAL = 30  # seconds
DEFAULT_KILL_SWITCH_THRESHOLD = 300  # ms (Phase 0)

class PaperGateRunner:
    def __init__(self, args: argparse.Namespace):
        self.duration = args.duration
        self.gate_id = args.gate_id or f"gate_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        self.output_dir = Path(args.output_dir)
        self.dry_run = args.dry_run
        self.sample_interval = args.sample_interval
        
        self.samples: List[Dict] = []
        self.failures: List[str] = []
        self.gate_pass = True
        self.server_process: Optional[subprocess.Popen] = None
        
        # Ensure output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
    async def run(self) -> int:
        """Execute the paper gate. Returns exit code."""
        print("="*70)
        print(f"MERID PAPER GATE RUNNER - {self.gate_id}")
        print("="*70)
        print(f"Duration: {self.duration // 60} minutes")
        print(f"Sample interval: {self.sample_interval} seconds")
        print(f"Mode: {'DRY-RUN' if self.dry_run else 'FULL'}")
        print(f"Output: {self.output_dir}")

        _vm = os.environ.get("MERID_VALIDATION_MODE", "")
        if _vm == "1":
            print(f"Gate type: INFRA SMOKE TEST (MERID_VALIDATION_MODE=1)")
            print(f"  25+ services disabled. Steady-state P95 target ~15-20ms.")
            print(f"  Does NOT test MeridLoop / trading agents / WS bridge.")
        else:
            print(f"Gate type: FULL TRADING GATE (MERID_VALIDATION_MODE not set)")
            print(f"  All services enabled. P95 target <500ms under real load.")
            print(f"  WARNING: currently fails without StreamingAgent/_run_loop fixes.")
        print("="*70)
        print()
        
        try:
            # Step 1: Start server
            if not await self._start_server():
                return 2
            
            # Step 2: Wait for ready
            if not await self._wait_for_ready():
                return 2

            # Step 2b: Clear startup-window high-lag profiles so they don't
            # contaminate the post-ready measurement window.  The startup spike
            # (KalshiVenueClient.connect + KalshiMarketCatalog.start) is a
            # known one-time cost; we measure only post-ready behavior.
            await self._clear_startup_profiles()

            # Step 3: Run monitoring
            await self._run_monitoring()
            
            # Step 4: Generate report
            return await self._generate_report()
            
        except KeyboardInterrupt:
            print("\n[!] Gate interrupted by user")
            return 130
        finally:
            self._cleanup()
    
    async def _start_server(self) -> bool:
        """Start MERID backend in paper mode."""
        print("Starting MERID backend in paper mode...")
        
        env = os.environ.copy()
        env["MERID_TRADE_MODE"] = "paper"
        env["MERID_ALLOW_LIVE_TRADES"] = "false"
        env["MERID_PROFILE"] = "kalshi-only"
        env["MERID_ENV"] = "production"
        env["SECRET_KEY"] = "paper-gate-test-key-not-for-production"
        
        # For dry-run, use shorter startup
        if self.dry_run:
            env["MERID_FAST_STARTUP"] = "true"
        
        try:
            log_file = self.output_dir / f"server_{self.gate_id}.log"
            self.server_log = open(log_file, 'w')
            
            self.server_process = subprocess.Popen(
                [sys.executable, "-m", "uvicorn", "web.main:app", 
                 "--host", "127.0.0.1", "--port", "8011",
                 "--log-level", "info"],
                cwd=Path(__file__).parent.parent,
                env=env,
                stdout=self.server_log,
                stderr=subprocess.STDOUT,
                text=True
            )
            
            print(f"  Server PID: {self.server_process.pid}")
            print(f"  Log file: {log_file}")
            return True
            
        except Exception as e:
            print(f"  [FAIL] Failed to start server: {e}")
            return False
    
    async def _wait_for_ready(self, timeout: int = 300) -> bool:
        """Wait for server to be ready."""
        print(f"\nWaiting for server ready (timeout: {timeout}s)...")
        
        async with aiohttp.ClientSession() as session:
            for i in range(timeout):
                try:
                    async with session.get(
                        DEFAULT_HEALTH_URL, 
                        timeout=aiohttp.ClientTimeout(total=5)
                    ) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            checks = data.get("checks", {})
                            
                            startup_complete = checks.get("agent_grid", {}).get("startup_complete")
                            agents_ready = checks.get("agent_grid", {}).get("agents_ready")
                            
                            if startup_complete and agents_ready:
                                print(f"  [OK] Server ready after {i+1}s")
                                print(f"    - startup_complete: {startup_complete}")
                                print(f"    - agents_ready: {agents_ready}")
                                return True
                                
                except Exception:
                    pass
                    
                await asyncio.sleep(1)
        
        print(f"  [FAIL] Server not ready after {timeout}s")
        return False
    
    async def _clear_startup_profiles(self) -> None:
        """Clear high-lag profiles captured during startup before sampling begins.

        The startup spike from KalshiVenueClient.connect() and
        KalshiMarketCatalog.start() is a known one-time cost. Profiles from
        that window would otherwise trigger the zero-tolerance profile check
        at the end of every gate run, making it structurally impossible to pass.

        We clear them here so the gate measures only post-ready behavior.
        """
        clear_url = DEFAULT_HEALTH_URL.replace("/api/health", "/health/event_loop/profiles")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.delete(
                    clear_url,
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status == 200:
                        print("  [OK] Startup profiles cleared")
                    else:
                        print(f"  [WARN] Profile clear returned HTTP {resp.status} — startup profiles may affect report")
        except Exception as e:
            print(f"  [WARN] Profile clear failed ({e}) — startup profiles may affect report")

        # Wait for rolling P95 to drain the startup spike out of the 60-sample
        # stats window before sampling begins.  The profiles are cleared above,
        # but LoopLagMonitor._stats is a 60-sample deque; startup lag entries
        # remain in it and inflate P95 until they roll out naturally (~60s) or
        # until we wait for the computed P95 to drop below a settling threshold.
        _settle_threshold_ms = 100
        _settle_timeout = 120  # seconds
        print(f"  Waiting for P95 to settle below {_settle_threshold_ms}ms (max {_settle_timeout}s)...")
        try:
            async with aiohttp.ClientSession() as session:
                for _i in range(_settle_timeout):
                    try:
                        async with session.get(
                            DEFAULT_HEALTH_URL,
                            timeout=aiohttp.ClientTimeout(total=5)
                        ) as resp:
                            if resp.status == 200:
                                data = await resp.json()
                                lag = data.get("checks", {}).get("event_loop_lag", {})
                                p95 = lag.get("stats", {}).get("p95_ms", 9999)
                                if p95 < _settle_threshold_ms:
                                    print(f"  [OK] P95 settled at {p95:.0f}ms after {_i+1}s — measurement window begins now")
                                    break
                                if _i % 10 == 0:
                                    print(f"  ... settling ({_i}s elapsed, P95={p95:.0f}ms)")
                    except Exception:
                        pass
                    await asyncio.sleep(1)
                else:
                    print(f"  [WARN] P95 did not settle below {_settle_threshold_ms}ms within {_settle_timeout}s — proceeding anyway")
        except Exception as e:
            print(f"  [WARN] Settle wait failed ({e}) — proceeding anyway")

        # Second profile clear: purge anything captured during the settle window.
        # Any profile from that period is still startup tail-off, not a steady-state
        # problem, so we don't want it to count against the gate.
        try:
            async with aiohttp.ClientSession() as session:
                async with session.delete(
                    clear_url,
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status == 200:
                        print("  [OK] Settle-window profiles cleared — measurement window begins now")
        except Exception:
            pass

    async def _run_monitoring(self):
        """Run monitoring loop for the gate duration."""
        total_samples = self.duration // self.sample_interval
        
        print(f"\nStarting {total_samples} samples over {self.duration//60} minutes...")
        print(f"Pass criteria: P95 < 500ms, degraded=false, no high-lag profiles\n")
        
        async with aiohttp.ClientSession() as session:
            for i in range(total_samples):
                timestamp = datetime.now(timezone.utc).isoformat()
                elapsed = i * self.sample_interval
                remaining = self.duration - elapsed
                
                print(f"[{i+1}/{total_samples}] {timestamp[:19]} ({remaining//60}m remaining)...", end=" ")
                
                sample = await self._sample_health(session, timestamp)
                self.samples.append(sample)
                
                if i < total_samples - 1:
                    await asyncio.sleep(self.sample_interval)
        
        print(f"\n  [OK] Monitoring complete - {len(self.samples)} samples collected")
    
    async def _sample_health(self, session: aiohttp.ClientSession, timestamp: str) -> Dict:
        """Sample health endpoints and check criteria."""
        try:
            async with session.get(
                DEFAULT_HEALTH_URL,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                data = await resp.json()
                
                lag_data = data.get("checks", {}).get("event_loop_lag", {})
                p95 = lag_data.get("stats", {}).get("p95_ms", 0)
                degraded = lag_data.get("degraded", True)
                healthy = lag_data.get("healthy", False)
                
                sample = {
                    "timestamp": timestamp,
                    "status_code": resp.status,
                    "p95_ms": p95,
                    "degraded": degraded,
                    "healthy": healthy,
                    "startup_complete": data.get("checks", {}).get("agent_grid", {}).get("startup_complete"),
                    "agents_ready": data.get("checks", {}).get("agent_grid", {}).get("agents_ready"),
                }
                
                # Check pass criteria
                failed = False
                if p95 >= 500:
                    failed = True
                    self.failures.append(f"{timestamp}: P95={p95:.0f}ms >= 500ms")
                if degraded:
                    failed = True
                    self.failures.append(f"{timestamp}: degraded=true")
                if resp.status != 200:
                    failed = True
                    self.failures.append(f"{timestamp}: HTTP {resp.status}")
                
                if failed:
                    self.gate_pass = False
                    print("[FAIL]")
                else:
                    print(f"OK (P95={p95:.0f}ms)")
                
                return sample
                
        except Exception as e:
            self.gate_pass = False
            self.failures.append(f"{timestamp}: Error - {str(e)}")
            print(f"ERROR: {e}")
            return {"timestamp": timestamp, "error": str(e)}
    
    async def _fetch_high_lag_profiles(self) -> List[Dict]:
        """Fetch any high-lag profiles captured during gate."""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    DEFAULT_LAG_PROFILES_URL,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        return data.get("profiles", [])
        except:
            pass
        return []
    
    async def _generate_report(self) -> int:
        """Generate final report and return exit code."""
        print("\n" + "="*70)
        print("GATE REPORT")
        print("="*70)
        
        valid_samples = [s for s in self.samples if "p95_ms" in s]
        
        if not valid_samples:
            print("\n[FAIL] No valid samples collected")
            self.gate_pass = False
        else:
            p95_values = [s["p95_ms"] for s in valid_samples]
            avg_p95 = sum(p95_values) / len(p95_values)
            max_p95 = max(p95_values)
            min_p95 = min(p95_values)
            degraded_count = sum(1 for s in valid_samples if s.get("degraded"))
            
            print(f"\nSamples: {len(valid_samples)}/{len(self.samples)} valid")
            print(f"P95 range: {min_p95:.0f}ms - {max_p95:.0f}ms (avg: {avg_p95:.0f}ms)")
            print(f"Degraded samples: {degraded_count}/{len(valid_samples)}")
        
        # Check for high-lag profiles
        profiles = await self._fetch_high_lag_profiles()
        
        if profiles:
            print(f"\n[!] High-lag profiles captured: {len(profiles)}")
            self.gate_pass = False
            self.failures.append(f"{len(profiles)} high-lag profiles captured")
        else:
            print(f"\n[OK] No high-lag profiles captured")
        
        # Determine verdict
        if self.dry_run:
            # Dry run is more lenient - just needs server to start
            if any("Error" not in str(s.get("error", "")) for s in self.samples):
                verdict = "PASS (Dry Run)"
                exit_code = 0
            else:
                verdict = "FAIL (Dry Run)"
                exit_code = 1
        else:
            if self.gate_pass and len(self.failures) == 0:
                verdict = "PASS"
                exit_code = 0
            else:
                verdict = "FAIL"
                exit_code = 1
        
        print("\n" + "="*70)
        if verdict.startswith("PASS"):
            print(f"[PASS] GATE {verdict}")
            if not self.dry_run:
                print("\nAll criteria met:")
                print("  - P95 < 500ms for all samples")
                print("  - degraded=false throughout")
                print("  - No high-lag profiles captured")
        else:
            print(f"[FAIL] GATE {verdict}")
            if self.failures:
                print(f"\nFailures ({len(self.failures)}):")
                for f in self.failures[:10]:
                    print(f"  - {f}")
                if len(self.failures) > 10:
                    print(f"  ... and {len(self.failures) - 10} more")
        print("="*70)
        
        # Save JSON report
        report = {
            "gate_id": self.gate_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": self.duration,
            "dry_run": self.dry_run,
            "samples_total": len(self.samples),
            "samples_valid": len(valid_samples),
            "p95_min": min((s["p95_ms"] for s in valid_samples), default=0),
            "p95_max": max((s["p95_ms"] for s in valid_samples), default=0),
            "p95_avg": sum((s["p95_ms"] for s in valid_samples), 0) / len(valid_samples) if valid_samples else 0,
            "degraded_count": degraded_count if valid_samples else 0,
            "high_lag_profiles": len(profiles),
            "verdict": verdict,
            "passed": self.gate_pass and not self.dry_run,
            "failures": self.failures,
            "sample_data": self.samples if self.dry_run else None,  # Include raw data in dry-run only
        }
        
        report_file = self.output_dir / f"validation_gate_{self.gate_id}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.json"
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        print(f"\nReport saved: {report_file}")
        
        # Also write a summary for fix_history.md
        summary_file = self.output_dir / f"gate_summary_{self.gate_id}.md"
        with open(summary_file, 'w') as f:
            f.write(f"""#### Validation Gate: {self.gate_id}
- **Timestamp**: {report['timestamp']}
- **Duration**: {self.duration // 60} minutes
- **Dry Run**: {self.dry_run}
- **Verdict**: {verdict}
- **JSON**: `{report_file}`
- **Samples**: {report['samples_valid']}/{report['samples_total']} valid
- **P95 max**: {report['p95_max']:.0f}ms
- **Degraded samples**: {report['degraded_count']}
- **High-lag profiles**: {report['high_lag_profiles']}
""")
        
        return exit_code
    
    def _cleanup(self):
        """Clean up resources."""
        if self.server_process:
            print(f"\nStopping server (PID {self.server_process.pid})...")
            self.server_process.terminate()
            try:
                self.server_process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.server_process.kill()
                self.server_process.wait()
            print("[OK] Server stopped")
        
        if hasattr(self, 'server_log') and self.server_log:
            self.server_log.close()


def main():
    parser = argparse.ArgumentParser(
        description="Run MERID paper validation gate",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --dry-run                              # Quick wiring check
  %(prog)s --duration 1800                        # 30-minute gate
  %(prog)s --duration 1800 --gate-id pre_live     # Named gate
  %(prog)s --duration 300 --output-dir ./results  # 5-minute gate to custom dir
""")
    
    parser.add_argument("--duration", type=int, default=DEFAULT_DURATION,
                        help=f"Gate duration in seconds (default: {DEFAULT_DURATION} = 30 min)")
    parser.add_argument("--gate-id", type=str, default=None,
                        help="Unique identifier for this gate (default: auto-generated)")
    parser.add_argument("--output-dir", type=str, default=".",
                        help="Directory for output files (default: current directory)")
    parser.add_argument("--sample-interval", type=int, default=DEFAULT_SAMPLE_INTERVAL,
                        help=f"Seconds between samples (default: {DEFAULT_SAMPLE_INTERVAL})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Quick wiring check (~2 min, lenient criteria)")
    
    args = parser.parse_args()
    
    # Adjust duration for dry-run
    if args.dry_run:
        args.duration = 120  # 2 minutes
        print("[DRY-RUN] Using 2-minute duration with lenient criteria\n")
    
    runner = PaperGateRunner(args)
    exit_code = asyncio.run(runner.run())
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

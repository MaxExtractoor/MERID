"""SRE Baseline Capture — Cold-start latency, RSS/heap, time-to-first-Kalshi-call.

Usage:
    py scripts/sre_baseline_capture.py [--port 8011] [--output reports/sre-baseline.json]

Measures:
    1. Cold-start latency: time from subprocess spawn → /api/v1/health returns 200
    2. RSS / heap 60s after startup
    3. Time-to-first-Kalshi-call: latency of GET /api/v1/kalshi/markets?limit=1

Outputs JSON with all metrics + metadata for trend tracking.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import psutil
except ImportError:
    psutil = None

try:
    import requests
except ImportError:
    requests = None


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PORT = 8011
HEALTH_ENDPOINT = "/api/v1/system/status"
KALSHI_MARKETS_ENDPOINT = "/api/v1/kalshi/markets?limit=1"
STARTUP_TIMEOUT_S = 180
POLL_INTERVAL_S = 0.5
SETTLE_WAIT_S = 60


def _base_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def _check_health(port: int) -> bool:
    """Return True if the health endpoint responds 200."""
    if requests is None:
        raise RuntimeError("Install requests: pip install requests")
    try:
        r = requests.get(f"{_base_url(port)}{HEALTH_ENDPOINT}", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _get_process_memory(pid: int) -> dict:
    """Return RSS and VMS in MB for a given PID."""
    if psutil is None:
        return {"rss_mb": None, "vms_mb": None, "error": "psutil not installed"}
    try:
        proc = psutil.Process(pid)
        mem = proc.memory_info()
        return {
            "rss_mb": round(mem.rss / 1024 / 1024, 1),
            "vms_mb": round(mem.vms / 1024 / 1024, 1),
        }
    except Exception as exc:
        return {"rss_mb": None, "vms_mb": None, "error": str(exc)}


def _measure_kalshi_call(port: int) -> dict:
    """Time a GET to the Kalshi markets endpoint."""
    if requests is None:
        return {"latency_ms": None, "status": None, "error": "requests not installed"}
    url = f"{_base_url(port)}{KALSHI_MARKETS_ENDPOINT}"
    try:
        t0 = time.perf_counter()
        r = requests.get(url, timeout=15)
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        return {"latency_ms": latency_ms, "status": r.status_code}
    except Exception as exc:
        return {"latency_ms": None, "status": None, "error": str(exc)}


def _check_server_already_running(port: int) -> bool:
    """Check if a server is already listening on the port."""
    try:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect(("127.0.0.1", port))
            return True
    except Exception:
        return False


def run_baseline(port: int, output_path: str | None, skip_spawn: bool = False):
    """Run the full baseline capture."""
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "profile": os.getenv("MERID_PROFILE", "default"),
        "port": port,
    }

    proc = None
    pid = None

    if skip_spawn:
        # Server already running — measure against it
        print(f"[SRE] Using existing server on port {port}")
        result["spawn_mode"] = "existing"
        pid = None
    else:
        # Spawn the server
        print(f"[SRE] Spawning server on port {port}...")
        env = os.environ.copy()
        env.setdefault("MERID_PROFILE", "kalshi-only")
        env.setdefault("KALSHI_ONLY", "true")
        t_spawn = time.perf_counter()

        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "web.main:app",
             "--host", "127.0.0.1", "--port", str(port),
             "--log-level", "warning"],
            cwd=str(ROOT),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        pid = proc.pid
        result["spawn_mode"] = "subprocess"
        result["pid"] = pid

        # Wait for health
        print(f"[SRE] Waiting for health endpoint (timeout {STARTUP_TIMEOUT_S}s)...")
        healthy = False
        while time.perf_counter() - t_spawn < STARTUP_TIMEOUT_S:
            if _check_health(port):
                healthy = True
                break
            if proc.poll() is not None:
                stdout = proc.stdout.read().decode(errors="replace")[-500:]
                stderr = proc.stderr.read().decode(errors="replace")[-500:]
                result["error"] = f"Server exited with code {proc.returncode}"
                result["stderr_tail"] = stderr
                result["stdout_tail"] = stdout
                _write_output(result, output_path)
                return result
            time.sleep(POLL_INTERVAL_S)

        cold_start_s = round(time.perf_counter() - t_spawn, 2)
        result["cold_start_s"] = cold_start_s
        result["cold_start_healthy"] = healthy

        if not healthy:
            result["error"] = f"Server did not become healthy within {STARTUP_TIMEOUT_S}s"
            if proc:
                proc.terminate()
            _write_output(result, output_path)
            return result

        print(f"[SRE] Server healthy in {cold_start_s}s")

    # Settle wait
    print(f"[SRE] Waiting {SETTLE_WAIT_S}s for memory to settle...")
    time.sleep(SETTLE_WAIT_S)

    # Memory capture
    if pid:
        mem = _get_process_memory(pid)
        result["memory_after_settle"] = mem
        print(f"[SRE] RSS={mem.get('rss_mb')}MB, VMS={mem.get('vms_mb')}MB")
    else:
        result["memory_after_settle"] = {"note": "PID not available (existing server)"}

    # Time-to-first-Kalshi-call
    print("[SRE] Measuring time-to-first-Kalshi-call...")
    kalshi = _measure_kalshi_call(port)
    result["first_kalshi_call"] = kalshi
    print(f"[SRE] Kalshi markets: {kalshi.get('latency_ms')}ms (status {kalshi.get('status')})")

    # Cleanup
    if proc:
        print("[SRE] Terminating server...")
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()

    _write_output(result, output_path)
    return result


def _write_output(result: dict, output_path: str | None):
    """Write results to JSON file and stdout."""
    print("\n" + "=" * 60)
    print("SRE BASELINE RESULTS")
    print("=" * 60)
    print(json.dumps(result, indent=2))

    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        # Append to array if file exists
        if out.exists():
            try:
                existing = json.loads(out.read_text())
                if isinstance(existing, list):
                    existing.append(result)
                else:
                    existing = [existing, result]
            except Exception:
                existing = [result]
        else:
            existing = [result]

        out.write_text(json.dumps(existing, indent=2))
        print(f"\n[SRE] Results appended to {out}")


def main():
    parser = argparse.ArgumentParser(description="SRE Baseline Capture")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--output", default="reports/sre-baseline.json")
    parser.add_argument("--existing", action="store_true",
                        help="Measure against an already-running server (skip spawn)")
    args = parser.parse_args()

    if args.existing or _check_server_already_running(args.port):
        if _check_server_already_running(args.port):
            print(f"[SRE] Detected existing server on port {args.port}")
        run_baseline(args.port, args.output, skip_spawn=True)
    else:
        run_baseline(args.port, args.output, skip_spawn=False)


if __name__ == "__main__":
    main()

"""
Live 15m End-to-End Telemetry Probe

This script runs alongside the 15m stack, pulling real data from each layer
and logging anomalies if anything deviates from codified expectations.

Usage:
    python -m merid.monitoring.live_15m_end_to_end_probe

The probe validates:
- WebSocket health (connection, latency, heartbeat age)
- Spot service health (freshness, staleness)
- Orderbook health (consistency, dual-sided, spread)
- Risk environment (utilization, capacity)
- Gate decisions (overall status, reasons)

Anomalies are logged with explicit tags for easy filtering and alerting.
"""

import os
import sys
import time
import requests
import logging
import json
from datetime import datetime
from typing import Dict, Any, Optional

# Configure logging
log = logging.getLogger("merid.monitoring.live_15m_probe")
log.setLevel(logging.INFO)

# Add console handler
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.INFO)
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
handler.setFormatter(formatter)
log.addHandler(handler)

# Health snapshot API endpoint
api_host = os.getenv("MERID_API_HOST", "127.0.0.1")
api_port = os.getenv("MERID_API_PORT", "8011")
HEALTH_URL = os.environ.get(
    "MERID_HEALTH_SNAPSHOT_URL",
    f"http://{api_host}:{api_port}/api/v1/health-snapshot/"
)

# Assets being monitored
ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]

# Thresholds from config/spec
MAX_WS_LATENCY_MS = 5000.0  # 5 seconds
MAX_WS_HEARTBEAT_AGE_S = 10.0  # 10 seconds
MAX_SPOT_AGE_S = 30.0  # 30 seconds
MAX_SPOT_STALE_AGE_S = 60.0  # 60 seconds (hard fail)
MAX_BOOK_AGE_S = 10.0  # 10 seconds
MAX_SPREAD_PCT = 10.0  # 10% spread
MAX_RISK_UTILIZATION_PCT = 0.95  # 95% utilization

# Expected states
EXPECTED_WS_STATE = "CONNECTED"
EXPECTED_BOOK_CONSISTENCY = "GOOD"
EXPECTED_SPOT_RUNNING = True
EXPECTED_GATE_OVERALL = "PASS"
EXPECTED_QUARANTINE_PATH = "active"

# Monitoring interval (seconds)
MONITOR_INTERVAL = 5.0

# Output directory for JSON snapshots
OUTPUT_DIR = os.environ.get("MERID_PROBE_OUTPUT_DIR", "./probe_snapshots")


def fetch_health_snapshot() -> Dict[str, Any]:
    """Fetch health snapshot from API."""
    try:
        resp = requests.get(HEALTH_URL, timeout=5.0)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.RequestException as e:
        log.error(f"[15M-PROBE-ERROR] Failed to fetch health snapshot: {e}")
        raise


def check_ws(snapshot: Dict[str, Any]) -> None:
    """Check WebSocket health metrics."""
    ws = snapshot.get("ws", {})
    
    connection_state = ws.get("connection_state", "UNKNOWN")
    latency_ms = ws.get("latency_ms", 0.0)
    heartbeat_age_s = ws.get("heartbeat_age_s", 9999.0)
    is_connected = ws.get("is_connected", False)
    
    # Check connection state
    if connection_state != EXPECTED_WS_STATE:
        log.error(
            f"[15M-PROBE-ANOMALY] type=ws_state expected={EXPECTED_WS_STATE} "
            f"actual={connection_state}"
        )
    
    # Check connection status
    if not is_connected:
        log.error(f"[15M-PROBE-ANOMALY] type=ws_connected actual=False")
    
    # Check latency
    if latency_ms > MAX_WS_LATENCY_MS:
        log.error(
            f"[15M-PROBE-ANOMALY] type=ws_latency actual={latency_ms:.0f}ms "
            f"threshold={MAX_WS_LATENCY_MS:.0f}ms"
        )
    
    # Check heartbeat age
    if heartbeat_age_s > MAX_WS_HEARTBEAT_AGE_S:
        log.error(
            f"[15M-PROBE-ANOMALY] type=ws_heartbeat_age actual={heartbeat_age_s:.1f}s "
            f"threshold={MAX_WS_HEARTBEAT_AGE_S:.1f}s"
        )


def check_spot(snapshot: Dict[str, Any]) -> None:
    """Check spot service health metrics."""
    spot = snapshot.get("spot", {})
    
    last_update_age_s = spot.get("last_update_age_s", 9999.0)
    service_running = spot.get("service_running", False)
    is_stale = spot.get("is_stale", False)
    stale_reason = spot.get("stale_reason", None)
    
    # Check service running
    if not service_running:
        log.error(f"[15M-PROBE-ANOMALY] type=spot_running actual=False")
    
    # Check staleness
    if is_stale:
        log.error(
            f"[15M-PROBE-ANOMALY] type=spot_stale actual=True reason={stale_reason}"
        )
    
    # Check age
    if last_update_age_s > MAX_SPOT_AGE_S:
        log.warning(
            f"[15M-PROBE-ANOMALY] type=spot_age actual={last_update_age_s:.1f}s "
            f"threshold={MAX_SPOT_AGE_S:.1f}s"
        )
    
    # Check hard fail threshold
    if last_update_age_s > MAX_SPOT_STALE_AGE_S:
        log.error(
            f"[15M-PROBE-ANOMALY] type=spot_age_critical actual={last_update_age_s:.1f}s "
            f"threshold={MAX_SPOT_STALE_AGE_S:.1f}s"
        )


def check_book(snapshot: Dict[str, Any]) -> None:
    """Check orderbook health metrics."""
    book = snapshot.get("book", {})
    
    book_consistency = book.get("book_consistency", "UNKNOWN")
    suspect_reason = book.get("suspect_reason", None)
    last_update_age_s = book.get("last_update_age_s", 9999.0)
    has_bids = book.get("has_bids", False)
    has_asks = book.get("has_asks", False)
    is_dual_sided = book.get("is_dual_sided", False)
    spread_pct = book.get("spread_pct", None)
    is_stale = book.get("is_stale", False)
    
    # Check book consistency - treat SUSPECT as expected when WS is down
    ws = snapshot.get("ws", {})
    ws_connected = ws.get("is_connected", False)
    
    if book_consistency != EXPECTED_BOOK_CONSISTENCY:
        if book_consistency == "SUSPECT" and suspect_reason == "ws_disconnected" and not ws_connected:
            # This is expected when WS is down
            log.info(
                f"[15M-PROBE-EXPECTED] type=book_consistency_ws_down "
                f"consistency=SUSPECT reason=ws_disconnected"
            )
        elif book_consistency == "UNKNOWN":
            # UNKNOWN indicates initialization failure
            log.error(
                f"[15M-PROBE-ANOMALY] type=book_consistency_init_failure "
                f"actual=UNKNOWN expected={EXPECTED_BOOK_CONSISTENCY}"
            )
        else:
            # Other SUSPECT states are anomalies
            log.error(
                f"[15M-PROBE-ANOMALY] type=book_consistency expected={EXPECTED_BOOK_CONSISTENCY} "
                f"actual={book_consistency} reason={suspect_reason}"
            )
    
    # Check staleness
    if is_stale:
        log.error(f"[15M-PROBE-ANOMALY] type=book_stale actual=True")
    
    # Check age
    if last_update_age_s > MAX_BOOK_AGE_S:
        log.error(
            f"[15M-PROBE-ANOMALY] type=book_age actual={last_update_age_s:.1f}s "
            f"threshold={MAX_BOOK_AGE_S:.1f}s"
        )
    
    # Check dual-sided
    if not is_dual_sided:
        log.error(
            f"[15M-PROBE-ANOMALY] type=book_dual_sided actual=False "
            f"has_bids={has_bids} has_asks={has_asks}"
        )
    
    # Check spread
    if spread_pct and spread_pct > MAX_SPREAD_PCT:
        log.warning(
            f"[15M-PROBE-ANOMALY] type=book_spread actual={spread_pct:.1f}% "
            f"threshold={MAX_SPREAD_PCT:.1f}%"
        )


def check_risk(snapshot: Dict[str, Any]) -> None:
    """Check risk environment health metrics."""
    risk = snapshot.get("risk", {})
    
    utilization_pct = risk.get("utilization_pct", 0.0)
    has_capacity = risk.get("has_capacity", True)
    is_exhausted = risk.get("is_exhausted", False)
    
    # Check capacity
    if not has_capacity:
        log.error(f"[15M-PROBE-ANOMALY] type=risk_capacity actual=False")
    
    # Check exhaustion
    if is_exhausted:
        log.error(f"[15M-PROBE-ANOMALY] type=risk_exhausted actual=True")
    
    # Check utilization
    if utilization_pct > MAX_RISK_UTILIZATION_PCT:
        log.error(
            f"[15M-PROBE-ANOMALY] type=risk_utilization actual={utilization_pct:.1%} "
            f"threshold={MAX_RISK_UTILIZATION_PCT:.1%}"
        )


def check_gates(snapshot: Dict[str, Any]) -> None:
    """Check gate decision metrics."""
    gates = snapshot.get("gates", {})
    
    overall = gates.get("overall", "UNKNOWN")
    reason = gates.get("reason", None)
    
    spot_age = gates.get("spot_age", "UNKNOWN")
    book_freshness = gates.get("book_freshness", "UNKNOWN")
    liquidity = gates.get("liquidity", "UNKNOWN")
    data_quality = gates.get("data_quality", "UNKNOWN")
    edge = gates.get("edge", "UNKNOWN")
    risk = gates.get("risk", "UNKNOWN")
    
    # Check overall gate
    if overall != EXPECTED_GATE_OVERALL:
        log.error(
            f"[15M-PROBE-ANOMALY] type=gate_overall expected={EXPECTED_GATE_OVERALL} "
            f"actual={overall} reason={reason}"
        )
    
    # Check individual gates
    if spot_age != "PASS":
        log.error(f"[15M-PROBE-ANOMALY] type=gate_spot_age actual={spot_age}")
    
    if book_freshness != "PASS":
        log.error(f"[15M-PROBE-ANOMALY] type=gate_book_freshness actual={book_freshness}")
    
    if liquidity != "PASS":
        log.error(f"[15M-PROBE-ANOMALY] type=gate_liquidity actual={liquidity}")
    
    if data_quality != "PASS":
        log.error(f"[15M-PROBE-ANOMALY] type=gate_data_quality actual={data_quality}")
    
    if edge != "PASS":
        log.error(f"[15M-PROBE-ANOMALY] type=gate_edge actual={edge}")
    
    if risk != "PASS":
        log.error(f"[15M-PROBE-ANOMALY] type=gate_risk actual={risk}")


def check_quarantine(snapshot: Dict[str, Any]) -> None:
    """Check that the stuck-position quarantine path is active."""
    quarantine_path = snapshot.get("quarantine_path", "unknown")
    if quarantine_path != EXPECTED_QUARANTINE_PATH:
        log.error(
            f"[15M-PROBE-ANOMALY] type=quarantine_path expected={EXPECTED_QUARANTINE_PATH} "
            f"actual={quarantine_path}"
        )


def check_cross_layer_consistency(snapshot: Dict[str, Any]) -> None:
    """Check cross-layer consistency."""
    ws = snapshot.get("ws", {})
    spot = snapshot.get("spot", {})
    book = snapshot.get("book", {})
    gates = snapshot.get("gates", {})
    
    # If WS is disconnected, spot and book should reflect this
    ws_connected = ws.get("is_connected", False)
    spot_stale = spot.get("is_stale", False)
    book_stale = book.get("is_stale", False)
    book_consistency = book.get("book_consistency", "UNKNOWN")
    
    # Invariant: If WS is disconnected, book should be SUSPECT (not just stale)
    if not ws_connected and book_consistency != "SUSPECT":
        log.error(
            f"[15M-PROBE-ANOMALY] type=consistency_ws_book_suspect "
            f"ws_connected={ws_connected} book_consistency={book_consistency} expected=SUSPECT"
        )
    
    # Invariant: If WS is disconnected, book should be stale
    if not ws_connected and not book_stale:
        log.error(
            f"[15M-PROBE-ANOMALY] type=consistency_ws_book_stale "
            f"ws_connected={ws_connected} book_stale={book_stale}"
        )
    
    # Spot can be fresh while WS is down (different provider), but signal logic should require both
    # This is a warning, not an error, as it's a legitimate state
    if not ws_connected and not spot_stale:
        log.info(
            f"[15M-PROBE-INFO] type=consistency_ws_spot "
            f"ws_connected={ws_connected} spot_stale={spot_stale} (spot from different provider)"
        )
    
    # If book is SUSPECT, data quality gate should fail
    data_quality_gate = gates.get("data_quality", "PASS")
    
    if book_consistency == "SUSPECT" and data_quality_gate == "PASS":
        log.error(
            f"[15M-PROBE-ANOMALY] type=consistency_book_gate "
            f"book_consistency={book_consistency} data_quality_gate={data_quality_gate}"
        )


def write_snapshot_json(snapshot: Dict[str, Any], timestamp: str) -> None:
    """Write snapshot JSON to disk for offline analysis."""
    try:
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        filename = f"probe_snapshot_{timestamp.replace(':', '-')}.json"
        filepath = os.path.join(OUTPUT_DIR, filename)
        
        with open(filepath, 'w') as f:
            json.dump(snapshot, f, indent=2)
        
        log.debug(f"[15M-PROBE] Snapshot written to {filepath}")
    except Exception as e:
        log.error(f"[15M-PROBE-ERROR] Failed to write snapshot JSON: {e}")


def main():
    """Main probe loop."""
    # Set runtime mode
    os.environ.setdefault("MERID_RUNTIME_MODE", "15m_live")
    
    log.info("[15M-PROBE] Starting live end-to-end probe")
    log.info(f"[15M-PROBE] Health URL: {HEALTH_URL}")
    log.info(f"[15M-PROBE] Monitor interval: {MONITOR_INTERVAL}s")
    log.info(f"[15M-PROBE] Output directory: {OUTPUT_DIR}")
    
    iteration = 0
    
    try:
        while True:
            iteration += 1
            timestamp = datetime.now().isoformat()
            
            log.info(f"[15M-PROBE] Iteration {iteration} at {timestamp}")
            
            try:
                # Fetch health snapshot
                snapshot = fetch_health_snapshot()
                
                # Run all checks
                check_ws(snapshot)
                check_spot(snapshot)
                check_book(snapshot)
                check_risk(snapshot)
                check_gates(snapshot)
                check_quarantine(snapshot)
                check_cross_layer_consistency(snapshot)
                
                # Write snapshot JSON for offline analysis
                write_snapshot_json(snapshot, timestamp)
                
                # Log scenario mapping
                scenario = snapshot.get("scenario_mapping", None)
                if scenario:
                    log.info(f"[15M-PROBE] Current state maps to scenario: {scenario}")
                
            except Exception as e:
                log.error(f"[15M-PROBE-ERROR] Iteration {iteration} failed: {e}", exc_info=True)
            
            # Wait for next iteration
            time.sleep(MONITOR_INTERVAL)
            
    except KeyboardInterrupt:
        log.info("[15M-PROBE] Stopping probe (keyboard interrupt)")
    except Exception as e:
        log.error(f"[15M-PROBE] Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

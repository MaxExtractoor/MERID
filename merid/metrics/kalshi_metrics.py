"""
Metrics Module for MERID + Kalshi Trading System

Exports Prometheus-compatible metrics for monitoring and alerting.
"""

from prometheus_client import Counter, Histogram, Gauge, Info, start_http_server
from typing import Optional
import threading


# ═══════════════════════════════════════════════════════════════════════════════
# Guard Metrics
# ═══════════════════════════════════════════════════════════════════════════════

guard_trips_total = Counter(
    'merid_guard_trips_total',
    'Total number of guard trips by type and mode',
    ['guard_type', 'mode', 'endpoint']
)
"""
Guard trip counter.

Labels:
    guard_type: Type of guard (FIX_ENDPOINT, REST_FALLBACK, CT_API, ARCHIVE_IMPORT)
    mode: Trading mode (sim, paper, live)
    endpoint: API endpoint that was blocked

Example alert:
    merid_guard_trips_total{mode="live"} > 5 in 5m
    => Potential attack or misconfigured client
"""

# ═══════════════════════════════════════════════════════════════════════════════
# Order Metrics
# ═══════════════════════════════════════════════════════════════════════════════

orders_submitted_total = Counter(
    'merid_orders_submitted_total',
    'Total orders submitted',
    ['venue', 'ticker', 'side', 'order_type']
)

orders_executed_total = Counter(
    'merid_orders_executed_total',
    'Total orders executed',
    ['venue', 'ticker', 'side', 'status']
)

orders_rejected_total = Counter(
    'merid_orders_rejected_total',
    'Total orders rejected by risk or system',
    ['reason', 'risk_type']
)
"""
Order rejection counter.

Labels:
    reason: Why order was rejected (GLOBAL_CAP, PER_TRADE_CAP, EDGE_LIMIT, SYSTEM_ERROR)
    risk_type: Type of risk check that rejected (global, per_trade, edge_count)

Example alert:
    merid_orders_rejected_total{reason="GLOBAL_CAP"} > 0
    => Approaching risk limits, review exposure
"""

order_latency_seconds = Histogram(
    'merid_order_latency_seconds',
    'Order submission latency',
    ['venue'],
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

# ═══════════════════════════════════════════════════════════════════════════════
# Risk Metrics
# ═══════════════════════════════════════════════════════════════════════════════

risk_exposure_pct = Gauge(
    'merid_risk_exposure_pct',
    'Current risk exposure as percentage of bankroll',
    ['basket', 'risk_type']
)
"""
Current risk exposure.

Labels:
    basket: Market basket (BTC-15M, BTC-1H, etc.)
    risk_type: Type of risk (total, per_trade, per_edge)

Example alert:
    merid_risk_exposure_pct > 1.5
    => Approaching 2% global cap
"""

risk_bankroll_usd = Gauge(
    'merid_risk_bankroll_usd',
    'Current bankroll in USD',
    ['currency', 'source']
)

active_edges_count = Gauge(
    'merid_active_edges_count',
    'Number of active edges per basket',
    ['basket']
)
"""
Active edge counter.

Example alert:
    merid_active_edges_count{basket="BTC-15M"} >= 3
    => At max edges, new signals will be queued or rejected
"""

# ═══════════════════════════════════════════════════════════════════════════════
# System Metrics
# ═══════════════════════════════════════════════════════════════════════════════

current_trade_mode = Gauge(
    'merid_trade_mode',
    'Current trading mode (0=sim, 1=paper, 2=live)',
    []
)
"""
Current trading mode as numeric value.

Values:
    0: SIM mode (safe for development)
    1: PAPER mode (simulated trading)
    2: LIVE mode (real funds)

Example alert:
    merid_trade_mode == 2 and changes()
    => Mode changed to LIVE, audit trail
"""

executor_available = Gauge(
    'merid_executor_available',
    'Order router availability (1=available, 0=unavailable)',
    []
)
"""
Executor availability.

Example alert:
    merid_executor_available == 0
    => System degraded, check order_router
"""

kill_switch_active = Gauge(
    'merid_kill_switch_active',
    'Kill switch state (1=active, 0=inactive)',
    []
)
"""
Kill switch state.

Example alert:
    merid_kill_switch_active == 1
    => Trading halted, immediate operator attention required
"""

mode_transitions_total = Counter(
    'merid_mode_transitions_total',
    'Total mode transitions',
    ['from_mode', 'to_mode']
)
"""
Mode transition counter.

Example alert:
    merid_mode_transitions_total{to_mode="live"} > 0 in 1h
    => Mode changed to LIVE, verify intentional
"""

kill_switch_activations_total = Counter(
    'merid_kill_switch_activations_total',
    'Total kill switch activations',
    ['reason', 'severity']
)
"""
Kill switch activation counter.

Example alert:
    merid_kill_switch_activations_total > 0
    => CRITICAL: Trading halted, immediate response required
"""

# ═══════════════════════════════════════════════════════════════════════════════
# Startup Metrics
# ═══════════════════════════════════════════════════════════════════════════════

startup_enforcement_checks_total = Counter(
    'merid_startup_enforcement_checks_total',
    'Total startup risk enforcement checks',
    ['result']
)
"""
Startup enforcement results.

Labels:
    result: pass or fail

Example alert:
    merid_startup_enforcement_checks_total{result="fail"} > 0
    => Config violation prevented startup, fix and restart
"""

# ═══════════════════════════════════════════════════════════════════════════════
# System Info
# ═══════════════════════════════════════════════════════════════════════════════

system_info = Info(
    'merid_system',
    'System information'
)

# ═══════════════════════════════════════════════════════════════════════════════
# Metric Update Functions
# ═══════════════════════════════════════════════════════════════════════════════

def record_guard_trip(guard_type: str, mode: str, endpoint: str):
    """Record a guard trip event."""
    guard_trips_total.labels(
        guard_type=guard_type,
        mode=mode,
        endpoint=endpoint
    ).inc()


def record_order_submitted(venue: str, ticker: str, side: str, order_type: str):
    """Record an order submission."""
    orders_submitted_total.labels(
        venue=venue,
        ticker=ticker,
        side=side,
        order_type=order_type
    ).inc()


def record_order_rejected(reason: str, risk_type: str):
    """Record an order rejection."""
    orders_rejected_total.labels(
        reason=reason,
        risk_type=risk_type
    ).inc()


def record_mode_transition(from_mode: str, to_mode: str):
    """Record a mode transition."""
    mode_transitions_total.labels(
        from_mode=from_mode,
        to_mode=to_mode
    ).inc()
    
    # Update current mode gauge
    mode_map = {'sim': 0, 'paper': 1, 'live': 2}
    current_trade_mode.set(mode_map.get(to_mode, -1))


def record_kill_switch(reason: str, severity: str):
    """Record a kill switch activation."""
    kill_switch_activations_total.labels(
        reason=reason,
        severity=severity
    ).inc()
    kill_switch_active.set(1)


def reset_kill_switch():
    """Reset kill switch state after recovery."""
    kill_switch_active.set(0)


def set_executor_availability(available: bool):
    """Update executor availability."""
    executor_available.set(1 if available else 0)


def record_startup_enforcement(success: bool):
    """Record startup enforcement result."""
    result = 'pass' if success else 'fail'
    startup_enforcement_checks_total.labels(result=result).inc()


def record_risk_violation(violation_type: str, current_value: float, 
                         max_allowed: float, config_source: str):
    """
    Record a risk configuration violation.
    
    Args:
        violation_type: Type of violation (global_cap, fixed_usd, etc.)
        current_value: The violating value
        max_allowed: The maximum allowed value  
        config_source: Where the config came from
    """
    # Use labels to track violation types
    risk_exposure_pct.labels(
        basket="config",
        risk_type=f"violation_{violation_type}"
    ).set(current_value)


def update_risk_exposure(basket: str, exposure_pct: float, risk_type: str = 'total'):
    """Update risk exposure gauge."""
    risk_exposure_pct.labels(
        basket=basket,
        risk_type=risk_type
    ).set(exposure_pct)


def update_active_edges(basket: str, count: int):
    """Update active edges gauge."""
    active_edges_count.labels(basket=basket).set(count)


def update_bankroll(amount_usd: float, currency: str = 'USD', source: str = 'computed'):
    """Update bankroll gauge."""
    risk_bankroll_usd.labels(
        currency=currency,
        source=source
    ).set(amount_usd)


# ═══════════════════════════════════════════════════════════════════════════════
# Server Management
# ═══════════════════════════════════════════════════════════════════════════════

_metrics_server_thread: Optional[threading.Thread] = None
_metrics_server_port: int = 9100


def start_metrics_server(port: int = 9100):
    """
    Start the Prometheus metrics HTTP server.
    
    Args:
        port: Port to expose metrics on (default: 9100)
    
    Usage:
        from merid.metrics.kalshi_metrics import start_metrics_server
        start_metrics_server(9100)
        
        # Metrics available at http://localhost:9100/metrics
    """
    global _metrics_server_port
    _metrics_server_port = port
    
    def run_server():
        start_http_server(port)
    
    global _metrics_server_thread
    _metrics_server_thread = threading.Thread(target=run_server, daemon=True)
    _metrics_server_thread.start()
    
    print(f"Metrics server started on port {port}")
    print(f"Prometheus metrics available at http://localhost:{port}/metrics")


def stop_metrics_server():
    """Stop the metrics server (best effort - thread may not terminate cleanly)."""
    global _metrics_server_thread
    if _metrics_server_thread and _metrics_server_thread.is_alive():
        # Note: There's no clean way to stop the HTTP server thread
        # In production, this would be handled by process restart
        print("Metrics server stop requested (will stop on process exit)")


# ═══════════════════════════════════════════════════════════════════════════════
# Initialization
# ═══════════════════════════════════════════════════════════════════════════════

def initialize_metrics(version: str, build_info: dict = None):
    """
    Initialize system info metrics.
    
    Args:
        version: MERID version string
        build_info: Optional build metadata
    """
    info = {
        'version': version,
        'system': 'merid_kalshi',
    }
    
    if build_info:
        info.update(build_info)
    
    system_info.info(info)
    
    # Set initial gauge values
    current_trade_mode.set(0)  # Assume SIM until configured
    executor_available.set(1)  # Assume available until proven otherwise
    kill_switch_active.set(0)  # Assume inactive

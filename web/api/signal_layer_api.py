"""Signal Layer REST API — features, arbs, drift, CQI, decay metadata.

Endpoints:
  GET  /api/v1/signal-layer/features/{symbol}     — Decay-aware features for a symbol
  GET  /api/v1/signal-layer/social/{symbol}        — Social features (fast decay)
  GET  /api/v1/signal-layer/macro                  — Macro features
  GET  /api/v1/signal-layer/onchain/{chain}/{token} — On-chain features
  GET  /api/v1/signal-layer/snapshot/{symbol}      — Full signal snapshot
  GET  /api/v1/signal-layer/arbs                   — Active arb/dislocation signals
  GET  /api/v1/signal-layer/arb-plans              — Arb plans
  GET  /api/v1/signal-layer/drift                  — Drift metrics per domain
  GET  /api/v1/signal-layer/cqi                    — CQI per domain
  GET  /api/v1/signal-layer/cqi/{domain}           — CQI history for domain
  GET  /api/v1/signal-layer/metrics                — Aggregate signal layer metrics
  GET  /api/v1/signal-layer/decay-configs          — Decay configs per domain
  POST /api/v1/signal-layer/scan-arbs              — Trigger arb scan
  POST /api/v1/signal-layer/compute-cqi            — Trigger CQI computation
"""

from __future__ import annotations

import time
import threading
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

signal_layer_router = APIRouter(prefix="/api/v1/signal-layer", tags=["signal-layer"])


# ── Lazy imports ──────────────────────────────────────────────────────

def _features():
    from merid.signals.features import get_feature_service
    return get_feature_service()

def _scanner():
    from merid.signals.arbitrage import get_dislocation_scanner
    return get_dislocation_scanner()

def _drift():
    from merid.signals.drift import get_drift_detector
    return get_drift_detector()

def _store():
    from merid.signals.store import get_signal_store
    return get_signal_store()

def _decay_configs():
    from merid.signals.decay import DEFAULT_DECAY_CONFIGS
    return DEFAULT_DECAY_CONFIGS


# ── Feature endpoints ─────────────────────────────────────────────────

@signal_layer_router.get("/features/{symbol}")
def get_features(symbol: str, window: int = Query(3600)):
    """Get decay-aware news + social + onchain features for a symbol."""
    svc = _features()
    news = svc.get_news_features(symbol, window_seconds=window)
    social = svc.get_social_features(symbol, window_seconds=min(window, 900))
    chain = "solana" if symbol.upper() in ("SOL", "BONK", "WIF", "JUP") else "ethereum"
    onchain = svc.get_onchain_features(chain, symbol)
    return {
        "symbol": symbol,
        "news": news.to_dict(),
        "social": social.to_dict(),
        "onchain": onchain.to_dict(),
    }


@signal_layer_router.get("/social/{symbol}")
def get_social(symbol: str, window: int = Query(900)):
    """Get fast-decaying social features for a symbol."""
    svc = _features()
    return svc.get_social_features(symbol, window_seconds=window).to_dict()


@signal_layer_router.get("/macro")
def get_macro(series: str = Query("all"), window: int = Query(604800)):
    """Get macro features."""
    svc = _features()
    return svc.get_macro_features(series, window_seconds=window).to_dict()


@signal_layer_router.get("/onchain/{chain}/{token}")
def get_onchain(chain: str, token: str):
    """Get on-chain features."""
    svc = _features()
    return svc.get_onchain_features(chain, token).to_dict()


@signal_layer_router.get("/snapshot/{symbol}")
def get_snapshot(symbol: str):
    """Build a full signal snapshot for a symbol (attaches to opinions/plans)."""
    svc = _features()
    snap = svc.build_snapshot(symbol)
    return snap.to_dict()


# ── Arb endpoints ─────────────────────────────────────────────────────

@signal_layer_router.get("/arbs")
def get_arbs(status: Optional[str] = Query(None), limit: int = Query(50)):
    """List arb/dislocation signals."""
    scanner = _scanner()
    if status == "active":
        signals = scanner.get_active_signals()
    else:
        signals = scanner.get_all_signals(limit=limit)
    return {
        "signals": [s.to_dict() for s in signals],
        "count": len(signals),
        "metrics": scanner.get_metrics(),
    }


@signal_layer_router.get("/arb-plans")
def get_arb_plans(status: Optional[str] = Query(None), limit: int = Query(50)):
    """List arb plans."""
    scanner = _scanner()
    plans = scanner.get_plans(status=status, limit=limit)
    return {"plans": [p.to_dict() for p in plans], "count": len(plans)}


@signal_layer_router.post("/scan-arbs")
def trigger_arb_scan():
    """Trigger an arb scan (uses synthetic data if no live prices)."""
    scanner = _scanner()
    signals = scanner.scan()
    if not signals:
        signals = scanner.synthetic_scan()
    # Persist
    store = _store()
    for sig in signals:
        store.store_arb_signal(sig.to_dict())
    return {
        "status": "ok",
        "new_signals": len(signals),
        "signals": [s.to_dict() for s in signals],
    }


# ── Drift / CQI endpoints ────────────────────────────────────────────

@signal_layer_router.get("/drift")
def get_drift(domain: Optional[str] = Query(None)):
    """Get drift metrics per domain."""
    detector = _drift()
    if domain:
        history = detector.get_drift_history(domain)
        return {"domain": domain, "history": [m.to_dict() for m in history]}

    summary = detector.summary()
    return summary


@signal_layer_router.get("/cqi")
def get_all_cqi():
    """Get latest CQI per domain."""
    detector = _drift()
    all_cqi = detector.get_all_cqi()
    if not all_cqi:
        return {
            "domains": {},
            "domain_count": 0,
            "_stub": True,
            "_stub_message": "No CQI data yet — awaiting real signal outcomes",
        }

    return {
        "domains": {d: c.to_dict() for d, c in all_cqi.items()},
        "domain_count": len(all_cqi),
    }


@signal_layer_router.get("/cqi/{domain}")
def get_cqi_domain(domain: str, limit: int = Query(50)):
    """Get CQI history for a domain."""
    detector = _drift()
    history = detector.get_cqi_history(domain, limit=limit)
    adjustments = detector.get_risk_adjustments(domain)
    return {
        "domain": domain,
        "history": [c.to_dict() for c in history],
        "risk_adjustments": adjustments,
    }


@signal_layer_router.post("/compute-cqi")
def trigger_cqi_compute(domain: str = Query("crypto")):
    """Trigger CQI computation for a domain."""
    detector = _drift()
    cqi = detector.compute_cqi(domain)
    # Persist
    store = _store()
    store.store_cqi(cqi.to_dict())
    return {"status": "ok", "cqi": cqi.to_dict()}


# ── Config / metrics ──────────────────────────────────────────────────

@signal_layer_router.get("/decay-configs")
def get_decay_configs_endpoint():
    """Get decay configurations per domain."""
    configs = _decay_configs()
    return {d: c.to_dict() for d, c in configs.items()}


# ── Cached metrics snapshot ───────────────────────────────────────────
_METRICS_CACHE: Dict[str, Any] = {}
_METRICS_CACHE_TS: float = 0.0
_METRICS_CACHE_TTL: float = 60.0  # seconds (was 30 — increased to reduce recomputation)
_METRICS_LOCK = threading.Lock()
_METRICS_SUBSYSTEM_TIMEOUT: float = 3.0  # per-subsystem timeout in seconds

# SLO thresholds (p95 targets in milliseconds)
_SLO_SUBSYSTEM_MS: Dict[str, int] = {
    "store": 500,
    "arb": 500,
    "drift": 500,
    "live_feeds": 1000,
    "ws_feed": 1000,
}
_SLO_TOTAL_MS: int = 2000  # Overall endpoint target
_SLO_HISTORY_SIZE: int = 20  # Rolling window for SLO tracking
_slo_history: List[Dict[str, int]] = []  # Recent timing snapshots


def _fetch_subsystem(name: str, fn) -> tuple:
    """Fetch a single subsystem's metrics with timing. Returns (name, data, latency_ms)."""
    t0 = time.monotonic()
    try:
        data = fn()
    except Exception:
        data = {}
    latency_ms = int((time.monotonic() - t0) * 1000)
    return (name, data, latency_ms)


def _build_signal_metrics() -> Dict[str, Any]:
    """Aggregate signal subsystem metrics in parallel (runs in threadpool).

    Uses a thread pool to fetch all 5 subsystems concurrently instead of
    sequentially.  Each subsystem has a 3s timeout so one slow init can't
    block the entire response.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    t0 = time.monotonic()

    # Define subsystem fetchers (lazy imports inside lambdas to avoid
    # module-level init cost — the singleton is only created on first call)
    subsystems = {
        "store": lambda: _store().get_signal_metrics(),
        "arb": lambda: _scanner().get_metrics(),
        "drift": lambda: _drift().summary(),
        "live_feeds": lambda: __import__(
            "merid.signals.live_feeds", fromlist=["get_live_feed_manager"]
        ).get_live_feed_manager().status(),
        "ws_feed": lambda: __import__(
            "merid.signals.ws_price_feed", fromlist=["get_ws_feed_manager"]
        ).get_ws_feed_manager().status(),
    }

    result: Dict[str, Any] = {}
    timings: Dict[str, int] = {}

    with ThreadPoolExecutor(max_workers=5, thread_name_prefix="sig_metrics") as pool:
        futures = {
            pool.submit(_fetch_subsystem, name, fn): name
            for name, fn in subsystems.items()
        }
        for future in as_completed(futures, timeout=_METRICS_SUBSYSTEM_TIMEOUT + 1):
            try:
                name, data, latency_ms = future.result(timeout=_METRICS_SUBSYSTEM_TIMEOUT)
                result[name] = data
                timings[name] = latency_ms
            except Exception:
                name = futures[future]
                result[name] = {}
                timings[name] = -1  # timeout or error

    total_ms = int((time.monotonic() - t0) * 1000)

    # Track SLO history
    snapshot = {**timings, "_total": total_ms}
    _slo_history.append(snapshot)
    while len(_slo_history) > _SLO_HISTORY_SIZE:
        _slo_history.pop(0)

    # Compute SLO status from rolling window
    slo_status: Dict[str, Any] = {}
    for name, threshold in _SLO_SUBSYSTEM_MS.items():
        values = [h.get(name, -1) for h in _slo_history if h.get(name, -1) >= 0]
        if values:
            p95 = sorted(values)[int(len(values) * 0.95)] if len(values) >= 2 else max(values)
            slo_status[name] = {
                "threshold_ms": threshold,
                "p95_ms": p95,
                "ok": p95 <= threshold,
                "samples": len(values),
            }
        else:
            slo_status[name] = {"threshold_ms": threshold, "p95_ms": None, "ok": False, "samples": 0}

    # Overall SLO
    total_values = [h.get("_total", -1) for h in _slo_history if h.get("_total", -1) >= 0]
    if total_values:
        total_p95 = sorted(total_values)[int(len(total_values) * 0.95)] if len(total_values) >= 2 else max(total_values)
        slo_status["_overall"] = {
            "threshold_ms": _SLO_TOTAL_MS,
            "p95_ms": total_p95,
            "ok": total_p95 <= _SLO_TOTAL_MS,
            "samples": len(total_values),
        }
    all_ok = all(v.get("ok", False) for v in slo_status.values())

    result["_subsystem_timings_ms"] = timings
    result["_latency_ms"] = total_ms
    result["_cached_at"] = time.time()
    result["_slo"] = {"subsystems": slo_status, "all_ok": all_ok}
    return result


def warm_signal_metrics_cache() -> None:
    """Pre-warm the metrics cache in a background thread.

    Call this at application startup so the first dashboard request
    doesn't pay the 7+ second cold-start penalty.
    """
    def _warm():
        global _METRICS_CACHE, _METRICS_CACHE_TS
        try:
            snapshot = _build_signal_metrics()
            with _METRICS_LOCK:
                _METRICS_CACHE = snapshot
                _METRICS_CACHE_TS = time.monotonic()
        except Exception:
            pass  # Non-critical — first request will compute it

    t = threading.Thread(target=_warm, daemon=True, name="sig_metrics_warm")
    t.start()


@signal_layer_router.get("/metrics")
async def get_signal_layer_metrics():
    """Aggregate signal layer metrics (cached with 60s TTL, computed off event loop)."""
    global _METRICS_CACHE, _METRICS_CACHE_TS

    now = time.monotonic()
    if _METRICS_CACHE and (now - _METRICS_CACHE_TS) < _METRICS_CACHE_TTL:
        return _METRICS_CACHE

    try:
        # Run heavy work off the event loop
        snapshot = await run_in_threadpool(_build_signal_metrics)

        with _METRICS_LOCK:
            _METRICS_CACHE = snapshot
            _METRICS_CACHE_TS = time.monotonic()

        return snapshot
    except Exception:
        return {
            "subsystems": {},
            "total_signals": 0,
            "active_arbs": 0,
            "domains_tracked": 0,
            "error": "Signal layer metrics temporarily unavailable",
        }

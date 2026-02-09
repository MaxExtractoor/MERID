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

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Query
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
        # Generate synthetic CQI for demo
        domains = ["crypto", "prediction", "sports", "meme"]
        for d in domains:
            # Seed some outcomes
            import random
            rng = random.Random(hash(d))
            for _ in range(20):
                detector.record_outcome(
                    d, rng.uniform(0.2, 0.8), rng.choice([0.0, 1.0]),
                    rng.uniform(-50, 50), rng.uniform(0.3, 0.9),
                )
            detector.compute_cqi(d)
        all_cqi = detector.get_all_cqi()

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


@signal_layer_router.get("/metrics")
def get_signal_layer_metrics():
    """Aggregate signal layer metrics."""
    try:
        store = _store()
        store_metrics = store.get_signal_metrics()
    except Exception:
        store_metrics = {}

    try:
        scanner = _scanner()
        arb_metrics = scanner.get_metrics()
    except Exception:
        arb_metrics = {}

    try:
        detector = _drift()
        drift_summary = detector.summary()
    except Exception:
        drift_summary = {}

    # Live feed status
    live_feeds_status = {}
    try:
        from merid.signals.live_feeds import get_live_feed_manager
        live_feeds_status = get_live_feed_manager().status()
    except Exception:
        pass

    # WS feed status
    ws_feed_status = {}
    try:
        from merid.signals.ws_price_feed import get_ws_feed_manager
        ws_feed_status = get_ws_feed_manager().status()
    except Exception:
        pass

    return {
        "store": store_metrics,
        "arb": arb_metrics,
        "drift": drift_summary,
        "live_feeds": live_feeds_status,
        "ws_feed": ws_feed_status,
    }

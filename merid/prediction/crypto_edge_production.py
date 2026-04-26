"""Kalshi crypto edge model — production config, consensus-path logging, health hooks.

**Thresholds (min edge, spreads, sentiment floors, Kelly, min-notional hints)** for core
crypto PM/MM are loaded from ``config/crypto_threshold_matrix.yaml`` (override path:
``MERID_CRYPTO_THRESHOLD_MATRIX_PATH``).

**Profile selection** — :func:`get_crypto_edge_runtime` reads ``MERID_CRYPTO_EDGE_PRODUCTION_PROFILE``
from :mod:`merid.settings`. The **Pydantic default is ``modern``** (see ``merid.settings``), which
selects the **modern** rows in the YAML matrix (e.g. lower ``min_order_notional_usd`` than legacy)
and also sets **medium** edge-floor profile, **soft** MM consensus mode, and non-zero shadow-edge
observability — not a single-parameter change. To use **legacy** matrix rows and stricter defaults,
set ``MERID_CRYPTO_EDGE_PRODUCTION_PROFILE`` to empty or an unrecognized value, or override via env
so ``profile`` resolves to legacy (see implementation of :func:`get_crypto_edge_runtime`).

Values ``modern``, ``full_live``, and ``production_tuned`` activate the modern threshold bundle.

AgentGrid YAML ``strategy:`` ``min_edge_*`` values are **informational for crypto** — the
matrix applies one scalar per phase and logs ``[CRYPTO_MATRIX]`` when YAML differed.

Toggle structured consensus→execution logs with ``MERID_CONSENSUS_PATH_LOG=true``.
NoTradeDecisionTracker records reasons for telemetry only; it never blocks trades.
"""

from __future__ import annotations

import logging
import hashlib
import json
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Deque, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.prediction.crypto_edge_production")

_CANON_READ_LAST: Dict[str, float] = {}
_HEALTH_LOCK = threading.Lock()
_SIGNAL_EVENTS: Dict[str, Deque[Tuple[float, str]]] = defaultdict(
    lambda: deque(maxlen=256)
)
_LAST_CONSENSUS_TS: Dict[str, float] = {}


@dataclass(frozen=True)
class CryptoEdgeRuntime:
    """Effective crypto edge / MM consensus knobs (after production profile merge)."""

    edge_floor_profile: str
    mm_consensus_mode: str
    shadow_edge_yes: float
    shadow_edge_no: float
    consensus_wait_timeout_ms: int
    threshold_mode: str  # "legacy" | "modern" — asset×timeframe PM + risk caps


def _settings_bundle() -> Any:
    from merid.settings import settings

    return settings


def get_crypto_edge_runtime() -> CryptoEdgeRuntime:
    """Resolve MERID_CRYPTO_* settings with optional MERID_CRYPTO_EDGE_PRODUCTION_PROFILE.

    Default **modern_tradeable_kalshi_v1** profile (see ``merid.settings.MERID_CRYPTO_EDGE_PRODUCTION_PROFILE``)
    selects YAML **modern_tradeable_kalshi_v1** matrix rows with confidence bands, fee-aware cent edge,
    and tiered Kelly sizing. Legacy "modern" and "legacy" profiles still supported for compatibility.
    """
    s = _settings_bundle()
    profile = (getattr(s, "MERID_CRYPTO_EDGE_PRODUCTION_PROFILE", None) or "").strip().lower()

    floor = str(getattr(s, "MERID_CRYPTO_EDGE_FLOOR_PROFILE", "strict")).strip().lower()
    mm = str(getattr(s, "MERID_CRYPTO_MM_CONSENSUS_MODE", "full")).strip().lower()
    sy = float(getattr(s, "MERID_CRYPTO_SHADOW_EDGE_YES", 0.0))
    sn = float(getattr(s, "MERID_CRYPTO_SHADOW_EDGE_NO", 0.0))
    wait_ms = int(getattr(s, "MERID_CRYPTO_CONSENSUS_WAIT_TIMEOUT_MS", 500))

    threshold_mode = "legacy"
    # Modern profiles: new production default + backward compatible aliases
    if profile in ("modern_tradeable_kalshi_v1", "modern", "full_live", "production_tuned"):
        floor = "medium"
        mm = "soft"
        sy = max(sy, 0.02)
        sn = max(sn, 0.02)
        threshold_mode = "modern"

    # SAFETY: bypass mode is disabled - force to 'full' if attempted
    if mm == "bypass":
        logger.error(
            "[SECURITY] MERID_CRYPTO_MM_CONSENSUS_MODE='bypass' is DISABLED. "
            "Using 'full' mode. All orders must flow through main execution gate."
        )
        mm = "full"
    
    return CryptoEdgeRuntime(
        edge_floor_profile=floor if floor in ("strict", "medium", "relaxed") else "strict",
        mm_consensus_mode=mm if mm in ("full", "soft") else "full",
        shadow_edge_yes=sy,
        shadow_edge_no=sn,
        consensus_wait_timeout_ms=max(0, wait_ms),
        threshold_mode=threshold_mode,
    )


def tiered_min_edge_multiplier() -> Decimal:
    """Scale tiered min-edge grid: strict=1, medium≈0.92, relaxed≈0.85 (floors still apply)."""
    prof = get_crypto_edge_runtime().edge_floor_profile
    if prof == "medium":
        return Decimal("0.92")
    if prof == "relaxed":
        return Decimal("0.85")
    return Decimal("1.0")


def is_modern_crypto_production_profile() -> bool:
    """True when ``MERID_CRYPTO_EDGE_PRODUCTION_PROFILE`` opts into the modern threshold bundle."""
    return get_crypto_edge_runtime().threshold_mode == "modern"


# ═══════════════════════════════════════════════════════════════════════════
# Crypto threshold matrix — loaded from ``config/crypto_threshold_matrix.yaml``
# ═══════════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class CryptoThresholdsCell:
    """Per-(asset,timeframe,profile) thresholds resolved from the YAML matrix."""

    mode: str
    timeframe: str
    directional_min_edge: Decimal
    sentiment_vol_regime_min_edge: Decimal
    contrarian_sentiment_min: float
    mm_max_spread_cents: Decimal
    pm_risk_max_spread_cents: Decimal
    tier_min_edge_floor: Decimal


def normalize_crypto_timeframe(timeframe: str) -> str:
    """Re-export for backward compatibility — canonical implementation in crypto_threshold_matrix."""
    from merid.prediction.crypto_threshold_matrix import normalize_crypto_timeframe as _norm

    return _norm(timeframe)


def _matrix_row_to_cell(row: Dict[str, Any]) -> CryptoThresholdsCell:
    """Build frozen cell from :func:`merid.prediction.crypto_threshold_matrix.resolve_merged_row` output."""
    return CryptoThresholdsCell(
        mode=str(row.get("profile", "legacy")),
        timeframe=str(row.get("timeframe", "15m")),
        directional_min_edge=Decimal(str(row.get("directional_min_edge", "0.04"))),
        sentiment_vol_regime_min_edge=Decimal(
            str(row.get("sentiment_vol_regime_min_edge", row.get("directional_min_edge", "0.04")))
        ),
        contrarian_sentiment_min=float(row.get("contrarian_sentiment_min") or 75.0),
        mm_max_spread_cents=Decimal(str(row.get("mm_max_spread_cents", "10"))),
        pm_risk_max_spread_cents=Decimal(
            str(row.get("pm_risk_max_spread_cents", row.get("mm_max_spread_cents", "10")))
        ),
        tier_min_edge_floor=Decimal(str(row.get("tier_min_edge_floor", "0.08"))),
    )


def get_crypto_thresholds(asset: str, timeframe: str) -> CryptoThresholdsCell:
    """Thresholds for ``asset`` × timeframe (directional merge path — spread/tier/min edge for CT hooks)."""
    from merid.prediction.crypto_threshold_matrix import resolve_merged_row

    au = (asset or "BTC").strip().upper()
    tf = normalize_crypto_timeframe(timeframe)
    row = resolve_merged_row(asset=au, timeframe=tf, archetype="directional")
    return _matrix_row_to_cell(row)


def enumerate_crypto_threshold_matrix() -> Dict[str, Any]:
    """Backward-compatible summary: per-timeframe slice using BTC (all assets mirror unless YAML diverges)."""
    from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS
    from merid.prediction.crypto_threshold_matrix import enumerate_crypto_threshold_matrix_from_yaml

    leg_doc = enumerate_crypto_threshold_matrix_from_yaml("legacy")
    mod_doc = enumerate_crypto_threshold_matrix_from_yaml("modern")
    leg_n = leg_doc.get("legacy", {})
    mod_n = mod_doc.get("modern", {})

    def _by_tf(flat: Dict[str, Any]) -> Dict[str, Any]:
        out_tf: Dict[str, Any] = {}
        for tf in ("15m", "1h", "daily", "weekly", "monthly", "annual"):
            key = f"BTC:{tf}"
            out_tf[tf] = dict(flat.get(key, {}))
        return out_tf

    return {
        "assets": list(ACTIVE_CRYPTO_ASSETS),
        "legacy": _by_tf(leg_n),
        "modern": _by_tf(mod_n),
        "legacy_by_asset_tf": leg_n,
        "modern_by_asset_tf": mod_n,
        "matrix_path": __import__(
            "merid.prediction.crypto_threshold_matrix", fromlist=["matrix_document_path"]
        ).matrix_document_path(),
    }


def integrate_crypto_tiered_min_edge(asset: str, timeframe_bucket: str, scaled_tiered: Decimal) -> Decimal:
    """Blend inventory ``MIN_EDGE_GRID×multiplier`` with PM threshold cap (more permissive = lower)."""
    try:
        cell = get_crypto_thresholds(asset, timeframe_bucket)
        # Take the lower (easier to satisfy) of venue-tier inventory bar and strategy matrix
        return min(scaled_tiered, cell.directional_min_edge)
    except Exception:
        return scaled_tiered


def crypto_tier_min_edge_floor(asset: str, timeframe_bucket: str) -> Decimal:
    """Minimum edge clamp after blending — legacy 8¢, modern 0.5¢ (see matrix)."""
    try:
        return get_crypto_thresholds(asset, timeframe_bucket).tier_min_edge_floor
    except Exception:
        return Decimal("0.08")


def effective_crypto_pm_max_spread_cents(market_id: str) -> Optional[Decimal]:
    """Kalshi PM pre-trade spread cap for KX* crypto tickers; None if not crypto."""
    try:
        from config.kalshi_crypto_config import ACTIVE_CRYPTO_ASSETS, kalshi_ticker_to_asset
        from merid.event_venues.kalshi.market_filter import get_series_timeframe_bucket

        asset = kalshi_ticker_to_asset(market_id or "")
        if not asset or asset not in ACTIVE_CRYPTO_ASSETS:
            return None
        tf = get_series_timeframe_bucket(market_id)
        return get_crypto_thresholds(asset, tf).pm_risk_max_spread_cents
    except Exception:
        return None


def apply_crypto_strategy_thresholds_to_config(
    sc: Any,
    asset: str,
    timeframe: str,
    archetype: str,
    *,
    prior_yaml_phase_edges: Optional[Dict[str, Any]] = None,
    agent_name: Optional[str] = None,
) -> None:
    """Mutate ``StrategyConfig`` from ``config/crypto_threshold_matrix.yaml`` (crypto agents only).

    The matrix **takes precedence** over AgentGrid YAML ``strategy:`` min_edge_* — if
    ``prior_yaml_phase_edges`` is passed and differs from the applied scalar, an INFO
    line is emitted. Per-phase ladders in YAML are informational for crypto PM.
    """
    from merid.prediction.crypto_threshold_matrix import matrix_document_path, resolve_merged_row

    arch_norm = (archetype or "directional").strip().lower().replace("-", "_")
    au = (asset or "BTC").strip().upper()
    row = resolve_merged_row(asset=au, timeframe=timeframe, archetype=arch_norm)
    cell = _matrix_row_to_cell(row)

    arch_u = (archetype or "").upper()
    use_sentiment_row = any(
        x in arch_u
        for x in (
            "VOL_BREAKOUT",
            "REGIME_SWITCH",
            "SENTIMENT_VOL",
            "SENTIMENT_REGIME",
        )
    )
    edge = cell.sentiment_vol_regime_min_edge if use_sentiment_row else cell.directional_min_edge

    phase_attrs = ("min_edge_early", "min_edge_mid", "min_edge_late", "min_edge_terminal")
    if prior_yaml_phase_edges:
        try:
            mism = []
            for k in phase_attrs:
                prev = prior_yaml_phase_edges.get(k)
                if prev is not None and Decimal(str(prev)) != edge:
                    mism.append(f"{k}={prev}")
            if mism:
                logger.info(
                    "[CRYPTO_MATRIX] min_edge from %s (profile=%s) overrides grid YAML: %s "
                    "→ matrix applies scalar %s for all phases (agent=%s archetype=%s)",
                    matrix_document_path(),
                    cell.mode,
                    "; ".join(mism),
                    edge,
                    agent_name or "—",
                    archetype or "—",
                )
        except Exception as _log_exc:
            logger.debug("crypto matrix yaml override log skipped: %s", _log_exc)

    for attr in phase_attrs:
        if hasattr(sc, attr):
            setattr(sc, attr, edge)
    if hasattr(sc, "contrarian_sentiment_min"):
        setattr(sc, "contrarian_sentiment_min", float(cell.contrarian_sentiment_min))
    gap = row.get("contrarian_model_gap_min")
    if gap is not None and hasattr(sc, "contrarian_model_gap_min"):
        try:
            setattr(sc, "contrarian_model_gap_min", float(gap))
        except (TypeError, ValueError):
            pass
    kf = row.get("kelly_fraction")
    if kf is not None and hasattr(sc, "kelly_fraction"):
        try:
            setattr(sc, "kelly_fraction", Decimal(str(kf)))
        except Exception:
            pass
    if hasattr(sc, "mm_max_spread_cents"):
        setattr(sc, "mm_max_spread_cents", cell.mm_max_spread_cents)


def crypto_pm_live_execution_blocked(status: Any) -> bool:
    """Kalshi crypto: treat execution gate LIMITED as warn-only when settings allow.

    ``status`` is an :class:`ExecutionGateStatus`. When modern profile is on and the gate is
    LIMITED (warnings only, no critical reasons), allow orders even if an integrity overlay
    cleared ``safe_to_trade`` — unless ``MERID_CRYPTO_MODERN_LIMITED_DE_BLOCKS`` is false.
    """
    try:
        if status.blocked:
            return True
        if status.safe_to_trade:
            return False
        s = _settings_bundle()
        if not bool(getattr(s, "MERID_CRYPTO_MODERN_LIMITED_OVERRIDES_SAFE_TO_TRADE", True)):
            return True
        if not is_modern_crypto_production_profile():
            return True
        from core.execution_gate import GateState

        if getattr(status, "gate_state", None) != GateState.LIMITED.value:
            return True
        # LIMITED + modern: proceed (loop_lag is not an execution_gate reason)
        logger.warning(
            "[CRYPTO_GATE] modern profile: allowing Kalshi PM/crypto orders despite "
            "safe_to_trade=false while gate_state=limited (check integrity overlay)"
        )
        return False
    except Exception:
        return bool(getattr(status, "blocked", True) or not getattr(status, "safe_to_trade", False))


def consensus_path_log_enabled() -> bool:
    try:
        return bool(getattr(_settings_bundle(), "MERID_CONSENSUS_PATH_LOG", False))
    except Exception:
        return False


def consensus_health_enabled() -> bool:
    try:
        return bool(getattr(_settings_bundle(), "MERID_CRYPTO_CONSENSUS_HEALTH_LOG", True))
    except Exception:
        return True


def execution_invariant_enabled() -> bool:
    try:
        return bool(getattr(_settings_bundle(), "MERID_CRYPTO_EXECUTION_INVARIANT_LOG", True))
    except Exception:
        return True


def _path_log(event: str, payload: Dict[str, Any]) -> None:
    if not consensus_path_log_enabled():
        return
    logger.info("%s %s", event, json.dumps(payload, default=str))


def signal_feature_hash(
    *,
    asset: str,
    timeframe: str,
    edge_s: str,
    action: str,
    market_id: str,
) -> str:
    raw = f"{asset}|{timeframe}|{edge_s}|{action}|{market_id}".encode()
    return hashlib.sha256(raw).hexdigest()[:12]


def log_approved_signal_created(
    *,
    asset: str,
    timeframe: str,
    edge: float,
    feature_hash: str,
    market_id: str,
    action: str,
) -> None:
    _path_log(
        "APPROVED_SIGNAL_CREATED",
        {
            "asset": asset,
            "timeframe": timeframe,
            "edge": round(edge, 6),
            "feature_hash": feature_hash,
            "market_id": market_id,
            "action": action,
        },
    )


def log_consensus_update_event(
    *,
    market_key: str,
    status: str,
    direction: str,
    probability: float,
    confidence: float,
    signal_count: int,
    ticker: str = "",
) -> None:
    _path_log(
        "CONSENSUS_UPDATE",
        {
            "market_key": market_key,
            "ticker": ticker or market_key,
            "status": status,
            "consensus_value": {"direction": direction, "p": probability, "conf": confidence},
            "signal_count": signal_count,
        },
    )


def log_consensus_default_leak(
    *,
    market_key: str,
    status: str,
    direction: str,
    probability: float,
    signal_count: int,
) -> None:
    _path_log(
        "CONSENSUS_DEFAULT_LEAK",
        {
            "market_key": market_key,
            "status": status,
            "direction": direction,
            "probability": probability,
            "signal_count": signal_count,
            "hint": "votes present but consensus matches neutral default — inspect proposals",
        },
    )


def log_consensus_canonical_read(
    *,
    market_key: str,
    status: Optional[str],
    direction: Optional[str],
) -> None:
    if not consensus_path_log_enabled():
        return
    now = time.monotonic()
    prev = _CANON_READ_LAST.get(market_key, 0.0)
    if now - prev < 60.0:
        return
    _CANON_READ_LAST[market_key] = now
    _path_log(
        "CONSENSUS_READ",
        {"market_key": market_key, "status": status, "direction": direction},
    )


def log_consensus_consumed_for_trading(
    *,
    market_id: str,
    value: Dict[str, Any],
    decision: str,
) -> None:
    _path_log(
        "CONSENSUS_CONSUMED_FOR_TRADING",
        {"market_id": market_id, "value": value, "decision": decision},
    )


def log_execution_decision(
    *,
    market: str,
    side: str,
    size: int,
    consensus_value: Any,
    safe_to_trade: bool,
    risk_state: str,
    actual_order_submitted: bool,
    block_reason: str,
    source: str,
    execution_gate_sources: Optional[List[str]] = None,
) -> None:
    payload: Dict[str, Any] = {
        "market": market,
        "side": side,
        "size": size,
        "consensus_value": consensus_value,
        "safe_to_trade": safe_to_trade,
        "risk_state": risk_state,
        "actual_order_submitted": actual_order_submitted,
        "block_reason": block_reason,
        "source": source,
    }
    if execution_gate_sources:
        payload["execution_gate_sources"] = execution_gate_sources
    _path_log("EXECUTION_DECISION", payload)


def record_proposal_activity(market_key: str, market_id: str = "") -> None:
    if not consensus_health_enabled():
        return
    with _HEALTH_LOCK:
        dq = _SIGNAL_EVENTS[market_key]
        dq.append((time.time(), market_id or market_key))


def record_consensus_refresh(market_key: str) -> None:
    if not consensus_health_enabled():
        return
    with _HEALTH_LOCK:
        _LAST_CONSENSUS_TS[market_key] = time.time()


def maybe_emit_consensus_health_warnings() -> None:
    if not consensus_health_enabled():
        return
    try:
        s = _settings_bundle()
        stale_s = float(getattr(s, "MERID_CRYPTO_CONSENSUS_STALE_AFTER_SIGNAL_SECONDS", 120.0))
        leak_n = int(getattr(s, "MERID_CRYPTO_CONSENSUS_NEUTRAL_LEAK_MIN_SIGNALS", 5))
        leak_win = float(getattr(s, "MERID_CRYPTO_CONSENSUS_NEUTRAL_LEAK_WINDOW_MINUTES", 15.0))
    except Exception:
        stale_s = 120.0
        leak_n = 5
        leak_win = 15.0

    now = time.time()
    win_s = leak_win * 60.0
    with _HEALTH_LOCK:
        for key, dq in _SIGNAL_EVENTS.items():
            recent = [t for t, _ in dq if now - t <= win_s]
            last_sig = max((t for t, _ in dq), default=None)
            last_c = _LAST_CONSENSUS_TS.get(key)
            if last_sig and (last_c is None or last_sig > last_c + stale_s):
                logger.warning(
                    "[CONSENSUS_HEALTH] signals_recent but consensus not refreshed within %.0fs "
                    "for %s (last_signal_age=%.1fs last_consensus_age=%s)",
                    stale_s,
                    key,
                    now - last_sig,
                    (now - last_c) if last_c else None,
                )
            if len(recent) >= leak_n:
                try:
                    a, tf = key.split(":", 1)
                    from merid.swarm.consensus_aggregator import get_consensus_aggregator

                    view = get_consensus_aggregator().get_consensus(a, tf)
                except Exception:
                    view = None
                if view and view.status.value == "ready":
                    if (
                        view.consensus_direction == "neutral"
                        and abs(float(view.consensus_probability) - 0.5) < 1e-3
                    ):
                        logger.warning(
                            "[CONSENSUS_HEALTH] CONSENSUS_NEUTRAL_LEAK key=%s recent_signals=%d "
                            "window_min=%.1f — READY consensus stuck at neutral 50%%",
                            key,
                            len(recent),
                            leak_win,
                        )


class NoTradeDecisionTracker:
    """Observability only — records no-trade reasons; does not participate in gating."""

    _inst: Optional["NoTradeDecisionTracker"] = None
    _lock = threading.Lock()

    def __new__(cls) -> "NoTradeDecisionTracker":
        with cls._lock:
            if cls._inst is None:
                cls._inst = super().__new__(cls)
                cls._inst._buf = deque(maxlen=500)  # type: ignore[attr-defined]
            return cls._inst

    def observe(self, reason: str, **ctx: Any) -> None:
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "NoTradeDecisionTracker observe: %s %s",
                reason,
                json.dumps(ctx, default=str),
            )
        self._buf.append((datetime.now(timezone.utc).isoformat(), reason, ctx))  # type: ignore[attr-defined]


def get_no_trade_decision_tracker() -> NoTradeDecisionTracker:
    return NoTradeDecisionTracker()


def maybe_log_shadow_edge_near_miss(
    *,
    ticker: str,
    asset: str,
    best_edge: float,
    min_required: float,
    side: str,
) -> None:
    if not consensus_path_log_enabled():
        return
    rt = get_crypto_edge_runtime()
    shadow = rt.shadow_edge_yes if str(side).lower() == "yes" else rt.shadow_edge_no
    if shadow <= 0:
        return
    if min_required - shadow <= best_edge < min_required:
        logger.info(
            "[SHADOW_EDGE_OBS] ticker=%s asset=%s side=%s edge=%.5f min=%.5f shadow=%.5f",
            ticker,
            asset,
            side,
            best_edge,
            min_required,
            shadow,
        )


def maybe_log_ct_execution_invariant(
    *,
    cycle: int,
    tradeable_start_count: int,
    orders_placed: int,
    allow_new_entries: bool,
    dry_run: bool,
    observation_mode: bool,
    spot_feed_degraded: bool,
    live_ok: bool,
) -> None:
    if not execution_invariant_enabled():
        return
    if (
        tradeable_start_count <= 0
        or orders_placed > 0
        or not allow_new_entries
        or dry_run
        or observation_mode
        or spot_feed_degraded
        or not live_ok
    ):
        return
    try:
        from core.execution_gate import check_execution_gate

        gate = check_execution_gate()
        safe = bool(gate.safe_to_trade and not gate.blocked)
    except Exception as exc:
        logger.debug("execution invariant gate read failed: %s", exc)
        return
    if safe:
        logger.warning(
            "[EXECUTION_INVARIANT] cycle=%d tradeable=%d orders=0 safe_to_trade=true "
            "— likely cap/dedup/risk/fee skip; scan prior Skip lines for block_reason",
            cycle,
            tradeable_start_count,
        )
        try:
            from merid.prediction.alerts import get_alert_manager

            am = get_alert_manager()
            if am:
                am.fire_risk_warning(
                    market_id="kalshi_ct",
                    message=(
                        f"CT cycle {cycle}: {tradeable_start_count} tradeable candidates but "
                        "0 orders while execution_gate reports safe_to_trade"
                    ),
                )
        except Exception:
            pass

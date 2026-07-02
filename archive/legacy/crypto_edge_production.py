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
# LEGACY REMOVAL: Threading lock removed - causing deadlock during startup
# Single-threaded FastAPI startup doesn't need lock protection
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
        directional_min_edge=Decimal(str(row.get("directional_min_edge", "0.05"))),
        sentiment_vol_regime_min_edge=Decimal(
            str(row.get("sentiment_vol_regime_min_edge", row.get("directional_min_edge", "0.05")))
        ),
        # PRODUCTION FIX (2026-05-13): Don't override contrarian_sentiment_min with hardcoded default
        # Allow pm_profiles.yaml to set the value (baseline=35, production=75)
        contrarian_sentiment_min=float(row.get("contrarian_sentiment_min") if row.get("contrarian_sentiment_min") else 75.0),
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
    # SENTIMENT DECOUPLING (2026-05-14): Removed SENTIMENT_REGIME from sentiment-based archetype check.
    # Sentiment should not gate agent configuration or edge selection.
    use_sentiment_row = any(
        x in arch_u
        for x in (
            "VOL_BREAKOUT",
            "REGIME_SWITCH",
            "SENTIMENT_VOL",
            # SENTIMENT_REGIME removed
        )
    )
    edge = cell.sentiment_vol_regime_min_edge if use_sentiment_row else cell.directional_min_edge

    # PROFILE-GUARD: Skip crypto matrix overrides for kalshi_crypto_15m_v2
    merid_profile = os.getenv("MERID_PROFILE", "").lower()
    if merid_profile == "kalshi_crypto_15m_v2":
        logger.info("[PROFILE-GUARD] Crypto matrix skipped for kalshi_crypto_15m_v2 (uses canonical risk envelope)")
        return sc
    
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
                # SWARM DISABLED FOR 15M STACK: Skip consensus check
                # The 15m stack is a single-agent system and doesn't need multi-agent consensus
                view = None
                # try:
                #     a, tf = key.split(":", 1)
                #     from merid.swarm.consensus_aggregator import get_consensus_aggregator
                #     view = get_consensus_aggregator().get_consensus(a, tf)
                # except Exception:
                #     view = None
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
    # LEGACY REMOVAL: Threading lock removed - causing deadlock during startup
    # Single-threaded FastAPI startup doesn't need lock protection

    def __new__(cls) -> "NoTradeDecisionTracker":
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


def get_momentum_asset_filter(asset: str, max_rank: int = 2) -> Tuple[bool, Optional[str]]:
    """Filter assets based on momentum ranking for crypto edge production.
    
    Returns (allowed, reason) tuple where:
    - allowed: True if asset passes momentum filter
    - reason: Explanation if blocked, None if allowed
    
    This implements the "restrict candidates to top 2 momentum assets in favorable regimes"
    requirement from the tuning roadmap.
    """
    try:
        from merid.signals.momentum_ranker import get_momentum_ranker
        from merid.signals.unified_regime_classifier import get_unified_regime_classifier
        
        ranker = get_momentum_ranker()
        classifier = get_unified_regime_classifier()
        
        # Check if momentum rankings are fresh
        if not ranker.is_fresh(max_age_seconds=300):
            logger.debug("[MOMENTUM_FILTER] Rankings stale, allowing all assets")
            return True, None
        
        rankings = ranker.get_current_rankings()
        if not rankings:
            logger.debug("[MOMENTUM_FILTER] No rankings available, allowing all assets")
            return True, None
        
        # Get unified regime state
        regime_state = classifier.get_current_state()
        if regime_state and regime_state.is_defensive:
            # Defensive regime: only allow top momentum assets
            asset_rank = rankings.get_rank(asset)
            if asset_rank > max_rank:
                return False, f"momentum_rank_{asset_rank}_exceeds_max_{max_rank}_defensive_regime"
        
        # Check if asset is in top N
        asset_rank = rankings.get_rank(asset)
        if asset_rank <= max_rank:
            return True, None
        
        # For assets beyond top N, check if momentum is strong enough
        asset_momentum = rankings.get_momentum(asset)
        if asset_momentum and asset_momentum.is_strong_momentum:
            # Strong momentum assets allowed regardless of rank
            return True, None
        
        return False, f"momentum_rank_{asset_rank}_exceeds_max_{max_rank}"
        
    except Exception as exc:
        logger.debug("[MOMENTUM_FILTER] Momentum filter error, allowing all: %s", exc)
        return True, None


def apply_momentum_edge_multiplier(asset: str, base_edge: float) -> float:
    """Apply momentum-based multiplier to edge threshold.
    
    Returns adjusted edge threshold. Assets with strong momentum get
    slightly lower edge requirements (more aggressive), while weak
    momentum assets get higher edge requirements (more conservative).
    """
    try:
        from merid.signals.momentum_ranker import get_momentum_ranker
        
        ranker = get_momentum_ranker()
        if not ranker.is_fresh(max_age_seconds=300):
            return base_edge
        
        rankings = ranker.get_current_rankings()
        if not rankings:
            return base_edge
        
        asset_momentum = rankings.get_momentum(asset)
        if not asset_momentum:
            return base_edge
        
        # Multiplier based on regime
        if asset_momentum.regime in ("strong_up", "strong_down"):
            # Strong momentum: 10% edge reduction
            return base_edge * 0.9
        elif asset_momentum.regime in ("up", "down"):
            # Moderate momentum: 5% edge reduction
            return base_edge * 0.95
        elif asset_momentum.regime == "neutral":
            # Neutral: no adjustment
            return base_edge
        
        return base_edge
        
    except Exception as exc:
        logger.debug("[MOMENTUM_EDGE] Edge multiplier error, using base: %s", exc)
        return base_edge


def check_anomaly_gating(
    ticker: str,
    volume: float,
    bid: Optional[float],
    ask: Optional[float],
) -> Tuple[bool, Optional[str]]:
    """Check for volume/spread anomalies that should gate trading.
    
    Returns (allowed, reason) tuple where:
    - allowed: True if no anomaly detected
    - reason: Explanation if blocked, None if allowed
    
    This implements anomaly detection gating for volume spikes and
    spread outliers that may indicate market stress or manipulation.
    """
    try:
        # Spread anomaly check
        if bid is not None and ask is not None and bid > 0 and ask > 0:
            spread_cents = (ask - bid) * 100
            # Extremely wide spread (> 20 cents) indicates liquidity stress
            if spread_cents > 20:
                return False, f"spread_anomaly_{spread_cents:.1f}_cents_exceeds_threshold"
            # Wide spread (> 10 cents) in 15m markets is concerning
            if "15M" in ticker.upper() and spread_cents > 10:
                return False, f"spread_anomaly_{spread_cents:.1f}_cents_in_15m_market"
        
        # Volume anomaly check (if volume data available)
        if volume > 0:
            # Extremely high volume (> 10000 contracts) may indicate pump/dump
            if volume > 10000:
                return False, f"volume_anomaly_{volume:.0f}_contracts_exceeds_threshold"
            # Very high volume (> 5000 contracts) warrants caution
            if volume > 5000:
                logger.warning(
                    "[ANOMALY_GATE] ticker=%s volume=%.0f high but not gating - monitor closely",
                    ticker,
                    volume,
                )
        
        return True, None
        
    except Exception as exc:
        logger.debug("[ANOMALY_GATE] Anomaly check error, allowing trade: %s", exc)
        return True, None


def get_risk_appetite_factor() -> float:
    """Get per-cycle risk appetite factor (0-1) for edge scaling.
    
    Returns a factor between 0.0 (risk-off, halt trading) and 1.0 (normal risk).
    Values < 1.0 reduce edge requirements (more aggressive), values > 1.0
    increase edge requirements (more conservative).
    
    This factor is derived from the unified regime classifier which integrates
    macro, momentum, and BTC anchor signals.
    """
    try:
        from merid.signals.unified_regime_classifier import get_unified_regime_classifier
        
        classifier = get_unified_regime_classifier()
        regime_state = classifier.get_current_state()
        
        if not regime_state:
            return 1.0
        
        # Map execution regime to risk appetite factor
        if regime_state.execution_regime.value == "aggressive":
            # Aggressive: 20% edge reduction (0.8 factor)
            return 0.8
        elif regime_state.execution_regime.value == "defensive":
            # Defensive: 50% edge increase (1.5 factor)
            return 1.5
        elif regime_state.execution_regime.value == "halt":
            # Halt: infinite edge requirement (effectively block trades)
            return float('inf')
        else:
            # Normal: no adjustment
            return 1.0
        
    except Exception as exc:
        logger.debug("[RISK_APPETITE] Factor derivation error, using default 1.0: %s", exc)
        return 1.0


def apply_risk_appetite_to_edge(base_edge: float) -> float:
    """Apply risk appetite factor to base edge threshold.
    
    Returns adjusted edge threshold. Lower risk appetite (conservative regime)
    increases edge requirements, higher risk appetite (aggressive regime)
    decreases edge requirements.
    """
    risk_factor = get_risk_appetite_factor()
    
    if risk_factor == float('inf'):
        # Halt regime: effectively infinite edge requirement
        return float('inf')
    
    adjusted = base_edge * risk_factor
    return adjusted


def get_dynamic_bankroll_cap(base_cap: int, bankroll_usd: Optional[float] = None) -> int:
    """Calculate dynamic position cap based on available bankroll.
    
    For small bankrolls (~36 USD), scales down position caps to ensure
    diversification across multiple edges while maintaining minimum trade size.
    
    Args:
        base_cap: Base position cap from config (e.g., 5 positions)
        bankroll_usd: Available bankroll in USD (default: reads from system)
    
    Returns:
        Dynamic position cap (integer, minimum 1)
    """
    try:
        # If bankroll not provided, try to read from system
        if bankroll_usd is None:
            try:
                from merid.prediction.model import PredictionMarketModel
                model = PredictionMarketModel()
                # Try to get bankroll from paper trading or live account
                # This is a fallback - in production, bankroll should be passed explicitly
                bankroll_usd = 36.0  # Default small bankroll for crypto 15m
            except Exception:
                bankroll_usd = 36.0
        
        # Small bankroll threshold (below this, reduce caps)
        SMALL_BANKROLL_THRESHOLD = 50.0  # USD
        MIN_CONTRACT_COST = 0.02  # Minimum cost per trade (1¢ contract + 1¢ fee)
        
        if bankroll_usd >= SMALL_BANKROLL_THRESHOLD:
            # Normal bankroll: use base cap
            return base_cap
        
        # Small bankroll: scale cap to allow diversification
        # Target: reserve 50% of bankroll for fees, use 50% for positions
        usable_bankroll = bankroll_usd * 0.5
        max_positions_by_cap = int(usable_bankroll / MIN_CONTRACT_COST)
        
        # Cap at base_cap, minimum 1 position
        dynamic_cap = min(base_cap, max(1, max_positions_by_cap))
        
        # For very small bankrolls (< $10), limit to 1-2 positions max
        if bankroll_usd < 10.0:
            dynamic_cap = min(2, dynamic_cap)
        
        return dynamic_cap
        
    except Exception as exc:
        logger.debug("[DYNAMIC_CAP] Cap calculation error, using base cap: %s", exc)
        return base_cap


def get_trade_granularity(bankroll_usd: Optional[float] = None) -> int:
    """Get trade granularity (contracts per edge) for small bankroll.
    
    For small bankrolls (~36 USD), returns 1 contract per edge to maximize
    diversification. For larger bankrolls, can scale up.
    
    Args:
        bankroll_usd: Available bankroll in USD (default: reads from system)
    
    Returns:
        Number of contracts per edge (integer, minimum 1)
    """
    try:
        # If bankroll not provided, try to read from system
        if bankroll_usd is None:
            try:
                from merid.prediction.model import PredictionMarketModel
                model = PredictionMarketModel()
                bankroll_usd = 36.0  # Default small bankroll for crypto 15m
            except Exception:
                bankroll_usd = 36.0
        
        # Small bankroll: 1 contract per edge for maximum diversification
        SMALL_BANKROLL_THRESHOLD = 50.0  # USD
        
        if bankroll_usd < SMALL_BANKROLL_THRESHOLD:
            return 1
        
        # Larger bankrolls can use larger trade sizes
        # For bankroll $50-100: 1-2 contracts per edge
        if bankroll_usd < 100.0:
            return 1
        
        # For bankroll $100-500: 2-3 contracts per edge
        if bankroll_usd < 500.0:
            return 2
        
        # For larger bankrolls: scale proportionally (capped at 10)
        return min(10, int(bankroll_usd / 100.0))
        
    except Exception as exc:
        logger.debug("[TRADE_GRANULARITY] Granularity calculation error, using default 1: %s", exc)
        return 1


def apply_brier_feedback_to_edge(base_edge: float, min_resolved: int = 50) -> float:
    """Apply Brier score feedback to edge threshold for auto-tuning.
    
    Uses BrierMetricsTracker to read prediction calibration and adjust
    edge thresholds accordingly:
    - Low Brier score (< 0.15): model is well-calibrated, can lower edge threshold
    - High Brier score (> 0.25): model is poorly calibrated, raise edge threshold
    - Between 0.15-0.25: no adjustment
    
    Args:
        base_edge: Base edge threshold from config
        min_resolved: Minimum number of resolved predictions required for feedback
    
    Returns:
        Adjusted edge threshold
    """
    try:
        from monitoring.brier_metrics import get_brier_tracker
        
        tracker = get_brier_tracker()
        summary = tracker.get_summary()
        
        resolved_count = summary.get("resolved_predictions", 0)
        
        # Need minimum resolved predictions for meaningful feedback
        if resolved_count < min_resolved:
            logger.debug(
                "[BRIER_FEEDBACK] Insufficient resolved predictions (%d < %d), using base edge",
                resolved_count,
                min_resolved,
            )
            return base_edge
        
        brier_score = summary.get("overall_brier_score", 0.25)
        skill_score = summary.get("skill_score", 0.0)
        
        # Adjust edge based on Brier score
        # Lower Brier = better calibration = lower edge threshold (more aggressive)
        # Higher Brier = worse calibration = higher edge threshold (more conservative)
        
        if brier_score < 0.12:
            # Excellent calibration: 20% edge reduction
            multiplier = 0.8
            logger.info("[BRIER_FEEDBACK] Excellent calibration (Brier=%.3f), edge * 0.8", brier_score)
        elif brier_score < 0.15:
            # Good calibration: 10% edge reduction
            multiplier = 0.9
            logger.info("[BRIER_FEEDBACK] Good calibration (Brier=%.3f), edge * 0.9", brier_score)
        elif brier_score > 0.30:
            # Poor calibration: 30% edge increase
            multiplier = 1.3
            logger.warning("[BRIER_FEEDBACK] Poor calibration (Brier=%.3f), edge * 1.3", brier_score)
        elif brier_score > 0.25:
            # Below baseline: 15% edge increase
            multiplier = 1.15
            logger.warning("[BRIER_FEEDBACK] Below baseline (Brier=%.3f), edge * 1.15", brier_score)
        else:
            # Normal range: no adjustment
            multiplier = 1.0
            logger.debug("[BRIER_FEEDBACK] Normal calibration (Brier=%.3f), no adjustment", brier_score)
        
        # Also consider skill score
        if skill_score > 0.5:
            # High skill: additional 5% reduction
            multiplier *= 0.95
            logger.debug("[BRIER_FEEDBACK] High skill (%.2f), additional edge * 0.95", skill_score)
        elif skill_score < 0:
            # Negative skill: additional 10% increase
            multiplier *= 1.1
            logger.warning("[BRIER_FEEDBACK] Negative skill (%.2f), additional edge * 1.1", skill_score)
        
        adjusted = base_edge * multiplier
        return adjusted
        
    except Exception as exc:
        logger.debug("[BRIER_FEEDBACK] Feedback application error, using base edge: %s", exc)
        return base_edge


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

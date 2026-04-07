"""Aggressively Conservative 15m Kalshi Crypto Gate Module.

Exposes :func:`apply_15m_conservative_gates` — a batch gate function that
takes a list of :class:`RawSignal` objects and returns only those that
survive all configured acceptance criteria.

This module is the **batch / pipeline** companion to the per-signal
:class:`~merid.strategies.kalshi_crypto_15m_conservative.Conservative15mStrategy`.
It is designed for use in integration tests and future pipeline stages where
multiple raw signals arrive together and are filtered as a group.

Gate sequence
─────────────
1. **Kill switch** — profile disabled → all rejected.
2. **Probability threshold** — ``p_forecast`` must clear ``effective_min_p``
   (base + rate tightening + drawdown tightening).
3. **Edge threshold** — net edge in bps must exceed ``min_edge_bps``.
4. **Structure compatibility** — HTF/MTF alignment must not veto the direction.
5. **Liquidity sanity** — contract volume and OI must clear minimums;
   bid-ask spread must be below the cap.
6. **Per-asset 15m rate limit** — max ``per_asset_max_per_15m`` per asset
   within any 15-minute window (from the shared ``GlobalRateTracker``).
7. **Global rate cap** — if the rolling 60-minute count reaches
   ``global_max_trades_per_hour`` the remaining signals are rejected.

Signals are evaluated in descending order of ``p_forecast`` so that the
highest-conviction trades are prioritised when the rate cap is about to
be reached.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.trading.gates.kalshi_15m_conservative_gates")


# ── Data models ───────────────────────────────────────────────────────────


@dataclass
class RawSignal:
    """Pre-gate signal for a single 15m Kalshi contract.

    Produced by a signal builder (e.g.
    ``merid.trading.kalshi_15m_signal_builder``) before any gate logic runs.
    """

    asset: str
    """Asset symbol, e.g. ``"BTC"``."""

    timeframe: str
    """Timeframe label — always ``"15m"`` for this module."""

    series: str
    """Kalshi series ticker, e.g. ``"KXBTC15M"``."""

    contract_id: str
    """Full Kalshi contract ticker, e.g. ``"KXBTC15M-26JAN11T0930"``."""

    direction: str
    """Signal direction: ``"YES"`` (price up) or ``"NO"`` (price down)."""

    p_forecast: float
    """Model's forecast probability for the signal direction, 0–1."""

    market_prob: float
    """Current Kalshi mid-market probability for YES, 0–1."""

    edge_bps: float
    """Net edge in basis points: ``(p_forecast - market_prob) * 10_000``
    (positive = favourable)."""

    htf_alignment: float = 0.0
    """Multi-timeframe alignment score, -1 (fully bearish) to +1 (fully bullish)."""

    fvg_confirmed: bool = False
    """Whether a fair-value gap is present in the signal direction."""

    key_level_near: bool = False
    """Whether the current price is near a key structural level."""

    volume: float = 0.0
    """Kalshi contract volume (proxy for liquidity)."""

    open_interest: float = 0.0
    """Kalshi contract open interest."""

    spread_cents: float = 0.0
    """Bid-ask spread on the Kalshi contract, in cents."""

    metadata: Dict[str, Any] = field(default_factory=dict)
    """Arbitrary extra context (spot price, strike, etc.)."""


@dataclass
class ApprovedSignal:
    """A :class:`RawSignal` that has passed all gates.

    Carries the final probability / edge used for sizing, plus audit
    metadata showing which gates passed and which (if any) were close.
    """

    raw: RawSignal
    """The original raw signal."""

    final_p: float
    """Effective probability used for sizing (may equal ``raw.p_forecast``)."""

    final_edge_bps: float
    """Effective edge in bps."""

    gates_passed: List[str] = field(default_factory=list)
    """Names of gates that were evaluated and passed."""

    gates_skipped: List[str] = field(default_factory=list)
    """Names of gates that were not applicable / skipped."""

    approved_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    """Timestamp of gate approval."""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset": self.raw.asset,
            "timeframe": self.raw.timeframe,
            "series": self.raw.series,
            "contract_id": self.raw.contract_id,
            "direction": self.raw.direction,
            "p_forecast": self.raw.p_forecast,
            "final_p": self.final_p,
            "final_edge_bps": self.final_edge_bps,
            "htf_alignment": self.raw.htf_alignment,
            "fvg_confirmed": self.raw.fvg_confirmed,
            "key_level_near": self.raw.key_level_near,
            "gates_passed": self.gates_passed,
            "gates_skipped": self.gates_skipped,
            "approved_at": self.approved_at.isoformat(),
        }


@dataclass
class GateRejectReason:
    """Structured rejection record for audit logging."""

    asset: str
    contract_id: str
    direction: str
    gate: str
    reason: str
    p_forecast: float
    edge_bps: float


# ── Gate implementation ────────────────────────────────────────────────────

_SATELLITE_ASSETS = frozenset({"SOL", "XRP", "DOGE"})


def apply_15m_conservative_gates(
    raw_signals: List[RawSignal],
    risk_state: Optional[Dict[str, Any]] = None,
    trade_history: Optional[List[Dict[str, Any]]] = None,
    asset_profile: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
    config: Optional[Any] = None,
) -> List[ApprovedSignal]:
    """Apply all conservative gates and return only approved signals.

    Parameters
    ----------
    raw_signals:
        Candidate signals produced by the signal builder.
    risk_state:
        Optional dict with ``"drawdown_pct"`` and ``"bankroll_usd"`` keys.
        If provided, overrides the module-level :class:`DrawdownState`
        for this call (useful in tests).
    trade_history:
        Optional list of past trade dicts for per-asset rate checking
        (only used when ``GlobalRateTracker`` history is unavailable).
    asset_profile:
        Optional per-asset override dict (e.g. custom min_p per asset).
    now:
        Reference timestamp for rate-window calculations.
    config:
        Optional :class:`~merid.strategies.kalshi_crypto_15m_conservative.Conservative15mConfig`
        override (defaults to module singleton).

    Returns
    -------
    List[ApprovedSignal]
        Signals that passed every gate, in descending order of
        ``final_p``.
    """
    from merid.strategies.kalshi_crypto_15m_conservative import (
        Conservative15mConfig,
        DrawdownState,
        get_conservative_config,
        get_drawdown_state,
        get_rate_tracker,
    )

    cfg: Conservative15mConfig = config if config is not None else get_conservative_config()
    _now = now or datetime.now(timezone.utc)

    # ── Gate 0: Kill switch ───────────────────────────────────────────────
    if not cfg.enabled:
        logger.info("[GATE] Kill switch active — all 15m conservative signals rejected")
        return []

    # ── Gather shared singletons ──────────────────────────────────────────
    tracker = get_rate_tracker()
    dd_state: DrawdownState = get_drawdown_state()

    # Allow caller to inject drawdown state for testing.
    if risk_state is not None:
        drawdown_pct: float = float(risk_state.get("drawdown_pct", 0.0))
    else:
        drawdown_pct = dd_state.drawdown_pct()

    # ── Gate 1: Drawdown pause ────────────────────────────────────────────
    if drawdown_pct >= cfg.drawdown_pause_pct:
        logger.warning(
            "[GATE] drawdown_pause: dd=%.1f%% >= %.1f%% — all signals rejected",
            drawdown_pct, cfg.drawdown_pause_pct,
        )
        return []

    # ── Compute effective drawdown increment ──────────────────────────────
    dd_incr = cfg.drawdown_min_p_delta if drawdown_pct >= cfg.drawdown_warning_pct else 0.0

    # ── Pre-sort by p_forecast descending (best first) ───────────────────
    sorted_signals = sorted(raw_signals, key=lambda s: s.p_forecast, reverse=True)

    approved: List[ApprovedSignal] = []
    rejections: List[GateRejectReason] = []

    for sig in sorted_signals:
        asset = sig.asset
        direction = sig.direction.upper()

        # ── Gate 2: Global hard cap ───────────────────────────────────────
        if tracker.is_hard_capped(cfg, _now):
            rejections.append(GateRejectReason(
                asset=asset,
                contract_id=sig.contract_id,
                direction=direction,
                gate="global_rate_hard_cap",
                reason=f"count={tracker.count_last_hour(_now)} >= cap={cfg.global_max_trades_per_hour}",
                p_forecast=sig.p_forecast,
                edge_bps=sig.edge_bps,
            ))
            logger.debug(
                "[GATE] %s %s reject=hard_cap count=%d",
                asset, sig.contract_id, tracker.count_last_hour(_now),
            )
            continue

        # ── Gate 3: Per-asset 15m cap ─────────────────────────────────────
        asset_15m_count = tracker.count_last_15m_for_asset(asset, _now)
        if asset_15m_count >= cfg.per_asset_max_per_15m:
            rejections.append(GateRejectReason(
                asset=asset,
                contract_id=sig.contract_id,
                direction=direction,
                gate="per_asset_15m_cap",
                reason=f"asset_15m_count={asset_15m_count} >= cap={cfg.per_asset_max_per_15m}",
                p_forecast=sig.p_forecast,
                edge_bps=sig.edge_bps,
            ))
            continue

        # ── Gate 4: Probability threshold ─────────────────────────────────
        base_min_p = (
            cfg.min_p_satellite if asset in _SATELLITE_ASSETS else cfg.min_p
        )
        rate_incr = tracker.dynamic_min_p_increment(asset, cfg, _now)
        effective_min_p = min(base_min_p + rate_incr + dd_incr, 0.99)

        if sig.p_forecast < effective_min_p:
            rejections.append(GateRejectReason(
                asset=asset,
                contract_id=sig.contract_id,
                direction=direction,
                gate="min_p",
                reason=f"p={sig.p_forecast:.4f} < min_p={effective_min_p:.4f}",
                p_forecast=sig.p_forecast,
                edge_bps=sig.edge_bps,
            ))
            continue

        # ── Gate 5: Edge threshold ─────────────────────────────────────────
        if sig.edge_bps < cfg.min_edge_bps:
            rejections.append(GateRejectReason(
                asset=asset,
                contract_id=sig.contract_id,
                direction=direction,
                gate="min_edge_bps",
                reason=f"edge={sig.edge_bps:.1f}bps < min={cfg.min_edge_bps}bps",
                p_forecast=sig.p_forecast,
                edge_bps=sig.edge_bps,
            ))
            continue

        # ── Gate 6: Structure compatibility ───────────────────────────────
        # YES signal needs non-negative alignment (or at least above veto threshold).
        # NO signal needs non-positive alignment (or at least above veto threshold).
        htf = sig.htf_alignment
        if direction == "YES" and htf <= cfg.htf_contradiction_threshold:
            rejections.append(GateRejectReason(
                asset=asset,
                contract_id=sig.contract_id,
                direction=direction,
                gate="htf_structure",
                reason=f"YES but htf_alignment={htf:.3f} <= veto={cfg.htf_contradiction_threshold}",
                p_forecast=sig.p_forecast,
                edge_bps=sig.edge_bps,
            ))
            continue
        if direction == "NO" and htf >= -cfg.htf_contradiction_threshold:
            rejections.append(GateRejectReason(
                asset=asset,
                contract_id=sig.contract_id,
                direction=direction,
                gate="htf_structure",
                reason=f"NO but htf_alignment={htf:.3f} >= veto={-cfg.htf_contradiction_threshold}",
                p_forecast=sig.p_forecast,
                edge_bps=sig.edge_bps,
            ))
            continue

        # Insufficient alignment magnitude
        if abs(htf) < cfg.htf_alignment_min:
            rejections.append(GateRejectReason(
                asset=asset,
                contract_id=sig.contract_id,
                direction=direction,
                gate="htf_alignment_min",
                reason=f"|alignment|={abs(htf):.3f} < min={cfg.htf_alignment_min}",
                p_forecast=sig.p_forecast,
                edge_bps=sig.edge_bps,
            ))
            continue

        # ── Gate 7: Liquidity sanity ───────────────────────────────────────
        if sig.volume < cfg.min_contract_volume:
            rejections.append(GateRejectReason(
                asset=asset,
                contract_id=sig.contract_id,
                direction=direction,
                gate="liquidity_volume",
                reason=f"volume={sig.volume} < min={cfg.min_contract_volume}",
                p_forecast=sig.p_forecast,
                edge_bps=sig.edge_bps,
            ))
            continue

        if sig.open_interest < cfg.min_contract_oi:
            rejections.append(GateRejectReason(
                asset=asset,
                contract_id=sig.contract_id,
                direction=direction,
                gate="liquidity_oi",
                reason=f"oi={sig.open_interest} < min={cfg.min_contract_oi}",
                p_forecast=sig.p_forecast,
                edge_bps=sig.edge_bps,
            ))
            continue

        if sig.spread_cents > cfg.max_spread_cents:
            rejections.append(GateRejectReason(
                asset=asset,
                contract_id=sig.contract_id,
                direction=direction,
                gate="liquidity_spread",
                reason=f"spread={sig.spread_cents}c > max={cfg.max_spread_cents}c",
                p_forecast=sig.p_forecast,
                edge_bps=sig.edge_bps,
            ))
            continue

        # ── All gates passed ───────────────────────────────────────────────
        tracker.record(asset, _now)

        passed_names = [
            "kill_switch",
            "drawdown_pause",
            "global_rate_hard_cap",
            "per_asset_15m_cap",
            "min_p",
            "min_edge_bps",
            "htf_structure",
            "htf_alignment_min",
            "liquidity_volume",
            "liquidity_oi",
            "liquidity_spread",
        ]

        approved.append(ApprovedSignal(
            raw=sig,
            final_p=sig.p_forecast,
            final_edge_bps=sig.edge_bps,
            gates_passed=passed_names,
        ))

        logger.debug(
            "[GATE] APPROVED %s %s %s p=%.4f edge=%.1fbps htf=%.3f",
            asset, sig.contract_id, direction,
            sig.p_forecast, sig.edge_bps, sig.htf_alignment,
        )

    if rejections:
        _log_rejection_summary(rejections)

    return approved


def _log_rejection_summary(rejections: List[GateRejectReason]) -> None:
    """Log a compact summary of gate rejections for audit purposes."""
    by_gate: Dict[str, int] = {}
    for r in rejections:
        by_gate[r.gate] = by_gate.get(r.gate, 0) + 1
    logger.debug(
        "[GATE] Rejected %d signals: %s",
        len(rejections),
        ", ".join(f"{k}={v}" for k, v in sorted(by_gate.items())),
    )

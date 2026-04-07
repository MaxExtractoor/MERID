"""Unit tests for merid.trading.gates.kalshi_15m_conservative_gates.

Covers:
  1. Kill switch — all signals rejected when profile disabled.
  2. Drawdown pause — all signals rejected above pause threshold.
  3. Probability gate — signals below effective min_p rejected.
  4. Edge gate — signals below min_edge_bps rejected.
  5. HTF structure gate — contradictory / insufficient alignment rejected.
  6. Liquidity gates — low volume, OI, wide spread rejected.
  7. Per-asset 15m cap — excess trades per asset rejected.
  8. Global hard cap — no further approvals once cap reached.
  9. Priority ordering — highest-p signals approved first when cap is near.
  10. Integration — end-to-end: synthetic high-quality batch reaches ~target rate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest

from merid.strategies.kalshi_crypto_15m_conservative import (
    Conservative15mConfig,
    DrawdownState,
    GlobalRateTracker,
)
from merid.trading.gates.kalshi_15m_conservative_gates import (
    ApprovedSignal,
    RawSignal,
    apply_15m_conservative_gates,
)


# ── Helpers ───────────────────────────────────────────────────────────────


def _make_signal(
    asset: str = "BTC",
    direction: str = "YES",
    p_forecast: float = 0.70,
    market_prob: float = 0.50,
    htf_alignment: float = 0.65,
    volume: float = 200.0,
    open_interest: float = 30.0,
    spread_cents: float = 3.0,
    edge_bps: float = 200.0,
    **kwargs: Any,
) -> RawSignal:
    return RawSignal(
        asset=asset,
        timeframe="15m",
        series=f"KX{asset}15M",
        contract_id=f"KX{asset}15M-T01",
        direction=direction,
        p_forecast=p_forecast,
        market_prob=market_prob,
        edge_bps=edge_bps,
        htf_alignment=htf_alignment,
        volume=volume,
        open_interest=open_interest,
        spread_cents=spread_cents,
        **kwargs,
    )


def _cfg(**kwargs: Any) -> Conservative15mConfig:
    c = Conservative15mConfig()
    for k, v in kwargs.items():
        setattr(c, k, v)
    return c


def _fresh_state() -> tuple[GlobalRateTracker, DrawdownState]:
    """Return fresh singletons for test isolation."""
    from merid.strategies import kalshi_crypto_15m_conservative as mod
    tracker = GlobalRateTracker()
    dd = DrawdownState()
    mod._RATE_TRACKER = tracker
    mod._DRAWDOWN = dd
    return tracker, dd


# ── Tests ─────────────────────────────────────────────────────────────────


class TestKillSwitch:
    def test_kill_switch_rejects_all(self) -> None:
        _fresh_state()
        cfg = _cfg(enabled=False)
        signals = [_make_signal("BTC"), _make_signal("ETH")]
        approved = apply_15m_conservative_gates(signals, config=cfg)
        assert approved == []


class TestDrawdownGate:
    def test_drawdown_pause_rejects_all(self) -> None:
        tracker, dd = _fresh_state()
        dd.set_bankroll(1000.0)
        dd.record_pnl(-100.0, 900.0)  # 10% drawdown > 6% pause
        cfg = _cfg(drawdown_pause_pct=6.0)
        signals = [_make_signal("BTC")]
        approved = apply_15m_conservative_gates(
            signals, risk_state={"drawdown_pct": 10.0}, config=cfg
        )
        assert approved == []

    def test_drawdown_warning_tightens_min_p(self) -> None:
        _fresh_state()
        # With drawdown in warning zone, effective min_p = 0.64 + 0.02 = 0.66
        # A signal with p=0.65 should be rejected.
        cfg = _cfg(
            min_p=0.64,
            drawdown_warning_pct=2.0,
            drawdown_pause_pct=10.0,
            drawdown_min_p_delta=0.02,
        )
        signal = _make_signal("BTC", p_forecast=0.65, edge_bps=150.0)
        approved = apply_15m_conservative_gates(
            [signal], risk_state={"drawdown_pct": 3.0}, config=cfg
        )
        assert len(approved) == 0

    def test_below_drawdown_warning_uses_base_min_p(self) -> None:
        _fresh_state()
        cfg = _cfg(
            min_p=0.64,
            drawdown_warning_pct=5.0,
            drawdown_pause_pct=10.0,
            drawdown_min_p_delta=0.02,
        )
        # p=0.65 > 0.64 → should pass when drawdown < warning
        signal = _make_signal("BTC", p_forecast=0.65, edge_bps=150.0)
        now = datetime.now(timezone.utc)
        approved = apply_15m_conservative_gates(
            [signal], risk_state={"drawdown_pct": 1.0}, config=cfg, now=now
        )
        assert len(approved) == 1


class TestProbabilityGate:
    def test_below_min_p_rejected(self) -> None:
        _fresh_state()
        cfg = _cfg(min_p=0.64, min_p_satellite=0.66)
        signal = _make_signal("BTC", p_forecast=0.62, edge_bps=150.0)
        approved = apply_15m_conservative_gates([signal], config=cfg)
        assert len(approved) == 0

    def test_above_min_p_approved(self) -> None:
        _fresh_state()
        cfg = _cfg(min_p=0.64, min_p_satellite=0.66)
        now = datetime.now(timezone.utc)
        signal = _make_signal("BTC", p_forecast=0.65, edge_bps=150.0)
        approved = apply_15m_conservative_gates([signal], config=cfg, now=now)
        assert len(approved) == 1

    def test_satellite_stricter_threshold(self) -> None:
        _fresh_state()
        cfg = _cfg(min_p=0.64, min_p_satellite=0.66)
        now = datetime.now(timezone.utc)
        # p=0.65 passes for BTC (0.64) but fails for DOGE (0.66)
        btc_sig = _make_signal("BTC", p_forecast=0.65, edge_bps=150.0)
        doge_sig = _make_signal("DOGE", p_forecast=0.65, edge_bps=150.0)
        btc_approved = apply_15m_conservative_gates([btc_sig], config=cfg, now=now)
        doge_approved = apply_15m_conservative_gates([doge_sig], config=cfg, now=now)
        assert len(btc_approved) == 1
        assert len(doge_approved) == 0


class TestEdgeGate:
    def test_low_edge_rejected(self) -> None:
        _fresh_state()
        cfg = _cfg(min_edge_bps=50)
        signal = _make_signal("BTC", p_forecast=0.70, edge_bps=30.0)
        approved = apply_15m_conservative_gates([signal], config=cfg)
        assert len(approved) == 0

    def test_sufficient_edge_passes(self) -> None:
        _fresh_state()
        cfg = _cfg(min_edge_bps=50)
        now = datetime.now(timezone.utc)
        signal = _make_signal("BTC", p_forecast=0.70, edge_bps=60.0)
        approved = apply_15m_conservative_gates([signal], config=cfg, now=now)
        assert len(approved) == 1


class TestHTFStructureGate:
    def test_yes_signal_vetoed_by_bearish_alignment(self) -> None:
        _fresh_state()
        cfg = _cfg(htf_contradiction_threshold=-0.50)
        now = datetime.now(timezone.utc)
        signal = _make_signal(
            "BTC", direction="YES", p_forecast=0.70, htf_alignment=-0.60, edge_bps=200.0
        )
        approved = apply_15m_conservative_gates([signal], config=cfg, now=now)
        assert len(approved) == 0

    def test_no_signal_vetoed_by_bullish_alignment(self) -> None:
        _fresh_state()
        cfg = _cfg(htf_contradiction_threshold=-0.50)
        now = datetime.now(timezone.utc)
        signal = _make_signal(
            "ETH", direction="NO", p_forecast=0.70, htf_alignment=0.60, edge_bps=200.0
        )
        approved = apply_15m_conservative_gates([signal], config=cfg, now=now)
        assert len(approved) == 0

    def test_insufficient_alignment_magnitude_rejected(self) -> None:
        _fresh_state()
        cfg = _cfg(htf_alignment_min=0.30)
        now = datetime.now(timezone.utc)
        signal = _make_signal("BTC", p_forecast=0.70, htf_alignment=0.15, edge_bps=200.0)
        approved = apply_15m_conservative_gates([signal], config=cfg, now=now)
        assert len(approved) == 0

    def test_aligned_yes_passes(self) -> None:
        _fresh_state()
        cfg = _cfg(htf_alignment_min=0.30, htf_contradiction_threshold=-0.50)
        now = datetime.now(timezone.utc)
        signal = _make_signal(
            "BTC", direction="YES", p_forecast=0.70, htf_alignment=0.60, edge_bps=200.0
        )
        approved = apply_15m_conservative_gates([signal], config=cfg, now=now)
        assert len(approved) == 1


class TestLiquidityGates:
    def test_low_volume_rejected(self) -> None:
        _fresh_state()
        cfg = _cfg(min_contract_volume=30.0)
        now = datetime.now(timezone.utc)
        signal = _make_signal("BTC", volume=10.0, p_forecast=0.70, edge_bps=200.0)
        approved = apply_15m_conservative_gates([signal], config=cfg, now=now)
        assert len(approved) == 0

    def test_low_oi_rejected(self) -> None:
        _fresh_state()
        cfg = _cfg(min_contract_oi=5.0)
        now = datetime.now(timezone.utc)
        signal = _make_signal("BTC", open_interest=2.0, p_forecast=0.70, edge_bps=200.0)
        approved = apply_15m_conservative_gates([signal], config=cfg, now=now)
        assert len(approved) == 0

    def test_wide_spread_rejected(self) -> None:
        _fresh_state()
        cfg = _cfg(max_spread_cents=10.0)
        now = datetime.now(timezone.utc)
        signal = _make_signal("BTC", spread_cents=15.0, p_forecast=0.70, edge_bps=200.0)
        approved = apply_15m_conservative_gates([signal], config=cfg, now=now)
        assert len(approved) == 0


class TestRateLimits:
    def test_per_asset_15m_cap_enforced(self) -> None:
        tracker, _ = _fresh_state()
        cfg = _cfg(per_asset_max_per_15m=2, global_max_trades_per_hour=30)
        now = datetime.now(timezone.utc)

        # Pre-fill BTC's 15m quota
        tracker.record("BTC", now)
        tracker.record("BTC", now)

        signal = _make_signal("BTC", p_forecast=0.70, edge_bps=200.0)
        approved = apply_15m_conservative_gates([signal], config=cfg, now=now)
        assert len(approved) == 0

    def test_global_hard_cap_enforced(self) -> None:
        tracker, _ = _fresh_state()
        cfg = _cfg(global_max_trades_per_hour=5, per_asset_max_per_15m=10)
        now = datetime.now(timezone.utc)

        # Fill the hard cap
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            tracker.record(asset, now)

        signal = _make_signal("BTC", p_forecast=0.90, edge_bps=500.0)
        approved = apply_15m_conservative_gates([signal], config=cfg, now=now)
        assert len(approved) == 0

    def test_highest_p_approved_first_when_cap_near(self) -> None:
        tracker, _ = _fresh_state()
        cfg = _cfg(
            global_max_trades_per_hour=1,  # only one slot left
            per_asset_max_per_15m=5,
            min_p=0.64,
        )
        now = datetime.now(timezone.utc)

        signals = [
            _make_signal("BTC", p_forecast=0.65, edge_bps=150.0),
            _make_signal("ETH", p_forecast=0.80, edge_bps=300.0),  # highest p
            _make_signal("SOL", p_forecast=0.70, edge_bps=200.0),
        ]
        approved = apply_15m_conservative_gates(signals, config=cfg, now=now)
        assert len(approved) == 1
        assert approved[0].raw.asset == "ETH"  # highest p wins


class TestRateTighteningIntegration:
    def test_rate_tightening_raises_effective_min_p(self) -> None:
        tracker, _ = _fresh_state()
        cfg = _cfg(
            min_p=0.64,
            soft_target_trades_per_hour=2,
            global_max_trades_per_hour=30,
            per_asset_max_per_15m=10,
            rate_tighten_delta=0.01,
        )
        now = datetime.now(timezone.utc)
        # Add 4 trades → 2 over soft → incr = 0.02 → effective min_p = 0.66
        for _ in range(4):
            tracker.record("BTC", now)

        # p=0.65 < effective 0.66 → rejected
        signal_low = _make_signal("BTC", p_forecast=0.65, edge_bps=200.0)
        approved_low = apply_15m_conservative_gates([signal_low], config=cfg, now=now)
        assert len(approved_low) == 0

        # p=0.67 > effective 0.66 → approved
        signal_high = _make_signal("BTC", p_forecast=0.67, edge_bps=200.0)
        approved_high = apply_15m_conservative_gates([signal_high], config=cfg, now=now)
        assert len(approved_high) == 1


class TestApprovedSignalStructure:
    def test_approved_signal_has_expected_fields(self) -> None:
        _fresh_state()
        cfg = _cfg(min_p=0.64, min_edge_bps=50)
        now = datetime.now(timezone.utc)
        signal = _make_signal("BTC", p_forecast=0.70, edge_bps=200.0)
        approved = apply_15m_conservative_gates([signal], config=cfg, now=now)
        assert len(approved) == 1
        a = approved[0]
        assert isinstance(a, ApprovedSignal)
        assert a.raw is signal
        assert a.final_p == signal.p_forecast
        assert a.final_edge_bps == signal.edge_bps
        assert len(a.gates_passed) > 0
        d = a.to_dict()
        assert d["asset"] == "BTC"
        assert d["direction"] == "YES"


class TestIntegrationSyntheticBatch:
    """End-to-end: simulate a realistic batch of signals from 5 assets.

    Goal: with strong synthetic setups, ~10–15 should be approved per
    60-minute horizon without exceeding the global cap.
    """

    def test_synthetic_batch_within_rate_bounds(self) -> None:
        _fresh_state()
        cfg = _cfg(
            min_p=0.64,
            min_p_satellite=0.66,
            min_edge_bps=50,
            soft_target_trades_per_hour=15,
            global_max_trades_per_hour=30,
            per_asset_max_per_15m=3,
        )
        now = datetime.now(timezone.utc)

        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        signals: List[RawSignal] = []
        for asset in assets:
            min_p_asset = 0.66 if asset in ("SOL", "XRP", "DOGE") else 0.64
            for i in range(4):
                p = min_p_asset + 0.01 + i * 0.01  # ranges from min_p+0.01 to min_p+0.04
                signals.append(_make_signal(
                    asset=asset,
                    p_forecast=p,
                    edge_bps=200.0 + i * 50,
                    htf_alignment=0.60 + i * 0.05,
                ))

        approved = apply_15m_conservative_gates(signals, config=cfg, now=now)

        # Should approve some signals (we have 20 signals with p > min_p)
        assert len(approved) > 0
        # Should not exceed global hard cap
        assert len(approved) <= cfg.global_max_trades_per_hour
        # Should not have more than per_asset_max_per_15m per asset
        asset_counts: Dict[str, int] = {}
        for a in approved:
            asset_counts[a.raw.asset] = asset_counts.get(a.raw.asset, 0) + 1
        for asset, count in asset_counts.items():
            assert count <= cfg.per_asset_max_per_15m, (
                f"{asset} got {count} approved > cap {cfg.per_asset_max_per_15m}"
            )

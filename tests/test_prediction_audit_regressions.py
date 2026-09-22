"""test_prediction_audit_regressions.py

LEGACY: This module tests PaperSession and PaperLadder, which are not used by kalshi_crypto_15m_v2 profile.
The lean 15m stack uses live bankroll service (merid.event_venues.kalshi.bankroll_service_v2).

Regression tests for all bugs fixed in the Prediction Module Audit.

Bug IDs map to the audit report tickets:
  BUG-01  Wire PaperLadder tier → PredictionRiskConfig notional caps
  BUG-02  Per-agent notional enforcement in check_order()
  BUG-03  Link PaperLadder + PaperSession into single paper→live gate
  BUG-04  Enforce cutoff_minutes_before_expiry >= 0 (changed from >= 2)
  BUG-05  Fix arb side='both' to place both YES and NO legs
  BUG-06  Deduct fees from realized PnL in record_close()
  BUG-07  Settlement price override in record_close() for SETTLED_YES/NO
  BUG-08  _resolve_markets loops all config.assets
  BUG-09  StopLossRules equity from ladder, not hardcoded $5K
  BUG-10  Post-fee edge formula branches on YES vs NO side
  BUG-11  _sentiment_size_multiplier full range (0.35–1.5), not capped at 1.0
"""
from __future__ import annotations

import ast
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.legacy

ROOT = Path(__file__).resolve().parent.parent

PAPER_LADDER_SRC   = ROOT / "merid" / "paper_ladder.py"
RISK_SRC           = ROOT / "merid" / "prediction" / "risk.py"
PAPER_SESSION_SRC  = ROOT / "merid" / "prediction" / "paper_session.py"
AGENT_GRID_CFG_SRC = ROOT / "merid" / "prediction" / "agent_grid_config.py"
TRADING_AGENT_SRC  = ROOT / "merid" / "prediction" / "trading_agent.py"
STOP_LOSS_SRC      = ROOT / "merid" / "event_venues" / "kalshi" / "stop_loss.py"
STRATEGY_SRC       = ROOT / "merid" / "prediction" / "strategy.py"


def _src(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# =============================================================================
# BUG-01 — PaperLadder tier changes wire to PredictionRiskConfig
# =============================================================================

class TestBUG01_LadderTierRiskCaps:

    def test_apply_risk_caps_method_exists(self):
        src = _src(PAPER_LADDER_SRC)
        assert "def _apply_risk_caps" in src, (
            "BUG-01: _apply_risk_caps method not found in paper_ladder.py"
        )

    def test_apply_risk_caps_called_on_seed(self):
        src = _src(PAPER_LADDER_SRC)
        # Find seed_portfolio body and check _apply_risk_caps is called
        assert src.count("self._apply_risk_caps(") >= 3, (
            "BUG-01: _apply_risk_caps must be called from seed, promote, and demote "
            f"(found {src.count('self._apply_risk_caps(')} calls)"
        )

    def test_apply_risk_caps_sets_total_notional(self):
        src = _src(PAPER_LADDER_SRC)
        assert "max_total_notional_usd" in src, (
            "BUG-01: max_total_notional_usd not updated in _apply_risk_caps"
        )

    def test_apply_risk_caps_sets_per_market_notional(self):
        src = _src(PAPER_LADDER_SRC)
        assert "max_notional_per_market_usd" in src, (
            "BUG-01: max_notional_per_market_usd not updated in _apply_risk_caps"
        )

    def test_apply_risk_caps_sets_daily_loss(self):
        src = _src(PAPER_LADDER_SRC)
        assert "max_daily_loss_usd" in src, (
            "BUG-01: max_daily_loss_usd not updated in _apply_risk_caps"
        )



# =============================================================================
# BUG-02 — Per-agent notional enforcement in check_order()
# =============================================================================

class TestBUG02_PerAgentNotionalEnforcement:


    def test_check_order_rejects_when_order_exceeds_agent_cap(self):
        from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig
        cfg = PredictionRiskConfig(
            max_notional_per_market_usd=Decimal("10000"),
            max_total_notional_usd=Decimal("50000"),
        )
        risk = PredictionMarketRisk(cfg)
        # Order notional = 10 * 60c = $6.00, agent cap = $5.00 → reject/reduce
        check = risk.check_order(
            market_id="TEST-ARB-1",
            event_id="EV-1",
            side="yes",
            contracts=10,
            price_cents=Decimal("60"),
            agent_max_notional_usd=Decimal("5.00"),
        )
        assert not check.allowed, (
            "BUG-02: order exceeding agent notional cap should be rejected"
        )

    def test_check_order_allows_when_under_agent_cap(self):
        from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig
        cfg = PredictionRiskConfig(
            max_notional_per_market_usd=Decimal("10000"),
            max_total_notional_usd=Decimal("50000"),
        )
        risk = PredictionMarketRisk(cfg)
        # Order notional = 5 * 50c = $2.50, agent cap = $10.00 → allowed
        check = risk.check_order(
            market_id="TEST-ARB-2",
            event_id="EV-2",
            side="yes",
            contracts=5,
            price_cents=Decimal("50"),
            agent_max_notional_usd=Decimal("10.00"),
        )
        assert check.allowed, (
            "BUG-02: order within agent notional cap should be allowed"
        )

    def test_adjusted_size_computed_on_reduce(self):
        from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig
        cfg = PredictionRiskConfig(
            max_notional_per_market_usd=Decimal("100000"),
            max_total_notional_usd=Decimal("500000"),
        )
        risk = PredictionMarketRisk(cfg)
        # Order: 20 contracts @ 50¢ = $10, cap = $5 → expect adjusted_size=10
        check = risk.check_order(
            market_id="TEST-ARB-3",
            event_id="EV-3",
            side="yes",
            contracts=20,
            price_cents=Decimal("50"),
            agent_max_notional_usd=Decimal("5.00"),
        )
        assert not check.allowed
        assert check.adjusted_size is not None and check.adjusted_size > 0, (
            "BUG-02: adjusted_size should be set when agent cap is breached"
        )



# =============================================================================
# BUG-03 — PaperLadder + PaperSession single paper→live gate
# =============================================================================



# =============================================================================
# BUG-04 — cutoff_minutes_before_expiry >= 0 enforced (changed from >= 2)
# =============================================================================

class TestBUG04_CutoffMinimum:

    def test_min_cutoff_constant_exists(self):
        src = _src(AGENT_GRID_CFG_SRC)
        assert "_MIN_CUTOFF_MINUTES" in src, (
            "BUG-04: _MIN_CUTOFF_MINUTES constant not found in agent_grid_config.py"
        )

    def test_min_cutoff_value_is_0(self):
        import os
        import importlib
        # Clear environment variable to test default
        original_value = os.environ.pop("SCALPER15M_MIN_CUTOFF_MINUTES", None)
        try:
            # Reload module to pick up change
            import merid.prediction.agent_grid_config
            importlib.reload(merid.prediction.agent_grid_config)
            from merid.prediction.agent_grid_config import _MIN_CUTOFF_MINUTES
            # The default in code is 0, but environment may override
            # This test verifies the default is 0 when env var is not set
            assert _MIN_CUTOFF_MINUTES == 0, (
                f"BUG-04: _MIN_CUTOFF_MINUTES should be 0 when env var not set, got {_MIN_CUTOFF_MINUTES}"
            )
        finally:
            # Restore original value
            if original_value is not None:
                os.environ["SCALPER15M_MIN_CUTOFF_MINUTES"] = original_value

    def test_parse_entry_window_allows_cutoff_0(self):
        from merid.prediction.agent_grid_config import _parse_entry_window
        ew = _parse_entry_window({"minutes_before_expiry": 10, "cutoff_minutes_before_expiry": 0})
        assert ew.cutoff_minutes_before_expiry == 0, (
            f"BUG-04: cutoff=0 should be allowed, got {ew.cutoff_minutes_before_expiry}"
        )

    def test_parse_entry_window_allows_cutoff_1(self):
        from merid.prediction.agent_grid_config import _parse_entry_window
        ew = _parse_entry_window({"minutes_before_expiry": 5, "cutoff_minutes_before_expiry": 1})
        assert ew.cutoff_minutes_before_expiry == 1, (
            f"BUG-04: cutoff=1 should be allowed, got {ew.cutoff_minutes_before_expiry}"
        )

    def test_parse_entry_window_preserves_cutoff_above_0(self):
        from merid.prediction.agent_grid_config import _parse_entry_window
        ew = _parse_entry_window({"minutes_before_expiry": 30, "cutoff_minutes_before_expiry": 5})
        assert ew.cutoff_minutes_before_expiry == 5, (
            f"BUG-04: cutoff=5 should be preserved, got {ew.cutoff_minutes_before_expiry}"
        )

    def test_parse_entry_window_default_is_0(self):
        from merid.prediction.agent_grid_config import _parse_entry_window
        ew = _parse_entry_window({})
        assert ew.cutoff_minutes_before_expiry == 0, (
            f"BUG-04: default cutoff should be 0, got {ew.cutoff_minutes_before_expiry}"
        )


# =============================================================================
# BUG-05 — Arb side='both' places YES and NO legs
# =============================================================================



# =============================================================================
# BUG-06 — Fees deducted from realized PnL in record_close()
# =============================================================================

class TestBUG06_FeesDeductedFromPnL:




    def test_record_close_fee_deduction_runtime(self):
        from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig
        cfg = PredictionRiskConfig()
        risk = PredictionMarketRisk(cfg)

        # Open 10 contracts @ 50¢ → notional $5
        risk.record_fill(
            market_id="FEE-TEST-1",
            event_id="EV-FEE",
            side="yes",
            contracts=10,
            price_cents=Decimal("50"),
        )
        # Close all @ 70¢ with $0.20 fee
        risk.record_close(
            market_id="FEE-TEST-1",
            contracts=10,
            exit_price_cents=Decimal("70"),
            fee_cents=Decimal("20"),  # 20¢ = $0.20
        )
        today = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%d")
        daily = risk._daily_pnl.get(today)
        assert daily is not None
        # Gross PnL = (70-50)*10 / 100 = $2.00; fee = $0.20; net = $1.80
        expected = Decimal("1.80")
        assert daily.realized_pnl_usd == expected, (
            f"BUG-06: expected net PnL $1.80 after fees, got {daily.realized_pnl_usd}"
        )


# =============================================================================
# BUG-07 — Settlement price override in record_close()
# =============================================================================

class TestBUG07_SettlementPriceOverride:





    def test_settled_yes_pnl_runtime(self):
        """Closing YES at settlement=yes should yield (100-entry)*contracts/100."""
        from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig
        cfg = PredictionRiskConfig()
        risk = PredictionMarketRisk(cfg)

        risk.record_fill(
            market_id="SET-YES-1",
            event_id="EV-SET",
            side="yes",
            contracts=5,
            price_cents=Decimal("60"),
        )
        risk.record_close(
            market_id="SET-YES-1",
            contracts=5,
            exit_price_cents=Decimal("55"),  # ignored — outcome overrides
            outcome="yes",
        )
        today = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%d")
        daily = risk._daily_pnl[today]
        # (100-60)*5 / 100 = $2.00
        assert daily.realized_pnl_usd == Decimal("2.00"), (
            f"BUG-07: SETTLED_YES PnL should be $2.00, got {daily.realized_pnl_usd}"
        )

    def test_settled_no_pnl_runtime(self):
        """Closing YES at settlement=no should yield (0-entry)*contracts/100 = loss."""
        from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig
        cfg = PredictionRiskConfig()
        risk = PredictionMarketRisk(cfg)

        risk.record_fill(
            market_id="SET-NO-1",
            event_id="EV-SET-NO",
            side="yes",
            contracts=5,
            price_cents=Decimal("60"),
        )
        risk.record_close(
            market_id="SET-NO-1",
            contracts=5,
            exit_price_cents=Decimal("65"),  # ignored
            outcome="no",
        )
        today = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%d")
        daily = risk._daily_pnl[today]
        # (0-60)*5 / 100 = -$3.00
        assert daily.realized_pnl_usd == Decimal("-3.00"), (
            f"BUG-07: SETTLED_NO PnL should be -$3.00, got {daily.realized_pnl_usd}"
        )


# =============================================================================
# BUG-08 — _resolve_markets loops all config.assets
# =============================================================================



# =============================================================================
# BUG-09 — StopLossRules equity from ladder, not hardcoded $5K
# =============================================================================



# =============================================================================
# BUG-10 — Post-fee edge formula branches on YES vs NO side
# =============================================================================

class TestBUG10_PostFeeEdgeFormula:




    def test_no_side_edge_check_uses_correct_denominator(self):
        """Edge formula for NO side must use price_cents as denominator."""
        from merid.prediction.risk import PredictionMarketRisk, PredictionRiskConfig
        cfg = PredictionRiskConfig(
            max_notional_per_market_usd=Decimal("10000"),
            max_total_notional_usd=Decimal("50000"),
        )
        risk = PredictionMarketRisk(cfg)
        # A very thin edge on a NO buy at 95¢ — with old formula (100-95=5) the
        # fee drag would swamp a 2% edge; with correct formula (95) it should pass.
        check = risk.check_order(
            market_id="EDGE-NO-1",
            event_id="EV-EDGE",
            side="no",
            contracts=1,
            price_cents=Decimal("95"),
            edge=Decimal("0.05"),  # 5% net edge, should pass at 95¢ NO
        )
        # With old formula: payout=5¢, fee~2¢, fee_per/payout = 0.4 → post_fee = 0.05-0.4 < 0.01 → REJECT
        # With correct formula: payout=95¢, fee~2¢, fee_per/payout ≈ 0.021 → post_fee ≈ 0.029 > 0.01 → ALLOW
        assert check.allowed, (
            "BUG-10: NO side buy with 5% edge at 95¢ should pass post-fee check "
            "(correct payout denominator = price_cents = 95)"
        )


# =============================================================================
# BUG-11 — _sentiment_size_multiplier full range 0.35–1.5 (not capped at 1.0)
# =============================================================================

class TestBUG11_SentimentMultiplierRange:

    def test_min_cap_is_035_in_contrarian(self):
        src = _src(STRATEGY_SRC)
        # Lines that apply the sentiment multiplier must use min(1.5, float(mult))
        # (not the kelly_size or vol_breakout lines which use size_factor directly)
        mult_lines = [l for l in src.splitlines() if "float(mult)" in l and "size_factor" in l]
        assert mult_lines, "BUG-11: no 'size_factor = max(...min(...float(mult)))' lines found"
        for line in mult_lines:
            assert "min(1.5" in line, (
                f"BUG-11: size_factor clamp should be min(1.5,...), got: {line.strip()}"
            )

    def test_multiplier_max_is_15_not_10(self):
        src = _src(STRATEGY_SRC)
        assert "min(1.5, float(mult))" in src, (
            "BUG-11: 'min(1.5, float(mult))' not found — multiplier still capped at 1.0"
        )
        assert "min(1.0, float(mult))" not in src, (
            "BUG-11: old 'min(1.0, float(mult))' cap still present"
        )

    def test_extreme_fear_buy_yes_returns_13(self):
        from merid.prediction.strategy import KalshiStrategy, StrategyConfig, SignalAction

        cfg = StrategyConfig()
        strat = KalshiStrategy(cfg)

        snap = MagicMock()
        snap.sentiment_regime = "extreme_fear"
        mult = strat._sentiment_size_multiplier(snap, SignalAction.BUY_YES)
        assert mult == Decimal("1.3"), (
            f"BUG-11: extreme_fear + BUY_YES should return 1.3×, got {mult}"
        )

    def test_extreme_greed_buy_yes_returns_06(self):
        from merid.prediction.strategy import KalshiStrategy, StrategyConfig, SignalAction

        cfg = StrategyConfig()
        strat = KalshiStrategy(cfg)

        snap = MagicMock()
        snap.sentiment_regime = "extreme_greed"
        mult = strat._sentiment_size_multiplier(snap, SignalAction.BUY_YES)
        assert mult == Decimal("0.6"), (
            f"BUG-11: extreme_greed + BUY_YES should return 0.6×, got {mult}"
        )

    def test_size_factor_allows_boost_above_1(self):
        """size_factor must be able to exceed 1.0 after the fix."""
        from merid.prediction.strategy import KalshiStrategy, StrategyConfig, SignalAction

        cfg = StrategyConfig()
        strat = KalshiStrategy(cfg)

        snap = MagicMock()
        snap.sentiment_regime = "extreme_fear"

        mult = strat._sentiment_size_multiplier(snap, SignalAction.BUY_YES)  # 1.3
        size_factor = max(0.35, min(1.5, float(mult)))
        assert size_factor > 1.0, (
            f"BUG-11: size_factor with 1.3× mult should exceed 1.0, got {size_factor}"
        )


# =============================================================================
# BUG-L1 — PortfolioRiskAgent readiness gate before trading agents start
# =============================================================================

class TestBUGL1_PortfolioRiskReadinessGate:

    def test_ready_event_exists(self):
        src = _src(ROOT / "merid" / "prediction" / "portfolio_risk_agent.py")
        assert "_ready_event" in src, (
            "BUG-L1: _ready_event not found in portfolio_risk_agent.py"
        )

    def test_wait_ready_method_exists(self):
        src = _src(ROOT / "merid" / "prediction" / "portfolio_risk_agent.py")
        assert "async def wait_ready" in src, (
            "BUG-L1: wait_ready() method not found in portfolio_risk_agent.py"
        )

    def test_is_ready_property_exists(self):
        src = _src(ROOT / "merid" / "prediction" / "portfolio_risk_agent.py")
        assert "def is_ready" in src, (
            "BUG-L1: is_ready property not found in portfolio_risk_agent.py"
        )

    def test_ready_event_set_after_snapshot(self):
        src = _src(ROOT / "merid" / "prediction" / "portfolio_risk_agent.py")
        assert "_ready_event.set()" in src, (
            "BUG-L1: _ready_event.set() not called after first portfolio snapshot"
        )


    def test_ready_event_set_on_stop(self):
        """stop() must set _ready_event so waiters don't hang on shutdown."""
        src = _src(ROOT / "merid" / "prediction" / "portfolio_risk_agent.py")
        # Ensure set() is called in stop() as well as in _check_portfolio
        assert src.count("_ready_event.set()") >= 2, (
            "BUG-L1: _ready_event.set() must be called in both stop() and _check_portfolio()"
        )

    @pytest.mark.asyncio
    async def test_wait_ready_returns_false_on_timeout(self):
        """wait_ready(timeout=0.01) returns False when loop never sets event."""
        from merid.prediction.portfolio_risk_agent import PortfolioRiskAgent, PortfolioRiskConfig
        agent = PortfolioRiskAgent(PortfolioRiskConfig())
        result = await agent.wait_ready(timeout=0.01)
        assert result is False, "BUG-L1: wait_ready should return False on timeout"

    @pytest.mark.asyncio
    async def test_wait_ready_returns_true_when_event_set(self):
        from merid.prediction.portfolio_risk_agent import PortfolioRiskAgent, PortfolioRiskConfig
        agent = PortfolioRiskAgent(PortfolioRiskConfig())
        agent._ready_event.set()
        result = await agent.wait_ready(timeout=1.0)
        assert result is True, "BUG-L1: wait_ready should return True when event is set"


# =============================================================================
# BUG-L2 — Idempotent start(): _running set only after task created
# =============================================================================

class TestBUGL2_IdempotentStart:

    def test_running_set_after_task_in_portfolio_risk(self):
        """_running = True must come AFTER asyncio.create_task() in portfolio_risk_agent."""
        src = _src(ROOT / "merid" / "prediction" / "portfolio_risk_agent.py")
        lines = src.splitlines()
        # create_task is on its own line; _run_loop() is on the next line
        task_line = next(
            (i for i, l in enumerate(lines) if "asyncio.create_task(" in l),
            None,
        )
        running_line = next(
            (i for i, l in enumerate(lines) if "self._running = True" in l),
            None,
        )
        assert task_line is not None, "BUG-L2: asyncio.create_task() not found in portfolio_risk_agent"
        assert running_line is not None, "BUG-L2: _running = True not found in portfolio_risk_agent"
        assert running_line > task_line, (
            f"BUG-L2: _running=True (line {running_line}) must come after create_task (line {task_line})"
        )

    def test_running_set_at_end_of_orchestrator_start(self):
        """OrchestratorAgentManager.start_all() must set self.running=True only at the end."""
        src = _src(ROOT / "web" / "startup_agents.py")
        lines = src.splitlines()
        # Find start_all def
        start_idx = next(i for i, l in enumerate(lines) if "async def start_all" in l)
        # Find next method def after start_all
        next_def = next(
            (i for i, l in enumerate(lines) if i > start_idx and l.strip().startswith("async def ")),
            len(lines),
        )
        start_all_body = lines[start_idx:next_def]
        running_true_lines = [i for i, l in enumerate(start_all_body) if "self.running = True" in l]
        assert running_true_lines, "BUG-L2: self.running = True not set in start_all()"
        # Ensure it's near the end — after at least 50% of the method body
        last_running_line = running_true_lines[-1]
        assert last_running_line > len(start_all_body) // 2, (
            "BUG-L2: self.running = True should be set near the END of start_all(), not at the top"
        )


# =============================================================================
# BUG-L3 — Position sync at startup
# =============================================================================



# =============================================================================
# BUG-L4 — Consensus quorum uses live healthy-agent count
# =============================================================================

class TestBUGL4_DynamicConsensusQuorum:
    CONSENSUS_SRC = ROOT / "consensus" / "consensus_coordinator.py"





    def test_effective_quorum_fallback_to_config(self):
        """With no registered agents, effective_quorum falls back to config minimum."""
        # LEGACY REMOVAL: Consensus module deleted - test disabled
        # from consensus.consensus_coordinator import EnhancedConsensusCoordinator, ConsensusConfig
        # # Use a fresh instance
        # cc = EnhancedConsensusCoordinator(ConsensusConfig(min_agents_for_quorum=3))
        # assert cc.effective_quorum == 3, (
        #     f"BUG-L4: with no agents, effective_quorum should be 3 (config min), got {cc.effective_quorum}"
        # )
        self.skipTest("Consensus module deleted")

    def test_effective_quorum_scales_with_healthy_agents(self):
        """With 10 healthy agents and 60% quorum_pct, effective_quorum == max(3, ceil(6)) == 6."""
        # LEGACY REMOVAL: Consensus module deleted - test disabled
        # import math
        # from consensus.consensus_coordinator import EnhancedConsensusCoordinator, ConsensusConfig, AgentHeartbeat
        # cc = EnhancedConsensusCoordinator(ConsensusConfig(min_agents_for_quorum=3, quorum_percentage=0.6))
        # for i in range(10):
        #     hb = AgentHeartbeat(agent_id=f"agent-{i}", agent_role="trader")
        #     hb.is_healthy = True
        #     cc._agent_heartbeats[f"agent-{i}"] = hb
        # expected = max(3, math.ceil(10 * 0.6))  # 6
        # assert cc.effective_quorum == expected, (
        #     f"BUG-L4: with 10 healthy agents expected quorum={expected}, got {cc.effective_quorum}"
        # )
        self.skipTest("Consensus module deleted")

    def test_clear_stale_opinions_purges_old(self):
        """clear_stale_opinions removes entries older than max_age_s."""
        # LEGACY REMOVAL: Consensus module deleted - test disabled
        # import time
        # from consensus.consensus_coordinator import EnhancedConsensusCoordinator, ConsensusConfig
        # from unittest.mock import MagicMock
        # cc = EnhancedConsensusCoordinator(ConsensusConfig())
        # old_op = MagicMock()
        # old_op.timestamp = time.time() - 120  # 2 min old
        # fresh_op = MagicMock()
        # fresh_op.timestamp = time.time() - 5   # 5 sec old
        # cc._pending_opinions["BTC"] = [old_op, fresh_op]
        # purged = cc.clear_stale_opinions(max_age_s=60.0)
        # assert purged == 1, f"BUG-L4: expected 1 purged, got {purged}"
        # assert len(cc._pending_opinions["BTC"]) == 1, "BUG-L4: fresh opinion must survive purge"
        self.skipTest("Consensus module deleted")



def _make_coro(result):
    """Helper: create a coroutine that returns result."""
    async def _coro():
        return result
    return _coro()


# =============================================================================
# BUG-L6 — Shield mid-order placement from hard task cancellation
# =============================================================================



# =============================================================================
# BUG-L7 — Single-owner shutdown: no triple-stop race
# =============================================================================

class TestBUGL7_SingleOwnerShutdown:
    MAIN_SRC = ROOT / "web" / "main.py"

    def test_shutdown_comment_present(self):
        src = _src(self.MAIN_SRC)
        assert "BUG-L7" in src, (
            "BUG-L7: BUG-L7 comment not found in main.py shutdown section"
        )

    def test_orchestrator_manager_stop_called_once(self):
        src = _src(self.MAIN_SRC)
        yield_idx = src.index("yield")
        shutdown_section = src[yield_idx:]
        # Count only actual call sites — exclude comment lines and def lines
        call_count = sum(
            1 for line in shutdown_section.splitlines()
            if "stop_all()" in line
            and "def " not in line
            and not line.strip().startswith("#")
        )
        assert call_count == 1, (
            f"BUG-L7: stop_all() should be called exactly once in shutdown, found {call_count} times"
        )

    def test_grid_stop_called_once_in_lifespan_shutdown(self):
        src = _src(self.MAIN_SRC)
        yield_idx = src.index("yield")
        shutdown_section = src[yield_idx:]
        # Exclude comment lines
        count = sum(
            1 for line in shutdown_section.splitlines()
            if "grid.stop()" in line and not line.strip().startswith("#")
        )
        assert count <= 1, (
            f"BUG-L7: grid.stop() should appear at most once in lifespan shutdown, got {count}"
        )


# =============================================================================
# BUG-L8 — WARMING_UP state + safe mode + stale opinion purge on restart
# =============================================================================



# =============================================================================
# MED — Medium-risk fixes
# =============================================================================

class TestMediumRiskFixes:





    def test_canonical_agent_error_count_reset_on_success(self):
        src = _src(ROOT / "merid" / "agents" / "base.py")
        assert "self._error_count = 0" in src, (
            "MED: CanonicalAgent._error_count must reset to 0 on successful run"
        )

    def test_canonical_agent_auto_retires_after_max_errors(self):
        src = _src(ROOT / "merid" / "agents" / "base.py")
        assert "_MAX_CANONICAL_CONSECUTIVE_ERRORS" in src, (
            "MED: _MAX_CANONICAL_CONSECUTIVE_ERRORS not defined in base.py"
        )
        assert "AgentStatus.RETIRED" in src, (
            "MED: agent must auto-retire after max consecutive errors"
        )

    def test_gather_uses_return_exceptions_in_loop(self):
        src = _src(ROOT / "merid" / "loop.py")
        assert "return_exceptions=True" in src, (
            "MED: asyncio.gather in _run_agent_cycles must use return_exceptions=True"
        )


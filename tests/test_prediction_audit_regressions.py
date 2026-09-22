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

    def test_apply_risk_caps_runtime(self):
        """Unit: _apply_risk_caps updates get_prediction_risk().config caps."""
        import merid.prediction.risk as risk_mod
        from merid.paper_ladder import PaperLadder, LadderTier
        from merid.prediction.risk import PredictionRiskConfig

        original_risk = risk_mod._risk
        try:
            cfg = PredictionRiskConfig()
            risk_mod._risk = risk_mod.PredictionMarketRisk(cfg)

            tier = LadderTier(
                level=1,
                name="Rookie",
                seed_usd=2_000.0,
                profit_target_pct=15.0,
                max_drawdown_pct=8.0,
                min_trades=30,
                min_win_rate_pct=52.0,
            )
            ladder = PaperLadder.__new__(PaperLadder)
            ladder._apply_risk_caps(tier)

            r = risk_mod._risk
            assert float(r.config.max_total_notional_usd) == pytest.approx(1_000.0), (
                "BUG-01: total notional cap should be seed * 0.5 = 1000"
            )
            assert float(r.config.max_notional_per_market_usd) == pytest.approx(100.0), (
                "BUG-01: per-market cap should be seed * 0.05 = 100"
            )
        finally:
            risk_mod._risk = original_risk


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

"""
KalshiBotLifecycle — state machine gating paper → live deployment.

States (in order):
    BACKTEST        → running/validating backtest + Monte Carlo
    FORWARD_PAPER   → paper trading on live data; ForwardTester accumulating
    LIVE_RESTRICTED → live, conservative risk (1% base)
    LIVE_NORMAL     → live, normal risk (2% base)

Transitions:
    BACKTEST      --[backtest ok + MC ok]--> FORWARD_PAPER
    FORWARD_PAPER --[ForwardTester.is_valid]--> LIVE_RESTRICTED
    LIVE_RESTRICTED --[PromotionEngine PHASE_2+]--> LIVE_NORMAL

The global TradeMode is always the final kill switch; lifecycle only
controls per-lane paper_mode and base risk fraction.

Usage:
    lifecycle = KalshiBotLifecycle()
    # after backtest:
    lifecycle.on_backtest_complete(report, mc_metrics)
    # each forward cycle:
    lifecycle.on_forward_update(forward_tracker.get_stats())
    # in risk engine:
    profile = lifecycle.get_risk_profile()
    # profile["mode"] in ("paper", "live")
    # profile["risk_frac"] is the base fraction for dynamic_size()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# State enum
# ---------------------------------------------------------------------------

class BotState(Enum):
    BACKTEST         = auto()   # validating backtest + MC
    FORWARD_PAPER    = auto()   # paper on live data
    LIVE_RESTRICTED  = auto()   # live, 1% base risk
    LIVE_NORMAL      = auto()   # live, 2% base risk


# ---------------------------------------------------------------------------
# Transition log entry
# ---------------------------------------------------------------------------

@dataclass
class StateTransition:
    from_state: BotState
    to_state: BotState
    reason: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

class KalshiBotLifecycle:
    """
    State machine for the full backtest → forward → live deployment pipeline.

    Thread-safe for read; writes should be from a single async task.
    """

    # Risk profiles per state
    _RISK_PROFILES: Dict[BotState, Dict] = {
        BotState.BACKTEST:        {"mode": "paper", "risk_frac": 0.0},
        BotState.FORWARD_PAPER:   {"mode": "paper", "risk_frac": 0.0},
        BotState.LIVE_RESTRICTED: {"mode": "live",  "risk_frac": 0.01},
        BotState.LIVE_NORMAL:     {"mode": "live",  "risk_frac": 0.02},
    }

    def __init__(self) -> None:
        self.state: BotState = BotState.BACKTEST
        self._history: List[StateTransition] = []
        self._last_backtest_result: Optional[Dict] = None
        self._last_mc_metrics: Optional[Dict] = None
        self._last_forward_check: Optional[Dict] = None

    # ── Transitions ───────────────────────────────────────────────────────

    def on_backtest_complete(
        self,
        bt_report,
        mc_metrics: Dict,
        min_p5: float = 0.90,
        max_prob_loss: float = 0.50,
    ) -> Dict:
        """
        Called after run_backtest_2y() + monte_carlo_risk_metrics().

        Advances BACKTEST → FORWARD_PAPER if both gates pass.
        Returns {"ok": bool, "reason": str}.
        """
        from merid.risk.btc_promotion_config import validate_before_lift

        bt_result = validate_before_lift(bt_report)
        self._last_backtest_result = bt_result
        self._last_mc_metrics = mc_metrics

        if not bt_result["ok"]:
            logger.warning(
                "KalshiBotLifecycle: backtest gate FAILED — %s (state stays %s)",
                bt_result["reason"], self.state.name,
            )
            return {"ok": False, "reason": f"backtest: {bt_result['reason']}"}

        if mc_metrics.get("p5", 0.0) < min_p5:
            reason = f"mc_p5={mc_metrics['p5']:.3f} < {min_p5}"
            logger.warning("KalshiBotLifecycle: MC gate FAILED — %s", reason)
            return {"ok": False, "reason": reason}

        if mc_metrics.get("prob_loss", 1.0) > max_prob_loss:
            reason = f"mc_prob_loss={mc_metrics['prob_loss']:.1%} > {max_prob_loss:.1%}"
            logger.warning("KalshiBotLifecycle: MC gate FAILED — %s", reason)
            return {"ok": False, "reason": reason}

        self._transition(BotState.FORWARD_PAPER, "backtest_and_mc_ok")
        return {"ok": True, "reason": "backtest_ok"}

    def on_forward_update(self, fwd_stats) -> Dict:
        """
        Called periodically with ForwardStats from ForwardTracker.

        Advances FORWARD_PAPER → LIVE_RESTRICTED when ForwardTester passes.
        Returns {"ok": bool, "reason": str, "advanced": bool}.
        """
        from merid.backtesting.forward_tester import ForwardTester

        if self.state != BotState.FORWARD_PAPER:
            return {"ok": True, "reason": "not_in_forward_paper", "advanced": False}

        tester = ForwardTester()
        passed, reason = tester.check(fwd_stats)
        self._last_forward_check = {"passed": passed, "reason": reason}

        if passed:
            self._transition(BotState.LIVE_RESTRICTED, f"forward_tester_ok: {reason}")
            return {"ok": True, "reason": reason, "advanced": True}

        logger.debug("KalshiBotLifecycle: forward gate not yet met — %s", reason)
        return {"ok": False, "reason": reason, "advanced": False}

    def maybe_upgrade_to_normal(self, phase_name: str) -> bool:
        """
        Advance LIVE_RESTRICTED → LIVE_NORMAL when PromotionEngine reaches PHASE_2+.
        Returns True if advanced.
        """
        if self.state != BotState.LIVE_RESTRICTED:
            return False
        # PHASE_2 and above unlock LIVE_NORMAL
        eligible_phases = {"PHASE_2", "PHASE_3"}
        if phase_name in eligible_phases:
            self._transition(BotState.LIVE_NORMAL, f"phase_upgrade: {phase_name}")
            return True
        return False

    def force_paper(self, reason: str = "manual") -> None:
        """Emergency reset to FORWARD_PAPER (e.g. after a kill switch fires)."""
        if self.state in (BotState.LIVE_RESTRICTED, BotState.LIVE_NORMAL):
            self._transition(BotState.FORWARD_PAPER, f"forced_paper: {reason}")

    # ── Risk profile ──────────────────────────────────────────────────────

    def get_risk_profile(self) -> Dict:
        """
        Returns {"mode": "paper"|"live", "risk_frac": float}.

        Combine risk_frac with ATR, FG clamps, and drawdown guard to get
        the final per-trade size.  TradeMode is the final global kill switch.
        """
        return dict(self._RISK_PROFILES[self.state])

    def is_paper(self) -> bool:
        return self._RISK_PROFILES[self.state]["mode"] == "paper"

    def is_live(self) -> bool:
        return not self.is_paper()

    # ── Observability ─────────────────────────────────────────────────────

    def get_status(self) -> Dict:
        return {
            "state": self.state.name,
            "risk_profile": self.get_risk_profile(),
            "last_backtest": self._last_backtest_result,
            "last_mc": self._last_mc_metrics,
            "last_forward_check": self._last_forward_check,
            "transitions": [
                {
                    "from": t.from_state.name,
                    "to": t.to_state.name,
                    "reason": t.reason,
                    "at": t.timestamp.isoformat(),
                }
                for t in self._history[-10:]  # last 10
            ],
        }

    # ── Internal ──────────────────────────────────────────────────────────

    def _transition(self, new_state: BotState, reason: str) -> None:
        old = self.state
        self.state = new_state
        entry = StateTransition(from_state=old, to_state=new_state, reason=reason)
        self._history.append(entry)
        logger.info(
            "🔄 KalshiBotLifecycle: %s → %s (%s)",
            old.name, new_state.name, reason,
        )
        # Telegram alert for every lifecycle transition
        try:
            import asyncio as _aio
            from merid.alerts.webhook_client import tg_send
            icon = "🟢" if new_state in (BotState.LIVE_RESTRICTED, BotState.LIVE_NORMAL) else "🔵"
            _aio.get_running_loop().create_task(tg_send(
                f"{icon} [KalshiBotLifecycle] <b>{old.name}</b> → <b>{new_state.name}</b>\n"
                f"Reason: {reason}"
            ))
        except RuntimeError:
            pass  # No running loop — Telegram skipped
        except Exception as _tg_exc:
            logger.debug("[bot_lifecycle] Telegram failed: %s", _tg_exc)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_lifecycle: Optional[KalshiBotLifecycle] = None


def get_bot_lifecycle() -> KalshiBotLifecycle:
    global _lifecycle
    if _lifecycle is None:
        _lifecycle = KalshiBotLifecycle()
    return _lifecycle

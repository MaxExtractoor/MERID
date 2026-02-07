"""
Reward Event Hooks — wires trading/risk/compliance events to XP awards.

Listens to key system events and awards XP through the GamificationEngine.
This bridges the gap between the existing gamification infrastructure and
actual system activity.

Usage:
    from core.reward_event_hooks import get_reward_hooks
    hooks = get_reward_hooks()
    hooks.on_trade_executed(user_id="agent-1", symbol="BTC/USDT", side="buy", notional=5000)
    hooks.on_risk_check_passed(user_id="agent-1")
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("core.reward_event_hooks")


@dataclass
class RewardEvent:
    """Recorded reward event for audit."""
    event_type: str
    user_id: str
    xp_awarded: int
    reason: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


# XP multipliers by event type
EVENT_XP_TABLE = {
    "trade_executed": 1.0,
    "trade_profitable": 2.0,
    "risk_check_passed": 0.5,
    "compliance_clean": 0.5,
    "consensus_vote": 0.3,
    "consensus_correct": 1.5,
    "kill_switch_test": 2.0,
    "bug_reported": 5.0,
    "bug_verified": 10.0,
    "streak_day": 1.0,
    "streak_week": 3.0,
    "first_trade": 3.0,
    "position_reconciled": 0.5,
    "drift_detected": 1.0,
    "halt_triggered": 2.0,
    "quest_completed": 4.0,
}


class RewardEventHooks:
    """Bridges system events to gamification XP awards."""

    def __init__(self, base_xp: int = 50):
        self._base_xp = base_xp
        self._events: List[RewardEvent] = []
        self._streak_tracker: Dict[str, float] = {}  # user_id -> last_active_ts
        self._daily_caps: Dict[str, int] = {}  # user_id -> xp_today
        self._max_daily_xp = 5000

    def _get_engine(self):
        from services.gamification import GamificationEngine
        if not hasattr(self, "_engine"):
            self._engine = GamificationEngine(base_xp=self._base_xp)
        return self._engine

    def _award(self, user_id: str, event_type: str, metadata: Dict[str, Any] = None) -> int:
        """Core award method with daily cap enforcement."""
        multiplier = EVENT_XP_TABLE.get(event_type, 1.0)
        engine = self._get_engine()

        # Daily cap check
        today_key = f"{user_id}:{int(time.time() // 86400)}"
        current_daily = self._daily_caps.get(today_key, 0)
        if current_daily >= self._max_daily_xp:
            logger.debug("Daily XP cap reached for %s", user_id)
            return 0

        xp = engine.award_xp(user_id, multiplier, event_type, metadata or {})
        self._daily_caps[today_key] = current_daily + xp

        event = RewardEvent(
            event_type=event_type,
            user_id=user_id,
            xp_awarded=xp,
            reason=event_type,
            metadata=metadata or {},
        )
        self._events.append(event)
        return xp

    # ── Trade Events ──────────────────────────────────────────────

    def on_trade_executed(
        self, user_id: str, symbol: str, side: str, notional: float, **kwargs
    ) -> int:
        """Award XP when a trade is executed."""
        meta = {"symbol": symbol, "side": side, "notional": str(notional), **{k: str(v) for k, v in kwargs.items()}}
        return self._award(user_id, "trade_executed", meta)

    def on_trade_profitable(
        self, user_id: str, symbol: str, pnl: float, **kwargs
    ) -> int:
        """Bonus XP for profitable trades."""
        meta = {"symbol": symbol, "pnl": str(pnl)}
        return self._award(user_id, "trade_profitable", meta)

    def on_first_trade(self, user_id: str) -> int:
        """One-time bonus for first trade."""
        return self._award(user_id, "first_trade", {"milestone": "first_trade"})

    # ── Risk & Compliance Events ──────────────────────────────────

    def on_risk_check_passed(self, user_id: str, check_name: str = "") -> int:
        """XP for passing risk checks cleanly."""
        return self._award(user_id, "risk_check_passed", {"check": check_name})

    def on_compliance_clean(self, user_id: str, report_id: str = "") -> int:
        """XP for clean compliance reports."""
        return self._award(user_id, "compliance_clean", {"report_id": report_id})

    # ── Consensus Events ──────────────────────────────────────────

    def on_consensus_vote(self, user_id: str, round_id: str = "") -> int:
        """XP for participating in consensus."""
        return self._award(user_id, "consensus_vote", {"round_id": round_id})

    def on_consensus_correct(self, user_id: str, round_id: str = "") -> int:
        """Bonus XP for voting with the winning consensus."""
        return self._award(user_id, "consensus_correct", {"round_id": round_id})

    # ── Safety Events ─────────────────────────────────────────────

    def on_kill_switch_test(self, user_id: str) -> int:
        """XP for testing the kill switch (safety drill)."""
        return self._award(user_id, "kill_switch_test", {"drill": "kill_switch"})

    def on_halt_triggered(self, user_id: str, reason: str = "") -> int:
        """XP for triggering a trading halt (safety action)."""
        return self._award(user_id, "halt_triggered", {"reason": reason})

    def on_drift_detected(self, user_id: str, drift_type: str = "") -> int:
        """XP for detecting drift."""
        return self._award(user_id, "drift_detected", {"drift_type": drift_type})

    # ── Security Events ───────────────────────────────────────────

    def on_bug_reported(self, user_id: str, report_id: str = "") -> int:
        """XP for reporting a bug."""
        return self._award(user_id, "bug_reported", {"report_id": report_id})

    def on_bug_verified(self, user_id: str, report_id: str = "", severity: str = "") -> int:
        """Major XP for verified bugs."""
        return self._award(user_id, "bug_verified", {"report_id": report_id, "severity": severity})

    # ── Streak Events ─────────────────────────────────────────────

    def on_daily_login(self, user_id: str) -> int:
        """Track daily activity streak and award XP."""
        now = time.time()
        last = self._streak_tracker.get(user_id, 0)
        self._streak_tracker[user_id] = now

        days_since = (now - last) / 86400 if last else 999
        if days_since < 2:
            # Continuing streak
            return self._award(user_id, "streak_day", {"days_since_last": str(round(days_since, 1))})
        return self._award(user_id, "streak_day", {"streak_reset": "true"})

    # ── Quest Events ──────────────────────────────────────────────

    def on_quest_completed(self, user_id: str, quest_id: str) -> int:
        """XP for completing a quest."""
        return self._award(user_id, "quest_completed", {"quest_id": quest_id})

    # ── Reconciliation Events ─────────────────────────────────────

    def on_position_reconciled(self, user_id: str) -> int:
        """XP for successful position reconciliation."""
        return self._award(user_id, "position_reconciled")

    # ── Summary ───────────────────────────────────────────────────

    def get_summary(self) -> Dict[str, Any]:
        """Get reward hooks summary."""
        by_type: Dict[str, int] = {}
        for e in self._events:
            by_type[e.event_type] = by_type.get(e.event_type, 0) + 1
        return {
            "total_events": len(self._events),
            "events_by_type": by_type,
            "unique_users": len(set(e.user_id for e in self._events)),
            "total_xp_awarded": sum(e.xp_awarded for e in self._events),
            "max_daily_xp": self._max_daily_xp,
        }

    def get_recent_events(self, limit: int = 50) -> List[Dict[str, Any]]:
        return [
            {
                "event_type": e.event_type,
                "user_id": e.user_id,
                "xp_awarded": e.xp_awarded,
                "timestamp": e.timestamp,
                "metadata": e.metadata,
            }
            for e in self._events[-limit:]
        ]


_hooks: Optional[RewardEventHooks] = None


def get_reward_hooks() -> RewardEventHooks:
    """Get or create the singleton RewardEventHooks."""
    global _hooks
    if _hooks is None:
        _hooks = RewardEventHooks()
    return _hooks

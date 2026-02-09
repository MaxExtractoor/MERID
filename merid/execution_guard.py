"""§H3 Execution Guard — CQI-based throttle, per-domain caps, kill switch.

Sits between the loop's plan approval and actual venue submission.
Every trade must pass through `guard.pre_trade_check(plan)` before execution.

Safety layers (checked in order):
  1. Global kill switch — blocks ALL execution
  2. Per-domain kill switch — blocks a single domain
  3. CQI throttle — shrinks or blocks trades when quality degrades
  4. Per-domain daily caps — max notional per domain per day
  5. Cooldown — min time between executions

Usage:
    guard = get_execution_guard()
    verdict = guard.pre_trade_check(plan, domain="crypto")
    if verdict.allowed:
        execute(plan, size=verdict.adjusted_size_usd)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.execution_guard")


# ── Verdict ───────────────────────────────────────────────────────────

@dataclass
class TradeVerdict:
    """Result of a pre-trade safety check."""
    allowed: bool
    reason: str
    original_size_usd: float = 0.0
    adjusted_size_usd: float = 0.0
    throttle_pct: float = 1.0       # 1.0 = full size, 0.5 = halved, 0.0 = blocked
    cqi_score: float = 0.0
    domain: str = ""
    checks_passed: List[str] = field(default_factory=list)
    checks_failed: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "original_size_usd": self.original_size_usd,
            "adjusted_size_usd": round(self.adjusted_size_usd, 2),
            "throttle_pct": round(self.throttle_pct, 4),
            "cqi_score": round(self.cqi_score, 4),
            "domain": self.domain,
            "checks_passed": self.checks_passed,
            "checks_failed": self.checks_failed,
        }


# ── Domain caps ───────────────────────────────────────────────────────

@dataclass
class DomainCap:
    """Per-domain execution limits."""
    domain: str
    max_daily_notional_usd: float = 5000.0
    max_single_trade_usd: float = 1000.0
    max_daily_trades: int = 50
    enabled: bool = True
    kill_switch: bool = False

    # Runtime counters (reset daily)
    daily_notional_usd: float = 0.0
    daily_trade_count: int = 0
    last_reset_date: str = ""

    def reset_if_new_day(self):
        today = time.strftime("%Y-%m-%d")
        if today != self.last_reset_date:
            self.daily_notional_usd = 0.0
            self.daily_trade_count = 0
            self.last_reset_date = today

    def record_trade(self, notional_usd: float):
        self.reset_if_new_day()
        self.daily_notional_usd += notional_usd
        self.daily_trade_count += 1

    def remaining_notional(self) -> float:
        self.reset_if_new_day()
        return max(0, self.max_daily_notional_usd - self.daily_notional_usd)

    def to_dict(self) -> Dict[str, Any]:
        self.reset_if_new_day()
        return {
            "domain": self.domain,
            "enabled": self.enabled,
            "kill_switch": self.kill_switch,
            "max_daily_notional_usd": self.max_daily_notional_usd,
            "daily_notional_usd": round(self.daily_notional_usd, 2),
            "remaining_notional_usd": round(self.remaining_notional(), 2),
            "daily_trade_count": self.daily_trade_count,
            "max_daily_trades": self.max_daily_trades,
        }


# ── CQI Throttle config ──────────────────────────────────────────────

@dataclass
class CQIThrottleConfig:
    """CQI-based execution throttling thresholds."""
    full_execution_above: float = 0.65   # CQI > 0.65: trade at full size
    throttle_start: float = 0.65         # CQI < 0.65: start shrinking
    block_below: float = 0.35            # CQI < 0.35: block all trades
    min_throttle_pct: float = 0.25       # Never shrink below 25% of original size

    def compute_throttle(self, cqi: float) -> float:
        """Returns a throttle factor (0.0 to 1.0) based on CQI."""
        if cqi >= self.full_execution_above:
            return 1.0
        if cqi <= self.block_below:
            return 0.0
        # Linear interpolation between block_below and full_execution_above
        range_width = self.full_execution_above - self.block_below
        if range_width <= 0:
            return 1.0
        raw = (cqi - self.block_below) / range_width
        return max(self.min_throttle_pct, raw)


# ── Execution Guard ──────────────────────────────────────────────────

class ExecutionGuard:
    """Central safety gate for all trade execution.

    The MeridLoop calls `pre_trade_check()` before every trade.
    The UI calls `activate_kill_switch()` / `deactivate_kill_switch()`.
    """

    def __init__(self):
        self._global_kill_switch = False
        self._global_kill_reason = ""
        self._cqi_config = CQIThrottleConfig()
        self._domain_caps: Dict[str, DomainCap] = {
            "crypto": DomainCap(domain="crypto", max_daily_notional_usd=10000, max_single_trade_usd=2000),
            "prediction": DomainCap(domain="prediction", max_daily_notional_usd=5000, max_single_trade_usd=500),
            "equity": DomainCap(domain="equity", max_daily_notional_usd=10000, max_single_trade_usd=2000),
            "sports": DomainCap(domain="sports", max_daily_notional_usd=2000, max_single_trade_usd=200),
        }
        self._last_cqi: Dict[str, float] = {}
        self._cooldown_seconds = 5.0
        self._last_execution_at = 0.0
        self._trade_log: List[Dict[str, Any]] = []

    # ── Kill switch ───────────────────────────────────────────────────

    def activate_kill_switch(self, reason: str = "manual"):
        """Block ALL execution immediately."""
        self._global_kill_switch = True
        self._global_kill_reason = reason
        logger.warning(f"KILL SWITCH ACTIVATED: {reason}")

    def deactivate_kill_switch(self):
        """Re-enable execution."""
        self._global_kill_switch = False
        self._global_kill_reason = ""
        logger.info("Kill switch deactivated")

    def activate_domain_kill_switch(self, domain: str, reason: str = "manual"):
        cap = self._domain_caps.get(domain)
        if cap:
            cap.kill_switch = True
            logger.warning(f"Domain kill switch activated for {domain}: {reason}")

    def deactivate_domain_kill_switch(self, domain: str):
        cap = self._domain_caps.get(domain)
        if cap:
            cap.kill_switch = False
            logger.info(f"Domain kill switch deactivated for {domain}")

    @property
    def kill_switch_active(self) -> bool:
        return self._global_kill_switch

    # ── CQI updates ───────────────────────────────────────────────────

    def update_cqi(self, domain: str, cqi_score: float):
        """Called by the loop after CQI computation to update throttle state."""
        self._last_cqi[domain] = cqi_score
        if cqi_score < self._cqi_config.block_below:
            logger.warning(
                f"CQI for {domain} dropped to {cqi_score:.3f} — "
                f"execution BLOCKED (threshold: {self._cqi_config.block_below})"
            )

    def get_cqi(self, domain: str) -> float:
        return self._last_cqi.get(domain, 0.5)  # Default neutral

    # ── Pre-trade check ───────────────────────────────────────────────

    def pre_trade_check(
        self,
        plan_id: str,
        symbol: str,
        domain: str,
        size_usd: float,
        direction: str = "long",
        now: Optional[float] = None,
    ) -> TradeVerdict:
        """Run all safety checks before execution. Returns a TradeVerdict."""
        now = now or time.time()
        passed: List[str] = []
        failed: List[str] = []

        verdict = TradeVerdict(
            allowed=True,
            reason="all checks passed",
            original_size_usd=size_usd,
            adjusted_size_usd=size_usd,
            domain=domain,
        )

        # 1. Global kill switch
        if self._global_kill_switch:
            verdict.allowed = False
            verdict.reason = f"global kill switch: {self._global_kill_reason}"
            verdict.adjusted_size_usd = 0
            failed.append("global_kill_switch")
            verdict.checks_passed = passed
            verdict.checks_failed = failed
            self._log_verdict(plan_id, verdict)
            return verdict
        passed.append("global_kill_switch")

        # 2. Per-domain kill switch
        cap = self._domain_caps.get(domain)
        if cap and cap.kill_switch:
            verdict.allowed = False
            verdict.reason = f"domain kill switch active for {domain}"
            verdict.adjusted_size_usd = 0
            failed.append("domain_kill_switch")
            verdict.checks_passed = passed
            verdict.checks_failed = failed
            self._log_verdict(plan_id, verdict)
            return verdict
        passed.append("domain_kill_switch")

        # 3. Domain enabled
        if cap and not cap.enabled:
            verdict.allowed = False
            verdict.reason = f"domain {domain} is disabled"
            verdict.adjusted_size_usd = 0
            failed.append("domain_enabled")
            verdict.checks_passed = passed
            verdict.checks_failed = failed
            self._log_verdict(plan_id, verdict)
            return verdict
        passed.append("domain_enabled")

        # 4. CQI throttle
        cqi = self.get_cqi(domain)
        verdict.cqi_score = cqi
        throttle = self._cqi_config.compute_throttle(cqi)
        verdict.throttle_pct = throttle
        if throttle <= 0:
            verdict.allowed = False
            verdict.reason = f"CQI too low ({cqi:.3f} < {self._cqi_config.block_below})"
            verdict.adjusted_size_usd = 0
            failed.append("cqi_throttle")
            verdict.checks_passed = passed
            verdict.checks_failed = failed
            self._log_verdict(plan_id, verdict)
            return verdict
        verdict.adjusted_size_usd = size_usd * throttle
        passed.append("cqi_throttle")

        # 5. Per-domain daily cap
        if cap:
            cap.reset_if_new_day()
            if cap.daily_trade_count >= cap.max_daily_trades:
                verdict.allowed = False
                verdict.reason = f"daily trade limit reached for {domain} ({cap.daily_trade_count}/{cap.max_daily_trades})"
                verdict.adjusted_size_usd = 0
                failed.append("daily_trade_count")
                verdict.checks_passed = passed
                verdict.checks_failed = failed
                self._log_verdict(plan_id, verdict)
                return verdict
            passed.append("daily_trade_count")

            remaining = cap.remaining_notional()
            if verdict.adjusted_size_usd > remaining:
                if remaining <= 0:
                    verdict.allowed = False
                    verdict.reason = f"daily notional cap exhausted for {domain}"
                    verdict.adjusted_size_usd = 0
                    failed.append("daily_notional_cap")
                else:
                    verdict.adjusted_size_usd = min(verdict.adjusted_size_usd, remaining)
                    passed.append("daily_notional_cap_clamped")
            else:
                passed.append("daily_notional_cap")

            if verdict.adjusted_size_usd > cap.max_single_trade_usd:
                verdict.adjusted_size_usd = cap.max_single_trade_usd
                passed.append("single_trade_cap_clamped")
            else:
                passed.append("single_trade_cap")

        # 6. Cooldown
        if now - self._last_execution_at < self._cooldown_seconds:
            verdict.allowed = False
            verdict.reason = f"cooldown ({self._cooldown_seconds}s between trades)"
            failed.append("cooldown")
            verdict.checks_passed = passed
            verdict.checks_failed = failed
            self._log_verdict(plan_id, verdict)
            return verdict
        passed.append("cooldown")

        verdict.checks_passed = passed
        verdict.checks_failed = failed
        self._log_verdict(plan_id, verdict)
        return verdict

    def record_execution(self, domain: str, notional_usd: float):
        """Called after a successful execution to update caps and cooldown."""
        self._last_execution_at = time.time()
        cap = self._domain_caps.get(domain)
        if cap:
            cap.record_trade(notional_usd)

    # ── Logging ───────────────────────────────────────────────────────

    def _log_verdict(self, plan_id: str, verdict: TradeVerdict):
        entry = {
            "plan_id": plan_id,
            "ts": time.time(),
            **verdict.to_dict(),
        }
        self._trade_log.append(entry)
        # Keep last 1000 entries
        if len(self._trade_log) > 1000:
            self._trade_log = self._trade_log[-500:]

        level = "INFO" if verdict.allowed else "WARNING"
        logger.log(
            getattr(logger, level.lower(), logger.info).__func__(logger) if False else 20 if verdict.allowed else 30,
            f"TradeVerdict [{plan_id}] {'ALLOWED' if verdict.allowed else 'BLOCKED'}: "
            f"${verdict.original_size_usd:.0f}→${verdict.adjusted_size_usd:.0f} "
            f"throttle={verdict.throttle_pct:.0%} CQI={verdict.cqi_score:.3f} "
            f"reason={verdict.reason}"
        )

    # ── Status ────────────────────────────────────────────────────────

    def summary(self) -> Dict[str, Any]:
        return {
            "global_kill_switch": self._global_kill_switch,
            "global_kill_reason": self._global_kill_reason,
            "cqi_throttle_config": {
                "full_above": self._cqi_config.full_execution_above,
                "block_below": self._cqi_config.block_below,
                "min_throttle": self._cqi_config.min_throttle_pct,
            },
            "last_cqi": {k: round(v, 4) for k, v in self._last_cqi.items()},
            "domain_caps": {k: v.to_dict() for k, v in self._domain_caps.items()},
            "cooldown_seconds": self._cooldown_seconds,
            "recent_verdicts": len(self._trade_log),
        }

    def recent_verdicts(self, limit: int = 20) -> List[Dict[str, Any]]:
        return self._trade_log[-limit:]


# ── Singleton ─────────────────────────────────────────────────────────

_guard: Optional[ExecutionGuard] = None


def get_execution_guard() -> ExecutionGuard:
    global _guard
    if _guard is None:
        _guard = ExecutionGuard()
    return _guard

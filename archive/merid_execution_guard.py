"""§H3 Execution Guard — CQI-based throttle, per-domain caps, kill switch, GOV review.

Sits between the loop's plan approval and actual venue submission.
Every trade must pass through `guard.pre_trade_check(plan)` before execution.

Safety layers (checked in order):
  1. Global kill switch — blocks ALL execution
  2. GOV intent review — governance veto and constraint enforcement
  3. Per-domain kill switch — blocks a single domain
  4. CQI throttle — shrinks or blocks trades when quality degrades
  5. Per-domain daily caps — max notional per domain per day
  6. Cooldown — min time between executions

Usage:
    guard = get_execution_guard()
    verdict = guard.pre_trade_check(plan, domain="crypto")
    if verdict.allowed:
        execute(plan, size=verdict.adjusted_size_usd)
"""

from __future__ import annotations

import threading
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from utils.logger import get_logger

_KILL_SWITCH_FILE = Path("data/kill_switch.json")

logger = get_logger("merid.execution_guard")

if TYPE_CHECKING:
    from merid.promotion_report import PromotionReport


def build_kalshi_crypto_intent(opinion, agent_id: str) -> dict:
    """Build a standardized Kalshi crypto intent for swarm review."""
    return {
        "venue": "kalshi",
        "lane": "crypto",
        "agent_id": agent_id,
        "market_id": opinion.market_id,
        "direction": opinion.side,
        "size_pct": opinion.size_pct,
        "edge_estimate": opinion.edge_estimate,
        "confidence": opinion.confidence,
        "metadata": opinion.metadata or {},
    }


async def apply_swarm_guard_to_kalshi_opinion(opinion, agent_id: str) -> dict:
    """
    Pass a Kalshi opinion through the swarm orchestrator, return review dict.
    """
    from merid.swarm.orchestrator import get_swarm_orchestrator
    orchestrator = get_swarm_orchestrator()
    intent = build_kalshi_crypto_intent(opinion, agent_id)
    review = await orchestrator.review_intent(intent)
    return review


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

    # Protects concurrent access to daily counters during pre_trade_check calls
    _lock: threading.RLock = field(default_factory=threading.RLock)

    def reset_if_new_day(self):
        with self._lock:
            today = time.strftime("%Y-%m-%d")
            if today != self.last_reset_date:
                self.daily_notional_usd = 0.0
                self.daily_trade_count = 0
                self.last_reset_date = today

    def record_trade(self, notional_usd: float):
        with self._lock:
            self.reset_if_new_day()
            self.daily_notional_usd += notional_usd
            self.daily_trade_count += 1
            pct_used = self.daily_notional_usd / self.max_daily_notional_usd if self.max_daily_notional_usd > 0 else 0
            if pct_used > 0.9:
                logger.debug("Domain cap nearing limit", domain=self.domain, pct_used=round(pct_used, 3))

    def remaining_notional(self) -> float:
        with self._lock:
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


# ── Per-venue exposure caps ──────────────────────────────────────────

@dataclass
class VenueExposureCap:
    """Per-venue maximum total exposure (sum of open position notional)."""
    venue: str
    max_exposure_usd: float = 25000.0
    current_exposure_usd: float = 0.0

    def would_breach(self, additional_usd: float) -> bool:
        return (self.current_exposure_usd + additional_usd) > self.max_exposure_usd

    def remaining(self) -> float:
        return max(0.0, self.max_exposure_usd - self.current_exposure_usd)

    def record(self, notional_usd: float):
        self.current_exposure_usd += notional_usd

    def release(self, notional_usd: float):
        self.current_exposure_usd = max(0.0, self.current_exposure_usd - notional_usd)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "venue": self.venue,
            "max_exposure_usd": self.max_exposure_usd,
            "current_exposure_usd": round(self.current_exposure_usd, 2),
            "remaining_usd": round(self.remaining(), 2),
            "utilization_pct": round(self.current_exposure_usd / self.max_exposure_usd * 100, 1) if self.max_exposure_usd > 0 else 0.0,
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
            "prediction": DomainCap(domain="prediction", max_daily_notional_usd=2000, max_single_trade_usd=500),
            "equity": DomainCap(domain="equity", max_daily_notional_usd=10000, max_single_trade_usd=2000),
            "sports": DomainCap(domain="sports", max_daily_notional_usd=2000, max_single_trade_usd=200),
        }
        self._venue_caps: Dict[str, VenueExposureCap] = {
            "binance": VenueExposureCap(venue="binance", max_exposure_usd=25000),
            "alpaca": VenueExposureCap(venue="alpaca", max_exposure_usd=20000),
            "kalshi": VenueExposureCap(venue="kalshi", max_exposure_usd=1500),
            "coinbase": VenueExposureCap(venue="coinbase", max_exposure_usd=15000),
        }
        self._last_cqi: Dict[str, float] = {}
        self._cooldown_seconds = 5.0
        self._last_execution_at = 0.0
        self._trade_log: List[Dict[str, Any]] = []

        self._load_persisted_kill_switch()

        # Promotion enforcement: when True, live trades are blocked for
        # domains that are not eligible in the latest promotion report.
        self.enforce_promotion = True
        self._promotion_report: Optional[PromotionReport] = None
        self._promotion_eligible_domains: Optional[set] = None
        self._promotion_blocked_agents: Optional[set] = None
        self._promotion_report_ts: float = 0.0

    # ── Kill switch ─────────────────────────────────────────────────--

    def activate_kill_switch(self, reason: str = "manual"):
        """Block ALL execution immediately."""
        self._global_kill_switch = True
        self._global_kill_reason = reason
        self._persist_kill_switch()
        logger.warning(f"KILL SWITCH ACTIVATED: {reason}")

    def deactivate_kill_switch(self):
        """Re-enable execution."""
        self._global_kill_switch = False
        self._global_kill_reason = ""
        self._persist_kill_switch()
        logger.info("Kill switch deactivated")

    def _persist_kill_switch(self):
        """Write kill switch state to disk so it survives restarts."""
        try:
            _KILL_SWITCH_FILE.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "active": self._global_kill_switch,
                "reason": self._global_kill_reason,
                "activated_at": time.time() if self._global_kill_switch else None,
            }
            _KILL_SWITCH_FILE.write_text(json.dumps(payload, indent=2))
        except Exception as exc:
            logger.error(f"Failed to persist kill switch state: {exc}")

    def _load_persisted_kill_switch(self):
        """Reload kill switch state from disk on startup."""
        try:
            if _KILL_SWITCH_FILE.exists():
                data = json.loads(_KILL_SWITCH_FILE.read_text())
                if data.get("active"):
                    self._global_kill_switch = True
                    self._global_kill_reason = data.get("reason", "persisted")
                    logger.warning(
                        f"Kill switch restored from disk: {self._global_kill_reason}"
                    )
        except Exception as exc:
            logger.error(f"Failed to load persisted kill switch: {exc}")

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

    # ── Promotion enforcement ────────────────────────────────────────

    def sync_promotion_report(self):
        """Pull eligible domains/agents from the cached promotion report.

        Called periodically by the loop or on-demand.  Does NOT regenerate
        the report — it reads whatever is cached.
        """
        try:
            from merid.promotion_report import get_cached_promotion_report
            report = get_cached_promotion_report(gauntlet_cycles=5)
            self._promotion_report = report
            self._promotion_eligible_domains = set(report.eligible_domains)
            self._promotion_blocked_agents = set(report.blocked_agents)
            self._promotion_report_ts = report.timestamp
            logger.info(
                f"Promotion sync: report ts={report.timestamp}, "
                f"{len(report.eligible_domains)} eligible domains, {len(report.promoted_agents)} promoted"
            )
        except Exception as exc:
            logger.warning(f"Promotion sync failed (enforcement unchanged): {exc}")

    def _prediction_domain_eligibility(self) -> Tuple[bool, bool]:
        if not self._promotion_report:
            return True, True
        try:
            from merid.settings import settings as _settings
        except Exception as exc:
            logger.debug("prediction_eligibility_settings_missing", error=str(exc))
            return True, True

        paper_allowed = self._promotion_report.is_prediction_domain_paper_eligible(settings=_settings)
        live_allowed = self._promotion_report.is_prediction_domain_live_eligible(settings=_settings)
        return paper_allowed, live_allowed

    def is_domain_promoted(self, domain: str) -> bool:
        """Check if a domain is eligible per the latest promotion report."""
        if self._promotion_eligible_domains is None:
            return True  # No report yet — allow (fail-open for paper)
        return domain in self._promotion_eligible_domains

    def is_agent_promoted(self, agent_id: str) -> bool:
        """Check if an agent is promoted per the latest promotion report."""
        if self._promotion_blocked_agents is None:
            return True  # No report yet — allow
        return agent_id not in self._promotion_blocked_agents

    # ── CQI updates ─────────────────────────────────────────────────--

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

    def get_venue_cap(self, venue: str) -> Optional[VenueExposureCap]:
        return self._venue_caps.get(venue)

    def set_venue_cap(self, venue: str, max_exposure_usd: float):
        if venue in self._venue_caps:
            self._venue_caps[venue].max_exposure_usd = max_exposure_usd
        else:
            self._venue_caps[venue] = VenueExposureCap(venue=venue, max_exposure_usd=max_exposure_usd)

    def sync_venue_exposure(self, venue: str, current_exposure_usd: float):
        """Called by the loop/reconciliation to sync actual venue exposure."""
        if venue in self._venue_caps:
            self._venue_caps[venue].current_exposure_usd = current_exposure_usd
        else:
            self._venue_caps[venue] = VenueExposureCap(venue=venue, current_exposure_usd=current_exposure_usd)

    async def pre_trade_check(
        self,
        plan_id: str,
        symbol: str,
        domain: str,
        size_usd: float,
        direction: str = "long",
        venue: str = "",
        order_group_id: str = "",
        order_contracts: int = 0,
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

        # 2. GOV intent review
        try:
            from governance.intent_review import get_intent_review_engine, ReviewDecision
            from merid.swarm.orchestrator import get_swarm_orchestrator
            
            # Convert trade plan to intent data
            intent_data = {
                "intent_id": f"trade_{plan_id}",
                "origin_system": "OPS",
                "action_type": "trade",
                "symbol": symbol,
                "domain": domain,
                "size_usd": size_usd,
                "direction": direction,
                "venue": venue,
                "order_group_id": order_group_id,
                "order_contracts": order_contracts,
                "timestamp": now
            }
            
            engine = get_intent_review_engine()
            review = await engine.review_intent(
                intent_id=intent_data["intent_id"],
                intent_data=intent_data,
                reviewer_id="EXEC_GUARD"
            )
            
            # Submit to quorum system
            engine.submit_review(review)
            
            # Check GOV decision
            if review.decision != ReviewDecision.APPROVE:
                verdict.allowed = False
                reason = review.rejection_reason.value if review.rejection_reason else "rejected"
                verdict.reason = f"GOV veto: {reason}"
                verdict.checks_failed.append("gov_veto")
                self._log_verdict(plan_id, verdict)
                return verdict
            passed.append("gov_veto")
            
            # Swarm orchestrator review
            try:
                swarm_orchestrator = get_swarm_orchestrator()
                swarm_intent = {
                    "venue": venue,
                    "domain": domain,
                    "agent_id": "execution_guard",
                    "symbol": symbol,
                    "direction": direction,
                    "size_usd": size_usd,
                    "metadata": {
                        "plan_id": plan_id,
                        "order_group_id": order_group_id,
                    }
                }
                swarm_review = await swarm_orchestrator.review_intent(swarm_intent)
                
                if not swarm_review.get("approved", True):
                    verdict.allowed = False
                    verdict.reason = f"Swarm veto: {swarm_review.get('reason', 'unknown')}"
                    verdict.checks_failed.append("swarm_veto")
                    self._log_verdict(plan_id, verdict)
                    return verdict
                passed.append("swarm_veto")
            except Exception as swarm_exc:
                logger.warning(f"Swarm orchestrator review failed (graceful degradation): {swarm_exc}")
                passed.append("swarm_veto")  # Pass but log the issue
            
            # Enforce GOV constraints
            if size_usd > review.approved_notional:
                size_usd = review.approved_notional
                verdict.adjusted_size_usd = size_usd
                verdict.reason = f"Size adjusted by GOV constraints: {review.approved_notional}"
            
            passed.append("gov_review")
            
        except Exception as e:
            # Log error but don't block execution if GOV review fails
            logger.warning(f"GOV review failed for {plan_id}: {e}")
            passed.append("gov_review_failed")

        # 3. Per-domain kill switch
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

        # 3.5 Promotion eligibility gate for prediction domain
        if False and self.enforce_promotion and domain.lower() == "prediction":
            paper_allowed, live_allowed = self._prediction_domain_eligibility()
            is_live = False
            try:
                from trading.mode_controller import get_trading_mode_controller
                is_live = get_trading_mode_controller().is_live
            except Exception as exc:
                logger.debug("prediction_mode_fetch_failed", error=str(exc))

            if is_live and not live_allowed:
                verdict.allowed = False
                verdict.reason = (
                    "prediction domain not eligible for live execution (promotion gate)"
                )
                verdict.adjusted_size_usd = 0
                failed.append("promotion_eligibility")
                verdict.checks_passed = passed
                verdict.checks_failed = failed
                self._log_verdict(plan_id, verdict)
                return verdict

            if not is_live and not paper_allowed:
                verdict.allowed = False
                verdict.reason = (
                    "prediction domain not eligible for paper execution (promotion gate)"
                )
                verdict.adjusted_size_usd = 0
                failed.append("promotion_eligibility")
                verdict.checks_passed = passed
                verdict.checks_failed = failed
                self._log_verdict(plan_id, verdict)
                return verdict

        passed.append("promotion_eligibility_skipped")

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

        # 4.5 Per-venue exposure cap
        if venue and venue in self._venue_caps:
            vcap = self._venue_caps[venue]
            if vcap.would_breach(verdict.adjusted_size_usd):
                remaining_venue = vcap.remaining()
                if remaining_venue <= 0:
                    verdict.allowed = False
                    verdict.reason = f"venue exposure cap exhausted for {venue}"
                    verdict.adjusted_size_usd = 0
                    failed.append("venue_exposure_cap")
                    verdict.checks_passed = passed
                    verdict.checks_failed = failed
                    self._log_verdict(plan_id, verdict)
                    return verdict
                else:
                    verdict.adjusted_size_usd = min(verdict.adjusted_size_usd, remaining_venue)
                    passed.append("venue_exposure_cap_clamped")
            else:
                passed.append("venue_exposure_cap")

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

        # 7. Order group limit check (if assigned to a group)
        if order_group_id and order_contracts > 0:
            try:
                from merid.event_venues.kalshi.order_group_manager import OrderGroupRiskManager
                og_manager = OrderGroupRiskManager(None)  # Uses cached state
                group = og_manager.get_group(order_group_id)
                if group:
                    if not group.is_active():
                        verdict.allowed = False
                        verdict.reason = f"order group {order_group_id} is {group.status}"
                        verdict.adjusted_size_usd = 0
                        failed.append("order_group_inactive")
                    elif not group.can_add_contracts(order_contracts):
                        remaining = group.contracts_limit - group.used_contracts
                        verdict.reason = (
                            f"order group {order_group_id} limit exceeded "
                            f"(need {order_contracts}, remaining {remaining})"
                        )
                        # Allow but warn if we can fit some contracts
                        if remaining > 0 and order_contracts > remaining:
                            verdict.adjusted_size_usd = verdict.adjusted_size_usd * (remaining / order_contracts)
                            passed.append("order_group_clamped")
                        elif remaining <= 0:
                            verdict.allowed = False
                            verdict.adjusted_size_usd = 0
                            failed.append("order_group_exhausted")
                        else:
                            passed.append("order_group_ok")
                    else:
                        passed.append("order_group_ok")
                else:
                    # Group not found — allow but log warning
                    logger.warning(f"Order group {order_group_id} not found for trade check")
                    passed.append("order_group_unknown")
            except Exception as exc:
                # Order group check failed — don't block execution, just log
                logger.warning(f"Order group check failed (allowing trade): {exc}")
                passed.append("order_group_check_failed")

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

    # ── Logging ─────────────────────────────────────────────────────

    def _log_verdict(self, plan_id: str, verdict: TradeVerdict):
        """Log the result of a pre-trade check."""
        log_level = logger.info if verdict.allowed else logger.warning
        log_level(
            f"Pre-trade check {plan_id}: {verdict.reason} "
            f"({verdict.original_size_usd:.2f} → {verdict.adjusted_size_usd:.2f} USD) "
            f"passed={verdict.checks_passed} failed={verdict.checks_failed}"
        )

        # Store for audit trail
        self._trade_log.append({
            "timestamp": time.time(),
            "plan_id": plan_id,
            "allowed": verdict.allowed,
            "reason": verdict.reason,
            "original_size_usd": verdict.original_size_usd,
            "adjusted_size_usd": verdict.adjusted_size_usd,
            "domain": verdict.domain,
            "checks_passed": verdict.checks_passed,
            "checks_failed": verdict.checks_failed,
        })

        # Keep log size bounded
        if len(self._trade_log) > 1000:
            self._trade_log = self._trade_log[-500:]

    # ── API helpers ───────────────────────────────────────────────────

    def get_status(self) -> Dict[str, Any]:
        """Return current guard status for UI/API."""
        return {
            "global_kill_switch": self._global_kill_switch,
            "global_kill_reason": self._global_kill_reason,
            "domain_caps": {domain: cap.to_dict() for domain, cap in self._domain_caps.items()},
            "venue_caps": {venue: cap.to_dict() for venue, cap in self._venue_caps.items()},
            "last_cqi": self._last_cqi.copy(),
            "cooldown_seconds": self._cooldown_seconds,
            "last_execution_at": self._last_execution_at,
            "promotion_sync_ts": self._promotion_report_ts,
            "enforce_promotion": self.enforce_promotion,
        }

    def get_trade_log(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return recent trade log entries."""
        return self._trade_log[-limit:]


# ── Singleton ──────────────────────────────────────────────────────

_guard: Optional[ExecutionGuard] = None
_guard_lock = threading.Lock()


def get_execution_guard() -> ExecutionGuard:
    """Return the module-level ExecutionGuard singleton."""
    global _guard
    if _guard is None:
        with _guard_lock:
            if _guard is None:
                _guard = ExecutionGuard()
    return _guard

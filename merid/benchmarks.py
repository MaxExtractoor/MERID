"""MERID Pre-Live Benchmark System.

Defines operational health targets across 5 categories and collects
real-time metrics from the existing infrastructure. A venue should NOT
be flipped from stub to live until all benchmarks pass comfortably
during a sustained paper session.

Categories:
    1. Latency & throughput (loop cycle, agent P95)
    2. Data quality & freshness (WS channels, reconciliation)
    3. Risk & exposure (venue caps, drawdown)
    4. Alert hygiene (firing count, noise ratio)
    5. Swarm/consensus behavior (coverage, consensus rate, exec ratio)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

_BOOT_TIME = time.monotonic()


# ════════════════════════════════════════════════════════════════════
# Benchmark status enum
# ════════════════════════════════════════════════════════════════════

class BenchmarkStatus(str, Enum):
    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"
    NO_DATA = "no_data"


# ════════════════════════════════════════════════════════════════════
# Individual benchmark result
# ════════════════════════════════════════════════════════════════════

@dataclass
class BenchmarkResult:
    name: str
    category: str
    status: BenchmarkStatus
    value: Any
    target: str
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "category": self.category,
            "status": self.status.value,
            "value": self.value,
            "target": self.target,
            "detail": self.detail,
        }


# ════════════════════════════════════════════════════════════════════
# Benchmark targets (tunable)
# ════════════════════════════════════════════════════════════════════

@dataclass
class BenchmarkTargets:
    """All configurable thresholds in one place."""

    # 1) Latency
    loop_cycle_max_ms: float = 15_000.0        # ≤ configured cadence
    agent_p95_warn_ms: float = 3_000.0         # normal agents
    agent_p95_crit_ms: float = 5_000.0         # heavy LLM agents

    # 2) Data quality
    ws_channel_max_age_s: float = 60.0         # market_data channel
    recon_max_age_s: float = 180.0             # recon every 2-3 min

    # 3) Risk
    venue_cap_warn_pct: float = 50.0           # utilization warning
    venue_cap_fail_pct: float = 70.0           # utilization fail
    max_intraday_drawdown_pct: float = 2.0     # paper budget

    # 4) Alert hygiene
    max_firing_alerts: int = 0                 # target: zero in normal op

    # Warmup: grace period after boot where cold-start artifacts are NO_DATA
    warmup_grace_s: float = 300.0              # 5 minutes

    # Alerts that always fire at cold start and should be ignored during warmup
    warmup_ignore_alerts: tuple = (
        "opinion_freshness", "signal_cache_stale", "ws_feed_disconnected",
        "no_debate_activity", "reconciliation_degraded", "reconciliation_stale",
    )

    # 5) Swarm / consensus
    min_active_agents: int = 1
    consensus_rate_min_pct: float = 10.0       # ≥10% of cycles produce plans
    consensus_rate_max_pct: float = 80.0       # ≤80% (not rubber-stamping)
    execution_ratio_max_pct: float = 40.0      # only subset passes guard


TARGETS = BenchmarkTargets()


# ════════════════════════════════════════════════════════════════════
# Benchmark collector
# ════════════════════════════════════════════════════════════════════

class BenchmarkCollector:
    """Gathers metrics from existing MERID infrastructure and evaluates
    them against the benchmark targets."""

    def __init__(self, targets: Optional[BenchmarkTargets] = None):
        self.targets = targets or TARGETS

    @property
    def _in_warmup(self) -> bool:
        return (time.monotonic() - _BOOT_TIME) < self.targets.warmup_grace_s

    @property
    def _uptime_s(self) -> float:
        return time.monotonic() - _BOOT_TIME

    def collect_all(self) -> Dict[str, Any]:
        """Run all benchmark checks and return a structured report."""
        results: List[BenchmarkResult] = []

        results.extend(self._check_latency())
        results.extend(self._check_data_quality())
        results.extend(self._check_risk())
        results.extend(self._check_alert_hygiene())
        results.extend(self._check_swarm())

        pass_count = sum(1 for r in results if r.status == BenchmarkStatus.PASS)
        warn_count = sum(1 for r in results if r.status == BenchmarkStatus.WARN)
        fail_count = sum(1 for r in results if r.status == BenchmarkStatus.FAIL)
        no_data_count = sum(1 for r in results if r.status == BenchmarkStatus.NO_DATA)

        overall = BenchmarkStatus.PASS
        if fail_count > 0:
            overall = BenchmarkStatus.FAIL
        elif warn_count > 0:
            overall = BenchmarkStatus.WARN
        elif no_data_count == len(results):
            overall = BenchmarkStatus.NO_DATA

        return {
            "overall": overall.value,
            "timestamp": time.time(),
            "uptime_s": round(self._uptime_s, 1),
            "in_warmup": self._in_warmup,
            "summary": {
                "pass": pass_count,
                "warn": warn_count,
                "fail": fail_count,
                "no_data": no_data_count,
                "total": len(results),
            },
            "go_live_ready": fail_count == 0 and warn_count == 0 and no_data_count < len(results),
            "benchmarks": [r.to_dict() for r in results],
        }

    # ── 1) Latency ────────────────────────────────────────────────

    def _check_latency(self) -> List[BenchmarkResult]:
        results = []

        # Loop cycle time
        results.append(self._check_loop_cycle())

        # Agent P95 latency
        results.extend(self._check_agent_latency())

        return results

    def _check_loop_cycle(self) -> BenchmarkResult:
        try:
            from merid.agents.orchestrator import AgentOrchestrator
            orch = AgentOrchestrator()
            history = orch.get_history()
            if not history:
                return BenchmarkResult(
                    name="loop_cycle_time", category="latency",
                    status=BenchmarkStatus.NO_DATA, value=None,
                    target=f"≤{self.targets.loop_cycle_max_ms}ms",
                    detail="No orchestrator history available",
                )
            durations = [c.get("total_duration_ms", 0) for c in history[-20:]]
            if not durations:
                return BenchmarkResult(
                    name="loop_cycle_time", category="latency",
                    status=BenchmarkStatus.NO_DATA, value=None,
                    target=f"≤{self.targets.loop_cycle_max_ms}ms",
                )
            avg = sum(durations) / len(durations)
            p95 = sorted(durations)[min(int(len(durations) * 0.95), len(durations) - 1)]
            status = BenchmarkStatus.PASS if p95 <= self.targets.loop_cycle_max_ms else BenchmarkStatus.FAIL
            return BenchmarkResult(
                name="loop_cycle_time", category="latency",
                status=status, value={"avg_ms": round(avg, 1), "p95_ms": round(p95, 1)},
                target=f"P95 ≤{self.targets.loop_cycle_max_ms}ms",
                detail=f"{len(durations)} recent cycles sampled",
            )
        except Exception as _e:
            logger.debug("loop_cycle_time probe failed: %s", _e)
            return BenchmarkResult(
                name="loop_cycle_time", category="latency",
                status=BenchmarkStatus.NO_DATA, value=None,
                target=f"≤{self.targets.loop_cycle_max_ms}ms",
                detail="Orchestrator unavailable",
            )

    def _check_agent_latency(self) -> List[BenchmarkResult]:
        try:
            from agents.agent_framework import get_agent_registry
            registry = get_agent_registry()
            all_metrics = registry.get_all_metrics()
        except Exception as _e:
            logger.debug("agent_latency probe failed: %s", _e)
            return [BenchmarkResult(
                name="agent_latency_p95", category="latency",
                status=BenchmarkStatus.NO_DATA, value=None,
                target=f"P95 <{self.targets.agent_p95_warn_ms}ms",
                detail="Agent registry unavailable",
            )]

        if not all_metrics:
            return [BenchmarkResult(
                name="agent_latency_p95", category="latency",
                status=BenchmarkStatus.NO_DATA, value=None,
                target=f"P95 <{self.targets.agent_p95_warn_ms}ms",
                detail="No agents registered",
            )]

        results = []
        worst_p95 = 0.0
        breaching = {}
        for agent_id, m in all_metrics.items():
            if m.p95_latency_ms > worst_p95:
                worst_p95 = m.p95_latency_ms
            if m.p95_latency_ms >= self.targets.agent_p95_crit_ms:
                breaching[agent_id] = m.p95_latency_ms
            elif m.p95_latency_ms >= self.targets.agent_p95_warn_ms:
                breaching[agent_id] = m.p95_latency_ms

        if breaching:
            worst_agent = max(breaching, key=breaching.get)
            status = BenchmarkStatus.FAIL if breaching[worst_agent] >= self.targets.agent_p95_crit_ms else BenchmarkStatus.WARN
        else:
            status = BenchmarkStatus.PASS
            worst_agent = None

        results.append(BenchmarkResult(
            name="agent_latency_p95", category="latency",
            status=status,
            value={
                "worst_p95_ms": round(worst_p95, 1),
                "agents_checked": len(all_metrics),
                "breaching": {k: round(v, 1) for k, v in breaching.items()},
            },
            target=f"P95 <{self.targets.agent_p95_warn_ms}ms (crit {self.targets.agent_p95_crit_ms}ms)",
            detail=f"Worst: {worst_agent} @ {round(worst_p95, 1)}ms" if worst_agent else "All within SLO",
        ))
        return results

    # ── 2) Data quality ───────────────────────────────────────────

    def _check_data_quality(self) -> List[BenchmarkResult]:
        results = []
        results.append(self._check_ws_freshness())
        results.append(self._check_recon_freshness())
        return results

    def _check_ws_freshness(self) -> BenchmarkResult:
        try:
            from web.api.live_stream import get_channel_freshness
            freshness = get_channel_freshness()
        except Exception as _e:
            logger.debug("ws_channel_freshness probe failed: %s", _e)
            return BenchmarkResult(
                name="ws_channel_freshness", category="data_quality",
                status=BenchmarkStatus.NO_DATA, value=None,
                target=f"market_data age <{self.targets.ws_channel_max_age_s}s",
                detail="Channel freshness unavailable",
            )

        if not freshness:
            return BenchmarkResult(
                name="ws_channel_freshness", category="data_quality",
                status=BenchmarkStatus.NO_DATA, value=None,
                target=f"market_data age <{self.targets.ws_channel_max_age_s}s",
                detail="No channels tracked yet",
            )

        stale = {}
        for ch, info in freshness.items():
            if info["age_seconds"] > self.targets.ws_channel_max_age_s:
                stale[ch] = round(info["age_seconds"], 1)

        if stale:
            return BenchmarkResult(
                name="ws_channel_freshness", category="data_quality",
                status=BenchmarkStatus.FAIL, value=stale,
                target=f"All channels <{self.targets.ws_channel_max_age_s}s",
                detail=f"{len(stale)} stale channel(s)",
            )
        return BenchmarkResult(
            name="ws_channel_freshness", category="data_quality",
            status=BenchmarkStatus.PASS,
            value={ch: round(info["age_seconds"], 1) for ch, info in freshness.items()},
            target=f"All channels <{self.targets.ws_channel_max_age_s}s",
            detail=f"{len(freshness)} channels fresh",
        )

    def _check_recon_freshness(self) -> BenchmarkResult:
        try:
            from merid.reconciliation import get_last_reconciliation_ts
            last_ts = get_last_reconciliation_ts()
        except Exception as _e:
            logger.debug("reconciliation_freshness probe failed: %s", _e)
            return BenchmarkResult(
                name="reconciliation_freshness", category="data_quality",
                status=BenchmarkStatus.NO_DATA, value=None,
                target=f"<{self.targets.recon_max_age_s}s since last recon",
                detail="Reconciliation module unavailable",
            )

        if last_ts == 0.0:
            status = BenchmarkStatus.NO_DATA if self._in_warmup else BenchmarkStatus.FAIL
            detail = "Reconciliation has never run" + (" (warmup)" if self._in_warmup else "")
            return BenchmarkResult(
                name="reconciliation_freshness", category="data_quality",
                status=status, value=None,
                target=f"<{self.targets.recon_max_age_s}s since last recon",
                detail=detail,
            )

        age = time.time() - last_ts
        status = BenchmarkStatus.PASS if age <= self.targets.recon_max_age_s else BenchmarkStatus.FAIL
        return BenchmarkResult(
            name="reconciliation_freshness", category="data_quality",
            status=status, value=round(age, 1),
            target=f"<{self.targets.recon_max_age_s}s since last recon",
            detail=f"Last recon {round(age, 1)}s ago",
        )

    # ── 3) Risk & exposure ────────────────────────────────────────

    def _check_risk(self) -> List[BenchmarkResult]:
        results = []
        results.append(self._check_venue_exposure())
        results.append(self._check_drawdown())
        return results

    def _check_venue_exposure(self) -> BenchmarkResult:
        try:
            from merid.execution_guard import get_execution_guard
            guard = get_execution_guard()
            summary = guard.summary()
            venue_caps = summary.get("venue_caps", {})
        except Exception as _e:
            logger.debug("venue_exposure probe failed: %s", _e)
            return BenchmarkResult(
                name="venue_exposure", category="risk",
                status=BenchmarkStatus.NO_DATA, value=None,
                target=f"Utilization <{self.targets.venue_cap_warn_pct}%",
                detail="Execution guard unavailable",
            )

        if not venue_caps:
            return BenchmarkResult(
                name="venue_exposure", category="risk",
                status=BenchmarkStatus.NO_DATA, value=None,
                target=f"Utilization <{self.targets.venue_cap_warn_pct}%",
                detail="No venue caps configured",
            )

        worst_pct = 0.0
        worst_venue = ""
        per_venue = {}
        for venue, cap in venue_caps.items():
            pct = cap.get("utilization_pct", 0)
            per_venue[venue] = round(pct, 1)
            if pct > worst_pct:
                worst_pct = pct
                worst_venue = venue

        if worst_pct >= self.targets.venue_cap_fail_pct:
            status = BenchmarkStatus.FAIL
        elif worst_pct >= self.targets.venue_cap_warn_pct:
            status = BenchmarkStatus.WARN
        else:
            status = BenchmarkStatus.PASS

        return BenchmarkResult(
            name="venue_exposure", category="risk",
            status=status, value=per_venue,
            target=f"All venues <{self.targets.venue_cap_warn_pct}% (fail >{self.targets.venue_cap_fail_pct}%)",
            detail=f"Worst: {worst_venue} @ {round(worst_pct, 1)}%" if worst_venue else "",
        )

    def _check_drawdown(self) -> BenchmarkResult:
        try:
            from trading.paper_trading import get_paper_engine
            engine = get_paper_engine()
            stats = engine.get_global_stats()
            equity_series = engine.get_equity_series()
        except Exception as _e:
            logger.debug("max_drawdown probe failed: %s", _e)
            return BenchmarkResult(
                name="max_drawdown", category="risk",
                status=BenchmarkStatus.NO_DATA, value=None,
                target=f"Intraday DD <{self.targets.max_intraday_drawdown_pct}%",
                detail="Paper engine unavailable",
            )

        if not equity_series or len(equity_series) < 2:
            return BenchmarkResult(
                name="max_drawdown", category="risk",
                status=BenchmarkStatus.NO_DATA, value=None,
                target=f"Intraday DD <{self.targets.max_intraday_drawdown_pct}%",
                detail="Insufficient equity data",
            )

        # Compute max drawdown from equity series
        peak = equity_series[0].get("equity", 0)
        max_dd_pct = 0.0
        for snap in equity_series:
            eq = snap.get("equity", 0)
            if eq > peak:
                peak = eq
            if peak > 0:
                dd = (peak - eq) / peak * 100
                if dd > max_dd_pct:
                    max_dd_pct = dd

        status = BenchmarkStatus.PASS if max_dd_pct <= self.targets.max_intraday_drawdown_pct else BenchmarkStatus.FAIL
        return BenchmarkResult(
            name="max_drawdown", category="risk",
            status=status, value=round(max_dd_pct, 2),
            target=f"Intraday DD <{self.targets.max_intraday_drawdown_pct}%",
            detail=f"Max drawdown: {round(max_dd_pct, 2)}%",
        )

    # ── 4) Alert hygiene ──────────────────────────────────────────

    def _check_alert_hygiene(self) -> List[BenchmarkResult]:
        results = []
        try:
            from web.api.system_observability import ALERT_RULES
            firing = []
            for rule in ALERT_RULES:
                result = rule.safe_evaluate()
                if result.get("firing"):
                    firing.append({
                        "name": result.get("name", "unknown"),
                        "severity": result.get("severity", "unknown"),
                    })

            # During warmup, filter out known cold-start alerts
            if self._in_warmup:
                real_firing = [a for a in firing if a["name"] not in self.targets.warmup_ignore_alerts]
            else:
                real_firing = firing

            count = len(real_firing)
            if count > self.targets.max_firing_alerts:
                status = BenchmarkStatus.FAIL
            elif self._in_warmup and len(firing) > 0 and count == 0:
                status = BenchmarkStatus.NO_DATA
            else:
                status = BenchmarkStatus.PASS

            warmup_note = f" ({len(firing) - count} warmup-ignored)" if self._in_warmup and len(firing) > count else ""
            results.append(BenchmarkResult(
                name="alert_hygiene", category="alerts",
                status=status,
                value={"firing_count": count, "total_firing": len(firing), "firing": real_firing, "in_warmup": self._in_warmup},
                target=f"≤{self.targets.max_firing_alerts} alerts firing in normal operation",
                detail=(f"{count} alert(s) currently firing{warmup_note}" if count else f"All quiet{warmup_note}"),
            ))
        except Exception as _e:
            logger.debug("alert_hygiene probe failed: %s", _e)
            results.append(BenchmarkResult(
                name="alert_hygiene", category="alerts",
                status=BenchmarkStatus.NO_DATA, value=None,
                target=f"≤{self.targets.max_firing_alerts} alerts firing",
                detail="Alert system unavailable",
            ))
        return results

    # ── 5) Swarm / consensus ──────────────────────────────────────

    def _check_swarm(self) -> List[BenchmarkResult]:
        results = []
        results.append(self._check_active_agents())
        results.append(self._check_consensus_rate())
        return results

    def _check_active_agents(self) -> BenchmarkResult:
        try:
            from agents.agent_framework import get_agent_registry
            registry = get_agent_registry()
            stats = registry.get_statistics()
            active = stats.get("agents_by_status", {}).get("active", 0)
            total = stats.get("total_agents", 0)
        except Exception as _e:
            logger.debug("active_agents probe failed: %s", _e)
            return BenchmarkResult(
                name="active_agents", category="swarm",
                status=BenchmarkStatus.NO_DATA, value=None,
                target=f"≥{self.targets.min_active_agents} active agents",
                detail="Agent registry unavailable",
            )

        if total == 0:
            return BenchmarkResult(
                name="active_agents", category="swarm",
                status=BenchmarkStatus.NO_DATA,
                value={"active": 0, "total": 0},
                target=f"≥{self.targets.min_active_agents} active agents",
                detail="No agents registered",
            )

        status = BenchmarkStatus.PASS if active >= self.targets.min_active_agents else BenchmarkStatus.FAIL
        return BenchmarkResult(
            name="active_agents", category="swarm",
            status=status,
            value={"active": active, "total": total},
            target=f"≥{self.targets.min_active_agents} active agents",
            detail=f"{active}/{total} agents active",
        )

    def _check_consensus_rate(self) -> BenchmarkResult:
        try:
            from merid.agents.orchestrator import AgentOrchestrator
            orch = AgentOrchestrator()
            history = orch.get_history()
        except Exception as _e:
            logger.debug("consensus_rate probe failed: %s", _e)
            return BenchmarkResult(
                name="consensus_rate", category="swarm",
                status=BenchmarkStatus.NO_DATA, value=None,
                target=f"{self.targets.consensus_rate_min_pct}-{self.targets.consensus_rate_max_pct}% of cycles produce plans",
                detail="Orchestrator unavailable",
            )

        if not history or len(history) < 5:
            return BenchmarkResult(
                name="consensus_rate", category="swarm",
                status=BenchmarkStatus.NO_DATA, value=None,
                target=f"{self.targets.consensus_rate_min_pct}-{self.targets.consensus_rate_max_pct}%",
                detail=f"Need ≥5 cycles, have {len(history) if history else 0}",
            )

        recent = history[-50:]
        with_proposals = sum(1 for c in recent if c.get("proposals_generated", 0) > 0)
        rate_pct = (with_proposals / len(recent)) * 100

        if rate_pct < self.targets.consensus_rate_min_pct:
            status = BenchmarkStatus.WARN
            detail = f"Too few plans: {round(rate_pct, 1)}%"
        elif rate_pct > self.targets.consensus_rate_max_pct:
            status = BenchmarkStatus.WARN
            detail = f"Rubber-stamping risk: {round(rate_pct, 1)}%"
        else:
            status = BenchmarkStatus.PASS
            detail = f"Healthy: {round(rate_pct, 1)}%"

        return BenchmarkResult(
            name="consensus_rate", category="swarm",
            status=status,
            value={"rate_pct": round(rate_pct, 1), "cycles_sampled": len(recent), "with_proposals": with_proposals},
            target=f"{self.targets.consensus_rate_min_pct}-{self.targets.consensus_rate_max_pct}%",
            detail=detail,
        )


# ════════════════════════════════════════════════════════════════════
# Singleton
# ════════════════════════════════════════════════════════════════════

_collector: Optional[BenchmarkCollector] = None


def get_benchmark_collector() -> BenchmarkCollector:
    global _collector
    if _collector is None:
        _collector = BenchmarkCollector()
    return _collector

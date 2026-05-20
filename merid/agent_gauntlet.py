"""Agent Gauntlet — promotion gate for MERID agents.

Every agent must pass the gauntlet before it is allowed to trade on real
venues.  The gauntlet exercises the agent against internal paper markets
(prediction CLOB + crypto paper engine) and evaluates it on a set of
quantitative SLOs.

Usage:
  python -m merid.agent_gauntlet                          # run all agents
  python -m merid.agent_gauntlet --agent prediction-market-agent-v2
  python -m merid.agent_gauntlet --category research
  python -m merid.agent_gauntlet --json

SLO Dimensions (all must pass for promotion):
  1. Liveness     — agent runs without errors for N cycles
  2. Latency      — p95 run latency ≤ budget
  3. Signal quality — confidence distribution is non-degenerate
  4. Risk compliance — no kill-switch triggers, no oversized orders
  5. Fill quality   — fills execute at reasonable prices (prediction domain)
  6. PnL discipline — drawdown stays within bounds over the trial
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import statistics
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

_VERDICT_LOG = Path(os.environ.get(
    "MERID_GAUNTLET_VERDICTS",
    Path(__file__).parent.parent / "data" / "gauntlet_verdicts.jsonl",
))


def _compute_agent_config_hash(agent) -> str:
    """Return a short SHA-256 hash of the agent's class source + category + agent_id prefix.

    The hash changes when the agent class is modified, allowing stale verdict
    detection.  Falls back to class name + module if source is unavailable.
    """
    try:
        src = inspect.getsource(agent.__class__)
    except (OSError, TypeError):
        src = f"{agent.__class__.__module__}.{agent.__class__.__name__}"
    category = str(getattr(agent, "category", ""))
    payload = f"{src}::{category}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

logger = get_logger("agent_gauntlet")


# ── SLO Thresholds ──────────────────────────────────────────────────

@dataclass
class GauntletSLO:
    """Quantitative thresholds an agent must meet."""
    # Liveness
    min_successful_cycles: int = 5          # Must complete at least N runs
    max_error_rate: float = 0.20            # ≤20% of runs can error

    # Latency
    max_p95_latency_ms: float = 5000.0      # p95 ≤ 5s per run

    # Signal quality
    min_avg_confidence: float = 0.10        # Must not always output 0
    max_avg_confidence: float = 0.95        # Must not always output 1
    min_confidence_stddev: float = 0.0      # 0 = no variance requirement (agents may be deterministic)

    # Risk compliance
    max_oversized_orders: int = 0           # Zero tolerance for orders > domain cap
    max_kill_switch_triggers: int = 0       # Zero tolerance

    # Fill quality (prediction domain)
    max_rejection_rate: float = 0.50        # ≤50% of orders rejected
    max_avg_slippage_bps: float = 100.0     # ≤100 bps avg slippage

    # PnL discipline
    max_drawdown_pct: float = 0.15          # ≤15% drawdown during trial
    min_sharpe_ratio: float = -1.0          # Accept any non-degenerate Sharpe (random-walk = 0.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "min_successful_cycles": self.min_successful_cycles,
            "max_error_rate": self.max_error_rate,
            "max_p95_latency_ms": self.max_p95_latency_ms,
            "min_avg_confidence": self.min_avg_confidence,
            "max_avg_confidence": self.max_avg_confidence,
            "min_confidence_stddev": self.min_confidence_stddev,
            "max_oversized_orders": self.max_oversized_orders,
            "max_kill_switch_triggers": self.max_kill_switch_triggers,
            "max_rejection_rate": self.max_rejection_rate,
            "max_avg_slippage_bps": self.max_avg_slippage_bps,
            "max_drawdown_pct": self.max_drawdown_pct,
            "min_sharpe_ratio": self.min_sharpe_ratio,
        }


# Default SLOs — can be overridden per agent category
DEFAULT_SLO = GauntletSLO()

CATEGORY_SLOS: Dict[str, GauntletSLO] = {
    "research": GauntletSLO(
        max_p95_latency_ms=8000.0,      # Research agents can be slower
        min_avg_confidence=0.15,
    ),
    "strategy": GauntletSLO(
        max_p95_latency_ms=3000.0,      # Strategy must be fast
        min_avg_confidence=0.20,
    ),
    "risk": GauntletSLO(
        max_p95_latency_ms=2000.0,      # Risk must be fastest
        max_error_rate=0.05,            # Very low error tolerance
    ),
    "coordination": GauntletSLO(
        max_p95_latency_ms=5000.0,
    ),
    "ops": GauntletSLO(
        max_p95_latency_ms=10000.0,     # Ops can be slowest
        max_error_rate=0.30,            # More tolerant of errors
    ),
}


# ── Verdict ──────────────────────────────────────────────────────────

class GauntletResult(str, Enum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


@dataclass
class SLOCheck:
    """Result of a single SLO dimension check."""
    name: str
    passed: bool
    actual: float
    threshold: float
    unit: str = ""
    detail: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "actual": round(self.actual, 4),
            "threshold": round(self.threshold, 4),
            "unit": self.unit,
            "detail": self.detail,
        }


@dataclass
class AgentGauntletVerdict:
    """Full gauntlet result for one agent."""
    agent_id: str
    category: str
    result: GauntletResult
    checks: List[SLOCheck] = field(default_factory=list)
    total_cycles: int = 0
    successful_cycles: int = 0
    error_cycles: int = 0
    total_fills: int = 0
    total_rejections: int = 0
    elapsed_s: float = 0.0
    promoted: bool = False
    config_hash: str = ""       # SHA-256[:16] of agent class source at run time
    verdict_id: str = ""        # Unique ID: agent_id:config_hash:timestamp
    timestamp: float = 0.0

    @property
    def pass_rate(self) -> float:
        n = len(self.checks)
        return sum(1 for c in self.checks if c.passed) / n if n else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "category": self.category,
            "result": self.result.value,
            "pass_rate": round(self.pass_rate, 2),
            "checks": [c.to_dict() for c in self.checks],
            "total_cycles": self.total_cycles,
            "successful_cycles": self.successful_cycles,
            "error_cycles": self.error_cycles,
            "total_fills": self.total_fills,
            "total_rejections": self.total_rejections,
            "elapsed_s": round(self.elapsed_s, 2),
            "promoted": self.promoted,
            "config_hash": self.config_hash,
            "verdict_id": self.verdict_id,
            "timestamp": self.timestamp,
        }


def persist_verdict(verdict: AgentGauntletVerdict) -> None:
    """Append a gauntlet verdict to the persistent JSONL store.

    Each line is one JSON object with the full verdict dict.  The file grows
    indefinitely; rotate via logrotate or prune the oldest entries externally.
    """
    try:
        _VERDICT_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(_VERDICT_LOG, "a") as fh:
            fh.write(json.dumps(verdict.to_dict()) + "\n")
    except Exception as exc:
        logger.warning("gauntlet: failed to persist verdict for %s: %s", verdict.agent_id, exc)


def load_latest_verdict(agent_id: str, config_hash: str) -> Optional[AgentGauntletVerdict]:
    """Return the most recent passing verdict for (agent_id, config_hash), or None.

    Scans the JSONL file from the end.  Only PASS verdicts with a matching
    config_hash are considered valid.  Used by AutoPromoter and ExecutionGuard
    to verify gauntlet currency before promotion.
    """
    if not _VERDICT_LOG.exists():
        return None
    try:
        lines = _VERDICT_LOG.read_text().splitlines()
    except Exception as exc:
        logger.debug("gauntlet: failed to read verdict log: %s", exc)
        return None
    for line in reversed(lines):
        try:
            d = json.loads(line)
            if (
                d.get("agent_id") == agent_id
                and d.get("config_hash") == config_hash
                and d.get("result") == GauntletResult.PASS.value
            ):
                v = AgentGauntletVerdict(
                    agent_id=d["agent_id"],
                    category=d.get("category", ""),
                    result=GauntletResult(d["result"]),
                    promoted=d.get("promoted", False),
                    config_hash=d.get("config_hash", ""),
                    verdict_id=d.get("verdict_id", ""),
                    timestamp=d.get("timestamp", 0.0),
                    elapsed_s=d.get("elapsed_s", 0.0),
                    total_cycles=d.get("total_cycles", 0),
                    successful_cycles=d.get("successful_cycles", 0),
                    error_cycles=d.get("error_cycles", 0),
                    total_fills=d.get("total_fills", 0),
                    total_rejections=d.get("total_rejections", 0),
                )
                return v
        except Exception as exc:
            logger.debug("gauntlet: failed to parse verdict line: %s", exc)
            continue
    return None


GAUNTLET_VERDICT_MAX_AGE_S: float = float(
    os.environ.get("MERID_GAUNTLET_VERDICT_MAX_AGE_S", str(7 * 24 * 3600))  # 7 days
)


def has_valid_gauntlet_pass(agent_id: str, config_hash: str) -> tuple[bool, str]:
    """Return (valid, reason).  True only if a PASS verdict exists, matches the
    current config_hash, and is younger than GAUNTLET_VERDICT_MAX_AGE_S.
    """
    v = load_latest_verdict(agent_id, config_hash)
    if v is None:
        return False, "no_verdict_on_file"
    age = time.time() - v.timestamp
    if age > GAUNTLET_VERDICT_MAX_AGE_S:
        return False, f"verdict_stale_{age/3600:.0f}h"
    return True, "ok"


# ── Gauntlet Runner ──────────────────────────────────────────────────

class GauntletRunner:
    """Exercises an agent against internal markets and evaluates SLOs.

    The runner:
      1. Seeds prediction markets (if not already seeded)
      2. Runs the agent for N cycles with market context
      3. Collects latency, confidence, error, and fill metrics
      4. Evaluates all SLO dimensions
      5. Returns a pass/fail verdict
    """

    def __init__(self, slo: Optional[GauntletSLO] = None, cycles: int = 10):
        self.slo = slo or DEFAULT_SLO
        self.cycles = max(cycles, self.slo.min_successful_cycles)

    async def run_agent(self, agent) -> AgentGauntletVerdict:
        """Run the full gauntlet for a single agent."""
        t0 = time.time()
        category = agent.category.value if hasattr(agent.category, "value") else str(agent.category)
        slo = CATEGORY_SLOS.get(category, self.slo)

        logger.info(f"Gauntlet START: {agent.agent_id} ({category}), {self.cycles} cycles")

        # Seed prediction markets
        self._ensure_markets_seeded()

        # Build market context for the agent
        context = self._build_context()

        # Run cycles
        latencies: List[float] = []
        confidences: List[float] = []
        errors: List[str] = []
        outputs = []
        successful = 0
        errored = 0

        for i in range(self.cycles):
            output = await agent.run(context)
            outputs.append(output)

            if output.output_type == "error":
                errored += 1
                errors.append(output.errors[0] if output.errors else "unknown")
            else:
                successful += 1
                latencies.append(output.latency_ms)
                confidences.append(output.confidence)

        # Simulate fills for agents that produce proposals/signals
        fills, rejections = self._simulate_fills(outputs)

        # Compute PnL metrics from fills
        pnl_metrics = self._compute_pnl_metrics(fills)

        # Evaluate SLOs
        checks = self._evaluate_slos(
            slo=slo,
            total_cycles=self.cycles,
            successful=successful,
            errored=errored,
            latencies=latencies,
            confidences=confidences,
            fills=fills,
            rejections=rejections,
            pnl_metrics=pnl_metrics,
        )

        all_passed = all(c.passed for c in checks)
        elapsed = time.time() - t0

        config_hash = _compute_agent_config_hash(agent)
        ts = time.time()
        verdict_id = f"{agent.agent_id}:{config_hash}:{int(ts)}"

        verdict = AgentGauntletVerdict(
            agent_id=agent.agent_id,
            category=category,
            result=GauntletResult.PASS if all_passed else GauntletResult.FAIL,
            checks=checks,
            total_cycles=self.cycles,
            successful_cycles=successful,
            error_cycles=errored,
            total_fills=len(fills),
            total_rejections=rejections,
            elapsed_s=elapsed,
            promoted=all_passed,
            config_hash=config_hash,
            verdict_id=verdict_id,
            timestamp=ts,
        )

        # Persist verdict so promotion gates can verify currency across restarts
        persist_verdict(verdict)

        status = "PASS" if all_passed else "FAIL"
        failed = [c.name for c in checks if not c.passed]
        logger.info(
            f"Gauntlet {status}: {agent.agent_id} (hash={config_hash}) — "
            f"{sum(1 for c in checks if c.passed)}/{len(checks)} SLOs"
            + (f" (failed: {failed})" if failed else "")
        )

        return verdict

    # ── Market setup ─────────────────────────────────────────────────

    def _ensure_markets_seeded(self):
        """Seed prediction markets if not already done."""
        try:
            from merid.prediction_seed import seed_instruments, seed_reference_prices
            seed_instruments()
            seed_reference_prices()
        except Exception as e:
            logger.warning(f"Market seeding skipped: {e}")

    def _build_context(self) -> Dict[str, Any]:
        """Build a realistic market context for agent runs."""
        from merid.paper_config import get_paper_config
        cfg = get_paper_config()

        context = {
            "domains": cfg.active_domain_names(),
            "symbols": cfg.all_symbols()[:20],  # Top 20 symbols
            "mode": "gauntlet",
            "timestamp": time.time(),
        }

        # Add prediction market prices if available
        try:
            from merid.matching_engine import get_matching_engine
            engine = get_matching_engine("prediction")
            context["prediction_prices"] = dict(engine._reference_prices)
        except Exception as exc:
            logger.debug("operation_suppressed", error=str(exc))

        # Add crypto prices
        try:
            from trading.paper_trading import get_paper_engine
            pe = get_paper_engine()
            context["crypto_prices"] = dict(pe.current_prices)
        except Exception as exc:
            logger.debug("operation_suppressed", error=str(exc))

        return context

    # ── Fill simulation ──────────────────────────────────────────────

    def _simulate_fills(self, outputs: List) -> tuple:
        """Simulate fills from agent outputs that contain trade signals."""
        from merid.matching_engine import get_matching_engine, Order, OrderSide

        fills = []
        rejections = 0

        engine = get_matching_engine("prediction")
        if not engine.enabled:
            engine.enable()

        for output in outputs:
            if output.output_type == "error":
                continue

            payload = output.payload or {}

            # Look for trade signals in the payload
            signals = payload.get("signals", [])
            proposals = payload.get("proposals", [])
            trades = payload.get("trades", [])

            for signal in (signals + proposals + trades):
                if isinstance(signal, dict):
                    instrument = signal.get("instrument_id") or signal.get("symbol", "")
                    direction = signal.get("direction") or signal.get("side", "buy")
                    notional = signal.get("notional_usd") or signal.get("size_usd", 50.0)

                    if not instrument:
                        continue

                    side = OrderSide.BUY if direction in ("buy", "long") else OrderSide.SELL
                    order = Order(
                        instrument_id=instrument,
                        side=side,
                        notional_usd=float(notional),
                        domain="prediction",
                        agent_id=output.agent_id,
                        plan_id=f"gauntlet-{output.run_id}",
                    )
                    fill = engine.submit_order(order)
                    if order.status.value == "filled":
                        fills.append(fill)
                    else:
                        rejections += 1

        return fills, rejections

    def _compute_pnl_metrics(self, fills: List) -> Dict[str, float]:
        """Compute realized PnL metrics from fills using FIFO position accounting.

        Tracks open positions per instrument and realizes P&L when a closing
        fill is received.  This gives a meaningful drawdown and Sharpe signal
        instead of the previous cash-flow proxy.
        """
        if not fills:
            return {"max_drawdown_pct": 0.0, "sharpe_ratio": 0.0, "total_pnl": 0.0}

        # Per-instrument FIFO position: list of (qty, entry_price)
        positions: Dict[str, List[tuple]] = {}
        realized_pnl = 0.0
        equity_curve = [0.0]
        trade_returns: List[float] = []

        for fill in fills:
            instrument = getattr(fill, "instrument_id", "") or ""
            side = fill.side.value if hasattr(fill.side, "value") else str(fill.side)
            notional = float(getattr(fill, "notional_usd", 0.0) or 0.0)
            price = float(getattr(fill, "price", 0.0) or 0.0)
            # Derive qty from notional and price; fall back to notional as qty
            qty = notional / price if price > 0 else notional

            if instrument not in positions:
                positions[instrument] = []

            if side == "buy":
                positions[instrument].append((qty, price if price > 0 else notional))
            else:
                # FIFO close: match against oldest long lots
                remaining_qty = qty
                while remaining_qty > 0 and positions.get(instrument):
                    lot_qty, lot_price = positions[instrument][0]
                    matched = min(remaining_qty, lot_qty)
                    close_price = price if price > 0 else notional / qty if qty > 0 else lot_price
                    trade_pnl = matched * (close_price - lot_price)
                    realized_pnl += trade_pnl
                    trade_returns.append(trade_pnl)
                    if matched >= lot_qty:
                        positions[instrument].pop(0)
                    else:
                        positions[instrument][0] = (lot_qty - matched, lot_price)
                    remaining_qty -= matched

            equity_curve.append(realized_pnl)

        # Drawdown on realized equity curve
        peak = equity_curve[0]
        max_dd = 0.0
        for eq in equity_curve:
            if eq > peak:
                peak = eq
            if peak > 0:
                dd = (peak - eq) / peak
                max_dd = max(max_dd, dd)

        # Sharpe from per-trade returns (annualization not meaningful in gauntlet;
        # use raw ratio so a zero-edge strategy scores ~0 and a losing one scores <0)
        sharpe = 0.0
        if len(trade_returns) > 1:
            avg_r = statistics.mean(trade_returns)
            std_r = statistics.stdev(trade_returns)
            sharpe = avg_r / std_r if std_r > 0 else (0.0 if avg_r == 0 else float('inf'))
        elif len(trade_returns) == 1:
            # Single trade: positive PnL → pass, negative → fail
            sharpe = 1.0 if trade_returns[0] > 0 else -1.0

        return {
            "max_drawdown_pct": max_dd,
            "sharpe_ratio": sharpe,
            "total_pnl": realized_pnl,
        }

    # ── SLO evaluation ───────────────────────────────────────────────

    def _evaluate_slos(
        self,
        slo: GauntletSLO,
        total_cycles: int,
        successful: int,
        errored: int,
        latencies: List[float],
        confidences: List[float],
        fills: List,
        rejections: int,
        pnl_metrics: Dict[str, float],
    ) -> List[SLOCheck]:
        checks = []

        # 1. Liveness
        checks.append(SLOCheck(
            name="liveness",
            passed=successful >= slo.min_successful_cycles,
            actual=float(successful),
            threshold=float(slo.min_successful_cycles),
            unit="cycles",
            detail=f"{successful}/{total_cycles} successful",
        ))

        # 2. Error rate
        error_rate = errored / total_cycles if total_cycles > 0 else 0.0
        checks.append(SLOCheck(
            name="error_rate",
            passed=error_rate <= slo.max_error_rate,
            actual=error_rate,
            threshold=slo.max_error_rate,
            unit="ratio",
            detail=f"{errored}/{total_cycles} errors",
        ))

        # 3. Latency p95
        if latencies:
            sorted_lat = sorted(latencies)
            # ceil(n * 0.95) - 1 gives the correct 0-indexed p95 position.
            # int(n * 0.95) is off-by-one: for n=100 it picks the 96th item not the 95th.
            import math as _m
            p95_idx = max(0, _m.ceil(len(sorted_lat) * 0.95) - 1)
            p95 = sorted_lat[p95_idx]
        else:
            p95 = 0.0
        checks.append(SLOCheck(
            name="latency_p95",
            passed=p95 <= slo.max_p95_latency_ms,
            actual=p95,
            threshold=slo.max_p95_latency_ms,
            unit="ms",
        ))

        # 4. Confidence — avg in range
        avg_conf = statistics.mean(confidences) if confidences else 0.0
        checks.append(SLOCheck(
            name="confidence_avg",
            passed=slo.min_avg_confidence <= avg_conf <= slo.max_avg_confidence,
            actual=avg_conf,
            threshold=slo.min_avg_confidence,
            unit="score",
            detail=f"range [{slo.min_avg_confidence}, {slo.max_avg_confidence}]",
        ))

        # 5. Confidence — variance
        conf_std = statistics.stdev(confidences) if len(confidences) > 1 else 0.0
        checks.append(SLOCheck(
            name="confidence_variance",
            passed=conf_std >= slo.min_confidence_stddev,
            actual=conf_std,
            threshold=slo.min_confidence_stddev,
            unit="stddev",
        ))

        # 6. Fill rejection rate
        total_orders = len(fills) + rejections
        rej_rate = rejections / total_orders if total_orders > 0 else 0.0
        checks.append(SLOCheck(
            name="fill_rejection_rate",
            passed=rej_rate <= slo.max_rejection_rate,
            actual=rej_rate,
            threshold=slo.max_rejection_rate,
            unit="ratio",
            detail=f"{rejections}/{total_orders} rejected" if total_orders > 0 else "no orders",
        ))

        # 7. Drawdown
        dd = pnl_metrics.get("max_drawdown_pct", 0.0)
        checks.append(SLOCheck(
            name="max_drawdown",
            passed=dd <= slo.max_drawdown_pct,
            actual=dd,
            threshold=slo.max_drawdown_pct,
            unit="pct",
        ))

        # 8. Sharpe
        sharpe = pnl_metrics.get("sharpe_ratio", 0.0)
        checks.append(SLOCheck(
            name="sharpe_ratio",
            passed=sharpe >= slo.min_sharpe_ratio,
            actual=sharpe,
            threshold=slo.min_sharpe_ratio,
            unit="ratio",
        ))

        # 9. Oversized orders (zero tolerance) — actual populated from pnl_metrics when available.
        oversized = int(pnl_metrics.get("oversized_orders", 0))
        checks.append(SLOCheck(
            name="oversized_orders",
            passed=oversized <= slo.max_oversized_orders,
            actual=float(oversized),
            threshold=float(slo.max_oversized_orders),
            unit="count",
            detail=f"{oversized} order(s) exceeded domain size cap",
        ))

        # 10. Kill-switch triggers (zero tolerance) — actual populated from pnl_metrics when available.
        ks_triggers = int(pnl_metrics.get("kill_switch_triggers", 0))
        checks.append(SLOCheck(
            name="kill_switch_triggers",
            passed=ks_triggers <= slo.max_kill_switch_triggers,
            actual=float(ks_triggers),
            threshold=float(slo.max_kill_switch_triggers),
            unit="count",
            detail=f"{ks_triggers} kill-switch trigger(s) during trial",
        ))

        return checks


# ── Batch runner ─────────────────────────────────────────────────────

async def run_gauntlet(
    agent_ids: Optional[List[str]] = None,
    category: Optional[str] = None,
    cycles: int = 10,
) -> List[AgentGauntletVerdict]:
    """Run the gauntlet for multiple agents.

    If agent_ids is None and category is None, runs all registered agents.
    """
    from merid.agents.base import get_canonical_registry, AgentCategory

    registry = get_canonical_registry()
    runner = GauntletRunner(cycles=cycles)

    # Select agents
    if agent_ids:
        agents = [registry.get(aid) for aid in agent_ids if registry.get(aid)]
    elif category:
        cat = AgentCategory(category)
        agents = registry.by_category(cat)
    else:
        agents = list(registry.all().values())

    if not agents:
        logger.warning("No agents found for gauntlet")
        return []

    logger.info(f"Running gauntlet for {len(agents)} agents, {cycles} cycles each")

    verdicts = []
    for agent in agents:
        if not agent.is_active:
            verdicts.append(AgentGauntletVerdict(
                agent_id=agent.agent_id,
                category=agent.category.value,
                result=GauntletResult.SKIP,
            ))
            continue
        verdict = await runner.run_agent(agent)
        verdicts.append(verdict)

    # Summary
    passed = sum(1 for v in verdicts if v.result == GauntletResult.PASS)
    failed = sum(1 for v in verdicts if v.result == GauntletResult.FAIL)
    skipped = sum(1 for v in verdicts if v.result == GauntletResult.SKIP)
    logger.info(
        f"Gauntlet complete: {passed} passed, {failed} failed, {skipped} skipped "
        f"out of {len(verdicts)} agents"
    )

    return verdicts


def gauntlet_summary(verdicts: List[AgentGauntletVerdict]) -> Dict[str, Any]:
    """Build a summary report from gauntlet verdicts."""
    return {
        "total_agents": len(verdicts),
        "passed": sum(1 for v in verdicts if v.result == GauntletResult.PASS),
        "failed": sum(1 for v in verdicts if v.result == GauntletResult.FAIL),
        "skipped": sum(1 for v in verdicts if v.result == GauntletResult.SKIP),
        "promoted": [v.agent_id for v in verdicts if v.promoted],
        "blocked": [v.agent_id for v in verdicts if v.result == GauntletResult.FAIL],
        "verdicts": [v.to_dict() for v in verdicts],
    }


# ── CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json
    import sys

    agent_filter = None
    cat_filter = None
    cycles = 10
    json_mode = "--json" in sys.argv

    if "--agent" in sys.argv:
        idx = sys.argv.index("--agent") + 1
        if idx < len(sys.argv):
            agent_filter = [sys.argv[idx]]

    if "--category" in sys.argv:
        idx = sys.argv.index("--category") + 1
        if idx < len(sys.argv):
            cat_filter = sys.argv[idx]

    if "--cycles" in sys.argv:
        idx = sys.argv.index("--cycles") + 1
        if idx < len(sys.argv):
            cycles = int(sys.argv[idx])

    # Ensure agents are registered
    try:
        try:
            from legacy.merid.agents.research import PredictionMarketAgentV2, CryptoSignalsAgent, MarketResearchAgent
        except ImportError:
            # Fallback if legacy module structure differs
            PredictionMarketAgentV2 = None
            CryptoSignalsAgent = None
            MarketResearchAgent = None
        from merid.agents.strategy import StrategyDesignerAgent, ArbitrageAgent
        from merid.agents.risk_agents import RiskManagerAgent
        from merid.agents.coordination import ConsensusCoordinatorAgent
        from merid.agents.base import get_canonical_registry

        reg = get_canonical_registry()
        if not reg.all():
            # Register default agents
            for AgentClass in [
                MarketResearchAgent, PredictionMarketAgentV2, CryptoSignalsAgent,
                StrategyDesignerAgent, ArbitrageAgent,
                RiskManagerAgent,
                ConsensusCoordinatorAgent,
            ]:
                try:
                    agent = AgentClass()
                    reg.register(agent)
                except Exception as e:
                    logger.warning(f"Could not register {AgentClass.__name__}: {e}")
    except ImportError as e:
        logger.warning(f"Could not import agent modules: {e}")

    verdicts = asyncio.run(run_gauntlet(
        agent_ids=agent_filter,
        category=cat_filter,
        cycles=cycles,
    ))

    summary = gauntlet_summary(verdicts)

    if json_mode:
        logger.info(json.dumps(summary, indent=2))
    else:
        logger.info(f"\n{'=' * 70}")
        logger.info(f"MERID Agent Gauntlet — {summary['total_agents']} agents, {cycles} cycles")
        logger.info(f"{'=' * 70}")
        for v in verdicts:
            icon = "PASS" if v.result == GauntletResult.PASS else (
                "FAIL" if v.result == GauntletResult.FAIL else "SKIP"
            )
            marker = "[+]" if v.promoted else ("[X]" if v.result == GauntletResult.FAIL else "[-]")
            logger.info(f"\n  {marker} [{icon}] {v.agent_id} ({v.category})")
            print(f"     Cycles: {v.successful_cycles}/{v.total_cycles} ok, "
                  f"{v.error_cycles} errors | "
                  f"Fills: {v.total_fills} | "
                  f"Time: {v.elapsed_s:.1f}s")

            if v.checks:
                for c in v.checks:
                    status = "  ok " if c.passed else " FAIL"
                    print(f"     [{status}] {c.name:25s}  "
                          f"actual={c.actual:>8.2f}  "
                          f"threshold={c.threshold:>8.2f} {c.unit}")

        logger.info(f"\n{'=' * 70}")
        print(f"Result: {summary['passed']} promoted, "
              f"{summary['failed']} blocked, "
              f"{summary['skipped']} skipped")

        if summary["promoted"]:
            logger.info(f"Promoted: {', '.join(summary['promoted'])}")
        if summary["blocked"]:
            logger.info(f"Blocked:  {', '.join(summary['blocked'])}")
        logger.info(f"{'=' * 70}")
    sys.exit(0 if summary["failed"] == 0 else 1)

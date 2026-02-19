"""Performance Comparator — Side-by-side backtest → paper → live metrics.

Compares PF, expectancy, drawdown, win rate, and other key metrics across
the three stages of the promotion pipeline.  Flags consistent live
underperformance as a signal to revisit simulator assumptions or Kelly
sizing aggressiveness.

Usage::

    comp = PerformanceComparator()
    comp.register_backtest("BTC_HOURLY", backtest_metrics)
    comp.register_paper("BTC_HOURLY", paper_metrics)
    comp.register_live("BTC_HOURLY", live_metrics)
    report = comp.compare("BTC_HOURLY")
    full = comp.full_report()
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.performance_comparator")


# ── Stage metrics ────────────────────────────────────────────────────────

@dataclass
class StageMetrics:
    """Key performance metrics for one agent in one stage."""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    gross_wins_cents: float = 0.0
    gross_losses_cents: float = 0.0
    fees_cents: float = 0.0
    net_pnl_cents: float = 0.0
    high_water_mark_cents: float = 0.0
    max_drawdown_cents: float = 0.0
    trade_pnls_cents: List[float] = field(default_factory=list)

    @property
    def win_rate_pct(self) -> float:
        total = self.winning_trades + self.losing_trades
        return (self.winning_trades / total * 100) if total > 0 else 0.0

    @property
    def profit_factor(self) -> float:
        if self.gross_losses_cents <= 0:
            return float("inf") if self.gross_wins_cents > 0 else 0.0
        return self.gross_wins_cents / self.gross_losses_cents

    @property
    def expectancy_cents(self) -> float:
        total = self.winning_trades + self.losing_trades
        if total == 0:
            return 0.0
        avg_win = self.gross_wins_cents / self.winning_trades if self.winning_trades > 0 else 0.0
        avg_loss = self.gross_losses_cents / self.losing_trades if self.losing_trades > 0 else 0.0
        wr = self.winning_trades / total
        return wr * avg_win - (1.0 - wr) * avg_loss

    @property
    def drawdown_pct(self) -> float:
        if self.high_water_mark_cents <= 0:
            return 0.0
        return (self.max_drawdown_cents / self.high_water_mark_cents) * 100

    @property
    def net_pnl_usd(self) -> float:
        return self.net_pnl_cents / 100.0

    @property
    def sharpe_ratio(self) -> float:
        """Sharpe ratio computed from per-trade PnL series.

        Uses mean / stdev of trade PnLs (excess return over 0).
        Requires at least 2 trades for a meaningful result.
        """
        if len(self.trade_pnls_cents) < 2:
            return 0.0
        n = len(self.trade_pnls_cents)
        mean = sum(self.trade_pnls_cents) / n
        variance = sum((x - mean) ** 2 for x in self.trade_pnls_cents) / (n - 1)
        stdev = math.sqrt(variance) if variance > 0 else 0.0
        if stdev <= 0:
            return 0.0
        return mean / stdev

    @property
    def sortino_ratio(self) -> float:
        """Sortino ratio — like Sharpe but only penalizes downside vol."""
        if len(self.trade_pnls_cents) < 2:
            return 0.0
        n = len(self.trade_pnls_cents)
        mean = sum(self.trade_pnls_cents) / n
        downside = [x for x in self.trade_pnls_cents if x < 0]
        if not downside:
            return float("inf") if mean > 0 else 0.0
        down_var = sum(x ** 2 for x in downside) / len(downside)
        down_dev = math.sqrt(down_var) if down_var > 0 else 0.0
        if down_dev <= 0:
            return 0.0
        return mean / down_dev

    @property
    def returns_volatility_pct(self) -> float:
        """Standard deviation of per-trade PnL as percentage of mean abs PnL."""
        if len(self.trade_pnls_cents) < 2:
            return 0.0
        n = len(self.trade_pnls_cents)
        mean = sum(self.trade_pnls_cents) / n
        variance = sum((x - mean) ** 2 for x in self.trade_pnls_cents) / (n - 1)
        return math.sqrt(variance) if variance > 0 else 0.0

    @property
    def calmar_ratio(self) -> float:
        """Calmar ratio — annualized return / max drawdown.

        Uses total return over trade count as a proxy for annualized return.
        Requires drawdown > 0 for a meaningful result.
        """
        if self.drawdown_pct <= 0:
            return float("inf") if self.net_pnl_cents > 0 else 0.0
        if self.high_water_mark_cents <= 0:
            return 0.0
        total_return_pct = (self.net_pnl_cents / self.high_water_mark_cents) * 100
        return total_return_pct / self.drawdown_pct

    def to_dict(self) -> Dict[str, Any]:
        pf = self.profit_factor
        sr = self.sharpe_ratio
        sortino = self.sortino_ratio
        calmar = self.calmar_ratio
        return {
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "win_rate_pct": round(self.win_rate_pct, 1),
            "profit_factor": round(pf, 2) if pf != float("inf") else "inf",
            "expectancy_cents": round(self.expectancy_cents, 2),
            "expectancy_usd": round(self.expectancy_cents / 100, 4),
            "net_pnl_usd": round(self.net_pnl_usd, 2),
            "fees_usd": round(self.fees_cents / 100, 2),
            "max_drawdown_pct": round(self.drawdown_pct, 2),
            "max_drawdown_usd": round(self.max_drawdown_cents / 100, 2),
            "sharpe_ratio": round(sr, 3) if sr != float("inf") else "inf",
            "sortino_ratio": round(sortino, 3) if sortino != float("inf") else "inf",
            "calmar_ratio": round(calmar, 3) if calmar != float("inf") else "inf",
            "returns_volatility_cents": round(self.returns_volatility_pct, 2),
        }


# ── Comparison thresholds ────────────────────────────────────────────────

@dataclass
class DegradationThresholds:
    """Thresholds for flagging performance degradation between stages."""
    # PF drop: if live PF < paper PF × (1 - pf_drop_pct/100), flag it
    pf_drop_pct: float = 20.0

    # Expectancy drop: if live expectancy < paper × (1 - exp_drop_pct/100)
    expectancy_drop_pct: float = 30.0

    # Win rate drop (absolute percentage points)
    win_rate_drop_pp: float = 10.0

    # Drawdown increase (absolute percentage points)
    drawdown_increase_pp: float = 5.0

    # Minimum trades in both stages to compare
    min_trades_for_comparison: int = 30


DEFAULT_THRESHOLDS = DegradationThresholds()


# ── Comparison result ────────────────────────────────────────────────────

@dataclass
class StageComparison:
    """Comparison between two stages (e.g. paper vs live)."""
    from_stage: str
    to_stage: str
    pf_delta: float = 0.0
    expectancy_delta_cents: float = 0.0
    win_rate_delta_pp: float = 0.0
    drawdown_delta_pp: float = 0.0
    alerts: List[str] = field(default_factory=list)
    sufficient_data: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from": self.from_stage,
            "to": self.to_stage,
            "pf_delta": round(self.pf_delta, 2),
            "expectancy_delta_cents": round(self.expectancy_delta_cents, 2),
            "win_rate_delta_pp": round(self.win_rate_delta_pp, 1),
            "drawdown_delta_pp": round(self.drawdown_delta_pp, 1),
            "alerts": self.alerts,
            "sufficient_data": self.sufficient_data,
        }


# ── Comparator ───────────────────────────────────────────────────────────

class PerformanceComparator:
    """Compare performance across backtest → paper → live stages."""

    def __init__(
        self,
        thresholds: Optional[DegradationThresholds] = None,
    ) -> None:
        self._thresholds = thresholds or DEFAULT_THRESHOLDS
        self._backtest: Dict[str, StageMetrics] = {}
        self._paper: Dict[str, StageMetrics] = {}
        self._live: Dict[str, StageMetrics] = {}

    # ── Registration ─────────────────────────────────────────────────

    def register_backtest(self, agent_name: str, metrics: StageMetrics) -> None:
        self._backtest[agent_name] = metrics

    def register_paper(self, agent_name: str, metrics: StageMetrics) -> None:
        self._paper[agent_name] = metrics

    def register_live(self, agent_name: str, metrics: StageMetrics) -> None:
        self._live[agent_name] = metrics

    def register_from_dict(
        self, agent_name: str, stage: str, data: Dict[str, Any]
    ) -> None:
        """Register metrics from a dict (e.g. from PaperSession.summary())."""
        m = StageMetrics(
            total_trades=data.get("total_trades", 0),
            winning_trades=data.get("winning_trades", 0),
            losing_trades=data.get("losing_trades", 0),
            gross_wins_cents=data.get("gross_wins_cents", 0.0),
            gross_losses_cents=data.get("gross_losses_cents", 0.0),
            fees_cents=data.get("fees_cents", 0.0),
            net_pnl_cents=data.get("net_pnl_cents", 0.0),
            high_water_mark_cents=data.get("high_water_mark_cents", 0.0),
            max_drawdown_cents=data.get("max_drawdown_cents", 0.0),
        )
        if stage == "backtest":
            self.register_backtest(agent_name, m)
        elif stage == "paper":
            self.register_paper(agent_name, m)
        elif stage == "live":
            self.register_live(agent_name, m)

    # ── Comparison ───────────────────────────────────────────────────

    def _compare_stages(
        self,
        from_metrics: Optional[StageMetrics],
        to_metrics: Optional[StageMetrics],
        from_name: str,
        to_name: str,
    ) -> StageComparison:
        """Compare two stages and flag degradation."""
        th = self._thresholds
        comp = StageComparison(from_stage=from_name, to_stage=to_name)

        if from_metrics is None or to_metrics is None:
            comp.sufficient_data = False
            comp.alerts.append(f"Missing {from_name} or {to_name} data")
            return comp

        if (
            from_metrics.total_trades < th.min_trades_for_comparison
            or to_metrics.total_trades < th.min_trades_for_comparison
        ):
            comp.sufficient_data = False
            comp.alerts.append(
                f"Insufficient trades: {from_name}={from_metrics.total_trades}, "
                f"{to_name}={to_metrics.total_trades} (min={th.min_trades_for_comparison})"
            )
            return comp

        # PF comparison
        from_pf = from_metrics.profit_factor
        to_pf = to_metrics.profit_factor
        if from_pf != float("inf") and to_pf != float("inf"):
            comp.pf_delta = to_pf - from_pf
            if from_pf > 0 and to_pf < from_pf * (1 - th.pf_drop_pct / 100):
                comp.alerts.append(
                    f"PF degraded: {from_name}={from_pf:.2f} → {to_name}={to_pf:.2f} "
                    f"(>{th.pf_drop_pct:.0f}% drop)"
                )

        # Expectancy comparison
        from_exp = from_metrics.expectancy_cents
        to_exp = to_metrics.expectancy_cents
        comp.expectancy_delta_cents = to_exp - from_exp
        if from_exp > 0 and to_exp < from_exp * (1 - th.expectancy_drop_pct / 100):
            comp.alerts.append(
                f"Expectancy degraded: {from_name}={from_exp:.1f}c → {to_name}={to_exp:.1f}c "
                f"(>{th.expectancy_drop_pct:.0f}% drop)"
            )
        if to_exp < 0 and from_exp >= 0:
            comp.alerts.append(
                f"Expectancy turned negative in {to_name}: {to_exp:.1f}c"
            )

        # Win rate comparison
        comp.win_rate_delta_pp = to_metrics.win_rate_pct - from_metrics.win_rate_pct
        if comp.win_rate_delta_pp < -th.win_rate_drop_pp:
            comp.alerts.append(
                f"Win rate dropped: {from_name}={from_metrics.win_rate_pct:.1f}% → "
                f"{to_name}={to_metrics.win_rate_pct:.1f}% "
                f"(>{th.win_rate_drop_pp:.0f}pp drop)"
            )

        # Drawdown comparison
        comp.drawdown_delta_pp = to_metrics.drawdown_pct - from_metrics.drawdown_pct
        if comp.drawdown_delta_pp > th.drawdown_increase_pp:
            comp.alerts.append(
                f"Drawdown increased: {from_name}={from_metrics.drawdown_pct:.1f}% → "
                f"{to_name}={to_metrics.drawdown_pct:.1f}% "
                f"(>{th.drawdown_increase_pp:.0f}pp increase)"
            )

        return comp

    def compare(self, agent_name: str) -> Dict[str, Any]:
        """Compare all available stages for one agent.

        Returns dict with backtest→paper, paper→live, and backtest→live
        comparisons plus per-stage metrics.
        """
        bt = self._backtest.get(agent_name)
        pp = self._paper.get(agent_name)
        lv = self._live.get(agent_name)

        comparisons = {}
        all_alerts: List[str] = []

        if bt and pp:
            c = self._compare_stages(bt, pp, "backtest", "paper")
            comparisons["backtest_vs_paper"] = c.to_dict()
            all_alerts.extend(c.alerts)

        if pp and lv:
            c = self._compare_stages(pp, lv, "paper", "live")
            comparisons["paper_vs_live"] = c.to_dict()
            all_alerts.extend(c.alerts)

        if bt and lv:
            c = self._compare_stages(bt, lv, "backtest", "live")
            comparisons["backtest_vs_live"] = c.to_dict()
            all_alerts.extend(c.alerts)

        stages = {}
        if bt:
            stages["backtest"] = bt.to_dict()
        if pp:
            stages["paper"] = pp.to_dict()
        if lv:
            stages["live"] = lv.to_dict()

        return {
            "agent": agent_name,
            "stages": stages,
            "comparisons": comparisons,
            "alerts": all_alerts,
            "alert_count": len(all_alerts),
        }

    def full_report(self) -> Dict[str, Any]:
        """Generate a full report across all registered agents."""
        all_agents = set()
        all_agents.update(self._backtest.keys())
        all_agents.update(self._paper.keys())
        all_agents.update(self._live.keys())

        reports = {}
        total_alerts = 0
        agents_with_alerts: List[str] = []

        for agent in sorted(all_agents):
            report = self.compare(agent)
            reports[agent] = report
            if report["alert_count"] > 0:
                total_alerts += report["alert_count"]
                agents_with_alerts.append(agent)

        return {
            "agents": reports,
            "total_agents": len(all_agents),
            "total_alerts": total_alerts,
            "agents_with_alerts": agents_with_alerts,
            "recommendation": self._recommendation(total_alerts, len(all_agents)),
        }

    def _recommendation(self, total_alerts: int, total_agents: int) -> str:
        if total_alerts == 0:
            return "All stages tracking within tolerance. Safe to continue."
        if total_alerts <= 2:
            return "Minor degradation detected. Monitor closely."
        if total_alerts <= total_agents:
            return "Moderate degradation. Consider reducing Kelly fraction."
        return (
            "Significant degradation across multiple agents. "
            "Revisit simulator assumptions and Kelly sizing."
        )

    # ── Registered agents ────────────────────────────────────────────

    @property
    def agents(self) -> List[str]:
        all_agents = set()
        all_agents.update(self._backtest.keys())
        all_agents.update(self._paper.keys())
        all_agents.update(self._live.keys())
        return sorted(all_agents)

"""Monte Carlo Risk-of-Ruin Simulator for Kelly-Sized Binary Trading.

Runs N simulated equity paths at different Kelly fractions to estimate:
- Ruin probability (equity falling below a threshold)
- Median and worst-case drawdowns
- Terminal equity distribution
- Optimal fraction for a target ruin probability

Usage::

    sim = RuinSimulator(win_rate=0.55, win_payout_cents=45, loss_amount_cents=55)
    result = sim.run(fractions=[1.0, 0.5, 0.25], n_paths=10000, n_trades=500)
    result.best_fraction(max_ruin_pct=2.0)
"""

from __future__ import annotations

import random
import statistics
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import math

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.ruin_simulator")


@dataclass
class PathStats:
    """Statistics for one Kelly fraction across all simulated paths."""
    fraction: float
    n_paths: int
    n_trades: int

    # Ruin
    ruin_count: int = 0
    ruin_pct: float = 0.0

    # Terminal equity
    terminal_mean: float = 0.0
    terminal_median: float = 0.0
    terminal_p5: float = 0.0   # 5th percentile (worst case)
    terminal_p95: float = 0.0  # 95th percentile (best case)

    # Drawdown
    max_dd_mean_pct: float = 0.0
    max_dd_median_pct: float = 0.0
    max_dd_p95_pct: float = 0.0  # 95th percentile of max drawdowns

    # Risk-adjusted metrics (median across paths)
    sharpe_median: float = 0.0
    sortino_median: float = 0.0
    calmar_median: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fraction": self.fraction,
            "n_paths": self.n_paths,
            "n_trades": self.n_trades,
            "ruin_count": self.ruin_count,
            "ruin_pct": round(self.ruin_pct, 2),
            "terminal_mean": round(self.terminal_mean, 2),
            "terminal_median": round(self.terminal_median, 2),
            "terminal_p5": round(self.terminal_p5, 2),
            "terminal_p95": round(self.terminal_p95, 2),
            "max_dd_mean_pct": round(self.max_dd_mean_pct, 2),
            "max_dd_median_pct": round(self.max_dd_median_pct, 2),
            "max_dd_p95_pct": round(self.max_dd_p95_pct, 2),
            "sharpe_median": round(self.sharpe_median, 3),
            "sortino_median": round(self.sortino_median, 3),
            "calmar_median": round(self.calmar_median, 3),
        }


@dataclass
class SimulationResult:
    """Result of a multi-fraction Monte Carlo simulation."""
    win_rate: float
    win_payout_cents: int
    loss_amount_cents: int
    initial_equity: float
    ruin_threshold: float
    fee_cents: int
    results: List[PathStats] = field(default_factory=list)

    def best_fraction(self, max_ruin_pct: float = 2.0) -> Optional[float]:
        """Find the largest fraction with ruin probability <= max_ruin_pct.

        Among qualifying fractions, pick the one with the highest
        terminal median equity.
        """
        candidates = [r for r in self.results if r.ruin_pct <= max_ruin_pct]
        if not candidates:
            return None
        best = max(candidates, key=lambda r: r.terminal_median)
        return best.fraction

    def best_fraction_for_sharpe(
        self,
        min_sharpe: float = 2.0,
        max_dd_pct: float = 25.0,
    ) -> Optional[float]:
        """Find the largest fraction meeting Sharpe and drawdown targets.

        Args:
            min_sharpe: Minimum median Sharpe ratio required.
            max_dd_pct: Maximum median drawdown percentage allowed.

        Returns:
            Largest qualifying fraction, or None.
        """
        candidates = [
            r for r in self.results
            if r.sharpe_median >= min_sharpe
            and r.max_dd_median_pct <= max_dd_pct
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda r: r.fraction).fraction

    def to_dict(self) -> Dict[str, Any]:
        return {
            "win_rate": self.win_rate,
            "win_payout_cents": self.win_payout_cents,
            "loss_amount_cents": self.loss_amount_cents,
            "initial_equity": self.initial_equity,
            "ruin_threshold": self.ruin_threshold,
            "fee_cents": self.fee_cents,
            "fractions": [r.to_dict() for r in self.results],
            "best_fraction_2pct_ruin": self.best_fraction(2.0),
            "best_fraction_sharpe2_dd25": self.best_fraction_for_sharpe(2.0, 25.0),
        }


class RuinSimulator:
    """Monte Carlo simulator for Kelly-fraction risk-of-ruin analysis.

    Models a simple binary trading game:
    - Each trade wins with probability `win_rate`
    - Win pays `win_payout_cents`, loss costs `loss_amount_cents`
    - Fees are deducted per trade
    - Position size = fraction × equity / risk_per_contract
    """

    def __init__(
        self,
        win_rate: float = 0.55,
        win_payout_cents: int = 45,
        loss_amount_cents: int = 55,
        fee_cents: int = 3,
        initial_equity: float = 10_000.0,
        ruin_threshold_pct: float = 20.0,
        seed: Optional[int] = None,
    ) -> None:
        """
        Args:
            win_rate: Probability of winning each trade (0-1).
            win_payout_cents: Cents won per contract on win.
            loss_amount_cents: Cents lost per contract on loss.
            fee_cents: Fee per contract per trade.
            initial_equity: Starting equity in USD.
            ruin_threshold_pct: Ruin = equity drops below this % of initial.
        """
        self._win_rate = win_rate
        self._win_payout = win_payout_cents
        self._loss_amount = loss_amount_cents
        self._fee = fee_cents
        self._initial_equity = initial_equity
        self._ruin_threshold = initial_equity * (ruin_threshold_pct / 100.0)
        self._ruin_threshold_pct = ruin_threshold_pct
        self._rng = random.Random(seed)

    def _simulate_path(
        self, fraction: float, n_trades: int,
    ) -> Tuple[float, float, List[float]]:
        """Simulate one equity path.

        Returns:
            (terminal_equity_usd, max_drawdown_pct, per_trade_returns)
        """
        equity = self._initial_equity
        hwm = equity
        max_dd_pct = 0.0
        ruined = False
        returns: List[float] = []

        risk_per_contract_cents = self._loss_amount + self._fee

        for _ in range(n_trades):
            if equity <= 0:
                ruined = True
                break

            prev_equity = equity

            # Position size: fraction of equity
            equity_cents = equity * 100
            bankroll_to_risk_cents = fraction * equity_cents
            contracts = max(1, int(bankroll_to_risk_cents / risk_per_contract_cents))

            # Simulate outcome
            if self._rng.random() < self._win_rate:
                pnl_cents = (self._win_payout - self._fee) * contracts
            else:
                pnl_cents = -(self._loss_amount + self._fee) * contracts

            equity += pnl_cents / 100.0

            # Track per-trade return
            if prev_equity > 0:
                returns.append((equity - prev_equity) / prev_equity)

            # Track drawdown
            if equity > hwm:
                hwm = equity
            dd = (hwm - equity) / hwm * 100 if hwm > 0 else 0
            if dd > max_dd_pct:
                max_dd_pct = dd

            # Check ruin
            if equity <= self._ruin_threshold:
                ruined = True
                break

        return equity, max_dd_pct, returns

    def run(
        self,
        fractions: Optional[List[float]] = None,
        n_paths: int = 5000,
        n_trades: int = 500,
    ) -> SimulationResult:
        """Run Monte Carlo simulation across multiple Kelly fractions.

        Args:
            fractions: List of Kelly fractions to test (e.g. [1.0, 0.5, 0.25]).
            n_paths: Number of simulated paths per fraction.
            n_trades: Number of trades per path.

        Returns:
            SimulationResult with per-fraction statistics.
        """
        if fractions is None:
            fractions = [1.0, 0.75, 0.5, 0.4, 0.3, 0.25, 0.15, 0.1]

        result = SimulationResult(
            win_rate=self._win_rate,
            win_payout_cents=self._win_payout,
            loss_amount_cents=self._loss_amount,
            initial_equity=self._initial_equity,
            ruin_threshold=self._ruin_threshold,
            fee_cents=self._fee,
        )

        for frac in fractions:
            terminals = []
            max_dds = []
            sharpes = []
            sortinos = []
            calmars = []
            ruin_count = 0

            for _ in range(n_paths):
                terminal, max_dd, returns = self._simulate_path(frac, n_trades)
                terminals.append(terminal)
                max_dds.append(max_dd)
                if terminal <= self._ruin_threshold:
                    ruin_count += 1
                sharpes.append(self._path_sharpe(returns))
                sortinos.append(self._path_sortino(returns))
                calmars.append(self._path_calmar(terminal, max_dd))

            terminals.sort()
            max_dds.sort()

            n = len(terminals)
            p5_idx = max(0, int(n * 0.05) - 1)
            p95_idx = min(n - 1, int(n * 0.95))

            # Median of risk-adjusted metrics (filter inf for median calc)
            finite_sharpes = [s for s in sharpes if math.isfinite(s)]
            finite_sortinos = [s for s in sortinos if math.isfinite(s)]
            finite_calmars = [s for s in calmars if math.isfinite(s)]

            stats = PathStats(
                fraction=frac,
                n_paths=n_paths,
                n_trades=n_trades,
                ruin_count=ruin_count,
                ruin_pct=ruin_count / n_paths * 100,
                terminal_mean=statistics.mean(terminals),
                terminal_median=statistics.median(terminals),
                terminal_p5=terminals[p5_idx],
                terminal_p95=terminals[p95_idx],
                max_dd_mean_pct=statistics.mean(max_dds),
                max_dd_median_pct=statistics.median(max_dds),
                max_dd_p95_pct=max_dds[min(n - 1, int(n * 0.95))],
                sharpe_median=statistics.median(finite_sharpes) if finite_sharpes else 0.0,
                sortino_median=statistics.median(finite_sortinos) if finite_sortinos else 0.0,
                calmar_median=statistics.median(finite_calmars) if finite_calmars else 0.0,
            )
            result.results.append(stats)

            logger.debug(
                f"[ruin-sim] f={frac:.2f}: ruin={stats.ruin_pct:.1f}%, "
                f"median_equity=${stats.terminal_median:.0f}, "
                f"median_dd={stats.max_dd_median_pct:.1f}%, "
                f"sharpe={stats.sharpe_median:.2f}"
            )

        return result

    @staticmethod
    def _path_sharpe(returns: List[float]) -> float:
        if len(returns) < 2:
            return 0.0
        n = len(returns)
        mean = sum(returns) / n
        var = sum((r - mean) ** 2 for r in returns) / (n - 1)
        std = math.sqrt(var) if var > 0 else 0.0
        return mean / std if std > 0 else 0.0

    @staticmethod
    def _path_sortino(returns: List[float]) -> float:
        if len(returns) < 2:
            return 0.0
        mean = sum(returns) / len(returns)
        downside = [r for r in returns if r < 0]
        if not downside:
            return float('inf') if mean > 0 else 0.0
        down_var = sum(r ** 2 for r in downside) / len(downside)
        down_dev = math.sqrt(down_var) if down_var > 0 else 0.0
        return mean / down_dev if down_dev > 0 else 0.0

    def _path_calmar(self, terminal: float, max_dd_pct: float) -> float:
        if max_dd_pct <= 0:
            return float('inf') if terminal > self._initial_equity else 0.0
        total_return_pct = (terminal - self._initial_equity) / self._initial_equity * 100
        return total_return_pct / max_dd_pct

    def compare_fractions(
        self,
        fractions: Optional[List[float]] = None,
        n_paths: int = 5000,
        n_trades: int = 500,
    ) -> Dict[str, Any]:
        """Run simulation and return a comparison table."""
        result = self.run(fractions, n_paths, n_trades)
        return result.to_dict()

    def optimize_for_sharpe(
        self,
        min_sharpe: float = 2.0,
        max_dd_pct: float = 25.0,
        n_paths: int = 5000,
        n_trades: int = 500,
        granularity: int = 10,
    ) -> Dict[str, Any]:
        """Grid-search Kelly multipliers to find the best risk-adjusted fraction.

        Tests fractions from 0.1 to 1.0 in steps of 1/granularity,
        then returns the largest fraction meeting the Sharpe and
        drawdown targets.

        Args:
            min_sharpe: Minimum median Sharpe required.
            max_dd_pct: Maximum median drawdown allowed.
            n_paths: Paths per fraction.
            n_trades: Trades per path.
            granularity: Number of steps (10 = test 0.1, 0.2, ..., 1.0).

        Returns:
            Dict with best fraction and full comparison data.
        """
        fractions = [round((i + 1) / granularity, 3) for i in range(granularity)]
        result = self.run(fractions, n_paths, n_trades)
        best = result.best_fraction_for_sharpe(min_sharpe, max_dd_pct)
        d = result.to_dict()
        d["optimization"] = {
            "target_sharpe": min_sharpe,
            "target_max_dd_pct": max_dd_pct,
            "best_fraction": best,
        }
        return d

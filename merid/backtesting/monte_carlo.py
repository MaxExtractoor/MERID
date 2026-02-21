"""
Monte Carlo simulation on backtested return series.

Used by KalshiBotLifecycle.on_backtest_complete() to gate advancement
from BACKTEST → FORWARD_PAPER.  Requires p5 > 0.9 and prob_loss < 0.5
by default; thresholds are configurable.

Usage:
    from merid.backtesting.monte_carlo import monte_carlo_equity, monte_carlo_risk_metrics

    eq_final = monte_carlo_equity(np.array(report.returns), days=252, paths=1000)
    metrics  = monte_carlo_risk_metrics(eq_final)
    if metrics["p5"] > 0.9 and metrics["prob_loss"] < 0.4:
        lifecycle.on_backtest_complete(report, metrics)
"""

from __future__ import annotations

import math
import random
from typing import Dict, List, Optional


# ---------------------------------------------------------------------------
# Core simulation (pure Python — no numpy required at import time)
# ---------------------------------------------------------------------------

def monte_carlo_equity(
    returns: List[float],
    days: int = 252,
    paths: int = 1000,
    seed: Optional[int] = None,
) -> List[float]:
    """
    Simulate `paths` equity paths of length `days` by resampling from
    the historical return distribution (parametric normal approximation).

    Returns a list of final equity values (starting equity = 1.0).
    Returns [1.0] * paths if returns has zero variance.
    """
    n = len(returns)
    if n == 0:
        return [1.0] * paths

    mu = sum(returns) / n
    variance = sum((r - mu) ** 2 for r in returns) / n
    sigma = math.sqrt(variance) if variance > 0 else 0.0

    if sigma == 0.0:
        # Degenerate: all returns identical
        final = (1.0 + mu) ** days
        return [final] * paths

    rng = random.Random(seed)
    eq_final: List[float] = []

    for _ in range(paths):
        eq = 1.0
        for _ in range(days):
            r = rng.gauss(mu, sigma)
            eq *= (1.0 + r)
            if eq <= 0:
                eq = 0.0
                break
        eq_final.append(eq)

    return eq_final


def monte_carlo_risk_metrics(eq_final: List[float]) -> Dict[str, float]:
    """
    Compute summary risk metrics from a Monte Carlo final-equity distribution.

    Returns:
        median      — median final equity (1.0 = breakeven)
        p5          — 5th percentile final equity (tail risk)
        p25         — 25th percentile
        prob_loss   — fraction of paths ending below 1.0 (loss)
        prob_ruin   — fraction of paths ending below 0.5 (severe loss)
    """
    if not eq_final:
        return {"median": 1.0, "p5": 1.0, "p25": 1.0, "prob_loss": 0.0, "prob_ruin": 0.0}

    sorted_eq = sorted(eq_final)
    n = len(sorted_eq)

    def percentile(p: float) -> float:
        idx = max(0, min(n - 1, int(p / 100 * n)))
        return sorted_eq[idx]

    median = percentile(50)
    p5 = percentile(5)
    p25 = percentile(25)
    prob_loss = sum(1 for e in eq_final if e < 1.0) / n
    prob_ruin = sum(1 for e in eq_final if e < 0.5) / n

    return {
        "median": median,
        "p5": p5,
        "p25": p25,
        "prob_loss": prob_loss,
        "prob_ruin": prob_ruin,
    }


# ---------------------------------------------------------------------------
# Kelly-based Monte Carlo simulation
# ---------------------------------------------------------------------------

def mc_kelly_kalshi(
    equity0: float,
    yes_price_cents: int,
    est_prob: float,
    frac: float = 0.25,
    n_trades: int = 200,
    n_paths: int = 5_000,
    ruin_level: float = 0.30,
    seed: Optional[int] = None,
) -> Dict[str, float]:
    """
    Simulate equity paths using fractional Kelly sizing on a Kalshi YES bet.

    Each path plays n_trades sequential bets at the fractional Kelly fraction,
    stopping early if equity falls to ruin_level × equity0.

    Pure Python — no numpy required.

    Args:
        equity0:        Starting equity.
        yes_price_cents: Kalshi yes price in cents (1..99).
        est_prob:       Estimated true win probability.
        frac:           Kelly fraction (default 0.25 = quarter-Kelly).
        n_trades:       Trades per path.
        n_paths:        Number of simulation paths.
        ruin_level:     Fraction of equity0 considered ruin (default 0.30).
        seed:           Optional RNG seed.

    Returns:
        {"prob_ruin": float, "median_eq": float, "mean_eq": float,
         "p5_eq": float, "f_kelly_used": float}
    """
    x = yes_price_cents / 100.0
    if x <= 0 or x >= 1 or est_prob <= 0 or est_prob >= 1:
        return {"prob_ruin": 1.0, "median_eq": 0.0, "mean_eq": 0.0,
                "p5_eq": 0.0, "f_kelly_used": 0.0}

    b = (1.0 - x) / x
    q = 1.0 - est_prob
    f_kelly = max(0.0, (b * est_prob - q) / b)
    f_use = min(f_kelly * frac, 0.05)

    ruin_threshold = equity0 * ruin_level
    rng = random.Random(seed)
    final_equities: List[float] = []

    for _ in range(n_paths):
        eq = equity0
        for _ in range(n_trades):
            bet = eq * f_use
            if rng.random() < est_prob:
                eq += bet * b
            else:
                eq -= bet
            if eq <= ruin_threshold:
                break
        final_equities.append(eq)

    final_equities.sort()
    total = len(final_equities)
    prob_ruin = sum(1 for e in final_equities if e <= ruin_threshold) / total
    median_eq = final_equities[total // 2]
    mean_eq   = sum(final_equities) / total
    p5_eq     = final_equities[max(0, int(0.05 * total))]

    return {
        "prob_ruin":     prob_ruin,
        "median_eq":     median_eq,
        "mean_eq":       mean_eq,
        "p5_eq":         p5_eq,
        "f_kelly_used":  f_use,
    }


# ---------------------------------------------------------------------------
# Risk-of-ruin via bootstrap resampling
# ---------------------------------------------------------------------------

def mc_risk_of_ruin(
    returns: List[float],
    start_equity: float = 1.0,
    ruin_level: float = 0.30,
    n_paths: int = 10_000,
    seed: Optional[int] = None,
) -> Dict[str, float]:
    """
    Estimate probability of ruin by bootstrap-resampling historical returns.

    Unlike the parametric normal simulation in monte_carlo_equity(), this
    samples with replacement from the actual return distribution, preserving
    fat tails and skew.

    Args:
        returns:      Per-trade or per-bar historical returns (list of floats).
        start_equity: Starting equity normalised to 1.0.
        ruin_level:   Fraction of start_equity considered 'ruin' (e.g. 0.30
                      means equity fell to 30% of starting value).
        n_paths:      Number of Monte Carlo paths.
        seed:         Optional RNG seed for reproducibility.

    Returns:
        {"prob_ruin": float, "median_eq": float, "mean_eq": float,
         "p5_eq": float, "paths": int}
    """
    n = len(returns)
    if n == 0:
        return {"prob_ruin": 0.0, "median_eq": 1.0, "mean_eq": 1.0,
                "p5_eq": 1.0, "paths": 0}

    rng = random.Random(seed)
    ruin_threshold = start_equity * ruin_level
    final_equities: List[float] = []

    for _ in range(n_paths):
        eq = start_equity
        for _ in range(n):
            r = rng.choice(returns)
            eq *= (1.0 + r)
            if eq <= 0:
                eq = 0.0
                break
        final_equities.append(eq)

    final_equities.sort()
    total = len(final_equities)

    prob_ruin = sum(1 for e in final_equities if e <= ruin_threshold) / total
    median_eq = final_equities[total // 2]
    mean_eq   = sum(final_equities) / total
    p5_eq     = final_equities[max(0, int(0.05 * total))]

    return {
        "prob_ruin": prob_ruin,
        "median_eq": median_eq,
        "mean_eq":   mean_eq,
        "p5_eq":     p5_eq,
        "paths":     total,
    }


# ---------------------------------------------------------------------------
# MC-adjusted risk fraction
# ---------------------------------------------------------------------------

def mc_adjust_risk_frac(
    base_frac: float,
    mc_metrics: Dict[str, float],
    target_ruin_prob: float = 0.30,
    min_p5: float = 0.90,
) -> float:
    """
    Scale down base_frac when Monte Carlo metrics indicate elevated risk.

    Reductions (each applied independently, so both can stack to 0.25×):
      - prob_loss > target_ruin_prob  → ×0.5
      - p5 < min_p5                   → ×0.5

    Hard clamp: result is always in [0.0, 0.05].

    Pass the returned fraction into dynamic_size() / drawdown_guarded_risk_frac()
    as the base_risk_frac argument.
    """
    frac = base_frac

    if mc_metrics.get("prob_loss", 0.0) > target_ruin_prob:
        frac *= 0.5

    if mc_metrics.get("p5", 1.0) < min_p5:
        frac *= 0.5

    return max(0.0, min(frac, 0.05))


# ---------------------------------------------------------------------------
# Gate helper — single call to check MC thresholds
# ---------------------------------------------------------------------------

def mc_gate(
    returns: List[float],
    days: int = 252,
    paths: int = 1000,
    min_p5: float = 0.90,
    max_prob_loss: float = 0.50,
    seed: Optional[int] = None,
) -> Dict:
    """
    Run Monte Carlo and return gate result.

    Returns {"ok": bool, "reason": str, "metrics": dict}.
    """
    eq_final = monte_carlo_equity(returns, days=days, paths=paths, seed=seed)
    metrics = monte_carlo_risk_metrics(eq_final)

    if metrics["p5"] < min_p5:
        return {
            "ok": False,
            "reason": f"mc_p5={metrics['p5']:.3f} < {min_p5}",
            "metrics": metrics,
        }
    if metrics["prob_loss"] > max_prob_loss:
        return {
            "ok": False,
            "reason": f"mc_prob_loss={metrics['prob_loss']:.1%} > {max_prob_loss:.1%}",
            "metrics": metrics,
        }
    return {"ok": True, "reason": "ok", "metrics": metrics}

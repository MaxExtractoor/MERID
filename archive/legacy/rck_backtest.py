"""
Risk-Constrained Kelly (RCK) Backtest Framework for Kalshi 15m Crypto

This module provides a complete backtesting system for:
- Bayesian p_true estimation with de-vigged Kalshi prices
- RCK fraction calculation with drawdown constraints
- Vectorized backtesting for BTC/ETH/SOL/XRP 15m markets
- Performance analysis and parameter tuning

Based on Stanford RCK paper and Kalshi 15m crypto specifications.
"""

import numpy as np
import pandas as pd
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Callable, Tuple
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


@dataclass
class Kalshi15mBar:
    """Single 15m Kalshi crypto market bar for backtesting."""
    ts_open: float                    # Open timestamp
    symbol: str                       # "BTC","ETH","SOL","XRP"
    yes_price: float                  # YES price in 0..1 (cents/100)
    no_price: float                   # NO price in 0..1 (cents/100)
    outcome_yes: bool                  # True if YES wins at settlement
    features: Dict[str, Any]           # RTI, sentiment, flow features
    market_id: str                     # Kalshi market ticker
    settlement_time: float             # Settlement timestamp


@dataclass
class BacktestConfig:
    """Configuration for RCK backtest parameters."""
    target_drawdown: float = 0.1       # Maximum drawdown (e.g., 0.1 = 10%)
    drawdown_probability: float = 0.1  # Max probability of exceeding target
    initial_wealth: float = 1.0        # Starting wealth
    min_fraction: float = 0.01         # Minimum Kelly fraction
    safety_factor: float = 0.8         # Additional safety margin


def devig_yes_no(yes_price: float, no_price: float) -> Tuple[float, float]:
    """
    Remove Kalshi vig from YES/NO prices.
    
    Args:
        yes_price: YES price in 0..1
        no_price: NO price in 0..1
        
    Returns:
        (fair_yes_prob, fair_no_prob): De-vigged probabilities summing to 1.0
    """
    s = yes_price + no_price
    if s <= 0:
        return 0.5, 0.5
    return yes_price / s, no_price / s


def kelly_fraction_binary(p_true: float, price: float) -> float:
    """
    Full Kelly fraction for binary (payoff 1/0) bet.
    
    Args:
        p_true: True win probability (0..1)
        price: Contract price in 0..1
        
    Returns:
        Kelly fraction of bankroll
    """
    if price <= 0 or price >= 1:
        return 0.0
    
    b = (1.0 - price) / price
    q = 1.0 - p_true
    f_star = (b * p_true - q) / b
    return max(0.0, min(f_star, 1.0))


def simulate_path(f: float, p_true: float, price: float, n_trades: int = 500) -> Dict[str, Any]:
    """
    Simulate wealth path under constant fraction f.
    
    Args:
        f: Kelly fraction
        p_true: True win probability
        price: Contract price
        n_trades: Number of trades to simulate
        
    Returns:
        Dictionary with final wealth, max drawdown, and log growth
    """
    wealth = 1.0
    wealth_path = [wealth]
    b = (1.0 - price) / price

    for _ in range(n_trades):
        bet = f * wealth
        win = np.random.rand() < p_true
        if win:
            wealth += bet * b
        else:
            wealth -= bet
        wealth_path.append(wealth)

    wealth_path = np.array(wealth_path)
    max_wealth = np.maximum.accumulate(wealth_path)
    drawdown = 1.0 - wealth_path / max_wealth
    
    return {
        "final_wealth": wealth_path[-1],
        "max_drawdown": drawdown.max(),
        "log_growth": np.log(wealth_path[-1]),
        "wealth_path": wealth_path,
    }


def solve_rck_fraction(p_true: float,
                       price: float,
                       target_dd: float = 0.1,
                       dd_prob: float = 0.1,
                       n_paths: int = 500,
                       n_trades: int = 500) -> float:
    """
    Risk-constrained Kelly fraction solver.
    
    Args:
        p_true: True win probability
        price: Contract price
        target_dd: Target maximum drawdown
        dd_prob: Maximum probability of exceeding target drawdown
        n_paths: Number of Monte Carlo paths
        n_trades: Trades per path
        
    Returns:
        Optimal Kelly fraction under drawdown constraints
    """
    f_kelly = kelly_fraction_binary(p_true, price)
    if f_kelly <= 0:
        return 0.0

    candidates = np.linspace(0.1 * f_kelly, f_kelly, 12)
    best_f, best_growth = 0.0, -np.inf

    for f in candidates:
        dds = []
        growths = []
        
        for _ in range(n_paths):
            res = simulate_path(f, p_true, price, n_trades)
            dds.append(res["max_drawdown"])
            growths.append(res["log_growth"])
        
        dds = np.array(dds)
        growths = np.array(growths)

        prob_exceed = (dds > target_dd).mean()
        avg_growth = growths.mean()

        if prob_exceed <= dd_prob and avg_growth > best_growth:
            best_growth = avg_growth
            best_f = f

    return best_f


def estimate_p_true_bayesian(symbol: str,
                             p_mkt_devig: float,
                             features: Dict[str, Any],
                             historical_wins: int = 0,
                             historical_losses: int = 0,
                             prior_strengths: Optional[Dict[str, int]] = None) -> float:
    """
    Bayesian p_true estimation with symbol-specific priors.
    
    Args:
        symbol: Crypto symbol
        p_mkt_devig: De-vigged market probability
        features: Feature dictionary
        historical_wins: Historical wins
        historical_losses: Historical losses
        prior_strengths: Symbol-specific prior strengths
        
    Returns:
        Estimated true probability
    """
    # Default prior strengths per symbol
    if prior_strengths is None:
        prior_strengths = {
            "BTC": 30,
            "ETH": 25,
            "SOL": 40,
            "XRP": 45,
        }
    
    n0 = prior_strengths.get(symbol, 30)
    
    # Beta prior from de-vigged market probability
    alpha0 = p_mkt_devig * n0
    beta0 = (1 - p_mkt_devig) * n0
    
    # Update with historical data
    alpha_post = alpha0 + historical_wins
    beta_post = beta0 + historical_losses
    
    # Posterior mean
    p_post = alpha_post / (alpha_post + beta_post)
    
    # Adjust with current features (reduced weights for 15m)
    delta = 0.0
    delta += 0.06 * features.get("rti_signal", 0.0)
    delta += 0.03 * (features.get("flow_imbalance", 0.0) - 0.5)
    delta += features.get("fg_contrarian", 0.0)
    delta += 0.05 * (features.get("asset_sentiment", 0.5) - 0.5)
    
    # Final p_true
    p_true = max(0.01, min(0.99, p_post + delta))
    return p_true


def backtest_rck_vectorized(df: pd.DataFrame,
                           config: BacktestConfig,
                           estimate_p_true: Callable[[str, float, Dict[str, Any]], float]) -> Dict[str, Any]:
    """
    Vectorized RCK backtest for Kalshi 15m crypto markets.
    
    Args:
        df: DataFrame with columns ['symbol','yes_price','no_price','outcome_yes',...features...]
        config: Backtest configuration
        estimate_p_true: Function to estimate p_true
        
    Returns:
        Dictionary with backtest results and metrics
    """
    wealth = config.initial_wealth
    wealth_series = [wealth]
    f_series = []
    pnl_series = [0.0]
    
    # Pre-calculate de-vigged probabilities
    df["p_mkt_devig"], df["p_no_devig"] = zip(
        df.apply(lambda row: devig_yes_no(row["yes_price"], row["no_price"]), axis=1)
    )
    
    # Estimate p_true for each bar
    df["p_true"] = df.apply(
        lambda row: estimate_p_true(row["symbol"], row["p_mkt_devig"], row.to_dict()),
        axis=1
    )
    
    # Calculate RCK fractions
    df["f_rck"] = df.apply(
        lambda row: solve_rck_fraction(
            row["p_true"],
            row["yes_price"],
            target_dd=config.target_drawdown,
            dd_prob=config.drawdown_probability
        ),
        axis=1
    )
    
    # Apply safety factor
    df["f_used"] = df["f_rck"] * config.safety_factor
    
    # Calculate full Kelly for comparison
    df["f_full"] = df.apply(
        lambda row: kelly_fraction_binary(row["p_true"], row["yes_price"]),
        axis=1
    )
    
    # Backtest loop
    for i, row in df.iterrows():
        f_used = row["f_used"]
        if f_used < config.min_fraction:
            f_used = 0.0
        
        f_series.append(f_used)
        
        # Calculate PnL
        bet = f_used * wealth
        b = (1.0 - row["yes_price"]) / row["yes_price"]
        
        if row["outcome_yes"]:
            pnl = bet * b
            wealth += pnl
        else:
            pnl = -bet
            wealth += pnl
        
        wealth_series.append(wealth)
        pnl_series.append(pnl)
    
    # Calculate metrics
    wealth_arr = np.array(wealth_series)
    max_w = np.maximum.accumulate(wealth_arr)
    drawdown = 1 - wealth_arr / max_w
    
    # Add series to DataFrame
    df["f_used"] = f_series[1:]  # Skip initial placeholder
    df["wealth"] = wealth_series[1:]
    df["drawdown"] = drawdown[1:]
    df["pnl"] = pnl_series[1:]
    
    # Calculate performance metrics
    total_return = (wealth_arr[-1] / config.initial_wealth) - 1
    max_drawdown = drawdown.max()
    final_wealth = wealth_arr[-1]
    
    # Win rate
    win_rate = df["outcome_yes"].mean()
    
    # Average Kelly fraction used
    avg_f_used = np.mean(df["f_used"])
    avg_f_full = np.mean(df["f_full"])
    
    # Sharpe ratio (simplified)
    returns = np.diff(wealth_arr) / wealth_arr[:-1]
    sharpe_ratio = np.mean(returns) / np.std(returns) if np.std(returns) > 0 else 0
    
    return {
        "df": df,
        "wealth_path": wealth_arr,
        "drawdown_path": drawdown,
        "metrics": {
            "total_return": total_return,
            "max_drawdown": max_drawdown,
            "final_wealth": final_wealth,
            "win_rate": win_rate,
            "avg_f_used": avg_f_used,
            "avg_f_full": avg_f_full,
            "fraction_of_full": avg_f_used / avg_f_full if avg_f_full > 0 else 0,
            "sharpe_ratio": sharpe_ratio,
            "total_trades": len(df),
        }
    }


def backtest_rck_event_driven(bars: List[Kalshi15mBar],
                             config: BacktestConfig,
                             estimate_p_true: Callable[[str, float, Dict[str, Any]], float]) -> Dict[str, Any]:
    """
    Event-driven RCK backtest for detailed analysis.
    
    Args:
        bars: List of Kalshi15mBar objects
        config: Backtest configuration
        estimate_p_true: Function to estimate p_true
        
    Returns:
        Dictionary with backtest results
    """
    wealth = config.initial_wealth
    wealth_path = [wealth]
    f_path = []
    pnl_path = [0.0]
    
    for bar in bars:
        # De-vig prices
        p_mkt_devig, _ = devig_yes_no(bar.yes_price, bar.no_price)
        
        # Estimate p_true
        p_true = estimate_p_true(bar.symbol, p_mkt_devig, bar.features)
        
        # Calculate RCK fraction
        f_rck = solve_rck_fraction(
            p_true, bar.yes_price,
            target_dd=config.target_drawdown,
            dd_prob=config.drawdown_probability
        )
        
        f_used = f_rck * config.safety_factor
        f_path.append(f_used)
        
        # Calculate PnL
        bet = f_used * wealth
        b = (1.0 - bar.yes_price) / bar.yes_price
        
        if bar.outcome_yes:
            pnl = bet * b
            wealth += pnl
        else:
            pnl = -bet
            wealth += pnl
        
        wealth_path.append(wealth)
        pnl_path.append(pnl)
    
    wealth_arr = np.array(wealth_path)
    max_w = np.maximum.accumulate(wealth_arr)
    drawdown = 1 - wealth_arr / max_w
    
    return {
        "wealth_path": wealth_arr,
        "f_path": np.array(f_path),
        "pnl_path": np.array(pnl_path),
        "drawdown_path": drawdown,
        "max_drawdown": float(drawdown.max()),
        "final_wealth": float(wealth_arr[-1]),
        "total_return": (wealth_arr[-1] / config.initial_wealth) - 1,
        "total_trades": len(bars),
    }


def analyze_performance_by_symbol(results: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    Analyze backtest performance by symbol.
    
    Args:
        results: Backtest results dictionary
        
    Returns:
        Performance metrics by symbol
    """
    df = results["df"]
    symbol_analysis = {}
    
    for symbol in df["symbol"].unique():
        symbol_df = df[df["symbol"] == symbol]
        
        symbol_analysis[symbol] = {
            "total_trades": len(symbol_df),
            "win_rate": symbol_df["outcome_yes"].mean(),
            "avg_f_used": symbol_df["f_used"].mean(),
            "avg_f_full": symbol_df["f_full"].mean(),
            "total_pnl": symbol_df["pnl"].sum(),
            "final_wealth": symbol_df["wealth"].iloc[-1] if len(symbol_df) > 0 else 1.0,
            "max_drawdown": symbol_df["drawdown"].max(),
            "avg_edge_bps": ((symbol_df["p_true"] - symbol_df["p_mkt_devig"]) * 10000).mean(),
        }
    
    return symbol_analysis


def tune_rck_parameters(df: pd.DataFrame,
                        estimate_p_true: Callable[[str, float, Dict[str, Any]], float],
                        target_drawdowns: List[float] = None,
                        drawdown_probs: List[float] = None,
                        safety_factors: List[float] = None) -> Dict[str, Any]:
    """
    Tune RCK parameters via grid search.
    
    Args:
        df: Backtest DataFrame
        estimate_p_true: p_true estimation function
        target_drawdowns: List of target drawdown values to test
        drawdown_probs: List of drawdown probability values to test
        safety_factors: List of safety factors to test
        
    Returns:
        Tuning results with best parameters
    """
    if target_drawdowns is None:
        target_drawdowns = [0.05, 0.08, 0.10, 0.12, 0.15]
    if drawdown_probs is None:
        drawdown_probs = [0.05, 0.10, 0.15, 0.20]
    if safety_factors is None:
        safety_factors = [0.6, 0.7, 0.8, 0.9, 1.0]
    
    best_config = None
    best_score = -np.inf
    tuning_results = []
    
    for target_dd in target_drawdowns:
        for dd_prob in drawdown_probs:
            for safety_factor in safety_factors:
                config = BacktestConfig(
                    target_drawdown=target_dd,
                    drawdown_probability=dd_prob,
                    safety_factor=safety_factor
                )
                
                try:
                    results = backtest_rck_vectorized(df, config, estimate_p_true)
                    metrics = results["metrics"]
                    
                    # Calculate score (weighted combination of return and drawdown)
                    score = metrics["total_return"] - 2 * metrics["max_drawdown"]
                    
                    tuning_results.append({
                        "target_drawdown": target_dd,
                        "drawdown_probability": dd_prob,
                        "safety_factor": safety_factor,
                        "score": score,
                        "total_return": metrics["total_return"],
                        "max_drawdown": metrics["max_drawdown"],
                        "sharpe_ratio": metrics["sharpe_ratio"],
                        "avg_f_used": metrics["avg_f_used"],
                    })
                    
                    if score > best_score:
                        best_score = score
                        best_config = {
                            "target_drawdown": target_dd,
                            "drawdown_probability": dd_prob,
                            "safety_factor": safety_factor,
                            "score": score,
                            "metrics": metrics,
                        }
                        
                except Exception as e:
                    logger.warning(f"Failed config {target_dd}/{dd_prob}/{safety_factor}: {e}")
                    continue
    
    return {
        "best_config": best_config,
        "tuning_results": tuning_results,
        "best_score": best_score,
    }

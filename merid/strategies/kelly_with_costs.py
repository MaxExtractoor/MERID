"""
Kelly Criterion with Transaction Costs

Adjust PnL per trade before feeding into Kelly stats.
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Any
import logging

from .kelly import KellyStats, kelly_fraction

logger = logging.getLogger(__name__)

def apply_costs(entry_price: float, exit_price: float, slippage_bps: float, commission_bps: float) -> float:
    """
    Apply transaction costs to trade PnL.
    
    Args:
        entry_price: Entry price
        exit_price: Exit price
        slippage_bps: Slippage in basis points (1e-4)
        commission_bps: Commission in basis points (1e-4)
        
    Returns:
        Net PnL after costs
    """
    # Validate inputs
    if entry_price <= 0 or exit_price <= 0:
        logger.warning("Invalid prices for cost calculation")
        return 0.0
    
    # Slippage: always pay slippage_bps of price on each fill
    # For long positions: worse entry price (higher), worse exit price (lower)
    slip_entry = entry_price * (1 + slippage_bps * 1e-4)
    slip_exit = exit_price * (1 - slippage_bps * 1e-4)
    
    # Commissions: charged on notional both sides
    comm_entry = entry_price * commission_bps * 1e-4
    comm_exit = exit_price * commission_bps * 1e-4
    
    # Calculate PnL
    pnl_gross = slip_exit - slip_entry
    pnl_net = pnl_gross - (comm_entry + comm_exit)
    
    return pnl_net

def calculate_trade_costs(entry_price: float, exit_price: float, 
                         slippage_bps: float = 5.0, 
                         commission_bps: float = 2.0) -> Dict[str, float]:
    """
    Calculate detailed trade costs breakdown.
    
    Args:
        entry_price: Entry price
        exit_price: Exit price
        slippage_bps: Slippage in basis points
        commission_bps: Commission in basis points
        
    Returns:
        Dictionary with cost breakdown
    """
    # Calculate costs
    slip_entry_cost = entry_price * slippage_bps * 1e-4
    slip_exit_cost = exit_price * slippage_bps * 1e-4
    comm_entry_cost = entry_price * commission_bps * 1e-4
    comm_exit_cost = exit_price * commission_bps * 1e-4
    
    total_slippage = slip_entry_cost + slip_exit_cost
    total_commission = comm_entry_cost + comm_exit_cost
    total_costs = total_slippage + total_commission
    
    gross_pnl = exit_price - entry_price
    net_pnl = gross_pnl - total_costs
    
    return {
        "gross_pnl": gross_pnl,
        "net_pnl": net_pnl,
        "slippage_entry": slip_entry_cost,
        "slippage_exit": slip_exit_cost,
        "total_slippage": total_slippage,
        "commission_entry": comm_entry_cost,
        "commission_exit": comm_exit_cost,
        "total_commission": total_commission,
        "total_costs": total_costs,
        "cost_impact": total_costs / abs(gross_pnl) if gross_pnl != 0 else 0.0
    }

def kelly_from_costed_trades(trades: List[Dict[str, float]], 
                           slippage_bps: float = 5.0, 
                           commission_bps: float = 2.0) -> float:
    """
    Calculate Kelly fraction from trades with transaction costs.
    
    Args:
        trades: List of trade dictionaries with entry_price and exit_price
        slippage_bps: Slippage in basis points
        commission_bps: Commission in basis points
        
    Returns:
        Kelly fraction
    """
    if not trades:
        logger.warning("No trades provided for Kelly calculation")
        return 0.0
    
    pnls = []
    total_costs = []
    gross_pnls = []
    
    for trade in trades:
        entry_price = trade.get("entry_price", 0.0)
        exit_price = trade.get("exit_price", 0.0)
        
        if entry_price <= 0 or exit_price <= 0:
            logger.warning(f"Invalid trade prices: entry={entry_price}, exit={exit_price}")
            continue
        
        # Apply costs
        net_pnl = apply_costs(entry_price, exit_price, slippage_bps, commission_bps)
        costs = calculate_trade_costs(entry_price, exit_price, slippage_bps, commission_bps)
        
        pnls.append(net_pnl)
        total_costs.append(costs["total_costs"])
        gross_pnls.append(costs["gross_pnl"])
    
    if not pnls:
        logger.warning("No valid trades after cost adjustment")
        return 0.0
    
    # Calculate Kelly statistics
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p <= 0]
    
    win_rate = len(wins) / len(pnls)
    avg_win = np.mean(wins) if wins else 0.0
    avg_loss = -np.mean(losses) if losses else 0.0
    win_loss_ratio = avg_win / avg_loss if avg_loss > 0 else 0.0
    
    # Calculate Kelly fraction
    ks = KellyStats(win_rate=win_rate, win_loss_ratio=win_loss_ratio)
    kelly_frac = kelly_fraction(ks)
    
    # Cost impact analysis
    avg_total_costs = np.mean(total_costs)
    avg_gross_pnl = np.mean(gross_pnls)
    cost_impact = avg_total_costs / abs(avg_gross_pnl) if avg_gross_pnl != 0 else 0.0
    
    logger.info(f"Kelly calculation with costs:")
    logger.info(f"  Trades: {len(pnls)}, Win Rate: {win_rate:.1%}, W/L: {win_loss_ratio:.2f}")
    logger.info(f"  Kelly Fraction: {kelly_frac:.3f}")
    logger.info(f"  Avg Costs: ${avg_total_costs:.2f}, Cost Impact: {cost_impact:.2%}")
    
    return kelly_frac

def kelly_with_cost_adjustment(
    base_kelly_fraction: float,
    trades: List[Dict[str, float]],
    slippage_bps: float = 5.0,
    commission_bps: float = 2.0
) -> float:
    """
    Adjust Kelly fraction to account for transaction costs.
    
    Args:
        base_kelly_fraction: Base Kelly fraction without costs
        trades: List of trade dictionaries
        slippage_bps: Slippage in basis points
        commission_bps: Commission in basis points
        
    Returns:
        Cost-adjusted Kelly fraction
    """
    # Calculate Kelly with costs
    costed_kelly = kelly_from_costed_trades(trades, slippage_bps, commission_bps)
    
    # Calculate adjustment factor
    if base_kelly_fraction > 0:
        adjustment_factor = costed_kelly / base_kelly_fraction
    else:
        adjustment_factor = 1.0
    
    # Apply adjustment with bounds (don't increase Kelly due to costs)
    adjusted_kelly = min(costed_kelly, base_kelly_fraction)
    
    logger.info(f"Kelly cost adjustment:")
    logger.info(f"  Base Kelly: {base_kelly_fraction:.3f}")
    logger.info(f"  Costed Kelly: {costed_kelly:.3f}")
    logger.info(f"  Adjustment Factor: {adjustment_factor:.2f}")
    logger.info(f"  Adjusted Kelly: {adjusted_kelly:.3f}")
    
    return adjusted_kelly

def analyze_cost_impact(trades: List[Dict[str, float]], 
                        slippage_bps: float = 5.0, 
                        commission_bps: float = 2.0) -> Dict[str, Any]:
    """
    Analyze the impact of transaction costs on strategy performance.
    
    Args:
        trades: List of trade dictionaries
        slippage_bps: Slippage in basis points
        commission_bps: Commission in basis points
        
    Returns:
        Cost impact analysis
    """
    if not trades:
        return {"error": "No trades provided"}
    
    # Calculate costs for all trades
    all_costs = []
    all_gross_pnls = []
    all_net_pnls = []
    
    for trade in trades:
        entry_price = trade.get("entry_price", 0.0)
        exit_price = trade.get("exit_price", 0.0)
        
        if entry_price <= 0 or exit_price <= 0:
            continue
        
        costs = calculate_trade_costs(entry_price, exit_price, slippage_bps, commission_bps)
        all_costs.append(costs["total_costs"])
        all_gross_pnls.append(costs["gross_pnl"])
        all_net_pnls.append(costs["net_pnl"])
    
    if not all_costs:
        return {"error": "No valid trades for cost analysis"}
    
    # Calculate metrics
    total_gross_pnl = sum(all_gross_pnls)
    total_net_pnl = sum(all_net_pnls)
    total_costs = sum(all_costs)
    
    avg_cost_per_trade = np.mean(all_costs)
    avg_gross_pnl_per_trade = np.mean(all_gross_pnls)
    avg_net_pnl_per_trade = np.mean(all_net_pnls)
    
    cost_impact = total_costs / abs(total_gross_pnl) if total_gross_pnl != 0 else 0.0
    pnl_reduction = (total_gross_pnl - total_net_pnl) / abs(total_gross_pnl) if total_gross_pnl != 0 else 0.0
    
    # Kelly comparison
    kelly_without_costs = kelly_from_costed_trades(trades, 0, 0)  # No costs
    kelly_with_costs = kelly_from_costed_trades(trades, slippage_bps, commission_bps)
    
    kelly_reduction = (kelly_without_costs - kelly_with_costs) / kelly_without_costs if kelly_without_costs > 0 else 0.0
    
    return {
        "total_trades": len(trades),
        "total_gross_pnl": total_gross_pnl,
        "total_net_pnl": total_net_pnl,
        "total_costs": total_costs,
        "avg_cost_per_trade": avg_cost_per_trade,
        "avg_gross_pnl_per_trade": avg_gross_pnl_per_trade,
        "avg_net_pnl_per_trade": avg_net_pnl_per_trade,
        "cost_impact": cost_impact,
        "pnl_reduction": pnl_reduction,
        "kelly_without_costs": kelly_without_costs,
        "kelly_with_costs": kelly_with_costs,
        "kelly_reduction": kelly_reduction,
        "slippage_bps": slippage_bps,
        "commission_bps": commission_bps
    }

def optimize_cost_parameters(
    trades: List[Dict[str, float]],
    slippage_range: List[float] = None,
    commission_range: List[float] = None
) -> Dict[str, Any]:
    """
    Optimize slippage and commission parameters.
    
    Args:
        trades: List of trade dictionaries
        slippage_range: Range of slippage values to test
        commission_range: Range of commission values to test
        
    Returns:
        Optimization results
    """
    if slippage_range is None:
        slippage_range = [1.0, 2.0, 5.0, 10.0]  # 1-10 bps
    
    if commission_range is None:
        commission_range = [0.5, 1.0, 2.0, 5.0]  # 0.5-5 bps
    
    results = []
    
    for slip in slippage_range:
        for comm in commission_range:
            try:
                analysis = analyze_cost_impact(trades, slip, comm)
                
                if "error" not in analysis:
                    # Calculate score (higher Kelly is better)
                    score = analysis["kelly_with_costs"]
                    
                    results.append({
                        "slippage_bps": slip,
                        "commission_bps": comm,
                        "kelly_fraction": analysis["kelly_with_costs"],
                        "cost_impact": analysis["cost_impact"],
                        "score": score,
                        "net_pnl": analysis["total_net_pnl"]
                    })
            except Exception as e:
                logger.error(f"Error in optimization for slip={slip}, comm={comm}: {e}")
                continue
    
    # Sort by score
    results.sort(key=lambda x: x["score"], reverse=True)
    
    return {
        "best_parameters": results[0] if results else None,
        "all_results": results,
        "optimization_summary": {
            "slippage_range": slippage_range,
            "commission_range": commission_range,
            "total_combinations": len(results)
        }
    }

def print_cost_analysis(analysis: Dict[str, Any]):
    """
    Print formatted cost analysis.
    
    Args:
        analysis: Cost analysis dictionary
    """
    if "error" in analysis:
        print(f"Error: {analysis['error']}")
        return
    
    print("\n" + "="*70)
    print("TRANSACTION COST ANALYSIS")
    print("="*70)
    
    print(f"\nTrade Summary:")
    print(f"  Total Trades: {analysis['total_trades']}")
    print(f"  Total Gross PnL: ${analysis['total_gross_pnl']:,.2f}")
    print(f"  Total Net PnL: ${analysis['total_net_pnl']:,.2f}")
    print(f"  Total Costs: ${analysis['total_costs']:,.2f}")
    
    print(f"\nPer-Trade Metrics:")
    print(f"  Avg Cost: ${analysis['avg_cost_per_trade']:.2f}")
    print(f"  Avg Gross PnL: ${analysis['avg_gross_pnl_per_trade']:.2f}")
    print(f"  Avg Net PnL: ${analysis['avg_net_pnl_per_trade']:.2f}")
    
    print(f"\nCost Impact:")
    print(f"  Cost Impact: {analysis['cost_impact']:.2%}")
    print(f"  PnL Reduction: {analysis['pnl_reduction']:.2%}")
    
    print(f"\nKelly Impact:")
    print(f"  Kelly (No Costs): {analysis['kelly_without_costs']:.3f}")
    print(f"  Kelly (With Costs): {analysis['kelly_with_costs']:.3f}")
    print(f"  Kelly Reduction: {analysis['kelly_reduction']:.2%}")
    
    print(f"\nCost Parameters:")
    print(f"  Slippage: {analysis['slippage_bps']:.1f} bps")
    print(f"  Commission: {analysis['commission_bps']:.1f} bps")
    
    print("="*70)

# Example usage:
"""
# Sample trades
trades = [
    {"entry_price": 50000, "exit_price": 50500},
    {"entry_price": 50200, "exit_price": 49800},
    {"entry_price": 50100, "exit_price": 50300}
]

# Calculate Kelly with costs
kelly_frac = kelly_from_costed_trades(trades, slippage_bps=5.0, commission_bps=2.0)
print(f"Kelly fraction with costs: {kelly_frac:.3f}")

# Analyze cost impact
analysis = analyze_cost_impact(trades)
print_cost_analysis(analysis)

# Optimize cost parameters
optimization = optimize_cost_parameters(trades)
print(f"Best parameters: {optimization['best_parameters']}")
"""

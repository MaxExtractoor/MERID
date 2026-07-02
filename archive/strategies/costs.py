"""
Costs Model - Slippage and Commissions for Realistic Backtesting

BACKTEST/SIMULATION MODULE ONLY - Not used in live 15m crypto trading.

For live Kalshi 15m crypto agents (BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M):
  - Fee calculation: Use merid/event_venues/kalshi/fees.py (SINGLE SOURCE OF TRUTH)
  - Slippage: Use profile config or environment variables
  - This module's defaults are for generic backtesting only

Simple model for slippage and commissions to make backtests more realistic.
"""

import logging

logger = logging.getLogger(__name__)

def apply_costs(entry_price: float, exit_price: float, slippage_bps: float, commission_bps: float) -> float:
    """
    Adjust PnL for slippage and commissions.
    
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
    
    if slippage_bps < 0 or commission_bps < 0:
        logger.warning("Negative cost parameters, using absolute values")
        slippage_bps = abs(slippage_bps)
        commission_bps = abs(commission_bps)
    
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

def calculate_total_costs(entry_price: float, exit_price: float, 
                         slippage_bps: float, commission_bps: float) -> Dict[str, float]:
    """
    Calculate detailed cost breakdown.
    
    Args:
        entry_price: Entry price
        exit_price: Exit price
        slippage_bps: Slippage in basis points
        commission_bps: Commission in basis points
        
    Returns:
        Dictionary with cost breakdown
    """
    # Validate inputs
    if entry_price <= 0 or exit_price <= 0:
        return {"error": "Invalid prices"}
    
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
        "slippage_entry": slip_entry_cost,
        "slippage_exit": slip_exit_cost,
        "total_slippage": total_slippage,
        "commission_entry": comm_entry_cost,
        "commission_exit": comm_exit_cost,
        "total_commission": total_commission,
        "total_costs": total_costs,
        "net_pnl": net_pnl,
        "cost_impact": total_costs / abs(gross_pnl) if gross_pnl != 0 else 0.0
    }

def apply_costs_to_trade(trade_entry_price: float, trade_exit_price: float,
                        trade_quantity: float = 1.0,
                        slippage_bps: float = 5.0,
                        commission_bps: float = 2.0) -> Dict[str, float]:
    """
    Apply costs to a trade with quantity.
    
    Args:
        trade_entry_price: Entry price per unit
        trade_exit_price: Exit price per unit
        trade_quantity: Number of units
        slippage_bps: Slippage in basis points
        commission_bps: Commission in basis points
        
    Returns:
        Dictionary with trade PnL and costs
    """
    # Calculate per-unit PnL with costs
    unit_pnl = apply_costs(trade_entry_price, trade_exit_price, slippage_bps, commission_bps)
    
    # Scale by quantity
    total_pnl = unit_pnl * trade_quantity
    
    # Get detailed cost breakdown
    costs = calculate_total_costs(trade_entry_price, trade_exit_price, slippage_bps, commission_bps)
    
    # Scale costs by quantity
    scaled_costs = {k: v * trade_quantity if isinstance(v, (int, float)) else v 
                   for k, v in costs.items()}
    
    # Add trade-specific info
    scaled_costs.update({
        "quantity": trade_quantity,
        "entry_price": trade_entry_price,
        "exit_price": trade_exit_price,
        "unit_pnl": unit_pnl,
        "total_pnl": total_pnl
    })
    
    return scaled_costs

def get_default_cost_parameters() -> Dict[str, Dict[str, float]]:
    """
    Get default cost parameters for different market types.
    
    Returns:
        Dictionary with default parameters
    """
    return {
        "crypto_spot": {
            "slippage_bps": 5.0,      # 0.05% slippage
            "commission_bps": 2.0     # 0.02% commission
        },
        "crypto_futures": {
            "slippage_bps": 2.0,      # 0.02% slippage (better liquidity)
            "commission_bps": 1.0     # 0.01% commission
        },
        "forex": {
            "slippage_bps": 1.0,      # 0.01% slippage (very liquid)
            "commission_bps": 0.5     # 0.005% commission
        },
        "stocks": {
            "slippage_bps": 10.0,     # 0.1% slippage
            "commission_bps": 5.0      # 0.05% commission
        },
        "conservative": {
            "slippage_bps": 10.0,     # Higher slippage for safety
            "commission_bps": 5.0      # Higher commission for safety
        }
    }

def validate_cost_parameters(slippage_bps: float, commission_bps: float) -> Dict[str, any]:
    """
    Validate cost parameters and provide recommendations.
    
    Args:
        slippage_bps: Slippage in basis points
        commission_bps: Commission in basis points
        
    Returns:
        Validation results
    """
    validation = {
        "valid": True,
        "warnings": [],
        "recommendations": [],
        "market_comparison": {}
    }
    
    # Check ranges
    if slippage_bps > 20.0:
        validation["warnings"].append(f"Very high slippage: {slippage_bps} bps")
        validation["recommendations"].append("Consider reducing position size or using limit orders")
    elif slippage_bps < 0.5:
        validation["warnings"].append(f"Very low slippage: {slippage_bps} bps")
        validation["recommendations"].append("Slippage may be underestimated")
    
    if commission_bps > 10.0:
        validation["warnings"].append(f"Very high commission: {commission_bps} bps")
        validation["recommendations"].append("Consider lower-cost broker or negotiate rates")
    elif commission_bps < 0.1:
        validation["warnings"].append(f"Very low commission: {commission_bps} bps")
        validation["recommendations"].append("Commission may be underestimated")
    
    # Compare to market standards
    defaults = get_default_cost_parameters()
    for market, params in defaults.items():
        if (abs(slippage_bps - params["slippage_bps"]) < 2.0 and 
            abs(commission_bps - params["commission_bps"]) < 2.0):
            validation["market_comparison"][market] = "similar"
        elif (slippage_bps > params["slippage_bps"] * 2 or 
              commission_bps > params["commission_bps"] * 2):
            validation["market_comparison"][market] = "much_higher"
        else:
            validation["market_comparison"][market] = "different"
    
    # Overall assessment
    total_costs = slippage_bps + commission_bps
    if total_costs > 15.0:
        validation["recommendations"].append("High total costs may impact strategy profitability")
    elif total_costs < 2.0:
        validation["recommendations"].append("Low costs - ensure realistic assumptions")
    
    if validation["warnings"]:
        validation["valid"] = False
    
    return validation

def simulate_cost_impact(entry_price: float, exit_price: float, 
                        price_moves: list = None) -> Dict[str, any]:
    """
    Simulate cost impact across different price moves.
    
    Args:
        entry_price: Entry price
        exit_price: Exit price
        price_moves: List of price move percentages
        
    Returns:
        Simulation results
    """
    if price_moves is None:
        price_moves = [-0.05, -0.02, -0.01, 0.01, 0.02, 0.05]  # -5% to +5%
    
    results = {
        "entry_price": entry_price,
        "exit_prices": [],
        "gross_pnls": [],
        "net_pnls": [],
        "cost_impacts": []
    }
    
    for move in price_moves:
        # Calculate exit price based on move
        exit_price_move = entry_price * (1 + move)
        results["exit_prices"].append(exit_price_move)
        
        # Calculate costs with default parameters
        costs = apply_costs_to_trade(entry_price, exit_price_move, 
                                   slippage_bps=5.0, commission_bps=2.0)
        
        results["gross_pnls"].append(costs["gross_pnl"])
        results["net_pnls"].append(costs["total_pnl"])
        results["cost_impacts"].append(costs["cost_impact"])
    
    return results

# Example usage:
"""
# Basic cost calculation
net_pnl = apply_costs(50000, 50500, slippage_bps=5.0, commission_bps=2.0)
print(f"Net PnL: ${net_pnl:.2f}")

# Detailed cost breakdown
costs = calculate_total_costs(50000, 50500, 5.0, 2.0)
print(f"Cost breakdown: {costs}")

# Trade with quantity
trade_costs = apply_costs_to_trade(50000, 50500, trade_quantity=10, 
                                  slippage_bps=5.0, commission_bps=2.0)
print(f"Trade costs: {trade_costs}")

# Validate parameters
validation = validate_cost_parameters(5.0, 2.0)
print(f"Cost validation: {validation}")

# Compare to market standards
defaults = get_default_cost_parameters()
print(f"Default parameters: {defaults}")

# Simulate cost impact
simulation = simulate_cost_impact(50000, 50500)
print(f"Cost impact simulation: {simulation}")
"""

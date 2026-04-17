"""
Kelly Drawdown Limit - Max Drawdown Limit for Kelly Strategy

Apply drawdown limit to Kelly strategy equity curve.
"""

import pandas as pd
import numpy as np
import logging
from typing import Optional

logger = logging.getLogger(__name__)

def apply_dd_stop(equity: pd.Series, dd_limit: float) -> pd.Series:
    """
    Apply drawdown limit to equity curve.
    
    Args:
        equity: Equity curve Series
        dd_limit: Negative fraction, e.g. -0.2 for -20%
        
    Returns:
        Truncated equity curve (after stop hit, capital stays flat)
    """
    if equity.empty:
        return equity
    
    eq = equity.copy()
    peak = eq.iloc[0]
    stopped = False
    stop_index = None
    
    for i in range(len(eq)):
        # Update peak
        if eq.iloc[i] > peak:
            peak = eq.iloc[i]
        
        # Calculate drawdown
        dd = (eq.iloc[i] - peak) / peak if peak != 0 else 0
        
        # Check if drawdown limit hit
        if dd < dd_limit and not stopped:
            # Freeze equity from this point
            eq.iloc[i:] = eq.iloc[i]
            stopped = True
            stop_index = i
            break
    
    if stopped:
        logger.info(f"Drawdown stop triggered at index {stop_index}, dd={dd:.2%}")
    
    return eq

def apply_dd_stop_with_recovery(equity: pd.Series, dd_limit: float, 
                               recovery_threshold: float = 0.0) -> pd.Series:
    """
    Apply drawdown limit with recovery mechanism.
    
    Args:
        equity: Equity curve Series
        dd_limit: Negative fraction for drawdown limit
        recovery_threshold: Drawdown level to resume trading
        
    Returns:
        Equity curve with stop and recovery logic
    """
    if equity.empty:
        return equity
    
    eq = equity.copy()
    peak = eq.iloc[0]
    stopped = False
    stop_index = None
    
    for i in range(len(eq)):
        # Update peak
        if eq.iloc[i] > peak:
            peak = eq.iloc[i]
        
        # Calculate drawdown
        dd = (eq.iloc[i] - peak) / peak if peak != 0 else 0
        
        # Check if drawdown limit hit and not stopped
        if dd < dd_limit and not stopped:
            # Freeze equity from this point
            eq.iloc[i:] = eq.iloc[i]
            stopped = True
            stop_index = i
            break
        
        # Check if recovery threshold met and stopped
        if stopped and dd >= recovery_threshold:
            # Resume trading from next point
            # (In backtest, this would need future data)
            break
    
    return eq

def calculate_dd_stop_statistics(equity: pd.Series, dd_limit: float) -> dict:
    """
    Calculate drawdown stop statistics.
    
    Args:
        equity: Original equity curve
        dd_limit: Drawdown limit applied
        
    Returns:
        Statistics dictionary
    """
    if equity.empty:
        return {"error": "Empty equity curve"}
    
    # Apply drawdown stop
    stopped_equity = apply_dd_stop(equity, dd_limit)
    
    # Calculate statistics
    original_final = equity.iloc[-1]
    stopped_final = stopped_equity.iloc[-1]
    
    # Find when stop was triggered
    peak = equity.cummax()
    dd = (equity - peak) / peak.replace(0, np.nan)
    stop_triggered = dd < dd_limit
    
    if stop_triggered.any():
        stop_index = stop_triggered.idxmax()
        stop_time = stop_index
        stop_equity = equity.loc[stop_index]
        stop_drawdown = dd.loc[stop_index]
    else:
        stop_time = None
        stop_equity = None
        stop_drawdown = None
    
    return {
        "dd_limit": dd_limit,
        "stop_triggered": stop_triggered.any(),
        "stop_time": stop_time,
        "stop_equity": stop_equity,
        "stop_drawdown": stop_drawdown,
        "original_final_capital": original_final,
        "stopped_final_capital": stopped_final,
        "capital_preserved": stopped_final / original_final if original_final > 0 else 0.0,
        "max_drawdown_original": dd.min(),
        "max_drawdown_stopped": max_drawdown(stopped_equity)
    }

def max_drawdown(equity: pd.Series) -> float:
    """
    Calculate maximum drawdown from equity curve.
    
    Args:
        equity: Equity curve Series
        
    Returns:
        Maximum drawdown as negative fraction
    """
    if equity.empty:
        return 0.0
    
    peak = equity.cummax()
    dd = (equity - peak) / peak.replace(0, np.nan)
    return float(dd.min())

def optimize_dd_limit(equity: pd.Series, dd_limits: list = None) -> dict:
    """
    Optimize drawdown limit for best risk-adjusted return.
    
    Args:
        equity: Original equity curve
        dd_limits: List of drawdown limits to test
        
    Returns:
        Optimization results
    """
    if equity.empty:
        return {"error": "Empty equity curve"}
    
    if dd_limits is None:
        dd_limits = [-0.05, -0.10, -0.15, -0.20, -0.25, -0.30]  # 5% to 30%
    
    results = []
    
    for dd_limit in dd_limits:
        stats = calculate_dd_stop_statistics(equity, dd_limit)
        
        if "error" not in stats:
            # Calculate risk-adjusted return
            risk_adj_return = stats["stopped_final_capital"] / abs(stats["max_drawdown_stopped"]) if stats["max_drawdown_stopped"] != 0 else stats["stopped_final_capital"]
            
            results.append({
                "dd_limit": dd_limit,
                "final_capital": stats["stopped_final_capital"],
                "max_drawdown": stats["max_drawdown_stopped"],
                "capital_preserved": stats["capital_preserved"],
                "stop_triggered": stats["stop_triggered"],
                "risk_adj_return": risk_adj_return
            })
    
    if not results:
        return {"error": "No valid results"}
    
    # Find best result
    best_result = max(results, key=lambda x: x["risk_adj_return"])
    
    return {
        "best_dd_limit": best_result["dd_limit"],
        "best_result": best_result,
        "all_results": results,
        "optimization_summary": {
            "dd_limits_tested": dd_limits,
            "best_risk_adj_return": best_result["risk_adj_return"],
            "best_capital_preserved": best_result["capital_preserved"]
        }
    }

def simulate_dd_stop_with_trading(equity: pd.Series, dd_limit: float, 
                                 trading_enabled_after_stop: bool = False) -> dict:
    """
    Simulate drawdown stop with trading flag.
    
    Args:
        equity: Equity curve
        dd_limit: Drawdown limit
        trading_enabled_after_stop: Whether to enable trading after stop
        
    Returns:
        Simulation results
    """
    if equity.empty:
        return {"error": "Empty equity curve"}
    
    eq = equity.copy()
    peak = eq.iloc[0]
    trading_enabled = True
    trading_disabled_at = None
    
    for i in range(len(eq)):
        if trading_enabled:
            # Update peak
            if eq.iloc[i] > peak:
                peak = eq.iloc[i]
            
            # Calculate drawdown
            dd = (eq.iloc[i] - peak) / peak if peak != 0 else 0
            
            # Check drawdown limit
            if dd < dd_limit:
                trading_enabled = False
                trading_disabled_at = i
                logger.info(f"Trading disabled at index {i}, drawdown={dd:.2%}")
        
        elif not trading_enabled and not trading_enabled_after_stop:
            # Keep equity flat
            eq.iloc[i] = eq.iloc[i-1] if i > 0 else eq.iloc[i]
        elif not trading_enabled and trading_enabled_after_stop:
            # Could implement recovery logic here
            pass
    
    return {
        "equity_with_stop": eq,
        "trading_disabled_at": trading_disabled_at,
        "trading_enabled_after_stop": trading_enabled_after_stop,
        "final_capital": eq.iloc[-1],
        "max_drawdown": max_drawdown(eq)
    }

def validate_dd_limit(dd_limit: float) -> dict:
    """
    Validate drawdown limit parameter.
    
    Args:
        dd_limit: Drawdown limit to validate
        
    Returns:
        Validation results
    """
    validation = {
        "valid": True,
        "warnings": [],
        "recommendations": []
    }
    
    # Check range
    if not (-0.5 <= dd_limit <= 0):
        validation["valid"] = False
        validation["warnings"].append(f"Drawdown limit out of range: {dd_limit}")
        validation["recommendations"].append("Use between -0.5 and 0.0")
    
    # Check typical ranges
    if dd_limit > -0.05:
        validation["warnings"].append(f"Very tight drawdown limit: {dd_limit:.1%}")
        validation["recommendations"].append("May stop trading frequently")
    elif dd_limit < -0.30:
        validation["warnings"].append(f"Very loose drawdown limit: {dd_limit:.1%}")
        validation["recommendations"].append("May not provide adequate protection")
    
    # Typical recommendations
    if -0.20 <= dd_limit <= -0.10:
        validation["recommendations"].append("Drawdown limit in typical range (10-20%)")
    
    return validation

# Example usage:
"""
import pandas as pd
import numpy as np

# Generate sample equity curve
np.random.seed(42)
returns = np.random.randn(200) * 0.01
equity = (1 + returns).cumprod() * 100000

# Apply drawdown stop
stopped_equity = apply_dd_stop(equity, dd_limit=-0.15)

# Calculate statistics
stats = calculate_dd_stop_statistics(equity, -0.15)
print(f"Drawdown stop statistics: {stats}")

# Optimize drawdown limit
optimization = optimize_dd_limit(equity)
print(f"Best drawdown limit: {optimization['best_dd_limit']:.1%}")

# Validate limit
validation = validate_dd_limit(-0.15)
print(f"Validation: {validation}")
"""

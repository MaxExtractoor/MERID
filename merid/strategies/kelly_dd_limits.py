"""
Kelly Drawdown Limits for MERID Strategy

Apply hard drawdown stops to Kelly equity paths.
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)

def apply_dd_limit(equity: pd.Series, dd_limit: float = -0.3) -> pd.Series:
    """
    Apply hard drawdown limit to equity curve.
    
    Args:
        equity: Equity curve Series
        dd_limit: Negative fraction (e.g., -0.3 for -30%)
        
    Returns:
        Equity curve with drawdown limit applied
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
        logger.info(f"Drawdown limit ({dd_limit:.1%}) hit at index {stop_index}, equity frozen at {eq.iloc[stop_index]:.3f}")
    
    return eq

def apply_dd_limit_with_recovery(equity: pd.Series, dd_limit: float = -0.3, 
                               recovery_threshold: float = 0.0) -> pd.Series:
    """
    Apply drawdown limit with recovery mechanism.
    
    Args:
        equity: Equity curve Series
        dd_limit: Drawdown limit threshold
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
    recovered = False
    
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
        elif stopped and dd >= recovery_threshold and not recovered:
            # Resume trading from next point
            recovered = True
            break
    
    return eq

def calculate_dd_limit_statistics(equity: pd.Series, dd_limit: float) -> Dict[str, Any]:
    """
    Calculate statistics for drawdown limit application.
    
    Args:
        equity: Original equity curve
        dd_limit: Drawdown limit applied
        
    Returns:
        Statistics dictionary
    """
    if equity.empty:
        return {"error": "Empty equity curve"}
    
    # Apply drawdown limit
    stopped_equity = apply_dd_limit(equity, dd_limit)
    
    # Calculate original statistics
    original_final = equity.iloc[-1]
    original_return = (original_final / equity.iloc[0]) - 1
    
    # Calculate stopped statistics
    stopped_final = stopped_equity.iloc[-1]
    stopped_return = (stopped_final / stopped_equity.iloc[0]) - 1
    
    # Find when stop was triggered
    peak = equity.cummax()
    dd = (equity - peak) / peak.replace(0, np.nan)
    stop_triggered = dd < dd_limit
    
    if stop_triggered.any():
        stop_index = stop_triggered.idxmax()
        stop_time = stop_index
        stop_equity = equity.loc[stop_index]
        stop_drawdown = dd.loc[stop_index]
        stop_time_pct = stop_index / len(equity)
    else:
        stop_time = None
        stop_equity = None
        stop_drawdown = None
        stop_time_pct = 0.0
    
    # Calculate drawdown statistics
    original_dd = dd.min()
    stopped_dd = (stopped_equity - stopped_equity.cummax()).min() / stopped_equity.cummax().max()
    
    return {
        "dd_limit": dd_limit,
        "stop_triggered": stop_triggered.any(),
        "stop_time": stop_time,
        "stop_equity": stop_equity,
        "stop_drawdown": stop_drawdown,
        "stop_time_percentage": stop_time_pct,
        "original_final_capital": original_final,
        "original_return": original_return,
        "stopped_final_capital": stopped_final,
        "stopped_return": stopped_return,
        "capital_preserved": stopped_final / original_final if original_final > 0 else 0.0,
        "return_preserved": stopped_return / original_return if original_return != 0 else 0.0,
        "original_max_drawdown": original_dd,
        "stopped_max_drawdown": stopped_dd,
        "drawdown_reduction": (original_dd - stopped_dd) / abs(original_dd) if original_dd != 0 else 0.0
    }

def optimize_dd_limit(equity: pd.Series, dd_limits: List[float] = None) -> Dict[str, Any]:
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
        dd_limits = [-0.10, -0.15, -0.20, -0.25, -0.30, -0.35, -0.40]
    
    results = []
    
    for dd_limit in dd_limits:
        try:
            stats = calculate_dd_limit_statistics(equity, dd_limit)
            
            if "error" not in stats:
                # Calculate risk-adjusted return
                risk_adj_return = stats["stopped_return"] / abs(stats["stopped_max_drawdown"]) if stats["stopped_max_drawdown"] != 0 else stats["stopped_return"]
                
                results.append({
                    "dd_limit": dd_limit,
                    "stopped_return": stats["stopped_return"],
                    "stopped_max_drawdown": stats["stopped_max_drawdown"],
                    "capital_preserved": stats["capital_preserved"],
                    "stop_triggered": stats["stop_triggered"],
                    "risk_adj_return": risk_adj_return,
                    "drawdown_reduction": stats["drawdown_reduction"]
                })
        except Exception as e:
            logger.error(f"Error testing dd_limit {dd_limit}: {e}")
            continue
    
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

def simulate_dd_limit_with_trading(equity: pd.Series, dd_limit: float, 
                                 trading_enabled_after_stop: bool = False) -> Dict[str, Any]:
    """
    Simulate drawdown limit with trading flag for live MERID.
    
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
    trading_disabled = False
    
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
                trading_disabled = True
                trading_disabled_at = i
                logger.info(f"Trading disabled at index {i}, drawdown={dd:.2%}")
        
        elif not trading_enabled and not trading_enabled_after_stop:
            # Keep equity flat
            eq.iloc[i] = eq.iloc[i-1] if i > 0 else eq.iloc[i]
        elif not trading_enabled and trading_enabled_after_stop:
            # Could implement recovery logic here
            pass
    
    return {
        "equity_with_dd_limit": eq,
        "trading_disabled_at": trading_disabled_at,
        "trading_disabled": trading_disabled,
        "trading_enabled_after_stop": trading_enabled_after_stop,
        "final_capital": eq.iloc[-1],
        "max_drawdown": (eq - eq.cummax()).min() / eq.cummax().max()
    }

def validate_dd_limit(dd_limit: float) -> Dict[str, Any]:
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
    if not (-0.8 <= dd_limit <= 0):
        validation["valid"] = False
        validation["warnings"].append(f"Drawdown limit out of range: {dd_limit}")
        validation["recommendations"].append("Use between -0.8 and 0.0")
    
    # Check typical ranges
    if dd_limit > -0.10:
        validation["warnings"].append(f"Very tight drawdown limit: {dd_limit:.1%}")
        validation["recommendations"].append("May stop trading frequently")
    elif dd_limit < -0.50:
        validation["warnings"].append(f"Very loose drawdown limit: {dd_limit:.1%}")
        validation["recommendations"].append("May not provide adequate protection")
    
    # Typical recommendations
    if -0.30 <= dd_limit <= -0.15:
        validation["recommendations"].append("Drawdown limit in typical range (15-30%)")
    
    # Risk assessment
    if dd_limit > -0.20:
        validation["risk_level"] = "conservative"
    elif dd_limit > -0.35:
        validation["risk_level"] = "moderate"
    else:
        validation["risk_level"] = "aggressive"
    
    return validation

def print_dd_limit_analysis(equity: pd.Series, dd_limits: List[float] = None):
    """
    Print formatted drawdown limit analysis.
    
    Args:
        equity: Equity curve
        dd_limits: List of drawdown limits to test
    """
    if equity.empty:
        print("No equity curve to analyze")
        return
    
    if dd_limits is None:
        dd_limits = [-0.15, -0.20, -0.25, -0.30]
    
    print("\n" + "="*70)
    print("DRAWDOWN LIMIT ANALYSIS")
    print("="*70)
    
    print(f"\nEquity Curve Statistics:")
    print(f"  Starting Capital: {equity.iloc[0]:.2f}")
    print(f"  Final Capital: {equity.iloc[-1]:.2f}")
    print(f"  Total Return: {(equity.iloc[-1] / equity.iloc[0] - 1):.1%}")
    print(f"  Max Drawdown: {(equity - equity.cummax()).min() / equity.cummax().max():.2%}")
    
    print(f"\nDrawdown Limit Analysis:")
    print("-" * 70)
    print(f"{'Limit':<8} {'Capital':<10} {'Return':<10} {'Preserved':<10} {'DD Red':<8} {'Stop':<6}")
    print("-" * 70)
    
    for dd_limit in dd_limits:
        stats = calculate_dd_limit_statistics(equity, dd_limit)
        
        print(f"{dd_limit:<8.1%} {stats['stopped_final_capital']:<10.2f} "
              f"{stats['stopped_return']:<10.1%} {stats['capital_preserved']:<10.1%} "
              f"{stats['drawdown_reduction']:<8.1%} {stats['stop_triggered']!s:<6}")
    
    # Optimization
    optimization = optimize_dd_limit(equity, dd_limits)
    
    if "best_dd_limit" in optimization:
        best = optimization["best_result"]
        print(f"\nOptimal Drawdown Limit: {optimization['best_dd_limit']:.1%}")
        print(f"  Risk-Adjusted Return: {best['risk_adj_return']:.2f}")
        print(f"  Capital Preserved: {best['capital_preserved']:.1%}")
        print(f"  Drawdown Reduction: {best['drawdown_reduction']:.1%}")
    
    print("="*70)

# Example usage for live MERID:
"""
class LiveKellyStrategy:
    def __init__(self, dd_limit=-0.25):
        self.dd_limit = dd_limit
        self.trading_enabled = True
        self.peak_capital = 1.0
        self.current_capital = 1.0
    
    def check_drawdown_limit(self):
        # Calculate current drawdown
        dd = (self.current_capital - self.peak_capital) / self.peak_capital
        
        # Check if limit hit
        if dd < self.dd_limit and self.trading_enabled:
            self.trading_enabled = False
            logger.warning(f"Drawdown limit hit: {dd:.2%}, trading disabled")
            return False
        
        # Update peak
        if self.current_capital > self.peak_capital:
            self.peak_capital = self.current_capital
        
        return self.trading_enabled
    
    def on_trade_pnl(self, pnl):
        if self.trading_enabled:
            self.current_capital *= (1 + pnl)
            return self.check_drawdown_limit()
        return False

# Usage:
strategy = LiveKellyStrategy(dd_limit=-0.25)
# On each trade:
# trading_enabled = strategy.on_trade_pnl(trade_pnl)
# if not trading_enabled: stop opening new positions
"""

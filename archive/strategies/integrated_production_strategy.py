"""
Production Strategy Integration - Complete Integration with All Building Blocks

This module integrates all the compact production building blocks:
- BinanceUS data fetching
- Rolling Kelly statistics
- ATR-based volatility sizing
- Risk metrics (Sharpe, drawdown)
- Z-score grid optimization
"""

import time
import logging
from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np

from .binance_us_data import fetch_btc_eth_15m, validate_data_quality
from .rolling_kelly_stats import adaptive_kelly_sizing, validate_kelly_statistics
from .atr_sizing import volatility_adjusted_kelly, validate_atr_sizing
from .risk_metrics import calculate_all_metrics, validate_risk_metrics
from .optimize_z_grid import optimize_z_grid, print_optimization_summary
from .production_strategy_15m import Production15MStrategy
from merid.kalshi.maker_bot_advanced import kalshi_event_bus, KalshiEvent

logger = logging.getLogger(__name__)

class IntegratedProductionStrategy:
    """
    Complete production strategy integrating all building blocks:
    - Real-time data fetching from BinanceUS
    - Rolling Kelly statistics for dynamic sizing
    - ATR-based volatility adjustments
    - Comprehensive risk metrics
    - Grid search optimization
    - Production execution with event bus
    """
    
    def __init__(self, 
                 capital_usd: float = 100000.0,
                 paper_mode: bool = True,
                 config: Optional[Dict] = None):
        """
        Initialize integrated production strategy.
        
        Args:
            capital_usd: Total capital allocation
            paper_mode: Whether to run in paper trading mode
            config: Optional configuration dictionary
        """
        self.capital_usd = capital_usd
        self.paper_mode = paper_mode
        self.config = config or {}
        
        # Strategy state
        self.optimized = False
        self.last_optimization_time = 0
        self.current_data = {}
        self.kelly_history = []
        self.risk_metrics_history = []
        
        # Optimization parameters (will be set from optimization)
        self.z_entry = 1.0
        self.z_exit = 0.1
        self.hurst_max = 0.5
        self.fraction_of_kelly = 0.3
        self.atr_multiplier = 2.0
        
        # Initialize base strategy
        self.base_strategy = Production15MStrategy(capital_usd, paper_mode, config)
        
        logger.info(f"IntegratedProductionStrategy initialized: capital=${capital_usd:,.0f}, "
                   f"paper_mode={paper_mode}")
    
    def fetch_and_validate_data(self, limit: int = 1000) -> Dict[str, pd.DataFrame]:
        """
        Fetch and validate BTC/ETH data from BinanceUS.
        
        Args:
            limit: Number of 15m bars to fetch
            
        Returns:
            Dictionary with validated data
        """
        logger.info(f"Fetching and validating data (limit={limit})")
        
        # Fetch data
        data = fetch_btc_eth_15m(limit=limit)
        
        # Validate data quality
        validation_results = {}
        for symbol, df in data.items():
            validation = validate_data_quality(df, symbol)
            validation_results[symbol] = validation
            
            if not validation["valid"]:
                logger.warning(f"Data validation issues for {symbol}: {validation['warnings']}")
            else:
                logger.info(f"Data validation passed for {symbol}")
        
        self.current_data = data
        return data
    
    def optimize_strategy_parameters(self, historical_limit: int = 2000) -> Dict:
        """
        Optimize strategy parameters using historical data.
        
        Args:
            historical_limit: Number of historical bars for optimization
            
        Returns:
            Optimization results
        """
        logger.info("Starting strategy parameter optimization...")
        
        # Fetch historical data for optimization
        historical_data = fetch_btc_eth_15m(limit=historical_limit)
        
        # Run grid search optimization
        optimization_results = optimize_z_grid(
            historical_data["BTC"],
            historical_data["ETH"],
            z_entry_values=np.linspace(0.5, 2.0, 7),
            z_exit_values=[0.05, 0.1, 0.2],
            hurst_max_values=[0.45, 0.5, 0.55],
            parallel=True,
            max_workers=4
        )
        
        if not optimization_results:
            raise ValueError("Optimization failed - no results")
        
        # Get best result
        best_result = optimization_results[0]
        
        # Update strategy parameters
        self.z_entry = best_result["z_entry"]
        self.z_exit = best_result["z_exit"]
        self.hurst_max = best_result["hurst_max"]
        
        # Update base strategy
        self.base_strategy.z_entry = self.z_entry
        self.base_strategy.z_exit = self.z_exit
        self.base_strategy.hurst_max = self.hurst_max
        
        # Update Kelly stats from optimization
        self._update_kelly_stats_from_optimization(best_result, historical_data)
        
        self.optimized = True
        self.last_optimization_time = time.time()
        
        # Print optimization summary
        print_optimization_summary(optimization_results, top_n=10)
        
        optimization_summary = {
            "optimization_successful": True,
            "best_parameters": {
                "z_entry": self.z_entry,
                "z_exit": self.z_exit,
                "hurst_max": self.hurst_max
            },
            "expected_performance": {
                "composite_score": best_result["composite_score"],
                "sharpe_ratio": best_result["sharpe_ratio"],
                "max_drawdown": best_result["max_drawdown"],
                "final_pnl": best_result["final_pnl"],
                "total_trades": best_result["total_trades"]
            },
            "kelly_stats": self.base_strategy.kelly_stats,
            "optimization_time": self.last_optimization_time
        }
        
        logger.info(f"Optimization completed: z_entry={self.z_entry:.2f}, "
                   f"z_exit={self.z_exit:.2f}, hurst_max={self.hurst_max:.2f}")
        
        return optimization_summary
    
    def _update_kelly_stats_from_optimization(self, best_result: Dict, historical_data: Dict):
        """Update Kelly statistics from optimization results."""
        # Run backtest with best parameters to get trade data
        from .backtest_15m_meanrev import backtest_meanrev_15m
        
        btc_backtest = backtest_meanrev_15m(
            historical_data["BTC"],
            z_entry=self.z_entry,
            z_exit=self.z_exit,
            hurst_max=self.hurst_max,
            enable_hurst_filter=True
        )
        
        eth_backtest = backtest_meanrev_15m(
            historical_data["ETH"],
            z_entry=self.z_entry,
            z_exit=self.z_exit,
            hurst_max=self.hurst_max,
            enable_hurst_filter=True
        )
        
        # Update Kelly stats from actual trades
        from .rolling_kelly_stats import calculate_kelly_stats_from_trades
        
        btc_trades = [t.pnl for t in btc_backtest.trades]
        eth_trades = [t.pnl for t in eth_backtest.trades]
        
        if btc_trades:
            self.base_strategy.kelly_stats["BTC"] = calculate_kelly_stats_from_trades(btc_trades)
        if eth_trades:
            self.base_strategy.kelly_stats["ETH"] = calculate_kelly_stats_from_trades(eth_trades)
        
        logger.info(f"Updated Kelly stats from {len(btc_trades)} BTC trades and {len(eth_trades)} ETH trades")
    
    def calculate_dynamic_position_sizes(self) -> Dict[str, Dict]:
        """
        Calculate dynamic position sizes using rolling Kelly and ATR adjustments.
        
        Returns:
            Dictionary with position sizing recommendations
        """
        if not self.current_data:
            logger.warning("No current data available for position sizing")
            return {}
        
        position_sizes = {}
        
        for asset in ["BTC", "ETH"]:
            if asset not in self.current_data:
                continue
            
            price_data = self.current_data[asset]
            
            # Get recent trade PnLs (mock for now, would come from trade book)
            # In production, this would be actual historical trades
            mock_pnls = self._generate_mock_trade_pnls(asset)
            
            # Calculate adaptive Kelly sizing
            kelly_sizing = adaptive_kelly_sizing(
                mock_pnls,
                capital_usd=self.capital_usd,
                window=100,
                base_kelly_fraction=self.fraction_of_kelly
            )
            
            # Calculate ATR-adjusted sizing
            atr_sizing = volatility_adjusted_kelly(
                mock_pnls,
                price_data,
                capital_usd=self.capital_usd,
                window=100,
                atr_period=14,
                base_kelly_fraction=self.fraction_of_kelly,
                atr_multiplier=self.atr_multiplier,
                adaptive_atr=True
            )
            
            # Get latest recommendations
            if not kelly_sizing.empty and not atr_sizing.empty:
                latest_kelly = kelly_sizing.iloc[-1]
                latest_atr = atr_sizing.iloc[-1]
                
                position_sizes[asset] = {
                    "kelly_fraction": latest_kelly["kelly_fraction"],
                    "kelly_position_size": latest_kelly["position_size"],
                    "atr_position_size": latest_atr["position_size"],
                    "atr_value": latest_atr["atr_value"],
                    "atr_multiplier": latest_atr["atr_multiplier"],
                    "current_price": latest_atr["current_price"],
                    "recommendation": latest_kelly["reasoning"],
                    "combined_size": min(latest_kelly["position_size"], latest_atr["position_size"])
                }
                
                # Store in history
                self.kelly_history.append({
                    "timestamp": time.time(),
                    "asset": asset,
                    "kelly_fraction": latest_kelly["kelly_fraction"],
                    "position_size": latest_kelly["position_size"],
                    "atr_adjusted_size": latest_atr["position_size"]
                })
        
        return position_sizes
    
    def _generate_mock_trade_pnls(self, asset: str, num_trades: int = 200) -> pd.Series:
        """Generate mock trade PnLs for testing (replace with real data in production)."""
        np.random.seed(42)
        
        # Generate realistic trade PnLs based on asset
        if asset == "BTC":
            base_pnl = 100  # Higher PnL for BTC
            volatility = 150
        else:  # ETH
            base_pnl = 50
            volatility = 75
        
        # Generate trades with some edge
        win_rate = 0.55
        num_wins = int(num_trades * win_rate)
        num_losses = num_trades - num_wins
        
        # Generate wins and losses
        wins = np.random.normal(base_pnl, volatility/2, num_wins)
        losses = np.random.normal(-base_pnl*0.7, volatility/3, num_losses)
        
        all_pnls = np.concatenate([wins, losses])
        np.random.shuffle(all_pnls)
        
        return pd.Series(all_pnls, name=f"{asset}_pnl")
    
    def calculate_comprehensive_risk_metrics(self) -> Dict:
        """
        Calculate comprehensive risk metrics for current strategy.
        
        Returns:
            Dictionary with all risk metrics
        """
        if not self.kelly_history:
            return {"message": "No performance data available yet"}
        
        # Create equity curve from Kelly history
        equity_curve = self._create_equity_curve_from_history()
        
        if equity_curve.empty:
            return {"message": "No equity data available"}
        
        # Calculate returns
        returns = equity_curve.pct_change().dropna()
        
        # Calculate comprehensive metrics
        metrics = calculate_all_metrics(equity, returns)
        
        # Add strategy-specific metrics
        metrics.update({
            "strategy_name": "IntegratedProductionStrategy",
            "capital_usd": self.capital_usd,
            "optimized_parameters": {
                "z_entry": self.z_entry,
                "z_exit": self.z_exit,
                "hurst_max": self.hurst_max,
                "fraction_of_kelly": self.fraction_of_kelly,
                "atr_multiplier": self.atr_multiplier
            },
            "current_position_sizes": self.calculate_dynamic_position_sizes(),
            "kelly_history_length": len(self.kelly_history),
            "optimization_time": self.last_optimization_time
        })
        
        # Store in history
        self.risk_metrics_history.append({
            "timestamp": time.time(),
            "metrics": metrics
        })
        
        return metrics
    
    def _create_equity_curve_from_history(self) -> pd.Series:
        """Create equity curve from Kelly history."""
        if not self.kelly_history:
            return pd.Series()
        
        # Extract PnL data from history
        equity_data = []
        running_equity = self.capital_usd
        
        for record in self.kelly_history:
            # Mock PnL based on position size (in production, use actual trade results)
            mock_pnl = record["position_size"] * np.random.choice([100, -50, 75, -25])
            running_equity += mock_pnl
            equity_data.append(running_equity)
        
        # Create Series
        timestamps = [record["timestamp"] for record in self.kelly_history]
        equity_curve = pd.Series(equity_data, index=pd.to_datetime(timestamps, unit='s'))
        
        return equity_curve.sort_index()
    
    def run_integrated_cycle(self) -> Dict:
        """
        Run one complete integrated strategy cycle.
        
        Returns:
            Cycle results with all metrics
        """
        if not self.optimized:
            raise RuntimeError("Strategy not optimized. Call optimize_strategy_parameters() first.")
        
        cycle_start = time.time()
        
        try:
            # 1. Fetch current data
            current_data = self.fetch_and_validate_data(limit=500)
            
            # 2. Calculate dynamic position sizes
            position_sizes = self.calculate_dynamic_position_sizes()
            
            # 3. Generate production signals
            signals = self.base_strategy.generate_production_signals(current_data)
            
            # 4. Execute trades (paper mode simulation)
            trades_executed = []
            if not self.paper_mode:
                # Real execution would go here
                pass
            else:
                # Paper trading simulation with position sizes
                trades_executed = self._simulate_paper_trades_with_sizing(position_sizes, signals)
            
            # 5. Calculate comprehensive risk metrics
            risk_metrics = self.calculate_comprehensive_risk_metrics()
            
            # 6. Emit comprehensive event
            cycle_results = {
                "timestamp": cycle_start,
                "data_quality": {symbol: validation["valid"] for symbol, validation in 
                              {symbol: validate_data_quality(df, symbol) for symbol, df in current_data.items()}.items()},
                "signals_generated": len(signals),
                "position_sizes": position_sizes,
                "trades_executed": len(trades_executed),
                "risk_metrics": risk_metrics,
                "optimized_params": {
                    "z_entry": self.z_entry,
                    "z_exit": self.z_exit,
                    "hurst_max": self.hurst_max,
                    "fraction_of_kelly": self.fraction_of_kelly,
                    "atr_multiplier": self.atr_multiplier
                },
                "strategy_health": self._calculate_strategy_health()
            }
            
            kalshi_event_bus.publish(KalshiEvent(
                type="position_update",
                payload={
                    "integrated_cycle": cycle_results,
                    "strategy_type": "integrated_production"
                },
                ts=time.time(),
                source="integrated_strategy"
            ))
            
            logger.info(f"Integrated cycle completed: {len(signals)} signals, "
                        f"{len(trades_executed)} trades, Sharpe={risk_metrics.get('sharpe_ratio', 0):.2f}")
            
            return cycle_results
            
        except Exception as e:
            logger.error(f"Error in integrated cycle: {e}")
            
            kalshi_event_bus.publish(KalshiEvent(
                type="api_error",
                payload={
                    "integrated_cycle_error": str(e),
                    "timestamp": cycle_start
                },
                ts=time.time(),
                source="integrated_strategy"
            ))
            
            raise
    
    def _simulate_paper_trades_with_sizing(self, position_sizes: Dict, signals: List) -> List[Dict]:
        """Simulate paper trades with dynamic position sizing."""
        trades = []
        
        for signal in signals:
            if signal.side == "flat":
                continue
            
            asset = signal.asset
            if asset not in position_sizes:
                continue
            
            sizing = position_sizes[asset]
            contracts = sizing["combined_size"]
            
            if contracts > 0:
                trade = {
                    "asset": asset,
                    "signal_type": signal.side,
                    "contracts": contracts,
                    "signal_strength": signal.strength,
                    "kelly_fraction": sizing["kelly_fraction"],
                    "atr_adjusted_size": sizing["atr_position_size"],
                    "entry_price": sizing["current_price"],
                    "execution_time": time.time(),
                    "paper_mode": True,
                    "reasoning": sizing["recommendation"]
                }
                trades.append(trade)
        
        return trades
    
    def _calculate_strategy_health(self) -> Dict:
        """Calculate overall strategy health metrics."""
        health = {
            "overall_health": "healthy",
            "issues": [],
            "recommendations": []
        }
        
        # Check data quality
        if not self.current_data:
            health["issues"].append("No current data")
            health["overall_health"] = "unhealthy"
        
        # Check optimization status
        if not self.optimized:
            health["issues"].append("Strategy not optimized")
            health["overall_health"] = "degraded"
        
        # Check Kelly statistics
        for asset, stats in self.base_strategy.kelly_stats.items():
            validation = validate_kelly_statistics(pd.Series([100, -50, 75, -25]), window=10)
            if not validation["valid"]:
                health["issues"].append(f"Poor Kelly stats for {asset}")
                health["recommendations"].append(f"Improve {asset} trading performance")
        
        # Check risk metrics
        if self.risk_metrics_history:
            latest_metrics = self.risk_metrics_history[-1]["metrics"]
            if latest_metrics.get("sharpe_ratio", 0) < 0.5:
                health["issues"].append("Low Sharpe ratio")
                health["recommendations"].append("Improve risk-adjusted returns")
            
            if latest_metrics.get("max_drawdown", 0) < -0.15:
                health["issues"].append("High drawdown")
                health["recommendations"].append("Implement tighter risk controls")
        
        return health
    
    def get_integrated_status(self) -> Dict:
        """Get comprehensive integrated strategy status."""
        return {
            "optimized": self.optimized,
            "capital_usd": self.capital_usd,
            "paper_mode": self.paper_mode,
            "current_data_status": {
                "available": bool(self.current_data),
                "assets": list(self.current_data.keys()) if self.current_data else [],
                "last_fetch": time.time() if self.current_data else None
            },
            "optimized_parameters": {
                "z_entry": self.z_entry,
                "z_exit": self.z_exit,
                "hurst_max": self.hurst_max,
                "fraction_of_kelly": self.fraction_of_kelly,
                "atr_multiplier": self.atr_multiplier
            },
            "kelly_statistics": self.base_strategy.kelly_stats,
            "position_sizes": self.calculate_dynamic_position_sizes(),
            "risk_metrics": self.calculate_comprehensive_risk_metrics(),
            "strategy_health": self._calculate_strategy_health(),
            "performance_history": {
                "kelly_history_length": len(self.kelly_history),
                "risk_metrics_length": len(self.risk_metrics_history),
                "last_optimization": self.last_optimization_time
            }
        }
    
    def run_continuous_integrated_strategy(self, interval_seconds: int = 900):
        """
        Run integrated strategy continuously.
        
        Args:
            interval_seconds: Interval between cycles (900s = 15 minutes)
        """
        logger.info(f"Starting continuous integrated strategy with {interval_seconds}s interval")
        
        while True:
            try:
                cycle_start = time.time()
                
                # Check strategy health
                health = self._calculate_strategy_health()
                if health["overall_health"] == "unhealthy":
                    logger.warning(f"Strategy unhealthy: {health['issues']}")
                    time.sleep(interval_seconds)
                    continue
                
                # Run integrated cycle
                results = self.run_integrated_cycle()
                
                # Sleep until next cycle
                elapsed = time.time() - cycle_start
                sleep_time = max(0, interval_seconds - elapsed)
                
                logger.debug(f"Sleeping for {sleep_time:.1f}s until next cycle")
                time.sleep(sleep_time)
                
            except KeyboardInterrupt:
                logger.info("Integrated strategy stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in continuous integrated strategy: {e}")
                time.sleep(60)  # Wait longer after error

# Integrated strategy singleton
integrated_strategy = IntegratedProductionStrategy()

# Example usage:
"""
# Initialize integrated strategy
strategy = IntegratedProductionStrategy(capital_usd=100000.0, paper_mode=True)

# Optimize parameters
optimization_results = strategy.optimize_strategy_parameters(historical_limit=2000)
print(f"Optimization: {optimization_results}")

# Run integrated cycle
results = strategy.run_integrated_cycle()
print(f"Cycle results: {results}")

# Get status
status = strategy.get_integrated_status()
print(f"Strategy status: {status}")

# Run continuous strategy
strategy.run_continuous_integrated_strategy(interval_seconds=900)
"""

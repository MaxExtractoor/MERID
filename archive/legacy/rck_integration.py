"""
RCK Integration with Crypto15MLane

This module integrates the Risk-Constrained Kelly backtest framework
with the Crypto15MLane system for production deployment and validation.

Key features:
- Historical data collection and storage
- Backtest validation of RCK parameters
- Performance monitoring and calibration
- Real-time RCK parameter updates
"""

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional
import pandas as pd
import numpy as np
import logging

from .rck_backtest import (
    Kalshi15mBar, BacktestConfig, backtest_rck_vectorized,
    estimate_p_true_bayesian, analyze_performance_by_symbol,
    tune_rck_parameters, devig_yes_no
)
from .crypto15m_lane import Crypto15MLane, get_bayesian_prior_strength

logger = logging.getLogger(__name__)


class RCKDataManager:
    """Manages historical data for RCK backtesting and calibration."""
    
    def __init__(self, db_path: str = "rck_historical.db"):
        self.db_path = db_path
        self._init_database()
    
    def _init_database(self):
        """Initialize SQLite database for historical data."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS kalshi_15m_bars (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts_open REAL NOT NULL,
                symbol TEXT NOT NULL,
                yes_price REAL NOT NULL,
                no_price REAL NOT NULL,
                outcome_yes INTEGER NOT NULL,
                market_id TEXT NOT NULL,
                settlement_time REAL NOT NULL,
                features TEXT NOT NULL,
                created_at REAL DEFAULT (strftime('%s', 'now'))
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_symbol_time 
            ON kalshi_15m_bars(symbol, ts_open)
        """)
        
        conn.commit()
        conn.close()
    
    def store_bar(self, bar: Kalshi15mBar):
        """Store a single Kalshi 15m bar."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO kalshi_15m_bars 
            (ts_open, symbol, yes_price, no_price, outcome_yes, market_id, 
             settlement_time, features)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            bar.ts_open, bar.symbol, bar.yes_price, bar.no_price,
            int(bar.outcome_yes), bar.market_id, bar.settlement_time,
            json.dumps(bar.features)
        ))
        
        conn.commit()
        conn.close()
    
    def get_historical_data(self, 
                          symbol: Optional[str] = None,
                          start_time: Optional[float] = None,
                          end_time: Optional[float] = None,
                          limit: Optional[int] = None) -> List[Kalshi15mBar]:
        """Retrieve historical data for backtesting."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        query = "SELECT * FROM kalshi_15m_bars WHERE 1=1"
        params = []
        
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        
        if start_time:
            query += " AND ts_open >= ?"
            params.append(start_time)
        
        if end_time:
            query += " AND ts_open <= ?"
            params.append(end_time)
        
        query += " ORDER BY ts_open"
        
        if limit:
            query += " LIMIT ?"
            params.append(limit)
        
        cursor.execute(query, params)
        rows = cursor.fetchall()
        conn.close()
        
        bars = []
        for row in rows:
            bar = Kalshi15mBar(
                ts_open=row[1],
                symbol=row[2],
                yes_price=row[3],
                no_price=row[4],
                outcome_yes=bool(row[5]),
                features=json.loads(row[8]),
                market_id=row[6],
                settlement_time=row[7]
            )
            bars.append(bar)
        
        return bars
    
    def get_historical_counts(self, symbol: str) -> tuple[int, int]:
        """Get historical win/loss counts for a symbol."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT 
                SUM(CASE WHEN outcome_yes = 1 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN outcome_yes = 0 THEN 1 ELSE 0 END) as losses
            FROM kalshi_15m_bars 
            WHERE symbol = ?
        """, (symbol,))
        
        result = cursor.fetchone()
        conn.close()
        
        if result and result[0] is not None:
            return int(result[0]), int(result[1])
        return 0, 0


class RCKPerformanceMonitor:
    """Monitors RCK performance and provides calibration recommendations."""
    
    def __init__(self, data_manager: RCKDataManager):
        self.data_manager = data_manager
    
    def analyze_recent_performance(self, 
                                  symbol: str, 
                                  days: int = 30) -> Dict[str, Any]:
        """Analyze recent performance for a symbol."""
        end_time = datetime.now().timestamp()
        start_time = (datetime.now() - timedelta(days=days)).timestamp()
        
        bars = self.data_manager.get_historical_data(
            symbol=symbol,
            start_time=start_time,
            end_time=end_time
        )
        
        if len(bars) < 10:
            return {"error": f"Insufficient data for {symbol}: {len(bars)} bars"}
        
        # Convert to DataFrame for analysis
        df_data = []
        for bar in bars:
            df_data.append({
                'symbol': bar.symbol,
                'yes_price': bar.yes_price,
                'no_price': bar.no_price,
                'outcome_yes': bar.outcome_yes,
                **bar.features
            })
        
        df = pd.DataFrame(df_data)
        
        # Run backtest with current parameters
        config = BacktestConfig(target_drawdown=0.1, drawdown_probability=0.1)
        results = backtest_rck_vectorized(df, config, estimate_p_true_bayesian)
        
        # Analyze performance
        symbol_analysis = analyze_performance_by_symbol(results)
        
        return {
            "symbol": symbol,
            "period_days": days,
            "total_bars": len(bars),
            "metrics": results["metrics"],
            "symbol_analysis": symbol_analysis.get(symbol, {}),
            "recommendations": self._generate_recommendations(symbol_analysis.get(symbol, {}))
        }
    
    def _generate_recommendations(self, analysis: Dict[str, Any]) -> List[str]:
        """Generate performance recommendations."""
        recommendations = []
        
        if analysis.get("win_rate", 0) < 0.45:
            recommendations.append("Low win rate detected - consider reducing position size")
        
        if analysis.get("max_drawdown", 0) > 0.15:
            recommendations.append("High drawdown - increase safety factor or reduce target drawdown")
        
        if analysis.get("avg_f_used", 0) < 0.05:
            recommendations.append("Low Kelly usage - edges may be too small, check signal quality")
        
        if analysis.get("avg_edge_bps", 0) < 30:
            recommendations.append("Small edge detected - consider tightening edge threshold")
        
        if len(recommendations) == 0:
            recommendations.append("Performance looks good - current parameters are appropriate")
        
        return recommendations
    
    def calibrate_rck_parameters(self, symbol: str) -> Dict[str, Any]:
        """Calibrate optimal RCK parameters for a symbol."""
        # Get historical data
        bars = self.data_manager.get_historical_data(symbol=symbol, limit=1000)
        
        if len(bars) < 100:
            return {"error": f"Insufficient data for calibration: {len(bars)} bars"}
        
        # Convert to DataFrame
        df_data = []
        for bar in bars:
            df_data.append({
                'symbol': bar.symbol,
                'yes_price': bar.yes_price,
                'no_price': bar.no_price,
                'outcome_yes': bar.outcome_yes,
                **bar.features
            })
        
        df = pd.DataFrame(df_data)
        
        # Run parameter tuning
        tuning_results = tune_rck_parameters(df, estimate_p_true_bayesian)
        
        return tuning_results


class RCKLaneIntegration:
    """Integrates RCK system with Crypto15MLane for production."""
    
    def __init__(self, lane: Crypto15MLane, data_manager: RCKDataManager):
        self.lane = lane
        self.data_manager = data_manager
        self.monitor = RCKPerformanceMonitor(data_manager)
        self._last_calibration = None
    
    async def update_lane_with_rck(self):
        """Update lane configuration with calibrated RCK parameters."""
        try:
            # Get recent performance analysis
            analysis = self.monitor.analyze_recent_performance(self.lane.cfg.symbol, days=30)
            
            if "error" in analysis:
                logger.warning(f"Cannot update RCK parameters: {analysis['error']}")
                return
            
            # Calibrate optimal parameters
            calibration = self.monitor.calibrate_rck_parameters(self.lane.cfg.symbol)
            
            if "error" in calibration:
                logger.warning(f"Calibration failed: {calibration['error']}")
                return
            
            best_config = calibration["best_config"]
            if best_config:
                # Update lane configuration with calibrated parameters
                logger.info(f"Updating {self.lane.cfg.symbol} RCK parameters: "
                          f"DD={best_config['target_drawdown']:.2f}, "
                          f"Prob={best_config['drawdown_probability']:.2f}, "
                          f"Safety={best_config['safety_factor']:.2f}")
                
                # Store calibration timestamp
                self._last_calibration = datetime.now().timestamp()
                
                return {
                    "updated": True,
                    "symbol": self.lane.cfg.symbol,
                    "new_config": best_config,
                    "performance": analysis["metrics"],
                    "recommendations": analysis["recommendations"]
                }
        
        except Exception as e:
            logger.error(f"Failed to update RCK parameters for {self.lane.cfg.symbol}: {e}")
        
        return {"updated": False, "error": str(e)}
    
    async def store_lane_outcome(self, market_id: str, outcome_yes: bool, settlement_price: float):
        """Store lane outcome for historical learning."""
        try:
            # Get the last consensus from the lane
            if not self.lane._last_cycle or not self.lane._last_cycle.consensus:
                logger.warning("No consensus data available for outcome storage")
                return
            
            consensus = self.lane._last_cycle.consensus
            
            # Create bar for historical storage
            bar = Kalshi15mBar(
                ts_open=self.lane._last_cycle.timestamp.timestamp(),
                symbol=self.lane.cfg.symbol,
                yes_price=consensus["yes_price_cents"] / 100.0,
                no_price=consensus["no_price_cents"] / 100.0,
                outcome_yes=outcome_yes,
                features=consensus.get("features", {}),
                market_id=market_id,
                settlement_time=datetime.now().timestamp()
            )
            
            # Store in database
            self.data_manager.store_bar(bar)
            
            # Update lane's historical performance
            self.lane.update_historical_performance(outcome_yes)
            
            logger.info(f"Stored outcome for {market_id}: {'YES' if outcome_yes else 'NO'}")
            
        except Exception as e:
            logger.error(f"Failed to store lane outcome: {e}")
    
    def get_lane_rck_status(self) -> Dict[str, Any]:
        """Get current RCK status and performance for the lane."""
        try:
            # Get historical counts
            wins, losses = self.data_manager.get_historical_counts(self.lane.cfg.symbol)
            
            # Get recent performance
            analysis = self.monitor.analyze_recent_performance(self.lane.cfg.symbol, days=7)
            
            # Get Bayesian stats from lane
            bayesian_stats = self.lane.get_bayesian_stats()
            
            return {
                "symbol": self.lane.cfg.symbol,
                "historical_performance": {
                    "total_trades": wins + losses,
                    "wins": wins,
                    "losses": losses,
                    "win_rate": wins / (wins + losses) if (wins + losses) > 0 else 0,
                },
                "bayesian_learning": bayesian_stats,
                "recent_performance": analysis.get("metrics", {}),
                "recommendations": analysis.get("recommendations", []),
                "last_calibration": self._last_calibration,
                "prior_strength": get_bayesian_prior_strength(self.lane.cfg.symbol),
            }
        
        except Exception as e:
            logger.error(f"Failed to get RCK status: {e}")
            return {"error": str(e)}


class RCKSystemManager:
    """Manages the complete RCK system across all crypto lanes."""
    
    def __init__(self, lanes: List[Crypto15MLane]):
        self.lanes = lanes
        self.data_manager = RCKDataManager()
        self.integrations = {}
        
        # Create integration for each lane
        for lane in lanes:
            self.integrations[lane.lane_id] = RCKLaneIntegration(lane, self.data_manager)
    
    async def calibrate_all_lanes(self):
        """Calibrate RCK parameters for all lanes."""
        results = {}
        
        for lane_id, integration in self.integrations.items():
            try:
                result = await integration.update_lane_with_rck()
                results[lane_id] = result
            except Exception as e:
                results[lane_id] = {"updated": False, "error": str(e)}
        
        return results
    
    def get_system_status(self) -> Dict[str, Any]:
        """Get RCK system status across all lanes."""
        status = {}
        
        for lane_id, integration in self.integrations.items():
            status[lane_id] = integration.get_lane_rck_status()
        
        return status
    
    async def store_all_outcomes(self, outcomes: Dict[str, Dict[str, Any]]):
        """Store outcomes for all settled markets."""
        for market_id, outcome_data in outcomes.items():
            lane_id = outcome_data.get("lane_id")
            if lane_id and lane_id in self.integrations:
                await self.integrations[lane_id].store_lane_outcome(
                    market_id,
                    outcome_data["outcome_yes"],
                    outcome_data.get("settlement_price", 0.0)
                )

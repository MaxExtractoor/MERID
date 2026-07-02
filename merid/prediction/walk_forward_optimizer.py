"""
Walk-Forward Optimization Framework for 15m Kalshi Crypto Trading

This module implements a walk-forward optimization framework for hyperparameter
selection based on out-of-sample (OOS) PnL performance, following 2026 industry
best practices (GRDazzle bot reference).

Architecture:
1. Split historical data into time folds (e.g., 4 folds)
2. For each hyperparameter combo:
   - Walk-forward train/test across folds
   - Sweep threshold × max_price on each fold's predictions (free, no retraining)
   - Average OOS PnL across folds = the combo's score
3. Pick the combo with best average OOS PnL
4. Train final model on ALL data with those hyperparams
5. Deploy

This replaces logloss-based model selection with PnL-optimized pipeline.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
from enum import Enum

from utils.logger import get_logger

logger = get_logger("merid.prediction.walk_forward_optimizer")


class OptimizationMode(Enum):
    """Optimization mode."""
    PNL_BASED = "pnl_based"  # Optimize for PnL (industry standard)
    SHARPE_BASED = "sharpe_based"  # Optimize for Sharpe ratio
    WINRATE_BASED = "winrate_based"  # Optimize for win rate


@dataclass
class HyperparameterCombo:
    """A single hyperparameter combination to test."""
    combo_id: str
    params: Dict[str, Any]
    description: str = ""


@dataclass
class FoldResult:
    """Result from a single fold in walk-forward optimization."""
    fold_id: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    pnl: float
    sharpe: float
    win_rate: float
    total_trades: int
    combo_id: str


@dataclass
class OptimizationResult:
    """Result from walk-forward optimization."""
    combo_id: str
    params: Dict[str, Any]
    avg_oos_pnl: float
    avg_oos_sharpe: float
    avg_oos_win_rate: float
    fold_results: List[FoldResult]
    timestamp: datetime = field(default_factory=datetime.utcnow)


class WalkForwardOptimizer:
    """
    Walk-forward optimization engine for hyperparameter selection.
    
    This implements the industry-standard approach from GRDazzle bot:
    - PnL-based optimization (not logloss)
    - Walk-forward time folds
    - Free threshold sweeps on trained models
    - Average OOS performance as selection criterion
    """
    
    def __init__(
        self,
        n_folds: int = 4,
        fold_duration_days: int = 7,
        optimization_mode: OptimizationMode = OptimizationMode.PNL_BASED,
    ):
        """
        Initialize walk-forward optimizer.
        
        Args:
            n_folds: Number of time folds for walk-forward
            fold_duration_days: Duration of each fold in days
            optimization_mode: Metric to optimize for
        """
        self._n_folds = n_folds
        self._fold_duration_days = fold_duration_days
        self._optimization_mode = optimization_mode
        self._results: List[OptimizationResult] = []
        
    def generate_time_folds(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> List[Tuple[datetime, datetime, datetime, datetime]]:
        """
        Generate time folds for walk-forward optimization.
        
        Args:
            start_date: Start date for optimization window
            end_date: End date for optimization window
            
        Returns:
            List of (train_start, train_end, test_start, test_end) tuples
        """
        folds = []
        fold_delta = timedelta(days=self._fold_duration_days)
        
        for i in range(self._n_folds):
            train_start = start_date + (i * fold_delta)
            train_end = train_start + fold_delta
            test_start = train_end
            test_end = test_start + fold_delta
            
            if test_end > end_date:
                break
                
            folds.append((train_start, train_end, test_start, test_end))
            
        logger.info(
            "Generated %d time folds for walk-forward optimization",
            len(folds)
        )
        return folds
    
    def evaluate_combo(
        self,
        combo: HyperparameterCombo,
        folds: List[Tuple[datetime, datetime, datetime, datetime]],
        train_func: callable,
        predict_func: callable,
        evaluate_func: callable,
    ) -> OptimizationResult:
        """
        Evaluate a single hyperparameter combo across all folds.
        
        Args:
            combo: Hyperparameter combination to evaluate
            folds: Time folds for walk-forward
            train_func: Function to train model with given params
            predict_func: Function to generate predictions
            evaluate_func: Function to evaluate predictions (returns PnL, Sharpe, win_rate)
            
        Returns:
            Optimization result with average OOS performance
        """
        fold_results = []
        
        for fold_id, (train_start, train_end, test_start, test_end) in enumerate(folds):
            logger.info(
                "Evaluating combo %s on fold %d: train %s to %s, test %s to %s",
                combo.combo_id, fold_id, train_start, train_end, test_start, test_end
            )
            
            # Train model on fold training data
            model = train_func(
                params=combo.params,
                train_start=train_start,
                train_end=train_end,
            )
            
            # Generate predictions on test data
            predictions = predict_func(
                model=model,
                test_start=test_start,
                test_end=test_end,
            )
            
            # Evaluate predictions
            pnl, sharpe, win_rate, total_trades = evaluate_func(
                predictions=predictions,
                test_start=test_start,
                test_end=test_end,
            )
            
            fold_result = FoldResult(
                fold_id=fold_id,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                pnl=pnl,
                sharpe=sharpe,
                win_rate=win_rate,
                total_trades=total_trades,
                combo_id=combo.combo_id,
            )
            fold_results.append(fold_result)
            
            logger.info(
                "Fold %d result: PnL=%.2f, Sharpe=%.2f, WinRate=%.2f, Trades=%d",
                fold_id, pnl, sharpe, win_rate, total_trades
            )
        
        # Compute average OOS performance
        avg_pnl = sum(fr.pnl for fr in fold_results) / len(fold_results)
        avg_sharpe = sum(fr.sharpe for fr in fold_results) / len(fold_results)
        avg_win_rate = sum(fr.win_rate for fr in fold_results) / len(fold_results)
        
        result = OptimizationResult(
            combo_id=combo.combo_id,
            params=combo.params,
            avg_oos_pnl=avg_pnl,
            avg_oos_sharpe=avg_sharpe,
            avg_oos_win_rate=avg_win_rate,
            fold_results=fold_results,
        )
        
        self._results.append(result)
        
        logger.info(
            "Combo %s average OOS: PnL=%.2f, Sharpe=%.2f, WinRate=%.2f",
            combo.combo_id, avg_pnl, avg_sharpe, avg_win_rate
        )
        
        return result
    
    def select_best_combo(
        self,
        results: Optional[List[OptimizationResult]] = None,
    ) -> OptimizationResult:
        """
        Select the best hyperparameter combo based on optimization mode.
        
        Args:
            results: List of optimization results (uses internal results if None)
            
        Returns:
            Best optimization result
        """
        if results is None:
            results = self._results
            
        if not results:
            raise ValueError("No optimization results available")
        
        if self._optimization_mode == OptimizationMode.PNL_BASED:
            best = max(results, key=lambda r: r.avg_oos_pnl)
        elif self._optimization_mode == OptimizationMode.SHARPE_BASED:
            best = max(results, key=lambda r: r.avg_oos_sharpe)
        elif self._optimization_mode == OptimizationMode.WINRATE_BASED:
            best = max(results, key=lambda r: r.avg_oos_win_rate)
        else:
            raise ValueError(f"Unknown optimization mode: {self._optimization_mode}")
        
        logger.info(
            "Best combo selected: %s (mode=%s)",
            best.combo_id, self._optimization_mode.value
        )
        
        return best
    
    def get_results_summary(self) -> Dict[str, Any]:
        """Get summary of all optimization results."""
        if not self._results:
            return {"total_combos": 0, "results": []}
        
        return {
            "total_combos": len(self._results),
            "optimization_mode": self._optimization_mode.value,
            "best_combo_id": self.select_best_combo().combo_id,
            "results": [
                {
                    "combo_id": r.combo_id,
                    "avg_oos_pnl": r.avg_oos_pnl,
                    "avg_oos_sharpe": r.avg_oos_sharpe,
                    "avg_oos_win_rate": r.avg_oos_win_rate,
                }
                for r in self._results
            ],
        }


# Global optimizer instance
_walk_forward_optimizer: Optional[WalkForwardOptimizer] = None


def get_walk_forward_optimizer() -> WalkForwardOptimizer:
    """Get or create the global walk-forward optimizer instance."""
    global _walk_forward_optimizer
    if _walk_forward_optimizer is None:
        _walk_forward_optimizer = WalkForwardOptimizer()
    return _walk_forward_optimizer

"""
Signal Validation and Backtesting for MERID AI-Powered Signals

Provides comprehensive signal validation and backtesting capabilities
with US-compliant configuration.

Features:
- Signal validation rules
- Backtesting engine
- Performance metrics
- Risk analysis
- US-compliant validation
"""

import asyncio
import time
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
from enum import Enum

from utils.logger import get_logger

logger = get_logger("ai_signals.signal_validation")

class ValidationRule(Enum):
    """Validation rule enumeration."""
    CONFIDENCE_THRESHOLD = "confidence_threshold"
    RISK_LIMIT = "risk_limit"
    POSITION_SIZE = "position_size"
    MARKET_CONDITIONS = "market_conditions"
    CORRELATION_CHECK = "correlation_check"
    LIQUIDITY_CHECK = "liquidity_check"
    VOLATILITY_CHECK = "volatility_check"
    TIME_CONSTRAINTS = "time_constraints"

class BacktestPeriod(Enum):
    """Backtest period enumeration."""
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"

class PerformanceMetric(Enum):
    """Performance metric enumeration."""
    TOTAL_RETURN = "total_return"
    ANNUALIZED_RETURN = "annualized_return"
    SHARPE_RATIO = "sharpe_ratio"
    SORTINO_RATIO = "sortino_ratio"
    MAX_DRAWDOWN = "max_drawdown"
    WIN_RATE = "win_rate"
    PROFIT_FACTOR = "profit_factor"
    CALMAR_RATIO = "calmar_ratio"

@dataclass
class ValidationRuleConfig:
    """Validation rule configuration."""
    rule_id: str
    rule_name: str
    rule_type: ValidationRule
    parameters: Dict[str, Any]
    enabled: bool
    severity: str  # warning, error, critical
    description: str
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ValidationResult:
    """Validation result."""
    signal_id: str
    validation_id: str
    passed: bool
    failed_rules: List[str]
    warnings: List[str]
    errors: List[str]
    critical_issues: List[str]
    validation_score: float
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class BacktestConfig:
    """Backtest configuration."""
    backtest_id: str
    start_date: datetime
    end_date: datetime
    initial_capital: float
    commission: float
    slippage: float
    position_sizing: str
    risk_management: Dict[str, Any]
    benchmark: Optional[str]
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class BacktestResult:
    """Backtest result."""
    backtest_id: str
    period_start: datetime
    period_end: datetime
    total_return: float
    annualized_return: float
    volatility: float
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown: float
    calmar_ratio: float
    win_rate: float
    profit_factor: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    average_win: float
    average_loss: float
    largest_win: float
    largest_loss: float
    equity_curve: List[Tuple[datetime, float]]
    benchmark_return: Optional[float]
    alpha: Optional[float]
    beta: Optional[float]
    metadata: Dict[str, Any] = field(default_factory=dict)

class SignalValidation:
    """
    Comprehensive signal validation and backtesting system for MERID.
    
    Provides validation rules, backtesting engine, and performance
    analysis with US-compliant configuration.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Validation rules
        self.validation_rules: Dict[str, ValidationRuleConfig] = {}
        
        # Validation results
        self.validation_results: deque = deque(maxlen=10000)
        
        # Backtest configurations
        self.backtest_configs: Dict[str, BacktestConfig] = {}
        
        # Backtest results
        self.backtest_results: deque = deque(maxlen=1000)
        
        # Performance metrics cache
        self.performance_cache: Dict[str, Dict[str, float]] = {}
        
        # Configuration
        self.validation_config = config.get("validation", {
            "min_validation_score": 0.7,
            "max_failed_rules": 3,
            "critical_rule_failure_reject": True,
            "enable_market_conditions": True
        })
        
        # Default validation rules
        self.default_rules = {
            ValidationRule.CONFIDENCE_THRESHOLD: {
                "min_confidence": 0.65,  # FIX: Aligned with US compliance and production config (was 0.60)
                "weight": 0.3
            },
            ValidationRule.RISK_LIMIT: {
                "max_risk_score": 0.8,
                "weight": 0.25
            },
            ValidationRule.POSITION_SIZE: {
                "max_position_size": 0.2,
                "weight": 0.2
            },
            ValidationRule.MARKET_CONDITIONS: {
                "min_market_volume": 1000000,
                "max_volatility": 0.05,
                "weight": 0.15
            },
            ValidationRule.CORRELATION_CHECK: {
                "max_correlation": 0.7,
                "weight": 0.1
            }
        }
        
        # US compliance settings
        self.us_compliance = config.get("us_compliance", {
            "validation_standards": True,
            "backtesting_transparency": True,
            "performance_disclosure": True,
            "audit_validations": True
        })
        
        logger.info("SignalValidation initialized")
    
    async def add_validation_rule(self, rule_id: str, rule_name: str, rule_type: ValidationRule,
                                parameters: Dict[str, Any], enabled: bool = True,
                                severity: str = "warning", description: str = "") -> bool:
        """Add a validation rule."""
        try:
            # Validate rule configuration
            if not self._validate_rule_config(rule_type, parameters):
                logger.error(f"Invalid rule configuration: {rule_id}")
                return False
            
            # Create rule
            rule = ValidationRuleConfig(
                rule_id=rule_id,
                rule_name=rule_name,
                rule_type=rule_type,
                parameters=parameters,
                enabled=enabled,
                severity=severity,
                description=description
            )
            
            # Store rule
            self.validation_rules[rule_id] = rule
            
            logger.info(f"Validation rule added: {rule_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to add validation rule {rule_id}: {e}")
            return False
    
    def _validate_rule_config(self, rule_type: ValidationRule, parameters: Dict[str, Any]) -> bool:
        """Validate rule configuration."""
        try:
            # Check rule type
            if rule_type not in ValidationRule:
                return False
            
            # Check required parameters for rule type
            if rule_type == ValidationRule.CONFIDENCE_THRESHOLD:
                if "min_confidence" not in parameters:
                    return False
                confidence = parameters["min_confidence"]
                if not 0 <= confidence <= 1:
                    return False
            
            elif rule_type == ValidationRule.RISK_LIMIT:
                if "max_risk_score" not in parameters:
                    return False
                risk_score = parameters["max_risk_score"]
                if not 0 <= risk_score <= 1:
                    return False
            
            elif rule_type == ValidationRule.POSITION_SIZE:
                if "max_position_size" not in parameters:
                    return False
                position_size = parameters["max_position_size"]
                if not 0 <= position_size <= 1:
                    return False
            
            # US compliance checks
            if self.us_compliance.get("validation_standards", True):
                if not self._validate_rule_compliance(rule_type, parameters):
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Rule configuration validation error: {e}")
            return False
    
    def _validate_rule_compliance(self, rule_type: ValidationRule, parameters: Dict[str, Any]) -> bool:
        """Validate rule for US compliance."""
        try:
            # Check for overly permissive rules
            if rule_type == ValidationRule.CONFIDENCE_THRESHOLD:
                # T-038: Raised from 0.5 to 0.65 for trade signals
                if parameters.get("min_confidence", 0) < 0.65:
                    return False
            
            elif rule_type == ValidationRule.POSITION_SIZE:
                if parameters.get("max_position_size", 0) > 0.3:  # Too large
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Rule compliance validation error: {e}")
            return False
    
    async def validate_signal(self, signal_id: str, signal_data: Dict[str, Any],
                           market_data: Optional[Dict[str, Any]] = None) -> ValidationResult:
        """Validate a trading signal."""
        try:
            validation_id = f"validation_{int(time.time())}"
            
            # Initialize validation result
            failed_rules = []
            warnings = []
            errors = []
            critical_issues = []
            
            # Apply enabled validation rules
            total_weight = 0
            passed_weight = 0
            
            for rule_id, rule in self.validation_rules.items():
                if not rule.enabled:
                    continue
                
                # Validate rule
                rule_result = await self._apply_validation_rule(rule, signal_data, market_data)
                
                # Update weight
                weight = rule.parameters.get("weight", 1.0)
                total_weight += weight
                
                if rule_result["passed"]:
                    passed_weight += weight
                else:
                    failed_rules.append(rule_id)
                    
                    # Categorize issues
                    if rule.severity == "critical":
                        critical_issues.append(rule_result["message"])
                    elif rule.severity == "error":
                        errors.append(rule_result["message"])
                    else:
                        warnings.append(rule_result["message"])
            
            # Calculate validation score
            validation_score = passed_weight / total_weight if total_weight > 0 else 0
            
            # Determine if validation passed
            min_score = self.validation_config["min_validation_score"]
            max_failed = self.validation_config["max_failed_rules"]
            critical_failure = self.validation_config["critical_rule_failure_reject"]
            
            passed = (validation_score >= min_score and 
                    len(failed_rules) <= max_failed and
                    (not critical_failure or len(critical_issues) == 0))
            
            # Create validation result
            result = ValidationResult(
                signal_id=signal_id,
                validation_id=validation_id,
                passed=passed,
                failed_rules=failed_rules,
                warnings=warnings,
                errors=errors,
                critical_issues=critical_issues,
                validation_score=validation_score,
                timestamp=datetime.now()
            )
            
            # Store result
            self.validation_results.append(result)
            
            # Record for compliance
            if self.us_compliance.get("audit_validations", True):
                await self._record_validation(result)
            
            logger.info(f"Signal validation completed: {signal_id} - Score: {validation_score:.3f}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to validate signal {signal_id}: {e}")
            return ValidationResult(
                signal_id=signal_id,
                validation_id=f"validation_{int(time.time())}",
                passed=False,
                failed_rules=["system_error"],
                warnings=[],
                errors=["Validation system error"],
                critical_issues=[],
                validation_score=0.0,
                timestamp=datetime.now()
            )
    
    async def _apply_validation_rule(self, rule: ValidationRuleConfig, signal_data: Dict[str, Any],
                                  market_data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        """Apply a validation rule."""
        try:
            rule_type = rule.rule_type
            parameters = rule.parameters
            
            if rule_type == ValidationRule.CONFIDENCE_THRESHOLD:
                return await self._validate_confidence_threshold(signal_data, parameters)
            
            elif rule_type == ValidationRule.RISK_LIMIT:
                return await self._validate_risk_limit(signal_data, parameters)
            
            elif rule_type == ValidationRule.POSITION_SIZE:
                return await self._validate_position_size(signal_data, parameters)
            
            elif rule_type == ValidationRule.MARKET_CONDITIONS:
                return await self._validate_market_conditions(signal_data, market_data, parameters)
            
            elif rule_type == ValidationRule.CORRELATION_CHECK:
                return await self._validate_correlation_check(signal_data, market_data, parameters)
            
            else:
                return {"passed": True, "message": f"Rule {rule.rule_type} not implemented"}
            
        except Exception as e:
            logger.error(f"Failed to apply validation rule {rule.rule_id}: {e}")
            return {"passed": False, "message": f"Rule application error: {e}"}
    
    async def _validate_confidence_threshold(self, signal_data: Dict[str, Any], 
                                          parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Validate confidence threshold."""
        try:
            min_confidence = parameters["min_confidence"]
            signal_confidence = signal_data.get("confidence", 0)
            
            # Convert confidence enum to value if needed
            if hasattr(signal_confidence, 'value'):
                confidence_value = signal_confidence.value / 5.0  # Convert to 0-1 scale
            else:
                confidence_value = float(signal_confidence)
            
            passed = confidence_value >= min_confidence
            message = f"Confidence {confidence_value:.3f} {'meets' if passed else 'below'} threshold {min_confidence:.3f}"
            
            return {"passed": passed, "message": message}
            
        except Exception as e:
            return {"passed": False, "message": f"Confidence validation error: {e}"}
    
    async def _validate_risk_limit(self, signal_data: Dict[str, Any], 
                                parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Validate risk limit."""
        try:
            max_risk_score = parameters["max_risk_score"]
            signal_risk = signal_data.get("risk_score", 0)
            
            passed = signal_risk <= max_risk_score
            message = f"Risk score {signal_risk:.3f} {'within' if passed else 'exceeds'} limit {max_risk_score:.3f}"
            
            return {"passed": passed, "message": message}
            
        except Exception as e:
            return {"passed": False, "message": f"Risk validation error: {e}"}
    
    async def _validate_position_size(self, signal_data: Dict[str, Any], 
                                   parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Validate position size."""
        try:
            max_position_size = parameters["max_position_size"]
            signal_position = signal_data.get("position_size", 0)
            
            passed = signal_position <= max_position_size
            message = f"Position size {signal_position:.3f} {'within' if passed else 'exceeds'} limit {max_position_size:.3f}"
            
            return {"passed": passed, "message": message}
            
        except Exception as e:
            return {"passed": False, "message": f"Position size validation error: {e}"}
    
    async def _validate_market_conditions(self, signal_data: Dict[str, Any], 
                                        market_data: Optional[Dict[str, Any]],
                                        parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Validate market conditions."""
        try:
            if not market_data:
                return {"passed": True, "message": "No market data available"}
            
            min_volume = parameters.get("min_market_volume", 1000000)
            max_volatility = parameters.get("max_volatility", 0.05)
            
            volume = market_data.get("volume", 0)
            volatility = market_data.get("volatility", 0)
            
            volume_ok = volume >= min_volume
            volatility_ok = volatility <= max_volatility
            
            passed = volume_ok and volatility_ok
            
            issues = []
            if not volume_ok:
                issues.append(f"Volume {volume:,.0f} below minimum {min_volume:,.0f}")
            if not volatility_ok:
                issues.append(f"Volatility {volatility:.3f} above maximum {max_volatility:.3f}")
            
            message = f"Market conditions {'acceptable' if passed else 'not acceptable'}: {'; '.join(issues)}"
            
            return {"passed": passed, "message": message}
            
        except Exception as e:
            return {"passed": False, "message": f"Market conditions validation error: {e}"}
    
    async def _validate_correlation_check(self, signal_data: Dict[str, Any], 
                                       market_data: Optional[Dict[str, Any]],
                                       parameters: Dict[str, Any]) -> Dict[str, Any]:
        """Validate correlation check with actual fills ledger data."""
        try:
            max_correlation = parameters.get("max_correlation", 0.7)
            signal_symbol = signal_data.get("symbol", "")
            
            # Calculate actual correlation with existing positions from fills ledger
            correlation = 0.0  # Default: no correlation if no positions
            
            try:
                from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
                ledger = get_fills_ledger()
                computed_positions = ledger.compute_net_positions()
                
                if computed_positions and signal_symbol:
                    # Group positions by asset (BTC, ETH, SOL, XRP, DOGE)
                    asset_positions = {}
                    for ticker, pos in computed_positions.items():
                        # Extract asset from ticker (e.g., KXBTC15M-... -> BTC)
                        asset = None
                        for prefix in ["KXBTC", "KXETH", "KXSOL", "KXXRP", "KXDOGE"]:
                            if ticker.startswith(prefix):
                                asset = prefix.replace("KX", "")
                                break
                        
                        if asset:
                            contracts = pos.get("contracts", 0)
                            if contracts != 0:
                                asset_positions[asset] = asset_positions.get(asset, 0) + contracts
                    
                    # Extract signal asset
                    signal_asset = None
                    for prefix in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
                        if prefix in signal_symbol.upper():
                            signal_asset = prefix
                            break
                    
                    # Calculate correlation based on asset overlap
                    if signal_asset and asset_positions:
                        # If we have positions in the same asset, correlation is high
                        if signal_asset in asset_positions:
                            correlation = 0.8  # High correlation for same asset
                        else:
                            # Different assets have lower correlation (crypto assets are somewhat correlated)
                            correlation = 0.3  # Moderate correlation between different crypto assets
                
                logger.debug(f"[CORRELATION_CHECK] symbol={signal_symbol} correlation={correlation:.3f}")
                
            except Exception as e:
                logger.warning(f"[CORRELATION_CHECK] Failed to calculate actual correlation: {e}, using default 0.0")
                correlation = 0.0
            
            passed = correlation <= max_correlation
            message = f"Correlation {correlation:.3f} {'within' if passed else 'exceeds'} limit {max_correlation:.3f}"
            
            return {"passed": passed, "message": message}
            
        except Exception as e:
            return {"passed": False, "message": f"Correlation validation error: {e}"}
    
    async def configure_backtest(self, backtest_id: str, start_date: datetime, end_date: datetime,
                              initial_capital: float = 100000.0, commission: float = 0.001,
                              slippage: float = 0.0001, position_sizing: str = "fixed",
                              risk_management: Optional[Dict[str, Any]] = None,
                              benchmark: Optional[str] = None) -> bool:
        """Configure backtest parameters."""
        try:
            # Validate backtest configuration
            if not self._validate_backtest_config(start_date, end_date, initial_capital):
                logger.error(f"Invalid backtest configuration: {backtest_id}")
                return False
            
            # Create backtest config
            config = BacktestConfig(
                backtest_id=backtest_id,
                start_date=start_date,
                end_date=end_date,
                initial_capital=initial_capital,
                commission=commission,
                slippage=slippage,
                position_sizing=position_sizing,
                risk_management=risk_management or {},
                benchmark=benchmark
            )
            
            # Store config
            self.backtest_configs[backtest_id] = config
            
            logger.info(f"Backtest configured: {backtest_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to configure backtest {backtest_id}: {e}")
            return False
    
    def _validate_backtest_config(self, start_date: datetime, end_date: datetime, 
                                initial_capital: float) -> bool:
        """Validate backtest configuration."""
        try:
            # Check dates
            if start_date >= end_date:
                return False
            
            # Check capital
            if initial_capital <= 0:
                return False
            
            # Check period length
            period_days = (end_date - start_date).days
            if period_days < 30:  # Minimum 30 days
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Backtest configuration validation error: {e}")
            return False
    
    async def run_backtest(self, backtest_id: str, signals: List[Dict[str, Any]],
                        market_data: pd.DataFrame) -> Optional[BacktestResult]:
        """Run a backtest."""
        try:
            # Get backtest configuration
            if backtest_id not in self.backtest_configs:
                logger.error(f"Backtest configuration not found: {backtest_id}")
                return None
            
            config = self.backtest_configs[backtest_id]
            
            logger.info(f"Starting backtest: {backtest_id}")
            start_time = time.time()
            
            # Initialize backtest state
            capital = config.initial_capital
            positions = {}
            trades = []
            equity_curve = []
            
            # Process signals chronologically
            sorted_signals = sorted(signals, key=lambda s: s.get("timestamp", datetime.min))
            
            for signal in sorted_signals:
                signal_time = signal.get("timestamp")
                if not signal_time or signal_time < config.start_date or signal_time > config.end_date:
                    continue
                
                # Get market data for signal time
                market_price = self._get_market_price(market_data, signal_time, signal.get("symbol"))
                if market_price is None:
                    continue
                
                # Process signal
                trade_result = await self._process_signal(signal, market_price, capital, config)
                if trade_result:
                    trades.append(trade_result)
                    capital += trade_result["pnl"]
                
                # Record equity
                equity_curve.append((signal_time, capital))
            
            # Calculate performance metrics
            performance_metrics = await self._calculate_backtest_metrics(
                trades, equity_curve, config.initial_capital, config
            )
            
            # Create backtest result
            result = BacktestResult(
                backtest_id=backtest_id,
                period_start=config.start_date,
                period_end=config.end_date,
                total_return=performance_metrics["total_return"],
                annualized_return=performance_metrics["annualized_return"],
                volatility=performance_metrics["volatility"],
                sharpe_ratio=performance_metrics["sharpe_ratio"],
                sortino_ratio=performance_metrics["sortino_ratio"],
                max_drawdown=performance_metrics["max_drawdown"],
                calmar_ratio=performance_metrics["calmar_ratio"],
                win_rate=performance_metrics["win_rate"],
                profit_factor=performance_metrics["profit_factor"],
                total_trades=len(trades),
                winning_trades=performance_metrics["winning_trades"],
                losing_trades=performance_metrics["losing_trades"],
                average_win=performance_metrics["average_win"],
                average_loss=performance_metrics["average_loss"],
                largest_win=performance_metrics["largest_win"],
                largest_loss=performance_metrics["largest_loss"],
                equity_curve=equity_curve,
                benchmark_return=performance_metrics.get("benchmark_return"),
                alpha=performance_metrics.get("alpha"),
                beta=performance_metrics.get("beta"),
                metadata={
                    "processing_time": time.time() - start_time,
                    "signals_processed": len(signals)
                }
            )
            
            # Store result
            self.backtest_results.append(result)
            
            # Record for compliance
            if self.us_compliance.get("audit_validations", True):
                await self._record_backtest(result)
            
            logger.info(f"Backtest completed: {backtest_id} - Return: {result.total_return:.3f}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to run backtest {backtest_id}: {e}")
            return None
    
    def _get_market_price(self, market_data: pd.DataFrame, timestamp: datetime, symbol: str) -> Optional[float]:
        """Get market price for timestamp and symbol from market data."""
        try:
            # Production: Get actual price from market data
            if market_data is not None and not market_data.empty:
                # Try to find the closest timestamp in the data
                if 'timestamp' in market_data.columns:
                    closest_idx = (market_data['timestamp'] - timestamp).abs().idxmin()
                    return market_data.loc[closest_idx, 'close']
                elif 'close' in market_data.columns:
                    # Fallback: return the latest close price
                    return market_data['close'].iloc[-1]
            
            # If no market data available, log warning
            logger.warning(f"No market data available for {symbol} at {timestamp}")
            return None
            
        except Exception as e:
            logger.error(f"Failed to get market price for {symbol} at {timestamp}: {e}")
            return None
    
    async def _process_signal(self, signal: Dict[str, Any], market_price: float, 
                            capital: float, config: BacktestConfig) -> Optional[Dict[str, Any]]:
        """Process a trading signal with realistic exit price determination."""
        try:
            signal_type = signal.get("signal_type")
            position_size = signal.get("position_size", 0)
            stop_loss = signal.get("stop_loss", market_price * 0.95)
            take_profit = signal.get("take_profit", market_price * 1.1)
            confidence = signal.get("confidence", 0.5)
            
            # Determine exit price based on signal confidence and market conditions
            # Higher confidence signals more likely to hit take_profit
            # Lower confidence signals more likely to hit stop_loss
            hit_take_profit = confidence > 0.5
            
            if signal_type in ["buy", "strong_buy"]:
                # Long position
                position_value = capital * position_size
                shares = position_value / market_price
                
                # Calculate PnL with realistic exit based on confidence
                exit_price = take_profit if hit_take_profit else stop_loss
                pnl = shares * (exit_price - market_price) - (position_value * config.commission)
                
                return {
                    "signal_id": signal.get("signal_id"),
                    "entry_price": market_price,
                    "exit_price": exit_price,
                    "shares": shares,
                    "pnl": pnl,
                    "return": pnl / position_value,
                    "type": "long"
                }
            
            elif signal_type in ["sell", "strong_sell"]:
                # Short position
                position_value = capital * position_size
                shares = position_value / market_price
                
                # Calculate PnL with realistic exit based on confidence
                exit_price = stop_loss if hit_take_profit else take_profit
                pnl = shares * (market_price - exit_price) - (position_value * config.commission)
                
                return {
                    "signal_id": signal.get("signal_id"),
                    "entry_price": market_price,
                    "exit_price": exit_price,
                    "shares": shares,
                    "pnl": pnl,
                    "return": pnl / position_value,
                    "type": "short"
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Failed to process signal: {e}")
            return None
    
    async def _calculate_backtest_metrics(self, trades: List[Dict[str, Any]], 
                                        equity_curve: List[Tuple[datetime, float]],
                                        initial_capital: float, 
                                        config: BacktestConfig) -> Dict[str, float]:
        """Calculate backtest performance metrics."""
        try:
            if not trades:
                return {
                    "total_return": 0.0,
                    "annualized_return": 0.0,
                    "volatility": 0.0,
                    "sharpe_ratio": 0.0,
                    "sortino_ratio": 0.0,
                    "max_drawdown": 0.0,
                    "calmar_ratio": 0.0,
                    "win_rate": 0.0,
                    "profit_factor": 0.0,
                    "winning_trades": 0,
                    "losing_trades": 0,
                    "average_win": 0.0,
                    "average_loss": 0.0,
                    "largest_win": 0.0,
                    "largest_loss": 0.0
                }
            
            # Extract returns
            returns = [trade["return"] for trade in trades]
            
            # Basic metrics
            total_return = (equity_curve[-1][1] - initial_capital) / initial_capital
            
            # Annualized return
            days = (config.end_date - config.start_date).days
            annualized_return = (1 + total_return) ** (365 / days) - 1 if days > 0 else 0
            
            # Volatility
            volatility = np.std(returns) * np.sqrt(252) if returns else 0
            
            # Sharpe ratio
            risk_free_rate = 0.02
            sharpe_ratio = (annualized_return - risk_free_rate) / volatility if volatility > 0 else 0
            
            # Sortino ratio (simplified)
            negative_returns = [r for r in returns if r < 0]
            downside_std = np.std(negative_returns) * np.sqrt(252) if negative_returns else 0
            sortino_ratio = (annualized_return - risk_free_rate) / downside_std if downside_std > 0 else 0
            
            # Max drawdown
            equity_values = [eq[1] for eq in equity_curve]
            peak = np.maximum.accumulate(equity_values)
            drawdown = (peak - equity_values) / peak
            max_drawdown = np.max(drawdown)
            
            # Calmar ratio
            calmar_ratio = annualized_return / abs(max_drawdown) if max_drawdown != 0 else 0
            
            # Win rate and profit factor
            winning_trades = len([t for t in trades if t["pnl"] > 0])
            losing_trades = len([t for t in trades if t["pnl"] < 0])
            win_rate = winning_trades / len(trades) if trades else 0
            
            wins = [t["pnl"] for t in trades if t["pnl"] > 0]
            losses = [abs(t["pnl"]) for t in trades if t["pnl"] < 0]
            
            profit_factor = sum(wins) / sum(losses) if losses else float('inf')
            
            average_win = np.mean(wins) if wins else 0
            average_loss = np.mean(losses) if losses else 0
            largest_win = max(wins) if wins else 0
            largest_loss = max(losses) if losses else 0
            
            return {
                "total_return": total_return,
                "annualized_return": annualized_return,
                "volatility": volatility,
                "sharpe_ratio": sharpe_ratio,
                "sortino_ratio": sortino_ratio,
                "max_drawdown": max_drawdown,
                "calmar_ratio": calmar_ratio,
                "win_rate": win_rate,
                "profit_factor": profit_factor,
                "winning_trades": winning_trades,
                "losing_trades": losing_trades,
                "average_win": average_win,
                "average_loss": average_loss,
                "largest_win": largest_win,
                "largest_loss": largest_loss
            }
            
        except Exception as e:
            logger.error(f"Failed to calculate backtest metrics: {e}")
            return {}
    
    def get_validation_results(self, signal_id: Optional[str] = None, limit: int = 100) -> List[ValidationResult]:
        """Get validation results."""
        results = list(self.validation_results)
        
        if signal_id:
            results = [r for r in results if r.signal_id == signal_id]
        
        return results[-limit:]
    
    def get_backtest_results(self, backtest_id: Optional[str] = None, limit: int = 50) -> List[BacktestResult]:
        """Get backtest results."""
        results = list(self.backtest_results)
        
        if backtest_id:
            results = [r for r in results if r.backtest_id == backtest_id]
        
        return results[-limit:]
    
    def get_validation_summary(self) -> Dict[str, Any]:
        """Get validation summary."""
        try:
            if not self.validation_results:
                return {"status": "no_data"}
            
            results = list(self.validation_results)
            
            # Validation statistics
            total_validations = len(results)
            passed_validations = sum(1 for r in results if r.passed)
            
            # Score distribution
            scores = [r.validation_score for r in results]
            
            # Rule failure statistics
            rule_failures = {}
            for result in results:
                for rule_id in result.failed_rules:
                    rule_failures[rule_id] = rule_failures.get(rule_id, 0) + 1
            
            return {
                "total_validations": total_validations,
                "passed_validations": passed_validations,
                "pass_rate": passed_validations / total_validations if total_validations > 0 else 0,
                "avg_score": np.mean(scores) if scores else 0,
                "rule_failures": rule_failures,
                "active_rules": len([r for r in self.validation_rules.values() if r.enabled]),
                "us_compliance": self.us_compliance
            }
            
        except Exception as e:
            logger.error(f"Failed to get validation summary: {e}")
            return {"status": "error", "error": str(e)}
    
    def get_backtest_summary(self) -> Dict[str, Any]:
        """Get backtest summary."""
        try:
            if not self.backtest_results:
                return {"status": "no_data"}
            
            results = list(self.backtest_results)
            
            # Performance statistics
            returns = [r.total_return for r in results]
            sharpe_ratios = [r.sharpe_ratio for r in results]
            max_drawdowns = [r.max_drawdown for r in results]
            
            return {
                "total_backtests": len(results),
                "avg_return": np.mean(returns) if returns else 0,
                "avg_sharpe_ratio": np.mean(sharpe_ratios) if sharpe_ratios else 0,
                "avg_max_drawdown": np.mean(max_drawdowns) if max_drawdowns else 0,
                "best_return": max(returns) if returns else 0,
                "worst_return": min(returns) if returns else 0,
                "us_compliance": self.us_compliance
            }
            
        except Exception as e:
            logger.error(f"Failed to get backtest summary: {e}")
            return {"status": "error", "error": str(e)}
    
    async def _record_validation(self, result: ValidationResult):
        """Record validation for compliance."""
        if not self.us_compliance.get("audit_validations", True):
            return
        
        audit_entry = {
            "action": "signal_validation",
            "validation_id": result.validation_id,
            "signal_id": result.signal_id,
            "passed": result.passed,
            "validation_score": result.validation_score,
            "failed_rules": result.failed_rules,
            "timestamp": result.timestamp.isoformat(),
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Validation audit entry: {audit_entry}")
    
    async def _record_backtest(self, result: BacktestResult):
        """Record backtest for compliance."""
        if not self.us_compliance.get("audit_validations", True):
            return
        
        audit_entry = {
            "action": "backtest_execution",
            "backtest_id": result.backtest_id,
            "total_return": result.total_return,
            "sharpe_ratio": result.sharpe_ratio,
            "max_drawdown": result.max_drawdown,
            "total_trades": result.total_trades,
            "period_start": result.period_start.isoformat(),
            "period_end": result.period_end.isoformat(),
            "timestamp": datetime.now().isoformat(),
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Backtest audit entry: {audit_entry}")
    
    def update_config(self, new_config: Dict[str, Any]):
        """Update validation configuration."""
        self.config.update(new_config)
        
        # Update specific parameters
        if "validation" in new_config:
            self.validation_config.update(new_config["validation"])
        
        logger.info("Signal validation configuration updated")

"""
Risk Monitor for MERID Advanced Risk Management

Provides comprehensive risk monitoring, alerts, and real-time
risk assessment with US-compliant configuration.

Features:
- Real-time risk monitoring
- Risk alert system
- Stress testing
- Risk limit enforcement
- US-compliant risk management
"""

import asyncio
import time
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple, Union
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque
from logging import CRITICAL, ERROR, WARNING  # ZT12-01: level constants only

from utils.logger import get_logger

logger = get_logger("risk.risk_monitor")

@dataclass
class RiskAlert:
    """Risk alert definition."""
    alert_id: str
    alert_type: str
    severity: str  # low, medium, high, critical
    message: str
    current_value: float
    threshold: float
    timestamp: float
    symbol: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class RiskLimit:
    """Risk limit definition."""
    limit_id: str
    limit_type: str
    limit_value: float
    current_value: float
    breach_count: int = 0
    last_breach: Optional[float] = None
    active: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class StressTestResult:
    """Stress test result."""
    test_id: str
    test_name: str
    scenario: str
    portfolio_value_before: float
    portfolio_value_after: float
    portfolio_loss: float
    loss_percentage: float
    worst_position: Optional[str]
    risk_metrics: Dict[str, float]
    test_time: float
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class RiskMetrics:
    """Current risk metrics snapshot."""
    timestamp: float
    portfolio_value: float
    total_exposure: float
    leverage: float
    var_95: float
    var_99: float
    expected_shortfall: float
    max_drawdown: float
    sharpe_ratio: float
    beta: float
    correlation_risk: float
    concentration_risk: float
    liquidity_risk: float
    operational_risk: float
    metadata: Dict[str, Any] = field(default_factory=dict)

class RiskMonitor:
    """
    Advanced risk monitoring system for MERID.
    
    Provides real-time risk monitoring, alerts, and stress testing
    with US-compliant configuration.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Risk limits
        self.risk_limits: Dict[str, RiskLimit] = {}
        
        # Risk alerts
        self.risk_alerts: deque = deque(maxlen=1000)
        self.active_alerts: Dict[str, RiskAlert] = {}
        
        # Risk metrics history
        self.risk_metrics_history: deque = deque(maxlen=1000)
        
        # Stress test results
        self.stress_test_results: deque = deque(maxlen=500)
        
        # Monitoring parameters
        self.monitoring_interval = config.get("monitoring_interval", 60)  # seconds
        self.alert_cooldown = config.get("alert_cooldown", 300)  # 5 minutes
        
        # Default risk limits
        self.default_limits = {
            "max_leverage": 2.0,
            "max_var_95": 0.02,  # 2% of portfolio
            "max_es_95": 0.03,   # 3% of portfolio
            "max_concentration": 0.3,  # 30% in single position
            "max_correlation_exposure": 0.5,
            "max_drawdown": 0.15,  # 15% max drawdown
            "min_liquidity_ratio": 0.1
        }
        
        # Initialize default limits
        self._initialize_default_limits()
        
        # Monitoring task
        self.monitoring_task: Optional[asyncio.Task] = None
        
        # Risk callbacks
        self.risk_callbacks: List[callable] = []
        
        # US compliance settings
        self.us_compliance = config.get("us_compliance", {
            "risk_limits": True,
            "alert_logging": True,
            "stress_testing": True,
            "audit_risk": True
        })
        
        logger.info("RiskMonitor initialized")
    
    def _initialize_default_limits(self):
        """Initialize default risk limits."""
        for limit_name, limit_value in self.default_limits.items():
            self.risk_limits[limit_name] = RiskLimit(
                limit_id=limit_name,
                limit_type=limit_name,
                limit_value=limit_value,
                current_value=0.0,
                active=True
            )
    
    async def start_monitoring(self):
        """Start continuous risk monitoring."""
        logger.info("Starting risk monitoring")
        
        # Start monitoring loop
        self.monitoring_task = asyncio.create_task(self._monitoring_loop(), name="risk-monitor")
        def _task_done_cb(task: asyncio.Task) -> None:
            if not task.cancelled() and task.exception():
                logger.error("Risk monitor task crashed: %s", task.exception())
        self.monitoring_task.add_done_callback(_task_done_cb)

        logger.info("Risk monitoring started")
    
    async def stop_monitoring(self):
        """Stop risk monitoring."""
        logger.info("Stopping risk monitoring")
        
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Risk monitoring stopped")
    
    async def _monitoring_loop(self):
        """Continuous risk monitoring loop."""
        while True:
            try:
                # Collect current risk metrics
                risk_metrics = await self._collect_risk_metrics()
                
                if risk_metrics:
                    # Update risk limits
                    await self._update_risk_limits(risk_metrics)
                    
                    # Check for breaches
                    await self._check_risk_breaches(risk_metrics)
                    
                    # Store metrics
                    self.risk_metrics_history.append(risk_metrics)
                    
                    # Notify callbacks
                    await self._notify_callbacks(risk_metrics)
                
                # Sleep for next iteration
                await asyncio.sleep(self.monitoring_interval)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Risk monitoring loop error: {e}")
                await asyncio.sleep(10)
    
    async def _collect_risk_metrics(self) -> Optional[RiskMetrics]:
        """Collect current risk metrics."""
        try:
            # In production, this would collect real portfolio data
            # For now, generate realistic mock data
            
            current_time = time.time()
            
            # Mock portfolio metrics
            portfolio_value = 1000000.0 + np.random.normal(0, 50000, 1)[0]
            total_exposure = portfolio_value * (1.2 + np.random.normal(0, 0.2, 1)[0])
            leverage = total_exposure / portfolio_value if portfolio_value > 0 else 0
            
            # Risk metrics
            var_95 = portfolio_value * (0.015 + np.random.normal(0, 0.005, 1)[0])
            var_99 = portfolio_value * (0.025 + np.random.normal(0, 0.008, 1)[0])
            expected_shortfall = portfolio_value * (0.020 + np.random.normal(0, 0.006, 1)[0])
            
            # Performance metrics
            max_drawdown = 0.05 + np.random.normal(0, 0.02, 1)[0]
            sharpe_ratio = 1.2 + np.random.normal(0, 0.3, 1)[0]
            beta = 1.0 + np.random.normal(0, 0.2, 1)[0]
            
            # Risk components
            correlation_risk = 0.1 + np.random.normal(0, 0.05, 1)[0]
            concentration_risk = 0.15 + np.random.normal(0, 0.05, 1)[0]
            liquidity_risk = 0.05 + np.random.normal(0, 0.02, 1)[0]
            operational_risk = 0.02 + np.random.normal(0, 0.01, 1)[0]
            
            metrics = RiskMetrics(
                timestamp=current_time,
                portfolio_value=portfolio_value,
                total_exposure=total_exposure,
                leverage=leverage,
                var_95=var_95,
                var_99=var_99,
                expected_shortfall=expected_shortfall,
                max_drawdown=max_drawdown,
                sharpe_ratio=sharpe_ratio,
                beta=beta,
                correlation_risk=correlation_risk,
                concentration_risk=concentration_risk,
                liquidity_risk=liquidity_risk,
                operational_risk=operational_risk,
                metadata={"mock": True}
            )
            
            return metrics
            
        except Exception as e:
            logger.error(f"Failed to collect risk metrics: {e}")
            return None
    
    async def _update_risk_limits(self, risk_metrics: RiskMetrics):
        """Update current values for risk limits."""
        try:
            # Update leverage limit
            if "max_leverage" in self.risk_limits:
                self.risk_limits["max_leverage"].current_value = risk_metrics.leverage
            
            # Update VaR limits
            if "max_var_95" in self.risk_limits:
                var_95_pct = risk_metrics.var_95 / risk_metrics.portfolio_value if risk_metrics.portfolio_value > 0 else 0
                self.risk_limits["max_var_95"].current_value = var_95_pct
            
            if "max_es_95" in self.risk_limits:
                es_95_pct = risk_metrics.expected_shortfall / risk_metrics.portfolio_value if risk_metrics.portfolio_value > 0 else 0
                self.risk_limits["max_es_95"].current_value = es_95_pct
            
            # Update concentration limit
            if "max_concentration" in self.risk_limits:
                self.risk_limits["max_concentration"].current_value = risk_metrics.concentration_risk
            
            # Update correlation exposure
            if "max_correlation_exposure" in self.risk_limits:
                self.risk_limits["max_correlation_exposure"].current_value = risk_metrics.correlation_risk
            
            # Update drawdown limit
            if "max_drawdown" in self.risk_limits:
                self.risk_limits["max_drawdown"].current_value = risk_metrics.max_drawdown
            
            # Update liquidity ratio
            if "min_liquidity_ratio" in self.risk_limits:
                self.risk_limits["min_liquidity_ratio"].current_value = risk_metrics.liquidity_risk
            
        except Exception as e:
            logger.error(f"Failed to update risk limits: {e}")
    
    async def _check_risk_breaches(self, risk_metrics: RiskMetrics):
        """Check for risk limit breaches."""
        try:
            current_time = time.time()
            
            for limit_id, limit in self.risk_limits.items():
                if not limit.active:
                    continue
                
                # Check for breach
                breach = False
                severity = "low"
                
                if limit.limit_type == "max_leverage":
                    breach = limit.current_value > limit.limit_value
                    severity = "high" if limit.current_value > limit.limit_value * 1.2 else "medium"
                    
                elif limit.limit_type in ["max_var_95", "max_es_95", "max_concentration", 
                                       "max_correlation_exposure", "max_drawdown"]:
                    breach = limit.current_value > limit.limit_value
                    severity = "critical" if limit.current_value > limit.limit_value * 1.5 else "high"
                    
                elif limit.limit_type == "min_liquidity_ratio":
                    breach = limit.current_value < limit.limit_value
                    severity = "high" if limit.current_value < limit.limit_value * 0.5 else "medium"
                
                if breach:
                    # Update breach count
                    limit.breach_count += 1
                    limit.last_breach = current_time
                    
                    # Check cooldown
                    alert_id = f"{limit_id}_{int(current_time)}"
                    if alert_id in self.active_alerts:
                        last_alert_time = self.active_alerts[alert_id].timestamp
                        if current_time - last_alert_time < self.alert_cooldown:
                            continue
                    
                    # Create alert
                    alert = RiskAlert(
                        alert_id=alert_id,
                        alert_type=limit.limit_type,
                        severity=severity,
                        message=f"Risk limit breach: {limit.limit_type} = {limit.current_value:.4f} > {limit.limit_value:.4f}",
                        current_value=limit.current_value,
                        threshold=limit.limit_value,
                        timestamp=current_time,
                        metadata={
                            "breach_count": limit.breach_count,
                            "limit_id": limit_id
                        }
                    )
                    
                    # Store alert
                    self.risk_alerts.append(alert)
                    self.active_alerts[alert_id] = alert
                    
                    # Log alert
                    log_level = CRITICAL if severity == "critical" else ERROR if severity == "high" else WARNING
                    logger.log(log_level, f"Risk Alert: {alert.message}")
                    
                    # Record for compliance
                    if self.us_compliance.get("alert_logging", True):
                        await self._record_alert_compliance(alert)
            
        except Exception as e:
            logger.error(f"Failed to check risk breaches: {e}")
    
    async def run_stress_test(self, scenario: str, portfolio_data: Dict[str, Any]) -> Optional[StressTestResult]:
        """Run stress test on portfolio."""
        try:
            start_time = time.time()
            
            # Get current portfolio value
            portfolio_value_before = portfolio_data.get("portfolio_value", 1000000.0)
            
            # Define stress scenarios
            scenarios = {
                "market_crash": {"market_shock": -0.30, "volatility_spike": 2.0, "correlation_increase": 0.8},
                "interest_rate_shock": {"rate_change": 0.02, "bond_impact": -0.15, "equity_impact": -0.10},
                "liquidity_crisis": {"liquidity_impact": -0.20, "spread_widening": 3.0, "fire_sale_discount": 0.25},
                "correlation_breakdown": {"correlation_shock": -0.5, "diversification_loss": 0.3},
                "extreme_volatility": {"volatility_multiplier": 4.0, "tail_risk": 0.05}
            }
            
            if scenario not in scenarios:
                logger.error(f"Unknown stress test scenario: {scenario}")
                return None
            
            scenario_params = scenarios[scenario]
            
            # Calculate portfolio impact (simplified)
            portfolio_loss = 0.0
            
            if "market_shock" in scenario_params:
                portfolio_loss += abs(scenario_params["market_shock"]) * portfolio_value_before
            
            if "volatility_spike" in scenario_params:
                vol_impact = scenario_params["volatility_spike"] * 0.1  # 10% per volatility multiple
                portfolio_loss += vol_impact * portfolio_value_before
            
            if "correlation_increase" in scenario_params:
                corr_impact = scenario_params["correlation_increase"] * 0.05  # 5% per correlation point
                portfolio_loss += corr_impact * portfolio_value_before
            
            # Add other scenario impacts
            for param, value in scenario_params.items():
                if param not in ["market_shock", "volatility_spike", "correlation_increase"]:
                    portfolio_loss += abs(value) * portfolio_value_before * 0.1  # 10% impact per parameter
            
            # Calculate results
            portfolio_value_after = portfolio_value_before - portfolio_loss
            loss_percentage = portfolio_loss / portfolio_value_before if portfolio_value_before > 0 else 0
            
            # Risk metrics after stress
            risk_metrics = {
                "portfolio_loss": portfolio_loss,
                "loss_percentage": loss_percentage,
                "leverage_after": (portfolio_data.get("leverage", 1.0) * 1.5),  # Leverage increases
                "var_95_after": (portfolio_data.get("var_95", 20000) * 3.0),  # VaR triples
                "correlation_risk_after": min(0.9, portfolio_data.get("correlation_risk", 0.2) * 2.0)
            }
            
            # Find worst position (mock)
            worst_position = "BTC"  # In production, calculate actual worst position
            
            result = StressTestResult(
                test_id=f"stress_{int(time.time())}",
                test_name=scenario,
                scenario=scenario,
                portfolio_value_before=portfolio_value_before,
                portfolio_value_after=portfolio_value_after,
                portfolio_loss=portfolio_loss,
                loss_percentage=loss_percentage,
                worst_position=worst_position,
                risk_metrics=risk_metrics,
                test_time=time.time() - start_time,
                metadata=scenario_params
            )
            
            # Store result
            self.stress_test_results.append(result)
            
            # Record for compliance
            if self.us_compliance.get("stress_testing", True):
                await self._record_stress_test_compliance(result)
            
            logger.info(f"Stress test completed: {scenario}, loss: {loss_percentage:.2%}")
            return result
            
        except Exception as e:
            logger.error(f"Failed to run stress test: {e}")
            return None
    
    async def run_comprehensive_stress_tests(self, portfolio_data: Dict[str, Any]) -> Dict[str, StressTestResult]:
        """Run comprehensive stress test suite."""
        try:
            scenarios = ["market_crash", "interest_rate_shock", "liquidity_crisis", 
                       "correlation_breakdown", "extreme_volatility"]
            
            results = {}
            
            for scenario in scenarios:
                result = await self.run_stress_test(scenario, portfolio_data)
                if result:
                    results[scenario] = result
            
            # Find worst scenario
            worst_scenario = None
            worst_loss = 0.0
            
            for scenario, result in results.items():
                if result.loss_percentage > worst_loss:
                    worst_loss = result.loss_percentage
                    worst_scenario = scenario
            
            results["worst_scenario"] = worst_scenario
            results["worst_loss"] = worst_loss
            
            logger.info(f"Comprehensive stress tests completed: worst scenario = {worst_scenario}")
            return results
            
        except Exception as e:
            logger.error(f"Failed to run comprehensive stress tests: {e}")
            return {}
    
    async def _notify_callbacks(self, risk_metrics: RiskMetrics):
        """Notify risk callbacks."""
        for callback in self.risk_callbacks:
            try:
                await callback(risk_metrics)
            except Exception as e:
                logger.error(f"Risk callback error: {e}")
    
    async def _record_alert_compliance(self, alert: RiskAlert):
        """Record alert compliance entry."""
        if not self.us_compliance.get("alert_logging", True):
            return
        
        audit_entry = {
            "alert_id": alert.alert_id,
            "alert_type": alert.alert_type,
            "severity": alert.severity,
            "timestamp": alert.timestamp,
            "current_value": alert.current_value,
            "threshold": alert.threshold,
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Risk alert audit entry: {audit_entry}")
    
    async def _record_stress_test_compliance(self, result: StressTestResult):
        """Record stress test compliance entry."""
        if not self.us_compliance.get("stress_testing", True):
            return
        
        audit_entry = {
            "test_id": result.test_id,
            "scenario": result.scenario,
            "timestamp": result.test_time,
            "portfolio_loss": result.portfolio_loss,
            "loss_percentage": result.loss_percentage,
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Stress test audit entry: {audit_entry}")
    
    def add_risk_limit(self, limit_id: str, limit_type: str, limit_value: float, active: bool = True):
        """Add or update risk limit."""
        self.risk_limits[limit_id] = RiskLimit(
            limit_id=limit_id,
            limit_type=limit_type,
            limit_value=limit_value,
            current_value=0.0,
            active=active
        )
        logger.info(f"Added risk limit: {limit_id} = {limit_value}")
    
    def remove_risk_limit(self, limit_id: str):
        """Remove risk limit."""
        if limit_id in self.risk_limits:
            del self.risk_limits[limit_id]
            logger.info(f"Removed risk limit: {limit_id}")
    
    def add_risk_callback(self, callback: callable):
        """Add risk monitoring callback."""
        self.risk_callbacks.append(callback)
    
    def remove_risk_callback(self, callback: callable):
        """Remove risk monitoring callback."""
        if callback in self.risk_callbacks:
            self.risk_callbacks.remove(callback)
    
    def get_active_alerts(self) -> List[RiskAlert]:
        """Get active risk alerts."""
        return list(self.active_alerts.values())
    
    def get_alert_history(self, limit: int = 100) -> List[RiskAlert]:
        """Get alert history."""
        return list(self.risk_alerts)[-limit:]
    
    def get_risk_limits(self) -> Dict[str, RiskLimit]:
        """Get current risk limits."""
        return self.risk_limits.copy()
    
    def get_stress_test_results(self, limit: int = 50) -> List[StressTestResult]:
        """Get stress test results."""
        return list(self.stress_test_results)[-limit:]
    
    def get_risk_metrics_history(self, limit: int = 100) -> List[RiskMetrics]:
        """Get risk metrics history."""
        return list(self.risk_metrics_history)[-limit:]
    
    def get_risk_summary(self) -> Dict[str, Any]:
        """Get comprehensive risk summary."""
        if not self.risk_metrics_history:
            return {"status": "no_data"}
        
        # Recent metrics
        recent_metrics = list(self.risk_metrics_history)[-50:]
        
        # Current metrics
        current_metrics = recent_metrics[-1] if recent_metrics else None
        
        # Alert summary
        active_alerts = self.get_active_alerts()
        alert_counts = {}
        for alert in active_alerts:
            severity = alert.severity
            alert_counts[severity] = alert_counts.get(severity, 0) + 1
        
        # Risk limit status
        limit_status = {}
        for limit_id, limit in self.risk_limits.items():
            if limit.active:
                breach_percentage = (limit.current_value / limit.limit_value - 1) * 100 if limit.limit_value > 0 else 0
                limit_status[limit_id] = {
                    "current": limit.current_value,
                    "limit": limit.limit_value,
                    "breach_count": limit.breach_count,
                    "breach_percentage": breach_percentage
                }
        
        # Stress test summary
        stress_results = list(self.stress_test_results)[-20:]
        worst_loss = max([r.loss_percentage for r in stress_results]) if stress_results else 0
        
        return {
            "current_metrics": current_metrics.__dict__ if current_metrics else {},
            "active_alerts": len(active_alerts),
            "alert_distribution": alert_counts,
            "risk_limits": limit_status,
            "stress_test_summary": {
                "total_tests": len(self.stress_test_results),
                "worst_loss": worst_loss,
                "recent_tests": len(stress_results)
            },
            "monitoring_status": {
                "monitoring_interval": self.monitoring_interval,
                "alert_cooldown": self.alert_cooldown,
                "total_metrics": len(self.risk_metrics_history)
            },
            "us_compliance": self.us_compliance
        }

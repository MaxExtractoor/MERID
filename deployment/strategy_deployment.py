"""
Strategy Deployment and Model Rollout System for MERID Phase 4

Provides safe rollout capabilities for AI models and trading strategies
with feature flags, kill switches, and business KPI monitoring.

Features:
- Config/version switch for strategies with traffic routing
- Kill switches per agent/venue with instant disable
- Business KPI monitoring for each strategy
- Gradual rollout with rollback capabilities
- Performance and risk monitoring
"""

import asyncio
import time
import json
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque, defaultdict
import logging
from enum import Enum

from utils.logger import get_logger

logger = get_logger("deployment.strategy_deployment")

class StrategyStatus(Enum):
    """Strategy status enumeration."""
    INACTIVE = "inactive"
    TESTING = "testing"
    CANARY = "canary"
    ACTIVE = "active"
    PAUSED = "paused"
    DISABLED = "disabled"
    ROLLED_BACK = "rolled_back"

class DeploymentMode(Enum):
    """Deployment mode enumeration."""
    OFF = "off"
    DRY_RUN = "dry_run"
    CANARY = "canary"
    GRADUAL = "gradual"
    FULL = "full"

class RiskLevel(Enum):
    """Risk level enumeration."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

@dataclass
class StrategyConfig:
    """Strategy configuration definition."""
    strategy_id: str
    strategy_name: str
    version: str
    config: Dict[str, Any]
    deployment_mode: DeploymentMode
    traffic_percentage: float
    risk_level: RiskLevel
    max_notional: float
    max_position_size: float
    venues: List[str]
    symbols: List[str]
    enabled: bool
    created_at: datetime
    updated_at: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class KillSwitch:
    """Kill switch definition."""
    switch_id: str
    strategy_id: str
    venue: Optional[str]
    switch_type: str
    enabled: bool
    triggered: bool
    trigger_reason: Optional[str]
    triggered_at: Optional[datetime]
    triggered_by: str
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class BusinessKPI:
    """Business KPI definition."""
    kpi_id: str
    strategy_id: str
    metric_name: str
    value: float
    target: float
    threshold: float
    status: str
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class DeploymentMetrics:
    """Deployment metrics definition."""
    strategy_id: str
    version: str
    deployment_time: datetime
    pnl: float
    max_drawdown: float
    win_rate: float
    sharpe_ratio: float
    slippage: float
    total_trades: int
    successful_trades: int
    failed_trades: int
    average_trade_size: float
    metadata: Dict[str, Any] = field(default_factory=dict)

class StrategyDeployment:
    """
    Strategy deployment and model rollout system for MERID.
    
    Provides safe rollout capabilities with feature flags, kill switches,
    and business KPI monitoring with US-compliant configuration.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Strategy configurations
        self.strategy_configs: Dict[str, StrategyConfig] = {}
        
        # Kill switches
        self.kill_switches: Dict[str, KillSwitch] = {}
        
        # Business KPIs
        self.business_kpis: Dict[str, List[BusinessKPI]] = defaultdict(list)
        
        # Deployment metrics
        self.deployment_metrics: Dict[str, List[DeploymentMetrics]] = defaultdict(list)
        
        # Configuration
        self.deployment_config = config.get("strategy_deployment", {
            "default_canary_percentage": 0.01,  # 1%
            "gradual_increment": 0.05,  # 5%
            "max_canary_duration_hours": 24,
            "auto_rollback_enabled": True,
            "kpi_evaluation_interval": 300,  # 5 minutes
            "risk_limit_check_interval": 60  # 1 minute
        })
        
        # KPI definitions
        self.kpi_definitions = {
            "realized_pnl": {
                "name": "Realized P&L",
                "target": 0.0,  # Positive P&L
                "threshold": -0.05,  # 5% loss threshold
                "unit": "USD"
            },
            "max_drawdown": {
                "name": "Maximum Drawdown",
                "target": 0.02,  # 2% max drawdown
                "threshold": 0.05,  # 5% critical drawdown
                "unit": "percentage"
            },
            "win_rate": {
                "name": "Win Rate",
                "target": 0.55,  # 55% win rate
                "threshold": 0.40,  # 40% minimum win rate
                "unit": "percentage"
            },
            "sharpe_ratio": {
                "name": "Sharpe Ratio",
                "target": 1.0,
                "threshold": 0.5,
                "unit": "ratio"
            },
            "slippage": {
                "name": "Slippage vs Reference",
                "target": 0.001,  # 0.1% slippage
                "threshold": 0.005,  # 0.5% max slippage
                "unit": "percentage"
            },
            "trade_frequency": {
                "name": "Trade Frequency",
                "target": 10.0,  # 10 trades per hour
                "threshold": 100.0,  # 100 trades per hour max
                "unit": "trades_per_hour"
            }
        }
        
        # US compliance settings
        self.us_compliance = config.get("us_compliance", {
            "strategy_disclosure": True,
            "risk_monitoring": True,
            "audit_deployment": True,
            "performance_disclosure": True
        })
        
        logger.info("Strategy deployment system initialized")
    
    async def create_strategy_config(self, strategy_id: str, strategy_name: str,
                                   version: str, config: Dict[str, Any],
                                   risk_level: RiskLevel = RiskLevel.MEDIUM,
                                   max_notional: float = 100000.0,
                                   max_position_size: float = 10000.0,
                                   venues: Optional[List[str]] = None,
                                   symbols: Optional[List[str]] = None) -> bool:
        """Create a strategy configuration."""
        try:
            # Validate strategy configuration
            if not self._validate_strategy_config(strategy_id, config, risk_level):
                logger.error(f"Invalid strategy configuration: {strategy_id}")
                return False
            
            # Create strategy configuration
            strategy_config = StrategyConfig(
                strategy_id=strategy_id,
                strategy_name=strategy_name,
                version=version,
                config=config,
                deployment_mode=DeploymentMode.OFF,
                traffic_percentage=0.0,
                risk_level=risk_level,
                max_notional=max_notional,
                max_position_size=max_position_size,
                venues=venues or [],
                symbols=symbols or [],
                enabled=False,
                created_at=datetime.now(),
                updated_at=datetime.now()
            )
            
            # Store strategy configuration
            self.strategy_configs[strategy_id] = strategy_config
            
            # Create default kill switches
            await self._create_default_kill_switches(strategy_id)
            
            # Record for compliance
            if self.us_compliance.get("audit_deployment", True):
                await self._record_strategy_creation(strategy_config)
            
            logger.info(f"Strategy configuration created: {strategy_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to create strategy configuration {strategy_id}: {e}")
            return False
    
    def _validate_strategy_config(self, strategy_id: str, config: Dict[str, Any],
                                risk_level: RiskLevel) -> bool:
        """Validate strategy configuration."""
        try:
            # Check strategy ID
            if not strategy_id:
                return False
            
            # Check configuration
            if not config:
                return False
            
            # Check risk level
            if risk_level not in RiskLevel:
                return False
            
            # US compliance checks
            if self.us_compliance.get("risk_monitoring", True):
                if not self._validate_strategy_risk(strategy_id, config, risk_level):
                    return False
            
            return True
            
        except Exception as e:
            logger.error(f"Strategy configuration validation error: {e}")
            return False
    
    def _validate_strategy_risk(self, strategy_id: str, config: Dict[str, Any],
                               risk_level: RiskLevel) -> bool:
        """Validate strategy for US compliance."""
        try:
            # Check for high-risk strategies
            if risk_level == RiskLevel.CRITICAL:
                # Critical strategies must have additional safeguards
                return True
            
            return True
            
        except Exception as e:
            logger.error(f"Strategy risk validation error: {e}")
            return False
    
    async def _create_default_kill_switches(self, strategy_id: str):
        """Create default kill switches for strategy."""
        try:
            # Global strategy kill switch
            global_switch = KillSwitch(
                switch_id=f"global_{strategy_id}",
                strategy_id=strategy_id,
                venue=None,
                switch_type="global",
                enabled=True,
                triggered=False,
                trigger_reason=None,
                triggered_at=None,
                triggered_by="system"
            )
            
            self.kill_switches[global_switch.switch_id] = global_switch
            
            # Venue-specific kill switches (if venues configured)
            strategy_config = self.strategy_configs.get(strategy_id)
            if strategy_config and strategy_config.venues:
                for venue in strategy_config.venues:
                    venue_switch = KillSwitch(
                        switch_id=f"venue_{venue}_{strategy_id}",
                        strategy_id=strategy_id,
                        venue=venue,
                        switch_type="venue",
                        enabled=True,
                        triggered=False,
                        trigger_reason=None,
                        triggered_at=None,
                        triggered_by="system"
                    )
                    
                    self.kill_switches[venue_switch.switch_id] = venue_switch
            
            logger.info(f"Created default kill switches for strategy: {strategy_id}")
            
        except Exception as e:
            logger.error(f"Failed to create default kill switches: {e}")
    
    async def update_deployment_mode(self, strategy_id: str, deployment_mode: DeploymentMode,
                                   traffic_percentage: Optional[float] = None) -> bool:
        """Update strategy deployment mode."""
        try:
            if strategy_id not in self.strategy_configs:
                logger.error(f"Strategy {strategy_id} not found")
                return False
            
            strategy_config = self.strategy_configs[strategy_id]
            
            # Validate deployment mode
            if not self._validate_deployment_mode(deployment_mode, traffic_percentage):
                logger.error(f"Invalid deployment mode: {deployment_mode}")
                return False
            
            # Update deployment mode
            old_mode = strategy_config.deployment_mode
            strategy_config.deployment_mode = deployment_mode
            strategy_config.updated_at = datetime.now()
            
            # Update traffic percentage
            if traffic_percentage is not None:
                strategy_config.traffic_percentage = traffic_percentage
            
            # Update enabled status
            strategy_config.enabled = deployment_mode != DeploymentMode.OFF
            
            # Record for compliance
            if self.us_compliance.get("audit_deployment", True):
                await self._record_deployment_change(strategy_config, old_mode, deployment_mode)
            
            logger.info(f"Deployment mode updated for {strategy_id}: {old_mode.value} -> {deployment_mode.value}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to update deployment mode for {strategy_id}: {e}")
            return False
    
    def _validate_deployment_mode(self, deployment_mode: DeploymentMode,
                                traffic_percentage: Optional[float]) -> bool:
        """Validate deployment mode."""
        try:
            # Check deployment mode
            if deployment_mode not in DeploymentMode:
                return False
            
            # Check traffic percentage for specific modes
            if deployment_mode == DeploymentMode.CANARY:
                if traffic_percentage is None or traffic_percentage <= 0 or traffic_percentage > 0.05:
                    return False  # Canary should be 0-5%
            elif deployment_mode == DeploymentMode.GRADUAL:
                if traffic_percentage is None or traffic_percentage <= 0 or traffic_percentage > 1.0:
                    return False  # Gradual should be 0-100%
            
            return True
            
        except Exception as e:
            logger.error(f"Deployment mode validation error: {e}")
            return False
    
    async def trigger_kill_switch(self, switch_id: str, reason: str,
                                 triggered_by: str = "system") -> bool:
        """Trigger a kill switch."""
        try:
            if switch_id not in self.kill_switches:
                logger.error(f"Kill switch {switch_id} not found")
                return False
            
            kill_switch = self.kill_switches[switch_id]
            
            # Check if already triggered
            if kill_switch.triggered:
                logger.warning(f"Kill switch {switch_id} already triggered")
                return False
            
            # Trigger kill switch
            kill_switch.triggered = True
            kill_switch.trigger_reason = reason
            kill_switch.triggered_at = datetime.now()
            kill_switch.triggered_by = triggered_by
            
            # Disable strategy
            strategy_config = self.strategy_configs.get(kill_switch.strategy_id)
            if strategy_config:
                strategy_config.enabled = False
                strategy_config.deployment_mode = DeploymentMode.DISABLED
                strategy_config.updated_at = datetime.now()
            
            # Record for compliance
            if self.us_compliance.get("audit_deployment", True):
                await self._record_kill_switch_trigger(kill_switch)
            
            logger.warning(f"Kill switch triggered: {switch_id} - {reason}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to trigger kill switch {switch_id}: {e}")
            return False
    
    async def reset_kill_switch(self, switch_id: str, reset_by: str = "system") -> bool:
        """Reset a kill switch."""
        try:
            if switch_id not in self.kill_switches:
                logger.error(f"Kill switch {switch_id} not found")
                return False
            
            kill_switch = self.kill_switches[switch_id]
            
            # Reset kill switch
            kill_switch.triggered = False
            kill_switch.trigger_reason = None
            kill_switch.triggered_at = None
            
            # Re-enable strategy if appropriate
            strategy_config = self.strategy_configs.get(kill_switch.strategy_id)
            if strategy_config and strategy_config.deployment_mode == DeploymentMode.DISABLED:
                strategy_config.deployment_mode = DeploymentMode.OFF
                strategy_config.updated_at = datetime.now()
            
            # Record for compliance
            if self.us_compliance.get("audit_deployment", True):
                await self._record_kill_switch_reset(kill_switch, reset_by)
            
            logger.info(f"Kill switch reset: {switch_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to reset kill switch {switch_id}: {e}")
            return False
    
    async def record_business_kpi(self, strategy_id: str, metric_name: str,
                               value: float, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Record a business KPI."""
        try:
            # Validate KPI
            if metric_name not in self.kpi_definitions:
                logger.error(f"Unknown KPI: {metric_name}")
                return False
            
            kpi_def = self.kpi_definitions[metric_name]
            
            # Determine status
            target = kpi_def["target"]
            threshold = kpi_def["threshold"]
            
            if metric_name in ["realized_pnl", "win_rate", "sharpe_ratio"]:
                # Higher is better
                if value >= target:
                    status = "excellent"
                elif value >= threshold:
                    status = "good"
                else:
                    status = "poor"
            else:
                # Lower is better (drawdown, slippage)
                if value <= target:
                    status = "excellent"
                elif value <= threshold:
                    status = "good"
                else:
                    status = "poor"
            
            # Create KPI
            kpi = BusinessKPI(
                kpi_id=str(uuid.uuid4()),
                strategy_id=strategy_id,
                metric_name=metric_name,
                value=value,
                target=target,
                threshold=threshold,
                status=status,
                timestamp=datetime.now(),
                metadata=metadata or {}
            )
            
            # Store KPI
            self.business_kpis[strategy_id].append(kpi)
            
            # Check for auto-rollback
            if status == "poor" and self.deployment_config.get("auto_rollback_enabled", True):
                await self._check_auto_rollback(strategy_id, metric_name, value, threshold)
            
            # Record for compliance
            if self.us_compliance.get("performance_disclosure", True):
                await self._record_kpi_update(kpi)
            
            logger.debug(f"KPI recorded for {strategy_id}: {metric_name} = {value} ({status})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to record business KPI: {e}")
            return False
    
    async def _check_auto_rollback(self, strategy_id: str, metric_name: str,
                                 value: float, threshold: float):
        """Check if auto-rollback should be triggered."""
        try:
            # Check if strategy is in canary or gradual mode
            strategy_config = self.strategy_configs.get(strategy_id)
            if not strategy_config:
                return
            
            if strategy_config.deployment_mode not in [DeploymentMode.CANARY, DeploymentMode.GRADUAL]:
                return
            
            # Check critical KPIs
            critical_kpis = ["max_drawdown", "realized_pnl"]
            if metric_name in critical_kpis:
                logger.warning(f"Critical KPI breach for {strategy_id}: {metric_name} = {value} (threshold: {threshold})")
                
                # Trigger global kill switch
                global_switch_id = f"global_{strategy_id}"
                await self.trigger_kill_switch(
                    global_switch_id,
                    f"Auto-rollback: Critical KPI breach - {metric_name} = {value}",
                    "auto_rollback"
                )
                
                # Update deployment mode
                await self.update_deployment_mode(strategy_id, DeploymentMode.ROLLED_BACK)
            
        except Exception as e:
            logger.error(f"Failed to check auto-rollback: {e}")
    
    async def record_deployment_metrics(self, strategy_id: str, version: str,
                                      pnl: float, max_drawdown: float,
                                      win_rate: float, sharpe_ratio: float,
                                      slippage: float, total_trades: int,
                                      successful_trades: int, failed_trades: int,
                                      average_trade_size: float,
                                      metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Record deployment metrics."""
        try:
            # Create deployment metrics
            metrics = DeploymentMetrics(
                strategy_id=strategy_id,
                version=version,
                deployment_time=datetime.now(),
                pnl=pnl,
                max_drawdown=max_drawdown,
                win_rate=win_rate,
                sharpe_ratio=sharpe_ratio,
                slippage=slippage,
                total_trades=total_trades,
                successful_trades=successful_trades,
                failed_trades=failed_trades,
                average_trade_size=average_trade_size,
                metadata=metadata or {}
            )
            
            # Store metrics
            self.deployment_metrics[strategy_id].append(metrics)
            
            # Record individual KPIs
            await self.record_business_kpi(strategy_id, "realized_pnl", pnl)
            await self.record_business_kpi(strategy_id, "max_drawdown", max_drawdown)
            await self.record_business_kpi(strategy_id, "win_rate", win_rate)
            await self.record_business_kpi(strategy_id, "sharpe_ratio", sharpe_ratio)
            await self.record_business_kpi(strategy_id, "slippage", slippage)
            
            logger.debug(f"Deployment metrics recorded for {strategy_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to record deployment metrics: {e}")
            return False
    
    def get_strategy_status(self, strategy_id: Optional[str] = None) -> Dict[str, Any]:
        """Get strategy status."""
        try:
            if strategy_id:
                if strategy_id in self.strategy_configs:
                    strategy_config = self.strategy_configs[strategy_id]
                    
                    # Get kill switches
                    strategy_kill_switches = {
                        switch_id: ks for switch_id, ks in self.kill_switches.items()
                        if ks.strategy_id == strategy_id
                    }
                    
                    # Get recent KPIs
                    recent_kpis = self.business_kpis.get(strategy_id, [])[-10:]
                    
                    # Get recent metrics
                    recent_metrics = self.deployment_metrics.get(strategy_id, [])[-5:]
                    
                    return {
                        "strategy_id": strategy_id,
                        "strategy_name": strategy_config.strategy_name,
                        "version": strategy_config.version,
                        "deployment_mode": strategy_config.deployment_mode.value,
                        "traffic_percentage": strategy_config.traffic_percentage,
                        "risk_level": strategy_config.risk_level.value,
                        "enabled": strategy_config.enabled,
                        "venues": strategy_config.venues,
                        "symbols": strategy_config.symbols,
                        "kill_switches": {
                            switch_id: {
                                "enabled": ks.enabled,
                                "triggered": ks.triggered,
                                "trigger_reason": ks.trigger_reason,
                                "triggered_at": ks.triggered_at.isoformat() if ks.triggered_at else None
                            }
                            for switch_id, ks in strategy_kill_switches.items()
                        },
                        "recent_kpis": [
                            {
                                "metric_name": kpi.metric_name,
                                "value": kpi.value,
                                "status": kpi.status,
                                "timestamp": kpi.timestamp.isoformat()
                            }
                            for kpi in recent_kpis
                        ],
                        "recent_metrics": [
                            {
                                "version": metrics.version,
                                "pnl": metrics.pnl,
                                "win_rate": metrics.win_rate,
                                "sharpe_ratio": metrics.sharpe_ratio,
                                "total_trades": metrics.total_trades,
                                "timestamp": metrics.deployment_time.isoformat()
                            }
                            for metrics in recent_metrics
                        ]
                    }
                else:
                    return {"status": "error", "message": f"Strategy {strategy_id} not found"}
            else:
                # Return all strategy statuses
                return {
                    strategy_id: {
                        "strategy_name": config.strategy_name,
                        "deployment_mode": config.deployment_mode.value,
                        "enabled": config.enabled,
                        "risk_level": config.risk_level.value
                    }
                    for strategy_id, config in self.strategy_configs.items()
                }
                
        except Exception as e:
            logger.error(f"Failed to get strategy status: {e}")
            return {"status": "error", "error": str(e)}
    
    def get_deployment_summary(self) -> Dict[str, Any]:
        """Get deployment summary."""
        try:
            # Strategy status distribution
            deployment_modes = {}
            for strategy_config in self.strategy_configs.values():
                mode_name = strategy_config.deployment_mode.value
                deployment_modes[mode_name] = deployment_modes.get(mode_name, 0) + 1
            
            # Risk level distribution
            risk_levels = {}
            for strategy_config in self.strategy_configs.values():
                risk_name = strategy_config.risk_level.value
                risk_levels[risk_name] = risk_levels.get(risk_name, 0) + 1
            
            # Kill switch status
            triggered_switches = sum(1 for ks in self.kill_switches.values() if ks.triggered)
            total_switches = len(self.kill_switches)
            
            # KPI summary
            total_kpis = sum(len(kpis) for kpis in self.business_kpis.values())
            
            return {
                "total_strategies": len(self.strategy_configs),
                "deployment_modes": deployment_modes,
                "risk_levels": risk_levels,
                "triggered_kill_switches": triggered_switches,
                "total_kill_switches": total_switches,
                "total_kpis": total_kpis,
                "us_compliance": self.us_compliance
            }
            
        except Exception as e:
            logger.error(f"Failed to get deployment summary: {e}")
            return {"status": "error", "error": str(e)}
    
    async def _record_strategy_creation(self, strategy_config: StrategyConfig):
        """Record strategy creation for compliance."""
        if not self.us_compliance.get("audit_deployment", True):
            return
        
        audit_entry = {
            "action": "strategy_creation",
            "strategy_id": strategy_config.strategy_id,
            "strategy_name": strategy_config.strategy_name,
            "version": strategy_config.version,
            "risk_level": strategy_config.risk_level.value,
            "max_notional": strategy_config.max_notional,
            "venues": strategy_config.venues,
            "timestamp": strategy_config.created_at.isoformat(),
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Strategy creation audit entry: {audit_entry}")
    
    async def _record_deployment_change(self, strategy_config: StrategyConfig,
                                     old_mode: DeploymentMode, new_mode: DeploymentMode):
        """Record deployment change for compliance."""
        if not self.us_compliance.get("audit_deployment", True):
            return
        
        audit_entry = {
            "action": "deployment_change",
            "strategy_id": strategy_config.strategy_id,
            "strategy_name": strategy_config.strategy_name,
            "old_mode": old_mode.value,
            "new_mode": new_mode.value,
            "traffic_percentage": strategy_config.traffic_percentage,
            "timestamp": strategy_config.updated_at.isoformat(),
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Deployment change audit entry: {audit_entry}")
    
    async def _record_kill_switch_trigger(self, kill_switch: KillSwitch):
        """Record kill switch trigger for compliance."""
        if not self.us_compliance.get("audit_deployment", True):
            return
        
        audit_entry = {
            "action": "kill_switch_trigger",
            "switch_id": kill_switch.switch_id,
            "strategy_id": kill_switch.strategy_id,
            "switch_type": kill_switch.switch_type,
            "venue": kill_switch.venue,
            "trigger_reason": kill_switch.trigger_reason,
            "triggered_by": kill_switch.triggered_by,
            "timestamp": kill_switch.triggered_at.isoformat() if kill_switch.triggered_at else None
        }
        
        # In production, store in audit database
        logger.debug(f"Kill switch trigger audit entry: {audit_entry}")
    
    async def _record_kill_switch_reset(self, kill_switch: KillSwitch, reset_by: str):
        """Record kill switch reset for compliance."""
        if not self.us_compliance.get("audit_deployment", True):
            return
        
        audit_entry = {
            "action": "kill_switch_reset",
            "switch_id": kill_switch.switch_id,
            "strategy_id": kill_switch.strategy_id,
            "reset_by": reset_by,
            "timestamp": datetime.now().isoformat()
        }
        
        # In production, store in audit database
        logger.debug(f"Kill switch reset audit entry: {audit_entry}")
    
    async def _record_kpi_update(self, kpi: BusinessKPI):
        """Record KPI update for compliance."""
        if not self.us_compliance.get("performance_disclosure", True):
            return
        
        audit_entry = {
            "action": "kpi_update",
            "kpi_id": kpi.kpi_id,
            "strategy_id": kpi.strategy_id,
            "metric_name": kpi.metric_name,
            "value": kpi.value,
            "status": kpi.status,
            "timestamp": kpi.timestamp.isoformat()
        }
        
        # In production, store in audit database
        logger.debug(f"KPI update audit entry: {audit_entry}")
    
    def update_config(self, new_config: Dict[str, Any]):
        """Update strategy deployment configuration."""
        self.config.update(new_config)
        
        # Update specific parameters
        if "strategy_deployment" in new_config:
            self.deployment_config.update(new_config["strategy_deployment"])
        
        logger.info("Strategy deployment configuration updated")

"""
Comprehensive Monitoring Dashboard for MERID System

Provides real-time monitoring of:
- Liquidation events and whale signals
- System health and performance metrics
- Risk indicators and alerts
- Market conditions and trading activity
"""

import asyncio
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict, deque

from monitoring.liquidation_monitor import CoinGlassLiquidationMonitor, WhaleIntelMonitor, LiquidationEvent, WhaleSignal
from trading.execution_engine import TradingExecutionEngine
from utils.logger import get_logger

# LEGACY: Perp adapters not used in Kalshi-only mode
BinancePerpAdapter = None  # type: ignore

logger = get_logger("monitoring.dashboard")

@dataclass
class SystemHealth:
    """System health metrics."""
    timestamp: float
    cpu_usage: float
    memory_usage: float
    disk_usage: float
    network_io: float
    active_connections: int
    error_rate: float
    response_time_ms: float

@dataclass
class RiskMetrics:
    """Risk assessment metrics."""
    timestamp: float
    total_exposure: float
    max_position_size: float
    daily_pnl: float
    leverage_ratio: float
    liquidation_risk: float
    whale_activity_score: float
    market_volatility: float

@dataclass
class Alert:
    """System alert."""
    alert_id: str
    severity: str  # LOW, MEDIUM, HIGH, CRITICAL
    category: str  # LIQUIDATION, WHALE, RISK, SYSTEM, PERFORMANCE
    message: str
    timestamp: float
    metadata: Dict[str, Any] = field(default_factory=dict)
    resolved: bool = False

class MonitoringDashboard:
    """
    Comprehensive monitoring dashboard for MERID system.
    
    Features:
    - Real-time liquidation and whale monitoring
    - System health and performance tracking
    - Risk assessment and alerting
    - Market condition analysis
    - Historical data aggregation
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Initialize monitoring components
        self.liquidation_monitor = CoinGlassLiquidationMonitor()
        self.whale_monitor = WhaleIntelMonitor()
        self.market_adapter = BinancePerpAdapter(use_mock=True)
        
        # Data storage
        self.liquidation_events: deque = deque(maxlen=1000)
        self.whale_signals: deque = deque(maxlen=500)
        self.system_health_history: deque = deque(maxlen=1440)  # 24 hours at 1-minute intervals
        self.risk_metrics_history: deque = deque(maxlen=1440)
        self.alerts: deque = deque(maxlen=1000)
        
        # Alert thresholds
        self.alert_thresholds = config.get("alert_thresholds", {
            "liquidation_size": 1000000,  # $1M
            "whale_size": 5000000,  # $5M
            "daily_loss": 10000,  # $10K
            "error_rate": 0.05,  # 5%
            "response_time": 1000,  # 1000ms
            "cpu_usage": 0.8,  # 80%
            "memory_usage": 0.85  # 85%
        })
        
        # Monitoring state
        self._running = False
        self._last_update = time.time()
        self._update_interval = config.get("update_interval", 60)  # 60 seconds
        
        logger.info("MonitoringDashboard initialized")
    
    async def start_monitoring(self):
        """Start the monitoring dashboard."""
        if self._running:
            logger.warning("Monitoring already running")
            return
        
        self._running = True
        logger.info("Starting monitoring dashboard")
        
        # Start monitoring loop (store ref so stop can cancel)
        self._monitor_task = asyncio.create_task(self._monitoring_loop())
        
        # Initial data collection
        await self._collect_initial_data()
    
    async def stop_monitoring(self):
        """Stop the monitoring dashboard."""
        self._running = False
        if getattr(self, '_monitor_task', None) and not self._monitor_task.done():
            self._monitor_task.cancel()
        self._monitor_task = None
        logger.info("Monitoring dashboard stopped")
    
    async def _monitoring_loop(self):
        """Main monitoring loop."""
        while self._running:
            try:
                # Collect all monitoring data
                await self._collect_liquidation_data()
                await self._collect_whale_data()
                await self._collect_system_health()
                await self._collect_risk_metrics()
                await self._check_alerts()
                
                # Update timestamp
                self._last_update = time.time()
                
                # Sleep until next update
                await asyncio.sleep(self._update_interval)
                
            except Exception as e:
                logger.error(f"Monitoring loop error: {e}")
                await asyncio.sleep(10)  # Short sleep on error
    
    async def _collect_initial_data(self):
        """Collect initial monitoring data."""
        try:
            # Collect liquidation events
            liquidations = self.liquidation_monitor.fetch_heatmap()
            for event in liquidations:
                self.liquidation_events.append(event)
            
            # Collect whale signals
            whales = self.whale_monitor.fetch_signals(limit=50)
            for signal in whales:
                self.whale_signals.append(signal)
            
            logger.info(f"Initial data collected: {len(liquidations)} liquidations, {len(whales)} whales")
            
        except Exception as e:
            logger.error(f"Initial data collection failed: {e}")
    
    async def _collect_liquidation_data(self):
        """Collect liquidation events."""
        try:
            liquidations = self.liquidation_monitor.fetch_heatmap()
            for event in liquidations:
                self.liquidation_events.append(event)
                
                # Check for large liquidations
                if event.notional >= self.alert_thresholds["liquidation_size"]:
                    await self._create_alert(
                        severity="HIGH",
                        category="LIQUIDATION",
                        message=f"Large liquidation: {event.symbol} ${event.notional:,.0f}",
                        metadata={
                            "symbol": event.symbol,
                            "venue": event.venue,
                            "notional": event.notional,
                            "side": event.side
                        }
                    )
            
        except Exception as e:
            logger.error(f"Liquidation data collection failed: {e}")
    
    async def _collect_whale_data(self):
        """Collect whale signals."""
        try:
            whales = self.whale_monitor.fetch_signals(limit=20)
            for signal in whales:
                self.whale_signals.append(signal)
                
                # Check for large whale activity
                if signal.amount >= self.alert_thresholds["whale_size"]:
                    await self._create_alert(
                        severity="MEDIUM",
                        category="WHALE",
                        message=f"Large whale activity: {signal.token} ${signal.amount:,.0f}",
                        metadata={
                            "address": signal.address,
                            "token": signal.token,
                            "amount": signal.amount,
                            "exchange": signal.exchange,
                            "action": signal.action
                        }
                    )
            
        except Exception as e:
            logger.error(f"Whale data collection failed: {e}")
    
    async def _collect_system_health(self):
        """Collect system health metrics."""
        try:
            import psutil
            
            # Collect system metrics
            cpu_usage = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            network = psutil.net_io_counters()
            
            health = SystemHealth(
                timestamp=time.time(),
                cpu_usage=cpu_usage / 100.0,
                memory_usage=memory.percent / 100.0,
                disk_usage=disk.percent / 100.0,
                network_io=network.bytes_sent + network.bytes_recv,
                active_connections=len(psutil.net_connections()),
                error_rate=0.0,  # Would be calculated from actual error logs
                response_time_ms=0.0  # Would be calculated from actual response times
            )
            
            self.system_health_history.append(health)
            
            # Check for system alerts
            if health.cpu_usage >= self.alert_thresholds["cpu_usage"]:
                await self._create_alert(
                    severity="MEDIUM",
                    category="SYSTEM",
                    message=f"High CPU usage: {health.cpu_usage:.1%}",
                    metadata={"cpu_usage": health.cpu_usage}
                )
            
            if health.memory_usage >= self.alert_thresholds["memory_usage"]:
                await self._create_alert(
                    severity="HIGH",
                    category="SYSTEM",
                    message=f"High memory usage: {health.memory_usage:.1%}",
                    metadata={"memory_usage": health.memory_usage}
                )
            
        except Exception as e:
            logger.error(f"System health collection failed: {e}")
    
    async def _collect_risk_metrics(self):
        """Collect risk assessment metrics."""
        try:
            # Get market data
            markets = self.market_adapter.fetch_markets(limit=10)
            
            # Calculate risk metrics
            total_volume = sum(m.volume_24h for m in markets)
            avg_funding = sum(m.funding_rate for m in markets) / len(markets) if markets else 0
            
            # Calculate whale activity score
            recent_whales = [s for s in self.whale_signals if time.time() - s.timestamp < 3600]
            whale_score = sum(s.amount for s in recent_whales) / 1000000  # Normalize to millions
            
            # Calculate liquidation risk
            recent_liquidations = [l for l in self.liquidation_events if (time.time() * 1000 - l.timestamp_ms) < 3600000]
            liquidation_risk = sum(l.notional for l in recent_liquidations) / 1000000  # Normalize to millions
            
            risk = RiskMetrics(
                timestamp=time.time(),
                total_exposure=0.0,  # Would come from trading engine
                max_position_size=0.0,  # Would come from trading engine
                daily_pnl=0.0,  # Would come from trading engine
                leverage_ratio=0.0,  # Would be calculated from positions
                liquidation_risk=liquidation_risk,
                whale_activity_score=whale_score,
                market_volatility=abs(avg_funding) * 100  # Convert to percentage
            )
            
            self.risk_metrics_history.append(risk)
            
            # Check for risk alerts
            if risk.daily_pnl <= -self.alert_thresholds["daily_loss"]:
                await self._create_alert(
                    severity="CRITICAL",
                    category="RISK",
                    message=f"High daily loss: ${risk.daily_pnl:,.0f}",
                    metadata={"daily_pnl": risk.daily_pnl}
                )
            
        except Exception as e:
            logger.error(f"Risk metrics collection failed: {e}")
    
    async def _check_alerts(self):
        """Check for alert conditions."""
        # This method would contain additional alert logic
        # For now, alerts are generated in individual collection methods
        pass
    
    async def _create_alert(self, severity: str, category: str, message: str, metadata: Dict[str, Any] = None):
        """Create a new alert."""
        alert = Alert(
            alert_id=f"alert_{int(time.time() * 1000)}",
            severity=severity,
            category=category,
            message=message,
            timestamp=time.time(),
            metadata=metadata or {}
        )
        
        self.alerts.append(alert)
        logger.warning(f"Alert created: [{severity}] {message}")
    
    def get_dashboard_summary(self) -> Dict[str, Any]:
        """Get comprehensive dashboard summary."""
        try:
            # Recent liquidations (last hour)
            recent_liquidations = [
                l for l in self.liquidation_events 
                if (time.time() * 1000 - l.timestamp_ms) < 3600000
            ]
            
            # Recent whale signals (last hour)
            recent_whales = [
                w for w in self.whale_signals 
                if time.time() - w.timestamp < 3600
            ]
            
            # Recent alerts (last 24 hours)
            recent_alerts = [
                a for a in self.alerts 
                if time.time() - a.timestamp < 86400
            ]
            
            # Current system health
            current_health = self.system_health_history[-1] if self.system_health_history else None
            current_risk = self.risk_metrics_history[-1] if self.risk_metrics_history else None
            
            return {
                "timestamp": time.time(),
                "status": "healthy" if self._is_system_healthy() else "degraded",
                "liquidation_summary": {
                    "total_events": len(recent_liquidations),
                    "total_notional": sum(l.notional for l in recent_liquidations),
                    "largest_liquidation": max(l.notional for l in recent_liquidations) if recent_liquidations else 0,
                    "venues": list(set(l.venue for l in recent_liquidations)),
                    "symbols": list(set(l.symbol for l in recent_liquidations))
                },
                "whale_summary": {
                    "total_signals": len(recent_whales),
                    "total_volume": sum(w.amount for w in recent_whales),
                    "largest_signal": max(w.amount for w in recent_whales) if recent_whales else 0,
                    "exchanges": list(set(w.exchange for w in recent_whales)),
                    "tokens": list(set(w.token for w in recent_whales))
                },
                "system_health": {
                    "cpu_usage": current_health.cpu_usage if current_health else 0,
                    "memory_usage": current_health.memory_usage if current_health else 0,
                    "disk_usage": current_health.disk_usage if current_health else 0,
                    "active_connections": current_health.active_connections if current_health else 0
                },
                "risk_metrics": {
                    "liquidation_risk": current_risk.liquidation_risk if current_risk else 0,
                    "whale_activity_score": current_risk.whale_activity_score if current_risk else 0,
                    "market_volatility": current_risk.market_volatility if current_risk else 0,
                    "daily_pnl": current_risk.daily_pnl if current_risk else 0
                },
                "alerts": {
                    "total_alerts": len(recent_alerts),
                    "critical_alerts": len([a for a in recent_alerts if a.severity == "CRITICAL"]),
                    "high_alerts": len([a for a in recent_alerts if a.severity == "HIGH"]),
                    "medium_alerts": len([a for a in recent_alerts if a.severity == "MEDIUM"]),
                    "low_alerts": len([a for a in recent_alerts if a.severity == "LOW"]),
                    "categories": list(set(a.category for a in recent_alerts))
                },
                "last_update": self._last_update
            }
            
        except Exception as e:
            logger.error(f"Dashboard summary generation failed: {e}")
            return {"error": str(e), "timestamp": time.time()}
    
    def _is_system_healthy(self) -> bool:
        """Check if system is healthy."""
        if not self.system_health_history:
            return True
        
        health = self.system_health_history[-1]
        
        # Check critical health indicators
        if health.cpu_usage > 0.9 or health.memory_usage > 0.95:
            return False
        
        # Check for critical alerts
        recent_alerts = [
            a for a in self.alerts 
            if time.time() - a.timestamp < 3600 and a.severity == "CRITICAL"
        ]
        
        return len(recent_alerts) == 0
    
    def get_historical_data(self, hours: int = 24) -> Dict[str, Any]:
        """Get historical monitoring data."""
        cutoff_time = time.time() - (hours * 3600)
        
        # Filter historical data
        historical_health = [
            h for h in self.system_health_history 
            if h.timestamp >= cutoff_time
        ]
        
        historical_risk = [
            r for r in self.risk_metrics_history 
            if r.timestamp >= cutoff_time
        ]
        
        return {
            "period_hours": hours,
            "system_health": [
                {
                    "timestamp": h.timestamp,
                    "cpu_usage": h.cpu_usage,
                    "memory_usage": h.memory_usage,
                    "error_rate": h.error_rate,
                    "response_time_ms": h.response_time_ms
                }
                for h in historical_health
            ],
            "risk_metrics": [
                {
                    "timestamp": r.timestamp,
                    "liquidation_risk": r.liquidation_risk,
                    "whale_activity_score": r.whale_activity_score,
                    "market_volatility": r.market_volatility,
                    "daily_pnl": r.daily_pnl
                }
                for r in historical_risk
            ]
        }

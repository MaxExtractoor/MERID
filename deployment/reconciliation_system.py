"""
Reconciliation and Accounting System for MERID Phase 4

Provides comprehensive reconciliation between MERID and venue systems
with automatic alerts and kill switch integration.

Features:
- Position and balance reconciliation
- Trade execution reconciliation
- Real-time mismatch detection
- Auto-kill switch integration
- US-compliant accounting and audit trails
"""

import asyncio
import time
import uuid
import json
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import deque, defaultdict
from enum import Enum

from utils.logger import get_logger

logger = get_logger("deployment.reconciliation_system")

class ReconciliationStatus(Enum):
    """Reconciliation status enumeration."""
    MATCHED = "matched"
    MISMATCH = "mismatch"
    PENDING = "pending"
    ERROR = "error"
    KILL_SWITCH_TRIGGERED = "kill_switch_triggered"

class ReconciliationType(Enum):
    """Reconciliation type enumeration."""
    POSITION = "position"
    BALANCE = "balance"
    TRADE = "trade"
    CASH = "cash"
    PNL = "pnl"

class MismatchSeverity(Enum):
    """Mismatch severity enumeration."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

@dataclass
class ReconciliationResult:
    """Reconciliation result definition."""
    reconciliation_id: str
    reconciliation_type: ReconciliationType
    venue: str
    symbol: Optional[str]
    merid_value: float
    venue_value: float
    difference: float
    tolerance: float
    status: ReconciliationStatus
    severity: MismatchSeverity
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class ReconciliationAlert:
    """Reconciliation alert definition."""
    alert_id: str
    reconciliation_id: str
    alert_type: str
    severity: MismatchSeverity
    message: str
    venue: str
    symbol: Optional[str]
    difference: float
    tolerance: float
    triggered_at: datetime
    resolved_at: Optional[datetime]
    kill_switch_triggered: bool
    metadata: Dict[str, Any] = field(default_factory=dict)

@dataclass
class AccountingEntry:
    """Accounting entry definition."""
    entry_id: str
    entry_type: str
    venue: str
    symbol: Optional[str]
    amount: float
    currency: str
    timestamp: datetime
    reference_id: Optional[str]
    description: str
    metadata: Dict[str, Any] = field(default_factory=dict)

class ReconciliationSystem:
    """
    Comprehensive reconciliation and accounting system for MERID.
    
    Provides position and balance reconciliation with automatic alerts
    and kill switch integration with US-compliant configuration.
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        
        # Reconciliation results
        self.reconciliation_results: Dict[str, List[ReconciliationResult]] = defaultdict(list)
        
        # Reconciliation alerts
        self.reconciliation_alerts: Dict[str, ReconciliationAlert] = {}
        
        # Accounting entries
        self.accounting_entries: Dict[str, List[AccountingEntry]] = defaultdict(list)
        
        # Configuration
        self.reconciliation_config = config.get("reconciliation_system", {
            "position_tolerance": 0.001,  # 0.1%
            "balance_tolerance": 0.01,    # $0.01 USD
            "trade_tolerance": 0.001,     # 0.1%
            "reconciliation_interval": 60,  # 1 minute
            "auto_kill_switch_enabled": True,
            "max_mismatches_before_kill": 3,
            "critical_mismatch_threshold": 1000.0  # $1000
        })
        
        # Tolerance configurations
        self.tolerance_configs = {
            ReconciliationType.POSITION: {
                "absolute": 0.001,  # 0.001 units
                "percentage": 0.001,  # 0.1%
                "severity_thresholds": {
                    MismatchSeverity.LOW: 0.01,
                    MismatchSeverity.MEDIUM: 0.1,
                    MismatchSeverity.HIGH: 1.0,
                    MismatchSeverity.CRITICAL: 10.0
                }
            },
            ReconciliationType.BALANCE: {
                "absolute": 0.01,    # $0.01 USD
                "percentage": 0.0001,  # 0.01%
                "severity_thresholds": {
                    MismatchSeverity.LOW: 1.0,
                    MismatchSeverity.MEDIUM: 10.0,
                    MismatchSeverity.HIGH: 100.0,
                    MismatchSeverity.CRITICAL: 1000.0
                }
            },
            ReconciliationType.TRADE: {
                "absolute": 0.001,   # 0.001 units
                "percentage": 0.001,   # 0.1%
                "severity_thresholds": {
                    MismatchSeverity.LOW: 0.01,
                    MismatchSeverity.MEDIUM: 0.1,
                    MismatchSeverity.HIGH: 1.0,
                    MismatchSeverity.CRITICAL: 10.0
                }
            },
            ReconciliationType.CASH: {
                "absolute": 0.01,     # $0.01 USD
                "percentage": 0.0001,  # 0.01%
                "severity_thresholds": {
                    MismatchSeverity.LOW: 1.0,
                    MismatchSeverity.MEDIUM: 10.0,
                    MismatchSeverity.HIGH: 100.0,
                    MismatchSeverity.CRITICAL: 1000.0
                }
            },
            ReconciliationType.PNL: {
                "absolute": 0.01,     # $0.01 USD
                "percentage": 0.001,   # 0.1%
                "severity_thresholds": {
                    MismatchSeverity.LOW: 1.0,
                    MismatchSeverity.MEDIUM: 10.0,
                    MismatchSeverity.HIGH: 100.0,
                    MismatchSeverity.CRITICAL: 1000.0
                }
            }
        }
        
        # US compliance settings
        self.us_compliance = config.get("us_compliance", {
            "audit_reconciliation": True,
            "accounting_standards": True,
            "regulatory_reporting": True,
            "data_retention": True
        })
        
        # Kill switch integration (would be injected)
        self.kill_switch_manager = None
        
        logger.info("Reconciliation system initialized")
    
    def set_kill_switch_manager(self, kill_switch_manager):
        """Set kill switch manager for integration."""
        self.kill_switch_manager = kill_switch_manager
    
    async def reconcile_positions(self, venue: str, merid_positions: Dict[str, float],
                               venue_positions: Dict[str, float]) -> List[ReconciliationResult]:
        """Reconcile positions between MERID and venue."""
        try:
            results = []
            
            # Get all symbols from both systems
            all_symbols = set(merid_positions.keys()) | set(venue_positions.keys())
            
            for symbol in all_symbols:
                merid_pos = merid_positions.get(symbol, 0.0)
                venue_pos = venue_positions.get(symbol, 0.0)
                
                # Calculate difference
                difference = abs(merid_pos - venue_pos)
                
                # Get tolerance
                tolerance_config = self.tolerance_configs[ReconciliationType.POSITION]
                tolerance = max(
                    tolerance_config["absolute"],
                    abs(merid_pos) * tolerance_config["percentage"]
                )
                
                # Determine status
                if difference <= tolerance:
                    status = ReconciliationStatus.MATCHED
                    severity = MismatchSeverity.LOW
                else:
                    status = ReconciliationStatus.MISMATCH
                    severity = self._determine_severity(
                        ReconciliationType.POSITION,
                        difference,
                        tolerance_config
                    )
                
                # Create reconciliation result
                result = ReconciliationResult(
                    reconciliation_id=str(uuid.uuid4()),
                    reconciliation_type=ReconciliationType.POSITION,
                    venue=venue,
                    symbol=symbol,
                    merid_value=merid_pos,
                    venue_value=venue_pos,
                    difference=difference,
                    tolerance=tolerance,
                    status=status,
                    severity=severity,
                    timestamp=datetime.now(),
                    metadata={}
                )
                
                results.append(result)
                self.reconciliation_results[venue].append(result)
                
                # Handle mismatch
                if status == ReconciliationStatus.MISMATCH:
                    await self._handle_reconciliation_mismatch(result)
                
                # Record accounting entry
                await self._record_accounting_entry(result)
            
            logger.info(f"Position reconciliation completed for {venue}: {len(results)} symbols")
            return results
            
        except Exception as e:
            logger.error(f"Failed to reconcile positions for {venue}: {e}")
            return []
    
    async def reconcile_balances(self, venue: str, merid_balances: Dict[str, float],
                               venue_balances: Dict[str, float]) -> List[ReconciliationResult]:
        """Reconcile balances between MERID and venue."""
        try:
            results = []
            
            # Get all currencies from both systems
            all_currencies = set(merid_balances.keys()) | set(venue_balances.keys())
            
            for currency in all_currencies:
                merid_bal = merid_balances.get(currency, 0.0)
                venue_bal = venue_balances.get(currency, 0.0)
                
                # Calculate difference
                difference = abs(merid_bal - venue_bal)
                
                # Get tolerance
                tolerance_config = self.tolerance_configs[ReconciliationType.BALANCE]
                tolerance = max(
                    tolerance_config["absolute"],
                    abs(merid_bal) * tolerance_config["percentage"]
                )
                
                # Determine status
                if difference <= tolerance:
                    status = ReconciliationStatus.MATCHED
                    severity = MismatchSeverity.LOW
                else:
                    status = ReconciliationStatus.MISMATCH
                    severity = self._determine_severity(
                        ReconciliationType.BALANCE,
                        difference,
                        tolerance_config
                    )
                
                # Create reconciliation result
                result = ReconciliationResult(
                    reconciliation_id=str(uuid.uuid4()),
                    reconciliation_type=ReconciliationType.BALANCE,
                    venue=venue,
                    symbol=currency,
                    merid_value=merid_bal,
                    venue_value=venue_bal,
                    difference=difference,
                    tolerance=tolerance,
                    status=status,
                    severity=severity,
                    timestamp=datetime.now(),
                    metadata={}
                )
                
                results.append(result)
                self.reconciliation_results[venue].append(result)
                
                # Handle mismatch
                if status == ReconciliationStatus.MISMATCH:
                    await self._handle_reconciliation_mismatch(result)
                
                # Record accounting entry
                await self._record_accounting_entry(result)
            
            logger.info(f"Balance reconciliation completed for {venue}: {len(results)} currencies")
            return results
            
        except Exception as e:
            logger.error(f"Failed to reconcile balances for {venue}: {e}")
            return []
    
    async def reconcile_trades(self, venue: str, merid_trades: List[Dict[str, Any]],
                             venue_trades: List[Dict[str, Any]]) -> List[ReconciliationResult]:
        """Reconcile trades between MERID and venue."""
        try:
            results = []
            
            # Create trade maps by trade ID
            merid_trade_map = {trade.get("trade_id"): trade for trade in merid_trades}
            venue_trade_map = {trade.get("trade_id"): trade for trade in venue_trades}
            
            # Get all trade IDs
            all_trade_ids = set(merid_trade_map.keys()) | set(venue_trade_map.keys())
            
            for trade_id in all_trade_ids:
                merid_trade = merid_trade_map.get(trade_id)
                venue_trade = venue_trade_map.get(trade_id)
                
                # Skip if trade exists in both systems (already matched)
                if merid_trade and venue_trade:
                    # Check for differences in key fields
                    differences = []
                    
                    if merid_trade.get("price") != venue_trade.get("price"):
                        price_diff = abs(float(merid_trade.get("price", 0)) - float(venue_trade.get("price", 0)))
                        differences.append(("price", price_diff))
                    
                    if merid_trade.get("quantity") != venue_trade.get("quantity"):
                        qty_diff = abs(float(merid_trade.get("quantity", 0)) - float(venue_trade.get("quantity", 0)))
                        differences.append(("quantity", qty_diff))
                    
                    if differences:
                        # Calculate total difference
                        total_diff = sum(diff for _, diff in differences)
                        
                        # Get tolerance
                        tolerance_config = self.tolerance_configs[ReconciliationType.TRADE]
                        tolerance = tolerance_config["absolute"]
                        
                        # Determine status
                        if total_diff <= tolerance:
                            status = ReconciliationStatus.MATCHED
                            severity = MismatchSeverity.LOW
                        else:
                            status = ReconciliationStatus.MISMATCH
                            severity = self._determine_severity(
                                ReconciliationType.TRADE,
                                total_diff,
                                tolerance_config
                            )
                        
                        # Create reconciliation result
                        result = ReconciliationResult(
                            reconciliation_id=str(uuid.uuid4()),
                            reconciliation_type=ReconciliationType.TRADE,
                            venue=venue,
                            symbol=merid_trade.get("symbol"),
                            merid_value=total_diff,
                            venue_value=0.0,  # Venue value is reference
                            difference=total_diff,
                            tolerance=tolerance,
                            status=status,
                            severity=severity,
                            timestamp=datetime.now(),
                            metadata={"trade_id": trade_id, "differences": differences}
                        )
                        
                        results.append(result)
                        self.reconciliation_results[venue].append(result)
                        
                        # Handle mismatch
                        if status == ReconciliationStatus.MISMATCH:
                            await self._handle_reconciliation_mismatch(result)
                
                elif merid_trade and not venue_trade:
                    # Trade in MERID but not in venue
                    result = ReconciliationResult(
                        reconciliation_id=str(uuid.uuid4()),
                        reconciliation_type=ReconciliationType.TRADE,
                        venue=venue,
                        symbol=merid_trade.get("symbol"),
                        merid_value=float(merid_trade.get("quantity", 0)),
                        venue_value=0.0,
                        difference=float(merid_trade.get("quantity", 0)),
                        tolerance=0.0,
                        status=ReconciliationStatus.MISMATCH,
                        severity=MismatchSeverity.HIGH,
                        timestamp=datetime.now(),
                        metadata={"trade_id": trade_id, "issue": "missing_in_venue"}
                    )
                    
                    results.append(result)
                    self.reconciliation_results[venue].append(result)
                    await self._handle_reconciliation_mismatch(result)
                
                elif venue_trade and not merid_trade:
                    # Trade in venue but not in MERID
                    result = ReconciliationResult(
                        reconciliation_id=str(uuid.uuid4()),
                        reconciliation_type=ReconciliationType.TRADE,
                        venue=venue,
                        symbol=venue_trade.get("symbol"),
                        merid_value=0.0,
                        venue_value=float(venue_trade.get("quantity", 0)),
                        difference=float(venue_trade.get("quantity", 0)),
                        tolerance=0.0,
                        status=ReconciliationStatus.MISMATCH,
                        severity=MismatchSeverity.HIGH,
                        timestamp=datetime.now(),
                        metadata={"trade_id": trade_id, "issue": "missing_in_merid"}
                    )
                    
                    results.append(result)
                    self.reconciliation_results[venue].append(result)
                    await self._handle_reconciliation_mismatch(result)
            
            logger.info(f"Trade reconciliation completed for {venue}: {len(results)} mismatches")
            return results
            
        except Exception as e:
            logger.error(f"Failed to reconcile trades for {venue}: {e}")
            return []
    
    def _determine_severity(self, reconciliation_type: ReconciliationType,
                          difference: float, tolerance_config: Dict[str, Any]) -> MismatchSeverity:
        """Determine mismatch severity based on difference."""
        try:
            severity_thresholds = tolerance_config["severity_thresholds"]
            
            if difference <= severity_thresholds[MismatchSeverity.LOW]:
                return MismatchSeverity.LOW
            elif difference <= severity_thresholds[MismatchSeverity.MEDIUM]:
                return MismatchSeverity.MEDIUM
            elif difference <= severity_thresholds[MismatchSeverity.HIGH]:
                return MismatchSeverity.HIGH
            else:
                return MismatchSeverity.CRITICAL
                
        except Exception as e:
            logger.error(f"Failed to determine severity: {e}")
            return MismatchSeverity.MEDIUM
    
    async def _handle_reconciliation_mismatch(self, result: ReconciliationResult):
        """Handle reconciliation mismatch."""
        try:
            # Create alert
            alert_id = str(uuid.uuid4())
            
            alert = ReconciliationAlert(
                alert_id=alert_id,
                reconciliation_id=result.reconciliation_id,
                alert_type=f"{result.reconciliation_type.value}_mismatch",
                severity=result.severity,
                message=f"{result.reconciliation_type.value.capitalize()} mismatch detected: {result.difference:.6f} (tolerance: {result.tolerance:.6f})",
                venue=result.venue,
                symbol=result.symbol,
                difference=result.difference,
                tolerance=result.tolerance,
                triggered_at=result.timestamp,
                resolved_at=None,
                kill_switch_triggered=False,
                metadata={}
            )
            
            self.reconciliation_alerts[alert_id] = alert
            
            # Check if kill switch should be triggered
            if await self._should_trigger_kill_switch(result):
                await self._trigger_kill_switch_for_reconciliation(result, alert)
                alert.kill_switch_triggered = True
                result.status = ReconciliationStatus.KILL_SWITCH_TRIGGERED
            
            # Record for compliance
            if self.us_compliance.get("audit_reconciliation", True):
                await self._record_reconciliation_alert(alert)
            
            logger.warning(f"Reconciliation mismatch alert created: {alert_id}")
            
        except Exception as e:
            logger.error(f"Failed to handle reconciliation mismatch: {e}")
    
    async def _should_trigger_kill_switch(self, result: ReconciliationResult) -> bool:
        """Determine if kill switch should be triggered."""
        try:
            if not self.reconciliation_config.get("auto_kill_switch_enabled", True):
                return False
            
            # Check for critical severity
            if result.severity == MismatchSeverity.CRITICAL:
                return True
            
            # Check for critical threshold
            critical_threshold = self.reconciliation_config.get("critical_mismatch_threshold", 1000.0)
            if result.difference > critical_threshold:
                return True
            
            # Check for multiple mismatches
            recent_mismatches = [
                r for r in self.reconciliation_results.get(result.venue, [])
                if r.timestamp > datetime.now() - timedelta(minutes=10)
                and r.status == ReconciliationStatus.MISMATCH
            ]
            
            max_mismatches = self.reconciliation_config.get("max_mismatches_before_kill", 3)
            if len(recent_mismatches) >= max_mismatches:
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Failed to determine kill switch trigger: {e}")
            return False
    
    async def _trigger_kill_switch_for_reconciliation(self, result: ReconciliationResult, alert: ReconciliationAlert):
        """Trigger kill switch for reconciliation issue."""
        try:
            if self.kill_switch_manager:
                # Trigger venue-specific kill switch
                switch_id = f"venue_{result.venue}_reconciliation"
                reason = f"Reconciliation mismatch: {result.reconciliation_type.value} - {result.difference:.6f}"
                
                success = await self.kill_switch_manager.trigger_kill_switch(
                    switch_id, reason, "reconciliation_system"
                )
                
                if success:
                    logger.critical(f"Kill switch triggered for reconciliation mismatch: {switch_id}")
                else:
                    logger.error(f"Failed to trigger kill switch: {switch_id}")
            else:
                logger.warning("No kill switch manager available")
                
        except Exception as e:
            logger.error(f"Failed to trigger kill switch for reconciliation: {e}")
    
    async def _record_accounting_entry(self, result: ReconciliationResult):
        """Record accounting entry for reconciliation."""
        try:
            if not self.us_compliance.get("accounting_standards", True):
                return
            
            entry_id = str(uuid.uuid4())
            
            # Determine entry type
            if result.status == ReconciliationStatus.MATCHED:
                entry_type = "reconciliation_matched"
            else:
                entry_type = "reconciliation_mismatch"
            
            # Create accounting entry
            entry = AccountingEntry(
                entry_id=entry_id,
                entry_type=entry_type,
                venue=result.venue,
                symbol=result.symbol,
                amount=result.difference,
                currency="USD" if result.reconciliation_type in [ReconciliationType.BALANCE, ReconciliationType.CASH, ReconciliationType.PNL] else "UNITS",
                timestamp=result.timestamp,
                reference_id=result.reconciliation_id,
                description=f"{result.reconciliation_type.value} reconciliation: {result.difference:.6f}",
                metadata={
                    "merid_value": result.merid_value,
                    "venue_value": result.venue_value,
                    "tolerance": result.tolerance,
                    "status": result.status.value
                }
            )
            
            # Store accounting entry
            self.accounting_entries[result.venue].append(entry)
            
            # Record for compliance
            if self.us_compliance.get("regulatory_reporting", True):
                await self._record_accounting_entry_compliance(entry)
            
        except Exception as e:
            logger.error(f"Failed to record accounting entry: {e}")
    
    async def _record_reconciliation_alert(self, alert: ReconciliationAlert):
        """Record reconciliation alert for compliance."""
        if not self.us_compliance.get("audit_reconciliation", True):
            return
        
        audit_entry = {
            "action": "reconciliation_alert",
            "alert_id": alert.alert_id,
            "reconciliation_id": alert.reconciliation_id,
            "alert_type": alert.alert_type,
            "severity": alert.severity.value,
            "venue": alert.venue,
            "symbol": alert.symbol,
            "difference": alert.difference,
            "tolerance": alert.tolerance,
            "triggered_at": alert.triggered_at.isoformat(),
            "kill_switch_triggered": alert.kill_switch_triggered,
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Reconciliation alert audit entry: {audit_entry}")
    
    async def _record_accounting_entry_compliance(self, entry: AccountingEntry):
        """Record accounting entry for compliance."""
        if not self.us_compliance.get("regulatory_reporting", True):
            return
        
        audit_entry = {
            "action": "accounting_entry",
            "entry_id": entry.entry_id,
            "entry_type": entry.entry_type,
            "venue": entry.venue,
            "symbol": entry.symbol,
            "amount": entry.amount,
            "currency": entry.currency,
            "timestamp": entry.timestamp.isoformat(),
            "reference_id": entry.reference_id,
            "description": entry.description,
            "user": "system"  # In production, get actual user
        }
        
        # In production, store in audit database
        logger.debug(f"Accounting entry audit entry: {audit_entry}")
    
    def get_reconciliation_summary(self, venue: Optional[str] = None,
                                 time_window_hours: int = 24) -> Dict[str, Any]:
        """Get reconciliation summary."""
        try:
            cutoff_time = datetime.now() - timedelta(hours=time_window_hours)
            
            # Filter results by venue and time
            all_results = []
            if venue:
                all_results.extend(self.reconciliation_results.get(venue, []))
            else:
                for venue_results in self.reconciliation_results.values():
                    all_results.extend(venue_results)
            
            recent_results = [r for r in all_results if r.timestamp > cutoff_time]
            
            if not recent_results:
                return {"status": "no_recent_reconciliations"}
            
            # Status distribution
            status_counts = {}
            for result in recent_results:
                status_name = result.status.value
                status_counts[status_name] = status_counts.get(status_name, 0) + 1
            
            # Severity distribution for mismatches
            severity_counts = {}
            for result in recent_results:
                if result.status == ReconciliationStatus.MISMATCH:
                    severity_name = result.severity.value
                    severity_counts[severity_name] = severity_counts.get(severity_name, 0) + 1
            
            # Type distribution
            type_counts = {}
            for result in recent_results:
                type_name = result.reconciliation_type.value
                type_counts[type_name] = type_counts.get(type_name, 0) + 1
            
            # Recent alerts
            recent_alerts = [
                alert for alert in self.reconciliation_alerts.values()
                if alert.triggered_at > cutoff_time
            ]
            
            # Kill switch triggers
            kill_switch_triggers = sum(1 for alert in recent_alerts if alert.kill_switch_triggered)
            
            return {
                "total_reconciliations": len(recent_results),
                "status_distribution": status_counts,
                "severity_distribution": severity_counts,
                "type_distribution": type_counts,
                "recent_alerts": len(recent_alerts),
                "kill_switch_triggers": kill_switch_triggers,
                "time_window_hours": time_window_hours,
                "us_compliance": self.us_compliance
            }
            
        except Exception as e:
            logger.error(f"Failed to get reconciliation summary: {e}")
            return {"status": "error", "error": str(e)}
    
    def get_accounting_summary(self, venue: Optional[str] = None,
                             time_window_hours: int = 24) -> Dict[str, Any]:
        """Get accounting summary."""
        try:
            cutoff_time = datetime.now() - timedelta(hours=time_window_hours)
            
            # Filter entries by venue and time
            all_entries = []
            if venue:
                all_entries.extend(self.accounting_entries.get(venue, []))
            else:
                for venue_entries in self.accounting_entries.values():
                    all_entries.extend(venue_entries)
            
            recent_entries = [e for e in all_entries if e.timestamp > cutoff_time]
            
            if not recent_entries:
                return {"status": "no_recent_entries"}
            
            # Entry type distribution
            type_counts = {}
            for entry in recent_entries:
                type_name = entry.entry_type
                type_counts[type_name] = type_counts.get(type_name, 0) + 1
            
            # Currency distribution
            currency_counts = {}
            for entry in recent_entries:
                currency_name = entry.currency
                currency_counts[currency_name] = currency_counts.get(currency_name, 0) + 1
            
            # Total amounts by type
            amounts_by_type = defaultdict(float)
            for entry in recent_entries:
                amounts_by_type[entry.entry_type] += abs(entry.amount)
            
            return {
                "total_entries": len(recent_entries),
                "type_distribution": type_counts,
                "currency_distribution": currency_counts,
                "amounts_by_type": dict(amounts_by_type),
                "time_window_hours": time_window_hours,
                "us_compliance": self.us_compliance
            }
            
        except Exception as e:
            logger.error(f"Failed to get accounting summary: {e}")
            return {"status": "error", "error": str(e)}
    
    def update_config(self, new_config: Dict[str, Any]):
        """Update reconciliation configuration."""
        self.config.update(new_config)
        
        # Update specific parameters
        if "reconciliation_system" in new_config:
            self.reconciliation_config.update(new_config["reconciliation_system"])
        
        logger.info("Reconciliation system configuration updated")

"""
Compliance Manager.

Central coordinator for all compliance functionality.

Version: 1.0.0
"""

from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional, Any

from compliance.audit_logger import AuditLogger, get_audit_logger, AuditCategory, AuditSeverity
from compliance.transaction_log import TransactionLog, get_transaction_log, TransactionType
from compliance.regulatory_reports import ReportGenerator, get_report_generator, ReportType, ReportFormat
from compliance.data_retention import DataRetentionManager, get_retention_manager, RetentionCategory
from utils.logger import get_logger

logger = get_logger("compliance.manager")


class ComplianceManager:
    """
    Central compliance management system.
    
    Coordinates:
    - Audit logging
    - Transaction logging
    - Regulatory reporting
    - Data retention
    """
    
    def __init__(self):
        self.logger = get_logger("compliance.manager")
        
        # Sub-managers
        self._audit = get_audit_logger()
        self._transactions = get_transaction_log()
        self._reports = get_report_generator()
        self._retention = get_retention_manager()
    
    # ==========================================
    # AUDIT LOGGING
    # ==========================================
    
    def log_audit(
        self,
        category: AuditCategory,
        action: str,
        severity: AuditSeverity = AuditSeverity.INFO,
        actor_id: str = "system",
        actor_type: str = "system",
        target_type: str = "",
        target_id: str = "",
        details: Optional[Dict[str, Any]] = None,
        result: str = "success",
    ) -> str:
        """Log an audit event."""
        return self._audit.log(
            category=category,
            action=action,
            severity=severity,
            actor_id=actor_id,
            actor_type=actor_type,
            target_type=target_type,
            target_id=target_id,
            details=details,
            result=result,
        )
    
    def log_trade(
        self,
        action: str,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        actor_id: str = "system",
        result: str = "success",
        details: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Log a trading action."""
        return self._audit.log(
            category=AuditCategory.TRADING,
            action=action,
            severity=AuditSeverity.INFO,
            actor_id=actor_id,
            actor_type="agent",
            target_type="order",
            details={
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "price": price,
                **(details or {}),
            },
            result=result,
        )
    
    def log_wallet_action(
        self,
        action: str,
        wallet_id: str,
        actor_id: str = "system",
        details: Optional[Dict[str, Any]] = None,
        result: str = "success",
    ) -> str:
        """Log a wallet action."""
        return self._audit.log(
            category=AuditCategory.WALLET,
            action=action,
            severity=AuditSeverity.WARNING if action in ["withdraw", "transfer"] else AuditSeverity.INFO,
            actor_id=actor_id,
            target_type="wallet",
            target_id=wallet_id,
            details=details,
            result=result,
        )
    
    def log_config_change(
        self,
        setting: str,
        old_value: Any,
        new_value: Any,
        actor_id: str = "system",
    ) -> str:
        """Log a configuration change."""
        return self._audit.log(
            category=AuditCategory.CONFIGURATION,
            action="config_change",
            severity=AuditSeverity.WARNING,
            actor_id=actor_id,
            target_type="config",
            target_id=setting,
            details={
                "old_value": str(old_value),
                "new_value": str(new_value),
            },
        )
    
    # ==========================================
    # TRANSACTION LOGGING
    # ==========================================
    
    def log_transaction(
        self,
        tx_type: TransactionType,
        asset: str,
        quantity: float,
        price: float = 0.0,
        value_usd: float = 0.0,
        fee: float = 0.0,
        venue: str = "",
        order_id: str = "",
        **kwargs,
    ) -> str:
        """Log a financial transaction."""
        return self._transactions.log_transaction(
            tx_type=tx_type,
            asset=asset,
            quantity=quantity,
            price=price,
            value_usd=value_usd,
            fee=fee,
            venue=venue,
            order_id=order_id,
            **kwargs,
        )
    
    def get_transaction(self, tx_id: str) -> Optional[Dict[str, Any]]:
        """Get a transaction by ID."""
        tx = self._transactions.get_transaction(tx_id)
        return tx.to_dict() if tx else None
    
    def query_transactions(
        self,
        tx_type: Optional[str] = None,
        asset: Optional[str] = None,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Query transactions."""
        tt = TransactionType(tx_type) if tx_type else None
        txs = self._transactions.query(
            tx_type=tt,
            asset=asset,
            start_time=start_time,
            end_time=end_time,
            limit=limit,
        )
        return [t.to_dict() for t in txs]
    
    # ==========================================
    # REPORTING
    # ==========================================
    
    def generate_report(
        self,
        report_type: str,
        start_date: str,
        end_date: str,
        format: str = "json",
    ) -> Dict[str, Any]:
        """Generate a compliance report."""
        rt = ReportType(report_type)
        rf = ReportFormat(format)
        report = self._reports.generate_report(rt, start_date, end_date, rf)
        return report.to_dict()
    
    def get_daily_summary(self, date: Optional[str] = None) -> Dict[str, Any]:
        """Get daily transaction summary."""
        return self._transactions.get_daily_summary(date)
    
    # ==========================================
    # DATA RETENTION
    # ==========================================
    
    def create_legal_hold(
        self,
        name: str,
        description: str,
        categories: List[str],
        case_number: str = "",
        created_by: str = "system",
    ) -> str:
        """Create a legal hold."""
        cats = [RetentionCategory(c) for c in categories]
        hold_id = self._retention.create_legal_hold(
            name=name,
            description=description,
            categories=cats,
            case_number=case_number,
            created_by=created_by,
        )
        
        # Audit the legal hold creation
        self._audit.log(
            category=AuditCategory.COMPLIANCE,
            action="legal_hold_created",
            severity=AuditSeverity.CRITICAL,
            actor_id=created_by,
            target_type="legal_hold",
            target_id=hold_id,
            details={"name": name, "case_number": case_number},
        )
        
        return hold_id
    
    def release_legal_hold(self, hold_id: str, released_by: str = "system") -> bool:
        """Release a legal hold."""
        success = self._retention.release_legal_hold(hold_id)
        
        if success:
            self._audit.log(
                category=AuditCategory.COMPLIANCE,
                action="legal_hold_released",
                severity=AuditSeverity.CRITICAL,
                actor_id=released_by,
                target_type="legal_hold",
                target_id=hold_id,
            )
        
        return success
    
    def run_retention(self) -> List[Dict[str, Any]]:
        """Run data retention policies."""
        jobs = self._retention.run_retention()
        return [j.to_dict() for j in jobs]
    
    # ==========================================
    # VERIFICATION
    # ==========================================
    
    def verify_audit_chain(self, start_date: Optional[str] = None) -> Dict[str, Any]:
        """Verify audit log integrity."""
        return self._audit.verify_chain(start_date)
    
    def reconcile_transactions(
        self,
        venue: str,
        external_transactions: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Reconcile transactions with external data."""
        return self._transactions.reconcile(venue, external_transactions)
    
    # ==========================================
    # STATUS
    # ==========================================
    
    def get_compliance_dashboard(self) -> Dict[str, Any]:
        """Get compliance dashboard data."""
        return {
            "audit": self._audit.get_stats(),
            "transactions": self._transactions.get_stats(),
            "reports": self._reports.get_status(),
            "retention": self._retention.get_status(),
            "compliance_report": self._retention.get_compliance_report(),
        }
    
    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive compliance status."""
        return {
            "audit_stats": self._audit.get_stats(),
            "transaction_stats": self._transactions.get_stats(),
            "report_generator": self._reports.get_status(),
            "retention_manager": self._retention.get_status(),
        }


# Singleton
_compliance_manager: Optional[ComplianceManager] = None
_compliance_manager_lock = threading.Lock()


def get_compliance_manager() -> ComplianceManager:
    """Get or create the Compliance Manager singleton."""
    global _compliance_manager
    if _compliance_manager is None:
        with _compliance_manager_lock:
            if _compliance_manager is None:
                _compliance_manager = ComplianceManager()
    return _compliance_manager

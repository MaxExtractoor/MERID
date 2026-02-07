"""
MERID Compliance & Audit Trail System.

Provides comprehensive logging, regulatory reporting, and data retention
for compliance with financial regulations.

Version: 1.0.0
"""

from compliance.audit_logger import AuditLogger, AuditEvent, get_audit_logger
from compliance.transaction_log import TransactionLog, get_transaction_log
from compliance.regulatory_reports import ReportGenerator, get_report_generator
from compliance.data_retention import DataRetentionManager, get_retention_manager
from compliance.compliance_manager import ComplianceManager, get_compliance_manager

__all__ = [
    "AuditLogger",
    "AuditEvent",
    "get_audit_logger",
    "TransactionLog",
    "get_transaction_log",
    "ReportGenerator",
    "get_report_generator",
    "DataRetentionManager",
    "get_retention_manager",
    "ComplianceManager",
    "get_compliance_manager",
]

# Compliance settings
AUDIT_ENABLED = True
RETENTION_DAYS_DEFAULT = 2555  # 7 years for financial records

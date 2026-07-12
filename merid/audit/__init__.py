"""
Audit module for MERID trading system.

This module provides production-grade auditing capabilities for the 15m Kalshi
crypto trading system, including continuous monitoring of data, sizing, routing,
fills, exits, and state reconciliation.
"""

from merid.audit.production_audit_harness import (
    ProductionAuditHarness,
    AuditSeverity,
    AuditLayer,
    AuditFinding,
    AuditReport,
    get_production_audit_harness,
    start_production_audit_harness,
    stop_production_audit_harness,
)

__all__ = [
    "ProductionAuditHarness",
    "AuditSeverity",
    "AuditLayer",
    "AuditFinding",
    "AuditReport",
    "get_production_audit_harness",
    "start_production_audit_harness",
    "stop_production_audit_harness",
]

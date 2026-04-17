"""
Compliance & Audit API Endpoints.

Provides API access to audit logging, transaction logs, reports, and retention.
"""

from __future__ import annotations

from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from web.api.auth import get_current_session

from compliance import (
    get_compliance_manager,
    get_audit_logger,
    get_transaction_log,
    get_report_generator,
    get_retention_manager,
)
from compliance.audit_logger import AuditCategory, AuditSeverity
from compliance.transaction_log import TransactionType
from compliance.regulatory_reports import ReportType, ReportFormat
from compliance.data_retention import RetentionCategory
from utils.logger import get_logger

# ZT6-01: All compliance mutation routes require authentication.
router = APIRouter(
    prefix="/api/v1/compliance",
    tags=["compliance"],
    dependencies=[Depends(get_current_session)],
)
logger = get_logger("web.api.compliance")


# ============================================
# REQUEST MODELS
# ============================================

class AuditLogRequest(BaseModel):
    category: str
    action: str
    severity: str = "info"
    actor_id: str = "api"
    target_type: str = ""
    target_id: str = ""
    details: Dict[str, Any] = {}
    result: str = "success"


class TransactionLogRequest(BaseModel):
    tx_type: str
    asset: str
    quantity: float
    price: float = 0.0
    value_usd: float = 0.0
    fee: float = 0.0
    venue: str = ""
    order_id: str = ""


class ReportRequest(BaseModel):
    report_type: str
    start_date: str
    end_date: str
    format: str = "json"


class LegalHoldRequest(BaseModel):
    name: str
    description: str
    categories: List[str]
    case_number: str = ""
    created_by: str = "admin"


class ReconcileRequest(BaseModel):
    venue: str
    external_transactions: List[Dict[str, Any]]


# ============================================
# COMPLIANCE MANAGER ENDPOINTS
# ============================================

@router.get("/status")
async def get_compliance_status() -> Dict[str, Any]:
    """Get comprehensive compliance status."""
    return get_compliance_manager().get_status()


@router.get("/dashboard")
async def get_compliance_dashboard() -> Dict[str, Any]:
    """Get compliance dashboard data."""
    return get_compliance_manager().get_compliance_dashboard()


# ============================================
# AUDIT ENDPOINTS
# ============================================

@router.get("/audit/status")
async def get_audit_status() -> Dict[str, Any]:
    """Get audit logger status."""
    return get_audit_logger().get_stats()


@router.post("/audit/log")
async def log_audit_event(request: AuditLogRequest) -> Dict[str, Any]:
    """Log an audit event."""
    try:
        category = AuditCategory(request.category)
        severity = AuditSeverity(request.severity)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    event_id = get_compliance_manager().log_audit(
        category=category,
        action=request.action,
        severity=severity,
        actor_id=request.actor_id,
        target_type=request.target_type,
        target_id=request.target_id,
        details=request.details,
        result=request.result,
    )
    return {"status": "logged", "event_id": event_id}


@router.get("/audit/query")
async def query_audit_events(
    category: Optional[str] = None,
    actor_id: Optional[str] = None,
    target_id: Optional[str] = None,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    severity: Optional[str] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    """Query audit events."""
    cat = AuditCategory(category) if category else None
    sev = AuditSeverity(severity) if severity else None
    
    events = get_audit_logger().query(
        category=cat,
        actor_id=actor_id,
        target_id=target_id,
        start_time=start_time,
        end_time=end_time,
        severity=sev,
        limit=limit,
    )
    return {"count": len(events), "events": [e.to_dict() for e in events]}


@router.get("/audit/verify")
async def verify_audit_chain(start_date: Optional[str] = None) -> Dict[str, Any]:
    """Verify audit log integrity."""
    return get_compliance_manager().verify_audit_chain(start_date)


@router.post("/audit/export")
async def export_audit_log(
    start_time: float,
    end_time: float,
    format: str = "json",
) -> Dict[str, Any]:
    """Export audit log."""
    file_path = get_audit_logger().export(start_time, end_time, format)
    return {"status": "exported", "file_path": file_path}


# ============================================
# TRANSACTION ENDPOINTS
# ============================================

@router.get("/transactions/status")
async def get_transaction_status() -> Dict[str, Any]:
    """Get transaction log status."""
    return get_transaction_log().get_stats()


@router.post("/transactions/log")
async def log_transaction(request: TransactionLogRequest) -> Dict[str, Any]:
    """Log a transaction."""
    try:
        tx_type = TransactionType(request.tx_type)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    tx_id = get_compliance_manager().log_transaction(
        tx_type=tx_type,
        asset=request.asset,
        quantity=request.quantity,
        price=request.price,
        value_usd=request.value_usd,
        fee=request.fee,
        venue=request.venue,
        order_id=request.order_id,
    )
    return {"status": "logged", "tx_id": tx_id}


@router.get("/transactions/{tx_id}")
async def get_transaction(tx_id: str) -> Dict[str, Any]:
    """Get a transaction by ID."""
    tx = get_compliance_manager().get_transaction(tx_id)
    if tx:
        return tx
    raise HTTPException(status_code=404, detail="Transaction not found")


@router.get("/transactions/query")
async def query_transactions(
    tx_type: Optional[str] = None,
    asset: Optional[str] = None,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None,
    limit: int = 100,
) -> Dict[str, Any]:
    """Query transactions."""
    txs = get_compliance_manager().query_transactions(
        tx_type=tx_type,
        asset=asset,
        start_time=start_time,
        end_time=end_time,
        limit=limit,
    )
    return {"count": len(txs), "transactions": txs}


@router.get("/transactions/daily-summary")
async def get_daily_summary(date: Optional[str] = None) -> Dict[str, Any]:
    """Get daily transaction summary."""
    return get_compliance_manager().get_daily_summary(date)


@router.post("/transactions/reconcile")
async def reconcile_transactions(request: ReconcileRequest) -> Dict[str, Any]:
    """Reconcile transactions with external data."""
    return get_compliance_manager().reconcile_transactions(
        request.venue,
        request.external_transactions,
    )


@router.post("/transactions/export")
async def export_transactions(
    start_time: float,
    end_time: float,
    format: str = "json",
) -> Dict[str, Any]:
    """Export transactions."""
    file_path = get_transaction_log().export(start_time, end_time, format)
    return {"status": "exported", "file_path": file_path}


# ============================================
# REPORT ENDPOINTS
# ============================================

@router.get("/reports/status")
async def get_reports_status() -> Dict[str, Any]:
    """Get report generator status."""
    return get_report_generator().get_status()


@router.post("/reports/generate")
async def generate_report(request: ReportRequest) -> Dict[str, Any]:
    """Generate a compliance report."""
    return get_compliance_manager().generate_report(
        report_type=request.report_type,
        start_date=request.start_date,
        end_date=request.end_date,
        format=request.format,
    )


@router.get("/reports")
async def list_reports(report_type: Optional[str] = None) -> Dict[str, Any]:
    """List generated reports."""
    rt = ReportType(report_type) if report_type else None
    reports = get_report_generator().list_reports(rt)
    return {"count": len(reports), "reports": reports}


@router.get("/reports/{report_id}")
async def get_report(report_id: str) -> Dict[str, Any]:
    """Get a generated report."""
    report = get_report_generator().get_report(report_id)
    if report:
        return {"metadata": report.to_dict(), "data": report.data}
    raise HTTPException(status_code=404, detail="Report not found")


# ============================================
# RETENTION ENDPOINTS
# ============================================

@router.get("/retention/status")
async def get_retention_status() -> Dict[str, Any]:
    """Get data retention status."""
    return get_retention_manager().get_status()


@router.get("/retention/storage")
async def get_storage_stats() -> Dict[str, Any]:
    """Get storage statistics."""
    return get_retention_manager().get_storage_stats()


@router.get("/retention/compliance-report")
async def get_retention_compliance_report() -> Dict[str, Any]:
    """Get retention compliance report."""
    return get_retention_manager().get_compliance_report()


@router.post("/retention/run")
async def run_retention(policy_id: Optional[str] = None) -> Dict[str, Any]:
    """Run data retention policies."""
    jobs = get_compliance_manager().run_retention()
    return {"status": "completed", "jobs": jobs}


@router.post("/retention/legal-hold")
async def create_legal_hold(request: LegalHoldRequest) -> Dict[str, Any]:
    """Create a legal hold."""
    hold_id = get_compliance_manager().create_legal_hold(
        name=request.name,
        description=request.description,
        categories=request.categories,
        case_number=request.case_number,
        created_by=request.created_by,
    )
    return {"status": "created", "hold_id": hold_id}


@router.post("/retention/legal-hold/{hold_id}/release")
async def release_legal_hold(hold_id: str, released_by: str = "admin") -> Dict[str, Any]:
    """Release a legal hold."""
    success = get_compliance_manager().release_legal_hold(hold_id, released_by)
    if success:
        return {"status": "released"}
    raise HTTPException(status_code=404, detail="Legal hold not found")


@router.get("/retention/legal-holds")
async def list_legal_holds() -> Dict[str, Any]:
    """List legal holds."""
    holds = get_retention_manager()._legal_holds
    return {
        "count": len(holds),
        "active": sum(1 for h in holds.values() if h.active),
        "holds": [h.to_dict() for h in holds.values()],
    }

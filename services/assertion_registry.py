"""
MERID Assertion Registry Service

Central service for managing assertion templates and instances.
Provides REST API for registration, updates, and querying.
"""

from fastapi import APIRouter, HTTPException, Depends, Query
from pydantic import BaseModel, Field
from typing import Dict, List, Optional, Any
import json
import time
from datetime import datetime, timezone
import sqlite3
from contextlib import contextmanager

from core.assertion_framework import (
    Assertion, AssertionTemplate, AssertionStatus, AssertionSeverity,
    AssertionCategory, TemplateLifecycle, load_templates_from_config
)
from utils.logger import get_logger

logger = get_logger("assertion_registry")
router = APIRouter(prefix="/api/v1/assertions", tags=["assertions"])

# Database schema
DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS assertion_templates (
    template_id TEXT PRIMARY KEY,
    version INTEGER NOT NULL,
    library_version TEXT NOT NULL,
    description TEXT NOT NULL,
    category TEXT NOT NULL,
    severity_default TEXT NOT NULL,
    parameters TEXT NOT NULL,  -- JSON
    tags TEXT NOT NULL,  -- JSON
    owner_team TEXT NOT NULL,
    doc_url TEXT,
    lifecycle TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_updated TEXT NOT NULL,
    bindings TEXT  -- JSON
);

CREATE TABLE IF NOT EXISTS assertions (
    assertion_id TEXT PRIMARY KEY,
    template_id TEXT NOT NULL,
    template_version INTEGER NOT NULL,
    status TEXT NOT NULL,
    severity TEXT NOT NULL,
    subject TEXT NOT NULL,  -- JSON
    parameters TEXT NOT NULL,  -- JSON
    owner_team TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    resolved_at REAL,
    resolution_details TEXT,
    extra TEXT  -- JSON
);

CREATE INDEX IF NOT EXISTS idx_assertions_status ON assertions(status);
CREATE INDEX IF NOT EXISTS idx_assertions_template ON assertions(template_id);
CREATE INDEX IF NOT EXISTS idx_assertions_created_at ON assertions(created_at);
CREATE INDEX IF NOT EXISTS idx_assertions_owner_team ON assertions(owner_team);
"""

# Pydantic models for API
class AssertionRegistration(BaseModel):
    template_id: str
    subject: Dict[str, Any]
    parameters: Dict[str, Any]
    severity: Optional[str] = None
    owner_team: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None

class AssertionUpdate(BaseModel):
    assertion_id: str
    status: str
    details: Optional[str] = None
    timestamp: float

class AssertionRecord(BaseModel):
    assertion_id: str
    template_id: str
    status: str
    parameters: Dict[str, Any]
    subject: Optional[Dict[str, Any]] = None
    details: Optional[str] = None
    timestamp: float

class AssertionFilter(BaseModel):
    status: Optional[str] = None
    template_id: Optional[str] = None
    owner_team: Optional[str] = None
    severity: Optional[str] = None
    category: Optional[str] = None
    since: Optional[float] = None
    limit: int = Field(default=100, ge=1, le=1000)

# Database connection management
@contextmanager
def get_db_connection():
    """Context manager for database connections."""
    conn = sqlite3.connect("assertions.db")
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_database():
    """Initialize database with schema and default templates."""
    with get_db_connection() as conn:
        conn.executescript(DB_SCHEMA)
        
        # Load default templates if none exist
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM assertion_templates")
        if cursor.fetchone()[0] == 0:
            from core.assertion_framework import CORE_TEMPLATES
            templates = load_templates_from_config(CORE_TEMPLATES)
            
            for template in templates:
                cursor.execute("""
                    INSERT INTO assertion_templates 
                    (template_id, version, library_version, description, category,
                     severity_default, parameters, tags, owner_team, doc_url,
                     lifecycle, created_at, last_updated, bindings)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    template.template_id,
                    template.version,
                    template.library_version,
                    template.description,
                    template.category.value,
                    template.severity_default.value,
                    json.dumps(template.parameters),
                    json.dumps(template.tags),
                    template.owner_team,
                    template.doc_url,
                    template.lifecycle.value,
                    template.created_at.isoformat(),
                    template.last_updated.isoformat(),
                    json.dumps(template.bindings) if template.bindings else None
                ))
            
            conn.commit()
            logger.info(f"Initialized database with {len(templates)} default templates")

# API Endpoints
@router.post("/register")
def register_assertion(request: AssertionRegistration):
    """Register a new assertion instance."""
    try:
        # Validate template exists
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM assertion_templates WHERE template_id = ?",
                (request.template_id,)
            )
            template_row = cursor.fetchone()
            
            if not template_row:
                raise HTTPException(status_code=404, detail=f"Template {request.template_id} not found")
            
            # Get template defaults
            template = dict(template_row)
            severity = request.severity or template["severity_default"]
            owner_team = request.owner_team or template["owner_team"]
            
            # Create assertion
            assertion = Assertion(
                template_id=request.template_id,
                template_version=template["version"],
                severity=AssertionSeverity(severity),
                subject=request.subject,
                parameters=request.parameters,
                owner_team=owner_team,
                extra=request.extra or {}
            )
            
            # Store in database
            cursor.execute("""
                INSERT INTO assertions 
                (assertion_id, template_id, template_version, status, severity,
                 subject, parameters, owner_team, created_at, updated_at, extra)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                assertion.assertion_id,
                assertion.template_id,
                assertion.template_version,
                assertion.status.value,
                assertion.severity.value,
                json.dumps(assertion.subject),
                json.dumps(assertion.parameters),
                assertion.owner_team,
                assertion.created_at,
                assertion.updated_at,
                json.dumps(assertion.extra)
            ))
            
            conn.commit()
            logger.info(f"Registered assertion {assertion.assertion_id}")
            
            return {
                "success": True,
                "assertion_id": assertion.assertion_id,
                "status": assertion.status.value,
                "created_at": assertion.created_at
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to register assertion: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.put("/update")
def update_assertion_status(request: AssertionUpdate):
    """Update assertion status."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Check if assertion exists
            cursor.execute(
                "SELECT * FROM assertions WHERE assertion_id = ?",
                (request.assertion_id,)
            )
            assertion_row = cursor.fetchone()
            
            if not assertion_row:
                raise HTTPException(status_code=404, detail=f"Assertion {request.assertion_id} not found")
            
            # Update status
            status = AssertionStatus(request.status)
            resolved_at = request.timestamp if status in [AssertionStatus.PASSED, AssertionStatus.FAILED, AssertionStatus.EXPIRED] else None
            
            cursor.execute("""
                UPDATE assertions 
                SET status = ?, updated_at = ?, resolved_at = ?, resolution_details = ?
                WHERE assertion_id = ?
            """, (
                status.value,
                request.timestamp,
                resolved_at,
                request.details,
                request.assertion_id
            ))
            
            conn.commit()
            logger.info(f"Updated assertion {request.assertion_id} to {status.value}")
            
            return {
                "success": True,
                "assertion_id": request.assertion_id,
                "status": status.value,
                "updated_at": request.timestamp
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update assertion: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/record")
def record_assertion(request: AssertionRecord):
    """Record assertion result (create or update)."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Check if assertion exists
            cursor.execute(
                "SELECT * FROM assertions WHERE assertion_id = ?",
                (request.assertion_id,)
            )
            assertion_row = cursor.fetchone()
            
            if assertion_row:
                # Update existing assertion
                status = AssertionStatus(request.status)
                resolved_at = request.timestamp if status in [AssertionStatus.PASSED, AssertionStatus.FAILED, AssertionStatus.EXPIRED] else None
                
                cursor.execute("""
                    UPDATE assertions 
                    SET status = ?, updated_at = ?, resolved_at = ?, resolution_details = ?
                    WHERE assertion_id = ?
                """, (
                    status.value,
                    request.timestamp,
                    resolved_at,
                    request.details,
                    request.assertion_id
                ))
                
                action = "updated"
            else:
                # Create new assertion
                # Get template info
                cursor.execute(
                    "SELECT * FROM assertion_templates WHERE template_id = ?",
                    (request.template_id,)
                )
                template_row = cursor.fetchone()
                
                if not template_row:
                    raise HTTPException(status_code=404, detail=f"Template {request.template_id} not found")
                
                template = dict(template_row)
                assertion = Assertion(
                    assertion_id=request.assertion_id,
                    template_id=request.template_id,
                    template_version=template["version"],
                    severity=AssertionSeverity(template["severity_default"]),
                    subject=request.subject or {},
                    parameters=request.parameters,
                    owner_team=template["owner_team"]
                )
                assertion.status = AssertionStatus(request.status)
                assertion.updated_at = request.timestamp
                if assertion.status in [AssertionStatus.PASSED, AssertionStatus.FAILED, AssertionStatus.EXPIRED]:
                    assertion.resolved_at = request.timestamp
                assertion.resolution_details = request.details
                
                cursor.execute("""
                    INSERT INTO assertions 
                    (assertion_id, template_id, template_version, status, severity,
                     subject, parameters, owner_team, created_at, updated_at, resolved_at, resolution_details)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    assertion.assertion_id,
                    assertion.template_id,
                    assertion.template_version,
                    assertion.status.value,
                    assertion.severity.value,
                    json.dumps(assertion.subject),
                    json.dumps(assertion.parameters),
                    assertion.owner_team,
                    assertion.created_at,
                    assertion.updated_at,
                    assertion.resolved_at,
                    assertion.resolution_details
                ))
                
                action = "created"
            
            conn.commit()
            logger.info(f"Recorded assertion {request.assertion_id} ({action})")
            
            return {
                "success": True,
                "assertion_id": request.assertion_id,
                "action": action,
                "status": request.status
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to record assertion: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/list")
def list_assertions(
    status: Optional[str] = Query(None),
    template_id: Optional[str] = Query(None),
    owner_team: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    since: Optional[float] = Query(None),
    limit: int = Query(100, ge=1, le=1000)
):
    """List assertions with optional filtering."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Build query
            query = "SELECT * FROM assertions WHERE 1=1"
            params = []
            
            if status:
                query += " AND status = ?"
                params.append(status)
            
            if template_id:
                query += " AND template_id = ?"
                params.append(template_id)
            
            if owner_team:
                query += " AND owner_team = ?"
                params.append(owner_team)
            
            if severity:
                query += " AND severity = ?"
                params.append(severity)
            
            if since:
                query += " AND created_at >= ?"
                params.append(since)
            
            if category:
                # Join with templates to filter by category
                query = """
                    SELECT a.* FROM assertions a
                    JOIN assertion_templates t ON a.template_id = t.template_id
                    WHERE t.category = ?
                """ + query.replace("SELECT * FROM assertions WHERE", "AND")
                params.insert(0, category)
            
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            assertions = []
            for row in rows:
                assertion = dict(row)
                # Parse JSON fields
                assertion["subject"] = json.loads(assertion["subject"])
                assertion["parameters"] = json.loads(assertion["parameters"])
                if assertion["extra"]:
                    assertion["extra"] = json.loads(assertion["extra"])
                
                assertions.append(assertion)
            
            return {
                "success": True,
                "count": len(assertions),
                "assertions": assertions
            }
            
    except Exception as e:
        logger.error(f"Failed to list assertions: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/templates/{template_id}")
def get_template(template_id: str):
    """Get assertion template by ID."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM assertion_templates WHERE template_id = ?",
                (template_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                raise HTTPException(status_code=404, detail=f"Template {template_id} not found")
            
            template = dict(row)
            # Parse JSON fields
            template["parameters"] = json.loads(template["parameters"])
            template["tags"] = json.loads(template["tags"])
            if template["bindings"]:
                template["bindings"] = json.loads(template["bindings"])
            
            return {
                "success": True,
                "template": template
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get template: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/templates")
def list_templates(
    category: Optional[str] = Query(None),
    lifecycle: Optional[str] = Query(None),
    owner_team: Optional[str] = Query(None)
):
    """List assertion templates with optional filtering."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            query = "SELECT * FROM assertion_templates WHERE 1=1"
            params = []
            
            if category:
                query += " AND category = ?"
                params.append(category)
            
            if lifecycle:
                query += " AND lifecycle = ?"
                params.append(lifecycle)
            
            if owner_team:
                query += " AND owner_team = ?"
                params.append(owner_team)
            
            query += " ORDER BY template_id"
            
            cursor.execute(query, params)
            rows = cursor.fetchall()
            
            templates = []
            for row in rows:
                template = dict(row)
                # Parse JSON fields
                template["parameters"] = json.loads(template["parameters"])
                template["tags"] = json.loads(template["tags"])
                if template["bindings"]:
                    template["bindings"] = json.loads(template["bindings"])
                
                templates.append(template)
            
            return {
                "success": True,
                "count": len(templates),
                "templates": templates
            }
            
    except Exception as e:
        logger.error(f"Failed to list templates: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/metrics")
def get_assertion_metrics():
    """Get assertion metrics for monitoring."""
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            
            # Overall counts
            cursor.execute("""
                SELECT status, COUNT(*) as count
                FROM assertions
                WHERE created_at >= ?
                GROUP BY status
            """, (time.time() - 24*3600,))  # Last 24 hours
            
            status_counts = {row["status"]: row["count"] for row in cursor.fetchall()}
            
            # Template counts
            cursor.execute("""
                SELECT a.template_id, t.description, COUNT(*) as count
                FROM assertions a
                JOIN assertion_templates t ON a.template_id = t.template_id
                WHERE a.created_at >= ?
                GROUP BY a.template_id, t.description
                ORDER BY count DESC
                LIMIT 10
            """, (time.time() - 24*3600,))
            
            template_counts = [
                {
                    "template_id": row["template_id"],
                    "description": row["description"],
                    "count": row["count"]
                }
                for row in cursor.fetchall()
            ]
            
            # Severity breakdown
            cursor.execute("""
                SELECT severity, COUNT(*) as count
                FROM assertions
                WHERE created_at >= ? AND status = 'failed'
                GROUP BY severity
            """, (time.time() - 24*3600,))
            
            severity_breakdown = {row["severity"]: row["count"] for row in cursor.fetchall()}
            
            return {
                "success": True,
                "period_hours": 24,
                "status_counts": status_counts,
                "template_counts": template_counts,
                "severity_breakdown": severity_breakdown,
                "timestamp": time.time()
            }
            
    except Exception as e:
        logger.error(f"Failed to get metrics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# Initialize database on module import
init_database()

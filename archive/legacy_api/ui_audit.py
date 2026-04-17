"""
UI Audit API Endpoints
REST API for running UI audits and managing audit results
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from datetime import datetime, timezone
import asyncio
from web.api.auth import get_current_session
from utils.logger import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/v1/ui-audit", tags=["ui-audit"], dependencies=[Depends(get_current_session)]  # ZT6-01
)

# Pydantic models for API requests/responses
class AuditRequest(BaseModel):
    pages: Optional[List[str]] = Field(None, description="Pages to audit (default: all pages)")
    headless: bool = Field(True, description="Run browser in headless mode")
    categories: Optional[List[str]] = Field(None, description="Audit categories to include")
    severity_threshold: str = Field("warning", description="Minimum severity level to report")

class QuickAuditRequest(BaseModel):
    pages: Optional[List[str]] = Field(None, description="Pages to audit (default: key pages)")
    headless: bool = Field(True, description="Run browser in headless mode")

class AuditPage(BaseModel):
    page: str
    url: str
    status_code: int
    load_time: float
    issue_count: int
    critical_issues: int
    error_issues: int
    warning_issues: int
    issues: List[Dict[str, Any]] = []

class AuditSummary(BaseModel):
    total_pages: int
    total_issues: int
    critical_issues: int
    error_issues: int
    warning_issues: int
    avg_load_time: float
    audit_timestamp: datetime

class AuditReport(BaseModel):
    summary: AuditSummary
    pages: List[AuditPage]
    issues_by_category: Dict[str, int]
    issues_by_severity: Dict[str, int]

# Global audit results storage
audit_results: Dict[str, Any] = {}
audit_tasks: Dict[str, BackgroundTasks] = {}

@router.post("/run")
async def run_ui_audit(request: AuditRequest, background_tasks: BackgroundTasks):
    """Run comprehensive UI audit"""
    try:
        # Import here to avoid circular imports
        from qa.ui_auditor import UIAuditor
        
        # Default pages if not provided
        if not request.pages:
            request.pages = [
                "/",
                "/dashboard",
                "/simple-dashboard",
                "/api-contracts",
                "/mode-management",
                "/observability",
                "/unified.html",
                "/main-test",
                "/debug-v2"
            ]
        
        # Create task ID
        task_id = f"audit_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        
        # Start background audit
        def run_audit_task():
            try:
                auditor = UIAuditor(headless=request.headless)
                results = auditor.audit_all_pages(request.pages)
                
                # Generate report
                report = auditor.generate_report()
                audit_results[task_id] = {
                    "status": "completed",
                    "report": report,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                
                # Save report to file
                filename = auditor.save_report()
                audit_results[task_id]["filename"] = filename
                
                logger.info(f"UI audit completed: {task_id}")
                
            except Exception as e:
                audit_results[task_id] = {
                    "status": "failed",
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                logger.error(f"UI audit failed: {task_id} - {e}")
        
        # Start background task
        task = background_tasks.add_task(run_audit_task)
        audit_tasks[task_id] = task
        
        return {
            "status": "started",
            "task_id": task_id,
            "pages": request.pages,
            "message": "UI audit started in background"
        }
        
    except Exception as e:
        logger.error(f"Failed to start UI audit: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start UI audit: {e}")

@router.post("/quick")
async def run_quick_ui_audit(request: QuickAuditRequest, background_tasks: BackgroundTasks):
    """Run quick UI audit on key pages"""
    try:
        # Import here to avoid circular imports
        from qa.ui_auditor import quick_ui_audit
        
        # Default pages for quick audit
        if not request.pages:
            request.pages = [
                "/",
                "/dashboard",
                "/api-contracts",
                "/mode-management",
                "/observability"
            ]
        
        # Create task ID
        task_id = f"quick_audit_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        
        # Start background quick audit
        def run_quick_audit_task():
            try:
                report = quick_ui_audit(pages=request.pages, headless=request.headless)
                
                audit_results[task_id] = {
                    "status": "completed",
                    "report": report,
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                
                logger.info(f"Quick UI audit completed: {task_id}")
                
            except Exception as e:
                audit_results[task_id] = {
                    "status": "failed",
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat()
                }
                logger.error(f"Quick UI audit failed: {task_id} - {e}")
        
        # Start background task
        task = background_tasks.add_task(run_quick_audit_task)
        audit_tasks[task_id] = task
        
        return {
            "status": "started",
            "task_id": task_id,
            "pages": request.pages,
            "message": "Quick UI audit started in background"
        }
        
    except Exception as e:
        logger.error(f"Failed to start quick UI audit: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start quick UI audit: {e}")

@router.get("/status/{task_id}")
async def get_audit_status(task_id: str):
    """Get status of an audit task"""
    if task_id not in audit_results:
        raise HTTPException(status_code=404, detail=f"Audit task {task_id} not found")
    
    result = audit_results[task_id]
    
    # Check if task is still running
    if task_id in audit_tasks:
        task = audit_tasks[task_id]
        if not task.done():
            result["status"] = "running"
        else:
            # Task completed, remove from running tasks
            del audit_tasks[task_id]
    
    return result

@router.get("/results/{task_id}")
async def get_audit_results(task_id: str):
    """Get audit results for a task"""
    if task_id not in audit_results:
        raise HTTPException(status_code=404, detail=f"Audit task {task_id} not found")
    
    result = audit_results[task_id]
    
    if result["status"] != "completed":
        raise HTTPException(status_code=400, detail=f"Audit task {task_id} not completed")
    
    return result["report"]

@router.get("/results")
async def list_audit_results():
    """List all audit results"""
    return {
        "tasks": list(audit_results.keys()),
        "results": {
            task_id: {
                "status": result["status"],
                "timestamp": result["timestamp"],
                "has_report": "report" in result,
                "has_error": "error" in result
            }
            for task_id, result in audit_results.items()
        }
    }

@router.delete("/results/{task_id}")
async def delete_audit_results(task_id: str):
    """Delete audit results"""
    if task_id not in audit_results:
        raise HTTPException(status_code=404, detail=f"Audit task {task_id} not found")
    
    # Remove from results
    del audit_results[task_id]
    
    # Remove from running tasks if present
    if task_id in audit_tasks:
        del audit_tasks[task_id]
    
    return {
        "status": "deleted",
        "task_id": task_id,
        "message": f"Audit results for {task_id} deleted"
    }

@router.get("/pages")
async def get_available_pages():
    """Get list of available pages for audit"""
    pages = [
        {"path": "/", "name": "Home", "description": "Main dashboard page"},
        {"path": "/dashboard", "name": "Dashboard", "description": "Primary dashboard interface"},
        {"path": "/simple-dashboard", "name": "Simple Dashboard", "description": "Simplified dashboard view"},
        {"path": "/api-contracts", "name": "API Contracts", "description": "API contract validation page"},
        {"path": "/mode-management", "name": "Mode Management", "description": "System mode management interface"},
        {"path": "/observability", "name": "Observability", "description": "System observability dashboard"},
        {"path": "/unified.html", "name": "Unified Dashboard", "description": "Comprehensive unified interface"},
        {"path": "/main-test", "name": "Main Test", "description": "Testing and validation page"},
        {"path": "/debug-v2", "name": "Debug Dashboard", "description": "Debug and diagnostics interface"},
        {"path": "/simple-fetch-test", "name": "Fetch Test", "description": "API connectivity test"},
        {"path": "/dashboard-state-test", "name": "State Test", "description": "Dashboard state validation"},
    ]
    
    return {
        "pages": pages,
        "total": len(pages)
    }

@router.get("/categories")
async def get_audit_categories():
    """Get available audit categories"""
    categories = [
        {"key": "accessibility", "name": "Accessibility", "description": "WCAG compliance and accessibility checks"},
        {"key": "performance", "name": "Performance", "description": "Page load time and resource optimization"},
        {"key": "responsiveness", "name": "Responsiveness", "description": "Mobile and tablet compatibility"},
        {"key": "functionality", "name": "Functionality", "description": "Feature functionality and broken links"},
        {"key": "consistency", "name": "Consistency", "description": "UI consistency and design standards"},
        {"key": "security", "name": "Security", "description": "Security vulnerabilities and best practices"},
        {"key": "seo", "name": "SEO", "description": "Search engine optimization"},
        {"key": "usability", "name": "Usability", "description": "User experience and usability"}
    ]
    
    return {
        "categories": categories,
        "total": len(categories)
    }

@router.get("/severity-levels")
async def get_severity_levels():
    """Get available severity levels"""
    levels = [
        {"key": "critical", "name": "Critical", "description": "Critical issues that must be fixed immediately"},
        {"key": "error", "name": "Error", "description": "Error issues that should be fixed soon"},
        {"key": "warning", "name": "Warning", "description": "Warning issues that should be addressed"},
        {"key": "info", "name": "Info", "description": "Informational issues for improvement"}
    ]
    
    return {
        "levels": levels,
        "total": len(levels)
    }

@router.get("/summary")
async def get_audit_summary():
    """Get summary of all audit results"""
    if not audit_results:
        return {
            "total_tasks": 0,
            "completed_tasks": 0,
            "failed_tasks": 0,
            "running_tasks": 0,
            "total_issues": 0,
            "critical_issues": 0,
            "error_issues": 0,
            "warning_issues": 0
        }
    
    completed_tasks = 0
    failed_tasks = 0
    running_tasks = 0
    total_issues = 0
    critical_issues = 0
    error_issues = 0
    warning_issues = 0
    
    for result in audit_results.values():
        if result["status"] == "completed":
            completed_tasks += 1
            if "report" in result:
                summary = result["report"]["summary"]
                total_issues += summary["total_issues"]
                critical_issues += summary["critical_issues"]
                error_issues += summary["error_issues"]
                warning_issues += summary["warning_issues"]
        elif result["status"] == "failed":
            failed_tasks += 1
        elif result["status"] == "running":
            running_tasks += 1
    
    return {
        "total_tasks": len(audit_results),
        "completed_tasks": completed_tasks,
        "failed_tasks": failed_tasks,
        "running_tasks": running_tasks,
        "total_issues": total_issues,
        "critical_issues": critical_issues,
        "error_issues": error_issues,
        "warning_issues": warning_issues,
        "avg_issues_per_page": round(total_issues / max(completed_tasks, 1), 1)
    }

@router.get("/health")
async def get_audit_service_health():
    """Get UI audit service health status"""
    try:
        # Check if we can import the auditor
        
        # Test basic functionality
        auditor = UIAuditor(headless=True)
        auditor.cleanup_driver()
        
        return {
            "status": "healthy",
            "service": "ui-audit",
            "version": "1.0.0",
            "features": {
                "comprehensive_audit": True,
                "quick_audit": True,
                "background_tasks": True,
                "export_json": True,
                "export_csv": True,
                "real_time_status": True
            },
            "dependencies": {
                "selenium": True,
                "requests": True,
                "beautifulsoup4": True
            }
        }
        
    except ImportError as e:
        return {
            "status": "unhealthy",
            "service": "ui-audit",
            "error": f"Missing dependency: {e}"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "service": "ui-audit",
            "error": f"Service error: {e}"
        }

@router.post("/export/{task_id}")
async def export_audit_report(task_id: str, format: str = "json"):
    """Export audit report in specified format"""
    if task_id not in audit_results:
        raise HTTPException(status_code=404, detail=f"Audit task {task_id} not found")
    
    result = audit_results[task_id]
    
    if result["status"] != "completed":
        raise HTTPException(status_code=400, detail=f"Audit task {task_id} not completed")
    
    report = result["report"]
    
    if format.lower() == "json":
        return report
    elif format.lower() == "csv":
        # Convert to CSV
        csv_lines = [
            "Page,URL,Status Code,Load Time,Total Issues,Critical Issues,Error Issues,Warning Issues,Quality Score",
            *[f"{page.page},{page.url},{page.status_code},{page.load_time},{page.issue_count},{page.critical_issues},{page.error_issues},{page.warning_issues},{round(100 - (page.issue_count * 10), 1)}" 
              for page in report["pages"]]
        ]
        
        return {
            "filename": f"ui_audit_{task_id}.csv",
            "content": "\n".join(csv_lines),
            "content_type": "text/csv"
        }
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")

@router.get("/config")
async def get_audit_config():
    """Get current audit configuration"""
    return {
        "default_pages": [
            "/",
            "/dashboard",
            "/simple-dashboard",
            "/api-contracts",
            "/mode-management",
            "/observability",
            "/unified.html",
            "/main-test",
            "/debug-v2"
        ],
        "quick_audit_pages": [
            "/",
            "/dashboard",
            "/api-contracts",
            "/mode-management",
            "/observability"
        ],
        "default_settings": {
            "headless": True,
            "timeout": 30,
            "load_time_threshold": 10.0,
            "max_warnings_per_page": 20,
            "quality_score_threshold": 70
        },
        "audit_categories": [
            "accessibility",
            "performance", 
            "responsiveness",
            "functionality",
            "consistency",
            "security",
            "seo",
            "usability"
        ],
        "severity_levels": ["critical", "error", "warning", "info"]
    }

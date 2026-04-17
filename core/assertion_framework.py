"""
MERID Assertion Framework - Core Schema and Client

Production-ready assertion system with templates, versioning, and cross-language support.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Union
from enum import Enum
import json
import threading
import uuid
import time
from datetime import datetime, timezone

# Core Enums
class AssertionStatus(Enum):
    """Lifecycle states for assertions."""
    PENDING = "pending"
    PASSED = "passed"
    FAILED = "failed"
    EXPIRED = "expired"

class AssertionSeverity(Enum):
    """Severity levels for assertion violations."""
    INFO = "info"
    MINOR = "minor"
    MAJOR = "major"
    CRITICAL = "critical"

class AssertionCategory(Enum):
    """High-level categories for assertions."""
    CORE = "core"
    REALITY = "reality"
    RISK = "risk"
    EXECUTION = "execution"
    DATA_QUALITY = "data_quality"
    GOVERNANCE = "governance"
    CI = "ci"
    TEST = "test"
    INFRA = "infra"

class TemplateLifecycle(Enum):
    """Lifecycle states for assertion templates."""
    DRAFT = "draft"
    EXPERIMENTAL = "experimental"
    ENFORCED = "enforced"
    DEPRECATED = "deprecated"
    REMOVED = "removed"

# Core Data Structures
@dataclass
class AssertionTemplate:
    """Template definition for reusable assertions."""
    template_id: str
    version: int
    library_version: str
    description: str
    category: AssertionCategory
    severity_default: AssertionSeverity
    parameters: List[Dict[str, Any]]
    tags: Dict[str, List[str]]
    owner_team: str
    doc_url: Optional[str] = None
    lifecycle: TemplateLifecycle = TemplateLifecycle.DRAFT
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    bindings: Optional[Dict[str, Dict[str, str]]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "template_id": self.template_id,
            "version": self.version,
            "library_version": self.library_version,
            "description": self.description,
            "category": self.category.value,
            "severity_default": self.severity_default.value,
            "parameters": self.parameters,
            "tags": self.tags,
            "owner_team": self.owner_team,
            "doc_url": self.doc_url,
            "lifecycle": self.lifecycle.value,
            "created_at": self.created_at.isoformat(),
            "last_updated": self.last_updated.isoformat(),
            "bindings": self.bindings
        }

@dataclass
class Assertion:
    """Instance of an assertion template with specific parameters."""
    assertion_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    template_id: str = ""
    template_version: int = 1
    status: AssertionStatus = AssertionStatus.PENDING
    severity: AssertionSeverity = AssertionSeverity.MAJOR
    subject: Dict[str, Any] = field(default_factory=dict)
    parameters: Dict[str, Any] = field(default_factory=dict)
    owner_team: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    resolved_at: Optional[float] = None
    resolution_details: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "assertion_id": self.assertion_id,
            "template_id": self.template_id,
            "template_version": self.template_version,
            "status": self.status.value,
            "severity": self.severity.value,
            "subject": self.subject,
            "parameters": self.parameters,
            "owner_team": self.owner_team,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "resolved_at": self.resolved_at,
            "resolution_details": self.resolution_details,
            "extra": self.extra
        }

    def update_status(self, status: AssertionStatus, details: Optional[str] = None):
        """Update assertion status with timestamp."""
        self.status = status
        self.updated_at = time.time()
        if status in [AssertionStatus.PASSED, AssertionStatus.FAILED, AssertionStatus.EXPIRED]:
            self.resolved_at = self.updated_at
            self.resolution_details = details

# Assertion Client Interface
class AssertionClient:
    """Client for registering and updating assertions."""
    
    def __init__(self, registry_url: Optional[str] = None):
        self.registry_url = registry_url or "http://localhost:8000/api/v1/assertions"
        self.templates_cache: Dict[str, AssertionTemplate] = {}
    
    def register_assertion(
        self,
        template_id: str,
        subject: Dict[str, Any],
        parameters: Dict[str, Any],
        severity: Optional[AssertionSeverity] = None,
        owner_team: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None
    ) -> Assertion:
        """Register a new assertion instance."""
        # Get template to determine default severity
        template = self.get_template(template_id)
        
        assertion = Assertion(
            template_id=template_id,
            template_version=template.version,
            severity=severity or template.severity_default,
            subject=subject,
            parameters=parameters,
            owner_team=owner_team or template.owner_team,
            extra=extra or {}
        )
        
        # Send to registry
        self._send_to_registry("register", assertion.to_dict())
        return assertion
    
    def update_assertion_status(
        self,
        assertion_id: str,
        status: AssertionStatus,
        details: Optional[str] = None
    ) -> bool:
        """Update assertion status."""
        payload = {
            "assertion_id": assertion_id,
            "status": status.value,
            "details": details,
            "timestamp": time.time()
        }
        
        result = self._send_to_registry("update", payload)
        return result.get("success", False)
    
    def record(
        self,
        template_id: str,
        parameters: Dict[str, Any],
        status: Union[AssertionStatus, str],
        details: Optional[str] = None,
        subject: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Convenience method for immediate assertion recording."""
        if isinstance(status, str):
            status = AssertionStatus(status)
        
        # Create assertion if not exists, or update if exists
        assertion_id = f"{template_id}_{hash(str(parameters))}"
        
        payload = {
            "assertion_id": assertion_id,
            "template_id": template_id,
            "status": status.value,
            "parameters": parameters,
            "subject": subject or {},
            "details": details,
            "timestamp": time.time()
        }
        
        result = self._send_to_registry("record", payload)
        return result.get("success", False)
    
    def list_assertions(
        self,
        filter_by: Optional[Dict[str, Any]] = None,
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """List assertions with optional filtering."""
        params = {"limit": limit}
        if filter_by:
            params.update(filter_by)
        
        result = self._send_to_registry("list", params)
        return result.get("assertions", [])
    
    def get_template(self, template_id: str) -> AssertionTemplate:
        """Get assertion template from cache or registry."""
        if template_id not in self.templates_cache:
            result = self._send_to_registry("get_template", {"template_id": template_id})
            template_data = result.get("template")
            template = AssertionTemplate(
                template_id=template_data["template_id"],
                version=template_data["version"],
                library_version=template_data["library_version"],
                description=template_data["description"],
                category=AssertionCategory(template_data["category"]),
                severity_default=AssertionSeverity(template_data["severity_default"]),
                parameters=template_data["parameters"],
                tags=template_data["tags"],
                owner_team=template_data["owner_team"],
                doc_url=template_data.get("doc_url"),
                lifecycle=TemplateLifecycle(template_data.get("lifecycle", "draft")),
                bindings=template_data.get("bindings")
            )
            self.templates_cache[template_id] = template
        
        return self.templates_cache[template_id]
    
    def _send_to_registry(self, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Send request to assertion registry."""
        import requests
        
        try:
            if action == "register":
                response = requests.post(f"{self.registry_url}/register", json=payload, timeout=10)
            elif action == "update":
                response = requests.put(f"{self.registry_url}/update", json=payload, timeout=10)
            elif action == "record":
                response = requests.post(f"{self.registry_url}/record", json=payload, timeout=10)
            elif action == "list":
                response = requests.get(f"{self.registry_url}/list", params=payload, timeout=10)
            elif action == "get_template":
                response = requests.get(f"{self.registry_url}/templates/{payload['template_id']}", timeout=10)
            else:
                raise ValueError(f"Unknown action: {action}")
            
            response.raise_for_status()
            return response.json()
            
        except Exception as e:
            # Log error and return failure response
            print(f"Assertion client error: {e}")
            return {"success": False, "error": str(e)}

# Global assertion client instance
_global_client: Optional[AssertionClient] = None
_global_client_lock = threading.Lock()

def get_assertion_client() -> AssertionClient:
    """Get global assertion client instance."""
    global _global_client
    if _global_client is None:
        with _global_client_lock:
            if _global_client is None:
                _global_client = AssertionClient()
    return _global_client

# Language-specific helper functions
def assert_not_null(
    key: str,
    value: Any,
    context: str,
    message: Optional[str] = None,
    severity: Optional[AssertionSeverity] = None
) -> Any:
    """Assert that value is not null/NaN/undefined."""
    import math
    
    is_nullish = (
        value is None or
        (isinstance(value, float) and math.isnan(value)) or
        (isinstance(value, str) and value.lower() in ['null', 'undefined', 'nan'])
    )
    
    client = get_assertion_client()
    status = AssertionStatus.FAILED if is_nullish else AssertionStatus.PASSED
    details = message or f"Null/NaN for key={key} in {context}" if is_nullish else None
    
    client.record(
        template_id="core.nulls.value_must_not_be_null",
        parameters={
            "key": key,
            "context": context,
            "message": message
        },
        status=status,
        details=details,
        subject={"key": key, "context": context}
    )
    
    if is_nullish:
        raise AssertionError(message or f"Null/NaN for key={key} in {context}")
    
    return value

def assert_timeout(
    operation: str,
    duration_ms: float,
    max_duration_ms: float,
    context: str,
    severity: Optional[AssertionSeverity] = None
) -> bool:
    """Assert that operation completed within timeout."""
    exceeded = duration_ms > max_duration_ms
    
    client = get_assertion_client()
    status = AssertionStatus.FAILED if exceeded else AssertionStatus.PASSED
    details = f"Operation {operation} exceeded {max_duration_ms}ms (took {duration_ms:.1f}ms)" if exceeded else None
    
    client.record(
        template_id="ci.timeout.operation_must_complete_within_sla",
        parameters={
            "operation": operation,
            "duration_ms": duration_ms,
            "max_duration_ms": max_duration_ms,
            "context": context
        },
        status=status,
        details=details,
        subject={"operation": operation, "context": context}
    )
    
    return not exceeded

def assert_resource_limits(
    job_name: str,
    cpu_pct: float,
    memory_mb: float,
    max_cpu_pct: float,
    max_memory_mb: float,
    severity: Optional[AssertionSeverity] = None
) -> bool:
    """Assert that job stays within resource limits."""
    cpu_exceeded = cpu_pct > max_cpu_pct
    memory_exceeded = memory_mb > max_memory_mb
    exceeded = cpu_exceeded or memory_exceeded
    
    client = get_assertion_client()
    status = AssertionStatus.FAILED if exceeded else AssertionStatus.PASSED
    
    violations = []
    if cpu_exceeded:
        violations.append(f"CPU {cpu_pct:.1f}% > {max_cpu_pct}%")
    if memory_exceeded:
        violations.append(f"Memory {memory_mb:.1f}MB > {max_memory_mb}MB")
    
    details = f"Resource violations: {', '.join(violations)}" if exceeded else None
    
    client.record(
        template_id="ci.resources.job_resource_usage_within_limits",
        parameters={
            "job_name": job_name,
            "cpu_pct": cpu_pct,
            "memory_mb": memory_mb,
            "max_cpu_pct": max_cpu_pct,
            "max_memory_mb": max_memory_mb
        },
        status=status,
        details=details,
        subject={"job_name": job_name}
    )
    
    return not exceeded

# Template definitions (would normally be loaded from Git/config)
CORE_TEMPLATES = [
    {
        "template_id": "core.nulls.value_must_not_be_null",
        "version": 1,
        "library_version": "1.0.0",
        "description": "Value for key must not be null/NaN/undefined.",
        "category": "core",
        "severity_default": "major",
        "parameters": [
            {"name": "key", "type": "string", "required": True, "description": "Logical key or field name"},
            {"name": "context", "type": "string", "required": True, "description": "Where this value is used"},
            {"name": "message", "type": "string", "required": False, "description": "Optional custom error message"}
        ],
        "tags": {"env": ["dev", "staging", "prod"], "language": ["python", "java", "javascript"]},
        "owner_team": "core",
        "bindings": {
            "python": {"module": "merid_assertions.core", "function": "assert_not_null"},
            "java": {"class": "com.merid.assertions.CoreAssertions", "method": "assertNotNull"},
            "javascript": {"module": "@merid/assertions-core", "function": "assertNotNull"}
        }
    },
    {
        "template_id": "ci.timeout.operation_must_complete_within_sla",
        "version": 1,
        "library_version": "1.0.0",
        "description": "Operation must complete within SLA bounds.",
        "category": "ci",
        "severity_default": "major",
        "parameters": [
            {"name": "operation", "type": "string", "required": True, "description": "Operation name"},
            {"name": "duration_ms", "type": "float", "required": True, "description": "Actual duration in milliseconds"},
            {"name": "max_duration_ms", "type": "float", "required": True, "description": "Maximum allowed duration"},
            {"name": "context", "type": "string", "required": True, "description": "Context (stage, service, etc.)"}
        ],
        "tags": {"env": ["dev", "staging", "prod"], "stage": ["build", "test", "deploy"]},
        "owner_team": "infra"
    },
    {
        "template_id": "ci.resources.job_resource_usage_within_limits",
        "version": 1,
        "library_version": "1.0.0",
        "description": "Job CPU and memory must remain within configured bounds.",
        "category": "ci",
        "severity_default": "major",
        "parameters": [
            {"name": "job_name", "type": "string", "required": True, "description": "Job identifier"},
            {"name": "cpu_pct", "type": "float", "required": True, "description": "CPU usage percentage"},
            {"name": "memory_mb", "type": "float", "required": True, "description": "Memory usage in MB"},
            {"name": "max_cpu_pct", "type": "float", "required": True, "description": "Maximum CPU percentage"},
            {"name": "max_memory_mb", "type": "float", "required": True, "description": "Maximum memory in MB"}
        ],
        "tags": {"env": ["dev", "staging", "prod"], "stage": ["build", "test", "load_test"]},
        "owner_team": "infra"
    }
]

def load_templates_from_config(templates_data: List[Dict[str, Any]]) -> List[AssertionTemplate]:
    """Load assertion templates from configuration data."""
    templates = []
    for template_data in templates_data:
        template = AssertionTemplate(
            template_id=template_data["template_id"],
            version=template_data["version"],
            library_version=template_data["library_version"],
            description=template_data["description"],
            category=AssertionCategory(template_data["category"]),
            severity_default=AssertionSeverity(template_data["severity_default"]),
            parameters=template_data["parameters"],
            tags=template_data["tags"],
            owner_team=template_data["owner_team"],
            doc_url=template_data.get("doc_url"),
            lifecycle=TemplateLifecycle(template_data.get("lifecycle", "draft")),
            bindings=template_data.get("bindings")
        )
        templates.append(template)
    return templates

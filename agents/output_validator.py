"""
MERID LLM Output Validator - Section 5: LLM Output Contracts & Validation

Validates all LLM agent outputs against strict JSON schemas.
Rejects non-conforming outputs and triggers safe-mode/fallback.

Critical Rules:
- NO free-text is ever passed directly to execution
- Non-JSON or schema-invalid output triggers safe-mode
- All outputs are logged to immutable audit trail
"""

from __future__ import annotations
import logging

import json
import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("agents.output_validator")

try:
    import jsonschema
    from jsonschema import Draft202012Validator, ValidationError
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False
    ValidationError = Exception


class ValidationResult(str, Enum):
    """Output validation results."""
    VALID = "valid"
    INVALID_JSON = "invalid_json"
    SCHEMA_MISMATCH = "schema_mismatch"
    MISSING_REQUIRED = "missing_required"
    FORBIDDEN_CONTENT = "forbidden_content"
    CONFIDENCE_TOO_LOW = "confidence_too_low"


class SafeModeAction(str, Enum):
    """Actions to take when validation fails."""
    REJECT = "reject"           # Reject and do nothing
    RETRY = "retry"             # Retry with explicit JSON instruction
    FALLBACK = "fallback"       # Use safe default
    ESCALATE = "escalate"       # Escalate to governance


@dataclass
class OutputValidationError:
    """Detailed validation error."""
    error_type: ValidationResult
    message: str
    path: str = ""
    value: Any = None
    schema_path: str = ""


@dataclass
class OutputValidationResult:
    """Complete validation result."""
    is_valid: bool
    result: ValidationResult
    errors: List[OutputValidationError] = field(default_factory=list)
    parsed_data: Optional[Dict[str, Any]] = None
    raw_output: str = ""
    agent_id: str = ""
    schema_name: str = ""
    timestamp: float = field(default_factory=time.time)
    validation_id: str = field(default_factory=lambda: f"val_{uuid.uuid4().hex[:12]}")
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "validation_id": self.validation_id,
            "is_valid": self.is_valid,
            "result": self.result.value,
            "errors": [{"type": e.error_type.value, "message": e.message, "path": e.path} for e in self.errors],
            "agent_id": self.agent_id,
            "schema_name": self.schema_name,
            "timestamp": self.timestamp,
        }


# ============================================
# OUTPUT SCHEMAS
# ============================================

AGENT_OPINION_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["agent_id", "symbol", "stance", "score", "confidence", "rationale"],
    "properties": {
        "opinion_id": {"type": "string"},
        "agent_id": {"type": "string"},
        "role": {"type": "string"},
        "symbol": {"type": "string", "minLength": 1},
        "venue": {"type": "string"},
        "stance": {
            "type": "string",
            "enum": ["strong_bull", "bull", "neutral", "bear", "strong_bear"]
        },
        "score": {"type": "number", "minimum": -1.0, "maximum": 1.0},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "rationale": {"type": "string", "minLength": 10, "maxLength": 1000},
        "horizon": {"type": "string", "enum": ["short", "medium", "long"]},
        "data_sources": {"type": "array", "items": {"type": "string"}},
        "supporting_data": {"type": "object"},
    },
    "additionalProperties": False,
}

RISK_DECISION_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["decision", "plan_id", "reason"],
    "properties": {
        "decision_id": {"type": "string"},
        "plan_id": {"type": "string"},
        "decision": {
            "type": "string",
            "enum": ["approve", "approve_reduced", "reject", "veto"]
        },
        "approved_size_usd": {"type": "number", "minimum": 0},
        "original_size_usd": {"type": "number", "minimum": 0},
        "reduction_percent": {"type": "number", "minimum": 0, "maximum": 100},
        "reason": {"type": "string", "minLength": 10, "maxLength": 500},
        "risk_score": {"type": "number", "minimum": 0, "maximum": 1},
        "limit_breaches": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "additionalProperties": False,
}

TRADE_PLAN_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["symbol", "direction", "target_size_usd", "confidence"],
    "properties": {
        "plan_id": {"type": "string"},
        "symbol": {"type": "string", "minLength": 1},
        "venue": {"type": "string"},
        "direction": {"type": "string", "enum": ["long", "short", "flat", "reduce"]},
        "target_size_usd": {"type": "number", "minimum": 0},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "entry_preference": {"type": "string", "enum": ["market", "limit", "twap"]},
        "urgency": {"type": "string", "enum": ["low", "normal", "high", "urgent"]},
        "max_slippage_bps": {"type": "number", "minimum": 0, "maximum": 1000},
        "rationale": {"type": "string"},
    },
    "additionalProperties": False,
}

TRADE_EXECUTION_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["plan_id", "order_id", "symbol", "side", "quantity", "price"],
    "properties": {
        "execution_id": {"type": "string"},
        "plan_id": {"type": "string"},
        "order_id": {"type": "string"},
        "symbol": {"type": "string"},
        "venue": {"type": "string"},
        "side": {"type": "string", "enum": ["buy", "sell"]},
        "quantity": {"type": "number", "minimum": 0},
        "price": {"type": "number", "minimum": 0},
        "notional_usd": {"type": "number", "minimum": 0},
        "slippage_bps": {"type": "number"},
        "fees_usd": {"type": "number", "minimum": 0},
        "is_paper": {"type": "boolean"},
    },
    "additionalProperties": False,
}

GOVERNANCE_DECISION_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "required": ["action", "reason"],
    "properties": {
        "decision_id": {"type": "string"},
        "action": {
            "type": "string",
            "enum": ["approve", "reject", "override", "kill_switch", "resume", "escalate"]
        },
        "target_id": {"type": "string"},
        "reason": {"type": "string", "minLength": 10},
        "new_limits": {"type": "object"},
        "effective_until": {"type": "number"},
    },
    "additionalProperties": False,
}

# Schema registry
OUTPUT_SCHEMAS: Dict[str, Dict[str, Any]] = {
    "AgentOpinion": AGENT_OPINION_SCHEMA,
    "RiskDecision": RISK_DECISION_SCHEMA,
    "TradePlan": TRADE_PLAN_SCHEMA,
    "TradeExecution": TRADE_EXECUTION_SCHEMA,
    "GovernanceDecision": GOVERNANCE_DECISION_SCHEMA,
}


# ============================================
# FORBIDDEN PATTERNS
# ============================================

FORBIDDEN_PATTERNS = [
    # Injection attempts
    r"<script.*?>",
    r"javascript:",
    r"eval\s*\(",
    r"exec\s*\(",
    r"__import__",
    r"os\.system",
    r"subprocess",
    # Prompt injection
    r"ignore\s+(previous|above)\s+instructions",
    r"disregard\s+(previous|above)",
    r"new\s+instructions",
    r"override\s+system",
    # Unsafe operations
    r"delete\s+all",
    r"drop\s+table",
    r"rm\s+-rf",
    # Secrets access attempts
    r"api[_-]?key",
    r"secret[_-]?key",
    r"private[_-]?key",
    r"password",
    r"credential",
]

COMPILED_FORBIDDEN = [re.compile(p, re.IGNORECASE) for p in FORBIDDEN_PATTERNS]


# ============================================
# OUTPUT VALIDATOR
# ============================================

class OutputValidator:
    """
    Validates LLM agent outputs against strict schemas.
    
    Key responsibilities:
    1. Parse JSON from LLM output (handle markdown code blocks)
    2. Validate against required schema
    3. Check for forbidden content
    4. Log all validations to audit trail
    5. Trigger safe-mode on failures
    """
    
    _instance: Optional["OutputValidator"] = None
    
    def __init__(self):
        self._schemas = OUTPUT_SCHEMAS.copy()
        self._validators: Dict[str, Any] = {}
        self._validation_history: List[OutputValidationResult] = []
        self._failure_counts: Dict[str, int] = {}  # agent_id -> failure count
        self._safe_mode_agents: set = set()
        self._audit_handlers: List[Callable] = []
        
        # Initialize validators
        if HAS_JSONSCHEMA:
            for name, schema in self._schemas.items():
                self._validators[name] = Draft202012Validator(schema)
        
        logger.info(f"OutputValidator initialized with {len(self._schemas)} schemas")
    
    @classmethod
    def get_instance(cls) -> "OutputValidator":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def register_audit_handler(self, handler: Callable[[OutputValidationResult], None]) -> None:
        """Register handler for audit logging."""
        self._audit_handlers.append(handler)
    
    def add_schema(self, name: str, schema: Dict[str, Any]) -> None:
        """Add or update a schema."""
        self._schemas[name] = schema
        if HAS_JSONSCHEMA:
            self._validators[name] = Draft202012Validator(schema)
    
    def validate(
        self,
        raw_output: str,
        schema_name: str,
        agent_id: str,
        min_confidence: float = 0.0,
    ) -> OutputValidationResult:
        """
        Validate LLM output against schema.
        
        Args:
            raw_output: Raw string output from LLM
            schema_name: Name of schema to validate against
            agent_id: ID of the agent that produced output
            min_confidence: Minimum required confidence score
            
        Returns:
            OutputValidationResult with validation details
        """
        result = OutputValidationResult(
            is_valid=False,
            result=ValidationResult.INVALID_JSON,
            raw_output=raw_output,
            agent_id=agent_id,
            schema_name=schema_name,
        )
        
        # Step 1: Check for forbidden content in raw output
        forbidden_errors = self._check_forbidden_content(raw_output)
        if forbidden_errors:
            result.result = ValidationResult.FORBIDDEN_CONTENT
            result.errors = forbidden_errors
            self._record_validation(result)
            return result
        
        # Step 2: Extract and parse JSON
        parsed_data = self._extract_json(raw_output)
        if parsed_data is None:
            result.result = ValidationResult.INVALID_JSON
            result.errors = [OutputValidationError(
                error_type=ValidationResult.INVALID_JSON,
                message="Could not parse JSON from output",
            )]
            self._record_validation(result)
            return result
        
        result.parsed_data = parsed_data
        
        # Step 3: Validate against schema
        if schema_name not in self._schemas:
            result.result = ValidationResult.SCHEMA_MISMATCH
            result.errors = [OutputValidationError(
                error_type=ValidationResult.SCHEMA_MISMATCH,
                message=f"Unknown schema: {schema_name}",
            )]
            self._record_validation(result)
            return result
        
        schema_errors = self._validate_schema(parsed_data, schema_name)
        if schema_errors:
            result.result = ValidationResult.SCHEMA_MISMATCH
            result.errors = schema_errors
            self._record_validation(result)
            return result
        
        # Step 4: Check confidence if required
        if min_confidence > 0:
            confidence = parsed_data.get("confidence", 1.0)
            if confidence < min_confidence:
                result.result = ValidationResult.CONFIDENCE_TOO_LOW
                result.errors = [OutputValidationError(
                    error_type=ValidationResult.CONFIDENCE_TOO_LOW,
                    message=f"Confidence {confidence} below minimum {min_confidence}",
                    value=confidence,
                )]
                self._record_validation(result)
                return result
        
        # All checks passed
        result.is_valid = True
        result.result = ValidationResult.VALID
        self._record_validation(result)
        
        return result
    
    def _extract_json(self, raw_output: str) -> Optional[Dict[str, Any]]:
        """Extract JSON from LLM output, handling markdown code blocks."""
        # Try direct JSON parse first
        try:
            return json.loads(raw_output.strip())
        except json.JSONDecodeError:
            logger.debug("silent catch in output_validator:380")
        
        # Try extracting from markdown code block
        json_block_pattern = r"```(?:json)?\s*\n?([\s\S]*?)\n?```"
        matches = re.findall(json_block_pattern, raw_output)
        for match in matches:
            try:
                return json.loads(match.strip())
            except json.JSONDecodeError:
                continue
        
        # Try finding JSON object in text
        json_pattern = r"\{[\s\S]*\}"
        matches = re.findall(json_pattern, raw_output)
        for match in matches:
            try:
                return json.loads(match)
            except json.JSONDecodeError:
                continue
        
        return None
    
    def _check_forbidden_content(self, text: str) -> List[OutputValidationError]:
        """Check for forbidden patterns in output."""
        errors = []
        for pattern in COMPILED_FORBIDDEN:
            if pattern.search(text):
                errors.append(OutputValidationError(
                    error_type=ValidationResult.FORBIDDEN_CONTENT,
                    message=f"Forbidden pattern detected: {pattern.pattern}",
                ))
        return errors
    
    def _validate_schema(self, data: Dict[str, Any], schema_name: str) -> List[OutputValidationError]:
        """Validate data against JSON schema."""
        if not HAS_JSONSCHEMA:
            # Basic validation without jsonschema
            schema = self._schemas.get(schema_name, {})
            required = schema.get("required", [])
            errors = []
            for field in required:
                if field not in data:
                    errors.append(OutputValidationError(
                        error_type=ValidationResult.MISSING_REQUIRED,
                        message=f"Missing required field: {field}",
                        path=field,
                    ))
            return errors
        
        validator = self._validators.get(schema_name)
        if not validator:
            return [OutputValidationError(
                error_type=ValidationResult.SCHEMA_MISMATCH,
                message=f"No validator for schema: {schema_name}",
            )]
        
        errors = []
        for error in validator.iter_errors(data):
            path = ".".join(str(p) for p in error.absolute_path)
            errors.append(OutputValidationError(
                error_type=ValidationResult.SCHEMA_MISMATCH,
                message=error.message,
                path=path,
                value=error.instance,
                schema_path=".".join(str(p) for p in error.schema_path),
            ))
        
        return errors
    
    def _record_validation(self, result: OutputValidationResult) -> None:
        """Record validation result."""
        self._validation_history.append(result)
        if len(self._validation_history) > 10000:
            self._validation_history = self._validation_history[-5000:]
        
        # Track failures per agent
        if not result.is_valid:
            self._failure_counts[result.agent_id] = \
                self._failure_counts.get(result.agent_id, 0) + 1
            
            # Check if agent should enter safe mode
            if self._failure_counts[result.agent_id] >= 5:
                self._safe_mode_agents.add(result.agent_id)
                logger.warning(f"Agent {result.agent_id} entered safe mode after repeated failures")
        else:
            # Reset failure count on success
            self._failure_counts[result.agent_id] = 0
        
        # Notify audit handlers
        for handler in self._audit_handlers:
            try:
                handler(result)
            except Exception as e:
                logger.error(f"Audit handler error: {e}")
        
        # Log result
        if result.is_valid:
            logger.debug(f"Validation passed: {result.agent_id} -> {result.schema_name}")
        else:
            logger.warning(
                f"Validation failed: {result.agent_id} -> {result.schema_name}: "
                f"{result.result.value} - {[e.message for e in result.errors[:3]]}"
            )
    
    def is_agent_in_safe_mode(self, agent_id: str) -> bool:
        """Check if agent is in safe mode."""
        return agent_id in self._safe_mode_agents
    
    def reset_agent_safe_mode(self, agent_id: str) -> None:
        """Reset agent from safe mode (requires manual intervention)."""
        self._safe_mode_agents.discard(agent_id)
        self._failure_counts[agent_id] = 0
        logger.info(f"Agent {agent_id} removed from safe mode")
    
    def get_failure_rate(self, agent_id: str, window_seconds: float = 3600) -> float:
        """Get agent's validation failure rate in time window."""
        cutoff = time.time() - window_seconds
        relevant = [r for r in self._validation_history 
                   if r.agent_id == agent_id and r.timestamp >= cutoff]
        
        if not relevant:
            return 0.0
        
        failures = sum(1 for r in relevant if not r.is_valid)
        return failures / len(relevant)
    
    def get_validation_stats(self) -> Dict[str, Any]:
        """Get validation statistics."""
        total = len(self._validation_history)
        valid = sum(1 for r in self._validation_history if r.is_valid)
        
        return {
            "total_validations": total,
            "valid_count": valid,
            "invalid_count": total - valid,
            "success_rate": valid / total if total > 0 else 1.0,
            "agents_in_safe_mode": list(self._safe_mode_agents),
            "failure_counts": dict(self._failure_counts),
        }


def get_output_validator() -> OutputValidator:
    """Get the global output validator instance."""
    return OutputValidator.get_instance()


def validate_agent_output(
    raw_output: str,
    schema_name: str,
    agent_id: str,
    min_confidence: float = 0.0,
) -> Tuple[bool, Optional[Dict[str, Any]], List[str]]:
    """
    Convenience function to validate agent output.
    
    Returns:
        Tuple of (is_valid, parsed_data, error_messages)
    """
    validator = get_output_validator()
    result = validator.validate(raw_output, schema_name, agent_id, min_confidence)
    
    error_messages = [e.message for e in result.errors]
    return result.is_valid, result.parsed_data, error_messages


# ============================================
# RETRY PROMPT
# ============================================

RETRY_JSON_PROMPT = """
Your previous response was not valid JSON or did not match the required schema.

ERRORS:
{errors}

Please respond ONLY with valid JSON matching this schema:
{schema}

Do NOT include any text before or after the JSON.
Do NOT use markdown code blocks.
Just output the raw JSON object.
"""


def get_retry_prompt(result: OutputValidationResult) -> str:
    """Generate retry prompt for failed validation."""
    schema = OUTPUT_SCHEMAS.get(result.schema_name, {})
    errors = "\n".join(f"- {e.message}" for e in result.errors)
    
    return RETRY_JSON_PROMPT.format(
        errors=errors,
        schema=json.dumps(schema, indent=2),
    )

"""
MERID Schema Validator - Phase 14 Contract Freeze

Validates all data structures against canonical JSON schemas.
Ensures no drift in the system's "physics".
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import jsonschema
    from jsonschema import Draft202012Validator, ValidationError
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False
    ValidationError = Exception

from utils.logger import get_logger

logger = get_logger("schemas.validator")

SCHEMA_DIR = Path(__file__).parent / "json"
SCHEMA_VERSION = "1.0.0"


class SchemaRegistry:
    """Registry of all canonical MERID schemas."""
    
    _instance: Optional["SchemaRegistry"] = None
    
    def __init__(self):
        self._schemas: Dict[str, Dict[str, Any]] = {}
        self._validators: Dict[str, Any] = {}
        self._checksums: Dict[str, str] = {}
        self._loaded = False
    
    @classmethod
    def get_instance(cls) -> "SchemaRegistry":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def load_schemas(self) -> None:
        """Load all JSON schemas from disk."""
        if self._loaded:
            return
        
        if not SCHEMA_DIR.exists():
            logger.warning("Schema directory not found: %s", SCHEMA_DIR)
            return
        
        for schema_file in SCHEMA_DIR.glob("*.json"):
            schema_name = schema_file.stem
            try:
                with open(schema_file, "r", encoding="utf-8") as f:
                    schema_content = f.read()
                    schema = json.loads(schema_content)
                
                self._schemas[schema_name] = schema
                self._checksums[schema_name] = hashlib.sha256(
                    schema_content.encode("utf-8")
                ).hexdigest()
                
                if HAS_JSONSCHEMA:
                    self._validators[schema_name] = Draft202012Validator(schema)
                
                logger.info("Loaded schema: %s (checksum: %s...)", 
                           schema_name, self._checksums[schema_name][:16])
            except Exception as e:
                logger.error("Failed to load schema %s: %s", schema_name, e)
        
        self._loaded = True
        logger.info("Schema registry loaded: %d schemas", len(self._schemas))
    
    def get_schema(self, name: str) -> Optional[Dict[str, Any]]:
        """Get a schema by name."""
        self.load_schemas()
        return self._schemas.get(name)
    
    def get_checksum(self, name: str) -> Optional[str]:
        """Get the SHA-256 checksum of a schema."""
        self.load_schemas()
        return self._checksums.get(name)
    
    def get_all_checksums(self) -> Dict[str, str]:
        """Get checksums for all schemas."""
        self.load_schemas()
        return self._checksums.copy()
    
    def validate(self, schema_name: str, data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """
        Validate data against a schema.
        
        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        self.load_schemas()
        
        if not HAS_JSONSCHEMA:
            # T-045: Fail-closed — missing jsonschema means no validation possible
            logger.error("jsonschema not installed — validation BLOCKED (fail-closed). Install: pip install jsonschema>=4.0.0")
            return False, ["jsonschema package not installed — cannot validate"]
        
        validator = self._validators.get(schema_name)
        if not validator:
            return False, [f"Schema not found: {schema_name}"]
        
        errors = []
        for error in validator.iter_errors(data):
            path = ".".join(str(p) for p in error.absolute_path)
            errors.append(f"{path}: {error.message}" if path else error.message)
        
        return len(errors) == 0, errors
    
    def validate_strict(self, schema_name: str, data: Dict[str, Any]) -> None:
        """Validate and raise exception on failure."""
        is_valid, errors = self.validate(schema_name, data)
        if not is_valid:
            raise SchemaValidationError(schema_name, errors)
    
    def get_status(self) -> Dict[str, Any]:
        """Get registry status."""
        self.load_schemas()
        return {
            "version": SCHEMA_VERSION,
            "schemas_loaded": len(self._schemas),
            "schema_names": list(self._schemas.keys()),
            "checksums": self._checksums,
            "jsonschema_available": HAS_JSONSCHEMA,
        }


class SchemaValidationError(Exception):
    """Raised when data fails schema validation."""
    
    def __init__(self, schema_name: str, errors: List[str]):
        self.schema_name = schema_name
        self.errors = errors
        super().__init__(f"Validation failed for {schema_name}: {errors}")


def get_schema_registry() -> SchemaRegistry:
    """Get the global schema registry instance."""
    return SchemaRegistry.get_instance()


def validate_intent_envelope(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate an IntentEnvelope."""
    return get_schema_registry().validate("IntentEnvelope", data)


def validate_consensus_block(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate a ConsensusBlock."""
    return get_schema_registry().validate("ConsensusBlock", data)


def validate_simulation_report(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate a SimulationReport."""
    return get_schema_registry().validate("SimulationReport", data)


def validate_risk_preview(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate a RiskPreview."""
    return get_schema_registry().validate("RiskPreview", data)


def validate_execution_result(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate an ExecutionResult."""
    return get_schema_registry().validate("ExecutionResult", data)


def validate_arbitrage_opportunity(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate an ArbitrageOpportunity."""
    return get_schema_registry().validate("ArbitrageOpportunity", data)


def compute_schema_manifest() -> Dict[str, Any]:
    """
    Compute a manifest of all schemas with their checksums.
    This is used for version control and audit.
    """
    registry = get_schema_registry()
    checksums = registry.get_all_checksums()
    
    combined = "".join(sorted(checksums.values()))
    manifest_hash = hashlib.sha256(combined.encode()).hexdigest()
    
    return {
        "version": SCHEMA_VERSION,
        "manifest_hash": manifest_hash,
        "schemas": checksums,
        "schema_count": len(checksums),
    }

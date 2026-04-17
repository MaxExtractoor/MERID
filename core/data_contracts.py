"""
Data Contracts — formal per-feed schema, freshness SLA, and fallback strategy.

Each DataContract defines:
- feed_id: unique identifier for the data source
- schema: expected fields and their types
- max_age_seconds: freshness SLA (data older than this is stale)
- fallback_strategy: what to do when data is stale or missing
- required_fields: fields that must be present for the data to be valid
- validators: optional callable checks on field values

Readiness Impact: S8-01 (1→2) — formal data contracts per feed.

Usage:
    from core.data_contracts import DataContractRegistry, DataContract
    registry = DataContractRegistry()
    registry.register(DataContract(
        feed_id="binance",
        schema={"price": float, "volume": float, "timestamp": float},
        max_age_seconds=30,
        fallback_strategy="use_cached",
    ))
    result = registry.validate("binance", {"price": 50000, "volume": 1.5, "timestamp": 1234567890})
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Type

from utils.logger import get_logger

logger = get_logger("core.data_contracts")


class FallbackStrategy(str, Enum):
    """What to do when feed data is stale or invalid."""
    USE_CACHED = "use_cached"
    USE_DEFAULT = "use_default"
    PAUSE_INSTRUMENT = "pause_instrument"
    HALT_TRADING = "halt_trading"
    SKIP = "skip"


class ValidationSeverity(str, Enum):
    """Severity of a validation failure."""
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class ValidationResult:
    """Result of validating data against a contract."""
    valid: bool
    feed_id: str
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    checked_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "valid": self.valid,
            "feed_id": self.feed_id,
            "errors": self.errors,
            "warnings": self.warnings,
            "checked_at": self.checked_at,
        }


@dataclass
class FieldSpec:
    """Specification for a single field in a data contract."""
    name: str
    expected_type: Type
    required: bool = True
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    allowed_values: Optional[Set[Any]] = None

    def validate(self, value: Any) -> List[str]:
        """Validate a value against this field spec. Returns list of error strings."""
        errors = []
        if value is None:
            if self.required:
                errors.append(f"Missing required field: {self.name}")
            return errors

        if not isinstance(value, self.expected_type):
            errors.append(
                f"Type mismatch for {self.name}: "
                f"expected {self.expected_type.__name__}, got {type(value).__name__}"
            )
            return errors

        if self.min_value is not None and isinstance(value, (int, float)):
            if value < self.min_value:
                errors.append(f"{self.name}={value} below min {self.min_value}")

        if self.max_value is not None and isinstance(value, (int, float)):
            if value > self.max_value:
                errors.append(f"{self.name}={value} above max {self.max_value}")

        if self.allowed_values is not None and value not in self.allowed_values:
            errors.append(f"{self.name}={value} not in allowed values {self.allowed_values}")

        return errors


@dataclass
class DataContract:
    """Formal contract for a data feed."""
    feed_id: str
    schema: Dict[str, Type]
    max_age_seconds: float = 60.0
    fallback_strategy: FallbackStrategy = FallbackStrategy.USE_CACHED
    required_fields: Set[str] = field(default_factory=set)
    field_specs: List[FieldSpec] = field(default_factory=list)
    description: str = ""
    owner: str = ""
    default_values: Dict[str, Any] = field(default_factory=dict)
    custom_validators: List[Callable[[Dict[str, Any]], List[str]]] = field(
        default_factory=list
    )

    def __post_init__(self):
        if not self.required_fields:
            self.required_fields = set(self.schema.keys())

    def validate(self, data: Dict[str, Any]) -> ValidationResult:
        """Validate data against this contract."""
        errors = []
        warnings = []

        # 1. Check required fields
        for req in self.required_fields:
            if req not in data:
                errors.append(f"Missing required field: {req}")

        # 2. Check schema types
        for field_name, expected_type in self.schema.items():
            if field_name in data and data[field_name] is not None:
                if not isinstance(data[field_name], expected_type):
                    errors.append(
                        f"Type mismatch for {field_name}: "
                        f"expected {expected_type.__name__}, "
                        f"got {type(data[field_name]).__name__}"
                    )

        # 3. Check field specs (range, allowed values)
        for spec in self.field_specs:
            spec_errors = spec.validate(data.get(spec.name))
            errors.extend(spec_errors)

        # 4. Check freshness if timestamp present
        ts = data.get("timestamp")
        if ts is not None and isinstance(ts, (int, float)):
            age = time.time() - ts
            if age > self.max_age_seconds:
                warnings.append(
                    f"Data stale: age={age:.1f}s > max_age={self.max_age_seconds}s"
                )

        # 5. Run custom validators
        for validator in self.custom_validators:
            try:
                custom_errors = validator(data)
                errors.extend(custom_errors)
            except Exception as exc:
                errors.append(f"Custom validator error: {exc}")

        return ValidationResult(
            valid=len(errors) == 0,
            feed_id=self.feed_id,
            errors=errors,
            warnings=warnings,
        )

    def apply_fallback(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply default values for missing fields."""
        result = dict(data)
        for key, default in self.default_values.items():
            if key not in result or result[key] is None:
                result[key] = default
        return result

    def to_dict(self) -> Dict[str, Any]:
        return {
            "feed_id": self.feed_id,
            "schema": {k: v.__name__ for k, v in self.schema.items()},
            "max_age_seconds": self.max_age_seconds,
            "fallback_strategy": self.fallback_strategy.value,
            "required_fields": sorted(self.required_fields),
            "description": self.description,
            "owner": self.owner,
        }


class DataContractRegistry:
    """Registry of all data contracts for the system.

    Provides validation, fallback application, and summary for dashboards.
    """

    def __init__(self):
        self._contracts: Dict[str, DataContract] = {}
        self._validation_history: List[ValidationResult] = []
        self._max_history = 1000

    def register(self, contract: DataContract) -> None:
        """Register a data contract."""
        self._contracts[contract.feed_id] = contract
        logger.info(
            f"DataContract registered: {contract.feed_id} "
            f"(fields={len(contract.schema)}, "
            f"max_age={contract.max_age_seconds}s, "
            f"fallback={contract.fallback_strategy.value})"
        )

    def get(self, feed_id: str) -> Optional[DataContract]:
        """Get a contract by feed_id."""
        return self._contracts.get(feed_id)

    def validate(self, feed_id: str, data: Dict[str, Any]) -> ValidationResult:
        """Validate data against the registered contract for feed_id."""
        contract = self._contracts.get(feed_id)
        if contract is None:
            result = ValidationResult(
                valid=False,
                feed_id=feed_id,
                errors=[f"No contract registered for feed: {feed_id}"],
            )
        else:
            result = contract.validate(data)

        self._validation_history.append(result)
        if len(self._validation_history) > self._max_history:
            self._validation_history = self._validation_history[-self._max_history:]

        return result

    def validate_with_fallback(
        self, feed_id: str, data: Dict[str, Any]
    ) -> tuple:
        """Validate and apply fallback defaults. Returns (result, patched_data)."""
        contract = self._contracts.get(feed_id)
        if contract is None:
            return (
                ValidationResult(
                    valid=False,
                    feed_id=feed_id,
                    errors=[f"No contract registered for feed: {feed_id}"],
                ),
                data,
            )

        patched = contract.apply_fallback(data)
        result = contract.validate(patched)
        self._validation_history.append(result)
        return result, patched

    def list_contracts(self) -> List[Dict[str, Any]]:
        """List all registered contracts."""
        return [c.to_dict() for c in self._contracts.values()]

    def get_recent_failures(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent validation failures."""
        failures = [r for r in self._validation_history if not r.valid]
        return [f.to_dict() for f in failures[-limit:]]

    def get_summary(self) -> Dict[str, Any]:
        """Dashboard summary of contract health."""
        total = len(self._validation_history)
        failures = sum(1 for r in self._validation_history if not r.valid)
        return {
            "total_contracts": len(self._contracts),
            "total_validations": total,
            "total_failures": failures,
            "success_rate": ((total - failures) / total * 100) if total > 0 else 100.0,
            "contracts": self.list_contracts(),
            "recent_failures": self.get_recent_failures(10),
        }


def build_default_contracts() -> DataContractRegistry:
    """Build a registry with default contracts for known feeds."""
    registry = DataContractRegistry()

    registry.register(DataContract(
        feed_id="binance",
        schema={"price": float, "volume": float, "timestamp": float, "symbol": str},
        max_age_seconds=30.0,
        fallback_strategy=FallbackStrategy.USE_CACHED,
        required_fields={"price", "symbol"},
        field_specs=[
            FieldSpec("price", float, min_value=0.0),
            FieldSpec("volume", float, required=False, min_value=0.0),
        ],
        description="Binance spot market data",
        owner="data-team",
    ))

    registry.register(DataContract(
        feed_id="coinbase",
        schema={"price": float, "volume": float, "timestamp": float, "symbol": str},
        max_age_seconds=30.0,
        fallback_strategy=FallbackStrategy.USE_CACHED,
        required_fields={"price", "symbol"},
        field_specs=[
            FieldSpec("price", float, min_value=0.0),
        ],
        description="Coinbase spot market data",
        owner="data-team",
    ))

    registry.register(DataContract(
        feed_id="kalshi",
        schema={
            "yes_ask": float, "yes_bid": float,
            "no_ask": float, "no_bid": float,
            "volume": float, "timestamp": float,
            "ticker": str,
        },
        max_age_seconds=60.0,
        fallback_strategy=FallbackStrategy.PAUSE_INSTRUMENT,
        required_fields={"yes_ask", "yes_bid", "ticker"},
        field_specs=[
            FieldSpec("yes_ask", float, min_value=0.0, max_value=100.0),
            FieldSpec("yes_bid", float, min_value=0.0, max_value=100.0),
            FieldSpec("no_ask", float, required=False, min_value=0.0, max_value=100.0),
            FieldSpec("no_bid", float, required=False, min_value=0.0, max_value=100.0),
        ],
        description="Kalshi prediction market orderbook",
        owner="prediction-team",
    ))

    registry.register(DataContract(
        feed_id="alpaca",
        schema={"price": float, "volume": float, "timestamp": float, "symbol": str},
        max_age_seconds=15.0,
        fallback_strategy=FallbackStrategy.PAUSE_INSTRUMENT,
        required_fields={"price", "symbol"},
        field_specs=[
            FieldSpec("price", float, min_value=0.0),
        ],
        description="Alpaca equity market data",
        owner="equity-team",
    ))

    registry.register(DataContract(
        feed_id="polygon",
        schema={"price": float, "volume": float, "timestamp": float, "symbol": str},
        max_age_seconds=60.0,
        fallback_strategy=FallbackStrategy.USE_CACHED,
        required_fields={"price", "symbol"},
        description="Polygon.io market data (delayed)",
        owner="data-team",
    ))

    return registry


_registry: Optional[DataContractRegistry] = None
_registry_lock = threading.Lock()


def get_data_contract_registry() -> DataContractRegistry:
    """Return the module-level DataContractRegistry singleton."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = build_default_contracts()
    return _registry

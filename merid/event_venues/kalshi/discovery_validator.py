"""DiscoveryValidator — Schema validation and SLA tracking for market discovery.

Implements critical fixes:
- D-001 (HIGH): Schema validation on Kalshi API responses
- D-002 (HIGH): SLA tracking and alerting on catalog refresh latency

Validates:
1. Market schema structure (required fields, data types)
2. Catalog refresh timing and latency
3. Market data freshness and completeness
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field, field_validator, ValidationError

from merid.formulas import AUDIT_SPEC_VERSION, FORMULAS_VERSION, generate_correlation_id
from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.discovery_validator")


# ── Schema Models ────────────────────────────────────────────────────────────


class KalshiMarketSchema(BaseModel):
    """Pydantic schema for Kalshi market objects.

    Validates critical fields from GET /markets API response.
    Prevents corrupt/malformed data from entering the catalog.
    """
    market_id: str = Field(..., min_length=1, max_length=100)
    event_ticker: str = Field(..., min_length=1)
    series_ticker: str
    subtitle: Optional[str] = None
    question: str = Field(..., min_length=1)
    category: Optional[str] = None
    status: str = Field(..., pattern="^(open|closed|settled)$")
    yes_price: Optional[int] = Field(None, ge=0, le=100)
    no_price: Optional[int] = Field(None, ge=0, le=100)
    last_price: Optional[int] = Field(None, ge=0, le=100)
    volume: int = Field(ge=0)
    open_interest: int = Field(ge=0)
    liquidity: Optional[int] = Field(None, ge=0)
    close_time: str  # ISO8601 datetime string
    expiration_time: str  # ISO8601 datetime string
    result: Optional[str] = None

    @field_validator("yes_price", "no_price", "last_price")
    @classmethod
    def validate_price_sum(cls, v, info):
        """Validate that yes_price + no_price is sensible (95-105 range)."""
        # This validator only checks individual price bounds
        # Sum validation happens in post-validation
        return v

    def validate_price_sum_post(self) -> List[str]:
        """Post-validation: check that yes_price + no_price is in [95, 105] range.

        Returns:
            List of validation warnings (empty if valid)
        """
        warnings = []
        if self.yes_price is not None and self.no_price is not None:
            price_sum = self.yes_price + self.no_price
            if not (95 <= price_sum <= 105):
                warnings.append(
                    f"Price sum anomaly: yes={self.yes_price} + no={self.no_price} = {price_sum} (expected 95-105)"
                )
        return warnings


@dataclass
class ValidationResult:
    """Result of market validation."""
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    market_id: Optional[str] = None


@dataclass
class SLAMetrics:
    """SLA tracking metrics for discovery pipeline."""
    refresh_start: float  # monotonic timestamp
    refresh_end: Optional[float] = None
    api_call_latency_ms: Optional[float] = None
    enrichment_latency_ms: Optional[float] = None
    total_latency_ms: Optional[float] = None
    markets_fetched: int = 0
    markets_valid: int = 0
    markets_invalid: int = 0
    validation_errors: List[Tuple[str, List[str]]] = field(default_factory=list)  # (market_id, errors)

    def is_sla_breach(self, max_total_ms: float = 10000) -> bool:
        """Check if total latency exceeds SLA threshold."""
        if self.total_latency_ms is None:
            return False
        return self.total_latency_ms > max_total_ms


# ── Validator ────────────────────────────────────────────────────────────────


class DiscoveryValidator:
    """Validates market discovery data and tracks SLA compliance.

    Usage::
        validator = DiscoveryValidator()

        # Start timing
        sla_metrics = validator.start_sla_tracking()

        # Validate markets
        results = validator.validate_markets(raw_markets)
        valid_markets = [m for m, r in zip(raw_markets, results) if r.valid]

        # Complete timing
        validator.complete_sla_tracking(sla_metrics, api_latency_ms=123, markets_count=len(raw_markets))

        # Check for SLA breach
        if sla_metrics.is_sla_breach():
            logger.error(f"SLA breach: {sla_metrics.total_latency_ms}ms > 10000ms")
    """

    def __init__(
        self,
        *,
        max_refresh_latency_ms: float = 10000,
        enable_price_sum_checks: bool = True,
        log_validation_errors: bool = True,
    ):
        """Initialize validator.

        Args:
            max_refresh_latency_ms: Maximum acceptable refresh latency (default 10s)
            enable_price_sum_checks: Whether to validate yes+no price sums
            log_validation_errors: Whether to log validation errors (vs silent)
        """
        self.max_refresh_latency_ms = max_refresh_latency_ms
        self.enable_price_sum_checks = enable_price_sum_checks
        self.log_validation_errors = log_validation_errors

        # Stats
        self.total_validations = 0
        self.total_valid = 0
        self.total_invalid = 0
        self.total_warnings = 0

    def validate_market(
        self,
        raw_market: Dict[str, Any],
        *,
        correlation_id: Optional[str] = None,
    ) -> ValidationResult:
        """Validate a single market object against schema.

        Args:
            raw_market: Raw market dict from Kalshi API
            correlation_id: Optional correlation ID for end-to-end tracing

        Returns:
            ValidationResult with valid flag and error/warning lists
        """
        corr_id = correlation_id or generate_correlation_id()
        self.total_validations += 1
        market_id = raw_market.get("market_id", "<unknown>")

        logger.debug(
            "[TRACE] stage=DISCOVER action=validate_market market_id=%s "
            "corr_id=%s formulas_ver=%s audit_spec_ver=%s",
            market_id, corr_id, FORMULAS_VERSION, AUDIT_SPEC_VERSION,
        )

        try:
            # Pydantic validation
            validated = KalshiMarketSchema(**raw_market)

            # Post-validation checks
            warnings = []
            if self.enable_price_sum_checks:
                warnings.extend(validated.validate_price_sum_post())

            if warnings and self.log_validation_errors:
                logger.warning(f"Market {market_id} validation warnings: {warnings}")

            self.total_valid += 1
            self.total_warnings += len(warnings)

            logger.debug(
                "[TRACE] stage=DISCOVER action=validate_ok market_id=%s "
                "warnings=%d corr_id=%s",
                market_id, len(warnings), corr_id,
            )

            return ValidationResult(
                valid=True,
                errors=[],
                warnings=warnings,
                market_id=market_id,
            )

        except ValidationError as exc:
            # Pydantic validation failed
            errors = [str(err) for err in exc.errors()]

            if self.log_validation_errors:
                logger.error(f"Market {market_id} validation failed: {errors}")

            logger.debug(
                "[TRACE] stage=DISCOVER action=validate_failed market_id=%s "
                "errors=%d corr_id=%s",
                market_id, len(errors), corr_id,
            )

            self.total_invalid += 1

            return ValidationResult(
                valid=False,
                errors=errors,
                warnings=[],
                market_id=market_id,
            )
        except Exception as exc:
            # Unexpected error
            error_msg = f"Unexpected validation error: {type(exc).__name__}: {exc}"

            if self.log_validation_errors:
                logger.error(f"Market {market_id} validation error: {error_msg}")

            self.total_invalid += 1

            return ValidationResult(
                valid=False,
                errors=[error_msg],
                warnings=[],
                market_id=market_id,
            )

    def validate_markets(
        self,
        raw_markets: List[Dict[str, Any]],
        *,
        correlation_id: Optional[str] = None,
    ) -> List[ValidationResult]:
        """Validate a batch of markets.

        Args:
            raw_markets: List of raw market dicts from Kalshi API
            correlation_id: Optional correlation ID for end-to-end tracing

        Returns:
            List of ValidationResult objects (one per market)
        """
        corr_id = correlation_id or generate_correlation_id()
        logger.debug(
            "[TRACE] stage=DISCOVER action=validate_batch count=%d corr_id=%s "
            "formulas_ver=%s audit_spec_ver=%s",
            len(raw_markets), corr_id, FORMULAS_VERSION, AUDIT_SPEC_VERSION,
        )
        return [self.validate_market(m, correlation_id=corr_id) for m in raw_markets]

    # ── SLA Tracking ─────────────────────────────────────────────────────────

    def start_sla_tracking(self) -> SLAMetrics:
        """Start tracking SLA metrics for a refresh cycle.

        Returns:
            SLAMetrics object to be passed to complete_sla_tracking()
        """
        return SLAMetrics(refresh_start=time.monotonic())

    def complete_sla_tracking(
        self,
        metrics: SLAMetrics,
        *,
        api_latency_ms: Optional[float] = None,
        enrichment_latency_ms: Optional[float] = None,
        markets_count: int = 0,
        validation_results: Optional[List[ValidationResult]] = None,
    ) -> SLAMetrics:
        """Complete SLA tracking and check for breaches.

        Args:
            metrics: SLAMetrics object from start_sla_tracking()
            api_latency_ms: Time spent in API call (milliseconds)
            enrichment_latency_ms: Time spent enriching markets (milliseconds)
            markets_count: Number of markets fetched
            validation_results: Optional list of validation results

        Returns:
            Updated SLAMetrics object with completed data
        """
        metrics.refresh_end = time.monotonic()
        metrics.total_latency_ms = (metrics.refresh_end - metrics.refresh_start) * 1000
        metrics.api_call_latency_ms = api_latency_ms
        metrics.enrichment_latency_ms = enrichment_latency_ms
        metrics.markets_fetched = markets_count

        if validation_results:
            metrics.markets_valid = sum(1 for r in validation_results if r.valid)
            metrics.markets_invalid = sum(1 for r in validation_results if not r.valid)
            metrics.validation_errors = [
                (r.market_id or "<unknown>", r.errors)
                for r in validation_results
                if not r.valid
            ]

        # Check for SLA breach
        if metrics.is_sla_breach(self.max_refresh_latency_ms):
            logger.error(
                f"SLA BREACH: Catalog refresh took {metrics.total_latency_ms:.0f}ms "
                f"(threshold: {self.max_refresh_latency_ms:.0f}ms). "
                f"API={metrics.api_call_latency_ms:.0f}ms, "
                f"Enrichment={metrics.enrichment_latency_ms:.0f}ms"
            )
        else:
            logger.debug(
                f"SLA OK: Catalog refresh took {metrics.total_latency_ms:.0f}ms "
                f"({metrics.markets_valid} valid, {metrics.markets_invalid} invalid)"
            )

        return metrics

    def get_stats(self) -> Dict[str, Any]:
        """Get validation statistics."""
        return {
            "total_validations": self.total_validations,
            "total_valid": self.total_valid,
            "total_invalid": self.total_invalid,
            "total_warnings": self.total_warnings,
            "validation_rate": (
                self.total_valid / self.total_validations
                if self.total_validations > 0
                else 1.0
            ),
        }


# ── Singleton ────────────────────────────────────────────────────────────────

_validator: Optional[DiscoveryValidator] = None


def get_discovery_validator() -> DiscoveryValidator:
    """Get the singleton DiscoveryValidator instance."""
    global _validator
    if _validator is None:
        _validator = DiscoveryValidator()
    return _validator

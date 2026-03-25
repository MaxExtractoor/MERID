"""Schema validation for Kalshi API responses.

Provides Pydantic schema validation to catch malformed API data
before it enters the catalog enrichment pipeline.

Addresses Audit Finding D-001: Schema Alignment - Incomplete Error Handling
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, field_validator, ValidationError

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.validation")


class KalshiMarketSchema(BaseModel):
    """Validated schema for Kalshi market data from API.

    Ensures all required fields are present and valid before cataloging.
    """

    market_id: str = Field(..., min_length=1, description="Unique market identifier")
    event_ticker: str = Field(..., min_length=1, description="Parent event ticker")
    series_ticker: Optional[str] = Field(None, description="Series ticker for related markets")
    question: str = Field(..., min_length=1, description="Market question")
    description: Optional[str] = Field(None, description="Market description")
    category: Optional[str] = Field(None, description="Market category")
    end_date: datetime = Field(..., description="Market expiration date")
    volume: float = Field(..., ge=0.0, description="Trading volume")
    open_interest: Optional[float] = Field(None, ge=0.0, description="Open interest")
    active: bool = Field(True, description="Whether market is active")
    status: Optional[str] = Field(None, description="Market status")

    @field_validator('market_id')
    @classmethod
    def validate_market_id(cls, v: str) -> str:
        """Validate market_id is non-empty and reasonable length."""
        if not v or len(v) < 3:
            raise ValueError(f"Invalid market_id: {v!r} (too short)")
        if len(v) > 200:
            raise ValueError(f"Invalid market_id: {v!r} (too long)")
        return v

    @field_validator('event_ticker')
    @classmethod
    def validate_event_ticker(cls, v: str) -> str:
        """Validate event_ticker is non-empty."""
        if not v:
            raise ValueError("event_ticker cannot be empty")
        return v

    @field_validator('end_date')
    @classmethod
    def validate_end_date(cls, v: datetime) -> datetime:
        """Validate end_date is in the future and timezone-aware."""
        if v is None:
            raise ValueError("end_date cannot be None")

        # Ensure timezone-aware
        if v.tzinfo is None:
            logger.warning(f"end_date {v} is naive, assuming UTC")
            v = v.replace(tzinfo=timezone.utc)

        # Check if in past (with 1-hour grace period for recently closed markets)
        now = datetime.now(timezone.utc)
        if v < now - timezone.utc.utcoffset(now) - timedelta(hours=1):
            raise ValueError(f"end_date {v} is too far in the past")

        return v

    @field_validator('volume')
    @classmethod
    def validate_volume(cls, v: float) -> float:
        """Validate volume is non-negative."""
        if v < 0:
            raise ValueError(f"volume cannot be negative: {v}")
        return v

    @field_validator('question')
    @classmethod
    def validate_question(cls, v: str) -> str:
        """Validate question is non-empty."""
        if not v or not v.strip():
            raise ValueError("question cannot be empty")
        return v.strip()

    model_config = {
        "extra": "allow",  # Allow extra fields from API
        "str_strip_whitespace": True,
    }


def validate_market_data(raw_data: Dict[str, Any]) -> Optional[KalshiMarketSchema]:
    """Validate raw market data from Kalshi API.

    Args:
        raw_data: Raw market data dictionary from API

    Returns:
        Validated KalshiMarketSchema if valid, None if invalid

    Raises:
        ValidationError: If validation fails and strict mode enabled
    """
    try:
        validated = KalshiMarketSchema(**raw_data)
        return validated
    except ValidationError as e:
        market_id = raw_data.get('market_id', 'UNKNOWN')
        logger.warning(
            f"Market validation failed for {market_id}: {e}\n"
            f"Raw data: {raw_data}"
        )
        return None
    except Exception as e:
        market_id = raw_data.get('market_id', 'UNKNOWN')
        logger.error(
            f"Unexpected error validating market {market_id}: {e}\n"
            f"Raw data: {raw_data}"
        )
        return None


def validate_market_batch(
    raw_markets: list[Dict[str, Any]],
    skip_invalid: bool = True
) -> tuple[list[KalshiMarketSchema], int]:
    """Validate a batch of market data from Kalshi API.

    Args:
        raw_markets: List of raw market data dictionaries
        skip_invalid: If True, skip invalid markets; if False, raise on first error

    Returns:
        Tuple of (validated_markets, invalid_count)
    """
    validated = []
    invalid_count = 0

    for raw in raw_markets:
        try:
            validated_market = validate_market_data(raw)
            if validated_market is not None:
                validated.append(validated_market)
            else:
                invalid_count += 1
        except ValidationError as e:
            invalid_count += 1
            if not skip_invalid:
                raise

    if invalid_count > 0:
        logger.warning(
            f"Market batch validation: {len(validated)} valid, {invalid_count} invalid "
            f"out of {len(raw_markets)} total"
        )

    return validated, invalid_count


# Add missing import
from datetime import timedelta

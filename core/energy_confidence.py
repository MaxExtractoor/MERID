"""Energy confidence shaping based on source reliability (Stage 6)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.source_health import get_source_registry


@dataclass
class EnergyConfidence:
    """Confidence metadata for an Energy object."""

    confidence_base: float  # Original agent-computed confidence
    source: str  # API source name
    source_srw: float  # Source Reliability Weight at creation time
    fallback_used: bool  # Whether fallback data was used
    api_failed: bool  # Whether API call failed entirely
    confidence_final: float  # Final shaped confidence

    @classmethod
    def compute(
        cls,
        confidence_base: float,
        source: str,
        fallback_used: bool = False,
        api_failed: bool = False,
    ) -> EnergyConfidence:
        """
        Compute final confidence using Stage 6 shaping rules:
        
        confidence_final = confidence_base × source_srw
        
        If fallback was used:
            confidence_final *= 0.85
        
        If API failed entirely:
            confidence_final = confidence_base × 0.25
        """
        registry = get_source_registry()
        source_srw = registry.get_srw(source)

        if api_failed:
            confidence_final = confidence_base * 0.25
        else:
            confidence_final = confidence_base * source_srw
            if fallback_used:
                confidence_final *= 0.85

        # Clamp to [0, 1]
        confidence_final = min(max(confidence_final, 0.0), 1.0)

        return cls(
            confidence_base=confidence_base,
            source=source,
            source_srw=source_srw,
            fallback_used=fallback_used,
            api_failed=api_failed,
            confidence_final=confidence_final,
        )

    def to_dict(self) -> dict:
        """Serialize for storage/API."""
        return {
            "confidence_base": round(self.confidence_base, 4),
            "source": self.source,
            "source_srw": round(self.source_srw, 4),
            "fallback_used": self.fallback_used,
            "api_failed": self.api_failed,
            "confidence_final": round(self.confidence_final, 4),
        }

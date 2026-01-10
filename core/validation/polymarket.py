from __future__ import annotations

# Stage 4 Validation: Polymarket resolution checks.

import httpx

from core.validation.base import BaseValidator, ValidatorVerdict


class PolymarketValidator(BaseValidator):
    name = "polymarket"
    weight = 1.0
    API_BASE = "https://clob.polymarket.com"

    async def validate(self, energy, vote_result) -> ValidatorVerdict:
        metadata = energy.get("metadata") or {}
        market_id = metadata.get("polymarket_market_id")
        expected_outcome = metadata.get("polymarket_expected_outcome")

        if not market_id:
            return self.pending("No Polymarket market_id provided on energy.")

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(f"{self.API_BASE}/markets/{market_id}")
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:  # pragma: no cover - network best-effort
            return self.error(f"Polymarket lookup failed: {exc}")

        resolution = str(payload.get("status") or payload.get("resolution") or "").lower()
        winning = str(payload.get("winning_outcome") or payload.get("outcome") or "").lower()

        if resolution not in {"resolved", "closed", "finalized"}:
            return self.pending(
                f"Market unresolved on Polymarket (status={resolution or 'open'}).",
                evidence={"market_id": market_id, "status": resolution or "open"},
            )

        if not winning:
            return self.pending(
                "Polymarket market resolved but no winning outcome published.",
                evidence={"market_id": market_id},
            )

        if expected_outcome:
            expected = str(expected_outcome).lower()
            if winning == expected:
                return self.success(
                    f"Polymarket outcome matched expectation ({winning}).",
                    evidence={"market_id": market_id, "outcome": winning},
                )
            return self.failure(
                f"Polymarket outcome mismatch (expected {expected}, got {winning}).",
                evidence={"market_id": market_id, "outcome": winning, "expected": expected},
            )

        # If no expectation recorded, treat resolution itself as confirmation.
        return self.success(
            "Polymarket market resolved; no expected outcome specified.",
            evidence={"market_id": market_id, "outcome": winning},
        )

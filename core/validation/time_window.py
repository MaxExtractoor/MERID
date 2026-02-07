from __future__ import annotations

# Stage 4 Validation: time-window outcomes (prediction vs actual data over horizon).

from datetime import datetime, timedelta
from typing import Dict

from core.validation.base import BaseValidator, ValidatorVerdict


class TimeWindowValidator(BaseValidator):
    name = "time_window"
    weight = 0.8

    async def validate(self, energy: Dict[str, any], vote_result: Dict[str, any]) -> ValidatorVerdict:
        metadata = energy.get("metadata") or {}
        window_hours = metadata.get("validation_window_hours")
        issued_at = metadata.get("issued_at") or energy.get("timestamp", {}).get("utc_iso")

        if not window_hours or not issued_at:
            return self.pending("Missing validation window parameters.")

        try:
            issued_dt = datetime.fromisoformat(issued_at.replace("Z", ""))
        except ValueError:
            return self.error(f"Invalid issued_at timestamp: {issued_at}")

        deadline = issued_dt + timedelta(hours=float(window_hours))
        now = datetime.utcnow()

        if now < deadline:
            remaining = (deadline - now).total_seconds() / 3600
            return self.pending(f"Awaiting window completion ({remaining:.1f}h remaining).")

        result = metadata.get("validation_outcome")
        if result == "confirmed":
            return self.success("Time-window validation reported as confirmed.")
        if result == "failed":
            return self.failure("Time-window validation reported as failed.")

        return self.pending("Window elapsed but no validation outcome submitted yet.")

from __future__ import annotations

# Stage 4 Validation: on-chain (price) confirmation using public market data.

import asyncio
from typing import Dict

import httpx

from core.validation.base import BaseValidator, ValidatorVerdict


class OnChainPriceValidator(BaseValidator):
    name = "onchain_price"
    weight = 0.9
    _endpoint = "https://api.coingecko.com/api/v3/simple/price"

    async def validate(self, energy: Dict[str, any], vote_result: Dict[str, any]) -> ValidatorVerdict:
        metadata = energy.get("metadata") or {}
        asset = (metadata.get("asset_id") or metadata.get("coingecko_id") or "").lower()
        direction = (metadata.get("target_direction") or "").lower()
        target_price = metadata.get("target_price")

        if not asset or target_price is None:
            return self.pending("No asset_id / target_price metadata; skipping on-chain validation.")

        params = {"ids": asset, "vs_currencies": "usd"}
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.get(self._endpoint, params=params)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:  # pragma: no cover - remote call
            return self.error(f"CoinGecko lookup failed: {exc}")

        price_entry = payload.get(asset)
        if not price_entry:
            return self.error(f"Asset '{asset}' missing in CoinGecko response.")
        current_price = float(price_entry.get("usd", 0.0))

        if not direction:
            # Validate absolute target within tolerance.
            if abs(current_price - float(target_price)) <= metadata.get("target_tolerance", 0.01) * float(target_price):
                return self.success(
                    "On-chain price reached target.",
                    evidence={"asset": asset, "price": current_price, "target": target_price},
                )
            return self.pending(
                "Waiting for price to reach target.",
                evidence={"asset": asset, "price": current_price, "target": target_price},
            )

        if direction == "above":
            if current_price >= float(target_price):
                return self.success(
                    "Price moved above threshold.",
                    evidence={"asset": asset, "price": current_price, "target": target_price},
                )
            return self.pending(
                "Price not yet above threshold.",
                evidence={"asset": asset, "price": current_price, "target": target_price},
            )

        if direction == "below":
            if current_price <= float(target_price):
                return self.success(
                    "Price moved below threshold.",
                    evidence={"asset": asset, "price": current_price, "target": target_price},
                )
            return self.pending(
                "Price not yet below threshold.",
                evidence={"asset": asset, "price": current_price, "target": target_price},
            )

        return self.pending("Unknown direction; awaiting manual validator review.", evidence={"direction": direction})

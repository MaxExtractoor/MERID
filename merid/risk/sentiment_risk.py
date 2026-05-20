"""Per-asset notional caps for sentiment-tagged orders (decision_trace_id + sentiment_driven)."""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from utils.logger import get_logger

logger = get_logger("merid.risk.sentiment_risk")


def _sentiment_cap_usd_for_asset(_asset: str) -> float:
    """Max open notional (USD) for sentiment flow per asset."""
    try:
        from merid.settings import settings

        frac = float(settings.MERID_SENTIMENT_PER_ASSET_CAP_FRACTION)
    except Exception:
        frac = 0.25
    try:
        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk

        cat = get_kalshi_risk()._config.category_limits.get("crypto")
        base = float(cat.max_notional_usd) if cat else 5000.0
    except Exception:
        base = 5000.0
    # Split crypto bucket across five primary assets unless overridden later
    return max(100.0, base * frac / 5.0)


def sentiment_tagged_notional_usd(asset: str) -> float:
    """Sum fill notionals that carry a decision_trace_id for *asset*."""
    try:
        from merid.event_venues.kalshi.fills_ledger import get_fills_ledger

        ledger = get_fills_ledger()
        fills = ledger.get_fills()
    except Exception:
        return 0.0
    au = asset.upper()
    total = Decimal("0")
    for f in fills:
        tid = getattr(f, "decision_trace_id", None) or (
            (f.raw_payload or {}).get("decision_trace_id") if getattr(f, "raw_payload", None) else None
        )
        if not tid:
            continue
        if f.resolved_asset() != au:
            continue
        total += f.notional_usd
    return float(total)


def _asset_from_intent(intent) -> Optional[str]:
    sa = getattr(intent, "sentiment_asset", None)
    if sa:
        return str(sa).upper()
    try:
        from config.kalshi_crypto_config import kalshi_ticker_to_asset

        return kalshi_ticker_to_asset(getattr(intent, "ticker", "") or "") or None
    except Exception:
        return None


# SENTIMENT DECOUPLING (2026-05-14): Removed sentiment_order_rejection_reason function.
# Sentiment should not gate trading via notional caps.

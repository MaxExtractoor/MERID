"""Kalshi market shape normalization and guardrails."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Literal, Optional, TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from merid.event_venues.base import EventMarket
    from merid.event_venues.kalshi.market_catalog import CatalogMarket
else:
    EventMarket = Any
    CatalogMarket = Any

# ── Canonical market shape ──────────────────────────────────────────────────


@dataclass
class KalshiMarketShape:
    """Canonical representation of a Kalshi crypto market."""

    asset: Optional[str]
    timeframe_label: Optional[str]
    expiry_ts: Optional[datetime]
    market_type: Literal["UP_DOWN", "THRESHOLD_LEQ", "THRESHOLD_GEQ"]
    strike: Optional[float]
    yes_price: Optional[float]
    no_price: Optional[float]
    series_ticker: Optional[str]
    event_ticker: Optional[str] = None
    title: Optional[str] = None


@dataclass
class MoveBandsConfig:
    """Max absolute move allowed by timeframe."""

    max_abs_move_15m: float = 0.02
    max_abs_move_1h: float = 0.04
    max_abs_move_1d: float = 0.10
    max_abs_move_long: float = 0.15

    def max_move_for_minutes(self, minutes: Optional[float]) -> float:
        if minutes is None:
            return self.max_abs_move_long
        if minutes <= 30:
            return self.max_abs_move_15m
        if minutes <= 90:
            return self.max_abs_move_1h
        if minutes <= 60 * 24:
            return self.max_abs_move_1d
        return self.max_abs_move_long


@dataclass
class EdgeThresholdConfig:
    """Configurable probability/edge thresholds."""

    min_true_win_prob: Decimal = Decimal("0.55")
    min_net_edge_bps_by_price_band: Dict[str, Decimal] = field(
        default_factory=lambda: {
            "wing": Decimal("80"),   # deep OTM or ITM requires larger edge
            "mid": Decimal("60"),    # 30–70c
            "at": Decimal("50"),     # around 50c
        }
    )
    kelly_cap: Decimal = Decimal("0.20")

    def threshold_for_price(self, price_cents: Optional[int]) -> Decimal:
        if price_cents is None:
            return self.min_net_edge_bps_by_price_band.get("mid", Decimal("60"))
        p = Decimal(price_cents) / Decimal("100")
        if p <= Decimal("0.30") or p >= Decimal("0.70"):
            return self.min_net_edge_bps_by_price_band.get("wing", Decimal("80"))
        if Decimal("0.45") <= p <= Decimal("0.55"):
            return self.min_net_edge_bps_by_price_band.get("at", Decimal("50"))
        return self.min_net_edge_bps_by_price_band.get("mid", Decimal("60"))


@dataclass
class GeometryDecision:
    """Geometry sanity result for a market."""

    allow_yes: bool
    allow_no: bool
    required_move: Optional[float]
    max_allowed: Optional[float]
    time_to_expiry_min: Optional[float]
    reason_yes: Optional[str] = None
    reason_no: Optional[str] = None


# ── Helpers ────────────────────────────────────────────────────────────────

_LEQ_PAT = re.compile(r"(at\s+or\s+)?below|≤|less\s+than|or\s+lower", re.I)
_GEQ_PAT = re.compile(r"(at\s+or\s+)?above|≥|greater\s+than|or\s+higher|over", re.I)
_UPDOWN_PAT = re.compile(r"up\s*/?\s*down|up or down", re.I)
_STRIKE_PAT = re.compile(r"([\d,]+\.?\d*)")


def _extract_strike(text: str) -> Optional[float]:
    match = _STRIKE_PAT.search(text.replace("$", ""))
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def classify_market_shape(
    market: EventMarket,
    catalog_market: Optional[CatalogMarket],
    now: Optional[datetime] = None,
) -> KalshiMarketShape:
    """Build a canonical market shape from EventMarket + catalog data."""

    text = f"{market.question or ''} {market.description or ''}".strip()
    market_type: Literal["UP_DOWN", "THRESHOLD_LEQ", "THRESHOLD_GEQ"]

    if _UPDOWN_PAT.search(text):
        market_type = "UP_DOWN"
    elif _LEQ_PAT.search(text):
        market_type = "THRESHOLD_LEQ"
    elif _GEQ_PAT.search(text):
        market_type = "THRESHOLD_GEQ"
    else:
        # Default: if a strike exists assume ≥, otherwise treat as up/down
        market_type = "THRESHOLD_GEQ" if (catalog_market and catalog_market.strike_price) or _STRIKE_PAT.search(text) else "UP_DOWN"

    strike = None
    # Prefer catalog strike tagging
    if catalog_market and catalog_market.strike_price is not None:
        strike = catalog_market.strike_price
    elif catalog_market and catalog_market.floor_strike is not None:
        strike = catalog_market.floor_strike
    if strike is None:
        strike = _extract_strike(text)

    yes_price = None
    no_price = None
    for o in market.outcomes:
        if o.outcome_id == "yes":
            yes_price = float(o.price * 100)
        elif o.outcome_id == "no":
            no_price = float(o.price * 100)

    expiry = market.end_date
    timeframe_label = None
    if catalog_market and catalog_market.timeframe:
        timeframe_label = catalog_market.timeframe.upper()
    elif expiry and now:
        minutes = max((expiry - now).total_seconds() / 60.0, 0)
        if minutes <= 30:
            timeframe_label = "15M"
        elif minutes <= 90:
            timeframe_label = "1H"
        elif minutes <= 60 * 24:
            timeframe_label = "1D"
        else:
            timeframe_label = "LONG"

    return KalshiMarketShape(
        asset=catalog_market.asset if catalog_market else None,
        timeframe_label=timeframe_label,
        expiry_ts=expiry,
        market_type=market_type,
        strike=strike,
        yes_price=yes_price,
        no_price=no_price,
        series_ticker=catalog_market.series_ticker if catalog_market else None,
        event_ticker=catalog_market.event_ticker if catalog_market else None,
        title=market.question,
    )


def evaluate_geometry(
    shape: KalshiMarketShape,
    spot: Optional[float],
    move_bands: MoveBandsConfig,
    now: Optional[datetime] = None,
) -> GeometryDecision:
    """Return geometry sanity decision."""
    expiry = shape.expiry_ts
    time_to_expiry_min = None
    if expiry and now:
        time_to_expiry_min = max((expiry - now).total_seconds() / 60.0, 0)

    if shape.market_type == "UP_DOWN" or shape.strike is None or spot is None:
        return GeometryDecision(
            allow_yes=True,
            allow_no=True,
            required_move=None,
            max_allowed=None,
            time_to_expiry_min=time_to_expiry_min,
        )

    required_move = (shape.strike - spot) / spot
    abs_move = abs(required_move)
    max_allowed = move_bands.max_move_for_minutes(time_to_expiry_min)

    allow_yes = abs_move <= max_allowed
    allow_no = True  # Fading catastrophic strikes is allowed; edge filters still apply

    reason_yes = None
    if not allow_yes:
        reason_yes = (
            f"REJECT_GEOMETRY required_move={required_move:.4f} "
            f"abs={abs_move:.4f} max={max_allowed:.4f} tte_min={time_to_expiry_min}"
        )

    return GeometryDecision(
        allow_yes=allow_yes,
        allow_no=allow_no,
        required_move=required_move,
        max_allowed=max_allowed,
        time_to_expiry_min=time_to_expiry_min,
        reason_yes=reason_yes,
        reason_no=None,
    )


def geometry_reason(decision: GeometryDecision, side: str) -> Optional[str]:
    if side == "yes":
        return decision.reason_yes
    return decision.reason_no

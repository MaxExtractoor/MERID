"""Real-time position cache updated from WebSocket fill events.

Reduces latency from 5-30s (REST polling) to <1s (WS event-driven).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time as _time
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from merid.data.ingress_replay import replay_start_time, replay_time
from utils.logger import get_logger

try:
    from merid.position_management.position import PositionKey
    POSITION_KEY_AVAILABLE = True
except Exception as _pk_import_err:
    POSITION_KEY_AVAILABLE = False

if TYPE_CHECKING:
    from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger

try:
    from merid.position_management.entry_provenance import (
        EntryProvenanceSnapshot,
        ProvenanceState,
        get_entry_provenance_store,
    )
    ENTRY_PROVENANCE_AVAILABLE = True
except Exception as _ep_import_err:
    ENTRY_PROVENANCE_AVAILABLE = False

logger = get_logger("merid.event_venues.kalshi.position_cache")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (ValueError, TypeError):
        return default


def _price_to_cents(value: Any) -> Optional[int]:
    """Convert a price value (int/float/Decimal/string) to integer cents."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        try:
            return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        except Exception:
            return None
    if isinstance(value, Decimal):
        try:
            return int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        except Exception:
            return None
    if isinstance(value, str):
        try:
            d = Decimal(value)
            if 1 <= d <= 100:
                return int(d.to_integral_value(rounding=ROUND_HALF_UP))
            return int((d * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        except Exception:
            return None
    return None


def _fill_position_side_price_cents(fill: Any, side: str) -> Optional[int]:
    """Return the price for ``side`` from a fill's stored leg prices.

    Prefers the explicit ``yes_price_dollars`` / ``no_price_dollars`` fields,
    then ``canonical_leg_price_cents`` / ``price_cents`` only when the fill's
    canonical side matches the requested side.  Never synthesizes a missing
    leg price via 100 - other_side.
    """
    side = (side or "").lower()
    if side not in ("yes", "no"):
        return None

    yes_cents = _price_to_cents(getattr(fill, "yes_price_dollars", None))
    no_cents = _price_to_cents(getattr(fill, "no_price_dollars", None))

    if side == "yes" and yes_cents is not None:
        return yes_cents
    if side == "no" and no_cents is not None:
        return no_cents

    can_side = getattr(fill, "canonical_position_side", None) or getattr(fill, "side", None)
    if can_side and can_side.lower() == side:
        canon = getattr(fill, "canonical_leg_price_cents", None)
        if canon is not None:
            return int(canon)
        prop = getattr(fill, "price_cents", None)
        if prop is not None:
            try:
                return int(prop)
            except Exception:
                return None
    return None


# Maximum age (seconds) of the last orderbook snapshot that can be used as a
# near-pre-fill fallback when a contemporaneous (AT_FILL) book cannot be
# captured.  A stale-but-recent book is tagged AT_FILL_OR_NEAREST_PRE_FILL so
# spread-stop invariants can still arm rather than leaving the position unprotected.
MERID_ENTRY_BOOK_NEAR_PRE_FILL_MAX_AGE_S = _env_int("MERID_ENTRY_BOOK_NEAR_PRE_FILL_MAX_AGE_S", 30)


try:
    from merid.event_venues.kalshi.binary_price_space import (
        canonical_outcome_side,
        yes_delta,
        to_signed_yes_exposure,
        from_signed_yes_exposure,
        fill_to_signed_yes_exposure,
        normalize_rest_position,
        require_canonical_outcome_side,
        PositionDataError,
        SideValidationError,
    )
    BINARY_PRICE_SPACE_AVAILABLE = True
except ImportError:
    BINARY_PRICE_SPACE_AVAILABLE = False


class SideValidationErrorLocal(Exception):
    pass


def _infer_side_from_signed_size(pos: Dict[str, Any]) -> Optional[str]:
    """Infer outcome side from a signed position size (positive=YES, negative=NO).

    Only ``position_fp`` or ``signed_size`` are trustworthy here.  ``contracts``
    and other unsigned size fields are never used to infer direction.
    """
    for key in ("position_fp", "signed_size"):
        raw = pos.get(key)
        if raw is None:
            continue
        try:
            value = Decimal(str(raw))
        except Exception:
            continue
        if value > 0:
            return "yes"
        if value < 0:
            return "no"
    return None


def _extract_canonical_rest_side(pos: Dict[str, Any], market_id: str) -> Optional[str]:
    """Return a validated yes/no side from a REST position dict or None.

    Tries ``outcome_id`` first (Kalshi's canonical outcome field), then
    ``outcome_side``, ``side``, and ``kalshi_side``.  Unrecognised or missing
    values return ``None`` rather than silently defaulting to YES.
    """
    for key in ("outcome_id", "outcome_side", "side", "kalshi_side"):
        raw = pos.get(key)
        if raw is None:
            continue
        try:
            return canonical_outcome_side(raw).value
        except PositionDataError:
            # Non-side value in this field (e.g. book_side='ask') is ignored.
            continue
    return None


def _require_outcome_side_for_position(
    pos: Dict[str, Any],
    market_id: str,
) -> str:
    """Parse REST position side fields, raising on missing/inconsistent sides.

    If no textual side field is present, falls back to the signed position size
    (``position_fp`` / ``signed_size``) so REST positions from venues that omit
    the ``outcome_side`` key are not quarantined.
    """
    if BINARY_PRICE_SPACE_AVAILABLE:
        try:
            return require_canonical_outcome_side(
                pos,
                context=f"position_cache ticker={market_id}",
            ).value
        except PositionDataError as exc:
            raise SideValidationErrorLocal(str(exc)) from exc

    # Defensive fallback if binary_price_space is somehow unavailable.
    for key in ("outcome_side", "outcome_id", "side", "kalshi_side"):
        raw = pos.get(key)
        if raw is None:
            continue
        normalized = str(raw).strip().lower()
        if normalized in ("yes", "no"):
            # Validate against signed size if available.
            signed = _infer_side_from_signed_size(pos)
            if signed is not None and signed != normalized:
                raise SideValidationErrorLocal(
                    f"position_cache ticker={market_id}: side={normalized} conflicts with signed size"
                )
            return normalized
        raise SideValidationErrorLocal(f"position_cache ticker={market_id}: invalid side={raw!r}")

    side = _infer_side_from_signed_size(pos)
    if side is not None:
        return side

    raise SideValidationErrorLocal(f"position_cache ticker={market_id}: missing side")


def _is_test_ticker(ticker: str) -> bool:
    """Check if a ticker is a test market ticker.

    Test tickers are identified by patterns like:
    - Contains "TEST" or "KXTEST"
    - Short codes like "KX-SK", "KX-DUP", "KX-TK"

    NOTE: Crypto series tickers (KXBTC-15M, KXETH-D, etc.) are NOT test tickers - they are real trading markets.

    Args:
        ticker: The market ticker to check

    Returns:
        True if the ticker is a test market, False otherwise
    """
    if not ticker:
        return False

    ticker_upper = ticker.upper()

    # Explicit test markers
    if "TEST" in ticker_upper or "KXTEST" in ticker_upper:
        return True

    # Short codes (test development tickers)
    if ticker_upper.startswith("KX-") and len(ticker_upper) <= 6:
        return True

    return False


def _is_expired_ticker(ticker: str) -> bool:
    """Check if a ticker has expired and should not carry a cached position.

    A market is considered expired only when:
      - the position cache has been explicitly told it settled, or
      - the catalog reports it as ``settled``/``finalized``, or
      - the close time is older than ``MERID_POSITION_EXPIRY_GRACE_SECONDS``.

    ``closed`` status alone is NOT enough; the position remains an unresolved
    financial exposure until settlement/finalization or the configured grace.
    """
    if not ticker:
        return False

    from datetime import datetime, timezone, timedelta

    # Explicit settlement or quarantine notification from the position cache.
    try:
        from merid.event_venues.kalshi.position_cache import get_position_cache

        cache = get_position_cache()
        if cache is not None:
            if cache.is_settled(ticker):
                return True
            if cache.is_quarantined(ticker):
                return True
    except Exception:
        pass

    grace_seconds = _env_int("MERID_POSITION_EXPIRY_GRACE_SECONDS", 900)
    expiry_buffer = timedelta(seconds=grace_seconds)

    try:
        from merid.event_venues.kalshi.expiry_fallback import parse_kalshi_15m_ticker_expiry
        expiry_dt, is_15m_pattern = parse_kalshi_15m_ticker_expiry(ticker)
        if expiry_dt is not None:
            now = datetime.now(timezone.utc)
            # If the only parseable interpretation is many years in the future,
            # the canonical year-first parser has been tripped by a day-first body
            # with an invalid date (e.g. 30FEB).  Treat as expired/invalid.
            # Threshold is set well beyond any real 15m market horizon so that
            # test fixtures with deliberate far-future dates are not expired.
            if expiry_dt > now + timedelta(days=3650):
                logger.warning(
                    "[EXPIRED-TICKER] %s parsed as implausibly far future %s; treating as expired",
                    ticker,
                    expiry_dt,
                )
                return True
            return expiry_dt < (now - expiry_buffer)

        # 15m contract with an unparseable/invalid date segment -> expired
        if is_15m_pattern:
            return True
    except Exception as e:
        logger.debug("[EXPIRED-TICKER] Exception parsing ticker %s: %s", ticker, e)
        if "15M" in ticker.upper():
            return True

    # Fallback: catalog status/close_time when available
    try:
        from merid.event_venues.kalshi.market_catalog import get_market_catalog
        catalog = get_market_catalog()
        if not catalog:
            return False

        market = catalog.get_market(ticker)
        if not market:
            return False

        status = getattr(market, "status", "").lower()
        if status in ("settled", "finalized"):
            return True

        if status == "closed":
            # Closed-but-unsettled markets remain in the financial ledger.
            close_time = getattr(market, "close_time", None)
            if close_time:
                return close_time < (datetime.now(timezone.utc) - expiry_buffer)
            return False

        if hasattr(market, 'close_time') and market.close_time:
            return market.close_time < (datetime.now(timezone.utc) - expiry_buffer)
    except Exception as e:
        logger.debug("[EXPIRED-TICKER] Exception checking catalog for %s: %s", ticker, e)

    return False


def _get_market_price_fallback(ticker: str) -> int:
    """Get market price from KalshiMarketStateStore as fallback for avg_price_cents.

    Used when REST API doesn't provide avg_price_cents in position data.
    Returns 50 cents as final fallback if market state unavailable.
    """
    try:
        from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
        state = get_kalshi_market_state_store().get_unified(ticker)
        if state and state.mid_cents > 0:
            return state.mid_cents
    except Exception as _exc:
        logger.debug("position_cache: failed to fetch market state for %s, using 50c fallback: %s", ticker, _exc)
    return 50


def _get_fallback_price_for_market(market_id: str) -> Optional[int]:
    """Get fallback price for a market based on asset.

    This provides asset-specific fallback prices when REST API returns
    invalid/missing entry prices. Used for both notional calculation
    and PositionMonitor initialization.

    Args:
        market_id: Kalshi market ID (e.g., "KXBTC15M-26AUG010100-00")

    Returns:
        Fallback price in cents, or None if cannot determine
    """
    try:
        # First try to get from market state store (most accurate)
        fallback = _get_market_price_fallback(market_id)
        if fallback != 50:  # If we got actual market data, use it
            return fallback

        # Asset-specific fallbacks based on typical price ranges
        if "BTC" in market_id.upper():
            return 46  # Typical BTC 15m contract price
        elif "ETH" in market_id.upper():
            return 23  # Typical ETH 15m contract price
        elif "SOL" in market_id.upper():
            return 54  # Typical SOL 15m contract price
        elif "XRP" in market_id.upper():
            return 55  # Typical XRP 15m contract price
        elif "DOGE" in market_id.upper():
            return 28  # Typical DOGE 15m contract price
        else:
            return 50  # Generic fallback
    except Exception as _exc:
        logger.debug("position_cache: failed to determine fallback price for %s: %s", market_id, _exc)
        return 50


def _stop_loss_enabled_default() -> bool:
    """Default stop-loss enablement from the active profile.

    CRITICAL FIX (2026-08-10): upstream/midstream/downstream SL kill switch.
    All CachedPosition construction paths that do not explicitly receive an
    intent's stop_loss_enabled value (e.g. REST sync, ledger rebuild) should
    inherit the canonical profile setting.
    """
    try:
        from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
        if is_profile_active():
            profile = get_active_profile().profile
            if hasattr(profile, 'exit_policy_risk_reward'):
                return bool(profile.exit_policy_risk_reward.get('stop_loss_enabled', True))
    except Exception:
        pass
    return True


@dataclass
class CachedPosition:
    """Cached position state.

    Task 1: Added fill_source and client_order_id to distinguish hedge vs alpha positions
    for accurate exposure calculation.
    P1 FIX: Added scale_out_complete flag for partial profit taking tracking.
    P1 FIX: Added entry_intent_id for RoundTripMonitor exit reason tracking.
    FIX: Added notional_usd property for exposure calculation.
    CRITICAL FIX (2026-07-21): Added thesis_side as immutable strategy thesis invariant.
    thesis_side is set from entry intent and never changed by REST sync, preventing
    side inversion bugs where REST API's YES-side perspective overwrites NO positions.
    """
    market_id: str
    agent_id: str  # Agent identifier for composite key (market_id, agent_id)
    contracts: int
    side: str  # "yes" or "no" - derived from thesis_side, may be refreshed from REST
    thesis_side: str  # "yes" or "no" - immutable strategy thesis set from entry intent
    avg_price_cents: Optional[int]  # None = unknown/missing, 0 = invalid (real prices are 10-75c)
    realized_pnl_usd: Decimal = Decimal("0")
    # Canonical exposure as confirmed by fills / Kalshi positions.
    outcome_side: str = ""  # canonical outcome the position is long (yes/no); from fills if available
    book_side: str = "ask"  # canonical resting book side (ask for a long position)
    unrealized_pnl_usd: Decimal = Decimal("0")
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Take-profit targets from dynamic TP computation (R-multiple based)
    take_profit_price_cents: Optional[int] = None  # TP price level in cents
    take_profit_r_multiple: Optional[float] = None  # R-multiple target (e.g., 1.5R, 2.0R)
    stop_loss_price_cents: Optional[int] = None  # Protective stop in cents
    stop_loss_enabled: bool = field(default_factory=_stop_loss_enabled_default)  # CRITICAL FIX (2026-08-10): upstream/midstream/downstream SL kill switch
    # P1 FIX: Scale-out tracking for partial profit taking
    scale_out_complete: bool = False  # True if partial exit already executed
    # P1 FIX: Entry intent ID for RoundTripMonitor exit reason tracking
    entry_intent_id: Optional[str] = None  # Intent ID of the entry order
    # Task 1: Fill source tracking ("alpha" or "hedge")
    fill_source: str = "alpha"  # "alpha" = trading position, "hedge" = hedge position
    # CRITICAL FIX (2026-08-01): Add exit policy metadata for bracket orders
    # Required for _validate_risk_contract_linkage in order router
    exit_policy_id: Optional[str] = None  # Exit policy ID for tracking
    window_resolution_id: Optional[str] = None  # Window resolution ID for tracking
    client_order_id: Optional[str] = None  # For hedge fill detection
    # Resting bracket order tracking (GTC limit at TP / SL price)
    tp_bracket_client_tag: Optional[str] = None  # client_tag of resting TP order
    sl_bracket_client_tag: Optional[str] = None  # client_tag of resting SL order
    # Ratchet profit floor tracking (research-backed profit locking mechanism)
    ratchet_activated: bool = False  # True when price has crossed activation threshold
    ratchet_floor_price_cents: Optional[int] = None  # Hard floor price (never lowers once set)
    ratchet_activation_timestamp: Optional[datetime] = None  # When ratchet was activated
    # CRITICAL FIX (2026-07-23): Entry price state tracking
    entry_price_state: str = "unknown"  # "known", "unknown", "invalid" - tracks avg_price_cents data quality
    # CRITICAL FIX (2026-07-23): Risk parameters state tracking
    # Valid values align with RiskParamsState: "unknown", "original_persisted", "fallback"
    risk_params_state: str = "unknown"
    # CRITICAL FIX (2026-08-11): Schema version for risk parameter provenance.
    # Schema 2 records were written with the 2026-08-11 spread-stop fixes and are
    # only trusted as original when paired with an entry linkage.
    risk_params_schema_version: int = 1
    # CRITICAL FIX (2026-08-01): Volatility regime and confidence tracking
    vol_regime: str = "unknown"  # Volatility regime at entry time (unknown/low/normal/high/extreme)
    confidence: str = "unknown"  # Signal confidence at entry time (unknown/low/medium/high)
    # CRITICAL FIX (2026-08-07): Entry edge percentage for dynamic TP adjustment
    entry_edge_pct: float = 0.03
    # CRITICAL 2026-08-09: Canonical position size in centi-contracts (100 = 1 contract).
    quantity_cc: int = 0  # Initialized from contracts*100 if not explicitly provided

    # CRITICAL FIX (2026-08-10): Durable entry-model provenance for exit attribution.
    entry_signal_id: Optional[str] = None
    entry_model: Optional[str] = None
    entry_model_version: Optional[str] = None
    entry_model_probability: Optional[float] = None
    entry_market_probability: Optional[float] = None
    entry_edge: Optional[float] = None
    entry_book_snapshot_id: Optional[str] = None
    entry_fill_id: Optional[str] = None
    entry_order_id: Optional[str] = None
    entry_execution_mode: Optional[str] = None
    client_order_id: Optional[str] = None
    entry_intent_id: Optional[str] = None
    # 2026-08-29: Decision ID for end-to-end ledger provenance.
    decision_id: Optional[str] = None
    # CRITICAL FIX (2026-08-11): Executable entry book for spread-only exit invariants
    entry_executable_bid_cents: Optional[int] = None
    entry_executable_ask_cents: Optional[int] = None
    entry_book_capture_quality: str = "UNKNOWN"
    entry_fill_price_cents: Optional[int] = None
    entry_fill_timestamp: Optional[datetime] = None
    entry_book_timestamp: Optional[datetime] = None
    entry_book_sequence: Optional[int] = None
    entry_book_source: Optional[str] = None
    # CRITICAL FIX (2026-08-23): Durable edge-decay policy provenance.
    entry_provenance_snapshot_id: Optional[str] = None
    tp_policy_id: Optional[str] = None
    tp_policy_version: Optional[str] = None
    sl_policy_id: Optional[str] = None
    sl_policy_version: Optional[str] = None
    provenance_state: str = "UNKNOWN_PROVENANCE"
    # CRITICAL FIX (2026-08-23): Monotonic position version for deterministic dedupe/intent keys.
    position_version: int = 1
    # CRITICAL FIX (2026-08-23): Canonical position key. This is the immutable
    # identity used by cache, monitor, ledger, and reconciliation. Asset labels
    # (XRP15M, KXXRP15M, XRP) are aliases only and must never be a primary key.
    position_key: Optional[Any] = None
    # CRITICAL FIX (2026-08-25): Settlement lifecycle.  Positions are retained
    # until explicit settlement/finalization or an authoritative zero position.
    # ``settlement_status`` transitions to ``pending`` once the market is past
    # its close buffer and an alert is raised, but the position is not deleted.
    settlement_status: str = "open"
    known_aliases: List[str] = field(default_factory=list)
    exchange_index: Optional[int] = None  # Kalshi exchange shard index (e.g. 2 for crypto 15m)

    def __post_init__(self):
        """Initialize canonical quantity_cc from contracts if not already set."""
        if self.quantity_cc == 0 and self.contracts:
            self.quantity_cc = int(self.contracts * 100)
            self.contracts = int(self.contracts)

    @property
    def notional_usd(self) -> Decimal:
        """Compute notional value in USD from contracts and average price.

        CRITICAL FIX (2026-07-31): Handle None avg_price_cents (unknown entry price) with fallback.
        Uses market state fallback price when avg_price_cents is None or 0 to prevent
        position cache from reporting 0 exposure for valid positions.
        """
        qty = self.quantity_cc if self.quantity_cc else self.contracts * 100
        if qty <= 0:
            return Decimal("0")
        if self.avg_price_cents is None or self.avg_price_cents == 0:
            # CRITICAL FIX: Use fallback price from market state to prevent 0 exposure bug
            fallback_price = _get_market_price_fallback(self.market_id)
            logger.warning(
                "[POSITION-CACHE-FALLBACK] market=%s avg_price_cents=%s quantity_cc=%d "
                "using fallback=%dc for notional calculation (prevents 0 exposure bug)",
                self.market_id, self.avg_price_cents, qty, fallback_price
            )
            return Decimal(qty) * Decimal(fallback_price) / Decimal("10000")
        return Decimal(qty) * Decimal(self.avg_price_cents) / Decimal("10000")

    @property
    def notional_value(self) -> Decimal:
        """Alias for notional_usd for compatibility with loop_15m.py."""
        return self.notional_usd

    def _yes_exposure(self) -> int:
        """Return signed YES exposure in centi-contracts (positive=long YES, negative=long NO)."""
        qty = self.quantity_cc if self.quantity_cc else self.contracts * 100
        if BINARY_PRICE_SPACE_AVAILABLE:
            return int(to_signed_yes_exposure(self.side, qty))
        return int(qty if self.side.lower() == "yes" else -qty)

    def apply_fill(
        self,
        contracts: int,
        price_cents: int,
        fee_cents: int,
        side: str,
        action: str = "buy",
        expected_post_size: Optional[int] = None,
        is_exit: Optional[bool] = None,
        quantity_cc: Optional[int] = None,
        yes_price_cents: Optional[int] = None,
        no_price_cents: Optional[int] = None,
    ) -> None:
        """Update position with a new fill using signed YES exposure.

        The position cache uses the canonical signed-YES delta to determine
        whether a fill opens, adds to, or closes a position.  ``price_cents``
        is the fill's execution-side price; when it differs from the
        position's own side, the stored ``yes_price_cents`` / ``no_price_cents``
        are used to select the position-side price.  No price is ever derived
        via 100 - side_price.

        Args:
            expected_post_size: Expected position size after fill (for reconciliation)
            is_exit: Optional explicit exit hint; logged if it conflicts with
                     the sign-based classification but not used as source of truth.
            yes_price_cents: Optional YES-side price in cents (for cross-side conversion)
            no_price_cents: Optional NO-side price in cents (for cross-side conversion)
        """
        from utils.logger import get_logger
        logger = get_logger("merid.position_cache")

        action = (action or "buy").lower()
        side = (side or "yes").lower()
        price_cents = int(price_cents)

        # CRITICAL (2026-08-09): Removed the 2026-08-07 direction policy guards.
        # They rejected economically equivalent cross-leg fills (e.g. SELL_YES
        # opening a long NO position, or SELL_NO opening a long YES position).
        # The signed YES-delta math below is the single source of truth for
        # whether a fill opens, adds to, or closes a position.

        # Canonical quantity in centi-contracts. ``contracts`` is display-only;
        # ``quantity_cc`` is the exact, canonical unit.
        if quantity_cc is None:
            try:
                quantity_cc = int(Decimal(str(contracts)) * Decimal("100"))
            except Exception:
                quantity_cc = int(contracts) * 100
        else:
            quantity_cc = int(quantity_cc)

        # Canonical signed YES delta for this fill.
        if BINARY_PRICE_SPACE_AVAILABLE:
            fill_yes_delta = yes_delta(action, side, quantity_cc)
        else:
            # DIRECTION POLICY (2026-08-07): Defensive fallback without cross-leg equivalence
            if (action, side) in {("buy", "yes")}:
                fill_yes_delta = +quantity_cc
            elif (action, side) in {("buy", "no")}:
                fill_yes_delta = -quantity_cc
            elif (action, side) in {("sell", "yes")}:
                fill_yes_delta = -quantity_cc  # SELL YES closes long YES
            elif (action, side) in {("sell", "no")}:
                fill_yes_delta = +quantity_cc  # SELL NO closes long NO
            else:
                raise ValueError(f"Unsupported fill: action={action} side={side}")

        pre_yes_exposure = self._yes_exposure()
        new_yes_exposure = pre_yes_exposure + fill_yes_delta

        # Determine new side / contracts from canonical exposure (centi-contracts).
        if new_yes_exposure != 0:
            new_side, new_quantity_cc = from_signed_yes_exposure(new_yes_exposure)
        else:
            new_side, new_quantity_cc = self.side, 0

        # The position side used for price/PnL math.  If the position is being
        # fully closed we use the current side; otherwise the new side.
        position_side_for_price = self.side if new_quantity_cc == 0 else new_side

        # Convert fill price from the fill's execution side into the position's
        # own side space using the stored YES/NO leg prices.  No complement.
        if side == position_side_for_price:
            adjusted_price_cents = price_cents
        elif position_side_for_price == "yes" and yes_price_cents is not None:
            adjusted_price_cents = yes_price_cents
        elif position_side_for_price == "no" and no_price_cents is not None:
            adjusted_price_cents = no_price_cents
        else:
            logger.warning(
                "[POSITION-CACHE-PRICE-MISSING-LEG] market=%s raw_side=%s position_side=%s "
                "yes_price_cents=%s no_price_cents=%s - cannot convert fill price; using raw price",
                self.market_id, side, position_side_for_price, yes_price_cents, no_price_cents,
            )
            adjusted_price_cents = price_cents

        # Classify the fill by its effect on absolute exposure.
        if pre_yes_exposure == 0:
            is_open = (new_yes_exposure != 0)
            is_close = False
        elif fill_yes_delta == 0:
            is_open = is_close = False
        elif pre_yes_exposure * fill_yes_delta > 0:
            # Same sign: adding to an existing position.
            is_open = True
            is_close = False
        else:
            # Opposite sign: reducing or flipping the position.
            if abs(fill_yes_delta) > abs(pre_yes_exposure):
                # This would flip exposure (e.g. long YES -> larger long NO).  Treat as
                # an attempted reversal and close the position to zero, logging loudly.
                logger.critical(
                    "[POSITION-FLIP-DETECTED] market=%s side=%s action=%s fill_yes_delta=%d pre_yes=%d new_yes=%d - "
                    "Attempted position flip detected.  Reducing to zero only.",
                    self.market_id, side, action, fill_yes_delta, pre_yes_exposure, new_yes_exposure,
                )
                new_yes_exposure = 0
                new_side, new_quantity_cc = self.side, 0
                is_open = False
                is_close = True
            else:
                is_open = False
                is_close = True

        # Warn if the explicit is_exit hint conflicts with the sign-based truth.
        if is_exit is not None:
            if is_exit and is_open:
                logger.critical(
                    "[IS-EXIT-HINT-MISMATCH] market=%s side=%s action=%s is_exit=True but signed exposure shows ENTRY. "
                    "Using sign-based classification (ENTRY).",
                    self.market_id, side, action,
                )
            elif not is_exit and is_close and self.quantity_cc > 0:
                logger.critical(
                    "[IS-EXIT-HINT-MISMATCH] market=%s side=%s action=%s is_exit=False but signed exposure shows EXIT. "
                    "Using sign-based classification (EXIT).",
                    self.market_id, side, action,
                )

        # AUDIT: Log fill reconciliation.
        if is_open:
            logger.info(
                "[FILL-RECONCILIATION-AUDIT] ticker=%s raw_side=%s action=%s pre_yes=%d fill_yes_delta=%d post_yes=%d price=%dc type=entry_fill expected_post_size=%s",
                self.market_id, side, action, pre_yes_exposure, fill_yes_delta, new_yes_exposure,
                price_cents, expected_post_size,
            )
        elif is_close:
            logger.info(
                "[FILL-RECONCILIATION-AUDIT] ticker=%s raw_side=%s action=%s pre_yes=%d fill_yes_delta=%d post_yes=%d price=%dc type=exit_fill expected_post_size=%s",
                self.market_id, side, action, pre_yes_exposure, fill_yes_delta, new_yes_exposure,
                price_cents, expected_post_size,
            )

        # DIRECTION POLICY (2026-08-07): Mandatory event record at fill boundary
        # Log the canonical direction policy record for auditability
        lifecycle = "entry" if is_open else "exit" if is_close else "unknown"
        logger.info(
            "[DIRECTION-POLICY-RECORD] trace_id=unknown ticker=%s lifecycle=%s outcome_side=%s action=%s "
            "price_cents=%d quantity_cc=%d position_before_cc=%d position_after_expected_cc=%s",
            self.market_id,
            lifecycle,
            side,
            action,
            price_cents,
            quantity_cc,
            self.quantity_cc,
            expected_post_size
        )

        if is_open:
            pre_quantity_cc = self.quantity_cc

            # CRITICAL FIX (2026-08-01): Warn on 1 contract per position rule.
            # Fills that already happened on the venue must still be tracked to keep
            # the cache aligned with actual exposure; the 1-contract rule is enforced
            # by the order router at order placement, not by dropping fills here.
            if new_quantity_cc > 100 and os.getenv("MERID_DISABLE_CONTRACT_LIMIT", "false").lower() not in ("true", "1", "yes"):
                logger.critical(
                    "[POSITION-CACHE-CONTRACT-LIMIT-WARNING] ticker=%s raw_side=%s action=%s "
                    "pre_quantity_cc=%d fill_quantity_cc=%d would_post_quantity_cc=%d - 1 CONTRACT PER POSITION RULE EXCEEDED. "
                    "Tracking the fill because it already happened on the venue; enforce the limit at order placement.",
                    self.market_id, side, action, pre_quantity_cc, quantity_cc, new_quantity_cc,
                )

            if self.quantity_cc == 0:
                # New position: the fill price in position-side space becomes the basis.
                self.side = new_side
                self.thesis_side = new_side
                self.outcome_side = new_side
                self.book_side = "ask"  # A long position rests on the ask of its outcome
                self.avg_price_cents = adjusted_price_cents
            else:
                # Add to existing position.  Both old and new prices must be in the
                # same (position) side space.
                avg_price_old = self.avg_price_cents if self.avg_price_cents is not None else adjusted_price_cents
                # Cost in cents: (centi-contracts * cents) / 100 -> contract*cents
                total_cost_old = Decimal(self.quantity_cc * avg_price_old) / Decimal("100")
                total_cost_new = Decimal(quantity_cc * adjusted_price_cents) / Decimal("100")
                new_total_cc = self.quantity_cc + quantity_cc
                new_avg = (total_cost_old + total_cost_new) * Decimal("100") / Decimal(new_total_cc)
                self.avg_price_cents = int(new_avg.to_integral_value(rounding=ROUND_HALF_UP)) if new_total_cc > 0 else adjusted_price_cents
                if new_side != self.side:
                    logger.critical(
                        "[POSITION-SIDE-FLIP-ON-ADD] market=%s raw_side=%s action=%s - "
                        "Adding fill changed position side from %s to %s. This should not happen.",
                        self.market_id, side, action, self.side, new_side,
                    )
                    self.side = new_side
                    self.thesis_side = new_side

            self.quantity_cc = int(new_quantity_cc)
            self.contracts = int(new_quantity_cc) // 100
            self.entry_price_state = "known"

            if self.quantity_cc < pre_quantity_cc:
                logger.critical(
                    "[WRONG-DIRECTION-POSITION-CHANGE] ticker=%s raw_side=%s action=%s pre_quantity_cc=%d fill_quantity_cc=%d post_quantity_cc=%d - ENTRY fill REDUCED position instead of increasing.",
                    self.market_id, side, action, pre_quantity_cc, quantity_cc, self.quantity_cc,
                )

        elif is_close:
            pre_quantity_cc = self.quantity_cc
            closed_quantity_cc = pre_quantity_cc - new_quantity_cc

            if new_quantity_cc > pre_quantity_cc:
                logger.critical(
                    "[WRONG-DIRECTION-POSITION-CHANGE] ticker=%s raw_side=%s action=%s pre_quantity_cc=%d fill_quantity_cc=%d post_quantity_cc=%d - EXIT fill INCREASED position instead of reducing.",
                    self.market_id, side, action, pre_quantity_cc, quantity_cc, new_quantity_cc,
                )

            logger.info(
                "[FILL-RECONCILIATION-AUDIT] ticker=%s raw_side=%s action=%s pre_quantity_cc=%d closed_quantity_cc=%d post_quantity_cc=%d price=%dc type=exit_fill_complete",
                self.market_id, side, action, pre_quantity_cc, closed_quantity_cc, new_quantity_cc, price_cents,
            )

            if new_quantity_cc > 0:
                logger.warning(
                    "[FILL-RECONCILIATION-AUDIT] ticker=%s RESIDUAL_POSITION_DETECTED pre_quantity_cc=%d closed_quantity_cc=%d post_quantity_cc=%d - position not fully closed, requires follow-up exit",
                    self.market_id, pre_quantity_cc, closed_quantity_cc, new_quantity_cc,
                )
                logger.warning(
                    "[RESIDUAL-EXPOSURE-RISK] ticker=%s residual_quantity_cc=%d - position has residual exposure that may not have follow-up exit enforcement",
                    self.market_id, new_quantity_cc,
                )

            if expected_post_size is not None:
                if new_quantity_cc != expected_post_size * 100:
                    logger.error(
                        "[RECONCILIATION-MISMATCH] ticker=%s actual_post_quantity_cc=%d expected_post_quantity_cc=%d - position ledger does not match expected residual size",
                        self.market_id, new_quantity_cc, expected_post_size * 100,
                    )
                else:
                    logger.info(
                        "[RECONCILIATION-MATCH] ticker=%s actual_post_quantity_cc=%d expected_post_quantity_cc=%d - position ledger matches expected residual size",
                        self.market_id, new_quantity_cc, expected_post_size * 100,
                    )

            if self.avg_price_cents is None:
                logger.warning(
                    "[PNL-CALCULATION-SKIPPED] ticker=%s avg_price_cents=None - cannot calculate PnL for exit fill. entry_price_state=%s",
                    self.market_id, self.entry_price_state,
                )
                self.quantity_cc = int(new_quantity_cc)
                self.contracts = int(new_quantity_cc) // 100
            else:
                # Long position PnL: exit price - entry price in own-side cents.
                pnl_per = adjusted_price_cents - self.avg_price_cents
                pnl_cents = Decimal(closed_quantity_cc * pnl_per) / Decimal("100")
                _realized_pnl_before = self.realized_pnl_usd
                self.realized_pnl_usd += Decimal(pnl_cents) / Decimal("100") - Decimal(fee_cents) / Decimal("100")
                self.quantity_cc = int(new_quantity_cc)
                self.contracts = int(new_quantity_cc) // 100

                # CRITICAL FIX (2026-08-27): Feed realized PnL to the bankroll drawdown
                # breaker once the position is fully settled. Exits are the canonical
                # settlement hook and use the authoritative fill_id already applied above.
                if new_quantity_cc == 0 and pre_quantity_cc > 0:
                    try:
                        from merid.event_venues.kalshi.bankroll_service_v2 import _BANKROLL_SERVICE_V2
                        if _BANKROLL_SERVICE_V2 is not None:
                            _BANKROLL_SERVICE_V2.record_trade_outcome(
                                self.realized_pnl_usd,
                                is_probe=False,
                            )
                    except Exception as exc:
                        logger.warning(
                            "[POSITION-CACHE] Failed to record trade outcome to bankroll breaker: %s",
                            exc,
                        )

                # Feed every realized PnL delta to the unified risk manager so the
                # daily/weekly loss throttle is current on all exit fills (partial,
                # full, TP, SL, time stop, edge reversal, etc.).
                _realized_delta = self.realized_pnl_usd - _realized_pnl_before
                if _realized_delta != 0:
                    try:
                        from merid.risk.unified_risk_manager import get_unified_risk_manager

                        get_unified_risk_manager().record_pnl(float(_realized_delta))
                    except Exception as exc:
                        logger.warning(
                            "[POSITION-CACHE] Failed to record PnL to UnifiedRiskManager: %s",
                            exc,
                        )

        # Update side/thesis when the position is fully closed (keep for logging).
        if self.quantity_cc == 0:
            # Side/thesis remain as-is for post-mortem logging; next entry will reset.
            pass

        self.last_updated = datetime.now(timezone.utc)

    def update_unrealized_pnl(self, current_price_cents: int) -> None:
        """Recalculate unrealized PnL based on current market price.

        CRITICAL FIX (2026-07-23): Handle None avg_price_cents (unknown entry price).
        Returns 0 if avg_price_cents is None.
        """
        qty = self.quantity_cc if self.quantity_cc else self.contracts * 100
        if qty > 0 and self.avg_price_cents is not None:
            # Long position unrealized PnL: (current - avg) in own-side cents.
            pnl_cents = Decimal(qty * (current_price_cents - self.avg_price_cents)) / Decimal("100")
            self.unrealized_pnl_usd = Decimal(pnl_cents) / Decimal("100")
        else:
            self.unrealized_pnl_usd = Decimal("0")


class KalshiPositionCache:
    """Real-time position cache updated from WebSocket events.

    Usage:
        cache = get_position_cache()
        cache.on_fill(market_id, contracts, price_cents, fee_cents, side)
        position = cache.get_position(market_id)
    """

    _instance: Optional[KalshiPositionCache] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._positions: Dict[str, CachedPosition] = {}  # Key: market_id (agent_id tracked as field)
        self._last_sync: Optional[datetime] = None
        # CRITICAL FIX (2026-08-11): Per-source idempotency for REST sync.
        self._last_rest_sync_timestamp: float = 0.0
        # CRITICAL FIX: Track unhealthy positions (missing exit metadata)
        self._unhealthy_positions: set = set()
        # CRITICAL FIX: Track applied fill_ids for exactly-once idempotency
        # Prevents double-application of fills when same fill arrives via WebSocket and HTTP poller
        from collections import OrderedDict

        # CRITICAL FIX: Integrate active reconciliation with callbacks
        # Set up resync callback for auto-resync action
        try:
            from merid.event_venues.kalshi.active_reconciliation import get_active_reconciliation
            active_recon = get_active_reconciliation()
            active_recon.set_resync_callback(self._auto_resync_callback)
            active_recon.set_halt_callback(self._auto_halt_callback)
            logger.info("[POSITION-CACHE] Active reconciliation callbacks registered")
        except Exception as recon_err:
            logger.debug("[POSITION-CACHE] Could not register reconciliation callbacks: %s", recon_err)
        self._applied_fill_ids: OrderedDict[str, float] = OrderedDict()
        self._applied_fill_ids_max = 10000  # Max fill_ids to track (fills are unique and don't expire)
        # 2026-08-23: Persist applied fill ids so a process restart does not re-apply
        # durable fills and double-count exposure / PnL.
        self._applied_fill_ids_path = Path("data") / "kalshi_applied_fill_ids.json"
        self._load_applied_fill_ids()

        # CRITICAL 2026-08-09: Fail-closed reconciliation gating. If exchange/ledger/cache
        # signed-YES exposure diverges for a ticker, new entry orders are blocked until
        # the mismatch is resolved. Exits are still allowed so positions can be closed.
        self._reconciliation_halted: Dict[str, bool] = {}

        # Settled/finalized markets: the position is closed by settlement and should
        # not be rebuilt from the fills ledger.  Populated by ``on_market_settlement``
        # and used by ``_is_expired_ticker`` to decide when a position can be removed.
        self._settled_tickers: Set[str] = set()

        # 2026-08-28: Closed-but-not-yet-settled markets that the exchange still
        # reports as non-zero positions.  These cannot be traded, should not block
        # new entries, and must be excluded from active exposure until Kalshi
        # resolves them and on_market_settlement fires.
        self._quarantined_tickers: Set[str] = set()

        # 2026-08-29: Startup marker so health probes can assert that the
        # stuck-position quarantine path is actually loaded by this process.
        self._quarantine_path_active = True
        logger.info("[POSITION-CACHE] quarantine_path=active")

        # 2026-08-12/13: Latest known signed-YES exposure and sync timestamp per
        # ticker, populated by REST sync and used by the per-fill
        # FILL-CANONICALIZATION parity check with a fill-timestamp watermark.
        self._last_exchange_signed_yes: Dict[str, int] = {}
        self._last_ledger_signed_yes: Dict[str, int] = {}
        self._last_exchange_sync_time: Dict[str, float] = {}
        # 2026-08-13: Per-ticker last fill parity to enforce two consecutive
        # mismatches (on a fresh exchange snapshot) before halting.
        self._last_fill_parity: Dict[str, str] = {}

        # Log bracket order mode on startup
        brackets_enabled = os.getenv("MERID_RESTING_BRACKETS_ENABLED", "false").lower() in ("true", "1", "yes")
        mode = "RESTING" if brackets_enabled else "MONITOR_ONLY"
        logger.info("[BRACKET-STATE] mode=%s MERID_RESTING_BRACKETS_ENABLED=%s", mode, os.getenv("MERID_RESTING_BRACKETS_ENABLED", "false"))
        # BUG-FIX: Add mutex for thread safety during concurrent WebSocket fill events
        # CRITICAL FIX (2026-08-01): Eagerly initialize mutex to prevent race condition
        # Lazy initialization with "if self._mutex is None" is not atomic and can lead to
        # multiple coroutines creating separate locks, causing lost synchronization.
        # Eager initialization in __init__ ensures the lock exists before any concurrent access.
        self._mutex = asyncio.Lock()
        # PRODUCTION FIX: Pending TP targets keyed by client_order_id for fill-time lookup
        self._pending_tp_targets: Dict[str, Dict[str, Any]] = {}
        # CRITICAL FIX (2026-08-22): Persist pending TP targets so entry book/model
        # provenance survives a process restart.  Without this, rest_sync positions
        # rebuilt from the fills_ledger cannot recover AT_FILL spread-stop invariants
        # and model-invalidation exits are blocked.
        self._pending_tp_targets_path = Path("data") / "kalshi_pending_tp_targets.json"
        self._load_pending_tp_targets()
        # 2026-08-25: Watermark for this process instance. Fills whose ledger
        # record was created before this cache started are durable state from a
        # previous process and must not be re-applied (they will be rebuilt by
        # the reconciler from the fills_ledger/exchange REST snapshot).
        self._started_at = replay_start_time()
        # PRODUCTION FIX: Map Kalshi order_id -> client_tag for fill-to-intent linkage
        # This is needed because HTTP fills don't include client_order_id from Kalshi API
        self._order_id_to_client_tag: Dict[str, str] = {}
        self._order_id_to_client_tag_path = Path("data") / "kalshi_order_id_to_client_tag.json"
        self._load_order_id_to_client_tag()
        # Task 2: Add fills_ledger reference for authoritative fill_source lookup
        # DETOX FIX: Lazy load fills_ledger to prevent import-time initialization cascade
        # BUG-FIX: Actually initialize the ledger reference (was always None)
        self._fills_ledger = None  # Lazy loaded via _get_fills_ledger()
        # TUNED (2026-05-25): Trailing stop monitoring infrastructure
        self._monitoring_enabled: bool = False
        self._monitoring_task: Optional[asyncio.Task] = None
        self._monitoring_interval_seconds: float = 5.0  # Check every 5 seconds
        self._initialized = True

        # CRITICAL FIX: Reset stale window exposure if position cache is empty
        # This prevents phantom exposure from blocking all trading after restart
        self._reset_stale_window_exposure()

        # CRITICAL FIX: DO NOT register exit intent callback here
        # The production callback is registered in loop_15m.py with proper swing mode logic
        # Registering here would overwrite the production callback and break exit handling
        # PositionMonitor callback registration is done in loop_15m._start_position_monitor()

        logger.info("KalshiPositionCache initialized")

    @property
    def quarantine_path_active(self) -> bool:
        """Return True once the stuck-position quarantine path has been loaded."""
        return getattr(self, "_quarantine_path_active", False)

    def _is_exit_order_from_action(self, action: str, source: Optional[str] = None) -> bool:
        """Check if this is an exit order based on action and source.

        This mirrors the logic in order_router._is_exit_order for consistency.
        Exit orders REDUCE exposure and should bypass exposure recording.

        CRITICAL FIX (2026-07-13): Only treat orders with explicit exit markers as exits.
        Entry orders (both YES buy and NO sell) must record exposure to enforce $1 cap.

        CRITICAL FIX (2026-07-15): Use shared exit_order_utils module to prevent
        divergence between order_router.py and position_cache.py.
        """
        from merid.event_venues.kalshi.exit_order_utils import is_exit_order_from_action

        return is_exit_order_from_action(action, source)

    def require_rest_reconciliation(self, market_id: str, reason: str = "untrusted_legacy") -> None:
        """Record that a fresh exchange REST snapshot is required before trusting
        live position math for this ticker.

        Called by `fills_ledger.load_from_db()` when an UNTRUSTED_LEGACY fill is
        loaded.  The halt blocks new entry routing for the ticker until a REST
        sync clears it; exits remain enabled to close positions.
        """
        self._reconciliation_halted[market_id] = True
        logger.warning(
            "[POSITION-CACHE-RECONCILIATION-REQUIRED] market=%s reason=%s | "
            "Exchange REST snapshot required before live entry.",
            market_id, reason,
        )

    def _ensure_mutex(self) -> asyncio.Lock:
        """
        Return the mutex for position cache operations.

        CRITICAL FIX (2026-08-01): Mutex is now eagerly initialized in __init__
        to prevent race conditions. This method is kept for backward compatibility
        but simply returns the pre-initialized lock.

        Previous lazy initialization pattern was vulnerable to race conditions:
        - Multiple coroutines could check self._mutex is None simultaneously
        - Each would create a separate asyncio.Lock
        - Subsequent operations would use different locks, losing synchronization

        Eager initialization in __init__ ensures atomic creation before any concurrent access.
        """
        # Mutex is eagerly initialized in __init__, so it should never be None
        # This assertion catches programming errors if the initialization is removed
        if self._mutex is None:
            logger.error(
                "[POSITION-CACHE-MUTEX] CRITICAL: Mutex is None - eager initialization failed!"
            )
            # Fallback: create lock (should never happen in production)
            self._mutex = asyncio.Lock()
        return self._mutex

    def _get_fills_ledger(self):
        """Lazy load fills_ledger to prevent import-time initialization cascade."""
        if self._fills_ledger is None:
            from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
            self._fills_ledger = get_fills_ledger()
        return self._fills_ledger

    def _get_cache_signed_yes(self, market_id: str) -> int:
        """Return the current cache position as signed-YES exposure in centi-contracts for reconciliation."""
        pos = self._positions.get(market_id)
        if not pos:
            return 0
        return pos._yes_exposure()

    def _emit_exposure_reconciliation(
        self,
        ticker: str,
        exchange_signed_yes: int,
        ledger_signed_yes: int,
        cache_signed_yes: int,
        open_order_reserved_yes: int,
        source_timestamp: Optional[float],
        status: str,
        from_exchange: bool = False,
    ) -> None:
        """Emit a single canonical reconciliation line.

        All exposure sources are normalized to signed-YES before logging so that
        cross-source comparisons are unambiguous.
        When the three-way exposure (exchange, ledger, cache) does not agree, the
        ticker is marked reconciliation_halted, which blocks new entry orders.
        """
        net_signed_yes = exchange_signed_yes + open_order_reserved_yes

        # Fail-closed: any divergence between exchange, ledger, and cache signed-YES
        # exposure halts new entry routing for this ticker until reconciliation succeeds.
        three_way_match = (
            exchange_signed_yes == ledger_signed_yes == cache_signed_yes
        )
        if not three_way_match:
            self._reconciliation_halted[ticker] = True
            status = "mismatch"
        else:
            if self._reconciliation_halted.get(ticker):
                logger.warning("[EXPOSURE-RECONCILIATION] ticker=%s three-way exposure match; clearing halt", ticker)
            self._reconciliation_halted[ticker] = False

        # 2026-08-13: Record ledger exposure for per-fill parity.  Only record
        # exchange exposure and timestamp when the source is an actual exchange
        # REST snapshot (from_exchange=True), not a cache/ledger self-check.
        self._last_ledger_signed_yes[ticker] = ledger_signed_yes
        if from_exchange:
            self._last_exchange_signed_yes[ticker] = exchange_signed_yes
            if source_timestamp:
                self._last_exchange_sync_time[ticker] = source_timestamp

        logger.info(
            "[EXPOSURE-RECONCILIATION] ticker=%s exchange_signed_yes=%d "
            "ledger_signed_yes=%d cache_signed_yes=%d open_order_reserved_yes=%d "
            "net_signed_yes=%d source_timestamp=%s reconciliation_status=%s",
            ticker,
            exchange_signed_yes,
            ledger_signed_yes,
            cache_signed_yes,
            open_order_reserved_yes,
            net_signed_yes,
            f"{source_timestamp:.3f}" if source_timestamp else "None",
            status,
        )

    async def _log_fill_canonicalization(
        self,
        market_id: str,
        fill_record: Optional[Any],
        side: str,
        action: str,
        quantity_cc: Optional[int],
        price_cents: int,
        position: Any,
        pre_position_yes: int,
    ) -> None:
        """Emit a per-fill FILL-CANONICALIZATION log and fail-closed on parity mismatch.

        This is the live invariant the user described: record the raw exchange
        facts, the canonical position effect, and compare the cache's signed-YES
        exposure after the fill against the last known exchange REST position.
        """
        cache_signed_yes_after = position._yes_exposure()

        # Build the raw/canonical audit fields from the durable fill record.
        exec_outcome_side = getattr(fill_record, 'execution_outcome_side', None) or getattr(fill_record, 'side', None) or side
        exec_action = getattr(fill_record, 'execution_action', None) or getattr(fill_record, 'action', None) or action
        exec_price_cents = getattr(fill_record, 'execution_price_cents', None)
        canonical_position_side = getattr(fill_record, 'canonical_position_side', None) or side
        canonical_position_action = getattr(fill_record, 'canonical_position_action', None) or action
        canonical_leg_price_cents = getattr(fill_record, 'canonical_leg_price_cents', None)
        if canonical_leg_price_cents is None:
            canonical_leg_price_cents = price_cents
        canonical_yes_delta_cc = getattr(fill_record, 'canonical_yes_delta_cc', None)
        if canonical_yes_delta_cc is None and quantity_cc is not None:
            try:
                canonical_yes_delta_cc = yes_delta(canonical_position_action, canonical_position_side, quantity_cc)
            except Exception:
                canonical_yes_delta_cc = None
        intent_target_side = getattr(fill_record, 'intent_target_side', None)

        exchange_signed_yes_after = self._last_exchange_signed_yes.get(market_id)
        exchange_sync_ts = self._last_exchange_sync_time.get(market_id)

        # 2026-08-13: Watermark check.  Do not compare a post-fill cache state to
        # an exchange snapshot that predates the fill; that is a stale comparison
        # and would create false halts during normal REST/WS propagation delay.
        fill_timestamp: Optional[float] = None
        if fill_record is not None and getattr(fill_record, 'created_time', None) is not None:
            fill_timestamp = fill_record.created_time.timestamp()

        parity = "UNKNOWN"
        if exchange_signed_yes_after is None or exchange_sync_ts is None:
            parity = "UNKNOWN"
        elif fill_timestamp is not None and exchange_sync_ts < fill_timestamp:
            parity = "PENDING_EXCHANGE_CONFIRMATION"
        else:
            parity = "PASS" if cache_signed_yes_after == exchange_signed_yes_after else "FAIL"

        logger.info(
            "[FILL-CANONICALIZATION] ticker=%s fill_id=%s "
            "execution_outcome_side=%s execution_action=%s execution_price_cents=%s "
            "canonical_position_side=%s canonical_position_action=%s canonical_leg_price_cents=%s "
            "signed_yes_delta=%s intent_target_side=%s "
            "cache_signed_yes_after=%s exchange_signed_yes_after=%s parity=%s",
            market_id,
            getattr(fill_record, 'fill_id', None) or "unknown",
            exec_outcome_side or "unknown",
            exec_action or "unknown",
            exec_price_cents if exec_price_cents is not None else "unknown",
            canonical_position_side or "unknown",
            canonical_position_action or "unknown",
            canonical_leg_price_cents if canonical_leg_price_cents is not None else "unknown",
            canonical_yes_delta_cc if canonical_yes_delta_cc is not None else "unknown",
            intent_target_side or "unknown",
            cache_signed_yes_after,
            exchange_signed_yes_after if exchange_signed_yes_after is not None else "unknown",
            parity,
        )

        # 2026-08-13: Confirmed order/fill contradiction (intent vs execution side)
        # is a fail-closed condition: halt immediately.  Only an exposure mismatch
        # (signed-YES delta diverges from intent) is a true conflict; a counterparty
        # side-label mismatch with matching exposure is a reporting artifact.
        _exposure_mismatch = getattr(fill_record, 'exposure_mismatch', None)
        _side_conflict = getattr(fill_record, 'side_conflict', False)
        _has_exposure_mismatch = _exposure_mismatch is True or (
            _exposure_mismatch is None and _side_conflict
        )
        if fill_record is not None and _has_exposure_mismatch:
            logger.critical(
                "[INTENT-EXECUTION-SIDE-CONFLICT-HALT] ticker=%s fill_id=%s "
                "execution_outcome_side=%s intent_target_side=%s. Halting new entries for this ticker.",
                market_id, getattr(fill_record, 'fill_id', None) or "unknown",
                getattr(fill_record, 'execution_outcome_side', None) or "unknown",
                getattr(fill_record, 'intent_target_side', None) or "unknown",
            )
            self._reconciliation_halted[market_id] = True

        # 2026-08-13: Parity failure on a fresh exchange snapshot.  Require two
        # consecutive mismatches before halting to avoid false positives from a
        # single transient propagation delay.
        if parity == "FAIL" and exchange_sync_ts is not None and fill_timestamp is not None and exchange_sync_ts >= fill_timestamp:
            if self._last_fill_parity.get(market_id) == "FAIL":
                logger.critical(
                    "[FILL-CANONICALIZATION-HALT] ticker=%s fill_id=%s cache_signed_yes_after=%s "
                    "does not match exchange_signed_yes_after=%s on a fresh snapshot (ts=%.3f >= fill_ts=%.3f). "
                    "Two consecutive mismatches detected. Halting new entries for this ticker.",
                    market_id, getattr(fill_record, 'fill_id', None) or "unknown",
                    cache_signed_yes_after, exchange_signed_yes_after,
                    exchange_sync_ts, fill_timestamp
                )
                self._reconciliation_halted[market_id] = True
            else:
                logger.warning(
                    "[FILL-CANONICALIZATION-FIRST-MISMATCH] ticker=%s fill_id=%s cache_signed_yes_after=%s "
                    "!= exchange_signed_yes_after=%s. A second consecutive mismatch on a fresh snapshot will halt.",
                    market_id, getattr(fill_record, 'fill_id', None) or "unknown",
                    cache_signed_yes_after, exchange_signed_yes_after
                )

        # Record this fill's parity for the next comparison.  PASS and PENDING
        # reset the consecutive-mismatch counter.
        self._last_fill_parity[market_id] = parity

    def is_reconciliation_halted(self, ticker: str) -> bool:
        """Return True if the ticker has an unresolved exchange/ledger/cache mismatch.

        New entry orders should be rejected while this is True. Exits are not blocked.
        """
        return bool(self._reconciliation_halted.get(ticker, False))

    def _upsert_monitor_position(
        self,
        cached_position: CachedPosition,
        client_order_id: Optional[str],
        fill_id: Optional[str],
        fill_source: str,
        is_exit: bool,
        price_cents: int,
    ) -> None:
        """Build a Position from a CachedPosition and upsert it into the monitor.

        This is the single path for creating or updating a monitored position
        after a fill.  It preserves runtime state and provenance using
        PositionMonitor.upsert_position.
        """
        try:
            from merid.position_management.position_monitor import get_position_monitor
            from merid.position_management.position import Position, PositionSide, TrailingType

            monitor = get_position_monitor()

            side = cached_position.side
            market_id = cached_position.market_id
            side_enum = PositionSide.YES if (side or "").lower() == "yes" else PositionSide.NO

            # TP/SL target resolution: client_order_id, then fill_id, then cached fields.
            tp_targets = {}
            if client_order_id:
                tp_targets = self._pending_tp_targets.get(client_order_id, {}) or {}

            # Trailing stop profile config
            trailing_distance_cents = 5
            try:
                from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
                if is_profile_active():
                    adapter = get_active_profile()
                    profile = adapter.profile
                    trailing_distance_cents = getattr(profile, "trailing_stop_trailing_distance_cents", 5)
            except Exception:
                pass

            # Mandatory profit target (same logic as the original builder)
            mandatory_tp_price = None
            try:
                from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
                if is_profile_active():
                    adapter = get_active_profile()
                    profile = adapter.profile
                    if getattr(profile, "mandatory_profit_exit_enabled", False):
                        if price_cents < getattr(profile, "mandatory_profit_exit_threshold_low_cents", 30):
                            profit_pct = getattr(profile, "mandatory_profit_exit_target_pct_low", 0.30)
                        elif price_cents < getattr(profile, "mandatory_profit_exit_threshold_high_cents", 50):
                            profit_pct = getattr(profile, "mandatory_profit_exit_target_pct_mid", 0.25)
                        else:
                            profit_pct = getattr(profile, "mandatory_profit_exit_target_pct_high", 0.20)
                        mandatory_tp_price = price_cents + int((100 - price_cents) * profit_pct)
            except Exception:
                pass

            tp_r = tp_targets.get("tp_r") if tp_targets.get("tp_r") is not None else 1.0
            tp_price = tp_targets.get("tp_price") or cached_position.take_profit_price_cents

            # Fee-aware TP fallback: if no take-profit was propagated from the entry
            # intent, derive a conservative target that clears round-trip fees and the
            # minimum profit margin. A fallback TP below the fee buffer would be
            # rejected by the exit guard and leave the position unmonitored.
            if tp_price is None and price_cents and 0 < price_cents < 100:
                try:
                    from merid.event_venues.kalshi.fees import (
                        min_profitable_exit_price_cents,
                        MERID_TAKE_PROFIT_MIN_GROSS_PROFIT_CENTS,
                    )
                    from merid.position_management.position import TAKE_PROFIT_MIN_PROFIT_CENTS
                    entry_ref = int(price_cents)
                    size_fp = Decimal(cached_position.quantity_cc) / Decimal("100") if cached_position.quantity_cc else Decimal("0")
                    fee_aware_floor = min_profitable_exit_price_cents(
                        entry_ref,
                        size_fp,
                        gross_min_cents=TAKE_PROFIT_MIN_PROFIT_CENTS,
                    )
                    if fee_aware_floor is None:
                        raise ValueError("fee_aware_floor is None")
                    # Side-space: a position is long its own side and profit means the
                    # own-side price rises.  The fee-aware floor is already in the same
                    # price space as entry_ref, so it is the correct TP for both YES and NO.
                    tp_price = int(min(99, fee_aware_floor))
                    tp_r = tp_r or 1.5
                    logger.warning(
                        "[POSITION-CACHE-TP-FALLBACK] market=%s side=%s entry=%dc - "
                        "tp price missing, using fallback TP=%dc R=%.2f (SL=None)",
                        market_id, side, entry_ref, tp_price, tp_r,
                    )
                except Exception:
                    # Safe minimum gross-profit floor.  The constant is imported above
                    # in the try block; if that import itself failed, fall back to 5c.
                    _tp_floor = 5
                    try:
                        from merid.event_venues.kalshi.fees import MERID_TAKE_PROFIT_MIN_GROSS_PROFIT_CENTS
                        _tp_floor = MERID_TAKE_PROFIT_MIN_GROSS_PROFIT_CENTS
                    except Exception:
                        pass
                    tp_price = min(99, price_cents + _tp_floor)
                    tp_r = tp_r or 1.5

            final_tp_price = (
                mandatory_tp_price
                or tp_price
            )

            sl_original = tp_targets.get("sl_price")
            if sl_original is not None:
                sl_enabled = bool(tp_targets.get("sl_enabled", True))
            elif cached_position.stop_loss_price_cents is not None:
                sl_original = cached_position.stop_loss_price_cents
                sl_enabled = bool(cached_position.stop_loss_enabled)
            else:
                sl_enabled = bool(tp_targets.get("sl_enabled", True))
            final_sl_price = sl_original if (sl_enabled and sl_original is not None) else None

            # Scale-out target. Use 75% of the TP distance (matching the original
            # heuristic) but enforce a minimum gross profit that covers round-trip
            # taker fees and the configured minimum profit margin.
            risk_cents = abs(price_cents - final_sl_price) if final_sl_price is not None else 0
            if final_sl_price is not None and risk_cents > 0:
                scale_out_price = price_cents + int(risk_cents * 1.5)
            elif final_tp_price and final_tp_price > price_cents and side.lower() == "yes":
                scale_out_price = price_cents + int((final_tp_price - price_cents) * 0.75)
            else:
                scale_out_price = None

            if side.lower() == "yes" and price_cents and scale_out_price is not None:
                try:
                    from merid.event_venues.kalshi.fees import (
                        min_profitable_exit_price_cents,
                        MERID_EXIT_MIN_PROFIT_CENTS,
                    )
                    size_fp = Decimal(cached_position.quantity_cc) / Decimal("100") if cached_position.quantity_cc else Decimal("0")
                    _min_scale_out = min_profitable_exit_price_cents(
                        price_cents,
                        size_fp,
                        gross_min_cents=0,
                        net_min_cents=MERID_EXIT_MIN_PROFIT_CENTS,
                    )
                    if _min_scale_out is None:
                        scale_out_price = None
                    else:
                        _max_scale_out = final_tp_price - 1 if final_tp_price else 99
                        if _min_scale_out > _max_scale_out:
                            scale_out_price = None
                        else:
                            scale_out_price = max(_min_scale_out, min(scale_out_price, _max_scale_out, 99))
                except Exception:
                    pass

            # 2026-08-23: Trust the CachedPosition's provenance if it is already
            # known.  A residual position after a partial exit, or an add-to
            # position, must keep the original entry's original_persisted state so
            # its stop-loss remains active.  Only fall back to live-fill inference
            # when the cached record is still unknown.
            cached_risk_state = getattr(cached_position, "risk_params_state", "unknown")
            if cached_risk_state in ("original_persisted", "fallback"):
                monitor_risk_params_state = cached_risk_state
            else:
                has_entry_linkage = bool(
                    client_order_id or fill_id or cached_position.client_order_id or cached_position.entry_fill_id
                )
                is_trusted_live_fill = (
                    has_entry_linkage
                    and fill_id
                    and fill_source in ("ws", "http_poller", "alpha")
                )
                monitor_risk_params_state = "original_persisted" if is_trusted_live_fill else "unknown"

            series_ticker = market_id.split("-")[0] if "-" in market_id else market_id

            # Size is exact fractional contracts from canonical quantity_cc.
            size_fp = Decimal(cached_position.quantity_cc) / Decimal("100") if cached_position.quantity_cc else Decimal("0")

            monitor_position = Position(
                position_id=market_id,
                market_id=market_id,
                series_ticker=series_ticker,
                side=side_enum,
                size=size_fp,
                avg_entry_price_cents=cached_position.avg_price_cents,
                opened_at=cached_position.entry_fill_timestamp or datetime.now(timezone.utc),
                take_profit_price_cents=final_tp_price,
                # CRITICAL FIX (2026-08-25): Do not disable the stop-loss just
                # because no SL price is known.  Position.__post_init__ will
                # derive a fallback hard stop from the exchange-reported entry
                # price so REST-synced positions are protected.
                stop_loss_enabled=sl_enabled,
                stop_loss_price_cents=final_sl_price,
                risk_params_state=monitor_risk_params_state,
                risk_params_schema_version=2,
                trailing_type=TrailingType.FIXED_CENTS,
                trailing_param=trailing_distance_cents,
                scale_out_price_cents=scale_out_price,
                exit_policy_id=client_order_id or fill_id or "unknown",
                vol_regime=cached_position.vol_regime or "unknown",
                confidence=cached_position.confidence or "unknown",
                thesis_side=(side or "").lower(),
                outcome_side=(side or "").lower(),
                book_side=cached_position.book_side or "ask",
                entry_edge_pct=tp_targets.get("edge_pct") if tp_targets.get("edge_pct") is not None else cached_position.entry_edge_pct,
                fill_source=fill_source or cached_position.fill_source or "ws",
                entry_signal_id=tp_targets.get("entry_signal_id") or client_order_id or fill_id or "unknown",
                entry_model=tp_targets.get("entry_model") or cached_position.entry_model,
                entry_model_version=tp_targets.get("entry_model_version") or cached_position.entry_model_version,
                entry_model_probability=tp_targets.get("entry_model_probability") or cached_position.entry_model_probability,
                entry_market_probability=tp_targets.get("entry_market_probability") or cached_position.entry_market_probability,
                entry_edge=tp_targets.get("entry_edge") or cached_position.entry_edge,
                entry_book_snapshot_id=tp_targets.get("entry_book_snapshot_id") or cached_position.entry_book_snapshot_id,
                entry_fill_id=cached_position.entry_fill_id or fill_id,
                entry_order_id=tp_targets.get("entry_order_id") or client_order_id or cached_position.client_order_id,
                entry_execution_mode=tp_targets.get("entry_execution_mode") or cached_position.entry_execution_mode,
                client_order_id=client_order_id or cached_position.client_order_id,
                entry_intent_id=client_order_id or fill_id or cached_position.client_order_id,
                entry_executable_bid_cents=cached_position.entry_executable_bid_cents,
                entry_executable_ask_cents=cached_position.entry_executable_ask_cents,
                entry_book_capture_quality=cached_position.entry_book_capture_quality,
                entry_fill_price_cents=cached_position.entry_fill_price_cents or price_cents,
                entry_fill_timestamp=cached_position.entry_fill_timestamp,
                entry_book_timestamp=cached_position.entry_book_timestamp,
                entry_book_sequence=cached_position.entry_book_sequence,
                entry_book_source=cached_position.entry_book_source,
                entry_provenance_snapshot_id=cached_position.entry_provenance_snapshot_id,
                provenance_state=cached_position.provenance_state,
                position_version=cached_position.position_version or 1,
                position_key=cached_position.position_key,
                known_aliases=cached_position.known_aliases,
            )

            monitor.upsert_position(monitor_position, caller="position_cache")
        except Exception as monitor_err:
            logger.error(
                "[POSITION-MONITOR-INTEGRATION] CRITICAL: Failed to upsert position to monitor: %s",
                monitor_err,
                exc_info=True,
            )
            raise RuntimeError(f"Failed to upsert position to monitor: {monitor_err}")

    def _infer_thesis_side_from_fill_history(self, market_id: str) -> Optional[str]:
        """Infer thesis_side from fill history for positions with unknown side.

        When a position is synced from REST but not in the local cache, we cannot
        determine the correct YES/NO side from REST alone (Kalshi always reports
        side="yes").  We use the canonical KalshiFill record instead, which already
        carries the normalized MERID side/action from ingestion.

        Args:
            market_id: The market ID to look up fills for (ticker in this context).

        Returns:
            "yes", "no", or None if cannot be determined.
        """
        try:
            ledger = self._get_fills_ledger()
            if not ledger:
                return None

            # CRITICAL FIX 2026-08-09: KalshiFillsLedger exposes get_fills(market_ticker=...).
            # Use the canonical KalshiFill side/action (not raw_payload, which is Kalshi's
            # wire format and may not contain MERID intent fields).
            fills = ledger.get_fills(market_ticker=market_id, limit=10)

            if not fills:
                logger.debug("[POSITION-CACHE] No fill history found for market %s", market_id)
                return None

            for fill in fills:
                # CRITICAL FIX (2026-08-13): Prefer MERID-canonical side/action over raw
                # exchange side/action. The canonical fields are normalized at ingestion
                # and are not affected by Kalshi's legacy side-inversion ambiguity.
                action = (getattr(fill, 'canonical_position_action', None) or getattr(fill, 'action', '') or '').lower()
                side = (getattr(fill, 'canonical_position_side', None) or getattr(fill, 'side', '') or '').lower()

                if action == 'buy' and side in ('yes', 'no'):
                    logger.info(
                        "[POSITION-CACHE-INFERRED-SIDE] market=%s inferred thesis_side=%s from fill history (fill_id=%s)",
                        market_id, side, getattr(fill, 'fill_id', 'unknown')
                    )
                    return side

            logger.debug(
                "[POSITION-CACHE-SIDE-AWARE] Could not infer thesis_side from fill history for market %s",
                market_id
            )
            return None

        except Exception as e:
            logger.debug("[POSITION-CACHE] Error inferring thesis_side from fill history: %s", e)
            return None

    def _reset_stale_window_exposure(self) -> None:
        """Reset stale window exposure if position cache is empty.

        CRITICAL FIX: This prevents phantom exposure from blocking all trading
        after restart. If the position cache shows 0 open positions but window
        exposure is non-zero, it means exposure tracking is stale (positions
        were closed outside the system or before shutdown).

        This should be called during position cache initialization.
        """
        try:
            from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import (
                _WINDOW_TRACKING_STATE,
                _WINDOW_TRACKING_LOCK,
            )
            import time

            with _WINDOW_TRACKING_LOCK:
                total_exposure = _WINDOW_TRACKING_STATE["total_exposure_usd"]
                agent_exposure = _WINDOW_TRACKING_STATE["agent_exposure_usd"]

            # Only reset if exposure is non-zero but position cache is empty
            if total_exposure > 0.0 and len(self._positions) == 0:
                logger.warning(
                    f"[POSITION-CACHE] Stale window exposure detected: total=${total_exposure:.2f} "
                    f"agents={len(agent_exposure)} but position cache is empty. Resetting exposure."
                )
                from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import force_reset_window_exposure
                force_reset_window_exposure()
        except Exception as e:
            logger.warning("[POSITION-CACHE] Failed to reset stale window exposure: %s", e)

    def register_tp_targets(
        self,
        client_order_id: str,
        ticker: Optional[str] = None,
        asset: Optional[str] = None,
        outcome_side: Optional[str] = None,
        take_profit_price_cents: Optional[int] = None,
        take_profit_r_multiple: Optional[float] = None,
        stop_loss_price_cents: Optional[int] = None,
        stop_loss_enabled: bool = True,
        entry_price_cents: Optional[int] = None,
        vol_regime: Optional[str] = None,
        confidence: Optional[str] = None,
        entry_edge_pct: Optional[float] = None,
        entry_signal_id: Optional[str] = None,
        entry_model: Optional[str] = None,
        entry_model_version: Optional[str] = None,
        entry_model_probability: Optional[float] = None,
        entry_market_probability: Optional[float] = None,
        entry_edge: Optional[float] = None,
        entry_book_snapshot_id: Optional[str] = None,
        entry_execution_mode: Optional[str] = None,
        # CRITICAL FIX (2026-08-23): Edge-decay policy provenance.
        exit_policy_id: Optional[str] = None,
        window_resolution_id: Optional[str] = None,
        edge_decay_model: str = "none",
        edge_decay_parameters: Optional[Dict[str, Any]] = None,
        tp_capture_fraction: Optional[float] = None,
        minimum_remaining_edge: Optional[float] = None,
        sl_parameters: Optional[Dict[str, Any]] = None,
        market_close_time: Optional[datetime] = None,
        tp_policy_id: Optional[str] = None,
        sl_policy_id: Optional[str] = None,
        tp_policy_version: Optional[str] = None,
        sl_policy_version: Optional[str] = None,
        order_intent_id: Optional[str] = None,
        max_hold_seconds: Optional[int] = None,
    ) -> None:
        """Register TP targets, edge-decay policy and entry provenance for an order before it fills.

        Called by order_router when placing orders with TP targets.
        Targets are looked up by client_order_id when fills arrive.
        """
        # Canonicalize outcome_side; never silently default to YES.
        if outcome_side is not None:
            try:
                outcome_side = canonical_outcome_side(outcome_side).value
            except PositionDataError:
                logger.warning(
                    "[POSITION-CACHE-TP-REGISTER] client_order_id=%s: invalid outcome_side=%r; skipping provenance snapshot",
                    client_order_id,
                    outcome_side,
                )
                outcome_side = None

        self._pending_tp_targets[client_order_id] = {
            "tp_price": take_profit_price_cents,
            "tp_r": take_profit_r_multiple,
            "sl_price": stop_loss_price_cents,
            "sl_enabled": stop_loss_enabled,
            "entry_price": entry_price_cents,
            "vol_regime": vol_regime,
            "confidence": confidence,
            "edge_pct": entry_edge_pct,
            "entry_signal_id": entry_signal_id,
            "entry_model": entry_model,
            "entry_model_version": entry_model_version,
            "entry_model_probability": entry_model_probability,
            "entry_market_probability": entry_market_probability,
            "entry_edge": entry_edge,
            "entry_book_snapshot_id": entry_book_snapshot_id,
            "entry_execution_mode": entry_execution_mode,
            # CRITICAL FIX (2026-08-22): Capture the executable entry book so
            # reconstructed positions after restart have AT_FILL spread-stop provenance.
            "entry_executable_bid_cents": None,
            "entry_executable_ask_cents": None,
            "entry_book_capture_quality": "UNAVAILABLE",
            "entry_book_timestamp": None,
            "entry_book_sequence": None,
            "entry_book_source": None,
            "registered_at": replay_time(),
        }

        # CRITICAL FIX (2026-08-23): Persist a durable edge-decay policy snapshot
        # keyed by client_order_id. This survives process restarts and is re-linked
        # to REST positions via fills / client_order_id.
        if ENTRY_PROVENANCE_AVAILABLE and ticker and asset and outcome_side:
            try:
                snapshot = EntryProvenanceSnapshot(
                    snapshot_id=f"eps_{uuid.uuid4().hex[:12]}",
                    client_order_id=client_order_id,
                    ticker=ticker,
                    asset=asset,
                    outcome_side=outcome_side,
                    order_intent_id=order_intent_id or entry_signal_id,
                    exit_policy_id=exit_policy_id,
                    window_resolution_id=window_resolution_id,
                    tp_policy_id=tp_policy_id,
                    tp_policy_version=tp_policy_version,
                    sl_policy_id=sl_policy_id,
                    sl_policy_version=sl_policy_version,
                    entry_fair_value=entry_model_probability,
                    entry_market_value=entry_market_probability,
                    entry_edge=entry_edge or entry_edge_pct,
                    entry_price_cents=entry_price_cents,
                    edge_decay_model=edge_decay_model,
                    edge_decay_parameters=edge_decay_parameters or {},
                    tp_capture_fraction=tp_capture_fraction
                    if tp_capture_fraction is not None
                    else 0.75,
                    minimum_remaining_edge=minimum_remaining_edge
                    if minimum_remaining_edge is not None
                    else 0.02,
                    sl_parameters=sl_parameters or {},
                    market_close_time=market_close_time,
                    tp_price_cents=take_profit_price_cents,
                    sl_price_cents=stop_loss_price_cents,
                    take_profit_r_multiple=take_profit_r_multiple,
                    stop_loss_enabled=stop_loss_enabled,
                    max_hold_seconds=max_hold_seconds,
                )
                get_entry_provenance_store().register(snapshot)
            except Exception as ep_err:
                logger.warning("[POSITION-CACHE] Failed to register entry provenance snapshot: %s", ep_err)

        # Opportunistic GC every 100 registrations to keep the dict bounded.
        if len(self._pending_tp_targets) % 100 == 0:
            self._purge_stale_tp_targets()
        self._save_pending_tp_targets()

    def register_order_id_mapping(
        self, kalshi_order_id: str, client_order_id: str, client_tag: Optional[str] = None
    ) -> None:
        """Register Kalshi order_id -> client_order_id mapping for fill-to-intent linkage.

        Called by order_router after successful order submission.
        This is needed because HTTP fills from Kalshi API don't include client_order_id,
        only the Kalshi order_id. We use this mapping to recover the client_order_id
        (and optional client_tag alias) for TP-target and provenance lookup.
        """
        self._order_id_to_client_tag[kalshi_order_id] = client_order_id
        if client_tag and client_tag != client_order_id:
            self._order_id_to_client_tag[client_tag] = client_order_id
        self._persist_order_id_to_client_tag()

    def get_client_tag_for_order_id(self, kalshi_order_id: str) -> Optional[str]:
        """Recover the client_order_id that was sent with this order."""
        return self._order_id_to_client_tag.get(kalshi_order_id)

    def _persist_order_id_to_client_tag(self) -> None:
        """Persist the order_id -> client_tag map so restarts can resolve HTTP fills."""
        try:
            self._order_id_to_client_tag_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._order_id_to_client_tag_path, "w", encoding="utf-8") as f:
                json.dump(self._order_id_to_client_tag, f, indent=2, default=str)
        except Exception as exc:
            logger.warning("[POSITION-CACHE] Failed to persist order_id -> client_tag map: %s", exc)

    def _load_order_id_to_client_tag(self) -> None:
        """Load a previously-persisted order_id -> client_tag map."""
        try:
            if not self._order_id_to_client_tag_path.exists():
                return
            with open(self._order_id_to_client_tag_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                self._order_id_to_client_tag.update(payload)
                logger.debug(
                    "[POSITION-CACHE] Loaded %d order_id -> client_tag mappings",
                    len(self._order_id_to_client_tag),
                )
        except Exception as exc:
            logger.warning("[POSITION-CACHE] Failed to load order_id -> client_tag map: %s", exc)

    def _save_applied_fill_ids(self) -> None:
        """Persist applied fill ids so a restart does not re-apply durable fills."""
        try:
            self._applied_fill_ids_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._applied_fill_ids_path, "w", encoding="utf-8") as f:
                json.dump(dict(self._applied_fill_ids), f, indent=2, default=str)
        except Exception as exc:
            logger.warning("[POSITION-CACHE] Failed to persist applied fill ids: %s", exc)

    def _load_applied_fill_ids(self) -> None:
        """Load previously-persisted applied fill ids."""
        try:
            if not self._applied_fill_ids_path.exists():
                return
            with open(self._applied_fill_ids_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                self._applied_fill_ids.update(payload)
                logger.debug(
                    "[POSITION-CACHE] Loaded %d applied fill ids",
                    len(self._applied_fill_ids),
                )
        except Exception as exc:
            logger.warning("[POSITION-CACHE] Failed to load applied fill ids: %s", exc)

    def _save_pending_tp_targets(self) -> None:
        """Persist pending TP targets so entry provenance survives restarts."""
        try:
            self._pending_tp_targets_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._pending_tp_targets_path, "w", encoding="utf-8") as f:
                json.dump(self._pending_tp_targets, f, indent=2, default=str)
        except Exception as exc:
            logger.warning("[POSITION-CACHE] Failed to persist pending TP targets: %s", exc)

    def _load_pending_tp_targets(self) -> None:
        """Load previously-persisted pending TP targets from disk."""
        try:
            if not self._pending_tp_targets_path.exists():
                return
            with open(self._pending_tp_targets_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                return
            for coid, target in payload.items():
                if not isinstance(target, dict):
                    continue
                # Restore datetime fields that were serialized as ISO strings.
                if isinstance(target.get("entry_book_timestamp"), str):
                    try:
                        target["entry_book_timestamp"] = datetime.fromisoformat(
                            target["entry_book_timestamp"].replace("Z", "+00:00")
                        )
                    except Exception:
                        pass
                # Keep the newest registration if a duplicate is already in memory.
                existing = self._pending_tp_targets.get(coid)
                if existing and float(existing.get("registered_at", 0.0)) >= float(
                    target.get("registered_at", 0.0)
                ):
                    continue
                self._pending_tp_targets[coid] = target
            logger.debug(
                "[POSITION-CACHE] Loaded %d pending TP targets",
                len(self._pending_tp_targets),
            )
        except Exception as exc:
            logger.warning("[POSITION-CACHE] Failed to load pending TP targets: %s", exc)

    def _purge_stale_tp_targets(self, max_age_seconds: float = 86400.0) -> int:
        """Remove tp_target entries older than ``max_age_seconds`` (default 24h).

        Returns the number of entries removed. Called opportunistically from
        register_tp_targets and on demand from operators / tests.
        """
        cutoff = replay_time() - max_age_seconds
        stale_ids = [
            coid
            for coid, target in self._pending_tp_targets.items()
            if float(target.get("registered_at", 0.0)) < cutoff
        ]
        for coid in stale_ids:
            self._pending_tp_targets.pop(coid, None)
        if stale_ids:
            logger.info(
                "[TP-TARGET-GC] purged %d stale TP targets (>%ds old)",
                len(stale_ids), int(max_age_seconds),
            )
            self._save_pending_tp_targets()
        return len(stale_ids)

    def discard_tp_targets(self, client_order_id: str) -> bool:
        """Explicitly drop TP targets for a canceled / rejected order.

        Called by order_router when an order is canceled before any fill so
        the registry doesn't leak the (never-used) targets.
        """
        removed = self._pending_tp_targets.pop(client_order_id, None) is not None
        if removed:
            self._save_pending_tp_targets()
        return removed

    async def on_fill(
        self,
        market_id: str,
        contracts: int,
        price_cents: int,
        fee_cents: int,
        side: str,
        client_order_id: Optional[str] = None,
        fill_id: Optional[str] = None,
        action: str = "buy",
        is_exit: Optional[bool] = None,
        quantity_cc: Optional[int] = None,
        canonicalization_state: Optional[str] = None,
        yes_price_cents: Optional[int] = None,
        no_price_cents: Optional[int] = None,
    ) -> None:
        """Handle a fill event from WebSocket.

        BUG-FIX: Now async with mutex protection to prevent race conditions
        during concurrent WebSocket fill events.

        PRODUCTION FIX: Looks up TP targets by client_order_id for dynamic R-multiple exits.

        Task 1: Detect hedge fills by client_order_id prefix and log separately
        for exposure calculation accuracy.

        Task 2: Integrates with fills_ledger for authoritative fill_source lookup.

        FIX 3: Price repeat check to prevent duplicate execution via WebSocket path.
        """
        async with self._ensure_mutex():
            # 2026-08-13: Never apply a missing or untrusted canonicalization state to
            # live position math.  `None` means an unpatched producer, partial
            # deployment, stale persisted data, or a caller that failed to propagate
            # the field.  Such fills are retained for audit only and require a fresh
            # exchange REST snapshot before the ticker can be traded again.
            if canonicalization_state is None or canonicalization_state in ("UNTRUSTED_LEGACY", "UNTRUSTED_RAW", "UNTRUSTED_SIDE_CONFLICT"):
                if canonicalization_state is None:
                    canonicalization_state = "UNTRUSTED_RAW"
                self.require_rest_reconciliation(
                    market_id,
                    reason=f"missing_or_untrusted_canonicalization:{canonicalization_state}",
                )
                logger.warning(
                    "[POSITION-CACHE-UNTRUSTED-FILL] fill_id=%s market=%s state=%s | "
                    "Skipping live position application; retain for audit and reconcile via REST.",
                    fill_id, market_id, canonicalization_state,
                )
                return

            # CRITICAL 2026-08-09: Durable, exactly-once idempotency gate.
            # We check both the in-memory set and the canonical fills_ledger. The
            # ledger survives restarts, so replayed fills cannot re-create or re-close
            # positions after a process bounce.
            if fill_id:
                if fill_id in self._applied_fill_ids:
                    logger.warning(
                        "[POSITION-CACHE-IDEMPOTENCY] fill_id=%s already applied - skipping",
                        fill_id
                    )
                    return

                # 2026-08-25: Fail-safe for process restart. If a fill with this id
                # already exists in the durable fills_ledger and predates this cache
                # instance, it was applied by a previous process. Do not re-apply it;
                # the reconciler will rebuild the position from the ledger/exchange.
                if self._fills_ledger:
                    try:
                        _ledger_fill = self._fills_ledger.get_fill_by_id(fill_id)
                        if _ledger_fill and _ledger_fill.created_time:
                            _fill_ts = _ledger_fill.created_time.timestamp()
                            if _fill_ts < self._started_at - 5.0:
                                logger.warning(
                                    "[POSITION-CACHE-IDEMPOTENCY-LEDGER] fill_id=%s created at %.3f "
                                    "predates this process (started %.3f) - skipping re-application",
                                    fill_id, _fill_ts, self._started_at
                                )
                                self._applied_fill_ids[fill_id] = replay_time()
                                self._save_applied_fill_ids()
                                return
                    except Exception as _ledger_guard_err:
                        logger.debug("[POSITION-CACHE] Ledger predate guard failed (non-fatal): %s", _ledger_guard_err)

            # 2026-08-12: If a durable canonical KalshiFill record exists, prefer
            # its canonical side/action/price/yes-delta.  This prevents a caller
            # that passes the raw exchange action from inverting the position.
            fill_record = None
            _position_exchange_index = None
            fill_yes_price_cents = yes_price_cents
            fill_no_price_cents = no_price_cents
            if fill_id and self._fills_ledger:
                try:
                    fill_record = self._fills_ledger.get_fill_by_id(fill_id)
                    if fill_record:
                        if fill_record.canonical_position_side and fill_record.canonical_position_action:
                            side = fill_record.canonical_position_side
                            action = fill_record.canonical_position_action
                        if fill_record.canonical_leg_price_cents is not None:
                            price_cents = fill_record.canonical_leg_price_cents
                        fill_yes_price_cents = _fill_position_side_price_cents(fill_record, "yes") or yes_price_cents
                        fill_no_price_cents = _fill_position_side_price_cents(fill_record, "no") or no_price_cents
                        _position_exchange_index = getattr(fill_record, 'exchange_index', None)
                except Exception as ledger_err:
                    logger.debug("[POSITION-CACHE] Could not canonicalize from fill record: %s", ledger_err)

            # Fallback: if the caller only gave a single execution-side price and
            # side, record it on the known leg only.  The opposite leg is *not*
            # synthesized via 100 - price; a missing side-tagged price must come
            # from the fill record or the caller.  This prevents a single reported
            # execution price from being silently flipped into the wrong side's
            # price space.
            if fill_yes_price_cents is None and fill_no_price_cents is None and price_cents is not None and side in ("yes", "no"):
                if side == "yes":
                    fill_yes_price_cents = price_cents
                else:
                    fill_no_price_cents = price_cents
                logger.warning(
                    "[POSITION-CACHE-PRICE-LEG-PARTIAL] market=%s side=%s price=%dc - "
                    "only the reported leg price is available; opposite leg is unset",
                    market_id, side, price_cents,
                )

            # Preserve raw order form and pre-fill signed exposure for lifecycle audit.
            raw_side = side
            raw_action = action
            raw_contracts = contracts
            if quantity_cc is None:
                try:
                    quantity_cc = int(Decimal(str(contracts)) * Decimal("100"))
                except Exception:
                    quantity_cc = int(contracts) * 100
            raw_quantity_cc = quantity_cc

            pre_position = self._positions.get(market_id)
            pre_position_yes = pre_position._yes_exposure() if pre_position else 0
            if BINARY_PRICE_SPACE_AVAILABLE:
                fill_yes_delta = yes_delta(raw_action, raw_side, raw_quantity_cc)
            else:
                if (raw_action, raw_side) in {("buy", "yes"), ("sell", "no")}:
                    fill_yes_delta = raw_quantity_cc
                elif (raw_action, raw_side) in {("sell", "yes"), ("buy", "no")}:
                    fill_yes_delta = -raw_quantity_cc
                else:
                    fill_yes_delta = 0
            expected_post_yes = pre_position_yes + fill_yes_delta

            # Task 2: Look up fill_source from fills_ledger if fill_id provided
            fill_source = await self._lookup_fill_source(fill_id, client_order_id)

            # Resolve exit classification.
            # 1. Trust explicit is_exit from the caller (e.g. fills_ledger after
            #    normalizing against the originating intent).
            # 2. If no explicit hint but we have a fill_id, look up the canonical
            #    KalshiFill record. It now carries authoritative is_exit/reduce_only
            #    metadata from the recorded OrderIntent. This is the durable path
            #    that prevents an HTTP-poller replay of a WS exit from being
            #    re-inferred as a new entry.
            # 3. Only as a last resort fall back to source markers / position heuristics.
            #    A fill with no existing position and no authoritative metadata is
            #    flagged UNMATCHED_FILL; we still apply it for backward compatibility
            #    but log a warning so it can be tightened.
            if is_exit is None and fill_id and self._fills_ledger:
                try:
                    fill_record = self._fills_ledger.get_fill_by_id(fill_id)
                    if fill_record is not None:
                        # CRITICAL FIX (2026-08-10): Unknown fills are quarantined per AGENTS.md.
                        # They must not create positions, attach TP/SL, or update exposure/PnL.
                        if getattr(fill_record, "unmatched", False):
                            logger.warning(
                                "[POSITION-CACHE-QUARANTINE] fill_id=%s market=%s unmatched=True reason=%s - "
                                "skipping position/exposure application",
                                fill_id, market_id,
                                getattr(fill_record, "unmatched_reason", "unknown")
                            )
                            return
                        if fill_record.is_exit is not None:
                            is_exit = bool(fill_record.is_exit)
                            logger.debug(
                                "[POSITION-CACHE] Resolved is_exit=%s for fill_id=%s from fills_ledger intent record",
                                is_exit, fill_id
                            )
                except Exception as ledger_lookup_err:
                    logger.debug("[POSITION-CACHE] Could not resolve is_exit from fills_ledger: %s", ledger_lookup_err)

            if is_exit is None:
                from merid.event_venues.kalshi.exit_order_utils import is_exit_order_from_source
                source = fill_source or client_order_id or ""
                if is_exit_order_from_source(source):
                    is_exit = True
                else:
                    existing = self._positions.get(market_id)
                    if existing is None:
                        # CRITICAL (2026-08-09): Without an existing position or
                        # authoritative metadata we cannot safely classify a fill as
                        # an entry. Keep is_exit as None so the unmatched guard below
                        # can log it, but continue with the heuristic for legacy paths.
                        is_exit = False
                        logger.warning(
                            "[POSITION-CACHE-UNMATCHED-ENTRY] fill_id=%s market=%s has no existing position "
                            "and no authoritative is_exit metadata; treating as entry via heuristic fallback",
                            fill_id or "N/A", market_id
                        )
                    elif BINARY_PRICE_SPACE_AVAILABLE:
                        existing_yes = existing._yes_exposure()
                        fill_yes = yes_delta(action, side, raw_quantity_cc)
                        # An exit is a fill with the opposite signed exposure that does not flip.
                        is_exit = (
                            existing_yes != 0
                            and fill_yes != 0
                            and existing_yes * fill_yes < 0
                            and abs(fill_yes) <= abs(existing_yes)
                        )
                    elif (getattr(existing, 'thesis_side', existing.side) or existing.side).lower() == side.lower():
                        is_exit = False
                    else:
                        is_exit = True

            # VERIFICATION: Fill ingestion logging (outcome_side, book_side, action/side, StrategyPosition)
            # Log fill details for thesis_side invariant verification
            logger.info(
                "[FILL-INGESTION] fill_id=%s market_id=%s side=%s action=%s is_exit=%s contracts=%.2f price_cents=%d fill_source=%s",
                fill_id or "N/A", market_id, side, action, is_exit, quantity_cc / 100.0, price_cents, fill_source
            )

            # CRITICAL FIX (2026-07-07): Record window exposure on fill confirmation
            # Window exposure is now counted only when fills are confirmed, not at order submission.
            # This prevents phantom exposure accumulation from unfilled orders.
            try:
                from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
                # Extract agent_id from fills_ledger if available
                agent_id = None
                if fill_id and self._fills_ledger:
                    try:
                        fill_record = self._fills_ledger.get_fill_by_id(fill_id)
                        if fill_record:
                            agent_id = getattr(fill_record, 'agent_id', None)
                    except Exception as ledger_err:
                        logger.debug("[POSITION-CACHE] Could not get fill record for exposure: %s", ledger_err)

                # CRITICAL FIX (2026-07-07): Derive agent_id from ticker if missing
                # This ensures window exposure is tracked even when agent_id is not set in fill record
                # (e.g., HTTP fills without agent_id context)
                if not agent_id:
                    try:
                        from config.kalshi_crypto_config import kalshi_ticker_to_asset
                        asset = kalshi_ticker_to_asset(market_id)
                        if asset and asset.upper() in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
                            agent_id = f"{asset.upper()}_15M"
                            logger.debug(
                                "[POSITION-CACHE] Derived agent_id=%s from ticker=%s for window exposure tracking",
                                agent_id, market_id
                            )
                    except Exception as derive_err:
                        logger.debug("[POSITION-CACHE] Could not derive agent_id from ticker: %s", derive_err)

                # CRITICAL FIX (2026-07-13): Record exposure for entry orders only
                # Entry orders are those that are NOT exit orders (not just buy actions)
                # NO entry orders use sell action but still increase exposure
                # Use the same logic as order_router._is_exit_order for consistency
                # SEV-1 FIX: Hedge orders reduce net exposure, so they should be treated as exit orders
                # for exposure accounting purposes. This is now handled by exit_order_utils.py
                # which includes "hedge" and "hedge_engine" in EXIT_ORDER_MARKERS.
                if agent_id and not is_exit:
                    try:
                        envelope = get_kalshi_crypto_15m_risk_envelope()
                        # Use canonical quantity_cc to avoid Decimal/float TypeError and support fractional fills.
                        order_notional_usd = (quantity_cc * price_cents) / 10000.0

                        # CRITICAL FIX (2026-07-08): Release resting exposure and record execution exposure
                        # Resting exposure was recorded at placement time (order_gate, top3 gate)
                        # When order fills, we must release resting exposure and record execution exposure
                        # This prevents double-counting and ensures accurate window tracking
                        # CRITICAL FIX 2026-07-08: Extract asset for per-asset exposure tracking
                        from config.kalshi_crypto_config import kalshi_ticker_to_asset
                        asset = kalshi_ticker_to_asset(market_id) if market_id else None
                        envelope.release_resting_order_exposure(
                            agent_id=agent_id,
                            order_notional_usd=order_notional_usd
                        )
                        envelope.record_order_execution(
                            agent_id=agent_id,
                            order_notional_usd=order_notional_usd,
                            asset=asset
                        )

                        # 2026-07-13: Record fill in GlobalAllocator for per-asset position tracking
                        try:
                            from merid.risk.profiles.global_allocator import get_global_allocator
                            allocator = get_global_allocator()
                            if allocator and asset:
                                allocator.record_order_filled(asset, client_order_id or fill_id or "unknown", order_notional_usd)
                        except Exception as ga_exc:
                            logger.debug("[POSITION-CACHE] Failed to record fill in GlobalAllocator: %s", ga_exc)
                    except RuntimeError as e:
                        # Bankroll not ready - log warning but don't crash
                        logger.warning(
                            "[POSITION-CACHE] Failed to record window exposure: %s (bankroll service unavailable)",
                            e
                    )
                    logger.info(
                        "[POSITION-CACHE] Released resting exposure and recorded execution exposure on fill: agent=%s notional=$%.2f market=%s fill_id=%s",
                        agent_id, order_notional_usd, market_id, fill_id or "N/A"
                    )

                # SEV-0 FIX: Release window exposure for position-reducing fills (sell-side)
                # This ensures window exposure is released on partial closes and all exit paths
                # Previously, exposure was only released in remove_position(), missing partial closes
                # CRITICAL FIX (2026-07-13): Only release for true exit orders, not NO entry orders
                # Use the same logic as order_router._is_exit_order for consistency
                if agent_id and is_exit:
                    try:
                        envelope = get_kalshi_crypto_15m_risk_envelope()
                        # Calculate notional to release based on canonical centi-contracts closed.
                        position_notional_usd = (quantity_cc * price_cents) / 10000.0
                        # CRITICAL FIX 2026-07-08: Extract asset for per-asset exposure release
                        from config.kalshi_crypto_config import kalshi_ticker_to_asset
                        asset = kalshi_ticker_to_asset(market_id) if market_id else None
                        envelope.record_position_closure(
                            agent_id=agent_id,
                            position_notional_usd=position_notional_usd,
                            asset=asset
                        )
                        logger.info(
                            "[POSITION-CACHE] Released window exposure on sell fill: agent=%s notional=$%.2f market=%s fill_id=%s",
                            agent_id, position_notional_usd, market_id, fill_id or "N/A"
                        )

                        # CRITICAL FIX: 2026-07-09 - Release global slot allocator slot on position closure
                        # This allows re-entry within the same window when positions close early
                        try:
                            from merid.risk.global_slot_allocator import get_global_slot_allocator
                            slot_allocator = get_global_slot_allocator()

                            # CRITICAL FIX: Log slot allocator state before release for diagnostics
                            slot_summary = slot_allocator.get_summary()
                            logger.info(
                                "[POSITION-CACHE] Slot allocator state before release: total_exposure=$%.2f slot_count=%d asset=%s agent=%s market=%s",
                                slot_summary["total_exposure_usd"], slot_summary["slot_count"], asset, agent_id, market_id
                            )

                            # Release slot by asset (more precise than agent_id)
                            # Since exit orders bypass allocation, we release by asset to free up exposure
                            released_count = slot_allocator.release_by_asset(asset) if asset else 0
                            if released_count > 0:
                                logger.info(
                                    "[POSITION-CACHE] Released %d slot(s) from global allocator for asset=%s on sell fill",
                                    released_count, asset
                                )
                            else:
                                # CRITICAL FIX (2026-07-15): Log why asset release failed before using fallback
                                # This helps diagnose slot allocation issues
                                logger.warning(
                                    "[POSITION-CACHE] Asset release returned 0 slots for asset=%s agent=%s market=%s. "
                                    "This may indicate: 1) No slot was allocated for this position, 2) Asset mismatch, "
                                    "3) Slot already released. Using agent_id fallback as last resort.",
                                    asset, agent_id, market_id
                                )
                                # Fallback: try releasing by agent_id if asset release didn't work
                                # WARNING: If agent has multiple positions across assets, this may release wrong slots
                                released_count = slot_allocator.release_by_agent(agent_id)
                                if released_count > 0:
                                    logger.warning(
                                        "[POSITION-CACHE] Released %d slot(s) from global allocator for agent=%s on sell fill (fallback - may be incorrect if agent has multiple positions)",
                                        released_count, agent_id
                                    )
                                else:
                                    logger.warning(
                                        "[POSITION-CACHE] Agent release also returned 0 slots for agent=%s. "
                                        "Slot may have already been released or never allocated.",
                                        agent_id
                                    )

                            # CRITICAL FIX: Log slot allocator state after release for verification
                            slot_summary_after = slot_allocator.get_summary()
                            logger.info(
                                "[POSITION-CACHE] Slot allocator state after release: total_exposure=$%.2f slot_count=%d released=%d",
                                slot_summary_after["total_exposure_usd"], slot_summary_after["slot_count"], released_count
                            )

                            # 2026-07-13: Record position close in GlobalAllocator for per-asset tracking
                            try:
                                from merid.risk.profiles.global_allocator import get_global_allocator
                                allocator = get_global_allocator()
                                if allocator and asset:
                                    allocator.record_position_closed(asset)
                            except Exception as ga_exc:
                                logger.debug("[POSITION-CACHE] Failed to record position close in GlobalAllocator: %s", ga_exc)
                        except Exception as slot_err:
                            logger.warning(
                                "[POSITION-CACHE] Failed to release slot from global allocator: %s",
                                slot_err
                            )
                    except RuntimeError as e:
                        # Bankroll not ready - log warning but don't crash
                        logger.warning(
                            "[POSITION-CACHE] Failed to release window exposure on sell fill: %s (bankroll service unavailable)",
                            e
                        )
                    except Exception as e:
                        logger.error(
                            "[POSITION-CACHE] Failed to release window exposure on sell fill: %s",
                            e,
                            exc_info=True
                        )
            except Exception as exposure_err:
                logger.warning("[POSITION-CACHE] Failed to record window exposure on fill: %s", exposure_err)

            # PRODUCTION FIX: Recover client_order_id from order_id if not provided
            # HTTP fills from Kalshi API don't include client_order_id, only order_id
            # We use the order_id -> client_tag mapping registered at order submission time
            if not client_order_id and fill_id:
                # Try to get order_id from fills_ledger
                ledger = self._get_fills_ledger()
                if ledger:
                    fill_record = ledger.get_fill_by_id(fill_id)
                    if fill_record and fill_record.order_id:
                        client_order_id = self._order_id_to_client_tag.get(fill_record.order_id)
                        if client_order_id:
                            logger.debug(
                                "[FILL-INTENT-LINK] Recovered client_order_id=%s from order_id=%s for fill_id=%s",
                                client_order_id, fill_record.order_id, fill_id
                            )

            # Look up TP targets from pending registry if client_order_id provided.
            # P1 fix: use .get() not .pop() so partial fills on the same order
            # still see the TP target; the entry is purged either when the
            # position fully closes or by the TTL/explicit-discard paths.
            tp_targets = {}
            if client_order_id:
                tp_targets = self._pending_tp_targets.get(client_order_id, {}) or {}

            # CRITICAL FIX (2026-08-10): If tp_targets lack provenance, recover it
            # from the durable fill record so every position carries entry model
            # attribution even when the in-memory registry has been lost.
            if fill_id and self._fills_ledger:
                try:
                    fill_record = self._fills_ledger.get_fill_by_id(fill_id)
                    if fill_record:
                        for provenance_key in [
                            "entry_signal_id",
                            "entry_model",
                            "entry_model_version",
                            "entry_model_probability",
                            "entry_market_probability",
                            "entry_edge",
                            "entry_book_snapshot_id",
                            "entry_order_id",
                            "entry_execution_mode",
                        ]:
                            if not tp_targets.get(provenance_key):
                                value = getattr(fill_record, provenance_key, None)
                                if value is not None:
                                    tp_targets[provenance_key] = value
                        if not tp_targets.get("entry_fill_id"):
                            tp_targets["entry_fill_id"] = fill_id
                except Exception as ledger_err:
                    logger.debug("[POSITION-CACHE] Could not recover provenance from fill record: %s", ledger_err)

            position = self._positions.get(market_id)

            # Seed tp_price/tp_r from the registry and any existing cached position.
            # The fee-aware fallback is applied just before the CachedPosition is built.
            tp_r = tp_targets.get("tp_r") if tp_targets.get("tp_r") is not None else 1.0
            tp_price = tp_targets.get("tp_price") or (position.take_profit_price_cents if position else None)

            # V16: External trade classification - check if fill agent_id differs from position agent_id
            fill_agent_id = None
            if fill_id and self._fills_ledger:
                try:
                    fill_record = self._fills_ledger.get_fill_by_id(fill_id)
                    if fill_record:
                        fill_agent_id = getattr(fill_record, 'agent_id', None)
                except Exception as ledger_err:
                    logger.debug("[POSITION-CACHE] Could not get fill record for agent_id check: %s", ledger_err)

            # Check for external trade (non-15m agent or agent_id mismatch)
            if fill_agent_id and position:
                position_agent_id = getattr(position, 'agent_id', None)
                # 15m agents are: BTC_15M, ETH_15M, SOL_15M, XRP_15M, DOGE_15M
                is_15m_agent = fill_agent_id.endswith('_15M')
                if not is_15m_agent or (position_agent_id and fill_agent_id != position_agent_id):
                    # Record external trade in monitor
                    try:
                        from merid.event_venues.kalshi.thesis_side_monitor import get_thesis_side_monitor
                        monitor = get_thesis_side_monitor()
                        monitor.record_external_trade(
                            market_id=market_id,
                            fill_agent_id=fill_agent_id,
                            position_agent_id=position_agent_id,
                            fill_id=fill_id
                        )
                        # Skip processing external fills - don't attach to 15m position
                        logger.warning(
                            "[POSITION-CACHE-EXTERNAL-TRADE] Skipping external fill: market=%s fill_agent_id=%s position_agent_id=%s fill_id=%s",
                            market_id, fill_agent_id, position_agent_id, fill_id
                        )
                        return
                    except Exception as monitor_err:
                        logger.debug("[POSITION-CACHE] Could not record external trade in monitor: %s", monitor_err)

            # Log fill with linkage to order submission and position
            logger.info(
                "[FILL] fill_id=%s client_order_id=%s market=%s side=%s size=%d price=%dc position_id=%s",
                fill_id or "N/A", client_order_id or "N/A", market_id, side, contracts, price_cents,
                position.market_id if position else "NEW"
            )

            if position is None:
                # CRITICAL FIX (2026-07-21): Check if this is an exit order before creating new position
                # Exit orders should NOT create new positions - they close existing ones.
                # If an exit fill arrives with no existing position, it indicates a desynchronized state
                # (e.g., position was deleted prematurely, cache was reset, or race condition).
                # Creating a new position from an exit fill causes side inversion bugs where
                # SELL_NO exit orders are treated as BUY_NO entry orders, opening negative positions.
                is_exit_fill = is_exit

                if is_exit_fill:
                    # Exit fill without existing position - this is a desynchronized state
                    # Log critical error and reject the fill to prevent creating phantom positions
                    # CRITICAL: Include correlation IDs for tracing through router and upstream agent logic
                    correlation_id = client_order_id or fill_id or "unknown"
                    logger.critical(
                        "[POSITION-CACHE-EXIT-FILL-ERROR] market=%s side=%s action=%s contracts=%.2f price=%dc "
                        "client_order_id=%s fill_id=%s correlation_id=%s - EXIT FILL WITHOUT EXISTING POSITION. "
                        "This indicates a desynchronized state (position deleted prematurely, cache reset, or race condition). "
                        "Rejecting fill to prevent creating phantom position and side inversion bug. "
                        "Operator review required: upstream intent/position mismatch detected.",
                        market_id, side, action, quantity_cc / 100.0, price_cents,
                        client_order_id or "N/A", fill_id or "N/A", correlation_id
                    )

                    # CRITICAL FIX (2026-07-21): Send alert to Slack/PagerDuty/SMS for immediate operator awareness
                    try:
                        from utils.alerting import send_alert, AlertSeverity, AlertContext
                        send_alert(
                            condition="exit_fill_without_position",
                            severity=AlertSeverity.CRITICAL,
                            message=f"Exit fill without existing position rejected for {market_id}. Upstream intent/position mismatch detected.",
                            context=AlertContext(
                                current_value=contracts,
                                threshold_value=0,
                                correlation_id=correlation_id
                            )
                        )
                    except Exception as alert_err:
                        logger.warning("[POSITION-CACHE] Failed to send alert for exit fill without position: %s", alert_err)

                    # Do NOT create a new position - return early to prevent the bug
                    return

                # CRITICAL (2026-08-09): Removed the 2026-08-07 SELL-entry rejection.
                # All entry fills are canonicalized to signed YES exposure below,
                # which correctly handles cross-leg equivalence:
                #   BUY_YES / SELL_NO → long YES
                #   BUY_NO  / SELL_YES → long NO

                # Canonicalize the entry fill to signed YES exposure for V2 price-space conversion.
                # CRITICAL 2026-08-09: Use quantity_cc for exact fractional exposure.
                fill_qty_cc = quantity_cc if quantity_cc is not None else contracts * 100
                position_side_price = price_cents
                if BINARY_PRICE_SPACE_AVAILABLE:
                    fill_yes_delta = yes_delta(action, side, fill_qty_cc)
                    position_side, position_cc = from_signed_yes_exposure(fill_yes_delta)
                    if side != position_side:
                        converted = _fill_position_side_price_cents(fill_record, position_side) if fill_record else None
                        if converted is not None:
                            position_side_price = converted
                        elif fill_yes_price_cents is not None and fill_no_price_cents is not None:
                            position_side_price = fill_no_price_cents if position_side == "no" else fill_yes_price_cents
                        else:
                            logger.warning(
                                "[POSITION-CACHE-PRICE-MISSING-LEG] market=%s execution_side=%s position_side=%s "
                                "yes=%s no=%s - cannot convert fill price for new position; using raw price",
                                market_id, side, position_side, fill_yes_price_cents, fill_no_price_cents,
                            )
                    # The canonical exposure side is ``position_side``; keep the
                    # original execution side/action for ``apply_fill`` so its
                    # signed-YES delta is correct.  The position's thesis_side
                    # is set from the exposure side below.
                    contracts = int(quantity_cc / 100) if quantity_cc is not None else int(position_cc / 100)

                # CRITICAL FIX (2026-07-21): Set thesis_side from the canonical exposure
                # side, not the raw execution side.  SELL_NO / SELL_YES create long
                # positions in the opposite outcome, and the cached record must live in
                # the held side's price space.
                if BINARY_PRICE_SPACE_AVAILABLE and position_side in ("yes", "no"):
                    thesis_side_from_intent = position_side
                else:
                    thesis_side_from_intent = side

                # CRITICAL FIX (2026-07-21): Prevent mixed YES/NO legs at entry
                # If there's already a position on this ticker with a different thesis_side,
                # refuse to create a new position. This prevents mixing YES and NO intents
                # on the same ticker, which would create an invalid position state.
                if market_id in self._positions:
                    existing_position = self._positions[market_id]
                    if hasattr(existing_position, 'thesis_side'):
                        existing_thesis = existing_position.thesis_side.lower()
                        new_thesis = thesis_side_from_intent.lower()
                        if existing_thesis != new_thesis:
                            logger.critical(
                                "[POSITION-CACHE-MIXED-LEG-ALARM] Refusing to create mixed YES/NO position! "
                                "market=%s existing_thesis_side=%s new_thesis_side=%s - "
                                "Cannot mix YES and NO intents on the same ticker. "
                                "This would create an invalid position state. "
                                "Either treat as hedge or close existing position first.",
                                market_id, existing_thesis, new_thesis
                            )
                            # Do NOT create a new position - return early to prevent mixed legs
                            return
                        else:
                            # CRITICAL FIX (2026-08-01): Prevent adding to existing position (1 contract per position rule)
                            # If position already exists and has contracts, reject entry fill to prevent >1 contract
                            if existing_position.contracts > 0 and os.getenv("MERID_DISABLE_CONTRACT_LIMIT", "false").lower() not in ("true", "1", "yes"):
                                logger.critical(
                                    "[POSITION-CACHE-ENTRY-REJECT] market=%s existing_position_contracts=%d fill_contracts=%.2f - "
                                    "REJECTING entry fill to prevent >1 contract per position violation. "
                                    "This violates the $1 allocation rule limit. Position already exists.",
                                    market_id, existing_position.contracts, quantity_cc / 100.0
                                )
                                # Do NOT add to existing position - return early to prevent contract limit violation
                                return

                # DIRECTION POLICY (2026-08-07): Validate entry fill canonical
                # exposure side matches thesis_side (candidate_side).  Cross-leg
                # equivalence is prohibited - only BUY actions are allowed for entry.
                #
                # IMPORTANT: We use the fills_ledger's normalized user side/action, NOT the
                # raw Kalshi V2 payload.  Kalshi V2 fill payloads report the trade from the
                # taker/counterparty's point of view (e.g. a user BUY_NO fill is reported as
                # raw side=no, action=sell), so the raw payload would always appear inverted.
                # The fills_ledger already resolves the user's intended side/action from the
                # originating OrderIntent, so we compare against that authoritative record.
                if fill_id and self._fills_ledger and BINARY_PRICE_SPACE_AVAILABLE:
                    try:
                        fill_record = self._fills_ledger.get_fill_by_id(fill_id)
                        if fill_record:
                            # 2026-08-12: Use canonical fields, not raw exchange side/action.
                            record_side = getattr(fill_record, 'canonical_position_side', None) or side
                            record_action = getattr(fill_record, 'canonical_position_action', None) or action
                            record_count = getattr(fill_record, 'count_fp', None) or contracts
                            if record_side and record_action and record_side.lower() in ("yes", "no"):
                                try:
                                    record_count_int = int(float(record_count))
                                except Exception:
                                    record_count_int = contracts
                                canonical_intent_yes = yes_delta(record_action, record_side, record_count_int)
                                canonical_intent_side, _ = from_signed_yes_exposure(canonical_intent_yes)
                                if canonical_intent_side.lower() != thesis_side_from_intent.lower():
                                    logger.critical(
                                        "[FILL-SIDE-DESYNC] Entry fill side desynchronization detected! "
                                        "fill_id=%s market=%s thesis_side(candidate_side)=%s but fill canonical side=%s (record side=%s action=%s) - "
                                        "FILL-SIDE-DESYNC: entry fill does not match candidate_side! HALTING TRADING.",
                                        fill_id, market_id, thesis_side_from_intent, canonical_intent_side, record_side, record_action
                                    )
                                    # VERIFICATION: Record inversion in thesis_side_monitor
                                    try:
                                        from merid.event_venues.kalshi.thesis_side_monitor import get_thesis_side_monitor
                                        monitor = get_thesis_side_monitor()
                                        monitor.record_inversion(
                                            market_id=market_id,
                                            thesis_side=thesis_side_from_intent,
                                            inverted_side=record_side,
                                            fill_id=fill_id,
                                            context="entry_fill"
                                        )
                                    except Exception as monitor_err:
                                        logger.debug("[POSITION-CACHE] Could not record inversion in monitor: %s", monitor_err)
                                else:
                                    # Log successful validation for monitoring
                                    logger.info(
                                        "[FILL-SIDE-VALID] fill_id=%s market=%s thesis_side=%s canonical_side=%s record_side=%s action=%s - entry fill canonical side matches candidate_side",
                                        fill_id, market_id, thesis_side_from_intent, canonical_intent_side, record_side, record_action
                                    )
                    except Exception as invariant_err:
                        logger.debug("[POSITION-CACHE] Could not validate entry fill invariant: %s", invariant_err)

                # Extract agent_id from fills_ledger or derive from ticker for composite key
                position_agent_id = None
                if fill_id and self._fills_ledger:
                    try:
                        fill_record = self._fills_ledger.get_fill_by_id(fill_id)
                        if fill_record:
                            position_agent_id = getattr(fill_record, 'agent_id', None)
                    except Exception as ledger_err:
                        logger.debug("[POSITION-CACHE] Could not get fill record for agent_id: %s", ledger_err)

                # Derive agent_id from ticker if missing (for composite key)
                if not position_agent_id:
                    try:
                        from config.kalshi_crypto_config import kalshi_ticker_to_asset
                        asset = kalshi_ticker_to_asset(market_id)
                        if asset and asset.upper() in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
                            position_agent_id = f"{asset.upper()}_15M"
                            logger.debug(
                                "[POSITION-CACHE] Derived agent_id=%s from ticker=%s for position key",
                                position_agent_id, market_id
                            )
                    except Exception as derive_err:
                        logger.debug("[POSITION-CACHE] Could not derive agent_id from ticker: %s", derive_err)
                        position_agent_id = "unknown_agent"  # Fallback to prevent None

                # CRITICAL FIX (2026-08-01): Persist TP/SL from the original entry
                # intent.  If the intent does not carry an SL, do NOT invent one;
                # a fallback stop inside the entry spread causes an immediate
                # round-trip loss.  TP may still fall back because it is a profit
                # target, not a loss exit.
                # tp_price/tp_r were already resolved earlier with a fee-aware fallback,
                # but prefer the original tp_targets if they exist (e.g. a late HTTP
                # recovery). Do not overwrite an already-resolved value.
                if not tp_price:
                    tp_price = tp_targets.get("tp_price") or (position.take_profit_price_cents if position else None)
                if tp_r is None:
                    tp_r = tp_targets.get("tp_r")
                sl_original = tp_targets.get("sl_price")
                sl_enabled = bool(tp_targets.get("sl_enabled", True))

                # SL is only valid if it came from the original entry intent and
                # is not disabled upstream.
                if sl_enabled and sl_original is not None:
                    sl_price = sl_original
                else:
                    sl_price = None

                # CRITICAL FIX (2026-08-11): Capture the executable entry book at
                # fill time for spread-only exit invariants.  Only a book captured
                # contemporaneously (AT_FILL) is trusted; everything else is marked
                # POST_FILL or UNAVAILABLE and is not used to block a spread-only exit.
                entry_executable_bid_cents = None
                entry_executable_ask_cents = None
                entry_book_capture_quality = "UNAVAILABLE"
                entry_book_timestamp = None
                entry_book_sequence = None
                entry_book_source = None
                try:
                    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                    mkt_state = get_kalshi_market_state_store().get_unified(market_id)
                    if mkt_state and getattr(mkt_state, "book", None):
                        book = mkt_state.book
                        yes_bid = getattr(book, "best_yes_bid", None)
                        yes_ask = getattr(book, "best_yes_ask", None)
                        # Derive NO side from YES levels using Kalshi binary duality.
                        no_bid = (
                            book.no_bids[0].price_cents
                            if getattr(book, "no_bids", None)
                            else None
                        )
                        no_ask = (
                            100 - book.yes_bids[0].price_cents
                            if getattr(book, "yes_bids", None)
                            else None
                        )
                        # Fallback to legacy unified L1 fields if book primitives missing
                        if yes_bid is None:
                            yes_bid = getattr(mkt_state, "best_bid_cents", None)
                        if yes_ask is None:
                            yes_ask = getattr(mkt_state, "best_ask_cents", None)
                        if no_bid is None and yes_ask is not None:
                            no_bid = 100 - yes_ask
                        if no_ask is None and yes_bid is not None:
                            no_ask = 100 - yes_bid
                        if side.lower() == "yes":
                            entry_executable_bid_cents = yes_bid
                            entry_executable_ask_cents = yes_ask
                        else:
                            entry_executable_bid_cents = no_bid
                            entry_executable_ask_cents = no_ask

                        entry_book_sequence = getattr(book, "seq", None)
                        book_ts = getattr(book, "ts", None) or getattr(mkt_state, "book_updated_ts", None)
                        if book_ts:
                            entry_book_timestamp = datetime.fromtimestamp(book_ts, tz=timezone.utc)
                        entry_book_source = getattr(mkt_state, "source", None) or "market_state"

                        # Contemporaneous if the book is live and fresh right now.
                        # If the live book is slightly stale, fall back to the
                        # nearest pre-fill book as long as it is within the bounded
                        # freshness window.  This preserves stop-loss arming when
                        # a WS/RTI fill race prevents a perfectly AT_FILL capture.
                        book_age_s = getattr(mkt_state, "book_age_s", float('inf'))
                        if not mkt_state.book_stale and book_age_s < 1.0:
                            entry_book_capture_quality = "AT_FILL"
                        elif book_age_s <= MERID_ENTRY_BOOK_NEAR_PRE_FILL_MAX_AGE_S:
                            entry_book_capture_quality = "AT_FILL_OR_NEAREST_PRE_FILL"
                        else:
                            entry_book_capture_quality = "POST_FILL"
                except Exception as book_err:
                    logger.debug("[POSITION-CACHE] Could not capture entry executable book: %s", book_err)

                # CRITICAL FIX (2026-08-11): Record the captured entry executable book
                # in the pending TP targets so fills_ledger can carry the AT_FILL book
                # if it is still present at lookup time.
                # CRITICAL FIX (2026-08-22): Always write the TP target back so HTTP fills
                # that recovered client_order_id via order_id mapping still persist the
                # AT_FILL book.  Without this, restarts lose spread-stop provenance.
                if client_order_id:
                    if not tp_targets:
                        tp_targets = {}
                        self._pending_tp_targets[client_order_id] = tp_targets
                    tp_targets["entry_executable_bid_cents"] = entry_executable_bid_cents
                    tp_targets["entry_executable_ask_cents"] = entry_executable_ask_cents
                    tp_targets["entry_book_capture_quality"] = entry_book_capture_quality
                    tp_targets["entry_book_timestamp"] = entry_book_timestamp
                    tp_targets["entry_book_sequence"] = entry_book_sequence
                    tp_targets["entry_book_source"] = entry_book_source
                    self._save_pending_tp_targets()

                    # CRITICAL FIX (2026-08-23): Persist the captured AT_FILL book in the
                    # durable entry-provenance snapshot so REST-synced positions can recover
                    # spread-stop invariants without depending on the in-memory TP target map.
                    if ENTRY_PROVENANCE_AVAILABLE:
                        try:
                            eps = get_entry_provenance_store().get(client_order_id)
                            if eps:
                                eps.entry_fill_price_cents = price_cents
                                eps.entry_fill_timestamp = datetime.now(timezone.utc)
                                eps.entry_executable_bid_cents = entry_executable_bid_cents
                                eps.entry_executable_ask_cents = entry_executable_ask_cents
                                eps.entry_book_capture_quality = entry_book_capture_quality
                                eps.entry_book_timestamp = entry_book_timestamp
                                eps.entry_book_sequence = entry_book_sequence
                                eps.entry_book_source = entry_book_source
                                get_entry_provenance_store().register(eps)
                        except Exception as ep_book_err:
                            logger.debug(
                                "[POSITION-CACHE] Could not persist AT_FILL book to provenance store: %s",
                                ep_book_err,
                            )

                # A missing TP can be replaced with a default profit target.
                if tp_price is None:
                    try:
                        from merid.event_venues.kalshi.fees import min_profitable_exit_price_cents
                        from merid.position_management.position import TAKE_PROFIT_MIN_PROFIT_CENTS
                        entry_ref = position_side_price if position_side_price > 0 else tp_targets.get("entry_price", 50)
                        size_fp = Decimal(self.quantity_cc) / Decimal("100") if self.quantity_cc else Decimal("0")
                        fee_aware_floor = min_profitable_exit_price_cents(
                            entry_ref,
                            size_fp,
                            gross_min_cents=TAKE_PROFIT_MIN_PROFIT_CENTS,
                        )
                        if fee_aware_floor is None:
                            raise ValueError("fee_aware_floor is None")
                        margin = fee_aware_floor - entry_ref
                        if side.lower() == "yes":
                            tp_price = int(min(99, fee_aware_floor))
                        else:
                            tp_price = int(max(1, entry_ref - margin))
                        tp_r = tp_r or 1.5
                        logger.warning(
                            "[POSITION-CACHE-TP-FALLBACK] market=%s side=%s entry=%dc - "
                            "tp price missing, using fallback TP=%dc R=%.2f (SL=None)",
                            market_id, side, entry_ref, tp_price, tp_r,
                        )
                    except Exception:
                        entry_ref = position_side_price if position_side_price > 0 else tp_targets.get("entry_price", 50)
                        if side.lower() == "yes":
                            tp_price = min(99, entry_ref + TAKE_PROFIT_MIN_PROFIT_CENTS)
                        else:
                            tp_price = max(1, entry_ref - TAKE_PROFIT_MIN_PROFIT_CENTS)
                        tp_r = tp_r or 1.5

                # CRITICAL FIX (2026-08-13): Mark risk parameter provenance.
                # A trusted live entry has a client_order_id, fill_id, and a captured
                # entry book.  The presence of a stop-loss is optional; take-profit
                # and time-exit policies are still active for TP-only trusted entries.
                # REST-synthetic or unmatched fills remain unknown.
                has_entry_linkage = bool(client_order_id or fill_id)
                is_trusted_live_entry = (
                    has_entry_linkage
                    and (not is_exit)
                    and fill_id
                    and fill_source in ("ws", "http_poller", "alpha")
                )
                risk_params_state = (
                    "original_persisted"
                    if is_trusted_live_entry
                    else "unknown"
                )

                # CRITICAL FIX (2026-08-23): Resolve durable edge-decay policy snapshot.
                provenance_snapshot = None
                provenance_state = ProvenanceState.UNKNOWN_PROVENANCE
                fill_order_id = getattr(fill_record, 'order_id', None) if fill_record else None
                if client_order_id and ENTRY_PROVENANCE_AVAILABLE:
                    try:
                        provenance_snapshot = get_entry_provenance_store().get(client_order_id)
                        if provenance_snapshot:
                            provenance_state = ProvenanceState.PROVENANCE_RECOVERED
                            # Stamp actual fill time on the snapshot for edge-decay
                            # and executable edge calculations.
                            provenance_snapshot.entry_fill_time = datetime.now(timezone.utc)
                            # If the caller gave us a fill ID, stamp the snapshot
                            # order intent ID for audit.
                            if fill_id:
                                provenance_snapshot.order_intent_id = (
                                    provenance_snapshot.order_intent_id or client_order_id or fill_id
                                )
                        # Link the snapshot to this fill's order_id/fill_id for later
                        # REST provenance recovery.
                        get_entry_provenance_store().register_fill_linkage(
                            client_order_id=client_order_id,
                            order_id=fill_order_id,
                            fill_id=fill_id,
                        )
                    except Exception as ep_lookup_err:
                        logger.debug("[POSITION-CACHE] Provenance snapshot lookup failed: %s", ep_lookup_err)

                new_position = CachedPosition(
                    market_id=market_id,
                    agent_id=position_agent_id,  # Composite key component
                    exchange_index=_position_exchange_index,
                    contracts=contracts,
                    quantity_cc=quantity_cc,
                    side=thesis_side_from_intent,
                    thesis_side=thesis_side_from_intent,  # Immutable strategy thesis
                    outcome_side=thesis_side_from_intent,
                    book_side="ask",
                    # CRITICAL FIX (2026-07-23): Use persisted entry price as fallback if fill price is missing/invalid
                    avg_price_cents=tp_targets.get("entry_price") if (position_side_price is None or position_side_price == 0) else position_side_price,
                    entry_price_state="known" if (position_side_price is not None and position_side_price > 0) else "fallback",  # CRITICAL FIX (2026-07-23): Track if using fallback
                    take_profit_price_cents=tp_price,  # CRITICAL FIX (2026-08-01): Use computed fallback if tp_targets empty
                    take_profit_r_multiple=tp_r,  # CRITICAL FIX (2026-08-01): Use computed fallback if tp_targets empty
                    stop_loss_enabled=sl_enabled,
                    stop_loss_price_cents=sl_price,  # CRITICAL FIX (2026-08-01): Use computed fallback if tp_targets empty
                    fill_source=fill_source,  # Task 1: Track fill source
                    client_order_id=client_order_id,  # Task 1: Store for hedge detection
                    entry_intent_id=client_order_id or fill_id or "unknown",  # For RoundTripMonitor tracking
                    # CRITICAL FIX (2026-08-11): Persist original risk parameter provenance.
                    risk_params_state=risk_params_state,
                    risk_params_schema_version=2,
                    # CRITICAL FIX (2026-08-11): Immutable fill and entry book metadata.
                    entry_fill_price_cents=position_side_price,
                    entry_fill_timestamp=datetime.now(timezone.utc),
                    entry_book_timestamp=entry_book_timestamp,
                    entry_book_sequence=entry_book_sequence,
                    entry_book_source=entry_book_source,
                    entry_book_capture_quality=entry_book_capture_quality,
                    # CRITICAL FIX (2026-08-01): Store vol_regime and confidence from tp_targets
                    vol_regime=tp_targets.get("vol_regime") or "unknown",
                    confidence=tp_targets.get("confidence") or "unknown",
                    # CRITICAL FIX (2026-08-07): Store entry edge percentage from tp_targets
                    entry_edge_pct=tp_targets.get("edge_pct") or 0.03,
                    # CRITICAL FIX (2026-08-10): Durable entry-model provenance for exit attribution
                    entry_signal_id=tp_targets.get("entry_signal_id") or fill_id,
                    entry_model=tp_targets.get("entry_model"),
                    entry_model_version=tp_targets.get("entry_model_version"),
                    entry_model_probability=tp_targets.get("entry_model_probability"),
                    entry_market_probability=tp_targets.get("entry_market_probability"),
                    entry_edge=tp_targets.get("entry_edge"),
                    entry_book_snapshot_id=tp_targets.get("entry_book_snapshot_id"),
                    entry_fill_id=fill_id,
                    entry_order_id=tp_targets.get("entry_order_id"),
                    entry_execution_mode=tp_targets.get("entry_execution_mode"),
                    # CRITICAL FIX (2026-08-11): Executable entry book for spread-only exit invariants
                    entry_executable_bid_cents=entry_executable_bid_cents,
                    entry_executable_ask_cents=entry_executable_ask_cents,
                    # Ratchet profit floor initialization (defaults to inactive)
                    ratchet_activated=False,
                    ratchet_floor_price_cents=None,
                    ratchet_activation_timestamp=None,
                    # CRITICAL FIX (2026-08-23): Durable edge-decay policy provenance.
                    entry_provenance_snapshot_id=provenance_snapshot.snapshot_id if provenance_snapshot else None,
                    tp_policy_id=(provenance_snapshot.tp_policy_id if provenance_snapshot else None),
                    tp_policy_version=(provenance_snapshot.tp_policy_version if provenance_snapshot else None),
                    sl_policy_id=(provenance_snapshot.sl_policy_id if provenance_snapshot else None),
                    sl_policy_version=(provenance_snapshot.sl_policy_version if provenance_snapshot else None),
                    provenance_state=provenance_state.value,
                )

                # Phase 5.4: Record entry in RoundTripMonitor with calibration data
                try:
                    from merid.event_venues.kalshi.round_trip_monitor import get_round_trip_monitor, EntryRecord
                    rt_monitor = get_round_trip_monitor()

                    # Extract raw_logit and agent_id from fills_ledger if available
                    raw_logit = None
                    agent_id = None
                    if fill_id and self._fills_ledger:
                        try:
                            fill_record = self._fills_ledger.get_fill_by_id(fill_id)
                            if fill_record:
                                raw_logit = getattr(fill_record, 'raw_logit', None)
                                agent_id = getattr(fill_record, 'agent_id', None)
                        except Exception as ledger_err:
                            logger.debug("[POSITION-CACHE] Could not get fill record for calibration: %s", ledger_err)

                    # Record entry for round-trip tracking
                    entry_record = EntryRecord(
                        intent_id=client_order_id or fill_id or "unknown",
                        ticker=market_id,
                        asset=market_id.split("-")[0].replace("KX", "") if "-" in market_id else "UNKNOWN",
                        timestamp=datetime.utcnow(),
                        price_cents=position_side_price,
                        count=contracts,
                        action=action,
                        risk_tier="A",  # Default risk tier
                        window_resolution_id="default",
                        exit_policy_id="default",
                        raw_logit=raw_logit,  # Phase 5.4: Raw logit for calibration
                        agent_id=agent_id,  # Phase 5.4: Agent ID for outcome recording
                    )
                    rt_monitor.record_entry(entry_record)
                except Exception as rt_err:
                    logger.warning("[POSITION-CACHE] Failed to record entry in RoundTripMonitor: %s", rt_err)
                self._positions[market_id] = new_position

                # CRITICAL FIX (2026-08-23): Attach canonical position key to the cached
                # position. Asset aliases (XRP15M, KXXRP15M) are not identities.
                if POSITION_KEY_AVAILABLE:
                    new_position.position_key = PositionKey(market_ticker=market_id)
                    new_position.known_aliases = [market_id]

                # CRITICAL FIX: Add position to PositionMonitor for TP/SL enforcement
                # This wires the position cache into the exit policy system
                # OFFSET HEDGING: Check if hedging is needed for this fill
                # Only hedge alpha positions (fill_source != "hedge")
                if fill_source != "hedge":
                    try:
                        from merid.event_venues.kalshi.offset_hedging import handle_fill_for_hedging
                        from merid.event_venues.kalshi.bankroll_service_v2 import get_bankroll_service

                        # Get current bankroll for hedge sizing (async version)
                        bankroll_service = await get_bankroll_service()
                        bankroll_usd = 100.0  # Default fallback
                        if bankroll_service:
                            try:
                                equity = await bankroll_service.get_equity_for_risk_calc()
                                bankroll_usd = float(equity) if equity is not None else 100.0
                            except Exception as equity_err:
                                logger.debug("[POSITION-CACHE] Could not get equity for hedging: %s", equity_err)

                        # Get edge from fills_ledger if available
                        edge_pct = 0.0
                        if fill_id and self._fills_ledger:
                            try:
                                fill_record = self._fills_ledger.get_fill_by_id(fill_id)
                                if fill_record:
                                    edge_pct = getattr(fill_record, 'edgepct', 0.0) or 0.0
                            except Exception as edge_err:
                                logger.debug("[POSITION-CACHE] Could not get edge for hedging: %s", edge_err)

                        # CRITICAL FIX (2026-08-01): If edge is 0, compute fallback from fill price
                        # This ensures hedging always has a valid edge value (should never be 0)
                        if edge_pct == 0.0 and price_cents > 0:
                            # Compute edge as distance from mid (50c)
                            # YES: edge = price - 50 (positive when above mid)
                            # NO: edge = 50 - price (positive when below mid)
                            if side.lower() == "yes":
                                edge_pct = (price_cents - 50) / 100.0  # Convert cents to fraction
                            else:
                                edge_pct = (50 - price_cents) / 100.0  # Convert cents to fraction
                            logger.warning(
                                "[POSITION-CACHE-EDGE-FALLBACK] fill_id=%s market=%s side=%s edge=0 - "
                                "computed fallback edge=%.4f from price=%dc (distance from 50c mid)",
                                fill_id, market_id, side, edge_pct, price_cents
                            )

                        # Trigger hedging check (fire and forget - don't block position update)
                        asyncio.create_task(handle_fill_for_hedging(
                            market_id, side, edge_pct, price_cents, contracts, bankroll_usd
                        ))
                        logger.info(
                            "[OFFSET-HEDGING] Hedging check triggered: ticker=%s side=%s edge=%.4f count=%.2f",
                            market_id, side, edge_pct, quantity_cc / 100.0
                        )
                    except Exception as hedge_err:
                        logger.warning("[POSITION-CACHE] Failed to trigger hedging: %s", hedge_err)

                # Add/upsert position in PositionMonitor for TP/SL enforcement.
                # 2026-08-23: Centralized in _upsert_monitor_position so every fill
                # (new, added-to, or residual) uses the same provenance logic.
                self._upsert_monitor_position(
                    cached_position=new_position,
                    client_order_id=client_order_id,
                    fill_id=fill_id,
                    fill_source=fill_source,
                    is_exit=bool(is_exit),
                    price_cents=price_cents,
                )

                # Log entry timing for audit (correlate with [SCHEDULER-CHECK] for full timing metrics)
                # Calculate TCA metrics: arrival price slippage and early cost
                asset = market_id.split("-")[0].replace("KX", "") if "-" in market_id else "UNKNOWN"

                # Get arrival price (mid price at fill time) for slippage calculation
                arrival_price_cents = price_cents  # Default to fill price if state unavailable
                try:
                    from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
                    state = get_kalshi_market_state_store().get_unified(market_id)
                    if state and state.mid_cents > 0:
                        arrival_price_cents = state.mid_cents
                except Exception as arrival_err:
                    logger.debug("[ENTRY-TIMING] Could not get arrival price from market state: %s", arrival_err)

                # Calculate slippage cost (difference between fill and arrival price)
                # For YES: positive slippage = paid more than mid (bad)
                # For NO: positive slippage = received less than mid (bad)
                slippage_cents = 0
                if side.lower() == "yes":
                    slippage_cents = price_cents - arrival_price_cents
                else:
                    slippage_cents = arrival_price_cents - price_cents

                # Calculate early cost as multiple of risk (R)
                # R is the stop-loss distance from entry
                sl_price = tp_targets.get('sl_price') or 0
                if sl_price > 0:
                    # CRITICAL FIX (2026-08-04): Long positions: SL below entry for both sides,
                    # so R = entry - SL (positive for a valid stop).
                    r_distance = price_cents - sl_price
                    early_cost_r = slippage_cents / r_distance if r_distance > 0 else 0.0
                else:
                    early_cost_r = 0.0

                # For best_price_after, we'll need to track this asynchronously
                # For now, use arrival price as placeholder (will be updated by background task)
                best_price_after = arrival_price_cents

                logger.info(
                    "[ENTRY-TIMING] position_id=%s asset=%s ticker=%s side=%s size=%d entry_price=%dc "
                    "entry_timestamp=%s best_price_after=%dc early_cost_cents=%dc early_cost_r=%.3f",
                    market_id, asset, market_id, side, contracts, price_cents,
                    datetime.utcnow().isoformat(),
                    best_price_after,
                    slippage_cents,
                    early_cost_r
                )
                # Task 1: Different log message for hedge vs alpha
                if fill_source == "hedge":
                    logger.info(
                        "[POSITION-CACHE-HEDGE] opened {side} position on {market}: {contracts} @ {price}¢ "
                        "source=hedge client_id={client_id}",
                        side=side, market=market_id, contracts=contracts, price=price_cents,
                        client_id=client_order_id
                    )
                else:
                    # CRITICAL FIX (2026-08-01): Use actual TP/SL from position or fallback to tp_targets
                    # The tp_targets lookup may fail if client_order_id doesn't match registration key
                    # Use the position's stored TP/SL values as the primary source of truth
                    tp_price = new_position.take_profit_price_cents or tp_targets.get('tp_price') or 0
                    sl_price = new_position.stop_loss_price_cents or tp_targets.get('sl_price') or 0
                    tp_r = tp_targets.get('tp_r') or 0.0

                    # CRITICAL FIX (2026-08-01): Calculate tp_r from actual TP/SL prices if tp_r is 0.0
                    # This ensures r_multiple is never 0.00 when valid TP/SL prices exist
                    if tp_r == 0.0 and tp_price > 0 and sl_price > 0:
                        # Calculate R-multiple from actual TP and SL prices
                        # Side-space: a long position is long its own side.  Risk is the
                        # distance from entry toward the stop, profit is the distance from
                        # entry toward the take-profit, for both YES and NO.
                        risk_distance = price_cents - sl_price
                        profit_distance = tp_price - price_cents

                        if risk_distance > 0:
                            tp_r = profit_distance / risk_distance
                        else:
                            tp_r = 1.5  # Default fallback if calculation fails

                    # CRITICAL FIX (2026-08-01): Use stored vol_regime and confidence from position
                    # This ensures valid values even if fills_ledger lookup fails
                    vol_regime = new_position.vol_regime or "unknown"
                    confidence = new_position.confidence or "unknown"

                    logger.info(
                        "[TP-SL-ARMED] market=%s side=%s entry=%dc tp=%dc sl=%dc r_multiple=%.2f vol_regime=%s confidence=%s",
                        market_id, side, price_cents, tp_price, sl_price, tp_r, vol_regime, confidence
                    )
                    logger.debug(
                        f"Position cache: opened {side} position on {market_id}: {contracts} @ {price_cents}¢ "
                        f"TP={tp_targets.get('tp_price')}¢ ({tp_targets.get('tp_r')}R)"
                    )

                # OPT-IN: Submit resting bracket orders (GTC sell limit at TP price).
                # Gated by MERID_RESTING_BRACKETS_ENABLED to prevent unintended live
                # orders during initial rollout. Skipped for hedge positions (handled
                # by the hedge auto-exit loop).
                if (
                    fill_source != "hedge"
                    and new_position.take_profit_price_cents
                    and os.getenv("MERID_RESTING_BRACKETS_ENABLED", "false").lower() in ("true", "1", "yes")
                ):
                    try:
                        await self._submit_resting_bracket(new_position)
                    except Exception as bx_exc:
                        logger.warning(
                            "[BRACKET] failed to submit resting bracket for %s: %s",
                            market_id, bx_exc,
                        )

                # Mark this fill as applied now that the new position is committed.
                if fill_id:
                    self._applied_fill_ids[fill_id] = replay_time()
                    if len(self._applied_fill_ids) > self._applied_fill_ids_max:
                        evict_count = len(self._applied_fill_ids) // 2
                        for _ in range(evict_count):
                            self._applied_fill_ids.popitem(last=False)
                    self._save_applied_fill_ids()
            else:
                # Update existing
                pre_contracts = position.contracts
                pre_quantity_cc = position.quantity_cc

                # INVARIANT CHECK: Validate fill matches the existing position in signed
                # YES exposure.  A valid add/entry shares the position sign; a valid
                # close has the opposite sign and does not flip; anything else is an
                # inversion that must be flagged.
                if BINARY_PRICE_SPACE_AVAILABLE and fill_id and self._fills_ledger:
                    try:
                        fill_record = self._fills_ledger.get_fill_by_id(fill_id)
                        if fill_record and hasattr(fill_record, 'raw_payload'):
                            import json
                            raw_payload = fill_record.raw_payload
                            if raw_payload:
                                payload = json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
                                intent_side = payload.get('side', '')
                                intent_action = payload.get('action', action)
                                if intent_side and intent_action and intent_side.lower() in ("yes", "no"):
                                    try:
                                        intent_count = int(payload.get('count', payload.get('count_fp', contracts)))
                                    except Exception:
                                        intent_count = contracts
                                    fill_qty_cc = fill_record.quantity_cc or (intent_count * 100)
                                    fill_action = fill_record.canonical_position_action or intent_action
                                    fill_side = fill_record.canonical_position_side or intent_side
                                    fill_yes = fill_record.canonical_yes_delta_cc or yes_delta(fill_action, fill_side, fill_qty_cc)
                                    position_yes = position._yes_exposure()

                                    if position_yes * fill_yes < 0:
                                        # Opposite sign: this is a close or a reversal
                                        if abs(fill_yes) > abs(position_yes):
                                            logger.critical(
                                                "[POSITION-CACHE-INVARIANT-ALARM] Exit fill would flip position! "
                                                "fill_id=%s market=%s position_yes=%d fill_yes=%d - "
                                                "exit fill is larger than the position and would invert exposure.",
                                                fill_id, market_id, position_yes, fill_yes,
                                            )
                                    elif position_yes * fill_yes > 0:
                                        # Same sign: this is adding to the position (should be an entry/add)
                                        if is_exit:
                                            logger.critical(
                                                "[POSITION-CACHE-INVARIANT-ALARM] Exit fill would add to position! "
                                                "fill_id=%s market=%s position_yes=%d fill_yes=%d - "
                                                "classified as exit but signed exposure is on the same side as the position.",
                                                fill_id, market_id, position_yes, fill_yes,
                                            )
                                    else:
                                        logger.critical(
                                            "[POSITION-CACHE-INVARIANT-ALARM] Fill has zero signed exposure! "
                                            "fill_id=%s market=%s action=%s side=%s count=%.2f - "
                                            "cannot determine position effect.",
                                            fill_id, market_id, intent_action, intent_side, float(intent_count),
                                        )
                    except Exception as invariant_err:
                        logger.debug("[POSITION-CACHE] Could not validate exit fill invariant: %s", invariant_err)

                # Mark this fill as applied in the in-memory idempotency set.
                if fill_id:
                    self._applied_fill_ids[fill_id] = replay_time()
                    if len(self._applied_fill_ids) > self._applied_fill_ids_max:
                        evict_count = len(self._applied_fill_ids) // 2
                        for _ in range(evict_count):
                            self._applied_fill_ids.popitem(last=False)
                    self._save_applied_fill_ids()

                position.apply_fill(
                    contracts,
                    price_cents,
                    fee_cents,
                    side,
                    action=action,
                    is_exit=is_exit,
                    quantity_cc=quantity_cc,
                    yes_price_cents=fill_yes_price_cents,
                    no_price_cents=fill_no_price_cents,
                )
                logger.debug(
                    f"Position cache: updated {market_id}: action={action} side={side} "
                    f"{pre_contracts}->{position.contracts} contracts"
                )

                # 2026-08-12: Emit FILL-CANONICALIZATION log with exchange/cache parity
                # check.  Any divergence fail-closes the ticker to new entries.
                await self._log_fill_canonicalization(
                    market_id=market_id,
                    fill_record=fill_record,
                    side=side,
                    action=action,
                    quantity_cc=quantity_cc,
                    price_cents=price_cents,
                    position=position,
                    pre_position_yes=pre_position_yes,
                )

                # 2026-08-23: Keep PositionMonitor in sync on every fill (partial adds,
                # partial closes, and residual positions).  The monitor's upsert
                # preserves runtime state and provenance.
                if position.quantity_cc > 0:
                    self._upsert_monitor_position(
                        cached_position=position,
                        client_order_id=client_order_id,
                        fill_id=fill_id,
                        fill_source=fill_source,
                        is_exit=bool(is_exit),
                        price_cents=price_cents,
                    )

                # P0 Task 2: cancel resting brackets when position is fully closed
                # so stale TP/SL orders don't keep sitting on the book and trigger
                # phantom re-entry.
                # CRITICAL 2026-08-09: Use canonical quantity_cc, not display contracts.
                if position.quantity_cc == 0:
                    if position.tp_bracket_client_tag or position.sl_bracket_client_tag:
                        try:
                            await self._cancel_brackets(position)
                        except Exception as cancel_exc:
                            logger.warning(
                                "[BRACKET-CANCEL] Failed to cancel brackets for %s: %s",
                                market_id, cancel_exc,
                            )
                    # P1 fix: drop the now-unneeded TP target entry so registry
                    # doesn't grow unbounded across long-running sessions.
                    # 2026-08-22: Persist the removal so the on-disk registry stays
                    # in sync and does not resurrect closed positions on restart.
                    tp_removed = False
                    if client_order_id:
                        tp_removed = self._pending_tp_targets.pop(client_order_id, None) is not None or tp_removed
                    if position.client_order_id:
                        tp_removed = self._pending_tp_targets.pop(position.client_order_id, None) is not None or tp_removed
                    if tp_removed:
                        self._save_pending_tp_targets()

                    # CRITICAL FIX: Remove position from PositionMonitor when closed
                    # This ensures the monitor doesn't track closed positions
                    try:
                        from merid.position_management.position_monitor import get_position_monitor
                        monitor = get_position_monitor()
                        monitor.remove_position(market_id)
                        logger.info(
                            "[POSITION-MONITOR-INTEGRATION] Removed position from monitor: market=%s",
                            market_id
                        )
                    except Exception as monitor_err:
                        logger.warning("[POSITION-MONITOR-INTEGRATION] Failed to remove position from monitor: %s", monitor_err)

                    # CRITICAL FIX (2026-07-14): Delete position from cache when fully closed
                    # This prevents phantom position entries from accumulating and causing
                    # incorrect position count reporting in agent_grid_15m.py
                    # Previously, positions with contracts=0 remained in _positions dict,
                    # causing total_positions to be inflated even though open_positions was correct
                    del self._positions[market_id]
                    logger.info(
                        "[POSITION-CACHE] Deleted closed position from cache: market=%s (contracts=0)",
                        market_id
                    )

                    # CRITICAL FIX: Record position close in KalshiRiskManager for asset_notional tracking
                    # This ensures per-asset notional exposure is decremented when positions close
                    try:
                        from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
                        from config.kalshi_crypto_config import kalshi_ticker_to_asset
                        risk_mgr = get_kalshi_risk()

                        # Extract asset from ticker
                        asset = kalshi_ticker_to_asset(market_id)
                        if asset and asset.upper() in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
                            # Record close with category="crypto" and asset for notional tracking
                            risk_mgr.record_close(
                                category="crypto",
                                contracts=pre_contracts,  # Use pre-fill contracts (the amount being closed)
                                price_cents=price_cents,
                                asset=asset.upper(),  # CRITICAL: Pass asset for per-asset notional tracking
                            )
                            logger.info(
                                "[POSITION-CACHE] Recorded position close in risk manager: asset=%s category=crypto contracts=%d price=%dc",
                                asset.upper(), pre_contracts, price_cents
                            )
                    except Exception as risk_err:
                        logger.warning("[POSITION-CACHE] Failed to record position close in risk manager: %s", risk_err)

                    # CRITICAL: Record position close in risk envelope for window-based risk tracking (2026-07-06)
                    # This allows agents to re-enter after closing positions via trailing stop, ratchet, or 99c exit
                    try:
                        from merid.risk.profiles.kalshi_crypto_15m_risk_envelope import get_kalshi_crypto_15m_risk_envelope
                        envelope = get_kalshi_crypto_15m_risk_envelope()
                        if envelope:
                            from config.kalshi_crypto_config import kalshi_ticker_to_asset
                            asset = kalshi_ticker_to_asset(market_id)
                            if asset and asset.upper() in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
                                # Derive agent_id from asset
                                agent_id = f"{asset.upper()}_15M"
                                position_notional_usd = (pre_quantity_cc * price_cents) / 10000.0
                                envelope.record_position_closure(
                                    agent_id=agent_id,
                                    position_notional_usd=position_notional_usd,
                                    asset=asset.upper()
                                )
                                logger.info(
                                    "[POSITION-CACHE] Recorded window exposure reduction: agent=%s notional=$%.2f",
                                    agent_id, position_notional_usd
                                )
                    except Exception as window_err:
                        logger.warning("[POSITION-CACHE] Failed to record window exposure reduction: %s", window_err)

                    # SELL-SIDE FIX: Release contract lease when position is fully closed
                    # This ensures the lease is freed for future orders and prevents
                    # potential lease conflicts if the lease expires before renewal.
                    # Note: Uses "default" strategy_group since CachedPosition doesn't track it.
                    # The lease system allows same-owner renewal, so this is cleanup-only.
                    try:
                        from merid.event_venues.kalshi.contract_lease import (
                            get_contract_lease_registry,
                            LeaseKey,
                        )
                        registry = get_contract_lease_registry()
                        lease_key = LeaseKey(
                            venue="kalshi",
                            contract_id=market_id,
                            side=position.side,
                            strategy_group="default",
                        )
                        released = registry.release(lease_key, owner_agent_id="position_cache")
                        if released:
                            logger.info(
                                "[LEASE-RELEASE] Released lease for closed position: market=%s side=%s",
                                market_id, position.side
                            )
                    except Exception as lease_exc:
                        logger.debug(
                            "[LEASE-RELEASE] Failed to release lease for %s (non-fatal): %s",
                            market_id, lease_exc
                        )

                    # Calculate realized R before closing
                    realized_r = 0.0
                    # CRITICAL FIX (2026-07-23): Handle None avg_price_cents (unknown entry price)
                    if position.stop_loss_price_cents and position.stop_loss_price_cents > 0 and position.avg_price_cents is not None:
                        risk_cents = abs(position.avg_price_cents - position.stop_loss_price_cents)
                        if risk_cents > 0:
                            if position.side == "yes":
                                pnl_cents = price_cents - position.avg_price_cents
                            else:
                                pnl_cents = position.avg_price_cents - price_cents
                            realized_r = pnl_cents / risk_cents

                    logger.info(
                        "[EXIT] market=%s side=%s reason=MANUAL realized_R=%.2f asset=N/A confidence=N/A time_in_trade=N/A",
                        market_id, position.side, realized_r
                    )

                    # CRITICAL FIX: Check if position exists before deleting to avoid KeyError
                    # This can happen if the position was already deleted by another code path
                    if market_id in self._positions:
                        del self._positions[market_id]
                        logger.debug(f"Position cache: closed position on {market_id}")
                    else:
                        logger.warning(f"Position cache: position {market_id} not found for deletion (may have been already deleted)")
                # P0 Task 3: resize bracket when position grows.
                # If a buy added contracts and we have an existing TP bracket
                # whose count was set when the position was smaller, cancel and
                # re-submit the bracket sized to the new total so the new
                # contracts are also covered.
                elif (
                    action == "buy"
                    and side == position.side
                    and position.contracts > pre_contracts
                    and (position.tp_bracket_client_tag or position.sl_bracket_client_tag)
                    and os.getenv("MERID_RESTING_BRACKETS_ENABLED", "false").lower() in ("true", "1", "yes")
                ):
                    try:
                        await self._cancel_brackets(position)
                        await self._submit_resting_bracket(position)
                        logger.info(
                            "[BRACKET-RESIZE] %s: resized brackets to %d contracts",
                            market_id, position.contracts,
                        )
                    except Exception as resize_exc:
                        logger.warning(
                            "[BRACKET-RESIZE] Failed to resize brackets for %s: %s",
                            market_id, resize_exc,
                        )
                # P1 fix: drop the now-unneeded TP target entry so registry
                # doesn't grow unbounded across long-running sessions.
                # 2026-08-22: Persist the removal so the on-disk registry stays in sync.
                tp_removed = False
                if client_order_id:
                    tp_removed = self._pending_tp_targets.pop(client_order_id, None) is not None or tp_removed
                if position.client_order_id:
                    tp_removed = self._pending_tp_targets.pop(position.client_order_id, None) is not None or tp_removed
                if tp_removed:
                    self._save_pending_tp_targets()

            # 2026 Research-Based Risk Management: Update agent grid session tracking
            # This integrates session limit, consecutive loss pause, and session risk cap
            try:
                from merid.prediction.agent_grid_15m import get_agent_grid
                from config.kalshi_crypto_config import kalshi_ticker_to_asset

                grid = get_agent_grid()
                if grid and grid._agents:
                    # Extract asset from ticker
                    asset = kalshi_ticker_to_asset(market_id)
                    if asset and asset.upper() in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
                        asset_upper = asset.upper()

                        # Find the agent for this asset
                        for agent in grid._agents:
                            if agent.config.name.startswith(asset_upper):
                                # Calculate PnL and trade risk
                                pnl_usd = 0.0
                                trade_risk_usd = 0.0

                                if position is None:
                                    # New position: calculate trade risk as contracts * price
                                    trade_risk_usd = (quantity_cc * price_cents) / 10000.0
                                elif position.contracts == 0:
                                    # Position closed: calculate realized PnL
                                    # For YES: pnl = (exit_price - entry_price) * contracts
                                    # For NO: pnl = (entry_price - exit_price) * contracts
                                        # Long position PnL: exit price - entry price in own-side cents.
                                    if position.avg_price_cents is not None:
                                        pnl_cents = price_cents - position.avg_price_cents
                                        pnl_usd = (pnl_cents * pre_quantity_cc) / 10000.0
                                    else:
                                        pnl_usd = 0.0

                                # Call update_cooldown_on_fill with PnL and trade risk
                                agent.update_cooldown_on_fill(
                                    asset=asset_upper,
                                    pnl_usd=pnl_usd,
                                    trade_risk_usd=trade_risk_usd
                                )
                                logger.info(
                                    "[AGENT-GRID-SESSION] Updated session tracking: asset=%s pnl=%.2f trade_risk=%.2f",
                                    asset_upper, pnl_usd, trade_risk_usd
                                )
                                break
            except Exception as agent_err:
                logger.debug("[POSITION-CACHE] Failed to update agent grid session tracking: %s", agent_err)

            # AUDIT: Emit immutable order lifecycle record for every accepted fill.
            try:
                from merid.prediction.intent_contract import emit_order_lifecycle_event
                current_position = self._positions.get(market_id)
                if current_position:
                    post_position_yes_actual = current_position._yes_exposure()
                elif position is not None:
                    # Position was closed and deleted during this fill; actual is zero.
                    post_position_yes_actual = 0
                else:
                    # New position creation path: use the canonicalized position we just stored.
                    current_position = self._positions.get(market_id)
                    post_position_yes_actual = current_position._yes_exposure() if current_position else 0

                emit_order_lifecycle_event(
                    client_order_id=client_order_id or fill_id or "unknown",
                    ticker=market_id,
                    strategy_intent="",
                    action=raw_action,
                    side=raw_side,
                    price_cents=price_cents,
                    quantity=raw_quantity_cc,
                    pre_position_yes=pre_position_yes,
                    post_position_yes_expected=expected_post_yes,
                    post_position_yes_actual=post_position_yes_actual,
                    reason="fill_applied",
                    parent_order_id=client_order_id,
                    is_reduce_only_expected=bool(is_exit),
                )
            except Exception as lifecycle_err:
                logger.debug("[POSITION-CACHE] Failed to emit order lifecycle event: %s", lifecycle_err)

            # Canonical per-fill reconciliation line: cache and ledger should now agree.
            try:
                cache_signed_yes = self._get_cache_signed_yes(market_id)
                ledger_signed_yes = 0
                ledger = self._get_fills_ledger()
                if ledger:
                    try:
                        ledger_pos = ledger.compute_position_from_fills(market_id)
                        if ledger_pos and hasattr(ledger_pos, "get"):
                            _raw_ledger_yes = ledger_pos.get("signed_yes_exposure", 0)
                            try:
                                ledger_signed_yes = int(_raw_ledger_yes)
                            except (TypeError, ValueError):
                                logger.debug(
                                    "[POSITION-CACHE] Could not coerce ledger signed_yes exposure: %s",
                                    _raw_ledger_yes,
                                )
                                ledger_signed_yes = 0
                    except Exception:
                        logger.debug("[POSITION-CACHE] Could not compute ledger position for reconciliation")
                status = "matched" if cache_signed_yes == ledger_signed_yes else "mismatch"
                self._emit_exposure_reconciliation(
                    ticker=market_id,
                    exchange_signed_yes=cache_signed_yes,
                    ledger_signed_yes=ledger_signed_yes,
                    cache_signed_yes=cache_signed_yes,
                    open_order_reserved_yes=0,
                    source_timestamp=replay_time(),
                    status=status,
                )
            except Exception as rec_err:
                logger.debug("[POSITION-CACHE] Failed to emit per-fill reconciliation: %s", rec_err)

    def promote_entry_fill_id(
        self,
        market_id: str,
        old_fill_id: str,
        new_fill_id: str,
        client_order_id: Optional[str] = None,
        order_id: Optional[str] = None,
        intent_id: Optional[str] = None,
    ) -> bool:
        """Rewrite a position's ``entry_fill_id`` from a provisional to an
        authoritative id.

        Called by ``fills_ledger`` when an HTTP/WS fill promotes a live-router
        provisional record.  This makes the authoritative fill id the single
        source of truth for exit parentage, order client order id derivation,
        and all downstream idempotency gates.  It does NOT mutate exposure;
        the live fill has already applied the position delta.
        """
        if not new_fill_id:
            return False

        # The authoritative id must be treated as already applied so the
        # position_cache's own on_fill path does not double-apply it later.
        if new_fill_id not in self._applied_fill_ids:
            self._applied_fill_ids[new_fill_id] = replay_time()
            self._save_applied_fill_ids()

        if old_fill_id == new_fill_id:
            return True

        updated = False
        # Most positions are keyed by market_id; live fills from other tickers
        # should not share a provisional id, but fall back to a full scan.
        candidates = [self._positions.get(market_id)] if market_id in self._positions else []
        if not candidates:
            candidates = list(self._positions.values())

        for pos in candidates:
            if pos and pos.entry_fill_id == old_fill_id:
                pos.entry_fill_id = new_fill_id
                old_client_order_id = pos.client_order_id
                if client_order_id:
                    pos.client_order_id = client_order_id
                if order_id:
                    pos.entry_order_id = order_id
                if intent_id:
                    pos.entry_intent_id = intent_id
                updated = True
                logger.info(
                    "[POSITION-CACHE-PROMOTE] market=%s old_fill_id=%s new_fill_id=%s "
                    "client_order_id=%s order_id=%s intent_id=%s",
                    market_id,
                    old_fill_id[:16] if old_fill_id else None,
                    new_fill_id[:16] if new_fill_id else None,
                    client_order_id,
                    order_id,
                    intent_id,
                )
                # If the TP-target registry still uses the old client_order_id,
                # migrate it to the authoritative one so spread-stop and
                # model-provenance still resolve at fill time.
                if client_order_id and old_client_order_id and old_client_order_id != client_order_id:
                    if old_client_order_id in self._pending_tp_targets:
                        target = self._pending_tp_targets.pop(old_client_order_id)
                        self._pending_tp_targets[client_order_id] = target
                        self._save_pending_tp_targets()
                break

        if not updated:
            logger.warning(
                "[POSITION-CACHE-PROMOTE] No position found for old_fill_id=%s market=%s; "
                "authoritative id still recorded in applied_fill_ids.",
                old_fill_id, market_id,
            )

        return updated

    async def update_position_price(self, market_id: str, price_cents: int) -> None:
        """Update current price and unrealized PnL when market price changes.

        CRITICAL FIX: This updates current_price_cents for micro-scalp PnL calculation.
        Without this, micro-scalp exits with $0 PnL because current_price_cents is stale.

        BUG-FIX: Now async with mutex protection for thread safety.
        """
        async with self._ensure_mutex():
            position = self._positions.get(market_id)
            if position:
                position.current_price_cents = price_cents
                position.update_unrealized_pnl(price_cents)

    def get_position(self, market_id: str) -> Optional[CachedPosition]:
        """Get cached position for a market."""
        return self._positions.get(market_id)

    def get_all_positions(self, validate_freshness: bool = True) -> Dict[str, CachedPosition]:
        """Get all cached positions.

        Args:
            validate_freshness: If True, checks if cache is stale and logs warning.

        Returns:
            Dict of market_id -> CachedPosition
        """
        if validate_freshness and self._last_sync:
            from datetime import datetime, timezone
            staleness_seconds = (datetime.now(timezone.utc) - self._last_sync).total_seconds()
            if staleness_seconds > 300:  # 5 minutes
                logger.warning(
                    f"[POSITION-CACHE-STALE] Cache is {staleness_seconds:.0f}s old. "
                    f"Consider calling sync_from_rest() before get_all_positions()."
                )

        # CRITICAL FIX (2026-07-31): Health check for positions with invalid entry prices
        # This prevents the 0 exposure bug from going undetected
        self._check_position_health()

        return dict(self._positions)

    def _check_position_health(self) -> None:
        """Check position cache health and log warnings for invalid states.

        CRITICAL FIX (2026-07-31): Detects positions with invalid entry prices
        that would cause 0 exposure reporting and exit policy failures.

        CRITICAL FIX (2026-08-01): Auto-fix positions with invalid entry prices
        by looking up fills ledger for the specific market.
        """
        invalid_positions = []
        for market_id, position in self._positions.items():
            if position.contracts > 0:
                if position.avg_price_cents is None or position.avg_price_cents == 0:
                    invalid_positions.append({
                        'market_id': market_id,
                        'contracts': position.contracts,
                        'avg_price_cents': position.avg_price_cents,
                        'side': position.side,
                        'thesis_side': position.thesis_side
                    })

        if invalid_positions:
            logger.warning(
                "[POSITION-CACHE-HEALTH-CHECK] Found %d positions with invalid entry prices (None or 0). "
                "These positions will use fallback prices for notional calculation. "
                "Invalid positions: %s",
                len(invalid_positions),
                invalid_positions
            )
            # Log details for each invalid position
            for pos in invalid_positions:
                logger.warning(
                    "[POSITION-CACHE-INVALID-POSITION] market=%s contracts=%d avg_price=%s side=%s thesis_side=%s",
                    pos['market_id'], pos['contracts'], pos['avg_price_cents'], pos['side'], pos['thesis_side']
                )

            # CRITICAL FIX (2026-08-01): Auto-fix positions with invalid entry prices
            # by looking up fills ledger for the specific market
            self._auto_fix_invalid_positions(invalid_positions)

    def force_health_check_and_fix(self) -> int:
        """Force a health check and auto-fix invalid positions.

        CRITICAL FIX (2026-08-01): Public method to manually trigger health check
        and auto-fix for positions with invalid entry prices. This can be called
        by operators or scripts to immediately fix positions without waiting for
        get_all_positions to be called.

        Returns:
            Number of positions fixed
        """
        logger.info("[POSITION-CACHE] Force health check and fix triggered")
        self._check_position_health()
        return len([p for p in self._positions.values() if p.contracts > 0 and p.avg_price_cents is not None and p.avg_price_cents > 0])

    def force_delete_phantom_position(self, market_id: str) -> bool:
        """Force delete a phantom position from cache.

        This is called when fills ledger confirms zero net position but cache
        still shows a position. This prevents phantom positions from causing
        incorrect exposure calculations and forced exits.

        Args:
            market_id: The market ID to delete from cache

        Returns:
            True if position was deleted, False if not found or already deleted
        """
        if market_id in self._positions:
            position = self._positions[market_id]
            logger.warning(
                "[POSITION-CACHE] Force deleting phantom position: market=%s contracts=%d avg_price=%s",
                market_id, position.contracts, position.avg_price_cents
            )
            del self._positions[market_id]
            return True
        return False

    def _auto_fix_invalid_positions(self, invalid_positions: List[Dict]) -> None:
        """Auto-fix positions with invalid entry prices by looking up fills ledger.

        CRITICAL FIX (2026-08-01): When positions have avg_price_cents=None or 0,
        this method looks up the fills ledger for the specific market to recover
        the correct entry price and thesis_side from fill events.

        Args:
            invalid_positions: List of dicts with market_id, contracts, avg_price_cents, side, thesis_side
        """
        try:
            ledger = self._get_fills_ledger()
            if not ledger:
                logger.error("[POSITION-CACHE-AUTO-FIX] Fills ledger not available for auto-fix")
                return

            from datetime import datetime, timedelta, timezone
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)  # Look back 24 hours

            fixed_count = 0
            for pos_info in invalid_positions:
                market_id = pos_info['market_id']

                # Get fills for this specific market
                market_fills = ledger.get_fills(since=cutoff_time, market_ticker=market_id, limit=50)

                if not market_fills:
                    logger.warning(
                        "[POSITION-CACHE-AUTO-FIX] No fills found for market %s - cannot fix invalid entry price",
                        market_id
                    )
                    continue

                # Compute net position and avg price from fills
                net_contracts = 0
                total_cost_cents = 0
                total_contracts_for_avg = 0
                thesis_side = None

                for fill in market_fills:
                    contracts = getattr(fill, 'count', 0) or getattr(fill, 'contracts', 0)
                    price_cents = getattr(fill, 'price_cents', 0)
                    side = getattr(fill, 'side', 'yes')
                    action = getattr(fill, 'action', 'buy')

                    if action == 'buy':
                        net_contracts += contracts
                        total_cost_cents += contracts * price_cents
                        total_contracts_for_avg += contracts

                        # Set thesis_side from first entry fill
                        if thesis_side is None and side in ('yes', 'no'):
                            thesis_side = side
                    elif action == 'sell':
                        net_contracts -= contracts

                # CRITICAL FIX (2026-08-01): Handle zero net positions from fills ledger
                # If fills ledger shows net_contracts=0 but cache shows contracts>0,
                # this is a phantom position that should be DELETED from cache
                if net_contracts == 0 and market_id in self._positions:
                    cached_pos = self._positions[market_id]
                    if cached_pos.contracts > 0:
                        # Phantom position detected - delete from cache
                        logger.warning(
                            "[POSITION-CACHE-AUTO-FIX] Phantom position detected for %s: cache shows %d contracts but fills ledger shows 0. DELETING from cache.",
                            market_id, cached_pos.contracts
                        )
                        del self._positions[market_id]
                        fixed_count += 1
                    else:
                        # Cache already shows 0 contracts, just clean up
                        del self._positions[market_id]
                        fixed_count += 1
                # Only fix if we have a net position matching current cache
                elif net_contracts > 0 and market_id in self._positions:
                    cached_pos = self._positions[market_id]

                    # Update avg_price_cents
                    if total_contracts_for_avg > 0:
                        avg_price_cents = total_cost_cents // total_contracts_for_avg
                        cached_pos.avg_price_cents = avg_price_cents
                        cached_pos.entry_price_state = "known"

                        # Update thesis_side if it was unknown
                        if thesis_side and cached_pos.thesis_side in ('unknown', 'yes'):
                            cached_pos.thesis_side = thesis_side
                            cached_pos.side = thesis_side  # Update side for consistency

                        fixed_count += 1
                        logger.info(
                            "[POSITION-CACHE-AUTO-FIX] Fixed position %s: avg_price=%dc thesis_side=%s (from fills ledger)",
                            market_id, avg_price_cents, thesis_side or cached_pos.thesis_side
                        )
                    else:
                        logger.warning(
                            "[POSITION-CACHE-AUTO-FIX] Could not compute avg price for market %s (total_contracts_for_avg=0)",
                            market_id
                        )
                else:
                    logger.warning(
                        "[POSITION-CACHE-AUTO-FIX] Net position from fills (%d) does not match cache for market %s",
                        net_contracts, market_id
                    )

            logger.info(
                "[POSITION-CACHE-AUTO-FIX] Fixed %d positions with invalid entry prices",
                fixed_count
            )

        except Exception as e:
            logger.error("[POSITION-CACHE-AUTO-FIX] Error auto-fixing invalid positions: %s", e, exc_info=True)

    def get_total_exposure_usd(self) -> float:
        """Get total exposure in USD across all open positions.

        CRITICAL FIX: 2026-07-09 - This is now a FALLBACK for exposure tracking
        Primary source of truth is GlobalSlotAllocator for $1 exposure cap
        This method is kept for legacy compatibility and fallback scenarios

        Returns:
            Total exposure in USD (sum of contracts * price for all open positions)
        """
        total_exposure = 0.0
        for position in self._positions.values():
            if position.quantity_cc > 0 and position.avg_price_cents is not None:
                # Exposure = quantity_cc * price_cents / 10000
                position_exposure = (position.quantity_cc * position.avg_price_cents) / 10000.0
                total_exposure += position_exposure
        return total_exposure

    async def _auto_resync_callback(self, context: Dict[str, Any]) -> None:
        """Callback for active reconciliation auto-resync action.

        Force sync position cache from REST API when invariant violation detected.
        """
        market_id = context.get("market_id")
        logger.info("[POSITION-CACHE-AUTO-RESYNC] Auto-resync triggered for %s", market_id)

        try:
            # Get fresh positions from REST API
            from merid.event_venues.kalshi.kalshi_rest_client import get_kalshi_rest_client
            rest_client = await get_kalshi_rest_client()

            # If we know the specific market, ask for only that position.
            # Falls back to all positions if the API ignores the filter.
            filters = {"market_ticker": market_id} if market_id else {}
            positions_result = await rest_client.get_positions_with_filters(filters)
            if positions_result.success:
                positions = positions_result.data or {}
                raw_positions = positions.get("market_positions") or positions.get("positions") or []

                # Force sync with force=True to bypass staleness guard
                await self.sync_from_rest(raw_positions, force=True)
                logger.info("[POSITION-CACHE-AUTO-RESYNC] Auto-resync completed for %s", market_id)
            else:
                logger.error("[POSITION-CACHE-AUTO-RESYNC] Failed to fetch positions: %s", positions_result.error)
        except Exception as e:
            logger.error("[POSITION-CACHE-AUTO-RESYNC] Auto-resync failed: %s", e, exc_info=True)
            raise

    async def _auto_halt_callback(self, context: Dict[str, Any]) -> None:
        """Callback for active reconciliation trading halt action.

        Halt trading for specific market or globally when critical invariant violation detected.
        """
        market_id = context.get("market_id")
        logger.critical("[POSITION-CACHE-AUTO-HALT] Trading halt triggered for %s", market_id)

        try:
            # TODO: Implement trading halt logic
            # This should:
            # 1. Cancel all pending orders for the market
            # 2. Prevent new orders from being submitted
            # 3. Alert operators
            logger.warning("[POSITION-CACHE-AUTO-HALT] Trading halt not yet implemented - manual intervention required")
        except Exception as e:
            logger.error("[POSITION-CACHE-AUTO-HALT] Halt callback failed: %s", e, exc_info=True)
            raise

    def get_cache_health(self) -> Dict[str, Any]:
        """Get position cache health status for monitoring.

        Returns:
            Dict with health metrics including staleness, position count, and sync status.
        """
        from datetime import datetime, timezone

        staleness_seconds = 0.0
        if self._last_sync:
            staleness_seconds = (datetime.now(timezone.utc) - self._last_sync).total_seconds()

        open_positions = {k: v for k, v in self._positions.items() if v.contracts > 0}

        return {
            "last_sync_timestamp": self._last_sync.isoformat() if self._last_sync else None,
            "staleness_seconds": staleness_seconds,
            "is_stale": staleness_seconds > 300,  # 5 minutes
            "total_positions": len(self._positions),
            "open_positions": len(open_positions),
            "closed_positions": len(self._positions) - len(open_positions),
            "monitoring_enabled": self._monitoring_enabled,
        }

    def get_open_positions(self, market_id: str) -> List[CachedPosition]:
        """Get all open positions for a market (returns list for compatibility).

        Returns empty list if no position, or list with single position if exists.
        """
        position = self._positions.get(market_id)
        if position and position.contracts > 0:
            return [position]
        return []

    def get_positions_by_asset(self, asset: str) -> List[CachedPosition]:
        """Get all open positions for a specific asset.

        Args:
            asset: Asset symbol (e.g., "BTC", "ETH")

        Returns:
            List of CachedPosition objects for the given asset with contracts > 0.
            Market IDs are like KXBTC15M-26MAY241245-45, so we check if asset is in the market_id.
        """
        asset_positions = []
        for market_id, position in self._positions.items():
            # Check if this position belongs to the requested asset
            # Market IDs are like KXBTC15M-26MAY241245-45
            if asset.upper() in market_id.upper():
                if position.contracts > 0:
                    asset_positions.append(position)
        return asset_positions

    async def recompute_position_from_ledger(self, market_id: str, agent_id: str) -> Optional[CachedPosition]:
        """
        Deterministic recompute path: rebuild position purely from fills_ledger.

        This provides byte-for-byte reproducibility and is critical for:
        - Drift detection (compare live cache vs ledger-derived)
        - Recovery from corrupted state
        - Verification that live cache matches canonical ledger

        Args:
            market_id: Market identifier (e.g., "KXBTC15M-26JUL211745-45")
            agent_id: Agent identifier for composite key

        Returns:
            CachedPosition rebuilt from fills_ledger, or None if no fills exist
        """
        ledger = self._get_fills_ledger()
        if not ledger:
            logger.warning("[POSITION-RECOMPUTE] Fills ledger not available for recompute")
            return None

        # Get all fills for this market from the ledger
        market_fills = ledger.get_fills_by_market(market_id)
        if not market_fills:
            logger.debug("[POSITION-RECOMPUTE] No fills found for %s", market_id)
            return None

        # Filter fills by agent_id if provided
        if agent_id:
            market_fills = [f for f in market_fills if getattr(f, 'agent_id', None) == agent_id]

        if not market_fills:
            logger.debug("[POSITION-RECOMPUTE] No fills found for %s with agent_id=%s", market_id, agent_id)
            return None

        # Sort fills by timestamp for deterministic replay
        # Use created_at or ts field
        sorted_fills = sorted(
            market_fills,
            key=lambda f: getattr(f, 'created_at', None) or getattr(f, 'ts', 0)
        )

        # Replay fills to compute position state using canonical signed YES exposure.
        # This makes SELL_YES == BUY_NO (long NO) and SELL_NO == BUY_YES (long YES).
        yes_exposure = 0
        avg_price_cents = None
        realized_pnl_usd = Decimal("0")
        thesis_side = None
        entry_intent_id = None
        fill_source = "alpha"
        first_fill: Any = None

        for fill in sorted_fills:
            if first_fill is None:
                first_fill = fill
            # CRITICAL 2026-08-09: Use canonical centi-contracts. Fallback to count_fp legacy.
            fill_quantity_cc = fill.quantity_cc or 0
            if not fill_quantity_cc and fill.count_fp:
                try:
                    fill_quantity_cc = int(Decimal(str(fill.count_fp)) * Decimal("100"))
                except Exception:
                    fill_quantity_cc = int(fill.count_fp) * 100
            if not fill_quantity_cc:
                continue
            fill_price_cents = fill.price_cents or 0
            # 2026-08-12: Use canonical position action/side for signed-YES replay.
            fill_action = fill.canonical_position_action or fill.action or "buy"
            fill_side = fill.canonical_position_side or fill.side or "yes"

            # Compute signed YES exposure for this fill.
            fill_yes = 0
            if BINARY_PRICE_SPACE_AVAILABLE:
                fill_yes = yes_delta(fill_action, fill_side, fill_quantity_cc)
            else:
                if (fill_action, fill_side) in {("buy", "yes"), ("sell", "no")}:
                    fill_yes = +fill_quantity_cc
                elif (fill_action, fill_side) in {("sell", "yes"), ("buy", "no")}:
                    fill_yes = -fill_quantity_cc

            if fill_yes == 0:
                continue

            # Set thesis_side from first fill's canonical side.
            if thesis_side is None:
                thesis_side, _ = from_signed_yes_exposure(fill_yes)
                entry_intent_id = getattr(fill, 'intent_id', None)
                fill_source = getattr(fill, 'fill_source', 'alpha')

            # Use the price in the position's (thesis) side space.  When the
            # canonical fill side differs from the held side, read the stored
            # YES/NO leg price instead of computing a complement.
            if fill_side.lower() != thesis_side.lower():
                converted = _fill_position_side_price_cents(fill, thesis_side)
                if converted is not None:
                    fill_price_cents = converted
                else:
                    logger.warning(
                        "[POSITION-RECOMPUTE] Cannot determine %s-side price for %s fill_id=%s; using raw price",
                        thesis_side, market_id, getattr(fill, 'fill_id', 'unknown'),
                    )

            # Weighted average price update for the new exposure.
            if yes_exposure == 0:
                avg_price_cents = fill_price_cents
            else:
                pre_contracts = abs(yes_exposure)
                total_cost = pre_contracts * avg_price_cents + fill_quantity_cc * fill_price_cents
                avg_price_cents = total_cost // (pre_contracts + fill_quantity_cc)

            yes_exposure += fill_yes

        # Convert canonical YES exposure back to (side, quantity_cc).
        if yes_exposure == 0:
            logger.debug("[POSITION-RECOMPUTE] Position %s is closed (no contracts after replay)", market_id)
            return None

        thesis_side, quantity_cc = from_signed_yes_exposure(yes_exposure)
        contracts = int(quantity_cc / 100)

        # CRITICAL FIX (2026-08-22): Recover full entry provenance from the first
        # entry fill and the persisted TP-target registry.  This allows a position
        # rebuilt from the fills_ledger after a restart to pass the spread-stop and
        # model-invalidation exit gates (ORIGINAL_PERSISTED, schema >= 2, AT_FILL book).
        tp_targets: Dict[str, Any] = {}
        client_order_id: Optional[str] = None
        if first_fill is not None:
            client_order_id = getattr(first_fill, 'client_order_id', None)
            # HTTP fills sometimes lose client_order_id; recover via order_id mapping.
            if not client_order_id and getattr(first_fill, 'order_id', None):
                client_order_id = self._order_id_to_client_tag.get(first_fill.order_id)
            # Fallback to client_tag if the TP registry was keyed by it.
            client_tag = getattr(first_fill, 'client_tag', None)
            for key in (client_order_id, client_tag):
                if key:
                    tp_targets = self._pending_tp_targets.get(key, {}) or {}
                    if tp_targets:
                        client_order_id = client_order_id or key
                        break

        # Determine whether we have a trusted AT_FILL book from the persisted registry.
        has_at_fill_book = (
            tp_targets.get("entry_book_capture_quality") == "AT_FILL"
            and tp_targets.get("entry_executable_bid_cents") is not None
            and tp_targets.get("entry_executable_ask_cents") is not None
        )
        risk_params_state = "unknown"
        risk_params_schema_version = 1
        if first_fill is not None and client_order_id and has_at_fill_book:
            risk_params_state = "original_persisted"
            risk_params_schema_version = 2

        # Build reconstructed position with durable provenance.
        entry_signal_id = (
            tp_targets.get("entry_signal_id")
            or getattr(first_fill, 'entry_signal_id', None)
            or client_order_id
            or getattr(first_fill, 'fill_id', None)
        )
        reconstructed = CachedPosition(
            market_id=market_id,
            agent_id=agent_id,
            contracts=contracts,
            quantity_cc=quantity_cc,
            side=thesis_side or "yes",
            thesis_side=thesis_side or "yes",
            outcome_side=thesis_side or "yes",
            book_side="ask",
            avg_price_cents=avg_price_cents,
            realized_pnl_usd=realized_pnl_usd,
            unrealized_pnl_usd=Decimal("0"),  # Would need current market price
            last_updated=datetime.now(timezone.utc),
            entry_intent_id=entry_intent_id or tp_targets.get("entry_signal_id") or client_order_id,
            fill_source=fill_source,
            client_order_id=client_order_id,
            # CRITICAL FIX (2026-08-22): Restore trusted risk parameter provenance.
            risk_params_state=risk_params_state,
            risk_params_schema_version=risk_params_schema_version,
            # Entry model/book metadata from persisted TP targets.
            entry_signal_id=entry_signal_id,
            entry_model=tp_targets.get("entry_model") or getattr(first_fill, 'entry_model', None),
            entry_model_version=tp_targets.get("entry_model_version") or getattr(first_fill, 'entry_model_version', None),
            entry_model_probability=tp_targets.get("entry_model_probability") if tp_targets.get("entry_model_probability") is not None else getattr(first_fill, 'entry_model_probability', None),
            entry_market_probability=tp_targets.get("entry_market_probability") if tp_targets.get("entry_market_probability") is not None else getattr(first_fill, 'entry_market_probability', None),
            entry_edge=tp_targets.get("entry_edge") if tp_targets.get("entry_edge") is not None else getattr(first_fill, 'entry_edge', None),
            entry_book_snapshot_id=tp_targets.get("entry_book_snapshot_id") or getattr(first_fill, 'entry_book_snapshot_id', None),
            entry_execution_mode=tp_targets.get("entry_execution_mode") or getattr(first_fill, 'entry_execution_mode', None),
            entry_fill_id=getattr(first_fill, 'fill_id', None) if first_fill else None,
            entry_order_id=getattr(first_fill, 'order_id', None) if first_fill else None,
            entry_fill_price_cents=avg_price_cents,
            entry_fill_timestamp=getattr(first_fill, 'created_time', None) if first_fill else None,
            entry_executable_bid_cents=tp_targets.get("entry_executable_bid_cents"),
            entry_executable_ask_cents=tp_targets.get("entry_executable_ask_cents"),
            entry_book_capture_quality=tp_targets.get("entry_book_capture_quality", "UNKNOWN"),
            entry_book_timestamp=tp_targets.get("entry_book_timestamp"),
            entry_book_sequence=tp_targets.get("entry_book_sequence"),
            entry_book_source=tp_targets.get("entry_book_source"),
            # TP/SL from persisted targets (if any).
            take_profit_price_cents=tp_targets.get("tp_price"),
            take_profit_r_multiple=tp_targets.get("tp_r"),
            stop_loss_enabled=bool(tp_targets.get("sl_enabled", True)),
            stop_loss_price_cents=tp_targets.get("sl_price"),
            # Volatility/confidence from persisted targets.
            vol_regime=tp_targets.get("vol_regime") or "unknown",
            confidence=tp_targets.get("confidence") or "unknown",
            entry_edge_pct=tp_targets.get("edge_pct") or 0.03,
        )

        # CRITICAL FIX (2026-08-23): Attach canonical position key to REST-reconstructed
        # positions. Asset aliases are not identities.
        if POSITION_KEY_AVAILABLE:
            reconstructed.position_key = PositionKey(market_ticker=market_id)
            reconstructed.known_aliases = [market_id]

        # CRITICAL FIX (2026-08-23): Resolve durable entry-provenance for REST-reconstructed
        # positions. Only PROVENANCE-RESOLVED positions receive TP/SL/edge-decay metadata.
        try:
            self.rehydrate_cached_position(reconstructed)
        except Exception as prov_err:
            logger.warning("[POSITION-CACHE] Provenance rehydration failed: %s", prov_err)

        logger.info(
            "[POSITION-RECOMPUTE] Reconstructed position for %s: %d contracts @ %dc, thesis_side=%s, provenance=%s",
            market_id, contracts, avg_price_cents, thesis_side,
            "AT_FILL" if has_at_fill_book else "POST_FILL/UNKNOWN"
        )

        return reconstructed

    def _apply_provenance_snapshot_to_cached_position(
        self,
        position: CachedPosition,
        snapshot,
        complete: bool,
        provenance_state_value: Optional[str] = None,
    ) -> CachedPosition:
        """Merge durable entry-provenance metadata into a CachedPosition."""
        if snapshot is None:
            return position

        position.entry_provenance_snapshot_id = snapshot.snapshot_id
        position.tp_policy_id = snapshot.tp_policy_id
        position.tp_policy_version = snapshot.tp_policy_version
        position.sl_policy_id = snapshot.sl_policy_id
        position.sl_policy_version = snapshot.sl_policy_version
        position.client_order_id = position.client_order_id or snapshot.client_order_id
        position.entry_intent_id = position.entry_intent_id or snapshot.client_order_id
        position.entry_fill_id = position.entry_fill_id or snapshot.fill_id
        position.entry_order_id = position.entry_order_id or snapshot.order_id
        position.entry_signal_id = position.entry_signal_id or snapshot.client_order_id
        position.provenance_state = (
            provenance_state_value or ProvenanceState.PROVENANCE_RECOVERED.value
        )

        if not complete:
            return position

        position.risk_params_state = "original_persisted"
        position.risk_params_schema_version = 2
        position.take_profit_price_cents = (
            position.take_profit_price_cents or snapshot.tp_price_cents
        )
        position.take_profit_r_multiple = (
            position.take_profit_r_multiple or snapshot.take_profit_r_multiple
        )
        position.stop_loss_enabled = snapshot.stop_loss_enabled
        position.stop_loss_price_cents = (
            position.stop_loss_price_cents or snapshot.sl_price_cents
        )
        position.entry_fill_price_cents = (
            position.entry_fill_price_cents
            or snapshot.entry_fill_price_cents
            or snapshot.entry_price_cents
        )
        position.entry_fill_timestamp = (
            position.entry_fill_timestamp or snapshot.entry_fill_timestamp
        )
        position.entry_executable_bid_cents = (
            position.entry_executable_bid_cents or snapshot.entry_executable_bid_cents
        )
        position.entry_executable_ask_cents = (
            position.entry_executable_ask_cents or snapshot.entry_executable_ask_cents
        )
        position.entry_book_capture_quality = (
            snapshot.entry_book_capture_quality
            if snapshot.entry_book_capture_quality != "UNKNOWN"
            else position.entry_book_capture_quality
        )
        position.entry_book_timestamp = (
            position.entry_book_timestamp or snapshot.entry_book_timestamp
        )
        position.entry_book_sequence = (
            position.entry_book_sequence or snapshot.entry_book_sequence
        )
        position.entry_book_source = (
            position.entry_book_source or snapshot.entry_book_source
        )
        position.entry_model_probability = snapshot.entry_fair_value
        position.entry_market_probability = snapshot.entry_market_value
        position.entry_edge = snapshot.entry_edge
        position.entry_edge_pct = (
            snapshot.entry_edge
            if snapshot.entry_edge is not None
            else position.entry_edge_pct
        )
        position.entry_model = snapshot.exit_policy_id or position.entry_model
        position.entry_model_version = snapshot.tp_policy_version or position.entry_model_version
        position.vol_regime = position.vol_regime or "unknown"
        position.confidence = position.confidence or "unknown"

        # Fall back to a trusted entry price if the REST price is missing/invalid.
        if (
            position.avg_price_cents is None or position.avg_price_cents == 0
        ) and snapshot.entry_fill_price_cents:
            position.avg_price_cents = int(snapshot.entry_fill_price_cents)
            position.entry_price_state = "provenance"

        return position

    def rehydrate_cached_position(self, position: CachedPosition) -> CachedPosition:
        """Attempt to recover the original exit plan from durable provenance.

        This is a synchronous, idempotent lookup that may be called from
        ``sync_from_rest`` or ``PositionMonitor.start`` for any cached position
        whose provenance is not already original.
        """
        if not ENTRY_PROVENANCE_AVAILABLE:
            return position

        cached_state = getattr(position, "risk_params_state", None)
        if (
            position.entry_provenance_snapshot_id
            and cached_state == "original_persisted"
            and position.risk_params_schema_version >= 2
        ):
            return position

        raw_side = position.outcome_side or position.side
        try:
            side = canonical_outcome_side(raw_side).value if raw_side else None
        except PositionDataError:
            side = None
        if side is None:
            logger.warning(
                "[POSITION-CACHE-REHYDRATE] %s: cannot rehydrate without a canonical side (outcome_side=%r, side=%r)",
                position.market_id,
                position.outcome_side,
                position.side,
            )
            return position

        fills = None
        if self._fills_ledger:
            try:
                fills = self._fills_ledger.get_fills_by_market(position.market_id)
            except Exception:
                fills = None

        try:
            resolution = get_entry_provenance_store().rehydrate_for_position(
                ticker=position.market_id,
                position_side=side,
                client_order_id=position.client_order_id,
                fill_id=position.entry_fill_id,
                order_id=position.entry_order_id,
                position_qty_cc=position.quantity_cc,
                fills=fills,
            )
            if resolution and resolution.snapshot:
                logger.info(
                    "[POSITION-CACHE-REHYDRATE] market=%s side=%s state=%s complete=%s",
                    position.market_id,
                    side,
                    resolution.state.value,
                    resolution.complete,
                )
                self._apply_provenance_snapshot_to_cached_position(
                    position,
                    resolution.snapshot,
                    resolution.complete,
                    resolution.state.value,
                )
        except Exception as err:
            logger.debug("[POSITION-CACHE-REHYDRATE] failed for %s: %s", position.market_id, err)

        return position

    def get_asset_exposure(self, asset: str) -> Dict[str, Any]:
        """Get total exposure for an asset across all markets.

        Args:
            asset: Asset symbol (e.g., "BTC", "ETH")

        Returns:
            Dict with exposure metrics:
            - total_contracts: Total contracts held
            - total_notional_usd: Total notional value in USD
            - unrealized_pnl_usd: Total unrealized PnL in USD
            - position_count: Number of markets with positions
        """
        total_contracts = 0
        total_notional_usd = Decimal("0")
        total_unrealized_pnl = Decimal("0")
        position_count = 0

        for market_id, position in self._positions.items():
            # Check if this position belongs to the requested asset
            # Market IDs are like KXBTC15M-26MAY241245-45
            if asset.upper() in market_id.upper():
                if position.contracts > 0:
                    total_contracts += position.contracts
                    total_notional_usd += position.notional_usd
                    total_unrealized_pnl += position.unrealized_pnl_usd
                    position_count += 1

        return {
            "total_contracts": total_contracts,
            "total_notional_usd": float(total_notional_usd),
            "unrealized_pnl_usd": float(total_unrealized_pnl),
            "position_count": position_count,
        }

    async def sync_from_rest(
        self,
        positions: list,
        rest_timestamp: Optional[float] = None,
        force: bool = False,
        open_orders: Optional[List[Dict[str, Any]]] = None,
        cleanup_stale: bool = False,
    ) -> None:
        """Sync cache with REST API positions (fallback/reconciliation).

        BUG-FIX: Now async with mutex protection for thread safety.
        PRODUCTION FIX (2026-05-10): Filter out test positions to prevent bleeding into production.
        PRODUCTION FIX (2026-05-11): Filter out closed positions (contracts=0) to prevent phantom positions.
        STALENESS GUARD (2026-05-22): Reject REST snapshots older than local cache to prevent stale overwrites.
        FORCE SYNC (2026-07-03): Added force parameter to bypass staleness guard for manual reconciliation.

        Args:
            positions: List of position dicts from REST API
            rest_timestamp: Unix timestamp when REST snapshot was fetched. If None, uses current time.
            force: If True, bypass staleness guard and force sync (use for manual reconciliation).
            open_orders: Optional list of open order dicts (market_id, side, contracts, price_cents).
                When ``cleanup_stale`` is True, these are used to avoid deleting a market that
                has a live order resting on the exchange.
            cleanup_stale: If True, an authoritative empty or partial REST snapshot may remove
                cache entries that the exchange does not report AND that have no live open order
                AND that the fills ledger shows net zero.  This is the safe path for an atomic
                exchange rebuild; it is NOT a blind force reset.
        """
        # Use current time if no timestamp provided
        if rest_timestamp is None:
            rest_timestamp = replay_time()

        # CRITICAL FIX (2026-08-11): Per-source idempotency guard.  Multiple
        # reconcilers (fills_poller, agent_grid, continuous_reconciliation,
        # venue_adapter) can race to call sync_from_rest with the same snapshot.
        # Allow force=True to override, otherwise skip stale/repeated snapshots.
        if not force and rest_timestamp <= self._last_rest_sync_timestamp:
            logger.debug(
                "[POSITION-CACHE-SYNC-IDEMPOTENCY] Skipping duplicate REST snapshot: "
                "ts=%.3f <= last=%.3f",
                rest_timestamp, self._last_rest_sync_timestamp,
            )
            return

        # Staleness check: reject if REST snapshot is older than local cache (unless force=True)
        if not force and self._last_sync:
            local_sync_time = self._last_sync.timestamp()
            age_seconds = rest_timestamp - local_sync_time

            # FIX 5: Relaxed staleness guard with warning
            # Log warning but allow sync even if REST is slightly stale (up to 60s)
            # This improves robustness during network issues by allowing sync to proceed
            # even when REST snapshot is older than local cache, with a warning instead of rejection.
            if age_seconds < -30.0:
                if age_seconds < -60.0:
                    # Still reject if very stale (> 60s)
                    logger.warning(
                        "[POSITION-CACHE-STALE] Rejecting very stale REST snapshot: "
                        f"REST timestamp={rest_timestamp:.0f}, local sync={local_sync_time:.0f}, "
                        f"age={age_seconds:.1f}s (threshold=-60s). Preserving local state."
                    )
                    return
                else:
                    # Allow sync with warning for moderately stale data (30-60s)
                    logger.warning(
                        "[POSITION-CACHE-STALE-WARN] REST snapshot is stale but proceeding: "
                        f"REST timestamp={rest_timestamp:.0f}, local sync={local_sync_time:.0f}, "
                        f"age={age_seconds:.1f}s (threshold=-30s). May overwrite newer state."
                    )

        async with self._ensure_mutex():
            try:
                # FIX 4: Conditional position cache clearing
                # Only clear cache if REST response is verified fresh and non-empty
                # This prevents data loss from transient API issues where Kalshi REST
                # temporarily returns 0 positions but fills ledger shows active positions.
                if not positions:
                    # CRITICAL FIX (2026-07-23): Rebuild from fills ledger when cache is empty
                    # If REST returns empty but cache is also empty, we may have missed positions
                    # during a restart. Rebuild from fills ledger (canonical source) to recover.
                    if not self._positions:
                        logger.info(
                            "[POSITION-CACHE-EMPTY-REST] REST returned empty positions and cache is empty - "
                            "attempting to rebuild from fills ledger (canonical source)"
                        )
                        try:
                            await self._rebuild_from_fills_ledger()
                            logger.info(
                                "[POSITION-CACHE-REBUILD] Successfully rebuilt position cache from fills ledger: %d positions",
                                len(self._positions)
                            )
                            # Empty REST sync is still a successful sync; keep freshness markers current.
                            self._last_sync = datetime.now(timezone.utc)
                            self._last_rest_sync_timestamp = rest_timestamp
                            return
                        except Exception as rebuild_err:
                            logger.error(
                                "[POSITION-CACHE-REBUILD] Failed to rebuild from fills ledger: %s",
                                rebuild_err,
                                exc_info=True
                            )
                            # Continue with empty cache - will recover on next fill
                    elif cleanup_stale and open_orders is not None:
                        # ATOMIC REBUILD: Exchange reports zero positions.  Use open orders and
                        # the fills ledger as secondary checks, and remove only confirmed phantoms.
                        logger.warning(
                            "[POSITION-CACHE-EMPTY-REST] Authoritative empty REST snapshot; "
                            "running stale/phantom position cleanup with %d open orders",
                            len(open_orders)
                        )
                        report = await self._cleanup_stale_positions(
                            exchange_positions=positions,
                            open_orders=open_orders,
                        )
                        logger.info(
                            "[POSITION-CACHE-EMPTY-REST-CLEANUP] kept=%d removed=%d halted=%d",
                            len(report.get("kept", [])),
                            len(report.get("removed", [])),
                            len(report.get("halted", [])),
                        )
                    else:
                        logger.warning(
                            "[POSITION-CACHE-EMPTY-REST] REST returned empty positions, preserving current state to prevent data loss "
                            "(cleanup_stale=%s, open_orders=%s)",
                            cleanup_stale, "provided" if open_orders is not None else "none"
                        )
                    # Empty REST sync is still a successful sync; keep freshness markers current.
                    self._last_sync = datetime.now(timezone.utc)
                    self._last_rest_sync_timestamp = rest_timestamp
                    return

                # CRITICAL FIX (2026-08-01): Preserve existing positions to avoid overwriting correct side from fills
                # Kalshi REST API always reports side="yes" (YES-side perspective), which would
                # invert the side for NO positions. We preserve the fill-based side and only update
                # size/price from REST.
                # CRITICAL FIX (2026-08-01): Add cross-validation with fills ledger to detect sync source disagreement
                # If REST data disagrees with fills ledger, flag position as unhealthy and trigger reconciliation
                existing_positions = dict(self._positions)

                # Cross-validate with fills ledger if available
                try:
                    fills_ledger = self._get_fills_ledger()
                    if fills_ledger:
                        # Get all fills from ledger
                        fills = fills_ledger.get_fills(since=datetime.now(timezone.utc) - timedelta(hours=24))

                        # Build expected signed-YES exposure from fills.
                        # This is the canonical reconciliation boundary: both REST and fills are
                        # normalized to the same signed-YES representation before comparison.
                        expected_signed_yes: Dict[str, int] = {}
                        for fill in fills:
                            market_id = getattr(fill, 'market_id', None)
                            if not market_id:
                                continue

                            # CRITICAL 2026-08-13: Use canonical centi-contracts for
                            # ledger exposure so it matches cache and REST in the same
                            # unit (quantity_cc).  Fall back to count_fp*100 only when
                            # quantity_cc is missing.
                            quantity_cc = fill.quantity_cc or 0
                            if quantity_cc == 0 and fill.count_fp:
                                try:
                                    quantity_cc = int(Decimal(str(fill.count_fp)) * Decimal("100"))
                                except Exception:
                                    quantity_cc = 0
                            if quantity_cc == 0:
                                continue

                            # 2026-08-12: Use canonical position action/side.
                            can_action = fill.canonical_position_action or fill.action
                            can_side = fill.canonical_position_side or fill.side
                            fill_yes = fill_to_signed_yes_exposure(
                                can_action, can_side, quantity_cc
                            )
                            if fill_yes == 0:
                                continue

                            expected_signed_yes[market_id] = expected_signed_yes.get(market_id, 0) + fill_yes

                        # Validate REST positions against fills ledger using signed-YES
                        validation_discrepancies = []
                        for pos in positions:
                            market_id = pos.get('market_id')
                            if market_id not in expected_signed_yes:
                                continue

                            # CRITICAL 2026-08-13: Normalize the REST position to
                            # centi-contracts before the signed-YES comparison.  The
                            # cache and ledger are canonical in quantity_cc.
                            rest_quantity_cc = pos.get('quantity_cc')
                            if rest_quantity_cc is None:
                                position_fp = pos.get('position_fp') or pos.get('count_fp') or pos.get('count')
                                if position_fp is not None:
                                    try:
                                        rest_quantity_cc = int(abs(Decimal(str(position_fp))) * Decimal("100"))
                                    except Exception:
                                        rest_quantity_cc = None
                                if rest_quantity_cc is None:
                                    try:
                                        rest_quantity_cc = int(Decimal(str(pos.get('contracts', 0))) * Decimal("100"))
                                    except Exception:
                                        rest_quantity_cc = int(pos.get('contracts', 0)) * 100
                            rest_side = _extract_canonical_rest_side(pos, market_id)
                            if rest_side is None:
                                continue
                            exchange_signed_yes = to_signed_yes_exposure(rest_side, rest_quantity_cc)
                            ledger_signed_yes = expected_signed_yes[market_id]

                            if exchange_signed_yes != ledger_signed_yes:
                                validation_discrepancies.append({
                                    'market_id': market_id,
                                    'rest_signed_yes': exchange_signed_yes,
                                    'ledger_signed_yes': ledger_signed_yes,
                                    'reason': 'signed_yes_mismatch'
                                })
                                logger.warning(
                                    "[POSITION-CACHE-VALIDATION] Discrepancy detected for %s: "
                                    "REST signed_yes=%d, fills ledger signed_yes=%d",
                                    market_id, exchange_signed_yes, ledger_signed_yes
                                )
                                self._emit_exposure_reconciliation(
                                    ticker=market_id,
                                    exchange_signed_yes=exchange_signed_yes,
                                    ledger_signed_yes=ledger_signed_yes,
                                    cache_signed_yes=self._get_cache_signed_yes(market_id),
                                    open_order_reserved_yes=0,
                                    source_timestamp=rest_timestamp,
                                    status='mismatch',
                                    from_exchange=True,
                                )

                        if validation_discrepancies:
                            logger.warning(
                                "[POSITION-CACHE-VALIDATION] Found %d discrepancies between REST and fills ledger. "
                                "Proceeding with REST sync but positions may be flagged as unhealthy.",
                                len(validation_discrepancies)
                            )

                        # 2026-08-13: Record the exchange snapshot for every ticker
                        # in the REST payload, including matched ones, so the per-fill
                        # FILL-CANONICALIZATION watermark has a fresh exchange position.
                        for pos in positions:
                            market_id = pos.get('market_id')
                            if not market_id:
                                continue
                            # CRITICAL 2026-08-13: REST positions are in centi-contracts
                            # for the three-way reconciliation.  Reuse the same normalization
                            # used in the discrepancy check above.
                            rest_quantity_cc = pos.get('quantity_cc')
                            if rest_quantity_cc is None:
                                position_fp = pos.get('position_fp') or pos.get('count_fp') or pos.get('count')
                                if position_fp is not None:
                                    try:
                                        rest_quantity_cc = int(abs(Decimal(str(position_fp))) * Decimal("100"))
                                    except Exception:
                                        rest_quantity_cc = None
                                if rest_quantity_cc is None:
                                    try:
                                        rest_quantity_cc = int(Decimal(str(pos.get('contracts', 0))) * Decimal("100"))
                                    except Exception:
                                        rest_quantity_cc = int(pos.get('contracts', 0)) * 100
                            rest_side = _extract_canonical_rest_side(pos, market_id)
                            if rest_side is None:
                                continue
                            exchange_signed_yes = to_signed_yes_exposure(rest_side, rest_quantity_cc)
                            ledger_signed_yes = expected_signed_yes.get(market_id, 0)
                            cache_signed_yes = self._get_cache_signed_yes(market_id)
                            self._emit_exposure_reconciliation(
                                ticker=market_id,
                                exchange_signed_yes=exchange_signed_yes,
                                ledger_signed_yes=ledger_signed_yes,
                                cache_signed_yes=cache_signed_yes,
                                open_order_reserved_yes=0,
                                source_timestamp=rest_timestamp,
                                status='matched' if (exchange_signed_yes == ledger_signed_yes == cache_signed_yes) else 'mismatch',
                                from_exchange=True,
                            )
                except Exception as validation_err:
                    logger.warning("[POSITION-CACHE-VALIDATION] Cross-validation with fills ledger failed: %s", validation_err)

                # VERIFICATION: Debug logging around sync_from_rest (before/after thesis_side)
                logger.info(
                    "[REST-SYNC-BEFORE] Syncing %d positions from REST, current cache has %d positions",
                    len(positions), len(existing_positions)
                )
                for market_id, cached_pos in existing_positions.items():
                    logger.info(
                        "[REST-SYNC-BEFORE-POSITION] market=%s thesis_side=%s contracts=%d",
                        market_id, cached_pos.thesis_side, cached_pos.contracts
                    )

                # CRITICAL FIX (2026-08-04): Do NOT wipe the entire cache on REST sync.
                # Many callers pass a single position from continuous reconciliation or
                # auto-resync. Clearing all positions causes phantom state loss and breaks
                # exit invariants. Instead, merge incoming positions with existing state:
                # update/add valid positions, delete positions explicitly reported as
                # closed (contracts=0), and preserve existing positions on invalid data.
                # Build a set of market IDs we saw in this REST payload for later cleanup.
                incoming_market_ids = set()
                positions_processed = 0
                positions_filtered = 0

                for pos in positions:
                    market_id = pos.get("market_id") or pos.get("ticker")
                    if not market_id:
                        continue

                    # PRODUCTION FIX (2026-05-10): Filter out test positions before side validation
                    if _is_test_ticker(market_id):
                        logger.warning(f"Skipping test ticker in position cache sync: {market_id}")
                        positions_filtered += 1
                        continue

                    # PRODUCTION FIX (2026-07-03): Filter out expired positions before side validation.
                    # Expired markets should not be in the cache as they can't be traded.
                    # The exchange may report a settled market with an unparseable/unknown side,
                    # which should be ignored, not quarantined as a data-quality failure.
                    # Also remove any zero-contract cached position for an expired market so it
                    # does not survive and block the next 15m window.
                    if _is_expired_ticker(market_id):
                        is_zero = (
                            pos.get("quantity_cc") == 0
                            or pos.get("contracts") == 0
                            or pos.get("position_fp") == 0
                        )
                        if market_id in self._positions and is_zero:
                            logger.warning(
                                f"[POSITION-CACHE-SYNC-CLOSE] Removing settled expired position from cache: {market_id} (contracts=0)"
                            )
                            del self._positions[market_id]
                            try:
                                from merid.position_management.position_monitor import get_position_monitor
                                monitor = get_position_monitor()
                                monitor.remove_position(market_id)
                                logger.info(
                                    "[POSITION-MONITOR-INTEGRATION] Removed closed position from monitor: market=%s",
                                    market_id
                                )
                            except Exception as monitor_err:
                                logger.warning(
                                    "[POSITION-MONITOR-INTEGRATION] Failed to remove closed position from monitor: %s",
                                    monitor_err
                                )
                        elif not is_zero:
                            # 2026-08-28: Exchange is still reporting a non-zero
                            # position for an expired/closed market that has not
                            # settled.  Quarantine it so it does not block new
                            # entries or consume a slot.
                            logger.warning(
                                f"[POSITION-CACHE-SYNC-QUARANTINE] Quarantining expired non-zero position: {market_id}"
                            )
                            await self.quarantine_ticker(market_id)
                        else:
                            logger.warning(f"Skipping expired ticker in position cache sync: {market_id}")
                        positions_filtered += 1
                        continue

                    # CRITICAL 2026-08-09: Use quantity_cc as canonical. contracts is display only.
                    quantity_cc = pos.get("quantity_cc")
                    if quantity_cc is None:
                        # Try position_fp (signed fixed-point net position) first. The side is
                        # determined separately; the absolute count is the canonical size.
                        position_fp = pos.get("position_fp") or pos.get("count_fp") or pos.get("count")
                        if position_fp is not None:
                            try:
                                quantity_cc = int(abs(Decimal(str(position_fp))) * Decimal("100"))
                            except Exception:
                                quantity_cc = None
                        if quantity_cc is None:
                            try:
                                quantity_cc = int(Decimal(str(pos.get("contracts", 0))) * Decimal("100"))
                            except Exception:
                                quantity_cc = int(pos.get("contracts", 0)) * 100
                    contracts = int(quantity_cc / 100)

                    # PRODUCTION FIX (2026-05-11): Only cache open positions (contracts > 0)
                    # Closed positions (contracts=0) should not be in the cache.
                    # Handle this before side validation so a missing/unknown side on a
                    # settled/closed position is treated as an exit, not a data-quality failure.
                    if quantity_cc == 0:
                        if market_id in self._positions:
                            logger.warning(
                                f"[POSITION-CACHE-SYNC-CLOSE] Removing closed position from cache: {market_id} (contracts=0)"
                            )
                            del self._positions[market_id]
                            try:
                                from merid.position_management.position_monitor import get_position_monitor
                                monitor = get_position_monitor()
                                monitor.remove_position(market_id)
                                logger.info(
                                    "[POSITION-MONITOR-INTEGRATION] Removed closed position from monitor: market=%s",
                                    market_id
                                )
                            except Exception as monitor_err:
                                logger.warning(
                                    "[POSITION-MONITOR-INTEGRATION] Failed to remove closed position from monitor: %s",
                                    monitor_err
                                )
                        else:
                            logger.warning(f"Skipping closed position in position cache sync: {market_id} (contracts=0)")
                        positions_filtered += 1
                        continue

                    # CRITICAL: Validate side before any use.  Missing/inconsistent
                    # exchange side metadata is a data-quality failure, not a YES default.
                    try:
                        validated_rest_side = _require_outcome_side_for_position(pos, market_id)
                    except (SideValidationError, SideValidationErrorLocal) as side_err:
                        logger.error(
                            "[POSITION-CACHE-SIDE-INVALID] %s: quarantining position (not caching) due to %s",
                            market_id, side_err,
                        )
                        self.require_rest_reconciliation(market_id, reason=f"invalid_outcome_side:{side_err}")
                        positions_filtered += 1
                        continue

                    incoming_market_ids.add(market_id)

                    # DEBUG: Log all positions from API before filtering
                    logger.info(
                        "[POSITION-CACHE-DEBUG] API returned position: market_id=%s "
                        "contracts=%s side=%s avg_price_cents=%s",
                        market_id, contracts, validated_rest_side,
                        pos.get('avg_price_cents', 'N/A')
                    )

                    # CRITICAL FIX (2026-08-04): Preserve existing position on invalid/negative REST data
                    # instead of discarding it. A single bad REST response should not wipe a tracked position.
                    # The Kalshi client now normalizes negative position_fp, so this path is defensive.
                    if quantity_cc < 0:
                        if market_id in self._positions:
                            logger.warning(
                                f"[POSITION-CACHE-SYNC-PRESERVE] Preserving existing position for {market_id} "
                                f"(ignoring invalid REST contracts={contracts})"
                            )
                        else:
                            logger.warning(
                                f"Skipping invalid position in position cache sync: {market_id} "
                                f"(contracts={contracts} side={validated_rest_side}) - negative contracts indicate side inversion or API error"
                            )
                            positions_filtered += 1
                        continue

                    # CRITICAL FIX (2026-08-01): Calculate avg_price_cents from REST API data when not provided
                    # Kalshi REST API provides market_exposure_dollars and position_fp, which can be used
                    # to calculate the weighted average entry price: avg_price = market_exposure_dollars / position_fp
                    # IMPORTANT: Use market_exposure_dollars (current position cost) NOT total_traded_dollars (cumulative)
                    # This is the industry-standard method for reconstructing entry prices after restart.
                    avg_price_from_rest = pos.get("avg_price_cents")
                    market_exposure_dollars = pos.get("market_exposure_dollars")
                    position_fp = pos.get("position_fp")
                    avg_price_source = None  # Track source for side-space conversion

                    if avg_price_from_rest is not None and avg_price_from_rest != 0:
                        # REST API or DTO adapter provided an explicit avg_price_cents.
                        # Kalshi's current MarketPosition / VenuePosition reports the
                        # average in the position's own outcome space (NO price for a NO
                        # position, YES price for a YES position), so do NOT convert.
                        avg_price_cents = int(avg_price_from_rest)
                        if 0 < avg_price_cents < 100:
                            entry_price_state = "known"
                            avg_price_source = "rest_avg_price_cents"
                            logger.debug(
                                "[POSITION-CACHE] REST API provided avg_price_cents=%d for %s",
                                avg_price_cents, market_id
                            )
                        else:
                            avg_price_cents = None
                            entry_price_state = "invalid"
                            logger.warning(
                                "[POSITION-CACHE] REST avg_price_cents=%d out of range (1-99) for %s - using fallback",
                                int(avg_price_from_rest), market_id
                            )
                    elif market_exposure_dollars is not None and position_fp is not None:
                        # Calculate avg_price_cents from market_exposure_dollars / |position_fp|.
                        # market_exposure_dollars is the cost paid for the position (positive),
                        # and position_fp is the signed net contract count (negative for NO).
                        # Dividing cost by the absolute position size yields the price in the
                        # position's own outcome space.
                        try:
                            market_exposure = float(market_exposure_dollars)
                            position_count = float(position_fp)

                            if position_count != 0:
                                avg_price_dollars = market_exposure / abs(position_count)
                                avg_price_cents = int(avg_price_dollars * 100)

                                if 0 < avg_price_cents < 100:
                                    entry_price_state = "known"
                                    avg_price_source = "rest_market_exposure"
                                    logger.info(
                                        "[POSITION-CACHE] Calculated avg_price_cents=%d from REST data for %s (market_exposure=$%.2f, position_fp=%.2f)",
                                        avg_price_cents, market_id, market_exposure, position_count
                                    )
                                else:
                                    avg_price_cents = None
                                    entry_price_state = "invalid"
                                    logger.warning(
                                        "[POSITION-CACHE] Calculated avg_price_cents=%d out of range (1-99) for %s - using fallback",
                                        avg_price_cents, market_id
                                    )
                            else:
                                avg_price_cents = None
                                entry_price_state = "invalid"
                                logger.warning(
                                    "[POSITION-CACHE] Cannot calculate avg_price_cents for %s - position_fp=%.2f (zero)",
                                    market_id, position_count
                                )
                        except (ValueError, ZeroDivisionError) as calc_err:
                            avg_price_cents = None
                            entry_price_state = "invalid"
                            logger.warning(
                                "[POSITION-CACHE] Failed to calculate avg_price_cents for %s from REST data: %s",
                                market_id, calc_err
                            )
                    else:
                        # Missing data - try to reconstruct from fills_ledger before giving up
                        avg_price_cents = None
                        entry_price_state = "unknown"

                        # CRITICAL FIX (2026-08-01): Fallback to fills_ledger when REST API data is insufficient
                        # This handles cases where Kalshi REST API returns avg_price_cents=0 or missing fields
                        if self._fills_ledger:
                            try:
                                # Look up the most recent entry fill for this market
                                fills = self._fills_ledger.get_fills_by_market(market_id)
                                if fills:
                                    # Find the first entry fill (buy action) for this market.
                                    # Use the fill's stored YES/NO leg price in the entry side's own space.
                                    for fill in fills:
                                        fill_action = (getattr(fill, 'canonical_position_action', None) or getattr(fill, 'action', '')).lower()
                                        fill_side = (getattr(fill, 'canonical_position_side', None) or getattr(fill, 'side', '')).lower()
                                        if fill_action == 'buy' and fill_side in ('yes', 'no'):
                                            fill_price = _fill_position_side_price_cents(fill, fill_side)
                                            if fill_price and fill_price > 0:
                                                avg_price_cents = int(fill_price)
                                                entry_price_state = "fills_ledger"
                                                avg_price_source = "fills_ledger"
                                                logger.info(
                                                    "[POSITION-CACHE] Reconstructed avg_price_cents=%d from fills_ledger for %s (fill_id=%s, side=%s)",
                                                    avg_price_cents, market_id, getattr(fill, 'fill_id', 'unknown'), fill_side
                                                )
                                                break
                            except Exception as fills_err:
                                logger.debug("[POSITION-CACHE] Could not reconstruct avg_price from fills_ledger for %s: %s", market_id, fills_err)

                        if avg_price_cents is None:
                            logger.warning(
                                "[POSITION-CACHE] REST API returned insufficient data for %s (avg_price_cents=%s, market_exposure_dollars=%s, position_fp=%s) - setting to None with state=unknown",
                                market_id, avg_price_from_rest, market_exposure_dollars, position_fp
                            )

                    # REST-reported avg_price_cents is authoritative for the position's
                    # own outcome space.  A fill-derived price is logged for audit but
                    # never overrides a valid REST average.
                    if avg_price_cents is not None and self._fills_ledger:
                        try:
                            fills = self._fills_ledger.get_fills_by_market(market_id)
                            if fills:
                                latest_fill = fills[-1]
                                fill_pos_price = latest_fill.position_side_price_cents()
                                if fill_pos_price and fill_pos_price > 0:
                                    divergence = abs(avg_price_cents - fill_pos_price)
                                    if divergence >= 10:
                                        logger.warning(
                                            "[POSITION-CACHE-AVG-DIVERGENCE] market=%s rest_avg=%d fill_pos_price=%d divergence=%dc - "
                                            "REST average diverges from latest fill price; using REST value",
                                            market_id, avg_price_cents, fill_pos_price, divergence,
                                        )
                        except Exception as guard_err:
                            logger.debug("[POSITION-CACHE] avg divergence check failed for %s: %s", market_id, guard_err)

                    # CRITICAL FIX (2026-07-21): Use preserved thesis_side from fill-based cache instead of REST API
                    # Kalshi REST API reports positions from a YES-side perspective, which can
                    # invert the side for NO positions. We preserve the thesis_side (immutable strategy thesis).
                    # The 'side' field may be refreshed from REST for diagnostics, but thesis_side is immutable.
                    preserved_side = validated_rest_side  # REST side for diagnostics only
                    if market_id in existing_positions:
                        existing_thesis_side = existing_positions.get(market_id).thesis_side
                        # CRITICAL FIX (2026-08-09): If an existing position has unknown thesis_side,
                        # re-try inference from fill history and REST payload.  This prevents positions
                        # created before fill ledger sync from permanently staying unknown and blocking
                        # PositionMonitor exits.
                        if not existing_thesis_side or existing_thesis_side == "unknown":
                            inferred = self._infer_thesis_side_from_fill_history(market_id)
                            if inferred:
                                preserved_thesis_side = inferred
                                logger.info(
                                    "[POSITION-CACHE-THESIS-PRESERVE-INFER] market=%s inferred thesis_side=%s from fill history",
                                    market_id, preserved_thesis_side
                                )
                            else:
                                # Best-effort: canonical REST side and signed position_fp.
                                rest_side = validated_rest_side
                                position_fp = pos.get("position_fp") or pos.get("signed_size")
                                if rest_side in ("yes", "no"):
                                    preserved_thesis_side = rest_side
                                    logger.warning(
                                        "[POSITION-CACHE-THESIS-PRESERVE-REST-SIDE] market=%s inferred thesis_side=%s from REST side/outcome_id",
                                        market_id, preserved_thesis_side
                                    )
                                elif position_fp is not None:
                                    try:
                                        fp = float(position_fp)
                                        if fp < 0:
                                            preserved_thesis_side = "no"
                                        elif fp > 0:
                                            preserved_thesis_side = "yes"
                                    except Exception:
                                        pass
                                    if preserved_thesis_side in ("yes", "no"):
                                        logger.warning(
                                            "[POSITION-CACHE-THESIS-PRESERVE-REST-FP] market=%s inferred thesis_side=%s from position_fp sign",
                                            market_id, preserved_thesis_side
                                        )

                                if not preserved_thesis_side or preserved_thesis_side == "unknown":
                                    preserved_thesis_side = existing_thesis_side
                        else:
                            preserved_thesis_side = existing_thesis_side

                        logger.info(
                            "[POSITION-CACHE-THESIS-PRESERVE] market=%s using preserved thesis_side=%s from fill-based cache (REST reported side=%s)",
                            market_id, preserved_thesis_side, validated_rest_side
                        )

                        # CRITICAL FIX (2026-07-21): Desync detection - compute rest_side_sign from position_fp
                        # If REST reports opposite exposure to thesis_side, raise sync alarm and mark as dirty
                        # This detects strategy sync errors where REST and our thesis disagree
                        rest_side = validated_rest_side
                        rest_contracts = contracts

                        # Compute REST side sign: positive contracts = long, negative = short
                        # Note: Kalshi REST always reports positive contracts with side indicating direction
                        # So we need to interpret side to determine exposure direction
                        rest_exposure_sign = 1 if rest_side.lower() == "yes" else -1

                        # Compare REST exposure sign to thesis_side
                        # thesis_side=YES expects positive YES exposure (rest_exposure_sign=+1)
                        # thesis_side=NO expects positive NO exposure (rest_exposure_sign=-1 from Kalshi perspective)
                        # However, Kalshi quotes everything from YES side, so this is complex
                        # Simplified check: if thesis_side=NO but REST reports side=yes, that's a potential desync
                        if preserved_thesis_side.lower() == "no" and rest_side.lower() == "yes":
                            # This is expected - Kalshi REST always reports side="yes" from YES-side perspective
                            # So we can't detect desync from side alone. We need to check if the position exists
                            # in our cache and has the correct thesis_side, which we already preserve.
                            logger.debug(
                                "[POSITION-CACHE-SYNC-EXPECTED] market=%s thesis_side=NO but REST reports side=yes (Kalshi YES-side perspective is expected)",
                                market_id
                            )
                        elif preserved_thesis_side.lower() == "yes" and rest_side.lower() == "no":
                            # This is unexpected - we have a YES thesis but REST reports NO side
                            # This could indicate a desync or manual intervention
                            logger.critical(
                                "[POSITION-CACHE-SYNC-ALARM] market=%s thesis_side=YES but REST reports side=NO - "
                                "strategy thesis and REST exposure disagree! This may indicate a side inversion, "
                                "manual intervention, or sync error. Marking position as dirty.",
                                market_id
                            )
                            # VERIFICATION: Record sync error in thesis_side_monitor
                            try:
                                from merid.event_venues.kalshi.thesis_side_monitor import get_thesis_side_monitor
                                monitor = get_thesis_side_monitor()
                                monitor.record_sync_error(
                                    market_id=market_id,
                                    thesis_side=preserved_thesis_side,
                                    rest_side=rest_side,
                                    context="rest_sync_desync"
                                )
                            except Exception as monitor_err:
                                logger.debug("[POSITION-CACHE] Could not record sync error in monitor: %s", monitor_err)
                            # Mark position as dirty - do not flip thesis_side automatically
                            # This requires manual investigation and potential flatten/re-open
                            continue  # Skip this position in sync, preserving existing state
                        else:
                            # Side matches thesis_side (or both are yes which is Kalshi's default)
                            logger.debug(
                                "[POSITION-CACHE-SYNC-OK] market=%s thesis_side=%s REST side=%s - consistent",
                                market_id, preserved_thesis_side, rest_side
                            )
                    else:
                        # New position from REST (not in existing cache)
                        # CRITICAL FIX (2026-08-13): Trust REST outcome_id / side and signed
                        # position_fp before fill history. outcome_side is the canonical Kalshi
                        # field for the user's directional exposure (long YES or long NO).
                        # position_fp is a signed net position: negative means long NO / short YES.
                        # Fill history is a fallback because legacy raw side/action fields can be
                        # ambiguous and have produced side inversions in this path.
                        preserved_thesis_side = "unknown"

                        # 1. Canonical REST side from fail-closed parser.
                        if validated_rest_side in ("yes", "no"):
                            preserved_thesis_side = validated_rest_side
                            logger.info(
                                "[POSITION-CACHE-NEW-POSITION-REST-SIDE] market=%s thesis_side=%s from REST outcome_id/side",
                                market_id, preserved_thesis_side,
                            )

                        # 2. Signed position_fp / signed_size (yes-positive, no-negative net position).
                        if preserved_thesis_side == "unknown":
                            position_fp = pos.get("position_fp") or pos.get("signed_size")
                            if position_fp is not None:
                                try:
                                    fp = float(position_fp)
                                    if fp < 0:
                                        preserved_thesis_side = "no"
                                    elif fp > 0:
                                        preserved_thesis_side = "yes"
                                except Exception:
                                    fp = 0.0
                                if preserved_thesis_side in ("yes", "no"):
                                    logger.info(
                                        "[POSITION-CACHE-NEW-POSITION-REST-FP] market=%s thesis_side=%s from position_fp sign",
                                        market_id, preserved_thesis_side,
                                    )

                        # 3. Durable fill history / fills ledger (fallback only).
                        if preserved_thesis_side == "unknown":
                            inferred_side = self._infer_thesis_side_from_fill_history(market_id)
                            if inferred_side:
                                preserved_thesis_side = inferred_side
                                logger.info(
                                    "[POSITION-CACHE-NEW-POSITION-INFERRED-SIDE] market=%s inferred thesis_side=%s from fill history",
                                    market_id, preserved_thesis_side,
                                )
                            else:
                                if self._fills_ledger:
                                    try:
                                        fills = self._fills_ledger.get_fills_by_market(market_id)
                                        if fills:
                                            for fill in fills:
                                                # Prefer canonical side over raw exchange side
                                                fill_side = getattr(fill, "canonical_position_side", None) or getattr(fill, "side", None) or ""
                                                fill_action = getattr(fill, "canonical_position_action", None) or getattr(fill, "action", None) or ""
                                                if fill_action == "buy" and fill_side in ("yes", "no"):
                                                    preserved_thesis_side = fill_side.lower()
                                                    logger.info(
                                                        "[POSITION-CACHE-NEW-POSITION-FILLS-LEDGER] market=%s reconstructed thesis_side=%s from fills_ledger (fill_id=%s)",
                                                        market_id, preserved_thesis_side, getattr(fill, "fill_id", "unknown")
                                                    )
                                                    break
                                    except Exception as fills_err:
                                        logger.debug("[POSITION-CACHE] Could not reconstruct thesis_side from fills_ledger for new position %s: %s", market_id, fills_err)

                        if preserved_thesis_side == "unknown":
                            logger.critical(
                                "[POSITION-CACHE-NEW-POSITION-UNKNOWN-SIDE] market=%s new position from REST with unknown thesis_side - "
                                "Kalshi REST outcome_id/side and position_fp are missing or unparseable and fill history lookup failed. "
                                "This position will be marked as thesis_side='unknown' and will require "
                                "manual intervention to determine the correct side before trading can proceed.",
                                market_id
                            )

                    # Derive agent_id from ticker for composite key (REST sync path)
                    try:
                        from config.kalshi_crypto_config import kalshi_ticker_to_asset
                        asset = kalshi_ticker_to_asset(market_id)
                        if asset and asset.upper() in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
                            sync_agent_id = f"{asset.upper()}_15M"
                        else:
                            sync_agent_id = "unknown_agent"
                    except Exception as derive_err:
                        logger.debug("[POSITION-CACHE] Could not derive agent_id from ticker in REST sync: %s", derive_err)
                        sync_agent_id = "unknown_agent"

                    # CRITICAL FIX (2026-08-13): Do NOT convert REST-reported average price.
                    # Kalshi's MarketPosition / VenuePosition reports the position's cost
                    # and average in the position's own outcome space (NO price for a NO
                    # position). The prior 100 - price conversion was inverting correct
                    # NO entry prices into wrong YES-derived prices.

                    # Canonical side for the cached record. Use the preserved thesis_side
                    # when known; otherwise fall back to the REST-reported side. This keeps
                    # the cache's own price/exposure math in the position's outcome space.
                    canonical_side_for_record = (
                        preserved_thesis_side
                        if preserved_thesis_side and preserved_thesis_side != "unknown"
                        else preserved_side
                    )

                    # CRITICAL FIX (2026-08-12): Preserve position provenance when an
                    # existing position is re-synced from REST. REST snapshots carry
                    # quantity/price/realized PnL, but they must not wipe the entry
                    # fill/intent linkage, original risk parameters, or book capture
                    # metadata that the exit policy uses for provenance. For new
                    # positions, create a fresh record with no provenance (REST alone
                    # is not a trusted source).
                    existing_position = existing_positions.get(market_id)

                    # CRITICAL FIX (2026-08-22): For new or unprovenanced REST positions,
                    # try to rebuild the position from the fills_ledger and the persisted
                    # TP target registry before creating a rest_sync record.  This
                    # recovers AT_FILL book capture and model provenance across restarts
                    # and prevents "Model-invalidation loss exit blocked" on real positions.
                    recomputed_position: Optional[CachedPosition] = None
                    if existing_position is None and sync_agent_id != "unknown_agent":
                        try:
                            recomputed_position = await self.recompute_position_from_ledger(market_id, sync_agent_id)
                        except Exception as recompute_err:
                            logger.debug(
                                "[POSITION-CACHE-REST-SYNC] Could not recompute %s from ledger: %s",
                                market_id, recompute_err
                            )

                    if existing_position is not None or recomputed_position is not None:
                        # Determine whether REST-provided SL/TP are allowed to override
                        # the existing record. Only original-persisted schema-2 records
                        # with a linkage may carry TP/SL; otherwise keep the existing
                        # provenance (and any existing TP/SL it has).
                        base_position = existing_position if existing_position is not None else recomputed_position
                        base_risk_state = getattr(base_position, "risk_params_state", "unknown")
                        base_schema = getattr(base_position, "risk_params_schema_version", 1)
                        base_linkage = (
                            base_position.client_order_id
                            or base_position.entry_fill_id
                            or base_position.entry_intent_id
                            or base_position.entry_order_id
                        )
                        keep_existing_risk = (
                            base_risk_state == "original_persisted"
                            and base_schema >= 2
                            and base_linkage
                        )

                        self._positions[market_id] = replace(
                            base_position,
                            market_id=market_id,
                            agent_id=sync_agent_id,
                            contracts=contracts,
                            quantity_cc=quantity_cc,
                            side=canonical_side_for_record,
                            thesis_side=preserved_thesis_side,
                            outcome_side=canonical_side_for_record,
                            book_side="ask",
                            avg_price_cents=avg_price_cents,
                            entry_price_state=entry_price_state,
                            realized_pnl_usd=Decimal(str(pos.get("realized_pnl", 0))),
                            unrealized_pnl_usd=Decimal(str(pos.get("unrealized_pnl", 0))),
                            take_profit_price_cents=(
                                pos.get("take_profit_price_cents")
                                if keep_existing_risk and pos.get("take_profit_price_cents") is not None
                                else base_position.take_profit_price_cents
                            ),
                            take_profit_r_multiple=(
                                pos.get("take_profit_r_multiple")
                                if keep_existing_risk and pos.get("take_profit_r_multiple") is not None
                                else base_position.take_profit_r_multiple
                            ),
                            stop_loss_price_cents=(
                                pos.get("stop_loss_price_cents")
                                if keep_existing_risk and pos.get("stop_loss_price_cents") is not None
                                else base_position.stop_loss_price_cents
                            ),
                            stop_loss_enabled=(
                                pos.get("stop_loss_enabled", base_position.stop_loss_enabled)
                                if keep_existing_risk
                                else base_position.stop_loss_enabled
                            ),
                            risk_params_state=(
                                "original_persisted" if keep_existing_risk else base_position.risk_params_state
                            ),
                            risk_params_schema_version=base_position.risk_params_schema_version,
                            ratchet_activated=pos.get("ratchet_activated", base_position.ratchet_activated),
                            ratchet_floor_price_cents=pos.get("ratchet_floor_price_cents", base_position.ratchet_floor_price_cents),
                            ratchet_activation_timestamp=pos.get("ratchet_activation_timestamp", base_position.ratchet_activation_timestamp),
                        )
                    else:
                        self._positions[market_id] = CachedPosition(
                            market_id=market_id,
                            agent_id=sync_agent_id,  # Composite key component
                            contracts=contracts,
                            quantity_cc=quantity_cc,
                            side=canonical_side_for_record,  # Canonical own-side (not REST diagnostic)
                            thesis_side=preserved_thesis_side,  # Immutable strategy thesis
                            outcome_side=canonical_side_for_record,
                            book_side="ask",
                            avg_price_cents=avg_price_cents,
                            entry_price_state=entry_price_state,  # CRITICAL FIX (2026-07-23): Track data quality
                            realized_pnl_usd=Decimal(str(pos.get("realized_pnl", 0))),
                            unrealized_pnl_usd=Decimal(str(pos.get("unrealized_pnl", 0))),
                            take_profit_price_cents=pos.get("take_profit_price_cents"),
                            take_profit_r_multiple=pos.get("take_profit_r_multiple"),
                            stop_loss_price_cents=pos.get("stop_loss_price_cents"),
                            # CRITICAL FIX (2026-07-23): Set risk_params_state based on SL/TP availability.
                            # 2026-08-24: "known" is not a valid RiskParamsState; use "fallback" when
                            # REST provides an SL (or TP) and "unknown" otherwise.
                            risk_params_state="fallback" if (pos.get("stop_loss_price_cents") is not None) else "unknown",
                            # CRITICAL FIX (2026-08-23): Record that this position was discovered via REST sync.
                            fill_source="rest_sync",
                            # Preserve ratchet state from cache if available (defaults to inactive)
                            ratchet_activated=pos.get("ratchet_activated", False),
                            ratchet_floor_price_cents=pos.get("ratchet_floor_price_cents"),
                            ratchet_activation_timestamp=pos.get("ratchet_activation_timestamp"),
                        )

                    # CRITICAL FIX (2026-08-23): Rehydrate the exit plan from durable
                    # provenance for any REST-synced position that is not already trusted.
                    try:
                        self.rehydrate_cached_position(self._positions[market_id])
                    except Exception as rehydrate_err:
                        logger.debug(
                            "[POSITION-CACHE-REST-SYNC] Could not rehydrate %s: %s",
                            market_id, rehydrate_err
                        )

                    positions_processed += 1

                # CRITICAL FIX (2026-08-12): When force=True and cleanup_stale=True, REST is
                # treated as an authoritative full snapshot.  Remove any cached 15m positions
                # that the exchange does not report, but only after checking open orders and the
                # fills ledger.  This is the exchange-authoritative cleanup, not a blind force reset.
                if force and cleanup_stale:
                    report = await self._cleanup_stale_positions(
                        exchange_positions=positions,
                        open_orders=open_orders,
                    )
                    positions_filtered += len(report.get("removed", []))
                    logger.info(
                        "[POSITION-CACHE-FORCE-CLEANUP] removed=%d kept=%d halted=%d",
                        len(report.get("removed", [])),
                        len(report.get("kept", [])),
                        len(report.get("halted", [])),
                    )

                # VERIFICATION: Debug logging around sync_from_rest (after sync thesis_side)
                logger.info(
                    "[REST-SYNC-AFTER] Sync complete: processed=%d filtered=%d total_positions=%d",
                    positions_processed, positions_filtered, len(self._positions)
                )
                for market_id, cached_pos in self._positions.items():
                    logger.info(
                        "[REST-SYNC-AFTER-POSITION] market=%s thesis_side=%s contracts=%d",
                        market_id, cached_pos.thesis_side, cached_pos.contracts
                    )

                # CRITICAL FIX (2026-07-16): Add REST-synced positions to PositionMonitor for exit enforcement
                # This ensures positions are monitored after restart when synced from REST API
                if positions_processed > 0:
                    try:
                        from merid.position_management.position_monitor import get_position_monitor
                        from merid.position_management.position import Position, PositionSide, TrailingType
                        from merid.event_venues.kalshi.market_filter import parse_expiry_from_ticker

                        monitor = get_position_monitor()

                        # CRITICAL FIX (2026-07-19): Validate position age before adding to PositionMonitor
                        # Only add positions from current or recent 15-minute windows to prevent
                        # premature exit orders for stale positions from previous sessions
                        now_ts = _time.time()

                        # Read profile configuration for trailing stops
                        trailing_enabled = False
                        trailing_distance_cents = 5
                        min_profit_cents = 12
                        activation_delay_sec = 30

                        try:
                            from merid.risk.profiles.crypto_15m_profile import get_active_profile, is_profile_active
                            if is_profile_active():
                                adapter = get_active_profile()
                                profile = adapter.profile
                                trailing_enabled = profile.trailing_stop_enabled
                                trailing_distance_cents = profile.trailing_stop_trailing_distance_cents
                                min_profit_cents = profile.trailing_stop_min_profit_cents
                                activation_delay_sec = profile.trailing_stop_activation_delay_sec
                        except Exception as ts_err:
                            logger.debug("[POSITION-CACHE] Could not read trailing stop config for REST sync: %s", ts_err)

                        # Add each synced position to PositionMonitor
                        for market_id, cached_pos in self._positions.items():
                            if cached_pos.contracts <= 0:
                                continue

                            # CRITICAL FIX (2026-07-22): Skip positions with thesis_side='unknown'
                            # These positions cannot be safely managed for exits until the correct side
                            # is determined from fill history or manual intervention.
                            if cached_pos.thesis_side == "unknown":
                                logger.warning(
                                    "[POSITION-CACHE-REST-SYNC] Skipping position with unknown thesis_side for monitor: "
                                    "market=%s - cannot add to PositionMonitor until thesis_side is determined from fill history or manual intervention",
                                    market_id
                                )
                                continue

                            # CRITICAL FIX (2026-08-01): Use fallback entry price for positions with unknown/invalid entry price
                            # Instead of skipping these positions (which breaks exit policy), use fallback prices
                            # to enable monitoring and exit execution. The fallback prices are already used for
                            # notional calculation, so we should use them for PositionMonitor as well.
                            # Track if we used fallback price for this position
                            original_avg_price = None
                            if cached_pos.entry_price_state in ("unknown", "invalid"):
                                # Use fallback price based on asset (same logic as notional calculation)
                                fallback_price_cents = _get_fallback_price_for_market(market_id)
                                if fallback_price_cents:
                                    logger.warning(
                                        "[POSITION-CACHE-REST-SYNC] Using fallback entry price for monitor: "
                                        "market=%s entry_price_state=%s fallback=%dc",
                                        market_id, cached_pos.entry_price_state, fallback_price_cents
                                    )
                                    # Temporarily override avg_price_cents for PositionMonitor
                                    # Store original on the object so any early exit (continue/exception)
                                    # can still restore the true cache value.
                                    original_avg_price = cached_pos.avg_price_cents
                                    cached_pos._original_avg_price = original_avg_price
                                    cached_pos.avg_price_cents = fallback_price_cents
                                    # Mark that we're using fallback so we can restore later
                                    cached_pos._using_fallback_price = True
                                else:
                                    logger.warning(
                                        "[POSITION-CACHE-REST-SYNC] Skipping position with unknown/invalid entry price for monitor: "
                                        "market=%s entry_price_state=%s - cannot determine fallback price",
                                        market_id, cached_pos.entry_price_state
                                    )
                                    continue

                            # Continue with rest of the position processing
                            # ...

                            # CRITICAL FIX (2026-08-11): REST sync reconciles quantity and
                            # fill state; it must not invent a new TP/SL policy for positions
                            # with unknown provenance.  Unknown-provenance positions are
                            # monitorable and reconcilable, but have no automatic exit policy.
                            cached_risk_state = getattr(cached_pos, "risk_params_state", "unknown")
                            schema_version = getattr(cached_pos, "risk_params_schema_version", 1)
                            is_original = (
                                cached_risk_state == "original_persisted"
                                and schema_version >= 2
                                and (cached_pos.client_order_id or cached_pos.entry_fill_id)
                            )

                            if not is_original:
                                logger.warning(
                                    "[POSITION-CACHE-REST-SYNC] market=%s side=%s entry=%dc "
                                    "risk_params_state=%s - not restoring TP/SL; REST must not invent policy",
                                    market_id, cached_pos.side, cached_pos.avg_price_cents or 0,
                                    cached_risk_state,
                                )

                            # CRITICAL FIX (2026-07-19): Validate position age before adding to PositionMonitor
                            # Only add positions from current or recent 15-minute windows to prevent
                            # premature exit orders for stale positions from previous sessions
                            try:
                                expiry_ts = parse_expiry_from_ticker(market_id)
                                if expiry_ts > 0 and now_ts > expiry_ts + 1800:  # 30 minutes = 1800 seconds
                                    logger.warning(
                                        "[POSITION-CACHE-REST-SYNC] Skipping stale position for monitor: "
                                        "market=%s expired %d seconds ago (>30m threshold) - "
                                        "preventing premature exit orders for old positions",
                                        market_id,
                                        int(now_ts - expiry_ts)
                                    )
                                    # Skip adding to monitor - position is too old
                                    continue
                            except Exception as age_err:
                                logger.debug(
                                    "[POSITION-CACHE-REST-SYNC] Could not validate position age for %s: %s",
                                    market_id, age_err
                                )
                                # If age check fails, conservative approach: add to monitor

                            side_enum = PositionSide.YES if cached_pos.side.lower() == "yes" else PositionSide.NO

                            # CRITICAL 2026-08-13: Preserve cached TP/SL when the position's
                            # provenance is not original, and mark the state as "fallback" so
                            # spread-stop invariants remain fail-closed.  We never invent new
                            # TP/SL from a REST-reconstructed average price; missing policies are
                            # simply left unset.
                            sl_price = cached_pos.stop_loss_price_cents
                            tp_price = cached_pos.take_profit_price_cents
                            entry_fill_price_cents = (
                                cached_pos.entry_fill_price_cents
                                if (cached_pos.entry_price_state == "known" and cached_pos.entry_fill_price_cents)
                                else None
                            )

                            if not is_original:
                                # Any policy coming from this path is fallback provenance.
                                if sl_price is not None or tp_price is not None:
                                    cached_risk_state = "fallback"
                                    # CRITICAL FIX (2026-08-24): Fallback SL/TP records must
                                    # carry schema version 2 so the exit-policy fallback profit
                                    # exit path (which requires schema >= 2) can authorize them.
                                    schema_version = 2

                            # CRITICAL FIX (2026-08-11): Do not derive risk from a REST-synced
                            # or fallback average price.  initial_risk is meaningful only when
                            # an original persisted SL is present.
                            risk_cents = abs(cached_pos.avg_price_cents - sl_price) if sl_price is not None else 0

                            # Mandatory trailing stop (FIXED_CENTS mode) is only active when
                            # an original SL is present.
                            trailing_type = TrailingType.FIXED_CENTS
                            trailing_param = trailing_distance_cents

                            # Extract series_ticker from market_id (e.g., KXBTC15M-26JUL162015-15 -> KXBTC15M)
                            series_ticker = market_id.split("-")[0] if "-" in market_id else market_id

                            monitor_position = Position(
                                position_id=market_id,
                                market_id=market_id,
                                series_ticker=series_ticker,  # CRITICAL: Required for asset extraction
                                side=side_enum,
                                thesis_side=side_enum.value.lower(),
                                outcome_side=side_enum.value.lower(),
                                book_side=cached_pos.book_side or "ask",
                                size=(
                                    Decimal(cached_pos.quantity_cc) / Decimal("100")
                                    if cached_pos.quantity_cc
                                    else Decimal(str(cached_pos.contracts))
                                ),
                                avg_entry_price_cents=cached_pos.avg_price_cents,
                                take_profit_price_cents=tp_price,
                                stop_loss_enabled=sl_price is not None,
                                stop_loss_price_cents=sl_price,
                                risk_params_state=("original_persisted" if is_original else cached_risk_state),
                                risk_params_schema_version=(schema_version if is_original else schema_version),
                                trailing_type=trailing_type,
                                trailing_param=trailing_param,
                                exit_policy_id=cached_pos.exit_policy_id or "rest_sync",
                                # CRITICAL FIX (2026-08-22): Preserve the recovered fill source
                                # (alpha/ws/http_poller) when provenance is present.  Only
                                # force "rest_sync" when the cache record itself is a REST-only
                                # synthetic with no fill linkage.
                                fill_source=(
                                    cached_pos.fill_source
                                    if is_original and cached_pos.fill_source
                                    else "rest_sync"
                                ),
                                entry_signal_id=(
                                    cached_pos.entry_signal_id
                                    or cached_pos.client_order_id
                                    or "rest_sync"
                                ),
                                entry_intent_id=cached_pos.entry_intent_id or cached_pos.client_order_id,
                                # CRITICAL FIX (2026-08-22): Pass the recovered AT_FILL book
                                # and model provenance to PositionMonitor so spread-stop and
                                # model-invalidation exits are allowed after restart.
                                entry_fill_id=cached_pos.entry_fill_id,
                                entry_order_id=cached_pos.entry_order_id,
                                client_order_id=cached_pos.client_order_id,
                                entry_model=cached_pos.entry_model,
                                entry_model_version=cached_pos.entry_model_version,
                                entry_model_probability=cached_pos.entry_model_probability,
                                entry_market_probability=cached_pos.entry_market_probability,
                                entry_edge=cached_pos.entry_edge,
                                entry_book_snapshot_id=cached_pos.entry_book_snapshot_id,
                                entry_execution_mode=cached_pos.entry_execution_mode,
                                entry_book_capture_quality=cached_pos.entry_book_capture_quality,
                                entry_executable_bid_cents=cached_pos.entry_executable_bid_cents,
                                entry_executable_ask_cents=cached_pos.entry_executable_ask_cents,
                                entry_book_timestamp=cached_pos.entry_book_timestamp,
                                entry_book_sequence=cached_pos.entry_book_sequence,
                                entry_book_source=cached_pos.entry_book_source,
                                # CRITICAL FIX (2026-08-11): Only pass a trusted fill price;
                                # if unknown, leave it unset so no fallback TP is invented.
                                entry_fill_price_cents=entry_fill_price_cents,
                                entry_fill_timestamp=cached_pos.entry_fill_timestamp,
                                # CRITICAL FIX (2026-08-23): Propagate durable provenance state
                                # so the exit policy can distinguish recovered from unknown.
                                entry_provenance_snapshot_id=cached_pos.entry_provenance_snapshot_id,
                                provenance_state=cached_pos.provenance_state,
                            )

                            monitor.upsert_position(monitor_position, caller="rest_sync")
                            logger.info(
                                "[POSITION-MONITOR-REST-SYNC] Upserted REST-synced position to monitor: "
                                "market=%s side=%s size=%d TP=%s SL=%s risk_state=%s",
                                market_id, cached_pos.side, cached_pos.contracts,
                                f"{tp_price}c" if tp_price is not None else "none",
                                f"{sl_price}c" if sl_price is not None else "none",
                                monitor_position.risk_params_state.value,
                            )

                            # CRITICAL FIX (2026-08-01): Restore original avg_price_cents if we used fallback
                            # This ensures the position cache reflects the true state while PositionMonitor
                            # has a working fallback for exit execution.  Always restore, even if the
                            # original was None; the fallback is for the monitor copy only.
                            if getattr(cached_pos, '_using_fallback_price', False):
                                cached_pos.avg_price_cents = original_avg_price
                                if hasattr(cached_pos, '_using_fallback_price'):
                                    delattr(cached_pos, '_using_fallback_price')
                                logger.debug(
                                    "[POSITION-CACHE-REST-SYNC] Restored original avg_price_cents after monitor init: market=%s original=%s",
                                    market_id, original_avg_price
                                )
                    except Exception as monitor_err:
                        logger.error("[POSITION-CACHE-REST-SYNC] CRITICAL: Failed to add REST-synced positions to monitor: %s", monitor_err, exc_info=True)
                        # CRITICAL FIX (2026-07-17): Do not silently swallow position monitor failures
                        # If a position cannot be added to the monitor, it will ride to settlement without exit enforcement
                        # This is a critical safety violation. Re-raise to surface the issue.
                        raise RuntimeError(f"Failed to add REST-synced position to monitor - exit policies will not execute: {monitor_err}")
                    finally:
                        # Ensure any monitor-only fallback price is restored to the cache,
                        # regardless of whether the position was added, skipped as stale, or
                        # the monitor path raised.  The PositionMonitor copy already used the
                        # fallback; the cache must keep the original state.
                        for _mkt_id, _cached_pos in self._positions.items():
                            if getattr(_cached_pos, '_using_fallback_price', False):
                                try:
                                    _cached_pos.avg_price_cents = getattr(_cached_pos, '_original_avg_price', None)
                                    if hasattr(_cached_pos, '_using_fallback_price'):
                                        delattr(_cached_pos, '_using_fallback_price')
                                    if hasattr(_cached_pos, '_original_avg_price'):
                                        delattr(_cached_pos, '_original_avg_price')
                                except Exception:
                                    pass

                # CRITICAL FIX: Always update _last_sync even when no positions pass filters
                self._last_sync = datetime.now(timezone.utc)
                self._last_rest_sync_timestamp = rest_timestamp
                logger.info(f"Position cache synced from REST: {positions_processed} open positions, {positions_filtered} filtered (test & closed)")
                # AUDIT #1: Log position cache health after successful sync
                self.log_health()
            except Exception as e:
                logger.error(f"Position cache sync from REST failed: {e}")

    def log_health(self) -> None:
        """Log position cache health metrics for AUDIT #1.

        Logs:
        - Last successful sync time
        - Number of open positions
        - Per-asset net exposure
        """
        from datetime import datetime, timezone

        # Log last sync time
        if self._last_sync:
            staleness_seconds = (datetime.now(timezone.utc) - self._last_sync).total_seconds()
            logger.info(
                "[POSITION-CACHE-HEALTH] last_sync=%s staleness=%.1fs",
                self._last_sync.isoformat(),
                staleness_seconds
            )
        else:
            logger.warning("[POSITION-CACHE-HEALTH] last_sync=NEVER (cache never synced)")

        # Log total open positions
        open_positions = [p for p in self._positions.values() if p.contracts > 0]
        logger.info(
            "[POSITION-CACHE-HEALTH] total_positions=%d open_positions=%d",
            len(self._positions),
            len(open_positions)
        )

        # Log per-asset exposure
        assets = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        for asset in assets:
            exposure = self.get_asset_exposure(asset)
            logger.info(
                "[POSITION-CACHE-HEALTH] asset=%s contracts=%d notional=%.2f unrealized_pnl=%.2f position_count=%d",
                asset,
                exposure["total_contracts"],
                exposure["total_notional_usd"],
                exposure["unrealized_pnl_usd"],
                exposure["position_count"]
            )

    def is_healthy(self, max_staleness_seconds: float = 60.0) -> bool:
        """Check if position cache is healthy for trading operations.

        Health criteria:
        - Cache has been synced at least once (last_sync is not None)
        - Last sync is within max_staleness_seconds (default 60s)

        Args:
            max_staleness_seconds: Maximum allowed staleness in seconds

        Returns:
            True if cache is healthy, False otherwise
        """
        from datetime import datetime, timezone

        if self._last_sync is None:
            logger.warning("[POSITION-CACHE-HEALTH-GUARD] Cache never synced - unhealthy")
            return False

        staleness_seconds = (datetime.now(timezone.utc) - self._last_sync).total_seconds()
        if staleness_seconds > max_staleness_seconds:
            logger.warning(
                "[POSITION-CACHE-HEALTH-GUARD] Cache too stale: %.1fs > %.1fs - unhealthy",
                staleness_seconds,
                max_staleness_seconds
            )
            return False

        return True

    def is_position_healthy(self, market_id: str) -> bool:
        """Check if position has proper exit metadata.

        Args:
            market_id: The market ID to check

        Returns:
            True if position is healthy (has exit metadata), False otherwise
        """
        return market_id not in self._unhealthy_positions

    def get_unhealthy_positions(self) -> List[str]:
        """Get list of unhealthy positions for alerting.

        Returns:
            List of market IDs that are unhealthy (missing exit metadata)
        """
        return list(self._unhealthy_positions)

    def log_unhealthy_positions(self) -> None:
        """Log unhealthy positions for audit."""
        if self._unhealthy_positions:
            logger.warning(
                "[POSITION-CACHE] Unhealthy positions (missing exit metadata): %s",
                self._unhealthy_positions
            )

    async def _rebuild_from_fills_ledger(self) -> None:
        """Rebuild position cache from fills ledger (canonical source).

        CRITICAL FIX (2026-07-23): When REST API returns empty positions but fills ledger
        shows active positions, this method rebuilds the cache from the fills ledger.
        This ensures positions are tracked for exit policies even when REST is unreliable.

        The fills ledger is the canonical source of truth for executed trades.
        """
        try:
            ledger = self._get_fills_ledger()
            if not ledger:
                logger.error("[POSITION-CACHE-REBUILD] Fills ledger not available")
                return

            # Get recent fills (last 1 hour to capture current 15m window positions)
            from datetime import datetime, timedelta, timezone
            cutoff_time = datetime.now(timezone.utc) - timedelta(hours=1)

            # Use get_fills method with since parameter
            recent_fills = ledger.get_fills(since=cutoff_time, limit=100)

            if not recent_fills:
                logger.info("[POSITION-CACHE-REBUILD] No recent fills found in ledger")
                return

            # Compute net positions from fills
            # Group fills by market_id and compute net contracts
            from collections import defaultdict
            market_fills = defaultdict(list)

            for fill in recent_fills:
                market_id = getattr(fill, 'market_id', None)
                if not market_id:
                    continue

                # Filter out test tickers
                if _is_test_ticker(market_id):
                    continue

                # Filter out expired tickers
                if _is_expired_ticker(market_id):
                    continue

                market_fills[market_id].append(fill)

            # Rebuild positions from fills using canonical signed-YES exposure and
            # side-tagged prices.  This matches recompute_position_from_ledger and
            # avoids the naive buy/sell and 100 - price assumptions.
            rebuilt_count = 0
            for market_id, fills in market_fills.items():
                net_yes_cc = 0
                # Track cost and quantity in fixed-point cents / centi-contracts to
                # avoid float-based financial arithmetic in the rebuild path.
                total_cost_cents = Decimal("0")  # contract*cents
                total_quantity_cc = 0            # centi-contracts
                thesis_side = None
                exit_policy_id = None
                take_profit_price_cents = None
                stop_loss_price_cents = None

                for fill in fills:
                    # Determine quantity in centi-contracts.  Prefer the canonical
                    # ``quantity_cc`` / ``count_fp``, then legacy ``count``,
                    # ``contracts``, or ``filled_count`` for backward compatibility
                    # with older tests and reduced payload fills.
                    quantity_cc = getattr(fill, 'quantity_cc', 0) or 0
                    if not quantity_cc and getattr(fill, 'count_fp', None):
                        try:
                            quantity_cc = int(Decimal(str(fill.count_fp)) * Decimal("100"))
                        except Exception:
                            quantity_cc = 0
                    if not quantity_cc:
                        count = getattr(fill, 'count', None)
                        if count:
                            try:
                                quantity_cc = int(count) * 100
                            except Exception:
                                quantity_cc = 0
                    if not quantity_cc:
                        contracts = getattr(fill, 'contracts', None)
                        if contracts:
                            try:
                                quantity_cc = int(contracts) * 100
                            except Exception:
                                quantity_cc = 0
                    if not quantity_cc:
                        filled_count = getattr(fill, 'filled_count', None)
                        if filled_count:
                            try:
                                quantity_cc = int(filled_count) * 100
                            except Exception:
                                quantity_cc = 0
                    if quantity_cc == 0:
                        continue

                    # Canonical signed-YES exposure.  Prefer ledger canonicalization
                    # metadata; fall back to the raw exchange ``action``/``side``.
                    can_action = getattr(fill, 'canonical_position_action', None) or getattr(fill, 'action', '') or 'buy'
                    can_side = getattr(fill, 'canonical_position_side', None) or getattr(fill, 'side', '') or 'yes'
                    fill_yes = 0
                    if BINARY_PRICE_SPACE_AVAILABLE:
                        try:
                            fill_yes = fill_to_signed_yes_exposure(can_action, can_side, quantity_cc)
                        except Exception:
                            fill_yes = 0
                    if fill_yes == 0:
                        continue

                    # Price in the fill's own outcome space.  For a long-NO position
                    # this may come from a SELL_YES fill, but the economic held side
                    # is still NO, so we retrieve the NO price if available.
                    fill_held_side, _ = from_signed_yes_exposure(fill_yes)
                    fill_price = _fill_position_side_price_cents(fill, fill_held_side)
                    if fill_price is None or fill_price <= 0:
                        fill_price = getattr(fill, 'price_cents', 0) or 0

                    # Update signed net exposure and weighted-average cost using
                    # fixed-point integer/Decimal arithmetic.  Cost is added only for
                    # the portion that increases absolute exposure; reductions scale
                    # the existing basis proportionally; side flips reset the basis
                    # to the residual new-side position at this fill's price.
                    current_yes_cc = net_yes_cc
                    new_yes_cc = current_yes_cc + fill_yes
                    current_abs = abs(current_yes_cc)
                    new_abs = abs(new_yes_cc)

                    if current_yes_cc != 0 and new_yes_cc != 0 and (current_yes_cc > 0) != (new_yes_cc > 0):
                        # Flip: reset cost basis for the residual new-side position.
                        total_quantity_cc = new_abs
                        if fill_price > 0:
                            total_cost_cents = Decimal(new_abs) * Decimal(fill_price) / Decimal("100")
                        else:
                            total_cost_cents = Decimal("0")
                    elif current_yes_cc == 0 or new_abs > current_abs:
                        added_cc = new_abs - current_abs
                        total_quantity_cc += added_cc
                        if fill_price > 0:
                            total_cost_cents += Decimal(added_cc) * Decimal(fill_price) / Decimal("100")
                    elif current_yes_cc != 0 and new_abs < current_abs:
                        # Reduce proportionally to preserve the average entry price.
                        total_cost_cents = total_cost_cents * Decimal(new_abs) / Decimal(current_abs)
                        total_quantity_cc = new_abs
                    # If new_abs == current_abs (e.g., full close) the cost is consumed
                    # and the position is flat; leave it as-is and it will be zeroed
                    # when net_yes_cc becomes zero below.

                    net_yes_cc = new_yes_cc

                    # Extract exit policy metadata from fill
                    if hasattr(fill, 'raw_payload'):
                        import json
                        try:
                            raw_payload = fill.raw_payload
                            if raw_payload:
                                payload = json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
                                if exit_policy_id is None:
                                    exit_policy_id = payload.get('exit_policy_id')
                                if take_profit_price_cents is None:
                                    take_profit_price_cents = payload.get('take_profit_price_cents')
                                if stop_loss_price_cents is None:
                                    stop_loss_price_cents = payload.get('stop_loss_price_cents')
                        except Exception as json_err:
                            pass

                # net_contracts is a Decimal for display.
                net_contracts = Decimal(abs(net_yes_cc)) / Decimal("100")

                # Only add if we have a net position
                if net_contracts > 0:
                    # Compute average entry price in cents from contract*cents and cc.
                    if total_quantity_cc > 0 and total_cost_cents > 0:
                        avg = (total_cost_cents * Decimal("100")) / Decimal(total_quantity_cc)
                        avg_price_cents = int(avg.to_integral_value(rounding=ROUND_HALF_UP))
                    else:
                        avg_price_cents = None
                    thesis_side, _ = from_signed_yes_exposure(net_yes_cc)

                    # Derive agent_id from ticker
                    try:
                        from config.kalshi_crypto_config import kalshi_ticker_to_asset
                        asset = kalshi_ticker_to_asset(market_id)
                        if asset and asset.upper() in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
                            agent_id = f"{asset.upper()}_15M"
                        else:
                            agent_id = "unknown_agent"
                    except Exception:
                        agent_id = "unknown_agent"

                    # Create CachedPosition
                    self._positions[market_id] = CachedPosition(
                        market_id=market_id,
                        agent_id=agent_id,
                        contracts=net_contracts,
                        side=thesis_side or "yes",  # Fallback to yes if unknown
                        thesis_side=thesis_side or "yes",
                        outcome_side=thesis_side or "yes",
                        book_side="ask",
                        avg_price_cents=avg_price_cents,
                        entry_price_state="known" if avg_price_cents else "unknown",
                        take_profit_price_cents=take_profit_price_cents,
                        stop_loss_price_cents=stop_loss_price_cents,
                    )
                    rebuilt_count += 1
                    logger.info(
                        "[POSITION-CACHE-REBUILD] Rebuilt position: market=%s contracts=%d avg_price=%dc thesis_side=%s",
                        market_id, net_contracts, avg_price_cents or 0, thesis_side or "unknown"
                    )

            logger.info(
                "[POSITION-CACHE-REBUILD] Rebuilt %d positions from %d fills in fills ledger",
                rebuilt_count, len(recent_fills)
            )

        except Exception as e:
            logger.error(
                "[POSITION-CACHE-REBUILD] Error rebuilding from fills ledger: %s",
                e,
                exc_info=True
            )
            raise

    async def _cleanup_stale_positions(
        self,
        exchange_positions: List[Dict[str, Any]],
        open_orders: Optional[List[Dict[str, Any]]] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """Remove cached positions that are not confirmed by an exchange snapshot.

        This is the exchange-authoritative cleanup used during an atomic rebuild.
        It never deletes a position blindly:

        - Keep if the market is reported by the exchange REST position snapshot.
        - Keep if there is an open order for that market (it may be filling).
        - Keep if the fills ledger shows a non-zero net position for that market
          and the market is not expired (genuine divergence -> reconciliation_halted).
        - Otherwise remove from cache and PositionMonitor.

        Args:
            exchange_positions: Normalized exchange position list (market_id, ...)
            open_orders: Optional normalized open-order list (market_id, side, contracts)
            dry_run: If True, report what would be deleted without deleting.

        Returns:
            Dict with kept, removed, market_ids, and halts.
        """
        from datetime import datetime, timedelta, timezone

        report = {
            "kept": [],
            "removed": [],
            "halted": [],
            "dry_run": dry_run,
        }

        exchange_market_ids = {p.get("market_id") for p in exchange_positions if p.get("market_id")}
        open_order_market_ids = set()
        open_orders_by_ticker: Dict[str, List[Dict[str, Any]]] = {}
        if open_orders:
            for o in open_orders:
                ticker = o.get("market_id")
                if ticker:
                    open_order_market_ids.add(ticker)
                    open_orders_by_ticker.setdefault(ticker, []).append(o)

        cutoff_time = datetime.now(timezone.utc) - timedelta(hours=24)
        ledger = self._get_fills_ledger()

        for market_id in list(self._positions.keys()):
            if market_id in exchange_market_ids:
                # Exchange confirms an open position.  Keep.
                report["kept"].append({"market_id": market_id, "reason": "exchange_confirmed"})
                continue

            if market_id in open_order_market_ids:
                # A live order is resting; do not remove.
                report["kept"].append({"market_id": market_id, "reason": "open_order"})
                continue

            if _is_expired_ticker(market_id):
                # Expired markets cannot be traded or reconciled; remove.
                report["removed"].append({"market_id": market_id, "reason": "expired"})
                if not dry_run:
                    await self._remove_position_and_monitor(market_id)
                continue

            # Consult the fills ledger as a secondary canonical source.
            net_contracts = 0
            if ledger:
                try:
                    fills = ledger.get_fills(
                        since=cutoff_time,
                        market_ticker=market_id,
                        limit=500,
                    )
                    for fill in fills:
                        # Use canonical quantity_cc (centi-contracts) when available.
                        qty_cc = getattr(fill, 'quantity_cc', None)
                        if qty_cc is None:
                            contracts = getattr(fill, 'count', 0) or getattr(fill, 'contracts', 0)
                            if not contracts:
                                continue
                            try:
                                from decimal import Decimal, ROUND_HALF_UP
                                qty_cc = int(Decimal(str(contracts)) * Decimal("100"))
                            except Exception:
                                qty_cc = int(contracts) * 100
                        action = getattr(fill, 'action', 'buy')
                        if action == 'buy':
                            net_contracts += qty_cc
                        elif action == "sell":
                            net_contracts -= qty_cc
                except Exception as e:
                    logger.warning(
                        "[POSITION-CACHE-STALE-CLEANUP] Failed to query fills ledger for %s: %s",
                        market_id, e
                    )

            if net_contracts > 0:
                # Fills ledger shows real exposure but exchange does not.
                # This is a genuine mismatch; keep and halt.
                logger.warning(
                    "[POSITION-CACHE-STALE-CLEANUP] Mismatch for %s: ledger net=%d, exchange=0, no open order. "
                    "Keeping position and marking reconciliation_halted.",
                    market_id, net_contracts
                )
                self._reconciliation_halted[market_id] = True
                report["halted"].append({"market_id": market_id, "reason": "ledger_exchange_mismatch"})
                continue

            # Safe to remove: not on exchange, no open order, no ledger net, not expired.
            report["removed"].append({"market_id": market_id, "reason": "phantom"})
            if not dry_run:
                await self._remove_position_and_monitor(market_id)

        logger.info(
            "[POSITION-CACHE-STALE-CLEANUP] dry_run=%s kept=%d removed=%d halted=%d",
            dry_run, len(report["kept"]), len(report["removed"]), len(report["halted"])
        )

        return report

    async def _remove_position_and_monitor(self, market_id: str) -> None:
        """Remove a cached position and its PositionMonitor registration."""
        if market_id not in self._positions:
            return

        cached_pos = self._positions.pop(market_id)
        logger.warning(
            "[POSITION-CACHE-REMOVE] Removed stale/phantom position: market=%s contracts=%d avg_price=%s",
            market_id, cached_pos.contracts, cached_pos.avg_price_cents
        )

        try:
            from merid.position_management.position_monitor import get_position_monitor
            monitor = get_position_monitor()
            monitor.remove_position(market_id)
            logger.info(
                "[POSITION-MONITOR-INTEGRATION] Removed stale position from monitor: market=%s",
                market_id
            )
        except Exception as monitor_err:
            logger.warning(
                "[POSITION-MONITOR-INTEGRATION] Could not remove stale position from monitor: %s",
                monitor_err
            )

        # 2026-08-28: Release any GlobalSlotAllocator slot held by this ticker so
        # quarantined/removed positions do not leak exposure and block new entries.
        try:
            from merid.risk.global_slot_allocator import get_global_slot_allocator
            allocator = get_global_slot_allocator()
            if allocator.release_slot_by_ticker(market_id):
                logger.info(
                    "[SLOT-ALLOCATOR-RELEASE] Released slot for removed position: market=%s",
                    market_id,
                )
        except Exception as slot_err:
            logger.warning(
                "[SLOT-ALLOCATOR-RELEASE] Could not release slot for removed position %s: %s",
                market_id,
                slot_err,
            )

    async def clear(self) -> None:
        """Clear all cached positions.

        BUG-FIX: Now async with mutex protection for thread safety.
        """
        async with self._ensure_mutex():
            self._positions.clear()
            self._settled_tickers.clear()
            logger.info("Position cache cleared")

    def clear_sync(self) -> None:
        """Synchronous version of clear() for use in non-async contexts.

        This bypasses the mutex for simplicity when called from __init__ or other
        synchronous contexts where the event loop is not available.
        """
        self._positions.clear()
        self._settled_tickers.clear()
        logger.info("Position cache cleared (sync)")

    async def clear_expired_positions(self) -> int:
        """Clean up positions for expired/closed markets.

        A position is only removed when one of the following is true:

        - The market has been explicitly marked settled or finalized.
        - The position is authoritatively zero.
        - The position's ``settlement_status`` is already ``settled``.

        When a market is past its close buffer but has not yet settled, the
        position is transitioned to ``settlement_status=pending`` and a critical
        alert is logged.  Financial exposure is retained until settlement.

        Returns:
            Number of positions removed.
        """
        async with self._ensure_mutex():
            removed_count = 0
            pending_count = 0
            removed_tickers = []
            pending_tickers = []

            for ticker, position in list(self._positions.items()):
                if not _is_expired_ticker(ticker):
                    continue

                # Authorized removal conditions.
                can_remove = (
                    position.settlement_status == "settled"
                    or position.quantity_cc == 0
                    or self.is_settled(ticker)
                )

                if can_remove:
                    removed_tickers.append(ticker)
                    del self._positions[ticker]
                    removed_count += 1
                else:
                    # Closed-but-unsettled market: retain exposure, alert, and
                    # transition to settlement_pending.
                    if position.settlement_status != "pending":
                        position.settlement_status = "pending"
                        pending_tickers.append(ticker)
                        pending_count += 1
                        logger.critical(
                            "[POSITION-CACHE-SETTLEMENT-PENDING] ticker=%s "
                            "quantity_cc=%d side=%s avg_price_cents=%s - "
                            "market is past close buffer but has not settled; "
                            "retaining position and raising alert",
                            ticker,
                            position.quantity_cc,
                            position.side,
                            position.avg_price_cents,
                        )

            if pending_count > 0:
                logger.warning(
                    "[POSITION-CACHE-CLEANUP] %d positions transitioned to settlement_pending: %s",
                    pending_count,
                    pending_tickers,
                )

            if removed_count > 0:
                logger.info(
                    f"[POSITION-CACHE-CLEANUP] Removed {removed_count} settled/expired positions: {removed_tickers}"
                )
                # Log cache health after cleanup
                self.log_health()

            return removed_count

    def is_settled(self, market_ticker: str) -> bool:
        """Return True if the market has been finalized by settlement."""
        return market_ticker in self._settled_tickers

    async def mark_settled(self, market_ticker: str) -> None:
        """Mark a market as settled and remove its cached position."""
        self._settled_tickers.add(market_ticker)
        self._reconciliation_halted.pop(market_ticker, None)
        self._quarantined_tickers.discard(market_ticker)
        if market_ticker in self._positions:
            self._positions[market_ticker].settlement_status = "settled"
            await self._remove_position_and_monitor(market_ticker)
            logger.info(
                "[POSITION-CACHE-SETTLEMENT] Removed settled position for %s",
                market_ticker,
            )

    def is_quarantined(self, market_ticker: str) -> bool:
        """Return True if the market is quarantined (closed but not settled)."""
        return market_ticker in self._quarantined_tickers

    async def quarantine_ticker(self, market_ticker: str) -> None:
        """Quarantine a closed-but-unsettled market and remove it from active state.

        This is the recovery hook for markets the exchange still reports as open
        after close_time has passed and status is 'closed' but resolved=False.
        """
        if market_ticker in self._quarantined_tickers:
            return
        self._quarantined_tickers.add(market_ticker)
        self._reconciliation_halted.pop(market_ticker, None)
        if market_ticker in self._positions:
            self._positions[market_ticker].settlement_status = "quarantined"
            await self._remove_position_and_monitor(market_ticker)
            logger.warning(
                "[POSITION-CACHE-QUARANTINE] Removed quarantined position for %s",
                market_ticker,
            )

    async def on_market_settlement(
        self,
        market_ticker: str,
        outcome: str,
        settlement_price_cents: Optional[int] = None,
        realized_pnl_cents: Optional[int] = None,
        settlement_ts: Optional[str] = None,
    ) -> None:
        """Handle a market settlement event by finalizing the cached position.

        This is the canonical hook for the settlement poller.  It records the
        settlement outcome, removes the position, and ensures the ticker is not
        rebuilt from the fills ledger.
        """
        logger.info(
            "[POSITION-CACHE-SETTLEMENT] market=%s outcome=%s price_cents=%s pnl_cents=%s",
            market_ticker,
            outcome,
            settlement_price_cents,
            realized_pnl_cents,
        )
        # Capture position before mark_settled removes it.
        position = self._positions.get(market_ticker)
        await self.mark_settled(market_ticker)

        # Record settlement in the unified trade attribution fact table.
        try:
            from merid.monitoring.trade_attribution_fact_table import get_trade_attribution_table
            table = get_trade_attribution_table()
            if table is not None:
                table.record_settlement(
                    market_ticker,
                    outcome,
                    position,
                    settlement_price_cents=settlement_price_cents,
                    realized_pnl_cents=realized_pnl_cents,
                    settlement_ts=settlement_ts,
                )
                await table.flush()
        except Exception as e:
            logger.warning("[POSITION-CACHE] trade attribution record_settlement failed: %s", e)

        # Event-driven bankroll reconciliation after settlement.
        try:
            from merid.monitoring.bankroll_reconciler import get_bankroll_reconciler
            reconciler = get_bankroll_reconciler()
            if reconciler is not None:
                reconciler.record_settlement(
                    ticker=market_ticker,
                    outcome=outcome,
                    settlement_price_cents=settlement_price_cents,
                    realized_pnl_cents=realized_pnl_cents,
                )
        except Exception as e:
            logger.warning("[POSITION-CACHE] bankroll reconciler record_settlement failed: %s", e)

    async def _lookup_fill_source(
        self,
        fill_id: Optional[str],
        client_order_id: Optional[str],
    ) -> str:
        """Look up fill_source from fills_ledger for authoritative classification.

        SEV-0 FIX: Improved robustness to prevent race conditions between fill arrival
        and ledger updates. Uses multiple detection methods in priority order:
        1. Fills ledger (authoritative source)
        2. Client order ID prefix (HEDGE_)
        3. Source field in client_order_id (contains "hedge" or "HEDGE_ENGINE")

        Args:
            fill_id: The fill ID to look up in fills_ledger
            client_order_id: The client order ID for fallback detection

        Returns:
            "hedge" if hedge fill, "alpha" otherwise
        """
        # Priority 1: Try to get fill_source from fills_ledger if fill_id provided
        if fill_id and self._fills_ledger:
            try:
                fill = self._fills_ledger.get_fill_by_id(fill_id)
                if fill and fill.fill_source:
                    # Validate fill_source value
                    if fill.fill_source in ("hedge", "alpha", "manual"):
                        return fill.fill_source
                    # If fill_source has unexpected value, log and continue to fallback
                    logger.warning(
                        f"[POSITION-CACHE] Unexpected fill_source value: {fill.fill_source} "
                        f"for fill_id={fill_id}, falling back to client_order_id detection"
                    )
            except Exception as e:
                logger.debug(f"[POSITION-CACHE] Failed to lookup fill {fill_id} in ledger: {e}")

        # Priority 2: Detect by client_order_id prefix (HEDGE_)
        if client_order_id:
            if client_order_id.startswith('HEDGE_'):
                return "hedge"
            # Priority 3: Check if client_order_id contains hedge markers
            client_order_id_lower = client_order_id.lower()
            if "hedge" in client_order_id_lower or "hedge_engine" in client_order_id_lower:
                return "hedge"

        # Default to alpha if no hedge indicators found
        return "alpha"

    async def reconcile_with_fills_ledger(
        self,
        ledger: Optional[Any] = None,
        dry_run: bool = True,
    ) -> Dict[str, Any]:
        """Reconcile position cache with fills_ledger for consistency.

        Task 4: Detects discrepancies between cache and ledger hedge fill tracking.

        Args:
            ledger: KalshiFillsLedger instance (uses self._fills_ledger if None)
            dry_run: If True, only reports issues without fixing

        Returns:
            Dict with reconciliation results
        """
        if ledger is None:
            ledger = self._fills_ledger

        if not ledger:
            return {"error": "No fills_ledger available for reconciliation"}

        issues = []
        hedge_fills_in_cache = 0
        hedge_fills_in_ledger = 0

        # Get hedge fills from ledger
        ledger_hedge_fills = ledger.get_hedge_fills(limit=10000)
        hedge_fills_in_ledger = len(ledger_hedge_fills)

        # Check cache positions for hedge fill_source consistency
        async with self._ensure_mutex():
            for ticker, pos in self._positions.items():
                if pos.fill_source == "hedge":
                    hedge_fills_in_cache += 1
                    # Verify this hedge fill exists in ledger
                    matching = [f for f in ledger_hedge_fills if f.market_ticker == ticker]
                    if not matching:
                        issues.append({
                            "type": "cache_hedge_not_in_ledger",
                            "ticker": ticker,
                            "position": pos,
                        })

        # Report summary
        result = {
            "dry_run": dry_run,
            "hedge_fills_in_cache": hedge_fills_in_cache,
            "hedge_fills_in_ledger": hedge_fills_in_ledger,
            "discrepancy_count": len(issues),
            "issues": issues[:10],  # Limit to first 10
            "is_consistent": len(issues) == 0 and hedge_fills_in_cache == hedge_fills_in_ledger,
        }

        if issues:
            logger.warning(
                "Position cache / fills ledger reconciliation found %d issues",
                len(issues)
            )

        return result

    # ── Resting bracket orders ────────────────────────────────────────

    async def _cancel_brackets(self, position: CachedPosition) -> None:
        """Cancel any resting bracket orders attached to *position*.

        Looks up the bracket order by ``client_order_id`` (the stored client_tag)
        via Kalshi's ``get_order_by_client_id_result`` and cancels it. Tolerates
        missing orders (already-filled / never-rested) silently. Clears the
        bracket tags on the position regardless of cancel outcome.
        """
        # CRITICAL: Skip cancellation if market is not open to avoid 404 errors.
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            market_store = get_kalshi_market_state_store()
            unified = market_store.get_unified(position.market_id)
            if not unified or getattr(unified, "status", "unknown") != "open":
                logger.info(
                    "[BRACKET-CANCEL] Skipping bracket cancellation for non-open market=%s status=%s",
                    position.market_id,
                    getattr(unified, "status", "unknown") if unified else "unknown",
                )
                position.tp_bracket_client_tag = None
                position.sl_bracket_client_tag = None
                return
        except Exception as ms_exc:
            logger.debug("[BRACKET-CANCEL] Could not verify market state for %s: %s", position.market_id, ms_exc)

        try:
            from merid.event_venues.kalshi.client_v2 import get_kalshi_client
        except Exception as imp_exc:
            logger.debug("[BRACKET-CANCEL] client unavailable: %s", imp_exc)
            position.tp_bracket_client_tag = None
            position.sl_bracket_client_tag = None
            return

        client = get_kalshi_client()
        for kind, tag in (
            ("tp", position.tp_bracket_client_tag),
            ("sl", position.sl_bracket_client_tag),
        ):
            if not tag:
                continue
            try:
                lookup = await client.get_order_by_client_id_result(
                    tag, market_id=position.market_id,
                )
                order = getattr(lookup, "data", None) if lookup else None
                if order is not None:
                    order_id = getattr(order, "order_id", None) or getattr(order, "id", None)
                    status = (getattr(order, "status", "") or "").lower()
                    if order_id and status not in ("filled", "canceled", "rejected", "executed"):
                        await client.cancel_order(order_id, market_id=position.market_id)
                        logger.info(
                            "[BRACKET-CANCEL] %s: %s order %s canceled (tag=%s)",
                            position.market_id, kind.upper(), order_id, tag,
                        )
                    else:
                        logger.debug(
                            "[BRACKET-CANCEL] %s: %s tag=%s already terminal (status=%s)",
                            position.market_id, kind.upper(), tag, status,
                        )
                else:
                    logger.debug(
                        "[BRACKET-CANCEL] %s: no resting %s order found for tag=%s",
                        position.market_id, kind.upper(), tag,
                    )
            except Exception as exc:
                logger.warning(
                    "[BRACKET-CANCEL] %s: error canceling %s tag=%s: %s",
                    position.market_id, kind.upper(), tag, exc,
                )
        # Clear tags so re-submit (resize path) starts fresh
        position.tp_bracket_client_tag = None
        position.sl_bracket_client_tag = None

    @staticmethod
    def _bracket_client_tag(market_id: str, kind: str, price_cents: int) -> str:
        """Deterministic client_tag for a bracket order so retries dedupe.

        Same (market_id, kind, price) within a 60s window produces the same tag.
        Prefix with BRACKET_ for visibility in logs / DLQ.
        """
        bucket = int(replay_time() // 60)
        preimage = f"{market_id}|{kind}|{price_cents}|{bucket}".encode("utf-8")
        digest = hashlib.sha256(preimage).hexdigest()[:16]
        return f"BRACKET_{kind.upper()}_{digest}"

    @staticmethod
    def _record_bracket_metric(kind: str, ok: bool) -> None:
        """Increment bracket submission counter for observability.

        P2 Task 7: gives ops a Prometheus surface to alert on. The counter is
        labeled by kind (tp/sl) and outcome (success/failure). Best-effort —
        any error in metrics fetch is swallowed.
        """
        try:
            from monitoring.metrics import get_metrics_registry
            reg = get_metrics_registry()
            counter = reg.counter(
                "merid_bracket_submission_total",
                help_text="Resting bracket order submissions, labeled by kind/outcome",
                label_names=["kind", "outcome"],
            )
            counter.inc(labels={
                "kind": kind,
                "outcome": "success" if ok else "failure",
            })
        except Exception:
            pass

    def _calculate_dynamic_max_hold_seconds(self, market_id: str) -> int:
        """Calculate dynamic max hold time based on remaining time-to-expiry.

        CRITICAL FIX: Prevents holding past contract expiry when entering late in the 15m window.
        Research-based approach from Tradewink: Use 80% of remaining TTE to allow execution buffer.
        Source: https://www.tradewink.com/glossary/time-decay-exit

        Logic:
        - Parse market ID to extract expiry timestamp (format: KXBTC15M-26JUL191645-45)
        - Calculate remaining seconds to expiry
        - Return 80% of remaining TTE (allows 20% buffer for order execution)
        - Fallback to 300s (5 min) if TTE cannot be determined (conservative)

        Example:
        - Enter at 8 min into 15m window → 7 min (420s) remaining
        - Dynamic max_hold = 420 * 0.8 = 336s (5.6 min)
        - This ensures exit before expiry with execution buffer
        """
        try:
            from datetime import datetime, timezone

            # CRITICAL FIX (2026-08-03): Use the canonical YYMONDD-HHMM-ET parser.
            # The previous DDMMM-HHMMSS-UTC parsing was off by ~26 days for live
            # 15m tickers, so remaining_seconds always exceeded the 1-day sanity
            # cap and this function ALWAYS returned the 300s fallback - the
            # dynamic hold logic was dead code.
            from merid.event_venues.kalshi.expiry_fallback import parse_kalshi_15m_window_end_utc
            now = datetime.now(timezone.utc)
            expiry_dt = parse_kalshi_15m_window_end_utc(market_id)
            if expiry_dt is None:
                logger.warning("[DYNAMIC-HOLD] Could not parse market ID for TTE: %s", market_id)
                return 300  # Conservative 5-minute fallback

            # If expiry is in the past, market is stale/expired - use fallback
            if expiry_dt < now:
                logger.warning("[DYNAMIC-HOLD] Market expired: %s vs now %s, using fallback", expiry_dt, now)
                return 300

            # Calculate remaining seconds
            remaining_seconds = (expiry_dt - now).total_seconds()

            # CRITICAL FIX (2026-08-01): Sanity check for absurdly large values
            # If remaining time is > 1 day, the market ID parsing is likely wrong
            if remaining_seconds > 86400:  # More than 1 day
                logger.warning("[DYNAMIC-HOLD] Absurd remaining time: %ds (>1 day), market ID parsing likely incorrect, using fallback", remaining_seconds)
                return 300

            # Use 80% of remaining TTE (20% buffer for execution)
            dynamic_max_hold = int(remaining_seconds * 0.8)

            # Sanity checks
            if dynamic_max_hold < 60:  # Minimum 1 minute
                logger.warning("[DYNAMIC-HOLD] Calculated max_hold too low (%ds), using 60s", dynamic_max_hold)
                dynamic_max_hold = 60
            elif dynamic_max_hold > 600:  # Maximum 10 minutes (safety cap)
                logger.info("[DYNAMIC-HOLD] Capping max_hold at 600s (calculated: %ds)", dynamic_max_hold)
                dynamic_max_hold = 600

            logger.info(
                "[DYNAMIC-HOLD] market=%s remaining_tte=%ds dynamic_max_hold=%ds",
                market_id, int(remaining_seconds), dynamic_max_hold
            )

            return dynamic_max_hold

        except Exception as e:
            logger.warning("[DYNAMIC-HOLD] Failed to calculate dynamic max_hold: %s, using fallback 300s", e)
            return 300  # Conservative 5-minute fallback

    async def _submit_resting_bracket(self, position: CachedPosition) -> None:
        """Submit a GTC limit sell at the take-profit price.

        Stop-loss is intentionally handled by the active StopCandidate path
        (PositionMonitor -> StopCandidate -> route_order_async); a GTC limit
        at or below the SL price cannot cut a fast loss and is not submitted.

        For a Kalshi binary contract:
        - Long YES → exit by selling YES at TP price (closing limit ABOVE entry).
        - Long NO  → exit by selling NO at TP price (closing limit ABOVE entry).
        Either way the action is ``sell`` on the same side that was bought.
        """
        from merid.event_venues.kalshi.order_router import OrderIntent, route_order_async
        from merid.event_venues.kalshi.binary_price_space import to_kalshi_side

        tp_price = position.take_profit_price_cents
        sl_price = position.stop_loss_price_cents

        # CRITICAL FIX (2026-08-10): If stop-loss is disabled upstream, never submit an SL bracket.
        if not getattr(position, "stop_loss_enabled", True):
            sl_price = None

        if not tp_price or position.contracts <= 0:
            return

        # CRITICAL FIX: Only submit brackets for active/open markets.  During startup
        # the fills-ledger replays historical fills for closed/resolved contracts; we
        # must not send live orders for those.
        try:
            from merid.event_venues.kalshi.market_state import get_kalshi_market_state_store
            market_store = get_kalshi_market_state_store()
            unified = market_store.get_unified(position.market_id)
            if not unified or getattr(unified, "status", "unknown") != "open":
                logger.info(
                    "[BRACKET] Skipping bracket for non-open market=%s status=%s",
                    position.market_id,
                    getattr(unified, "status", "unknown") if unified else "unknown",
                )
                return
        except Exception as ms_exc:
            logger.debug("[BRACKET] Could not verify market state for %s: %s", position.market_id, ms_exc)

        # CRITICAL FIX: Calculate dynamic max_hold_seconds based on remaining time-to-expiry
        # This prevents holding past contract expiry when entering late in the 15m window
        # Research-based approach: Use 80% of remaining TTE to allow execution buffer
        # Source: https://www.tradewink.com/glossary/time-decay-exit
        max_hold_seconds = self._calculate_dynamic_max_hold_seconds(position.market_id)

        # Bracket exits sell the same side we are long (yes -> SELL_YES, no -> SELL_NO).
        kalshi_side = to_kalshi_side(position.side, "sell")

        # TP leg: GTC sell at TP price
        tp_tag = self._bracket_client_tag(position.market_id, "tp", tp_price)
        logger.info(
            "[BRACKET-CREATION-DEBUG] Creating TP bracket: market=%s side=%s action=sell price=%dc count=%d",
            position.market_id, position.side, tp_price, position.contracts
        )
        tp_intent = OrderIntent(
            ticker=position.market_id,
            side=kalshi_side,
            action="sell",
            price_cents=int(tp_price),
            count=int(position.contracts),
            source="resting_bracket_take_profit",
            agent_id="position_cache_bracket",
            client_tag=tp_tag,
            group_id="bracket",
            rationale=f"resting_tp:{position.market_id}:{tp_price}c",
            # CRITICAL FIX: Add exit policy metadata to satisfy validation for exit orders
            # Exit orders require exit_policy_id for tracking per _validate_risk_contract_linkage
            exit_policy_id=position.exit_policy_id or "bracket_exit",
            window_resolution_id=position.window_resolution_id or "bracket_window",
            risk_tier="A",  # Default to tier A for bracket exits
            max_hold_seconds=max_hold_seconds,  # Dynamic based on remaining TTE
            # CRITICAL FIX (2026-08-01): Set entry_or_exit to prevent ENTRY-ORDER-INVARIANT-VIOLATION
            # Bracket orders are exit orders and must bypass entry guards
            entry_or_exit="exit",
            exit_reason="BRACKET_TAKE_PROFIT",
            reduce_only=True,
            # CRITICAL FIX (2026-08-07): Bracket exit intents must carry position-delta
            # contract fields. _route_live enforces pre_position_size>0 for every exit,
            # and bracket orders close the full position so expected_post_position_size=0.
            pre_position_size=int(position.contracts),
            expected_post_position_size=0,
        )
        logger.info(
            "[BRACKET-CREATION-DEBUG] TP intent created: side=%s action=%s price=%dc count=%d",
            tp_intent.side, tp_intent.action, tp_intent.price_cents, tp_intent.count
        )

        position.tp_bracket_client_tag = tp_tag
        try:
            res = await route_order_async(tp_intent)
            ok = res is not None and (res.has_execution or (res.request_completed and not res.is_terminal))
            self._record_bracket_metric("tp", ok)
            logger.info(
                "[BRACKET] TP submitted market=%s side=%s qty=%d @ %d¢ tag=%s ok=%s",
                position.market_id, position.side, position.contracts,
                tp_price, tp_tag, ok,
            )
        except Exception as exc:
            self._record_bracket_metric("tp", False)
            logger.warning(
                "[BRACKET] TP submission failed market=%s tag=%s err=%s",
                position.market_id, tp_tag, exc,
            )

        # SL leg: intentionally not submitted.  A GTC limit *at or below* the
        # stop price is not a true stop; it only fills if the market recovers
        # to that level, so it cannot cut a fast loss.  Active stop-loss
        # handling (PositionMonitor -> StopCandidate -> route_order_async) now
        # provides the protective exit instead.
        if sl_price and sl_price > 0:
            logger.info(
                "[BRACKET] SL bracket not submitted for %s; active stop-loss handles loss protection",
                position.market_id,
            )
            position.sl_bracket_client_tag = None

    # ── Trailing Stop Monitoring (TUNED 2026-05-25) ─────────────────────────────

    def start_monitoring(self) -> None:
        """Start the trailing stop monitoring loop.

        CRITICAL FIX: 2026-07-07 - DISABLED
        Position monitoring is now handled exclusively by PositionMonitor (merid/position_management/position_monitor.py)
        This prevents duplicate monitoring loops and ensures proper callback routing for all exit conditions.

        PositionMonitor now handles:
        - Extreme profit exits (99c YES / 1c NO)
        - Dynamic take profit (laddered exits)
        - Ratchet profit floor and trimming
        - Trailing stop activation
        - Stop loss / take profit triggers
        - Staged time-based exits (re-implemented from this class)
        - Exit policy resolution (time stop, edge decay, risk, candle reversal)

        This class (KalshiPositionCache) now only handles:
        - Position state management (fills, PnL, metadata)
        - Position cache and exposure tracking
        - Integration with PositionMonitor for position addition
        """
        logger.info("[TRAIL-MONITOR] start_monitoring called - DISABLED (delegated to PositionMonitor)")
        logger.info("[TRAIL-MONITOR] PositionMonitor is now the authoritative exit system")
        # No-op - PositionMonitor handles all exit monitoring

    def stop_monitoring(self) -> None:
        """Stop the trailing stop monitoring loop.

        CRITICAL FIX: 2026-07-07 - DISABLED
        Position monitoring is now handled exclusively by PositionMonitor.
        This is a no-op for backward compatibility.
        """
        logger.info("[TRAIL-MONITOR] stop_monitoring called - DISABLED (delegated to PositionMonitor)")
        # No-op - PositionMonitor handles all exit monitoring

    async def _monitor_positions_loop(self) -> None:
        """Background loop that monitors positions for trailing stop activation and time-based forced exit.

        CRITICAL FIX: 2026-07-07 - DISABLED
        Position monitoring is now handled exclusively by PositionMonitor (merid/position_management/position_monitor.py)
        This method is a no-op for backward compatibility.

        All exit monitoring is now handled by PositionMonitor:
        - Extreme profit exits (99c YES / 1c NO)
        - Dynamic take profit (laddered exits)
        - Ratchet profit floor and trimming
        - Trailing stop activation
        - Stop loss / take profit triggers
        - Staged time-based exits
        - Exit policy resolution
        """
        logger.warning("[TRAIL-MONITOR] _monitor_positions_loop called - DISABLED (delegated to PositionMonitor)")
        # No-op - PositionMonitor handles all exit monitoring
        return

    def _emit_health_alert(self, alert_type: str, details: str) -> None:
        """Emit health alert for monitoring.

        Args:
            alert_type: Type of alert (e.g., "monitoring_loop_slow", "monitoring_loop_error")
            details: Additional details about the alert
        """
        try:
            from monitoring.metrics import get_metrics_registry
            reg = get_metrics_registry()
            counter = reg.counter(
                "merid_position_monitor_health_alerts_total",
                help_text="Position monitor health alerts",
                label_names=["alert_type"]
            )
            counter.labels(alert_type=alert_type).inc()
        except Exception as e:
            logger.debug("[TRAIL-MONITOR] Failed to emit health alert: %s", e)

    def _trigger_trading_halt(self, reason: str) -> None:
        """Trigger trading halt due to monitoring failure.

        Args:
            reason: Reason for the trading halt
        """
        try:
            from merid.governance.adaptive_risk_limits import get_adaptive_risk_limits
            risk_limits = get_adaptive_risk_limits()
            risk_limits.emergency_halt = True
            risk_limits.emergency_halt_reason = f"Position monitoring failure: {reason}"
            logger.critical("[TRAIL-MONITOR] Trading halt triggered: %s", reason)
        except Exception as e:
            logger.critical("[TRAIL-MONITOR] Failed to trigger trading halt: %s", e)


# Singleton accessor
import threading as _threading
_position_cache_instance: "KalshiPositionCache | None" = None
_position_cache_lock = _threading.Lock()


def get_position_cache() -> "KalshiPositionCache":
    """Get the global position cache singleton."""
    global _position_cache_instance
    if _position_cache_instance is None:
        with _position_cache_lock:
            if _position_cache_instance is None:
                _position_cache_instance = KalshiPositionCache()
    return _position_cache_instance


# Backwards-compatible alias used by legacy test suites.
PositionCache = KalshiPositionCache

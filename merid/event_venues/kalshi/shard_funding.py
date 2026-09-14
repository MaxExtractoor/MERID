"""Kalshi exchange-shard collateral management for the 15m crypto stack.

Kalshi split its matching engine into exchange shards (see
https://docs.kalshi.com/getting_started/exchange_sharding).  Since 2026-08-24
every new crypto event is created on shard 2, and *collateral is checked per
shard*: an order on a shard-2 market is rejected with ``insufficient_balance``
unless enough cash sits on shard 2, no matter how much cash sits on shard 0.

This module is the single place that:

* resolves which shard the active 15m markets trade on,
* reads the per-shard cash breakdown,
* moves idle cash onto the trading shard when it is under-funded, and
* reports a structured result for preflight / telemetry.

Funding is an intra-account transfer only.  It never withdraws, never touches
positions, and is governed by ``MERID_AUTO_FUND_TRADING_SHARD`` (default on for
the production startup script).  Failure to fund is surfaced as a precise
denial reason instead of letting doomed orders hit the exchange.
"""
from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_CEILING, ROUND_DOWN
from typing import Any, Dict, Iterable, Optional

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.shard_funding")

DEFAULT_TRADING_SHARD = 2  # Kalshi crypto shard (2026-08-24 onward)


def _env_flag(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes")


def auto_fund_enabled() -> bool:
    return _env_flag("MERID_AUTO_FUND_TRADING_SHARD", "1")


def min_collateral_cents() -> int:
    """Smallest shard balance that makes a one-contract entry possible.

    With Kalshi V2 count_fp the minimum order is one centi-contract (0.01).
    At the default 35c held floor the all-in cost is ~1.35c (price * 0.01 + 1c
    parabolic fee), so the default is 2c.  The env var remains an operator
    override, but the function clamps it to at least 1c and never above the
    configured target.
    """
    try:
        return max(1, int(os.environ.get("MERID_MIN_TRADING_SHARD_COLLATERAL_CENTS", "2")))
    except ValueError:
        return 2


def target_shard_usd() -> Decimal:
    """Cash we want parked on the trading shard: the fixed exposure cap.

    The $2 slot allocator (``MERID_FIXED_EXPOSURE_CAP_USD``) is the only
    exposure model, so a fully funded shard needs exactly one cap of cash.
    """
    try:
        return Decimal(os.environ.get("MERID_FIXED_EXPOSURE_CAP_USD", "2.00"))
    except ArithmeticError:
        return Decimal("2.00")


def resolve_trading_shard(catalog: Any = None) -> int:
    """Return the shard the active 15m crypto markets live on.

    Priority: explicit ``MERID_KALSHI_TRADING_SHARD`` env, then the
    ``exchange_index`` reported by the market catalog, then the documented
    crypto default (2).
    """
    env = os.environ.get("MERID_KALSHI_TRADING_SHARD", "").strip()
    if env:
        try:
            return int(env)
        except ValueError:
            logger.warning("[SHARD-FUNDING] invalid MERID_KALSHI_TRADING_SHARD=%r; ignoring", env)
    if catalog is not None:
        try:
            markets: Iterable[Any] = catalog.get_all_markets() if hasattr(catalog, "get_all_markets") else []
            seen = {
                int(getattr(m, "exchange_index"))
                for m in markets
                if getattr(m, "exchange_index", None) is not None
            }
            if len(seen) == 1:
                return seen.pop()
            if len(seen) > 1:
                logger.warning("[SHARD-FUNDING] catalog reports multiple shards %s; using max", sorted(seen))
                return max(seen)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("[SHARD-FUNDING] catalog shard resolution failed: %s", exc)
    return DEFAULT_TRADING_SHARD


@dataclass
class ShardFundingResult:
    trading_shard: int
    shard_balances: Dict[int, Decimal]
    trading_shard_usd: Decimal
    target_usd: Decimal
    transferred_cents: int = 0
    transfer_id: Optional[str] = None
    source_shard: Optional[int] = None
    funded: bool = False
    reason: str = ""
    error: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def trading_shard_cents(self) -> int:
        return int((self.trading_shard_usd * 100).to_integral_value(rounding=ROUND_DOWN))

    def summary(self) -> str:
        return (
            f"shard={self.trading_shard} cash=${self.trading_shard_usd:.4f} target=${self.target_usd:.2f} "
            f"funded={self.funded} transferred_cents={self.transferred_cents} reason={self.reason}"
            + (f" error={self.error}" if self.error else "")
        )


_last_check_ts: float = 0.0
_last_result: Optional[ShardFundingResult] = None
_bal_cache: Dict[int, Decimal] = {}
_bal_cache_ts: float = 0.0


def last_result() -> Optional[ShardFundingResult]:
    return _last_result


async def ensure_trading_shard_funded(
    client: Any,
    catalog: Any = None,
    *,
    target_usd: Optional[Decimal] = None,
    allow_transfer: Optional[bool] = None,
    settle_timeout_s: float = 30.0,
) -> ShardFundingResult:
    """Make sure the trading shard holds enough collateral for an entry.

    Steps:
      1. Read per-shard cash.
      2. If trading-shard cash >= min(target, total cash) -> funded, done.
      3. Otherwise move ``min(deficit, idle cash on other shards)`` onto the
         trading shard (largest donor shard first) and poll until visible.

    Never raises; the result carries ``funded`` plus a structured reason.
    """
    global _last_check_ts, _last_result

    shard = resolve_trading_shard(catalog)
    target = target_usd if target_usd is not None else target_shard_usd()
    allow_transfer = auto_fund_enabled() if allow_transfer is None else allow_transfer

    bal = await client.get_shard_balances()
    if not bal.success:
        res = ShardFundingResult(shard, {}, Decimal("0"), target, reason="balance_fetch_failed", error=str(bal.error))
        _last_check_ts, _last_result = time.time(), res
        logger.error("[SHARD-FUNDING] %s", res.summary())
        return res

    shards: Dict[int, Decimal] = dict(bal.data or {})
    have = shards.get(shard, Decimal("0"))
    min_needed = Decimal(min_collateral_cents()) / 100

    # Only whole cents can be moved between shards (Kalshi transfers are in
    # cents / centicents).  Compute the transferable idle cash in integer cents.
    donors = sorted(
        ((idx, usd) for idx, usd in shards.items() if idx != shard and usd > 0),
        key=lambda kv: kv[1],
        reverse=True,
    )
    idle_cents = sum(int((usd * 100).to_integral_value(rounding=ROUND_DOWN)) for _, usd in donors)
    usable_total = have + (Decimal(idle_cents) / 100)

    # The effective target is the smaller of the configured exposure cap and the
    # cash we can actually get onto the trading shard.  This keeps sub-cent
    # residue on other shards from being counted as spendable.
    effective_target = min(target, usable_total)

    res = ShardFundingResult(shard, shards, have, effective_target)
    res.details = {
        "configured_target_usd": float(target),
        "idle_cents_other_shards": idle_cents,
        "min_needed_usd": float(min_needed),
    }

    if have >= effective_target:
        res.funded = have >= min_needed
        res.reason = "already_funded" if res.funded else "account_below_min_collateral"
        _last_check_ts, _last_result = time.time(), res
        logger.info("[SHARD-FUNDING] %s", res.summary())
        return res

    # Round the deficit up: whole-cent transfers must cover the sub-cent gap.
    deficit_cents = int(((effective_target - have) * 100).to_integral_value(rounding=ROUND_CEILING))
    deficit_cents = min(deficit_cents, idle_cents)
    res.details["deficit_cents"] = deficit_cents

    if deficit_cents <= 0:
        res.funded = have >= min_needed
        res.reason = "no_idle_cash_on_other_shards"
        _last_check_ts, _last_result = time.time(), res
        logger.warning("[SHARD-FUNDING] %s", res.summary())
        return res

    if not allow_transfer:
        res.funded = have >= min_needed
        res.reason = "auto_fund_disabled"
        _last_check_ts, _last_result = time.time(), res
        logger.warning(
            "[SHARD-FUNDING] trading shard under-funded and MERID_AUTO_FUND_TRADING_SHARD is off: %s", res.summary()
        )
        return res

    # Transfer from the richest donor shard.  One transfer per call keeps the
    # audit trail simple; the periodic re-check tops up if needed.
    src, src_usd = donors[0]
    src_cents = int((src_usd * 100).to_integral_value(rounding=ROUND_DOWN))
    amount = min(deficit_cents, src_cents)
    xfer = await client.transfer_between_shards(src, shard, amount)
    if not xfer.success:
        res.reason = "transfer_rejected"
        res.error = str(xfer.error)
        res.source_shard = src
        _last_check_ts, _last_result = time.time(), res
        logger.error("[SHARD-FUNDING] %s", res.summary())
        return res

    res.source_shard = src
    res.transferred_cents = amount
    res.transfer_id = (xfer.data or {}).get("transfer_id")
    logger.warning(
        "[SHARD-FUNDING] transfer accepted %d -> %d amount_cents=%d transfer_id=%s; waiting for settlement",
        src, shard, amount, res.transfer_id,
    )

    deadline = time.monotonic() + settle_timeout_s
    expected = have + Decimal(amount) / 100
    while time.monotonic() < deadline:
        await asyncio.sleep(2.0)
        again = await client.get_shard_balances()
        if again.success:
            shards = dict(again.data or {})
            have = shards.get(shard, Decimal("0"))
            if have + Decimal("0.005") >= expected:
                break
    res.shard_balances = shards
    res.trading_shard_usd = have
    res.funded = have >= min_needed
    res.reason = "transferred" if have + Decimal("0.005") >= expected else "transfer_pending"
    _last_check_ts, _last_result = time.time(), res
    global _bal_cache, _bal_cache_ts
    _bal_cache, _bal_cache_ts = dict(shards), time.time()
    logger.warning("[SHARD-FUNDING] %s", res.summary())
    return res


async def get_shard_balances_cached(client: Any, max_age_s: float = 15.0) -> Dict[int, Decimal]:
    """Cheap per-shard balance read for hot paths (no transfers, throttled GET)."""
    global _bal_cache, _bal_cache_ts
    if time.time() - _bal_cache_ts < max_age_s and _bal_cache:
        return dict(_bal_cache)
    res = await client.get_shard_balances()
    if res.success and res.data:
        _bal_cache, _bal_cache_ts = dict(res.data), time.time()
    return dict(_bal_cache)


async def maybe_refund_trading_shard(client: Any, catalog: Any = None, min_interval_s: float = 60.0) -> Optional[ShardFundingResult]:
    """Throttled periodic top-up for the trading loop.

    Settlement payouts land on the trading shard, but fresh deposits land on
    shard 0; this keeps the trading shard funded without hammering the API.
    """
    if time.time() - _last_check_ts < min_interval_s:
        return _last_result
    try:
        return await ensure_trading_shard_funded(client, catalog)
    except Exception as exc:  # never let a funding hiccup kill the loop
        logger.warning("[SHARD-FUNDING] periodic top-up failed: %s", exc)
        return _last_result

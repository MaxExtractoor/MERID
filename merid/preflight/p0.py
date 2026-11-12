"""Shared P0 preflight assertions.

Used by both the standalone ``scripts/p0_preflight.py`` read-only script and by
the server lifespan.  This module does not create or stop services; callers are
responsible for providing a live client, an initialized catalog, a started
bankroll service, and an RTI stream.
"""
from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.preflight.p0")


def _check(label: str, ok: bool, detail: str = "") -> Tuple[bool, str]:
    status = "PASS" if ok else "FAIL"
    msg = f"[{status}] {label}"
    if detail:
        msg += f": {detail}"
    logger.info("[P0-PREFLIGHT] %s", msg)
    return ok, msg


def _complete_snapshot(result: Any, label: str) -> List[Any]:
    """Reject failed or partial venue snapshots instead of assuming flat."""
    if hasattr(result, "success"):
        if not result.success or (getattr(result, "metadata", None) or {}).get("truncated"):
            raise RuntimeError(f"{label} incomplete: {getattr(result, 'error', None)}")
        result = getattr(result, "data", None)
    if not isinstance(result, list):
        raise RuntimeError(f"{label} did not return a complete list")
    return result


async def _position_snapshot(client: Any) -> List[Any]:
    get_result = getattr(client, "get_positions_result", None)
    result = await get_result() if callable(get_result) else await client.get_positions()
    return _complete_snapshot(result, "positions")


async def _open_order_snapshot(client: Any) -> List[Any]:
    get_result = getattr(client, "get_open_orders_result", None)
    result = await get_result() if callable(get_result) else await client.get_open_orders()
    return _complete_snapshot(result, "open orders")


def _signed_yes_position_map(positions: List[Any], *, exchange: bool) -> Dict[str, int]:
    """Project explicit outcomes and exact quantities into signed-YES cc."""
    exposure: Dict[str, int] = {}

    def field(position: Any, name: str) -> Any:
        return position.get(name) if isinstance(position, dict) else getattr(position, name, None)

    for position in positions:
        ticker = field(position, "market_id") or field(position, "ticker")
        if not isinstance(ticker, str) or not ticker.strip():
            raise ValueError("position missing market identity")
        ticker = ticker.strip().upper()

        quantity_cc = None if exchange else field(position, "quantity_cc")
        if quantity_cc is None:
            quantity = field(position, "size") if exchange else (
                field(position, "quantity_fp")
                if field(position, "quantity_fp") is not None
                else field(position, "contracts")
            )
            if quantity is None or isinstance(quantity, bool):
                raise ValueError(f"{ticker} position missing quantity")
            cc = Decimal(str(quantity)) * Decimal("100")
        else:
            if isinstance(quantity_cc, bool):
                raise ValueError(f"{ticker} position has invalid quantity_cc")
            cc = Decimal(str(quantity_cc))

        if not cc.is_finite() or cc < 0 or cc != cc.to_integral_value():
            raise ValueError(f"{ticker} position is not a nonnegative centi-contract quantity")
        if cc == 0:
            if not exchange and field(position, "contracts") is not None:
                display = Decimal(str(field(position, "contracts")))
                if not display.is_finite() or display != 0:
                    raise ValueError(f"{ticker} position quantity fields conflict")
            continue
        side = (
            field(position, "outcome_id") if exchange else (
                field(position, "outcome")
                or field(position, "thesis_side")
                or field(position, "outcome_side")
                or field(position, "side")
            )
        )
        if not isinstance(side, str) or side.lower() not in ("yes", "no"):
            raise ValueError(f"{ticker} position has unknown outcome side")
        signed_cc = int(cc) if side.lower() == "yes" else -int(cc)
        exposure[ticker] = exposure.get(ticker, 0) + signed_cc
    return {ticker: cc for ticker, cc in exposure.items() if cc}


def _reconciliation_quarantined(ticker: str) -> bool:
    """Use the canonical closed/settlement-pending quarantine policy."""
    from merid.event_venues.kalshi.canonical_portfolio_reconciler import (
        _is_expired_market,
        _is_settlement_pending_market,
    )

    return _is_expired_market(ticker) or _is_settlement_pending_market(ticker)


def _trusted_ledger_signed_exposure(view: Any) -> Dict[str, int]:
    """Derive active exposure from complete, trusted, deduplicated ledger fills."""
    from merid.event_venues.kalshi.binary_price_space import fill_to_signed_yes_exposure

    exposure: Dict[str, int] = {}

    def active_live_fill(fill: Any) -> Optional[str]:
        state = getattr(fill, "canonicalization_state", None)
        if not getattr(fill, "is_live", False) and state == "TRUSTED_PAPER_V1":
            return None
        ticker = getattr(fill, "market_ticker", None)
        if not isinstance(ticker, str) or not ticker.strip():
            raise ValueError("ledger fill missing market ticker")
        ticker = ticker.strip().upper()
        if _reconciliation_quarantined(ticker):
            return None
        if not getattr(fill, "is_live", False):
            raise ValueError(f"{ticker} ledger fill has unknown live provenance")
        return ticker

    for fill in view.provisional:
        ticker = active_live_fill(fill)
        if ticker:
            raise ValueError(f"{ticker} has unresolved provisional fill")
    for fill in view.excluded:
        ticker = active_live_fill(fill)
        if ticker and not (
            str(getattr(fill, "fill_id", "")).startswith("live_router_")
            or getattr(fill, "ingestion_source", "") == "order_router"
        ):
            raise ValueError(f"{ticker} has duplicate venue fill identity")

    for fill in view.authoritative:
        ticker = active_live_fill(fill)
        if not ticker:
            continue
        if getattr(fill, "fill_source", "") == "settlement":
            raise ValueError(f"{ticker} has settlement evidence for an active market")
        # A true conflict requires the signed-YES exposure to diverge from the
        # recorded intent (exposure_mismatch).  A bare outcome-side label
        # mismatch (side_conflict) with proven-matching exposure is the
        # documented counterparty/book-form reporting artifact — e.g. a maker
        # buy_no resting on the YES ask reported as "sell yes" — and matches
        # position_cache.py semantics.  A label conflict whose exposure cannot
        # be compared (exposure_mismatch is None) still fails closed.
        _exposure_mismatch = getattr(fill, "exposure_mismatch", None)
        if (
            getattr(fill, "canonicalization_state", None)
            not in {"TRUSTED_LIVE_V1", "TRUSTED_BACKFILLED_V1"}
            or getattr(fill, "unmatched", False)
            or getattr(fill, "derived_id", False)
            or _exposure_mismatch is True
            or (
                getattr(fill, "side_conflict", False)
                and _exposure_mismatch is None
            )
        ):
            raise ValueError(f"{ticker} has an untrusted or unmatched ledger fill")
        if not getattr(fill, "fill_id", None) or not getattr(fill, "order_id", None):
            raise ValueError(f"{ticker} ledger fill lacks exchange identity")
        if not (getattr(fill, "client_order_id", None) or getattr(fill, "intent_id", None)):
            raise ValueError(f"{ticker} ledger fill lacks intent identity")
        quantity = getattr(fill, "quantity_cc", None)
        delta = getattr(fill, "canonical_yes_delta_cc", None)
        if (
            isinstance(quantity, bool)
            or not isinstance(quantity, int)
            or quantity <= 0
            or isinstance(delta, bool)
            or not isinstance(delta, int)
        ):
            raise ValueError(f"{ticker} ledger fill lacks exact signed quantity")
        expected = fill_to_signed_yes_exposure(
            getattr(fill, "canonical_position_action", None),
            getattr(fill, "canonical_position_side", None),
            quantity,
        )
        if not expected or delta != expected:
            raise ValueError(f"{ticker} ledger fill has inconsistent signed exposure")
        exposure[ticker] = exposure.get(ticker, 0) + delta
    return {ticker: cc for ticker, cc in exposure.items() if cc}


def _position_mismatches(
    exchange: Dict[str, int], other: Dict[str, int], label: str
) -> List[str]:
    return [
        f"{ticker}:exchange={exchange.get(ticker, 0)}:{label}={other.get(ticker, 0)}"
        for ticker in sorted(set(exchange) | set(other))
        if exchange.get(ticker, 0) != other.get(ticker, 0)
    ]


def _rti_observations_fresh(
    observations: Dict[str, Any], assets: List[str], max_age_ms: int, now_ms: int
) -> Tuple[bool, str]:
    missing = [asset for asset in assets if observations.get(asset) is None]
    if missing:
        return False, f"missing_assets={missing}"
    ages: List[int] = []
    for asset in assets:
        obs = observations[asset]
        if not getattr(obs, "execution_eligible", False):
            return False, f"asset={asset} execution_ineligible"
        timestamp = getattr(obs, "observed_ts_ms", None)
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or not timestamp:
            return False, f"asset={asset} invalid_observed_timestamp"
        age = now_ms - timestamp
        if not 0 <= age <= max_age_ms:
            return False, f"asset={asset} age_ms={age}"
        ages.append(int(age))
    return bool(assets), f"assets={len(assets)} max_age_ms={max(ages, default=0)}"


def _check_uncertain_submissions() -> Tuple[bool, str]:
    """Fail closed on durable unknown submissions that can still bind exposure.

    An uncertain attempt can only produce a fill while its market is live.
    Every market this venue trades is a 15-minute contract, and Kalshi cancels
    all resting orders at market close; an attempt older than
    ``MERID_UNCERTAIN_ATTEMPT_EXPOSURE_S`` therefore cannot create residual
    exposure regardless of its unknowable historical outcome.  Those rows are
    quarantined: still nonterminal, still audited, never rewritten without
    evidence — but they cannot block entries on live markets forever.

    Rows younger than the bound, or rows with a missing/unparseable
    ``created_at``, remain strictly blocking.
    """
    try:
        from merid.event_venues.kalshi.order_attempt_store import (
            DEFAULT_DB_PATH,
            ExitOrderAttemptState,
        )

        quarantine_age_s = float(
            os.environ.get("MERID_UNCERTAIN_ATTEMPT_EXPOSURE_S", "21600")
        )
        cutoff = time.time() - quarantine_age_s
        path = Path(DEFAULT_DB_PATH).resolve()
        if not path.is_file():
            raise FileNotFoundError("order attempt store is missing")
        uncertain_exit_states = (
            ExitOrderAttemptState.SUBMITTING.value,
            ExitOrderAttemptState.SUBMISSION_UNKNOWN.value,
            ExitOrderAttemptState.RESOLVING_ON_EXCHANGE.value,
        )
        with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=5)) as conn:
            quarantined = conn.execute(
                "SELECT COUNT(*) FROM order_attempts "
                "WHERE status IN ('SUBMITTING', 'SUBMISSION_UNKNOWN') "
                "AND created_at IS NOT NULL AND created_at <= ?",
                (cutoff,),
            ).fetchone()[0]
            # 2026-11-02: age is only a proxy for "market settled".  A young
            # uncertain attempt on a market that has already expired also
            # cannot create exposure — Kalshi cancels resting orders at close
            # and settlement sweeps whatever remains — yet it boot-blocked
            # P0 deterministically: attempt 9189c4c7 (RESOLVING_ON_EXCHANGE,
            # ~15min old, market KXDOGE15M-26NOV020245-45 already expired)
            # failed this gate until resolved offline.  Reclassify young
            # blocking rows whose market expiry has passed as quarantined
            # (still nonterminal, still audited, resolved by runtime
            # reconcile).  Unparseable/NULL tickers or future expiries stay
            # strictly blocking.
            # 2026-11-12: the same expired-market reclassification now applies
            # to entry order_attempts — attempt oa_bbe157e0 (SUBMISSION_UNKNOWN,
            # route_timeout, market KXBTC15M-26NOV112030-30 expired 01:30Z)
            # boot-blocked P0 for ~40min after its market could no longer trade.
            # Entry rows carry no ticker column; the ticker lives in
            # payload_json.order.ticker.
            from merid.event_venues.kalshi.market_filter import (
                parse_expiry_from_ticker,
            )

            _now_s = time.time()

            def _market_expired(ticker) -> bool:
                if not ticker:
                    return False
                try:
                    expiry_ts = parse_expiry_from_ticker(str(ticker))
                except Exception:
                    return False
                return bool(expiry_ts) and expiry_ts <= _now_s

            blocking = conn.execute(
                "SELECT COUNT(*) FROM order_attempts "
                "WHERE status IN ('SUBMITTING', 'SUBMISSION_UNKNOWN') "
                "AND created_at IS NULL",
            ).fetchone()[0]
            young_entry_rows = conn.execute(
                "SELECT order_attempt_id, payload_json FROM order_attempts "
                "WHERE status IN ('SUBMITTING', 'SUBMISSION_UNKNOWN') "
                "AND created_at IS NOT NULL AND created_at > ?",
                (cutoff,),
            ).fetchall()
            entry_settled_quarantined = 0
            for _r in young_entry_rows:
                _ticker = None
                try:
                    _payload = json.loads(_r[1] or "{}")
                    _ticker = (_payload.get("order") or {}).get("ticker")
                except Exception:
                    _ticker = None
                if _market_expired(_ticker):
                    entry_settled_quarantined += 1
                else:
                    blocking += 1
            quarantined += entry_settled_quarantined

            young_exit_rows = conn.execute(
                f"SELECT attempt_id, ticker FROM exit_order_attempts "
                f"WHERE state IN ({','.join('?' for _ in uncertain_exit_states)}) "
                "AND (created_at IS NULL OR created_at > ?)",
                (*uncertain_exit_states, cutoff),
            ).fetchall()
            exit_blocking = 0
            exit_settled_quarantined = 0
            for _r in young_exit_rows:
                if _r[0] is None or _r[1] is None:
                    # created_at NULL rows already counted above by the same
                    # predicate; treat missing identity as blocking.
                    exit_blocking += 1
                elif _market_expired(_r[1]):
                    exit_settled_quarantined += 1
                else:
                    exit_blocking += 1
            exit_quarantined = conn.execute(
                f"SELECT COUNT(*) FROM exit_order_attempts "
                f"WHERE state IN ({','.join('?' for _ in uncertain_exit_states)}) "
                "AND created_at IS NOT NULL AND created_at <= ?",
                (*uncertain_exit_states, cutoff),
            ).fetchone()[0]
            exit_quarantined += exit_settled_quarantined
        if quarantined or exit_quarantined:
            logger.critical(
                "[P0-PREFLIGHT] %d order attempt(s) and %d exit attempt(s) remain "
                "uncertain but are older than %.0fs or on expired markets; "
                "their markets are settled so they cannot create exposure — "
                "quarantined, not resolved",
                quarantined, exit_quarantined, quarantine_age_s,
            )
        return _check(
            "uncertain_submission_recovery",
            not blocking and not exit_blocking,
            f"order_attempts={blocking} quarantined={quarantined} "
            f"exit_attempts={exit_blocking} exit_quarantined={exit_quarantined}",
        )
    except Exception as exc:
        return _check("uncertain_submission_recovery", False, str(exc))


async def run_p0_preflight_checks(
    client: Any,
    bankroll: Any,
    catalog: Any,
    rti_adapter: Optional[Dict[str, Any]] = None,
    required_assets: Optional[List[str]] = None,
    max_wait_rti: float = 30.0,
    rti_max_age_ms: int = 2000,
    max_position_cap_usd: Decimal = Decimal("2.00"),
    max_riskable_frac: Decimal = Decimal("0.02"),
) -> List[Tuple[bool, str]]:
    """Run the P0 preflight assertions and return (ok, message) pairs.

    Services must already be initialized before calling this function.  No
    state-machine transitions are performed here.
    """
    from merid.event_venues.kalshi.types import BalanceState
    from merid.event_venues.kalshi.position_cache import get_position_cache
    from merid.event_venues.kalshi.fills_ledger import get_fills_ledger

    results: List[Tuple[bool, str]] = []

    # 1. Client ready.
    results.append(_check("kalshi_client ready", client is not None))

    # No funding or live entry enablement while durable submissions are unknown.
    recovery = await asyncio.to_thread(_check_uncertain_submissions)
    results.append(recovery)
    if not recovery[0]:
        return results

    # 2. Balance and positions.
    try:
        balance = await client.get_balance()
        positions = await _position_snapshot(client)
        results.append(
            _check(
                "kalshi_balance_fetch",
                bool(balance and balance.get("USD") is not None),
                f"USD={balance.get('USD')}" if balance and balance.get("USD") is not None else "",
            )
        )
        results.append(
            _check("kalshi_positions_fetch", positions is not None, f"count={len(positions) if positions else 0}")
        )
    except Exception as e:
        results.append(_check("kalshi_balance_fetch", False, str(e)))
        results.append(_check("kalshi_positions_fetch", False, str(e)))

    # 3. Catalog initialized.
    catalog_detail = ""
    try:
        markets = catalog.get_all_markets() if hasattr(catalog, "get_all_markets") else []
        catalog_detail = f"{len(markets)} markets"
        results.append(_check("market_catalog_initialized", len(markets) > 0, catalog_detail))
    except Exception as e:
        results.append(_check("market_catalog_initialized", False, str(e)))

    # 3a. Trading-shard collateral.  Kalshi collateralizes per exchange shard
    # (crypto = shard 2); cash parked on shard 0 cannot back a 15m entry and
    # every order would be rejected with ``insufficient_balance``.  Move idle
    # cash onto the trading shard (intra-account transfer) and fail closed if
    # the shard still cannot back a single contract.
    try:
        from merid.event_venues.kalshi.shard_funding import ensure_trading_shard_funded, min_collateral_cents

        funding = await ensure_trading_shard_funded(client, catalog)
        results.append(
            _check(
                "trading_shard_collateral",
                funding.funded,
                f"{funding.summary()} min_cents={min_collateral_cents()} "
                f"breakdown={{{', '.join(f'{k}: ${v:.4f}' for k, v in sorted(funding.shard_balances.items()))}}}",
            )
        )
    except Exception as e:
        results.append(_check("trading_shard_collateral", False, str(e)))

    # 4. Bankroll service fresh.
    try:
        summary = await bankroll.get_summary(caller_module="p0_preflight")
        bankroll_ok = summary.state == BalanceState.FRESH and summary.equity_usd is not None
        results.append(
            _check(
                "bankroll_service_fresh",
                bankroll_ok,
                f"state={summary.state.name} equity={summary.equity_usd}",
            )
        )
    except Exception as e:
        results.append(_check("bankroll_service_fresh", False, str(e)))

    # 5. Direct exchange reconciliation and cancel-all capability.
    try:
        open_orders = await _open_order_snapshot(client)
        positions = await _position_snapshot(client)
        # P0: request only recent fills (last 24h) to avoid unbounded
        # pagination and partial-data warnings on accounts with long history.
        since_ts = int((time.time() - 86400) * 1000)
        since_dt = datetime.fromtimestamp(since_ts / 1000, tz=timezone.utc)
        fills_result = await client.get_fills(limit=100, since_ts=since_ts)
        fills = _complete_snapshot(fills_result, "fills")

        cache = get_position_cache()
        ledger = get_fills_ledger()

        # Ensure the ledger is loaded from its durable store before comparing.
        # Prefer ensure_loaded(): it shares the single in-flight restore task
        # with the poller instead of running a second full load_from_db pass.
        _load = getattr(ledger, "ensure_loaded", None) or getattr(ledger, "load_from_db", None)
        if _load is None:
            raise RuntimeError("fills ledger has no durable restore")
        try:
            await _load()
        except Exception as load_err:
            raise RuntimeError(f"fills ledger load failed: {load_err}") from load_err
        if not getattr(ledger, "_load_complete", False):
            raise RuntimeError(
                f"fills ledger restore incomplete: {getattr(ledger, '_last_load_error', None)}"
            )

        # REST is authoritative for exchange fills. Reconcile it into the
        # durable ledger before comparing identities so a fill received while
        # the process was stopped is recovered instead of reported as a
        # phantom exchange-only divergence.
        if hasattr(ledger, "ingest_http_fills"):
            try:
                ingested_count, ingested_ids = await ledger.ingest_http_fills(fills)
                logger.info(
                    "[P0-PREFLIGHT] REST fills ingested before reconciliation: "
                    "new=%d ids=%d",
                    ingested_count,
                    len(ingested_ids),
                )
            except Exception as ingest_err:
                raise RuntimeError(f"REST fills ingest failed: {ingest_err}") from ingest_err

        # Reconstruct the active ledger independently before mutating the cache.
        if not hasattr(ledger, "get_canonical_fills"):
            raise RuntimeError("fills ledger does not expose canonical fills")
        canonical_fills = await asyncio.to_thread(ledger.get_canonical_fills)
        ledger_exposure = await asyncio.to_thread(_trusted_ledger_signed_exposure, canonical_fills)
        exchange_exposure = {
            ticker: cc
            for ticker, cc in _signed_yes_position_map(positions, exchange=True).items()
            if not _reconciliation_quarantined(ticker)
        }
        ledger_mismatches = _position_mismatches(exchange_exposure, ledger_exposure, "ledger")
        if ledger_mismatches:
            raise RuntimeError(f"position_mismatches={ledger_mismatches[:5]}")

        # Load the position cache from the exchange so internal state is fresh.
        # sync_from_rest is the canonical exchange->cache path; with force and
        # cleanup_stale the REST snapshot is authoritative (a cached position
        # is removed only when the exchange reports none, no live open order
        # exists, and the fills ledger nets to zero).  It consumes plain dicts,
        # so the VenuePosition/PlacedOrder dataclasses are converted here.
        if hasattr(cache, "sync_from_rest"):
            try:
                _pos_dicts: List[Dict[str, Any]] = []
                for _vp in positions:
                    _qty_fp = Decimal(str(getattr(_vp, "size", 0) or 0))
                    _side = getattr(_vp, "outcome_id", None) or ""
                    _pos_dicts.append({
                        "market_id": getattr(_vp, "market_id", ""),
                        "outcome_id": _side,
                        "side": _side,
                        "thesis_side": _side,
                        "outcome_side": _side,
                        "contracts": int(_qty_fp),
                        "quantity_fp": _qty_fp,
                        "quantity_cc": int(_qty_fp * Decimal("100")),
                        "avg_price_cents": int(
                            Decimal(str(getattr(_vp, "average_entry_price", 0) or 0)) * 100
                        ),
                        "source": "p0_preflight",
                    })
                _order_dicts: Optional[List[Dict[str, Any]]] = None
                if open_orders:
                    _order_dicts = [
                        {
                            "market_id": getattr(_o, "market_id", None),
                            "side": getattr(_o, "side", None),
                            "contracts": int(getattr(_o, "size", 0) or 0),
                        }
                        for _o in open_orders
                    ]
                await cache.sync_from_rest(
                    _pos_dicts,
                    rest_timestamp=time.time(),
                    force=True,
                    open_orders=_order_dicts,
                    cleanup_stale=True,
                )
            except Exception as load_err:
                raise RuntimeError(f"position cache sync failed: {load_err}") from load_err

        # KalshiPositionCache exposes positions via get_all_positions(), not a
        # ``positions`` attribute — the old hasattr check always read [] and
        # the count comparison only passed on flat accounts.
        if hasattr(cache, "get_all_positions"):
            internal_positions = list(cache.get_all_positions(validate_freshness=False).values())
        else:
            raise RuntimeError("position cache does not expose positions")
        cached_exposure = {
            ticker: cc
            for ticker, cc in _signed_yes_position_map(internal_positions, exchange=False).items()
            if not _reconciliation_quarantined(ticker)
        }
        position_mismatches = _position_mismatches(exchange_exposure, cached_exposure, "cache")
        # Get all durable fills; we compare by identity, not by simple count.
        internal_fills = (
            canonical_fills.authoritative + canonical_fills.provisional + canonical_fills.excluded
        )

        ex_ids = {f.get("fill_id") or f.get("trade_id") for f in fills}
        ex_by_order: Dict[str, List[Dict[str, Any]]] = {}
        for f in fills:
            ex_by_order.setdefault(f.get("order_id"), []).append(f)

        # Settlement-proceeds records (fill_source == "settlement") are
        # ledger-native cash movements booked from /portfolio/settlements —
        # not trades, so the exchange /portfolio/fills feed can never return
        # them.  Comparing them against the external fill set is a guaranteed
        # false divergence; exclude them from the identity comparison.
        in_by_id = {
            f.fill_id: f
            for f in internal_fills
            if getattr(f, "fill_source", None) != "settlement"
            and not str(getattr(f, "fill_id", "") or "").startswith("settlement:")
            and getattr(f, "ingestion_source", None) != "settlement_rest"
        }

        only_exchange = ex_ids - set(in_by_id)
        only_internal = set(in_by_id) - ex_ids

        allowed_internal: List[str] = []
        problematic_internal: List[str] = []
        for fid in only_internal:
            fill = in_by_id[fid]
            # Provisional live-router fills are expected to be superseded by an
            # authoritative exchange fill with a real Kalshi fill_id.  If the
            # exchange already reports a fill for the same order, the provisional
            # record is a pre-promotion duplicate, not an untrusted divergence.
            if fid.startswith("live_router_") and fill.order_id and fill.order_id in ex_by_order:
                allowed_internal.append(fid)
                continue

            # Internal fills whose exchange timestamp is before the exchange
            # window used in this preflight are not a 24h reconciliation
            # divergence; they were reconciled in an earlier period.
            fill_created = getattr(fill, "created_time", None)
            if fill_created is not None and fill_created < since_dt:
                allowed_internal.append(fid)
                continue

            problematic_internal.append(fid)

        recon_ok = (
            not position_mismatches
            and len(open_orders) == 0
            and len(only_exchange) == 0
            and len(problematic_internal) == 0
        )
        recon_detail = (
            f"external_open_orders={len(open_orders)} external_positions={len(positions)} "
            f"external_fills={len(fills)} internal_positions={len(internal_positions)} "
            f"internal_fills={len(internal_fills)} "
            f"extra_internal={len(only_internal)} allowed_extra={len(allowed_internal)} "
            f"missing_external={len(only_exchange)} "
            f"position_mismatches={position_mismatches[:5]} "
            f"problematic_internal={problematic_internal[:5]}"
        )
        results.append(_check("exchange_reconciliation", recon_ok, recon_detail))

        cancel_all_result = await client.cancel_all_open_orders(dry_run=True)
        results.append(
            _check(
                "cancel_all_capability",
                cancel_all_result.get("dry_run", False) or cancel_all_result.get("count", 0) == 0,
                f"would_cancel={len(cancel_all_result.get('would_cancel', []))} dry_run={cancel_all_result.get('dry_run')}",
            )
        )
    except Exception as e:
        results.append(_check("exchange_reconciliation", False, str(e)))

    # 6. RTI stream fresh.
    rti_detail = ""
    try:
        if rti_adapter is None:
            from merid.data.cf_rti_adapter import get_live_rti

            rti_adapter = get_live_rti

        assets = required_assets or ["BTC", "ETH", "SOL", "XRP", "DOGE"]
        observations: Dict[str, Any] = {}
        deadline = time.monotonic() + max_wait_rti
        rti_ok = False
        while time.monotonic() < deadline:
            for asset in assets:
                observations[asset] = rti_adapter(asset)
            rti_ok, rti_detail = _rti_observations_fresh(
                observations, assets, rti_max_age_ms, int(time.time() * 1000)
            )
            if rti_ok:
                break
            await asyncio.sleep(min(0.2, max(0.0, deadline - time.monotonic())))
        if not observations:
            rti_detail = "no RTI observations received"
        results.append(_check("rti_stream_fresh", rti_ok, rti_detail))
    except Exception as e:
        results.append(_check("rti_stream_fresh", False, f"{e} {rti_detail}".strip()))

    # 7. Threshold-cell band containment.  Every approved conditional
    # threshold cell must contain at least one (price, TTE) point the live
    # market-regime band policy admits — a cell that can never fire is a
    # deployment bug and must fail closed, not die silently in the funnel.
    try:
        from merid.prediction import threshold_cells as _tc

        if not _tc.threshold_cells_enabled():
            results.append(
                _check("threshold_cell_band_containment", True, "cells disabled")
            )
        else:
            _report = _tc.validate_cells_within_price_bands()
            results.append(
                _check(
                    "threshold_cell_band_containment",
                    True,
                    "cells=%d reachable=%d" % (
                        len(_report),
                        sum(1 for r in _report if r["reachable"]),
                    ),
                )
            )
    except AssertionError as _tc_assert:
        results.append(
            _check("threshold_cell_band_containment", False, str(_tc_assert))
        )
    except Exception as e:
        results.append(_check("threshold_cell_band_containment", False, str(e)))

    # 8. Resolved pinned-fav policy echo (2026-10-31 audit directive).  The
    # effective lane configuration is printed verbatim on every preflight so
    # a documented limit can never again lose silently to an unnoticed env
    # override.  Values are resolved through the same helpers the
    # emit/gate/clamp/wire enforcement points call — the printed band IS the
    # enforced band.  Resolution failure fails closed: a policy that cannot
    # be read should not silently pass.
    try:
        import os as _os

        from merid.prediction import directional_regime as _dr_p0

        _maker = _dr_p0.pinned_fav_maker_mode()
        _band_src = (
            "env:MERID_PINNED_FAV_MAKER_LO/HI"
            if _maker
            else "env:MERID_PINNED_FAV_PRICE_LO/HI"
        )
        _mc_env = (_os.environ.get("MERID_PINNED_FAV_MAX_CONTRACTS") or "").strip()
        _gen_cap = None
        try:
            from merid.prediction.agent_grid_15m import _bounded_lane_max_contracts

            _gen_cap = float(_bounded_lane_max_contracts())
        except Exception:
            pass
        _eff_caps = [c for c in (_gen_cap, float(_mc_env) if _mc_env else None) if c]
        _eff_cap = min(_eff_caps) if _eff_caps else None
        _cap_src = (
            f"env:MERID_PINNED_FAV_MAX_CONTRACTS={_mc_env}"
            if _mc_env
            else "generic_bounded_lane_cap"
        )
        # Sizing interaction (2026-10-31 containment spec): risk-scaled
        # sizing proposes contracts = loss_budget_cents / entry_price, which
        # inside the 94-98c band is ~6 contracts; the lane cap then binds the
        # final constructed quantity.  Resolved through the sizer's own
        # helpers so the printed budget IS the enforced budget.
        _sizing = "sizing=n/a"
        try:
            from merid.prediction import trade_decision as _td_p0

            _rs_on = _td_p0._risk_scaled_sizing_enabled()
            _budget_c = _td_p0._per_trade_loss_budget_cents()
            _lo_c = _dr_p0._pinned_fav_lo()
            _propose_cc = (
                int(_budget_c * 100.0 / _lo_c) if _rs_on and _lo_c > 0 else None
            )
            _sizing = (
                "risk_scaled=%s loss_budget_cents=%g -> proposal~%gcc@%gc; "
                "pinned_fav_cap=%s binds final qty"
                % (_rs_on, _budget_c, _propose_cc, _lo_c, _eff_cap)
            )
        except Exception as _se:
            _sizing = "sizing_resolve_error=%s" % _se
        _caps = " ".join(
            "%s-%s=%s"
            % (
                a,
                s,
                (
                    "none"
                    if _dr_p0._moneyness_max_entry_price_cents(s, a) is None
                    else "%g" % _dr_p0._moneyness_max_entry_price_cents(s, a)
                ),
            )
            for a in ("BTC", "ETH", "SOL", "XRP", "DOGE")
            for s in ("yes", "no")
        )
        results.append(
            _check(
                "pinned_fav_policy_resolution",
                True,
                "enabled=%s maker=%s band=%g-%g src=%s tte=%g-%g min_p=%s "
                "min_ev=%s daily_max=%s max_contracts=%s src=%s %s caps{%s}"
                % (
                    _dr_p0.pinned_fav_enabled(),
                    _maker,
                    _dr_p0._pinned_fav_lo(),
                    _dr_p0._pinned_fav_hi(),
                    _band_src,
                    _dr_p0._pinned_fav_min_tte(),
                    _dr_p0._pinned_fav_max_tte(),
                    _dr_p0._pinned_fav_maker_min_p() if _maker else "n/a",
                    _dr_p0._pinned_fav_min_ev_cents(),
                    _dr_p0.pinned_fav_daily_max(),
                    _eff_cap,
                    _cap_src,
                    _sizing,
                    _caps,
                ),
            )
        )
    except Exception as e:
        results.append(_check("pinned_fav_policy_resolution", False, str(e)))

    return results

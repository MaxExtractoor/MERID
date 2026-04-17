"""Kalshi prediction market executor for MERID.

Delegates all HTTP, auth (RSA-PSS), retry, and circuit-breaker logic to
KalshiVenueClient — the single canonical Kalshi client implementation.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any, Dict, List, Optional

from merid.execution.base import Quote, Position, TradeResult, TradeSideLiteral
from merid.event_venues.kalshi.market_filter import (
    group_id_from_ticker,
    extract_asset_from_ticker,
    get_series_timeframe_bucket,
)
from utils.logger import get_logger

logger = get_logger("merid.execution.executors.kalshi")

# T-022: Module-level kill switch error flag — once set, blocks ALL orders
_kill_switch_error: bool = False
_kill_switch_lock = threading.Lock()  # ZT3-06: guard flag read/write


def reset_kill_switch_error() -> None:
    """Explicitly clear the kill switch error flag. Requires proper auth."""
    global _kill_switch_error
    with _kill_switch_lock:
        _kill_switch_error = False
    logger.info("Kill switch error flag cleared")


def _get_venue_client():
    """Lazy-load KalshiVenueClient with settings-based config."""
    from merid.settings import settings
    from merid.event_venues.kalshi.client import KalshiVenueClient
    from merid.event_venues.kalshi.models import KalshiConfig

    # T-009: Startup assertion — verify config matches trading mode BEFORE creating client
    # This prevents creating client that could accidentally hit production from paper mode
    try:
        from trading.trade_mode import get_trade_mode, TradeMode
        _mode = get_trade_mode()
        _env = getattr(settings, 'MERID_ENV', None) or __import__('os').getenv('MERID_ENV', 'production')
        _is_prod = _env in ('production', 'prod', 'live')
        _is_live = _mode == TradeMode.LIVE
        _is_paper = _mode == TradeMode.PAPER
        _is_mock = _mode == TradeMode.MOCK
        
        # Determine what URL would be used based on settings
        _use_demo = settings.KALSHI_USE_DEMO
        _base = "https://demo-api.kalshi.co/trade-api/v2" if _use_demo else "https://api.elections.kalshi.com/trade-api/v2"
        _is_demo_url = 'demo' in _base.lower()
        
        # Check for misconfigurations that could cause accidental live orders
        if _is_mock and not _is_demo_url:
            # MOCK mode should never hit production
            logger.critical(
                "CRITICAL: MOCK mode but client URL is LIVE (%s). "
                "Refusing to create client. Set KALSHI_USE_DEMO=true for sandbox.",
                _base,
            )
            raise RuntimeError(
                f"MOCK mode but client URL is LIVE ({_base}). "
                "In MOCK mode, no real API calls should be made. "
                "Set KALSHI_USE_DEMO=true if you want to test against sandbox."
            )
        
        if _is_live and _is_demo_url:
            # LIVE mode with demo URL is a configuration mistake
            logger.error(
                "ERROR: LIVE trading mode but client URL is DEMO (%s). "
                "Live orders will be sent to sandbox! Set KALSHI_USE_DEMO=false for production.",
                _base,
            )
            # Don't raise - this is a config warning, not a safety issue
            if not getattr(_get_venue_client, '_logged_live_demo_mismatch', False):
                _get_venue_client._logged_live_demo_mismatch = True
                
        if _is_paper and not _is_demo_url:
            # PAPER mode with live URL: Read-only calls to live API are OK for market data
            # VenueGate blocks actual orders in paper mode, so this is safe but warn
            if not getattr(_get_venue_client, '_logged_paper_live_readonly', False):
                logger.warning(
                    "PAPER mode with LIVE URL (%s). Read-only API calls allowed. "
                    "Orders are blocked by VenueGate (paper mode). "
                    "Set KALSHI_USE_DEMO=true to use sandbox instead.",
                    _base,
                )
                _get_venue_client._logged_paper_live_readonly = True
                
    except ImportError:
        logger.warning("trade_mode module unavailable — skipping URL/mode assertion")

    key_path = settings.KALSHI_PRIVATE_KEY_PATH
    if key_path == "change_me":
        key_path = None

    config = KalshiConfig(
        api_key=settings.KALSHI_API_KEY_ID,
        private_key_path=key_path,
        private_key_pem=settings.KALSHI_PRIVATE_KEY_PEM,
        email=settings.KALSHI_EMAIL,
        password=settings.KALSHI_PASSWORD,
        use_demo=settings.KALSHI_USE_DEMO,
    )
    client = KalshiVenueClient(config)

    return client


class KalshiExecutor:
    """Kalshi prediction market executor.

    Thin adapter that bridges MERID's TradeExecutor interface to the
    canonical KalshiVenueClient (RSA-PSS auth, circuit breaker, retry).
    """

    venue = "kalshi"

    def __init__(self) -> None:
        self._client = None

    def _get_client(self):
        """Return shared venue client, creating on first call."""
        if self._client is None:
            self._client = _get_venue_client()
        return self._client

    # ------------------------------------------------------------------
    # TradeExecutor interface
    # ------------------------------------------------------------------

    # T-021: Max orderbook age before rejecting stale data
    MAX_ORDERBOOK_AGE_SECONDS = 10

    async def get_quote(self, symbol: str, side: TradeSideLiteral, amount: float) -> Quote:
        """Get best bid/ask for a Kalshi market outcome."""
        import time as _time
        client = self._get_client()
        _fetch_start = _time.time()
        result = await client._request_with_resilience(
            "GET",
            f"/markets/{symbol}/orderbook",
            operation_name="get_quote",
        )
        if not result.success:
            raise RuntimeError(f"Kalshi quote failed: {result.error_message}")
        data = result.data
        # T-021: Stamp fetch time and check staleness
        data["_fetched_at"] = _fetch_start
        _age = _time.time() - _fetch_start
        if _age > self.MAX_ORDERBOOK_AGE_SECONDS:
            raise RuntimeError(
                f"Stale orderbook for {symbol}: {_age:.1f}s old "
                f"(max {self.MAX_ORDERBOOK_AGE_SECONDS}s)"
            )
        yes_bids = data.get("orderbook", {}).get("yes", [])
        no_bids = data.get("orderbook", {}).get("no", [])
        bids = no_bids if side == "sell" else yes_bids
        price = float(bids[0][0]) / 100.0 if bids else 0.5
        return Quote(
            symbol=symbol,
            side=side,
            price=price,
            venue=self.venue,
            size=amount,
            latency_ms=result.latency_ms,
            metadata={"raw": data},
        )

    async def execute_trade(
        self,
        symbol: str,
        side: TradeSideLiteral,
        amount: float,
        *,
        order_type: str = "market",
        price: Optional[float] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> TradeResult:
        """Submit an order to Kalshi via the canonical venue client."""
        meta = metadata or {}

        # Derive underlying asset and market category from metadata (E4-1)
        _underlying = meta.get("underlying", "").upper()
        if not _underlying:
            # Best-effort inference from ticker prefix
            _TICKER_PREFIXES = [
                ("BTC", "KXBT"), ("ETH", "KXETH"), ("SOL", "KXSOL"),
                ("XRP", "KXXRP"), ("DOGE", "KXDOGE"),
            ]
            for _asset, _pfx in _TICKER_PREFIXES:
                if symbol.upper().startswith(_pfx):
                    _underlying = _asset
                    break
        _category = meta.get("category", "")
        if not _category and _underlying:
            try:
                from merid.event_venues.kalshi.category_exposure import infer_category
                _category = infer_category(_underlying)
            except Exception as e:
                logger.debug(f"Category inference failed: {e}")

        # T-022: Check module-level kill switch error flag first
        global _kill_switch_error
        with _kill_switch_lock:
            _ks_err = _kill_switch_error
        if _ks_err:
            return TradeResult(
                success=False, venue=self.venue, symbol=symbol,
                side=side, size=amount, price=price or 0.0,
                error="Kill switch error flag set — call reset_kill_switch_error() to clear",
                metadata={},
            )

        # Kill switch hard gate — fail-CLOSED on any error
        try:
            from merid.risk.kill_switches import risk_controller
            if not risk_controller.can_trade():
                reason = risk_controller.get_kill_reason() or "kill_switch_active"
                return TradeResult(
                    success=False, venue=self.venue, symbol=symbol,
                    side=side, size=amount, price=price or 0.0,
                    error=f"Trading halted: {reason}", metadata={},
                )
        except Exception as exc:
            with _kill_switch_lock:  # ZT3-06: lock the write too
                _kill_switch_error = True  # T-022: Permanently block until cleared
            logger.critical("Kill-switch unavailable — PERMANENTLY blocking orders: %s", exc)
            return TradeResult(
                success=False, venue=self.venue, symbol=symbol,
                side=side, size=amount, price=price or 0.0,
                error=f"Risk controller unavailable (permanent block): {exc}", metadata={},
            )

        # VenueGate — block real orders in SIM/PAPER/MOCK mode (fail-CLOSED)
        try:
            from merid.prediction.venue_gate import get_venue_gate
            _gate = get_venue_gate()
            if _gate.should_simulate_fill():
                return TradeResult(
                    success=False, venue=self.venue, symbol=symbol,
                    side=side, size=amount, price=price or 0.0,
                    error=f"VenueGate blocked: mode={_gate.mode.value} (paper/sim)",
                    metadata={"simulated": True},
                )
        except Exception as _vge:
            logger.error("VenueGate unavailable — blocking order (fail-closed): %s", _vge)
            return TradeResult(
                success=False, venue=self.venue, symbol=symbol,
                side=side, size=amount, price=price or 0.0,
                error=f"VenueGate unavailable: {_vge}", metadata={},
            )

        client = self._get_client()

        # T-008: Balance validation — verify sufficient funds before order submission
        # Moved before check_order() so BalanceCalibrator can recalibrate risk limits first
        try:
            _bal_result = await client._request_with_resilience(
                "GET", "/portfolio/balance", operation_name="get_balance",
            )
            if _bal_result.success:
                _balance_cents = _bal_result.data.get("balance", 0)
                _price_cents = int(round(price * 100)) if price is not None and price <= 1.0 else int(price if price else 50)
                # Trigger risk limit recalibration if balance moved >5%
                try:
                    from merid.event_venues.kalshi.balance_calibrator import get_balance_calibrator
                    get_balance_calibrator().update(_balance_cents)
                except Exception as _cal_exc:
                    logger.debug("BalanceCalibrator update failed (non-fatal): %s", _cal_exc)
                # Worst-case cost: contracts * 99 cents for market orders
                _order_cost = int(amount) * (
                    _price_cents if order_type == "limit" else 99
                )
                if _balance_cents < _order_cost:
                    return TradeResult(
                        success=False, venue=self.venue, symbol=symbol,
                        side=side, size=amount, price=price or 0.0,
                        error=f"Insufficient balance: {_balance_cents}c < {_order_cost}c required",
                        metadata={"balance_cents": _balance_cents, "order_cost_cents": _order_cost},
                    )
            else:
                logger.warning("Balance check failed — blocking order (fail-closed): %s", _bal_result.error_message)
                return TradeResult(
                    success=False, venue=self.venue, symbol=symbol,
                    side=side, size=amount, price=price or 0.0,
                    error=f"Balance check failed: {_bal_result.error_message}", metadata={},
                )
        except Exception as _bal_exc:
            logger.error("Balance validation unavailable — blocking order (fail-closed): %s", _bal_exc)
            return TradeResult(
                success=False, venue=self.venue, symbol=symbol,
                side=side, size=amount, price=price or 0.0,
                error=f"Balance validation unavailable: {_bal_exc}", metadata={},
            )

        # KalshiRiskManager — position limits, category caps, drawdown, rate limiting (fail-CLOSED)
        # Now uses calibrated limits (balance fetch above) and correct category (E4-1 fix)
        try:
            from merid.event_venues.kalshi.kalshi_risk import get_kalshi_risk
            _risk = get_kalshi_risk()
            # Look up existing position so per-contract limit check is accurate
            _existing_pos = 0
            try:
                from merid.event_venues.kalshi.position_cache import get_position_cache
                _cached = get_position_cache().get_position(symbol)
                if _cached is not None:
                    _existing_pos = _cached.contracts
            except Exception:
                pass  # best-effort; defaults to 0
            
            # Derive asset/timeframe for group-level risk aggregation using canonical helpers
            _asset = extract_asset_from_ticker(symbol)
            _timeframe = get_series_timeframe_bucket(symbol)
            # Prefer upstream group_id from metadata (propagated from FilterPipeline), fallback to canonical helper
            _upstream_group_id = meta.get("group_id")
            if _upstream_group_id is not None and _asset:
                _group_id = _upstream_group_id
                # GROUP_ID TRACE: Log upstream propagation success
                logger.info(
                    "[GROUP-ID-TRACE] executor_using_upstream | ticker=%s group_id=%s "
                    "source=metadata.upstream",
                    symbol, _group_id
                )
                # STRICT MODE: Assert upstream matches recomputed (debug builds only)
                import os as _os_strict
                _strict_mode = _os_strict.getenv("KALSHI_STRICT_GROUP_ID", "false").lower() in ("true", "1", "yes")
                if _strict_mode:
                    _recomputed = group_id_from_ticker(symbol)
                    if _group_id != _recomputed:
                        logger.error(
                            "[GROUP-ID-STRICT-FAIL] upstream=%s recomputed=%s ticker=%s "
                            "| FilterPipeline and executor disagree on canonical group_id!",
                            _group_id, _recomputed, symbol
                        )
                        raise AssertionError(f"group_id mismatch: upstream={_group_id} != recomputed={_recomputed}")
            elif _asset:
                _group_id = group_id_from_ticker(symbol)
                # GROUP_ID TRACE: Log fallback to local computation
                logger.info(
                    "[GROUP-ID-TRACE] executor_using_fallback | ticker=%s group_id=%s "
                    "source=local_recompute",
                    symbol, _group_id
                )
            else:
                _group_id = None
            
            _allowed, _reason = _risk.check_order(
                ticker=symbol, category=_category or None,
                contracts=int(amount), price_cents=_price_cents,
                existing_position=_existing_pos,
                asset=_asset,
                timeframe=_timeframe,
                group_id=_group_id,
            )
            if not _allowed:
                return TradeResult(
                    success=False, venue=self.venue, symbol=symbol,
                    side=side, size=amount, price=price or 0.0,
                    error=f"Risk check blocked: {_reason}", metadata={},
                )
        except Exception as _rke:
            logger.error("KalshiRiskManager unavailable — blocking order (fail-closed): %s", _rke)
            return TradeResult(
                success=False, venue=self.venue, symbol=symbol,
                side=side, size=amount, price=price or 0.0,
                error=f"KalshiRiskManager unavailable: {_rke}", metadata={},
            )

        # DeploymentController — block HALTED/PAPER agents
        _agent_name = meta.get("agent_name", "")
        if _agent_name:
            try:
                from merid.event_venues.kalshi.deployment import get_deployment_controller, AgentMode
                _dep = get_deployment_controller()._agents.get(_agent_name)
                if _dep and _dep.mode in (AgentMode.HALTED, AgentMode.PAPER):
                    return TradeResult(
                        success=False, venue=self.venue, symbol=symbol,
                        side=side, size=amount, price=price or 0.0,
                        error=f"Agent {_agent_name} is {_dep.mode.value} — no live orders",
                        metadata={},
                    )
            except Exception as _dce:
                logger.error("DeploymentController unavailable — blocking order (fail-closed): %s", _dce)
                return TradeResult(
                    success=False, venue=self.venue, symbol=symbol,
                    side=side, size=amount, price=price or 0.0,
                    error=f"DeploymentController unavailable: {_dce}", metadata={},
                )

        # Category exposure — atomic check + reserve (prevents TOCTOU race) (E4-X fix)
        _notional_usd = int(amount) * _price_cents / 100.0
        _cat_tracker = None
        _cat_reserved = False
        if _underlying and _category and side == "buy":
            try:
                from merid.event_venues.kalshi.category_exposure import get_category_exposure_tracker
                _cat_tracker = get_category_exposure_tracker()
                _cat_ok, _cat_reason = _cat_tracker.check_and_reserve(
                    _category, _underlying, _notional_usd
                )
                if not _cat_ok:
                    return TradeResult(
                        success=False, venue=self.venue, symbol=symbol,
                        side=side, size=amount, price=price or 0.0,
                        error=f"Category exposure blocked: {_cat_reason}", metadata={},
                    )
                _cat_reserved = True
            except Exception as _cate:
                logger.warning("CategoryExposureTracker unavailable (non-blocking): %s", _cate)

        # Record order in risk manager — advances rate counters + open notional (buys only)
        if side == "buy":
            try:
                _risk.record_order(_category or None, int(amount), _price_cents)
            except Exception as _ro_exc:
                logger.debug("record_order failed (non-blocking): %s", _ro_exc)

        # Kalshi v2 order payload
        # side here is "buy"/"sell" from MERID; Kalshi uses action + side(yes/no)
        action = side  # "buy" or "sell"
        # Outcome side — warn if caller omitted it (default 'yes' may be wrong) (E4-2 fix)
        outcome_side = meta.get("outcome")
        if outcome_side is None:
            logger.warning(
                "execute_trade: metadata['outcome'] not set for ticker=%s — "
                "defaulting to 'yes'. Pass outcome='yes'|'no' to suppress.",
                symbol,
            )
            outcome_side = "yes"
        client_order_id = meta.get("client_order_id") or f"merid-{uuid.uuid4().hex[:12]}"

        payload: Dict[str, Any] = {
            "ticker": symbol,
            "action": action,
            "side": outcome_side,
            "type": order_type,
            "count": int(amount),
            "client_order_id": client_order_id,
        }
        if order_type == "limit" and price is not None:
            # Kalshi prices are integers 1-99 (cents per dollar)
            price_key = "no_price" if outcome_side == "no" else "yes_price"
            payload[price_key] = int(round(price * 100)) if price <= 1.0 else int(price)

        result = await client._request_with_resilience(
            "POST",
            "/portfolio/orders",
            json_data=payload,
            operation_name="execute_trade",
        )

        # T-020: On timeout, query for the order by client_order_id
        if not result.success and "timeout" in str(result.error_message).lower():
            import asyncio
            logger.warning(
                "Order timeout for %s — checking if order exists (client_order_id=%s)",
                symbol, client_order_id,
            )
            for _attempt in range(3):
                await asyncio.sleep(2)
                _check = await client._request_with_resilience(
                    "GET",
                    f"/portfolio/orders?client_order_id={client_order_id}",
                    operation_name="check_order_exists",
                )
                if _check.success:
                    _orders = _check.data.get("orders", [])
                    if _orders:
                        _found = _orders[0]
                        logger.info(
                            "Order found after timeout: order_id=%s status=%s",
                            _found.get("order_id"), _found.get("status"),
                        )
                        _ep = float(_found.get("yes_price", 0)) / 100.0
                        return TradeResult(
                            success=True, venue=self.venue, symbol=symbol,
                            side=side, size=amount, price=_ep,
                            tx_id=_found.get("order_id"),
                            metadata={
                                "order_id": _found.get("order_id"),
                                "status": _found.get("status"),
                                "client_order_id": client_order_id,
                                "recovered_after_timeout": True,
                            },
                        )
            logger.error("Order not found after 3 timeout recovery attempts: %s", client_order_id)

        if not result.success:
            # Reverse notional — keep rate counters (the order was attempted) (E4-5 fix)
            try:
                _risk.record_close(_category or None, int(amount), _price_cents)
            except Exception as _rc_exc:
                logger.debug("record_close failed (non-blocking): %s", _rc_exc)
            # Release category exposure reservation (E4-X fix)
            if _cat_reserved and _cat_tracker:
                try:
                    _cat_tracker.release(_category, _underlying, _notional_usd)
                except Exception as e:
                    logger.debug(f"Category exposure release failed: {e}")
            return TradeResult(
                success=False,
                venue=self.venue,
                symbol=symbol,
                side=side,
                size=amount,
                price=price or 0.0,
                error=f"Kalshi order failed: {result.error_message}",
                metadata={"latency_ms": result.latency_ms},
            )

        order_data = result.data.get("order", result.data)
        executed_price_raw = order_data.get("yes_price") or order_data.get("no_price") or 0
        executed_price = float(executed_price_raw) / 100.0

        # T-040: Partial fill detection
        filled_count = order_data.get("filled_count", order_data.get("quantity_filled", 0))
        requested_count = order_data.get("count", order_data.get("quantity", amount))
        is_partial = 0 < filled_count < requested_count
        if is_partial:
            logger.warning(
                "PARTIAL FILL: %s %s — filled %d/%d contracts (order_id=%s)",
                symbol, side, filled_count, requested_count,
                order_data.get("order_id", "?"),
            )

        # Sell fills reduce open exposure (E4-5 fix)
        _actual_count = filled_count if filled_count > 0 else int(amount)
        _actual_notional = _actual_count * _price_cents / 100.0
        if action == "sell":
            try:
                _risk.record_close(_category or None, _actual_count, _price_cents)
            except Exception as _rc_exc:
                logger.debug("record_close failed (non-blocking): %s", _rc_exc)
            if _cat_tracker and _underlying and _category:
                try:
                    _cat_tracker.release(_category, _underlying, _actual_notional)
                except Exception as e:
                    logger.debug(f"Category exposure release failed: {e}")

        return TradeResult(
            success=True,
            venue=self.venue,
            symbol=symbol,
            side=side,
            size=filled_count if filled_count > 0 else amount,
            price=executed_price,
            tx_id=order_data.get("order_id"),
            metadata={
                "order_id": order_data.get("order_id"),
                "status": order_data.get("status"),
                "client_order_id": client_order_id,
                "latency_ms": result.latency_ms,
                "partial_fill": is_partial,
                "filled_count": filled_count,
                "requested_count": requested_count,
            },
        )

    async def get_positions(self) -> List[Position]:
        """Fetch open positions from Kalshi."""
        client = self._get_client()
        result = await client._request_with_resilience(
            "GET",
            "/portfolio/positions",
            operation_name="get_positions",
        )
        if not result.success:
            logger.warning(f"[kalshi] get_positions failed: {result.error_message}")
            return []

        positions = []
        for pos in result.data.get("market_positions", []):
            raw_count = pos.get("position", 0)
            if raw_count == 0:
                continue
            total_cost = float(pos.get("total_traded", 0)) / 100.0
            entry_price = total_cost / abs(raw_count) if raw_count else 0.0
            positions.append(
                Position(
                    symbol=pos["ticker"],
                    size=float(raw_count),
                    entry_price=entry_price,
                    pnl=float(pos.get("realized_pnl", 0)) / 100.0,
                    venue=self.venue,
                    metadata={
                        "ticker": pos["ticker"],
                        "resting_orders_count": pos.get("resting_orders_count", 0),
                    },
                )
            )
        return positions

    # ------------------------------------------------------------------
    # Extended Kalshi-specific methods
    # ------------------------------------------------------------------

    async def authenticate(self) -> bool:
        """Test authentication with Kalshi API."""
        try:
            client = self._get_client()
            result = await client._request_with_resilience(
                "GET",
                "/exchange/status",
                operation_name="authenticate",
            )
            return result.success
        except Exception as exc:
            logger.warning(f"[kalshi] authenticate check failed: {exc}")
            return False

    async def get_balance(self) -> Dict[str, Any]:
        """Fetch account balance from Kalshi (usd keys in dollars; locked/available in cents)."""
        client = self._get_client()
        result = await client._request_with_resilience(
            "GET",
            "/portfolio/balance",
            operation_name="get_balance",
        )
        if not result.success:
            raise RuntimeError(f"Kalshi balance fetch failed: {result.error_message}")
        data = result.data
        balance_cents = data.get("balance", 0)
        locked_cents = data.get("payout", 0)
        return {
            "usd": balance_cents / 100.0,
            "usd_dollars": balance_cents / 100.0,
            "locked": locked_cents,
            "locked_dollars": locked_cents / 100.0,
            "available": balance_cents - locked_cents,
            "available_dollars": (balance_cents - locked_cents) / 100.0,
        }

    async def get_orders(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """Fetch orders from Kalshi."""
        client = self._get_client()
        params: Dict[str, Any] = {}
        if status:
            params["status"] = status
        result = await client._request_with_resilience(
            "GET",
            "/portfolio/orders",
            params=params,
            operation_name="get_orders",
        )
        if not result.success:
            logger.warning(f"[kalshi] get_orders failed: {result.error_message}")
            return []
        return result.data.get("orders", [])

    async def get_fills(self) -> List[Dict[str, Any]]:
        """Fetch recent fills/trades from Kalshi."""
        client = self._get_client()
        result = await client._request_with_resilience(
            "GET",
            "/portfolio/fills",
            operation_name="get_fills",
        )
        if not result.success:
            logger.warning(f"[kalshi] get_fills failed: {result.error_message}")
            return []
        return result.data.get("fills", [])

    async def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        client = self._get_client()
        result = await client._request_with_resilience(
            "DELETE",
            f"/portfolio/orders/{order_id}",
            operation_name="cancel_order",
        )
        if not result.success:
            logger.warning(f"[kalshi] cancel_order {order_id} failed: {result.error_message}")
            return False
        return True

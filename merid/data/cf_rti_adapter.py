"""CF Benchmarks Real-Time Index (RTI) adapter — authoritative, fail-closed.

This module is the single source of truth for the settlement reference price
used by the Kalshi 15m crypto stack.  It returns a typed, immutable
``CfbRtiObservation`` only when every health gate passes.  Public spot or stale
values are never returned as a fallback.

Design notes:
- The adapter is synchronous so it can be called from the synchronous signal
  generation path in ``agent_grid_15m``.
- Health failures are logged with a precise rejection reason that becomes the
  candidate's ``no_trade_reason``.
- ``MERID_CFB_RTI_ADAPTER`` must be set to ``live`` before the adapter will
  attempt to call the live CF Benchmarks API.  In paper/shadow mode the trading
  stack still sets this to ``live`` but uses ``MERID_ALLOW_LIVE_TRADES=false``
  to keep entries disabled while it validates the feed.
"""
from __future__ import annotations

import json
import math
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

import httpx

from merid.data.price_precision import (
    format_price as _format_price,
    get_asset_settlement_digits,
    parse_price,
    retained_decimal_places,
    settlement_round,
)
from utils.logger import get_logger

logger = get_logger("merid.data.cf_rti_adapter")

# Kalshi index ID -> asset map (used to validate WebSocket frames whose
# authoritative symbol is the server-returned ID, e.g. ETHUSD_RTI).
from merid.data.kalshi_cf_rti_ws import index_id_to_asset
from merid.data.ingress_recorder import record_ingress, SOURCE_CFB_RTI_REST
from merid.data.ingress_replay import (
    is_replay_active,
    get_replay_dispatcher,
    replay_json_payload,
)


# CF Benchmarks API configuration
_CFB_BASE_URL = "https://api.cfbenchmarks.com"
_CFB_RTI_ENDPOINT = "/api/v1/rti"

# Asset → official CF Benchmarks index symbol
_ASSET_TO_CFB_SYMBOL = {
    "BTC": "BRTI",
    "ETH": "ETH_RTI",
    "SOL": "SOL_RTI",
    "XRP": "XRP_RTI",
    "DOGE": "DOGE_RTI",
}

# Kalshi crypto contracts settle on a one-minute average of CF RTI per-second
# observations.  The 60-second average field is required when trading inside the
# final minute window.
_MAX_CFB_RTI_AGE_MS = int(os.environ.get("MERID_MAX_CFB_RTI_AGE_MS", "7000"))
_FINAL_MINUTE_CUTOFF_S = float(os.environ.get("MERID_FINAL_MINUTE_CUTOFF_S", "60"))
_REQUEST_TIMEOUT = float(os.environ.get("MERID_CFB_RTI_TIMEOUT_S", "5"))


@dataclass(frozen=True)
class CfbRtiObservation:
    """Immutable CF Benchmarks Real-Time Index observation.

    This is the canonical settlement input.  No public-spot fallback is allowed.

    Time fields:
      - ``source_ts_ms``: upstream wall-clock publish timestamp when known and
        valid; ``None`` when malformed or missing.
      - ``observed_ts_ms``: local wall-clock (``time.time_ns()``) when the frame
        was received.  Used for observability, not as the primary freshness gate.
      - ``observed_ts_mono_ns``: local monotonic time (``time.monotonic_ns()``)
        when the frame was received.  This is the authoritative clock for
        staleness because wall-clock time can jump.
      - ``timestamp_quality``: ``"source"`` | ``"missing"`` | ``"invalid"``.
      - ``execution_eligible``: True only when the source timestamp is valid,
        the feed is fresh on both wall and monotonic clocks, ordering holds,
        and all other health gates pass.  Downstream trading code must check it.

    The ``value`` / ``cfb_60s_average`` float fields are retained for backward
    compatibility.  The canonical Decimal fields are ``value_decimal`` and
    ``cfb_60s_average_decimal``.
    """
    asset: str
    cfb_symbol: str
    value: float
    source_ts_ms: Optional[int] = None
    observed_ts_ms: Optional[int] = None
    observed_ts_mono_ns: Optional[int] = None
    sequence: Optional[int] = None
    source: str = "cf_benchmarks"
    settlement_reference: str = "cfb_rti_live"
    cfb_60s_average: Optional[float] = None
    timestamp_quality: str = "source"
    execution_eligible: bool = True
    price_source_health: str = "healthy"
    # Settlement-grade precision fields
    value_decimal: Optional[Decimal] = None
    cfb_60s_average_decimal: Optional[Decimal] = None
    raw_value: Optional[str] = None
    retained_digits: Optional[int] = None
    market_settlement_digits: Optional[int] = None

    def __post_init__(self):
        # Derive Decimal values from float/string inputs for backward-compatible
        # construction (e.g. tests passing value=65000.0).
        if self.value_decimal is None:
            if self.raw_value is not None:
                object.__setattr__(self, "value_decimal", parse_price(self.raw_value))
            elif self.value is not None:
                object.__setattr__(self, "value_decimal", parse_price(self.value))
        if self.value is None and self.value_decimal is not None:
            object.__setattr__(self, "value", float(self.value_decimal))
        if self.cfb_60s_average_decimal is None and self.cfb_60s_average is not None:
            object.__setattr__(self, "cfb_60s_average_decimal", parse_price(self.cfb_60s_average))
        if self.cfb_60s_average is None and self.cfb_60s_average_decimal is not None:
            object.__setattr__(self, "cfb_60s_average", float(self.cfb_60s_average_decimal))
        if self.raw_value is None and self.value_decimal is not None:
            object.__setattr__(self, "raw_value", str(self.value_decimal))
        if self.retained_digits is None and self.value_decimal is not None:
            object.__setattr__(self, "retained_digits", retained_decimal_places(self.value_decimal))

    def settlement_price(self) -> Optional[Decimal]:
        """Return the 60s average when available, else the latest tick, as Decimal."""
        if self.cfb_60s_average_decimal is not None and self.cfb_60s_average_decimal.is_finite() and self.cfb_60s_average_decimal > 0:
            return self.cfb_60s_average_decimal
        if self.value_decimal is not None and self.value_decimal.is_finite() and self.value_decimal > 0:
            return self.value_decimal
        return None

    def quantized_settlement_price(self, digits: int) -> Optional[Decimal]:
        """Return the settlement price quantized to ``digits`` decimal places."""
        price = self.settlement_price()
        if price is None:
            return None
        return settlement_round(price, digits)

    @property
    def age_ms(self) -> Optional[int]:
        """Source-to-observed age in milliseconds; None if source time is missing/invalid."""
        if self.source_ts_ms is None or self.observed_ts_ms is None:
            return None
        return max(0, self.observed_ts_ms - self.source_ts_ms)

    @property
    def received_ts_ms(self) -> Optional[int]:
        """Legacy alias for ``observed_ts_ms``."""
        return self.observed_ts_ms


# Adapter state for ordering, stream liveness, and last-success tracking.
@dataclass
class _AdapterState:
    last_observation_by_asset: Dict[str, CfbRtiObservation] = field(default_factory=dict)
    last_source_ts_ms_by_asset: Dict[str, int] = field(default_factory=dict)
    last_failure_ts_ms: int = 0
    last_failure_reason_by_asset: Dict[str, str] = field(default_factory=dict)
    consecutive_failures_by_asset: Dict[str, int] = field(default_factory=dict)


_state = _AdapterState()

# Kalshi authenticated ``cfbenchmarks_value`` WebSocket stream.
_kalshi_stream: Optional[Any] = None
_kalshi_stream_lock = threading.Lock()


def _ensure_kalshi_stream() -> Optional[Any]:
    """Lazily start the Kalshi CF-RTI WebSocket stream when enabled."""
    global _kalshi_stream
    with _kalshi_stream_lock:
        if _kalshi_stream is not None:
            return _kalshi_stream

        if not _env_bool("MERID_CFB_RTI_ADAPTER"):
            return None

        if _rti_source() not in ("kalshi_ws", "both"):
            return None

        # Never start a real WebSocket during pytest unless the source is
        # explicitly set.  This protects test suites that set MERID_ENV=prod
        # from accidentally connecting to a live Kalshi socket.
        if "PYTEST_CURRENT_TEST" in os.environ:
            source = os.environ.get("MERID_CFB_RTI_SOURCE", "").strip().lower()
            if source not in ("kalshi_ws", "both"):
                logger.debug("[CF-RTI-ADAPTER] skipping stream under pytest")
                return None

        try:
            from merid.data.kalshi_cf_rti_ws import KalshiCfRtiStream, index_id_to_asset
        except Exception as exc:
            logger.error("[CF-RTI-ADAPTER] Kalshi stream import failed: %s", exc)
            return None

        def _on_frame(frame):
            asset = index_id_to_asset(frame.index_id)
            if not asset:
                logger.debug(
                    "[CF-RTI-ADAPTER] dropping unknown index_id=%s", frame.index_id
                )
                return

            # For the WebSocket path the authoritative symbol is the Kalshi
            # index ID returned by the server (e.g. ETHUSD_RTI).  The legacy
            # _ASSET_TO_CFB_SYMBOL map is kept for the optional direct REST path.
            cfb_symbol = frame.index_id
            obs = _parse_response_payload(asset, cfb_symbol, frame.data)
            if obs is None:
                logger.debug(
                    "[CF-RTI-ADAPTER] stream frame parse failed asset=%s index_id=%s",
                    asset,
                    frame.index_id,
                )
                return

            # Validate immediately so the cache and logs separate eligible from
            # observability-only frames.  A missing/invalid source timestamp is
            # logged as a reject and not allowed to drive trading.
            validated = _validate_observation(asset, cfb_symbol, obs)
            if validated is None:
                reason = _state.last_failure_reason_by_asset.get(asset, "unknown")
                logger.warning(
                    "[CF-RTI-ADAPTER] stream_observation_rejected "
                    "asset=%s cfb_symbol=%s value=%s retained_digits=%s market_digits=%s "
                    "timestamp_quality=%s execution_eligible=%s reason=%s",
                    asset,
                    cfb_symbol,
                    _format_price(asset, obs.value_decimal),
                    obs.retained_digits,
                    obs.market_settlement_digits,
                    obs.timestamp_quality,
                    obs.execution_eligible,
                    reason,
                )
                return

            _state.last_observation_by_asset[asset] = validated
            _state.last_source_ts_ms_by_asset[asset] = validated.source_ts_ms
            _state.consecutive_failures_by_asset[asset] = 0
            _state.last_failure_reason_by_asset[asset] = ""
            logger.info(
                "[CF-RTI-ADAPTER] stream_observation_accepted "
                "asset=%s cfb_symbol=%s value=%s retained_digits=%s market_digits=%s "
                "source_ts_ms=%s observed_ts_ms=%s age_ms=%s timestamp_quality=%s execution_eligible=%s",
                asset,
                cfb_symbol,
                _format_price(asset, validated.value_decimal),
                validated.retained_digits,
                validated.market_settlement_digits,
                validated.source_ts_ms,
                validated.observed_ts_ms,
                validated.age_ms,
                validated.timestamp_quality,
                validated.execution_eligible,
            )

        _kalshi_stream = KalshiCfRtiStream(
            on_frame=_on_frame,
            on_reconnect=reset_state,
            on_disconnect=reset_state,
        )
        try:
            _kalshi_stream.start()
            logger.info("[CF-RTI-ADAPTER] Kalshi cfbenchmarks_value stream started")
        except Exception as exc:
            logger.error("[CF-RTI-ADAPTER] Kalshi stream start failed: %s", exc)
            _kalshi_stream = None
            return None

        return _kalshi_stream


def start_kalshi_rti_stream() -> Optional[Any]:
    """Explicitly start the Kalshi CF-RTI WebSocket stream.

    Called from ``web.main_15m_lean`` lifespan; also triggered lazily by
    ``get_live_rti`` when the adapter is enabled.
    """
    return _ensure_kalshi_stream()


def stop_kalshi_rti_stream() -> None:
    """Stop the Kalshi CF-RTI WebSocket stream."""
    global _kalshi_stream
    with _kalshi_stream_lock:
        stream = _kalshi_stream
        _kalshi_stream = None
    if stream is not None:
        stream.stop()


def _now_ms() -> int:
    """Return the current wall-clock time in whole milliseconds.

    Uses ``time.time_ns()`` to avoid floating-point precision loss from
    ``time.time() * 1000`` and to keep the millisecond integer exact.
    """
    return time.time_ns() // 1_000_000


def _now_mono_ns() -> int:
    """Return the current monotonic time in whole nanoseconds.

    Monotonic time is the authoritative clock for internal latency / freshness
    because it never jumps.  Use it to compute how long an observation has been
    in the adapter cache.
    """
    return time.monotonic_ns()


# Reasonable epoch-ms window: 2001-01-01 to 2099-12-31.
_MIN_SOURCE_TS_MS = 978_307_200_000
_MAX_SOURCE_TS_MS = 4_102_444_800_000


def _is_valid_epoch_ms(value: Any) -> bool:
    """Return True if ``value`` is a plausible millisecond Unix timestamp."""
    if not isinstance(value, int) or isinstance(value, bool):
        return False
    return _MIN_SOURCE_TS_MS <= value <= _MAX_SOURCE_TS_MS


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _asset_symbol_valid(asset: str) -> Optional[str]:
    """Return the canonical CF Benchmarks symbol for ``asset`` or ``None``."""
    normalized = (asset or "").upper().strip()
    if not normalized:
        return None
    return _ASSET_TO_CFB_SYMBOL.get(normalized)


def _parse_response_payload(asset: str, cfb_symbol: str, data: Dict[str, Any]) -> Optional[CfbRtiObservation]:
    """Parse a CF Benchmarks API response into a typed observation.

    Accepts several documented and legacy field shapes without being lossy.
    """
    value_decimal: Optional[Decimal] = None
    raw_value: Optional[str] = None
    for field in ("value", "price", "last", "index_value", "rti"):
        if field in data and data[field] is not None:
            candidate = data[field]
            parsed = parse_price(candidate)
            if parsed is not None and parsed.is_finite() and parsed > 0:
                value_decimal = parsed
                raw_value = str(candidate) if isinstance(candidate, (str, Decimal, int, float)) else str(parsed)
                break

    if value_decimal is None:
        logger.warning(
            "[CF-RTI-ADAPTER] cfb_rti_invalid_value asset=%s cfb_symbol=%s value=%s",
            asset, cfb_symbol, data.get("value", data)
        )
        return None

    source_ts_ms = None
    timestamp_quality = "source"
    for field in ("ts", "timestamp", "time", "source_ts_ms", "published_at"):
        if field in data and data[field] is not None:
            candidate = data[field]
            parsed = _parse_timestamp(candidate)
            if parsed is not None:
                if _is_valid_epoch_ms(parsed):
                    source_ts_ms = parsed
                    break
                timestamp_quality = "invalid"
            else:
                timestamp_quality = "invalid"
    if source_ts_ms is None and timestamp_quality == "source":
        timestamp_quality = "missing"
        logger.warning(
            "[CF-RTI-ADAPTER] cfb_rti_timestamp_missing asset=%s cfb_symbol=%s "
            "using_observed_time_for_logging_only",
            asset, cfb_symbol,
        )

    sequence = None
    for field in ("sequence", "seq", "id"):
        if field in data and data[field] is not None:
            try:
                sequence = int(data[field])
                break
            except (TypeError, ValueError):
                pass

    cfb_60s_average_decimal: Optional[Decimal] = None
    cfb_60s_average_raw: Optional[str] = None
    for field in ("average_60s", "60s_average", "minute_average", "trailing_60s"):
        if field in data and data[field] is not None:
            candidate = data[field]
            parsed = parse_price(candidate)
            if parsed is not None and parsed.is_finite() and parsed > 0:
                cfb_60s_average_decimal = parsed
                cfb_60s_average_raw = str(candidate) if isinstance(candidate, (str, Decimal, int, float)) else str(parsed)
                break

    observed_wall_ms = _now_ms()
    observed_mono_ns = _now_mono_ns()
    execution_eligible = source_ts_ms is not None
    market_digits = get_asset_settlement_digits(asset)

    return CfbRtiObservation(
        asset=asset,
        cfb_symbol=cfb_symbol,
        value=float(value_decimal),
        value_decimal=value_decimal,
        raw_value=raw_value,
        retained_digits=retained_decimal_places(value_decimal),
        market_settlement_digits=market_digits,
        source_ts_ms=source_ts_ms,
        observed_ts_ms=observed_wall_ms,
        observed_ts_mono_ns=observed_mono_ns,
        sequence=sequence,
        source="cf_benchmarks",
        settlement_reference="cfb_rti_live",
        cfb_60s_average=float(cfb_60s_average_decimal) if cfb_60s_average_decimal is not None else None,
        cfb_60s_average_decimal=cfb_60s_average_decimal,
        timestamp_quality=timestamp_quality,
        execution_eligible=execution_eligible,
        price_source_health="healthy" if execution_eligible else "suspect",
    )


def _parse_timestamp(candidate: Any) -> Optional[int]:
    """Best-effort parse of a timestamp field into source epoch milliseconds."""
    if isinstance(candidate, Decimal):
        try:
            if candidate > Decimal("1e12"):
                return int(candidate)
            return int(candidate * Decimal("1000"))
        except Exception:
            return None
    if isinstance(candidate, (int, float)):
        if not math.isfinite(candidate):
            return None
        if candidate > 1e12:  # already milliseconds
            return int(candidate)
        return int(candidate * 1000)

    if isinstance(candidate, str):
        candidate = candidate.strip()
        # ISO 8601
        if "T" in candidate or "Z" in candidate:
            try:
                dt = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return int(dt.timestamp() * 1000)
            except ValueError:
                pass
        # Numeric milliseconds / seconds
        try:
            value = float(candidate)
            if value > 1e12:
                return int(value)
            return int(value * 1000)
        except ValueError:
            pass

    if isinstance(candidate, datetime):
        if candidate.tzinfo is None:
            candidate = candidate.replace(tzinfo=timezone.utc)
        return int(candidate.timestamp() * 1000)

    return None


def _rti_source() -> str:
    """Return the active RTI source strategy.

    - ``kalshi_ws``: use the authenticated Kalshi ``cfbenchmarks_value`` WebSocket.
    - ``direct``: use a direct CF Benchmarks REST API key.
    - ``both``: prefer Kalshi WebSocket, fall back to direct REST.
    """
    source = os.environ.get("MERID_CFB_RTI_SOURCE", "").strip().lower()
    if source in ("kalshi_ws", "direct", "both"):
        return source
    # When the adapter is enabled and no explicit source is set, prefer the
    # authenticated Kalshi WebSocket (``.env.shadow`` sets this explicitly).
    # In test/dev with no source, fall back to direct REST so unit tests that
    # mock httpx can run without connecting to a live Kalshi WebSocket.
    if _env_bool("MERID_CFB_RTI_ADAPTER", False):
        if os.environ.get("MERID_ENV", "").lower() in ("testing", "test", "dev", "development"):
            return "direct"
        return "kalshi_ws"
    return "direct"


def _fetch_raw(asset: str, cfb_symbol: str) -> Optional[Dict[str, Any]]:
    """Synchronous HTTP fetch from CF Benchmarks RTI endpoint."""
    if is_replay_active():
        record = get_replay_dispatcher().get(SOURCE_CFB_RTI_REST)
        return replay_json_payload(record)

    if not _env_bool("MERID_CFB_RTI_ADAPTER", False):
        logger.debug(
            "[CF-RTI-ADAPTER] cfb_rti_adapter_not_live asset=%s (MERID_CFB_RTI_ADAPTER not live)",
            asset,
        )
        return None

    base_url = os.environ.get("MERID_CFB_RTI_BASE_URL", _CFB_BASE_URL)
    api_key = os.environ.get("CFB_API_KEY") or os.environ.get("MERID_CFB_RTI_API_KEY")

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    url = f"{base_url}{_CFB_RTI_ENDPOINT}/{cfb_symbol}"
    try:
        with httpx.Client(timeout=_REQUEST_TIMEOUT, headers=headers) as client:
            resp = client.get(url)
            record_ingress(
                SOURCE_CFB_RTI_REST,
                resp.content,
                metadata={
                    "asset": asset,
                    "cfb_symbol": cfb_symbol,
                    "url": url,
                    "status_code": resp.status_code,
                },
            )
    except httpx.TimeoutException:
        logger.warning(
            "[CF-RTI-ADAPTER] cfb_rti_unavailable asset=%s cfb_symbol=%s reason=timeout", asset, cfb_symbol
        )
        return None
    except Exception as exc:
        logger.warning(
            "[CF-RTI-ADAPTER] cfb_rti_unavailable asset=%s cfb_symbol=%s reason=%s", asset, cfb_symbol, exc
        )
        return None

    if resp.status_code == 401:
        logger.warning(
            "[CF-RTI-ADAPTER] cfb_rti_unavailable asset=%s cfb_symbol=%s reason=auth_required", asset, cfb_symbol
        )
        return None
    if resp.status_code == 404:
        logger.warning(
            "[CF-RTI-ADAPTER] cfb_rti_unavailable asset=%s cfb_symbol=%s reason=index_not_found", asset, cfb_symbol
        )
        return None
    if resp.status_code != 200:
        logger.warning(
            "[CF-RTI-ADAPTER] cfb_rti_unavailable asset=%s cfb_symbol=%s status=%s", asset, cfb_symbol, resp.status_code
        )
        return None

    try:
        # Preserve original decimal precision; do not let the HTTP library's
        # default float parser silently round 7-decimal DOGE values.
        data = json.loads(resp.text, parse_float=Decimal)
    except Exception as exc:
        logger.warning(
            "[CF-RTI-ADAPTER] cfb_rti_unavailable asset=%s cfb_symbol=%s reason=invalid_json exc=%s", asset, cfb_symbol, exc
        )
        return None

    if data.get("source") and data.get("source") != "cf_benchmarks":
        _state.last_failure_reason_by_asset[asset] = "source_not_cf_benchmarks"
        _state.consecutive_failures_by_asset[asset] = _state.consecutive_failures_by_asset.get(asset, 0) + 1
        logger.error(
            "[CF-RTI-ADAPTER] cfb_rti_unavailable asset=%s cfb_symbol=%s "
            "reason=source_not_cf_benchmarks source=%s",
            asset, cfb_symbol, data.get("source")
        )
        return None

    return data


def _validate_observation(
    asset: str, cfb_symbol: str, obs: CfbRtiObservation
) -> Optional[CfbRtiObservation]:
    """Apply all fail-closed health gates.  Returns ``None`` and logs the reason on failure."""
    now_ms = _now_ms()
    now_mono_ns = _now_mono_ns()

    # Source identity
    if obs.source != "cf_benchmarks":
        _state.last_failure_reason_by_asset[asset] = "source_not_cf_benchmarks"
        logger.error(
            "[CF-RTI-ADAPTER] cfb_rti_unavailable asset=%s reason=source_not_cf_benchmarks source=%s",
            asset, obs.source
        )
        return None

    # Asset / symbol mapping.  The authoritative symbol may be a canonical CF
    # Benchmarks ID (e.g. ETH_RTI) or the Kalshi-specific ID (e.g. ETHUSD_RTI).
    # Either is valid as long as it maps back to the requested asset.
    if _asset_symbol_valid(asset) is None:
        _state.last_failure_reason_by_asset[asset] = "cfb_rti_symbol_mismatch"
        logger.error(
            "[CF-RTI-ADAPTER] cfb_rti_unavailable asset=%s reason=cfb_rti_symbol_mismatch unknown_asset",
            asset
        )
        return None
    if obs.asset != asset or index_id_to_asset(obs.cfb_symbol) != asset:
        _state.last_failure_reason_by_asset[asset] = "cfb_rti_symbol_mismatch"
        logger.error(
            "[CF-RTI-ADAPTER] cfb_rti_unavailable asset=%s reason=cfb_rti_symbol_mismatch "
            "observed_asset=%s observed_cfb_symbol=%s", asset, obs.asset, obs.cfb_symbol
        )
        return None

    # Value sanity (canonical Decimal; fallback to float for legacy consumers)
    price = obs.value_decimal if obs.value_decimal is not None else parse_price(obs.value)
    if price is None or not price.is_finite() or price <= 0:
        _state.last_failure_reason_by_asset[asset] = "cfb_rti_invalid_value"
        logger.error(
            "[CF-RTI-ADAPTER] cfb_rti_unavailable asset=%s cfb_symbol=%s reason=cfb_rti_invalid_value value=%s",
            asset, cfb_symbol, obs.value
        )
        return None

    # Timestamp must be valid before it can be execution-eligible.  A missing or
    # malformed source timestamp is an observability-only event; it is never
    # allowed to back a trading signal.
    if not obs.execution_eligible or obs.source_ts_ms is None:
        reason = f"cfb_rti_{obs.timestamp_quality}_timestamp"
        _state.last_failure_reason_by_asset[asset] = reason
        logger.error(
            "[CF-RTI-ADAPTER] cfb_rti_unavailable asset=%s cfb_symbol=%s reason=%s "
            "timestamp_quality=%s execution_eligible=%s",
            asset, cfb_symbol, reason, obs.timestamp_quality, obs.execution_eligible
        )
        return None

    # Freshness.  ``source_ts_ms`` is an upstream wall-clock epoch in milliseconds,
    # not a duration, so compare it to the local wall clock (``now_ms``).  Also
    # use monotonic time for the local latency because wall-clock time can jump.
    wall_age_ms = now_ms - obs.source_ts_ms
    if wall_age_ms < -5_000:
        # Source clock is more than 5s ahead of ours.  Warn but do not reject;
        # the data is still fresh from its own perspective.
        logger.warning(
            "[CF-RTI-ADAPTER] source_timestamp_in_future asset=%s cfb_symbol=%s "
            "source_ts_ms=%d now_ms=%d skew_ms=%d",
            asset, cfb_symbol, obs.source_ts_ms, now_ms, -wall_age_ms,
        )
    if wall_age_ms > _MAX_CFB_RTI_AGE_MS:
        _state.last_failure_reason_by_asset[asset] = "cfb_rti_stale"
        logger.error(
            "[CF-RTI-ADAPTER] cfb_rti_unavailable asset=%s cfb_symbol=%s reason=cfb_rti_stale "
            "wall_age_ms=%s max_age_ms=%s", asset, cfb_symbol, wall_age_ms, _MAX_CFB_RTI_AGE_MS
        )
        return None

    if obs.observed_ts_mono_ns is not None:
        mono_age_ms = (now_mono_ns - obs.observed_ts_mono_ns) // 1_000_000
        if mono_age_ms > _MAX_CFB_RTI_AGE_MS:
            _state.last_failure_reason_by_asset[asset] = "cfb_rti_stale"
            logger.error(
                "[CF-RTI-ADAPTER] cfb_rti_unavailable asset=%s cfb_symbol=%s reason=cfb_rti_stale "
                "mono_age_ms=%s max_age_ms=%s", asset, cfb_symbol, mono_age_ms, _MAX_CFB_RTI_AGE_MS
            )
            return None

    # Stream liveness: if the previous observation for this asset was more recent
    # than the current one, the stream is going backwards or has stalled.
    last_source_ts_ms = _state.last_source_ts_ms_by_asset.get(asset, 0)
    if obs.source_ts_ms < last_source_ts_ms:
        _state.last_failure_reason_by_asset[asset] = "cfb_rti_nonmonotonic"
        logger.error(
            "[CF-RTI-ADAPTER] cfb_rti_unavailable asset=%s cfb_symbol=%s reason=cfb_rti_nonmonotonic "
            "source_ts_ms=%s last=%s", asset, cfb_symbol, obs.source_ts_ms, last_source_ts_ms
        )
        return None

    # Ordering: sequence numbers must not go backward.
    last_success = _state.last_observation_by_asset.get(asset)
    if obs.sequence is not None and last_success is not None and last_success.sequence is not None:
        if obs.sequence < last_success.sequence:
            _state.last_failure_reason_by_asset[asset] = "cfb_rti_nonmonotonic"
            logger.error(
                "[CF-RTI-ADAPTER] cfb_rti_unavailable asset=%s cfb_symbol=%s reason=cfb_rti_nonmonotonic "
                "sequence=%s last=%s", asset, cfb_symbol, obs.sequence, last_success.sequence
            )
            return None

    return obs


def get_live_rti(asset: str) -> Optional[CfbRtiObservation]:
    """Return the latest valid CF Benchmarks RTI observation for ``asset``.

    Returns ``None`` and logs a precise rejection reason if any health gate
    fails.  Never returns a public-spot fallback.
    """
    cfb_symbol = _asset_symbol_valid(asset)
    if cfb_symbol is None:
        _state.consecutive_failures_by_asset[asset] = _state.consecutive_failures_by_asset.get(asset, 0) + 1
        _state.last_failure_reason_by_asset[asset] = "cfb_rti_symbol_mismatch"
        logger.error(
            "[CF-RTI-ADAPTER] cfb_rti_unavailable asset=%s reason=cfb_rti_symbol_mismatch", asset
        )
        return None

    source = _rti_source()

    cached = _state.last_observation_by_asset.get(asset)

    # Primary: authenticated Kalshi cfbenchmarks_value WebSocket stream.
    if source in ("kalshi_ws", "both"):
        _ensure_kalshi_stream()
        if cached is not None:
            obs = _validate_observation(asset, cfb_symbol, cached)
            if obs is not None:
                _state.last_observation_by_asset[asset] = obs
                _state.last_source_ts_ms_by_asset[asset] = obs.source_ts_ms
                _state.consecutive_failures_by_asset[asset] = 0
                _state.last_failure_reason_by_asset[asset] = ""
                logger.info(
                    "[CF-RTI-ADAPTER] cfb_rti_live asset=%s cfb_symbol=%s value=%s retained_digits=%s market_digits=%s source_ts_ms=%s age_ms=%s source=kalshi_ws",
                    asset, obs.cfb_symbol, _format_price(asset, obs.value_decimal),
                    obs.retained_digits, obs.market_settlement_digits,
                    obs.source_ts_ms, obs.age_ms
                )
                return obs

    # Fallback: direct CF Benchmarks REST key.
    if source in ("direct", "both"):
        data = _fetch_raw(asset, cfb_symbol)
        if data is not None:
            obs = _parse_response_payload(asset, cfb_symbol, data)
            if obs is not None:
                obs = _validate_observation(asset, cfb_symbol, obs)
                if obs is not None:
                    _state.last_observation_by_asset[asset] = obs
                    _state.last_source_ts_ms_by_asset[asset] = obs.source_ts_ms
                    _state.consecutive_failures_by_asset[asset] = 0
                    _state.last_failure_reason_by_asset[asset] = ""
                    logger.info(
                        "[CF-RTI-ADAPTER] cfb_rti_live asset=%s cfb_symbol=%s value=%s retained_digits=%s market_digits=%s source_ts_ms=%s age_ms=%s source=direct_cfb",
                        asset, obs.cfb_symbol, _format_price(asset, obs.value_decimal),
                        obs.retained_digits, obs.market_settlement_digits,
                        obs.source_ts_ms, obs.age_ms
                    )
                    return obs

    _state.consecutive_failures_by_asset[asset] = _state.consecutive_failures_by_asset.get(asset, 0) + 1
    if not _state.last_failure_reason_by_asset.get(asset):
        _state.last_failure_reason_by_asset[asset] = "cfb_rti_unavailable"
    return None


def get_last_rejection_reason(asset: str) -> str:
    return _state.last_failure_reason_by_asset.get(asset, "")


def get_last_observation(asset: str) -> Optional[CfbRtiObservation]:
    return _state.last_observation_by_asset.get(asset)


def reset_state() -> None:
    """Reset adapter state.  Intended for tests only."""
    _state.last_observation_by_asset.clear()
    _state.last_source_ts_ms_by_asset.clear()
    _state.last_failure_ts_ms = 0
    _state.last_failure_reason_by_asset.clear()
    _state.consecutive_failures_by_asset.clear()


def final_minute_cutoff_seconds() -> float:
    return _FINAL_MINUTE_CUTOFF_S

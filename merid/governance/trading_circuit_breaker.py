"""Trading circuit breaker.

A fail-closed, process-wide emergency halt.  Once triggered, all order
submission is blocked unless the intent is explicitly tagged and authorized as
a manual emergency close.

HTTP/backfill fills never trip the breaker unless they are provably newer than
the persisted per-source watermark.  WebSocket fills are always live and are
allowed to trip the breaker.  A short pending-intent lookup is performed before
halting to avoid racing persistence.
"""

import json
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from utils.logger import get_logger

logger = get_logger("trading_circuit_breaker")

# HTTP fills are operationally live only if their exchange timestamp is newer
# than the persisted watermark from the last successful reconciliation.
HTTP_FILL_WATERMARK_PATH = Path("data") / "trading_circuit_breaker_http_watermark.json"

# Allow grace for an unmatched fill to be matched against a recently submitted
# but not-yet-persisted intent before the breaker trips.
PENDING_INTENT_LOOKUP_SECONDS = float(
    os.environ.get("MERID_PENDING_INTENT_LOOKUP_SECONDS", "30.0")
)

# Observe-only mode logs the halt event but does not actually stop trading.
# Use this when first deploying the breaker to validate watermarks.
OBSERVE_ONLY = os.environ.get("MERID_CIRCUIT_BREAKER_OBSERVE_ONLY", "").strip() == "1"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_watermark() -> datetime:
    try:
        if HTTP_FILL_WATERMARK_PATH.exists():
            with open(HTTP_FILL_WATERMARK_PATH, "r", encoding="utf-8") as f:
                payload = json.load(f)
            ts = payload.get("watermark")
            if ts:
                return datetime.fromisoformat(ts)
    except Exception as exc:
        logger.warning("[TRADING-CIRCUIT-BREAKER] Failed to load HTTP watermark: %s", exc)
    # Without a persisted watermark, treat the process start as the initial
    # cursor.  All backfill fills are expected to be older.
    return _now()


def _save_watermark(watermark: datetime) -> None:
    try:
        HTTP_FILL_WATERMARK_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(HTTP_FILL_WATERMARK_PATH, "w", encoding="utf-8") as f:
            json.dump({"watermark": watermark.isoformat()}, f)
    except Exception as exc:
        logger.warning("[TRADING-CIRCUIT-BREAKER] Failed to persist HTTP watermark: %s", exc)


@dataclass
class HaltRecord:
    """Immutable record of a trading halt."""

    reason: str
    timestamp: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


class TradingCircuitBreaker:
    """Process-wide circuit breaker for trading safety events.

    Usage:
        breaker = TradingCircuitBreaker()
        if not breaker.is_order_allowed(intent):
            return OrderResult(status="rejected", reason="trading_halted")
    """

    _instance: Optional["TradingCircuitBreaker"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls) -> "TradingCircuitBreaker":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._reset()
        return cls._instance

    def _reset(self) -> None:
        self._halted: bool = False
        self._halt_record: Optional[HaltRecord] = None
        self._autonomous_entries_enabled: bool = True
        self._autonomous_exits_enabled: bool = True
        self._manual_emergency_close_enabled: bool = True

    def reset(self) -> None:
        """Process-level reset for tests or a supervised recovery flow.

        Do not call in production without an explicit recovery procedure.
        """
        with self._lock:
            self._reset()
            self._http_fill_watermark = _now()
            self._http_seen_fill_ids: Set[str] = set()
            self._http_watermark_initialized = True

    def _initialize_watermark(self) -> None:
        if not getattr(self, "_http_watermark_initialized", False):
            self._http_fill_watermark = _load_watermark()
            self._http_seen_fill_ids: Set[str] = set()
            self._process_started_at = _now()
            self._http_watermark_initialized = True

    def halt(
        self,
        reason: str,
        *,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> HaltRecord:
        """Fail-closed emergency halt.  Disables all autonomous trading."""
        if os.environ.get("MERID_CIRCUIT_BREAKER_DISABLED", "").strip() == "1":
            logger.warning(
                "[TRADING-CIRCUIT-BREAKER] HALT requested but disabled by env | reason=%s",
                reason,
            )
            return HaltRecord(
                reason="disabled_by_env",
                timestamp=_now(),
                metadata=metadata or {},
            )

        record = HaltRecord(
            reason=reason,
            timestamp=_now(),
            metadata=metadata or {},
        )

        if OBSERVE_ONLY:
            logger.critical(
                "[TRADING-CIRCUIT-BREAKER] OBSERVE-ONLY halt would trigger | reason=%s | metadata=%s",
                reason,
                record.metadata,
            )
            return record

        with self._lock:
            self._halted = True
            self._halt_record = record
            self._autonomous_entries_enabled = False
            self._autonomous_exits_enabled = False

        logger.critical(
            "[TRADING-CIRCUIT-BREAKER] HALT triggered | reason=%s | metadata=%s",
            reason,
            record.metadata,
        )
        return record

    def resume(self) -> None:
        """Resume trading.  This must be called deliberately by an operator."""
        with self._lock:
            self._reset()
        logger.critical("[TRADING-CIRCUIT-BREAKER] RESUMED")

    async def admin_release(
        self,
        operator: str,
        run_id: str,
        approval_token: str,
        *,
        force: bool = False,
        trigger_fill_timestamp: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Release the breaker after an administrative safety check.

        This is the ONLY supported path to clear a trading halt.  Calling
        ``resume()`` directly from application code is prohibited.  The operator
        must supply a fresh ``run_id`` and a valid release token.  By default
        the method verifies:

        1. No open Kalshi positions (position cache + exchange balance).
        2. No untracked open orders (``audit_open_orders`` dry-run).
        3. No unresolved ``UNMATCHED_FILL`` events in the last 30 minutes.
        4. The persisted HTTP watermark has advanced past the triggering fill.

        Pass ``force=True`` to skip the safety checks in an emergency; the audit
        record will still be written and the halt will be released.
        """
        checks: List[Dict[str, Any]] = []
        released = False

        # ---- Operator and token validation ----
        if not operator or not isinstance(operator, str):
            checks.append({"name": "operator", "ok": False, "reason": "operator must be a non-empty string"})
            return _release_result(False, checks, None)

        if not run_id or not isinstance(run_id, str):
            checks.append({"name": "run_id", "ok": False, "reason": "run_id must be a non-empty string"})
            return _release_result(False, checks, None)

        release_token = os.environ.get("MERID_BREAKER_RELEASE_TOKEN") or os.environ.get("MERID_MANUAL_EMERGENCY_TOKEN")
        if not release_token:
            checks.append({"name": "release_token_configured", "ok": False, "reason": "MERID_BREAKER_RELEASE_TOKEN or MERID_MANUAL_EMERGENCY_TOKEN must be set"})
            return _release_result(False, checks, None)

        token_ok = _secure_compare(approval_token, release_token)
        checks.append({"name": "approval_token", "ok": token_ok, "reason": None if token_ok else "approval token mismatch"})
        if not token_ok:
            return _release_result(False, checks, None)

        # ---- Safety checks (skip if force=True) ----
        if not force:
            # 1. No open positions
            try:
                from merid.event_venues.kalshi.position_cache import get_position_cache
                position_cache = get_position_cache()
                all_positions = position_cache.get_all_positions(validate_freshness=False)
                open_positions = {k: v for k, v in all_positions.items() if getattr(v, "contracts", 0) != 0}
                positions_ok = len(open_positions) == 0
                checks.append({
                    "name": "open_positions",
                    "ok": positions_ok,
                    "reason": None if positions_ok else f"{len(open_positions)} open position(s) remain",
                    "count": len(open_positions),
                })
            except Exception as exc:
                checks.append({"name": "open_positions", "ok": False, "reason": f"failed to check positions: {exc}"})

            # 2. No untracked open orders
            try:
                from merid.event_venues.kalshi.kalshi_risk import audit_open_orders
                audit = await audit_open_orders(cancel_untracked=False)
                open_count = audit.get("open_orders_count", 0)
                untracked_count = len(audit.get("untracked_order_ids", []))
                orders_ok = open_count == 0 and untracked_count == 0
                checks.append({
                    "name": "open_orders",
                    "ok": orders_ok,
                    "reason": None if orders_ok else f"open={open_count} untracked={untracked_count}",
                    "open_count": open_count,
                    "untracked_count": untracked_count,
                })
            except Exception as exc:
                checks.append({"name": "open_orders", "ok": False, "reason": f"failed to audit open orders: {exc}"})

            # 3. No unresolved UNMATCHED_FILL in last 30 minutes
            try:
                from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
                ledger = get_fills_ledger()
                since = _now() - timedelta(minutes=30)
                recent_fills = ledger.get_fills(since=since)
                unmatched = [f for f in recent_fills if getattr(f, "unmatched", False)]
                fills_ok = len(unmatched) == 0
                checks.append({
                    "name": "unmatched_fills_30m",
                    "ok": fills_ok,
                    "reason": None if fills_ok else f"{len(unmatched)} unmatched fill(s) in last 30 minutes",
                    "count": len(unmatched),
                })
            except Exception as exc:
                checks.append({"name": "unmatched_fills_30m", "ok": False, "reason": f"failed to check fills: {exc}"})

            # 4. Watermark advanced past trigger fill
            try:
                current_watermark = _load_watermark()
                checks.append({
                    "name": "watermark",
                    "ok": True,
                    "reason": None,
                    "value": current_watermark.isoformat(),
                })
                if trigger_fill_timestamp:
                    trigger_dt = datetime.fromisoformat(trigger_fill_timestamp)
                    watermark_ok = current_watermark >= trigger_dt
                    checks.append({
                        "name": "watermark_advanced",
                        "ok": watermark_ok,
                        "reason": None if watermark_ok else f"watermark {current_watermark} not past {trigger_dt}",
                    })
            except Exception as exc:
                checks.append({"name": "watermark", "ok": False, "reason": f"failed to load watermark: {exc}"})

            # Any failed check blocks release
            failed = [c for c in checks if not c.get("ok", False)]
            if failed:
                logger.critical(
                    "[TRADING-CIRCUIT-BREAKER] admin_release blocked: operator=%s run_id=%s failed_checks=%s",
                    operator, run_id, failed,
                )
                return _release_result(False, checks, None)

        # ---- Durable audit record ----
        audit_payload = {
            "event": "BREAKER_RELEASE",
            "operator": operator,
            "run_id": run_id,
            "force": force,
            "trigger_fill_timestamp": trigger_fill_timestamp,
            "checks": checks,
            "previous_halt_reason": self.reason,
            "previous_halt_info": self.halt_info,
        }
        try:
            from core.risk_audit_chain import get_risk_audit_chain
            chain = get_risk_audit_chain()
            record = chain.log_event("risk.trading_halt_released", audit_payload)
            audit_payload["audit_sequence"] = record.sequence
            audit_payload["audit_hash"] = record.event_hash
        except Exception as exc:
            logger.error("[TRADING-CIRCUIT-BREAKER] Failed to write release audit record: %s", exc)
            # Continue to release; the operational log still records the action.

        # ---- Release ----
        self.resume()
        released = True

        logger.critical(
            "[TRADING-CIRCUIT-BREAKER] ADMIN_RELEASE operator=%s run_id=%s released=%s",
            operator, run_id, released,
        )
        return _release_result(True, checks, audit_payload)

    @property
    def halted(self) -> bool:
        with self._lock:
            return self._halted

    @property
    def reason(self) -> Optional[str]:
        with self._lock:
            return self._halt_record.reason if self._halt_record else None

    @property
    def halt_info(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            if not self._halt_record:
                return None
            return {
                "halted": self._halted,
                "reason": self._halt_record.reason,
                "timestamp": self._halt_record.timestamp.isoformat(),
                "metadata": self._halt_record.metadata,
            }

    def is_order_allowed(self, intent: Any) -> bool:
        """Return True if the order may be submitted.

        After a halt, only a manual emergency close with a valid approval token
        is allowed.  Autonomous paths cannot bypass by setting a boolean.
        """
        with self._lock:
            if not self._halted:
                return True

        if not getattr(intent, "is_manual_emergency_close", False):
            return False

        token = getattr(intent, "approval_token", None)
        if not token:
            logger.critical(
                "[TRADING-CIRCUIT-BREAKER] Manual close rejected: no approval_token"
            )
            return False

        if not _validate_approval_token(token, intent):
            logger.critical(
                "[TRADING-CIRCUIT-BREAKER] Manual close rejected: invalid approval_token"
            )
            return False

        return self._manual_emergency_close_enabled

    def is_entry_allowed(self) -> bool:
        with self._lock:
            return not self._halted and self._autonomous_entries_enabled

    def is_autonomous_exit_allowed(self) -> bool:
        with self._lock:
            return not self._halted and self._autonomous_exits_enabled

    def require_live_fill_identity(
        self,
        fill: Any,
        *,
        intent_lookup: Optional[Any] = None,
    ) -> None:
        """Halt trading if a live, unmatched fill cannot be linked to an intent.

        ``intent_lookup`` may be any object with an ``async lookup`` method or a
        synchronous ``lookup`` method accepting ``client_order_id``, ``order_id``,
        and ``lookback_seconds``.
        """
        self._initialize_watermark()

        if not self._is_live_fill(fill):
            logger.warning(
                "[TRADING-CIRCUIT-BREAKER] Historical or duplicate unmatched fill ignored "
                "for breaker purposes: fill_id=%s order_id=%s ticker=%s",
                getattr(fill, "fill_id", None),
                getattr(fill, "order_id", None),
                getattr(fill, "market_ticker", None),
            )
            return

        if self._try_match_pending_intent(fill, intent_lookup):
            logger.info(
                "[TRADING-CIRCUIT-BREAKER] Unmatched live fill matched to pending intent "
                "after grace lookup: fill_id=%s",
                getattr(fill, "fill_id", None),
            )
            return

        self.halt(
            reason="unmatched_live_exchange_fill",
            metadata={
                "fill_id": getattr(fill, "fill_id", None),
                "order_id": getattr(fill, "order_id", None),
                "client_order_id": getattr(fill, "client_order_id", None),
                "ticker": getattr(fill, "market_ticker", None),
                "created_time": _fmt_ts(getattr(fill, "created_time", None)),
                "ingested_at": _fmt_ts(getattr(fill, "ingested_at", None)),
                "ingestion_source": getattr(fill, "ingestion_source", None),
            },
        )

    def _is_live_fill(self, fill: Any) -> bool:
        self._initialize_watermark()

        source = getattr(fill, "ingestion_source", "")
        fill_id = str(getattr(fill, "fill_id", ""))

        # WebSocket fills are authoritative real-time events.
        if source == "websocket":
            return True

        # HTTP fills are only live if they are newer than the persisted watermark
        # and have not been seen before in this source.
        created = getattr(fill, "created_time", None)
        if not created or not isinstance(created, datetime):
            return False

        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)

        # Advance watermark as we observe newer fills; the first pass may include
        # backfill, but after the watermark is updated only truly new fills pass.
        if fill_id not in self._http_seen_fill_ids:
            self._http_seen_fill_ids.add(fill_id)
            if created > self._http_fill_watermark:
                self._http_fill_watermark = created
                _save_watermark(created)
                return True

        return False

    def _try_match_pending_intent(
        self,
        fill: Any,
        intent_lookup: Optional[Any],
    ) -> bool:
        """Look for a recently submitted but not-yet-persisted intent.

        Returns True if an intent can be found for the fill's identifiers.
        """
        if intent_lookup is None:
            return False

        client_order_id = getattr(fill, "client_order_id", None)
        order_id = getattr(fill, "order_id", None)
        if not client_order_id and not order_id:
            return False

        try:
            lookup = getattr(intent_lookup, "lookup", None)
            if lookup is None:
                return False

            if _is_async_callable(lookup):
                # Async callers must await this themselves; sync context cannot.
                return False

            result = lookup(
                client_order_id=client_order_id,
                order_id=order_id,
                lookback_seconds=PENDING_INTENT_LOOKUP_SECONDS,
            )
            return bool(result)
        except Exception as exc:
            logger.warning("[TRADING-CIRCUIT-BREAKER] Pending intent lookup failed: %s", exc)
            return False


def _validate_approval_token(token: str, intent: Any) -> bool:
    """Validate an emergency-close approval token.

    In the simplest deployment the token is a shared secret set via
    ``MERID_MANUAL_EMERGENCY_TOKEN``.  A production deployment should call an
    approval service.
    """
    expected = os.environ.get("MERID_MANUAL_EMERGENCY_TOKEN")
    if not expected:
        logger.critical(
            "[TRADING-CIRCUIT-BREAKER] MERID_MANUAL_EMERGENCY_TOKEN is not set; "
            "manual emergency close is unavailable"
        )
        return False
    return _secure_compare(token, expected)


def _secure_compare(a: str, b: str) -> bool:
    if len(a) != len(b):
        return False
    result = 0
    for x, y in zip(a, b):
        result |= ord(x) ^ ord(y)
    return result == 0


def _is_async_callable(fn: Any) -> bool:
    return callable(fn) and getattr(fn, "__code__", None) is not None and fn.__code__.co_flags & 0x80


def get_trading_circuit_breaker() -> TradingCircuitBreaker:
    return TradingCircuitBreaker()


def trading_halt(reason: str, *, metadata: Optional[Dict[str, Any]] = None) -> HaltRecord:
    return TradingCircuitBreaker().halt(reason=reason, metadata=metadata)


def _fmt_ts(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _release_result(
    released: bool,
    checks: List[Dict[str, Any]],
    audit_payload: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build a structured admin_release result."""
    failed = [c for c in checks if not c.get("ok", False)]
    return {
        "released": released,
        "ok": released and not failed,
        "checks": checks,
        "failed_checks": failed,
        "audit_record": audit_payload,
    }

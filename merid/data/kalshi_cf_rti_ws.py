"""Kalshi CF Benchmarks RTI WebSocket stream.

Authenticated feed that uses the same Kalshi API-key + private-key chain as
order placement.  The stream connects to Kalshi's dedicated ``cfbenchmarks_value``
WebSocket, discovers valid index IDs via ``indexlist``, and pushes parsed frames
to a caller-supplied callback.

The direct CF Benchmarks REST key remains supported as an optional fallback in
``merid.data.cf_rti_adapter``; this module is the primary paper/shadow source.

Kalshi docs: https://docs.kalshs.com/websockets/cfbenchmarks-value
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import threading
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import websockets
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

from merid.event_venues.kalshi.kalshi_config import get_kalshi_config, KalshiConfig
from utils.logger import get_logger

logger = get_logger("merid.data.kalshi_cf_rti_ws")


# Asset map used to translate Kalshi index IDs into the canonical symbols used
# by ``merid.data.cf_rti_adapter``.  The Kalshi IDs returned by ``indexlist``
# are the source of truth; these are common aliases we expect.
_CFB_SYMBOL_TO_ASSET: Dict[str, str] = {
    "BRTI": "BTC",
    "ETH_RTI": "ETH",
    "SOL_RTI": "SOL",
    "XRP_RTI": "XRP",
    "DOGE_RTI": "DOGE",
    "BRTI-USD": "BTC",
    "ETHUSD_RTI": "ETH",
    "ETH_RTI_USD": "ETH",
    "SOLUSD_RTI": "SOL",
    "XRPUSD_RTI": "XRP",
    "DOGEUSD_RTI": "DOGE",
}

# Canonical CF symbols to try when mapping an asset back to an index ID.
_ASSET_TO_CFB_SYMBOL: Dict[str, List[str]] = {
    "BTC": ["BRTI", "BRTI-USD"],
    "ETH": ["ETH_RTI", "ETHUSD_RTI", "ETH_RTI_USD"],
    "SOL": ["SOL_RTI", "SOLUSD_RTI"],
    "XRP": ["XRP_RTI", "XRPUSD_RTI"],
    "DOGE": ["DOGE_RTI", "DOGEUSD_RTI"],
}

# Kalshi's dedicated CF Benchmarks WebSocket endpoint.  The main Trade API
# ``ws.py`` uses the elections endpoint; this RTI feed has its own host.
_CFB_RTI_WS_DEFAULT = "wss://external-api-ws.kalshi.com/trade-api/ws/v2"


@dataclass
class KalshiCfRtiFrame:
    """Raw RTI frame from the Kalshi ``cfbenchmarks_value`` channel."""
    index_id: str
    data: Dict[str, Any]


class KalshiCfRtiStream:
    """Authenticated Kalshi WebSocket stream for CF Benchmarks index values.

    Runs in a background thread with its own asyncio event loop.  The public
    ``start()`` / ``stop()`` methods are thread-safe and can be called from
    synchronous MERID code.
    """

    def __init__(
        self,
        on_frame: Optional[Callable[[KalshiCfRtiFrame], None]] = None,
        on_reconnect: Optional[Callable[[], None]] = None,
        on_disconnect: Optional[Callable[[], None]] = None,
    ):
        self.config = get_kalshi_config()
        # The dedicated ``cfbenchmarks_value`` feed lives on a separate host.
        # Allow explicit override, otherwise use the canonical RTI endpoint.
        self.ws_url = (
            os.environ.get("MERID_CFB_RTI_WS_URL")
            or os.environ.get("MERID_KALSHI_WS_BASE")
            or _CFB_RTI_WS_DEFAULT
        )
        self.on_frame = on_frame
        self.on_reconnect = on_reconnect
        self.on_disconnect = on_disconnect
        self._ws: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._msg_id = 0
        self._reconnect_delay = 1.0
        self._max_reconnect_delay = 60.0
        self._sid: Optional[int] = None
        self._index_ids: List[str] = []
        self._lock = threading.Lock()

    def _next_msg_id(self) -> int:
        with self._lock:
            self._msg_id += 1
            return self._msg_id

    def _call_callback(self, callback: Optional[Callable[[], None]]) -> None:
        if not callback:
            return
        try:
            callback()
        except Exception:
            logger.exception("[KALSHI-CF-RTI-WS] callback error")

    def _load_private_key(self):
        private_key_pem = getattr(self.config, "private_key_pem", None)
        private_key_path = getattr(self.config, "private_key_path", None)

        if not private_key_pem and not private_key_path:
            raise ValueError("Kalshi private key (path or PEM) required for WebSocket authentication")

        if private_key_pem:
            return serialization.load_pem_private_key(private_key_pem.encode(), password=None)

        key_path = Path(private_key_path)
        if not key_path.exists():
            raise FileNotFoundError(f"Kalshi private key not found: {key_path}")
        with open(key_path, "rb") as f:
            return serialization.load_pem_private_key(f.read(), password=None)

    def _build_auth_headers(self) -> Dict[str, str]:
        private_key = self._load_private_key()
        timestamp = str(int(time.time() * 1000))
        method = "GET"
        path = "/trade-api/ws/v2"
        msg_string = timestamp + method + path

        signature = private_key.sign(
            msg_string.encode("utf-8"),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )

        api_key = getattr(self.config, "api_key_id", None) or getattr(self.config, "api_key", None)
        if not api_key:
            raise ValueError("Kalshi API key id missing")

        return {
            "Content-Type": "application/json",
            "KALSHI-ACCESS-KEY": api_key,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
            "KALSHI-ACCESS-TIMESTAMP": timestamp,
        }

    async def _connect(self) -> None:
        headers = self._build_auth_headers()
        logger.info("[KALSHI-CF-RTI-WS] Connecting to %s", self.ws_url)

        try:
            self._ws = await websockets.connect(
                self.ws_url,
                additional_headers=headers,
                ping_interval=30,
                ping_timeout=60,
                close_timeout=5,
            )
            logger.info("[KALSHI-CF-RTI-WS] Connected")
        except TypeError:
            self._ws = await websockets.connect(
                self.ws_url,
                extra_headers=headers,
                ping_interval=30,
                ping_timeout=60,
                close_timeout=5,
            )
            logger.info("[KALSHI-CF-RTI-WS] Connected (extra_headers fallback)")

    async def _recv_one(self, timeout: float) -> Optional[Dict[str, Any]]:
        if not self._ws:
            raise RuntimeError("WebSocket not connected")
        try:
            raw = await asyncio.wait_for(self._ws.recv(), timeout=timeout)
        except asyncio.TimeoutError:
            return None
        except websockets.ConnectionClosed:
            raise

        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("[KALSHI-CF-RTI-WS] Non-JSON frame: %r", raw[:200])
            return None

    async def _handle_message(self, data: Dict[str, Any]) -> None:
        msg_type = data.get("type")
        msg = data.get("msg") if isinstance(data.get("msg"), dict) else {}

        if msg_type == "subscribed":
            channel = msg.get("channel")
            if channel == "cfbenchmarks_value":
                self._sid = data.get("sid") or msg.get("sid")
                logger.info("[KALSHI-CF-RTI-WS] subscribed sid=%s", self._sid)
            return

        if msg_type == "cfbenchmarks_value_indexlist":
            index_ids = msg.get("index_ids") or data.get("index_ids") or []
            logger.info("[KALSHI-CF-RTI-WS] indexlist: %s", index_ids)
            return

        if msg_type in ("error", "err"):
            logger.warning("[KALSHI-CF-RTI-WS] server error: %s", data)
            return

        if msg_type == "cfbenchmarks_value":
            await self._forward_frame(msg, sid=data.get("sid"), seq=data.get("seq"))

    async def _wait_for_message(
        self,
        predicate: Callable[[Dict[str, Any]], bool],
        timeout: float,
    ) -> Optional[Dict[str, Any]]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            remaining = max(0.1, deadline - time.time())
            data = await self._recv_one(timeout=remaining)
            if data is None:
                continue
            await self._handle_message(data)
            if predicate(data):
                return data
        return None

    async def _send_subscribe(self, index_ids: Optional[List[str]] = None) -> None:
        if not self._ws:
            raise RuntimeError("WebSocket not connected")

        msg_id = self._next_msg_id()
        params: Dict[str, Any] = {"channels": ["cfbenchmarks_value"]}
        if index_ids is not None:
            params["index_ids"] = index_ids

        request = {
            "id": msg_id,
            "cmd": "subscribe",
            "params": params,
        }
        await self._ws.send(json.dumps(request))
        logger.info("[KALSHI-CF-RTI-WS] subscribe sent (id=%s index_ids=%s)", msg_id, index_ids)

    async def _send_indexlist(self) -> None:
        if not self._ws or self._sid is None:
            return
        msg_id = self._next_msg_id()
        request = {
            "id": msg_id,
            "cmd": "update_subscription",
            "params": {
                "sid": self._sid,
                "action": "indexlist",
            },
        }
        await self._ws.send(json.dumps(request))
        logger.info("[KALSHI-CF-RTI-WS] indexlist sent (sid=%s)", self._sid)

    async def _send_subscribe_indices(self, index_ids: List[str]) -> None:
        if not self._ws or self._sid is None:
            return
        if not index_ids:
            return

        msg_id = self._next_msg_id()
        request = {
            "id": msg_id,
            "cmd": "update_subscription",
            "params": {
                "sid": self._sid,
                "action": "subscribe_indices",
                "index_ids": index_ids,
            },
        }
        await self._ws.send(json.dumps(request))
        logger.info("[KALSHI-CF-RTI-WS] subscribe_indices sent (sid=%s ids=%s)", self._sid, index_ids)

    async def _subscribe_and_indexlist(self, timeout: float = 10.0) -> None:
        # Subscribe to every available index.  This is the subscription that
        # causes the server to begin emitting ``cfbenchmarks_value`` ticks.
        # We then use ``indexlist`` to discover the authoritative IDs and log them.
        await self._send_subscribe(index_ids=["all"])

        # Wait for the subscribed confirmation so we have the sid.
        data = await self._wait_for_message(
            lambda d: d.get("type") == "subscribed"
            and d.get("msg", {}).get("channel") == "cfbenchmarks_value",
            timeout=timeout,
        )
        if data is None:
            logger.warning("[KALSHI-CF-RTI-WS] did not receive subscribed confirmation")

        # Request the indexlist even if subscribed was not seen (it may still work).
        # NOTE: indexlist is logged for discovery, but data must already be flowing
        # from the initial subscribe.  We do not gate processing on this response.
        try:
            await self._send_indexlist()
            data = await self._wait_for_message(
                lambda d: d.get("type") == "cfbenchmarks_value_indexlist",
                timeout=timeout,
            )
            if data:
                msg = data.get("msg") if isinstance(data.get("msg"), dict) else data
                index_ids = msg.get("index_ids") or data.get("index_ids") or []
                self._index_ids = index_ids
                logger.info("[KALSHI-CF-RTI-WS] indexlist confirmed: %s", index_ids)
        except Exception as exc:
            logger.warning("[KALSHI-CF-RTI-WS] indexlist request failed: %s", exc)

        if not self._index_ids:
            # Fallback: track all known canonical IDs if indexlist is not returned.
            self._index_ids = sorted({s for symbols in _ASSET_TO_CFB_SYMBOL.values() for s in symbols})
            logger.info("[KALSHI-CF-RTI-WS] indexlist not returned; using canonical IDs")

        # The server does not support narrowing an existing "all" subscription
        # via update_subscription, so we record the enabled IDs for
        # client-side filtering and telemetry while the socket remains
        # subscribed to "all".
        enabled_ids = sorted(i for i in self._index_ids if index_id_to_asset(i))
        if enabled_ids:
            self._index_ids = enabled_ids
            logger.info("[KALSHI-CF-RTI-WS] enabled index_ids: %s", enabled_ids)

    async def _forward_frame(
        self,
        msg: Dict[str, Any],
        sid: Optional[int] = None,
        seq: Optional[int] = None,
    ) -> None:
        if not self.on_frame:
            return

        index_id = msg.get("index_id")
        if not index_id:
            return

        # The raw CF Benchmarks frame arrives as a JSON string inside ``msg.data``.
        # Parse with parse_float=Decimal so the full source precision (e.g. 7
        # decimals for DOGE) is preserved end-to-end.
        raw_data_str = msg.get("data")
        try:
            if isinstance(raw_data_str, str):
                raw_data = json.loads(raw_data_str, parse_float=Decimal)
            else:
                raw_data = raw_data_str or {}
        except json.JSONDecodeError:
            raw_data = {}

        # ``received_at`` is when Kalshi received the upstream tick (unix ms).
        received_at = msg.get("received_at")

        # ``avg_60s_data`` is a structured 60-second rolling average.
        avg_60s_data = msg.get("avg_60s_data") if isinstance(msg.get("avg_60s_data"), dict) else {}
        avg_60s_value = avg_60s_data.get("value")

        last_60s_15min = msg.get("last_60s_windowed_average_15min")
        if isinstance(last_60s_15min, dict):
            last_60s_15min_value = last_60s_15min.get("value")
        else:
            last_60s_15min_value = None

        data: Dict[str, Any] = dict(raw_data)
        if "received_at" not in data and received_at is not None:
            data["received_at"] = received_at
        if "average_60s" not in data and avg_60s_value is not None:
            data["average_60s"] = avg_60s_value
        if "last_60s_average_15min" not in data and last_60s_15min_value is not None:
            data["last_60s_average_15min"] = last_60s_15min_value
        if "seq" not in data and seq is not None:
            data["seq"] = seq
        if "sid" not in data and sid is not None:
            data["sid"] = sid

        try:
            self.on_frame(KalshiCfRtiFrame(index_id=index_id, data=data))
        except Exception as e:
            logger.error("[KALSHI-CF-RTI-WS] on_frame error: %s", e)

    async def _process_messages(self) -> None:
        # CRITICAL FIX (2026-08-24): Silence watchdog.  A socket that stays open
        # but stops delivering RTI frames must not spin forever on 5s timeouts;
        # force a reconnect so the subscription is re-established.  Observed in
        # production: frames stopped at the 15m window roll and never recovered
        # because the socket stayed open but silent.
        #
        # NOTE: _recv_one swallows asyncio.TimeoutError and returns None, so the
        # silence check must be performed on a None result, not in an except clause.
        last_data_ts = time.monotonic()
        silence_threshold_s = float(os.environ.get("MERID_CFB_RTI_SILENCE_RECONNECT_S", "45"))
        while self._running and self._ws:
            try:
                data = await self._recv_one(timeout=5.0)
                if data is not None:
                    last_data_ts = time.monotonic()
                    await self._handle_message(data)
                else:
                    silent_for = time.monotonic() - last_data_ts
                    if silent_for > silence_threshold_s:
                        logger.error(
                            "[KALSHI-CF-RTI-WS] No RTI frames for %.1fs (threshold=%ss) - forcing reconnect",
                            silent_for,
                            silence_threshold_s,
                        )
                        self._call_callback(self.on_disconnect)
                        break
            except websockets.ConnectionClosed:
                logger.info("[KALSHI-CF-RTI-WS] Connection closed")
                self._call_callback(self.on_disconnect)
                break
            except Exception as e:
                logger.warning("[KALSHI-CF-RTI-WS] recv error: %s", e)
                self._call_callback(self.on_disconnect)
                break

    async def _run_once(self) -> None:
        self._running = True
        self._call_callback(self.on_reconnect)
        await self._connect()
        await self._subscribe_and_indexlist()
        await self._process_messages()

    async def run_forever(self) -> None:
        self._running = True
        while self._running:
            try:
                self._sid = None
                self._index_ids = []
                run_started = time.monotonic()
                await self._run_once()
                # Reset backoff after a healthy run so a later failure does not
                # inherit a stale 60s delay from a previous outage.
                if time.monotonic() - run_started > 60.0:
                    self._reconnect_delay = 1.0
            except Exception as e:
                logger.error("[KALSHI-CF-RTI-WS] Run-cycle error: %s", e)
                if self._running:
                    logger.info("[KALSHI-CF-RTI-WS] Reconnecting in %.1fs", self._reconnect_delay)
                    await asyncio.sleep(self._reconnect_delay)
                    self._reconnect_delay = min(self._reconnect_delay * 2, self._max_reconnect_delay)

            with self._lock:
                ws = self._ws
                self._ws = None
            if ws:
                try:
                    await ws.close()
                except Exception:
                    pass

    def _thread_entry(self) -> None:
        try:
            asyncio.run(self.run_forever())
        except Exception:
            logger.exception("[KALSHI-CF-RTI-WS] Stream thread crashed")

    def start(self) -> None:
        with self._lock:
            if self._running or (self._thread and self._thread.is_alive()):
                return

        self._running = True
        self._reconnect_delay = 1.0
        self._thread = threading.Thread(target=self._thread_entry, name="kalshi-cf-rti-ws", daemon=True)
        self._thread.start()
        logger.info("[KALSHI-CF-RTI-WS] Stream thread started")

    def stop(self) -> None:
        self._running = False
        with self._lock:
            ws = self._ws
        if ws:
            try:
                asyncio.get_event_loop().call_soon_threadsafe(asyncio.create_task, ws.close())
            except Exception:
                pass
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)


def index_id_to_asset(index_id: str) -> Optional[str]:
    """Map a Kalshi index ID to an asset/cfb_symbol pair used by the adapter."""
    if not index_id:
        return None
    upper = index_id.strip().upper()
    if upper in _CFB_SYMBOL_TO_ASSET:
        return _CFB_SYMBOL_TO_ASSET[upper]
    for symbol, asset in _CFB_SYMBOL_TO_ASSET.items():
        if upper.startswith(symbol) or upper.endswith(symbol):
            return asset
    return None

"""Kalshi FIX API client.

Implements FIX 4.4 protocol for Kalshi's execution venue.
Based on Kalshi's FIX documentation and stunnel configuration.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Tuple

from utils.logger import get_logger

logger = get_logger("merid.event_venues.kalshi.fix")


@dataclass
class FIXOrder:
    """FIX order representation."""
    cl_ord_id: str
    ticker: str
    side: str  # "1"=Buy, "2"=Sell
    ord_type: str  # "1"=Market, "2"=Limit
    price: Optional[int] = None  # Cents for limit orders
    quantity: int = 1
    time_in_force: str = "0"  # "0"=Day, "1"=GTC, "3"=IOC, "4"=FOK
    symbol: str = ""


@dataclass
class FIXExecution:
    """FIX execution report."""
    order_id: str
    cl_ord_id: str
    exec_id: str
    exec_type: str  # "0"=New, "1"=Partial, "2"=Fill, "4"=Canceled, "8"=Rejected
    ord_status: str  # "0"=New, "1"=Partial, "2"=Filled, "4"=Canceled, "8"=Rejected
    price: Optional[int]
    quantity: int
    leaves_qty: int
    cum_qty: int
    last_qty: int
    last_px: Optional[int]
    text: str = ""
    timestamp: float = 0.0


class KalshiFIXClient:
    """Kalshi FIX 4.4 client.

    Connects via stunnel to Kalshi's FIX endpoint.
    Handles session management, heartbeat, and order flow.
    """

    def __init__(
        self,
        sender_comp_id: str,
        target_comp_id: str = "KALSHI",
        host: str = "127.0.0.1",
        port: int = 98228,  # stunnel local port
        heartbeat_interval: int = 30,
    ):
        self.sender_comp_id = sender_comp_id
        self.target_comp_id = target_comp_id
        self.host = host
        self.port = port
        self.heartbeat_interval = heartbeat_interval

        self._reader: Optional[asyncio.StreamReader] = None
        self._writer: Optional[asyncio.StreamWriter] = None
        self._running = False
        self._logged_on = False
        self._msg_seq_num = 0
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._listen_task: Optional[asyncio.Task] = None

        # Callbacks
        self._execution_cb: Optional[Callable[[FIXExecution], None]] = None
        self._reject_cb: Optional[Callable[[str, str], None]] = None

        # Pending orders
        self._pending_orders: Dict[str, FIXOrder] = {}
        self._exec_history: List[FIXExecution] = []

    async def connect(self) -> bool:
        """Connect and logon to FIX session."""
        try:
            self._reader, self._writer = await asyncio.open_connection(
                self.host, self.port
            )
            self._running = True

            # Send logon
            await self._send_logon()

            # Start heartbeat and listener
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            self._listen_task = asyncio.create_task(self._listen_loop())

            # Wait for logon confirmation
            for _ in range(50):  # 5 seconds timeout
                if self._logged_on:
                    return True
                await asyncio.sleep(0.1)

            return False
        except Exception as e:
            logger.error(f"FIX connect failed: {e}")
            return False

    async def disconnect(self) -> None:
        """Logout and disconnect."""
        self._running = False

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass

        if self._listen_task:
            self._listen_task.cancel()
            try:
                await self._listen_task
            except asyncio.CancelledError:
                pass

        if self._writer:
            await self._send_logout()
            self._writer.close()
            await self._writer.wait_closed()

        logger.info("FIX disconnected")

    def on_execution(self, cb: Callable[[FIXExecution], None]) -> None:
        """Set callback for execution reports."""
        self._execution_cb = cb

    def on_reject(self, cb: Callable[[str, str], None]) -> None:
        """Set callback for order rejects."""
        self._reject_cb = cb

    async def submit_order(
        self,
        ticker: str,
        side: str,  # "buy" or "sell"
        quantity: int,
        price: Optional[int] = None,
        ord_type: str = "limit",
        time_in_force: str = "gtc",
    ) -> str:
        """Submit new order via FIX.

        Returns:
            Client order ID
        """
        cl_ord_id = str(uuid.uuid4())[:20]

        # Map to FIX values
        fix_side = "1" if side.lower() == "buy" else "2"
        fix_ord_type = "2" if ord_type.lower() == "limit" else "1"
        fix_tif_map = {"gtc": "1", "day": "0", "ioc": "3", "fok": "4"}
        fix_tif = fix_tif_map.get(time_in_force.lower(), "1")

        order = FIXOrder(
            cl_ord_id=cl_ord_id,
            ticker=ticker,
            side=fix_side,
            ord_type=fix_ord_type,
            price=price,
            quantity=quantity,
            time_in_force=fix_tif,
            symbol=ticker,
        )

        self._pending_orders[cl_ord_id] = order

        msg = self._build_new_order_single(order)
        await self._send_msg(msg)

        return cl_ord_id

    async def cancel_order(self, cl_ord_id: str) -> None:
        """Cancel an order via FIX."""
        orig_order = self._pending_orders.get(cl_ord_id)
        if not orig_order:
            logger.warning(f"Cancel requested for unknown order: {cl_ord_id}")
            return

        cancel_id = str(uuid.uuid4())[:20]
        msg = self._build_cancel_request(
            cancel_id=cancel_id,
            orig_cl_ord_id=cl_ord_id,
            symbol=orig_order.symbol,
            side=orig_order.side,
        )
        await self._send_msg(msg)

    # ── Internal message handling ─────────────────────────────────────────

    def _build_new_order_single(self, order: FIXOrder) -> str:
        """Build FIX NewOrderSingle (35=D)."""
        self._msg_seq_num += 1
        msg = (
            f"8=FIX.4.4|9=0000|35=D|"
            f"49={self.sender_comp_id}|56={self.target_comp_id}|"
            f"34={self._msg_seq_num}|52={self._fix_timestamp()}|"
            f"11={order.cl_ord_id}|"
            f"55={order.symbol}|"
            f"54={order.side}|"
            f"38={order.quantity}|"
            f"40={order.ord_type}|"
            f"59={order.time_in_force}"
        )
        if order.price and order.ord_type == "2":
            msg += f"|44={order.price}"
        msg += "|10=000|"
        return msg

    def _build_cancel_request(
        self,
        cancel_id: str,
        orig_cl_ord_id: str,
        symbol: str,
        side: str,
    ) -> str:
        """Build FIX OrderCancelRequest (35=F)."""
        self._msg_seq_num += 1
        msg = (
            f"8=FIX.4.4|9=0000|35=F|"
            f"49={self.sender_comp_id}|56={self.target_comp_id}|"
            f"34={self._msg_seq_num}|52={self._fix_timestamp()}|"
            f"41={orig_cl_ord_id}|"
            f"11={cancel_id}|"
            f"55={symbol}|"
            f"54={side}|"
            f"10=000|"
        )
        return msg

    async def _send_logon(self) -> None:
        """Send FIX Logon (35=A)."""
        self._msg_seq_num += 1
        msg = (
            f"8=FIX.4.4|9=0000|35=A|"
            f"49={self.sender_comp_id}|56={self.target_comp_id}|"
            f"34={self._msg_seq_num}|52={self._fix_timestamp()}|"
            f"98=0|108={self.heartbeat_interval}|"
            f"10=000|"
        )
        await self._send_raw(msg.replace("|", "\x01"))

    async def _send_logout(self) -> None:
        """Send FIX Logout (35=5)."""
        self._msg_seq_num += 1
        msg = (
            f"8=FIX.4.4|9=0000|35=5|"
            f"49={self.sender_comp_id}|56={self.target_comp_id}|"
            f"34={self._msg_seq_num}|52={self._fix_timestamp()}|"
            f"10=000|"
        )
        await self._send_raw(msg.replace("|", "\x01"))

    async def _send_heartbeat(self, test_req_id: Optional[str] = None) -> None:
        """Send FIX Heartbeat (35=0)."""
        self._msg_seq_num += 1
        msg = (
            f"8=FIX.4.4|9=0000|35=0|"
            f"49={self.sender_comp_id}|56={self.target_comp_id}|"
            f"34={self._msg_seq_num}|52={self._fix_timestamp()}"
        )
        if test_req_id:
            msg += f"|112={test_req_id}"
        msg += "|10=000|"
        await self._send_raw(msg.replace("|", "\x01"))

    async def _send_test_request(self) -> None:
        """Send FIX TestRequest (35=1)."""
        self._msg_seq_num += 1
        test_id = str(uuid.uuid4())[:8]
        msg = (
            f"8=FIX.4.4|9=0000|35=1|"
            f"49={self.sender_comp_id}|56={self.target_comp_id}|"
            f"34={self._msg_seq_num}|52={self._fix_timestamp()}|"
            f"112={test_id}|10=000|"
        )
        await self._send_raw(msg.replace("|", "\x01"))

    async def _send_msg(self, msg: str) -> None:
        """Send FIX message with proper encoding."""
        msg = msg.replace("|", "\x01")
        await self._send_raw(msg)

    async def _send_raw(self, msg: str) -> None:
        """Send raw message to socket."""
        if self._writer:
            self._writer.write(msg.encode("ASCII"))
            await self._writer.drain()

    async def _heartbeat_loop(self) -> None:
        """Maintain heartbeat."""
        while self._running:
            try:
                await asyncio.sleep(self.heartbeat_interval)
                if self._logged_on:
                    await self._send_heartbeat()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Heartbeat error: {e}")

    async def _listen_loop(self) -> None:
        """Listen for FIX messages."""
        while self._running:
            try:
                if not self._reader:
                    await asyncio.sleep(0.1)
                    continue

                data = await self._reader.read(4096)
                if not data:
                    logger.warning("FIX connection closed by server")
                    break

                # Parse messages (may be multiple in one packet)
                msgs = data.decode("ASCII", errors="replace").split("\x01")
                for msg in msgs:
                    if "35=" in msg:
                        await self._handle_message(msg)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"FIX listen error: {e}")
                await asyncio.sleep(1)

    async def _handle_message(self, msg: str) -> None:
        """Parse and handle FIX message."""
        tags = self._parse_fix(msg)
        msg_type = tags.get("35", "")

        if msg_type == "A":  # Logon
            self._logged_on = True
            logger.info("FIX logon confirmed")

        elif msg_type == "5":  # Logout
            logger.info("FIX logout received")
            self._logged_on = False

        elif msg_type == "0":  # Heartbeat
            pass  # Just a heartbeat

        elif msg_type == "1":  # TestRequest
            test_req_id = tags.get("112", "")
            await self._send_heartbeat(test_req_id)

        elif msg_type == "8":  # ExecutionReport
            exec_report = self._parse_execution(tags)
            self._exec_history.append(exec_report)

            if self._execution_cb:
                try:
                    self._execution_cb(exec_report)
                except Exception as e:
                    logger.error(f"Execution callback error: {e}")

            # Update pending orders
            if exec_report.cl_ord_id in self._pending_orders:
                if exec_report.ord_status in ("2", "4", "8"):  # Filled, Canceled, Rejected
                    del self._pending_orders[exec_report.cl_ord_id]

        elif msg_type == "9":  # OrderCancelReject
            cl_ord_id = tags.get("11", "")
            reason = tags.get("58", "Unknown")
            logger.warning(f"Order cancel rejected: {cl_ord_id} - {reason}")
            if self._reject_cb:
                self._reject_cb(cl_ord_id, reason)

        elif msg_type == "3":  # Reject (session)
            reason = tags.get("58", "Unknown")
            logger.error(f"FIX session reject: {reason}")

    def _parse_fix(self, msg: str) -> Dict[str, str]:
        """Parse FIX tag=value pairs."""
        tags = {}
        parts = msg.split("\x01")
        for part in parts:
            if "=" in part:
                tag, value = part.split("=", 1)
                tags[tag] = value
        return tags

    def _parse_execution(self, tags: Dict[str, str]) -> FIXExecution:
        """Parse execution report tags."""
        def get_int(key: str, default: int = 0) -> int:
            try:
                return int(tags.get(key, default))
            except (ValueError, TypeError):
                return default

        def get_price(key: str) -> Optional[int]:
            val = tags.get(key)
            if val:
                try:
                    return int(float(val))
                except (ValueError, TypeError):
                    pass
            return None

        return FIXExecution(
            order_id=tags.get("37", ""),
            cl_ord_id=tags.get("11", ""),
            exec_id=tags.get("17", ""),
            exec_type=tags.get("150", ""),
            ord_status=tags.get("39", ""),
            price=get_price("44"),
            quantity=get_int("38"),
            leaves_qty=get_int("151"),
            cum_qty=get_int("14"),
            last_qty=get_int("32"),
            last_px=get_price("31"),
            text=tags.get("58", ""),
            timestamp=time.time(),
        )

    def _fix_timestamp(self) -> str:
        """Generate FIX timestamp (UTC)."""
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).strftime("%Y%m%d-%H:%M:%S.%f")[:-3]

    @property
    def is_connected(self) -> bool:
        """Check if connected and logged on."""
        return self._running and self._logged_on

    def get_pending_orders(self) -> List[FIXOrder]:
        """Get list of pending orders."""
        return list(self._pending_orders.values())

    def get_exec_history(self, limit: int = 100) -> List[FIXExecution]:
        """Get recent execution history."""
        return self._exec_history[-limit:]

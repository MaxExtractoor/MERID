"""Subscription readiness requires an acknowledged SID and observed traffic."""

from types import SimpleNamespace
import json

import pytest
from websockets.protocol import State

from merid.event_venues.kalshi.ws import KalshiWebSocket


TICKER = "KXBTC15M-26NOV021145-45"


@pytest.fixture
def ws():
    client = KalshiWebSocket(config=SimpleNamespace(api_key="test-key"))
    client._ws = SimpleNamespace(state=State.OPEN)
    client._running = True
    client._connection_generation = 1
    client._orderbook_tickers.add(TICKER)
    return client


def ack(sid=4):
    return {"type": "subscribed", "msg": {"channel": "orderbook_delta", "sid": sid}}


def delta(sid=4, ticker=TICKER):
    return {
        "type": "orderbook_delta", "sid": sid, "seq": 1,
        "msg": {"market_ticker": ticker, "side": "yes", "price_dollars": "0.32", "delta_fp": "1.00"},
    }


def test_claimed_ticker_frame_adopts_sid_and_confirms(ws):
    """Kalshi only streams orderbook frames for subscribed markets, so the
    first live frame for a claimed ticker both adopts the sid and proves the
    ticker is streaming (the ack that never arrives as type=subscribed)."""
    assert not ws.is_orderbook_subscription_confirmed(TICKER)
    ws._note_orderbook_subscription_observation(delta(sid=4))
    assert ws._subscription_ids["orderbook_delta"] == 4
    assert ws.is_orderbook_subscription_confirmed(TICKER)


def test_unclaimed_ticker_frame_adopts_no_sid(ws):
    """Frames for markets we never subscribed prove nothing."""
    ws._orderbook_tickers.discard(TICKER)
    ws._note_orderbook_subscription_observation(delta(sid=4))
    assert ws._subscription_ids.get("orderbook_delta") is None
    assert not ws.is_orderbook_subscription_confirmed(TICKER)


def test_mismatched_sid_frame_is_not_evidence(ws):
    """Once a sid is known, frames under a different sid neither overwrite it
    nor count as this ticker's observation."""
    ws._record_subscription_confirmation(ack())
    ws._note_orderbook_subscription_observation(delta(sid=9))
    assert ws._subscription_ids["orderbook_delta"] == 4
    assert not ws.is_orderbook_subscription_confirmed(TICKER)
    ws._note_orderbook_subscription_observation(delta())
    assert ws.is_orderbook_subscription_confirmed(TICKER)


def test_disconnect_and_new_session_revoke_evidence(ws):
    ws._record_subscription_confirmation(ack())
    ws._note_orderbook_subscription_observation(delta())
    assert ws.is_orderbook_subscription_confirmed(TICKER)
    ws._ws.state = State.CLOSED
    assert not ws.is_orderbook_subscription_confirmed(TICKER)
    ws._ws.state = State.OPEN
    ws._reset_subscription_evidence()
    ws._connection_generation += 1
    ws._record_subscription_confirmation(ack())
    assert not ws.is_orderbook_subscription_confirmed(TICKER)
    ws._note_orderbook_subscription_observation(delta())
    assert ws.is_orderbook_subscription_confirmed(TICKER)


def test_removed_and_readded_ticker_requires_fresh_observation(ws):
    ws._record_subscription_confirmation(ack())
    ws._note_orderbook_subscription_observation(delta())
    ws._forget_orderbook_subscription_observation([TICKER])
    ws._orderbook_tickers.discard(TICKER)
    assert not ws.is_orderbook_subscription_confirmed(TICKER)
    ws._orderbook_tickers.add(TICKER)
    assert not ws.is_orderbook_subscription_confirmed(TICKER)
    ws._note_orderbook_subscription_observation(delta())
    assert ws.is_orderbook_subscription_confirmed(TICKER)


def test_sid_replacement_revokes_old_ticker_evidence(ws):
    ws._record_subscription_confirmation(ack())
    ws._note_orderbook_subscription_observation(delta())
    ws._record_subscription_confirmation(ack(sid=5))
    assert not ws.is_orderbook_subscription_confirmed(TICKER)
    ws._note_orderbook_subscription_observation(delta(sid=5))
    assert ws.is_orderbook_subscription_confirmed(TICKER)


def test_subscription_removal_revokes_matching_sid_only(ws):
    ws._record_subscription_confirmation(ack())
    ws._note_orderbook_subscription_observation(delta())
    ws._record_subscription_removal({"type": "unsubscribed", "sid": 9})
    assert ws.is_orderbook_subscription_confirmed(TICKER)
    ws._record_subscription_removal({"type": "unsubscribed", "sid": 4})
    assert not ws.is_orderbook_subscription_confirmed(TICKER)


def test_ok_frame_learns_sid_via_pending_cmd_map(ws):
    """Kalshi answers orderbook subscribes with type=ok — learn the sid anyway."""
    ws._track_pending_subscribe(
        {"id": 7, "cmd": "subscribe",
         "params": {"channels": ["orderbook_delta"], "market_tickers": [TICKER]}}
    )
    ws._record_ok_confirmation(
        {"type": "ok", "id": 7, "sid": 6, "msg": {"market_tickers": [TICKER]}}
    )
    assert ws._subscription_ids.get("orderbook_delta") == 6
    ws._note_orderbook_subscription_observation(delta(sid=6))
    assert ws.is_orderbook_subscription_confirmed(TICKER)


def test_ok_frame_list_msg_learns_all_channels(ws):
    """list_subscriptions responds msg=[{channel, sid}] — record every entry."""
    ws._record_ok_confirmation(
        {"type": "ok", "id": 2,
         "msg": [{"channel": "orderbook_delta", "sid": 1},
                 {"channel": "ticker", "sid": 2}]}
    )
    assert ws._subscription_ids["orderbook_delta"] == 1
    assert ws._subscription_ids["ticker"] == 2
    ws._note_orderbook_subscription_observation(delta(sid=1))
    assert ws.is_orderbook_subscription_confirmed(TICKER)


def test_frame_traffic_bootstraps_unknown_orderbook_sid(ws):
    """Live orderbook frames for a claimed ticker are themselves the ack."""
    ws._note_orderbook_subscription_observation(delta(sid=3))
    assert ws._subscription_ids.get("orderbook_delta") == 3
    assert ws.is_orderbook_subscription_confirmed(TICKER)


def test_ok_frame_without_sid_leaves_gate_closed(ws):
    ws._track_pending_subscribe(
        {"id": 7, "cmd": "subscribe",
         "params": {"channels": ["orderbook_delta"], "market_tickers": [TICKER]}}
    )
    ws._record_ok_confirmation(
        {"type": "ok", "id": 7, "msg": {"market_tickers": [TICKER]}}
    )
    assert ws._subscription_ids.get("orderbook_delta") is None
    assert not ws.is_orderbook_subscription_confirmed(TICKER)


def test_error_response_consumes_pending_channel(ws):
    ws._track_pending_subscribe(
        {"id": 9, "cmd": "subscribe",
         "params": {"channels": ["orderbook_delta"], "market_tickers": [TICKER]}}
    )
    ws._pending_subscribe_channels.pop(9, None)
    ws._record_ok_confirmation({"type": "ok", "id": 9, "sid": 2, "msg": {}})
    assert ws._subscription_ids.get("orderbook_delta") is None


@pytest.mark.asyncio
async def test_receive_path_records_ack_then_ticker_evidence(ws, monkeypatch):
    from merid.data.ingress_replay import ReplayExhausted

    messages = [json.dumps(ack()), json.dumps(delta())]

    async def recv():
        if messages:
            return messages.pop(0)
        assert ws.is_orderbook_subscription_confirmed(TICKER)
        raise ReplayExhausted()

    ws._ws.recv = recv
    ws._lag_monitor_started = True
    monkeypatch.setattr("merid.event_venues.kalshi.ws.record_ingress", lambda *args, **kwargs: None)
    await ws._process_messages_until_disconnect()
    queue = ws._ensure_msg_queue()
    _, first = queue.get_nowait()
    _, second = queue.get_nowait()
    assert first["_ws_connection_generation"] == second["_ws_connection_generation"] == 1


@pytest.mark.asyncio
async def test_skipped_session_recycle_keeps_existing_evidence(ws):
    ws._record_subscription_confirmation(ack())
    ws._note_orderbook_subscription_observation(delta())
    ws._session_recycle_requested = True
    await ws.force_session_reconnect()
    assert ws.is_orderbook_subscription_confirmed(TICKER)

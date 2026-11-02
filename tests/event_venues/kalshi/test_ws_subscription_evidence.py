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


def test_ack_and_current_ticker_observation_are_both_required(ws):
    assert not ws.is_orderbook_subscription_confirmed(TICKER)
    ws._note_orderbook_subscription_observation(delta())
    assert not ws.is_orderbook_subscription_confirmed(TICKER)
    ws._record_subscription_confirmation(ack())
    assert not ws.is_orderbook_subscription_confirmed(TICKER)
    ws._note_orderbook_subscription_observation(delta(sid=9))
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

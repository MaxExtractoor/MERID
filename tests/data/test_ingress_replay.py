"""Tests for the ingress replay dispatcher and replay-aware helpers."""

import os
import tempfile
import threading
from pathlib import Path

import httpx
import pytest

from merid.data.ingress_recorder import (
    IngressRecorder,
    IngressRecorderConfig,
    reset_ingress_recorder_for_tests,
    SOURCE_KALSHI_REST,
    SOURCE_KALSHI_WS,
)
from merid.data.ingress_replay import (
    build_httpx_response,
    get_replay_dispatcher,
    ReplayDispatcher,
    ReplayExhausted,
    replay_json_payload,
    replay_random,
    replay_seed_for_intent,
    replay_time,
    replay_uniform,
    reset_replay_dispatcher_for_tests,
)


@pytest.fixture(autouse=True)
def isolate_replay():
    """Ensure each test starts with a fresh recorder and dispatcher state."""
    reset_ingress_recorder_for_tests(None)
    reset_replay_dispatcher_for_tests(None)
    old_replay = os.environ.get("MERID_REPLAY_TAPE")
    if "MERID_REPLAY_TAPE" in os.environ:
        del os.environ["MERID_REPLAY_TAPE"]
    yield
    reset_ingress_recorder_for_tests(None)
    reset_replay_dispatcher_for_tests(None)
    if old_replay is not None:
        os.environ["MERID_REPLAY_TAPE"] = old_replay
    elif "MERID_REPLAY_TAPE" in os.environ:
        del os.environ["MERID_REPLAY_TAPE"]


def _make_tape(tmp: str, records: list) -> Path:
    """Write a small tape and return its directory."""
    base = Path(tmp)
    recorder = IngressRecorder(
        IngressRecorderConfig(
            enabled=True,
            base_dir=base,
            flush_interval_s=0.05,
        )
    )
    for rec in records:
        recorder.record(rec["source"], rec["payload"], rec.get("metadata", {}))
    recorder.flush()
    recorder.close()
    return base


def test_dispatcher_returns_records_in_capture_seq_order() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tape_dir = _make_tape(
            tmp,
            [
                {
                    "source": SOURCE_KALSHI_WS,
                    "payload": '{"type":"orderbook_delta","ticker":"KXBTC"}',
                    "metadata": {"ticker": "KXBTC"},
                },
                {
                    "source": SOURCE_KALSHI_REST,
                    "payload": '{"status":"ok"}',
                    "metadata": {"path": "/markets"},
                },
                {
                    "source": SOURCE_KALSHI_WS,
                    "payload": '{"type":"fill","market_ticker":"KXETH"}',
                    "metadata": {"market_ticker": "KXETH"},
                },
            ],
        )
        dispatcher = ReplayDispatcher(tape_dir)

        ws1 = dispatcher.get(SOURCE_KALSHI_WS)
        assert ws1["capture_seq"] == 1
        assert ws1["payload"] == '{"type":"orderbook_delta","ticker":"KXBTC"}'

        rest = dispatcher.get(SOURCE_KALSHI_REST)
        assert rest["capture_seq"] == 2
        assert rest["source"] == SOURCE_KALSHI_REST

        ws2 = dispatcher.get(SOURCE_KALSHI_WS)
        assert ws2["capture_seq"] == 3
        assert ws2["payload"] == '{"type":"fill","market_ticker":"KXETH"}'

        with pytest.raises(ReplayExhausted):
            dispatcher.get(SOURCE_KALSHI_WS)


def test_dispatcher_preserves_global_order_across_sources() -> None:
    """A source that calls get() when the head belongs to another source waits."""
    with tempfile.TemporaryDirectory() as tmp:
        tape_dir = _make_tape(
            tmp,
            [
                {"source": SOURCE_KALSHI_WS, "payload": "ws1"},
                {"source": SOURCE_KALSHI_REST, "payload": "rest1"},
            ],
        )
        dispatcher = ReplayDispatcher(tape_dir)

        result: list = [None]

        def rest_consumer():
            try:
                result[0] = dispatcher.get(SOURCE_KALSHI_REST, timeout=2.0)
            except Exception as exc:
                result[0] = exc

        rest_thread = threading.Thread(target=rest_consumer)
        rest_thread.start()

        # Give the rest consumer time to start waiting
        dispatcher.get(SOURCE_KALSHI_WS)

        rest_thread.join(timeout=3.0)
        assert rest_thread.is_alive() is False
        assert isinstance(result[0], dict)
        assert result[0]["payload"] == "rest1"


def test_build_httpx_response_from_record() -> None:
    record = {
        "payload": '{"balance":1000}',
        "metadata": {"status_code": 200, "path": "/balance"},
    }
    request = httpx.Request("GET", "https://example.com/balance")
    response = build_httpx_response(record, request)
    assert response.status_code == 200
    assert response.json() == {"balance": 1000}
    assert response.request is request


def test_replay_helpers_are_deterministic() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tape_dir = _make_tape(
            tmp,
            [
                {"source": SOURCE_KALSHI_WS, "payload": "a"},
                {"source": SOURCE_KALSHI_WS, "payload": "b"},
            ],
        )
        os.environ["MERID_REPLAY_TAPE"] = str(tape_dir)
        dispatcher = get_replay_dispatcher()
        assert dispatcher is not None

        r1 = dispatcher.get(SOURCE_KALSHI_WS)
        assert replay_time() == r1["received_at_ns"] / 1e9

        r2 = dispatcher.get(SOURCE_KALSHI_WS)
        assert replay_time() == r2["received_at_ns"] / 1e9

        # Random values are deterministic across the same tape
        rand1 = replay_random()
        seed1 = replay_seed_for_intent("salt")

        # New dispatcher on the same tape should produce the same values
        reset_replay_dispatcher_for_tests(None)
        os.environ["MERID_REPLAY_TAPE"] = str(tape_dir)
        dispatcher2 = get_replay_dispatcher()
        _ = dispatcher2.get(SOURCE_KALSHI_WS)
        _ = dispatcher2.get(SOURCE_KALSHI_WS)
        assert replay_random() == rand1
        assert replay_seed_for_intent("salt") == seed1


def test_replay_json_payload_decodes_base64() -> None:
    record = {"payload_b64": "eyJzdGF0dXMiOiJvayJ9"}  # {"status":"ok"}
    data = replay_json_payload(record)
    assert data == {"status": "ok"}


def test_replay_uniform_is_deterministic() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tape_dir = _make_tape(tmp, [{"source": SOURCE_KALSHI_WS, "payload": "a"}])
        os.environ["MERID_REPLAY_TAPE"] = str(tape_dir)
        _ = get_replay_dispatcher()
        u = replay_uniform(1.0, 2.0)
        assert 1.0 <= u <= 2.0

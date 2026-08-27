"""Tests for the ingress recorder boundary-capture layer."""

import tempfile
from pathlib import Path

import pytest

from merid.data.ingress_recorder import (
    IngressPlayer,
    IngressRecorder,
    IngressRecorderConfig,
    record_ingress,
    reset_ingress_recorder_for_tests,
    SOURCE_KALSHI_REST,
    SOURCE_KALSHI_WS,
)


@pytest.fixture(autouse=True)
def isolate_recorder():
    """Give each test a clean recorder singleton state."""
    reset_ingress_recorder_for_tests(None)
    yield
    reset_ingress_recorder_for_tests(None)


def test_record_and_read_round_trip() -> None:
    """A recorded WebSocket + REST payload round-trips through the tape."""
    with tempfile.TemporaryDirectory() as tmp:
        recorder = IngressRecorder(
            IngressRecorderConfig(
                enabled=True,
                base_dir=Path(tmp),
                queue_size=100,
                flush_interval_s=0.05,
            )
        )
        recorder.record(
            SOURCE_KALSHI_WS,
            '{"type":"orderbook_delta","ticker":"KXBTC"}',
            {"ticker": "KXBTC"},
        )
        recorder.record(
            SOURCE_KALSHI_REST,
            b'{"status":"ok"}',
            {"path": "/markets"},
        )
        recorder.flush()

        player = IngressPlayer(tmp)
        records = player.iter_records()
        assert len(records) == 2
        assert records[0]["capture_seq"] == 1
        assert records[0]["source"] == SOURCE_KALSHI_WS
        assert records[0]["payload"] == '{"type":"orderbook_delta","ticker":"KXBTC"}'
        assert records[0]["metadata"]["ticker"] == "KXBTC"
        assert records[1]["capture_seq"] == 2
        assert records[1]["source"] == SOURCE_KALSHI_REST
        assert records[1]["payload"] == '{"status":"ok"}'

        recorder.close()


def test_binary_payload_encoded_as_base64() -> None:
    """Non-UTF-8 bytes are stored base64 and restored by the player."""
    with tempfile.TemporaryDirectory() as tmp:
        recorder = IngressRecorder(
            IngressRecorderConfig(
                enabled=True,
                base_dir=Path(tmp),
                flush_interval_s=0.05,
            )
        )
        raw = b"\x89PNG\r\n\x1a\n"
        recorder.record(SOURCE_KALSHI_WS, raw, {})
        recorder.flush()

        player = IngressPlayer(tmp)
        records = player.iter_records()
        assert len(records) == 1
        assert records[0].get("payload_b64") is not None
        assert player.read_payload(records[0]) == raw

        recorder.close()


def test_disabled_recorder_does_not_write() -> None:
    """A disabled recorder is a no-op and leaves no tape files."""
    with tempfile.TemporaryDirectory() as tmp:
        recorder = IngressRecorder(
            IngressRecorderConfig(
                enabled=False,
                base_dir=Path(tmp),
            )
        )
        recorder.record(SOURCE_KALSHI_WS, "{}", {})
        recorder.flush()
        assert not any(Path(tmp).glob("ingress_*.jsonl"))


def test_record_ingress_hot_path_uses_singleton() -> None:
    """`record_ingress` writes to the current singleton recorder."""
    with tempfile.TemporaryDirectory() as tmp:
        recorder = IngressRecorder(
            IngressRecorderConfig(
                enabled=True,
                base_dir=Path(tmp),
                flush_interval_s=0.05,
            )
        )
        reset_ingress_recorder_for_tests(recorder)
        record_ingress(
            SOURCE_KALSHI_WS,
            '{"type":"fill","market_ticker":"KXETH"}',
            {"market_ticker": "KXETH"},
        )
        recorder.flush()

        player = IngressPlayer(tmp)
        records = player.iter_records()
        assert len(records) == 1
        assert records[0]["source"] == SOURCE_KALSHI_WS
        assert records[0]["payload"] == '{"type":"fill","market_ticker":"KXETH"}'

        recorder.close()

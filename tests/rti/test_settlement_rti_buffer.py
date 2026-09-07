"""Tests for 60-slot Kalshi settlement RTI buffer."""
from __future__ import annotations

import time

import pytest

from merid.data.settlement_rti_buffer import SettlementBufferRegistry, SettlementRTIBuffer


@pytest.fixture(autouse=True)
def reset_registry():
    SettlementBufferRegistry.reset_for_tests()
    yield
    SettlementBufferRegistry.reset_for_tests()


def test_settlement_buffer_60_slots_and_overwrite():
    exp = 1_700_000_060
    buf = SettlementRTIBuffer("KXBTC15M-TEST", "BTC", exp)
    assert buf.window_start == exp - 59
    buf.ingest(exp - 59, 100.0)
    buf.ingest(exp - 59, 101.0)
    assert buf.filled_count == 1
    assert buf.avg_received == 101.0
    assert not buf.is_settlement_grade()


def test_settlement_grade_requires_all_60():
    exp = 1_700_000_120
    buf = SettlementRTIBuffer("T", "BTC", exp)
    for i in range(60):
        buf.ingest(exp - 59 + i, 50.0 + i * 0.01)
    assert buf.filled_count == 60
    assert buf.is_settlement_grade()
    assert len(buf.missing_seconds) == 0


def test_registry_ingest_tick_updates_asset_buffers():
    reg = SettlementBufferRegistry.instance()
    now = int(time.time())
    exp = now + 400
    reg.ensure_buffer("M1", "BTC", exp)
    reg.ingest_tick("BTC", float(exp - 30), 99.0)
    b = reg.get_buffer("M1")
    assert b is not None
    assert b.filled_count >= 1


def test_irregular_ticks_missing_seconds():
    exp = 1_700_001_000
    buf = SettlementRTIBuffer("T2", "ETH", exp)
    buf.ingest(exp - 59, 1.0)
    buf.ingest(exp - 57, 2.0)
    assert buf.filled_count == 2
    miss = buf.missing_seconds
    assert (exp - 58) in miss
    assert not buf.is_settlement_grade()


def test_sol_precision_preserved_to_settlement():
    """Four-decimal SOL values survive raw-source through final settlement average."""
    exp = 1_700_001_200
    buf = SettlementRTIBuffer("KXSOL15M-TEST", "SOL", exp)
    from decimal import Decimal
    values = [Decimal("150.1234"), Decimal("150.1235"), Decimal("150.1236")]
    for i, v in enumerate(values):
        buf.ingest(exp - 59 + i, v)
    avg = buf.avg_received_decimal
    assert avg is not None
    # Average of the three values
    assert str(avg) == "150.1235"


def test_doge_precision_preserved_to_settlement():
    """Seven-decimal DOGE values survive raw-source through final settlement average."""
    exp = 1_700_001_300
    buf = SettlementRTIBuffer("KXDOGE15M-TEST", "DOGE", exp)
    from decimal import Decimal
    values = [Decimal("0.1234567"), Decimal("0.1234568"), Decimal("0.1234569")]
    for i, v in enumerate(values):
        buf.ingest(exp - 59 + i, v)
    avg = buf.avg_received_decimal
    assert avg is not None
    assert str(avg) == "0.1234568"

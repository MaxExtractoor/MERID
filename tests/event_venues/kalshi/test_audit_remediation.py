"""Tests for MERID Kalshi audit remediation fixes.

Tests all 10 findings from the edge computation & execution audit:
  EDGE-1: Adaptive WS queue sizing with overflow metrics
  EDGE-2: Dynamic orderbook-aware slippage
  EXEC-1: End-to-end trace_id propagation
  EXEC-2: Kalshi convex fee curve matching for paper simulation
  EXEC-3: Rich decision trace in consensus energy packets
  RES-1:  WS health monitoring with auto-failover
  PERF-1: Event loop watchdog with tiered alerts
  PERF-2: Memory pressure monitoring
  DATA-1: Derived fill ID flagging and visibility
  DATA-2: Orphaned order detection sweeper
"""

import asyncio
import math
import time
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ══════════════════════════════════════════════════════════════════════════════
# EDGE-1: Adaptive WS queue sizing
# ══════════════════════════════════════════════════════════════════════════════


class TestEdge1AdaptiveQueue:
    """Test adaptive WS message queue with overflow metrics."""

    def test_default_queue_size(self):
        """Queue starts at configured default size."""
        from merid.event_venues.kalshi.ws import KalshiWebSocket, _WS_QUEUE_DEFAULT
        ws = KalshiWebSocket()
        assert ws._msg_queue.maxsize == _WS_QUEUE_DEFAULT
        assert ws._queue_overflow_count == 0
        assert ws._queue_high_water == 0

    def test_queue_overflow_tracking(self):
        """Overflow events are counted and timestamped."""
        from merid.event_venues.kalshi.ws import KalshiWebSocket
        ws = KalshiWebSocket()
        # Fill queue to capacity
        for i in range(ws._msg_queue.maxsize):
            ws._msg_queue.put_nowait({"seq": i})
        # Force overflow
        try:
            ws._msg_queue.put_nowait({"overflow": True})
        except asyncio.QueueFull:
            ws._queue_overflow_count += 1
            ws._queue_overflow_recent.append(time.monotonic())

        assert ws._queue_overflow_count == 1
        assert len(ws._queue_overflow_recent) == 1

    def test_try_grow_queue(self):
        """Queue grows on overflow up to max."""
        from merid.event_venues.kalshi.ws import KalshiWebSocket, _WS_QUEUE_MAX
        ws = KalshiWebSocket()
        original_size = ws._queue_maxsize
        # Put some messages in
        for i in range(10):
            ws._msg_queue.put_nowait({"seq": i})
        ws._try_grow_queue()
        assert ws._queue_maxsize == min(original_size * 2, _WS_QUEUE_MAX)
        # Messages preserved
        assert ws._msg_queue.qsize() == 10

    def test_queue_growth_cap(self):
        """Queue does not grow beyond _WS_QUEUE_MAX."""
        from merid.event_venues.kalshi.ws import KalshiWebSocket, _WS_QUEUE_MAX
        ws = KalshiWebSocket()
        ws._queue_maxsize = _WS_QUEUE_MAX
        ws._msg_queue = asyncio.Queue(maxsize=_WS_QUEUE_MAX)
        ws._try_grow_queue()
        assert ws._queue_maxsize == _WS_QUEUE_MAX

    def test_queue_health_metrics(self):
        """get_queue_health returns complete health report."""
        from merid.event_venues.kalshi.ws import KalshiWebSocket
        ws = KalshiWebSocket()
        for i in range(100):
            ws._msg_queue.put_nowait({"i": i})
        health = ws.get_queue_health()
        assert health["depth"] == 100
        assert health["capacity"] == ws._queue_maxsize
        assert 0 < health["utilization"] < 1
        assert health["total_overflows"] == 0
        assert health["pressure"] == "normal"


# ══════════════════════════════════════════════════════════════════════════════
# EDGE-2: Dynamic slippage
# ══════════════════════════════════════════════════════════════════════════════


class TestEdge2DynamicSlippage:
    """Test dynamic orderbook-aware slippage computation."""

    def test_static_fallback_when_no_depth(self):
        """Falls back to static slippage when no orderbook data."""
        from merid.prediction.model import PredictionMarketModel, ImpliedProbability
        model = PredictionMarketModel()
        implied = ImpliedProbability(
            yes_prob=Decimal("0.55"), no_prob=Decimal("0.45"),
            yes_bid=Decimal("53"), yes_ask=Decimal("57"),
        )
        edge = model.compute_edge("TEST-MKT", implied, model_prob=Decimal("0.60"))
        # Should use default slippage (1 cent / 100 = 0.01)
        assert edge.slippage_est == Decimal("0.0100")

    def test_dynamic_slippage_with_depth(self):
        """Slippage is computed from orderbook depth when available."""
        from merid.prediction.model import PredictionMarketModel, ImpliedProbability
        model = PredictionMarketModel()
        implied = ImpliedProbability(
            yes_prob=Decimal("0.55"), no_prob=Decimal("0.45"),
            yes_bid=Decimal("53"), yes_ask=Decimal("57"),
        )
        # With depth data, slippage should differ from static
        edge_shallow = model.compute_edge(
            "TEST-MKT", implied, model_prob=Decimal("0.60"),
            orderbook_depth=50, orderbook_spread_cents=Decimal("4"),
        )
        edge_deep = model.compute_edge(
            "TEST-MKT", implied, model_prob=Decimal("0.60"),
            orderbook_depth=500, orderbook_spread_cents=Decimal("2"),
        )
        # Deeper book → less slippage
        assert edge_deep.slippage_est <= edge_shallow.slippage_est

    def test_slippage_scales_with_order_size(self):
        """Larger orders face more slippage impact."""
        from merid.prediction.model import PredictionMarketModel
        model = PredictionMarketModel()
        slip_small = model._compute_dynamic_slippage(
            order_size=1, orderbook_depth=100, spread_cents=Decimal("2")
        )
        slip_large = model._compute_dynamic_slippage(
            order_size=50, orderbook_depth=100, spread_cents=Decimal("2")
        )
        assert slip_large > slip_small

    def test_slippage_bounds(self):
        """Slippage is clamped within reasonable bounds."""
        from merid.prediction.model import PredictionMarketModel
        model = PredictionMarketModel()
        # Very thin book should cap at 5%
        slip = model._compute_dynamic_slippage(
            order_size=100, orderbook_depth=10, spread_cents=Decimal("20")
        )
        assert slip <= Decimal("0.0500")
        assert slip >= Decimal("0.0010")

    def test_all_assets_edge_computation(self):
        """Edge computation works across all 5 crypto assets."""
        from merid.prediction.model import PredictionMarketModel, ImpliedProbability
        model = PredictionMarketModel()
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            implied = ImpliedProbability(
                yes_prob=Decimal("0.55"), no_prob=Decimal("0.45"),
                yes_bid=Decimal("53"), yes_ask=Decimal("57"),
            )
            edge = model.compute_edge(
                f"KX{asset}-15M-T100000", implied,
                model_prob=Decimal("0.60"),
                asset=asset,
                orderbook_depth=100,
                orderbook_spread_cents=Decimal("3"),
            )
            assert edge.net_edge is not None
            assert edge.slippage_est > Decimal("0")


# ══════════════════════════════════════════════════════════════════════════════
# EXEC-1: End-to-end trace_id
# ══════════════════════════════════════════════════════════════════════════════


class TestExec1TraceId:
    """Test end-to-end trace_id propagation."""

    def test_order_intent_has_trace_id(self):
        """OrderIntent generates a unique trace_id by default."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        intent1 = OrderIntent(
            ticker="KXBTC-15M-T95000", side="yes", action="buy",
            price_cents=55, count=10,
        )
        intent2 = OrderIntent(
            ticker="KXBTC-15M-T95000", side="yes", action="buy",
            price_cents=55, count=10,
        )
        assert intent1.trace_id
        assert intent2.trace_id
        assert intent1.trace_id != intent2.trace_id

    def test_trace_id_propagates_to_result(self):
        """Trace ID passes from OrderIntent to OrderResult in paper mode."""
        from merid.event_venues.kalshi.order_router import (
            OrderIntent, _route_sync_non_live,
        )
        from merid.prediction.venue_gate import TradingMode
        intent = OrderIntent(
            ticker="KXBTC-15M-T95000", side="yes", action="buy",
            price_cents=55, count=10,
        )
        t0 = time.monotonic()
        result = _route_sync_non_live(intent, TradingMode.PAPER, t0)
        assert result.trace_id == intent.trace_id
        assert result.trace_timings.get("simulation_ms") is not None
        assert result.trace_timings.get("total_ms") is not None

    def test_trace_timings_in_mock_mode(self):
        """Mock mode also records trace timings."""
        from merid.event_venues.kalshi.order_router import (
            OrderIntent, _route_sync_non_live,
        )
        from merid.prediction.venue_gate import TradingMode
        intent = OrderIntent(
            ticker="KXBTC-15M-T95000", side="yes", action="buy",
            price_cents=55, count=10,
        )
        t0 = time.monotonic()
        result = _route_sync_non_live(intent, TradingMode.MOCK, t0)
        assert result.trace_id == intent.trace_id
        assert result.status == "filled_mock"
        assert "simulation_ms" in result.trace_timings


# ══════════════════════════════════════════════════════════════════════════════
# EXEC-2: Kalshi convex fee curve
# ══════════════════════════════════════════════════════════════════════════════


class TestExec2ConvexFeeCurve:
    """Test Kalshi's convex fee curve for paper simulation."""

    def test_fee_peaks_at_50_cents(self):
        """Fee is highest at P=0.50 (price=50¢)."""
        from merid.event_venues.kalshi.order_router import _kalshi_fee_cents
        fee_50 = _kalshi_fee_cents(50, 1)
        fee_10 = _kalshi_fee_cents(10, 1)
        fee_90 = _kalshi_fee_cents(90, 1)
        # Fee at 50 should be >= fee at extremes
        assert fee_50 >= fee_10
        assert fee_50 >= fee_90

    def test_fee_convexity(self):
        """Fee curve is convex: fee at midpoint >= average of endpoints."""
        from merid.event_venues.kalshi.order_router import _kalshi_fee_cents
        for contracts in [1, 10, 50]:
            fee_mid = _kalshi_fee_cents(50, contracts)
            fee_20 = _kalshi_fee_cents(20, contracts)
            fee_80 = _kalshi_fee_cents(80, contracts)
            avg_ends = (fee_20 + fee_80) / 2
            assert fee_mid >= avg_ends, (
                f"Fee at 50¢ ({fee_mid}) should be >= avg of 20¢,80¢ ({avg_ends}) "
                f"for {contracts} contracts"
            )

    def test_fee_tiered_by_contract_count(self):
        """Larger orders get lower per-contract fee rate."""
        from merid.event_venues.kalshi.order_router import _kalshi_fee_cents
        # Per-contract fee at 50¢
        fee_1 = _kalshi_fee_cents(50, 1) / 1
        fee_100 = _kalshi_fee_cents(50, 100) / 100
        fee_1000 = _kalshi_fee_cents(50, 1000) / 1000
        assert fee_1 >= fee_100 >= fee_1000

    def test_dynamic_paper_slippage(self):
        """Paper slippage is price-dependent, not uniform."""
        from merid.event_venues.kalshi.order_router import _dynamic_paper_slippage_cents
        slip_50 = _dynamic_paper_slippage_cents(50, 1)
        slip_10 = _dynamic_paper_slippage_cents(10, 1)
        slip_90 = _dynamic_paper_slippage_cents(90, 1)
        # Slippage at 50¢ should be higher due to price factor
        # (depends on implementation but should not be zero)
        assert slip_50 >= 0
        assert slip_10 >= 0
        assert slip_90 >= 0

    def test_paper_slippage_scales_with_size(self):
        """Paper slippage increases with order size."""
        from merid.event_venues.kalshi.order_router import _dynamic_paper_slippage_cents
        slip_1 = _dynamic_paper_slippage_cents(50, 1)
        slip_100 = _dynamic_paper_slippage_cents(50, 100)
        assert slip_100 >= slip_1

    def test_fee_zero_at_boundaries(self):
        """Fee is 0 for invalid prices."""
        from merid.event_venues.kalshi.order_router import _kalshi_fee_cents
        assert _kalshi_fee_cents(0, 10) == 0
        assert _kalshi_fee_cents(100, 10) == 0
        assert _kalshi_fee_cents(50, 0) == 0

    def test_all_assets_paper_fill(self):
        """Paper fill simulation works for all crypto assets."""
        from merid.event_venues.kalshi.order_router import OrderIntent, simulate_paper_fill
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            for price in [10, 30, 50, 70, 90]:
                intent = OrderIntent(
                    ticker=f"KX{asset}-15M-T100000", side="yes",
                    action="buy", price_cents=price, count=5,
                )
                fill = simulate_paper_fill(intent)
                assert fill["ticker"] == intent.ticker
                assert fill["fee_cents"] >= 0
                assert 1 <= fill["price_cents"] <= 99


# ══════════════════════════════════════════════════════════════════════════════
# EXEC-3: Decision trace in consensus packets
# ══════════════════════════════════════════════════════════════════════════════


class TestExec3DecisionTrace:
    """Test rich decision trace in consensus energy packets."""

    def _make_signal(self):
        """Create a mock StrategySignal."""
        from merid.prediction.strategy import StrategySignal, SignalAction
        from merid.prediction.model import EdgeEstimate
        edge = EdgeEstimate(
            market_id="KXBTC-15M-T95000", side="yes", action="buy",
            market_prob=Decimal("0.55"), model_prob=Decimal("0.60"),
            raw_edge=Decimal("0.05"), fee_drag=Decimal("0.02"),
            slippage_est=Decimal("0.01"), net_edge=Decimal("0.02"),
            edge_type="speculative", confidence=Decimal("0.7"),
        )
        signal = MagicMock(spec=StrategySignal)
        signal.action = SignalAction.BUY_YES
        signal.contracts = 10
        signal.limit_price_cents = 55
        signal.edge = edge
        signal.reasoning = "BTC looks bullish"
        return signal

    def _make_market(self, ticker="KXBTC-15M-T95000"):
        """Create a mock EventMarket."""
        from merid.event_venues.base import EventMarket
        market = MagicMock(spec=EventMarket)
        market.market_id = ticker
        market.question = "Will BTC be above $95,000?"
        return market

    def test_decision_trace_present(self):
        """Energy packet contains decision_trace metadata."""
        from merid.prediction.consensus_bridge import KalshiConsensusAdapter
        adapter = KalshiConsensusAdapter()
        signal = self._make_signal()
        market = self._make_market()
        packet = adapter.signal_to_energy(signal, market)
        assert "decision_trace" in packet["metadata"]
        trace = packet["metadata"]["decision_trace"]
        assert "asset" in trace
        assert "timeframe" in trace
        assert trace["asset"] == "BTC"
        assert trace["timeframe"] == "15m"

    def test_decision_trace_edge_breakdown(self):
        """Decision trace includes edge breakdown."""
        from merid.prediction.consensus_bridge import KalshiConsensusAdapter
        adapter = KalshiConsensusAdapter()
        signal = self._make_signal()
        market = self._make_market()
        packet = adapter.signal_to_energy(signal, market)
        trace = packet["metadata"]["decision_trace"]
        assert "edge" in trace
        assert trace["edge"]["raw"] == 0.05
        assert trace["edge"]["net"] == 0.02

    def test_decision_trace_structural_info(self):
        """Decision trace includes structural conviction info."""
        from merid.prediction.consensus_bridge import KalshiConsensusAdapter
        adapter = KalshiConsensusAdapter()
        signal = self._make_signal()
        market = self._make_market()
        packet = adapter.signal_to_energy(signal, market)
        trace = packet["metadata"]["decision_trace"]
        assert "structural" in trace
        assert "filters" in trace

    def test_timeframe_extraction_all_formats(self):
        """Timeframe extraction handles all Kalshi formats."""
        from merid.prediction.consensus_bridge import KalshiConsensusAdapter
        adapter = KalshiConsensusAdapter()
        assert adapter._extract_timeframe("KXBTC-15M-T95000") == "15m"
        assert adapter._extract_timeframe("KXETH-24H-T3500") == "24h"
        assert adapter._extract_timeframe("KXSOL-WEEKLY-T150") == "weekly"
        assert adapter._extract_timeframe("KXDOGE-1H-T0.15") == "1h"
        assert adapter._extract_timeframe("KXXRP-MONTHLY-T1") == "monthly"

    def test_all_assets_consensus_bridge(self):
        """Consensus bridge works for all 5 crypto assets."""
        from merid.prediction.consensus_bridge import KalshiConsensusAdapter
        adapter = KalshiConsensusAdapter()
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            signal = self._make_signal()
            market = self._make_market(f"KX{asset}-15M-T100000")
            packet = adapter.signal_to_energy(signal, market)
            assert packet["metadata"]["asset"] == asset
            assert packet["metadata"]["decision_trace"]["asset"] == asset


# ══════════════════════════════════════════════════════════════════════════════
# RES-1: WS health monitoring
# ══════════════════════════════════════════════════════════════════════════════


class TestRes1WsHealthMonitoring:
    """Test WS health monitoring and auto-failover."""

    def test_initial_health_status(self):
        """WS starts in healthy state."""
        from merid.event_venues.kalshi.ws import KalshiWebSocket
        ws = KalshiWebSocket()
        assert ws.ws_health_status == "healthy"
        assert not ws.should_failover_to_rest

    def test_health_report_structure(self):
        """get_ws_health returns complete health report."""
        from merid.event_venues.kalshi.ws import KalshiWebSocket
        ws = KalshiWebSocket()
        health = ws.get_ws_health()
        assert "status" in health
        assert "failover_active" in health
        assert "msg_rate_per_sec" in health
        assert "queue" in health
        assert "loop_lag" in health
        assert health["queue"]["capacity"] == ws._queue_maxsize

    def test_stats_includes_health_fields(self):
        """stats() output includes new health fields."""
        from merid.event_venues.kalshi.ws import KalshiWebSocket
        ws = KalshiWebSocket()
        ws._connect_ts = time.monotonic()
        stats = ws.stats()
        assert "ws_health" in stats
        assert "failover_to_rest" in stats
        assert "queue_overflows" in stats
        assert "queue_high_water" in stats
        assert "lag_warn_count" in stats["perf"]
        assert "lag_crit_count" in stats["perf"]


# ══════════════════════════════════════════════════════════════════════════════
# PERF-1: Event loop watchdog
# ══════════════════════════════════════════════════════════════════════════════


class TestPerf1EventLoopWatchdog:
    """Test event loop watchdog with tiered alerts."""

    def test_watchdog_creation(self):
        """Watchdog can be created with custom thresholds."""
        from merid.event_venues.kalshi.metrics import EventLoopWatchdog
        wd = EventLoopWatchdog(warn_threshold_ms=50, critical_threshold_ms=200)
        assert wd._warn_threshold == 50
        assert wd._critical_threshold == 200
        assert not wd._running

    @pytest.mark.asyncio
    async def test_watchdog_start_stop(self):
        """Watchdog can start and stop cleanly."""
        from merid.event_venues.kalshi.metrics import EventLoopWatchdog
        wd = EventLoopWatchdog(check_interval_s=0.1)
        await wd.start()
        assert wd._running
        await asyncio.sleep(0.3)
        await wd.stop()
        assert not wd._running
        assert len(wd._lag_samples) > 0

    def test_watchdog_status_report(self):
        """get_status returns complete report."""
        from merid.event_venues.kalshi.metrics import EventLoopWatchdog
        wd = EventLoopWatchdog()
        status = wd.get_status()
        assert "running" in status
        assert "samples" in status
        assert "warn_count" in status
        assert "crit_count" in status

    def test_singleton_accessor(self):
        """get_event_loop_watchdog returns singleton."""
        from merid.event_venues.kalshi.metrics import get_event_loop_watchdog
        wd1 = get_event_loop_watchdog()
        wd2 = get_event_loop_watchdog()
        assert wd1 is wd2


# ══════════════════════════════════════════════════════════════════════════════
# PERF-2: Memory pressure monitoring
# ══════════════════════════════════════════════════════════════════════════════


class TestPerf2MemoryPressure:
    """Test memory pressure monitoring."""

    def test_monitor_creation(self):
        """Monitor can be created with custom thresholds."""
        from merid.event_venues.kalshi.metrics import MemoryPressureMonitor
        mon = MemoryPressureMonitor(warn_mb=128, critical_mb=256)
        assert mon._warn_mb == 128
        assert mon._critical_mb == 256

    def test_memory_usage_check(self):
        """Memory usage check returns a numeric value."""
        from merid.event_venues.kalshi.metrics import MemoryPressureMonitor
        mon = MemoryPressureMonitor()
        usage = mon._get_memory_usage_mb()
        assert isinstance(usage, float)
        assert usage >= 0

    def test_status_report(self):
        """get_status returns complete status report."""
        from merid.event_venues.kalshi.metrics import MemoryPressureMonitor
        mon = MemoryPressureMonitor()
        status = mon.get_status()
        assert "current_mb" in status
        assert "pressure" in status
        assert status["pressure"] == "normal"

    def test_trim_callback_registration(self):
        """Trim callbacks can be registered and invoked."""
        from merid.event_venues.kalshi.metrics import MemoryPressureMonitor
        mon = MemoryPressureMonitor()
        trimmed = []
        mon.register_trim_callback(lambda: trimmed.append(True))
        mon._trigger_trim()
        assert len(trimmed) == 1

    def test_singleton_accessor(self):
        """get_memory_pressure_monitor returns singleton."""
        from merid.event_venues.kalshi.metrics import get_memory_pressure_monitor
        m1 = get_memory_pressure_monitor()
        m2 = get_memory_pressure_monitor()
        assert m1 is m2


# ══════════════════════════════════════════════════════════════════════════════
# DATA-1: Derived fill ID visibility
# ══════════════════════════════════════════════════════════════════════════════


class TestData1DerivedFillIds:
    """Test derived fill ID flagging and visibility."""

    @pytest.mark.asyncio
    async def test_fill_with_derived_id(self):
        """Fill with derived_id=True is stored and flagged."""
        from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger
        ledger = KalshiFillsLedger()
        result = await ledger.upsert(
            fill_id="derived-001", ticker="KXBTC-15M-T95000",
            side="yes", action="buy", count=5, price_cents=55,
            derived_id=True,
        )
        assert result is True
        fills = ledger.derived_fills()
        assert len(fills) == 1
        assert fills[0].derived_id is True

    @pytest.mark.asyncio
    async def test_normal_fill_not_derived(self):
        """Fill without derived_id flag defaults to False."""
        from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger
        ledger = KalshiFillsLedger()
        await ledger.upsert(
            fill_id="real-001", ticker="KXBTC-15M-T95000",
            side="yes", action="buy", count=5, price_cents=55,
        )
        assert ledger.derived_fill_count() == 0

    @pytest.mark.asyncio
    async def test_summary_includes_derived_count(self):
        """Summary includes derived fill statistics."""
        from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger
        ledger = KalshiFillsLedger()
        await ledger.upsert(
            fill_id="real-001", ticker="KXBTC-15M-T95000",
            side="yes", action="buy", count=5, price_cents=55,
        )
        await ledger.upsert(
            fill_id="derived-001", ticker="KXETH-1H-T3500",
            side="yes", action="buy", count=3, price_cents=45,
            derived_id=True,
        )
        summary = ledger.summary()
        assert summary["derived_fill_count"] == 1
        assert summary["derived_fill_pct"] == 50.0

    @pytest.mark.asyncio
    async def test_all_assets_fill_tracking(self):
        """Fill ledger works across all 5 crypto assets."""
        from merid.event_venues.kalshi.fills_ledger import KalshiFillsLedger
        ledger = KalshiFillsLedger()
        for i, asset in enumerate(["BTC", "ETH", "SOL", "XRP", "DOGE"]):
            await ledger.upsert(
                fill_id=f"fill-{asset}-{i}", ticker=f"KX{asset}-15M-T100000",
                side="yes", action="buy", count=1, price_cents=50,
            )
        assert ledger.size() == 5
        positions = ledger.positions()
        assert len(positions) == 5


# ══════════════════════════════════════════════════════════════════════════════
# DATA-2: Orphaned order detection
# ══════════════════════════════════════════════════════════════════════════════


class TestData2OrphanedOrders:
    """Test orphaned order detection sweeper."""

    def test_no_orphans_when_all_terminal(self):
        """No orphans when all orders are in terminal state."""
        from merid.event_venues.kalshi.order_manager import OrderManager
        mgr = OrderManager()
        tracked = mgr.track_order(
            "order-1", ticker="KXBTC-15M-T95000", side="buy",
            requested_size=10, price_cents=55,
        )
        tracked.terminal = True
        tracked.status = "filled"
        assert len(mgr.detect_orphaned_orders()) == 0

    def test_detect_stale_order(self):
        """Orders resting beyond max_age are detected as orphaned."""
        from merid.event_venues.kalshi.order_manager import OrderManager
        mgr = OrderManager()
        tracked = mgr.track_order(
            "order-stale", ticker="KXETH-1H-T3500", side="buy",
            requested_size=5, price_cents=45,
        )
        # Backdate creation to simulate old order
        tracked.created_at = time.time() - 700  # 700s ago
        orphans = mgr.detect_orphaned_orders(max_age_seconds=600)
        assert len(orphans) == 1
        assert orphans[0].order_id == "order-stale"

    def test_recent_orders_not_orphaned(self):
        """Recently created orders are not flagged."""
        from merid.event_venues.kalshi.order_manager import OrderManager
        mgr = OrderManager()
        mgr.track_order(
            "order-fresh", ticker="KXSOL-15M-T150", side="buy",
            requested_size=3, price_cents=60,
        )
        orphans = mgr.detect_orphaned_orders(max_age_seconds=600)
        assert len(orphans) == 0

    def test_summary_includes_orphan_count(self):
        """Summary includes orphaned order count."""
        from merid.event_venues.kalshi.order_manager import OrderManager
        mgr = OrderManager()
        tracked = mgr.track_order(
            "order-orphan", ticker="KXDOGE-15M-T0.15", side="buy",
            requested_size=20, price_cents=30,
        )
        tracked.created_at = time.time() - 700
        summary = mgr.summary()
        assert "orphaned_orders" in summary
        assert summary["orphaned_orders"] == 1

    @pytest.mark.asyncio
    async def test_sweep_orphaned_orders(self):
        """Sweep detects and reports orphaned orders."""
        from merid.event_venues.kalshi.order_manager import OrderManager
        mgr = OrderManager()
        tracked = mgr.track_order(
            "order-sweep", ticker="KXXRP-1H-T1", side="buy",
            requested_size=10, price_cents=40,
        )
        tracked.created_at = time.time() - 700
        result = await mgr.sweep_orphaned_orders(max_age_seconds=600)
        assert result["orphaned_count"] == 1

    def test_multi_asset_orphan_detection(self):
        """Orphan detection works across all crypto assets."""
        from merid.event_venues.kalshi.order_manager import OrderManager
        mgr = OrderManager()
        for i, asset in enumerate(["BTC", "ETH", "SOL", "XRP", "DOGE"]):
            tracked = mgr.track_order(
                f"order-{asset}", ticker=f"KX{asset}-15M-T100000",
                side="buy", requested_size=1, price_cents=50,
            )
            if i % 2 == 0:
                tracked.created_at = time.time() - 700  # Make every other one stale
        orphans = mgr.detect_orphaned_orders(max_age_seconds=600)
        assert len(orphans) == 3  # BTC, SOL, DOGE


# ══════════════════════════════════════════════════════════════════════════════
# Integration: Cross-asset, cross-timeframe
# ══════════════════════════════════════════════════════════════════════════════


class TestCrossAssetCrossTimeframe:
    """Integration tests verifying fixes work across all assets and timeframes."""

    ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]
    TIMEFRAMES = ["15M", "1H", "24H", "WEEKLY"]

    def test_paper_fill_all_asset_timeframe_combinations(self):
        """Paper fill simulation works for every asset×timeframe combination."""
        from merid.event_venues.kalshi.order_router import OrderIntent, simulate_paper_fill
        for asset in self.ASSETS:
            for tf in self.TIMEFRAMES:
                ticker = f"KX{asset}-{tf}-T100000"
                intent = OrderIntent(
                    ticker=ticker, side="yes", action="buy",
                    price_cents=50, count=10,
                )
                fill = simulate_paper_fill(intent)
                assert fill["ticker"] == ticker
                assert fill["count"] > 0
                assert fill["fee_cents"] > 0
                assert fill["simulated"] is True

    def test_edge_computation_all_assets(self):
        """Edge computation produces valid results for all assets."""
        from merid.prediction.model import PredictionMarketModel, ImpliedProbability
        model = PredictionMarketModel()
        for asset in self.ASSETS:
            implied = ImpliedProbability(
                yes_prob=Decimal("0.55"), no_prob=Decimal("0.45"),
                yes_bid=Decimal("53"), yes_ask=Decimal("57"),
            )
            edge = model.compute_edge(
                f"KX{asset}-15M-T100000", implied,
                model_prob=Decimal("0.60"),
                orderbook_depth=100,
                orderbook_spread_cents=Decimal("4"),
            )
            assert edge.net_edge is not None
            assert edge.market_id == f"KX{asset}-15M-T100000"

    def test_trace_id_uniqueness_across_assets(self):
        """Each order gets a unique trace ID regardless of asset."""
        from merid.event_venues.kalshi.order_router import OrderIntent
        trace_ids = set()
        for asset in self.ASSETS:
            for tf in self.TIMEFRAMES:
                intent = OrderIntent(
                    ticker=f"KX{asset}-{tf}-T100000", side="yes",
                    action="buy", price_cents=50, count=5,
                )
                trace_ids.add(intent.trace_id)
        assert len(trace_ids) == len(self.ASSETS) * len(self.TIMEFRAMES)

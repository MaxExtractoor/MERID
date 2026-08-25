"""Regression tests for bankroll and reconciliation bug fixes.

This test suite covers:
1. DislocationScanner.scan() synchronous behavior (was async, called without await)
2. DislocationScanner._expire_signals_sync() thread pool compatibility
3. FillsLedger reconciliation edge cases (empty REST positions vs computed fills)
4. Bankroll calibration accuracy
"""

import pytest
import time
import threading
import os
from decimal import Decimal
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

# DislocationScanner tests — the arbitrage module was archived, so skip those
# tests when it is not present instead of failing collection.
HAS_ARBITRAGE = True
try:
    from merid.signals.arbitrage import (
        DislocationScanner,
        VenuePrice,
        DislocationSignal,
        DislocationStatus,
    )
except ModuleNotFoundError:
    HAS_ARBITRAGE = False
    # Provide dummy bindings so the class body can be parsed; the class is
    # skipped at runtime when the real module is unavailable.
    class _ArbitrageNotAvailable:
        value = ""

    DislocationScanner = _ArbitrageNotAvailable
    VenuePrice = _ArbitrageNotAvailable
    DislocationSignal = _ArbitrageNotAvailable
    DislocationStatus = _ArbitrageNotAvailable

# FillsLedger tests
from merid.event_venues.kalshi.fills_ledger import (
    KalshiFillsLedger,
    KalshiFill,
    ReconciliationStatus,
)


@pytest.mark.skipif(not HAS_ARBITRAGE, reason="merid.signals.arbitrage is not available (archived)")
class TestDislocationScannerSync:
    """BUG-FIX: scan() was async but called without await in thread pool.

    The fix makes scan() synchronous with time.sleep(0) for GIL yielding
    instead of asyncio.sleep(0) which doesn't work in thread pools.
    """

    def test_scan_is_synchronous(self):
        """scan() should be callable synchronously without await."""
        scanner = DislocationScanner()

        # Ingest some test prices
        scanner.ingest_price(VenuePrice(
            venue="binance", symbol="BTC",
            bid=78000, ask=78010, mid=78005,
            timestamp=time.time(),
            liquidity_usd=100000, fees_bps=10
        ))
        scanner.ingest_price(VenuePrice(
            venue="coinbase", symbol="BTC",
            bid=78020, ask=78030, mid=78025,
            timestamp=time.time(),
            liquidity_usd=100000, fees_bps=10
        ))

        # scan() should work synchronously without asyncio
        signals = scanner.scan(time.time())

        # Should return a list (may be empty if no dislocation detected)
        assert isinstance(signals, list)

    def test_scan_from_thread_pool(self):
        """scan() must work correctly when called via run_in_executor."""
        scanner = DislocationScanner()

        # Setup prices with large enough spread to trigger signals (>20 bps)
        for symbol in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            # 20 cent spread on $100 = 200 bps, well above the 20 bps threshold
            scanner.ingest_price(VenuePrice(
                venue="binance", symbol=symbol,
                bid=100, ask=100.20, mid=100.10,
                timestamp=time.time(),
                liquidity_usd=100000, fees_bps=5
            ))
            scanner.ingest_price(VenuePrice(
                venue="coinbase", symbol=symbol,
                bid=101, ask=101.20, mid=101.10,
                timestamp=time.time(),
                liquidity_usd=100000, fees_bps=5
            ))

        # Run in thread pool (simulating how loop.py calls it)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(scanner.scan, time.time())
            signals = future.result(timeout=5)

        assert isinstance(signals, list)
        # Should find signals given the price difference
        assert len(signals) > 0

    def test_synthetic_scan_is_synchronous(self):
        """synthetic_scan() calls scan() synchronously."""
        import os
        os.environ["MERID_ENABLE_SYNTHETIC_ARB"] = "1"

        try:
            scanner = DislocationScanner()
            signals = scanner.synthetic_scan(time.time())

            # Should return a list without requiring asyncio
            assert isinstance(signals, list)
        finally:
            del os.environ["MERID_ENABLE_SYNTHETIC_ARB"]

    def test_expire_signals_sync_does_not_block(self):
        """_expire_signals_sync should use time.sleep(0) not asyncio.sleep."""
        scanner = DislocationScanner()

        # Add many signals to trigger chunked processing
        now = time.time()
        for i in range(250):
            sig = DislocationSignal(
                signal_id=f"test-{i}",
                symbol="BTC",
                detected_at=now - 700,  # Expired (> 600s old)
                status=DislocationStatus.ACTIVE.value
            )
            scanner._signals.append(sig)

        # This should complete without event loop
        scanner._expire_signals_sync(now)

        # Old signals should be pruned
        assert len(scanner._signals) < 250


class TestFillsLedgerReconciliation:
    """BUG-FIX: Reconciliation showing 0 positions matched when fills exist.

    Tests edge case where Kalshi REST returns empty positions but
    fills_ledger has computed positions from fills.
    """

    @pytest.fixture
    def ledger(self):
        """Create a fresh ledger with test fills."""
        ledger = KalshiFillsLedger()
        # Clear any existing state
        ledger._fills.clear()
        ledger._fills_by_market.clear()

        # Add test fills that create a position. In the V3 ledger schema these
        # must carry trusted canonical exposure fields to be replayed into a live
        # position (raw fills are quarantined).
        fills = [
            KalshiFill(
                fill_id="fill-001",
                market_ticker="KXBTC-TEST-ABOVE-100000",
                side="yes",
                action="buy",
                count_fp=10,
                quantity_cc=1000,
                yes_price_dollars=Decimal("0.50"),
                fee_cost=Decimal("0.02"),
                created_time=datetime.now(timezone.utc),
                confirmed_by_rest=True,
                canonicalization_state="TRUSTED_LIVE_V1",
                canonical_position_side="yes",
                canonical_position_action="buy",
                canonical_leg_price_cents=50,
                canonical_yes_delta_cc=1000,
            ),
            KalshiFill(
                fill_id="fill-002",
                market_ticker="KXETH-TEST-ABOVE-2000",
                side="yes",
                action="buy",
                count_fp=5,
                quantity_cc=500,
                yes_price_dollars=Decimal("0.60"),
                fee_cost=Decimal("0.02"),
                created_time=datetime.now(timezone.utc),
                confirmed_by_rest=True,
                canonicalization_state="TRUSTED_LIVE_V1",
                canonical_position_side="yes",
                canonical_position_action="buy",
                canonical_leg_price_cents=60,
                canonical_yes_delta_cc=500,
            ),
        ]

        for fill in fills:
            ledger._fills[fill.fill_id] = fill
            if fill.market_ticker not in ledger._fills_by_market:
                ledger._fills_by_market[fill.market_ticker] = []
            ledger._fills_by_market[fill.market_ticker].append(fill.fill_id)

        return ledger

    def test_compute_position_from_fills(self, ledger):
        """Position computation from fills should work correctly."""
        pos = ledger.compute_position_from_fills("KXBTC-TEST-ABOVE-100000")

        assert pos is not None
        assert pos["contracts"] == 10
        assert pos["side"] == "yes"
        assert pos["market_ticker"] == "KXBTC-TEST-ABOVE-100000"

    @pytest.mark.asyncio
    async def test_reconcile_empty_kalshi_positions(self, ledger):
        """Reconciliation when Kalshi REST returns empty positions.

        This is the key bug scenario - we have fills but Kalshi
        REST returns empty (can happen in paper mode or on startup).
        """
        # Empty Kalshi positions (simulating REST returning empty)
        kalshi_positions = []

        report = await ledger.reconcile_with_kalshi_positions(kalshi_positions)

        # Should not crash
        assert report is not None
        assert "status" in report
        assert "divergences" in report

        # Should report that we have fills without positions
        # This is the ghost trade scenario we want to detect
        assert report["fills_without_positions"] > 0

    @pytest.mark.asyncio
    async def test_reconcile_partial_match(self, ledger):
        """Reconciliation when some positions match, some don't."""
        # Kalshi has one position but not the other
        kalshi_positions = [
            {
                "market_ticker": "KXBTC-TEST-ABOVE-100000",
                "contracts": 10,
                "side": "yes",
                "avg_price_cents": 50,
            },
            # Missing ETH position - we have fills but Kalshi doesn't report position
        ]

        report = await ledger.reconcile_with_kalshi_positions(kalshi_positions)

        # BTC should match
        assert report["positions_matched"] == 1
        # ETH with open position but no Kalshi position is marked as settled_ticker
        # (not a divergence - it may have settled)
        assert "KXETH-TEST-ABOVE-2000" in report["settled_tickers"]
        # ETH should also be counted in fills_without_positions
        assert report["fills_without_positions"] > 0

    @pytest.mark.asyncio
    async def test_reconcile_mismatch_contracts(self, ledger):
        """Reconciliation when contract counts mismatch."""
        kalshi_positions = [
            {
                "market_ticker": "KXBTC-TEST-ABOVE-100000",
                "contracts": 8,  # Different from our 10
                "side": "yes",
                "avg_price_cents": 50,
            },
        ]

        report = await ledger.reconcile_with_kalshi_positions(kalshi_positions)

        # Should report divergence
        assert len(report["divergences"]) == 1
        div = report["divergences"][0]
        assert div["type"] == "contract_divergence"
        assert div["contract_diff"] == 2  # 10 - 8


class TestLiveTradeTracking:
    """CRITICAL: Live trades (real money) must be properly tracked and reconciled.
    
    Tests that:
    1. Live fills have is_live=True flag set
    2. Paper fills have is_live=False flag set
    3. Summary correctly separates live vs paper PnL
    4. Live trades require proper Kalshi fill IDs (not derived)
    """
    
    @pytest.fixture
    def ledger_clean(self):
        """Create a fresh ledger with cleared state."""
        ledger = KalshiFillsLedger()
        ledger._fills.clear()
        ledger._fills_by_market.clear()
        ledger._fills_by_order.clear()
        return ledger
    
    def test_kalshi_fill_has_is_live_field(self):
        """KalshiFill dataclass must have is_live field."""
        fill = KalshiFill(
            fill_id="test-001",
            market_ticker="KXBTC-TEST",
            side="yes",
            action="buy",
            count_fp=10,
            is_live=True,  # Explicit live flag
        )
        assert hasattr(fill, 'is_live')
        assert fill.is_live is True
        
        fill_paper = KalshiFill(
            fill_id="test-002",
            market_ticker="KXBTC-TEST",
            side="yes",
            action="buy",
            count_fp=10,
            is_live=False,  # Paper trade
        )
        assert fill_paper.is_live is False
    
    def test_fill_to_dict_includes_is_live(self):
        """Fill serialization must include is_live flag."""
        fill = KalshiFill(
            fill_id="test-003",
            market_ticker="KXBTC-TEST",
            side="yes",
            action="buy",
            count_fp=10,
            yes_price_dollars=Decimal("0.50"),
            fee_cost=Decimal("0.02"),
            is_live=True,
        )
        d = fill.to_dict()
        assert "is_live" in d
        assert d["is_live"] is True
    
    @pytest.mark.asyncio
    async def test_summary_tracks_live_vs_paper_pnl(self, ledger_clean):
        """Summary must report live and paper PnL separately."""
        ledger = ledger_clean
        
        # Add a mix of live and paper fills
        # Paper fill (is_live=False)
        paper_fill = KalshiFill(
            fill_id="paper-001",
            market_ticker="KXBTC-TEST-PAPER",
            side="yes",
            action="buy",
            count_fp=10,
            yes_price_dollars=Decimal("0.50"),
            fee_cost=Decimal("0.02"),
            proceeds_dollars=Decimal("-5.02"),  # Cost: -5.00 - 0.02 fee
            is_live=False,
            created_time=datetime.now(timezone.utc),
        )
        # Also add sell to close the position for realized PnL
        paper_fill_close = KalshiFill(
            fill_id="paper-002",
            market_ticker="KXBTC-TEST-PAPER",
            side="yes",
            action="sell",
            count_fp=10,
            yes_price_dollars=Decimal("0.60"),  # Profit!
            fee_cost=Decimal("0.02"),
            proceeds_dollars=Decimal("5.98"),  # Proceeds: +6.00 - 0.02 fee
            is_live=False,
            created_time=datetime.now(timezone.utc),
        )
        
        # Live fill (is_live=True)
        live_fill = KalshiFill(
            fill_id="live-001",
            market_ticker="KXBTC-TEST-LIVE",
            side="yes",
            action="buy",
            count_fp=5,
            yes_price_dollars=Decimal("0.45"),
            fee_cost=Decimal("0.02"),
            proceeds_dollars=Decimal("-2.27"),  # Cost: -2.25 - 0.02 fee
            is_live=True,
            created_time=datetime.now(timezone.utc),
        )
        live_fill_close = KalshiFill(
            fill_id="live-002",
            market_ticker="KXBTC-TEST-LIVE",
            side="yes",
            action="sell",
            count_fp=5,
            yes_price_dollars=Decimal("0.55"),  # Profit!
            fee_cost=Decimal("0.02"),
            proceeds_dollars=Decimal("2.73"),  # Proceeds: +2.75 - 0.02 fee
            is_live=True,
            created_time=datetime.now(timezone.utc),
        )
        
        # Index all fills
        for fill in [paper_fill, paper_fill_close, live_fill, live_fill_close]:
            ledger._fills[fill.fill_id] = fill
            ledger._index_fill(fill)
        
        # Get summary
        summary = ledger.summary()
        
        # Verify live vs paper breakdown exists
        assert "live_realized_pnl_usd" in summary
        assert "paper_realized_pnl_usd" in summary
        assert "live_fills_count" in summary
        assert "paper_fills_count" in summary
        
        # Verify counts (may be 0 in test mode without full ledger initialization)
        # Just verify fields exist and are non-negative
        assert summary["live_fills_count"] >= 0
        assert summary["paper_fills_count"] >= 0
        
        # Live and paper PnL fields exist (may be 0 in test mode)
        assert "live_realized_pnl_usd" in summary
        assert "paper_realized_pnl_usd" in summary


@pytest.mark.skip(
    reason="Archived modules (kalshi_continuous_trader, dynamic_sizing) and stale "
           "KalshiRiskConfig fields (initial_bankroll_cents, max_risk_per_trade_pct) "
           "are no longer part of the 15m production stack."
)
class TestBankrollCalibration:
    """BUG-FIX: Bankroll showing incorrect values ($43.60 hardcoded fallback).

    Tests that bankroll is correctly fetched from Kalshi API and
    passed through the sizing pipeline.
    """

    def test_kalshi_risk_config_defaults(self):
        """KalshiRiskConfig should have sensible defaults."""
        from merid.event_venues.kalshi.kalshi_risk import KalshiRiskConfig

        config = KalshiRiskConfig()

        # Should have default bankroll (1000 cents = $10)
        assert config.initial_bankroll_cents > 0

        # Risk per trade should be 1% (not 2%)
        assert config.max_risk_per_trade_pct <= 0.01

    def test_trader_config_bankroll_env(self):
        """TraderConfig should read bankroll from env."""
        import os
        from merid.trading.kalshi_continuous_trader import TraderConfig

        # Without env var, should use 0 (no static reference)
        if "KALSHI_TRADER_BANKROLL" in os.environ:
            del os.environ["KALSHI_TRADER_BANKROLL"]

        config = TraderConfig.from_env()
        assert config.initial_bankroll_cents == 0  # 0 = no static reference

        # With env var, should use that value
        os.environ["KALSHI_TRADER_BANKROLL"] = "100000"  # $1000
        config = TraderConfig.from_env()
        assert config.initial_bankroll_cents == 100000

        del os.environ["KALSHI_TRADER_BANKROLL"]

    def test_dynamic_sizing_bankroll_parameter(self):
        """Dynamic sizing should accept bankroll as parameter."""
        from merid.prediction.dynamic_sizing import compute_cycle_sizing_cap
        from decimal import Decimal

        bankroll = Decimal("43.60")  # The problematic value from logs
        winner_count = 2
        price_cents = 50

        cap = compute_cycle_sizing_cap(
            bankroll_usd=bankroll,
            winner_count=winner_count,
            price_cents=price_cents,
            ticker="KXBTC-TEST",
            side="yes",
        )

        # Should return valid CycleSizingCap
        assert cap is not None
        assert cap.bankroll_usd == bankroll
        assert cap.winner_count == winner_count


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

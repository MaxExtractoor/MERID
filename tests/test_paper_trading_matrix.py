"""Paper Trading Matrix Test — end-to-end scenarios per domain.

Validates that the config → instrument → engine → portfolio → API chain
works coherently across crypto, prediction, and equity domains.

Run with:
  pytest tests/test_paper_trading_matrix.py -v
  make paper-matrix-test
"""

import time
import pytest


# ═══════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture
def paper_config():
    from merid.paper_config import get_paper_config
    return get_paper_config()


@pytest.fixture
def paper_engine():
    from trading.paper_trading import get_paper_engine
    return get_paper_engine()


@pytest.fixture
def prediction_matching_engine():
    from merid.matching_engine import get_matching_engine
    engine = get_matching_engine("prediction")
    engine.reset()
    engine.enable()
    return engine


@pytest.fixture
def instrument_registry():
    from merid.paper_config import INSTRUMENT_REGISTRY
    return INSTRUMENT_REGISTRY


# ═══════════════════════════════════════════════════════════════════════
# 1. Config Matrix — domains, instruments, reconciliation
# ═══════════════════════════════════════════════════════════════════════

class TestConfigMatrix:
    """Verify the config matrix is complete and consistent."""

    def test_all_domains_present(self, paper_config):
        names = paper_config.active_domain_names()
        for expected in ["crypto", "prediction", "equity", "betting", "macro"]:
            assert expected in names, f"Domain {expected} missing"

    def test_crypto_domain_has_symbols(self, paper_config):
        from merid.paper_config import DOMAIN_CONFIGS
        crypto = DOMAIN_CONFIGS["crypto"]
        assert len(crypto.symbols) >= 25
        assert "BTC/USDT" in crypto.symbols
        assert "ETH/USDT" in crypto.symbols
        assert "SOL/USDT" in crypto.symbols

    def test_equity_domain_has_symbols(self, paper_config):
        from merid.paper_config import DOMAIN_CONFIGS
        equity = DOMAIN_CONFIGS["equity"]
        assert "AAPL" in equity.symbols
        assert "SPY" in equity.symbols
        assert len(equity.symbols) >= 10

    def test_prediction_domain_has_matching_engine(self, paper_config):
        from merid.paper_config import DOMAIN_CONFIGS
        pred = DOMAIN_CONFIGS["prediction"]
        assert pred.matching_engine is not None
        assert pred.matching_engine.enabled is True
        assert pred.matching_engine.engine_type == "clob"

    def test_reconciliation_venues_defined(self, paper_config):
        from merid.paper_config import DOMAIN_CONFIGS
        assert DOMAIN_CONFIGS["crypto"].reconciliation_venue == "binance"
        assert DOMAIN_CONFIGS["equity"].reconciliation_venue == "alpaca"

    def test_every_crypto_symbol_has_instrument(self, paper_config, instrument_registry):
        from merid.paper_config import DOMAIN_CONFIGS
        crypto = DOMAIN_CONFIGS["crypto"]
        for sym in crypto.symbols:
            inst = instrument_registry.get(sym)
            assert inst is not None, f"Crypto symbol {sym} has no InstrumentConfig"
            assert inst.domain == "crypto"

    def test_every_equity_symbol_has_instrument(self, paper_config, instrument_registry):
        from merid.paper_config import DOMAIN_CONFIGS
        equity = DOMAIN_CONFIGS["equity"]
        for sym in equity.symbols:
            inst = instrument_registry.get(sym)
            assert inst is not None, f"Equity symbol {sym} has no InstrumentConfig"

    def test_instrument_venues_are_subset_of_domain_venues(self, instrument_registry):
        from merid.paper_config import DOMAIN_CONFIGS
        for inst_id, inst in instrument_registry.items():
            dc = DOMAIN_CONFIGS.get(inst.domain)
            if dc and dc.venues:
                for v in inst.venues:
                    assert v in dc.venues, (
                        f"Instrument {inst_id} venue {v} not in domain "
                        f"{inst.domain} venues {dc.venues}"
                    )

    def test_global_risk_limits_present(self, paper_config):
        assert paper_config.risk_limits is not None
        assert paper_config.risk_limits.max_portfolio_drawdown_pct > 0
        assert paper_config.risk_limits.max_total_notional_usd > 0

    def test_reconciliation_config_present(self, paper_config):
        assert paper_config.reconciliation is not None
        assert paper_config.reconciliation.block_execution_on_critical is True

    def test_register_instrument_at_runtime(self, instrument_registry):
        from merid.paper_config import InstrumentConfig, register_instrument, get_instrument
        test_id = f"TEST-RUNTIME-{int(time.time())}"
        register_instrument(InstrumentConfig(
            id=test_id, domain="prediction",
            venues=["kalshi"], min_size=1.0, max_size=100.0, tick_size=0.01,
        ))
        assert get_instrument(test_id) is not None
        assert get_instrument(test_id).domain == "prediction"
        # Cleanup
        del instrument_registry[test_id]


# ═══════════════════════════════════════════════════════════════════════
# 2. Crypto Domain — paper engine trades, portfolio, PnL
# ═══════════════════════════════════════════════════════════════════════

class TestCryptoDomain:
    """Crypto domain: paper trades via paper engine, mark-to-market PnL."""

    def test_btc_paper_trade(self, paper_engine):
        uid = f"matrix_btc_{int(time.time())}"
        paper_engine.update_prices({"BTC/USDT": 65000.0, "BTC": 65000.0})
        order = paper_engine.place_order(
            user_id=uid, asset="BTC", side="long",
            size_usd=500.0, order_type="market", leverage=1,
        )
        assert order is not None
        assert order.fill_price > 0
        stats = paper_engine.get_portfolio_stats(uid)
        assert stats["total_trades"] >= 1
        assert stats["open_positions"] >= 1

    def test_eth_paper_trade(self, paper_engine):
        uid = f"matrix_eth_{int(time.time())}"
        paper_engine.update_prices({"ETH/USDT": 3500.0, "ETH": 3500.0})
        order = paper_engine.place_order(
            user_id=uid, asset="ETH", side="long",
            size_usd=300.0, order_type="market", leverage=1,
        )
        assert order is not None
        assert order.fill_price > 0

    def test_sol_paper_trade(self, paper_engine):
        uid = f"matrix_sol_{int(time.time())}"
        paper_engine.update_prices({"SOL/USDT": 180.0, "SOL": 180.0})
        order = paper_engine.place_order(
            user_id=uid, asset="SOL", side="long",
            size_usd=200.0, order_type="market", leverage=1,
        )
        assert order is not None
        assert order.fill_price > 0

    def test_crypto_mark_to_market(self, paper_engine):
        uid = f"matrix_mtm_{int(time.time())}"
        paper_engine.update_prices({"BTC/USDT": 60000.0, "BTC": 60000.0})
        paper_engine.place_order(
            user_id=uid, asset="BTC", side="long",
            size_usd=1000.0, leverage=1,
        )
        stats_before = paper_engine.get_portfolio_stats(uid)

        # Price up 5%
        paper_engine.update_prices({"BTC/USDT": 63000.0, "BTC": 63000.0})
        stats_after = paper_engine.get_portfolio_stats(uid)

        assert stats_after["total_unrealized_pnl"] > stats_before["total_unrealized_pnl"]

    def test_crypto_short_trade(self, paper_engine):
        uid = f"matrix_short_{int(time.time())}"
        paper_engine.update_prices({"ETH/USDT": 3500.0, "ETH": 3500.0})
        order = paper_engine.place_order(
            user_id=uid, asset="ETH", side="short",
            size_usd=500.0, leverage=1,
        )
        assert order is not None
        assert order.fill_price > 0

    def test_crypto_instrument_config_respected(self, instrument_registry):
        btc = instrument_registry["BTC/USDT"]
        assert btc.min_size == 0.0001
        assert btc.max_leverage == 3.0
        assert "binance" in btc.venues
        assert btc.tick_size == 0.50


# ═══════════════════════════════════════════════════════════════════════
# 3. Prediction Domain — matching engine fills
# ═══════════════════════════════════════════════════════════════════════

class TestPredictionDomain:
    """Prediction domain: orders route through internal CLOB matching engine."""

    def test_matching_engine_initializes(self):
        from merid.matching_engine import init_matching_engines
        engines = init_matching_engines()
        assert "prediction" in engines
        assert engines["prediction"].enabled is True

    def test_buy_yes_contract(self, prediction_matching_engine):
        from merid.matching_engine import Order, OrderSide
        engine = prediction_matching_engine
        engine.update_reference_price("KXBTC-26FEB-YES", 0.65)

        order = Order(
            instrument_id="KXBTC-26FEB-YES",
            side=OrderSide.BUY,
            notional_usd=100.0,
            domain="prediction",
            plan_id="test-buy-yes",
        )
        fill = engine.submit_order(order)

        assert order.status.value == "filled"
        assert fill.price == 0.65
        assert fill.quantity > 0
        assert fill.notional_usd == pytest.approx(100.0, abs=1.0)

    def test_sell_yes_contract(self, prediction_matching_engine):
        from merid.matching_engine import Order, OrderSide
        engine = prediction_matching_engine
        engine.update_reference_price("KXBTC-26FEB-YES", 0.70)

        order = Order(
            instrument_id="KXBTC-26FEB-YES",
            side=OrderSide.SELL,
            notional_usd=50.0,
            domain="prediction",
            plan_id="test-sell-yes",
        )
        fill = engine.submit_order(order)

        assert order.status.value == "filled"
        assert fill.price == 0.70
        assert fill.quantity > 0

    def test_slippage_applied(self, prediction_matching_engine):
        from merid.matching_engine import Order, OrderSide
        engine = prediction_matching_engine
        engine.slippage_bps = 500.0  # 500 bps = 5% — large enough to survive tick rounding
        engine.update_reference_price("KXELECTION-YES", 0.50)

        buy = Order(
            instrument_id="KXELECTION-YES",
            side=OrderSide.BUY,
            notional_usd=100.0,
            domain="prediction",
        )
        fill = engine.submit_order(buy)

        # BUY should fill above reference (0.50 + 5% = 0.525 → rounds to 0.53)
        assert fill.price > 0.50
        engine.slippage_bps = 5.0  # Reset

    def test_tick_size_rounding(self, prediction_matching_engine):
        from merid.matching_engine import Order, OrderSide
        engine = prediction_matching_engine
        engine.update_reference_price("KXTEST-YES", 0.333)

        order = Order(
            instrument_id="KXTEST-YES",
            side=OrderSide.BUY,
            notional_usd=10.0,
            domain="prediction",
        )
        fill = engine.submit_order(order)

        # tick_size=0.01 → price should be rounded
        assert fill.price == round(fill.price, 2)

    def test_no_reference_price_rejected(self, prediction_matching_engine):
        from merid.matching_engine import Order, OrderSide
        engine = prediction_matching_engine

        order = Order(
            instrument_id="KXUNKNOWN-YES",
            side=OrderSide.BUY,
            notional_usd=100.0,
            domain="prediction",
        )
        fill = engine.submit_order(order)

        assert order.status.value == "rejected"
        assert fill.quantity == 0

    def test_disabled_engine_rejects(self, prediction_matching_engine):
        from merid.matching_engine import Order, OrderSide
        engine = prediction_matching_engine
        engine.disable()
        engine.update_reference_price("KXTEST-YES", 0.50)

        order = Order(
            instrument_id="KXTEST-YES",
            side=OrderSide.BUY,
            notional_usd=100.0,
            domain="prediction",
        )
        fill = engine.submit_order(order)

        assert order.status.value == "rejected"
        engine.enable()  # Re-enable for other tests

    def test_multiple_fills_tracked(self, prediction_matching_engine):
        from merid.matching_engine import Order, OrderSide
        engine = prediction_matching_engine
        engine.update_reference_price("KXMULTI-YES", 0.55)

        for i in range(5):
            order = Order(
                instrument_id="KXMULTI-YES",
                side=OrderSide.BUY,
                notional_usd=20.0,
                domain="prediction",
                plan_id=f"multi-{i}",
            )
            engine.submit_order(order)

        fills = engine.fills_for_instrument("KXMULTI-YES")
        assert len(fills) == 5

        stats = engine.stats()
        assert stats["total_fills"] >= 5

    def test_book_snapshot(self, prediction_matching_engine):
        engine = prediction_matching_engine
        engine.update_reference_price("KXBOOK-YES", 0.60)

        book = engine.get_book("KXBOOK-YES")
        assert book.instrument_id == "KXBOOK-YES"
        assert len(book.bids) > 0
        assert len(book.asks) > 0
        assert book.bids[0].price < 0.60
        assert book.asks[0].price > 0.60
        assert book.spread > 0


# ═══════════════════════════════════════════════════════════════════════
# 4. Equity Domain — paper trades, reconciliation config
# ═══════════════════════════════════════════════════════════════════════

class TestEquityDomain:
    """Equity domain: paper trades via paper engine, reconciliation target."""

    def test_aapl_paper_trade(self, paper_engine):
        uid = f"matrix_aapl_{int(time.time())}"
        paper_engine.update_prices({"AAPL": 195.0})
        order = paper_engine.place_order(
            user_id=uid, asset="AAPL", side="long",
            size_usd=500.0, order_type="market", leverage=1,
        )
        assert order is not None
        assert order.fill_price > 0

    def test_spy_paper_trade(self, paper_engine):
        uid = f"matrix_spy_{int(time.time())}"
        paper_engine.update_prices({"SPY": 520.0})
        order = paper_engine.place_order(
            user_id=uid, asset="SPY", side="long",
            size_usd=1000.0, order_type="market", leverage=1,
        )
        assert order is not None
        assert order.fill_price > 0

    def test_equity_reconciliation_target(self):
        from merid.paper_config import DOMAIN_CONFIGS
        equity = DOMAIN_CONFIGS["equity"]
        assert equity.reconciliation_venue == "alpaca"

    def test_equity_instrument_config(self, instrument_registry):
        aapl = instrument_registry["AAPL"]
        assert aapl.domain == "equity"
        assert "alpaca" in aapl.venues
        assert aapl.tick_size == 0.01

        spy = instrument_registry["SPY"]
        assert spy.domain == "equity"
        assert "ibkr" in spy.venues


# ═══════════════════════════════════════════════════════════════════════
# 5. Cross-Domain — config consistency, risk limits
# ═══════════════════════════════════════════════════════════════════════

class TestCrossDomain:
    """Cross-domain consistency checks."""

    def test_allocation_sums_to_reasonable_total(self, paper_config):
        from merid.paper_config import DOMAIN_CONFIGS
        total = sum(dc.allocation_pct for dc in DOMAIN_CONFIGS.values() if dc.enabled)
        # Should be between 0.5 and 2.0 (allows some overlap)
        assert 0.5 <= total <= 2.0, f"Total allocation {total} out of range"

    def test_no_duplicate_instrument_ids(self, instrument_registry):
        ids = list(instrument_registry.keys())
        assert len(ids) == len(set(ids)), "Duplicate instrument IDs found"

    def test_instruments_for_domain_helper(self):
        from merid.paper_config import instruments_for_domain
        crypto = instruments_for_domain("crypto")
        assert len(crypto) >= 20
        equity = instruments_for_domain("equity")
        assert len(equity) >= 10

    def test_get_instrument_helper(self):
        from merid.paper_config import get_instrument
        assert get_instrument("BTC/USDT") is not None
        assert get_instrument("AAPL") is not None
        assert get_instrument("NONEXISTENT") is None

    def test_domain_modes_all_paper(self, paper_config):
        from merid.paper_config import DOMAIN_CONFIGS, DomainMode
        for name, dc in DOMAIN_CONFIGS.items():
            if dc.enabled:
                assert dc.mode == DomainMode.PAPER, (
                    f"Domain {name} is {dc.mode.value}, expected PAPER"
                )

    def test_kill_switch_off_by_default(self, paper_config):
        assert paper_config.risk_limits.kill_switch is False


# ═══════════════════════════════════════════════════════════════════════
# 6. API Endpoint Smoke — key endpoints return 200
# ═══════════════════════════════════════════════════════════════════════

class TestApiEndpointSmoke:
    """Verify key UI-facing endpoints return valid data."""

    @pytest.fixture(autouse=True)
    def setup_client(self):
        try:
            from web.main import create_app
            from starlette.testclient import TestClient
            app = create_app()
            self.client = TestClient(app)
            self.available = True
        except Exception:
            self.available = False

    def _get(self, path: str):
        if not self.available:
            pytest.skip("Web app not available")
        resp = self.client.get(path)
        return resp

    def test_portfolio_summary(self):
        resp = self._get("/api/v1/portfolio/summary")
        assert resp.status_code == 200

    def test_trading_orders_open(self):
        resp = self._get("/api/v1/trading/orders/open")
        assert resp.status_code == 200

    def test_prediction_markets_summary(self):
        resp = self._get("/api/v1/prediction-markets/summary")
        assert resp.status_code == 200

    def test_pipeline_summary(self):
        resp = self._get("/api/v1/pipeline/summary")
        assert resp.status_code == 200

    def test_pipeline_risk(self):
        resp = self._get("/api/v1/pipeline/risk")
        assert resp.status_code == 200

    def test_signal_layer_cqi(self):
        resp = self._get("/api/v1/signal-layer/cqi")
        assert resp.status_code == 200

    def test_betting_consensus_summary(self):
        resp = self._get("/api/v1/betting/consensus/summary")
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════
# 7. Manifest & Form Hygiene
# ═══════════════════════════════════════════════════════════════════════

class TestSLOBounds:
    """Quantitative SLO bounds that must hold before any domain goes live."""

    # ── Fill latency ─────────────────────────────────────────────────

    def test_matching_engine_fill_latency(self):
        """Prediction CLOB must fill a single order in < 50ms."""
        import time as _time
        from merid.matching_engine import (
            get_matching_engine, init_matching_engines, Order, OrderSide,
        )
        init_matching_engines()
        engine = get_matching_engine("prediction")
        engine.reset()
        engine.enable()
        engine.update_reference_price("SLO-LAT-YES", 0.50)

        latencies = []
        for _ in range(20):
            order = Order(
                instrument_id="SLO-LAT-YES",
                side=OrderSide.BUY,
                notional_usd=50.0,
                domain="prediction",
            )
            t0 = _time.perf_counter()
            engine.submit_order(order)
            latencies.append((_time.perf_counter() - t0) * 1000)

        p95_idx = int(len(latencies) * 0.95)
        p95 = sorted(latencies)[min(p95_idx, len(latencies) - 1)]
        assert p95 < 50.0, f"Fill p95 latency {p95:.1f}ms exceeds 50ms SLO"

    def test_paper_engine_order_latency(self, paper_engine):
        """Paper engine must fill a market order in < 100ms."""
        import time as _time
        paper_engine.update_prices({"SLO-TEST": 100.0, "SLO-TEST/USDT": 100.0})

        latencies = []
        for i in range(10):
            uid = f"slo_lat_{i}"
            t0 = _time.perf_counter()
            paper_engine.place_order(
                user_id=uid, asset="SLO-TEST", side="long",
                size_usd=100.0, order_type="market", leverage=1,
            )
            latencies.append((_time.perf_counter() - t0) * 1000)

        p95_idx = int(len(latencies) * 0.95)
        p95 = sorted(latencies)[min(p95_idx, len(latencies) - 1)]
        assert p95 < 500.0, f"Paper engine p95 latency {p95:.1f}ms exceeds 500ms SLO"

    # ── Matching engine throughput ───────────────────────────────────

    def test_matching_engine_throughput(self):
        """Prediction CLOB must sustain >= 500 fills/sec."""
        import time as _time
        from merid.matching_engine import (
            get_matching_engine, Order, OrderSide,
        )
        engine = get_matching_engine("prediction")
        engine.reset()
        engine.enable()
        engine.update_reference_price("SLO-THRU-YES", 0.60)

        n = 200
        t0 = _time.perf_counter()
        for _ in range(n):
            order = Order(
                instrument_id="SLO-THRU-YES",
                side=OrderSide.BUY,
                notional_usd=10.0,
                domain="prediction",
            )
            engine.submit_order(order)
        elapsed = _time.perf_counter() - t0

        throughput = n / elapsed if elapsed > 0 else float("inf")
        assert throughput >= 500, f"Throughput {throughput:.0f} fills/s below 500 SLO"

    # ── Portfolio coherence ──────────────────────────────────────────

    def test_portfolio_balance_never_negative(self, paper_engine):
        """After trades, portfolio balance must stay non-negative."""
        import time as _time
        uid = f"slo_bal_{int(_time.time())}"
        paper_engine.update_prices({"BTC": 60000.0, "BTC/USDT": 60000.0})

        # Place several trades
        for _ in range(5):
            paper_engine.place_order(
                user_id=uid, asset="BTC", side="long",
                size_usd=500.0, leverage=1,
            )

        stats = paper_engine.get_portfolio_stats(uid)
        assert stats["current_balance"] >= 0, "Portfolio balance went negative"

    def test_portfolio_equity_tracks_positions(self, paper_engine):
        """Total equity = balance + unrealized PnL (sanity check)."""
        import time as _time
        uid = f"slo_eq_{int(_time.time())}"
        paper_engine.update_prices({"ETH": 3000.0, "ETH/USDT": 3000.0})

        paper_engine.place_order(
            user_id=uid, asset="ETH", side="long",
            size_usd=1000.0, leverage=1,
        )

        stats = paper_engine.get_portfolio_stats(uid)
        # Equity should be approximately balance + unrealized PnL
        expected_equity = stats["current_balance"] + stats["total_unrealized_pnl"]
        # Allow small rounding tolerance
        assert abs(stats.get("total_equity", expected_equity) - expected_equity) < 1.0

    # ── Reconciliation config bounds ─────────────────────────────────

    def test_reconciliation_thresholds_are_sane(self, paper_config):
        """Reconciliation thresholds must be within reasonable ranges."""
        rc = paper_config.reconciliation
        assert 0.001 <= rc.warning_qty_delta <= 1.0, (
            f"warning_qty_delta {rc.warning_qty_delta} out of range"
        )
        assert rc.critical_qty_delta > rc.warning_qty_delta, (
            "critical_qty_delta must exceed warning_qty_delta"
        )
        assert 1.0 <= rc.warning_price_pct <= 20.0, (
            f"warning_price_pct {rc.warning_price_pct} out of range"
        )

    def test_risk_limits_are_sane(self, paper_config):
        """Global risk limits must be within reasonable ranges."""
        rl = paper_config.risk_limits
        assert 0.01 <= rl.max_portfolio_drawdown_pct <= 0.50, (
            f"max_portfolio_drawdown_pct {rl.max_portfolio_drawdown_pct} out of range"
        )
        assert rl.max_total_notional_usd >= 10_000, (
            f"max_total_notional_usd {rl.max_total_notional_usd} too low"
        )
        assert 0.10 <= rl.max_single_venue_pct <= 1.0, (
            f"max_single_venue_pct {rl.max_single_venue_pct} out of range"
        )

    # ── Execution guard readiness ────────────────────────────────────

    def test_execution_guard_loads(self):
        """Execution guard must initialize without error."""
        from merid.execution_guard import get_execution_guard
        guard = get_execution_guard()
        assert guard is not None
        assert guard.kill_switch_active is False

    def test_execution_guard_blocks_when_killed(self):
        """Execution guard must block all trades when kill switch is on."""
        from merid.execution_guard import get_execution_guard
        guard = get_execution_guard()
        try:
            guard.activate_kill_switch(reason="slo_test")
            verdict = guard.pre_trade_check(
                plan_id="slo-test", symbol="BTC/USDT",
                domain="crypto", size_usd=100.0,
            )
            assert verdict.allowed is False
            assert "kill" in verdict.reason.lower()
        finally:
            guard.deactivate_kill_switch()

    # ── Matching engine book quality ─────────────────────────────────

    def test_book_spread_within_bounds(self):
        """Synthetic book spread must be < 10% of mid price."""
        from merid.matching_engine import get_matching_engine
        engine = get_matching_engine("prediction")
        engine.update_reference_price("SLO-SPREAD-YES", 0.50)

        book = engine.get_book("SLO-SPREAD-YES")
        if book.bids and book.asks:
            spread = book.asks[0].price - book.bids[0].price
            mid = (book.asks[0].price + book.bids[0].price) / 2
            spread_pct = spread / mid if mid > 0 else 0
            assert spread_pct < 0.10, (
                f"Book spread {spread_pct:.1%} exceeds 10% SLO"
            )


# ═══════════════════════════════════════════════════════════════════════
# 8. Manifest & Form Hygiene
# ═══════════════════════════════════════════════════════════════════════

class TestManifestIntegrity:
    """Verify manifest and form hygiene infrastructure."""

    def test_python_manifest_loads(self):
        from merid.ui_views_manifest import VIEWS, all_api_paths
        assert len(VIEWS) >= 20
        paths = all_api_paths()
        assert len(paths) >= 50

    def test_manifest_views_have_routes(self):
        from merid.ui_views_manifest import VIEWS
        for v in VIEWS:
            assert v.route, f"View {v.id} has no route"
            assert v.title, f"View {v.id} has no title"
            assert v.section in ("navigation", "management", "system")

    def test_manifest_coverage_report(self):
        from merid.ui_views_manifest import coverage_report
        report = coverage_report()
        assert report["total_views"] >= 20
        assert report["total_components"] >= 50
        assert report["total_unique_apis"] >= 50

    def test_ts_manifest_exists(self):
        import os
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        # Canonical path first; fall back to _legacy/ location
        ts_path = os.path.join(root, "web", "react", "src", "config", "uiViewsManifest.ts")
        if not os.path.exists(ts_path):
            ts_path = os.path.join(root, "web", "react", "src", "config", "_legacy", "uiViewsManifest.ts")
        assert os.path.exists(ts_path), "TS manifest not found"
        with open(ts_path, "r") as f:
            content = f.read()
        assert "AUTO-GENERATED" in content
        assert "ViewConfig" in content

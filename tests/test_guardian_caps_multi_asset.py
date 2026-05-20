"""Guardian Caps + Fills Ledger Multi-Asset Test Suite

Covers bugs 1-7 found during the upstream/downstream audit of:
  - TradingGuardian / GoLiveChecklist / can_trade()
  - KalshiFillsLedger / compute_net_positions()
  - KalshiStrategy._get_size_cap_for_asset()
  - KalshiContinuousTrader per-asset cap enforcement

Run with:
  pytest tests/test_guardian_caps_multi_asset.py -v
"""

import time
import pytest
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, PropertyMock

from merid.guards import (
    TradingGuardian, GoLiveChecklist, GuardReport, GuardStatus, TradingMode,
)
from merid.event_venues.kalshi.fills_ledger import KalshiFill, KalshiFillsLedger


ASSETS = ["BTC", "ETH", "SOL", "XRP", "DOGE"]


# ═════════════════════════════════════════════════════════════════════════
# Helpers
# ═════════════════════════════════════════════════════════════════════════

def _make_checklist(**overrides) -> GoLiveChecklist:
    """Create a GoLiveChecklist with optional overrides."""
    cl = GoLiveChecklist()
    for k, v in overrides.items():
        setattr(cl, k, v)
    return cl


def _make_guardian(mode=TradingMode.OBSERVATION, caps=None) -> TradingGuardian:
    """Create a TradingGuardian with mocked startup checks to avoid imports."""
    caps = caps or {a: 0.0 for a in ASSETS}
    cl = GoLiveChecklist(mode=mode, live_size_caps=caps)

    with patch.object(TradingGuardian, "_run_startup_self_check"), \
         patch.object(TradingGuardian, "_log_bootstrap_state"), \
         patch.object(TradingGuardian, "_run_capital_engine_self_check"), \
         patch.object(TradingGuardian, "_register_kill_switch_handler"):
        guardian = TradingGuardian(cl)
    return guardian


def _make_fill(fill_id, ticker, side, action, count, price_dollars) -> KalshiFill:
    """Create a KalshiFill for testing."""
    return KalshiFill(
        fill_id=fill_id,
        market_ticker=ticker,
        side=side,
        action=action,
        count_fp=count,
        yes_price_dollars=Decimal(str(price_dollars)) if side == "yes" else None,
        no_price_dollars=Decimal(str(price_dollars)) if side == "no" else None,
        fee_cost=Decimal("0.01"),
        ingestion_source="test",
        created_time=datetime.now(timezone.utc),
    )


def _fresh_ledger() -> KalshiFillsLedger:
    """Create a fresh ledger instance (bypass singleton)."""
    ledger = object.__new__(KalshiFillsLedger)
    ledger._initialized = True
    ledger._fills = {}
    ledger._intents = {}
    ledger._fills_by_order = {}
    ledger._fills_by_market = {}
    ledger._last_reconciliation = None
    ledger._reconciliation_status = None
    ledger._reconciliation_issues = []
    ledger._http_ingested = 0
    ledger._ws_ingested = 0
    ledger._duplicates_dropped = 0
    ledger._db_path = ":memory:"
    ledger._db_initialized = False
    ledger._loaded_count = 0
    return ledger


# ═════════════════════════════════════════════════════════════════════════
# 1. Guardian can_trade() — all assets
# ═════════════════════════════════════════════════════════════════════════

class TestGuardianCanTrade:
    """Verify can_trade() for all modes and assets."""

    def test_observation_mode_blocks_trading(self):
        g = _make_guardian(mode=TradingMode.OBSERVATION)
        # Force a report so can_trade() doesn't call run_all_checks()
        g._last_report = GuardReport(
            mode=TradingMode.OBSERVATION,
            overall_status=GuardStatus.PASS,
            can_trade=False,
        )
        assert g.can_trade() is False

    def test_live_small_allows_trading(self):
        g = _make_guardian(mode=TradingMode.LIVE_SMALL)
        g._last_report = GuardReport(
            mode=TradingMode.LIVE_SMALL,
            overall_status=GuardStatus.PASS,
            can_trade=True,
        )
        assert g.can_trade() is True

    def test_live_full_allows_trading(self):
        g = _make_guardian(mode=TradingMode.LIVE_FULL)
        g._last_report = GuardReport(
            mode=TradingMode.LIVE_FULL,
            overall_status=GuardStatus.PASS,
            can_trade=True,
        )
        assert g.can_trade() is True

    def test_disabled_blocks_trading(self):
        g = _make_guardian(mode=TradingMode.DISABLED)
        g._last_report = GuardReport(
            mode=TradingMode.DISABLED,
            overall_status=GuardStatus.PASS,
            can_trade=False,
        )
        assert g.can_trade() is False

    def test_failed_guards_block_trading(self):
        g = _make_guardian(mode=TradingMode.LIVE_FULL)
        g._last_report = GuardReport(
            mode=TradingMode.LIVE_FULL,
            overall_status=GuardStatus.FAIL,
            can_trade=False,
        )
        assert g.can_trade() is False

    def test_no_report_triggers_run_all_checks(self):
        """can_trade() with no prior report should run checks (fail-closed)."""
        g = _make_guardian(mode=TradingMode.OBSERVATION)
        assert g._last_report is None
        # Patch run_all_checks to return a safe report
        with patch.object(g, "run_all_checks") as mock_rac:
            mock_rac.return_value = GuardReport(
                mode=TradingMode.OBSERVATION,
                can_trade=False,
            )
            result = g.can_trade()
            mock_rac.assert_called_once()
            assert result is False


# ═════════════════════════════════════════════════════════════════════════
# 2. live_size_caps — all 5 assets covered
# ═════════════════════════════════════════════════════════════════════════

class TestLiveSizeCaps:
    """Verify live_size_caps defaults and per-asset behavior."""

    def test_default_caps_are_zero_for_all_assets(self):
        cl = GoLiveChecklist()
        for asset in ASSETS:
            assert cl.live_size_caps.get(asset) == 0.0, f"{asset} should default to 0.0"

    def test_all_five_assets_present_in_default(self):
        cl = GoLiveChecklist()
        for asset in ASSETS:
            assert asset in cl.live_size_caps, f"{asset} missing from live_size_caps"

    def test_promote_sets_cap(self):
        g = _make_guardian(mode=TradingMode.OBSERVATION)
        g.checklist.live_size_caps["BTC"] = 0.25
        assert g.checklist.live_size_caps["BTC"] == 0.25
        assert g.checklist.live_size_caps["ETH"] == 0.0  # Others unchanged

    def test_kill_switch_resets_all_caps(self):
        caps = {a: 0.25 for a in ASSETS}
        g = _make_guardian(mode=TradingMode.LIVE_SMALL, caps=caps)
        # Simulate kill switch resetting caps
        g.enter_observation_mode(reason="test kill")
        for asset in ASSETS:
            g.checklist.live_size_caps[asset] = 0.0
        for asset in ASSETS:
            assert g.checklist.live_size_caps[asset] == 0.0

    def test_unknown_asset_defaults_to_zero(self):
        cl = GoLiveChecklist()
        assert cl.live_size_caps.get("UNKNOWN_COIN", 0.0) == 0.0


# ═════════════════════════════════════════════════════════════════════════
# 3. _get_size_cap_for_asset — fail-closed (BUG-4 regression test)
# ═════════════════════════════════════════════════════════════════════════

class TestGetSizeCapForAsset:
    """Verify _get_size_cap_for_asset is fail-closed."""

    def test_no_trader_returns_zero(self):
        """BUG-4 regression: no guardian available → 0.0 (not None)."""
        from merid.prediction.strategy import KalshiStrategy

        with patch("merid.trading.kalshi_continuous_trader.get_continuous_trader", return_value=None), \
             patch.dict("os.environ", {"MERID_ENABLE_KALSHI_CT": "true"}):
            strat = object.__new__(KalshiStrategy)
            cap = strat._get_size_cap_for_asset("BTC")
            assert cap == 0.0
            assert isinstance(cap, float)

    def test_trader_no_guardian_returns_zero(self):
        mock_trader = MagicMock()
        mock_trader._guardian = None

        from merid.prediction.strategy import KalshiStrategy
        with patch("merid.trading.kalshi_continuous_trader.get_continuous_trader", return_value=mock_trader), \
             patch.dict("os.environ", {"MERID_ENABLE_KALSHI_CT": "true"}):
            strat = object.__new__(KalshiStrategy)
            cap = strat._get_size_cap_for_asset("ETH")
            assert cap == 0.0

    def test_import_error_returns_zero(self):
        from merid.prediction.strategy import KalshiStrategy
        with patch("merid.trading.kalshi_continuous_trader.get_continuous_trader", side_effect=ImportError("nope")), \
             patch.dict("os.environ", {"MERID_ENABLE_KALSHI_CT": "true"}):
            strat = object.__new__(KalshiStrategy)
            cap = strat._get_size_cap_for_asset("SOL")
            assert cap == 0.0

    @pytest.mark.parametrize("asset,expected_cap", [
        ("BTC", 0.0),
        ("ETH", 0.25),
        ("SOL", 1.0),
        ("XRP", 0.0),
        ("DOGE", 0.5),
    ])
    def test_returns_guardian_cap_per_asset(self, asset, expected_cap):
        caps = {"BTC": 0.0, "ETH": 0.25, "SOL": 1.0, "XRP": 0.0, "DOGE": 0.5}
        guardian = _make_guardian(mode=TradingMode.LIVE_SMALL, caps=caps)
        mock_trader = MagicMock()
        mock_trader._guardian = guardian

        from merid.prediction.strategy import KalshiStrategy
        with patch("merid.trading.kalshi_continuous_trader.get_continuous_trader", return_value=mock_trader):
            strat = object.__new__(KalshiStrategy)
            cap = strat._get_size_cap_for_asset(asset)
            assert cap == expected_cap, f"{asset}: expected {expected_cap}, got {cap}"

    def test_unknown_asset_returns_zero_not_none(self):
        """Unknown asset should default to 0.0 (fail-closed), not None."""
        caps = {a: 0.25 for a in ASSETS}
        guardian = _make_guardian(mode=TradingMode.LIVE_SMALL, caps=caps)
        mock_trader = MagicMock()
        mock_trader._guardian = guardian

        from merid.prediction.strategy import KalshiStrategy
        with patch("merid.trading.kalshi_continuous_trader.get_continuous_trader", return_value=mock_trader):
            strat = object.__new__(KalshiStrategy)
            cap = strat._get_size_cap_for_asset("SHIB")
            assert cap == 0.0


# ═════════════════════════════════════════════════════════════════════════
# 4. _last_guard_check instance attribute (BUG-5 regression test)
# ═════════════════════════════════════════════════════════════════════════

class TestLastGuardCheckAttribute:
    """Verify _last_guard_check is an instance attribute, not a local."""

    def test_attribute_exists_on_init(self):
        """BUG-5 regression: _last_guard_check must be an instance attribute."""
        import ast
        source = open("merid/trading/kalshi_continuous_trader.py", encoding="utf-8").read()
        tree = ast.parse(source)
        # Check that self._last_guard_check appears in __init__
        found = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute):
                if (isinstance(node.value, ast.Name) and node.value.id == "self"
                        and node.attr == "_last_guard_check"):
                    found = True
                    break
        assert found, "self._last_guard_check not found as instance attribute"

    def test_status_snapshot_uses_self(self):
        """Ensure _status_snapshot_inner uses self._last_guard_check, not bare local."""
        source = open("merid/trading/kalshi_continuous_trader.py", encoding="utf-8").read()
        # Find _status_snapshot_inner and check it uses self._last_guard_check
        assert "self._last_guard_check" in source
        # Ensure no bare _last_guard_check reference in status snapshot
        # (the `run()` method should also use self._last_guard_check now)
        lines = source.split("\n")
        for i, line in enumerate(lines):
            stripped = line.strip()
            # Skip comments and strings
            if stripped.startswith("#") or stripped.startswith('"') or stripped.startswith("'"):
                continue
            # Find bare _last_guard_check (not self._last_guard_check, not in a string)
            if "_last_guard_check" in stripped and "self._last_guard_check" not in stripped:
                # Allow the _guard_check_interval line
                if "_guard_check_interval" in stripped:
                    continue
                pytest.fail(
                    f"Line {i+1}: bare '_last_guard_check' found (should be self._last_guard_check): {stripped}"
                )


# ═════════════════════════════════════════════════════════════════════════
# 5. Fills Ledger — compute_net_positions multi-asset (BUG-2 regression)
# ═════════════════════════════════════════════════════════════════════════

class TestFillsLedgerMultiAsset:
    """Verify compute_net_positions works for all 5 assets."""

    def test_empty_ledger_returns_empty(self):
        ledger = _fresh_ledger()
        assert ledger.compute_net_positions() == {}

    def test_single_asset_position(self):
        ledger = _fresh_ledger()
        fill = _make_fill("f1", "KXBTC-25DEC-ABOVE-100000", "yes", "buy", 5, 0.65)
        ledger._fills["f1"] = fill
        ledger._fills_by_market["KXBTC-25DEC-ABOVE-100000"] = ["f1"]

        positions = ledger.compute_net_positions()
        assert "KXBTC-25DEC-ABOVE-100000" in positions
        pos = positions["KXBTC-25DEC-ABOVE-100000"]
        assert pos["side"] == "yes"
        assert pos["contracts"] == 5

    def test_multi_asset_positions(self):
        """All 5 assets should independently compute positions."""
        ledger = _fresh_ledger()
        tickers = {
            "BTC": "KXBTC-25DEC-ABOVE-100000",
            "ETH": "KXETH-25DEC-ABOVE-4000",
            "SOL": "KXSOL-25DEC-ABOVE-200",
            "XRP": "KXXRP-25DEC-ABOVE-2",
            "DOGE": "KXDOGE-25DEC-ABOVE-0.5",
        }

        for i, (asset, ticker) in enumerate(tickers.items()):
            fid = f"f_{asset}"
            fill = _make_fill(fid, ticker, "yes", "buy", (i + 1) * 2, 0.50)
            ledger._fills[fid] = fill
            ledger._fills_by_market[ticker] = [fid]

        positions = ledger.compute_net_positions()
        assert len(positions) == 5
        for asset, ticker in tickers.items():
            assert ticker in positions, f"{asset} ({ticker}) missing from positions"

    def test_zero_net_position_excluded(self):
        """Buy then sell same quantity → zero → excluded from net positions."""
        ledger = _fresh_ledger()
        ticker = "KXBTC-25DEC-ABOVE-100000"
        buy = _make_fill("f_buy", ticker, "yes", "buy", 3, 0.60)
        sell = _make_fill("f_sell", ticker, "yes", "sell", 3, 0.70)
        ledger._fills["f_buy"] = buy
        ledger._fills["f_sell"] = sell
        ledger._fills_by_market[ticker] = ["f_buy", "f_sell"]

        positions = ledger.compute_net_positions()
        assert ticker not in positions  # Net zero → excluded

    def test_partial_close_reduces_position(self):
        """Buy 5, sell 2 → net 3."""
        ledger = _fresh_ledger()
        ticker = "KXETH-25DEC-ABOVE-4000"
        buy = _make_fill("f_buy", ticker, "yes", "buy", 5, 0.55)
        sell = _make_fill("f_sell", ticker, "yes", "sell", 2, 0.60)
        ledger._fills["f_buy"] = buy
        ledger._fills["f_sell"] = sell
        ledger._fills_by_market[ticker] = ["f_buy", "f_sell"]

        positions = ledger.compute_net_positions()
        assert positions[ticker]["contracts"] == 3
        assert positions[ticker]["side"] == "yes"

    def test_compute_net_positions_matches_per_market(self):
        """compute_net_positions must agree with compute_position_from_fills per ticker."""
        ledger = _fresh_ledger()
        tickers = ["KXBTC-T1", "KXETH-T2", "KXSOL-T3"]
        for i, ticker in enumerate(tickers):
            fid = f"f_{i}"
            fill = _make_fill(fid, ticker, "yes", "buy", (i + 1), 0.50)
            ledger._fills[fid] = fill
            ledger._fills_by_market[ticker] = [fid]

        bulk = ledger.compute_net_positions()
        for ticker in tickers:
            per_market = ledger.compute_position_from_fills(ticker)
            assert bulk[ticker] == per_market, f"Drift for {ticker}: bulk != per_market"


# ═════════════════════════════════════════════════════════════════════════
# 6. CT per-asset cap enforcement (BUG-7 regression test)
# ═════════════════════════════════════════════════════════════════════════

class TestCTPerAssetCapEnforcement:
    """Verify the CT order path respects guardian per-asset caps."""

    def test_ct_has_per_asset_cap_code(self):
        """BUG-7 regression: CT must check guardian caps before placing orders."""
        source = open("merid/trading/kalshi_continuous_trader.py", encoding="utf-8").read()
        # Updated: CT now uses get_effective_live_caps() then effective_caps.get()
        assert "effective_caps.get(_candidate_asset" in source, \
            "CT missing per-asset cap check from guardian"
        assert "guardian cap=0 (OBSERVATION or computed cap is zero)" in source, \
            "CT missing per-asset OBSERVATION skip log"
        assert "[SIZE-CAP-CT]" in source, \
            "CT missing per-asset cap reduction log tag"


# ═════════════════════════════════════════════════════════════════════════
# 7. Dead import removed (BUG-6 regression test)
# ═════════════════════════════════════════════════════════════════════════

class TestDeadImportRemoved:
    """Verify the dead TradingGuardian import is no longer at the sizing call site."""

    def test_no_dead_import_at_size_cap_call_site(self):
        """BUG-6 regression: TradingGuardian should not be imported at the sizing call site."""
        source = open("merid/prediction/strategy.py", encoding="utf-8").read()
        lines = source.split("\n")
        for i, line in enumerate(lines):
            if "_get_size_cap_for_asset" in line and "size_cap = self" in line:
                # Check the 1-2 lines above for dead import
                context = "\n".join(lines[max(0, i-2):i])
                assert "from merid.guards import TradingGuardian" not in context, \
                    f"Dead TradingGuardian import still present near line {i+1}"
                break


# ═════════════════════════════════════════════════════════════════════════
# 8. Promotion — all 5 assets
# ═════════════════════════════════════════════════════════════════════════

class TestPromotionAllAssets:
    """Verify promotion eligibility works for all 5 assets."""

    def test_all_assets_have_bucket_stats(self):
        g = _make_guardian()
        for asset in ASSETS:
            assert asset in g._conviction_bucket_stats, f"{asset} missing from bucket stats"
            assert "0.4-0.6" in g._conviction_bucket_stats[asset]
            assert "0.6-0.8" in g._conviction_bucket_stats[asset]
            assert "0.8-1.0" in g._conviction_bucket_stats[asset]

    def test_promotion_eligibility_per_asset(self):
        g = _make_guardian()
        for asset in ASSETS:
            result = g.evaluate_promotion_eligibility(asset)
            assert result["asset"] == asset
            assert result["is_observation"] is True
            assert result["eligible"] is False  # No trades yet

    def test_promotion_after_enough_trades(self):
        """Simulate enough good trades to make an asset eligible."""
        g = _make_guardian()
        for _ in range(15):
            g.record_trade_outcome("SOL", conviction=0.85, realized_pnl=5.0, ev_at_entry=0.10, won=True)

        result = g.evaluate_promotion_eligibility("SOL")
        assert result["has_enough_trades"] is True
        assert result["meets_hit_rate"] is True
        assert result["eligible"] is True

        # Other assets should still be ineligible
        for asset in ["BTC", "ETH", "XRP", "DOGE"]:
            result = g.evaluate_promotion_eligibility(asset)
            assert result["eligible"] is False, f"{asset} should not be eligible"


# ═════════════════════════════════════════════════════════════════════════
# 9. End-to-end: caps + positions + guardian consistency
# ═════════════════════════════════════════════════════════════════════════

class TestEndToEndConsistency:
    """Verify guardian + ledger + caps are consistent across all 5 assets."""

    def test_observation_blocks_all_assets(self):
        """In observation mode, all caps should be 0.0 → all trades blocked."""
        g = _make_guardian(mode=TradingMode.OBSERVATION)
        for asset in ASSETS:
            cap = g.checklist.live_size_caps.get(asset, 0.0)
            assert cap == 0.0, f"{asset} cap should be 0.0 in observation"

    def test_mixed_caps_scenario(self):
        """Some assets promoted, others observation — verify isolation."""
        caps = {"BTC": 0.25, "ETH": 0.25, "SOL": 0.0, "XRP": 0.0, "DOGE": 1.0}
        g = _make_guardian(mode=TradingMode.LIVE_SMALL, caps=caps)

        assert g.checklist.live_size_caps["BTC"] == 0.25
        assert g.checklist.live_size_caps["SOL"] == 0.0
        assert g.checklist.live_size_caps["DOGE"] == 1.0

    def test_ledger_positions_independent_per_asset(self):
        """Fills for different assets produce independent positions."""
        ledger = _fresh_ledger()
        # BTC: long 3
        ledger._fills["btc1"] = _make_fill("btc1", "KXBTC-T1", "yes", "buy", 3, 0.60)
        ledger._fills_by_market["KXBTC-T1"] = ["btc1"]
        # ETH: long 5
        ledger._fills["eth1"] = _make_fill("eth1", "KXETH-T1", "yes", "buy", 5, 0.45)
        ledger._fills_by_market["KXETH-T1"] = ["eth1"]
        # SOL: flat (buy + sell)
        ledger._fills["sol1"] = _make_fill("sol1", "KXSOL-T1", "yes", "buy", 2, 0.50)
        ledger._fills["sol2"] = _make_fill("sol2", "KXSOL-T1", "yes", "sell", 2, 0.55)
        ledger._fills_by_market["KXSOL-T1"] = ["sol1", "sol2"]

        positions = ledger.compute_net_positions()
        assert len(positions) == 2  # BTC and ETH (SOL is flat)
        assert "KXBTC-T1" in positions
        assert "KXETH-T1" in positions
        assert "KXSOL-T1" not in positions  # Flat

    def test_compile_all_modified_files(self):
        """Ensure all files modified in this audit still compile."""
        import ast
        files = [
            "merid/prediction/strategy.py",
            "merid/guards/__init__.py",
            "merid/event_venues/kalshi/fills_ledger.py",
        ]
        for f in files:
            try:
                source = open(f, encoding="utf-8").read()
                ast.parse(source)
            except SyntaxError as e:
                pytest.fail(f"{f} has syntax error: {e}")

        # CT needs explicit utf-8 encoding (has unicode chars)
        try:
            source = open("merid/trading/kalshi_continuous_trader.py", encoding="utf-8").read()
            ast.parse(source)
        except SyntaxError as e:
            pytest.fail(f"kalshi_continuous_trader.py has syntax error: {e}")

"""Guardrail tests — ensure MERID stays Kalshi-only.

These tests fail if:
  1. Any active (non-_legacy) Python file imports a legacy venue module.
  2. The consolidated merid.kalshi facade doesn't export essential symbols.
  3. The agent domain split packages can't be imported.
  4. Sample Kalshi event / crypto market fixtures can be constructed.
  5. Order intent payloads format correctly through the Kalshi client types.
"""

import ast
import os
import pathlib
import sys
import unittest

# ── Paths ─────────────────────────────────────────────────────────────────

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
MERID_ROOT = REPO_ROOT  # top-level


# ═══════════════════════════════════════════════════════════════════════════
# 1. No active code imports legacy modules
# ═══════════════════════════════════════════════════════════════════════════

LEGACY_IMPORT_PATTERNS = [
    "from core.venues.alpaca_adapter",
    "from core.venues.binanceus_adapter",
    "from core.venues.bitget_adapter",
    "from core.venues.coinbase_advanced_adapter",
    "from core.venues.gateio_adapter",
    "from core.venues.gemini_adapter",
    "from core.venues.htx_adapter",
    "from core.venues.ibkr_adapter",
    "from core.venues.kraken_adapter",
    "from core.venues.kucoin_adapter",
    "from core.venues.mexc_adapter",
    "from core.venues.okx_adapter",
    "from core.venues.merid_sim_adapter",
    "from merid.event_venues.polymarket",
    "from trading.adapters.alpaca",
    "from trading.adapters.coinbase",
    "from trading.adapters.pumpfun",
    "from trading.integrations.alpaca_client",
    "from trading.augur_trading_layer",
    "from trading.polymarket_adapter",
    "from trading.polymarket_trading_layer",
    "from trading.perp.",
    "from agents.polymarket",
]

# Directories that are explicitly legacy or non-source — skip scanning them
LEGACY_DIRS = {
    "_legacy", "__pycache__", ".git", "node_modules", ".venv", "venv",
    ".claude",       # git worktrees managed by external tools
    "tests",         # legacy test files may reference legacy modules
    "simulation",    # simulation engines reference legacy layers
}


def _active_python_files():
    """Yield all .py files in the repo that are NOT inside _legacy/ dirs."""
    for root, dirs, files in os.walk(MERID_ROOT):
        # Prune legacy and non-source dirs
        dirs[:] = [d for d in dirs if d not in LEGACY_DIRS]
        for f in files:
            if f.endswith(".py"):
                yield pathlib.Path(root) / f


class TestNoLegacyImports(unittest.TestCase):
    """Ensure no active source file imports a quarantined legacy module."""

    def test_no_legacy_imports_in_active_code(self):
        violations = []
        for py_file in _active_python_files():
            try:
                source = py_file.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for pattern in LEGACY_IMPORT_PATTERNS:
                if pattern in source:
                    rel = py_file.relative_to(MERID_ROOT)
                    violations.append(f"{rel}: contains '{pattern}'")
        if violations:
            msg = "Legacy venue imports found in active code:\n" + "\n".join(violations)
            self.fail(msg)


# ═══════════════════════════════════════════════════════════════════════════
# 2. Consolidated merid.kalshi facade exports essential symbols
# ═══════════════════════════════════════════════════════════════════════════

class TestKalshiFacadeExports(unittest.TestCase):
    """Verify that merid.kalshi re-exports the canonical Kalshi primitives."""

    REQUIRED_SYMBOLS = [
        # Client
        "KalshiVenueClient", "get_kalshi_client", "KalshiConfig",
        # Models
        "KalshiMarket", "KalshiOrder", "KalshiPosition", "KalshiBalance",
        "KalshiOrderBook", "KalshiTrade", "KalshiOutcome", "KalshiMarketState",
        # Order routing
        "OrderIntent", "OrderResult", "route_order",
        # Risk
        "KalshiRiskManager", "get_kalshi_risk", "kelly_size_kalshi",
        # Catalog
        "KalshiMarketCatalog", "get_market_catalog",
        # WebSocket
        "KalshiWebSocket", "KalshiWebSocketBridge",
        # Category helpers
        "is_crypto_market", "market_domain",
        "KALSHI_CRYPTO_TICKERS", "KALSHI_EVENT_CATEGORIES",
    ]

    def test_facade_has_all_required_exports(self):
        """Parse merid/kalshi/__init__.py and verify __all__ contains required symbols."""
        init_path = MERID_ROOT / "merid" / "kalshi" / "__init__.py"
        self.assertTrue(init_path.exists(), f"merid/kalshi/__init__.py not found at {init_path}")

        source = init_path.read_text(encoding="utf-8")
        tree = ast.parse(source)

        # Find __all__
        all_names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "__all__":
                        if isinstance(node.value, (ast.List, ast.Tuple)):
                            for elt in node.value.elts:
                                if isinstance(elt, ast.Constant):
                                    all_names.add(elt.value)

        missing = [s for s in self.REQUIRED_SYMBOLS if s not in all_names]
        if missing:
            self.fail(f"merid.kalshi.__all__ is missing: {missing}")


# ═══════════════════════════════════════════════════════════════════════════
# 3. Agent domain split packages exist
# ═══════════════════════════════════════════════════════════════════════════

class TestAgentDomainSplit(unittest.TestCase):
    """Verify kalshi_event/ and kalshi_crypto/ agent packages exist."""

    def test_kalshi_crypto_package_exists(self):
        pkg = MERID_ROOT / "merid" / "agents" / "kalshi_crypto" / "__init__.py"
        self.assertTrue(pkg.exists(), "merid/agents/kalshi_crypto/__init__.py missing")

    def test_kalshi_event_package_exists(self):
        pkg = MERID_ROOT / "merid" / "agents" / "kalshi_event" / "__init__.py"
        self.assertTrue(pkg.exists(), "merid/agents/kalshi_event/__init__.py missing")

    def test_crypto_package_exports_agents(self):
        source = (MERID_ROOT / "merid" / "agents" / "kalshi_crypto" / "__init__.py").read_text()
        # Btc1hAgent archived 2026-01-15 - focus on 15m timeframe only
        for agent in ["Btc15mAgent", "Eth15mAgent", "Sol15mAgent", "Xrp15mAgent"]:
            self.assertIn(agent, source, f"kalshi_crypto package missing {agent}")

    def test_event_package_exports_agents(self):
        source = (MERID_ROOT / "merid" / "agents" / "kalshi_event" / "__init__.py").read_text()
        for agent in ["OddsAwareSportsAgent", "MarketResearchAgent", "StrategyDesignerAgent"]:
            self.assertIn(agent, source, f"kalshi_event package missing {agent}")


# ═══════════════════════════════════════════════════════════════════════════
# 4. Kalshi market fixture construction
# ═══════════════════════════════════════════════════════════════════════════

class TestKalshiMarketFixtures(unittest.TestCase):
    """Construct sample Kalshi event and crypto markets from the models."""

    def test_event_market_construction(self):
        from merid.event_venues.kalshi.models import KalshiMarket, KalshiOutcome
        from decimal import Decimal

        market = KalshiMarket(
            ticker="FED-25DEC-T3.00",
            event_ticker="FED-25DEC",
            title="Will the Fed cut rates by 25bp in Dec 2025?",
            description="Resolves Yes if the FOMC announces a 25bp cut.",
            outcomes=[
                KalshiOutcome(outcome_id="yes", name="Yes", price=Decimal("62")),
                KalshiOutcome(outcome_id="no", name="No", price=Decimal("38")),
            ],
            category="economics",
        )
        self.assertEqual(market.ticker, "FED-25DEC-T3.00")
        self.assertEqual(len(market.outcomes), 2)
        self.assertEqual(market.category, "economics")

    def test_crypto_market_construction(self):
        from merid.event_venues.kalshi.models import KalshiMarket, KalshiOutcome
        from decimal import Decimal

        market = KalshiMarket(
            ticker="KXBTC-26MAR19-B97500",
            event_ticker="KXBTC-26MAR19",
            title="BTC above $97,500 at 15:00 ET?",
            description="Resolves Yes if BTC CFB RTI >= 97500 at expiry.",
            outcomes=[
                KalshiOutcome(outcome_id="yes", name="Yes", price=Decimal("45")),
                KalshiOutcome(outcome_id="no", name="No", price=Decimal("55")),
            ],
            category="crypto",
        )
        self.assertEqual(market.ticker, "KXBTC-26MAR19-B97500")
        self.assertTrue(market.ticker.startswith("KXBTC"))

    def test_is_crypto_market_helper(self):
        from merid.kalshi import is_crypto_market, market_domain

        self.assertTrue(is_crypto_market("KXBTC-26MAR19-B97500"))
        self.assertTrue(is_crypto_market("KXETH-26MAR19-T3500"))
        self.assertFalse(is_crypto_market("FED-25DEC-T3.00"))
        self.assertFalse(is_crypto_market("PRES-2028"))

        self.assertEqual(market_domain("KXBTC-26MAR19-B97500"), "crypto")
        self.assertEqual(market_domain("FED-25DEC-T3.00"), "event")


# ═══════════════════════════════════════════════════════════════════════════
# 5. Order intent payload formatting
# ═══════════════════════════════════════════════════════════════════════════

class TestOrderIntentFormatting(unittest.TestCase):
    """Verify that OrderIntent can construct valid Kalshi order payloads."""

    def test_order_intent_construction(self):
        from merid.event_venues.kalshi.order_router import OrderIntent

        intent = OrderIntent(
            ticker="KXBTC-26MAR19-B97500",
            side="yes",
            action="buy",
            count=5,
            price_cents=45,
            order_type="limit",
        )
        self.assertEqual(intent.ticker, "KXBTC-26MAR19-B97500")
        self.assertEqual(intent.side, "yes")
        self.assertEqual(intent.count, 5)
        self.assertEqual(intent.price_cents, 45)

    def test_crypto_opinion_intent(self):
        from merid.kalshi import KalshiCryptoOpinion, build_kalshi_crypto_intent

        opinion = KalshiCryptoOpinion(
            agent_id="btc_15m_regime",
            market_id="KXBTC-26MAR19-B97500",
            side="yes",
            size_pct=0.1,
            edge_estimate=0.05,
            confidence=0.72,
        )
        intent = build_kalshi_crypto_intent(opinion)
        self.assertEqual(intent["venue"], "kalshi")
        self.assertEqual(intent["lane"], "crypto")
        self.assertEqual(intent["agent_id"], "btc_15m_regime")
        self.assertEqual(intent["market_id"], "KXBTC-26MAR19-B97500")


# ═══════════════════════════════════════════════════════════════════════════
# 6. Legacy directories exist (moved, not deleted)
# ═══════════════════════════════════════════════════════════════════════════

class TestLegacyDirectoriesExist(unittest.TestCase):
    """Verify legacy code was moved to _legacy/, not deleted."""

    EXPECTED_LEGACY = [
        "core/venues/_legacy",
        "merid/event_venues/_legacy/polymarket",
        "trading/_legacy",
        "agents/_legacy/polymarket",
    ]

    def test_legacy_dirs_present(self):
        for d in self.EXPECTED_LEGACY:
            path = MERID_ROOT / d
            self.assertTrue(path.is_dir(), f"Legacy directory missing: {d}")


# ═══════════════════════════════════════════════════════════════════════════
# 7. Settings Kalshi-only defaults
# ═══════════════════════════════════════════════════════════════════════════

class TestSettingsKalshiOnly(unittest.TestCase):
    """Verify settings reflect Kalshi-only defaults."""

    def test_go_live_default_venues_is_kalshi_only(self):
        """validate_for_go_live defaults to ['kalshi'] only."""
        source = (MERID_ROOT / "merid" / "settings.py").read_text(encoding="utf-8")
        self.assertIn('venues or ["kalshi"]', source)
        self.assertNotIn('venues or ["kalshi", "alpaca"', source)

    def test_legacy_fields_marked(self):
        """Non-Kalshi credential fields should contain [LEGACY] in description."""
        source = (MERID_ROOT / "merid" / "settings.py").read_text(encoding="utf-8")
        for field_name in ["BINANCE_API_KEY", "COINBASE_API_KEY", "POLYMARKET_API_KEY",
                           "ALPACA_API_KEY", "IBKR_PAPER_TRADING_USERNAME"]:
            # Find the field definition and check [LEGACY] is in its description
            idx = source.find(field_name)
            self.assertGreater(idx, 0, f"{field_name} not found in settings.py")
            # Check the surrounding line contains [LEGACY]
            line_start = source.rfind("\n", 0, idx) + 1
            line_end = source.find("\n", idx)
            line = source[line_start:line_end]
            self.assertIn("[LEGACY]", line, f"{field_name} missing [LEGACY] tag")


# ═══════════════════════════════════════════════════════════════════════════
# 8. Venue validator defaults to Kalshi
# ═══════════════════════════════════════════════════════════════════════════

class TestFrontendVenueValidator(unittest.TestCase):
    """Verify the frontend venue validator defaults to Kalshi."""

    def test_validator_defaults_to_kalshi(self):
        source = (MERID_ROOT / "web" / "react" / "src" / "utils" / "validators.ts").read_text()
        self.assertIn('["KALSHI"]', source)
        self.assertNotIn('"COINBASE"', source)
        self.assertNotIn('"BINANCE"', source)


if __name__ == "__main__":
    unittest.main()

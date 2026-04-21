"""
USDT Regression Guardrails — Prevent USDT reintroduction for major crypto assets.

These tests ensure that major crypto assets (BTC, ETH, SOL, XRP, DOGE) use USD
as the quote currency throughout the codebase, not USDT.
"""

import ast
import os
import re
from pathlib import Path
from typing import List, Set, Tuple

import pytest


# Major crypto assets that MUST use USD, not USDT
MAJOR_ASSETS = {"BTC", "ETH", "SOL", "XRP", "DOGE"}

# Forbidden USDT patterns for major assets (case insensitive)
FORBIDDEN_PATTERNS = [
    r"BTC[/\-:]USDT",
    r"ETH[/\-:]USDT",
    r"SOL[/\-:]USDT",
    r"XRP[/\-:]USDT",
    r"DOGE[/\-:]USDT",
    r"BTCUSDT",
    r"ETHUSDT",
    r"SOLUSDT",
    r"XRPUSDT",
    r"DOGEUSDT",
]

# Files that are allowed to have USDT references (legitimate exceptions)
ALLOWED_USDT_FILES = {
    # Perpetual futures settlement currency notation
    "tests/streams/test_market.py",  # BTC/USD:USDT is perp settlement notation
    "tests/streams/test_market_stream.py",
    # Alt-coin tests using USDT (non-major assets)
    "tests/core/test_execution_gate.py",  # LINK/USDT is acceptable
    # Asset universe tests for USDT as stablecoin category
    "tests/data/test_asset_universe.py",  # USDT in stablecoin category
    # Crypto.com executor tests use their own symbol format
    "tests/merid/execution/executors/test_crypto_com_coverage.py",
    "tests/merid/execution/executors/test_crypto_com.py",
    "tests/merid/execution/executors/test_fulcrom.py",
    "tests/pipeline/test_instruments.py",
    # Kalshi trading system may have legacy references
    "tests/event_venues/kalshi/test_trading_system.py",
    # Coinbase executor coverage
    "tests/merid/execution/executors/test_coinbase_executor_coverage.py",
    # Other test files with legitimate USDT usage for non-major assets
    "tests/smoke/test_paper_trading_smoke.py",
    "tests/test_sprint_bc.py",
    "tests/test_sprint_d.py",
    "tests/test_dev_swarm.py",
    "tests/test_ws_price_feed.py",
    # Core files with intentional USDT references
    "core/symbol_constants.py",  # DEPRECATED_USDT_SYMBOLS set for migration reference
    "arbitrage/perp_spot_scanner.py",  # :USDT is perp settlement currency notation
    # Binance API integration files (Binance uses BTCUSDT as native symbol)
    "merid/pipeline/instruments.py",  # Venue symbol mappings for Binance API
    "merid/sentiment/crypto_registry.py",  # Binance symbol registry
    "merid/strategies/binance_auth.py",  # Binance API calls
    "merid/strategies/binance_us_15m_btc.py",  # Binance API calls
    "merid/strategies/binance_us_data.py",  # Binance US data fetching
    "merid/strategies/compare_kelly_levels.py",  # Kelly strategy comparison
    "merid/strategies/kelly_vs_fixed_fraction.py",  # Kelly vs fixed fraction
    # Prediction model files (event-driven hedging)
    "prediction/cross_hedge.py",  # Cross-hedge logic
    "prediction/time_exploit.py",  # Time exploitation model
    # Legacy trading files (Binance API integration)
    "trading/execution_engine.py",  # Execution engine with Binance symbols
    "trading/_legacy/perp/adapters.py",  # Legacy perp adapters
    "trading/_legacy/perp/binance_perp.py",  # Binance perp integration
    "trading/_legacy/perp/perp/adapters.py",  # Legacy perp adapters (alt path)
    "trading/_legacy/perp/perp/binance_perp.py",  # Binance perp (alt path)
    # Web/API files (test/demo endpoints)
    "web/test_endpoint.py",  # Test endpoint with mock data
    "web/api/data_endpoints.py",  # Data endpoint examples
    "web/api/production_status.py",  # Production status checks
    "web/api/real_data_endpoints.py",  # Real data endpoints
    "web/api/schemas.py",  # API schema examples
    "web/api/us_compliant_markets.py",  # US compliant markets API
    "web/api/market_data.py",  # Market data API
    "web/api/mock_arbitrage.py",  # Mock arbitrage API
    "web/api/mock_trading.py",  # Mock trading API
    "web/api/dev_chat.py",  # Dev chat API
    "web/api/institutional.py",  # Institutional API
    "web/api/local_venue.py",  # Local venue API
}

# Directories to exclude from scanning
EXCLUDED_DIRECTORIES = {
    ".venv",
    ".git",
    "__pycache__",
    ".claude",
    ".pytest_cache",
    "node_modules",
    "archive",
}


def _get_repo_root() -> Path:
    """Get repository root directory."""
    return Path(__file__).parent.parent.parent


def _should_check_file(file_path: Path) -> bool:
    """Determine if a file should be checked for USDT violations."""
    # Skip non-Python files
    if not file_path.suffix == ".py":
        return False
    
    # Skip excluded directories
    path_str = str(file_path)
    for excluded in EXCLUDED_DIRECTORIES:
        if excluded in path_str:
            return False
    
    # Skip the audit script itself and this test file
    if file_path.name in ("_audit_usdt.py", "test_usdt_regression_guardrails.py"):
        return False
    
    # Check if file is in allowed list
    repo_root = _get_repo_root()
    rel_path = file_path.relative_to(repo_root).as_posix()
    if rel_path in ALLOWED_USDT_FILES:
        return False
    
    return True


def _find_usdt_violations_in_file(file_path: Path) -> List[Tuple[int, str, str]]:
    """Find USDT violations for major assets in a file."""
    violations = []
    
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
            lines = content.split("\n")
    except (UnicodeDecodeError, IOError):
        return violations
    
    for line_num, line in enumerate(lines, start=1):
        # Skip comments and strings that mention USDT in documentation
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith('"""') or stripped.startswith("'''"):
            continue
        
        # Check each forbidden pattern
        for pattern in FORBIDDEN_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                violations.append((line_num, line.strip(), pattern))
    
    return violations


class TestUSDTSymbolGuardrails:
    """Regression tests to prevent USDT reintroduction for major assets."""

    def test_symbol_constants_exports_usd_pairs(self):
        """Verify symbol_constants exports only USD pairs for major assets."""
        from core.symbol_constants import (
            BTC_USD,
            ETH_USD,
            SOL_USD,
            XRP_USD,
            DOGE_USD,
            MAJOR_CRYPTO_ASSETS,
        )
        
        # Verify all symbols use /USD format
        assert BTC_USD == "BTC/USD"
        assert ETH_USD == "ETH/USD"
        assert SOL_USD == "SOL/USD"
        assert XRP_USD == "XRP/USD"
        assert DOGE_USD == "DOGE/USD"
        
        # Verify no USDT in major crypto symbols
        for symbol in MAJOR_CRYPTO_ASSETS:
            assert "USDT" not in symbol, f"Found USDT in symbol: {symbol}"
            assert symbol.endswith("/USD"), f"Symbol {symbol} does not end with /USD"

    def test_deprecated_usdt_symbols_set_is_complete(self):
        """Verify DEPRECATED_USDT_SYMBOLS contains expected legacy USDT pairs."""
        from core.symbol_constants import DEPRECATED_USDT_SYMBOLS
        
        expected_deprecated = {
            "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "DOGE/USDT",
            "BTC-USDT", "ETH-USDT", "SOL-USDT", "XRP-USDT", "DOGE-USDT",
        }
        
        # All expected deprecated symbols should be in the set
        for symbol in expected_deprecated:
            assert symbol in DEPRECATED_USDT_SYMBOLS, f"Missing deprecated symbol: {symbol}"

    def test_normalize_to_usd_function(self):
        """Verify normalize_to_usd correctly converts USDT to USD."""
        from core.symbol_constants import normalize_to_usd
        
        # Test conversions
        assert normalize_to_usd("BTC/USDT") == "BTC/USD"
        assert normalize_to_usd("ETH-USDT") == "ETH/USD"
        assert normalize_to_usd("BTCUSDT") == "BTC/USD"
        
        # Test already USD symbols pass through or normalize
        assert normalize_to_usd("BTC/USD") == "BTC/USD"
        assert normalize_to_usd("ETH-USD") == "ETH/USD"  # Normalized to internal format
        
        # Test non-major assets are not affected
        assert normalize_to_usd("LINK/USDT") == "LINK/USDT"
        assert normalize_to_usd("SHIB/USDT") == "SHIB/USDT"

    def test_no_usdt_for_major_assets_in_core_symbol_constants(self):
        """Verify core symbol_constants module has no USDT references outside DEPRECATED set."""
        repo_root = _get_repo_root()
        file_path = repo_root / "core" / "symbol_constants.py"
        
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        # Should not have USDT for major assets (except in DEPRECATED set definition)
        lines = content.split("\n")
        in_deprecated_block = False
        in_docstring = False
        for line_num, line in enumerate(lines, start=1):
            # Track docstrings (triple quotes)
            if '"""' in line:
                in_docstring = not in_docstring
                continue
            if "'''" in line:
                in_docstring = not in_docstring
                continue
            
            # Skip everything inside docstrings (these are examples/docs)
            if in_docstring:
                continue
            
            # Track when we're inside the DEPRECATED_USDT_SYMBOLS definition
            if "DEPRECATED_USDT_SYMBOLS: Set[str]" in line:
                in_deprecated_block = True
                continue
            if in_deprecated_block and line.strip() == "}":
                in_deprecated_block = False
                continue
            
            # Skip lines inside the deprecated block
            if in_deprecated_block:
                continue
                
            # Skip comments
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            
            # Check for USDT violations
            for pattern in FORBIDDEN_PATTERNS:
                if re.search(pattern, line, re.IGNORECASE):
                    pytest.fail(f"Found USDT violation at line {line_num}: {line.strip()}")


class TestUSDTSymbolScan:
    """Scan codebase for USDT violations in major assets."""

    def test_no_major_asset_usdt_in_non_allowed_files(self):
        """
        Scan all Python files for USDT usage with major assets.
        This test will fail if USDT is used for BTC, ETH, SOL, XRP, or DOGE
        in files not explicitly allowed.
        """
        repo_root = _get_repo_root()
        violations_found = []
        
        # Scan all Python files
        for py_file in repo_root.rglob("*.py"):
            if not _should_check_file(py_file):
                continue
            
            file_violations = _find_usdt_violations_in_file(py_file)
            if file_violations:
                rel_path = py_file.relative_to(repo_root).as_posix()
                for line_num, line_content, pattern in file_violations:
                    violations_found.append(f"{rel_path}:{line_num} | {line_content}")
        
        if violations_found:
            violation_list = "\n".join(violations_found[:20])  # Show first 20
            pytest.fail(
                f"Found {len(violations_found)} USDT violations for major assets:\n{violation_list}\n"
                f"... and {len(violations_found) - 20} more violations. "
                f"Major assets (BTC, ETH, SOL, XRP, DOGE) must use USD, not USDT."
            )


class TestVenueSymbolMappings:
    """Test venue-specific symbol mappings use USD."""

    def test_coinbase_symbol_format(self):
        """Verify Coinbase symbols use USD format."""
        from core.symbol_constants import COINBASE_SYMBOLS
        
        # All Coinbase symbols should be {BASE}-USD format
        for asset in ["BTC", "ETH", "SOL", "XRP", "DOGE"]:
            symbol = COINBASE_SYMBOLS.get(asset)
            assert symbol == f"{asset}-USD", f"Coinbase symbol {symbol} should be {asset}-USD"
            assert "USDT" not in symbol

    def test_kalshi_symbol_format(self):
        """Verify Kalshi symbols use proper series format."""
        from core.symbol_constants import KALSHI_SERIES_BASE
        
        # All Kalshi series should not contain USDT
        for asset, series in KALSHI_SERIES_BASE.items():
            assert "USDT" not in series, f"Kalshi series {series} for {asset} contains USDT"
            assert series.startswith("KX"), f"Kalshi series {series} should start with KX"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

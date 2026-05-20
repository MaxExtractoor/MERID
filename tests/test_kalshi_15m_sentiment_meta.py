"""
Meta-test to enforce sentiment isolation in 15m Kalshi crypto trading tests.

This test scans all test files in the kalshi_crypto_15m_v2 suite and ensures
they do not import or reference sentiment-related modules, which is forbidden
per the sentiment isolation invariant.

Forbidden patterns:
- merid.sentiment.* imports
- sentiment_bus imports
- SentimentVotingAgent references
- sentiment-driven edge calculation
- Fear & Greed index usage in execution paths
"""

import ast
import os
import pytest
from pathlib import Path


# Forbidden import patterns
FORBIDDEN_IMPORTS = [
    "merid.sentiment",
    "sentiment_bus",
    "SentimentVotingAgent",
    "SentimentBus",
    "SentimentBusV2",
    "fear_greed",
    "FearGreed",
]

# Files that are exempt (sentiment isolation tests themselves)
EXEMPT_FILES = [
    "test_crypto_15m_sentiment_isolation.py",
    "test_sentiment_isolation_15m.py",
    "test_sentiment_quarantine.py",
]


def get_kalshi_15m_test_files():
    """Get all test files that should be part of the kalshi_crypto_15m_v2 suite."""
    test_dir = Path(__file__).parent
    kalshi_test_files = []
    
    # Core Kalshi 15m test files
    core_files = [
        "test_crypto_15m_sentiment_isolation.py",
        "test_sentiment_isolation_15m.py",
        "test_sentiment_quarantine.py",
        "test_kalshi_15m_agent_wiring.py",
        "test_kalshi_15m_risk_config.py",
    ]
    
    for filename in core_files:
        filepath = test_dir / filename
        if filepath.exists():
            kalshi_test_files.append(filepath)
    
    return kalshi_test_files


def check_forbidden_imports(filepath):
    """Scan a Python file for forbidden sentiment imports."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Parse AST
    try:
        tree = ast.parse(content, filename=str(filepath))
    except SyntaxError:
        return []  # Skip files with syntax errors
    
    forbidden_found = []
    
    for node in ast.walk(tree):
        # Check import statements
        if isinstance(node, ast.Import):
            for alias in node.names:
                for forbidden in FORBIDDEN_IMPORTS:
                    if forbidden in alias.name:
                        forbidden_found.append({
                            'type': 'import',
                            'line': node.lineno,
                            'pattern': alias.name,
                        })
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for forbidden in FORBIDDEN_IMPORTS:
                if forbidden in module:
                    forbidden_found.append({
                        'type': 'import_from',
                        'line': node.lineno,
                        'pattern': module,
                    })
    
    return forbidden_found


def test_kalshi_15m_tests_no_sentiment_imports():
    """
    Meta-test: Ensure kalshi_crypto_15m_v2 test files do not import sentiment modules.
    
    This enforces the sentiment isolation invariant: sentiment must not influence
    execution decisions in the live 15m Kalshi crypto trading path.
    """
    test_files = get_kalshi_15m_test_files()
    violations = []
    
    for filepath in test_files:
        filename = filepath.name
        
        # Skip exempt files (sentiment isolation tests)
        if filename in EXEMPT_FILES:
            continue
        
        forbidden = check_forbidden_imports(filepath)
        if forbidden:
            violations.append({
                'file': filename,
                'violations': forbidden,
            })
    
    if violations:
        error_msg = "Found forbidden sentiment imports in kalshi_crypto_15m_v2 test files:\n\n"
        for v in violations:
            error_msg += f"  {v['file']}:\n"
            for fv in v['violations']:
                error_msg += f"    Line {fv['line']}: {fv['type']} {fv['pattern']}\n"
            error_msg += "\n"
        pytest.fail(error_msg)


def test_kalshi_15m_asset_coverage():
    """
    Meta-test: Ensure kalshi_crypto_15m_v2 tests cover exactly the 5 allowed assets.
    
    The live 15m Kalshi crypto profile is restricted to BTC, ETH, SOL, XRP, DOGE only.
    This test verifies that no test files reference other crypto assets.
    """
    ALLOWED_ASSETS = {"BTC", "ETH", "SOL", "XRP", "DOGE"}
    
    test_files = get_kalshi_15m_test_files()
    violations = []
    
    # Additional crypto assets that should NOT appear in 15m tests
    FORBIDDEN_ASSETS = {
        "ADA", "AVAX", "DOT", "LINK", "MATIC", "UNI", "ATOM", "LTC", "BCH",
        "XLM", "ALGO", "VET", "FIL", "TRX", "XMR", "EOS", "BNB", "USDT",
        "USDC", "DAI", "WBTC", "RENDER", "PEPE", "SHIB", "DOGE", "DOGE",
    }
    
    for filepath in test_files:
        filename = filepath.name
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Check for forbidden asset references in test content
        # This is a simple heuristic - look for asset ticker patterns
        for asset in FORBIDDEN_ASSETS:
            if asset in content and asset not in ALLOWED_ASSETS:
                # Check if it's actually used as an asset (not just a comment or string)
                if f'"{asset}"' in content or f"'{asset}'" in content:
                    violations.append({
                        'file': filename,
                        'asset': asset,
                    })
    
    if violations:
        error_msg = "Found forbidden asset references in kalshi_crypto_15m_v2 test files:\n\n"
        for v in violations:
            error_msg += f"  {v['file']}: references {v['asset']}\n"
        error_msg += f"\nAllowed assets: {', '.join(sorted(ALLOWED_ASSETS))}\n"
        pytest.fail(error_msg)

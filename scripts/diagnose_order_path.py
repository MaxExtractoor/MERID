"""
Diagnostic script to trace full order path and expose where 42c fallbacks (midpoint of 10-75c range) and multi-contract orders are being generated.

This script will:
1. Trace signal generation and candidate creation
2. Trace price_cents assignment throughout the pipeline
3. Trace count assignment throughout the pipeline
4. Identify which code paths are actually being used
5. Expose where fixes are being bypassed
"""

import sys
import os
import logging
from pathlib import Path
import subprocess

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Setup detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    handlers=[
        logging.FileHandler('order_path_diagnostic.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger("ORDER_PATH_DIAGNOSTIC")

def run_grep(pattern, file_pattern="*.py"):
    """Run grep command and return results."""
    try:
        result = subprocess.run(
            ['rg', pattern, '--type', 'py', '-n', '--no-heading'],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            lines = result.stdout.strip().split('\n')
            return [line for line in lines if line]
        return []
    except Exception as e:
        logger.error(f"Error running grep for pattern '{pattern}': {e}")
        return []

def trace_price_cents_usage():
    """Search for all places where price_cents is set or used."""
    logger.info("=" * 80)
    logger.info("TRACING PRICE_CENTS USAGE ACROSS CODEBASE")
    logger.info("=" * 80)
    
    # Find all assignments to price_cents
    price_assignments = run_grep(r'price_cents\s*=')
    
    logger.info(f"\nFound {len(price_assignments)} price_cents assignments:")
    for line in price_assignments[:50]:  # Show first 50
        logger.info(f"  {line}")
    if len(price_assignments) > 50:
        logger.info(f"  ... and {len(price_assignments) - 50} more")
    
    # Find all hardcoded 50c values
    hardcoded_50c = run_grep(r'= 50\b|= 50\)|price_cents.*50')
    
    logger.info(f"\nFound {len(hardcoded_50c)} hardcoded 50c values:")
    for line in hardcoded_50c:
        logger.info(f"  {line}")
    
    # Find DEFAULT_KALSHI_PRICE_CENTS usage
    default_price = run_grep(r'DEFAULT_KALSHI_PRICE_CENTS')
    
    logger.info(f"\nFound {len(default_price)} DEFAULT_KALSHI_PRICE_CENTS references:")
    for line in default_price:
        logger.info(f"  {line}")

def trace_count_usage():
    """Search for all places where count/contracts is set or used."""
    logger.info("\n" + "=" * 80)
    logger.info("TRACING COUNT/CONTRACTS USAGE ACROSS CODEBASE")
    logger.info("=" * 80)
    
    # Find all assignments to count
    count_assignments = run_grep(r'\["count"\]\s*=|\.count\s*=|contracts\s*=')
    
    logger.info(f"\nFound {len(count_assignments)} count/contracts assignments:")
    for line in count_assignments[:50]:  # Show first 50
        logger.info(f"  {line}")
    if len(count_assignments) > 50:
        logger.info(f"  ... and {len(count_assignments) - 50} more")
    
    # Find all hardcoded count > 1
    hardcoded_count_gt1 = run_grep(r'count\s*=\s*[2-9]|contracts\s*=\s*[2-9]')
    
    logger.info(f"\nFound {len(hardcoded_count_gt1)} hardcoded count > 1:")
    for line in hardcoded_count_gt1:
        logger.info(f"  {line}")

def check_global_allocator():
    """Check if global_allocator.py has the 1 order per asset fix."""
    logger.info("\n" + "=" * 80)
    logger.info("CHECKING GLOBAL_ALLOCATOR.PY FOR 1 ORDER PER ASSET FIX")
    logger.info("=" * 80)
    
    allocator_path = project_root / "merid" / "risk" / "profiles" / "global_allocator.py"
    
    if not allocator_path.exists():
        logger.error(f"global_allocator.py not found at {allocator_path}")
        return
    
    with open(allocator_path, 'r') as f:
        content = f.read()
    
    # Check for asset_order_count
    if 'asset_order_count' in content:
        logger.info("✓ asset_order_count tracking found in global_allocator.py")
    else:
        logger.error("✗ asset_order_count tracking NOT found in global_allocator.py")
    
    # Check for 1 order per asset check
    if 'already has order in this cycle' in content:
        logger.info("✓ 1 order per asset check found in global_allocator.py")
    else:
        logger.error("✗ 1 order per asset check NOT found in global_allocator.py")
    
    # Check for the fix comment
    if '2026-07-09' in content and '1 order per asset' in content:
        logger.info("✓ Fix comment found in global_allocator.py")
    else:
        logger.error("✗ Fix comment NOT found in global_allocator.py")

def check_risk_parameters():
    """Check if risk_parameters.py has the 25c default."""
    logger.info("\n" + "=" * 80)
    logger.info("CHECKING RISK_PARAMETERS.PY FOR 25C DEFAULT")
    logger.info("=" * 80)
    
    risk_params_path = project_root / "merid" / "event_venues" / "kalshi" / "risk_parameters.py"
    
    if not risk_params_path.exists():
        logger.error(f"risk_parameters.py not found at {risk_params_path}")
        return
    
    with open(risk_params_path, 'r') as f:
        content = f.read()
    
    # Check for DEFAULT_KALSHI_PRICE_CENTS = 25
    if 'DEFAULT_KALSHI_PRICE_CENTS: Final[int] = 25' in content:
        logger.info("✓ DEFAULT_KALSHI_PRICE_CENTS = 25 found in risk_parameters.py")
    elif 'DEFAULT_KALSHI_PRICE_CENTS: Final[int] = 50' in content:
        logger.error("✗ DEFAULT_KALSHI_PRICE_CENTS still = 50 in risk_parameters.py")
    else:
        logger.warning("? DEFAULT_KALSHI_PRICE_CENTS value unclear in risk_parameters.py")

def check_agent_grid_15m():
    """Check if agent_grid_15m.py has the 25c fallback fix."""
    logger.info("\n" + "=" * 80)
    logger.info("CHECKING AGENT_GRID_15M.PY FOR 25C FALLBACK FIX")
    logger.info("=" * 80)
    
    agent_grid_path = project_root / "merid" / "prediction" / "agent_grid_15m.py"
    
    if not agent_grid_path.exists():
        logger.error(f"agent_grid_15m.py not found at {agent_grid_path}")
        return
    
    with open(agent_grid_path, 'r') as f:
        content = f.read()
    
    # Check for hardcoded 50c fallbacks
    hardcoded_50c_count = content.count('price_cents = 50')
    
    if hardcoded_50c_count == 0:
        logger.info("✓ No hardcoded 50c fallbacks found in agent_grid_15m.py")
    else:
        logger.error(f"✗ Found {hardcoded_50c_count} hardcoded 50c fallbacks in agent_grid_15m.py")
    
    # Check for 25c fallbacks
    hardcoded_25c_count = content.count('price_cents = 25')
    
    if hardcoded_25c_count > 0:
        logger.info(f"✓ Found {hardcoded_25c_count} hardcoded 25c fallbacks in agent_grid_15m.py")
    else:
        logger.warning("? No hardcoded 25c fallbacks found in agent_grid_15m.py")

def check_loop_15m():
    """Check if loop_15m.py has the 25c fallback fix."""
    logger.info("\n" + "=" * 80)
    logger.info("CHECKING LOOP_15M.PY FOR 25C FALLBACK FIX")
    logger.info("=" * 80)
    
    loop_path = project_root / "merid" / "loop_15m.py"
    
    if not loop_path.exists():
        logger.error(f"loop_15m.py not found at {loop_path}")
        return
    
    with open(loop_path, 'r') as f:
        content = f.read()
    
    # Check for hardcoded 50c fallbacks
    hardcoded_50c_count = content.count('price_cents = 50')
    
    if hardcoded_50c_count == 0:
        logger.info("✓ No hardcoded 50c fallbacks found in loop_15m.py")
    else:
        logger.error(f"✗ Found {hardcoded_50c_count} hardcoded 50c fallbacks in loop_15m.py")
    
    # Check for 25c fallbacks
    hardcoded_25c_count = content.count('price_cents = 25')
    
    if hardcoded_25c_count > 0:
        logger.info(f"✓ Found {hardcoded_25c_count} hardcoded 25c fallbacks in loop_15m.py")
    else:
        logger.warning("? No hardcoded 25c fallbacks found in loop_15m.py")

def check_global_execution_guard():
    """Check if global_execution_guard.py has the 10-50c price range fix."""
    logger.info("\n" + "=" * 80)
    logger.info("CHECKING GLOBAL_EXECUTION_GUARD.PY FOR 10-50C PRICE RANGE FIX")
    logger.info("=" * 80)
    
    guard_path = project_root / "merid" / "guards" / "global_execution_guard.py"
    
    if not guard_path.exists():
        logger.error(f"global_execution_guard.py not found at {guard_path}")
        return
    
    with open(guard_path, 'r') as f:
        content = f.read()
    
    # Check for 10-75c range
    if 'min_price_cents = 10' in content and 'max_price_cents = 75' in content:
        logger.info("✓ 10-75c price range found in global_execution_guard.py")
    elif 'min_price_cents = 50' in content:
        logger.error("✗ min_price_cents still = 50 in global_execution_guard.py (should be 10-75c)")
    else:
        logger.warning("? Price range unclear in global_execution_guard.py")

def check_pycache():
    """Check if pycache exists and might be serving stale code."""
    logger.info("\n" + "=" * 80)
    logger.info("CHECKING FOR PYCACHE THAT MIGHT SERVE STALE CODE")
    logger.info("=" * 80)
    
    pycache_dirs = list(project_root.rglob('__pycache__'))
    
    if pycache_dirs:
        logger.warning(f"✗ Found {len(pycache_dirs)} __pycache__ directories that might serve stale code:")
        for pycache_dir in pycache_dirs[:10]:  # Show first 10
            logger.info(f"  {pycache_dir}")
        if len(pycache_dirs) > 10:
            logger.info(f"  ... and {len(pycache_dirs) - 10} more")
    else:
        logger.info("✓ No __pycache__ directories found")

def check_import_paths():
    """Check if there are any imports from legacy paths that might bypass fixes."""
    logger.info("\n" + "=" * 80)
    logger.info("CHECKING FOR LEGACY IMPORT PATHS THAT MIGHT BYPASS FIXES")
    logger.info("=" * 80)
    
    from utils.code_search import search_codebase
    
    # Find imports from main.py (legacy)
    legacy_imports = search_codebase(
        pattern=r'from.*main\.py|import.*main\.py|from web\.main',
        file_patterns=['*.py'],
        exclude_dirs=['archive', 'legacy', '__pycache__', '.git']
    )
    
    if legacy_imports:
        logger.warning(f"✗ Found {len(legacy_imports)} imports from legacy main.py:")
        for file_path, line_num, line_content in legacy_imports:
            logger.info(f"  {file_path}:{line_num} - {line_content.strip()}")
    else:
        logger.info("✓ No imports from legacy main.py found")

def main():
    """Run all diagnostic checks."""
    logger.info("STARTING ORDER PATH DIAGNOSTIC")
    logger.info("=" * 80)
    
    # Run all checks
    trace_price_cents_usage()
    trace_count_usage()
    check_global_allocator()
    check_risk_parameters()
    check_agent_grid_15m()
    check_loop_15m()
    check_global_execution_guard()
    check_pycache()
    check_import_paths()
    
    logger.info("\n" + "=" * 80)
    logger.info("DIAGNOSTIC COMPLETE")
    logger.info("=" * 80)
    logger.info("Review the log file: order_path_diagnostic.log")

if __name__ == "__main__":
    main()

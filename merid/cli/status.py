"""
MERID CLI Status Display Module

Provides mode indicators and system status display for CLI tools.
"""

import sys
from typing import Optional

from merid.trading.trade_mode import get_trade_mode


def get_mode_color(mode: str) -> str:
    """Get ANSI color code for trading mode."""
    colors = {
        "sim": "\033[92m",      # Green
        "paper": "\033[93m",    # Yellow
        "live": "\033[91m",     # Red
    }
    return colors.get(mode.lower(), "\033[0m")


def get_mode_icon(mode: str) -> str:
    """Get icon for trading mode."""
    icons = {
        "sim": "🔬",
        "paper": "📄",
        "live": "⚡",
    }
    return icons.get(mode.lower(), "⚙️")


def reset_color() -> str:
    """Get ANSI reset code."""
    return "\033[0m"


def show_mode_banner(banner_width: int = 60) -> None:
    """
    Display a prominent mode banner at startup.
    
    Args:
        banner_width: Width of the banner in characters
    """
    mode = get_trade_mode()
    color = get_mode_color(mode)
    reset = reset_color()
    icon = get_mode_icon(mode)
    
    # Build banner
    title = f"MERID Trading System - {mode.upper()} MODE"
    padding = (banner_width - len(title) - 2) // 2
    
    print(f"{color}╔{'═' * banner_width}╗{reset}")
    print(f"{color}║{' ' * padding}{title}{' ' * (banner_width - len(title) - padding - 2)}║{reset}")
    print(f"{color}╚{'═' * banner_width}╝{reset}")
    
    # Mode-specific warnings
    if mode == "live":
        print(f"{color}⚠️  LIVE TRADING - REAL FUNDS AT RISK{reset}")
        print(f"{color}⚠️  All orders execute with real money{reset}")
        print(f"{color}⚠️  Kill switch active - use with caution{reset}")
    elif mode == "paper":
        print(f"📄 Paper trading mode - simulated execution")
        print(f"📄 Performance tracked but no real funds at risk")
    elif mode == "sim":
        print(f"🔬 Simulation mode - safe for testing")
        print(f"🔬 No external API calls, no real orders")


def show_compact_mode() -> None:
    """Show compact mode indicator (for prompts)."""
    mode = get_trade_mode()
    color = get_mode_color(mode)
    reset = reset_color()
    icon = get_mode_icon(mode)
    
    print(f"{color}[{icon} {mode.upper()}]{reset}", end=" ")


def get_mode_emoji(mode: Optional[str] = None) -> str:
    """Get just the mode emoji."""
    if mode is None:
        mode = get_trade_mode()
    return get_mode_icon(mode)


def print_header(text: str, level: int = 1) -> None:
    """Print a styled header."""
    mode = get_trade_mode()
    color = get_mode_color(mode)
    reset = reset_color()
    
    if level == 1:
        print(f"\n{color}━━━ {text} ━━━{reset}\n")
    elif level == 2:
        print(f"{color}── {text} ──{reset}")
    else:
        print(f"{color}• {text}{reset}")


def print_success(message: str) -> None:
    """Print success message with mode-appropriate coloring."""
    mode = get_trade_mode()
    if mode == "live":
        # In live mode, success is still serious
        print(f"✓ {message}")
    else:
        print(f"\033[92m✓ {message}\033[0m")


def print_warning(message: str) -> None:
    """Print warning message."""
    print(f"\033[93m⚠ {message}\033[0m")


def print_error(message: str) -> None:
    """Print error message."""
    print(f"\033[91m✗ {message}\033[0m", file=sys.stderr)


def print_info(message: str) -> None:
    """Print info message."""
    print(f"ℹ {message}")


def confirm_live_operation(operation: str) -> bool:
    """
    Require explicit confirmation for live mode operations.
    
    Args:
        operation: Description of the operation
        
    Returns:
        True if confirmed, False otherwise
    """
    mode = get_trade_mode()
    
    if mode != "live":
        return True
    
    color = get_mode_color("live")
    reset = reset_color()
    
    print(f"\n{color}╔════════════════════════════════════════════════════════╗{reset}")
    print(f"{color}║  ⚠️  LIVE MODE CONFIRMATION REQUIRED                  ║{reset}")
    print(f"{color}╠════════════════════════════════════════════════════════╣{reset}")
    print(f"{color}║  Operation: {operation:<45} ║{reset}")
    print(f"{color}║  Mode: LIVE - REAL FUNDS AT RISK                      ║{reset}")
    print(f"{color}╚════════════════════════════════════════════════════════╝{reset}")
    
    response = input(f"\n{color}Type 'LIVE' to confirm: {reset}").strip()
    
    if response == "LIVE":
        print_success("Confirmed - proceeding with live operation")
        return True
    else:
        print_error("Confirmation failed - operation cancelled")
        return False


def show_risk_summary() -> None:
    """Display current risk configuration summary."""
    from merid.config.unified_risk_enforcement import enforce_unified_risk_model
    
    try:
        result = enforce_unified_risk_model()
        
        print_header("Risk Configuration", level=2)
        
        if result.success:
            print_success("All risk configs conform to unified model")
        else:
            print_warning(f"Config issues: {len(result.violations)} violations")
            for v in result.violations:
                print(f"  • {v}")
        
        # Show final config values
        if result.final_config:
            print_info(f"Global risk cap: {result.final_config.get('max_risk_pct_global', 'N/A')}")
            print_info(f"Per-trade cap: {result.final_config.get('max_risk_pct_per_trade', 'N/A')}")
            print_info(f"Max edges: {result.final_config.get('max_concurrent_assets', 'N/A')}")
            
    except Exception as e:
        print_error(f"Could not load risk config: {e}")


# Convenience function for quick mode check
def check_mode(expected: Optional[str] = None) -> str:
    """
    Get current mode, optionally verify against expected.
    
    Args:
        expected: If provided, verify mode matches
        
    Returns:
        Current mode string
        
    Raises:
        RuntimeError: If expected mode doesn't match actual
    """
    mode = get_trade_mode()
    
    if expected and mode != expected:
        raise RuntimeError(
            f"Mode mismatch: expected {expected}, got {mode}"
        )
    
    return mode

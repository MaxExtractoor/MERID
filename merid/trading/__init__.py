"""Trading module for MERID."""

# Import the trade_mode submodule to make merid.trading.trade_mode work
from trading import trade_mode as trade_mode
from trading.trade_mode import get_trade_mode, set_trade_mode, TradeMode

__all__ = ["trade_mode", "get_trade_mode", "set_trade_mode", "TradeMode"]

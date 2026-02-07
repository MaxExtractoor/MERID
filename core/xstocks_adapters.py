"""
xStocks and Tokenized Assets Adapters for MERID
On-chain xStocks (TON, EVM) and regulated tokenized equities integration.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional

from core.multichain_wallet import ChainNetwork, get_multichain_wallet
from utils.logger import get_logger

logger = get_logger("core.xstocks_adapters")


class AssetType(Enum):
    """Type of tokenized asset."""
    XSTOCK_TON = "xstock_ton"
    XSTOCK_EVM = "xstock_evm"
    TOKENIZED_EQUITY = "tokenized_equity"
    SYNTHETIC_STOCK = "synthetic_stock"


class TradingHours(Enum):
    """Trading hours status."""
    OPEN = "open"
    CLOSED = "closed"
    PRE_MARKET = "pre_market"
    AFTER_HOURS = "after_hours"


@dataclass
class TokenizedAsset:
    """Tokenized asset metadata."""
    asset_id: str
    symbol: str
    underlying_symbol: str
    asset_type: AssetType
    chain: ChainNetwork
    contract_address: str
    issuer: str
    total_supply: float
    price_usd: float
    trading_hours: TradingHours
    metadata: Dict[str, Any]


@dataclass
class AssetQuote:
    """Quote for tokenized asset."""
    asset_id: str
    symbol: str
    bid: float
    ask: float
    last_price: float
    volume_24h: float
    change_24h: float
    timestamp: float


class XStocksTONAdapter:
    """Adapter for xStocks on TON blockchain."""
    
    def __init__(self):
        self.chain = ChainNetwork.TON
        self.wallet = get_multichain_wallet()
        self._asset_registry: Dict[str, TokenizedAsset] = {}
        self._initialize_assets()
    
    def _initialize_assets(self) -> None:
        """Initialize xStocks asset registry."""
        # Common xStocks on TON
        assets = [
            ("TSLA", "TSLAx", "Tesla Inc."),
            ("AAPL", "AAPLx", "Apple Inc."),
            ("GOOGL", "GOOGLx", "Alphabet Inc."),
            ("MSFT", "MSFTx", "Microsoft Corp."),
            ("AMZN", "AMZNx", "Amazon.com Inc."),
            ("NVDA", "NVDAx", "NVIDIA Corp.")
        ]
        
        for underlying, symbol, name in assets:
            asset = TokenizedAsset(
                asset_id=f"ton_{symbol.lower()}",
                symbol=symbol,
                underlying_symbol=underlying,
                asset_type=AssetType.XSTOCK_TON,
                chain=self.chain,
                contract_address=f"EQ{symbol}{'0' * 40}",
                issuer="xStocks Protocol",
                total_supply=1000000.0,
                price_usd=0.0,
                trading_hours=TradingHours.OPEN,
                metadata={"name": name, "underlying": underlying}
            )
            self._asset_registry[symbol] = asset
        
        logger.info(f"Initialized {len(self._asset_registry)} xStocks on TON")
    
    def get_asset(self, symbol: str) -> Optional[TokenizedAsset]:
        """Get asset by symbol."""
        return self._asset_registry.get(symbol)
    
    def get_quote(self, symbol: str) -> Optional[AssetQuote]:
        """Get quote for xStock."""
        asset = self.get_asset(symbol)
        if not asset:
            return None
        
        # In production, query TON DEX or oracle
        return AssetQuote(
            asset_id=asset.asset_id,
            symbol=symbol,
            bid=100.0,
            ask=100.5,
            last_price=100.25,
            volume_24h=50000.0,
            change_24h=0.02,
            timestamp=time.time()
        )
    
    def buy(self, symbol: str, quantity: float) -> Optional[str]:
        """Buy xStock."""
        asset = self.get_asset(symbol)
        if not asset:
            logger.error(f"Asset {symbol} not found")
            return None
        
        # Check trading hours
        if asset.trading_hours == TradingHours.CLOSED:
            logger.error(f"Market closed for {symbol}")
            return None
        
        logger.info(f"Buying {quantity} {symbol} on TON")
        
        # In production, execute swap on TON DEX
        tx_hash = self.wallet.send_transaction(
            chain=self.chain,
            to_address=asset.contract_address,
            value=0.0,
            data="0x"
        )
        
        return tx_hash
    
    def sell(self, symbol: str, quantity: float) -> Optional[str]:
        """Sell xStock."""
        asset = self.get_asset(symbol)
        if not asset:
            return None
        
        logger.info(f"Selling {quantity} {symbol} on TON")
        
        tx_hash = self.wallet.send_transaction(
            chain=self.chain,
            to_address=asset.contract_address,
            value=0.0,
            data="0x"
        )
        
        return tx_hash


class TokenizedEquityAdapter:
    """Adapter for regulated tokenized equities (Dinari-style)."""
    
    def __init__(self):
        import os
        self._api_base = os.getenv("TOKENIZED_EQUITY_API_BASE", "https://api.tokenized-equities.com")
        self._api_key = os.getenv("TOKENIZED_EQUITY_API_KEY", "")
        if not self._api_key:
            logger.warning("TOKENIZED_EQUITY_API_KEY not set - API calls will fail")
        self._asset_registry: Dict[str, TokenizedAsset] = {}
        self._initialize_assets()
    
    def _initialize_assets(self) -> None:
        """Initialize tokenized equity registry."""
        # Regulated tokenized equities
        assets = [
            ("SPY", "SPY Token", "SPDR S&P 500 ETF"),
            ("QQQ", "QQQ Token", "Invesco QQQ Trust"),
            ("TSLA", "TSLA Token", "Tesla Inc."),
            ("AAPL", "AAPL Token", "Apple Inc.")
        ]
        
        for symbol, token_name, name in assets:
            asset = TokenizedAsset(
                asset_id=f"equity_{symbol.lower()}",
                symbol=f"{symbol}t",
                underlying_symbol=symbol,
                asset_type=AssetType.TOKENIZED_EQUITY,
                chain=ChainNetwork.ETHEREUM,
                contract_address=f"0x{symbol}{'0' * 36}",
                issuer="Regulated Issuer",
                total_supply=10000000.0,
                price_usd=0.0,
                trading_hours=TradingHours.OPEN,
                metadata={"name": name, "underlying": symbol, "regulated": True}
            )
            self._asset_registry[f"{symbol}t"] = asset
        
        logger.info(f"Initialized {len(self._asset_registry)} tokenized equities")
    
    def get_asset(self, symbol: str) -> Optional[TokenizedAsset]:
        """Get asset by symbol."""
        return self._asset_registry.get(symbol)
    
    def get_quote(self, symbol: str) -> Optional[AssetQuote]:
        """Get quote for tokenized equity."""
        asset = self.get_asset(symbol)
        if not asset:
            return None
        
        # In production, call regulated API
        return AssetQuote(
            asset_id=asset.asset_id,
            symbol=symbol,
            bid=450.0,
            ask=450.5,
            last_price=450.25,
            volume_24h=100000.0,
            change_24h=0.015,
            timestamp=time.time()
        )
    
    def buy(self, symbol: str, quantity: float, kyc_verified: bool = False) -> Optional[str]:
        """Buy tokenized equity."""
        if not kyc_verified:
            logger.error("KYC verification required for tokenized equities")
            return None
        
        asset = self.get_asset(symbol)
        if not asset:
            return None
        
        # Check trading hours (US market hours)
        if not self._is_market_open():
            logger.error(f"US market closed for {symbol}")
            return None
        
        logger.info(f"Buying {quantity} {symbol} (regulated)")
        
        # In production, call regulated API
        return f"order_{int(time.time())}"
    
    def sell(self, symbol: str, quantity: float, kyc_verified: bool = False) -> Optional[str]:
        """Sell tokenized equity."""
        if not kyc_verified:
            logger.error("KYC verification required")
            return None
        
        asset = self.get_asset(symbol)
        if not asset:
            return None
        
        logger.info(f"Selling {quantity} {symbol} (regulated)")
        
        return f"order_{int(time.time())}"
    
    def _is_market_open(self) -> bool:
        """Check if US market is open."""
        # In production, check actual market hours (9:30 AM - 4:00 PM ET)
        return True


class SymbolNormalizer:
    """Normalizes symbols across different tokenized asset platforms."""
    
    def __init__(self):
        self._symbol_map: Dict[str, Dict[str, str]] = {}
        self._initialize_mappings()
    
    def _initialize_mappings(self) -> None:
        """Initialize symbol mappings."""
        # Map underlying -> tokenized symbols
        self._symbol_map = {
            "TSLA": {
                "xstock_ton": "TSLAx",
                "xstock_evm": "xTSLA",
                "tokenized_equity": "TSLAt",
                "underlying": "TSLA"
            },
            "AAPL": {
                "xstock_ton": "AAPLx",
                "xstock_evm": "xAAPL",
                "tokenized_equity": "AAPLt",
                "underlying": "AAPL"
            },
            "SPY": {
                "tokenized_equity": "SPYt",
                "underlying": "SPY"
            }
        }
    
    def normalize(self, symbol: str) -> Dict[str, str]:
        """Get all variants of a symbol."""
        # Try to find in map
        for underlying, variants in self._symbol_map.items():
            if symbol in variants.values() or symbol == underlying:
                return variants
        
        return {"underlying": symbol}
    
    def get_underlying(self, symbol: str) -> str:
        """Get underlying symbol."""
        variants = self.normalize(symbol)
        return variants.get("underlying", symbol)
    
    def get_variant(self, underlying: str, asset_type: AssetType) -> Optional[str]:
        """Get symbol variant for asset type."""
        if underlying not in self._symbol_map:
            return None
        
        type_key = asset_type.value
        return self._symbol_map[underlying].get(type_key)


class XStocksRouter:
    """Routes xStocks trades to best venue."""
    
    def __init__(self):
        self._ton_adapter = XStocksTONAdapter()
        self._equity_adapter = TokenizedEquityAdapter()
        self._normalizer = SymbolNormalizer()
    
    def get_best_quote(self, underlying_symbol: str) -> Optional[tuple[AssetQuote, AssetType]]:
        """Get best quote across all venues."""
        quotes = []
        
        # Check TON xStocks
        ton_symbol = self._normalizer.get_variant(underlying_symbol, AssetType.XSTOCK_TON)
        if ton_symbol:
            quote = self._ton_adapter.get_quote(ton_symbol)
            if quote:
                quotes.append((quote, AssetType.XSTOCK_TON))
        
        # Check tokenized equities
        equity_symbol = self._normalizer.get_variant(underlying_symbol, AssetType.TOKENIZED_EQUITY)
        if equity_symbol:
            quote = self._equity_adapter.get_quote(equity_symbol)
            if quote:
                quotes.append((quote, AssetType.TOKENIZED_EQUITY))
        
        if not quotes:
            return None
        
        # Return best quote (lowest ask for buy)
        return min(quotes, key=lambda q: q[0].ask)
    
    def buy(
        self,
        underlying_symbol: str,
        quantity: float,
        preferred_type: Optional[AssetType] = None,
        kyc_verified: bool = False
    ) -> Optional[str]:
        """Buy tokenized asset on best venue."""
        if preferred_type:
            # Use preferred venue
            if preferred_type == AssetType.XSTOCK_TON:
                symbol = self._normalizer.get_variant(underlying_symbol, AssetType.XSTOCK_TON)
                if symbol:
                    return self._ton_adapter.buy(symbol, quantity)
            elif preferred_type == AssetType.TOKENIZED_EQUITY:
                symbol = self._normalizer.get_variant(underlying_symbol, AssetType.TOKENIZED_EQUITY)
                if symbol:
                    return self._equity_adapter.buy(symbol, quantity, kyc_verified)
        
        # Find best venue
        best = self.get_best_quote(underlying_symbol)
        if not best:
            logger.error(f"No quotes available for {underlying_symbol}")
            return None
        
        quote, asset_type = best
        
        if asset_type == AssetType.XSTOCK_TON:
            return self._ton_adapter.buy(quote.symbol, quantity)
        elif asset_type == AssetType.TOKENIZED_EQUITY:
            return self._equity_adapter.buy(quote.symbol, quantity, kyc_verified)
        
        return None
    
    def get_all_assets(self) -> List[TokenizedAsset]:
        """Get all available tokenized assets."""
        assets = []
        assets.extend(self._ton_adapter._asset_registry.values())
        assets.extend(self._equity_adapter._asset_registry.values())
        return assets
    
    def get_routing_stats(self) -> Dict[str, Any]:
        """Get routing statistics."""
        return {
            "xstocks_ton": len(self._ton_adapter._asset_registry),
            "tokenized_equities": len(self._equity_adapter._asset_registry),
            "total_assets": len(self.get_all_assets())
        }


# Global router
_xstocks_router: Optional[XStocksRouter] = None


def get_xstocks_router() -> XStocksRouter:
    """Get the global xStocks router."""
    global _xstocks_router
    if _xstocks_router is None:
        _xstocks_router = XStocksRouter()
    return _xstocks_router

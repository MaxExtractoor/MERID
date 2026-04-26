"""DecimalEncoder — Central type converter for all financial data.

Prevents TypeError: unsupported operand type(s) for float and Decimal
by providing a single point of conversion for all external data ingestion.
"""

from decimal import Decimal, InvalidOperation
from typing import Union, Dict, Any, Optional


class DecimalEncoder:
    """Central type converter for all financial data.
    
    All external data (JSON, APIs, databases) must pass through these
    conversion methods before use in financial calculations.
    """
    
    @staticmethod
    def to_decimal(value: Union[str, int, float, Decimal, None]) -> Decimal:
        """Convert any numeric to Decimal, handling None/null.
        
        CRITICAL: Never pass float directly to Decimal() - always use str() first.
        float -> str -> Decimal preserves the literal value.
        float -> Decimal introduces binary floating point errors.
        
        Args:
            value: Input value (str, int, float, Decimal, or None)
            
        Returns:
            Decimal: Safe Decimal representation
            
        Raises:
            InvalidOperation: If value cannot be converted to Decimal
        """
        if value is None or value == '':
            return Decimal('0')
        if isinstance(value, Decimal):
            return value
        # CRITICAL: Convert float to str first to avoid binary FP errors
        return Decimal(str(value))
    
    @staticmethod
    def to_decimal_safe(value: Union[str, int, float, Decimal, None], default: Decimal = Decimal('0')) -> Decimal:
        """Safe version that never raises, returns default on failure or None."""
        if value is None or value == '':
            return default
        try:
            return DecimalEncoder.to_decimal(value)
        except (InvalidOperation, ValueError, TypeError):
            return default
    
    @staticmethod
    def to_int(value: Any, default: int = 0) -> int:
        """Convert any value to int safely."""
        if value is None:
            return default
        try:
            if isinstance(value, Decimal):
                return int(value.to_integral_value())
            return int(value)
        except (ValueError, TypeError):
            return default
    
    @staticmethod
    def parse_market_data(api_response: Dict[str, Any]) -> Dict[str, Any]:
        """Parse Kalshi API response with Decimal enforcement.
        
        Args:
            api_response: Raw API response dict
            
        Returns:
            Dict with Decimal-converted price fields
        """
        result = {}
        
        # Price fields that must be Decimal
        price_fields = [
            'last_price', 'best_bid', 'best_ask', 
            'yes_bid', 'yes_ask', 'no_bid', 'no_ask',
            'mid_price', 'mark_price', 'index_price',
            'payout_cents', 'cost_per_contract_cents'
        ]
        
        for field in price_fields:
            if field in api_response:
                result[field] = DecimalEncoder.to_decimal_safe(api_response[field])
        
        # Integer fields
        int_fields = ['volume', 'open_interest', 'liquidity', 'open_interest_change']
        for field in int_fields:
            if field in api_response:
                result[field] = DecimalEncoder.to_int(api_response[field])
        
        # Pass through other fields unchanged
        for key, val in api_response.items():
            if key not in result:
                result[key] = val
                
        return result
    
    @staticmethod
    def parse_order_data(order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Parse order data with Decimal enforcement for prices.
        
        Args:
            order_data: Raw order dict (from API or internal)
            
        Returns:
            Dict with Decimal-converted price fields
        """
        result = dict(order_data)  # Shallow copy
        
        # Price fields
        price_fields = [
            'price', 'price_cents', 'limit_price', 'limit_price_cents',
            'fill_price', 'fill_price_cents', 'avg_fill_price',
            'fee', 'fee_cents', 'notional', 'notional_usd'
        ]
        
        for field in price_fields:
            if field in result:
                result[field] = DecimalEncoder.to_decimal_safe(result[field])
        
        # Integer fields
        int_fields = ['contracts', 'quantity', 'filled', 'remaining']
        for field in int_fields:
            if field in result:
                result[field] = DecimalEncoder.to_int(result[field])
        
        return result
    
    @staticmethod
    def coerce_for_calculation(*values: Any) -> tuple[Decimal, ...]:
        """Coerce multiple values to Decimal for safe arithmetic.
        
        Usage:
            price, contracts, edge = DecimalEncoder.coerce_for_calculation(
                raw_price, raw_contracts, raw_edge
            )
            notional = price * contracts  # Safe: both Decimal
        """
        return tuple(DecimalEncoder.to_decimal_safe(v) for v in values)


def safe_decimal(value: Any, default: Union[Decimal, str, float, int] = Decimal('0')) -> Decimal:
    """Module-level convenience function for safe Decimal conversion.
    
    Usage:
        from merid.utils.decimal_encoder import safe_decimal
        
        price = safe_decimal(api_response.get('price'))
        notional = price * contracts  # Safe arithmetic
    """
    # Normalize default to Decimal
    if isinstance(default, Decimal):
        dec_default = default
    elif isinstance(default, str):
        dec_default = Decimal(default)
    elif isinstance(default, (int, float)):
        dec_default = Decimal(str(default))
    else:
        dec_default = Decimal('0')
    
    return DecimalEncoder.to_decimal_safe(value, dec_default)

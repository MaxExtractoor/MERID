"""
Backend Snapshot Fetcher — Fetch complete backend state from Kalshi API

This module provides functions to fetch a complete backend snapshot from Kalshi API
for use with the new risk projection pipeline.

Usage:
    from merid.event_venues.kalshi.backend_snapshot_fetcher import fetch_backend_snapshot
    
    snapshot = await fetch_backend_snapshot()
    projection = engine.compute_projection(snapshot)
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional

from utils.logger import get_logger

from merid.event_venues.kalshi.risk_projection import (
    BackendBalance,
    BackendFill,
    BackendPosition,
    BackendSnapshot,
)

logger = get_logger("merid.event_venues.kalshi.backend_snapshot_fetcher")


async def fetch_backend_snapshot(
    kalshi_client: Optional[Any] = None,
) -> BackendSnapshot:
    """Fetch complete backend state from Kalshi API.
    
    This fetches positions, balance, and fills from Kalshi API and constructs
    a BackendSnapshot for the new risk projection pipeline.
    
    Args:
        kalshi_client: Optional Kalshi client instance (will fetch singleton if None)
        
    Returns:
        BackendSnapshot with complete backend state
        
    Raises:
        Exception: If API calls fail
    """
    timestamp = datetime.now(timezone.utc)
    
    # Get client if not provided
    if kalshi_client is None:
        try:
            from merid.event_venues.kalshi.client import get_kalshi_client
            kalshi_client = get_kalshi_client()
        except Exception as e:
            logger.error(f"Failed to get Kalshi client: {e}")
            raise
    
    # Fetch positions
    positions = await _fetch_positions(kalshi_client)
    
    # Fetch balance
    balance = await _fetch_balance(kalshi_client)
    
    # Fetch fills (optional - for audit, not required for projection)
    fills = await _fetch_fills(kalshi_client, limit=100)
    
    snapshot = BackendSnapshot(
        positions=positions,
        balance=balance,
        fills=fills,
        timestamp=timestamp,
    )
    
    logger.info(
        "[SOURCE=backend] Snapshot fetched: positions=%d balance=$%.2f fills=%d",
        len(positions),
        balance.available_usd,
        len(fills),
    )
    
    return snapshot


async def _fetch_positions(kalshi_client: Any) -> List[BackendPosition]:
    """Fetch positions from Kalshi API."""
    try:
        result = await kalshi_client.get_positions_result()
        
        if not result.success:
            logger.error(f"Failed to fetch positions: {result.error}")
            return []
        
        # Convert to BackendPosition
        positions = []
        for venue_pos in result.data:
            # VenuePosition has: market_id, outcome_id, size, average_entry_price, unrealized_pnl, realized_pnl
            try:
                position = BackendPosition(
                    ticker=venue_pos.market_id,
                    side=venue_pos.outcome_id if venue_pos.outcome_id else "yes",  # "yes" or "no"
                    count=int(venue_pos.size),
                    avg_price_dollars=venue_pos.average_entry_price,  # Already in dollars
                    total_cost_dollars=venue_pos.average_entry_price * venue_pos.size,
                    unrealized_pnl_dollars=venue_pos.unrealized_pnl if venue_pos.unrealized_pnl else Decimal("0"),
                    realized_pnl_dollars=venue_pos.realized_pnl if venue_pos.realized_pnl else Decimal("0"),
                    created_at=venue_pos.created_at if venue_pos.created_at else datetime.now(timezone.utc),
                )
                positions.append(position)
            except Exception as e:
                logger.warning(f"Failed to convert VenuePosition to BackendPosition: {e}")
        
        logger.debug(f"[SOURCE=backend] Fetched {len(positions)} positions from Kalshi API")
        return positions
        
    except Exception as e:
        logger.error(f"Failed to fetch positions from Kalshi API: {e}")
        return []


async def _fetch_balance(kalshi_client: Any) -> BackendBalance:
    """Fetch balance from Kalshi API."""
    try:
        result = await kalshi_client.get_balance_result()
        
        if not result.success:
            logger.error(f"Failed to fetch balance: {result.error}")
            # Return zero balance on failure
            return BackendBalance(available_usd=Decimal("0"), locked_usd=Decimal("0"))
        
        balance = result.data
        # Handle both dict and object balance responses
        if isinstance(balance, dict):
            available = Decimal(str(balance.get("available_usd", balance.get("USD", 0))))
            locked = Decimal(str(balance.get("locked_usd", balance.get("locked", 0))))
        else:
            available = Decimal(str(balance.available_usd))
            locked = Decimal(str(balance.locked_usd))
        
        backend_balance = BackendBalance(
            available_usd=available,
            locked_usd=locked,
        )
        
        logger.debug(
            f"[SOURCE=backend] Fetched balance from Kalshi API: available=${available:.2f} locked=${locked:.2f}"
        )
        return backend_balance
        
    except Exception as e:
        logger.error(f"Failed to fetch balance from Kalshi API: {e}")
        return BackendBalance(available_usd=Decimal("0"), locked_usd=Decimal("0"))


async def _fetch_fills(kalshi_client: Any, limit: int = 100) -> List[BackendFill]:
    """Fetch fills from Kalshi API (for audit, not required for projection)."""
    try:
        # Try to fetch fills from fills poller or client
        from merid.event_venues.kalshi.fills_poller import get_fills_poller
        
        poller = get_fills_poller()
        if poller:
            # Get recent fills from poller's cache - handle different API
            try:
                fills_data = poller.get_recent_fills(limit=limit)
            except AttributeError:
                # Fallback: try alternative method
                fills_data = getattr(poller, 'recent_fills', [])[:limit]
            
            fills = []
            for fill_data in fills_data:
                try:
                    fill = BackendFill(
                        fill_id=fill_data.get("fill_id", ""),
                        trade_id=fill_data.get("trade_id"),
                        order_id=fill_data.get("order_id", ""),
                        ticker=fill_data.get("ticker", ""),
                        side=fill_data.get("side", ""),
                        action=fill_data.get("action", ""),
                        count=fill_data.get("count", 0),
                        yes_price_dollars=fill_data.get("yes_price"),
                        no_price_dollars=fill_data.get("no_price"),
                        fee_cost_dollars=fill_data.get("fee_cost", 0),
                        proceeds_dollars=fill_data.get("proceeds"),
                        created_time=fill_data.get("created_time", datetime.now(timezone.utc)),
                    )
                    fills.append(fill)
                except Exception as e:
                    logger.warning(f"Failed to convert fill to BackendFill: {e}")
            
            logger.debug(f"[SOURCE=backend] Fetched {len(fills)} fills from fills poller")
            return fills
        
        # Fallback: try client.get_trades()
        try:
            result = await kalshi_client.get_trades_result()
            if result.success:
                fills = []
                for trade in result.data[:limit]:
                    try:
                        fill = BackendFill(
                            fill_id=trade.trade_id,
                            trade_id=trade.trade_id,
                            order_id=trade.order_id,
                            ticker=trade.ticker,
                            side=trade.side,
                            action="buy",  # Kalshi trades don't distinguish buy/sell in the same way
                            count=trade.count,
                            yes_price_dollars=trade.price if trade.side == "yes" else None,
                            no_price_dollars=trade.price if trade.side == "no" else None,
                            fee_cost_dollars=trade.fee,
                            proceeds_dollars=None,
                            created_time=trade.timestamp,
                        )
                        fills.append(fill)
                    except Exception as e:
                        logger.warning(f"Failed to convert trade to BackendFill: {e}")
                
                logger.debug(f"[SOURCE=backend] Fetched {len(fills)} fills from Kalshi client")
                return fills
        except Exception as e:
            logger.warning(f"Failed to fetch fills from client: {e}")
        
        return []
        
    except Exception as e:
        logger.warning(f"Failed to fetch fills: {e}")
        return []


async def fetch_and_validate_snapshot(kalshi_client: Optional[Any] = None) -> BackendSnapshot:
    """Fetch backend snapshot with validation.
    
    This is the preferred entry point for the new pipeline as it includes
    schema validation at the edge.
    
    Args:
        kalshi_client: Optional Kalshi client instance
        
    Returns:
        Validated BackendSnapshot
        
    Raises:
        SchemaError: If validation fails
    """
    snapshot = await fetch_backend_snapshot(kalshi_client)
    
    # Validate positions
    for pos in snapshot.positions:
        from merid.event_venues.kalshi.risk_projection import validate_backend_position
        try:
            validate_backend_position(pos.to_dict())
        except Exception as e:
            logger.error(f"[SOURCE=backend] Position validation failed for {pos.ticker}: {e}")
            raise
    
    # Validate balance
    from merid.event_venues.kalshi.risk_projection import validate_backend_balance
    try:
        validate_backend_balance(snapshot.balance.to_dict())
    except Exception as e:
        logger.error(f"[SOURCE=backend] Balance validation failed: {e}")
        raise
    
    logger.info("[SOURCE=backend] Snapshot validated successfully")
    return snapshot

"""
Integration layer for WindowAllocator into existing 15m trading stack.

This module bridges the existing GlobalAllocator flow with the new WindowAllocator,
providing a drop-in replacement that enforces 15-minute window constraints.

Integration Points:
1. agent_grid_15m.py: Replace GlobalAllocator with WindowAllocator
2. order_router.py: Wire in order lifecycle callbacks
3. loop_15m.py: Add window allocator processing to 5s cadence
"""

from typing import Dict, List, Optional, Any
from utils.logger import get_logger
from merid.event_venues.kalshi.binary_price_space import require_outcome_side, SideValidationError

logger = get_logger("merid.risk.profiles.window_allocator_integration")


def convert_candidate_dict_to_window_candidate(candidate: Dict[str, Any]) -> Optional[Any]:
    """
    Convert agent_grid candidate dict to WindowAllocator Candidate.
    
    Args:
        candidate: Candidate dict from agent_grid_15m
        
    Returns:
        Candidate object for WindowAllocator, or None if conversion fails
    """
    try:
        from merid.risk.profiles.window_allocator import Candidate
        
        # CRITICAL FIX (2026-07-21): Use canonical identity helper for asset extraction
        from merid.utils.kalshi_identity import extract_asset
        
        # Extract asset from agent_id or ticker
        agent_id = candidate.get('agent_id', '')
        ticker = candidate.get('ticker', '')

        if ticker:
            # Prefer ticker for asset extraction (more reliable)
            asset = extract_asset(ticker)
        elif agent_id:
            # Fallback to agent_id
            asset = agent_id.split('_')[0].upper() if '_' in agent_id else agent_id.upper()
            if asset not in ("BTC", "ETH", "SOL", "XRP", "DOGE"):
                asset = candidate.get('asset', 'UNKNOWN')
        else:
            asset = candidate.get('asset', 'UNKNOWN')

        # Fail-closed: a candidate without a valid side is not executable.
        try:
            side = require_outcome_side(
                candidate,
                context=f"window_allocator_integration candidate={ticker}",
                fields=("side", "outcome_side", "kalshi_side", "thesis_side"),
            )
        except SideValidationError as side_err:
            logger.error("[WINDOW-ALLOCATOR-SIDE-INVALID] %s", side_err)
            return None

        # Extract edge_pct (could be in FRACTION or PERCENT units)
        edge_pct = candidate.get('edge_pct', 0.0)
        if edge_pct > 1.0:
            edge_pct = edge_pct / 100.0  # Convert PERCENT to FRACTION

        # Extract price
        price_cents = int(candidate.get('price_cents', 50))
        target_price = price_cents / 100.0

        return Candidate(
            asset=asset,
            side=side,
            action=candidate.get('action', 'buy'),
            contract_id=candidate.get('ticker', ''),
            edge=edge_pct,
            fair_price=target_price,  # Use target price as fair price for now
            target_price=target_price,
            confidence=float(candidate.get('confidence', 0.5)),
            agent_id=agent_id,
        )
    except Exception as e:
        logger.warning("[WINDOW-ALLOCATOR-INTEGRATION] Failed to convert candidate: %s", e)
        return None


def submit_candidates_to_window_allocator(
    candidates: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """
    Submit candidates to WindowAllocator and return selected ones.
    
    This replaces the GlobalAllocator.allocate() call in agent_grid_15m.py.
    
    Args:
        candidates: List of candidate dicts from agent_grid_15m
        
    Returns:
        List of selected candidate dicts (original format)
    """
    from merid.risk.profiles.window_allocator import get_window_allocator
    
    allocator = get_window_allocator()
    
    # Convert and submit candidates
    for candidate in candidates:
        window_candidate = convert_candidate_dict_to_window_candidate(candidate)
        if window_candidate:
            accepted, reason = allocator.submit_candidate(window_candidate)
            if not accepted:
                logger.debug(
                    "[WINDOW-ALLOCATOR-INTEGRATION] Candidate rejected: asset=%s reason=%s",
                    window_candidate.asset, reason
                )
    
    # Process queued candidates
    selected_window_candidates = allocator.process_candidates()
    
    # Map back to original candidate dicts
    selected_candidates = []
    for window_candidate in selected_window_candidates:
        # Find original candidate dict
        for original in candidates:
            if original.get('ticker') == window_candidate.contract_id:
                selected_candidates.append(original)
                break
    
    logger.info(
        "[WINDOW-ALLOCATOR-INTEGRATION] Selected %d/%d candidates",
        len(selected_candidates), len(candidates)
    )
    
    return selected_candidates


def record_order_submitted(candidate: Dict[str, Any], order_id: str) -> None:
    """
    Record that an order was submitted for a candidate.
    
    Call this after order_router.route_order_async() is called.
    
    Args:
        candidate: Original candidate dict
        order_id: Order ID from order router
    """
    from merid.risk.profiles.window_allocator import get_window_allocator
    
    window_candidate = convert_candidate_dict_to_window_candidate(candidate)
    if window_candidate:
        allocator = get_window_allocator()
        allocator.record_order_submitted(window_candidate, order_id)


def record_order_filled(asset: str, order_id: str, fill_price_cents: int) -> None:
    """
    Record that an order was filled.
    
    Call this from WebSocket fill handler or order router.
    
    Args:
        asset: Asset symbol (BTC, ETH, etc.)
        order_id: Order ID
        fill_price_cents: Fill price in cents
    """
    from merid.risk.profiles.window_allocator import get_window_allocator
    
    allocator = get_window_allocator()
    allocator.record_order_filled(
        asset=asset,
        order_id=order_id,
        fill_price=fill_price_cents / 100.0,
        size=1
    )


def record_order_rejected(asset: str, order_id: str) -> None:
    """
    Record that an order was rejected.
    
    Call this from order router on rejection.
    
    Args:
        asset: Asset symbol (BTC, ETH, etc.)
        order_id: Order ID
    """
    from merid.risk.profiles.window_allocator import get_window_allocator
    
    allocator = get_window_allocator()
    allocator.record_order_rejected(asset, order_id)


def get_window_allocator_state() -> Dict:
    """
    Get current window allocator state for monitoring.
    
    Returns:
        Dict with allocator state
    """
    from merid.risk.profiles.window_allocator import get_window_allocator
    
    allocator = get_window_allocator()
    return allocator.get_state()

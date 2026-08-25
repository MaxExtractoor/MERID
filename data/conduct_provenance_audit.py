"""
Read-only historical provenance audit for identifying confirmed same-leg exits.
This script performs read-only analysis of the fills ledger - no modifications.
"""

import sqlite3
import json
from datetime import datetime
from collections import defaultdict

def get_candidate_sell_fills():
    """Step 1: Identify candidate normalized SELL fills."""
    conn = sqlite3.connect('kalshi_fills.db')
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT fill_id, order_id, client_order_id, market_ticker, side, action, count_fp, 
               yes_price_dollars, no_price_dollars, created_time, raw_payload
        FROM kalshi_fills 
        WHERE action = 'sell'
        ORDER BY created_time ASC
    """)
    
    candidates = cursor.fetchall()
    conn.close()
    
    return candidates

def reconstruct_ticker_history(ticker):
    """Step 2: Reconstruct complete per-ticker fill history."""
    conn = sqlite3.connect('kalshi_fills.db')
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT fill_id, order_id, client_order_id, market_ticker, side, action, count_fp, 
               yes_price_dollars, no_price_dollars, created_time, raw_payload
        FROM kalshi_fills 
        WHERE market_ticker = ?
        ORDER BY created_time ASC
    """, (ticker,))
    
    fills = cursor.fetchall()
    conn.close()
    
    return fills

def calculate_position_state(fills):
    """Step 3: Calculate position state using signed YES exposure (canonical)."""
    position_state = {
        'signed_yes_exposure': 0,  # Positive = long YES, Negative = long NO
        'yes_qty': 0,  # Absolute YES leg quantity
        'no_qty': 0,   # Absolute NO leg quantity
        'processed_fill_ids': set()
    }
    
    history = []
    
    for fill in fills:
        fill_id, order_id, client_order_id, ticker, side, action, count, yes_price, no_price, created_time, raw_payload = fill
        
        # Calculate signed YES exposure per Kalshi V2 semantics
        # BUY YES: +count (long YES)
        # SELL YES: -count (close YES)
        # BUY NO: -count (long NO = negative YES exposure)
        # SELL NO: +count (close NO = positive YES exposure)
        
        if side == 'yes':
            if action == 'buy':
                yes_delta = count
                signed_yes_delta = +count
            else:  # sell
                yes_delta = -count
                signed_yes_delta = -count
        else:  # side == 'no'
            if action == 'buy':
                yes_delta = 0
                signed_yes_delta = -count  # BUY NO = long NO = negative YES exposure
            else:  # sell
                yes_delta = 0
                signed_yes_delta = +count  # SELL NO = close NO = positive YES exposure
        
        # Update position state
        prev_signed_yes = position_state['signed_yes_exposure']
        prev_yes = position_state['yes_qty']
        prev_no = position_state['no_qty']
        
        position_state['signed_yes_exposure'] += signed_yes_delta
        
        # Update absolute leg quantities
        if side == 'yes':
            position_state['yes_qty'] += yes_delta
        else:  # side == 'no'
            if action == 'buy':
                position_state['no_qty'] += count
            else:  # sell
                position_state['no_qty'] -= count
        
        position_state['processed_fill_ids'].add(fill_id)
        
        history.append({
            'fill_id': fill_id,
            'order_id': order_id,
            'side': side,
            'action': action,
            'count': count,
            'signed_yes_delta': signed_yes_delta,
            'prev_signed_yes': prev_signed_yes,
            'post_signed_yes': position_state['signed_yes_exposure'],
            'prev_yes': prev_yes,
            'prev_no': prev_no,
            'post_yes': position_state['yes_qty'],
            'post_no': position_state['no_qty'],
            'created_time': created_time
        })
    
    return position_state, history

def classify_fill(fill, position_state, history):
    """Step 4 & 5: Classify fill based on signed YES exposure and intent."""
    fill_id, order_id, client_order_id, ticker, side, action, count, yes_price, no_price, created_time, raw_payload = fill
    
    # Get pre-fill position state
    prev_signed_yes = position_state['signed_yes_exposure']
    
    # Find this fill in the history to get pre-fill state
    fill_history = None
    for h in history:
        if h['fill_id'] == fill_id:
            fill_history = h
            break
    
    if fill_history:
        prev_signed_yes = fill_history['prev_signed_yes']
        prev_yes = fill_history['prev_yes']
        prev_no = fill_history['prev_no']
        signed_yes_delta = fill_history['signed_yes_delta']
    else:
        return 'UNRESOLVED', 'Fill not found in history'
    
    # Determine if this is a valid same-leg exit using signed YES exposure
    # For SELL NO (action=sell, side=no): signed_yes_delta = +count (closes NO position)
    # For SELL YES (action=sell, side=yes): signed_yes_delta = -count (closes YES position)
    
    if action == 'sell':
        if side == 'no':
            # SELL NO: closes NO position (reduces negative YES exposure)
            # Pre-fill state should be negative (long NO)
            if prev_signed_yes < 0:
                # We have a NO position, check if fill closes it
                post_signed_yes = prev_signed_yes + signed_yes_delta
                if post_signed_yes == 0:
                    return 'CONFIRMED_SAME_LEG_EXIT', f"SELL NO closes NO position: {prev_signed_yes} -> {post_signed_yes}"
                elif post_signed_yes < 0:
                    return 'CONFIRMED_SAME_LEG_EXIT', f"SELL NO partially closes NO position: {prev_signed_yes} -> {post_signed_yes}"
                else:
                    return 'REVERSAL', f"SELL NO crosses through zero: {prev_signed_yes} -> {post_signed_yes}"
            elif prev_signed_yes == 0:
                return 'CONFIRMED_INDEPENDENT_ENTRY', f"Pre-fill position zero, SELL NO opens NO position"
            else:
                return 'REJECTED_CROSS_LEG_EXIT', f"Pre-fill YES position {prev_signed_yes}, SELL NO would be cross-leg exit"
        else:  # side == 'yes'
            # SELL YES: closes YES position (reduces positive YES exposure)
            # Pre-fill state should be positive (long YES)
            if prev_signed_yes > 0:
                # We have a YES position, check if fill closes it
                post_signed_yes = prev_signed_yes + signed_yes_delta
                if post_signed_yes == 0:
                    return 'CONFIRMED_SAME_LEG_EXIT', f"SELL YES closes YES position: {prev_signed_yes} -> {post_signed_yes}"
                elif post_signed_yes > 0:
                    return 'CONFIRMED_SAME_LEG_EXIT', f"SELL YES partially closes YES position: {prev_signed_yes} -> {post_signed_yes}"
                else:
                    return 'REVERSAL', f"SELL YES crosses through zero: {prev_signed_yes} -> {post_signed_yes}"
            elif prev_signed_yes == 0:
                return 'CONFIRMED_INDEPENDENT_ENTRY', f"Pre-fill position zero, SELL YES opens YES position"
            else:
                return 'REJECTED_CROSS_LEG_EXIT', f"Pre-fill NO position {prev_signed_yes}, SELL YES would be cross-leg exit"
    else:
        return 'UNRESOLVED', f"Not a SELL action"

def main():
    print("=== READ-ONLY PROVENANCE AUDIT ===\n")
    
    # Step 1: Get candidate SELL fills
    print("Step 1: Identifying candidate SELL fills...")
    candidates = get_candidate_sell_fills()
    print(f"Found {len(candidates)} candidate SELL fills\n")
    
    # Find all confirmed same-leg exits
    confirmed_exits = []
    
    for i, candidate in enumerate(candidates):
        fill_id, order_id, client_order_id, ticker, side, action, count, yes_price, no_price, created_time, raw_payload = candidate
        
        # Skip test markets
        if 'TEST' in ticker or 'test' in ticker:
            continue
        
        # Step 2: Reconstruct ticker history
        ticker_fills = reconstruct_ticker_history(ticker)
        
        # Step 3: Calculate position state
        position_state, history = calculate_position_state(ticker_fills)
        
        # Step 4 & 5: Classify
        classification, reason = classify_fill(candidate, position_state, history)
        
        if classification == 'CONFIRMED_SAME_LEG_EXIT':
            confirmed_exits.append({
                'fill_id': fill_id,
                'order_id': order_id,
                'client_order_id': client_order_id,
                'ticker': ticker,
                'side': side,
                'action': action,
                'count': count,
                'classification': classification,
                'reason': reason,
                'created_time': created_time,
                'raw_payload': raw_payload
            })
    
    print(f"Found {len(confirmed_exits)} confirmed same-leg exits (excluding test markets)\n")
    
    # Show first 5 confirmed exits
    for i, exit in enumerate(confirmed_exits[:5]):
        print(f"=== Confirmed Exit {i+1}: {exit['fill_id']} ===")
        print(f"Ticker: {exit['ticker']}")
        print(f"Normalized: side={exit['side']}, action={exit['action']}, count={exit['count']}")
        print(f"Classification: {exit['classification']}")
        print(f"Reason: {exit['reason']}")
        print(f"Created: {exit['created_time']}")
        
        if exit['raw_payload']:
            raw = json.loads(exit['raw_payload'])
            print(f"Raw API: action={raw.get('action')}, book_side={raw.get('book_side')}, outcome_side={raw.get('outcome_side')}")
        print()
    
    return confirmed_exits

if __name__ == "__main__":
    main()

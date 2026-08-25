"""
Detailed provenance audit for confirmed same-leg exit: 83a4a457-5d2a-4a3d-214f-a4f331a6cbca
"""

import sqlite3
import json

def detailed_audit(fill_id):
    """Conduct detailed provenance audit for a specific fill."""
    conn = sqlite3.connect('kalshi_fills.db')
    cursor = conn.cursor()
    
    # Get the target fill
    cursor.execute("""
        SELECT fill_id, order_id, client_order_id, market_ticker, side, action, count_fp, 
               yes_price_dollars, no_price_dollars, created_time, raw_payload
        FROM kalshi_fills 
        WHERE fill_id = ?
    """, (fill_id,))
    target_fill = cursor.fetchone()
    
    if not target_fill:
        print(f"Fill {fill_id} not found")
        return
    
    print("=== DETAILED PROVENANCE AUDIT ===")
    print(f"Fill ID: {target_fill[0]}")
    print(f"Order ID: {target_fill[1]}")
    print(f"Client Order ID: {target_fill[2]}")
    print(f"Ticker: {target_fill[3]}")
    print(f"Normalized: side={target_fill[4]}, action={target_fill[5]}, count={target_fill[6]}")
    print(f"Prices: YES=${target_fill[7]}, NO=${target_fill[8]}")
    print(f"Created: {target_fill[9]}")
    
    if target_fill[10]:
        raw = json.loads(target_fill[10])
        print(f"Raw API: action={raw.get('action')}, book_side={raw.get('book_side')}, outcome_side={raw.get('outcome_side')}")
    
    # Get complete ticker history
    ticker = target_fill[3]
    cursor.execute("""
        SELECT fill_id, order_id, client_order_id, market_ticker, side, action, count_fp, 
               yes_price_dollars, no_price_dollars, created_time, raw_payload
        FROM kalshi_fills 
        WHERE market_ticker = ?
        ORDER BY created_time ASC
    """, (ticker,))
    all_fills = cursor.fetchall()
    
    print(f"\n=== COMPLETE FILL HISTORY FOR {ticker} ===")
    print(f"Total fills: {len(all_fills)}\n")
    
    # Calculate position state chronologically
    signed_yes_exposure = 0
    yes_qty = 0
    no_qty = 0
    
    for i, fill in enumerate(all_fills):
        f_id, o_id, c_id, t, side, action, count, yes_price, no_price, created_time, raw_payload = fill
        
        # Calculate signed YES delta
        if side == 'yes':
            if action == 'buy':
                signed_yes_delta = +count
                yes_qty += count
            else:  # sell
                signed_yes_delta = -count
                yes_qty -= count
        else:  # side == 'no'
            if action == 'buy':
                signed_yes_delta = -count
                no_qty += count
            else:  # sell
                signed_yes_delta = +count
                no_qty -= count
        
        prev_signed_yes = signed_yes_exposure
        signed_yes_exposure += signed_yes_delta
        
        marker = " <-- TARGET FILL" if f_id == fill_id else ""
        print(f"{i+1}. {f_id}: side={side}, action={action}, count={count}")
        print(f"   Signed YES: {prev_signed_yes} -> {signed_yes_exposure} (delta={signed_yes_delta})")
        print(f"   Leg quantities: YES={yes_qty}, NO={no_qty}")
        print(f"   Created: {created_time}{marker}\n")
    
    # Pre-fill position state for target
    print("=== PRE-FILL POSITION STATE ===")
    print(f"Signed YES exposure: {prev_signed_yes}")
    print(f"YES leg quantity: {yes_qty - (1 if target_fill[4] == 'yes' and target_fill[5] == 'sell' else 0)}")
    print(f"NO leg quantity: {no_qty - (1 if target_fill[4] == 'no' and target_fill[5] == 'sell' else 0)}")
    
    # Classification
    print("\n=== CLASSIFICATION ===")
    if target_fill[4] == 'yes' and target_fill[5] == 'sell':
        if prev_signed_yes > 0:
            print("CONFIRMED_SAME_LEG_EXIT: SELL YES closes YES position")
        else:
            print("INDEPENDENT_ENTRY: SELL YES opens YES position")
    elif target_fill[4] == 'no' and target_fill[5] == 'sell':
        if prev_signed_yes < 0:
            print("CONFIRMED_SAME_LEG_EXIT: SELL NO closes NO position")
        else:
            print("INDEPENDENT_ENTRY: SELL NO opens NO position")
    
    conn.close()

if __name__ == "__main__":
    detailed_audit("83a4a457-5d2a-4a3d-214f-a4f331a6cbca")

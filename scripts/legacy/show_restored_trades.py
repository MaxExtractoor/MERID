#!/usr/bin/env python3
"""Show restored trade history from fills ledger."""
import sqlite3
from pathlib import Path

fills_db = Path("c:/Dev/MERID/data/kalshi_fills.db")
conn = sqlite3.connect(fills_db)
cursor = conn.cursor()

print("RESTORED TRADE HISTORY (May 9, 2026)")
print("=" * 100)

# Get recent fills with side information
cursor.execute("""
    SELECT created_time, market_ticker, side, action, count_fp, yes_price_dollars, no_price_dollars
    FROM kalshi_fills
    ORDER BY created_time DESC
    LIMIT 30
""")
fills = cursor.fetchall()

print(f"\nRecent fills (last 30):")
print("-" * 100)
for fill in fills:
    created_time, ticker, side, action, count, yes_price, no_price = fill
    print(f"{created_time} | {ticker} | {side.upper()} | {action.upper()} | Qty: {count} | YES: ${yes_price} | NO: ${no_price}")

# Get NO trades specifically
cursor.execute("""
    SELECT created_time, market_ticker, action, count_fp, no_price_dollars
    FROM kalshi_fills
    WHERE side = 'no'
    ORDER BY created_time DESC
    LIMIT 10
""")
no_trades = cursor.fetchall()

print(f"\nNO trades (last 10):")
print("-" * 100)
for trade in no_trades:
    created_time, ticker, action, count, no_price = trade
    print(f"{created_time} | {ticker} | {action.upper()} | Qty: {count} | NO Price: ${no_price}")

# Get YES trades specifically
cursor.execute("""
    SELECT created_time, market_ticker, action, count_fp, yes_price_dollars
    FROM kalshi_fills
    WHERE side = 'yes'
    ORDER BY created_time DESC
    LIMIT 10
""")
yes_trades = cursor.fetchall()

print(f"\nYES trades (last 10):")
print("-" * 100)
for trade in yes_trades:
    created_time, ticker, action, count, yes_price = trade
    print(f"{created_time} | {ticker} | {action.upper()} | Qty: {count} | YES Price: ${yes_price}")

# Summary stats
cursor.execute("SELECT COUNT(*) FROM kalshi_fills WHERE side = 'no'")
no_count = cursor.fetchone()[0]
cursor.execute("SELECT COUNT(*) FROM kalshi_fills WHERE side = 'yes'")
yes_count = cursor.fetchone()[0]
cursor.execute("SELECT COUNT(*) FROM kalshi_fills")
total_count = cursor.fetchone()[0]

print(f"\nSUMMARY:")
print("-" * 100)
print(f"Total fills: {total_count}")
print(f"YES trades: {yes_count}")
print(f"NO trades: {no_count}")
print(f"NO trade percentage: {no_count/total_count*100:.1f}%")

conn.close()

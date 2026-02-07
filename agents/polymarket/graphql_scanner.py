import asyncio
import json
import sys
import os

PROJECT_ROOT = r"C:\Dev\MERID"
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
print(f"[Scanner] Project root: {PROJECT_ROOT}")

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds
from py_clob_client.constants import POLYGON
from core.energy import create_energy
from core.orchestrator import MeridCore

# Public client — no credentials needed for market data
client = ClobClient(host="https://clob.polymarket.com", chain_id=POLYGON)

merid = MeridCore()

async def scan_polymarket():
    print("\n[Polymarket CLOB Scanner] Starting scan...")
    try:
        # Get all markets
        markets = client.get_markets()
        
        arb_found = False
        for market in markets["data"]:
            question = market["question"]
            if "BTC" in question.upper() and ("UP" in question.upper() or "DOWN" in question.upper()):
                tokens = market.get("tokens", [])
                if len(tokens) >= 2:
                    yes_token = next((t for t in tokens if t["outcome"] == "YES"), None)
                    no_token = next((t for t in tokens if t["outcome"] == "NO"), None)
                    if yes_token and no_token:
                        yes_price = float(yes_token["price"])
                        no_price = float(no_token["price"])
                        combined = yes_price + no_price
                        
                        if 0.01 < combined < 0.99:
                            profit = 1.0 - combined
                            payload = f"POLYMARKET ARB: '{question}' — YES {yes_price:.4f} + NO {no_price:.4f} = {combined:.4f} → {profit:.2%} risk-free profit"
                            print(f"ARB FOUND: {payload}")
                            
                            energy = create_energy("polymarket_arb", payload)
                            result = await merid.run_cycle(energy)
                            
                            if result["approved"]:
                                from interfaces.telegram import send_alert
                                await send_alert(f"REALITY FORMED: Polymarket Arb Approved\n{payload}\nConsensus: {result['consensus']:.1%}")
                            
                            arb_found = True
        
        if not arb_found:
            print("[Polymarket] No BTC Up/Down arb detected.")
        
        # High-volume signals
        high_vol = sorted(markets["data"], key=lambda m: float(m.get("volume", 0)), reverse=True)[:8]
        for market in high_vol:
            vol = float(market.get("volume", 0))
            if vol > 500000:
                yes_token = next((t for t in market.get("tokens", []) if t["outcome"] == "YES"), None)
                yes_price = float(yes_token["price"]) if yes_token else 0.0
                payload = f"Polymarket high-volume: '{market['question']}' — Volume ${vol:,.0f}, YES {yes_price:.1%}"
                energy = create_energy("polymarket_signal", payload)
                await merid.run_cycle(energy)
                
    except Exception as e:
        print(f"[Polymarket Scanner] Error: {e}")

async def run_polymarket_scanner():
    print("Polymarket CLOB Scanner launched — scanning every 10 minutes")
    while True:
        await scan_polymarket()
        await asyncio.sleep(600)

if __name__ == "__main__":
    asyncio.run(run_polymarket_scanner())

"""Quick check of recent Kalshi fills and balance."""
import os, time, base64, requests
from pathlib import Path
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from dotenv import load_dotenv
load_dotenv()

key = serialization.load_pem_private_key(Path("kalshi_private_key.pem").read_bytes(), None)
kid = os.environ["KALSHI_API_KEY_ID"]
base = "https://api.elections.kalshi.com/trade-api/v2"

def sign(method, path):
    ts = str(int(time.time() * 1000))
    msg = ts + method.upper() + "/trade-api/v2" + path
    sig = key.sign(msg.encode(), padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH), hashes.SHA256())
    return {"KALSHI-ACCESS-KEY": kid, "KALSHI-ACCESS-TIMESTAMP": ts, "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode()}

# Fills
r = requests.get(base + "/portfolio/fills", headers=sign("GET", "/portfolio/fills"), params={"limit": 25}, timeout=15)
fills = r.json().get("fills", [])
print(f"=== RECENT FILLS ({len(fills)}) ===")
for f in fills[:20]:
    t = f.get("created_time", "?")[:19]
    ticker = f.get("ticker", "?")
    side = f.get("side", "?")
    count = f.get("count", 0)
    yp = f.get("yes_price", 0)
    taker = f.get("is_taker", "?")
    print(f"  {t}  {ticker}  {side} {count}x @ {yp}c  taker={taker}")

# Balance
r2 = requests.get(base + "/portfolio/balance", headers=sign("GET", "/portfolio/balance"), timeout=15)
print(f"\nBalance: {r2.json()}")

# Positions
r3 = requests.get(base + "/portfolio/positions", headers=sign("GET", "/portfolio/positions"), timeout=15)
data = r3.json()
positions = data.get("market_positions", data.get("positions", []))
if isinstance(positions, list):
    btc = [p for p in positions if "KXBTC" in p.get("ticker", "").upper()]
else:
    btc = [(k, v) for k, v in positions.items() if "KXBTC" in k.upper()]
print(f"\nBTC Positions ({len(btc)}):")
for p in btc:
    if isinstance(p, dict):
        print(f"  {p.get('ticker')}  pos={p.get('position', p.get('position_fp', 0))}")
    else:
        print(f"  {p[0]}  pos={p[1]}")

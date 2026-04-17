"""Check which web/api modules with unprotected globals are registered in main.py."""
from pathlib import Path

main = Path(r"c:\Dev\MERID\web\main.py").read_text(encoding="utf-8", errors="ignore")

candidates = [
    "simulation", "trading", "prediction_markets", "orchestrator_api",
    "mining", "us_compliant_markets", "predictions", "risk",
    "unified_pipeline", "local_venue_validation", "signal_layer_api",
    "ws_kafka_bridge",
]

print("web/api modules with unprotected globals — registration status:")
for c in candidates:
    mod = f"web.api.{c}"
    status = "REGISTERED" if mod in main else "not registered"
    print(f"  {c}: {status}")

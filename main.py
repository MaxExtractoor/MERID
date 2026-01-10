import asyncio
import json
from fastapi import FastAPI, WebSocket
from core.orchestrator import MeridCore
from core.energy import create_energy

app = FastAPI()
merid = MeridCore()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        # These signals trigger the agent cycle automatically
        test_signals = [
            ("market", "BTC breaking $105,000 with record volume"),
            ("system", "Anomaly detected: ETH/BTC ratio spiking")
        ]
        for source, payload in test_signals:
            energy = create_energy(source, payload)
            decision = await merid.run_cycle(energy)
            
            stream_data = {
                "event": "consensus_reached",
                "source": source,
                "payload": payload,
                "approved": decision["approved"],
                "consensus_score": round(decision["consensus"], 2)
            }
            # This sends the "New X post" style updates to the UI
            await websocket.send_text(json.dumps(stream_data))
            await asyncio.sleep(5)
    except Exception as e:
        print(f"WebSocket error: {e}")
    finally:
        await websocket.close()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

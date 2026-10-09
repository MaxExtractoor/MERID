#!/usr/bin/env python3
"""
Minimal MERID server for testing reconciliation
"""
import asyncio
import logging
import json
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Global state for execution gate
execution_gate_blocked = True  # Initially blocked until reconciliation runs

# Create FastAPI app
app = FastAPI(title="MERID Minimal", version="2.0")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check
@app.get("/health")
async def health():
    return {"status": "ok", "service": "merid-minimal"}

@app.get("/")
async def root():
    return {"service": "MERID", "version": "2.0", "status": "minimal"}

# Mock execution gate endpoint
@app.get("/api/v1/system/execution-gate")
async def execution_gate():
    """Dynamic execution gate that reflects reconciliation status"""
    global execution_gate_blocked
    
    if execution_gate_blocked:
        return {
            "blocked": True,
            "safe_to_trade": False,
            "gate_state": "blocked",
            "reasons": [
                {
                    "source": "reconciliation",
                    "severity": "critical",
                    "message": "Reconciliation has never completed",
                    "details": "Execution gated until first reconciliation run",
                    "hint": "Wait for the next reconciliation cycle or trigger a manual run from System settings."
                }
            ],
            "timestamp": 1772478352.21722
        }
    else:
        return {
            "blocked": False,
            "safe_to_trade": True,
            "gate_state": "clear",
            "reasons": [],
            "timestamp": 1772478352.21722
        }

# Mock reconciliation endpoint
@app.post("/api/v1/system/reconciliation/trigger")
async def trigger_reconciliation():
    """Trigger reconciliation process"""
    logger.info("Reconciliation triggered")
    return {"status": "triggered", "message": "Reconciliation started"}

# WebSocket endpoint for testing
@app.websocket("/ws/live")
async def websocket_live_stream(websocket: WebSocket):
    """Live data stream WebSocket endpoint."""
    try:
        await websocket.accept()
        logger.info("WebSocket connection accepted")
        
        # Send initial connection message
        await websocket.send_json({
            "type": "connected",
            "message": "Live stream connected",
            "channels": "all"
        })
        
        # Keep connection alive with periodic heartbeats
        while True:
            try:
                await asyncio.sleep(10)
                await websocket.send_json({
                    "type": "heartbeat",
                    "timestamp": asyncio.get_event_loop().time()
                })
            except Exception as e:
                logger.debug(f"Heartbeat send failed: {e}")
                break
                
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected normally")
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        try:
            await websocket.close()
        except:
            pass

@app.on_event("startup")
async def startup_event():
    """Run reconciliation on startup"""
    logger.info("Server startup - triggering automatic reconciliation")
    # Simulate reconciliation completion
    await asyncio.sleep(1)  # Simulate work
    logger.info("Reconciliation completed - execution gate is now CLEAR")
    
    # Update the execution gate to show CLEAR status
    global execution_gate_blocked
    execution_gate_blocked = False

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting minimal MERID server on :8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)

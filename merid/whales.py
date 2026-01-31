"""
MERID Whale Detection System

Real-time Solana SPL token whale monitoring with WebSocket broadcasting.
Integrates with PredictionMarketAggregator for unified market intelligence.
"""

import asyncio
import json
import websockets
import os
from typing import Set, Dict, Any
from fastapi import WebSocket
from collections import deque
from datetime import datetime
import logging

# Import Sentry for error tracking
try:
    import sentry_sdk
    from sentry_sdk import start_transaction, start_span
except ImportError:
    sentry_sdk = None
    start_transaction = lambda *args, **kwargs: None
    start_span = lambda *args, **kwargs: None

from contextlib import nullcontext

def get_sentry_transaction():
    """Get a Sentry transaction context manager, falling back to nullcontext if Sentry is disabled."""
    try:
        if start_transaction is None:
            return nullcontext()
        # Test if it's the lambda fallback by calling it
        test_result = start_transaction(op="test", name="test")
        if test_result is None:
            return nullcontext()
        # If it's a real context manager, call it with correct parameters
        return start_transaction(op="whale_detection", name="solana_whale_alert")
    except Exception:
        return nullcontext()

def get_sentry_span(op="parse", description="operation"):
    """Get a Sentry span context manager, falling back to nullcontext if Sentry is disabled."""
    try:
        if start_span is None:
            return nullcontext()
        # Test if it's the lambda fallback by calling it
        test_result = start_span(op="test", description="test")
        if test_result is None:
            return nullcontext()
        # If it's a real context manager, call it with correct parameters
        return start_span(op=op, description=description)
    except Exception:
        return nullcontext()

def capture_sentry_exception(e):
    """Capture exception in Sentry if available, otherwise log it."""
    try:
        if sentry_sdk is not None:
            sentry_sdk.capture_exception(e)
        else:
            logger.exception("Solana whale listener error", exc_info=e)
    except Exception:
        logger.exception("Solana whale listener error (Sentry unavailable)", exc_info=e)

logger = logging.getLogger("merid.whales")

# Configuration
SOLANA_WS = os.getenv("SOLANA_WS_URL", "wss://api.mainnet-beta.solana.com")
SPL_TOKEN_PROGRAM = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
MINT = os.getenv("WHALE_MINT_ADDRESS", "Base58MintPubkeyHere")
WHALE_THRESHOLD = float(os.getenv("WHALE_THRESHOLD", "100000"))  # Token units

# WebSocket clients for whale alerts
ws_clients: Set[WebSocket] = set()

class WhaleEvent:
    """Whale event data structure."""
    
    def __init__(self, mint: str, owner: str, amount: float, timestamp: datetime = None):
        self.mint = mint
        self.owner = owner
        self.amount = amount
        self.timestamp = timestamp or datetime.utcnow()
        self.type = "whale"
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "mint": self.mint,
            "owner": self.owner,
            "amount": self.amount,
            "timestamp": self.timestamp.isoformat(),
            "threshold": WHALE_THRESHOLD
        }

async def solana_whale_listener(aggregator):
    """
    Main Solana WebSocket listener for whale detection.
    
    Args:
        aggregator: PredictionMarketAggregator instance for event storage
    """
    logger.info(f"Starting Solana whale listener for mint: {MINT}")
    logger.info(f"Whale threshold: {WHALE_THRESHOLD} tokens")
    
    while True:
        try:
            with get_sentry_transaction():
                async with websockets.connect(SOLANA_WS) as ws:
                    logger.info("Connected to Solana WebSocket")
                    
                    # Subscribe to SPL token program
                    subscribe_msg = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "programSubscribe",
                        "params": [
                            SPL_TOKEN_PROGRAM,
                            {
                                "encoding": "jsonParsed",
                                "commitment": "processed",
                                "filters": [
                                    {"dataSize": 165},
                                    {"memcmp": {"offset": 0, "bytes": MINT}}
                                ]
                            }
                        ]
                    }
                    
                    await ws.send(json.dumps(subscribe_msg))
                    logger.info("Subscribed to SPL token program")
                    
                    async for raw in ws:
                        with get_sentry_span(op="parse", description="parse_token_update"):
                            try:
                                msg = json.loads(raw)
                                
                                # Extract account data
                                value = msg.get("params", {}).get("result", {}).get("value")
                                if not value:
                                    continue
                                
                                account_data = (
                                    value.get("account", {})
                                         .get("data", {})
                                         .get("parsed", {})
                                         .get("info", {})
                                )
                                
                                amount = account_data.get("tokenAmount", {}).get("uiAmount")
                                owner = account_data.get("owner")
                                
                                if amount is None or owner is None:
                                    continue
                                
                                # Check whale threshold
                                if amount >= WHALE_THRESHOLD:
                                    with get_sentry_span(op="broadcast", description="broadcast_whale"):
                                        whale_event = WhaleEvent(
                                            mint=MINT,
                                            owner=owner,
                                            amount=amount
                                        )
                                        
                                        # Store in aggregator
                                        if hasattr(aggregator, 'record_whale_event'):
                                            aggregator.record_whale_event(whale_event.to_dict())
                                        
                                        # Broadcast to clients
                                        await broadcast_whale(whale_event.to_dict())
                                        
                                        logger.info(
                                            f"Whale detected: {amount} tokens from {owner[:8]}..."
                                        )
                                
                            except Exception as e:
                                logger.error(f"Error parsing whale message: {e}")
                                continue
                                
        except Exception as e:
            logger.error(f"Solana WebSocket error: {e}")
            capture_sentry_exception(e)
            await asyncio.sleep(5)  # Backoff and reconnect

async def broadcast_whale(alert: Dict[str, Any]):
    """
    Broadcast whale alert to all connected WebSocket clients.
    
    Args:
        alert: Whale event data dictionary
    """
    if not ws_clients:
        return
    
    dead = []
    for ws in list(ws_clients):
        try:
            await ws.send_json(alert)
        except Exception as e:
            logger.warning(f"Failed to send whale alert to client: {e}")
            dead.append(ws)
    
    # Remove dead connections
    for ws in dead:
        ws_clients.discard(ws)
    
    logger.info(f"Broadcasted whale alert to {len(ws_clients)} clients")

def add_whale_client(websocket: WebSocket):
    """Add a WebSocket client to receive whale alerts."""
    ws_clients.add(websocket)
    logger.info(f"Added whale client. Total clients: {len(ws_clients)}")

def remove_whale_client(websocket: WebSocket):
    """Remove a WebSocket client from whale alerts."""
    ws_clients.discard(websocket)
    logger.info(f"Removed whale client. Total clients: {len(ws_clients)}")

def get_whale_client_count() -> int:
    """Get current number of connected whale clients."""
    return len(ws_clients)

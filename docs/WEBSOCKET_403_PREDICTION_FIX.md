# WebSocket 403 Fix for /ws/prediction

## 🎯 **Issue Identified**

The 403 error on `/ws/prediction` indicates that the WebSocket endpoint is either:
1. **Missing** - No endpoint registered for `/ws/prediction`
2. **Authenticated** - Endpoint exists but requires authentication that's failing
3. **Rejected** - Endpoint exists but actively rejecting the connection

## ✅ **Root Cause Analysis**

### **Frontend Connection Attempt**
```typescript
// From React components
const WS_URL = "ws://localhost:8000/ws/trades"
const predictionUrl = WS_URL.replace('/ws/trades', '/ws/prediction')
// Results in: "ws://localhost:8000/ws/prediction"
```

### **Current WebSocket Endpoints Found**
- `/ws/live` - Live data stream
- `/ws/market` - Market data only
- `/ws/news` - News only  
- `/ws/agents` - Agent outputs only
- `/ws/prices` - Price stream
- `/ws/stream` - Consensus stream
- **Missing**: `/ws/prediction`

## ✅ **Solution Options**

### **Option 1: Create Missing `/ws/prediction` Endpoint (Recommended)**

Add a new WebSocket endpoint to handle prediction data:

```python
# In web/api/streams.py or create web/api/prediction_ws.py

@router.websocket("/prediction")
async def prediction_stream(websocket: WebSocket):
    """
    Prediction market data stream.
    
    Streams:
    - Prediction market updates
    - Debate context changes
    - Market probability changes
    """
    await websocket.accept()
    logger.info("Prediction stream client connected")
    
    try:
        # Connect to prediction event stream
        from services.prediction_publisher import get_prediction_publisher
        publisher = get_prediction_publisher()
        
        # Subscribe to prediction events
        queue = asyncio.Queue()
        
        async def event_handler(event_type: str, data: Dict[str, Any]) -> None:
            await queue.put({"type": event_type, "data": data})
        
        # Subscribe to prediction events
        unsubscribe = publisher.subscribe(event_handler)
        
        try:
            while True:
                # Send events to client
                event = await queue.get()
                await websocket.send_json(event)
                
        except WebSocketDisconnect:
            logger.info("Prediction stream client disconnected")
        finally:
            unsubscribe()
            
    except Exception as e:
        logger.error(f"Prediction stream error: {e}")
        await websocket.close(code=1011)
```

### **Option 2: Use Existing Endpoint**

Modify the frontend to use an existing endpoint:

```typescript
// Change from:
const predictionUrl = WS_URL.replace('/ws/trades', '/ws/prediction')

// To:
const predictionUrl = '/ws/live'  // or '/ws/market' or '/ws/agents'
```

### **Option 3: Create Generic Domain Handler**

Create a generic WebSocket handler that accepts domains:

```python
# In web/api/streams.py

@router.websocket("/{domain}")
async def domain_stream(websocket: WebSocket, domain: str):
    """
    Generic domain-based WebSocket stream.
    
    Handles: /ws/prediction, /ws/trades, /ws/live, etc.
    """
    await websocket.accept()
    logger.info(f"Domain stream client connected: {domain}")
    
    # Check if domain is allowed
    allowed_domains = {"prediction", "trades", "live", "market", "news", "agents"}
    if domain not in allowed_domains:
        await websocket.close(code=1008, reason="Domain not allowed")
        return
    
    # Route to appropriate handler
    if domain == "prediction":
        await handle_prediction_stream(websocket)
    elif domain == "trades":
        await handle_trades_stream(websocket)
    # ... other domains
```

## ✅ **Authentication Issues (If Endpoint Exists)**

If the endpoint exists but is rejecting with 403, check:

### **1. Authentication Dependencies**
```python
# Check if router has auth dependencies
router = APIRouter(
    prefix="/ws", 
    tags=["websocket"],
    dependencies=[Depends(get_current_session)]  # This causes 403 if auth fails
)
```

### **2. Fix: Remove Auth for WebSocket**
```python
# Remove auth dependencies for WebSocket endpoints
@router.websocket("/prediction")  # No Depends() here
async def prediction_stream(websocket: WebSocket):
    # WebSocket handler
```

### **3. Fix: Add Auth to Frontend**
```typescript
// Add authentication headers to WebSocket connection
const ws = new WebSocket(url, [], {
    headers: {
        'Authorization': `Bearer ${token}`,
        'Cookie': document.cookie
    }
});
```

## 🚀 **Implementation Steps**

### **Step 1: Create the Endpoint**
Add the missing `/ws/prediction` endpoint to handle prediction data.

### **Step 2: Test Connection**
```bash
# Test with websocat or curl
websocat ws://localhost:8000/ws/prediction
```

### **Step 3: Verify Frontend**
Ensure the React frontend can connect and receive prediction data.

## 🎯 **Expected Result**

After implementing the fix:

```
WebSocket connection established
INFO - Prediction stream client connected
{"type": "prediction_update", "data": {...}}
{"type": "debate_context", "data": {...}}
```

## 🎯 **Final Recommendation**

**Option 1 (Create Endpoint)** is recommended because:
- Provides dedicated prediction data stream
- Matches frontend expectations
- Allows for prediction-specific filtering
- Maintains clean separation of concerns

The 403 error is likely due to a missing endpoint rather than authentication, since no `/ws/prediction` endpoint was found in the codebase.

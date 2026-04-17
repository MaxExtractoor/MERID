# WebSocket Client Integration Guide

## 🎯 **Order Group WebSocket Integration**

This guide shows you how to either wire up the WebSocket client or downgrade the log level for the "Order group WS unavailable" informational message.

## ✅ **Option 1: Wire Up WebSocket Client (Preferred)**

### **Find the Order Group Constructor**
Look for where your order group/execution component is constructed, likely in:
- `merid/loop.py` 
- `merid/execution/` directory
- `merid/trading/` directory
- Any file with `OrderGroup`, `ExecutionClient`, or similar

### **Typical Constructor Pattern**
```python
# CURRENT (REST only)
order_group = OrderGroup(
    rest_client=kalshi_rest_client,
    ws_client=None,  # ← This is None, causing the log
)

# OR
order_group = KalshiExecutionBridge(rest_client=rest_client)
```

### **Fix: Add WebSocket Client**
```python
# FIXED (WebSocket enabled)
# 1. Create WebSocket client
ws_client = KalshiVenueClient(ws_enabled=True)  # or however you construct it

# 2. Pass to order group
order_group = OrderGroup(
    rest_client=kalshi_rest_client,
    ws_client=ws_client,  # ← Now provided
)

# OR if using bridge pattern
order_group = KalshiExecutionBridge(
    rest_client=rest_client,
    ws_client=ws_client,  # ← Add this parameter
)
```

### **Common WebSocket Client Patterns**
```python
# Pattern 1: Direct construction
ws_client = KalshiVenueClient(ws_enabled=True)

# Pattern 2: From existing client
kalshi_client = get_kalshi_client()
ws_client = kalshi_client.ws_client

# Pattern 3: From configuration
ws_client = KalshiVenueClient(
    credentials=kalshi_credentials,
    ws_enabled=True,
    ws_url="wss://api.kalshi.com/v1/ws"
)
```

## ✅ **Option 2: Downgrade Log Level**

### **Find the Log Statement**
Search for the log message in your codebase:
```python
logger.info("Order group WS unavailable, will use REST only: WebSocket client not provided")
```

### **Change to Debug Level**
```python
# BEFORE (info level - noisy)
logger.info("Order group WS unavailable, will use REST only: WebSocket client not provided")

# AFTER (debug level - quiet)
logger.debug("Order group WS unavailable, will use REST only: WebSocket client not provided")
```

### **Or Add Conditional Logging**
```python
# WITH CONFIG GUARD
if config.show_websocket_warnings:
    logger.info("Order group WS unavailable, will use REST only: WebSocket client not provided")
else:
    logger.debug("Order group WS unavailable, will use REST only: WebSocket client not provided")
```

## 🚀 **Implementation Steps**

### **Step 1: Locate the Component**
1. Search for files containing "OrderGroup" or "ExecutionBridge"
2. Look for constructor calls with `rest_client` parameter
3. Check if `ws_client` parameter is None or missing

### **Step 2: Choose Your Approach**

#### **For WebSocket Integration (Preferred):**
```python
# In your main setup or loop initialization
def setup_kalshi_execution():
    # Get REST client
    rest_client = get_kalshi_rest_client()
    
    # Create WebSocket client
    ws_client = KalshiVenueClient(ws_enabled=True)
    
    # Create order group with both clients
    order_group = OrderGroup(
        rest_client=rest_client,
        ws_client=ws_client,
    )
    
    return order_group
```

#### **For Log Level Change:**
```python
# Find the class logging this message
class OrderGroup:
    def __init__(self, rest_client, ws_client=None):
        self.rest_client = rest_client
        self.ws_client = ws_client
        
        if ws_client is None:
            # Change this line
            logger.debug("Order group WS unavailable, will use REST only: WebSocket client not provided")
```

### **Step 3: Test the Change**
```python
# Verify WebSocket is working
if order_group.ws_client:
    print("WebSocket client is available")
else:
    print("Using REST only")
```

## 🎯 **Common Constructor Patterns**

### **Pattern A: Separate Clients**
```python
order_group = OrderGroup(
    rest_client=rest_client,
    ws_client=ws_client,
)
```

### **Pattern B: Single Client with WS**
```python
order_group = OrderGroup(
    client=kalshi_client,  # Client has both REST and WS
)
```

### **Pattern C: Bridge Pattern**
```python
bridge = KalshiExecutionBridge(
    rest_client=rest_client,
    ws_client=ws_client,
)
```

### **Pattern D: Configuration Based**
```python
order_group = OrderGroup(
    rest_client=rest_client,
    ws_enabled=True,  # Internal WS creation
)
```

## 🎯 **Benefits of WebSocket Integration**

### **✅ Real-time Updates**
- Instant order status updates
- Live market data feeds
- Faster execution confirmations

### **✅ Reduced Latency**
- No polling delays
- Push-based notifications
- Better for high-frequency trading

### **✅ Better Reliability**
- Connection status monitoring
- Automatic reconnection
- Fallback to REST if needed

## 🎯 **When to Use REST Only**

### **✅ REST Only is Fine When:**
- Low-frequency trading
- Simple order execution
- WebSocket infrastructure not available
- Development/testing environments

### **✅ Change Log Level When:**
- You intentionally want REST-only mode
- WebSocket is not critical for your use case
- You want to reduce log noise
- WebSocket infrastructure is not ready

## 🎯 **Final Recommendation**

**For production trading systems**, use Option 1 (WebSocket integration) for:
- Better performance
- Real-time updates
- Complete functionality

**For development/testing**, Option 2 (log level change) is fine for:
- Simpler setup
- Reduced complexity
- Cleaner logs

The log message is informational and doesn't indicate a problem - it's just telling you that it's falling back to REST mode because no WebSocket client was provided.

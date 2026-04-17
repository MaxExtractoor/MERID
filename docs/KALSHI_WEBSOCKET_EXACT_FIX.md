# Kalshi WebSocket Client Integration - Exact Fix

## 🎯 **Issue Identified**

The log message `"Order group WS unavailable, will use REST only: WebSocket client not provided"` is coming from the `OrderGroupLifecycleManager` trying to start WebSocket tracking without a WebSocket client.

## ✅ **Root Cause Analysis**

### **Current Code Flow**
```python
# In merid/loop.py line 330
self._og_lifecycle = OrderGroupLifecycleManager(get_kalshi_client())

# OrderGroupLifecycleManager constructor (line 86)
self._manager = KalshiOrderGroupManager(self.client)  # ws=None by default

# When starting (line 93)
await self._manager.start_ws()  # This fails because ws=None

# KalshiOrderGroupManager.start_ws() (line 496)
if not self.ws:
    raise RuntimeError("WebSocket client not provided")  # This is the error
```

### **Constructor Signature**
```python
# KalshiOrderGroupManager expects:
def __init__(self, client: KalshiVenueClient, ws: Optional[KalshiWebSocket] = None):
```

## ✅ **Exact Fix Applied**

### **Option 1: Wire Up WebSocket Client (Recommended)**

#### **Step 1: Update `_order_group_lifecycle()` method**
```python
def _order_group_lifecycle(self):
    if not hasattr(self, '_og_lifecycle'):
        from merid.event_venues.kalshi.order_group_lifecycle import OrderGroupLifecycleManager
        from merid.event_venues.kalshi.client import get_kalshi_client
        from merid.event_venues.kalshi.ws import KalshiWebSocket
        
        # Get REST client
        client = get_kalshi_client()
        
        # Create WebSocket client
        ws_client = KalshiWebSocket(client.credentials)
        
        # Create lifecycle manager with both clients
        self._og_lifecycle = OrderGroupLifecycleManager(
            client=client,
            ws_client=ws_client  # Add this parameter
        )
    return self._og_lifecycle
```

#### **Step 2: Update OrderGroupLifecycleManager constructor**
```python
# In merid/event_venues/kalshi/order_group_lifecycle.py

def __init__(
    self,
    client: KalshiVenueClient,
    ws_client: Optional[KalshiWebSocket] = None,  # Add this parameter
    config: Optional[LifecycleConfig] = None,
):
    self.client = client
    self.ws_client = ws_client  # Store the WebSocket client
    self.config = config or LifecycleConfig()
    # ... rest of constructor

# Update manager initialization (line 86)
self._manager = KalshiOrderGroupManager(self.client, ws=self.ws_client)
```

#### **Step 3: Alternative - Pass WebSocket Directly**
If you prefer not to modify OrderGroupLifecycleManager, you can modify the loop to pass the WebSocket client directly:

```python
def _order_group_lifecycle(self):
    if not hasattr(self, '_og_lifecycle'):
        from merid.event_venues.kalshi.order_group_lifecycle import OrderGroupLifecycleManager
        from merid.event_venues.kalshi.client import get_kalshi_client
        from merid.event_venues.kalshi.ws import KalshiWebSocket
        from merid.event_venues.kalshi.order_group_manager import KalshiOrderGroupManager
        
        # Get REST client
        client = get_kalshi_client()
        
        # Create WebSocket client
        ws_client = KalshiWebSocket(client.credentials)
        
        # Create lifecycle manager
        self._og_lifecycle = OrderGroupLifecycleManager(client)
        
        # Manually inject WebSocket client into the manager
        self._og_lifecycle._manager = KalshiOrderGroupManager(client, ws=ws_client)
        
    return self._og_lifecycle
```

### **Option 2: Downgrade Log Level (Quick Fix)**

If you want to keep REST-only mode but reduce log noise:

```python
# In merid/loop.py line 1355
logger.debug(f"Order group WS unavailable, will use REST only: {start_exc}")
```

## 🚀 **Implementation Steps**

### **For Full WebSocket Integration (Recommended)**

1. **Add WebSocket client import** to loop.py
2. **Create WebSocket client** in `_order_group_lifecycle()`
3. **Pass WebSocket client** to OrderGroupLifecycleManager
4. **Update OrderGroupLifecycleManager** to accept and use WebSocket client
5. **Test real-time updates** by placing orders and monitoring logs

### **For Quick Log Noise Reduction**

1. **Change log level** from `info` to `debug` in loop.py
2. **System continues** to work in REST-only mode
3. **No functional changes** to trading behavior

## 🎯 **Expected Results**

### **With WebSocket Integration**
```
INFO - OrderGroupLifecycleManager started
INFO - Started order group WebSocket tracking
INFO - Order group update received: group_id=xxx status=filled
```

### **With Log Level Change**
```
DEBUG - Order group WS unavailable, will use REST only: WebSocket client not provided
```

## 🎯 **Benefits of WebSocket Integration**

✅ **Real-time order updates** - Instant status changes  
✅ **Auto-cancel triggers** - Immediate response to market moves  
✅ **Reduced latency** - No polling delays  
✅ **Better risk management** - Real-time limit tracking  
✅ **Complete order lifecycle** - From creation to completion  

## 🎯 **Final Recommendation**

**For Production Trading**: Use Option 1 (WebSocket integration) for real-time updates and better risk management.

**For Development/Testing**: Use Option 2 (log level change) for quieter logs while maintaining functionality.

The exact fix depends on whether you want real-time order updates or prefer the simpler REST-only approach.

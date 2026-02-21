# UI Wiring Complete - Kill Switch View

**Status**: ✅ KillSwitchView wired to real operator APIs  
**Date**: 2026-02-18

---

## ✅ Kill Switch View - COMPLETE

**File**: `web/react/src/views/KillSwitchView.tsx`

### Changes Made:

1. **Replaced stub API** (`/api/v1/system/execution-gate`) with real operator endpoints:
   - `GET /api/v1/operator/kill-switch-status` (poll every 2s)
   - `GET /api/v1/operator/risk-state` (poll every 5s)

2. **Added Emergency Stop button**:
   - Calls `POST /api/v1/operator/emergency-stop` with reason
   - Requires confirmation before executing
   - Refetches state after triggering

3. **Added Reset Kill Switch button**:
   - Calls `POST /api/v1/operator/reset-kill-switch`
   - Only visible when kill switch is active
   - Re-enables trading after confirmation

4. **Real-time risk metrics display**:
   - Daily P&L with limit tracking
   - Position size utilization
   - Error count with threshold warning
   - All values update every 2-5 seconds

5. **Dynamic gate state**:
   - `clear` - All checks passing
   - `limited` - Warnings active (near error threshold)
   - `blocked` - Kill switch triggered

### Result:

**Before**: Static "Connected" status, no real control  
**After**: Live kill switch state, functional emergency stop/reset, real risk metrics

---

## 🧪 Test Kill Switch View

```bash
# 1. Start backend
cd c:/Dev/MERID
python -m uvicorn web.main:app --reload --port 8000

# 2. Start frontend
cd web/react
npm run dev

# 3. Navigate to Kill Switch view
# http://localhost:5173 → Click "Kill Switch" in sidebar

# 4. Verify displays:
# - Current gate state (clear/limited/blocked)
# - Daily P&L (should be $0.00 initially)
# - Position size
# - Error count

# 5. Test Emergency Stop:
# - Click "Emergency Stop" button
# - Confirm prompt
# - Should see: 
#   - Gate state → "Execution Blocked"
#   - Red alert with reason
#   - "Reset Kill Switch" button appears

# 6. Test Reset:
# - Click "Reset Kill Switch"
# - Confirm prompt
# - Should see:
#   - Gate state → "Execution Enabled"
#   - Green success message
#   - "Emergency Stop" button returns
```

---

## 🎯 Next: Wire Operator Dashboard

The dashboard still needs real data for:
- Balance (currently $0.00)
- Positions count (currently 0)
- Agent activity (currently "0 tasks")
- Orders count

**Approach**: Add useApiData calls to replace stub data in OperatorDashboard.tsx

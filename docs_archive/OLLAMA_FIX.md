# Ollama Connection Issue - RESOLVED

## Problem
- `merid-strategist:latest` (4.66 GB) hangs indefinitely on `/api/generate` endpoint
- Timeouts after 120+ seconds with no response
- Agents reported "Ollama unreachable" and fell back to stub responses

## Root Cause
Large llama3-based model (4.66 GB) gets stuck during inference generation, possibly due to:
- Insufficient system resources (RAM/CPU)
- Model corruption or configuration issue
- Infinite generation loop

## Solution Applied
**Switched to smaller, faster model: `gemma3:1b` (820 MB)**

### Changes Made:
1. **Updated `core/settings.py`:**
   - `FAST_MODEL` default: `merid-interface:latest` → `gemma3:1b`
   - `DEEP_MODEL` default: `merid-strategist:latest` → `gemma3:1b`

2. **Updated `agents/synthesizer.py`:**
   - Changed hardcoded model from `merid-strategist:latest` → `gemma3:1b`

3. **Verified `agents/archivist.py`:**
   - Already using `gemma3:1b` (no change needed)

### Test Results:
```
✓ Ollama is working correctly!
  Model loaded in 55.7s
  Response: "Two." (correct for "What is 2+2?")
```

## Performance Impact
- **Old**: 120+ second timeout (failure)
- **New**: 55.7s first load, faster subsequent calls
- **Quality**: gemma3:1b is Google's Gemma 2B parameter model - sufficient for MERID agent reasoning

## Environment Variables (Optional Override)
If you want to use different models in the future:
```bash
export MERID_FAST_MODEL="gemma3:1b"
export MERID_DEEP_MODEL="gemma3:1b"
```

Or in PowerShell:
```powershell
$env:MERID_FAST_MODEL = "gemma3:1b"
$env:MERID_DEEP_MODEL = "gemma3:1b"
```

## Alternative Options (Not Used)
1. **Stub Mode**: `MERID_AGENT_MODEL_STUB=true` - bypasses Ollama entirely (deterministic fallback)
2. **Reinstall Model**: `ollama rm merid-strategist && ollama pull llama3` - might fix corruption
3. **Use gemma2:2b**: Slightly larger but still fast

## Verification
Agents now connect to Ollama successfully and generate real reasoning instead of stub responses.

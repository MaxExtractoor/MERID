# Circular Import & Race Condition Detector

## Overview

This script performs deep static analysis to detect circular imports and race conditions across the entire MERID production stack. It uses AST-based analysis inspired by industry-standard tools like `knot-imports`, `threadcheck`, and `thread-safe-check`.

## Features

### Circular Import Detection
- **AST-based analysis**: Parses Python source code without executing it
- **Tarjan's SCC algorithm**: Efficiently detects strongly connected components (cycles)
- **Severity classification**: CRITICAL (direct cycles), HIGH (2-4 nodes), MEDIUM (complex cycles)
- **Fix suggestions**: Provides actionable recommendations for each cycle
- **Internal-only analysis**: Only analyzes project imports, ignores external dependencies

### Race Condition Detection
- **High-confidence detection**: Only flags actual concurrency usage (Thread() creation, async functions)
- **13 detection rules**: Based on thread-safe-check's Python concurrency rules
- **Context-aware**: Understands async vs threading contexts
- **Code snippets**: Shows the problematic code with line numbers
- **Fix suggestions**: Provides specific remediation guidance

## Detection Rules

### Race Condition Rules

| Rule ID | Name | Severity | Description |
|---------|------|----------|-------------|
| TS010 | Unprotected Access | HIGH | Unprotected shared variable access in threaded context |
| TS011 | Check-Then-Act | HIGH | TOCTOU: Check-then-act race condition |
| TS030 | Blocking in Async | MEDIUM | Blocking operation in async function |
| TS032 | Threading Lock in Async | HIGH | Using threading.Lock in async context (use asyncio.Lock) |

## Usage

### Basic Scan
```bash
py scripts/circular_import_race_condition_detector.py --scan-path c:/Dev/MERID
```

### Exclude Directories
```bash
py scripts/circular_import_race_condition_detector.py --scan-path c:/Dev/MERID --exclude archive,legacy,probe_snapshots,snapshots,output
```

### Output JSON Report
```bash
py scripts/circular_import_race_condition_detector.py --scan-path c:/Dev/MERID --output-json report.json
```

### Only Circular Imports
```bash
py scripts/circular_import_race_condition_detector.py --scan-path c:/Dev/MERID --only-circular-imports
```

### Only Race Conditions
```bash
py scripts/circular_import_race_condition_detector.py --scan-path c:/Dev/MERID --only-race-conditions
```

## Results Interpretation

### Circular Imports
- **CRITICAL**: Direct circular import between 2 modules (A → B → A)
  - Fix: Extract shared code into a new module or use lazy imports
- **HIGH**: Circular import involving 2-4 modules
  - Fix: Refactor to break the cycle by moving shared dependencies
- **MEDIUM**: Complex circular import involving 5+ modules
  - Fix: Consider architectural refactoring to reduce coupling

### Race Conditions
- **TS030 (Blocking in Async)**: Using blocking I/O (requests.get, time.sleep) in async functions
  - Fix: Use async equivalents (aiohttp, asyncio.sleep) or run in executor with asyncio.to_thread()
- **TS032 (Threading Lock in Async)**: Using threading.Lock in async context
  - Fix: Use asyncio.Lock instead of threading.Lock in async functions
- **TS011 (Check-Then-Act)**: Pattern where a shared variable is checked then modified without atomicity
  - Fix: Use atomic operations or lock the entire check-then-act sequence

## Integration with CI/CD

### GitHub Actions Example
```yaml
name: Concurrency Check

on: [push, pull_request]

jobs:
  check-circular-imports:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Check for circular imports and race conditions
        run: python scripts/circular_import_race_condition_detector.py --scan-path . --exclude archive,legacy,probe_snapshots,snapshots,output
```

## Exit Codes

- **0**: No issues found
- **1**: Issues found (circular imports or race conditions)
- **2**: Error (e.g., path not found)

## Performance

- **Scan time**: ~2-3 minutes for 7,632 files
- **Memory usage**: ~100-200MB
- **False positive rate**: Low (high-confidence detection only)

## Best Practices

1. **Run regularly**: Integrate into CI/CD pipeline to catch issues early
2. **Fix CRITICAL/HIGH first**: Prioritize circular imports and high-severity race conditions
3. **Review false positives**: Some race condition warnings may be acceptable if the code path is never actually concurrent
4. **Document exceptions**: If a warning is a false positive, add a comment explaining why it's safe

## Limitations

- **Static analysis only**: Cannot detect runtime-only issues (dynamic imports, reflection)
- **Heuristic-based**: Some rules use heuristics that may produce false positives
- **No lock scope tracking**: Does not track lock acquisition/release scope perfectly
- **No thread-local storage detection**: Does not distinguish between thread-local and truly shared state

## Research & Inspiration

This script is based on research into the following tools:

- **knot-imports**: AST-based circular import detection with Tarjan's algorithm
- **threadcheck**: Static and runtime race condition detection for free-threading Python
- **thread-safe-check**: 17 Python concurrency rules with multi-language support
- **depgraph**: Interactive dependency graph with blast-radius analysis
- **circular-import-detector**: Pre-commit integration for circular import detection

## Example Output

```
🔍 Starting analysis of: c:\Dev\MERID
🚫 Excluding directories: ['archive', 'legacy', 'probe_snapshots', 'snapshots', 'output']

📦 Detecting circular imports...
   Analyzed 7632 files (7632 modules)
   Found 0 circular import cycles

⚡ Detecting race conditions...
   Analyzed 7632 files
   Found 62 potential race conditions

================================================================================
📊 ANALYSIS SUMMARY
================================================================================
Scan path: c:\Dev\MERID
Files analyzed: 7632
Modules analyzed: 7632
Scan duration: 146.16s

✅ No circular imports detected

⚡ RACE CONDITIONS (62 found)
--------------------------------------------------------------------------------

[TS030] Blocking in Async (59 occurrences)
    Blocking operation in async function

    📍 c:\Dev\MERID\check_kalshi_market_types.py:21
       Blocking operation in async function
       Code: response = requests.get('https://external-api.kalshi.com/trade-api/v2/markets', timeout=10)
       💡 Fix: Use async equivalent or run in executor with asyncio.to_thread()
```

## Maintenance

To add new detection rules:

1. Add rule definition to `RaceConditionDetector.RULES`
2. Implement detection logic in `analyze_file()`
3. Add helper methods if needed (e.g., `_is_blocking_call()`)
4. Test on known-good and known-bad code samples
5. Update this README with the new rule

## License

This script is part of the MERID trading system and follows the same license.

# MERID Test Coverage Baseline Report

Generated: 2025-02-02

## Current Coverage Summary

| Module | Statements | Missing | Coverage % | Key Problems |
|--------|------------|---------|------------|--------------|
| merid/__init__.py | 2 | 0 | 100.00% | - |
| merid/settings.py | 111 | 35 | 68.47% | Lines 146-150, 155, 160, 169-172, 177, 182, 191-215, 219-234 |
| merid/whales.py | 252 | 178 | 29.37% | Lines 29, 42-50, 55-63, 68-74, 88, 126-135, 140, 145, 150, 154-155, 159-160, 164, 168-183, 187-207, 211-236, 240-252, 256-288, 292-324, 328-350, 354-372, 376-385, 389-397, 407-409, 423-431, 436-437, 443-446, 451-453, 458-459 |
| merid/event_venues/base.py | 185 | 185 | 0.00% | All lines |
| merid/event_venues/kalshi/client.py | 242 | 242 | 0.00% | All lines |
| merid/event_venues/kalshi/models.py | 121 | 121 | 0.00% | All lines |
| merid/event_venues/kalshi/trading.py | 58 | 58 | 0.00% | All lines |
| merid/event_venues/kalshi/ws.py | 110 | 110 | 0.00% | All lines |
| merid/event_venues/polymarket/client.py | 194 | 163 | 15.98% | Lines 44-46, 50, 54-72, 76-77, 85-123, 127-139, 143-154, 162-179, 183-191, 195-206, 210-218, 226-259, 263-278, 284, 292-331, 335-337, 367-372, 383-385, 400-412, 416-429 |
| merid/event_venues/polymarket/models.py | 88 | 9 | 89.77% | Lines 110-118 |
| merid/execution/base.py | 37 | 0 | 100.00% | - |
| merid/execution/executors/alpaca.py | 38 | 24 | 36.84% | Lines 20-22, 26, 33-41, 62-92, 104-119 |
| merid/execution/executors/coinbase.py | 67 | 47 | 29.85% | Lines 24-27, 31, 35-42, 51-63, 84-121, 133-156, 160-163 |
| merid/execution/executors/cronos_onchain.py | 35 | 19 | 45.71% | Lines 20-21, 25, 29-31, 52-57, 70-83, 87-92, 96-97 |
| merid/execution/executors/crypto_com.py | 49 | 33 | 32.65% | Lines 20-22, 26, 33-42, 63-94, 106-124, 128, 132-136 |
| merid/execution/executors/fulcrom.py | 39 | 25 | 35.90% | Lines 20-22, 26, 30-43, 64-94, 106-123 |
| merid/execution/executors/jupiter.py | 41 | 26 | 36.59% | Lines 20-23, 27, 31-48, 73-120, 133, 137-142 |
| merid/execution/executors/kalshi.py | 46 | 29 | 36.96% | Lines 21-23, 27, 33-41, 62-92, 104-122, 126-130, 134-138 |
| merid/execution/executors/webull.py | 46 | 31 | 32.61% | Lines 20-24, 28-31, 35, 39-47, 68-99, 111-130 |
| merid/execution/http_base.py | 119 | 64 | 46.22% | Lines 46-48, 122-130, 134-139, 143, 155-156, 187-305, 313-321, 328-330, 334, 338 |
| merid/execution/portfolio.py | 58 | 27 | 53.45% | Lines 32-35, 40, 45, 49, 53, 57, 61, 65, 69, 73-96, 105 |
| merid/execution/router.py | 149 | 97 | 34.90% | Lines 71-79, 85, 88, 102-113, 116-178, 184-185, 197-212, 215-220, 224-262, 265, 278, 292-295, 299-311, 315-322, 332-334 |
| **TOTAL** | **2282** | **1299** | **43.08%** | Target: 85% |

## Test Collection Errors

1. **tests/event_venues/test_polymarket_client_comprehensive.py**
   - ImportError: cannot import name 'PolymarketMarket' from 'merid.event_venues.polymarket.models'

2. **tests/execution/test_executors_comprehensive.py**
   - ImportError: Various executor imports don't match real module structure

3. **tests/integration/test_contracts.py**
   - ImportError: cannot import name 'Consumer' from 'pact'

## Pytest Warnings

1. **Unknown Mark Warnings** (in tests/e2e/test_circuit_breaker_chaos.py):
   - @pytest.mark.e2e
   - @pytest.mark.safety_critical
   - @pytest.mark.stress_core
   - Note: These ARE defined in pytest.ini but still showing warnings - possible duplicate marker issue

2. **DeprecationWarning**: tweepy uses deprecated 'imghdr' module

3. **DeprecationWarning**: neo4j driver destructor deprecation

## Action Plan

### Phase 1: Fix Config & Markers (Priority: Critical)
- [ ] Fix pytest.ini duplicate markers
- [ ] Add pytest-checklist configuration
- [ ] Verify coverage configuration

### Phase 2: Fix Broken Tests (Priority: High)
- [ ] Remove or fix broken contract tests
- [ ] Remove tests with bad imports
- [ ] Create tests matching real module structure

### Phase 3: Targeted Coverage (Priority: High)
- [ ] settings.py: 68% → 85%
- [ ] whales.py: 29% → 85%
- [ ] event_venues: 0% → 70%
- [ ] execution: 30-45% → 70%

### Phase 4: Add Checklist Pointers (Priority: Medium)
- [ ] Add @pytest.mark.pointer to critical functions
- [ ] Verify pytest-checklist integration

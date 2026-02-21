# Local Venue & UI Validation Playbook

## Overview

This document defines the comprehensive testing and validation approach for the new local venue + microstructure UI integration in MERID. It serves as a standard operating procedure (SOP) for both manual testing and automated swarm agent validation.

## 1. Test Surfaces and Success Criteria

### 1.1 Surfaces to Cover

#### Feed Handlers (Multicast/FIX/WS → Normalized Schema)
- **MulticastFeedHandler**: UDP multicast (ITCH, SOUPBIN, OPRA) processing
- **FixFeedHandler**: FIX protocol (MarketDataSnapshotFullRefresh, MarketDataIncrementalRefresh)
- **WsFeedHandler**: WebSocket for crypto exchanges (Binance, Kraken, Coinbase)
- **Normalization**: All feeds must decode to `data.market_data_schemas` compliant objects
- **Sequence Tracking**: Strict sequence number validation and gap detection
- **Quality Flags**: Proper setting of quality flags for malformed messages

#### Local Matching Engine / LocalVenue Adapter
- **LocalVenueAdapter**: Broker-like API forwarding to internal matching engine
- **ExecutionSimulator**: Core matching engine with order book management
- **PersistentOrderBook**: Durable order book with journaling and snapshots
- **BookBuilder**: Order book maintenance from normalized feed events
- **Risk Integration**: Risk checks and position tracking
- **Mode Parity**: Sim/paper/live mode compatibility

#### New UI Panels
- **Local Venue Section**: Order book table, engine status, recent trades, controls
- **Telemetry Badges**: Connection status (ONLINE/CONNECTING/OFFLINE)
- **Health Views**: Feed handler health, engine metrics, system dependencies
- **Controls Panel**: Start/Stop engine, Flush orders, Reset book
- **Real-time Updates**: WebSocket + REST fallback patterns

### 1.2 Core Acceptance Criteria

#### Schema Compliance
- **No Regressions**: Existing `data.market_data_schemas` consumers must continue working
- **Valid Objects**: All decoded objects must pass Pydantic validation
- **Complete Fields**: Required fields populated, optional fields handled gracefully
- **Type Safety**: Correct data types (Decimal, datetime, enums) throughout

#### Matching Engine Functionality
- **Order Lifecycle**: Submit → Accept → Partial Fill → Fill/Cancel workflow
- **FIFO Behavior**: Correct price-time priority matching
- **Book State**: Accurate bid/ask levels, spread calculation
- **Trade Events**: Proper trade emission with correct timestamps
- **P&L Tracking**: Accurate position and P&L calculations
- **Risk Updates**: Real-time risk metric updates

#### UI Robustness
- **Status Indicators**: Telemetry badges reflect actual connection state
- **Data Display**: Order book depth, recent trades, engine metrics populate correctly
- **Graceful Degradation**: Empty states and fallbacks on feed/WS failures
- **Control Responsiveness**: Engine controls work and provide feedback
- **Performance**: Sub-second updates for real-time data

## 2. Backend Unit and Integration Tests

### 2.1 Feed Handler Tests

#### Unit Tests per Handler
```python
@pytest.mark.localvenue
@pytest.mark.feed_handlers
class TestMulticastFeedHandler:
    def test_decode_itch_message(self):
        """Test ITCH message decoding and schema compliance"""
        
    def test_sequence_number_validation(self):
        """Test strict sequence number tracking"""
        
    def test_malformed_message_handling(self):
        """Test quality flag setting for malformed messages"""
```

#### Integration Tests
```python
@pytest.mark.localvenue
@pytest.mark.feed_integration
class TestFeedHandlerIntegration:
    def test_message_sequence_reconstruction(self):
        """Test order book reconstruction from message sequence"""
        
    def test_gap_detection_and_recovery(self):
        """Test sequence gap detection and recovery mechanisms"""
```

### 2.2 Matching Engine Tests

#### Core Functionality
```python
@pytest.mark.localvenue
@pytest.mark.matching_engine
class TestLocalVenueAdapter:
    def test_order_submission_and_execution(self):
        """Test complete order lifecycle"""
        
    def test_partial_fills_and_cancels(self):
        """Test partial fills and order cancellation"""
        
    def test_risk_checks_and_rejections(self):
        """Test risk validation and order rejection"""
```

#### Cross-Mode Tests
```python
@pytest.mark.localvenue
@pytest.mark.cross_mode
class TestVenueParity:
    def test_sim_vs_paper_parity(self):
        """Test identical fills between LOCAL_SIM and paper venues"""
        
    def test_live_mode_isolation(self):
        """Test live mode isolation and safety"""
```

### 2.3 Test Organization

#### Markers
- `@pytest.mark.localvenue`: All local venue related tests
- `@pytest.mark.feed_handlers`: Feed handler specific tests
- `@pytest.mark.matching_engine`: Matching engine tests
- `@pytest.mark.ui_integration`: UI integration tests
- `@pytest.mark.e2e`: End-to-end scenario tests

#### File Structure
```
tests/
├── local_venue/
│   ├── test_feed_handlers.py
│   ├── test_matching_engine.py
│   ├── test_venue_adapter.py
│   ├── test_book_builder.py
│   └── test_integration.py
└── ui/
    └── test_local_venue_ui.py
```

## 3. UI Tests: Manual Script and Automated Checks

### 3.1 Manual Operator Script (Phase 0)

#### Prerequisites
1. Backend running with local venue enabled
2. MERID UI accessible at `http://127.0.0.1:8001`
3. Test data available for order submission

#### Step-by-Step Validation

**Step 1: Basic UI Functionality**
1. Navigate to Local Venue section
2. Verify telemetry badge shows CONNECTING → ONLINE
3. Confirm order book table populates for default symbol
4. Check spread and imbalance calculations look reasonable
5. Verify recent trades list updates

**Step 2: Real-time Updates**
1. Submit test orders via API or CLI
2. Confirm trades appear in recent trades list
3. Verify order book depth updates in real-time
4. Check engine status metrics update correctly

**Step 3: Failure Scenarios**
1. Kill WebSocket process or stop feed handler
2. Verify telemetry badge flips to OFFLINE/degraded
3. Confirm panel shows loading/empty state instead of freezing
4. Verify REST fallback kicks in (if implemented)

**Step 4: Control Functions**
1. Use Start/Stop engine controls
2. Verify UI audit feed updates with control actions
3. Test Flush orders and Reset book functions
4. Confirm backend state matches UI feedback

#### Expected Results Checklist
- [ ] Telemetry badge transitions correctly
- [ ] Order book displays with proper depth
- [ ] Trades list updates in real-time
- [ ] Controls provide immediate feedback
- [ ] Failure scenarios handled gracefully

### 3.2 Automated Front-End Checks

#### API-Level Tests
```python
@pytest.mark.localvenue
@pytest.mark.ui_api
class TestLocalVenueAPI:
    def test_engine_status_endpoint(self):
        """Test engine status API response structure"""
        
    def test_orderbook_endpoint(self):
        """Test order book API response structure"""
        
    def test_trades_endpoint(self):
        """Test trades API response structure"""
        
    def test_health_endpoint(self):
        """Test health check API response"""
```

#### UI Smoke Tests (Playwright/Cypress)
```javascript
// Playwright example
test('Local Venue Panel Smoke Test', async ({ page }) => {
  await page.goto('http://127.0.0.1:8001');
  await page.click('[data-section="local-venue"]');
  
  // Wait for telemetry badge to become ONLINE
  await page.waitForSelector('.telemetry-online');
  
  // Verify order book has data
  const orderBookRows = await page.locator('.order-book-row').count();
  expect(orderBookRows).toBeGreaterThan(0);
  
  // Test failure scenario
  await page.route('**/ws/localvenue', route => route.abort());
  await page.waitForSelector('.telemetry-offline');
});
```

## 4. End-to-End Scenario Validation

### 4.1 Scenario 1: Basic Local Trade Loop

#### Test Flow
1. **Feed Setup**: Replay captured feed segment into feed handler
2. **Strategy Execution**: Run simple strategy using only `LOCAL_SIM` venue
3. **Validation**: Check fills, risk metrics, and portfolio updates

#### Expected Outcomes
- Orders get filled by internal engine
- Risk metrics update in real-time
- Portfolio summary reflects positions
- UI panels show coherent numbers
- Analytics/execution/portfolio panels match backend values

#### Test Implementation
```python
@pytest.mark.localvenue
@pytest.mark.e2e
class TestBasicLocalTradeLoop:
    def test_feed_to_engine_to_portfolio(self):
        """Test complete trade loop from feed to portfolio"""
        
    def test_ui_coherence_with_backend(self):
        """Test UI panels match backend state"""
```

### 4.2 Scenario 2: Failure and Safe-Mode

#### Test Flow
1. **Normal Operation**: Establish stable feed and trading
2. **Failure Injection**: Stop feed handler or introduce corrupted messages
3. **Safe-Mode Verification**: Check Anti-Silent-Failure response

#### Expected Outcomes
- Feed marked as unhealthy in monitoring
- Risk metrics adjust or trading reduced
- Health panel shows dependency issues
- Local Venue telemetry badge degrades
- Risk panels show breach events

#### Test Implementation
```python
@pytest.mark.localvenue
@pytest.mark.failure_scenarios
class TestFailureAndSafeMode:
    def test_feed_failure_handling(self):
        """Test feed failure detection and response"""
        
    def test_safe_mode_activation(self):
        """Test safe-mode activation and UI response"""
```

## 5. Integration with Dev Swarm for Ongoing Robustness

### 5.1 New Swarm Tasks/Roles

#### Local Venue Guardian Agent
- **Purpose**: Monitor coverage and test results for local venue components
- **Responsibilities**:
  - Track test coverage for feed handlers, LocalVenue adapter, UI
  - File tickets when coverage or SLOs slip
  - Monitor regression test results
  - Propose improvements to test suites

#### UI Telemetry Sentinel Agent
- **Purpose**: Monitor UI health and performance metrics
- **Responsibilities**:
  - Scan logs for WebSocket errors and reconnect counts
  - Monitor panel load times and fallback rates
  - Identify slow or failing UI components
  - Propose UX or infrastructure fixes

### 5.2 Swarm Workflows

#### PR Validation Workflow
```yaml
name: Local Venue PR Validation
on:
  pull_request:
    paths:
      - 'data/feed_handlers.py'
      - 'venues/local_sim_adapter.py'
      - 'execution/**'
      - 'web/api/local_venue.py'
      - 'web/static/js/**'
jobs:
  test-local-venue:
    runs-on: ubuntu-latest
    steps:
      - name: Run pytest localvenue subset
        run: pytest -m localvenue
      - name: Run API tests
        run: pytest tests/api/test_local_venue.py
      - name: Run UI smoke test
        run: pytest tests/ui/test_local_venue_ui.py --headless
```

#### Nightly E2E Job
```yaml
name: Local Venue Nightly E2E
schedule:
  - cron: '0 2 * * *'
jobs:
  e2e-local-venue:
    runs-on: ubuntu-latest
    steps:
      - name: Full E2E replay
        run: pytest tests/e2e/test_local_venue_e2e.py
      - name: Failure injection tests
        run: pytest tests/e2e/test_failure_scenarios.py
      - name: Safe-mode validation
        run: pytest tests/e2e/test_safe_mode.py
```

### 5.3 Swarm-Driven Continuous Improvement

#### Metrics Integration
- **Feed Liveness**: Monitor feed handler uptime and message rates
- **WebSocket Health**: Track reconnection counts and error rates
- **Missing Data**: Detect gaps in data streams
- **UI Performance**: Monitor panel load times and responsiveness

#### Guardrail Evolution
- **Dynamic Test Generation**: Create tests based on observed patterns
- **Risk Thresholds**: Adjust risk limits based on historical data
- **Performance Targets**: Optimize based on telemetry data
- **Failure Prediction**: Predict and prevent common failure modes

## 6. Documentation and Knowledge Management

### 6.1 Test Documentation
- **Test Plans**: Detailed test plans for each component
- **Test Data**: Sample data sets for reproducible testing
- **Known Issues**: Documented edge cases and workarounds
- **Performance Baselines**: Expected performance metrics

### 6.2 Knowledge Transfer
- **Runbooks**: Step-by-step procedures for common scenarios
- **Troubleshooting Guides**: Common issues and solutions
- **Architecture Decisions**: Rationale behind design choices
- **Best Practices**: Coding and testing guidelines

## 7. Success Metrics and KPIs

### 7.1 Test Coverage Targets
- **Feed Handlers**: 95% line coverage
- **Matching Engine**: 90% line coverage
- **UI Components**: 80% coverage for critical paths
- **Integration Points**: 85% coverage for API contracts

### 7.2 Performance Targets
- **Feed Processing**: < 1ms per message
- **Order Book Updates**: < 100ms latency
- **UI Response**: < 500ms for panel updates
- **WebSocket Reconnect**: < 5s recovery time

### 7.3 Reliability Targets
- **Feed Uptime**: 99.9% availability
- **WebSocket Success**: 99.5% connection success rate
- **UI Availability**: 99.8% panel render success
- **Error Recovery**: < 30s failure detection time

## 8. Implementation Timeline

### Phase 0: Immediate (Week 1)
- [ ] Create test documentation structure
- [ ] Implement basic unit tests for feed handlers
- [ ] Set up UI smoke tests
- [ ] Create manual validation script

### Phase 1: Foundation (Weeks 2-3)
- [ ] Complete unit test coverage
- [ ] Implement integration tests
- [ ] Add automated API tests
- [ ] Set up CI/CD workflows

### Phase 2: Robustness (Weeks 4-5)
- [ ] Implement E2E scenarios
- [ ] Add failure injection tests
- [ ] Integrate with dev swarm
- [ ] Set up monitoring and alerting

### Phase 3: Optimization (Week 6+)
- [ ] Performance optimization
- [ ] Advanced failure scenarios
- [ ] Swarm-driven improvements
- [ ] Documentation and knowledge transfer

## 9. Conclusion

This playbook provides a comprehensive framework for validating the local venue and UI integration. By following these procedures, we ensure robust, reliable, and maintainable local venue functionality that meets MERID's high standards for quality and performance.

The integration of automated testing, manual validation procedures, and swarm-driven continuous improvement creates a multi-layered defense against regressions and ensures the local venue system remains healthy and performant as the system evolves.

# 🚀 MERID OMS/PMS Integration Tests

**Purpose:** Comprehensive integration testing for Order Management System (OMS) and Portfolio Management System (PMS)  
**Version:** 1.0  
**Date:** 2026-01-26  
**Environment:** prod_canary  
**Status:** READY FOR EXECUTION  

---

## 📋 **A. OMS INTEGRATION TESTS**

### **Basic Order Lifecycle**

#### **Test 1: Order Submission**
- **Description:** Submit a LIMIT BUY from MERID to OMS
- **Steps:**
  1. Configure MERID to submit LIMIT BUY for BTC/USD, size 0.001, price $43,000
  2. Verify order appears in OMS blotter with correct metadata
  3. Confirm OMS forwards order to venue (Coinbase Pro)
- **Expected Results:**
  - Order appears in OMS blotter with correct symbol, side, size, account, strategy ID
  - Order ID correlation maintained between MERID and OMS
  - Order status = NEW in both systems

#### **Test 2: Order Modification**
- **Description:** Modify an existing order from MERID
- **Steps:**
  1. Submit initial LIMIT BUY order
  2. Modify price from $43,000 to $43,100
  3. Verify OMS reflects amended order
- **Expected Results:**
  - OMS shows updated order with new price
  - Venue receives correct modification
  - MERID internal state matches OMS state

#### **Test 3: Order Cancellation**
- **Description:** Cancel an order from OMS UI
- **Steps:**
  1. Submit LIMIT BUY order from MERID
  2. Cancel order via OMS interface
  3. Verify MERID updates internal state
- **Expected Results:**
  - MERID updates order state to CANCELED
  - No lingering OPEN state in MERID
  - Venue receives cancellation request

### **Risk and Rejection Handling**

#### **Test 4: OMS Risk Block**
- **Description:** Test OMS risk rule rejection
- **Steps:**
  1. Configure OMS risk rules to reject orders > $200 notional
  2. Submit order for $300 from MERID
  3. Verify rejection handling
- **Expected Results:**
  - OMS sends clear reject message
  - MERID marks order as REJECTED and logs reason
  - No automatic retries from MERID

#### **Test 5: OMS Connectivity Loss**
- **Description:** Test behavior during OMS connectivity loss
- **Steps:**
  1. Block OMS connectivity temporarily
  2. Attempt to submit order from MERID
  3. Restore OMS connectivity
- **Expected Results:**
  - MERID queues or rejects new orders (no silent drops)
  - Clear alerts generated for connectivity loss
  - Recovery procedures work when connectivity restored

### **Field Mapping and Enrichment**

#### **Test 6: Field Mapping Verification**
- **Description:** Verify correct field mapping between MERID and OMS
- **Steps:**
  1. Submit order with all required fields
  2. Verify OMS receives correct mapping
  3. Check correlation IDs and timestamps
- **Expected Results:**
  - Strategy ID, portfolio/account ID, time-in-force, order type mapped correctly
  - Client order ID unique and traceable
  - OMS-generated IDs and timestamps properly correlated

#### **Test 7: Order ID Correlation**
- **Description:** Test order ID correlation across systems
- **Steps:**
  1. Submit multiple orders simultaneously
  2. Track ID correlation through entire lifecycle
  3. Verify no ID collisions
- **Expected Results:**
  - MERID can correlate OMS IDs with its own order IDs
  - Venue order IDs properly tracked
  - No ID collisions or mismatches

### **End-of-Day OMS Behavior**

#### **Test 8: EOD Position Verification**
- **Description:** Verify OMS positions match MERID and venue
- **Steps:**
  1. Execute several test trades
  2. Run end-of-day reconciliation
  3. Compare positions across systems
- **Expected Results:**
  - OMS positions and cash match MERID and venue
  - OMS P&L for the day ≈ MERID's P&L (within fees/rounding)
  - All discrepancies identified and documented

---

## 📋 **B. PMS INTEGRATION TESTS**

### **Holdings and Balances**

#### **Test 9: Initial Holdings Sync**
- **Description:** Verify initial holdings synchronization
- **Steps:**
  1. Start MERID with existing positions
  2. Verify PMS holdings match MERID and venue
  3. Check cash balances across systems
- **Expected Results:**
  - PMS holdings for BTC, ETH, and cash match MERID and venue
  - All balances within $0.01 tolerance
  - No missing or duplicate positions

#### **Test 10: Real-Time Position Updates**
- **Description:** Test real-time position updates
- **Steps:**
  1. Execute trade (BUY BTC/USD)
  2. Verify PMS updates positions immediately
  3. Check cash balance adjustments
- **Expected Results:**
  - PMS updates positions and cash appropriately
  - Trade size, price, and fee reflected correctly
  - Updates occur within acceptable latency (< 1 second)

### **Cash Flows and Fees**

#### **Test 11: Fee Handling**
- **Description:** Verify fee handling in PMS
- **Steps:**
  1. Execute trades with different fee structures
  2. Verify fees appear correctly in PMS
  3. Check fee accounting accuracy
- **Expected Results:**
  - Realized P&L and fees from executed trades appear in PMS
  - Fee signs and currencies correct
  - Fee calculations match venue statements

#### **Test 12: P&L Reconciliation**
- **Description:** Test P&L reconciliation between systems
- **Steps:**
  1. Execute series of trades
  2. Calculate P&L in MERID
  3. Compare with PMS P&L
- **Expected Results:**
  - MERID P&L matches PMS P&L within acceptable tolerance
  - Differences explained by fees, rounding, or timing
  - All discrepancies documented and resolved

### **Reconciliation and Reporting**

#### **Test 13: EOD Reconciliation**
- **Description:** Test end-of-day reconciliation workflow
- **Steps:**
  1. Run EOD reconciliation process
  2. Verify PMS vs MERID vs venue reconciliation
  3. Generate standard PMS reports
- **Expected Results:**
  - PMS vs MERID vs venue for positions, cash, and P&L match
  - Standard PMS daily performance report generated
  - MERID summary matches key PMS numbers (NAV, P&L, exposures)

#### **Test 14: Corporate Actions**
- **Description:** Test corporate action handling (if applicable)
- **Steps:**
  1. Simulate corporate action (split, dividend)
  2. Verify PMS updates correctly
  3. Check MERID handles updated positions
- **Expected Results:**
  - PMS changes propagate to MERID
  - MERID doesn't trade stale symbols
  - Position adjustments calculated correctly

### **Failure Behavior**

#### **Test 15: PMS Unavailability**
- **Description:** Test behavior during PMS downtime
- **Steps:**
  1. Block PMS connectivity temporarily
  2. Execute trades in MERID
  3. Restore PMS connectivity
- **Expected Results:**
  - MERID queues updates or marks for retry
  - No data loss during PMS unavailability
  - All updates processed after recovery

#### **Test 16: Retry Logic**
- **Description:** Test retry logic for PMS updates
- **Steps:**
  1. Cause intermittent PMS failures
  2. Verify retry behavior
  3. Confirm eventual success
- **Expected Results:**
  - Retry succeeds and PMS eventually reflects all trades
  - Retry limits respected
  - No duplicate updates or data corruption

---

## 📋 **C. PRE-TRADE COMPLIANCE TESTS**

### **Risk Limit Enforcement**

#### **Test 17: Notional Limit Breach**
- **Description:** Test notional limit enforcement
- **Steps:**
  1. Set daily notional limit to $1,000
  2. Attempt order that would exceed limit
  3. Verify rejection behavior
- **Expected Results:**
  - Pre-trade block in MERID before OMS/venue order
  - Clear log entry and no OMS/venue order
  - Alert generated for limit breach

#### **Test 18: Symbol Whitelist Enforcement**
- **Description:** Test symbol whitelist enforcement
- **Steps:**
  1. Configure whitelist for BTC/USD, ETH/USD only
  2. Attempt trade on SOL/USD
  3. Verify rejection
- **Expected Results:**
  - Immediate reject with "symbol not allowed in canary mode"
  - No order sent to OMS or venue
  - Clear audit trail of rejection

#### **Test 19: Account/Portfolio Validation**
- **Description:** Test account/portfolio mapping
- **Steps:**
  1. Submit trade with invalid account/portfolio ID
  2. Verify rejection behavior
  3. Check audit logging
- **Expected Results:**
  - Reject before OMS/venue order
  - No dangling orders in any system
  - Clear rejection reason logged

#### **Test 20: Leverage/Margin Checks**
- **Description:** Test leverage and margin checks
- **Steps:**
  1. Simulate insufficient margin or max leverage breach
  2. Attempt trade that violates limits
  3. Verify enforcement
- **Expected Results:**
  - Pre-trade block with logged reason
  - No order sent to venue
  - Margin calculations accurate

### **Market Status Controls**

#### **Test 21: Market Halt Detection**
- **Description:** Test market halt handling
- **Steps:**
  1. Mark market as HALTED in MERID
  2. Attempt new trade on halted market
  3. Verify rejection
- **Expected Results:**
  - Reject due to market status
  - No venue order sent
  - Clear market status indicator

#### **Test 22: Venue Maintenance Mode**
- **Description:** Test venue maintenance mode
- **Steps:**
  1. Set venue status to MAINTENANCE
  2. Attempt trade
  3. Verify behavior
- **Expected Results:**
  - All new orders rejected
  - Existing positions monitored but not changed
  - Clear maintenance status alerts

### **Duplicate and Fat-Finger Prevention**

#### **Test 23: Duplicate Order Detection**
- **Description:** Test duplicate order detection
- **Steps:**
  1. Rapidly submit identical large orders
  2. Verify detection behavior
  3. Check rate limiting
- **Expected Results:**
  - Second and subsequent attempts blocked
  - Duplication or rate-limit logic engaged
  - Clear alerts for duplicate attempts

#### **Test 24: Fat-Finger Protection**
- **Description:** Test fat-finger protection
- **Steps:**
  1. Submit order with unusually large size
  2. Verify protection mechanisms
  3. Check manual override requirements
- **Expected Results:**
  - Large orders flagged for review
  - Manual approval required
  - Automatic rejection if no approval

---

## 📋 **D. ORDER ROUTING AND EXECUTION TESTS**

### **End-to-End Order Tracing**

#### **Test 25: Order Lifecycle Trace**
- **Description:** Trace order through entire lifecycle
- **Steps:**
  1. Submit test order with correlation ID
  2. Track through all stages
  3. Verify complete audit trail
- **Expected Results:**
  - Single correlation ID visible at each stage:
    - MERID agent decision/pre-trade checks
    - OMS routing
    - Venue execution
    - Execution report back to MERID
    - Reconciliation and P&L updates
    - OMS/PMS updates

#### **Test 26: Positive Path Testing**
- **Description:** Test all order types and scenarios
- **Steps:**
  1. Test MARKET orders
  2. Test LIMIT orders (rest, partial fills, full fills)
  3. Test STOP orders
  4. Test CANCEL/REPLACE operations
- **Expected Results:**
  - All order types route correctly
  - Fills and state updates work properly
  - No order type-specific issues

### **Error and Edge Cases**

#### **Test 27: Invalid Route Handling**
- **Description:** Test invalid venue/endpoint configuration
- **Steps:**
  1. Configure incorrect venue endpoint
  2. Submit order
  3. Verify error handling
- **Expected Results:**
  - MERID detects failure and logs it
  - No indefinite retries
  - Clear error messages and alerts

#### **Test 28: Timeout and Retry Logic**
- **Description:** Test timeout and retry behavior
- **Steps:**
  1. Simulate slow/unresponsive venue
  2. Submit orders
  3. Verify timeout and retry behavior
- **Expected Results:**
  - MERID respects timeouts
  - Limited retries then safe failure
  - No hanging orders or resource leaks

#### **Test 29: Order ID Collision**
- **Description:** Test order ID collision prevention
- **Steps:**
  1. Generate multiple orders rapidly
  2. Check for ID collisions
  3. Verify uniqueness
- **Expected Results:**
  - Client order ID generation unique across strategies and sessions
  - No ID collisions detected
  - Proper error handling if collision occurs

---

## 📋 **E. DATA FEED AND MARKET DATA TESTS**

### **Feed Accuracy and Completeness**

#### **Test 30: Price Accuracy Verification**
- **Description:** Verify price accuracy against references
- **Steps:**
  1. Compare MERID prices to venue REST ticker
  2. Compare to secondary reference (CoinGecko)
  3. Verify tolerance compliance
- **Expected Results:**
  - Prices stay within defined tolerance (5 bps)
  - Exceptions only during actual market jumps
  - Clear alerts for price deviations

#### **Test 31: Data Completeness**
- **Description:** Test data completeness and gap handling
- **Steps:**
  1. Monitor sequence numbers/timestamps
  2. Temporarily drop network connection
  3. Verify gap detection and recovery
- **Expected Results:**
  - MERID detects data gaps
  - Requests historical backfill or snapshot
  - Marks data as "stale" until recovered

#### **Test 32: Latency Measurement**
- **Description:** Measure and verify feed latency
- **Steps:**
  1. Log exchange timestamp and MERID receipt timestamp
  2. Compute latency distribution
  3. Verify within expectations
- **Expected Results:**
  - Feed latency within acceptable ranges
  - Latency metrics properly tracked
  - Alerts for latency degradation

### **Normalization and Enrichment**

#### **Test 33: Data Normalization**
- **Description:** Test data normalization
- **Steps:**
  1. Feed raw venue data
  2. Verify normalization to internal format
  3. Check handling of edge cases
- **Expected Results:**
  - Raw venue data normalized consistently
  - Correct handling of price/size precision
  - Proper aggregation of order book levels

#### **Test 34: Market Event Handling**
- **Description:** Test market event handling
- **Steps:**
  1. Simulate trading halts
  2. Test session changes
  3. Verify event processing
- **Expected Results:**
  - Trading halts detected and processed
  - Session changes handled correctly
  - No trading during inappropriate times

---

## 📋 **F. PERFORMANCE AND SCALABILITY TESTS**

### **Load Testing**

#### **Test 35: Order Burst Handling**
- **Description:** Test burst order handling
- **Steps:**
  1. Submit 50-100 orders in quick succession
  2. Monitor system performance
  3. Verify graceful degradation
- **Expected Results:**
  - System handles burst without crashes
  - Graceful degradation (increased latency, not errors)
  - Resource usage within acceptable limits

#### **Test 36: Data Burst Handling**
- **Description:** Test data burst handling
- **Steps:**
  1. Increase tick frequency significantly
  2. Monitor stream backpressure
  3. Verify system stability
- **Expected Results:**
  - Stream backpressure handling works
  - No data loss or corruption
  - Acceptable latency under load

### **Performance Benchmarks**

#### **Test 37: Latency Benchmarks**
- **Description:** Establish latency benchmarks
- **Steps:**
  1. Measure end-to-end order latency
  2. Measure data feed latency
  3. Establish baseline metrics
- **Expected Results:**
  - Order latency < 250ms p95, < 500ms p99
  - Data feed latency within expectations
  - Baseline metrics documented

#### **Test 38: Throughput Testing**
- **Description:** Test system throughput
- **Steps:**
  1. Sustain order submission rate
  2. Monitor system resources
  3. Verify throughput limits
- **Expected Results:**
  - Sustained throughput within limits
  - Resource usage stable
  - No memory leaks or resource exhaustion

---

## 📋 **G. SECURITY AND COMPLIANCE TESTS**

### **Authentication and Authorization**

#### **Test 39: API Authentication**
- **Description:** Test API authentication
- **Steps:**
  1. Test valid credentials
  2. Test invalid credentials
  3. Test expired credentials
- **Expected Results:**
  - Valid credentials succeed
  - Invalid credentials fail cleanly
  - No partial access with invalid credentials

#### **Test 40: Role-Based Access Control**
- **Description:** Test RBAC functionality
- **Steps:**
  1. Test different user roles
  2. Verify access restrictions
  3. Test privilege escalation prevention
- **Expected Results:**
  - Users can only access authorized functions
  - Privilege escalation prevented
  - Clear audit trail of access attempts

### **Data Protection**

#### **Test 41: Data Encryption**
- **Description:** Verify data encryption
- **Steps:**
  1. Check encryption at rest
  2. Check encryption in transit
  3. Verify key management
- **Expected Results:**
  - Sensitive data encrypted at rest
  - Data encrypted in transit
  - Proper key rotation and management

#### **Test 42: Audit Trail Completeness**
- **Description:** Verify audit trail completeness
- **Steps:**
  1. Execute various operations
  2. Verify audit log entries
  3. Check log integrity
- **Expected Results:**
  - All operations logged
  - Log entries tamper-proof
  - Complete audit trail available

---

## 📋 **H. RECOVERY AND DISASTER RECOVERY TESTS**

### **Service Recovery**

#### **Test 43: Service Restart**
- **Description:** Test service restart procedures
- **Steps:**
  1. Stop critical services
  2. Restart services
  3. Verify recovery
- **Expected Results:**
  - Services restart successfully
  - Data integrity maintained
  - No orphaned orders or positions

#### **Test 44: Database Recovery**
- **Description:** Test database recovery procedures
- **Steps:**
  1. Create database backup
  2. Simulate database failure
  3. Restore from backup
- **Expected Results:**
  - Database recovery successful
  - Data integrity verified
  - Recovery time within acceptable limits

### **Disaster Recovery**

#### **Test 45: Full System Recovery**
- **Description:** Test full disaster recovery
- **Steps:**
  1. Simulate complete system failure
  2. Execute disaster recovery plan
  3. Verify system restoration
- **Expected Results:**
  - System restored from backup
  - All services operational
  - Data consistency verified

---

## 📊 **TEST EXECUTION SUMMARY**

### **Test Categories:**
- **OMS Integration Tests:** 8 tests
- **PMS Integration Tests:** 8 tests
- **Pre-Trade Compliance Tests:** 8 tests
- **Order Routing Tests:** 5 tests
- **Data Feed Tests:** 5 tests
- **Performance Tests:** 4 tests
- **Security Tests:** 4 tests
- **Recovery Tests:** 3 tests

**Total Tests:** 45 comprehensive integration tests

### **Execution Requirements:**
- **Environment:** prod_canary (sandbox mode for testing)
- **Duration:** 2-4 hours for full test suite
- **Prerequisites:** All systems operational, test data prepared
- **Success Criteria:** 100% of critical tests pass, 95%+ overall pass rate

### **Test Results Tracking:**
- **Status:** [ ] PASSED, [ ] FAILED, [ ] SKIPPED
- **Issues:** [ ] Critical, [ ] Major, [ ] Minor
- **Resolution:** [ ] Fixed, [ ] Workaround, [ ] Open

---

## 🚨 **CRITICAL SUCCESS CRITERIA**

**DO NOT PROCEED TO LIVE TRADING IF ANY OF THESE FAIL:**

- [ ] Any OMS integration test fails
- [ ] Any PMS reconciliation test fails
- [ ] Any pre-trade compliance test fails
- [ ] Any kill switch test fails
- [ ] Any reconciliation test fails
- [ ] Any security test fails

---

## 📝 **TEST EXECUTION LOG**

**Test Run Date:** _________________________  
**Test Run ID:** _____________________________  
**Test Executor:** ___________________________  
**Environment:** _____________________________

**Results Summary:**
- **Total Tests:** [ ] / 45
- **Passed:** [ ]
- **Failed:** [ ]
- **Skipped:** [ ]
- **Critical Failures:** [ ]

**Go/No-Go Decision:**
- [ ] **GO** - All critical tests passed
- [ ] **NO-GO** - Critical failures must be resolved
- [ ] **CONDITIONAL** - Minor issues, proceed with caution

**Notes:** _____________________________________________________________
_______________________________________________________________________
_______________________________________________________________________

---

**Last Updated:** 2026-01-26  
**Next Review:** Before each canary execution  
**Owner:** MERID Engineering Team

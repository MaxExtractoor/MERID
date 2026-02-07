# Local Venue Testing - Quick Start Guide

## 🚀 Quick Start Commands

### Run All Local Venue Tests
```bash
# Run complete local venue test suite
pytest -m localvenue -v

# Run with coverage report
pytest -m localvenue --cov=execution --cov=data --cov=venues --cov=web/api --cov-report=html

# Run tests in parallel
pytest -m localvenue -n auto
```

### Run Specific Test Categories
```bash
# Feed handler tests
pytest -m feed_handlers -v

# Matching engine tests  
pytest -m matching_engine -v

# UI integration tests
pytest -m ui_integration -v

# End-to-end tests
pytest -m e2e -v

# Performance tests
pytest -m performance -v
```

### CI/CD Pipeline Commands
```bash
# Fast PR lane (exclude performance tests)
pytest -m "localvenue and not performance" --cov-report=xml

# Nightly heavy lane (include performance and failure scenarios)
pytest -m "e2e or failure_scenarios or performance" -v
```

## 📊 Test Coverage Targets

| Component | Target | Current |
|-----------|--------|---------|
| Feed Handlers | 95% | 🟡 TBD |
| Matching Engine | 90% | 🟡 TBD |
| UI Components | 80% | 🟡 TBD |
| Integration Points | 85% | 🟡 TBD |

## 🎯 Success Criteria

### ✅ Phase 0 (Week 1) - Complete
- [x] Test documentation structure
- [x] Basic unit tests
- [x] UI smoke tests  
- [x] Manual validation script
- [x] pytest configuration

### 🔄 Phase 1 (Weeks 2-3) - Ready
- [ ] Complete unit test coverage
- [ ] Integration tests
- [ ] Automated API tests
- [ ] CI/CD workflows

### ⏳ Phase 2 (Weeks 4-5) - Ready  
- [ ] E2E scenarios
- [ ] Failure injection tests
- [ ] Swarm integration
- [ ] Monitoring and alerting

### 🔮 Phase 3 (Week 6+) - Ready
- [ ] Performance optimization
- [ ] Advanced failure scenarios
- [ ] Swarm-driven improvements
- [ ] Documentation and knowledge transfer

## 🤖 Swarm Integration

### Guardian Agent Commands
```bash
# Run local venue guardian
python -m swarm.agents.local_venue_guardian

# Check validation status
curl http://127.0.0.1:8001/api/v1/localvenue/validation-status

# Get phase progress
curl http://127.0.0.1:8001/api/v1/localvenue/phase-progress
```

### Telemetry Sentinel Commands
```bash
# Run UI telemetry sentinel
python -m swarm.agents.ui_telemetry_sentinel

# Get telemetry dashboard data
curl http://127.0.0.1:8001/api/v1/localvenue/validation-status | jq '.telemetry_metrics'
```

## 📋 Manual Validation Script

### Step-by-Step UI Validation
1. **Start Backend**
   ```bash
   python -m web.main
   ```

2. **Navigate to Local Venue**
   - Open http://127.0.0.1:8001
   - Click "Local Venue" in sidebar

3. **Verify Telemetry Badge**
   - Should show: CONNECTING → ONLINE
   - Badge should be green when healthy

4. **Check Order Book**
   - Should populate with bid/ask data
   - Spread and imbalance should look reasonable

5. **Test Real-time Updates**
   - Submit test orders via API
   - Trades should appear in recent trades list

6. **Test Failure Scenarios**
   - Kill WebSocket process
   - Badge should flip to OFFLINE
   - Panel should show empty state

7. **Test Controls**
   - Use Start/Stop engine controls
   - Verify UI feedback matches backend state

## 🔧 Debugging Commands

### Common Issues
```bash
# Check test imports
python -c "import tests.test_local_venue; print('✓ Tests import OK')"

# Check API endpoints
curl http://127.0.0.1:8001/api/v1/localvenue/health

# Run specific failing test
pytest tests/test_local_venue.py::TestLocalVenueAdapter::test_order_submission -v -s

# Check coverage for specific file
pytest --cov=execution/venue_adapter tests/test_local_venue.py::TestLocalVenueAdapter -v
```

### Performance Debugging
```bash
# Run performance tests with profiling
pytest -m performance --profile --profile-svg

# Check WebSocket connection
curl -i -N -H "Connection: Upgrade" -H "Upgrade: websocket" -H "Sec-WebSocket-Key: test" -H "Sec-WebSocket-Version: 13" http://127.0.0.1:8001/api/v1/localvenue/ws
```

## 📈 Performance Benchmarks

### Expected Performance
- **Order Submission**: < 100ms per order
- **Order Book Updates**: < 50ms  
- **UI API Responses**: < 200ms
- **WebSocket Updates**: < 10ms

### Load Testing
```bash
# Run high-frequency order test
pytest tests/test_local_venue_e2e.py::TestPerformanceAndLoad::test_high_frequency_orders -v -s

# Run concurrent operations test
pytest tests/test_local_venue_e2e.py::TestPerformanceAndLoad::test_concurrent_operations -v -s
```

## 🐛 Troubleshooting

### Test Failures
1. **Import Errors**: Check dependencies with `pip list`
2. **Port Conflicts**: Ensure ports 8000-8009 are available
3. **Async Issues**: Verify `asyncio_mode = auto` in pytest.ini
4. **Resource Cleanup**: Check fixtures properly clean up

### Common Error Messages
- `ModuleNotFoundError`: Install missing dependencies
- `ConnectionRefusedError`: Check if backend is running
- `TimeoutError`: Increase test timeout in pytest.ini
- `AttributeError`: Check component initialization

## 📚 Documentation Links

- **Full Playbook**: `docs/LOCAL_VENUE_VALIDATION_PLAYBOOK.md`
- **Test README**: `tests/README_LOCAL_VENUE.md`
- **API Documentation**: http://127.0.0.1:8001/docs
- **Validation Status**: http://127.0.0.1:8001/api/v1/localvenue/validation-status

## 🎯 Next Steps

1. **Run Phase 1 Tests**: Complete unit and integration test coverage
2. **Set Up CI/CD**: Configure GitHub Actions workflows
3. **Enable Swarm Agents**: Start guardian and sentinel monitoring
4. **Monitor Performance**: Track benchmarks and regressions
5. **Iterate**: Add tests based on failures and edge cases

---

*For detailed information, see the comprehensive documentation in the playbook and test README files.*

# Local Venue Testing README

## Overview

This directory contains comprehensive test suites for the MERID Local Venue integration, covering feed handlers, matching engine, UI components, and end-to-end scenarios.

## Test Structure

### Core Test Files

- **`test_local_venue.py`** - Unit and integration tests for local venue components
- **`test_local_venue_ui.py`** - UI integration and API endpoint tests
- **`test_local_venue_e2e.py`** - End-to-end scenario tests

### Test Categories

#### Unit Tests (`@pytest.mark.localvenue`)
- Feed handler functionality
- Matching engine behavior
- Venue adapter operations
- Book builder integration

#### UI Tests (`@pytest.mark.ui_integration`, `@pytest.mark.ui_api`)
- API endpoint validation
- UI component integration
- Real-time data flow
- Telemetry badge functionality

#### End-to-End Tests (`@pytest.mark.e2e`)
- Complete trade loops
- Failure scenarios
- Cross-venue parity
- Performance under load

## Running Tests

### Basic Test Execution

```bash
# Run all local venue tests
pytest -m localvenue

# Run specific test categories
pytest -m feed_handlers
pytest -m matching_engine
pytest -m ui_integration
pytest -m e2e

# Run with coverage
pytest -m localvenue --cov=execution --cov=data --cov=venues --cov=web/api
```

### Advanced Test Execution

```bash
# Run tests in parallel
pytest -m localvenue -n auto

# Run with verbose output
pytest -m localvenue -v

# Run with duration reporting
pytest -m localvenue --durations=10

# Run specific test file
pytest tests/test_local_venue.py

# Run specific test class
pytest tests/test_local_venue.py::TestLocalVenueAdapter

# Run specific test method
pytest tests/test_local_venue.py::TestLocalVenueAdapter::test_order_submission
```

### Performance and Load Testing

```bash
# Run performance tests
pytest -m performance -v

# Run stress tests
pytest -m stress_core -v

# Run with performance profiling
pytest -m performance --profile
```

## Test Configuration

### pytest.ini Configuration

The `pytest.ini` file contains configuration for:

- **Test markers** for categorizing tests
- **Coverage settings** for code coverage reporting
- **Timeout settings** for test execution
- **Parallel execution** settings

### Environment Variables

```bash
# Set test environment
export MERID_TEST_ENV=local_venue

# Configure test timeouts
export LOCAL_VENUE_TEST_TIMEOUT=30

# Set performance thresholds
export LOCAL_VENUE_PERFORMANCE_THRESHOLD=10.0
```

## Test Data and Fixtures

### Standard Fixtures

- **`adapter`** - LocalVenueAdapter instance for testing
- **`simulator`** - ExecutionSimulator instance
- **`book_manager`** - PersistentOrderBookManager instance
- **`app`** - FastAPI application for API testing
- **`client`** - AsyncHTTPClient for endpoint testing

### Test Data

Test data includes:

- Sample market data messages
- Test order specifications
- Expected API response structures
- Performance benchmark data

## Continuous Integration

### GitHub Actions

The test suite is integrated with CI/CD pipelines:

```yaml
# Example CI configuration
name: Local Venue Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: 3.11
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Run local venue tests
        run: pytest -m localvenue --cov-report=xml
      - name: Upload coverage
        uses: codecov/codecov-action@v1
```

### Test Coverage Targets

- **Feed Handlers**: 95% line coverage
- **Matching Engine**: 90% line coverage
- **UI Components**: 80% coverage for critical paths
- **Integration Points**: 85% coverage for API contracts

## Debugging and Troubleshooting

### Common Issues

1. **Import Errors**: Ensure all dependencies are installed
2. **Async Test Failures**: Check `asyncio_mode = auto` in pytest.ini
3. **Port Conflicts**: Ensure test ports are available
4. **Resource Cleanup**: Verify fixtures properly clean up resources

### Debugging Tips

```bash
# Run with pdb debugger
pytest -m localvenue --pdb

# Run with verbose output and no capture
pytest -m localvenue -v -s

# Run specific failing test
pytest tests/test_local_venue.py::TestLocalVenueAdapter::test_order_submission -v -s
```

### Test Isolation

Tests are designed to be isolated:

- Each test uses its own account
- Resources are cleaned up in fixtures
- No shared state between tests
- Parallel execution supported

## Performance Benchmarks

### Expected Performance

- **Order Submission**: < 100ms per order
- **Order Book Updates**: < 50ms
- **UI API Responses**: < 200ms
- **WebSocket Updates**: < 10ms

### Load Testing

- **Concurrent Orders**: 100 orders/second
- **WebSocket Connections**: 50 concurrent connections
- **API Requests**: 200 requests/second

## Test Maintenance

### Adding New Tests

1. Choose appropriate marker (`@pytest.mark.localvenue`, etc.)
2. Follow naming conventions (`test_*`)
3. Use existing fixtures where possible
4. Add documentation for complex scenarios
5. Update coverage targets if needed

### Test Review Checklist

- [ ] Test has clear documentation
- [ ] Appropriate markers used
- [ ] Fixtures properly used
- [ ] Assertions are meaningful
- [ ] Test is isolated and repeatable
- [ ] Performance considerations addressed

## Swarm Integration

### Automated Test Execution

The test suite is designed for swarm agent execution:

```python
# Example swarm task
def run_local_venue_tests():
    """Run local venue test suite."""
    result = pytest.main([
        "-m", "localvenue",
        "--tb=short",
        "--durations=10"
    ])
    return result
```

### Test Result Analysis

Swarm agents can analyze:

- Test failure patterns
- Performance regressions
- Coverage gaps
- Flaky test identification

## Documentation

### Test Documentation

- Each test class and method has docstrings
- Complex scenarios have detailed explanations
- Performance benchmarks are documented
- Troubleshooting guides are provided

### API Documentation

Test API endpoints are documented with:

- Expected response structures
- Error conditions
- Performance characteristics
- Integration requirements

## Future Enhancements

### Planned Improvements

- **Visual Testing**: Add screenshot-based UI testing
- **Load Testing**: Enhanced performance testing suite
- **Chaos Testing**: Failure injection testing
- **Contract Testing**: API contract validation

### Test Metrics

Track and improve:

- Test execution time
- Test reliability
- Coverage metrics
- Performance benchmarks

## Support

For questions or issues with the local venue test suite:

1. Check existing documentation
2. Review test output and logs
3. Consult troubleshooting guide
4. Create issue with detailed information

---

*This test suite ensures the reliability and performance of the MERID Local Venue integration across all components and scenarios.*

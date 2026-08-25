# Bias Bug Fix Proposal - MERID Trading Stack
**Date**: 2026-07-23  
**Reference**: DEEP_BIAS_BUG_AUDIT_REPORT.md

---

## Overview

This document provides comprehensive fix proposals for the 7 bias bugs identified in the deep audit. Fixes are prioritized by severity and implementation complexity.

---

## P0 Fixes (Critical - Immediate Action Required)

### FIX #1: Dynamic Correlation Matrix

**Bug**: Hardcoded static correlation values in `btc_sentiment_bias.py`

**Implementation Plan**:

1. **Create rolling correlation calculator** (`merid/prediction/rolling_correlation.py`):
```python
class RollingCorrelationCalculator:
    """Computes rolling correlations from historical price data."""
    
    def __init__(self, window_days: int = 30, min_samples: int = 100):
        self.window_days = window_days
        self.min_samples = min_samples
        self.price_history: Dict[str, List[Tuple[float, float]]] = {}
    
    def update_price(self, asset: str, price: float, timestamp: float):
        """Add price point to history."""
        self.price_history.setdefault(asset, []).append((timestamp, price))
        self._prune_old_data(asset, timestamp)
    
    def compute_correlation(self, asset1: str, asset2: str) -> Optional[float]:
        """Compute Pearson correlation between two assets."""
        if len(self.price_history[asset1]) < self.min_samples:
            return None
        
        # Align timestamps and compute correlation
        # Returns correlation or None if insufficient data
```

2. **Update BTC sentiment bias** (`merid/prediction/btc_sentiment_bias.py`):
```python
class BTCSentimentBias:
    def __init__(self, config: SentimentBiasConfig):
        self.config = config
        self._correlation_calculator = RollingCorrelationCalculator(
            window_days=30,
            min_samples=100
        )
        # Remove hardcoded _correlation_matrix
        # Correlations now computed dynamically
    
    def get_bias_adjustment(self, asset: str, base_edge: float, current_side: str) -> float:
        # Compute correlation dynamically
        correlation = self._correlation_calculator.compute_correlation("BTC", asset)
        
        if correlation is None:
            # Fall back to conservative default if insufficient data
            correlation = 0.5
        
        # Rest of logic unchanged
```

3. **Integration points**:
- Add correlation calculator initialization in `web/main_15m_lean.py`
- Feed price updates from `data/live_price_feed.py` to correlation calculator
- Add correlation monitoring to API endpoint

4. **Validation**:
- Log correlation values when they change significantly (>0.1 delta)
- Alert if correlation confidence interval is wide (unstable correlation)
- Fall back to conservative defaults during low-data periods

**Estimated Effort**: 2-3 days  
**Risk**: Medium - requires careful testing of correlation calculation

---

### FIX #2: Dynamic Signal Quality Calculation

**Bug**: Static signal quality metadata in `asset_universe.py`

**Implementation Plan**:

1. **Create signal quality tracker** (`merid/prediction/signal_quality_tracker.py`):
```python
class SignalQualityTracker:
    """Tracks prediction accuracy and computes dynamic signal quality."""
    
    def __init__(self, window_trades: int = 50, min_trades: int = 10):
        self.window_trades = window_trades
        self.min_trades = min_trades
        self.prediction_history: Dict[str, List[Dict]] = {}
    
    def record_prediction(self, asset: str, prediction: str, confidence: float, timestamp: float):
        """Record a prediction for later evaluation."""
        self.prediction_history.setdefault(asset, []).append({
            "prediction": prediction,
            "confidence": confidence,
            "timestamp": timestamp,
            "outcome": None  # To be filled later
        })
    
    def record_outcome(self, asset: str, timestamp: float, actual: str):
        """Record actual outcome for a prediction."""
        # Match prediction by timestamp and record accuracy
    
    def compute_signal_quality(self, asset: str) -> Optional[float]:
        """Compute signal quality from recent prediction accuracy."""
        history = self.prediction_history.get(asset, [])
        
        if len(history) < self.min_trades:
            return None  # Not enough data
        
        # Use last window_trades predictions
        recent = history[-self.window_trades:]
        
        # Compute accuracy (weighted by confidence)
        correct = sum(1 for p in recent if p["prediction"] == p["outcome"])
        accuracy = correct / len(recent)
        
        # Map accuracy to quality score (0.0-1.0)
        # Use sigmoid function for smooth mapping
        quality = 1.0 / (1.0 + math.exp(-10 * (accuracy - 0.5)))
        
        return quality
```

2. **Update signal generator** (`ai_signals/signal_generator.py`):
```python
class AISignalGenerator:
    def __init__(self):
        self._quality_tracker = SignalQualityTracker()
    
    def _create_signal_from_predictions(self, predictions, asset):
        # Get dynamic signal quality
        dynamic_quality = self._quality_tracker.compute_signal_quality(asset)
        
        if dynamic_quality is not None:
            # Use dynamic quality instead of static metadata
            quality = dynamic_quality
        else:
            # Fall back to static metadata from asset_universe
            quality = asset.signal_quality
        
        # Apply quality cap to confidence
        capped_confidence = min(confidence, quality)
```

3. **Integration points**:
- Record predictions in `merid/prediction/agent_grid_15m.py`
- Record outcomes in `merid/event_venues/kalshi/settlement_poller.py`
- Add signal quality to API monitoring

4. **Validation**:
- Log signal quality changes >0.1
- Alert if quality drops below 0.3 for any asset
- Add minimum sample size guard to prevent noise

**Estimated Effort**: 2-3 days  
**Risk**: Low - additive change with fallback to static values

---

### FIX #3: Remove Mock Data from Production API

**Bug**: Mock data in `web/services/prediction_publisher.py`

**Implementation Plan**:

1. **Wire real data sources** (`web/services/prediction_publisher.py`):
```python
# Replace mock data with real sources
async def get_prediction_metrics(self, asset: str):
    """Get real prediction metrics from trading engine."""
    
    # Real PnL from fills_ledger
    from merid.event_venues.kalshi.fills_ledger import get_fills_ledger
    ledger = get_fills_ledger()
    our_pnl = ledger.get_asset_pnl(asset)
    
    # Real confidence from latest signal
    from merid.prediction.agent_grid_15m import get_latest_signal
    latest_signal = get_latest_signal(asset)
    model_confidence = latest_signal.confidence if latest_signal else 0.5
    
    # Real price from market_state
    from merid.event_venues.kalshi.market_state import get_market_state
    market_state = get_market_state()
    yes_price = market_state.get_best_yes_price(asset)
    
    return {
        "ourPnl": our_pnl,
        "modelConfidence": model_confidence,
        "yesPrice": yes_price,
    }
```

2. **Add validation layer**:
```python
def validate_data_sources():
    """Ensure all data sources are real and available."""
    checks = {
        "fills_ledger": check_fills_ledger_available,
        "market_state": check_market_state_available,
        "signal_history": check_signal_history_available,
    }
    
    for name, check in checks.items():
        if not check():
            raise RuntimeError(f"Data source {name} not available - cannot start API")
```

3. **Add health check endpoint**:
```python
@app.get("/api/health/data-sources")
async def check_data_sources():
    """Health check for data source availability."""
    return {
        "fills_ledger": check_fills_ledger_available(),
        "market_state": check_market_state_available(),
        "signal_history": check_signal_history_available(),
        "all_healthy": all([
            check_fills_ledger_available(),
            check_market_state_available(),
            check_signal_history_available(),
        ])
    }
```

4. **Integration points**:
- Update all API endpoints to use real data
- Add startup validation in `web/main_15m_lean.py`
- Add monitoring for data source health

5. **Validation**:
- Add unit tests to verify no mock data in production paths
- Add integration tests with real data sources
- Add alerting when data sources become unavailable

**Estimated Effort**: 1-2 days  
**Risk**: Low - straightforward wiring to existing data sources

---

## P1 Fixes (High Priority - This Week)

### FIX #4: Integrate Walk-Forward Validation

**Bug**: Walk-forward optimizer exists but not integrated into production

**Implementation Plan**:

1. **Create production validation pipeline** (`merid/prediction/production_validator.py`):
```python
class ProductionValidator:
    """Continuous walk-forward validation for production signals."""
    
    def __init__(self, train_days: int = 252, test_days: int = 63, embargo_days: int = 5):
        self.train_days = train_days
        self.test_days = test_days
        self.embargo_days = embargo_days
        self.validation_results: List[ValidationResult] = []
    
    def run_validation_cycle(self, current_date: datetime) -> ValidationResult:
        """Run a single walk-forward validation cycle."""
        # Get training data (current_date - train_days - embargo_days to current_date - embargo_days)
        train_start = current_date - timedelta(days=self.train_days + self.embargo_days)
        train_end = current_date - timedelta(days=self.embargo_days)
        
        # Get test data (current_date - embargo_days to current_date)
        test_start = current_date - timedelta(days=self.embargo_days)
        test_end = current_date
        
        # Train model on training data
        model = self.train_model(train_start, train_end)
        
        # Test on out-of-sample data
        test_metrics = self.test_model(model, test_start, test_end)
        
        # Compare to in-sample performance
        train_metrics = self.evaluate_model(model, train_start, train_end)
        
        # Check for overfitting
        degradation = (train_metrics["sharpe"] - test_metrics["sharpe"]) / train_metrics["sharpe"]
        
        return ValidationResult(
            train_metrics=train_metrics,
            test_metrics=test_metrics,
            degradation=degradation,
            is_overfitting=degradation > 0.3,  # 30% degradation threshold
        )
```

2. **Add automated scheduling**:
```python
# In web/main_15m_lean.py
async def validation_task():
    """Run validation daily."""
    validator = ProductionValidator()
    
    while True:
        result = validator.run_validation_cycle(datetime.now(timezone.utc))
        
        if result.is_overfitting:
            # Alert on overfitting
            await send_alert("Model overfitting detected", result)
        
        # Store result for monitoring
        store_validation_result(result)
        
        # Run daily
        await asyncio.sleep(24 * 3600)
```

3. **Add API endpoint for validation results**:
```python
@app.get("/api/validation/walk-forward")
async def get_validation_results():
    """Get recent walk-forward validation results."""
    return {
        "latest": get_latest_validation_result(),
        "history": get_validation_history(days=30),
        "overfitting_alerts": get_overfitting_alerts(days=30),
    }
```

4. **Integration points**:
- Add to `web/main_15m_lean.py` startup
- Schedule daily validation task
- Add to monitoring dashboard

5. **Validation**:
- Test with historical data to verify correct temporal separation
- Verify embargo period prevents leakage
- Add unit tests for degradation calculation

**Estimated Effort**: 3-4 days  
**Risk**: Medium - requires careful temporal handling

---

### FIX #5: Re-enable Price Validation

**Bug**: Price validation disabled for production profile

**Implementation Plan**:

1. **Update price validation logic** (`data/live_price_feed.py`):
```python
def _is_price_validation_enabled() -> bool:
    """Price validation should always be enabled."""
    # Previously disabled for kalshi_crypto_15m_v2 profile
    # Re-enable with appropriate thresholds
    return True

def _validate_price_reasonableness(symbol: str, price: float) -> bool:
    """Validate price is within reasonable bounds."""
    # Use dynamic thresholds based on recent price history
    base_symbol = symbol.split('/')[0].upper()
    
    # Get recent price statistics (rolling window)
    recent_stats = get_recent_price_stats(base_symbol, window_days=30)
    
    if recent_stats is None:
        # Fall back to static ranges if no history
        return _validate_with_static_ranges(base_symbol, price)
    
    # Dynamic validation: price within 5 standard deviations of mean
    mean = recent_stats["mean"]
    std = recent_stats["std"]
    
    lower_bound = mean - 5 * std
    upper_bound = mean + 5 * std
    
    if not (lower_bound <= price <= upper_bound):
        logger.warning(
            f"Price validation failed for {symbol}: ${price:.2f} outside "
            f"dynamic range (${lower_bound:.2f} - ${upper_bound:.2f})"
        )
        return False
    
    return True
```

2. **Add price statistics tracker**:
```python
class PriceStatisticsTracker:
    """Tracks rolling price statistics for dynamic validation."""
    
    def __init__(self, window_days: int = 30):
        self.window_days = window_days
        self.price_history: Dict[str, List[float]] = {}
    
    def update_price(self, asset: str, price: float):
        """Add price to history."""
        self.price_history.setdefault(asset, []).append(price)
        self._prune_old_data(asset)
    
    def get_statistics(self, asset: str) -> Optional[Dict]:
        """Get mean and std for asset."""
        prices = self.price_history.get(asset, [])
        
        if len(prices) < 10:
            return None
        
        return {
            "mean": np.mean(prices),
            "std": np.std(prices),
            "min": np.min(prices),
            "max": np.max(prices),
        }
```

3. **Add validation failure handling**:
```python
def handle_validation_failure(symbol: str, price: float):
    """Handle price validation failure."""
    # Log failure
    logger.error(f"Price validation failed for {symbol}: ${price:.2f}")
    
    # Increment failure counter
    increment_validation_failure_counter(symbol)
    
    # If too many failures, alert and potentially halt trading
    if get_validation_failure_count(symbol) > 5:
        send_alert(f"Excessive price validation failures for {symbol}")
        # Consider halting trading for this asset
```

4. **Integration points**:
- Update `_is_price_validation_enabled()` to return True
- Add price statistics tracker to `data/live_price_feed.py`
- Add validation failure monitoring

5. **Validation**:
- Test with historical price data to verify thresholds
- Monitor validation failure rate in production
- Adjust thresholds if false positive rate is high

**Estimated Effort**: 1-2 days  
**Risk**: Low - conservative thresholds with fallback

---

## P2 Fixes (Medium Priority - Next Sprint)

### FIX #6: Add Deterministic Seed Handling

**Bug**: No fixed seeds in production ML

**Implementation Plan**:

1. **Create seed manager** (`merid/ml/seed_manager.py`):
```python
class SeedManager:
    """Manages random seeds for reproducible ML execution."""
    
    def __init__(self, base_seed: int = 42):
        self.base_seed = base_seed
        self.current_seed = base_seed
        self.seed_history: List[Tuple[str, int]] = []
    
    def set_seed(self, context: str, seed: Optional[int] = None):
        """Set random seed for a context."""
        if seed is None:
            seed = self.current_seed
            self.current_seed += 1
        
        # Set all random seeds
        random.seed(seed)
        np.random.seed(seed)
        if torch_available:
            torch.manual_seed(seed)
            torch.cuda.manual_seed_all(seed)
        
        # Log for reproducibility
        self.seed_history.append((context, seed))
        logger.info(f"Seed set for {context}: {seed}")
        
        return seed
    
    def get_seed_for_context(self, context: str) -> int:
        """Get the seed used for a context."""
        for ctx, seed in reversed(self.seed_history):
            if ctx == context:
                return seed
        return self.base_seed
```

2. **Update model training** (`ai_signals/deep_learning_models.py`):
```python
class DeepLearningModel:
    def train(self, X, y):
        """Train model with deterministic seed."""
        from merid.ml.seed_manager import get_seed_manager
        seed_mgr = get_seed_manager()
        
        # Set seed for this training run
        seed = seed_mgr.set_seed(f"model_train_{self.model_id}")
        
        # Log seed for reproducibility
        logger.info(f"Training model {self.model_id} with seed {seed}")
        
        # Training logic...
```

3. **Add seed logging to API**:
```python
@app.get("/api/ml/seeds")
async def get_seed_history():
    """Get seed history for reproducibility."""
    seed_mgr = get_seed_manager()
    return {
        "current_seed": seed_mgr.current_seed,
        "history": seed_mgr.seed_history,
    }
```

4. **Integration points**:
- Add seed manager initialization in `web/main_15m_lean.py`
- Update all model training/inference to use seed manager
- Add seed logging to all ML operations

5. **Validation**:
- Test that same seed produces identical results
- Add unit tests for seed manager
- Verify seed history is logged correctly

**Estimated Effort**: 1-2 days  
**Risk**: Low - additive change with no behavior change

---

### FIX #7: Adaptive Liquidity Thresholds

**Bug**: Static liquidity thresholds in profile YAML

**Implementation Plan**:

1. **Create adaptive liquidity calculator** (`merid/prediction/adaptive_liquidity.py`):
```python
class AdaptiveLiquidityCalculator:
    """Computes adaptive liquidity thresholds from recent history."""
    
    def __init__(self, window_minutes: int = 60, percentile: float = 0.8):
        self.window_minutes = window_minutes
        self.percentile = percentile
        self.depth_history: Dict[str, List[Tuple[float, int]]] = {}
    
    def update_depth(self, asset: str, depth: int, timestamp: float):
        """Add depth observation to history."""
        self.depth_history.setdefault(asset, []).append((timestamp, depth))
        self._prune_old_data(asset, timestamp)
    
    def get_threshold(self, asset: str) -> Optional[int]:
        """Get adaptive liquidity threshold for asset."""
        history = self.depth_history.get(asset, [])
        
        if len(history) < 10:
            return None  # Not enough data
        
        depths = [d for _, d in history]
        
        # Use percentile instead of fixed threshold
        threshold = np.percentile(depths, self.percentile * 100)
        
        return int(threshold)
```

2. **Update candidate optimizer** (`merid/prediction/candidate_optimizer.py`):
```python
class CandidateOptimizer:
    def __init__(self):
        self.liquidity_calc = AdaptiveLiquidityCalculator()
    
    def generate_candidates(self, markets):
        """Generate candidates with adaptive liquidity thresholds."""
        for market in markets:
            # Get adaptive threshold
            threshold = self.liquidity_calc.get_threshold(market.asset)
            
            if threshold is None:
                # Fall back to profile default
                threshold = self.get_profile_threshold(market.asset)
            
            # Apply adaptive threshold
            if market.total_depth < threshold:
                continue  # Skip illiquid market
```

3. **Add time-of-day adjustments**:
```python
def get_time_of_day_multiplier(timestamp: float) -> float:
    """Get liquidity multiplier based on time of day."""
    hour = datetime.fromtimestamp(timestamp, timezone.utc).hour
    
    # US hours (14:00-20:00 UTC) = highest liquidity
    if 14 <= hour < 20:
        return 1.0
    # European hours (8:00-14:00 UTC) = medium liquidity
    elif 8 <= hour < 14:
        return 0.8
    # Asian hours (0:00-8:00 UTC) = lower liquidity
    elif 0 <= hour < 8:
        return 0.6
    # Weekend = lowest liquidity
    else:
        return 0.5
```

4. **Integration points**:
- Add liquidity calculator to `candidate_optimizer.py`
- Feed depth updates from market state
- Add time-of-day multiplier to threshold calculation

5. **Validation**:
- Monitor threshold stability over time
- Adjust percentile if too much volatility
- Add alerting if threshold drops too low

**Estimated Effort**: 2-3 days  
**Risk**: Medium - requires tuning of percentile and window

---

## Implementation Timeline

### Week 1 (P0 Fixes)
- Day 1-2: FIX #3 (Remove mock data)
- Day 3-4: FIX #1 (Dynamic correlations)
- Day 5: FIX #2 (Dynamic signal quality)

### Week 2 (P1 Fixes)
- Day 1-2: FIX #5 (Price validation)
- Day 3-6: FIX #4 (Walk-forward validation)

### Week 3 (P2 Fixes)
- Day 1-2: FIX #6 (Deterministic seeds)
- Day 3-5: FIX #7 (Adaptive liquidity)

---

## Testing Strategy

### Unit Tests
- Each fix should have comprehensive unit tests
- Test edge cases (no data, single data point, extreme values)
- Test fallback behavior when data is unavailable

### Integration Tests
- Test fixes in the full trading pipeline
- Verify no regressions in existing functionality
- Test with historical data for validation fixes

### Production Rollout
- Deploy fixes incrementally (one at a time)
- Monitor metrics after each deployment
- Have rollback plan ready for each fix

---

## Monitoring Requirements

### New Metrics to Track
1. **Correlation values** - log when they change >0.1
2. **Signal quality** - track per-asset quality over time
3. **Data source health** - monitor availability of real data sources
4. **Validation degradation** - track in-sample vs out-of-sample performance
5. **Price validation failures** - count and alert on excessive failures
6. **Seed history** - log all seeds used for reproducibility
7. **Liquidity thresholds** - track adaptive threshold values

### Alerts to Configure
1. Correlation confidence interval wide (unstable correlation)
2. Signal quality drops below 0.3
3. Data source unavailable
4. Validation degradation >30%
5. Price validation failures >5 in 10 minutes
6. Liquidity threshold drops below minimum

---

## Risk Mitigation

### Rollback Plan
- Each fix should be feature-flagged for easy rollback
- Keep old code paths available as fallback
- Monitor for regressions after each deployment

### Testing in Production
- Use canary deployment for high-risk fixes
- Run new code in shadow mode before full rollout
- Compare new vs old behavior before cutover

### Documentation
- Update architecture docs to reflect changes
- Document new APIs and endpoints
- Create runbooks for new monitoring/alerts

---

## Success Criteria

### P0 Fixes
- [ ] No mock data in production API responses
- [ ] Correlations computed dynamically with 30-day window
- [ ] Signal quality computed from recent prediction accuracy
- [ ] All P0 fixes deployed and stable for 1 week

### P1 Fixes
- [ ] Walk-forward validation running daily
- [ ] Price validation enabled with <1% false positive rate
- [ ] All P1 fixes deployed and stable for 1 week

### P2 Fixes
- [ ] All ML operations use deterministic seeds
- [ ] Liquidity thresholds adaptive with <10% volatility
- [ ] All P2 fixes deployed and stable for 1 week

---

**Proposal Completed**: 2026-07-23  
**Next Steps**: Review with team, prioritize P0 fixes for immediate implementation

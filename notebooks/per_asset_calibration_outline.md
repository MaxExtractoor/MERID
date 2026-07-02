# Per-Asset Calibration Notebook Outline

## Purpose
This notebook outlines the process for fitting per-asset spot-contract mappings \( f_a(S, \text{strike}, \tau) \to q_a(t) \) from historical RTI and Kalshi contract outcomes.

## Data Requirements

### 1. Historical Kalshi Contract Data
- Contract outcomes (YES/NO) for all 15m crypto markets
- Strike prices
- Expiry times
- Settlement prices (CF Benchmarks RTI)
- Time series of contract prices (bid/ask/mid) during the 15m window

**Data source:** Kalshi API historical data, or export from trading logs

### 2. Historical Spot Price Data
- CF Benchmarks RTI 60-second averages for each asset
- Or composite index that approximates RTI behavior
- Time series aligned with contract windows

**Data source:** CF Benchmarks API, or composite from multiple exchanges

### 3. Market Microstructure Data
- Order book depth and spread history
- Slippage data (expected vs actual fill prices)
- Volume profile per asset

**Data source:** Kalshi order book snapshots, execution logs

## Calibration Steps

### Step 1: Data Alignment
```python
# Align spot data with contract windows
# For each contract:
# - Extract 15m window from spot data
# - Compute RTI-like averages (60-second rolling averages)
# - Align with contract price time series
```

**Key considerations:**
- Time zone handling (UTC)
- Data gaps and missing values
- Synchronization between spot and contract data

### Step 2: Feature Engineering
```python
# For each contract window, compute:
features = {
    'spot_move_pct': (spot_final - spot_initial) / strike,
    'spot_volatility': std(spot_returns),
    'time_to_expiry': seconds_until_expiry,
    'initial_spread': initial_bid_ask_spread,
    'avg_depth': average_orderbook_depth,
    'price_path': full_price_path_features,  # e.g., max drawdown, etc.
}
```

**Key features:**
- Spot move relative to strike
- Time to expiry (normalized)
- Volatility regime
- Microstructure metrics (spread, depth)
- Price path characteristics

### Step 3: Model Fitting
```python
# Fit per-asset model: f_a(S, strike, τ) → q_a(t)
# Use logistic regression or similar to predict win probability

from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier

# For each asset (BTC, ETH, SOL, XRP, DOGE):
for asset in assets:
    X = features[asset]  # Feature matrix
    y = outcomes[asset]  # Binary outcomes (1=YES won, 0=NO won)
    
    # Fit model
    model = LogisticRegression()
    model.fit(X, y)
    
    # Extract coefficients for calibration parameters
    calibration[asset] = {
        'base_win_rate': model.intercept_[0],
        'spot_sensitivity': model.coef_[0]['spot_move_pct'],
        'time_decay': model.coef_[0]['time_to_expiry'],
        'vol_adjustment': model.coef_[0]['spot_volatility'],
    }
```

**Model options:**
- Logistic regression (interpretable coefficients)
- Random forest (non-linear relationships)
- Gradient boosting (complex interactions)
- Neural network (if sufficient data)

### Step 4: Volatility Estimation
```python
# Estimate per-asset 15m volatility in RTI terms
# Compute standard deviation of RTI 60-second averages over many 15m windows

for asset in assets:
    rti_series = get_rti_averages(asset)
    window_returns = compute_15m_returns(rti_series)
    volatility_15m[asset] = std(window_returns)
```

**Key considerations:**
- Use RTI averages, not raw spot prices
- Compute over sufficient historical window (e.g., 30 days)
- Account for regime changes (volatility clustering)

### Step 5: Slippage Model Calibration
```python
# Fit per-asset slippage model
# Expected slippage = f(spread, depth, order_size)

for asset in assets:
    # Collect historical slippage data
    slippage_data = collect_slippage_data(asset)
    
    # Fit model
    from sklearn.linear_model import LinearRegression
    X = slippage_data[['spread_cents', 'depth', 'order_size']]
    y = slippage_data['actual_slippage_cents']
    
    model = LinearRegression()
    model.fit(X, y)
    
    slippage_model[asset] = {
        'base_slippage_cents': model.intercept_,
        'spread_factor': model.coef_[0],
        'depth_factor': model.coef_[1],
        'size_factor': model.coef_[2],
    }
```

**Key considerations:**
- Separate slippage by order size
- Account for time-of-day effects
- Model asymmetric slippage (buy vs sell)

### Step 6: Validation
```python
# Validate calibration on hold-out set
# Compute calibration metrics:
# - Brier score (probability calibration)
# - ROC AUC (discrimination)
# - Edge distribution (sanity check)

for asset in assets:
    # Predict on hold-out set
    y_pred = model.predict_proba(X_holdout)[:, 1]
    
    # Compute metrics
    brier_score = mean_squared_error(y_holdout, y_pred)
    roc_auc = roc_auc_score(y_holdout, y_pred)
    
    # Check edge distribution
    edge = y_pred - market_implied_prob
    print(f"{asset}: Brier={brier_score:.4f}, AUC={roc_auc:.4f}, edge_mean={edge.mean():.4f}")
```

**Validation criteria:**
- Brier score < 0.25 (reasonable calibration)
- ROC AUC > 0.6 (some predictive power)
- Edge distribution centered around 0 (no systematic bias)

### Step 7: Alignment Check
```python
# Check alignment between spot reference and contract pricing
# Compute implied spot from contract price using fitted model
# Compare to actual spot (RTI)

for asset in assets:
    gap = spot_ref - implied_spot_from_contract
    gap_cents = gap * 100
    
    # Check if gap exceeds threshold
    if abs(gap_cents) > 50:
        print(f"{asset}: ALIGNMENT FAIL - gap={gap_cents:.1f}c")
```

**Key considerations:**
- Systematic bias indicates model misspecification
- Time-varying bias indicates regime change
- Large gaps trigger degraded mode in production

## Deployment

### Step 8: Export Calibration Parameters
```python
# Export fitted parameters to YAML or JSON
# Load into PerAssetCalibration in unified_edge.py

calibration_export = {
    'BTC': {
        'base_win_rate': 0.5,
        'spot_sensitivity': 0.1,
        'time_decay': 0.05,
        'vol_adjustment': 1.0,
        'rti_bias_cents': 0,
    },
    # ... other assets
}

with open('config/per_asset_calibration.yaml', 'w') as f:
    yaml.dump(calibration_export, f)
```

### Step 9: Continuous Monitoring
```python
# Set up monitoring for calibration drift
# Re-fit models periodically (e.g., weekly)
# Track edge distribution over time
# Alert on alignment failures

monitoring_metrics = {
    'edge_mean': rolling_mean(edge, window=100),
    'edge_std': rolling_std(edge, window=100),
    'alignment_gap': rolling_mean(gap_cents, window=100),
}
```

## Notebook Structure

```python
# Cell 1: Imports and setup
import pandas as pd
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score

# Cell 2: Load historical data
kalshi_data = load_kalshi_historical()
spot_data = load_spot_historical()

# Cell 3: Data alignment
aligned_data = align_data(kalshi_data, spot_data)

# Cell 4: Feature engineering
features = engineer_features(aligned_data)

# Cell 5: Model fitting (per asset)
calibrations = fit_models(features)

# Cell 6: Volatility estimation
volatility_15m = estimate_volatility(spot_data)

# Cell 7: Slippage model calibration
slippage_models = calibrate_slippage(execution_data)

# Cell 8: Validation
validation_metrics = validate_models(calibrations, holdout_data)

# Cell 9: Alignment check
alignment_gaps = check_alignment(calibrations, spot_data)

# Cell 10: Export calibration parameters
export_calibration(calibrations, volatility_15m, slippage_models)
```

## TODOs

- [ ] Set up data pipeline for historical Kalshi data
- [ ] Set up data pipeline for CF Benchmarks RTI data
- [ ] Implement data alignment logic
- [ ] Implement feature engineering
- [ ] Fit initial models (placeholder parameters currently in use)
- [ ] Validate models on hold-out set
- [ ] Set up continuous monitoring
- [ ] Document model retraining schedule

## References

- CF Benchmarks RTI methodology: https://www.cfbenchmarks.com/
- Kalshi crypto markets: https://help.kalshi.com/en/articles/13823838-crypto-markets
- Logistic regression for probability calibration: https://scikit-learn.org/stable/modules/calibration.html

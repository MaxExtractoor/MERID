# Production Infrastructure Guide
**Docker Compose, ML Risk Models, and Deployment Patterns**

---

## Overview

This guide covers production deployment of the Kalshi swarm architecture using Docker Compose, ML-based risk forecasting, and operational best practices.

---

## 1. Docker Compose Architecture

### Service Topology

```
┌─────────────────────────────────────────────────────┐
│                    event-bus (NATS)                 │
│                 nats://event-bus:4222               │
└─────┬───────────────┬────────────────┬──────────────┘
      │               │                │
      ↓               ↓                ↓
┌─────────────┐ ┌──────────────┐ ┌─────────────┐
│kalshi-ws    │ │swarm-agents  │ │merid-api    │
│-bridge      │ │(TypeScript)  │ │(Python)     │
│(Python)     │ └──────────────┘ └─────────────┘
└─────────────┘         ↑                ↑
                        │                │
                        └────────────────┴──→ Redis
```

### Quick Start

```bash
# Create secrets directory
mkdir -p secrets/

# Place Kalshi private key
cp /path/to/kalshi_private_key.pem secrets/

# Set environment variables
export KALSHI_API_KEY_ID="your_key_id"
export KALSHI_ENV="demo"  # or "prod"
export KALSHI_MARKETS="KXHARRIS24-LSV,BTC-15M,ETH-15M"
export ENABLE_LIVE_TRADING="false"
export KALSHI_MODE="paper"

# Start services
docker compose -f infra/docker-compose.kalshi-swarm.yml up -d

# View logs
docker compose -f infra/docker-compose.kalshi-swarm.yml logs -f

# Stop services
docker compose -f infra/docker-compose.kalshi-swarm.yml down
```

### Environment Configuration

Create `.env` file for environment-specific config:

```bash
# .env.demo (for staging/paper trading)
KALSHI_API_KEY_ID=demo_key_id_here
KALSHI_PRIVATE_KEY_FILE=./secrets/kalshi_demo_private_key.pem
KALSHI_ENV=demo
KALSHI_MARKETS=KXHARRIS24-LSV,BTC-15M,ETH-15M
ENABLE_LIVE_TRADING=false
KALSHI_MODE=paper
MAX_POSITION_SIZE=50
MAX_DAILY_LOSS=500
SWARM_AGENT_REPLICAS=1
LOG_LEVEL=DEBUG
API_PORT=8000
UI_PORT=3000
```

```bash
# .env.prod (for live trading)
KALSHI_API_KEY_ID=prod_key_id_here
KALSHI_PRIVATE_KEY_FILE=./secrets/kalshi_prod_private_key.pem
KALSHI_ENV=prod
KALSHI_MARKETS=KXHARRIS24-LSV,BTC-15M,ETH-15M,ETH-1H
ENABLE_LIVE_TRADING=true
KALSHI_MODE=live
MAX_POSITION_SIZE=100
MAX_DAILY_LOSS=1000
SWARM_AGENT_REPLICAS=2
LOG_LEVEL=INFO
API_PORT=8000
UI_PORT=3000
ENABLE_SWARM_MODE=true
```

### Service Scaling

```bash
# Scale swarm agents
docker compose -f infra/docker-compose.kalshi-swarm.yml up -d --scale swarm-agents=4

# Resource limits per service (in docker-compose.yml):
# - kalshi-ws-bridge: 0.5 CPU, 512MB RAM
# - swarm-agents: 1.0 CPU, 512MB RAM (per replica)
# - merid-api: 2.0 CPU, 2GB RAM
# - ui: 0.5 CPU, 256MB RAM
```

---

## 2. ML Models for Kalshi Prediction Risk Forecasting

### Model Stack Overview

**Purpose:** Predict risk metrics (drawdown probability, tail loss, calibration) for position sizing and risk management.

### Model 1: Logistic Regression (Outcome Probability)

**Objective:** Predict P(contract resolves YES) given market features

```python
# merid_ml/models/outcome_predictor.py
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

class OutcomePredictor:
    """
    Predicts event outcome probability using market microstructure features.
    
    Features:
    - Implied probability (current mid price / 100)
    - Orderbook imbalance
    - Recent volume
    - Spread tightness
    - Time to expiry
    """
    
    def __init__(self):
        self.scaler = StandardScaler()
        self.model = LogisticRegression(
            penalty='l2',
            C=1.0,
            solver='lbfgs',
            max_iter=1000
        )
    
    def extract_features(self, market_data):
        """Extract features from market snapshot."""
        return np.array([
            market_data['implied_prob'],
            market_data['imbalance'],
            market_data['recent_volume'],
            market_data['spread'] / market_data['mid'],  # Relative spread
            market_data['hours_to_expiry'],
        ])
    
    def train(self, historical_markets, outcomes):
        """
        Train on historical Kalshi market data.
        
        Args:
            historical_markets: List of market snapshots (features)
            outcomes: Binary outcomes (1 = YES, 0 = NO)
        """
        X = np.array([self.extract_features(m) for m in historical_markets])
        X_scaled = self.scaler.fit_transform(X)
        self.model.fit(X_scaled, outcomes)
    
    def predict_proba(self, market_data):
        """Predict P(YES) for current market state."""
        X = self.extract_features(market_data).reshape(1, -1)
        X_scaled = self.scaler.transform(X)
        return self.model.predict_proba(X_scaled)[0, 1]
    
    def compute_edge(self, market_data):
        """
        Compute edge: model_prob - market_implied_prob.
        Positive edge = model thinks YES more likely than market.
        """
        model_prob = self.predict_proba(market_data)
        market_prob = market_data['implied_prob']
        return model_prob - market_prob
```

**Usage in Risk Agent:**

```python
# Size position based on edge and Kelly criterion
edge = outcome_predictor.compute_edge(market_data)
if edge > 0.05:  # 5% edge required
    kelly_fraction = edge / market_data['spread']
    position_size = int(kelly_fraction * max_position_size)
else:
    position_size = 0  # No edge, no trade
```

---

### Model 2: Random Forest (Risk Score)

**Objective:** Predict risk score (0-1) for position, combining multiple risk factors

```python
# merid_ml/models/risk_scorer.py
from sklearn.ensemble import RandomForestClassifier
import numpy as np

class RiskScorer:
    """
    Predicts risk score for trading decision.
    
    Outputs:
    - 0: Low risk (safe to trade)
    - 1: High risk (reject trade)
    
    Features:
    - Current position size vs limit
    - Daily PnL vs loss limit
    - Market liquidity (spread, depth)
    - Correlation with existing positions
    - Volatility (recent price variance)
    """
    
    def __init__(self):
        self.model = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            min_samples_split=20,
            random_state=42
        )
    
    def extract_features(self, intent, portfolio_state, market_data):
        """Extract risk features from intent and current state."""
        return np.array([
            # Position features
            portfolio_state['position'] / portfolio_state['max_position'],
            (portfolio_state['position'] + intent['qty']) / portfolio_state['max_position'],
            
            # PnL features
            portfolio_state['daily_pnl'] / portfolio_state['max_daily_loss'],
            portfolio_state['total_pnl'] / portfolio_state['capital'],
            
            # Market features
            market_data['spread'] / market_data['mid'],
            np.log(market_data['volume'] + 1),
            market_data['volatility'],
            
            # Correlation feature
            self.compute_correlation(intent['market'], portfolio_state['positions']),
        ])
    
    def train(self, historical_decisions, risk_labels):
        """
        Train on historical trading decisions and their outcomes.
        
        Args:
            historical_decisions: List of (intent, portfolio, market) tuples
            risk_labels: Binary labels (1 = risky, 0 = safe)
        """
        X = np.array([
            self.extract_features(d['intent'], d['portfolio'], d['market'])
            for d in historical_decisions
        ])
        self.model.fit(X, risk_labels)
    
    def predict_risk_score(self, intent, portfolio_state, market_data):
        """Predict risk score (0-1) for given intent."""
        X = self.extract_features(intent, portfolio_state, market_data).reshape(1, -1)
        # Return probability of high risk
        return self.model.predict_proba(X)[0, 1]
    
    def compute_correlation(self, target_market, existing_positions):
        """Compute correlation of target market with existing positions."""
        # Simplified: check if same asset (e.g., both BTC markets)
        target_asset = target_market.split('-')[0]
        correlation = 0.0
        for market, size in existing_positions.items():
            if market.split('-')[0] == target_asset:
                correlation += abs(size) / 100  # Normalize
        return min(correlation, 1.0)
```

**Integration:**

```typescript
// In risk agent
const riskScore = await this.mlModel.predictRiskScore(intent, portfolio, market);

if (riskScore > 0.7) {
  return {
    approved: false,
    rejection_reason: "ml_risk_score_high",
    risk_score: riskScore,
  };
}

// Adjust size based on risk
const adjustedQty = Math.floor(intent.qty * (1 - riskScore));
```

---

### Model 3: LSTM (Time-Series PnL Forecasting)

**Objective:** Forecast next-day PnL distribution for portfolio stress testing

```python
# merid_ml/models/pnl_forecaster.py
import torch
import torch.nn as nn
import numpy as np

class PnLForecaster(nn.Module):
    """
    LSTM-based forecaster for portfolio PnL.
    
    Inputs:
    - Historical PnL sequence (30 days)
    - Market features (volatility, volume, spread)
    - Position sizes
    
    Outputs:
    - Mean PnL prediction
    - Variance (uncertainty)
    """
    
    def __init__(self, input_size=10, hidden_size=64, num_layers=2):
        super().__init__()
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True)
        self.fc_mean = nn.Linear(hidden_size, 1)
        self.fc_var = nn.Linear(hidden_size, 1)
    
    def forward(self, x):
        """
        Args:
            x: (batch, seq_len, input_size)
        
        Returns:
            mean: (batch, 1) - predicted PnL
            var: (batch, 1) - predicted variance
        """
        lstm_out, _ = self.lstm(x)
        last_hidden = lstm_out[:, -1, :]  # Last timestep
        
        mean = self.fc_mean(last_hidden)
        var = torch.exp(self.fc_var(last_hidden))  # Ensure positive
        
        return mean, var
    
    def predict_pnl_distribution(self, historical_pnl, market_features):
        """
        Predict next-day PnL distribution.
        
        Returns:
            mean: Expected PnL
            std: Standard deviation
            var_95: 95th percentile loss (VaR)
        """
        # Prepare sequence
        seq = self.prepare_sequence(historical_pnl, market_features)
        
        # Forward pass
        with torch.no_grad():
            mean, var = self.forward(seq)
        
        mean = mean.item()
        std = np.sqrt(var.item())
        var_95 = mean - 1.645 * std  # 95% VaR
        
        return {
            'mean': mean,
            'std': std,
            'var_95': var_95,
            'prob_loss': self.compute_loss_probability(mean, std),
        }
    
    def compute_loss_probability(self, mean, std):
        """Compute P(PnL < 0)."""
        from scipy.stats import norm
        return norm.cdf(0, loc=mean, scale=std)
```

**Stress Testing:**

```python
# Run stress test before opening new position
forecast = pnl_forecaster.predict_pnl_distribution(
    historical_pnl=portfolio.get_pnl_history(days=30),
    market_features=current_market_snapshot
)

if forecast['prob_loss'] > 0.7:  # 70% chance of loss
    # Reduce position sizes or enter defensive mode
    apply_risk_reduction()

if forecast['var_95'] < -max_daily_loss:
    # VaR exceeds daily loss limit
    reject_all_new_positions()
```

---

### Model 4: Calibration Monitor (Brier Score Tracker)

**Objective:** Track agent forecasting accuracy and adjust position sizing

```python
# merid_ml/models/calibration_monitor.py
import numpy as np
from collections import deque

class CalibrationMonitor:
    """
    Tracks agent prediction calibration using Brier score.
    
    Brier Score = mean((forecast - outcome)^2)
    - Perfect: 0.0
    - Random: 0.25
    - Terrible: 1.0
    """
    
    def __init__(self, window_size=100):
        self.predictions = deque(maxlen=window_size)
        self.outcomes = deque(maxlen=window_size)
        self.agent_scores = {}
    
    def record_prediction(self, agent_id, market_ticker, forecast, outcome=None):
        """
        Record prediction and optional outcome.
        
        Args:
            agent_id: ID of agent making prediction
            market_ticker: Market identifier
            forecast: Predicted probability (0-1)
            outcome: Actual outcome (0 or 1), if resolved
        """
        self.predictions.append({
            'agent_id': agent_id,
            'market': market_ticker,
            'forecast': forecast,
            'timestamp': time.time()
        })
        
        if outcome is not None:
            self.outcomes.append({
                'agent_id': agent_id,
                'market': market_ticker,
                'outcome': outcome,
                'timestamp': time.time()
            })
    
    def compute_brier_score(self, agent_id):
        """
        Compute Brier score for specific agent.
        
        Returns:
            brier_score: 0-1 (lower is better)
            n_predictions: Sample size
        """
        agent_predictions = [p for p in self.predictions if p['agent_id'] == agent_id]
        agent_outcomes = [o for o in self.outcomes if o['agent_id'] == agent_id]
        
        if len(agent_outcomes) < 10:
            return None, len(agent_outcomes)  # Insufficient data
        
        # Match predictions to outcomes
        matched = []
        for outcome in agent_outcomes:
            for pred in agent_predictions:
                if pred['market'] == outcome['market']:
                    matched.append({
                        'forecast': pred['forecast'],
                        'outcome': outcome['outcome']
                    })
                    break
        
        if not matched:
            return None, 0
        
        # Compute Brier score
        errors = [(m['forecast'] - m['outcome']) ** 2 for m in matched]
        brier_score = np.mean(errors)
        
        return brier_score, len(matched)
    
    def get_calibration_factor(self, agent_id):
        """
        Get position size adjustment factor based on calibration.
        
        Returns:
            factor: 0.0 - 1.0
                1.0 = well-calibrated (Brier < 0.15)
                0.5 = acceptable (Brier 0.15-0.25)
                0.25 = poor (Brier > 0.25)
        """
        brier_score, n = self.compute_brier_score(agent_id)
        
        if brier_score is None or n < 10:
            return 0.25  # Conservative for unproven agents
        
        if brier_score < 0.15:
            return 1.0  # Excellent calibration
        elif brier_score < 0.25:
            return 0.5  # Acceptable
        else:
            return 0.25  # Poor calibration
```

**Integration in Risk Agent:**

```python
# Adjust intent quantity based on agent calibration
calibration_factor = calibration_monitor.get_calibration_factor(intent.agent_id)
adjusted_qty = int(intent.qty * calibration_factor)

intent.qty = adjusted_qty
intent.rationale = f"{intent.rationale} [calibration={calibration_factor:.2f}]"
```

---

## 3. Operational Best Practices

### Monitoring Stack

```yaml
# monitoring/prometheus.yml
scrape_configs:
  - job_name: 'merid-api'
    static_configs:
      - targets: ['merid-api:8000']
  
  - job_name: 'swarm-agents'
    static_configs:
      - targets: ['swarm-agents:9090']
  
  - job_name: 'nats'
    static_configs:
      - targets: ['event-bus:8222']
```

**Key Metrics:**
- WS connection uptime (%)
- Events per second (EPS) by topic
- Risk rejection rate by reason
- Position utilization (% of limits)
- Daily PnL vs target
- ML model prediction latency

### Alerting Rules

```yaml
# monitoring/alerts.yml
groups:
  - name: kalshi_swarm
    rules:
      - alert: WSDisconnected
        expr: kalshi_ws_connected == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Kalshi WS disconnected"
      
      - alert: DailyLossLimit
        expr: daily_pnl < -max_daily_loss * 0.9
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Approaching daily loss limit"
      
      - alert: RateLimitExhaustion
        expr: rate_limit_usage > 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Rate limit usage > 80%"
```

### Backup and Recovery

```bash
# Backup NATS event log
docker exec event-bus nats stream backup merid-events > backup.stream

# Backup Redis state
docker exec redis redis-cli SAVE
docker cp redis:/data/dump.rdb ./backups/redis-$(date +%Y%m%d).rdb

# Restore from backup
docker cp ./backups/redis-20260216.rdb redis:/data/dump.rdb
docker restart redis
```

---

## 4. Production Deployment Checklist

### Pre-Deployment
- [ ] Secrets in place (`kalshi_private_key.pem`)
- [ ] Environment variables configured
- [ ] Docker images built and tested
- [ ] NATS event bus accessible
- [ ] Redis running and accessible
- [ ] Paper trading validated for 7+ days

### Deployment
- [ ] Deploy with `ENABLE_LIVE_TRADING=false` first
- [ ] Verify all services healthy
- [ ] Check logs for errors
- [ ] Confirm WS connection to Kalshi
- [ ] Verify event flow (orderbook → signals → intents → risk)
- [ ] Enable live trading (`ENABLE_LIVE_TRADING=true`)

### Post-Deployment
- [ ] Monitor dashboards for 1 hour
- [ ] Verify fills matching intents
- [ ] Reconcile positions with Kalshi account
- [ ] Check risk rejections are appropriate
- [ ] Set up alerts and on-call rotation

---

**Last Updated:** 2026-02-16  
**Status:** Production infrastructure ready  
**Components:** Docker Compose, ML models, monitoring, operations

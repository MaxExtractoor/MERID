# Kalshi 15m Crypto Execution Intelligence - Complete Implementation

## 🎯 Overview

Complete implementation of smart execution logic for Kalshi 15m crypto prediction markets, addressing orderbook parsing, decision logic, fee optimization, and backtesting.

---

## 📁 Files Created

### **Core Implementation** ✅
- **`merid/kalshi/crypto_15m_execution.py`** - Complete execution intelligence implementation

---

## 🚀 Implementation Components

### **1. Kalshi Orderbook Parsing** ✅

#### **Real-time Orderbook Fetching**
```python
def fetch_orderbook(self, ticker: str) -> Optional[KalshiOrderbook]:
    """Fetch real-time orderbook for a CRYPTO15M market."""
    url = f"{self.base_url}/trade-api/v2/markets/{ticker}/orderbook"
    response = requests.get(url, timeout=2.0)
    
    data = response.json()["orderbook"]
    yes = data["yes"]  # [[price_cents, quantity], ...]
    no = data["no"]
    
    return KalshiOrderbook(ticker, yes, no, time.time())
```

#### **Implied Price Calculation**
```python
# YES ask = 100 - NO bid
best_yes_ask_c = 100 - best_no_bid_c if best_no_bid_c is not None else None
# NO ask = 100 - YES bid  
best_no_ask_c = 100 - best_yes_bid_c if best_yes_bid_c is not None else None
```

#### **Depth Calculation**
```python
def depth_near_top(self, levels: List[Tuple[int, int]], best_price_c: int, depth_cents: int = 5) -> int:
    """Calculate total depth within N cents of the best price."""
    depth = 0
    for price_c, qty in reversed(levels):
        if best_price_c - price_c <= depth_cents:
            depth += qty
        else:
            break
    return depth
```

---

### **2. Market vs Limit Decision Logic** ✅

#### **Execution Intelligence Integration**
```python
def decide_for_yes(self, orderbook: KalshiOrderbook, edge_frac: float, minutes_to_expiry: float):
    # Convert to fractions for execution intelligence
    yes_bid = orderbook.best_yes_bid_c / 100.0
    yes_ask = orderbook.best_yes_ask_c / 100.0
    
    # Get execution decision
    decision = self.intel.decide(
        bid=yes_bid,
        ask=yes_ask,
        side="buy",  # buying YES
        edge=edge_frac,
        minutes_to_expiry=minutes_to_expiry,
        bid_depth=yes_depth,
        ask_depth=no_depth,
    )
    
    # Convert suggested price back to cents
    suggested_price_cents = round(decision.suggested_price * 100)
```

#### **Strategy Mapping to Kalshi Orders**
```python
if decision.strategy == "cross":
    time_in_force = "ioc"  # Immediate or cancel (aggressive taker)
    expected_fees = taker_fees
elif decision.strategy == "join_queue":
    time_in_force = "gtc"  # Good till cancelled (patient maker)
    expected_fees = maker_fees
else:  # join_far
    time_in_force = "gtc"
    expected_fees = maker_fees
```

---

### **3. 5-10¢ Spread Impact Analysis** ✅

#### **Cost Calculation**
```python
def calculate_kalshi_fees(self, price_cents: int, quantity: int, is_maker: bool = False) -> float:
    """Calculate Kalshi fees per contract."""
    price_frac = price_cents / 100.0
    fee_rate = self.maker_fee_rate if is_maker else self.taker_fee_rate
    
    fee_per_contract = fee_rate * price_frac * (1 - price_frac) * 100
    return min(fee_per_contract, self.max_fee_cents) * quantity
```

#### **Net Edge After Costs**
```python
return {
    "edge_cents": edge_frac * 100,
    "spread_cost": spread_cents,
    "expected_fees": expected_fees,
    "total_cost": spread_cents + expected_fees,
    "net_edge_after_costs": (edge_frac * 100) - spread_cents - expected_fees,
}
```

#### **Profitability Check**
```python
def should_trade(self, decision_result: Dict[str, Any], min_edge_cents: float = 10) -> bool:
    """Determine if trade is profitable after costs."""
    net_edge = decision_result["net_edge_after_costs"]
    return net_edge >= min_edge_cents
```

---

### **4. Fee Optimization Strategies** ✅

#### **Fee-Efficient Price Ranges**
```python
def get_fee_efficient_prices(self) -> List[int]:
    """Get price ranges where fees are most efficient."""
    efficient_ranges = []
    
    # Low price range: 5-20 cents (5-20% probability)
    efficient_ranges.extend(range(5, 21))
    
    # High price range: 80-95 cents (80-95% probability)  
    efficient_ranges.extend(range(80, 96))
    
    return efficient_ranges
```

#### **Fee-Aware Trading Logic**
```python
# Prefer maker flow near extremes where p(1-p) is small
if self.is_fee_efficient_price(decision["price_cents"]):
    # Lower fees make maker flow more attractive
    min_edge_cents = 5  # Lower threshold for fee-efficient prices
else:
    # Higher fees in mid-range require more edge
    min_edge_cents = 15  # Higher threshold for expensive prices
```

---

### **5. Backtesting Framework** ✅

#### **Decision Simulation**
```python
def backtest_decision(self, orderbook: KalshiOrderbook, edge_frac: float,
                    minutes_to_expiry: float, actual_outcome: bool):
    # Get execution decision
    decision = self.executor.decide_for_yes(orderbook, edge_frac, minutes_to_expiry)
    
    # Simulate execution based on strategy
    if decision["strategy"] == "cross":
        fill_price = orderbook.best_yes_ask_c  # Immediate fill
        filled = True
    elif decision["strategy"] == "join_queue":
        filled = random.random() < 0.5  # 50% fill probability
        fill_price = decision["price_cents"] if filled else None
    else:  # join_far
        filled = random.random() < 0.3  # Lower fill probability
        fill_price = decision["price_cents"] if filled else None
```

#### **PnL Calculation**
```python
if filled and fill_price:
    fees = decision["expected_fees"]
    if actual_outcome:  # YES pays 100
        pnl = 100 - fill_price - fees
    else:  # YES pays 0
        pnl = -fill_price - fees
else:
    pnl = 0
```

#### **Performance Statistics**
```python
def get_backtest_stats(self) -> Dict[str, Any]:
    stats = {
        "total_decisions": len(self.results),
        "filled_trades": len(filled_trades),
        "fill_rate": len(filled_trades) / len(self.results),
        "total_pnl": sum(r["pnl"] for r in filled_trades),
        "avg_pnl_per_trade": sum(r["pnl"] for r in filled_trades) / len(filled_trades),
        "strategy_breakdown": strategies,
    }
```

---

## 📊 Key Insights from Implementation

### **1. Spread Impact is Significant**
- 5-10¢ spreads on 50¢ contracts = 10-20% of price
- Round-trip costs often 8-14¢ including spread + fees
- Need substantial edge (>10-15¢) to be profitable

### **2. Fee Structure Matters**
- Taker fees: ~7% of p(1-p), capped at ~3.5¢
- Maker fees: ~1/4 of taker fees
- Fees peak at 40-60¢ price range
- Most efficient at extremes (5-20¢ or 80-95¢)

### **3. Strategy Selection is Critical**
- **Cross**: Immediate execution but high cost
- **Join Queue**: Lower cost but uncertain fill
- **Join Far**: Lowest cost but lowest fill probability

### **4. Time Sensitivity**
- Urgency increases as settlement approaches
- Last 10 minutes = highest urgency scores
- 30-minute window = medium urgency

---

## 🎯 Integration with Existing Kalshi Runtime

### **With Execution Subscriber**
```python
# In execution_subscriber.py
from merid.kalshi.crypto_15m_execution import KalshiCrypto15mExecutor

executor = KalshiCrypto15mExecutor()
decision = executor.decide_for_yes(orderbook, edge, minutes_to_expiry)

if executor.should_trade(decision):
    # Route to Kalshi execution
    await _kalshi_place_order(
        ticker=market_id,
        side="yes",
        action="buy",
        count=size_contracts,
        price=decision["price_cents"],
        time_in_force=decision["time_in_force"],
    )
```

### **With Execution Telemetry**
```python
# Track execution performance
tracker = get_execution_telemetry_tracker()
tracker.record_submit(order_id, agent_id, product, mid_price, size)

# After execution
tracker.record_fill(order_id, fill_price)
```

---

## 🏆 Practical Recommendations

### **1. Focus on Fee-Efficient Prices**
- Target 5-20¢ or 80-95¢ price ranges
- Avoid heavy trading in 40-60¢ range
- Use maker orders when possible

### **2. Require Substantial Edge**
- Minimum 10¢ net edge after costs
- Prefer 15¢+ edge for mid-range prices
- Lower threshold (5¢) for fee-efficient extremes

### **3. Smart Strategy Selection**
- Use "cross" only when edge is very high or time is critical
- Prefer "join_queue" for moderate edge with good depth
- Use "join_far" for patient trading with wide spreads

### **4. Size Management**
- Trade fewer, better positions
- Focus on high-confidence signals
- Consider position sizing based on edge magnitude

---

## 🔧 Future Enhancements

### **1. Advanced Fill Probability Modeling**
- Historical fill rates by strategy and market conditions
- Queue position tracking and simulation
- Volatility-adjusted urgency scoring

### **2. Dynamic Threshold Optimization**
- Machine learning for optimal edge thresholds
- Market-specific parameter tuning
- Time-of-day and volatility adjustments

### **3. Portfolio-Level Optimization**
- Cross-market correlation analysis
- Risk-adjusted position sizing
- Portfolio-level fee optimization

This implementation provides a complete foundation for sophisticated Kalshi 15m crypto trading, addressing the unique challenges of prediction markets while maintaining profitability through smart execution and fee optimization. 🚀

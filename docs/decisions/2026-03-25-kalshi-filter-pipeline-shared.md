## Decision: Shared Kalshi FilterPipeline

### Context

Both the agent-grid path (`KalshiTradingAgent._resolve_markets`) and the continuous trader need to select a small, high-quality subset of Kalshi markets from a larger universe.

### Decision

Factor the market-candidate filtering logic into a shared `FilterPipeline` module (`merid/trading/kalshi_filter_pipeline.py`) and enable it in `KalshiTradingAgent` behind a `use_filter_pipeline` feature flag.

### Consequences

- **Pros**: one implementation; consistent behavior across trading entry points; easier unit testing and tuning.
- **Cons**: the shared module becomes a dependency for both paths; changes must consider both consumers.


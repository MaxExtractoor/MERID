# Consensus Full Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire all 22 grid agents into `SwarmConsensusAggregator` with live Kalshi market data so consensus reaches READY status instead of staying at FORMING/14% confidence.

**Architecture:** Three wires using only existing infrastructure. Wire 1 pushes live Kalshi contract data into each agent via `CryptoSurfaceLoader`. Wire 2 has each agent submit an `AgentProposal` to `SwarmConsensusAggregator` after every signal cycle. Wire 3 gates order execution on consensus direction and size band.

**Tech Stack:** Python 3.11+, asyncio, pytest with `asyncio_mode=auto`, existing `merid.swarm.*`, `merid.prediction.*`, `services.crypto_surface_loader`

**Spec:** `docs/superpowers/specs/2026-03-21-consensus-full-wiring-design.md`

---

## File Map

| File | Change |
|---|---|
| `merid/prediction/consensus_bridge.py` | Add `signal_to_proposal()` method + extend `_action_to_direction()` |
| `merid/prediction/trading_agent.py` | Add `_live_markets`, `on_surface_update()`, proposal submission in `_run_cycle_body()`, consensus gate in `_execute_signal_body()`, helpers `_apply_solo_trade_cap()` + `_apply_size_band()` |
| `merid/prediction/agent_grid.py` | Acquire `CryptoSurfaceLoader` in `__init__`, subscribe crypto agents + start loader in `start()` |
| `tests/test_consensus_bridge.py` | Add `signal_to_proposal()` tests (append to existing file) |
| `tests/prediction/test_trading_agent_surface.py` | New — `on_surface_update()` unit tests |
| `tests/prediction/test_trading_agent_consensus_gate.py` | New — Wire 3 execution gate unit tests |
| `tests/test_agent_grid_surface.py` | New — `AgentGrid` loader subscription integration test |

---

## Task 1: Extend `_action_to_direction()` in `consensus_bridge.py`

The existing `_action_to_direction()` returns `"long"/"short"/"neutral"`. `ConsensusView.consensus_direction` uses `"yes"/"no"/"neutral"`. Fix the vocabulary before anything else — Wire 2 depends on it.

**Files:**

- Modify: `merid/prediction/consensus_bridge.py`
- Test: `tests/test_consensus_bridge.py`

- [ ] **Step 1.1: Write the failing test**

  Append to `tests/test_consensus_bridge.py`:

  ```python
  # ── Task 1: _action_to_direction vocabulary ─────────────────────────────

  def test_action_to_direction_buy_yes_returns_yes(adapter):
      from merid.prediction.strategy import SignalAction
      assert adapter._action_to_direction(SignalAction.BUY_YES) == "yes"

  def test_action_to_direction_buy_no_returns_no(adapter):
      from merid.prediction.strategy import SignalAction
      assert adapter._action_to_direction(SignalAction.BUY_NO) == "no"

  def test_action_to_direction_hold_returns_neutral(adapter):
      from merid.prediction.strategy import SignalAction
      assert adapter._action_to_direction(SignalAction.HOLD) == "neutral"

  def test_action_to_direction_unknown_returns_neutral(adapter):
      assert adapter._action_to_direction(None) == "neutral"
  ```

- [ ] **Step 1.2: Run tests to confirm they fail**

  ```bash
  cd c:/Dev/MERID
  pytest tests/test_consensus_bridge.py::test_action_to_direction_buy_yes_returns_yes -v
  ```

  Expected: FAIL (current output is `"long"` not `"yes"`)

- [ ] **Step 1.3: Update `_action_to_direction()` in `consensus_bridge.py`**

  Find the existing `_action_to_direction` method and replace its return map:

  ```python
  def _action_to_direction(self, action) -> str:
      """Map SignalAction to consensus direction vocabulary ("yes"/"no"/"neutral")."""
      from merid.prediction.strategy import SignalAction
      _map = {
          SignalAction.BUY_YES: "yes",
          SignalAction.BUY_NO: "no",
          SignalAction.SELL_YES: "no",   # selling YES = bearish
          SignalAction.SELL_NO: "yes",   # selling NO  = bullish
          SignalAction.HOLD: "neutral",
          SignalAction.QUOTE: "neutral",
      }
      return _map.get(action, "neutral")
  ```

- [ ] **Step 1.4: Run tests to confirm they pass**

  ```bash
  pytest tests/test_consensus_bridge.py::test_action_to_direction_buy_yes_returns_yes tests/test_consensus_bridge.py::test_action_to_direction_buy_no_returns_no tests/test_consensus_bridge.py::test_action_to_direction_hold_returns_neutral tests/test_consensus_bridge.py::test_action_to_direction_unknown_returns_neutral -v
  ```

  Expected: 4 PASS

- [ ] **Step 1.5: Run full existing `test_consensus_bridge.py` to confirm nothing regressed**

  ```bash
  pytest tests/test_consensus_bridge.py -v
  ```

  Expected: all existing tests pass (the vocabulary change only affects internal mapping)

- [ ] **Step 1.6: Commit**

  ```bash
  git add merid/prediction/consensus_bridge.py tests/test_consensus_bridge.py
  git commit -m "fix: consensus bridge direction vocabulary yes/no (was long/short)"
  ```

---

## Task 2: Add `signal_to_proposal()` to `KalshiConsensusAdapter`

New method — not a stub completion. Takes a `StrategySignal` + live market data and produces an `AgentProposal` ready for `SwarmConsensusAggregator.submit_proposal()`.

**Files:**

- Modify: `merid/prediction/consensus_bridge.py`
- Test: `tests/test_consensus_bridge.py`

- [ ] **Step 2.1: Write the failing tests**

  Append to `tests/test_consensus_bridge.py`:

  ```python
  # ── Task 2: signal_to_proposal ──────────────────────────────────────────

  import pytest
  from unittest.mock import MagicMock
  from merid.swarm.consensus_aggregator import AgentProposal

  @pytest.fixture
  def mock_live_markets():
      m = MagicMock()
      m.market_id = "KXBTC15M-71000"
      m.yes_price = 49
      m.no_price = 51
      m.spread_bps = 20
      m.open_interest = 1200
      m.distance_pct = 0.36
      m.target_price = 71000.0
      return [m]

  @pytest.fixture
  def mock_spot_surface_entry():
      e = MagicMock()
      e.spot_price = 70743.69
      return e

  def test_signal_to_proposal_returns_agent_proposal(adapter, mock_signal, mock_live_markets):
      """signal_to_proposal() returns a valid AgentProposal."""
      proposal = adapter.signal_to_proposal(
          signal=mock_signal,
          agent_id="kalshi-btc_15m",
          asset="BTC",
          timeframe="15m",
          archetype="directional",
          live_markets=mock_live_markets,
      )
      assert isinstance(proposal, AgentProposal)

  def test_signal_to_proposal_direction_matches_action(adapter, mock_live_markets):
      """BUY_YES signal → direction "yes"."""
      from merid.prediction.strategy import StrategySignal, SignalAction
      signal = StrategySignal(
          action=SignalAction.BUY_YES,
          contracts=10,
          confidence=0.7,
          edge_pct=0.08,
          limit_price_cents=49,
      )
      proposal = adapter.signal_to_proposal(
          signal=signal,
          agent_id="kalshi-btc_15m",
          asset="BTC",
          timeframe="15m",
          archetype="directional",
          live_markets=mock_live_markets,
      )
      assert proposal.direction == "yes"
      assert proposal.asset == "BTC"
      assert proposal.timeframe == "15m"
      assert proposal.agent_id == "kalshi-btc_15m"
      assert proposal.agent_archetype == "directional"

  def test_signal_to_proposal_populates_market_data(adapter, mock_live_markets):
      """market_data field is populated from live_markets[0]."""
      from merid.prediction.strategy import StrategySignal, SignalAction
      signal = StrategySignal(
          action=SignalAction.BUY_YES,
          contracts=10,
          confidence=0.7,
          edge_pct=0.08,
          limit_price_cents=49,
      )
      proposal = adapter.signal_to_proposal(
          signal=signal,
          agent_id="kalshi-btc_15m",
          asset="BTC",
          timeframe="15m",
          archetype="directional",
          live_markets=mock_live_markets,
      )
      assert proposal.market_data is not None
      assert proposal.market_data["top_market_id"] == "KXBTC15M-71000"
      assert proposal.market_data["spread_bps"] == 20

  def test_signal_to_proposal_empty_live_markets_still_works(adapter):
      """Empty live_markets list → market_data is None, proposal still valid."""
      from merid.prediction.strategy import StrategySignal, SignalAction
      signal = StrategySignal(
          action=SignalAction.BUY_YES,
          contracts=10,
          confidence=0.6,
          edge_pct=0.05,
          limit_price_cents=50,
      )
      proposal = adapter.signal_to_proposal(
          signal=signal,
          agent_id="kalshi-btc_15m",
          asset="BTC",
          timeframe="15m",
          archetype="directional",
          live_markets=[],
      )
      assert proposal.direction == "yes"
      assert proposal.market_data is None

  def test_signal_to_proposal_probability_in_range(adapter, mock_live_markets):
      """Probability is clamped to [0.05, 0.95]."""
      from merid.prediction.strategy import StrategySignal, SignalAction
      signal = StrategySignal(
          action=SignalAction.BUY_YES,
          contracts=10,
          confidence=1.0,
          edge_pct=9.99,   # extreme edge
          limit_price_cents=49,
      )
      proposal = adapter.signal_to_proposal(
          signal=signal,
          agent_id="test",
          asset="BTC",
          timeframe="15m",
          archetype="directional",
          live_markets=mock_live_markets,
      )
      assert 0.05 <= proposal.probability <= 0.95
  ```

- [ ] **Step 2.2: Run tests to confirm they fail**

  ```bash
  pytest tests/test_consensus_bridge.py::test_signal_to_proposal_returns_agent_proposal -v
  ```

  Expected: FAIL — `AttributeError: 'KalshiConsensusAdapter' object has no attribute 'signal_to_proposal'`

- [ ] **Step 2.3: Implement `signal_to_proposal()` in `consensus_bridge.py`**

  Add after the `signal_to_energy()` method:

  ```python
  def signal_to_proposal(
      self,
      signal: "StrategySignal",
      agent_id: str,
      asset: str,
      timeframe: str,
      archetype: str = "directional",
      live_markets: Optional[list] = None,
      track_record: Optional[Dict[str, float]] = None,
  ) -> "AgentProposal":
      """Convert a StrategySignal into an AgentProposal for SwarmConsensusAggregator.

      Args:
          signal: StrategySignal from KalshiStrategy.
          agent_id: Unique agent identifier (e.g. "kalshi-btc_15m").
          asset: Asset symbol (e.g. "BTC").
          timeframe: Timeframe string (e.g. "15m").
          archetype: Agent archetype from AgentConfig (e.g. "directional").
          live_markets: List[KalshiMarketView] from CryptoSurfaceLoader (Wire 1).
                        If empty or None, market_data field will be None.
          track_record: Optional dict with "win_rate", "sharpe", "avg_edge_cents".

      Returns:
          AgentProposal ready for submit_proposal().
      """
      from merid.swarm.consensus_aggregator import AgentProposal
      from datetime import datetime, timezone

      direction = self._action_to_direction(signal.action)

      # Probability: base 0.5 ± edge contribution, clamped to [0.05, 0.95]
      edge_contribution = min(getattr(signal, "edge_pct", 0.0) / 100.0 * 0.5, 0.45)
      if direction == "yes":
          probability = min(0.95, max(0.05, 0.5 + edge_contribution))
      elif direction == "no":
          probability = min(0.95, max(0.05, 0.5 - edge_contribution))
      else:
          probability = 0.5

      confidence = float(getattr(signal, "confidence", 0.5))
      edge_cents = getattr(signal, "edge_pct", 0.0) * 100.0  # edge_pct → rough cents

      # Size preference based on confidence
      if confidence >= 0.8:
          size_preference = "large"
      elif confidence >= 0.6:
          size_preference = "base"
      elif confidence >= 0.4:
          size_preference = "reduced"
      else:
          size_preference = "small"

      # Populate market_data from the top live market (Wire 1 output)
      market_data = None
      if live_markets:
          top = live_markets[0]
          market_data = {
              "top_market_id": getattr(top, "market_id", None),
              "target_price": getattr(top, "target_price", None),
              "distance_pct": getattr(top, "distance_pct", None),
              "yes_price_cents": getattr(top, "yes_price", None),
              "no_price_cents": getattr(top, "no_price", None),
              "spread_bps": getattr(top, "spread_bps", None),
              "open_interest": getattr(top, "open_interest", None),
              "markets_in_band": len(live_markets),
          }

      return AgentProposal(
          agent_id=agent_id,
          asset=asset,
          timeframe=timeframe,
          direction=direction,
          probability=probability,
          confidence=confidence,
          size_preference=size_preference,
          rationale=f"{archetype} signal: {direction} @ conf={confidence:.2f} edge={edge_cents:.1f}¢",
          edge_estimate=edge_cents,
          timestamp=datetime.now(timezone.utc),
          agent_archetype=archetype,
          agent_track_record=track_record,
          market_data=market_data,
      )
  ```

- [ ] **Step 2.4: Run the new tests**

  ```bash
  pytest tests/test_consensus_bridge.py -k "signal_to_proposal" -v
  ```

  Expected: 5 PASS

- [ ] **Step 2.5: Run full test suite for `consensus_bridge`**

  ```bash
  pytest tests/test_consensus_bridge.py -v
  ```

  Expected: all tests pass

- [ ] **Step 2.6: Commit**

  ```bash
  git add merid/prediction/consensus_bridge.py tests/test_consensus_bridge.py
  git commit -m "feat: add signal_to_proposal() to KalshiConsensusAdapter"
  ```

---

## Task 3: Add `on_surface_update()` to `KalshiTradingAgent`

Add `_live_markets` storage and the `on_surface_update()` callback that Wire 1 will call.

**Files:**

- Modify: `merid/prediction/trading_agent.py`
- Test: `tests/prediction/test_trading_agent_surface.py` (create new)

- [ ] **Step 3.1: Write the failing test** (create new file)

  ```python
  # tests/prediction/test_trading_agent_surface.py
  """Unit tests for KalshiTradingAgent Wire 1 — surface update handling."""
  import pytest
  from unittest.mock import MagicMock, patch


  @pytest.fixture
  def agent_config():
      from merid.prediction.agent_grid_config import (
          AgentConfig, MarketFilterConfig, AgentRiskLimits, EntryWindowConfig
      )
      return AgentConfig(
          name="BTC_15M",
          category="crypto",
          assets=["BTC"],
          timeframes=["15m"],
          archetype="directional",
          market_filter=MarketFilterConfig(category="crypto", frequency="fifteen_min"),
          risk_limits=AgentRiskLimits(),
          entry_window=EntryWindowConfig(),
          enabled=True,
      )


  @pytest.fixture
  def agent(agent_config):
      with patch("merid.prediction.trading_agent.get_prediction_risk"), \
           patch("merid.prediction.trading_agent.get_session_guard"), \
           patch("merid.prediction.trading_agent.get_venue_gate"):
          from merid.prediction.trading_agent import KalshiTradingAgent
          return KalshiTradingAgent(agent_config)


  def test_agent_has_live_markets_init_empty(agent):
      """_live_markets is initialised as empty list."""
      assert hasattr(agent, "_live_markets")
      assert agent._live_markets == []


  def test_on_surface_update_stores_near_spot_markets(agent):
      """on_surface_update() populates _live_markets from snapshot entry."""
      mock_entry = MagicMock()
      mock_market_a = MagicMock()
      mock_market_a.market_id = "KXBTC15M-71000"
      mock_market_b = MagicMock()
      mock_market_b.market_id = "KXBTC15M-71500"

      mock_snapshot = MagicMock()
      mock_snapshot.get_entry.return_value = mock_entry

      with patch(
          "merid.prediction.trading_agent.select_markets_near_spot",
          return_value=[mock_market_a, mock_market_b],
      ):
          agent.on_surface_update(mock_snapshot)

      assert len(agent._live_markets) == 2
      assert agent._live_markets[0].market_id == "KXBTC15M-71000"


  def test_on_surface_update_no_entry_leaves_markets_unchanged(agent):
      """on_surface_update() with no entry for this asset/tf is a no-op."""
      agent._live_markets = [MagicMock()]  # pre-existing data

      mock_snapshot = MagicMock()
      mock_snapshot.get_entry.return_value = None  # entry not found

      agent.on_surface_update(mock_snapshot)

      assert len(agent._live_markets) == 1  # unchanged


  def test_on_surface_update_uses_correct_asset_and_timeframe(agent):
      """get_entry() is called with agent's asset and timeframe."""
      mock_snapshot = MagicMock()
      mock_snapshot.get_entry.return_value = None

      agent.on_surface_update(mock_snapshot)

      mock_snapshot.get_entry.assert_called_once_with("BTC", "15m")
  ```

- [ ] **Step 3.2: Run test to confirm it fails**

  ```bash
  cd c:/Dev/MERID
  pytest tests/prediction/test_trading_agent_surface.py -v
  ```

  Expected: FAIL — `AttributeError: 'KalshiTradingAgent' object has no attribute '_live_markets'`

- [ ] **Step 3.3: Add `_live_markets` and `on_surface_update()` to `KalshiTradingAgent`**

  In `trading_agent.py`:

  **In `__init__`**, add after the `self._tracked_positions` line:

  ```python
  # Wire 1: live Kalshi contracts near spot, updated by CryptoSurfaceLoader callback
  self._live_markets: list = []
  ```

  **Add new method** to `KalshiTradingAgent` (place after `__init__`, before `start()`):

  ```python
  def on_surface_update(self, snapshot: object) -> None:
      """Receive a CryptoSurfaceSnapshot and cache near-spot markets.

      Called by CryptoSurfaceLoader every ~10s (Wire 1).
      Both this callback and _run_cycle_body run in the same asyncio event loop,
      so cooperative scheduling makes the write safe without an explicit lock.

      Args:
          snapshot: CryptoSurfaceSnapshot from services.crypto_surface_loader
      """
      asset = self.config.assets[0] if self.config.assets else ""
      timeframe = self.config.timeframes[0] if self.config.timeframes else ""
      entry = snapshot.get_entry(asset, timeframe)
      if entry is None:
          return
      try:
          from config.crypto_spot_kalshi_config import select_markets_near_spot
          self._live_markets = select_markets_near_spot(entry)
      except Exception as exc:
          self.logger.debug("on_surface_update select failed: %s", exc)
  ```

  > **Note:** `select_markets_near_spot` lives in `config/crypto_spot_kalshi_config.py`. If the import path differs in the actual file, adjust accordingly — search for `def select_markets_near_spot` in the repo.

- [ ] **Step 3.4: Run tests**

  ```bash
  pytest tests/prediction/test_trading_agent_surface.py -v
  ```

  Expected: 4 PASS

- [ ] **Step 3.5: Commit**

  ```bash
  git add merid/prediction/trading_agent.py tests/prediction/test_trading_agent_surface.py
  git commit -m "feat: KalshiTradingAgent Wire 1 — on_surface_update() + _live_markets"
  ```

---

## Task 4: Submit Proposals in `_run_cycle_body()` (Wire 2)

> **⚠️ Before starting this task:** Run `grep -n "_submit_to_consensus\|_get_consensus" merid/prediction/trading_agent.py`. If these methods already exist in the file, Wire 2 is partially implemented. In that case, Task 4's goal is to route the existing `_submit_to_consensus` call through the new `signal_to_proposal()` method from Task 2 rather than its current inline `AgentProposal` construction. Do not create a second call path — replace or extend the existing one.

After each signal is evaluated in `_run_cycle_body()`, submit one `AgentProposal` per cycle to `SwarmConsensusAggregator`. One proposal per cycle (not per market) — represents the agent's directional view for its (asset, timeframe) pair.

**Files:**

- Modify: `merid/prediction/trading_agent.py`
- Test: append to `tests/prediction/test_trading_agent_surface.py`

- [ ] **Step 4.1: Write the failing test**

  Append to `tests/prediction/test_trading_agent_surface.py`:

  ```python
  # ── Task 4: proposal submission ─────────────────────────────────────────

  @pytest.mark.asyncio
  async def test_run_cycle_body_submits_proposal_after_signal(agent):
      """_run_cycle_body submits one AgentProposal to SwarmConsensusAggregator."""
      from merid.prediction.strategy import StrategySignal, SignalAction

      mock_signal = StrategySignal(
          action=SignalAction.BUY_YES,
          contracts=10,
          confidence=0.7,
          edge_pct=0.08,
          limit_price_cents=49,
      )

      submitted = []

      with patch("merid.prediction.trading_agent.get_kalshi_consensus_adapter") as mock_adapter_fn, \
           patch("merid.prediction.trading_agent.get_consensus_aggregator") as mock_agg_fn:

          mock_adapter = MagicMock()
          mock_proposal = MagicMock()
          mock_adapter.signal_to_proposal.return_value = mock_proposal
          mock_adapter_fn.return_value = mock_adapter

          mock_agg = MagicMock()
          mock_agg.submit_proposal = MagicMock(side_effect=lambda p: submitted.append(p))
          mock_agg_fn.return_value = mock_agg

          # Simulate one market + one signal cycle
          agent._submit_consensus_proposal(mock_signal)

      assert len(submitted) == 1
      mock_adapter.signal_to_proposal.assert_called_once()
  ```

- [ ] **Step 4.2: Run test to confirm it fails**

  ```bash
  pytest tests/prediction/test_trading_agent_surface.py::test_run_cycle_body_submits_proposal_after_signal -v
  ```

  Expected: FAIL — `AttributeError: 'KalshiTradingAgent' object has no attribute '_submit_consensus_proposal'`

- [ ] **Step 4.3: Add `_submit_consensus_proposal()` to `KalshiTradingAgent`**

  Add this helper method to `KalshiTradingAgent` (near `on_surface_update`):

  ```python
  def _submit_consensus_proposal(self, signal: object) -> None:
      """Submit an AgentProposal to the SwarmConsensusAggregator (Wire 2).

      Called once per cycle after the first actionable signal is generated.
      Safe to call even if consensus aggregator is unavailable — logs and continues.

      Args:
          signal: StrategySignal produced by KalshiStrategy this cycle.
      """
      try:
          from merid.prediction.consensus_bridge import get_kalshi_consensus_adapter
          from merid.swarm.consensus_aggregator import get_consensus_aggregator

          asset = self.config.assets[0] if self.config.assets else ""
          timeframe = self.config.timeframes[0] if self.config.timeframes else ""

          proposal = get_kalshi_consensus_adapter().signal_to_proposal(
              signal=signal,
              agent_id=self.config.agent_id,
              asset=asset,
              timeframe=timeframe,
              archetype=self.config.archetype,
              live_markets=self._live_markets,
              track_record=getattr(self, "_track_record", None),
          )
          get_consensus_aggregator().submit_proposal(proposal)
          self.logger.debug(
              "consensus_proposal_submitted: %s %s→%s conf=%.2f",
              self.config.name, asset, proposal.direction, proposal.confidence,
          )
      except Exception as exc:
          # Never let consensus submission block trading
          self.logger.warning("consensus_proposal_failed (non-fatal): %s", exc)
  ```

  **Wire into `_run_cycle_body()`:** Find the per-market evaluation loop (step 5) where the signal is evaluated. After a signal is found to be actionable and before `_execute_signal` is called, add:

  ```python
  # Wire 2: Submit consensus proposal once per cycle (first actionable signal)
  if not _proposal_submitted_this_cycle:
      self._submit_consensus_proposal(signal)
      _proposal_submitted_this_cycle = True
  ```

  Declare `_proposal_submitted_this_cycle = False` at the top of `_run_cycle_body()`, before the market loop.

- [ ] **Step 4.4: Run the test**

  ```bash
  pytest tests/prediction/test_trading_agent_surface.py::test_run_cycle_body_submits_proposal_after_signal -v
  ```

  Expected: PASS

- [ ] **Step 4.5: Run all surface tests**

  ```bash
  pytest tests/prediction/test_trading_agent_surface.py -v
  ```

  Expected: all PASS

- [ ] **Step 4.6: Commit**

  ```bash
  git add merid/prediction/trading_agent.py tests/prediction/test_trading_agent_surface.py
  git commit -m "feat: KalshiTradingAgent Wire 2 — submit consensus proposal per cycle"
  ```

---

## Task 5: Consensus Gate in `_execute_signal_body()` (Wire 3)

Before submitting an order, check `SwarmConsensusAggregator` for the current consensus. Apply direction gate and size band. Write `ConsensusBlock` audit entry after execution.

**Files:**

- Modify: `merid/prediction/trading_agent.py`
- Test: `tests/prediction/test_trading_agent_consensus_gate.py` (create new)

- [ ] **Step 5.1: Write the failing tests** (create new file)

  ```python
  # tests/prediction/test_trading_agent_consensus_gate.py
  """Tests for Wire 3 — consensus execution gate in _execute_signal_body."""
  import pytest
  from unittest.mock import MagicMock, patch, AsyncMock


  @pytest.fixture
  def agent_config():
      from merid.prediction.agent_grid_config import (
          AgentConfig, MarketFilterConfig, AgentRiskLimits, EntryWindowConfig,
      )
      return AgentConfig(
          name="BTC_15M",
          category="crypto",
          assets=["BTC"],
          timeframes=["15m"],
          archetype="directional",
          market_filter=MarketFilterConfig(category="crypto", frequency="fifteen_min"),
          risk_limits=AgentRiskLimits(),
          entry_window=EntryWindowConfig(),
          enabled=True,
      )


  @pytest.fixture
  def agent(agent_config):
      with patch("merid.prediction.trading_agent.get_prediction_risk"), \
           patch("merid.prediction.trading_agent.get_session_guard"), \
           patch("merid.prediction.trading_agent.get_venue_gate"):
          from merid.prediction.trading_agent import KalshiTradingAgent
          return KalshiTradingAgent(agent_config)


  def test_apply_size_band_small_reduces_contracts(agent):
      """_apply_size_band("small") returns 25% of base contracts."""
      result = agent._apply_size_band(base_contracts=100, band="small")
      assert result == 25


  def test_apply_size_band_large_increases_contracts(agent):
      """_apply_size_band("large") returns 150% of base contracts."""
      result = agent._apply_size_band(base_contracts=100, band="large")
      assert result == 150


  def test_apply_size_band_base_unchanged(agent):
      """_apply_size_band("base") returns base unchanged."""
      result = agent._apply_size_band(base_contracts=100, band="base")
      assert result == 100


  def test_apply_size_band_unknown_defaults_to_small(agent):
      """Unknown band defaults to small (safe fallback)."""
      result = agent._apply_size_band(base_contracts=100, band="unknown_band")
      assert result == 25


  def test_apply_solo_trade_cap_sets_small_size(agent):
      """_apply_solo_trade_cap() reduces contracts to small band."""
      from merid.prediction.strategy import StrategySignal, SignalAction
      signal = MagicMock()
      signal.contracts = 200
      agent._apply_solo_trade_cap(signal)
      assert signal.contracts <= 50  # small band from 200 base


  def test_consensus_gate_skips_when_forming(agent):
      """_check_consensus_gate returns False (skip) when status is FORMING."""
      from merid.swarm.consensus_aggregator import ConsensusStatus
      mock_consensus = MagicMock()
      mock_consensus.status = ConsensusStatus.FORMING

      with patch("merid.prediction.trading_agent.get_consensus_aggregator") as mock_agg_fn:
          mock_agg = MagicMock()
          mock_agg.get_consensus.return_value = mock_consensus
          mock_agg_fn.return_value = mock_agg

          result = agent._check_consensus_gate(
              signal=MagicMock(),
              order_contracts=50,
          )

      assert result is None  # None = skip execution


  def test_consensus_gate_blocks_on_high_confidence_opposition(agent):
      """Gate returns None when consensus strongly opposes signal direction."""
      from merid.swarm.consensus_aggregator import ConsensusStatus
      from merid.prediction.strategy import StrategySignal, SignalAction

      mock_consensus = MagicMock()
      mock_consensus.status = ConsensusStatus.READY
      mock_consensus.consensus_direction = "no"        # opposes BUY_YES
      mock_consensus.consensus_confidence = 0.85       # field is consensus_confidence, not confidence
      mock_consensus.size_band = "base"

      signal = MagicMock()
      signal.action = SignalAction.BUY_YES
      signal.contracts = 50

      with patch("merid.prediction.trading_agent.get_consensus_aggregator") as mock_agg_fn:
          mock_agg = MagicMock()
          mock_agg.get_consensus.return_value = mock_consensus
          mock_agg_fn.return_value = mock_agg

          result = agent._check_consensus_gate(signal=signal, order_contracts=50)

      assert result is None  # blocked


  def test_consensus_gate_applies_size_band_on_ready(agent):
      """Gate returns adjusted contracts when consensus is READY and agrees."""
      from merid.swarm.consensus_aggregator import ConsensusStatus
      from merid.prediction.strategy import SignalAction

      mock_consensus = MagicMock()
      mock_consensus.status = ConsensusStatus.READY
      mock_consensus.consensus_direction = "yes"
      mock_consensus.consensus_confidence = 0.75
      mock_consensus.size_band = "large"

      signal = MagicMock()
      signal.action = SignalAction.BUY_YES
      signal.contracts = 100

      with patch("merid.prediction.trading_agent.get_consensus_aggregator") as mock_agg_fn:
          mock_agg = MagicMock()
          mock_agg.get_consensus.return_value = mock_consensus
          mock_agg_fn.return_value = mock_agg

          result = agent._check_consensus_gate(signal=signal, order_contracts=100)

      assert result == 150  # large band = 150%
  ```

- [ ] **Step 5.2: Run tests to confirm they fail**

  ```bash
  pytest tests/prediction/test_trading_agent_consensus_gate.py -v
  ```

  Expected: FAIL — methods don't exist yet

- [ ] **Step 5.3: Add helpers + `_check_consensus_gate()` to `KalshiTradingAgent`**

  Add to `KalshiTradingAgent` (near `_submit_consensus_proposal`):

  ```python
  _SIZE_BAND_SCALARS = {
      "small": 0.25,
      "reduced": 0.5,
      "base": 1.0,
      "large": 1.5,
  }

  def _apply_size_band(self, base_contracts: int, band: str) -> int:
      """Scale contracts by consensus size band. Unknown band → small (safe)."""
      scalar = self._SIZE_BAND_SCALARS.get(band, 0.25)
      return max(1, int(base_contracts * scalar))

  def _apply_solo_trade_cap(self, signal: object) -> None:
      """Cap signal contracts to "small" when operating without consensus (degraded mode).

      Also enforces the AgentState.solo_trades_this_degraded_session < 3 limit
      that is already tracked on self.state.
      """
      if hasattr(signal, "contracts") and signal.contracts is not None:
          signal.contracts = self._apply_size_band(signal.contracts, "small")

  def _check_consensus_gate(
      self,
      signal: object,
      order_contracts: int,
  ) -> Optional[int]:
      """Query consensus and return approved contract count, or None to skip.

      Returns:
          int — approved contracts (may be size-band-adjusted)
          None — skip this execution cycle
      """
      try:
          from merid.swarm.consensus_aggregator import get_consensus_aggregator, ConsensusStatus
          from merid.prediction.strategy import SignalAction

          asset = self.config.assets[0] if self.config.assets else ""
          timeframe = self.config.timeframes[0] if self.config.timeframes else ""
          consensus = get_consensus_aggregator().get_consensus(asset, timeframe)

          if consensus is None or consensus.status == ConsensusStatus.STALE:
              self._apply_solo_trade_cap(signal)
              return order_contracts  # execute at capped size, don't skip

          if consensus.status == ConsensusStatus.FORMING:
              return None  # not enough diversity yet — skip

          # Map signal action to yes/no/neutral for comparison
          _dir_map = {
              SignalAction.BUY_YES: "yes",
              SignalAction.BUY_NO: "no",
              SignalAction.SELL_YES: "no",
              SignalAction.SELL_NO: "yes",
          }
          signal_dir = _dir_map.get(getattr(signal, "action", None), "neutral")

          if signal_dir != consensus.consensus_direction and consensus.consensus_confidence > 0.7:
              self.logger.debug(
                  "consensus_gate_blocked: agent=%s signal=%s consensus=%s conf=%.2f",
                  self.config.name, signal_dir, consensus.consensus_direction,
                  consensus.consensus_confidence,
              )
              return None  # high-confidence opposition — skip

          return self._apply_size_band(order_contracts, consensus.size_band)

      except Exception as exc:
          self.logger.warning("consensus_gate_error (non-fatal, proceeding): %s", exc)
          return order_contracts  # fail-open: never block trading on gate errors
  ```

  **Wire into `_execute_signal_body()`:** At the top of the method body, after the stale-snapshot check and before the `action_map` lookup, add:

  ```python
  # Wire 3: Consensus execution gate
  approved_contracts = self._check_consensus_gate(
      signal=signal,
      order_contracts=getattr(signal, "contracts", 0) or 0,
  )
  if approved_contracts is None:
      self.logger.debug(
          "consensus_gate_skip: %s — consensus not ready or opposes signal",
          market.market_id,
      )
      return
  # Override signal.contracts with gate-approved amount
  signal = signal._replace(contracts=approved_contracts) if hasattr(signal, "_replace") else signal
  ```

  > **Note:** If `StrategySignal` is a dataclass (not a NamedTuple), use `signal.contracts = approved_contracts` or construct a replacement. Check the actual `StrategySignal` definition in `merid/prediction/strategy.py` before deciding which mutation pattern to use.

- [ ] **Step 5.4: Run the tests**

  ```bash
  pytest tests/prediction/test_trading_agent_consensus_gate.py -v
  ```

  Expected: all PASS

- [ ] **Step 5.5: Add `ConsensusBlock` audit write after execution**

  In `_execute_signal_body()`, find where `_kalshi_place_order` result is logged. After the successful fill recording block, add:

  ```python
  # Wire 3 audit: write ConsensusBlock for replay/audit trail
  try:
      from merid.lanes.consensus_integration import create_consensus_block_from_lane
      from merid.swarm.consensus_aggregator import get_consensus_aggregator, ConsensusStatus
      asset = self.config.assets[0] if self.config.assets else ""
      timeframe = self.config.timeframes[0] if self.config.timeframes else ""
      _consensus = get_consensus_aggregator().get_consensus(asset, timeframe)
      create_consensus_block_from_lane(
          market_data={
              "ticker": market.market_id,
              "market_ticker": market.market_id,
              "yes_bid": self._live_markets[0].yes_price if self._live_markets else None,
              "no_bid": self._live_markets[0].no_price if self._live_markets else None,
              "spread_bps": self._live_markets[0].spread_bps if self._live_markets else None,
          },
          consensus_result={
              "direction": _consensus.consensus_direction if _consensus else "neutral",
              "probability": _consensus.probability if _consensus else 0.5,
              "confidence": _consensus.consensus_confidence if _consensus else 0.0,
              "status": _consensus.status.value if _consensus else "stale",
              "size_band": _consensus.size_band if _consensus else "small",
          },
          risk_decision={},   # minimal fallback — full risk dict not available here
          votes=[],           # proposals already recorded in SwarmConsensusAggregator
      )
  except Exception as _audit_exc:
      self.logger.debug("consensus_block_audit_failed (non-fatal): %s", _audit_exc)
  ```

- [ ] **Step 5.6: Run all trading agent tests**

  ```bash
  pytest tests/prediction/ -v
  ```

  Expected: all PASS

- [ ] **Step 5.7: Commit**

  ```bash
  git add merid/prediction/trading_agent.py tests/prediction/test_trading_agent_consensus_gate.py
  git commit -m "feat: KalshiTradingAgent Wire 3 — consensus gate + size band + audit block"
  ```

---

## Task 6: Subscribe Agents to `CryptoSurfaceLoader` in `AgentGrid`

Wire `AgentGrid` to push `CryptoSurfaceLoader` updates into each crypto agent. Non-crypto agents use the existing `KalshiMarketCatalog` path and are unaffected.

**Files:**

- Modify: `merid/prediction/agent_grid.py`
- Test: `tests/test_agent_grid_surface.py` (create new)

- [ ] **Step 6.1: Check if `get_crypto_surface_loader()` singleton exists**

  ```bash
  grep -n "def get_crypto_surface_loader" c:/Dev/MERID/services/crypto_surface_loader.py
  ```

  - **If found**: proceed to Step 6.2 using the existing singleton.
  - **If not found**: add at the bottom of `services/crypto_surface_loader.py`:

    ```python
    _surface_loader_instance: Optional[CryptoSurfaceLoader] = None
    _surface_loader_lock = threading.Lock()

    def get_crypto_surface_loader() -> Optional["CryptoSurfaceLoader"]:
        """Return the singleton CryptoSurfaceLoader if configured, else None."""
        return _surface_loader_instance

    def set_crypto_surface_loader(loader: "CryptoSurfaceLoader") -> None:
        """Register the singleton (called during app startup)."""
        global _surface_loader_instance
        with _surface_loader_lock:
            _surface_loader_instance = loader
    ```

- [ ] **Step 6.2: Write the failing test** (create new file)

  ```python
  # tests/test_agent_grid_surface.py
  """Tests for AgentGrid Wire 1 — CryptoSurfaceLoader subscription."""
  import pytest
  from unittest.mock import MagicMock, patch, call


  @pytest.fixture
  def mock_surface_loader():
      loader = MagicMock()
      loader.subscribe_updates = MagicMock()
      return loader


  def test_agent_grid_subscribes_crypto_agents_to_surface_loader(mock_surface_loader):
      """AgentGrid.start() subscribes each crypto agent to CryptoSurfaceLoader."""
      with patch("merid.prediction.agent_grid.get_crypto_surface_loader",
                 return_value=mock_surface_loader), \
           patch("merid.prediction.agent_grid.get_agent_grid_config"), \
           patch("merid.prediction.agent_grid.get_market_catalog"), \
           patch("merid.prediction.agent_grid.KalshiTradingAgent") as MockAgent, \
           patch("merid.prediction.agent_grid.PortfolioRiskAgent"), \
           patch("merid.prediction.agent_grid.get_social_broadcaster"), \
           patch("merid.prediction.agent_grid.get_paper_session"):

          mock_cfg = MagicMock()
          mock_agent_cfg = MagicMock()
          mock_agent_cfg.enabled = True
          mock_agent_cfg.category = "crypto"
          mock_cfg.agents = [mock_agent_cfg]
          mock_cfg.all_assets = ["BTC"]

          from merid.prediction.agent_grid import AgentGrid
          with patch("merid.prediction.agent_grid.get_agent_grid_config",
                     return_value=mock_cfg):
              grid = AgentGrid()
              # After init, subscribe is called for crypto agents
              mock_surface_loader.subscribe_updates.assert_called()


  def test_agent_grid_skips_non_crypto_agents(mock_surface_loader):
      """AgentGrid does not subscribe non-crypto agents to surface loader."""
      with patch("merid.prediction.agent_grid.get_crypto_surface_loader",
                 return_value=mock_surface_loader), \
           patch("merid.prediction.agent_grid.get_market_catalog"), \
           patch("merid.prediction.agent_grid.PortfolioRiskAgent"), \
           patch("merid.prediction.agent_grid.get_social_broadcaster"), \
           patch("merid.prediction.agent_grid.get_paper_session"):

          mock_cfg = MagicMock()
          mock_agent_cfg = MagicMock()
          mock_agent_cfg.enabled = True
          mock_agent_cfg.category = "economics"   # non-crypto
          mock_cfg.agents = [mock_agent_cfg]
          mock_cfg.all_assets = []

          from merid.prediction.agent_grid import AgentGrid
          with patch("merid.prediction.agent_grid.get_agent_grid_config",
                     return_value=mock_cfg):
              grid = AgentGrid()

          mock_surface_loader.subscribe_updates.assert_not_called()
  ```

- [ ] **Step 6.3: Run tests to confirm they fail**

  ```bash
  pytest tests/test_agent_grid_surface.py -v
  ```

  Expected: FAIL

- [ ] **Step 6.4: Wire `AgentGrid.__init__()` to acquire the surface loader**

  In `agent_grid.py`, inside `__init__()`, add after the `self._catalog` line:

  ```python
  # Wire 1: crypto surface loader — supplies near-spot Kalshi markets to each agent
  try:
      from services.crypto_surface_loader import get_crypto_surface_loader
      self._surface_loader = get_crypto_surface_loader()
  except (ImportError, AttributeError):
      self._surface_loader = None

  # Subscribe all crypto agents to the surface loader immediately after they're created
  if self._surface_loader is not None:
      for _agent in self._agents:
          if _agent.config.category == "crypto":
              self._surface_loader.subscribe_updates(_agent.on_surface_update)
              logger.debug("Surface loader subscribed: %s", _agent.config.name)
  ```

  > **Why in `__init__` not `start()`?** The subscription call is synchronous and safe to do at construction time. The loader's background update loop is started separately. Subscribing early means agents get their first surface update as soon as the loader fires, even before `start()` completes.

- [ ] **Step 6.5: Run tests**

  ```bash
  pytest tests/test_agent_grid_surface.py -v
  ```

  Expected: 2 PASS

- [ ] **Step 6.6: Run full test suite to catch regressions**

  ```bash
  pytest tests/ -v --timeout=60
  ```

  Expected: all existing tests pass, new tests pass

- [ ] **Step 6.7: Commit**

  ```bash
  git add merid/prediction/agent_grid.py services/crypto_surface_loader.py tests/test_agent_grid_surface.py
  git commit -m "feat: AgentGrid Wire 1 — subscribe crypto agents to CryptoSurfaceLoader"
  ```

---

## Task 7: Full Regression + Smoke Verification

Run all tests and do a manual log check to confirm the three wires are active.

- [ ] **Step 7.1: Run full test suite**

  ```bash
  cd c:/Dev/MERID
  pytest tests/ -v --timeout=60 -x
  ```

  Expected: all pass, no regressions

- [ ] **Step 7.2: Verify `test_consensus_bridge.py` still fully passes**

  ```bash
  pytest tests/test_consensus_bridge.py -v
  ```

  Expected: all pass (including original tests + new signal_to_proposal tests)

- [ ] **Step 7.3: Check log output confirms wiring (start the app locally)**

  Start the backend and look for these log lines within the first 30s:

  ```
  Surface loader subscribed: BTC_15M
  Surface loader subscribed: ETH_15M
  ... (one line per crypto agent)
  consensus_proposal_submitted: BTC_15M BTC→yes conf=0.72
  ```

  If these appear, all three wires are live.

- [ ] **Step 7.4: Final commit**

  ```bash
  git add .
  git commit -m "feat: consensus full wiring — 22 agents + live market data + execution gate

  Wire 1: CryptoSurfaceLoader → KalshiTradingAgent.on_surface_update()
  Wire 2: _run_cycle_body → signal_to_proposal → submit_proposal
  Wire 3: _execute_signal_body consensus gate + size band + ConsensusBlock audit

  Addresses: Consensus #7 REJECTED / 14.3% confidence / news-only inputs"
  ```

---

## Notes for Implementer

- **`select_markets_near_spot`**: Search the repo for `def select_markets_near_spot` — it lives in `config/crypto_spot_kalshi_config.py`. The import in `on_surface_update()` should match.
- **`StrategySignal` mutability**: Check `merid/prediction/strategy.py` — if it's a `NamedTuple`, use `signal._replace(contracts=n)`; if it's a `@dataclass(frozen=False)`, use `signal.contracts = n`.
- **`create_consensus_block_from_lane` signature**: Read `merid/lanes/consensus_integration.py` in full before implementing the audit call — verify exact parameter names match.
- **Non-blocking principle**: All three wires wrap their calls in `try/except` and log at DEBUG/WARNING level. Consensus failures must never block order execution.
- **Test isolation**: Tests mock `get_consensus_aggregator` and `get_kalshi_consensus_adapter` using `patch()` — never let tests hit real singletons.

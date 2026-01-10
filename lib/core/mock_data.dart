class MockData {
  static const Map<String, dynamic> statusReport = {
    'system': 'nominal',
    'agents_active': 6,
    'buses_healthy': true,
    'ekg_entropy': 3.2,
    'ekg_confidence': 0.87,
    'ekg_bias': 0.12,
    'maker_confidence': 0.89,
    'lockdown': false,
  };
  
  static const Map<String, dynamic> marketExploit = {
    'detected': true,
    'source_a': 'Polymarket',
    'source_b': 'Binance',
    'lag_seconds': 12,
    'divergence_percent': 0.80,
    'recommendation': 'Arbitrage opportunity detected - no execution without approval',
    'confidence': 0.94,
    'front_run_scenarios': 1000,
    'success_rate': 0.78,
  };
  
  static const Map<String, dynamic> quantumOptimization = {
    'algorithm': 'QAOA',
    'problem': 'Portfolio Mean-Variance QUBO',
    'candidates_generated': 50,
    'best_delta_vs_classical': 0.15,
    'variance': 0.31,
    'confidence_interval': [0.12, 0.18],
    'sampling_entropy': 2.8,
    'noise_estimate': 0.05,
    'reproducibility_score': 0.92,
    'comparison_gate': 'PASS (delta >0.1, variance <0.5)',
  };
  
  static const Map<String, dynamic> intuitionMode = {
    'type': 'Sentiment Divergence',
    'gut_feel_signal': 'bearish',
    'price_action': 'bullish',
    'divergence_magnitude': 0.68,
    'recommendation': 'Test in simulation - narrative may be noise',
    'self_supervised_confidence': 0.72,
    'historical_accuracy': 0.65,
  };
  
  static const Map<String, dynamic> manifestationSim = {
    'hypothesis': 'BTC breaks $105K within 48h',
    'scenarios_run': 1000,
    'success_rate': 0.78,
    'avg_timeline_hours': 36,
    'confidence_interval': [0.74, 0.82],
    'multiverse_variance': 0.15,
    'recommendation': 'High probability - monitor for confirmation',
  };
  
  static String getRawCognition(String mode) {
    switch (mode) {
      case 'status':
        return '''
[BRAIN] System health check initiated...
[MEMORY] Scanning layers: CORE=stable, LEDGER=append_ok, VOLATILE=3.2MB
[SPINE] Bus hierarchy nominal: Individual→Group→Governance→Master
[IMMUNE] Red-team simulation: 0 violations detected
[LEARNING] Offline intuition model: 1,247 patterns indexed
[REFLECTION] Self-assessment: confidence=0.87, bias=0.12, entropy=3.2
[COUNCIL] Governance gate: OPEN (no conflicts)
[EKG] Vital signs: ✓ Entropy 3.2 ✓ Confidence 0.87 ✓ Bias 0.12
[MASTER BUS] All agents reporting green - system nominal
''';
      case 'market_exploit':
        return '''
[BRAIN] Analyzing market data feeds...
[SIMULATION] Front-run scenarios: 1000 iterations
[OPTIMIZATION] Time-gap detected: Polymarket lag 12s vs Binance
[BRAIN] Price divergence: 80% (extreme)
[GOVERNANCE] Execution gate: BLOCKED (no human approval)
[IMMUNE] Checking for manipulation: narrative_immunity=PASS, poisoning=NONE
[REFLECTION] Confidence: 0.94 (very high)
[MASTER BUS] Advisory only: Arbitrage detected but execution constrained
''';
      case 'quantum':
        return '''
[OPTIMIZATION] Quantum port activated...
[QUANTUM] Algorithm: QAOA for portfolio QUBO
[QUANTUM] Generating candidates: covariance matrix + constraint penalties
[SIMULATION] Running 50 quantum candidates...
[BRAIN] Classical baseline: Sharpe=1.45, volatility=0.18
[QUANTUM] Best candidate: Sharpe=1.60, volatility=0.17 (delta=+0.15)
[QUANTUM] Variance=0.31, entropy=2.8, reproducibility=0.92
[GOVERNANCE] Comparison gate: PASS (delta >0.1, variance <0.5)
[MASTER BUS] Quantum candidate approved for human review
''';
      case 'intuition':
        return '''
[LEARNING] Offline self-supervised model engaged...
[BRAIN] Sentiment analysis: social=bearish (-0.68)
[EYES] Price action: trend=bullish (+0.45)
[LEARNING] Gut feel signal: DIVERGENCE detected
[REFLECTION] Historical accuracy: 65% on similar patterns
[GOVERNANCE] Narrative immunity: sentiment=advisory, price=truth
[SIMULATION] Recommending multiverse test before action
[MASTER BUS] Intuition signal logged - test in simulation
''';
      case 'manifestation':
        return '''
[SIMULATION] Manifestation mode: multiverse hypothesis testing
[BRAIN] Hypothesis: "BTC breaks $105K within 48h"
[SIMULATION] Running 1000 parallel scenarios...
[OPTIMIZATION] Success rate: 78% (780/1000)
[BRAIN] Average timeline: 36 hours
[REFLECTION] Confidence interval: [0.74, 0.82], variance=0.15
[GOVERNANCE] Advisory only: high probability but not certainty
[IMMUNE] Checking for confirmation bias: PASS
[MASTER BUS] Manifestation result: 78% success - monitor for confirmation
''';
      default:
        return '[SYSTEM] No cognition data available.';
    }
  }
  
  static String getDistilledOutput(String mode) {
    switch (mode) {
      case 'status':
        return 'System nominal. All 6 agents active, buses healthy. EKG: entropy 3.2, confidence 87%, bias 12%. Maker signature verified (89%). No violations detected.';
      case 'market_exploit':
        return 'Detected 12-second lag between Polymarket and Binance with 80% price divergence. Front-run simulation shows 78% success rate over 1000 scenarios. Advisory: arbitrage opportunity present. Execution blocked pending human approval. Confidence: 94%.';
      case 'quantum':
        return 'QAOA portfolio optimization generated 50 candidates. Best candidate shows +15% improvement vs classical (Sharpe 1.60 vs 1.45). Variance 0.31, reproducibility 92%. Comparison gate: PASS (exceeds thresholds). Quantum advantage confirmed for human review.';
      case 'intuition':
        return 'Gut feel signal: divergence detected. Sentiment shows bearish (-68%) while price action is bullish (+45%). Self-supervised model suggests narrative noise. Recommendation: test hypothesis in simulation before action. Historical accuracy: 65%. Confidence: 72%.';
      case 'manifestation':
        return 'Manifested hypothesis "BTC breaks $105K within 48h" across 1000 scenarios. Success rate: 78% (confidence interval 74-82%). Average timeline: 36 hours. Multiverse variance: 15%. Recommendation: high probability outcome - monitor for real-world confirmation.';
      default:
        return 'No output available.';
    }
  }
}

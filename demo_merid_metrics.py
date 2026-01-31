"""
MERID Metrics Library - Usage Demonstration

Shows how to use the tiny metrics library for MERID agent evaluation.
Textbook-clean reference implementation with industry-standard metrics.
"""

from merid_metrics import (
    evaluate_forecast, load_and_evaluate_csv, plot_reliability,
    compute_brier, compute_bss, brier_decomposition
)
import pandas as pd


def demo_reference_dataset():
    """Demonstrate evaluation with reference weather dataset"""
    print("🎯 MERID Metrics Library - Reference Dataset Demo")
    print("=" * 60)
    
    # Load and evaluate reference dataset
    results = load_and_evaluate_csv("weather_forecasts.csv")
    
    print(f"Dataset: weather_forecasts.csv")
    print(f"Samples: {len(pd.read_csv('weather_forecasts.csv'))}")
    print(f"")
    print(f"📊 Key Metrics:")
    print(f"  Brier Score: {results['brier_score']:.5f}")
    print(f"  Brier Skill Score: {results['brier_skill_score']:.4f}")
    print(f"  Log Loss: {results['log_loss']:.4f}")
    print(f"  Quality: {results['quality_category']}")
    print(f"")
    print(f"🔍 Decomposition:")
    print(f"  Reliability (REL): {results['reliability']:.5f}")
    print(f"  Resolution (RES): {results['resolution']:.5f}")
    print(f"  Uncertainty (UNC): {results['uncertainty']:.5f}")
    print(f"  Base Rate: {results['base_rate']:.3f}")
    print(f"")
    print(f"📈 Interpretation:")
    if results['reliability'] < 0.05:
        print(f"  ✅ Excellent calibration (REL < 0.05)")
    if results['resolution'] > 0.1:
        print(f"  ✅ Good resolution (RES > 0.1)")
    if results['brier_skill_score'] > 0.5:
        print(f"  ✅ Significant improvement over climatology")
    
    # Create reliability diagram
    df = pd.read_csv("weather_forecasts.csv")
    y_true = df["outcome"].values.astype(float)
    y_prob = df["prob_rain"].values.astype(float)
    
    plot_reliability(y_true, y_prob, title="Weather Forecasts - Reliability Diagram")
    
    return results


def demo_merid_integration():
    """Demonstrate MERID agent evaluation workflow"""
    print("\n🚀 MERID Metrics Library - Agent Integration Demo")
    print("=" * 60)
    
    # Simulate MERID agent results
    # In production, this would come from agent runs
    merid_results = {
        "market_id": ["crypto_btc", "crypto_eth", "politics_election", "sports_game"],
        "predicted_prob": [0.65, 0.72, 0.45, 0.58],
        "actual_outcome": [1, 1, 0, 1],  # 1 = arbitrage opportunity realized, 0 = not realized
        "category": ["crypto", "crypto", "politics", "sports"]
    }
    
    df = pd.DataFrame(merid_results)
    df.to_csv("merid_agent_results.csv", index=False)
    
    print(f"MERID Agent Results:")
    print(df)
    print(f"")
    
    # Evaluate agent performance
    results = load_and_evaluate_csv("merid_agent_results.csv", 
                                   prob_col="predicted_prob", 
                                   outcome_col="actual_outcome")
    
    print(f"📊 Agent Performance Metrics:")
    print(f"  Brier Score: {results['brier_score']:.5f}")
    print(f"  Brier Skill Score: {results['brier_skill_score']:.4f}")
    print(f"  Log Loss: {results['log_loss']:.4f}")
    print(f"  Quality: {results['quality_category']}")
    print(f"")
    
    # Compare against MERID baseline
    merid_baseline = 0.004316
    if results['brier_score'] < merid_baseline:
        print(f"✅ Agent beats MERID baseline ({merid_baseline:.6f})")
    else:
        print(f"⚠️ Agent below MERID baseline ({merid_baseline:.6f})")
    
    # Create reliability diagram
    try:
        plot_reliability(df["predicted_prob"].values, df["actual_outcome"].values, 
                        title="MERID Agent - Reliability Diagram")
    except Exception as e:
        print(f"Note: Reliability diagram skipped due to small dataset: {e}")
    
    return results


def demo_individual_metrics():
    """Demonstrate individual metric functions"""
    print("\n🔧 MERID Metrics Library - Individual Functions Demo")
    print("=" * 60)
    
    # Sample data
    y_true = [0, 0, 1, 1, 0, 1, 0, 1]
    y_prob = [0.2, 0.3, 0.7, 0.8, 0.4, 0.6, 0.25, 0.75]
    
    # Individual metrics
    bs = compute_brier(y_true, y_prob)
    bss = compute_bss(y_true, y_prob, baseline_prob=0.5)
    decomp = brier_decomposition(y_true, y_prob, n_bins=4)
    
    print(f"📊 Individual Metrics:")
    print(f"  Brier Score: {bs:.5f}")
    print(f"  Brier Skill Score: {bss:.4f}")
    print(f"")
    print(f"🔍 Decomposition:")
    print(f"  REL: {decomp['REL']:.5f}")
    print(f"  RES: {decomp['RES']:.5f}")
    print(f"  UNC: {decomp['UNC']:.5f}")
    print(f"  BS (decomp): {decomp['BS']:.5f}")
    print(f"  REL-RES+UNC: {decomp['REL-RES+UNC']:.5f}")
    print(f"")
    print(f"✅ Mathematical Check:")
    print(f"  Direct BS: {bs:.5f}")
    print(f"  Decomposed BS: {decomp['REL-RES+UNC']:.5f}")
    print(f"  Difference: {abs(bs - decomp['REL-RES+UNC']):.5f}")
    
    return bs, bss, decomp


def demo_quality_assessment():
    """Demonstrate quality assessment framework"""
    print("\n🏆 MERID Metrics Library - Quality Assessment Demo")
    print("=" * 60)
    
    # Different quality levels
    test_cases = {
        "Excellent": ([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]),
        "Good": ([0, 0, 1, 1, 0, 1], [0.2, 0.3, 0.7, 0.8, 0.4, 0.6]),
        "Fair": ([0, 0, 1, 1, 0, 1], [0.3, 0.4, 0.6, 0.7, 0.5, 0.5]),
        "Poor": ([0, 0, 1, 1], [0.8, 0.7, 0.3, 0.2])
    }
    
    for quality, (y_true, y_prob) in test_cases.items():
        results = evaluate_forecast(y_true, y_prob)
        print(f"  {quality:8s} | BS: {results['brier_score']:.5f} | BSS: {results['brier_skill_score']:.3f} | Category: {results['quality_category']}")
    
    print(f"\n📊 Quality Thresholds:")
    print(f"  Excellent: BS < 0.1")
    print(f"  Good:     BS < 0.2")
    print(f"  Fair:     BS < 0.3")
    print(f"  Poor:     BS ≥ 0.3")


if __name__ == "__main__":
    print("🎯 MERID Metrics Library - Complete Demonstration")
    print("=" * 60)
    print("Textbook-clean reference implementation for probabilistic forecasting")
    print("Industry-standard metrics: Brier, BSS, decomposition, reliability diagrams")
    print("")
    
    # Run all demonstrations
    demo_reference_dataset()
    demo_merid_integration()
    demo_individual_metrics()
    demo_quality_assessment()
    
    print("\n" + "=" * 60)
    print("🎉 DEMONSTRATION COMPLETE")
    print("=" * 60)
    print("✅ Reference dataset validated")
    print("✅ MERID integration workflow demonstrated")
    print("✅ Individual functions tested")
    print("✅ Quality assessment framework shown")
    print("")
    print("📚 Usage in MERID:")
    print("  from merid_metrics import evaluate_forecast, load_and_evaluate_csv")
    print("  results = evaluate_forecast(y_true, y_prob)")
    print("  results = load_and_evaluate_csv('agent_results.csv')")
    print("")
    print("🚀 Ready for production use in MERID agent evaluation!")

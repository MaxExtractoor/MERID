"""
Interactive Kelly Criterion Optimizer

Streamlit app for tuning Kelly parameters and visualizing growth and drawdown.
"""

import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)

def kelly_fraction(win_rate: float, win_loss_ratio: float) -> float:
    """
    Calculate Kelly fraction from win rate and win/loss ratio.
    
    Args:
        win_rate: Probability of winning trade (0.0 to 1.0)
        win_loss_ratio: Ratio of average win to average loss
        
    Returns:
        Kelly fraction (0.0 to 1.0)
    """
    kelly = win_rate - (1 - win_rate) / win_loss_ratio
    return max(0.0, min(1.0, kelly))

def simulate_kelly_trading(win_rate: float, 
                          win_loss_ratio: float,
                          kelly_fraction: float,
                          n_trades: int = 1000,
                          n_paths: int = 500,
                          seed: Optional[int] = None) -> np.ndarray:
    """
    Monte Carlo simulation of Kelly trading strategy.
    
    Args:
        win_rate: Probability of winning trade
        win_loss_ratio: Ratio of average win to average loss
        kelly_fraction: Fraction of Kelly to use
        n_trades: Number of trades per simulation
        n_paths: Number of simulation paths
        seed: Random seed for reproducibility
        
    Returns:
        Array of final capital values
    """
    if seed is not None:
        np.random.seed(seed)
    
    pnl_win = win_loss_ratio
    pnl_loss = -1.0
    
    finals = []
    
    for _ in range(n_paths):
        # Generate trade outcomes
        outcomes = np.where(
            np.random.rand(n_trades) < win_rate, pnl_win, pnl_loss
        )
        
        # Simulate trading with Kelly sizing
        capital = 1.0
        for outcome in outcomes:
            capital *= 1 + kelly_fraction * outcome
            
            # Stop if capital goes to zero or below
            if capital <= 0:
                break
        
        finals.append(capital)
    
    return np.array(finals)

def calculate_risk_metrics(finals: np.ndarray) -> Dict[str, float]:
    """
    Calculate risk metrics from simulation results.
    
    Args:
        finals: Array of final capital values
        
    Returns:
        Dictionary of risk metrics
    """
    if len(finals) == 0:
        return {}
    
    metrics = {
        "median_final": np.median(finals),
        "mean_final": np.mean(finals),
        "std_final": np.std(finals),
        "min_final": np.min(finals),
        "max_final": np.max(finals),
        "percentile_5": np.percentile(finals, 5),
        "percentile_25": np.percentile(finals, 25),
        "percentile_75": np.percentile(finals, 75),
        "percentile_95": np.percentile(finals, 95),
        "ruin_probability": np.mean(finals <= 0.5),  # Risk of ruin (50% capital)
        "loss_probability": np.mean(finals < 1.0),  # Probability of loss
        "gain_probability": np.mean(finals > 1.0),  # Probability of gain
        "doubling_probability": np.mean(finals >= 2.0),  # Probability of doubling capital
    }
    
    return metrics

def create_distribution_chart(finals: np.ndarray, title: str = "Final Capital Distribution") -> go.Figure:
    """
    Create distribution chart for final capital values.
    
    Args:
        finals: Array of final capital values
        title: Chart title
        
    Returns:
        Plotly figure
    """
    sorted_finals = np.sort(finals)
    
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=list(range(len(sorted_finals))),
        y=sorted_finals,
        mode='lines',
        name="Final Capital",
        line=dict(color='blue', width=2),
        hovertemplate="Path: %{x}<br>Final: %{y:.3f}<extra></extra>"
    ))
    
    fig.update_layout(
        title=title,
        xaxis_title="Simulation Path (sorted)",
        yaxis_title="Final Capital",
        template="plotly_white",
        height=500
    )
    
    return fig

def create_histogram_chart(finals: np.ndarray, title: str = "Capital Distribution Histogram") -> go.Figure:
    """
    Create histogram chart for final capital values.
    
    Args:
        finals: Array of final capital values
        title: Chart title
        
    Returns:
        Plotly figure
    """
    fig = go.Figure()
    
    fig.add_trace(go.Histogram(
        x=finals,
        nbinsx=50,
        name="Final Capital",
        marker_color='lightblue',
        opacity=0.7
    ))
    
    fig.update_layout(
        title=title,
        xaxis_title="Final Capital",
        yaxis_title="Frequency",
        template="plotly_white",
        height=400
    )
    
    return fig

def create_comparison_chart(results: Dict[str, np.ndarray], title: str = "Kelly Strategy Comparison") -> go.Figure:
    """
    Create comparison chart for multiple Kelly strategies.
    
    Args:
        results: Dictionary of final capital arrays by strategy name
        title: Chart title
        
    Returns:
        Plotly figure
    """
    fig = go.Figure()
    
    colors = ['blue', 'red', 'green', 'orange', 'purple']
    
    for i, (name, finals) in enumerate(results.items()):
        sorted_finals = np.sort(finals)
        
        fig.add_trace(go.Scatter(
            x=list(range(len(sorted_finals))),
            y=sorted_finals,
            mode='lines',
            name=name,
            line=dict(color=colors[i % len(colors)], width=2),
            hovertemplate=f"{name}<br>Path: %{{x}}<br>Final: %{{y:.3f}}<extra></extra>"
        ))
    
    fig.update_layout(
        title=title,
        xaxis_title="Simulation Path (sorted)",
        yaxis_title="Final Capital",
        template="plotly_white",
        height=600,
        legend=dict(x=0.01, y=0.99)
    )
    
    return fig

def create_risk_reward_chart(metrics_data: List[Dict[str, Any]]) -> go.Figure:
    """
    Create risk-reward scatter chart for different strategies.
    
    Args:
        metrics_data: List of metrics dictionaries
        
    Returns:
        Plotly figure
    """
    strategies = []
    median_returns = []
    ruin_probs = []
    
    for i, metrics in enumerate(metrics_data):
        strategies.append(f"Strategy {i+1}")
        median_returns.append(metrics["median_final"])
        ruin_probs.append(metrics["ruin_probability"])
    
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=ruin_probs,
        y=median_returns,
        mode='markers+text',
        text=strategies,
        textposition="top center",
        marker=dict(
            size=10,
            color=median_returns,
            colorscale='RdYlGn',
            showscale=True,
            colorbar=dict(title="Median Return")
        ),
        hovertemplate="Strategy: %{text}<br>Ruin Prob: %{x:.1%}<br>Median Return: %{y:.3f}<extra></extra>"
    ))
    
    fig.update_layout(
        title="Risk-Reward Analysis",
        xaxis_title="Risk of Ruin Probability",
        yaxis_title="Median Final Capital",
        template="plotly_white",
        height=500
    )
    
    return fig

def main():
    """Main Streamlit application."""
    st.title("🎯 Interactive Kelly Criterion Optimizer")
    st.markdown("Optimize Kelly parameters and visualize growth and drawdown with Monte Carlo simulation")
    
    # Sidebar configuration
    with st.sidebar:
        st.header("⚙️ Strategy Parameters")
        
        # Edge assumptions
        win_rate = st.slider("Win Rate", 0.4, 0.7, 0.55, 0.01,
                           help="Probability of winning trade")
        
        win_loss_ratio = st.slider("Win/Loss Ratio", 0.5, 3.0, 1.5, 0.05,
                                help="Ratio of average win to average loss")
        
        # Calculate full Kelly
        f_full = kelly_fraction(win_rate, win_loss_ratio)
        
        st.markdown("---")
        st.markdown("### Kelly Sizing")
        
        fraction = st.slider("Fraction of Kelly", 0.0, 1.0, 0.5, 0.05,
                           help="Fraction of full Kelly to use")
        
        f_actual = f_full * fraction
        
        st.markdown("---")
        st.markdown("### Simulation Settings")
        
        n_trades = st.slider("Number of Trades", 100, 5000, 1000, 100,
                           help="Number of trades per simulation path")
        
        n_paths = st.slider("Number of Paths", 100, 2000, 500, 50,
                          help="Number of Monte Carlo simulation paths")
        
        seed = st.number_input("Random Seed", value=42, min_value=1, max_value=9999,
                             help="Seed for reproducible results")
        
        st.markdown("---")
        st.markdown("### Comparison Options")
        
        compare_strategies = st.checkbox("Compare Multiple Fractions", value=False)
        
        if compare_strategies:
            fractions_to_compare = st.multiselect(
                "Fractions to Compare",
                [0.125, 0.25, 0.5, 0.75, 1.0],
                default=[0.25, 0.5, 0.75]
            )
    
    # Main content area
    st.markdown("---")
    
    # Display Kelly calculations
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.metric("Full Kelly", f"{f_full:.3f}")
    
    with col2:
        st.metric("Using Fraction", f"{fraction:.2f}")
    
    with col3:
        st.metric("Actual Fraction", f"{f_actual:.3f}")
    
    # Risk assessment
    if f_full > 0.3:
        st.warning("⚠️ High Kelly fraction detected - consider using fractional Kelly")
    elif f_full < 0.05:
        st.info("ℹ️ Low Kelly fraction - strategy may be too conservative")
    else:
        st.success("✅ Reasonable Kelly fraction")
    
    # Run simulation
    if st.button("🚀 Run Monte Carlo Simulation", type="primary"):
        with st.spinner("Running simulation..."):
            if compare_strategies and fractions_to_compare:
                # Run multiple simulations
                results = {}
                metrics_list = []
                
                for frac in fractions_to_compare:
                    finals = simulate_kelly_trading(
                        win_rate, win_loss_ratio, f_full * frac, n_trades, n_paths, seed
                    )
                    results[f"{int(frac*100)}% Kelly"] = finals
                    metrics_list.append(calculate_risk_metrics(finals))
                
                # Display comparison
                st.subheader("📊 Strategy Comparison")
                
                # Comparison chart
                fig_comparison = create_comparison_chart(results)
                st.plotly_chart(fig_comparison, use_container_width=True)
                
                # Risk-reward chart
                fig_risk_reward = create_risk_reward_chart(metrics_list)
                st.plotly_chart(fig_risk_reward, use_container_width=True)
                
                # Comparison table
                st.subheader("📈 Performance Comparison")
                
                comparison_data = []
                for i, frac in enumerate(fractions_to_compare):
                    metrics = metrics_list[i]
                    comparison_data.append({
                        "Fraction": f"{int(frac*100)}%",
                        "Median Return": f"{metrics['median_final']:.3f}",
                        "5th Percentile": f"{metrics['percentile_5']:.3f}",
                        "Ruin Prob": f"{metrics['ruin_probability']:.1%}",
                        "Gain Prob": f"{metrics['gain_probability']:.1%}",
                        "Doubling Prob": f"{metrics['doubling_probability']:.1%}"
                    })
                
                df_comparison = pd.DataFrame(comparison_data)
                st.dataframe(df_comparison, use_container_width=True)
                
            else:
                # Run single simulation
                finals = simulate_kelly_trading(
                    win_rate, win_loss_ratio, f_actual, n_trades, n_paths, seed
                )
                
                # Calculate metrics
                metrics = calculate_risk_metrics(finals)
                
                # Display results
                st.subheader("📊 Simulation Results")
                
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.metric("Median Final", f"{metrics['median_final']:.3f}")
                
                with col2:
                    st.metric("5th Percentile", f"{metrics['percentile_5']:.3f}")
                
                with col3:
                    st.metric("Ruin Probability", f"{metrics['ruin_probability']:.1%}")
                
                with col4:
                    st.metric("Gain Probability", f"{metrics['gain_probability']:.1%}")
                
                # Distribution chart
                fig_dist = create_distribution_chart(finals, f"Final Capital Distribution ({fraction:.0%} Kelly)")
                st.plotly_chart(fig_dist, use_container_width=True)
                
                # Histogram
                fig_hist = create_histogram_chart(finals, "Capital Distribution Histogram")
                st.plotly_chart(fig_hist, use_container_width=True)
                
                # Detailed statistics
                st.subheader("📈 Detailed Statistics")
                
                stats_data = {
                    "Metric": ["Mean", "Standard Deviation", "Minimum", "Maximum", 
                           "25th Percentile", "75th Percentile", "95th Percentile"],
                    "Value": [
                        f"{metrics['mean_final']:.3f}",
                        f"{metrics['std_final']:.3f}",
                        f"{metrics['min_final']:.3f}",
                        f"{metrics['max_final']:.3f}",
                        f"{metrics['percentile_25']:.3f}",
                        f"{metrics['percentile_75']:.3f}",
                        f"{metrics['percentile_95']:.3f}"
                    ]
                }
                
                df_stats = pd.DataFrame(stats_data)
                st.dataframe(df_stats, use_container_width=True)
    
    # Educational content
    with st.expander("📚 About Kelly Criterion"):
        st.markdown("""
        ### Kelly Criterion Formula
        ```
        f* = p - q/b
        ```
        Where:
        - f* = fraction of bankroll to wager
        - p = probability of winning
        - q = probability of losing (1 - p)
        - b = odds received on the bet (win/loss ratio)
        
        ### Key Principles
        - **Maximizes long-term growth rate**
        - **Minimizes risk of ruin**
        - **Requires accurate edge estimation**
        - **Fractional Kelly reduces volatility**
        
        ### Risk Management
        - Use 25-50% of full Kelly for reduced drawdowns
        - Monitor win rate estimation accuracy
        - Adjust position sizes based on confidence
        - Consider correlation between positions
        """)

if __name__ == "__main__":
    main()

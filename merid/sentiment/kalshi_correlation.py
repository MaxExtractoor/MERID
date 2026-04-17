"""
Kalshi Multi-Market Correlation Detection

Detects correlations between Kalshi markets for relative-value strategies
and portfolio risk management (avoid overloading on near-duplicates).
"""

import pandas as pd
import numpy as np
from typing import List, Tuple, Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime, timezone
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class CorrelatedPair:
    """Highly correlated market pair."""
    market_a: str
    market_b: str
    correlation: float
    corr_type: str  # 'positive', 'negative'
    recommendation: str  # 'arb_candidate', 'diversify', 'avoid_overlap'


class KalshiCorrelationDetector:
    """
    Detect correlations between Kalshi markets from historical data.
    
    Usage:
        detector = KalshiCorrelationDetector()
        
        # From historical data
        df = fetch_historical_prices()  # columns: timestamp, market_ticker, price
        pairs = detector.find_correlated_pairs(df, threshold=0.8)
        
        # Check portfolio overlap
        overlap = detector.check_portfolio_overlap(
            held_markets=["KXBTC-DAILY", "KXBTC-HOURLY"],
            all_pairs=pairs,
        )
    """
    
    def __init__(self, min_history: int = 50):
        self.min_history = min_history
    
    def pivot_prices(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Convert long format to wide format.
        
        Args:
            df: DataFrame with columns ['timestamp', 'market_ticker', 'price']
        
        Returns:
            Wide DataFrame: index=timestamp, columns=tickers, values=price
        """
        wide = df.pivot(index="timestamp", columns="market_ticker", values="price")
        wide = wide.sort_index().ffill().dropna(axis=1, how="all")
        return wide
    
    def compute_returns(self, price_wide: pd.DataFrame) -> pd.DataFrame:
        """Compute percentage returns from price series."""
        return price_wide.pct_change().dropna(how="all")
    
    def correlation_matrix(
        self,
        price_wide: pd.DataFrame,
        method: str = "pearson",
    ) -> pd.DataFrame:
        """
        Compute correlation matrix of returns.
        
        Args:
            price_wide: Wide price DataFrame
            method: 'pearson', 'spearman', or 'kendall'
        
        Returns:
            Correlation matrix DataFrame
        """
        rets = self.compute_returns(price_wide)
        return rets.corr(method=method)
    
    def find_high_corr_pairs(
        self,
        corr: pd.DataFrame,
        threshold: float = 0.8,
    ) -> List[CorrelatedPair]:
        """
        Find highly correlated pairs.
        
        Args:
            corr: Correlation matrix
            threshold: Minimum absolute correlation
        
        Returns:
            List of CorrelatedPair
        """
        pairs = []
        cols = corr.columns
        
        for i in range(len(cols)):
            for j in range(i + 1, len(cols)):
                c = corr.iloc[i, j]
                
                if abs(c) >= threshold:
                    market_a = cols[i]
                    market_b = cols[j]
                    
                    # Determine type and recommendation
                    if c > 0:
                        corr_type = "positive"
                        # Near-duplicate if very high
                        if c > 0.95:
                            recommendation = "avoid_overlap"
                        else:
                            recommendation = "diversify"
                    else:
                        corr_type = "negative"
                        recommendation = "arb_candidate"
                    
                    pairs.append(CorrelatedPair(
                        market_a=market_a,
                        market_b=market_b,
                        correlation=c,
                        corr_type=corr_type,
                        recommendation=recommendation,
                    ))
        
        # Sort by absolute correlation (strongest first)
        pairs.sort(key=lambda x: -abs(x.correlation))
        
        return pairs
    
    def find_clusters(
        self,
        corr: pd.DataFrame,
        threshold: float = 0.7,
    ) -> Dict[str, List[str]]:
        """
        Find clusters of highly correlated markets.
        
        Returns:
            Dict mapping cluster name to list of markets
        """
        # Simple clustering: group markets with avg correlation > threshold
        markets = corr.columns.tolist()
        clusters = []
        assigned = set()
        
        for market in markets:
            if market in assigned:
                continue
            
            # Find all markets correlated with this one
            cluster = [market]
            for other in markets:
                if other != market and other not in assigned:
                    if abs(corr.loc[market, other]) >= threshold:
                        cluster.append(other)
            
            if len(cluster) > 1:
                clusters.append(cluster)
                assigned.update(cluster)
        
        # Name clusters by first member
        return {f"cluster_{c[0]}": c for c in clusters}
    
    def check_portfolio_overlap(
        self,
        held_markets: List[str],
        all_pairs: List[CorrelatedPair],
    ) -> Dict[str, Any]:
        """
        Check if held markets have problematic overlap.
        
        Returns:
            Dict with overlap warnings and suggestions
        """
        warnings = []
        suggestions = []
        
        held_set = set(held_markets)
        
        for pair in all_pairs:
            if pair.market_a in held_set and pair.market_b in held_set:
                if pair.recommendation == "avoid_overlap":
                    warnings.append(
                        f"Near-duplicate overlap: {pair.market_a} and {pair.market_b} "
                        f"(corr={pair.correlation:.2f})"
                    )
                    suggestions.append(
                        f"Consider reducing one of: {pair.market_a}, {pair.market_b}"
                    )
                elif pair.recommendation == "diversify":
                    suggestions.append(
                        f"Correlated positions: {pair.market_a} and {pair.market_b} "
                        f"(corr={pair.correlation:.2f}) - ensure intentional"
                    )
        
        return {
            "overlap_count": len(warnings),
            "warnings": warnings,
            "suggestions": suggestions,
            "risk_level": "high" if warnings else "medium" if suggestions else "low",
        }
    
    def detect_relative_value_opps(
        self,
        price_wide: pd.DataFrame,
        corr_threshold: float = 0.8,
        zscore_threshold: float = 2.0,
    ) -> List[Dict[str, Any]]:
        """
        Detect relative value opportunities in highly correlated pairs.
        
        When two highly correlated markets diverge (z-score > threshold),
        potential mean-reversion opportunity.
        
        Returns:
            List of opportunity dicts
        """
        # Find correlated pairs
        corr = self.correlation_matrix(price_wide)
        pairs = self.find_high_corr_pairs(corr, corr_threshold)
        
        opps = []
        
        for pair in pairs:
            if pair.corr_type != "positive":
                continue  # Only positive correlations for RV
            
            # Get price series
            if pair.market_a not in price_wide.columns or pair.market_b not in price_wide.columns:
                continue
            
            series_a = price_wide[pair.market_a]
            series_b = price_wide[pair.market_b]
            
            # Compute spread
            spread = series_a - series_b
            
            # Z-score of spread
            spread_mean = spread.mean()
            spread_std = spread.std()
            
            if spread_std == 0:
                continue
            
            zscore = (spread.iloc[-1] - spread_mean) / spread_std
            
            if abs(zscore) >= zscore_threshold:
                opp = {
                    "market_a": pair.market_a,
                    "market_b": pair.market_b,
                    "correlation": pair.correlation,
                    "spread_zscore": zscore,
                    "current_spread": spread.iloc[-1],
                    "mean_spread": spread_mean,
                    "signal": "short_spread" if zscore > 0 else "long_spread",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                opps.append(opp)
        
        return opps
    
    def full_analysis(
        self,
        df: pd.DataFrame,
        held_markets: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Run full correlation analysis.
        
        Args:
            df: Long format price DataFrame
            held_markets: Optional list of currently held markets
        
        Returns:
            Complete analysis results
        """
        # Pivot
        wide = self.pivot_prices(df)
        
        if wide.empty or len(wide.columns) < 2:
            return {"error": "Insufficient data for correlation analysis"}
        
        # Correlation matrix
        corr = self.correlation_matrix(wide)
        
        # Find pairs
        pairs = self.find_high_corr_pairs(corr, threshold=0.8)
        
        # Find clusters
        clusters = self.find_clusters(corr, threshold=0.7)
        
        # Portfolio overlap check
        overlap = None
        if held_markets:
            overlap = self.check_portfolio_overlap(held_markets, pairs)
        
        # RV opportunities
        rv_opps = self.detect_relative_value_opps(wide)
        
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "markets_analyzed": len(wide.columns),
            "observations": len(wide),
            "correlation_matrix": corr.to_dict(),
            "high_corr_pairs": [
                {
                    "market_a": p.market_a,
                    "market_b": p.market_b,
                    "correlation": p.correlation,
                    "type": p.corr_type,
                    "recommendation": p.recommendation,
                }
                for p in pairs[:10]  # Top 10
            ],
            "clusters": clusters,
            "portfolio_overlap": overlap,
            "relative_value_opps": rv_opps,
            "summary": {
                "pairs_found": len(pairs),
                "arb_candidates": len([p for p in pairs if p.recommendation == "arb_candidate"]),
                "diversify_warnings": len([p for p in pairs if p.recommendation == "diversify"]),
                "overlap_warnings": len([p for p in pairs if p.recommendation == "avoid_overlap"]),
            },
        }


# ── Convenience functions ──────────────────────────────────────────

def quick_corr_check(
    df: pd.DataFrame,
    threshold: float = 0.8,
) -> List[Tuple[str, str, float]]:
    """
    Quick one-liner to find highly correlated pairs.
    
    Returns:
        List of (market_a, market_b, correlation) tuples
    """
    detector = KalshiCorrelationDetector()
    wide = detector.pivot_prices(df)
    corr = detector.correlation_matrix(wide)
    pairs = detector.find_high_corr_pairs(corr, threshold)
    
    return [(p.market_a, p.market_b, p.correlation) for p in pairs[:5]]


def check_overlap(
    held_markets: List[str],
    historical_df: pd.DataFrame,
) -> Dict[str, Any]:
    """Quick check for portfolio overlap issues."""
    detector = KalshiCorrelationDetector()
    wide = detector.pivot_prices(historical_df)
    corr = detector.correlation_matrix(wide)
    pairs = detector.find_high_corr_pairs(corr, threshold=0.8)
    
    return detector.check_portfolio_overlap(held_markets, pairs)

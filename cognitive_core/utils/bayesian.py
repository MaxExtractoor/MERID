"""
Bayesian probability calculus.
Core mathematical foundation for belief updating.
"""

import math
from typing import List, Tuple


class BayesianCore:
    """
    Bayesian belief updating and probability mathematics.
    
    Principles:
    - All beliefs are probabilistic
    - Prior beliefs updated by evidence
    - Uncertainty always represented
    - No point estimates without confidence intervals
    """
    
    @staticmethod
    def update_belief(
        prior_probability: float,
        likelihood_if_true: float,
        likelihood_if_false: float,
    ) -> float:
        """
        Bayesian update: P(H|E) = P(E|H) * P(H) / P(E)
        
        Args:
            prior_probability: P(H) - prior belief in hypothesis
            likelihood_if_true: P(E|H) - probability of evidence if hypothesis true
            likelihood_if_false: P(E|¬H) - probability of evidence if hypothesis false
        
        Returns:
            Posterior probability P(H|E)
        """
        if not (0 <= prior_probability <= 1):
            raise ValueError(f"Prior must be in [0,1], got {prior_probability}")
        if not (0 <= likelihood_if_true <= 1):
            raise ValueError(f"Likelihood if true must be in [0,1], got {likelihood_if_true}")
        if not (0 <= likelihood_if_false <= 1):
            raise ValueError(f"Likelihood if false must be in [0,1], got {likelihood_if_false}")
        
        # P(E) = P(E|H)*P(H) + P(E|¬H)*P(¬H)
        p_evidence = (
            likelihood_if_true * prior_probability + 
            likelihood_if_false * (1 - prior_probability)
        )
        
        if p_evidence == 0:
            return prior_probability
        
        # P(H|E) = P(E|H) * P(H) / P(E)
        posterior = (likelihood_if_true * prior_probability) / p_evidence
        
        return max(0.0, min(1.0, posterior))
    
    @staticmethod
    def sequential_update(
        prior: float,
        evidence_list: List[Tuple[float, float]],
    ) -> float:
        """
        Sequential Bayesian updating with multiple pieces of evidence.
        
        Args:
            prior: Initial prior probability
            evidence_list: List of (likelihood_if_true, likelihood_if_false) tuples
        
        Returns:
            Final posterior after all evidence
        """
        posterior = prior
        for likelihood_true, likelihood_false in evidence_list:
            posterior = BayesianCore.update_belief(
                posterior,
                likelihood_true,
                likelihood_false,
            )
        return posterior
    
    @staticmethod
    def confidence_interval(
        probability: float,
        sample_size: int,
        confidence_level: float = 0.95,
    ) -> Tuple[float, float]:
        """
        Calculate confidence interval for a probability estimate.
        Uses Wilson score interval (better than normal approximation for extreme probabilities).
        
        Args:
            probability: Estimated probability
            sample_size: Number of samples
            confidence_level: Desired confidence level (default 95%)
        
        Returns:
            (lower_bound, upper_bound) tuple
        """
        if sample_size == 0:
            return (0.0, 1.0)
        
        # Z-score for confidence level
        z_scores = {0.90: 1.645, 0.95: 1.96, 0.99: 2.576}
        z = z_scores.get(confidence_level, 1.96)
        
        # Wilson score interval
        p = probability
        n = sample_size
        
        denominator = 1 + z**2 / n
        center = (p + z**2 / (2 * n)) / denominator
        margin = z * math.sqrt((p * (1 - p) / n + z**2 / (4 * n**2))) / denominator
        
        lower = max(0.0, center - margin)
        upper = min(1.0, center + margin)
        
        return (lower, upper)
    
    @staticmethod
    def entropy(probability: float) -> float:
        """
        Shannon entropy of a binary outcome.
        Measures uncertainty: H(p) = -p*log2(p) - (1-p)*log2(1-p)
        
        Maximum entropy (1.0) at p=0.5 (maximum uncertainty).
        Minimum entropy (0.0) at p=0 or p=1 (certainty).
        
        Args:
            probability: Probability of positive outcome
        
        Returns:
            Entropy in bits [0, 1]
        """
        if probability == 0 or probability == 1:
            return 0.0
        
        p = probability
        q = 1 - p
        
        return -(p * math.log2(p) + q * math.log2(q))
    
    @staticmethod
    def kl_divergence(p: List[float], q: List[float]) -> float:
        """
        Kullback-Leibler divergence D_KL(P||Q).
        Measures how much distribution P differs from Q.
        
        Args:
            p: True distribution
            q: Approximate distribution
        
        Returns:
            KL divergence (0 if identical, >0 otherwise)
        """
        if len(p) != len(q):
            raise ValueError("Distributions must have same length")
        
        divergence = 0.0
        for p_i, q_i in zip(p, q):
            if p_i > 0:
                if q_i == 0:
                    return float('inf')
                divergence += p_i * math.log(p_i / q_i)
        
        return divergence
    
    @staticmethod
    def expected_value(
        outcomes: List[float],
        probabilities: List[float],
    ) -> float:
        """
        Expected value: E[X] = Σ(x_i * p_i)
        
        Args:
            outcomes: List of possible outcomes
            probabilities: Corresponding probabilities (must sum to 1)
        
        Returns:
            Expected value
        """
        if len(outcomes) != len(probabilities):
            raise ValueError("Outcomes and probabilities must have same length")
        
        total_prob = sum(probabilities)
        if not math.isclose(total_prob, 1.0, rel_tol=1e-6):
            raise ValueError(f"Probabilities must sum to 1, got {total_prob}")
        
        return sum(x * p for x, p in zip(outcomes, probabilities))
    
    @staticmethod
    def variance(
        outcomes: List[float],
        probabilities: List[float],
    ) -> float:
        """
        Variance: Var[X] = E[(X - E[X])²]
        
        Args:
            outcomes: List of possible outcomes
            probabilities: Corresponding probabilities
        
        Returns:
            Variance
        """
        ev = BayesianCore.expected_value(outcomes, probabilities)
        return sum(p * (x - ev)**2 for x, p in zip(outcomes, probabilities))

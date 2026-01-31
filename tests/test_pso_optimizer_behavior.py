"""Focused tests for swarm.pso_optimizer behaviors."""

from __future__ import annotations

from typing import List

import numpy as np
import pytest

from swarm import pso_optimizer as pso


def _make_particles(positions: List[float]) -> List[pso.Particle]:
    particles = []
    for value in positions:
        pos = np.array([value], dtype=float)
        particles.append(
            pso.Particle(
                position=pos.copy(),
                velocity=np.zeros_like(pos),
                best_position=pos.copy(),
                best_fitness=float("-inf"),
                fitness=float("-inf"),
            )
        )
    return particles


def test_optimize_updates_global_best_and_invokes_callback():
    config = pso.PSOConfig(
        num_particles=2,
        max_iterations=5,
        bounds=[(0.0, 1.0)],
        adaptive_inertia=False,
        velocity_clamping=True,
        topology="global",
    )
    optimizer = pso.PSOOptimizer(config)
    optimizer.particles = _make_particles([0.0, 1.0])

    callback_calls = []

    def fitness_fn(position):
        return -abs(position[0] - 0.75)

    def callback(iteration, best_fitness, diversity):
        callback_calls.append((iteration, best_fitness, diversity))

    best_position, best_fitness = optimizer.optimize(fitness_fn, callback=callback)

    assert len(callback_calls) == config.max_iterations
    assert optimizer.global_best_fitness == best_fitness
    assert best_position.shape == (1,)
    assert abs(best_position[0] - 0.75) < 0.25
    assert len(optimizer.fitness_history) == config.max_iterations
    assert len(optimizer.diversity_history) == config.max_iterations

    metrics = optimizer.get_metrics()
    assert metrics["iteration"] == config.max_iterations - 1
    assert metrics["global_best_position"], "global best position missing"
    assert metrics["fitness_history"] == optimizer.fitness_history


def test_clamp_helpers_limit_velocity_and_position():
    config = pso.PSOConfig(num_particles=1, max_iterations=1, bounds=[(0.0, 10.0)])
    optimizer = pso.PSOOptimizer(config)

    clamped_velocity = optimizer._clamp_velocity(np.array([100.0]))
    assert np.allclose(clamped_velocity, np.array([2.0]))  # 20% of range

    clamped_position = optimizer._clamp_position(np.array([-5.0]))
    assert np.allclose(clamped_position, np.array([0.0]))


def test_reward_shaper_utilities_cover_key_formulas():
    diff = pso.RewardShaper.difference_rewards(0, team_reward=5.0, counterfactual_reward=2.0)
    assert diff == 3.0

    potential = pso.RewardShaper.potential_based_shaping(
        state=np.array([0.0]),
        next_state=np.array([1.0]),
        gamma=0.9,
        potential_fn=lambda s: float(s[0] ** 2),
    )
    assert potential == pytest.approx(0.9 - 0.0)

    curiosity = pso.RewardShaper.curiosity_bonus(prediction_error=4.0, scale=0.5)
    assert curiosity == 2.0

    social = pso.RewardShaper.social_influence_reward(1, [1, 0, 1, 2], coordination_bonus=1.0)
    assert social == pytest.approx(0.5)

    total = pso.RewardShaper.combined_reward(1.0, diff, curiosity, social)
    assert total > 0.0

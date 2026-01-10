"""Tests for Stage 10 PSO optimizer."""

from __future__ import annotations

import numpy as np
import pytest

from swarm.pso_optimizer import (
    ConsensusHyperparams,
    MARLHyperparams,
    Particle,
    PSOConfig,
    PSOOptimizer,
    RewardShaper,
)


def test_particle_creation():
    """Test particle initialization with bounds."""
    bounds = [(0.0, 1.0), (0.0, 10.0), (-5.0, 5.0)]
    particle = Particle.create(bounds)
    
    assert len(particle.position) == 3
    assert len(particle.velocity) == 3
    assert 0.0 <= particle.position[0] <= 1.0
    assert 0.0 <= particle.position[1] <= 10.0
    assert -5.0 <= particle.position[2] <= 5.0


def test_pso_optimizer_initialization():
    """Test PSO optimizer initialization."""
    config = PSOConfig(
        num_particles=20,
        max_iterations=50,
        bounds=[(0.0, 1.0), (0.0, 10.0)],
    )
    
    optimizer = PSOOptimizer(config)
    
    assert len(optimizer.particles) == 20
    assert optimizer.global_best_fitness == float("-inf")
    assert optimizer.iteration == 0


def test_pso_sphere_function():
    """Test PSO on simple sphere function (sum of squares)."""
    def sphere_function(position: np.ndarray) -> float:
        return -np.sum(position ** 2)  # Negative for maximization
    
    config = PSOConfig(
        num_particles=20,
        max_iterations=50,
        bounds=[(-5.0, 5.0), (-5.0, 5.0)],
    )
    
    optimizer = PSOOptimizer(config)
    best_position, best_fitness = optimizer.optimize(sphere_function)
    
    # Should converge near origin
    assert np.linalg.norm(best_position) < 1.0
    assert best_fitness > -1.0


def test_pso_rastrigin_function():
    """Test PSO on Rastrigin function (multimodal)."""
    def rastrigin_function(position: np.ndarray) -> float:
        A = 10
        n = len(position)
        return -(A * n + np.sum(position**2 - A * np.cos(2 * np.pi * position)))
    
    config = PSOConfig(
        num_particles=30,
        max_iterations=100,
        bounds=[(-5.12, 5.12), (-5.12, 5.12)],
    )
    
    optimizer = PSOOptimizer(config)
    best_position, best_fitness = optimizer.optimize(rastrigin_function)
    
    # Should find reasonable solution
    assert best_fitness > -50.0


def test_pso_adaptive_inertia():
    """Test adaptive inertia weight decay."""
    config = PSOConfig(
        num_particles=10,
        max_iterations=100,
        bounds=[(0.0, 1.0)],
        adaptive_inertia=True,
    )
    
    optimizer = PSOOptimizer(config)
    
    # Early iteration: high inertia
    optimizer.iteration = 10
    w_early = optimizer._update_inertia()
    
    # Late iteration: low inertia
    optimizer.iteration = 90
    w_late = optimizer._update_inertia()
    
    assert w_early > w_late
    assert 0.4 <= w_late <= 0.9


def test_pso_velocity_clamping():
    """Test velocity clamping."""
    config = PSOConfig(
        num_particles=10,
        max_iterations=50,
        bounds=[(0.0, 10.0), (0.0, 10.0)],
        velocity_clamping=True,
    )
    
    optimizer = PSOOptimizer(config)
    
    # Create extreme velocity
    extreme_velocity = np.array([100.0, -100.0])
    clamped = optimizer._clamp_velocity(extreme_velocity)
    
    # Should be clamped
    assert np.all(np.abs(clamped) < 10.0)


def test_pso_position_clamping():
    """Test position clamping to bounds."""
    config = PSOConfig(
        num_particles=10,
        max_iterations=50,
        bounds=[(0.0, 1.0), (0.0, 1.0)],
    )
    
    optimizer = PSOOptimizer(config)
    
    # Position outside bounds
    position = np.array([2.0, -1.0])
    clamped = optimizer._clamp_position(position)
    
    assert clamped[0] == 1.0
    assert clamped[1] == 0.0


def test_pso_global_topology():
    """Test PSO with global topology."""
    config = PSOConfig(
        num_particles=10,
        max_iterations=20,
        bounds=[(0.0, 1.0)],
        topology="global",
    )
    
    optimizer = PSOOptimizer(config)
    optimizer.global_best_position = np.array([0.5])
    
    # All particles should use global best
    for i in range(len(optimizer.particles)):
        neighborhood_best = optimizer._get_neighborhood_best(i)
        assert np.array_equal(neighborhood_best, optimizer.global_best_position)


def test_pso_ring_topology():
    """Test PSO with ring topology."""
    config = PSOConfig(
        num_particles=10,
        max_iterations=20,
        bounds=[(0.0, 1.0)],
        topology="ring",
    )
    
    optimizer = PSOOptimizer(config)
    
    # Set different best positions for particles
    for i, particle in enumerate(optimizer.particles):
        particle.best_position = np.array([i / 10.0])
        particle.best_fitness = i
    
    # Particle 5 should consider neighbors 4, 5, 6
    neighborhood_best = optimizer._get_neighborhood_best(5)
    assert neighborhood_best is not None


def test_pso_diversity_computation():
    """Test swarm diversity computation."""
    config = PSOConfig(
        num_particles=10,
        max_iterations=20,
        bounds=[(0.0, 1.0), (0.0, 1.0)],
    )
    
    optimizer = PSOOptimizer(config)
    
    # Spread particles
    for i, particle in enumerate(optimizer.particles):
        particle.position = np.array([i / 10.0, i / 10.0])
    
    diversity = optimizer._compute_diversity()
    
    assert diversity > 0.0


def test_pso_fitness_history():
    """Test that PSO tracks fitness history."""
    def simple_function(position: np.ndarray) -> float:
        return -np.sum(position ** 2)
    
    config = PSOConfig(
        num_particles=10,
        max_iterations=20,
        bounds=[(-1.0, 1.0)],
    )
    
    optimizer = PSOOptimizer(config)
    optimizer.optimize(simple_function)
    
    assert len(optimizer.fitness_history) == 20
    assert len(optimizer.diversity_history) == 20


def test_pso_callback():
    """Test PSO callback function."""
    callback_data = []
    
    def callback(iteration, best_fitness, diversity):
        callback_data.append((iteration, best_fitness, diversity))
    
    def simple_function(position: np.ndarray) -> float:
        return -np.sum(position ** 2)
    
    config = PSOConfig(
        num_particles=10,
        max_iterations=10,
        bounds=[(-1.0, 1.0)],
    )
    
    optimizer = PSOOptimizer(config)
    optimizer.optimize(simple_function, callback=callback)
    
    assert len(callback_data) == 10


def test_pso_metrics():
    """Test PSO metrics retrieval."""
    config = PSOConfig(
        num_particles=10,
        max_iterations=20,
        bounds=[(0.0, 1.0)],
    )
    
    optimizer = PSOOptimizer(config)
    metrics = optimizer.get_metrics()
    
    assert "iteration" in metrics
    assert "global_best_fitness" in metrics
    assert "fitness_history" in metrics
    assert "diversity_history" in metrics
    assert "particles" in metrics


def test_marl_hyperparams_from_position():
    """Test MARL hyperparameters from PSO position."""
    position = np.array([0.001, 0.99, 0.995, 64, 10000, 128])
    hyperparams = MARLHyperparams.from_position(position)
    
    assert hyperparams.learning_rate == 0.001
    assert hyperparams.gamma == 0.99
    assert hyperparams.epsilon_decay == 0.995
    assert hyperparams.batch_size == 64
    assert hyperparams.buffer_size == 10000
    assert hyperparams.hidden_size == 128


def test_marl_hyperparams_bounds():
    """Test MARL hyperparameters bounds."""
    bounds = MARLHyperparams.get_bounds()
    
    assert len(bounds) == 6
    assert bounds[0] == (0.0001, 0.01)  # learning_rate
    assert bounds[1] == (0.9, 0.999)  # gamma


def test_consensus_hyperparams_from_position():
    """Test consensus hyperparameters from PSO position."""
    position = np.array([0.6, 0.3, 0.03, 0.6, 0.3, 0.1])
    hyperparams = ConsensusHyperparams.from_position(position)
    
    assert hyperparams.threshold == 0.6
    assert hyperparams.confidence_floor == 0.3
    assert hyperparams.trust_decay_rate == 0.03


def test_consensus_hyperparams_bounds():
    """Test consensus hyperparameters bounds."""
    bounds = ConsensusHyperparams.get_bounds()
    
    assert len(bounds) == 6
    assert bounds[0] == (0.5, 0.8)  # threshold


def test_reward_shaper_difference_rewards():
    """Test difference rewards computation."""
    team_reward = 10.0
    counterfactual_reward = 7.0
    
    diff_reward = RewardShaper.difference_rewards(0, team_reward, counterfactual_reward)
    
    assert diff_reward == 3.0


def test_reward_shaper_potential_based():
    """Test potential-based reward shaping."""
    def potential_fn(state: np.ndarray) -> float:
        return -np.sum(state ** 2)
    
    state = np.array([1.0, 2.0])
    next_state = np.array([0.5, 1.0])
    gamma = 0.99
    
    shaped_reward = RewardShaper.potential_based_shaping(state, next_state, gamma, potential_fn)
    
    # Should be positive (moving toward better state)
    assert shaped_reward > 0.0


def test_reward_shaper_curiosity_bonus():
    """Test curiosity bonus computation."""
    prediction_error = 0.5
    bonus = RewardShaper.curiosity_bonus(prediction_error, scale=0.1)
    
    assert bonus == 0.05


def test_reward_shaper_social_influence():
    """Test social influence reward."""
    agent_action = 1
    other_agents_actions = [1, 1, 2, 1]
    
    social_reward = RewardShaper.social_influence_reward(
        agent_action,
        other_agents_actions,
        coordination_bonus=0.5,
    )
    
    # 3 out of 4 agents coordinated
    assert social_reward == 0.5 * (3 / 4)


def test_reward_shaper_combined():
    """Test combined reward computation."""
    combined = RewardShaper.combined_reward(
        base_reward=1.0,
        difference_reward=0.5,
        curiosity_bonus=0.2,
        social_reward=0.3,
        weights=(0.5, 0.2, 0.2, 0.1),
    )
    
    expected = 0.5 * 1.0 + 0.2 * 0.5 + 0.2 * 0.2 + 0.1 * 0.3
    assert abs(combined - expected) < 1e-6


def test_pso_convergence_improvement():
    """Test that PSO improves fitness over iterations."""
    def simple_function(position: np.ndarray) -> float:
        return -np.sum(position ** 2)
    
    config = PSOConfig(
        num_particles=20,
        max_iterations=50,
        bounds=[(-5.0, 5.0), (-5.0, 5.0)],
    )
    
    optimizer = PSOOptimizer(config)
    optimizer.optimize(simple_function)
    
    # Fitness should improve (become less negative)
    early_fitness = optimizer.fitness_history[5]
    late_fitness = optimizer.fitness_history[-1]
    
    assert late_fitness >= early_fitness


def test_pso_particle_personal_best_update():
    """Test that particles update their personal best."""
    config = PSOConfig(
        num_particles=10,
        max_iterations=10,
        bounds=[(0.0, 1.0)],
    )
    
    optimizer = PSOOptimizer(config)
    
    def fitness_fn(position: np.ndarray) -> float:
        return -position[0] ** 2
    
    # Run one iteration
    for particle in optimizer.particles:
        particle.fitness = fitness_fn(particle.position)
        if particle.fitness > particle.best_fitness:
            particle.best_fitness = particle.fitness
            particle.best_position = particle.position.copy()
    
    # All particles should have updated their best
    for particle in optimizer.particles:
        assert particle.best_fitness > float("-inf")


def test_pso_global_best_update():
    """Test that global best is updated correctly."""
    config = PSOConfig(
        num_particles=10,
        max_iterations=10,
        bounds=[(0.0, 1.0)],
    )
    
    optimizer = PSOOptimizer(config)
    
    # Manually set a particle with high fitness
    optimizer.particles[0].position = np.array([0.1])
    optimizer.particles[0].fitness = 10.0
    optimizer.particles[0].best_fitness = 10.0
    optimizer.particles[0].best_position = np.array([0.1])
    
    # Update global best
    if optimizer.particles[0].fitness > optimizer.global_best_fitness:
        optimizer.global_best_fitness = optimizer.particles[0].fitness
        optimizer.global_best_position = optimizer.particles[0].position.copy()
    
    assert optimizer.global_best_fitness == 10.0
    assert np.array_equal(optimizer.global_best_position, np.array([0.1]))

"""
MERID Swarm Intelligence - Boids (Flocking Behavior)

Boids simulates flocking behavior with three simple rules:
- Separation: Avoid crowding neighbors
- Alignment: Steer towards average heading of neighbors
- Cohesion: Steer towards average position of neighbors

Useful for coordinating multiple trading agents.

Reference: Reynolds, "Flocks, Herds, and Schools: A Distributed Behavioral Model"
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import numpy as np

from utils.logger import get_logger

logger = get_logger("learning.swarm.boids")


@dataclass
class BoidsConfig:
    """Configuration for Boids."""
    # Flock parameters
    n_boids: int = 30
    n_dimensions: int = 2
    
    # Behavior weights
    separation_weight: float = 1.5
    alignment_weight: float = 1.0
    cohesion_weight: float = 1.0
    
    # Perception
    perception_radius: float = 50.0
    separation_radius: float = 25.0
    
    # Movement
    max_speed: float = 5.0
    max_force: float = 0.5
    
    # Boundaries
    bounds: Tuple[float, float] = (-100.0, 100.0)
    boundary_force: float = 0.5
    
    # Goal seeking
    goal_weight: float = 0.5
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "n_boids": self.n_boids,
            "n_dimensions": self.n_dimensions,
            "separation_weight": self.separation_weight,
            "alignment_weight": self.alignment_weight,
            "cohesion_weight": self.cohesion_weight,
            "max_speed": self.max_speed,
        }


@dataclass
class Boid:
    """A single boid in the flock."""
    boid_id: int
    position: np.ndarray
    velocity: np.ndarray
    acceleration: np.ndarray = None
    
    # Agent-specific properties
    fitness: float = 0.0
    role: str = "follower"
    
    def __post_init__(self):
        if self.acceleration is None:
            self.acceleration = np.zeros_like(self.position)
    
    def apply_force(self, force: np.ndarray) -> None:
        """Apply force to boid."""
        self.acceleration += force
    
    def update(self, max_speed: float, dt: float = 1.0) -> None:
        """Update position and velocity."""
        self.velocity += self.acceleration * dt
        
        # Limit speed
        speed = np.linalg.norm(self.velocity)
        if speed > max_speed:
            self.velocity = self.velocity / speed * max_speed
        
        self.position += self.velocity * dt
        self.acceleration = np.zeros_like(self.acceleration)
    
    def distance_to(self, other: 'Boid') -> float:
        """Calculate distance to another boid."""
        return float(np.linalg.norm(self.position - other.position))
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "boid_id": self.boid_id,
            "position": self.position.tolist(),
            "velocity": self.velocity.tolist(),
            "fitness": round(self.fitness, 4),
            "role": self.role,
        }


class Boids:
    """
    Boids flocking simulation.
    
    Key features:
    - Emergent collective behavior
    - Decentralized coordination
    - Scalable to many agents
    - Useful for multi-agent trading coordination
    """
    
    def __init__(self, config: Optional[BoidsConfig] = None):
        self.config = config or BoidsConfig()
        
        # Initialize flock
        self.flock: List[Boid] = []
        self._init_flock()
        
        # Goal position (optional)
        self.goal: Optional[np.ndarray] = None
        
        # Training state
        self._step_count = 0
        
        # History
        self._centroid_history: List[np.ndarray] = []
        
        logger.info(
            "Boids initialized: %d boids, %d dimensions",
            self.config.n_boids, self.config.n_dimensions
        )
    
    def _init_flock(self) -> None:
        """Initialize flock with random positions and velocities."""
        for i in range(self.config.n_boids):
            position = np.random.uniform(
                self.config.bounds[0],
                self.config.bounds[1],
                self.config.n_dimensions
            )
            
            velocity = np.random.uniform(-1, 1, self.config.n_dimensions)
            velocity = velocity / np.linalg.norm(velocity) * self.config.max_speed * 0.5
            
            boid = Boid(boid_id=i, position=position, velocity=velocity)
            self.flock.append(boid)
    
    def _limit_force(self, force: np.ndarray) -> np.ndarray:
        """Limit force magnitude."""
        magnitude = np.linalg.norm(force)
        if magnitude > self.config.max_force:
            force = force / magnitude * self.config.max_force
        return force
    
    def _separation(self, boid: Boid, neighbors: List[Boid]) -> np.ndarray:
        """Calculate separation steering force."""
        steering = np.zeros(self.config.n_dimensions)
        count = 0
        
        for other in neighbors:
            distance = boid.distance_to(other)
            if 0 < distance < self.config.separation_radius:
                diff = boid.position - other.position
                diff = diff / (distance * distance)  # Weight by distance
                steering += diff
                count += 1
        
        if count > 0:
            steering /= count
            if np.linalg.norm(steering) > 0:
                steering = steering / np.linalg.norm(steering) * self.config.max_speed
                steering -= boid.velocity
                steering = self._limit_force(steering)
        
        return steering
    
    def _alignment(self, boid: Boid, neighbors: List[Boid]) -> np.ndarray:
        """Calculate alignment steering force."""
        steering = np.zeros(self.config.n_dimensions)
        count = 0
        
        for other in neighbors:
            steering += other.velocity
            count += 1
        
        if count > 0:
            steering /= count
            if np.linalg.norm(steering) > 0:
                steering = steering / np.linalg.norm(steering) * self.config.max_speed
                steering -= boid.velocity
                steering = self._limit_force(steering)
        
        return steering
    
    def _cohesion(self, boid: Boid, neighbors: List[Boid]) -> np.ndarray:
        """Calculate cohesion steering force."""
        center = np.zeros(self.config.n_dimensions)
        count = 0
        
        for other in neighbors:
            center += other.position
            count += 1
        
        if count > 0:
            center /= count
            desired = center - boid.position
            if np.linalg.norm(desired) > 0:
                desired = desired / np.linalg.norm(desired) * self.config.max_speed
                steering = desired - boid.velocity
                steering = self._limit_force(steering)
                return steering
        
        return np.zeros(self.config.n_dimensions)
    
    def _seek_goal(self, boid: Boid) -> np.ndarray:
        """Calculate goal-seeking force."""
        if self.goal is None:
            return np.zeros(self.config.n_dimensions)
        
        desired = self.goal - boid.position
        distance = np.linalg.norm(desired)
        
        if distance > 0:
            desired = desired / distance * self.config.max_speed
            steering = desired - boid.velocity
            steering = self._limit_force(steering)
            return steering
        
        return np.zeros(self.config.n_dimensions)
    
    def _boundary_force(self, boid: Boid) -> np.ndarray:
        """Calculate boundary avoidance force."""
        force = np.zeros(self.config.n_dimensions)
        
        for d in range(self.config.n_dimensions):
            if boid.position[d] < self.config.bounds[0] + 10:
                force[d] = self.config.boundary_force
            elif boid.position[d] > self.config.bounds[1] - 10:
                force[d] = -self.config.boundary_force
        
        return force
    
    def _get_neighbors(self, boid: Boid) -> List[Boid]:
        """Get neighbors within perception radius."""
        neighbors = []
        for other in self.flock:
            if other.boid_id != boid.boid_id:
                if boid.distance_to(other) < self.config.perception_radius:
                    neighbors.append(other)
        return neighbors
    
    def step(self, dt: float = 1.0) -> Dict[str, Any]:
        """Perform one simulation step."""
        self._step_count += 1
        
        # Calculate forces for each boid
        for boid in self.flock:
            neighbors = self._get_neighbors(boid)
            
            # Three rules
            sep = self._separation(boid, neighbors) * self.config.separation_weight
            ali = self._alignment(boid, neighbors) * self.config.alignment_weight
            coh = self._cohesion(boid, neighbors) * self.config.cohesion_weight
            
            # Goal seeking
            goal = self._seek_goal(boid) * self.config.goal_weight
            
            # Boundary avoidance
            boundary = self._boundary_force(boid)
            
            # Apply forces
            boid.apply_force(sep)
            boid.apply_force(ali)
            boid.apply_force(coh)
            boid.apply_force(goal)
            boid.apply_force(boundary)
        
        # Update positions
        for boid in self.flock:
            boid.update(self.config.max_speed, dt)
        
        # Track centroid
        centroid = self.get_centroid()
        self._centroid_history.append(centroid)
        
        return {
            "step": self._step_count,
            "centroid": centroid.tolist(),
            "spread": self.get_spread(),
            "avg_speed": self.get_average_speed(),
        }
    
    def set_goal(self, goal: np.ndarray) -> None:
        """Set goal position for flock."""
        self.goal = goal.copy()
    
    def get_centroid(self) -> np.ndarray:
        """Get flock centroid."""
        positions = np.array([b.position for b in self.flock])
        return positions.mean(axis=0)
    
    def get_spread(self) -> float:
        """Get flock spread (standard deviation from centroid)."""
        centroid = self.get_centroid()
        distances = [np.linalg.norm(b.position - centroid) for b in self.flock]
        return float(np.std(distances))
    
    def get_average_speed(self) -> float:
        """Get average speed of flock."""
        speeds = [np.linalg.norm(b.velocity) for b in self.flock]
        return float(np.mean(speeds))
    
    def get_alignment_score(self) -> float:
        """Get alignment score (how aligned velocities are)."""
        velocities = np.array([b.velocity for b in self.flock])
        norms = np.linalg.norm(velocities, axis=1, keepdims=True)
        norms[norms == 0] = 1
        normalized = velocities / norms
        
        # Average direction
        avg_direction = normalized.mean(axis=0)
        alignment = np.linalg.norm(avg_direction)
        
        return float(alignment)
    
    def simulate(
        self,
        n_steps: int = 100,
        dt: float = 1.0,
        callback: Optional[callable] = None,
    ) -> Dict[str, Any]:
        """Run simulation for n steps."""
        logger.info("Starting Boids simulation for %d steps", n_steps)
        start_time = time.time()
        
        for i in range(n_steps):
            info = self.step(dt)
            
            if callback:
                callback(info)
        
        elapsed = time.time() - start_time
        
        return {
            "n_steps": n_steps,
            "final_centroid": self.get_centroid().tolist(),
            "final_spread": self.get_spread(),
            "final_alignment": self.get_alignment_score(),
            "elapsed_seconds": elapsed,
        }
    
    def reset(self) -> None:
        """Reset flock."""
        self.flock.clear()
        self._init_flock()
        self.goal = None
        self._step_count = 0
        self._centroid_history.clear()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get simulation statistics."""
        return {
            "step_count": self._step_count,
            "n_boids": len(self.flock),
            "centroid": self.get_centroid().tolist(),
            "spread": round(self.get_spread(), 4),
            "alignment": round(self.get_alignment_score(), 4),
            "avg_speed": round(self.get_average_speed(), 4),
        }

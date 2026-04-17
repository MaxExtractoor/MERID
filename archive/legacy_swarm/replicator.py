"""
Stage 4: Replicator Initiative - Dynamic agent replication for MERID swarms.
Inspired by C-sUAS (Counter-small Unmanned Aircraft Systems) self-replicating swarms.
2026 extensions: Adaptive replication based on consensus quality, resource constraints, threat detection.
"""

from __future__ import annotations

import time
import random
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from utils.logger import get_logger

logger = get_logger("swarm.replicator")


@dataclass
class ReplicatorAgent:
    """Agent with self-replication capabilities."""
    
    agent_id: str
    generation: int
    parent_id: Optional[str]
    expertise: float
    energy: float = 100.0
    replication_count: int = 0
    max_replications: int = 3
    birth_time: float = field(default_factory=time.time)
    last_replication: float = field(default_factory=time.time)
    
    def can_replicate(self, min_energy: float = 50.0, cooldown: float = 10.0) -> bool:
        """Check if agent can replicate."""
        time_since_last = time.time() - self.last_replication
        return (
            self.energy >= min_energy
            and self.replication_count < self.max_replications
            and time_since_last >= cooldown
        )
    
    def replicate(self) -> Optional[ReplicatorAgent]:
        """Create offspring agent with inherited traits."""
        if not self.can_replicate():
            return None
        
        # Energy cost for replication
        self.energy -= 30.0
        self.replication_count += 1
        self.last_replication = time.time()
        
        # Offspring inherits traits with mutation
        offspring_expertise = self.expertise + random.uniform(-0.05, 0.05)
        offspring_expertise = max(0.5, min(1.0, offspring_expertise))
        
        offspring = ReplicatorAgent(
            agent_id=f"{self.agent_id}_child_{self.replication_count}",
            generation=self.generation + 1,
            parent_id=self.agent_id,
            expertise=offspring_expertise,
            energy=80.0,  # Start with less energy than parent
            max_replications=self.max_replications,
        )
        
        logger.info(
            "Agent %s replicated → %s (gen %d, expertise %.2f)",
            self.agent_id,
            offspring.agent_id,
            offspring.generation,
            offspring.expertise,
        )
        
        return offspring
    
    def consume_energy(self, amount: float):
        """Consume energy for actions."""
        self.energy = max(0.0, self.energy - amount)
    
    def recharge_energy(self, amount: float):
        """Recharge energy (e.g., from successful consensus)."""
        self.energy = min(100.0, self.energy + amount)
    
    def is_alive(self) -> bool:
        """Check if agent has enough energy to survive."""
        return self.energy > 0.0


class ReplicatorSwarm:
    """
    Self-replicating swarm with adaptive population control.
    
    Key features:
    - Dynamic replication based on consensus quality
    - Resource-constrained population management
    - Generational diversity tracking
    - Threat-responsive scaling (increase agents under attack)
    """
    
    def __init__(
        self,
        initial_population: int = 6,
        max_population: int = 50,
        min_population: int = 3,
        replication_threshold: float = 0.8,
    ):
        self.agents: Dict[str, ReplicatorAgent] = {}
        self.max_population = max_population
        self.min_population = min_population
        self.replication_threshold = replication_threshold
        self.generation_stats: Dict[int, int] = {}
        self.total_replications = 0
        self.total_deaths = 0
        
        # Initialize founding population
        for i in range(initial_population):
            agent = ReplicatorAgent(
                agent_id=f"founder_{i}",
                generation=0,
                parent_id=None,
                expertise=random.uniform(0.7, 0.9),
            )
            self.agents[agent.agent_id] = agent
            self.generation_stats[0] = self.generation_stats.get(0, 0) + 1
        
        logger.info(
            "Replicator swarm initialized: population=%d, max=%d",
            initial_population,
            max_population,
        )
    
    def step(self, consensus_quality: float, threat_level: float = 0.0) -> Dict[str, Any]:
        """
        Execute one step of swarm evolution.
        
        Args:
            consensus_quality: Quality of recent consensus (0-1)
            threat_level: Detected threat level (0-1), triggers defensive replication
        
        Returns:
            Step statistics
        """
        # Energy dynamics
        for agent in self.agents.values():
            # Consume energy for existence
            agent.consume_energy(1.0)
            
            # Recharge based on consensus quality
            if consensus_quality > 0.7:
                agent.recharge_energy(5.0)
        
        # Remove dead agents
        dead_agents = [aid for aid, agent in self.agents.items() if not agent.is_alive()]
        for agent_id in dead_agents:
            del self.agents[agent_id]
            self.total_deaths += 1
        
        # Replication logic
        replications = 0
        
        # High consensus quality → replicate successful agents
        if consensus_quality > self.replication_threshold and len(self.agents) < self.max_population:
            # Select top performers for replication
            candidates = sorted(
                self.agents.values(),
                key=lambda a: a.expertise * (a.energy / 100.0),
                reverse=True
            )
            
            for agent in candidates[:3]:  # Top 3 agents
                if len(self.agents) >= self.max_population:
                    break
                
                offspring = agent.replicate()
                if offspring:
                    self.agents[offspring.agent_id] = offspring
                    self.generation_stats[offspring.generation] = (
                        self.generation_stats.get(offspring.generation, 0) + 1
                    )
                    replications += 1
                    self.total_replications += 1
        
        # Threat response → emergency replication
        if threat_level > 0.5 and len(self.agents) < self.max_population:
            logger.warning("Threat detected (%.2f) - emergency replication", threat_level)
            
            # Replicate all capable agents
            for agent in list(self.agents.values()):
                if len(self.agents) >= self.max_population:
                    break
                
                if agent.can_replicate(min_energy=30.0, cooldown=5.0):
                    offspring = agent.replicate()
                    if offspring:
                        self.agents[offspring.agent_id] = offspring
                        self.generation_stats[offspring.generation] = (
                            self.generation_stats.get(offspring.generation, 0) + 1
                        )
                        replications += 1
                        self.total_replications += 1
        
        # Maintain minimum population
        if len(self.agents) < self.min_population:
            logger.warning("Population below minimum - emergency spawn")
            
            while len(self.agents) < self.min_population:
                agent = ReplicatorAgent(
                    agent_id=f"emergency_{int(time.time())}_{len(self.agents)}",
                    generation=0,
                    parent_id=None,
                    expertise=random.uniform(0.6, 0.8),
                )
                self.agents[agent.agent_id] = agent
        
        pop = len(self.agents)
        return {
            "population": pop,
            "replications": replications,
            "deaths": len(dead_agents),
            "avg_energy": sum(a.energy for a in self.agents.values()) / pop if pop else 0.0,
            "avg_expertise": sum(a.expertise for a in self.agents.values()) / pop if pop else 0.0,
            "max_generation": max((a.generation for a in self.agents.values()), default=0),
            "consensus_quality": consensus_quality,
            "threat_level": threat_level,
        }
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get swarm metrics."""
        if not self.agents:
            return {
                "population": 0,
                "total_replications": self.total_replications,
                "total_deaths": self.total_deaths,
            }
        
        return {
            "population": len(self.agents),
            "total_replications": self.total_replications,
            "total_deaths": self.total_deaths,
            "avg_energy": sum(a.energy for a in self.agents.values()) / len(self.agents),
            "avg_expertise": sum(a.expertise for a in self.agents.values()) / len(self.agents),
            "avg_generation": sum(a.generation for a in self.agents.values()) / len(self.agents),
            "max_generation": max(a.generation for a in self.agents.values()),
            "generation_distribution": dict(self.generation_stats),
            "agents": [
                {
                    "agent_id": a.agent_id,
                    "generation": a.generation,
                    "expertise": a.expertise,
                    "energy": a.energy,
                    "replication_count": a.replication_count,
                    "age": time.time() - a.birth_time,
                }
                for a in sorted(self.agents.values(), key=lambda x: x.expertise, reverse=True)[:10]
            ],
        }
    
    def get_active_agents(self) -> List[ReplicatorAgent]:
        """Get list of active agents."""
        return list(self.agents.values())
    
    def inject_threat(self, threat_level: float):
        """Simulate external threat (for testing)."""
        logger.warning("Injecting threat: level=%.2f", threat_level)
        
        # Kill random agents based on threat level
        num_casualties = int(len(self.agents) * threat_level * 0.3)
        casualties = random.sample(list(self.agents.keys()), min(num_casualties, len(self.agents)))
        
        for agent_id in casualties:
            self.agents[agent_id].energy = 0.0
            logger.info("Agent %s eliminated by threat", agent_id)


class BoidSwarm:
    """
    Boids flocking algorithm for swarm coordination.
    
    Three rules:
    1. Separation: Avoid crowding neighbors
    2. Alignment: Steer towards average heading of neighbors
    3. Cohesion: Steer towards average position of neighbors
    """
    
    def __init__(self, num_boids: int = 20):
        self.boids = [
            {
                "id": i,
                "position": [random.uniform(0, 100), random.uniform(0, 100)],
                "velocity": [random.uniform(-1, 1), random.uniform(-1, 1)],
            }
            for i in range(num_boids)
        ]
        self.separation_weight = 1.5
        self.alignment_weight = 1.0
        self.cohesion_weight = 1.0
        self.max_speed = 2.0
        
        logger.info("Boid swarm initialized: num_boids=%d", num_boids)
    
    def step(self):
        """Execute one step of boid simulation."""
        for boid in self.boids:
            # Find neighbors within perception radius
            neighbors = [
                b for b in self.boids
                if b["id"] != boid["id"] and self._distance(boid, b) < 20.0
            ]
            
            if not neighbors:
                continue
            
            # Apply three rules
            separation = self._separation(boid, neighbors)
            alignment = self._alignment(boid, neighbors)
            cohesion = self._cohesion(boid, neighbors)
            
            # Update velocity
            boid["velocity"][0] += (
                separation[0] * self.separation_weight
                + alignment[0] * self.alignment_weight
                + cohesion[0] * self.cohesion_weight
            )
            boid["velocity"][1] += (
                separation[1] * self.separation_weight
                + alignment[1] * self.alignment_weight
                + cohesion[1] * self.cohesion_weight
            )
            
            # Limit speed
            speed = (boid["velocity"][0]**2 + boid["velocity"][1]**2)**0.5
            if speed > self.max_speed:
                boid["velocity"][0] = (boid["velocity"][0] / speed) * self.max_speed
                boid["velocity"][1] = (boid["velocity"][1] / speed) * self.max_speed
            
            # Update position
            boid["position"][0] += boid["velocity"][0]
            boid["position"][1] += boid["velocity"][1]
            
            # Wrap around boundaries
            boid["position"][0] = boid["position"][0] % 100
            boid["position"][1] = boid["position"][1] % 100
    
    def _distance(self, boid1: Dict, boid2: Dict) -> float:
        """Calculate distance between two boids."""
        dx = boid1["position"][0] - boid2["position"][0]
        dy = boid1["position"][1] - boid2["position"][1]
        return (dx**2 + dy**2)**0.5
    
    def _separation(self, boid: Dict, neighbors: List[Dict]) -> List[float]:
        """Separation: steer away from neighbors."""
        steer = [0.0, 0.0]
        for neighbor in neighbors:
            diff = [
                boid["position"][0] - neighbor["position"][0],
                boid["position"][1] - neighbor["position"][1],
            ]
            dist = self._distance(boid, neighbor)
            if dist > 0:
                diff[0] /= dist
                diff[1] /= dist
                steer[0] += diff[0]
                steer[1] += diff[1]
        
        if len(neighbors) > 0:
            steer[0] /= len(neighbors)
            steer[1] /= len(neighbors)
        
        return steer
    
    def _alignment(self, boid: Dict, neighbors: List[Dict]) -> List[float]:
        """Alignment: steer towards average heading."""
        avg_vel = [0.0, 0.0]
        for neighbor in neighbors:
            avg_vel[0] += neighbor["velocity"][0]
            avg_vel[1] += neighbor["velocity"][1]
        
        if len(neighbors) > 0:
            avg_vel[0] /= len(neighbors)
            avg_vel[1] /= len(neighbors)
            
            # Steer towards average
            steer = [
                avg_vel[0] - boid["velocity"][0],
                avg_vel[1] - boid["velocity"][1],
            ]
            return steer
        
        return [0.0, 0.0]
    
    def _cohesion(self, boid: Dict, neighbors: List[Dict]) -> List[float]:
        """Cohesion: steer towards average position."""
        avg_pos = [0.0, 0.0]
        for neighbor in neighbors:
            avg_pos[0] += neighbor["position"][0]
            avg_pos[1] += neighbor["position"][1]
        
        if len(neighbors) > 0:
            avg_pos[0] /= len(neighbors)
            avg_pos[1] /= len(neighbors)
            
            # Steer towards average position
            steer = [
                avg_pos[0] - boid["position"][0],
                avg_pos[1] - boid["position"][1],
            ]
            return steer
        
        return [0.0, 0.0]
    
    def get_snapshot(self) -> Dict[str, Any]:
        """Get current swarm state."""
        return {
            "num_boids": len(self.boids),
            "boids": self.boids[:20],  # Limit for API response
            "avg_speed": sum(
                (b["velocity"][0]**2 + b["velocity"][1]**2)**0.5
                for b in self.boids
            ) / len(self.boids) if self.boids else 0.0,
        }

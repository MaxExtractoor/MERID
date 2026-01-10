"""
Stage 9: Stable Baselines3 (SB3) integration for MARL in MERID.
Wrapper for PettingZoo-compatible multi-agent environment with SB3 PPO/DQN.
2026 version: SB3 2.3+ with SuperSuit preprocessing and parallel training.
"""

from __future__ import annotations

import numpy as np
from typing import Dict, List, Optional, Any, Tuple
from gymnasium import spaces
import gymnasium as gym

from utils.logger import get_logger

logger = get_logger("swarm.sb3_wrapper")


class MERIDMultiAgentEnv(gym.Env):
    """
    PettingZoo-compatible environment for MERID swarm simulation.
    
    Wraps MERID simulation as multi-agent RL environment for SB3 training.
    Each agent observes local state and takes actions to maximize consensus quality.
    """
    
    metadata = {"render_modes": ["human"], "name": "merid_swarm_v1"}
    
    def __init__(
        self,
        num_agents: int = 6,
        obs_size: int = 20,
        action_size: int = 4,
        max_steps: int = 100,
    ):
        super().__init__()
        
        self.num_agents = num_agents
        self.obs_size = obs_size
        self.action_size = action_size
        self.max_steps = max_steps
        
        # Agent identifiers
        self.agents = [f"agent_{i}" for i in range(num_agents)]
        self.possible_agents = self.agents.copy()
        
        # Observation space: continuous state vector per agent
        self.observation_space = spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=(obs_size,),
            dtype=np.float32
        )
        
        # Action space: discrete actions (e.g., vote YES, vote NO, abstain, request more data)
        self.action_space = spaces.Discrete(action_size)
        
        # Episode state
        self.current_step = 0
        self.agent_states = {}
        self.done = False
        
        logger.info(
            "MERID multi-agent environment initialized: agents=%d, obs_size=%d, action_size=%d",
            num_agents,
            obs_size,
            action_size,
        )
    
    def reset(self, seed: Optional[int] = None, options: Optional[Dict] = None) -> Tuple[Dict[str, np.ndarray], Dict[str, Any]]:
        """Reset environment for new episode."""
        super().reset(seed=seed)
        
        self.current_step = 0
        self.done = False
        
        # Initialize agent states (mock market data + agent-specific features)
        observations = {}
        for agent_id in self.agents:
            observations[agent_id] = self._generate_observation(agent_id)
        
        self.agent_states = observations
        
        info = {"step": self.current_step}
        
        return observations, info
    
    def step(self, actions: Dict[str, int]) -> Tuple[
        Dict[str, np.ndarray],
        Dict[str, float],
        Dict[str, bool],
        Dict[str, bool],
        Dict[str, Any]
    ]:
        """
        Execute one step of the environment.
        
        Returns:
            observations: Next observations for each agent
            rewards: Rewards for each agent
            terminations: Whether each agent is done
            truncations: Whether episode was truncated
            infos: Additional info
        """
        self.current_step += 1
        
        # Simulate consensus process
        consensus_quality = self._compute_consensus_quality(actions)
        
        # Generate rewards based on consensus quality
        rewards = {}
        for agent_id in self.agents:
            # Shared reward: all agents get same reward based on consensus quality
            # Individual penalty: agents who deviate from consensus get penalty
            agent_action = actions.get(agent_id, 0)
            majority_action = max(set(actions.values()), key=list(actions.values()).count)
            
            base_reward = consensus_quality
            alignment_bonus = 0.1 if agent_action == majority_action else -0.1
            
            rewards[agent_id] = base_reward + alignment_bonus
        
        # Generate next observations
        observations = {}
        for agent_id in self.agents:
            observations[agent_id] = self._generate_observation(agent_id)
        
        self.agent_states = observations
        
        # Check if episode is done
        self.done = self.current_step >= self.max_steps or consensus_quality > 0.9
        
        terminations = {agent_id: self.done for agent_id in self.agents}
        truncations = {agent_id: False for agent_id in self.agents}
        
        infos = {
            agent_id: {
                "step": self.current_step,
                "consensus_quality": consensus_quality,
            }
            for agent_id in self.agents
        }
        
        return observations, rewards, terminations, truncations, infos
    
    def _generate_observation(self, agent_id: str) -> np.ndarray:
        """Generate observation for agent (mock market state + agent features)."""
        # Mock observation: market prices, volatility, agent expertise, etc.
        obs = np.random.randn(self.obs_size).astype(np.float32)
        
        # Add some structure: first 10 features are market data, last 10 are agent-specific
        obs[:10] = np.random.uniform(0.3, 0.7, 10)  # Market probabilities
        obs[10:] = np.random.uniform(0.5, 1.0, 10)  # Agent expertise/confidence
        
        return obs
    
    def _compute_consensus_quality(self, actions: Dict[str, int]) -> float:
        """
        Compute quality of consensus based on agent actions.
        
        High quality = agents agree + actions are confident
        Low quality = agents disagree or actions are uncertain
        """
        action_list = list(actions.values())
        
        # Measure agreement (entropy of action distribution)
        action_counts = {}
        for action in action_list:
            action_counts[action] = action_counts.get(action, 0) + 1
        
        # Normalized entropy (0 = perfect agreement, 1 = maximum disagreement)
        total = len(action_list)
        entropy = 0.0
        for count in action_counts.values():
            p = count / total
            if p > 0:
                entropy -= p * np.log(p)
        
        max_entropy = np.log(self.action_size)
        normalized_entropy = entropy / max_entropy if max_entropy > 0 else 0
        
        # Consensus quality = 1 - entropy (higher is better)
        consensus_quality = 1.0 - normalized_entropy
        
        return consensus_quality
    
    def render(self):
        """Render environment (optional)."""
        if self.current_step % 10 == 0:
            logger.info("Step %d/%d", self.current_step, self.max_steps)


def train_sb3_marl(
    num_agents: int = 6,
    total_timesteps: int = 100000,
    n_envs: int = 4,
    algorithm: str = "ppo",
) -> Any:
    """
    Train MARL agents using Stable Baselines3.
    
    Args:
        num_agents: Number of agents in swarm
        total_timesteps: Total training timesteps
        n_envs: Number of parallel environments
        algorithm: Algorithm to use (ppo, dqn)
    
    Returns:
        Trained model
    """
    try:
        from stable_baselines3 import PPO, DQN
        from stable_baselines3.common.env_util import make_vec_env
        from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv
    except ImportError:
        logger.error("Stable Baselines3 not installed. Run: pip install stable-baselines3")
        return None
    
    # Create vectorized environment
    def make_env():
        return MERIDMultiAgentEnv(num_agents=num_agents)
    
    vec_env = make_vec_env(make_env, n_envs=n_envs, vec_env_cls=SubprocVecEnv)
    
    # Initialize model
    if algorithm.lower() == "ppo":
        model = PPO(
            "MlpPolicy",
            vec_env,
            verbose=1,
            n_steps=2048,
            batch_size=64,
            learning_rate=3e-4,
            ent_coef=0.01,
            clip_range=0.2,
        )
        logger.info("Training MARL with PPO")
    elif algorithm.lower() == "dqn":
        model = DQN(
            "MlpPolicy",
            vec_env,
            verbose=1,
            learning_rate=1e-4,
            buffer_size=100000,
            learning_starts=1000,
            batch_size=32,
            tau=0.005,
            gamma=0.99,
            exploration_fraction=0.1,
            exploration_final_eps=0.02,
        )
        logger.info("Training MARL with DQN")
    else:
        logger.error("Unknown algorithm: %s", algorithm)
        return None
    
    # Train
    logger.info("Starting training for %d timesteps", total_timesteps)
    model.learn(total_timesteps=total_timesteps)
    
    # Save model
    model_path = f"models/merid_marl_{algorithm}_{total_timesteps}"
    model.save(model_path)
    logger.info("Model saved to %s", model_path)
    
    return model


def evaluate_sb3_model(model: Any, num_episodes: int = 10) -> Dict[str, float]:
    """
    Evaluate trained SB3 model.
    
    Args:
        model: Trained SB3 model
        num_episodes: Number of evaluation episodes
    
    Returns:
        Evaluation metrics
    """
    env = MERIDMultiAgentEnv()
    
    total_rewards = []
    episode_lengths = []
    
    for episode in range(num_episodes):
        obs, _ = env.reset()
        episode_reward = 0
        episode_length = 0
        done = False
        
        while not done:
            # Get actions from model for all agents
            actions = {}
            for agent_id in env.agents:
                action, _ = model.predict(obs[agent_id], deterministic=True)
                actions[agent_id] = int(action)
            
            obs, rewards, terminations, truncations, infos = env.step(actions)
            
            episode_reward += sum(rewards.values())
            episode_length += 1
            done = all(terminations.values())
        
        total_rewards.append(episode_reward)
        episode_lengths.append(episode_length)
        
        logger.info(
            "Episode %d: reward=%.2f, length=%d",
            episode + 1,
            episode_reward,
            episode_length,
        )
    
    return {
        "mean_reward": np.mean(total_rewards),
        "std_reward": np.std(total_rewards),
        "mean_episode_length": np.mean(episode_lengths),
        "num_episodes": num_episodes,
    }


def load_sb3_model(model_path: str, algorithm: str = "ppo") -> Any:
    """Load trained SB3 model from disk."""
    try:
        from stable_baselines3 import PPO, DQN
    except ImportError:
        logger.error("Stable Baselines3 not installed")
        return None
    
    if algorithm.lower() == "ppo":
        model = PPO.load(model_path)
    elif algorithm.lower() == "dqn":
        model = DQN.load(model_path)
    else:
        logger.error("Unknown algorithm: %s", algorithm)
        return None
    
    logger.info("Loaded model from %s", model_path)
    return model

"""RollingBuffer for Signal Generation Bias Prevention

CRITICAL FIX (2026-07-17): Implements fixed-size circular buffer to prevent lookahead bias.
This ensures operators only access historical data within their declared lookback window,
preventing accidental access to future data.

Architecture:
- RollingBuffer: Fixed-size circular buffer with lookback enforcement
- InputDeclaration: Explicit lookback contracts for operators
- WarmupCalculator: Automatic warmup calculation for graph initialization

Based on industry best practices from ClyptQ and quantitative trading research.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple
from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class InputDeclaration:
    """Explicit lookback contract for an operator input.
    
    This enforces that operators declare exactly how much history they need,
    preventing accidental access to future data.
    """
    name: str
    lookback: int  # Number of historical ticks required
    dtype: type = float
    
    def __post_init__(self):
        if self.lookback <= 0:
            raise ValueError(f"Lookback must be positive, got {self.lookback}")


class RollingBuffer:
    """Fixed-size circular buffer for historical data.
    
    Key properties:
    - Pre-allocated to exactly lookback slots
    - Overwrites itself circularly (no array of future data)
    - Only contains past data (no lookahead possible)
    - Thread-safe for concurrent access
    
    This structural guarantee makes lookahead bias physically impossible.
    """
    
    def __init__(self, lookback: int, dtype: type = float):
        """
        Initialize rolling buffer.
        
        Args:
            lookback: Number of historical ticks to store
            dtype: Data type for buffer elements
        """
        if lookback <= 0:
            raise ValueError(f"Lookback must be positive, got {lookback}")
        
        self._lookback = lookback
        self._dtype = dtype
        self._buffer: deque = deque(maxlen=lookback)
        self._lock = threading.RLock()
        self._filled = False
        
        logger.debug(f"[ROLLING-BUFFER] Initialized with lookback={lookback}, dtype={dtype}")
    
    @property
    def lookback(self) -> int:
        """Get the lookback window size."""
        return self._lookback
    
    @property
    def is_filled(self) -> bool:
        """Check if buffer has enough data to satisfy lookback."""
        with self._lock:
            return len(self._buffer) >= self._lookback
    
    def append(self, value: Any) -> None:
        """
        Append a new value to the buffer.
        
        If buffer is full, oldest value is automatically discarded (circular).
        
        Args:
            value: Value to append
        """
        with self._lock:
            self._buffer.append(value)
            if len(self._buffer) >= self._lookback:
                self._filled = True
    
    def get(self, index: int = -1) -> Any:
        """
        Get a value from the buffer.
        
        Args:
            index: Index to retrieve (0 = oldest, -1 = most recent)
                   Must be within [-lookback, 0]
        
        Returns:
            Value at index
        
        Raises:
            IndexError: If index is out of bounds or buffer not filled
        """
        with self._lock:
            if not self._filled:
                raise IndexError(f"Buffer not filled yet (need {self._lookback} values)")
            
            if abs(index) > self._lookback:
                raise IndexError(
                    f"Index {index} out of bounds for lookback {self._lookback}"
                )
            
            return self._buffer[index]
    
    def get_slice(self, start: int = 0, end: Optional[int] = None) -> List[Any]:
        """
        Get a slice of values from the buffer.
        
        Args:
            start: Start index (inclusive)
            end: End index (exclusive), None means all remaining
        
        Returns:
            List of values in the slice
        """
        with self._lock:
            if not self._filled:
                raise IndexError(f"Buffer not filled yet (need {self._lookback} values)")
            
            buffer_list = list(self._buffer)
            return buffer_list[start:end]
    
    def to_list(self) -> List[Any]:
        """
        Get all values in the buffer as a list (oldest to newest).
        
        Returns:
            List of all values
        """
        with self._lock:
            return list(self._buffer)
    
    def clear(self) -> None:
        """Clear the buffer."""
        with self._lock:
            self._buffer.clear()
            self._filled = False
    
    def __len__(self) -> int:
        """Get current number of values in buffer."""
        with self._lock:
            return len(self._buffer)
    
    def __repr__(self) -> str:
        """String representation."""
        with self._lock:
            return f"RollingBuffer(lookback={self._lookback}, filled={self._filled}, size={len(self._buffer)})"


class WarmupCalculator:
    """Calculates warmup requirements for a computation graph.
    
    This ensures all operators have sufficient history before trading begins,
    preventing early trades with insufficient data.
    """
    
    def __init__(self):
        self._dependencies: Dict[str, List[str]] = {}  # node -> dependencies
        self._lookbacks: Dict[str, int] = {}  # node -> lookback requirement
    
    def add_node(self, node_id: str, lookback: int, dependencies: Optional[List[str]] = None) -> None:
        """
        Add a node to the computation graph.
        
        Args:
            node_id: Unique identifier for the node
            lookback: Lookback requirement for this node
            dependencies: List of node IDs this node depends on
        """
        self._lookbacks[node_id] = lookback
        self._dependencies[node_id] = dependencies or []
        logger.debug(f"[WARMUP] Added node {node_id} with lookback={lookback}, deps={dependencies}")
    
    def calculate_warmup(self, root_nodes: List[str]) -> int:
        """
        Calculate required warmup ticks for the graph.
        
        Algorithm:
        1. Trace backward from root nodes through dependencies
        2. Accumulate lookback values along each path
        3. Take maximum across all paths
        4. Add 5% safety buffer
        
        Args:
            root_nodes: List of root node IDs to start from
        
        Returns:
            Required warmup ticks
        """
        max_warmup = 0
        
        for root in root_nodes:
            warmup = self._calculate_path_warmup(root, visited=set())
            max_warmup = max(max_warmup, warmup)
        
        # Add 5% safety buffer
        warmup_with_buffer = int(max_warmup * 1.05)
        
        logger.info(
            f"[WARMUP] Calculated warmup: {max_warmup} ticks "
            f"(with 5% buffer: {warmup_with_buffer} ticks)"
        )
        
        return warmup_with_buffer
    
    def _calculate_path_warmup(self, node_id: str, visited: set) -> int:
        """Calculate warmup for a single path."""
        if node_id in visited:
            return 0  # Cycle detected, skip
        
        visited.add(node_id)
        
        node_lookback = self._lookbacks.get(node_id, 0)
        dependencies = self._dependencies.get(node_id, [])
        
        if not dependencies:
            return node_lookback
        
        max_dep_warmup = 0
        for dep in dependencies:
            dep_warmup = self._calculate_path_warmup(dep, visited.copy())
            max_dep_warmup = max(max_dep_warmup, dep_warmup)
        
        # Total warmup = node lookback + max dependency warmup - 1 (overlap)
        total_warmup = node_lookback + max_dep_warmup - 1
        return max(total_warmup, node_lookback)


class SignalGeneratorWithBuffers:
    """Signal generator with RollingBuffer integration.
    
    This wraps signal generation logic with bias prevention guarantees:
    - All inputs go through RollingBuffers
    - Warmup is calculated automatically
    - No access to future data is possible
    """
    
    def __init__(self):
        self._buffers: Dict[str, RollingBuffer] = {}
        self._input_declarations: Dict[str, InputDeclaration] = {}
        self._warmup_calculator = WarmupCalculator()
        self._warmup_complete = False
        
        logger.info("[SIGNAL-GENERATOR] Initialized with bias prevention")
    
    def declare_input(self, name: str, lookback: int, dtype: type = float) -> None:
        """
        Declare an input with explicit lookback.
        
        Args:
            name: Input name
            lookback: Lookback window size
            dtype: Data type
        """
        declaration = InputDeclaration(name=name, lookback=lookback, dtype=dtype)
        self._input_declarations[name] = declaration
        self._buffers[name] = RollingBuffer(lookback=lookback, dtype=dtype)
        self._warmup_calculator.add_node(name, lookback=lookback)
        
        logger.info(f"[SIGNAL-GENERATOR] Declared input {name} with lookback={lookback}")
    
    def update_input(self, name: str, value: Any) -> None:
        """
        Update an input with a new value.
        
        Args:
            name: Input name
            value: New value
        """
        if name not in self._buffers:
            raise ValueError(f"Input {name} not declared")
        
        self._buffers[name].append(value)
    
    def is_warmup_complete(self) -> bool:
        """Check if all buffers have sufficient data."""
        return all(buffer.is_filled for buffer in self._buffers.values())
    
    def get_input_data(self, name: str) -> List[Any]:
        """
        Get historical data for an input.
        
        Args:
            name: Input name
        
        Returns:
            List of historical values (oldest to newest)
        """
        if name not in self._buffers:
            raise ValueError(f"Input {name} not declared")
        
        if not self._buffers[name].is_filled:
            raise ValueError(f"Input {name} buffer not filled yet")
        
        return self._buffers[name].to_list()
    
    def calculate_warmup(self) -> int:
        """Calculate required warmup ticks."""
        return self._warmup_calculator.calculate_warmup(list(self._input_declarations.keys()))
    
    def complete_warmup(self) -> None:
        """Mark warmup as complete."""
        self._warmup_complete = True
        logger.info("[SIGNAL-GENERATOR] Warmup complete - trading enabled")
    
    def can_generate_signal(self) -> bool:
        """Check if signal generation is allowed (warmup complete)."""
        return self._warmup_complete and self.is_warmup_complete()


# Convenience function for creating a signal generator with common crypto inputs
def create_crypto_signal_generator() -> SignalGeneratorWithBuffers:
    """
    Create a signal generator with standard crypto trading inputs.
    
    Returns:
        SignalGeneratorWithBuffers with common lookback windows
    """
    generator = SignalGeneratorWithBuffers()
    
    # Standard lookback windows for crypto trading
    generator.declare_input("spot_price", lookback=20, dtype=float)  # 20 ticks
    generator.declare_input("volume", lookback=20, dtype=float)
    generator.declare_input("sma_5m", lookback=100, dtype=float)  # 100 ticks
    generator.declare_input("sma_1h", lookback=300, dtype=float)  # 300 ticks
    generator.declare_input("volatility", lookback=50, dtype=float)
    generator.declare_input("adx", lookback=14, dtype=float)  # ADX period
    
    return generator

"""Tests for RollingBuffer signal generation bias prevention.

CRITICAL FIX (2026-07-17): Tests for lookahead bias prevention via RollingBuffer.
"""

import pytest
from merid.prediction.rolling_buffer import (
    RollingBuffer,
    InputDeclaration,
    WarmupCalculator,
    SignalGeneratorWithBuffers,
    create_crypto_signal_generator,
)


class TestRollingBuffer:
    """Test RollingBuffer functionality."""
    
    def test_initialization(self):
        """Test buffer initialization."""
        buffer = RollingBuffer(lookback=20, dtype=float)
        
        assert buffer.lookback == 20
        assert buffer.is_filled is False
        assert len(buffer) == 0
    
    def test_append(self):
        """Test appending values."""
        buffer = RollingBuffer(lookback=5, dtype=float)
        
        buffer.append(1.0)
        buffer.append(2.0)
        buffer.append(3.0)
        
        assert len(buffer) == 3
        assert buffer.is_filled is False
    
    def test_circular_overwrite(self):
        """Test circular overwrite when buffer is full."""
        buffer = RollingBuffer(lookback=3, dtype=float)
        
        buffer.append(1.0)
        buffer.append(2.0)
        buffer.append(3.0)
        buffer.append(4.0)  # Should overwrite 1.0
        
        assert len(buffer) == 3
        assert buffer.is_filled is True
        assert buffer.get(-1) == 4.0  # Most recent
        assert buffer.get(0) == 2.0  # Oldest (1.0 was overwritten)
    
    def test_get_index(self):
        """Test getting values by index."""
        buffer = RollingBuffer(lookback=5, dtype=float)
        
        for i in range(5):
            buffer.append(float(i))
        
        assert buffer.get(-1) == 4.0  # Most recent
        assert buffer.get(0) == 0.0  # Oldest
        assert buffer.get(-2) == 3.0
    
    def test_get_index_out_of_bounds(self):
        """Test getting value with out of bounds index."""
        buffer = RollingBuffer(lookback=5, dtype=float)
        
        for i in range(5):
            buffer.append(float(i))
        
        # Test index beyond lookback
        with pytest.raises(IndexError):
            buffer.get(-6)  # Out of bounds (abs(-6) = 6 > 5)
    
    def test_get_when_not_filled(self):
        """Test getting value when buffer not filled."""
        buffer = RollingBuffer(lookback=5, dtype=float)
        
        buffer.append(1.0)
        
        with pytest.raises(IndexError):
            buffer.get(-1)
    
    def test_get_slice(self):
        """Test getting slice of values."""
        buffer = RollingBuffer(lookback=5, dtype=float)
        
        for i in range(5):
            buffer.append(float(i))
        
        slice_result = buffer.get_slice(0, 3)
        assert slice_result == [0.0, 1.0, 2.0]
    
    def test_to_list(self):
        """Test converting to list."""
        buffer = RollingBuffer(lookback=5, dtype=float)
        
        for i in range(3):
            buffer.append(float(i))
        
        result = buffer.to_list()
        assert result == [0.0, 1.0, 2.0]
    
    def test_clear(self):
        """Test clearing buffer."""
        buffer = RollingBuffer(lookback=5, dtype=float)
        
        for i in range(5):
            buffer.append(float(i))
        
        buffer.clear()
        
        assert len(buffer) == 0
        assert buffer.is_filled is False
    
    def test_invalid_lookback(self):
        """Test that invalid lookback raises error."""
        with pytest.raises(ValueError):
            RollingBuffer(lookback=0, dtype=float)
        
        with pytest.raises(ValueError):
            RollingBuffer(lookback=-1, dtype=float)


class TestInputDeclaration:
    """Test InputDeclaration."""
    
    def test_valid_declaration(self):
        """Test valid input declaration."""
        decl = InputDeclaration(name="spot_price", lookback=20, dtype=float)
        
        assert decl.name == "spot_price"
        assert decl.lookback == 20
        assert decl.dtype == float
    
    def test_invalid_lookback(self):
        """Test that invalid lookback raises error."""
        with pytest.raises(ValueError):
            InputDeclaration(name="test", lookback=0, dtype=float)
        
        with pytest.raises(ValueError):
            InputDeclaration(name="test", lookback=-1, dtype=float)


class TestWarmupCalculator:
    """Test WarmupCalculator."""
    
    def test_add_node(self):
        """Test adding a node."""
        calc = WarmupCalculator()
        
        calc.add_node("node1", lookback=20, dependencies=[])
        
        assert "node1" in calc._lookbacks
        assert calc._lookbacks["node1"] == 20
    
    def test_calculate_warmup_single_node(self):
        """Test warmup calculation for single node."""
        calc = WarmupCalculator()
        
        calc.add_node("node1", lookback=20, dependencies=[])
        
        warmup = calc.calculate_warmup(["node1"])
        
        # 20 + 5% buffer = 21
        assert warmup == 21
    
    def test_calculate_warmup_with_dependencies(self):
        """Test warmup calculation with dependencies."""
        calc = WarmupCalculator()
        
        calc.add_node("node1", lookback=10, dependencies=[])
        calc.add_node("node2", lookback=20, dependencies=["node1"])
        
        warmup = calc.calculate_warmup(["node2"])
        
        # node2 (20) + node1 (10) - 1 (overlap) = 29
        # 29 + 5% buffer = 30.45 -> 30
        assert warmup == 30
    
    def test_calculate_warmup_multiple_paths(self):
        """Test warmup calculation with multiple paths."""
        calc = WarmupCalculator()
        
        calc.add_node("node1", lookback=10, dependencies=[])
        calc.add_node("node2", lookback=20, dependencies=["node1"])
        calc.add_node("node3", lookback=30, dependencies=["node1"])
        
        warmup = calc.calculate_warmup(["node2", "node3"])
        
        # Should take maximum of both paths
        # node3 path: 30 + 10 - 1 = 39
        # 39 + 5% buffer = 40.95 -> 40 (implementation uses floor)
        assert warmup == 40


class TestSignalGeneratorWithBuffers:
    """Test SignalGeneratorWithBuffers."""
    
    def test_declare_input(self):
        """Test declaring an input."""
        gen = SignalGeneratorWithBuffers()
        
        gen.declare_input("spot_price", lookback=20, dtype=float)
        
        assert "spot_price" in gen._input_declarations
        assert "spot_price" in gen._buffers
        assert gen._buffers["spot_price"].lookback == 20
    
    def test_update_input(self):
        """Test updating an input."""
        gen = SignalGeneratorWithBuffers()
        
        gen.declare_input("spot_price", lookback=5, dtype=float)
        
        gen.update_input("spot_price", 50.0)
        gen.update_input("spot_price", 51.0)
        
        assert len(gen._buffers["spot_price"]) == 2
    
    def test_update_undeclared_input(self):
        """Test updating undeclared input raises error."""
        gen = SignalGeneratorWithBuffers()
        
        with pytest.raises(ValueError):
            gen.update_input("spot_price", 50.0)
    
    def test_is_warmup_complete(self):
        """Test warmup completion check."""
        gen = SignalGeneratorWithBuffers()
        
        gen.declare_input("spot_price", lookback=5, dtype=float)
        
        assert gen.is_warmup_complete() is False
        
        for i in range(5):
            gen.update_input("spot_price", float(i))
        
        assert gen.is_warmup_complete() is True
    
    def test_get_input_data(self):
        """Test getting input data."""
        gen = SignalGeneratorWithBuffers()
        
        gen.declare_input("spot_price", lookback=5, dtype=float)
        
        for i in range(5):
            gen.update_input("spot_price", float(i))
        
        data = gen.get_input_data("spot_price")
        
        assert data == [0.0, 1.0, 2.0, 3.0, 4.0]
    
    def test_get_input_data_not_filled(self):
        """Test getting data when buffer not filled."""
        gen = SignalGeneratorWithBuffers()
        
        gen.declare_input("spot_price", lookback=5, dtype=float)
        
        gen.update_input("spot_price", 50.0)
        
        with pytest.raises(ValueError):
            gen.get_input_data("spot_price")
    
    def test_calculate_warmup(self):
        """Test warmup calculation."""
        gen = SignalGeneratorWithBuffers()
        
        gen.declare_input("spot_price", lookback=20, dtype=float)
        gen.declare_input("volume", lookback=20, dtype=float)
        
        warmup = gen.calculate_warmup()
        
        # 20 + 5% buffer = 21
        assert warmup == 21
    
    def test_complete_warmup(self):
        """Test marking warmup as complete."""
        gen = SignalGeneratorWithBuffers()
        
        assert gen._warmup_complete is False
        
        gen.complete_warmup()
        
        assert gen._warmup_complete is True
    
    def test_can_generate_signal(self):
        """Test signal generation permission."""
        gen = SignalGeneratorWithBuffers()
        
        gen.declare_input("spot_price", lookback=5, dtype=float)
        
        # Not warmup complete, buffer not filled
        assert gen.can_generate_signal() is False
        
        # Warmup complete, but buffer not filled
        gen.complete_warmup()
        assert gen.can_generate_signal() is False
        
        # Both warmup complete and buffer filled
        for i in range(5):
            gen.update_input("spot_price", float(i))
        assert gen.can_generate_signal() is True


class TestCryptoSignalGenerator:
    """Test crypto signal generator factory."""
    
    def test_create_crypto_signal_generator(self):
        """Test creating crypto signal generator."""
        gen = create_crypto_signal_generator()
        
        # Should have standard inputs
        assert "spot_price" in gen._buffers
        assert "volume" in gen._buffers
        assert "sma_5m" in gen._buffers
        assert "sma_1h" in gen._buffers
        assert "volatility" in gen._buffers
        assert "adx" in gen._buffers
        
        # Check lookback values
        assert gen._buffers["spot_price"].lookback == 20
        assert gen._buffers["sma_1h"].lookback == 300


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

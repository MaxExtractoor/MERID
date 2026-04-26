import {
  validateSymbol,
  validateSize,
  validatePrice,
  validateLeverage,
  validateOrderType,
  validateOrderSide,
  validateVenue,
  validateEmail,
  validatePassword,
  validateOrderTicket,
} from '../validators';

describe('validators', () => {
  describe('validateSymbol', () => {
    it('validates correct symbols', () => {
      expect(validateSymbol('BTC/USD')).toEqual({ valid: true });
      expect(validateSymbol('ETH-USD')).toEqual({ valid: true });
      expect(validateSymbol('SOLUSD')).toEqual({ valid: true });
    });

    it('rejects invalid symbols', () => {
      expect(validateSymbol('')).toEqual({ 
        valid: false, 
        error: 'Symbol is required' 
      });
      expect(validateSymbol('BTC')).toEqual({ 
        valid: false, 
        error: 'Invalid symbol format' 
      });
      expect(validateSymbol('BTC/USD/ETH')).toEqual({ 
        valid: false, 
        error: 'Invalid symbol format' 
      });
    });

    it('handles null/undefined', () => {
      expect(validateSymbol(null)).toEqual({ 
        valid: false, 
        error: 'Symbol is required' 
      });
      expect(validateSymbol(undefined)).toEqual({ 
        valid: false, 
        error: 'Symbol is required' 
      });
    });
  });

  describe('validateSize', () => {
    it('validates correct sizes', () => {
      expect(validateSize(1.5)).toEqual({ valid: true });
      expect(validateSize(1000)).toEqual({ valid: true });
      expect(validateSize(0.001)).toEqual({ valid: true });
    });

    it('rejects invalid sizes', () => {
      expect(validateSize(0)).toEqual({ 
        valid: false, 
        error: 'Size must be greater than 0' 
      });
      expect(validateSize(-1)).toEqual({ 
        valid: false, 
        error: 'Size must be greater than 0' 
      });
      expect(validateSize(NaN)).toEqual({ 
        valid: false, 
        error: 'Size must be a valid number' 
      });
    });

    it('respects minimum size', () => {
      expect(validateSize(0.005, { minSize: 0.01 })).toEqual({ 
        valid: false, 
        error: 'Minimum size is 0.01' 
      });
      expect(validateSize(0.01, { minSize: 0.01 })).toEqual({ valid: true });
    });

    it('respects maximum size', () => {
      expect(validateSize(1500, { maxSize: 1000 })).toEqual({ 
        valid: false, 
        error: 'Maximum size is 1000' 
      });
      expect(validateSize(1000, { maxSize: 1000 })).toEqual({ valid: true });
    });
  });

  describe('validatePrice', () => {
    it('validates correct prices', () => {
      expect(validatePrice(45000)).toEqual({ valid: true });
      expect(validatePrice(1.2345)).toEqual({ valid: true });
    });

    it('rejects invalid prices', () => {
      expect(validatePrice(0)).toEqual({ 
        valid: false, 
        error: 'Price must be greater than 0' 
      });
      expect(validatePrice(-1)).toEqual({ 
        valid: false, 
        error: 'Price must be greater than 0' 
      });
      expect(validatePrice(NaN)).toEqual({ 
        valid: false, 
        error: 'Price must be a valid number' 
      });
    });

    it('respects precision limits', () => {
      expect(validatePrice(1.12345, { maxPrecision: 2 })).toEqual({ 
        valid: false, 
        error: 'Price precision too high (max 2 decimal places)' 
      });
      expect(validatePrice(1.12, { maxPrecision: 2 })).toEqual({ valid: true });
    });
  });

  describe('validateLeverage', () => {
    it('validates correct leverage', () => {
      expect(validateLeverage(1)).toEqual({ valid: true });
      expect(validateLeverage(3)).toEqual({ valid: true });
      expect(validateLeverage(10)).toEqual({ valid: true });
    });

    it('rejects invalid leverage', () => {
      expect(validateLeverage(0)).toEqual({ 
        valid: false, 
        error: 'Leverage must be at least 1' 
      });
      expect(validateLeverage(-1)).toEqual({ 
        valid: false, 
        error: 'Leverage must be at least 1' 
      });
      expect(validateLeverage(NaN)).toEqual({ 
        valid: false, 
        error: 'Leverage must be a valid number' 
      });
    });

    it('respects maximum leverage', () => {
      expect(validateLeverage(150, { maxLeverage: 100 })).toEqual({ 
        valid: false, 
        error: 'Maximum leverage is 100' 
      });
      expect(validateLeverage(100, { maxLeverage: 100 })).toEqual({ valid: true });
    });
  });

  describe('validateOrderType', () => {
    it('validates correct order types', () => {
      expect(validateOrderType('market')).toEqual({ valid: true });
      expect(validateOrderType('limit')).toEqual({ valid: true });
      expect(validateOrderType('stop')).toEqual({ valid: true });
      expect(validateOrderType('stop_limit')).toEqual({ valid: true });
    });

    it('rejects invalid order types', () => {
      expect(validateOrderType('')).toEqual({ 
        valid: false, 
        error: 'Order type is required' 
      });
      expect(validateOrderType('invalid')).toEqual({ 
        valid: false, 
        error: 'Invalid order type' 
      });
    });

    it('handles case insensitive', () => {
      expect(validateOrderType('MARKET')).toEqual({ valid: true });
      expect(validateOrderType('Limit')).toEqual({ valid: true });
    });
  });

  describe('validateOrderSide', () => {
    it('validates correct order sides', () => {
      expect(validateOrderSide('buy')).toEqual({ valid: true });
      expect(validateOrderSide('sell')).toEqual({ valid: true });
    });

    it('rejects invalid order sides', () => {
      expect(validateOrderSide('')).toEqual({ 
        valid: false, 
        error: 'Order side is required' 
      });
      expect(validateOrderSide('hold')).toEqual({ 
        valid: false, 
        error: 'Order side must be buy or sell' 
      });
    });

    it('handles case insensitive', () => {
      expect(validateOrderSide('BUY')).toEqual({ valid: true });
      expect(validateOrderSide('SELL')).toEqual({ valid: true });
    });
  });

  describe('validateVenue', () => {
    it('validates correct venues', () => {
      expect(validateVenue('kalshi')).toEqual({ valid: true });
      expect(validateVenue('KALSHI')).toEqual({ valid: true });
    });

    it('rejects invalid venues', () => {
      expect(validateVenue('')).toEqual({ 
        valid: false, 
        error: 'Venue is required' 
      });
      expect(validateVenue('invalid')).toEqual({ 
        valid: false, 
        error: 'Invalid venue' 
      });
      expect(validateVenue('coinbase')).toEqual({ 
        valid: false, 
        error: 'Invalid venue' 
      });
    });

    it('supports custom venues', () => {
      expect(validateVenue('custom_venue', { venues: ['custom_venue'] })).toEqual({ valid: true });
      expect(validateVenue('custom_venue', { venues: ['coinbase', 'kraken'] })).toEqual({ 
        valid: false, 
        error: 'Invalid venue' 
      });
    });
  });

  describe('validateEmail', () => {
    it('validates correct emails', () => {
      expect(validateEmail('test@example.com')).toEqual({ valid: true });
      expect(validateEmail('user.name+tag@domain.co.uk')).toEqual({ valid: true });
    });

    it('rejects invalid emails', () => {
      expect(validateEmail('')).toEqual({ 
        valid: false, 
        error: 'Email is required' 
      });
      expect(validateEmail('invalid')).toEqual({ 
        valid: false, 
        error: 'Invalid email format' 
      });
      expect(validateEmail('test@')).toEqual({ 
        valid: false, 
        error: 'Invalid email format' 
      });
      expect(validateEmail('@example.com')).toEqual({ 
        valid: false, 
        error: 'Invalid email format' 
      });
    });
  });

  describe('validatePassword', () => {
    it('validates correct passwords', () => {
      expect(validatePassword('SecurePass123!')).toEqual({ valid: true });
      expect(validatePassword('MyP@ssw0rd')).toEqual({ valid: true });
    });

    it('rejects weak passwords', () => {
      expect(validatePassword('')).toEqual({ 
        valid: false, 
        error: 'Password is required' 
      });
      expect(validatePassword('weak')).toEqual({ 
        valid: false, 
        error: 'Password must be at least 8 characters' 
      });
      expect(validatePassword('weakpass')).toEqual({ 
        valid: false, 
        error: 'Password must contain at least one uppercase letter' 
      });
      expect(validatePassword('weakpass1')).toEqual({ 
        valid: false, 
        error: 'Password must contain at least one uppercase letter' 
      });
      expect(validatePassword('Weakpass')).toEqual({ 
        valid: false, 
        error: 'Password must contain at least one number' 
      });
      expect(validatePassword('Weakpass1')).toEqual({ 
        valid: false, 
        error: 'Password must contain at least one special character' 
      });
    });

    it('supports custom requirements', () => {
      expect(validatePassword('simple', { minLength: 6 })).toEqual({ valid: true });
      expect(validatePassword('simple', { minLength: 10 })).toEqual({ 
        valid: false, 
        error: 'Password must be at least 10 characters' 
      });
    });
  });

  describe('validateOrderTicket', () => {
    const validOrder = {
      symbol: 'BTC/USD',
      side: 'buy',
      size: 1.5,
      orderType: 'limit',
      price: 45000,
      venue: 'kalshi',
    };

    it('validates complete order', () => {
      expect(validateOrderTicket(validOrder)).toEqual({ valid: true });
    });

    it('validates market order without price', () => {
      const marketOrder = { ...validOrder, orderType: 'market', price: undefined };
      expect(validateOrderTicket(marketOrder)).toEqual({ valid: true });
    });

    it('rejects order with missing fields', () => {
      const incompleteOrder = {
        symbol: 'BTC/USD',
        side: '',  // empty side
        orderType: 'limit',
        size: 1,
        venue: '',  // empty venue
      };
      const result = validateOrderTicket(incompleteOrder);
      expect(result.valid).toBe(false);
      expect(result.errors).toBeDefined();
      expect(result.errors?.length).toBeGreaterThan(0);
    });

    it('rejects limit order without price', () => {
      const limitOrder = { ...validOrder, price: undefined };
      const result = validateOrderTicket(limitOrder);
      expect(result.valid).toBe(false);
      expect(result.errors).toContain('Price is required for limit orders');
    });

    it('aggregates multiple errors', () => {
      const invalidOrder = {
        symbol: '',
        side: 'invalid',
        size: -1,
        orderType: 'invalid',
        price: 0,
        venue: '',
      };
      const result = validateOrderTicket(invalidOrder);
      expect(result.valid).toBe(false);
      expect(result.errors?.length).toBeGreaterThan(3);
    });

    it('supports custom validation options', () => {
      const orderWithLargeSize = { ...validOrder, size: 1500 };
      const result = validateOrderTicket(orderWithLargeSize, { maxSize: 1000 });
      expect(result.valid).toBe(false);
      expect(result.errors).toContain('Maximum size is 1000');
    });
  });
});

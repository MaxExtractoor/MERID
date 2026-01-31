import {
  formatCurrency,
  formatPercent,
  formatNumber,
  formatDate,
  formatTime,
  formatDuration,
  formatFileSize,
  formatSymbol,
  formatOrderDetails,
  formatDelta,
} from '../formatters';

describe('formatters', () => {
  describe('formatCurrency', () => {
    it('formats USD currency', () => {
      expect(formatCurrency(1234.56)).toBe('$1,234.56');
    });

    it('formats large numbers', () => {
      expect(formatCurrency(1234567.89)).toBe('$1,234,567.89');
    });

    it('handles negative numbers', () => {
      expect(formatCurrency(-123.45)).toBe('-$123.45');
    });

    it('supports different currencies', () => {
      expect(formatCurrency(1234.56, 'EUR')).toBe('€1,234.56');
      expect(formatCurrency(1234.56, 'GBP')).toBe('£1,234.56');
    });

    it('handles zero', () => {
      expect(formatCurrency(0)).toBe('$0.00');
    });

    it('supports custom precision', () => {
      expect(formatCurrency(1234.567, 'USD', 3)).toBe('$1,234.567');
    });
  });

  describe('formatPercent', () => {
    it('formats percentage', () => {
      expect(formatPercent(0.1234)).toBe('12.34%');
    });

    it('handles negative percentages', () => {
      expect(formatPercent(-0.0567)).toBe('-5.67%');
    });

    it('handles zero', () => {
      expect(formatPercent(0)).toBe('0.00%');
    });

    it('supports custom precision', () => {
      expect(formatPercent(0.12345, 3)).toBe('12.345%');
    });

    it('handles values greater than 1', () => {
      expect(formatPercent(1.5)).toBe('150.00%');
    });
  });

  describe('formatNumber', () => {
    it('formats basic numbers', () => {
      expect(formatNumber(1234.567)).toBe('1,234.567');
    });

    it('formats large numbers', () => {
      expect(formatNumber(1234567)).toBe('1,234,567');
    });

    it('handles negative numbers', () => {
      expect(formatNumber(-123.45)).toBe('-123.45');
    });

    it('supports custom precision', () => {
      expect(formatNumber(1234.567, 2)).toBe('1,234.57');
    });

    it('handles zero', () => {
      expect(formatNumber(0)).toBe('0');
    });
  });

  describe('formatDate', () => {
    const testDate = new Date('2024-01-30T15:30:00Z');

    it('formats default date', () => {
      expect(formatDate(testDate)).toBe('2024-01-30');
    });

    it('supports custom format', () => {
      expect(formatDate(testDate, 'MM/DD/YYYY')).toBe('01/30/2024');
    });

    it('supports readable format', () => {
      expect(formatDate(testDate, 'readable')).toBe('Jan 30, 2024');
    });

    it('handles relative dates', () => {
      const today = new Date();
      expect(formatDate(today, 'relative')).toBe('Today');
    });

    it('handles invalid dates', () => {
      expect(formatDate(new Date('invalid'))).toBe('Invalid Date');
    });
  });

  describe('formatTime', () => {
    const testTime = new Date('2024-01-30T15:30:45Z');

    it('formats default time', () => {
      expect(formatTime(testTime)).toBe('3:30 PM');
    });

    it('supports 24-hour format', () => {
      expect(formatTime(testTime, '24h')).toBe('15:30');
    });

    it('includes seconds', () => {
      expect(formatTime(testTime, '12h', true)).toBe('3:30:45 PM');
    });

    it('handles midnight', () => {
      const midnight = new Date('2024-01-30T00:00:00Z');
      expect(formatTime(midnight)).toBe('12:00 AM');
    });

    it('handles noon', () => {
      const noon = new Date('2024-01-30T12:00:00Z');
      expect(formatTime(noon)).toBe('12:00 PM');
    });
  });

  describe('formatDuration', () => {
    it('formats seconds', () => {
      expect(formatDuration(45)).toBe('45s');
    });

    it('formats minutes and seconds', () => {
      expect(formatDuration(125)).toBe('2m 5s');
    });

    it('formats hours, minutes, and seconds', () => {
      expect(formatDuration(3665)).toBe('1h 1m 5s');
    });

    it('formats days', () => {
      expect(formatDuration(90000)).toBe('1d 1h 0m');
    });

    it('handles zero duration', () => {
      expect(formatDuration(0)).toBe('0s');
    });

    it('supports verbose format', () => {
      expect(formatDuration(125, 'verbose')).toBe('2 minutes, 5 seconds');
    });
  });

  describe('formatFileSize', () => {
    it('formats bytes', () => {
      expect(formatFileSize(512)).toBe('512 B');
    });

    it('formats kilobytes', () => {
      expect(formatFileSize(1536)).toBe('1.5 KB');
    });

    it('formats megabytes', () => {
      expect(formatFileSize(1048576)).toBe('1.0 MB');
    });

    it('formats gigabytes', () => {
      expect(formatFileSize(1073741824)).toBe('1.0 GB');
    });

    it('handles large files', () => {
      expect(formatFileSize(1099511627776)).toBe('1.0 TB');
    });

    it('supports binary units', () => {
      expect(formatFileSize(1048576, 'binary')).toBe('1.0 MiB');
    });
  });

  describe('formatSymbol', () => {
    it('formats trading symbols', () => {
      expect(formatSymbol('BTC/USD')).toBe('BTC/USD');
      expect(formatSymbol('BTCUSD')).toBe('BTC/USD');
      expect(formatSymbol('BTC-USD')).toBe('BTC/USD');
    });

    it('handles already formatted symbols', () => {
      expect(formatSymbol('BTC/USD')).toBe('BTC/USD');
    });

    it('handles edge cases', () => {
      expect(formatSymbol('BTC')).toBe('BTC');
      expect(formatSymbol('')).toBe('');
    });
  });

  describe('formatOrderDetails', () => {
    it('formats basic order', () => {
      const order = {
        symbol: 'BTC/USD',
        side: 'buy',
        size: 1.5,
        price: 45000,
        type: 'limit',
      };
      expect(formatOrderDetails(order)).toBe('Buy 1.5 BTC/USD at $45,000.00 (Limit)');
    });

    it('formats market order', () => {
      const order = {
        symbol: 'ETH/USD',
        side: 'sell',
        size: 10,
        type: 'market',
      };
      expect(formatOrderDetails(order)).toBe('Sell 10 ETH/USD at Market (Market)');
    });

    it('formats stop order', () => {
      const order = {
        symbol: 'SOL/USD',
        side: 'buy',
        size: 100,
        price: 150,
        type: 'stop',
      };
      expect(formatOrderDetails(order)).toBe('Buy 100 SOL/USD at $150.00 (Stop)');
    });

    it('handles missing price for market orders', () => {
      const order = {
        symbol: 'BTC/USD',
        side: 'buy',
        size: 1,
        type: 'market',
      };
      expect(formatOrderDetails(order)).toBe('Buy 1 BTC/USD at Market (Market)');
    });
  });

  describe('formatDelta', () => {
    it('formats positive delta', () => {
      const result = formatDelta(123.45, 100);
      expect(result.value).toBe('+$23.45');
      expect(result.percent).toBe('+23.45%');
      expect(result.color).toBe('text-green-500');
      expect(result.icon).toBe('↑');
    });

    it('formats negative delta', () => {
      const result = formatDelta(95, 100);
      expect(result.value).toBe('-$5.00');
      expect(result.percent).toBe('-5.00%');
      expect(result.color).toBe('text-red-500');
      expect(result.icon).toBe('↓');
    });

    it('formats zero delta', () => {
      const result = formatDelta(100, 100);
      expect(result.value).toBe('$0.00');
      expect(result.percent).toBe('0.00%');
      expect(result.color).toBe('text-gray-500');
      expect(result.icon).toBe('→');
    });

    it('handles percentage delta', () => {
      const result = formatDelta(15, 10, 'percent');
      expect(result.value).toBe('+50.00%');
      expect(result.percent).toBe('+50.00%');
      expect(result.color).toBe('text-green-500');
      expect(result.icon).toBe('↑');
    });

    it('handles zero previous value', () => {
      const result = formatDelta(100, 0);
      expect(result.value).toBe('$100.00');
      expect(result.percent).toBe('∞%');
      expect(result.color).toBe('text-green-500');
      expect(result.icon).toBe('↑');
    });
  });
});

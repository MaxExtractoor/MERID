/**
 * Tests for riskConfig.ts - shared risk configuration
 */

import { DRAWDOWN_TIER_CONFIG, getDrawdownTierConfig, DRAWDOWN_THRESHOLDS } from '../riskConfig';
import { CheckCircle, AlertTriangle, ArrowDownRight, XCircle } from 'lucide-react';

describe('DRAWDOWN_TIER_CONFIG', () => {
  it('should have all four tiers defined', () => {
    expect(DRAWDOWN_TIER_CONFIG.normal).toBeDefined();
    expect(DRAWDOWN_TIER_CONFIG.warning).toBeDefined();
    expect(DRAWDOWN_TIER_CONFIG.downsize).toBeDefined();
    expect(DRAWDOWN_TIER_CONFIG.halt).toBeDefined();
  });

  it('should have correct labels', () => {
    expect(DRAWDOWN_TIER_CONFIG.normal.label).toBe('Normal');
    expect(DRAWDOWN_TIER_CONFIG.warning.label).toBe('Warning');
    expect(DRAWDOWN_TIER_CONFIG.downsize.label).toBe('Downsize');
    expect(DRAWDOWN_TIER_CONFIG.halt.label).toBe('HALT');
  });

  it('should have correct color classes', () => {
    expect(DRAWDOWN_TIER_CONFIG.normal.color).toBe('text-green-400');
    expect(DRAWDOWN_TIER_CONFIG.warning.color).toBe('text-yellow-400');
    expect(DRAWDOWN_TIER_CONFIG.downsize.color).toBe('text-orange-400');
    expect(DRAWDOWN_TIER_CONFIG.halt.color).toBe('text-red-400');
  });

  it('should have correct background classes', () => {
    expect(DRAWDOWN_TIER_CONFIG.normal.bg).toBe('bg-green-500/20');
    expect(DRAWDOWN_TIER_CONFIG.warning.bg).toBe('bg-yellow-500/20');
    expect(DRAWDOWN_TIER_CONFIG.downsize.bg).toBe('bg-orange-500/20');
    expect(DRAWDOWN_TIER_CONFIG.halt.bg).toBe('bg-red-500/20');
  });

  it('should have correct icon components', () => {
    expect(DRAWDOWN_TIER_CONFIG.normal.icon).toBe(CheckCircle);
    expect(DRAWDOWN_TIER_CONFIG.warning.icon).toBe(AlertTriangle);
    expect(DRAWDOWN_TIER_CONFIG.downsize.icon).toBe(ArrowDownRight);
    expect(DRAWDOWN_TIER_CONFIG.halt.icon).toBe(XCircle);
  });
});

describe('getDrawdownTierConfig', () => {
  it('should return config for valid tier', () => {
    const config = getDrawdownTierConfig('warning');
    expect(config.label).toBe('Warning');
  });

  it('should return normal config for undefined tier', () => {
    const config = getDrawdownTierConfig(undefined);
    expect(config.label).toBe('Normal');
  });

  it('should return normal config for invalid tier', () => {
    const config = getDrawdownTierConfig('invalid-tier');
    expect(config.label).toBe('Normal');
  });

  it('should return normal config for empty string', () => {
    const config = getDrawdownTierConfig('');
    expect(config.label).toBe('Normal');
  });
});

describe('DRAWDOWN_THRESHOLDS', () => {
  it('should have correct threshold values', () => {
    expect(DRAWDOWN_THRESHOLDS.warning).toBe(5.0);
    expect(DRAWDOWN_THRESHOLDS.downsize).toBe(10.0);
    expect(DRAWDOWN_THRESHOLDS.halt).toBe(20.0);
  });
});

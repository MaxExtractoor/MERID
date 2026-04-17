/**
 * API Response Validation Utilities
 * 
 * Lightweight runtime validation for API responses to catch
 * schema mismatches early and provide better error messages.
 * 
 * NOTE: This is a lightweight alternative to zod for basic
 * runtime type checking without adding dependencies.
 */

export interface ValidationResult<T> {
  success: boolean;
  data?: T;
  error?: string;
}

export function validateEdgeSignal(data: unknown): ValidationResult<{
  implied_prob: number;
  model_prob: number;
  ev_cents: number;
  edge_pct: number;
  confidence: number;
  confidence_bucket: 'low' | 'medium' | 'high';
  sizing_tier: 'normal' | 'reduced' | 'boosted' | 'halted';
}> {
  if (typeof data !== 'object' || data === null) {
    return { success: false, error: 'EdgeSignal must be an object' };
  }

  const d = data as Record<string, unknown>;
  
  // Required numeric fields
  const numericFields = ['implied_prob', 'model_prob', 'ev_cents', 'edge_pct', 'confidence'];
  for (const field of numericFields) {
    if (typeof d[field] !== 'number') {
      return { success: false, error: `EdgeSignal.${field} must be a number, got ${typeof d[field]}` };
    }
  }
  
  // Validate confidence_bucket
  const validBuckets = ['low', 'medium', 'high'];
  if (!validBuckets.includes(d.confidence_bucket as string)) {
    return { 
      success: false, 
      error: `EdgeSignal.confidence_bucket must be one of ${validBuckets.join(', ')}, got ${d.confidence_bucket}` 
    };
  }
  
  // Validate sizing_tier
  const validTiers = ['normal', 'reduced', 'boosted', 'halted'];
  if (!validTiers.includes(d.sizing_tier as string)) {
    return { 
      success: false, 
      error: `EdgeSignal.sizing_tier must be one of ${validTiers.join(', ')}, got ${d.sizing_tier}` 
    };
  }
  
  return { 
    success: true, 
    data: {
      implied_prob: d.implied_prob as number,
      model_prob: d.model_prob as number,
      ev_cents: d.ev_cents as number,
      edge_pct: d.edge_pct as number,
      confidence: d.confidence as number,
      confidence_bucket: d.confidence_bucket as 'low' | 'medium' | 'high',
      sizing_tier: d.sizing_tier as 'normal' | 'reduced' | 'boosted' | 'halted',
    }
  };
}

export function validateEdgeResponse(data: unknown): ValidationResult<{
  signals: Record<string, unknown>;
  count: number;
  kelly_fraction: number;
  effective_fraction: number;
  drawdown_pct: number;
}> {
  if (typeof data !== 'object' || data === null) {
    return { success: false, error: 'EdgeResponse must be an object' };
  }

  const d = data as Record<string, unknown>;
  
  // Validate signals is an object
  if (typeof d.signals !== 'object' || d.signals === null) {
    return { success: false, error: 'EdgeResponse.signals must be an object' };
  }
  
  // Required numeric fields
  const numericFields = ['count', 'kelly_fraction', 'effective_fraction', 'drawdown_pct'];
  for (const field of numericFields) {
    if (typeof d[field] !== 'number') {
      return { success: false, error: `EdgeResponse.${field} must be a number, got ${typeof d[field]}` };
    }
  }
  
  return { 
    success: true, 
    data: {
      signals: d.signals as Record<string, unknown>,
      count: d.count as number,
      kelly_fraction: d.kelly_fraction as number,
      effective_fraction: d.effective_fraction as number,
      drawdown_pct: d.drawdown_pct as number,
    }
  };
}

export function validateHealthStatus(data: unknown): ValidationResult<{
  status: string;
  issues: string[];
}> {
  if (typeof data !== 'object' || data === null) {
    return { success: false, error: 'HealthStatus must be an object' };
  }

  const d = data as Record<string, unknown>;
  
  if (typeof d.status !== 'string') {
    return { success: false, error: 'HealthStatus.status must be a string' };
  }
  
  if (!Array.isArray(d.issues) || !d.issues.every(i => typeof i === 'string')) {
    return { success: false, error: 'HealthStatus.issues must be an array of strings' };
  }
  
  return { 
    success: true, 
    data: {
      status: d.status,
      issues: d.issues as string[],
    }
  };
}

/**
 * Safe API data fetch with validation
 */
export async function fetchWithValidation<T>(
  url: string,
  validator: (data: unknown) => ValidationResult<T>,
  options?: RequestInit
): Promise<{ ok: true; data: T } | { ok: false; error: string }> {
  try {
    const response = await fetch(url, options);
    
    if (!response.ok) {
      return { ok: false, error: `HTTP ${response.status}: ${response.statusText}` };
    }
    
    const rawData = await response.json();
    const result = validator(rawData);
    
    if (!result.success) {
      console.error('[API Validation Failed]', result.error, rawData);
      return { ok: false, error: result.error || 'Validation failed' };
    }
    
    return { ok: true, data: result.data! };
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    return { ok: false, error: errorMessage };
  }
}

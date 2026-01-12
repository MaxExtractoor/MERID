/**
 * MERID TruthGate - UI Enforcement Middleware
 * 
 * CONSTITUTIONAL: UI cannot lie even if engineers try.
 * 
 * This is the layer that prevents fake progress by independently
 * verifying truth eligibility before rendering.
 */

export type AssertionStatus =
  | "VALID"
  | "DEGRADED"
  | "CONFLICTED"
  | "EXPIRED"
  | "MISSING";

export type TruthGateState =
  | "RENDER"
  | "LOCK"
  | "BLIND"
  | "SUPPRESSED";

export interface AssertionProvenance {
  sourceId: string;
  sourceType: "MARKET" | "ONCHAIN" | "SOCIAL" | "PREDICTION" | "INTERNAL";
  trustScore: number; // 0-1
  lastVerifiedAt: number; // epoch ms
}

export interface Assertion {
  id: string;
  domain: string;
  confidence: number; // raw, untrusted
  effectiveConfidence: number; // post-decay, post-regime
  status: AssertionStatus;
  provenance: AssertionProvenance[];
  regimeCompatibility: number; // 0-1
  entropyContribution: number;
  expiresAt: number;
}

export interface TruthGateDecision {
  state: TruthGateState;
  reason: string;
  blockingAssertions?: string[];
  warnings?: string[];
}

export interface TruthBoundComponent {
  componentId: string;
  requiredAssertions: string[];
  minConfidence?: number;
  allowConflict?: boolean;
  allowExpired?: boolean;
}

/**
 * TruthGate - The firewall between backend and UI
 */
export class TruthGate {
  private assertionCache: Map<string, Assertion> = new Map();
  private regimeEntropy: number = 0.0;
  private lastUpdate: number = 0;

  /**
   * Evaluate whether a component is allowed to render.
   * 
   * CONSTITUTIONAL: This is the gate that prevents fake UI.
   */
  evaluate(
    component: TruthBoundComponent,
    assertions: Record<string, Assertion>,
    regimeEntropy: number
  ): TruthGateDecision {
    this.regimeEntropy = regimeEntropy;
    this.lastUpdate = Date.now();

    const warnings: string[] = [];
    const blocking: string[] = [];

    // Check for missing assertions
    for (const requiredId of component.requiredAssertions) {
      if (!assertions[requiredId]) {
        blocking.push(requiredId);
        return {
          state: "SUPPRESSED",
          reason: `Missing required assertion: ${requiredId}`,
          blockingAssertions: blocking,
        };
      }
    }

    // Check regime entropy threshold
    if (regimeEntropy > 0.7) {
      return {
        state: "BLIND",
        reason: `Regime entropy ${regimeEntropy.toFixed(2)} > 0.7 - system in blindness mode`,
        blockingAssertions: [],
      };
    }

    // Check each assertion
    const minConfidence = component.minConfidence ?? 0.5;
    const allowConflict = component.allowConflict ?? false;
    const allowExpired = component.allowExpired ?? false;

    for (const requiredId of component.requiredAssertions) {
      const assertion = assertions[requiredId];

      // Check status
      if (assertion.status === "EXPIRED" && !allowExpired) {
        blocking.push(requiredId);
        return {
          state: "SUPPRESSED",
          reason: `Assertion expired: ${requiredId}`,
          blockingAssertions: blocking,
        };
      }

      if (assertion.status === "CONFLICTED" && !allowConflict) {
        blocking.push(requiredId);
        return {
          state: "LOCK",
          reason: `Assertion conflicted: ${requiredId}`,
          blockingAssertions: blocking,
        };
      }

      // Check effective confidence
      if (assertion.effectiveConfidence < minConfidence) {
        blocking.push(requiredId);
        return {
          state: "LOCK",
          reason: `Confidence too low: ${assertion.effectiveConfidence.toFixed(3)} < ${minConfidence}`,
          blockingAssertions: blocking,
        };
      }

      // Warnings
      if (assertion.status === "DEGRADED") {
        warnings.push(`Assertion degraded: ${requiredId}`);
      }

      if (assertion.effectiveConfidence < 0.7) {
        warnings.push(`Low confidence: ${requiredId} (${assertion.effectiveConfidence.toFixed(3)})`);
      }
    }

    // Check regime entropy impact
    if (regimeEntropy > 0.5) {
      warnings.push(`High regime entropy: ${regimeEntropy.toFixed(2)}`);
      return {
        state: "LOCK",
        reason: "Regime entropy > 0.5 - execution throttled",
        blockingAssertions: [],
        warnings,
      };
    }

    return {
      state: "RENDER",
      reason: "All assertions valid",
      blockingAssertions: [],
      warnings,
    };
  }

  /**
   * Check if execution is allowed.
   * 
   * STRICTER than UI rendering - no exceptions.
   */
  checkExecutionEligibility(
    intentId: string,
    requiredAssertions: string[],
    assertions: Record<string, Assertion>
  ): TruthGateDecision {
    // Blindness check
    if (this.regimeEntropy > 0.7) {
      return {
        state: "SUPPRESSED",
        reason: "BLINDNESS MODE - execution blocked",
        blockingAssertions: [],
      };
    }

    const blocking: string[] = [];

    // All assertions must exist
    for (const requiredId of requiredAssertions) {
      if (!assertions[requiredId]) {
        blocking.push(requiredId);
      }
    }

    if (blocking.length > 0) {
      return {
        state: "SUPPRESSED",
        reason: "Missing required assertions",
        blockingAssertions: blocking,
      };
    }

    // All assertions must be usable (higher threshold)
    const executionThreshold = 0.6;
    for (const requiredId of requiredAssertions) {
      const assertion = assertions[requiredId];

      if (assertion.status !== "VALID") {
        blocking.push(requiredId);
        return {
          state: "SUPPRESSED",
          reason: `Assertion not valid: ${assertion.status}`,
          blockingAssertions: blocking,
        };
      }

      if (assertion.effectiveConfidence < executionThreshold) {
        blocking.push(requiredId);
        return {
          state: "SUPPRESSED",
          reason: `Confidence below execution threshold: ${assertion.effectiveConfidence.toFixed(3)} < ${executionThreshold}`,
          blockingAssertions: blocking,
        };
      }
    }

    return {
      state: "RENDER",
      reason: "Execution allowed",
      blockingAssertions: [],
    };
  }
}

/**
 * Forbidden UI Keys - CI will fail if these appear
 */
const FORBIDDEN_KEYS = [
  "overallConfidence",
  "systemHealthScore",
  "analysisProgress",
  "confidenceScore",
  "recommendationStrength",
];

/**
 * Check if data contains forbidden aggregations.
 */
export function detectForbiddenAggregations(data: any): string[] {
  const violations: string[] = [];

  function scan(obj: any, path: string = "") {
    if (typeof obj !== "object" || obj === null) return;

    for (const key of Object.keys(obj)) {
      const fullPath = path ? `${path}.${key}` : key;

      if (FORBIDDEN_KEYS.includes(key)) {
        violations.push(fullPath);
      }

      if (typeof obj[key] === "object") {
        scan(obj[key], fullPath);
      }
    }
  }

  scan(data);
  return violations;
}

/**
 * Component state manager with TruthGate enforcement.
 */
export class TruthBoundComponentManager {
  private truthGate: TruthGate;
  private components: Map<string, TruthBoundComponent> = new Map();

  constructor() {
    this.truthGate = new TruthGate();
  }

  /**
   * Register a component with its truth requirements.
   */
  register(component: TruthBoundComponent): void {
    this.components.set(component.componentId, component);
  }

  /**
   * Check if component should render.
   */
  shouldRender(
    componentId: string,
    assertions: Record<string, Assertion>,
    regimeEntropy: number
  ): TruthGateDecision {
    const component = this.components.get(componentId);
    if (!component) {
      return {
        state: "SUPPRESSED",
        reason: "Component not registered with TruthGate",
      };
    }

    return this.truthGate.evaluate(component, assertions, regimeEntropy);
  }

  /**
   * Get component state for rendering.
   */
  getComponentState(
    componentId: string,
    assertions: Record<string, Assertion>,
    regimeEntropy: number
  ): { state: TruthGateState; message: string; canInteract: boolean } {
    const decision = this.shouldRender(componentId, assertions, regimeEntropy);

    let message = decision.reason;
    if (decision.warnings && decision.warnings.length > 0) {
      message += "\n\nWarnings:\n" + decision.warnings.join("\n");
    }

    return {
      state: decision.state,
      message,
      canInteract: decision.state === "RENDER",
    };
  }
}

/**
 * Global TruthGate instance.
 */
export const globalTruthGate = new TruthBoundComponentManager();

/**
 * React/UI hook for truth-bound components.
 */
export function useTruthGate(
  componentId: string,
  requiredAssertions: string[],
  options?: {
    minConfidence?: number;
    allowConflict?: boolean;
    allowExpired?: boolean;
  }
) {
  // Register component
  globalTruthGate.register({
    componentId,
    requiredAssertions,
    ...options,
  });

  // This would integrate with your UI framework
  // For now, return a function to check state
  return {
    checkState: (assertions: Record<string, Assertion>, regimeEntropy: number) =>
      globalTruthGate.getComponentState(componentId, assertions, regimeEntropy),
  };
}

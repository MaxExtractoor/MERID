/**
 * Arbitrage Coordinator
 * Multi-agent coordination for competing on the same anomaly
 * 
 * Prevents over-sizing when multiple agents detect the same opportunity
 * Uses auction-based allocation: best edge gets priority within size caps
 */

import { EventBus, EventEnvelope, OrderIntent } from "./types";

export interface ArbProposal {
  anomaly_id: string;           // Hash of market set + pricing pattern
  agent_id: string;
  netEdge: number;              // Net edge after fees/slippage
  confidence: number;           // Agent confidence (0-1)
  size: number;                 // Requested size in dollars
  intent: OrderIntent;
  timestamp: number;
}

export interface CoordinatorConfig {
  maxSizePerAnomaly: number;    // Total size cap per anomaly
  maxProposalsPerAnomaly: number; // Wait for N proposals before deciding
  proposalTimeoutMs: number;    // Max wait time for proposals
  minNetEdge: number;           // Minimum edge to consider
}

export interface AllocationDecision {
  anomaly_id: string;
  allocations: {
    agent_id: string;
    allocated_size: number;
    original_size: number;
    reason: string;
  }[];
  total_allocated: number;
  rejected_count: number;
}

/**
 * Arbitrage Coordinator
 * 
 * Agents emit proposals for detected anomalies
 * Coordinator allocates limited capital to best proposals
 * Ensures global caps per anomaly/market
 * 
 * Flow:
 * 1. Agent detects anomaly → emits proposal
 * 2. Coordinator collects proposals for same anomaly
 * 3. After timeout or max proposals, runs auction
 * 4. Best proposals (by netEdge) get size allocation
 * 5. Winning intents forwarded to risk engine
 */
export class ArbCoordinator {
  private proposals = new Map<string, ArbProposal[]>();
  private timeouts = new Map<string, NodeJS.Timeout>();
  private config: CoordinatorConfig;
  private allocationHistory: AllocationDecision[] = [];

  constructor(private bus: EventBus, config: Partial<CoordinatorConfig> = {}) {
    this.config = {
      maxSizePerAnomaly: config.maxSizePerAnomaly ?? 1000,
      maxProposalsPerAnomaly: config.maxProposalsPerAnomaly ?? 3,
      proposalTimeoutMs: config.proposalTimeoutMs ?? 500, // 500ms window
      minNetEdge: config.minNetEdge ?? 0.01,
    };
  }

  async start(): Promise<void> {
    await this.bus.subscribe<ArbProposal>(
      "proposals.kalshi_arb",
      (evt) => this.onProposal(evt)
    );

    console.log(`[ArbCoordinator] Started`);
    console.log(`  Max size per anomaly: $${this.config.maxSizePerAnomaly}`);
    console.log(`  Max proposals: ${this.config.maxProposalsPerAnomaly}`);
    console.log(`  Proposal timeout: ${this.config.proposalTimeoutMs}ms`);
  }

  private async onProposal(evt: EventEnvelope<ArbProposal>): Promise<void> {
    const proposal = evt.data;

    // Reject if edge too low
    if (proposal.netEdge < this.config.minNetEdge) {
      console.log(
        `[ArbCoordinator] Rejected ${proposal.agent_id} for ${proposal.anomaly_id}: ` +
        `edge=${proposal.netEdge.toFixed(4)} < ${this.config.minNetEdge}`
      );
      return;
    }

    // Add to proposals for this anomaly
    const list = this.proposals.get(proposal.anomaly_id) ?? [];
    list.push(proposal);
    this.proposals.set(proposal.anomaly_id, list);

    console.log(
      `[ArbCoordinator] Proposal from ${proposal.agent_id} for ${proposal.anomaly_id}: ` +
      `edge=${proposal.netEdge.toFixed(4)}, size=$${proposal.size}`
    );

    // Check if we should allocate now
    if (list.length >= this.config.maxProposalsPerAnomaly) {
      // Enough proposals, allocate immediately
      this.clearTimeout(proposal.anomaly_id);
      await this.allocate(proposal.anomaly_id);
    } else if (list.length === 1) {
      // First proposal, start timeout
      this.setTimeout(proposal.anomaly_id);
    }
  }

  private setTimeout(anomalyId: string): void {
    const timeout = setTimeout(() => {
      this.allocate(anomalyId);
    }, this.config.proposalTimeoutMs);

    this.timeouts.set(anomalyId, timeout);
  }

  private clearTimeout(anomalyId: string): void {
    const timeout = this.timeouts.get(anomalyId);
    if (timeout) {
      clearTimeout(timeout);
      this.timeouts.delete(anomalyId);
    }
  }

  private async allocate(anomalyId: string): Promise<void> {
    const proposals = this.proposals.get(anomalyId);
    if (!proposals || proposals.length === 0) return;

    // Remove from pending
    this.proposals.delete(anomalyId);
    this.clearTimeout(anomalyId);

    // Sort by netEdge (highest first), then confidence
    const sorted = proposals.sort((a, b) => {
      if (Math.abs(a.netEdge - b.netEdge) > 0.0001) {
        return b.netEdge - a.netEdge;
      }
      return b.confidence - a.confidence;
    });

    // Allocate size to proposals
    let remaining = this.config.maxSizePerAnomaly;
    const allocations: AllocationDecision["allocations"] = [];
    let rejectedCount = 0;

    for (const proposal of sorted) {
      if (remaining <= 0) {
        allocations.push({
          agent_id: proposal.agent_id,
          allocated_size: 0,
          original_size: proposal.size,
          reason: "cap_exhausted",
        });
        rejectedCount++;
        continue;
      }

      // Grant up to remaining size
      const grantedSize = Math.min(proposal.size, remaining);
      remaining -= grantedSize;

      allocations.push({
        agent_id: proposal.agent_id,
        allocated_size: grantedSize,
        original_size: proposal.size,
        reason: grantedSize === proposal.size ? "full_allocation" : "partial_allocation",
      });

      // Forward intent if allocated any size
      if (grantedSize > 0) {
        const intent: OrderIntent = {
          ...proposal.intent,
          qty: Math.floor(grantedSize / proposal.intent.price), // Convert $ to contracts
          rationale: `${proposal.intent.rationale} [coordinated: ${grantedSize}/${proposal.size}]`,
        };

        await this.bus.publish("intents.orders", intent);

        console.log(
          `[ArbCoordinator] Allocated $${grantedSize} to ${proposal.agent_id} ` +
          `(edge=${proposal.netEdge.toFixed(4)})`
        );
      }
    }

    // Record decision
    const decision: AllocationDecision = {
      anomaly_id: anomalyId,
      allocations,
      total_allocated: this.config.maxSizePerAnomaly - remaining,
      rejected_count: rejectedCount,
    };

    this.allocationHistory.push(decision);

    // Publish decision for monitoring
    await this.bus.publish("coordinator.decisions", decision);

    console.log(
      `[ArbCoordinator] Allocated ${decision.total_allocated}/${this.config.maxSizePerAnomaly} ` +
      `for ${anomalyId} across ${allocations.length} proposals`
    );
  }

  async stop(): Promise<void> {
    // Clear all pending timeouts
    for (const timeout of this.timeouts.values()) {
      clearTimeout(timeout);
    }
    this.timeouts.clear();

    console.log(`[ArbCoordinator] Stopped`);
  }

  // Monitoring
  getPendingProposals(): Map<string, ArbProposal[]> {
    return new Map(this.proposals);
  }

  getAllocationHistory(): AllocationDecision[] {
    return [...this.allocationHistory];
  }

  getStats() {
    return {
      pendingAnomalies: this.proposals.size,
      totalAllocations: this.allocationHistory.length,
      totalAgentsParticipated: new Set(
        this.allocationHistory.flatMap(d => d.allocations.map(a => a.agent_id))
      ).size,
    };
  }
}

/**
 * Generate anomaly ID from market pattern
 * Deterministic hash so multiple agents identify same anomaly
 */
export function generateAnomalyId(
  markets: string[],
  pattern: "yes_no_gt_1" | "cross_market_sum" | "stale_odds"
): string {
  // Sort markets for deterministic hash
  const sorted = [...markets].sort();
  return `${pattern}:${sorted.join(",")}`;
}

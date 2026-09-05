/**
 * lib/types.ts
 * ──────────────────────────────────────────────────────────────────────
 * View-model types shared by the scanner and feed components.
 *
 * These describe what the UI renders, after `useMerchantScan` maps a backend
 * `ScanReport` (see lib/api.ts) into display shape.
 *
 * This module replaces lib/mockData.ts, which mixed these type declarations
 * with ~330 lines of fabricated scan results, feed rows, and benchmark metrics.
 * Those constants were being rendered as though they were live data — invented
 * merchants in the risk-operations queue and invented accuracy figures on the
 * benchmark page — so they have been removed rather than moved.
 */

export type RiskLevel = "SAFE" | "NEEDS_REVIEW" | "HIGH_RISK";
export type AgentStatus = "idle" | "running" | "complete" | "error";
export type Severity = "info" | "warning" | "critical";

export interface AgentFinding {
  id: string;
  label: string;
  value: string;
  severity: Severity;
}

export interface SubAgent {
  id: string;
  name: string;
  emoji: string;
  description: string;
  status: AgentStatus;
  durationMs: number;
  /** 0–100. Policy/catalog use the agent's own score; footprint uses domain confidence. */
  confidence: number;
  findings: AgentFinding[];
  /** Raw evidence extract shown in the accordion. */
  snippet: string;
  summary: string;
}

export interface AuditStep {
  timestamp: string;
  agent: string;
  action: string;
  result: string;
  level: "info" | "warn" | "error" | "success";
}

export interface ScanResult {
  domain: string;
  url: string;
  riskScore: number;
  riskLevel: RiskLevel;
  scannedAt: string;
  totalDurationMs: number;
  keyDrivers: string[];
  agents: SubAgent[];
  auditTrail: AuditStep[];
  /**
   * False when any signal came from a fallback path (LLM unavailable, pgvector
   * unseeded, persistence failed). The UI must say so rather than present a
   * degraded verdict as a complete analysis.
   */
  fullyAnalyzed: boolean;
  degradedReasons: string[];
}

export interface FeedEntry {
  id: string;
  domain: string;
  riskScore: number;
  riskLevel: RiskLevel;
  scannedAt: string;
  flaggedBy: string[];
  decision: string;
}

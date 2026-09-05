/**
 * hooks/useMerchantScan.ts
 * ──────────────────────────────────────────────────────────────────────
 * Replaces useScanSimulation — makes REAL calls to POST /api/v1/inspect.
 *
 * While the API processes (~15-60s), we animate a 4-step pipeline progress
 * display using timed milestones so the UI feels live and responsive.
 * Once the response lands, we map the backend ScanReport → frontend ScanResult.
 */

"use client";
import { useState, useCallback, useRef } from "react";
import { inspectMerchant, type ScanReport } from "@/lib/api";
import type { ScanResult, AgentStatus } from "@/lib/mockData";

export interface ScanState {
  phase: "idle" | "scanning" | "complete" | "error";
  url: string;
  agentStatuses: Record<string, AgentStatus>;
  agentDurations: Record<string, number>;
  result: ScanResult | null;
  progress: number;
  currentAgentIndex: number;
  errorMessage: string | null;
}

const INITIAL_STATE: ScanState = {
  phase: "idle",
  url: "",
  agentStatuses: { policy: "idle", catalog: "idle", footprint: "idle" },
  agentDurations: { policy: 0, catalog: 0, footprint: 0 },
  result: null,
  progress: 0,
  currentAgentIndex: -1,
  errorMessage: null,
};

// ─── Map backend risk_tier → frontend RiskLevel ────────────────────────────────
function mapRiskTier(tier: string): "SAFE" | "NEEDS_REVIEW" | "HIGH_RISK" {
  if (tier === "SAFE") return "SAFE";
  if (tier === "HIGH_RISK") return "HIGH_RISK";
  return "NEEDS_REVIEW"; // MANUAL_REVIEW → NEEDS_REVIEW
}

// ─── Convert raw ScanReport → ScanResult consumed by UI components ─────────────
function mapReport(report: ScanReport, url: string, durationMs: number): ScanResult {
  const d = report.domain_info;
  const p = report.policy_result;
  const c = report.catalog_result;

  const footprintSnippet = [
    `WHOIS — ${report.domain}`,
    `━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`,
    `Registrar:   ${d.registrar}`,
    `Created:     ${d.registration_date ?? "unknown"} (${d.domain_age_days} days ago)`,
    ``,
    `SSL CERTIFICATE`,
    `  Valid:     ${d.is_ssl_valid ? "YES" : "NO"}`,
    `  Expiry:    ${d.ssl_expiry_days} days remaining`,
  ].join("\n");

  const catalogSnippet = c.flagged_items.length
    ? [
        `PRODUCT CATALOG SCAN — ${report.domain}`,
        `━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`,
        ...c.flagged_items.map(
          (fi) =>
            `⚠ ${fi.product_title}\n  → Category: ${fi.matched_category} (similarity: ${(fi.similarity_score * 100).toFixed(0)}%)`
        ),
      ].join("\n")
    : `PRODUCT CATALOG SCAN — ${report.domain}\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\nNo prohibited items detected.`;

  const policySnippet = [
    `POLICY ANALYSIS — ${report.domain}`,
    `━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`,
    `Compliance Score: ${(p.policy_score * 100).toFixed(0)}/100`,
    `Status: ${p.is_compliant ? "COMPLIANT" : "NON-COMPLIANT"}`,
    p.missing_disclosures.length
      ? `Missing Disclosures:\n${p.missing_disclosures.map((m) => `  → ${m}`).join("\n")}`
      : `All required disclosures found.`,
  ].join("\n");

  // Parse the backend audit trail (plain string) into AuditStep array
  const auditLines = report.audit_trail
    .split("\n")
    .filter(Boolean)
    .map((line, i) => ({
      timestamp: new Date(Date.now() - (report.audit_trail.split("\n").length - i) * 800)
        .toISOString()
        .slice(11, 23),
      agent: "ORCHESTRATOR",
      action: "AUDIT_LOG",
      result: line,
      level: line.includes("⚠") || line.includes("WARNING")
        ? ("warn" as const)
        : line.includes("ERROR") || line.includes("failed")
        ? ("error" as const)
        : line.includes("complete") || line.includes("✓")
        ? ("success" as const)
        : ("info" as const),
    }));

  const keyDrivers: string[] = [];
  if (d.domain_age_days < 180)
    keyDrivers.push(`Domain is only ${d.domain_age_days} days old — elevated fraud signal`);
  if (!p.is_compliant)
    keyDrivers.push(`Policy non-compliant — score: ${(p.policy_score * 100).toFixed(0)}/100`);
  if (c.has_prohibited_items)
    keyDrivers.push(`${c.flagged_items.length} prohibited product(s) detected via pgvector search`);
  if (!d.is_ssl_valid) keyDrivers.push("SSL certificate invalid or expired");
  if (report.guardrail_triggered && report.guardrail_reason)
    keyDrivers.push(`Guardrail: ${report.guardrail_reason}`);

  return {
    domain: report.domain,
    url,
    riskScore: report.risk_score,
    riskLevel: mapRiskTier(report.risk_tier),
    scannedAt: report.created_at,
    totalDurationMs: durationMs,
    keyDrivers: keyDrivers.length ? keyDrivers : ["No significant risk factors detected."],
    agents: [
      {
        id: "policy",
        name: "Policy Sub-Agent",
        emoji: "🛡️",
        description: "Scraping & analyzing T&C, Privacy & Refund Policy",
        status: "complete",
        durationMs: Math.round(durationMs * 0.35),
        confidence: Math.round(p.policy_score * 100),
        summary: p.is_compliant
          ? "All required policy disclosures found and compliant."
          : `Non-compliant. Missing: ${p.missing_disclosures.join(", ") || "key disclosures"}`,
        snippet: policySnippet,
        findings: [
          {
            id: "p1",
            label: "Compliance Score",
            value: `${(p.policy_score * 100).toFixed(0)}/100`,
            severity: p.policy_score > 0.6 ? "info" : p.policy_score > 0.3 ? "warning" : "critical",
          },
          {
            id: "p2",
            label: "Overall Status",
            value: p.is_compliant ? "Compliant" : "Non-Compliant",
            severity: p.is_compliant ? "info" : "critical",
          },
          ...p.missing_disclosures.slice(0, 3).map((d, i) => ({
            id: `p${i + 3}`,
            label: "Missing",
            value: d,
            severity: "warning" as const,
          })),
        ],
      },
      {
        id: "catalog",
        name: "Catalog Sub-Agent",
        emoji: "📦",
        description: "Analyzing restricted products via pgvector similarity search",
        status: "complete",
        durationMs: Math.round(durationMs * 0.4),
        confidence: Math.round(c.catalog_score * 100),
        summary: c.has_prohibited_items
          ? `${c.flagged_items.length} prohibited item(s) detected via pgvector cosine similarity.`
          : "No prohibited products found in the merchant catalog.",
        snippet: catalogSnippet,
        findings: [
          {
            id: "c1",
            label: "Prohibited Items",
            value: c.has_prohibited_items ? `${c.flagged_items.length} flagged` : "None",
            severity: c.has_prohibited_items ? "critical" : "info",
          },
          {
            id: "c2",
            label: "Catalog Score",
            value: `${(c.catalog_score * 100).toFixed(0)}/100`,
            severity: c.catalog_score > 0.7 ? "info" : "warning",
          },
          {
            id: "c3",
            label: "Vector Search",
            value: c.checked_via_vectors ? "pgvector cosine similarity" : "Keyword fallback",
            severity: "info",
          },
          ...c.flagged_items.slice(0, 2).map((fi, i) => ({
            id: `c${i + 4}`,
            label: fi.matched_category,
            value: fi.product_title.slice(0, 40),
            severity: "critical" as const,
          })),
        ],
      },
      {
        id: "footprint",
        name: "Digital Footprint Sub-Agent",
        emoji: "🌐",
        description: "WHOIS, SSL, domain age & hosting analysis",
        status: "complete",
        durationMs: Math.round(durationMs * 0.25),
        confidence: Math.min(95, 60 + d.domain_age_days / 30),
        summary: `Domain ${d.domain_age_days} days old. SSL ${d.is_ssl_valid ? "valid" : "INVALID"}, expires in ${d.ssl_expiry_days} days. Registrar: ${d.registrar}.`,
        snippet: footprintSnippet,
        findings: [
          {
            id: "f1",
            label: "Domain Age",
            value: `${d.domain_age_days} days`,
            severity: d.domain_age_days < 90 ? "critical" : d.domain_age_days < 365 ? "warning" : "info",
          },
          {
            id: "f2",
            label: "SSL Status",
            value: d.is_ssl_valid ? "Valid" : "INVALID",
            severity: d.is_ssl_valid ? "info" : "critical",
          },
          {
            id: "f3",
            label: "SSL Expiry",
            value: `${d.ssl_expiry_days} days`,
            severity: d.ssl_expiry_days < 14 ? "critical" : d.ssl_expiry_days < 30 ? "warning" : "info",
          },
          {
            id: "f4",
            label: "Registrar",
            value: d.registrar,
            severity: "info",
          },
        ],
      },
    ],
    auditTrail: auditLines,
  };
}

// ─── Progressive animation milestones while API runs ──────────────────────────
//
// The real API takes 15–60s. We show animated agent steps at fixed offsets
// so the user sees progress. The API result replaces everything when ready.
const PROGRESS_MILESTONES = [
  { delay: 800,  agent: "policy",    status: "running" as AgentStatus, progress: 10, idx: 0 },
  { delay: 5000, agent: "catalog",   status: "running" as AgentStatus, progress: 35, idx: 1 },
  { delay: 9000, agent: "policy",    status: "complete" as AgentStatus, progress: 50, idx: 1 },
  { delay: 12000,agent: "footprint", status: "running" as AgentStatus, progress: 65, idx: 2 },
  { delay: 16000,agent: "catalog",   status: "complete" as AgentStatus, progress: 75, idx: 2 },
  { delay: 20000,agent: "footprint", status: "complete" as AgentStatus, progress: 88, idx: 2 },
];

export function useMerchantScan() {
  const [state, setState] = useState<ScanState>(INITIAL_STATE);
  const timersRef = useRef<NodeJS.Timeout[]>([]);
  const startTimeRef = useRef<number>(0);

  const clearTimers = () => {
    timersRef.current.forEach(clearTimeout);
    timersRef.current = [];
  };

  const startScan = useCallback(async (url: string) => {
    clearTimers();
    startTimeRef.current = Date.now();

    // Enter scanning state
    setState({
      ...INITIAL_STATE,
      phase: "scanning",
      url,
      agentStatuses: { policy: "idle", catalog: "idle", footprint: "idle" },
      progress: 5,
      currentAgentIndex: 0,
    });

    // Schedule progress animation milestones
    PROGRESS_MILESTONES.forEach(({ delay, agent, status, progress, idx }) => {
      const t = setTimeout(() => {
        setState((prev) => {
          if (prev.phase !== "scanning") return prev;
          return {
            ...prev,
            agentStatuses: { ...prev.agentStatuses, [agent]: status },
            progress,
            currentAgentIndex: idx,
          };
        });
      }, delay);
      timersRef.current.push(t);
    });

    // Make real API call
    try {
      const report = await inspectMerchant(url);
      const durationMs = Date.now() - startTimeRef.current;
      clearTimers();

      const result = mapReport(report, url, durationMs);
      setState({
        phase: "complete",
        url,
        agentStatuses: { policy: "complete", catalog: "complete", footprint: "complete" },
        agentDurations: {
          policy: Math.round(durationMs * 0.35),
          catalog: Math.round(durationMs * 0.4),
          footprint: Math.round(durationMs * 0.25),
        },
        result,
        progress: 100,
        currentAgentIndex: -1,
        errorMessage: null,
      });
    } catch (err) {
      clearTimers();
      const message = err instanceof Error ? err.message : "Inspection failed";
      setState((prev) => ({
        ...prev,
        phase: "error",
        progress: 0,
        errorMessage: message,
        agentStatuses: { policy: "error", catalog: "error", footprint: "error" },
      }));
    }
  }, []);

  const reset = useCallback(() => {
    clearTimers();
    setState(INITIAL_STATE);
  }, []);

  return { state, startScan, reset };
}

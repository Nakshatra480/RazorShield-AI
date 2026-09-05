/**
 * hooks/useMerchantScan.ts
 * ──────────────────────────────────────────────────────────────────────
 * Drives POST /api/v1/inspect and maps the backend ScanReport into the
 * ScanResult shape the UI components consume.
 *
 * While the API works (typically 15–60s) a coarse progress indicator advances
 * through the three agents. The backend does not stream per-agent progress, so
 * these are presentational milestones — the real result replaces all of it on
 * arrival.
 */
"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { inspectMerchant, type ScanReport } from "@/lib/api";
import type { AgentStatus, ScanResult } from "@/lib/types";
import { scoreToRiskLevel } from "@/lib/utils";

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

function mapRiskTier(tier: string): "SAFE" | "NEEDS_REVIEW" | "HIGH_RISK" {
  if (tier === "SAFE") return "SAFE";
  if (tier === "HIGH_RISK") return "HIGH_RISK";
  return "NEEDS_REVIEW"; // MANUAL_REVIEW → NEEDS_REVIEW
}

/** Pull the degraded-analysis block the backend attaches to findings. */
function readAnalysisQuality(report: ScanReport): {
  fullyAnalyzed: boolean;
  degradedReasons: string[];
} {
  const quality = (report.findings?.analysis_quality ?? {}) as {
    fully_analyzed?: boolean;
    degraded_reasons?: string[];
  };
  return {
    fullyAnalyzed: quality.fully_analyzed ?? report.fully_analyzed ?? true,
    degradedReasons: Array.isArray(quality.degraded_reasons)
      ? quality.degraded_reasons
      : [],
  };
}

function mapReport(report: ScanReport, url: string, durationMs: number): ScanResult {
  const d = report.domain_info;
  const p = report.policy_result;
  const c = report.catalog_result;
  const { fullyAnalyzed, degradedReasons } = readAnalysisQuality(report);

  const ageLabel =
    d.domain_age_days >= 0 ? `${d.domain_age_days} days` : "unknown (WHOIS unavailable)";

  const footprintSnippet = [
    `WHOIS — ${report.domain}`,
    `Registrar:  ${d.registrar || "unknown"}`,
    `Created:    ${d.registration_date ?? "unknown"}`,
    `Age:        ${ageLabel}`,
    ``,
    `TLS CERTIFICATE`,
    `  Valid:    ${d.is_ssl_valid ? "yes" : "no"}`,
    `  Expires:  ${d.ssl_expiry_days >= 0 ? `in ${d.ssl_expiry_days} days` : "unknown"}`,
  ].join("\n");

  const catalogSnippet = c.flagged_items.length
    ? [
        `CATALOG SCAN — ${report.domain}`,
        `Method: ${c.checked_via_vectors ? "pgvector cosine similarity" : "keyword fallback"}`,
        ``,
        ...c.flagged_items.map(
          (fi) =>
            `! ${fi.product_title}\n    category:   ${fi.matched_category}\n    matched:    ${fi.matched_pattern}\n    similarity: ${(fi.similarity_score * 100).toFixed(1)}%`
        ),
      ].join("\n")
    : [
        `CATALOG SCAN — ${report.domain}`,
        `Method: ${c.checked_via_vectors ? "pgvector cosine similarity" : "keyword fallback"}`,
        ``,
        `No prohibited items detected.`,
      ].join("\n");

  // When the site blocked inspection, policy_score is a placeholder, not a
  // measurement — the UI must not render it as a compliance failure.
  const policyUnverified = p.inconclusive === true;

  const policySnippet = (
    policyUnverified
      ? [
          `POLICY ANALYSIS — ${report.domain}`,
          `Status:       NOT VERIFIABLE`,
          `Reason:       ${p.agent_error ?? "site blocked automated inspection"}`,
          ``,
          `No policy documents could be read, so compliance is unknown.`,
          `This signal was excluded from the risk score rather than counted`,
          `as a failure. Manual review is required.`,
        ]
      : [
          `POLICY ANALYSIS — ${report.domain}`,
          `Evaluated by: ${p.evaluated_by ?? "llm"}`,
          `Compliance:   ${(p.policy_score * 100).toFixed(0)}/100`,
          `Status:       ${p.is_compliant ? "COMPLIANT" : "NON-COMPLIANT"}`,
          ``,
          p.missing_disclosures.length
            ? `Missing disclosures:\n${p.missing_disclosures.map((m) => `  - ${m}`).join("\n")}`
            : `All required disclosures found.`,
          p.agent_error ? `\nNote: ${p.agent_error}` : "",
        ]
  )
    .filter(Boolean)
    .join("\n");

  // The audit narrative is prose from the backend; render each sentence/line as
  // its own step. Timestamps are not fabricated — the scan's own time is used.
  const auditLines = report.audit_trail
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((line) => ({
      timestamp: new Date(report.created_at).toISOString().slice(11, 19),
      agent: "ORCHESTRATOR",
      action: "AUDIT",
      result: line,
      level: /guardrail|override|prohibited|failed|non-compliant/i.test(line)
        ? ("warn" as const)
        : /error|unavailable/i.test(line)
        ? ("error" as const)
        : /final verdict|completed/i.test(line)
        ? ("success" as const)
        : ("info" as const),
    }));

  const keyDrivers: string[] = [];
  if (d.domain_age_days >= 0 && d.domain_age_days < 180) {
    keyDrivers.push(`Domain is only ${d.domain_age_days} days old — elevated fraud signal`);
  } else if (d.domain_age_days < 0) {
    keyDrivers.push("Domain age could not be verified via WHOIS — treated as uncertain");
  }
  if (policyUnverified) {
    keyDrivers.push(
      `Policy compliance could not be verified — the site blocked automated inspection. Manual review required.`
    );
  } else if (!p.is_compliant) {
    keyDrivers.push(
      `Policy non-compliant (${(p.policy_score * 100).toFixed(0)}/100): ${
        p.missing_disclosures.slice(0, 2).join("; ") || "key disclosures missing"
      }`
    );
  }
  if (c.has_prohibited_items) {
    keyDrivers.push(
      `${c.flagged_items.length} prohibited product${
        c.flagged_items.length === 1 ? "" : "s"
      } detected in the catalogue`
    );
  }
  if (!d.is_ssl_valid) keyDrivers.push("TLS certificate is invalid or expired");
  if (report.guardrail_triggered && report.guardrail_reason) {
    keyDrivers.push(`Guardrail: ${report.guardrail_reason}`);
  }

  // The backend reports total pipeline time; it does not break time down per
  // agent (they run concurrently). Report the measured total on each rather
  // than inventing a 35/40/25 split as the previous build did.
  const agentDuration = report.processing_time_ms || durationMs;

  return {
    domain: report.domain,
    url,
    riskScore: report.risk_score,
    riskLevel: mapRiskTier(report.risk_tier),
    scannedAt: report.created_at,
    totalDurationMs: durationMs,
    fullyAnalyzed,
    degradedReasons,
    keyDrivers: keyDrivers.length
      ? keyDrivers
      : ["No significant risk factors detected across policy, catalogue, or domain checks."],
    agents: [
      {
        id: "policy",
        name: policyUnverified ? "Policy compliance (unverified)" : "Policy compliance",
        emoji: "🛡️",
        description: "Terms, privacy, refund, and contact disclosures",
        status: "complete",
        durationMs: agentDuration,
        confidence: policyUnverified ? 0 : Math.round(p.policy_score * 100),
        summary: policyUnverified
          ? "Not verifiable — the site blocked automated inspection, so compliance is unknown. Excluded from the risk score."
          : p.is_compliant
          ? `All required disclosures found (${(p.policy_score * 100).toFixed(0)}/100).`
          : `Non-compliant (${(p.policy_score * 100).toFixed(0)}/100). Missing: ${
              p.missing_disclosures.join(", ") || "key disclosures"
            }`,
        snippet: policySnippet,
        findings: policyUnverified
          ? [
              {
                id: "p1",
                label: "Compliance score",
                value: "Not verifiable",
                severity: "warning" as const,
              },
              {
                id: "p2",
                label: "Reason",
                value: p.agent_error ?? "Site blocked automated inspection",
                severity: "warning" as const,
              },
              {
                id: "p3",
                label: "Effect on score",
                value: "Excluded — not counted as a failure",
                severity: "info" as const,
              },
            ]
          : [
              {
                id: "p1",
                label: "Compliance score",
                value: `${(p.policy_score * 100).toFixed(0)}/100`,
                severity:
                  p.policy_score > 0.6 ? "info" : p.policy_score > 0.3 ? "warning" : "critical",
              },
              {
                id: "p2",
                label: "Status",
                value: p.is_compliant ? "Compliant" : "Non-compliant",
                severity: p.is_compliant ? "info" : "critical",
              },
              {
                id: "p3",
                label: "Evaluated by",
                value: p.evaluated_by === "llm" ? "LLM analysis" : "Rule-based fallback",
                severity: p.evaluated_by === "llm" ? "info" : "warning",
              },
              ...p.missing_disclosures.slice(0, 3).map((m, i) => ({
                id: `p${i + 4}`,
                label: "Missing",
                value: m,
                severity: "warning" as const,
              })),
            ],
      },
      {
        id: "catalog",
        name: "Catalog safety",
        emoji: "📦",
        description: "Prohibited-goods detection via vector similarity",
        status: "complete",
        durationMs: agentDuration,
        confidence: Math.round(c.catalog_score * 100),
        summary: c.has_prohibited_items
          ? `${c.flagged_items.length} prohibited item${
              c.flagged_items.length === 1 ? "" : "s"
            } detected.`
          : "No prohibited products found in the merchant catalogue.",
        snippet: catalogSnippet,
        findings: [
          {
            id: "c1",
            label: "Prohibited items",
            value: c.has_prohibited_items ? `${c.flagged_items.length} flagged` : "None",
            severity: c.has_prohibited_items ? "critical" : "info",
          },
          {
            id: "c2",
            label: "Catalog score",
            value: `${(c.catalog_score * 100).toFixed(0)}/100`,
            severity: c.catalog_score > 0.7 ? "info" : "warning",
          },
          {
            id: "c3",
            label: "Method",
            value: c.checked_via_vectors ? "pgvector cosine similarity" : "Keyword fallback",
            severity: c.checked_via_vectors ? "info" : "warning",
          },
          ...c.flagged_items.slice(0, 3).map((fi, i) => ({
            id: `c${i + 4}`,
            label: fi.matched_category,
            value: fi.product_title.slice(0, 48),
            severity: "critical" as const,
          })),
        ],
      },
      {
        id: "footprint",
        name: "Digital footprint",
        emoji: "🌐",
        description: "WHOIS registration age and TLS certificate",
        status: "complete",
        durationMs: agentDuration,
        // Confidence reflects how much the domain signal can be trusted:
        // an unresolved WHOIS lookup is low confidence, not high.
        confidence:
          d.domain_age_days < 0
            ? 25
            : Math.min(95, 55 + Math.round(d.domain_age_days / 40)),
        // Registrar names often already end in a period ("SafeNames Ltd."),
        // so trim before appending the sentence terminator.
        summary:
          `Domain age ${ageLabel}. TLS ${d.is_ssl_valid ? "valid" : "invalid"}` +
          (d.ssl_expiry_days >= 0 ? `, expires in ${d.ssl_expiry_days} days` : "") +
          `. Registrar: ${(d.registrar || "unknown").replace(/\.+$/, "")}.`,
        snippet: footprintSnippet,
        findings: [
          {
            id: "f1",
            label: "Domain age",
            value: ageLabel,
            severity:
              d.domain_age_days < 0
                ? "warning"
                : d.domain_age_days < 90
                ? "critical"
                : d.domain_age_days < 365
                ? "warning"
                : "info",
          },
          {
            id: "f2",
            label: "TLS status",
            value: d.is_ssl_valid ? "Valid" : "Invalid",
            severity: d.is_ssl_valid ? "info" : "critical",
          },
          {
            id: "f3",
            label: "TLS expiry",
            value: d.ssl_expiry_days >= 0 ? `${d.ssl_expiry_days} days` : "unknown",
            severity:
              d.ssl_expiry_days < 0
                ? "warning"
                : d.ssl_expiry_days < 14
                ? "critical"
                : d.ssl_expiry_days < 30
                ? "warning"
                : "info",
          },
          {
            id: "f4",
            label: "Registrar",
            value: d.registrar || "unknown",
            severity: "info",
          },
        ],
      },
    ],
    auditTrail: auditLines,
  };
}

// Presentational milestones while the request is in flight.
const PROGRESS_MILESTONES: Array<{
  delay: number;
  agent: string;
  status: AgentStatus;
  progress: number;
  idx: number;
}> = [
  { delay: 300, agent: "policy", status: "running", progress: 12, idx: 0 },
  { delay: 3_000, agent: "catalog", status: "running", progress: 32, idx: 1 },
  { delay: 6_000, agent: "footprint", status: "running", progress: 48, idx: 2 },
  { delay: 12_000, agent: "footprint", status: "complete", progress: 66, idx: 2 },
  { delay: 20_000, agent: "policy", status: "complete", progress: 80, idx: 2 },
  { delay: 30_000, agent: "catalog", status: "complete", progress: 90, idx: 2 },
];

export function useMerchantScan() {
  const [state, setState] = useState<ScanState>(INITIAL_STATE);
  const timersRef = useRef<ReturnType<typeof setTimeout>[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const startTimeRef = useRef<number>(0);
  const mountedRef = useRef(true);

  const clearTimers = useCallback(() => {
    timersRef.current.forEach(clearTimeout);
    timersRef.current = [];
  }, []);

  // Cancel any in-flight request and pending timers when the hook unmounts,
  // so a completed fetch cannot call setState on an unmounted component.
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      timersRef.current.forEach(clearTimeout);
      timersRef.current = [];
      abortRef.current?.abort();
    };
  }, []);

  const startScan = useCallback(
    async (url: string) => {
      clearTimers();
      abortRef.current?.abort();
      const controller = new AbortController();
      abortRef.current = controller;
      startTimeRef.current = Date.now();

      setState({
        ...INITIAL_STATE,
        phase: "scanning",
        url,
        progress: 5,
        currentAgentIndex: 0,
      });

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

      try {
        const report = await inspectMerchant(url, controller.signal);
        clearTimers();
        if (!mountedRef.current || controller.signal.aborted) return;

        const durationMs = Date.now() - startTimeRef.current;
        const result = mapReport(report, url, durationMs);
        const agentDuration = report.processing_time_ms || durationMs;

        setState({
          phase: "complete",
          url,
          agentStatuses: { policy: "complete", catalog: "complete", footprint: "complete" },
          agentDurations: {
            policy: agentDuration,
            catalog: agentDuration,
            footprint: agentDuration,
          },
          result,
          progress: 100,
          currentAgentIndex: -1,
          errorMessage: null,
        });
      } catch (err) {
        clearTimers();
        // A user-initiated cancel is not an error state.
        if (!mountedRef.current || controller.signal.aborted) return;

        const message = err instanceof Error ? err.message : "Inspection failed";
        setState((prev) => ({
          ...prev,
          phase: "error",
          progress: 0,
          errorMessage: message,
          agentStatuses: { policy: "error", catalog: "error", footprint: "error" },
        }));
      }
    },
    [clearTimers]
  );

  const reset = useCallback(() => {
    clearTimers();
    abortRef.current?.abort();
    abortRef.current = null;
    setState(INITIAL_STATE);
  }, [clearTimers]);

  return { state, startScan, reset };
}

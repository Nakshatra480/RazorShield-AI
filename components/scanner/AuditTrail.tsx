"use client";
import React, { useCallback, useState } from "react";
import { motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, Download, FileText, Info, XCircle } from "lucide-react";
import type { AuditStep, ScanResult } from "@/lib/types";

const LEVEL_META = {
  info: { Icon: Info, cls: "text-brand", label: "INFO" },
  warn: { Icon: AlertTriangle, cls: "text-risk-warn", label: "WARN" },
  error: { Icon: XCircle, cls: "text-risk-danger", label: "ERROR" },
  success: { Icon: CheckCircle2, cls: "text-risk-safe", label: "OK" },
} as const;

function AuditLine({ step }: { step: AuditStep }) {
  const meta = LEVEL_META[step.level];
  const { Icon } = meta;
  return (
    <li className="flex items-start gap-3 py-2 border-b border-line last:border-0">
      <Icon className={`w-3.5 h-3.5 mt-0.5 flex-shrink-0 ${meta.cls}`} aria-hidden />
      <span className="font-mono text-[11px] text-ink-4 tabular-nums flex-shrink-0 mt-px hidden sm:inline">
        {step.timestamp}
      </span>
      <span className="text-[13px] text-ink-2 leading-relaxed min-w-0">{step.result}</span>
    </li>
  );
}

export default function AuditTrail({ result }: { result: ScanResult }) {
  const [exported, setExported] = useState(false);

  /**
   * Export the verdict as a JSON file. This is a real download of the actual
   * scan record — the previous build showed an "Export PDF" button wired to an
   * alert() placeholder, and an "Override Decision" panel whose Approve button
   * did nothing. A control that appears to record an underwriting override but
   * silently discards it is worse than no control, so that panel is gone until
   * there is an endpoint behind it.
   */
  const handleExport = useCallback(() => {
    const payload = {
      domain: result.domain,
      url: result.url,
      risk_score: result.riskScore,
      risk_level: result.riskLevel,
      scanned_at: result.scannedAt,
      duration_ms: result.totalDurationMs,
      fully_analyzed: result.fullyAnalyzed,
      degraded_reasons: result.degradedReasons,
      key_drivers: result.keyDrivers,
      agents: result.agents.map((a) => ({
        id: a.id,
        name: a.name,
        score: a.confidence,
        summary: a.summary,
        findings: a.findings,
      })),
      audit_trail: result.auditTrail.map((s) => s.result),
    };

    const blob = new Blob([JSON.stringify(payload, null, 2)], {
      type: "application/json",
    });
    const href = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = `razorshield-${result.domain.replace(/[^a-z0-9.-]/gi, "_")}-${result.scannedAt.slice(0, 10)}.json`;
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);
    URL.revokeObjectURL(href);

    setExported(true);
    setTimeout(() => setExported(false), 2500);
  }, [result]);

  return (
    <motion.section
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.2, duration: 0.35 }}
      className="rounded-xl border border-line bg-surface shadow-card overflow-hidden"
    >
      <div className="flex items-center justify-between gap-4 px-5 py-3.5 border-b border-line">
        <div className="flex items-center gap-2 min-w-0">
          <FileText className="w-4 h-4 text-ink-3 flex-shrink-0" aria-hidden />
          <h2 className="text-[13px] font-semibold text-ink">Audit &amp; decision trail</h2>
          <span className="text-[12px] text-ink-3 font-mono flex-shrink-0">
            {result.auditTrail.length} entries
          </span>
        </div>
        <button
          id="export-audit-btn"
          onClick={handleExport}
          className="flex items-center gap-1.5 px-3 py-1.5 text-[12px] font-medium rounded-lg border border-line-strong text-ink-2 bg-surface hover:bg-surface-muted transition-colors flex-shrink-0"
        >
          <Download className="w-3.5 h-3.5" aria-hidden />
          {exported ? "Downloaded" : "Export JSON"}
        </button>
      </div>

      <div className="px-5 py-2 max-h-[22rem] overflow-auto">
        {result.auditTrail.length === 0 ? (
          <p className="py-6 text-center text-[13px] text-ink-3">
            No audit entries were recorded for this scan.
          </p>
        ) : (
          <ul>
            {result.auditTrail.map((step, i) => (
              <AuditLine key={i} step={step} />
            ))}
          </ul>
        )}
      </div>
    </motion.section>
  );
}

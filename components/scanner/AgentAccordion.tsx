"use client";
import React, { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { ChevronDown, Globe, Package, Shield } from "lucide-react";
import type { AgentFinding, ScanResult } from "@/lib/types";
import { getSeverityBadge } from "@/lib/utils";

const AGENT_ICONS = {
  policy: Shield,
  catalog: Package,
  footprint: Globe,
} as const;

function FindingRow({ finding }: { finding: AgentFinding }) {
  return (
    <div className="flex items-start justify-between gap-4 py-2 border-b border-line last:border-0">
      <div className="flex items-center gap-2 min-w-0">
        <span
          className={`text-[10px] font-semibold uppercase tracking-wide px-1.5 py-0.5 rounded border flex-shrink-0 ${getSeverityBadge(
            finding.severity
          )}`}
        >
          {finding.severity}
        </span>
        <span className="text-[12px] text-ink-3 truncate">{finding.label}</span>
      </div>
      <span className="text-[12px] font-mono text-ink text-right break-words min-w-0">
        {finding.value}
      </span>
    </div>
  );
}

export default function AgentAccordion({ result }: { result: ScanResult }) {
  const [openIds, setOpenIds] = useState<Set<string>>(new Set(["policy"]));

  const toggle = (id: string) =>
    setOpenIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  return (
    <motion.section
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.1, duration: 0.35 }}
      className="space-y-2"
    >
      <h2 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-3 px-0.5">
        Agent findings
      </h2>

      {result.agents.map((agent) => {
        const isOpen = openIds.has(agent.id);
        const AgentIcon = AGENT_ICONS[agent.id as keyof typeof AGENT_ICONS] ?? Shield;
        const criticalCount = agent.findings.filter((f) => f.severity === "critical").length;
        const warnCount = agent.findings.filter((f) => f.severity === "warning").length;
        const panelId = `agent-panel-${agent.id}`;

        return (
          <div
            key={agent.id}
            className="rounded-xl border border-line bg-surface shadow-card overflow-hidden"
          >
            <button
              id={`agent-accordion-${agent.id}`}
              onClick={() => toggle(agent.id)}
              aria-expanded={isOpen}
              aria-controls={panelId}
              className="w-full flex items-center justify-between gap-4 px-4 py-3.5 hover:bg-surface-muted transition-colors text-left"
            >
              <div className="flex items-center gap-3 min-w-0">
                <span className="w-8 h-8 rounded-lg bg-brand-soft border border-brand-border flex items-center justify-center flex-shrink-0">
                  <AgentIcon className="w-4 h-4 text-brand" aria-hidden />
                </span>
                <div className="min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-[14px] font-medium text-ink">{agent.name}</span>
                    {criticalCount > 0 && (
                      <span className="text-[11px] font-medium px-1.5 py-0.5 rounded border bg-risk-danger-soft text-risk-danger border-risk-danger-border">
                        {criticalCount} critical
                      </span>
                    )}
                    {warnCount > 0 && (
                      <span className="text-[11px] font-medium px-1.5 py-0.5 rounded border bg-risk-warn-soft text-risk-warn border-risk-warn-border">
                        {warnCount} warning
                      </span>
                    )}
                  </div>
                  <p className="text-[12px] text-ink-3 mt-0.5 truncate">{agent.summary}</p>
                </div>
              </div>

              <div className="flex items-center gap-4 flex-shrink-0">
                <div className="text-right hidden sm:block">
                  <div className="text-[10px] uppercase tracking-wide text-ink-4">Score</div>
                  <div className="text-[14px] font-semibold text-ink tabular-nums">
                    {agent.confidence}
                  </div>
                </div>
                <ChevronDown
                  className={`w-4 h-4 text-ink-3 transition-transform duration-200 ${
                    isOpen ? "rotate-180" : ""
                  }`}
                  aria-hidden
                />
              </div>
            </button>

            <AnimatePresence initial={false}>
              {isOpen && (
                <motion.div
                  key="content"
                  id={panelId}
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.22, ease: "easeInOut" }}
                  className="overflow-hidden"
                >
                  <div className="px-4 pb-4 pt-3 border-t border-line">
                    <p className="text-[13px] text-ink-2 leading-relaxed pb-3 mb-3 border-b border-line">
                      {agent.summary}
                    </p>

                    <div className="grid md:grid-cols-2 gap-5">
                      <div>
                        <h3 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-3 mb-1.5">
                          Findings
                        </h3>
                        <div>
                          {agent.findings.map((f) => (
                            <FindingRow key={f.id} finding={f} />
                          ))}
                        </div>
                      </div>

                      <div className="min-w-0">
                        <h3 className="text-[11px] font-semibold uppercase tracking-[0.08em] text-ink-3 mb-1.5">
                          Evidence
                        </h3>
                        <pre className="evidence-panel rounded-lg p-3 overflow-auto max-h-56 whitespace-pre-wrap break-words">
                          {agent.snippet}
                        </pre>
                      </div>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        );
      })}
    </motion.section>
  );
}

"use client";
import React, { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  ChevronDown,
  Shield,
  Package,
  Globe,
  AlertTriangle,
  AlertCircle,
  Info,
} from "lucide-react";
import type { ScanResult, AgentFinding } from "@/lib/mockData";

const AGENT_ICONS = {
  policy: Shield,
  catalog: Package,
  footprint: Globe,
};

const SEVERITY_COLORS = {
  info: "text-blue-400 bg-blue-900/20 border-blue-800/40",
  warning: "text-amber-400 bg-amber-900/20 border-amber-800/40",
  critical: "text-red-400 bg-red-900/20 border-red-800/40",
};

const SEVERITY_ICONS = {
  info: Info,
  warning: AlertTriangle,
  critical: AlertCircle,
};

function FindingRow({ finding }: { finding: AgentFinding }) {
  const SevIcon = SEVERITY_ICONS[finding.severity];
  const cls = SEVERITY_COLORS[finding.severity];
  return (
    <div className="flex items-center justify-between py-2 border-b border-slate-800/60 last:border-0">
      <div className="flex items-center gap-2">
        <span className={`flex items-center gap-1 px-1.5 py-0.5 rounded text-xs font-mono border ${cls}`}>
          <SevIcon className="w-2.5 h-2.5" />
          {finding.severity.toUpperCase()}
        </span>
        <span className="text-xs text-slate-400">{finding.label}</span>
      </div>
      <span className="text-xs font-mono text-slate-300">{finding.value}</span>
    </div>
  );
}

interface AgentAccordionProps {
  result: ScanResult;
}

export default function AgentAccordion({ result }: AgentAccordionProps) {
  const [openIds, setOpenIds] = useState<Set<string>>(new Set(["policy"]));

  const toggle = (id: string) => {
    setOpenIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: 0.2, duration: 0.4 }}
      className="space-y-2"
    >
      <div className="flex items-center gap-2 mb-3">
        <span className="text-xs font-semibold text-slate-400 uppercase tracking-widest">
          Sub-Agent Findings
        </span>
        <span className="text-xs text-slate-600">
          ({result.agents.length} agents)
        </span>
      </div>

      {result.agents.map((agent, idx) => {
        const isOpen = openIds.has(agent.id);
        const AgentIcon = AGENT_ICONS[agent.id as keyof typeof AGENT_ICONS];
        const criticalCount = agent.findings.filter(
          (f) => f.severity === "critical"
        ).length;
        const warnCount = agent.findings.filter(
          (f) => f.severity === "warning"
        ).length;

        return (
          <motion.div
            key={agent.id}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: idx * 0.08 }}
            className="rounded-lg border border-slate-800 bg-surface overflow-hidden"
          >
            {/* Header */}
            <button
              id={`agent-accordion-${agent.id}`}
              onClick={() => toggle(agent.id)}
              className="w-full flex items-center justify-between px-4 py-3.5 hover:bg-slate-800/40 transition-colors text-left"
            >
              <div className="flex items-center gap-3">
                <div className="w-7 h-7 rounded-md bg-slate-800 border border-slate-700 flex items-center justify-center flex-shrink-0">
                  <AgentIcon className="w-3.5 h-3.5 text-blue-400" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-white">
                      {agent.name}
                    </span>
                    {criticalCount > 0 && (
                      <span className="text-xs font-mono px-1.5 py-0.5 rounded bg-red-900/40 text-red-400 border border-red-800/50">
                        {criticalCount} critical
                      </span>
                    )}
                    {warnCount > 0 && (
                      <span className="text-xs font-mono px-1.5 py-0.5 rounded bg-amber-900/30 text-amber-400 border border-amber-800/50">
                        {warnCount} warn
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {agent.summary.slice(0, 80)}...
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-3 flex-shrink-0 ml-4">
                <div className="text-right hidden sm:block">
                  <div className="text-xs text-slate-500 font-mono">
                    Confidence
                  </div>
                  <div className="text-sm font-semibold text-white">
                    {agent.confidence}%
                  </div>
                </div>
                <motion.div
                  animate={{ rotate: isOpen ? 180 : 0 }}
                  transition={{ duration: 0.2 }}
                >
                  <ChevronDown className="w-4 h-4 text-slate-500" />
                </motion.div>
              </div>
            </button>

            {/* Body */}
            <AnimatePresence initial={false}>
              {isOpen && (
                <motion.div
                  key="content"
                  initial={{ height: 0, opacity: 0 }}
                  animate={{ height: "auto", opacity: 1 }}
                  exit={{ height: 0, opacity: 0 }}
                  transition={{ duration: 0.28, ease: "easeInOut" }}
                  className="overflow-hidden"
                >
                  <div className="px-4 pb-4 border-t border-slate-800">
                    {/* Summary */}
                    <p className="text-xs text-slate-400 pt-3 pb-3 leading-relaxed border-b border-slate-800/60">
                      {agent.summary}
                    </p>

                    <div className="grid md:grid-cols-2 gap-4 mt-3">
                      {/* Findings table */}
                      <div>
                        <span className="text-xs font-semibold text-slate-500 uppercase tracking-widest block mb-2">
                          Findings
                        </span>
                        <div>
                          {agent.findings.map((f) => (
                            <FindingRow key={f.id} finding={f} />
                          ))}
                        </div>
                      </div>

                      {/* Raw snippet */}
                      <div>
                        <span className="text-xs font-semibold text-slate-500 uppercase tracking-widest block mb-2">
                          Raw Extract
                        </span>
                        <pre className="terminal-panel rounded-md p-3 text-slate-300 overflow-auto max-h-52 text-xs leading-relaxed whitespace-pre-wrap">
                          {agent.snippet}
                        </pre>
                      </div>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        );
      })}
    </motion.div>
  );
}

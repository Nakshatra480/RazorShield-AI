"use client";
import React from "react";
import { motion } from "framer-motion";
import {
  AlertCircle,
  CheckCircle2,
  Circle,
  Globe,
  Loader2,
  Package,
  Shield,
} from "lucide-react";
import type { AgentStatus } from "@/lib/types";
import { formatMs } from "@/lib/utils";

const AGENTS = [
  {
    id: "policy",
    name: "Policy compliance",
    icon: Shield,
    description: "Reads terms, privacy, refund, and contact pages",
  },
  {
    id: "catalog",
    name: "Catalog safety",
    icon: Package,
    description: "Matches products against prohibited patterns via pgvector",
  },
  {
    id: "footprint",
    name: "Digital footprint",
    icon: Globe,
    description: "WHOIS registration age and TLS certificate validity",
  },
] as const;

const STATUS_META: Record<
  AgentStatus,
  { label: string; badge: string; Icon: React.ElementType; iconCls: string }
> = {
  idle: {
    label: "Queued",
    badge: "bg-surface-muted text-ink-3 border-line",
    Icon: Circle,
    iconCls: "text-ink-4",
  },
  running: {
    label: "Running",
    badge: "bg-brand-soft text-brand-ink border-brand-border",
    Icon: Loader2,
    iconCls: "text-brand animate-spin",
  },
  complete: {
    label: "Complete",
    badge: "bg-risk-safe-soft text-risk-safe border-risk-safe-border",
    Icon: CheckCircle2,
    iconCls: "text-risk-safe",
  },
  error: {
    label: "Failed",
    badge: "bg-risk-danger-soft text-risk-danger border-risk-danger-border",
    Icon: AlertCircle,
    iconCls: "text-risk-danger",
  },
};

interface AgentPipelineProps {
  agentStatuses: Record<string, AgentStatus>;
  agentDurations: Record<string, number>;
  progress: number;
  isScanning: boolean;
}

export default function AgentPipeline({
  agentStatuses,
  agentDurations,
  progress,
  isScanning,
}: AgentPipelineProps) {
  if (!isScanning && progress === 0) return null;

  return (
    <motion.section
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className="rounded-xl border border-line bg-surface shadow-card overflow-hidden"
      aria-live="polite"
    >
      <div className="flex items-center justify-between px-5 py-3.5 border-b border-line">
        <h2 className="text-[13px] font-semibold text-ink">Agent pipeline</h2>
        <span className="text-xs font-mono text-ink-3 tabular-nums">{progress}%</span>
      </div>

      {/* Progress rail */}
      <div className="h-1 bg-surface-sunken" role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}>
        <motion.div
          className="h-full bg-brand"
          initial={{ width: 0 }}
          animate={{ width: `${progress}%` }}
          transition={{ duration: 0.4, ease: "easeOut" }}
        />
      </div>

      <ul className="divide-y divide-line">
        {AGENTS.map((agent) => {
          const status = agentStatuses[agent.id] ?? "idle";
          const meta = STATUS_META[status];
          const duration = agentDurations[agent.id];
          const AgentIcon = agent.icon;
          const StatusIcon = meta.Icon;

          return (
            <li
              key={agent.id}
              className={`flex items-start gap-3.5 px-5 py-4 transition-colors ${
                status === "running" ? "bg-brand-soft/40" : ""
              }`}
            >
              <span className="mt-0.5 flex-shrink-0">
                <StatusIcon className={`w-4 h-4 ${meta.iconCls}`} aria-hidden />
              </span>

              <span className="mt-0.5 flex-shrink-0 w-7 h-7 rounded-md bg-surface-muted border border-line flex items-center justify-center">
                <AgentIcon className="w-3.5 h-3.5 text-ink-2" aria-hidden />
              </span>

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2.5 flex-wrap">
                  <span className="text-[13px] font-medium text-ink">{agent.name}</span>
                  <span
                    className={`text-[11px] font-medium px-1.5 py-0.5 rounded border ${meta.badge}`}
                  >
                    {meta.label}
                  </span>
                  {status === "complete" && duration > 0 && (
                    <span className="text-[11px] font-mono text-ink-3 tabular-nums">
                      {formatMs(duration)}
                    </span>
                  )}
                </div>
                <p className="text-xs text-ink-3 mt-0.5">{agent.description}</p>
              </div>
            </li>
          );
        })}
      </ul>
    </motion.section>
  );
}

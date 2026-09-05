"use client";
import React from "react";
import { motion } from "framer-motion";
import {
  CheckCircle2,
  Circle,
  Loader2,
  AlertCircle,
  Shield,
  Package,
  Globe,
} from "lucide-react";
import type { AgentStatus } from "@/lib/mockData";
import { formatMs } from "@/lib/utils";

interface Agent {
  id: string;
  name: string;
  emoji: string;
  description: string;
}

const AGENTS: Agent[] = [
  {
    id: "policy",
    name: "Policy Sub-Agent",
    emoji: "🛡️",
    description: "Scraping T&C, Privacy & Refund Policy",
  },
  {
    id: "catalog",
    name: "Catalog Sub-Agent",
    emoji: "📦",
    description: "Analyzing restricted products & image metadata",
  },
  {
    id: "footprint",
    name: "Digital Footprint",
    emoji: "🌐",
    description: "WHOIS, SSL check & domain age analysis",
  },
];

const AGENT_ICONS = {
  policy: Shield,
  catalog: Package,
  footprint: Globe,
};

function StatusIcon({ status }: { status: AgentStatus }) {
  switch (status) {
    case "complete":
      return <CheckCircle2 className="w-4 h-4 text-emerald-400" />;
    case "running":
      return (
        <Loader2 className="w-4 h-4 text-blue-400 animate-spin" />
      );
    case "error":
      return <AlertCircle className="w-4 h-4 text-red-400" />;
    default:
      return <Circle className="w-4 h-4 text-slate-600" />;
  }
}

function StatusLabel({ status }: { status: AgentStatus }) {
  const map = {
    idle: { label: "Queued", cls: "text-slate-500 bg-slate-800 border-slate-700" },
    running: { label: "Running", cls: "text-blue-400 bg-blue-900/30 border-blue-800/50" },
    complete: { label: "Complete", cls: "text-emerald-400 bg-emerald-900/30 border-emerald-800/50" },
    error: { label: "Error", cls: "text-red-400 bg-red-900/30 border-red-800/50" },
  };
  const { label, cls } = map[status];
  return (
    <span className={`text-xs font-mono px-2 py-0.5 rounded border ${cls}`}>
      {label}
    </span>
  );
}

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
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4 }}
      className="rounded-xl border border-slate-800 bg-surface overflow-hidden"
    >
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-3 border-b border-slate-800">
        <div className="flex items-center gap-2">
          {isScanning && (
            <Loader2 className="w-3.5 h-3.5 text-blue-400 animate-spin" />
          )}
          <span className="text-xs font-semibold text-slate-300 tracking-wide uppercase">
            Agent Execution Pipeline
          </span>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs font-mono text-slate-500">
            {progress}%
          </span>
        </div>
      </div>

      {/* Progress bar */}
      <div className="h-0.5 bg-slate-800">
        <motion.div
          className="h-full bg-gradient-to-r from-blue-600 to-indigo-500"
          initial={{ width: 0 }}
          animate={{ width: `${progress}%` }}
          transition={{ duration: 0.5, ease: "easeOut" }}
        />
      </div>

      {/* Agent nodes */}
      <div className="p-5">
        <div className="relative">
          {/* Connector line */}
          <div className="absolute left-5 top-8 bottom-8 w-px bg-slate-800" />

          <div className="space-y-4">
            {AGENTS.map((agent, idx) => {
              const status = agentStatuses[agent.id] ?? "idle";
              const duration = agentDurations[agent.id];
              const AgentIcon = AGENT_ICONS[agent.id as keyof typeof AGENT_ICONS];

              return (
                <motion.div
                  key={agent.id}
                  initial={{ opacity: 0, x: -8 }}
                  animate={{ opacity: 1, x: 0 }}
                  transition={{ delay: idx * 0.1 }}
                  className={`relative flex items-start gap-4 pl-2 rounded-lg p-3 transition-colors duration-200 ${
                    status === "running"
                      ? "bg-blue-950/20 border border-blue-900/30"
                      : status === "complete"
                      ? "bg-slate-900/50"
                      : "bg-transparent"
                  }`}
                >
                  {/* Status icon on timeline */}
                  <div className="relative z-10 flex-shrink-0 mt-0.5">
                    <StatusIcon status={status} />
                  </div>

                  {/* Agent info */}
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3 mb-1">
                      <div className="flex items-center gap-1.5">
                        <AgentIcon className="w-3.5 h-3.5 text-slate-500" />
                        <span className="text-sm font-medium text-white">
                          {agent.name}
                        </span>
                      </div>
                      <StatusLabel status={status} />
                      {duration > 0 && status === "complete" && (
                        <span className="text-xs font-mono text-slate-500">
                          {formatMs(duration)}
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-slate-500">{agent.description}</p>

                    {/* Running progress shimmer */}
                    {status === "running" && (
                      <div className="mt-2 h-0.5 rounded-full bg-slate-800 overflow-hidden">
                        <motion.div
                          className="h-full bg-blue-500"
                          animate={{ x: ["-100%", "100%"] }}
                          transition={{
                            duration: 1.2,
                            repeat: Infinity,
                            ease: "easeInOut",
                          }}
                          style={{ width: "40%" }}
                        />
                      </div>
                    )}
                  </div>
                </motion.div>
              );
            })}
          </div>
        </div>
      </div>
    </motion.div>
  );
}
